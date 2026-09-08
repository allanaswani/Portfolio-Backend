"""Every Feedback Log resolves the customer and RM names.

``Feedback`` stores ``cust_id`` and ``sales_code``; all four logs — RM, TL,
branch, EXCO — render a Customer and an RM Name column. The lookup was written
into the branch view only, so the other three showed dashes on every row for
months.

These pin the resolution on the shared mixin, and pin that each view uses it,
so fixing one page cannot leave the others behind again.
"""

from django.contrib.auth.models import User
from django.db import connection
from rest_framework.test import APITestCase

from apps.portfolio.feedback_names import resolve_names
from apps.portfolio.models import Feedback


class _Row:
    """The two attributes ``resolve_names`` reads off a feedback row."""

    def __init__(self, cust_id, sales_code):
        self.cust_id = cust_id
        self.sales_code = sales_code


class ResolveNamesTests(APITestCase):
    """hf_customer and retail_allocated_portfolio are unmanaged warehouse
    mirrors, so the columns the lookup reads are created by hand here — the
    models declare precisions PostgreSQL will not accept for real DDL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hf_customer (
                    cust_id numeric PRIMARY KEY,
                    latin_surname text,
                    segment text,
                    banking_segment text,
                    branch text
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                    id serial PRIMARY KEY,
                    cust_id numeric,
                    sales_code text,
                    rm_name text
                )
            """)

    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS hf_customer")
            cur.execute("DROP TABLE IF EXISTS retail_allocated_portfolio")
        super().tearDownClass()

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO hf_customer (cust_id, latin_surname) VALUES (%s, %s)",
                [778899, "ACME HOLDINGS LTD"],
            )
            cur.execute(
                "INSERT INTO retail_allocated_portfolio (cust_id, sales_code, rm_name) "
                "VALUES (%s, %s, %s)",
                [778899, "RM4026", "JANE DOE"],
            )

    def test_a_customer_id_resolves_to_the_customers_name(self):
        cust_names, _ = resolve_names([_Row(778899, "RM4026")])
        self.assertEqual(cust_names[778899], "ACME HOLDINGS LTD")

    def test_a_sales_code_resolves_to_the_rms_name(self):
        _, rm_names = resolve_names([_Row(778899, "RM4026")])
        self.assertEqual(rm_names["RM4026"], "JANE DOE")

    def test_a_sales_code_repeated_across_customers_yields_one_name(self):
        """retail_allocated_portfolio has a row per allocation, not per RM."""
        with connection.cursor() as cur:
            for cid in (111, 222, 333):
                cur.execute(
                    "INSERT INTO retail_allocated_portfolio "
                    "(cust_id, sales_code, rm_name) VALUES (%s, %s, %s)",
                    [cid, "RM4026", "JANE DOE"],
                )
        _, rm_names = resolve_names([_Row(778899, "RM4026")])
        self.assertEqual(rm_names, {"RM4026": "JANE DOE"})

    def test_an_unknown_id_is_absent_rather_than_raising(self):
        cust_names, rm_names = resolve_names([_Row(999999, "NOPE")])
        self.assertEqual(cust_names, {})
        self.assertEqual(rm_names, {})

    def test_a_row_with_no_ids_is_handled(self):
        cust_names, rm_names = resolve_names([_Row(None, "")])
        self.assertEqual(cust_names, {})
        self.assertEqual(rm_names, {})

    def test_nothing_is_queried_for_an_empty_page(self):
        self.assertEqual(resolve_names([]), ({}, {}))


class EveryFeedbackLogResolvesNamesTests(APITestCase):
    """The four logs must all use the mixin and the naming serializer.

    This is the guard against the original fault: the lookup existed, but only
    one of the four views had it.
    """

    def test_every_feedback_list_view_uses_the_mixin(self):
        from apps.branch_portfolio.views import BranchFeedbackView
        from apps.exco_portfolio.views import ExcoFeedbackListView
        from apps.portfolio.feedback_names import FeedbackNamesMixin
        from apps.portfolio.views import FeedbackListView
        from apps.tl_portfolio.views import TlFeedbackListView

        for view in (FeedbackListView, TlFeedbackListView,
                     BranchFeedbackView, ExcoFeedbackListView):
            self.assertTrue(
                issubclass(view, FeedbackNamesMixin),
                f"{view.__name__} renders Customer and RM Name columns but does "
                "not resolve them — they will show as dashes",
            )

    def test_every_feedback_list_view_serialises_the_names(self):
        from apps.branch_portfolio.views import BranchFeedbackView
        from apps.exco_portfolio.views import ExcoFeedbackListView
        from apps.portfolio.serializers import NamedFeedbackSerializer
        from apps.portfolio.views import FeedbackListView
        from apps.tl_portfolio.views import TlFeedbackListView

        for view in (FeedbackListView, TlFeedbackListView,
                     BranchFeedbackView, ExcoFeedbackListView):
            self.assertTrue(
                issubclass(view.serializer_class, NamedFeedbackSerializer),
                f"{view.__name__} does not expose customer_name / rm_name",
            )

    def test_the_serializer_exposes_both_name_fields(self):
        from apps.portfolio.serializers import NamedFeedbackSerializer

        fields = NamedFeedbackSerializer().get_fields()
        self.assertIn("customer_name", fields)
        self.assertIn("rm_name", fields)
