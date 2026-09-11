"""The RM/DSR picker must not lose anybody.

The list started as ``staff_employee_data``, which was missing RMs the desk
needed. Moving it to the ``employee_table`` HR roster fixed those — and lost the
DSRs and sales staff whose record is not on that roster. Swapping one incomplete
source for another is not a fix, so it reads both.

Also pinned: the serialised register must not issue a query per row. Every one
of current_amount, the effective expiry, the diary status, the label and the
days to expiry reads a row's amendments, so without annotation a page of ten was
issuing dozens of aggregates.
"""

from datetime import date

from django.contrib.auth.models import User
from django.db import connection
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.staff_management.models import DSRSalesCode, StaffEmployeeData

from .models import TradeProduct, TradeRegisterEntry


class RMLookupSourceTests(APITestCase):
    """employee_table is unmanaged, so the columns the lookup reads are built
    by hand — the model declares precisions PostgreSQL will not accept."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS employee_table (
                    id bigserial PRIMARY KEY,
                    staff_id numeric,
                    name varchar(100),
                    job_title text,
                    department text,
                    unit text,
                    org_unit text,
                    exit integer,
                    staff_exit_date date
                )
            """)

    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS employee_table")
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username="rmlook", password="x")
        self.client.force_authenticate(self.user)
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO employee_table "
                "(staff_id, name, job_title, department, exit, staff_exit_date) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                [4026, "ROSTER PERSON", "Relationship Manager", "RETAIL", None, None],
            )
            cur.execute(
                "INSERT INTO employee_table "
                "(staff_id, name, job_title, department, exit, staff_exit_date) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                [5555, "LEAVER PERSON", "Relationship Manager", "RETAIL", 1,
                 date(2026, 1, 31)],
            )
        # In the sales tables but NOT on the HR roster — the people the move to
        # employee_table silently dropped.
        DSRSalesCode.objects.create(
            pf_number="9001", sales_code="DSR900", salesperson="DSR ONLY PERSON",
            department="BANCA",
        )
        StaffEmployeeData.objects.create(
            staff_pf_number=9002, staff_name="SALES ONLY PERSON",
            staff_email="s@hf.test", sales_code="RM9002", department="RETAIL",
            staff_unit="U", staff_org_unit="O", job_title="RM",
            employment_date=date(2020, 1, 1), employee_category="front_office",
        )

    def _names(self, query=""):
        res = self.client.get(f"/trade_register/rm-lookup/?search={query}")
        self.assertEqual(res.status_code, 200, res.content)
        return [r["name"] for r in res.data["results"]]

    def test_the_hr_roster_is_included(self):
        self.assertIn("ROSTER PERSON", self._names())

    def test_someone_only_in_the_dsr_table_is_not_lost(self):
        """The regression: moving to employee_table dropped these."""
        self.assertIn("DSR ONLY PERSON", self._names())

    def test_someone_only_in_the_sales_staff_table_is_not_lost(self):
        self.assertIn("SALES ONLY PERSON", self._names())

    def test_a_leaver_is_not_offered(self):
        self.assertNotIn("LEAVER PERSON", self._names())

    def test_a_leaver_can_be_asked_for(self):
        res = self.client.get("/trade_register/rm-lookup/?include_exited=1")
        names = [r["name"] for r in res.data["results"]]
        self.assertIn("LEAVER PERSON", names)

    def test_search_reaches_every_source(self):
        self.assertIn("DSR ONLY PERSON", self._names("DSR ONLY"))
        self.assertIn("SALES ONLY PERSON", self._names("SALES ONLY"))
        self.assertIn("ROSTER PERSON", self._names("ROSTER"))

    def test_a_dsr_can_be_found_by_sales_code(self):
        self.assertIn("DSR ONLY PERSON", self._names("DSR900"))

    def test_each_result_says_where_it_came_from(self):
        res = self.client.get("/trade_register/rm-lookup/")
        by_name = {r["name"]: r for r in res.data["results"]}
        self.assertEqual(by_name["ROSTER PERSON"]["source"], "roster")
        self.assertEqual(by_name["DSR ONLY PERSON"]["source"], "dsr")
        self.assertEqual(by_name["SALES ONLY PERSON"]["source"], "sales_staff")

    def test_somebody_in_both_appears_once(self):
        """The roster wins; the same person must not be listed twice."""
        DSRSalesCode.objects.create(
            pf_number="4026", sales_code="DSR999", salesperson="ROSTER PERSON",
        )
        names = self._names()
        self.assertEqual(names.count("ROSTER PERSON"), 1)


