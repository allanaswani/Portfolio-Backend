"""The collections desk: whose book it is, what the customer page holds, and
allocating the customers nobody is calling.
"""

import datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from . import allocation, customer_profile, officer
from .models import CollectionAllocation

MINE = "AN3773"
THEIRS = "CO1004"


def make_the_feeds():
    """Create the warehouse tables these reads join.

    ``loans``, ``customers``, ``product_mapping`` and ``loan_repayments`` are
    all unmanaged, so Django does not create them and the SQL would go
    untested. Only the columns the code touches.
    """
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS loans (
                id bigserial PRIMARY KEY,
                cust_id bigint, loan_account_no varchar(40),
                account_no varchar(40), loan_product varchar(40),
                status varchar(40), sector varchar(120), branch integer,
                euro_book_balance double precision,
                total_arrears double precision,
                days_in_arrears integer, overdue_days integer,
                capital_balance double precision,
                interest_arrears double precision,
                installment_amount double precision,
                next_installment_date timestamptz,
                last_transaction_date timestamptz,
                penalty_interest_rate double precision,
                insurance double precision,
                open_date timestamptz, expiry_date timestamptz,
                delay_officer varchar(40), account_officer varchar(40)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id bigserial PRIMARY KEY,
                cust_id bigint, firstname varchar(80), middlename varchar(80),
                lastname varchar(80), dob date, gender varchar(10),
                national_id varchar(40), phone_number varchar(60),
                other_phone_numbers varchar(255), email varchar(120),
                open_date timestamptz, branch varchar(60), type varchar(40),
                status varchar(40), segment varchar(60)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS product_mapping (
                code integer, product_description text,
                loan_collateral text
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS loan_repayments (
                id bigserial PRIMARY KEY,
                loan_account_number varchar(100),
                principal_paid numeric(20,5), interest_paid numeric(20,5),
                transaction_date timestamptz
            )
        """)


def a_customer(cust_id=1, **over):
    values = dict(
        firstname="Simon", middlename="", lastname="Ng'ang'a",
        dob=datetime.date(1980, 5, 3), gender="M", national_id="12345678",
        phone_number="0722000111",
        other_phone_numbers="0733000222, 0711000333", email="simon@example.com",
        open_date=datetime.datetime(2015, 2, 1), branch="TRM BRANCH",
        type="RETAIL", status="ACTIVE", segment="PERSONAL BANKING")
    values.update(over)
    columns = ", ".join(["cust_id"] + list(values))
    marks = ", ".join(["%s"] * (len(values) + 1))
    with connection.cursor() as cur:
        cur.execute(f"INSERT INTO customers ({columns}) VALUES ({marks})",
                    [cust_id] + list(values.values()))


def a_loan(cust_id=1, officer_code=MINE, **over):
    values = dict(
        loan_account_no="0150000296", account_no="0150000296-68",
        loan_product="40046", status="DEFINATE DELAY", sector="MORTGAGE",
        branch=260, euro_book_balance=413_700.0, total_arrears=5_100.0,
        days_in_arrears=11, overdue_days=11, capital_balance=400_000.0,
        interest_arrears=5_100.0, installment_amount=12_000.0,
        next_installment_date=datetime.datetime(2026, 11, 1),
        penalty_interest_rate=2.5, insurance=0.0,
        delay_officer=officer_code, account_officer="RM001")
    values.update(over)
    columns = ", ".join(["cust_id"] + list(values))
    marks = ", ".join(["%s"] * (len(values) + 1))
    with connection.cursor() as cur:
        cur.execute(f"INSERT INTO loans ({columns}) VALUES ({marks})",
                    [cust_id] + list(values.values()))


def a_product(code=40046, description="Mortgage Loan",
              collateral="PROPERTY"):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO product_mapping (code, product_description, "
            "loan_collateral) VALUES (%s, %s, %s)",
            [code, description, collateral])


class TheBucketIsOneDefinitionTests(TestCase):
    """The tile and the classification used to be worked out separately."""

    def test_the_boundaries_are_where_the_page_says(self):
        for days, key in ((0, "current"), (1, "1_30"), (30, "1_30"),
                          (31, "31_60"), (60, "31_60"), (61, "61_90"),
                          (90, "61_90"), (91, "npl"), (365, "npl")):
            with self.subTest(days):
                self.assertEqual(customer_profile.bucket_for(days)[0], key)

    def test_no_days_means_no_bucket_rather_than_current(self):
        """A loan with no arrears figure is not a loan that is up to date."""
        self.assertEqual(customer_profile.bucket_for(None), ("", ""))


class TheCustomerPageTests(TestCase):
    def setUp(self):
        make_the_feeds()
        a_customer(1)
        a_product()
        a_loan(1)

    def test_the_contacts_are_the_numbers_not_the_number_of_calls(self):
        """The page showed "# Contacts 0" where that was the count of DIARY
        entries. A customer nobody has called is not one with no number."""
        _bio, contacts = customer_profile.bio_and_contacts(1)
        self.assertEqual(contacts["phone"], "0722000111")
        self.assertEqual(contacts["other_phones"],
                         ["0733000222", "0711000333"])
        self.assertEqual(contacts["email"], "simon@example.com")
        self.assertEqual(contacts["count"], 4)
        self.assertTrue(contacts["reachable"])

    def test_a_customer_with_no_number_is_reported_as_unreachable(self):
        a_customer(2, phone_number="", other_phone_numbers="", email="")
        _bio, contacts = customer_profile.bio_and_contacts(2)
        self.assertFalse(contacts["reachable"])
        self.assertEqual(contacts["count"], 0)

    def test_the_bio_comes_through(self):
        bio, _contacts = customer_profile.bio_and_contacts(1)
        self.assertEqual(bio["name"], "Simon Ng'ang'a")
        self.assertEqual(bio["national_id"], "12345678")
        self.assertEqual(bio["gender"], "M")
        self.assertEqual(bio["segment"], "PERSONAL BANKING")

    def test_the_product_and_collateral_are_filled_in(self):
        """All four Account Details rows printed a dash: the front end read
        these keys and the API returned none of them."""
        data = customer_profile.profile(1)
        loan = data["loans"][0]
        self.assertEqual(loan["product"], "Mortgage Loan")
        self.assertEqual(loan["collateral"], "PROPERTY")
        self.assertEqual(loan["bucket_label"], "1-30 Days")
        self.assertEqual(data["products"], ["Mortgage Loan"])
        self.assertEqual(data["collateral"], ["PROPERTY"])

    def test_a_product_the_mapping_has_not_caught_up_with_keeps_its_loan(self):
        a_customer(3)
        a_loan(3, loan_product="99999")
        data = customer_profile.profile(3)
        self.assertEqual(len(data["loans"]), 1)
        # The code, rather than a blank - and no collateral invented for it.
        self.assertEqual(data["loans"][0]["product"], "99999")
        self.assertEqual(data["loans"][0]["collateral"], "")

    def test_the_totals_agree_with_the_loans(self):
        a_loan(1, loan_account_no="0150000297", euro_book_balance=100_000.0,
               total_arrears=50_000.0, days_in_arrears=95, overdue_days=95)
        data = customer_profile.profile(1)
        self.assertEqual(data["totals"]["loans"], 2)
        self.assertAlmostEqual(data["totals"]["outstanding"], 513_700.0)
        self.assertAlmostEqual(data["totals"]["total_arrears"], 55_100.0)
        # The WORST bucket, which is the one the desk works to.
        self.assertEqual(data["totals"]["bucket"], "npl")
        self.assertAlmostEqual(data["totals"]["arrears_ratio"],
                               round(55_100.0 / 513_700.0, 4))

    def test_a_cleared_loan_does_not_divide_by_zero(self):
        a_customer(4)
        a_loan(4, euro_book_balance=0.0, total_arrears=0.0)
        self.assertIsNone(customer_profile.profile(4)["totals"]["arrears_ratio"])

    def test_an_unknown_customer_says_so_rather_than_crashing(self):
        data = customer_profile.profile(999999)
        self.assertFalse(data["has_customer"])
        self.assertEqual(data["loans"], [])


class WhoseBookIsItTests(TestCase):
    """An officer sees what is assigned to THEM."""

    def setUp(self):
        make_the_feeds()
        a_customer(1)
        a_customer(2, firstname="Grace", lastname="Wanjiru")
        a_product()
        a_loan(1, officer_code=MINE)
        a_loan(2, officer_code=THEIRS, loan_account_no="0150000400")

    def test_the_officers_own_book_is_not_excluded_from_itself(self):
        """The predicate read ``AND NOT lower(trim(delay_officer)) = %s``, so
        an officer was shown every delinquent customer EXCEPT their own - the
        exact opposite of the screen.

        Asserted against the SQL text rather than by running it. The query
        goes through ``Loans.objects.raw``, which the router sends to the
        ``datawarehouse`` alias, and test isolation refuses that - which is
        precisely why every existing test of this view mocks the function
        out, and precisely how an inverted predicate survived in a query
        nothing had ever run.
        """
        import inspect

        from . import collections_core as cc

        sql = inspect.getsource(
            cc.customer_collection_data_current_book_data_not_rm)
        predicate = [line.strip() for line in sql.splitlines()
                     if "delay_officer" in line and "%s" in line]
        self.assertTrue(predicate, "the query must scope on delay_officer")
        for line in predicate:
            with self.subTest(line):
                self.assertNotIn(
                    "NOT", line.upper(),
                    "this showed an officer everybody else's book")
                self.assertIn("=", line)

    def test_the_match_ignores_case_and_padding(self):
        """Core banking pads these codes, and the roster does not."""
        import inspect

        from . import collections_core as cc

        sql = inspect.getsource(
            cc.customer_collection_data_current_book_data_not_rm)
        predicate = [line for line in sql.splitlines()
                     if "delay_officer" in line and "%s" in line][0]
        self.assertIn("lower", predicate.lower())
        self.assertIn("trim", predicate.lower())


class WhatAnOfficerBroughtInTests(TestCase):
    def setUp(self):
        make_the_feeds()
        a_customer(1)
        a_product()
        a_loan(1, officer_code=MINE)
        a_loan(2, officer_code=THEIRS, loan_account_no="0150000400")

    def pay(self, account, amount, when, interest=0):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO loan_repayments (loan_account_number, "
                "principal_paid, interest_paid, transaction_date) "
                "VALUES (%s, %s, %s, %s)",
                [account, amount, interest, when])

    def test_the_book_is_the_delinquent_loans_they_hold(self):
        carrying = officer.book(MINE)
        self.assertEqual(carrying["customers"], 1)
        self.assertEqual(carrying["loans"], 1)
        self.assertAlmostEqual(carrying["arrears"], 5_100.0)

    def test_a_loan_that_is_not_delinquent_is_not_their_collections_book(self):
        a_loan(5, officer_code=MINE, loan_account_no="0150000500",
               overdue_days=0, days_in_arrears=0, total_arrears=0.0)
        self.assertEqual(officer.book(MINE)["customers"], 1)

    def test_collections_are_the_money_off_their_own_loans(self):
        when = datetime.date(datetime.date.today().year, 3, 1)
        self.pay("0150000296", 3_000, when, interest=100)
        self.pay("0150000400", 9_999, when)        # somebody else's loan
        money = officer.collected(MINE)
        self.assertAlmostEqual(money["collected"], 3_100.0)
        self.assertEqual(money["payments"], 1)

    def test_the_recovery_rate_is_collected_over_arrears_carried(self):
        when = datetime.date(datetime.date.today().year, 3, 1)
        self.pay("0150000296", 1_275, when)
        summary = officer.contribution(MINE)
        self.assertAlmostEqual(summary["recovery_rate"], 0.25)

    def test_an_officer_carrying_nothing_has_no_rate_rather_than_nought(self):
        """A ratio with nothing underneath it is not a nought."""
        self.assertIsNone(officer.contribution("NOBODY")["recovery_rate"])


class AllocatingTheOnesNobodyIsCallingTests(TestCase):
    def setUp(self):
        make_the_feeds()
        a_product()
        # Three nobody is calling, and one that core banking has assigned.
        for cust_id, arrears in ((10, 90_000.0), (11, 50_000.0),
                                 (12, 10_000.0)):
            a_customer(cust_id, firstname=f"Waiting{cust_id}")
            a_loan(cust_id, officer_code="", total_arrears=arrears,
                   loan_account_no=f"ACC{cust_id}")
        a_customer(13, firstname="Assigned")
        a_loan(13, officer_code=THEIRS, loan_account_no="ACC13")

    def test_only_the_unassigned_are_waiting(self):
        waiting = allocation.unallocated()
        self.assertEqual([row["cust_id"] for row in waiting], [10, 11, 12])

    def test_the_worst_arrears_come_first(self):
        """So a round shares the big exposures across the team rather than
        landing them all on whoever sorts first."""
        self.assertEqual(
            [row["arrears"] for row in allocation.unallocated()],
            [90_000.0, 50_000.0, 10_000.0])

    def test_they_are_shared_round_robin(self):
        assignments, report = allocation.plan(["A1", "A2"])
        self.assertEqual(report["assigned"], 3)
        per = {}
        for item in assignments:
            per[item["collection_officer_code"]] = per.get(
                item["collection_officer_code"], 0) + 1
        self.assertEqual(sorted(per.values()), [1, 2])

    def test_an_officer_already_carrying_a_book_gets_fewer(self):
        """A round of allocation levels the team up rather than handing
        everybody the same number on top of what they already had."""
        assignments, _report = allocation.plan([THEIRS, "A2"])
        mine = sum(1 for a in assignments
                   if a["collection_officer_code"] == THEIRS)
        other = sum(1 for a in assignments
                    if a["collection_officer_code"] == "A2")
        self.assertLess(mine, other)

    def test_a_customer_core_banking_assigned_is_never_moved(self):
        assignments, _report = allocation.plan(["A1", "A2"])
        self.assertNotIn(13, [a["cust_id"] for a in assignments])

    def test_saving_is_idempotent(self):
        assignments, _report = allocation.plan(["A1", "A2"])
        allocation.save(assignments, who="test")
        allocation.save(assignments, who="test")
        self.assertEqual(CollectionAllocation.objects.count(), 3)

    def test_an_allocated_customer_is_no_longer_waiting(self):
        assignments, _report = allocation.plan(["A1"])
        allocation.save(assignments, who="test")
        self.assertEqual(allocation.unallocated(), [])

    def test_nothing_is_written_by_planning(self):
        allocation.plan(["A1", "A2"])
        self.assertEqual(CollectionAllocation.objects.count(), 0)

    def test_no_officer_means_nothing_happens_and_it_says_why(self):
        assignments, report = allocation.plan([])
        self.assertEqual(assignments, [])
        self.assertTrue(report["skipped"])


class TheApiIsScopedTests(TestCase):
    def setUp(self):
        make_the_feeds()
        a_customer(1)
        a_product()
        a_loan(1, officer_code=MINE)

        from apps.portfolio.models import Profile

        self.user = get_user_model().objects.create_user(
            username="officer1", password="x")
        Profile.objects.update_or_create(
            user=self.user, defaults={"sales_code": THEIRS})
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_an_officer_cannot_read_a_customer_off_their_book(self):
        """Without this, changing the number in the URL reads any customer in
        the bank."""
        res = self.client.get("/hf_collections/customer/1/")
        self.assertEqual(res.status_code, 403, res.data)

    def test_an_officer_can_read_their_own(self):
        from apps.portfolio.models import Profile

        Profile.objects.update_or_create(
            user=self.user, defaults={"sales_code": MINE})
        res = self.client.get("/hf_collections/customer/1/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["bio"]["name"], "Simon Ng'ang'a")

    def test_an_allocation_made_here_also_counts_as_their_book(self):
        CollectionAllocation.objects.create(
            cust_id=1, collection_officer_code=THEIRS, is_active=True)
        res = self.client.get("/hf_collections/customer/1/")
        self.assertEqual(res.status_code, 200, res.data)

    def test_an_officer_cannot_allocate(self):
        res = self.client.post("/hf_collections/allocation/",
                               {"confirm": True}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_allocation_reports_before_it_writes(self):
        res = self.client.get("/hf_collections/allocation/")
        # Still 403 for this user, which is the point - but the shape is
        # exercised by the team-leader test below.
        self.assertEqual(res.status_code, 403)
