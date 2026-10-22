"""Reallocating a customer from the Portfolio Allocations screen.

The Update Allocation dialog has always opened, filled and submitted. The
endpoint behind it was ``RetrieveAPIView`` - read only - so every Save
Changes came back **405 Method Not Allowed** and nothing moved. Reported from
the browser console:

    PUT .../staff_management/retail-allocated-portfolio/2037898/
    405 (Method Not Allowed)

Underneath that sits the fan-out this codebase has been bitten by twice:
``retail_allocated_portfolio`` has no unique key on ``cust_id``, so a
customer can hold several rows. Moving only the row the dialog happened to
load would split the customer between two RMs, which is worse than the 405 -
a 405 fails loudly, a split book does not.
"""

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

URL = "/staff_management/retail-allocated-portfolio/{}/"


# The router sends every unmanaged model to the ``datawarehouse`` alias, which
# in a test run is the REAL warehouse - there is no test database for it. With
# the routers off, the unmanaged model reads and writes ``default``, which is
# exactly the arrangement production runs under: both aliases point at the
# same physical database there, which is why these writes land at all.
@override_settings(DATABASE_ROUTERS=[])
class ReallocatingACustomerTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # managed = False, so Django does not build it for the test database.
        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                id bigserial PRIMARY KEY,
                cust_id integer, customer_name text, sales_code text,
                rm_name text, email text, branch integer,
                main_segment varchar(100), updated_at timestamptz)""")

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("TRUNCATE retail_allocated_portfolio RESTART IDENTITY")
            # One customer, THREE allocation rows - the shape that splits.
            cur.execute("""INSERT INTO retail_allocated_portfolio
                (cust_id, customer_name, sales_code, rm_name, email, branch,
                 main_segment) VALUES
                (166650,'SCALES AND SOFTWARE (K) LIMITED','BK1100',
                 'Benson Kara','Benson.Kara@hfcb.co.ke',200,'BUSINESS BANKING'),
                (166650,'SCALES AND SOFTWARE (K) LIMITED','BK1100',
                 'Benson Kara','Benson.Kara@hfcb.co.ke',200,'BUSINESS BANKING'),
                (166650,'SCALES AND SOFTWARE (K) LIMITED','BK1100',
                 'Benson Kara','Benson.Kara@hfcb.co.ke',200,'BUSINESS BANKING'),
                (999999,'SOMEBODY ELSE LTD','ZZ0001','Not This One',
                 'other@hfcb.co.ke',300,'SME')""")

        self.user = User.objects.create_user("stacy", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def rows(self, cust_id):
        with connection.cursor() as cur:
            cur.execute("""SELECT id, sales_code, rm_name, email, branch,
                                  main_segment
                           FROM retail_allocated_portfolio
                           WHERE cust_id = %s ORDER BY id""", [cust_id])
            return cur.fetchall()

    def first_id(self, cust_id):
        return self.rows(cust_id)[0][0]

    def reallocate(self, pk, **over):
        body = {
            "cust_id": 166650,
            "customer_name": "SCALES AND SOFTWARE (K) LIMITED",
            "sales_code": "EK3843", "rm_name": "Elijah Kilonzi",
            "email": "Elijah.Kilonzi@hfcb.co.ke", "branch": 200,
            "main_segment": "BUSINESS BANKING",
        }
        body.update(over)
        return self.client.put(URL.format(pk), body, format="json")

    # -- the reported fault -----------------------------------------------
    def test_saving_the_dialog_is_not_method_not_allowed(self):
        response = self.reallocate(self.first_id(166650))
        self.assertNotEqual(
            response.status_code, 405,
            "the Update Allocation dialog's PUT is refused, which is the "
            "405 reported from the browser console")
        self.assertEqual(response.status_code, 200, response.data)

    def test_the_row_that_was_opened_moves(self):
        self.reallocate(self.first_id(166650))
        _, sales_code, rm_name, _, _, _ = self.rows(166650)[0]
        self.assertEqual(sales_code, "EK3843")
        self.assertEqual(rm_name, "Elijah Kilonzi")

    # -- the fault underneath it ------------------------------------------
    def test_every_row_the_customer_has_moves_with_it(self):
        """Not just the one the dialog loaded. Three rows, one customer: if
        only one moves the customer is in two RMs' books at once."""
        self.reallocate(self.first_id(166650))

        owners = {(row[1], row[2]) for row in self.rows(166650)}
        self.assertEqual(
            owners, {("EK3843", "Elijah Kilonzi")},
            "this customer is split across RMs - some rows moved and some "
            "did not")

    def test_the_response_says_how_many_other_rows_moved(self):
        response = self.reallocate(self.first_id(166650))
        self.assertEqual(response.data["rows_also_updated"], 2)

    def test_nobody_elses_allocation_is_touched(self):
        self.reallocate(self.first_id(166650))
        _, sales_code, rm_name, _, _, _ = self.rows(999999)[0]
        self.assertEqual(sales_code, "ZZ0001")
        self.assertEqual(rm_name, "Not This One")

    # -- what the row records ---------------------------------------------
    def test_the_reallocation_is_stamped(self):
        self.reallocate(self.first_id(166650))
        with connection.cursor() as cur:
            cur.execute("""SELECT count(*) FROM retail_allocated_portfolio
                           WHERE cust_id = 166650 AND updated_at IS NULL""")
            self.assertEqual(cur.fetchone()[0], 0,
                             "a reallocation left no record of when it "
                             "happened")

    def test_a_client_cannot_set_the_stamp_itself(self):
        response = self.reallocate(self.first_id(166650),
                                   updated_at="2001-01-01T00:00:00Z")
        self.assertEqual(response.status_code, 200)
        with connection.cursor() as cur:
            cur.execute("""SELECT count(*) FROM retail_allocated_portfolio
                           WHERE cust_id = 166650
                             AND updated_at < '2010-01-01'""")
            self.assertEqual(cur.fetchone()[0], 0)

    # -- what is deliberately still refused --------------------------------
    def test_deleting_an_allocation_is_still_refused(self):
        """An unallocated customer is not the result; a customer who has
        fallen out of the allocation base altogether is."""
        response = self.client.delete(URL.format(self.first_id(166650)))
        self.assertEqual(response.status_code, 405)

    def test_it_still_needs_a_login(self):
        self.client.force_authenticate(None)
        response = self.reallocate(self.first_id(166650))
        self.assertIn(response.status_code, (401, 403))