class RegisterQueryCountTests(APITestCase):
    """Serialising the register must not scale queries with rows."""

    def setUp(self):
        self.user = User.objects.create_user(username="qcount", password="x")
        self.client.force_authenticate(self.user)
        product = TradeProduct.objects.get(code="14117")
        for i in range(8):
            parent = TradeRegisterEntry.objects.create(
                originating_branch="WESTLANDS BRANCH", rm_name="A", segment="S",
                our_customer=f"CUSTOMER {i}", currency="KES", amount_fcy=1_000_000,
                fx_rate=1, customer_id=1000 + i, issue_date=date(2026, 1, 1),
                expiry_date=date(2026, 12, 31), product=product,
            )
            TradeRegisterEntry.objects.create(
                originating_branch="WESTLANDS BRANCH", rm_name="A", segment="S",
                our_customer=f"CUSTOMER {i}", currency="KES", amount_fcy=0,
                fx_rate=1, customer_id=1000 + i, issue_date=date(2026, 2, 1),
                expiry_date=date(2026, 12, 31), product=product,
                action="AMENDMENT", parent_ref=parent.guarantee_ref,
                amount_delta=100_000,
            )

    def _page_queries(self, page_size):
        from django.db import connection, reset_queries
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(f"/trade_register/entries/?page_size={page_size}")
            self.assertEqual(res.status_code, 200)
        return len(ctx.captured_queries)

    def test_the_query_count_does_not_grow_with_the_number_of_rows(self):
        """The real guard. Before the annotations each row cost about five
        aggregates — the amendment total, the effective expiry (read three
        separate times, by the expiry field, the diary status and the days to
        expiry) and the count — so a bigger page cost proportionally more."""
        small = self._page_queries(2)
        large = self._page_queries(16)
        # Not necessarily EQUAL: the tariff line is looked up once per distinct
        # (product, action) on the page, so a bigger page can hold one or two
        # more pairs. That is bounded by the size of the product catalogue, not
        # by the row count — which is the property worth guarding. Eight times
        # the rows must not cost anything like eight times the queries.
        self.assertLessEqual(
            large, small + 3,
            f"{small} queries for 2 rows but {large} for 16 — the page is "
            "querying per row again",
        )

    def test_the_annotated_queryset_is_still_ordered(self):
        """The aggregates add a GROUP BY, and Django then reports the queryset
        as unordered even with Meta.ordering set. PostgreSQL may then return
        grouped rows in any order, so page 2 can repeat or skip rows from page 1
        — paging breaks, and an export that crawls the pages comes back short."""
        self.assertTrue(TradeRegisterEntry.objects.with_position().ordered)

    def test_paging_covers_every_row_exactly_once(self):
        """What the export actually relies on."""
        seen, page = [], 1
        while True:
            res = self.client.get(f"/trade_register/entries/?page_size=3&page={page}")
            self.assertEqual(res.status_code, 200)
            rows = res.data["results"]
            if not rows:
                break
            seen.extend(r["id"] for r in rows)
            if not res.data.get("next"):
                break
            page += 1

        expected = set(
            TradeRegisterEntry.objects.filter(is_archived=False).values_list("id", flat=True)
        )
        self.assertEqual(len(seen), len(set(seen)), "a row was returned on two pages")
        self.assertEqual(set(seen), expected, "paging did not reach every row")

    def test_the_live_position_is_still_right_when_annotated(self):
        res = self.client.get("/trade_register/entries/?page_size=20")
        rows = {r["our_customer"]: r for r in res.data["results"]
                if r["action"] == "ISSUANCE"}
        row = rows["CUSTOMER 0"]
        self.assertEqual(float(row["amount_fcy"]), 1_000_000)
        self.assertEqual(float(row["current_amount"]), 1_100_000)
        self.assertEqual(row["amendment_count"], 1)
