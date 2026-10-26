"""Guards for the branch-scoped Drawdowns and Staff & Costs endpoints.

Two things must never regress here.

**1. An unresolvable branch must match NOTHING.** ``drawdown_daily`` has no
branch column — the scope is a set of ``unit_code`` values resolved from the
branch name. If that resolution comes back empty and the query layer treated it
as "no filter", one branch manager would be served the whole bank's drawdown
book, customer names included. The scope builder therefore emits ``FALSE``, not
an absent predicate, and these tests pin that.

**2. No cost figure may be invented.** The warehouse holds no cost data at any
grain, so the departments endpoint reports ``has_cost_data: false`` and null
cost columns until Finance loads a month. Apportioning the organisation-wide
figure across branches would produce a number nobody measured.

The warehouse tables are ``managed = False`` mirrors, so a test database has no
``drawdown_daily`` and no ``employee_table``. Rather than settle for static
assertions, ``DrawdownSqlAgainstRealSchemaTests`` builds ``drawdown_daily`` from
the model Django already carries for it and runs every drawdown query against
real rows — which is what proves the SQL compiles and that the branch filter
actually filters. The staff path degrades instead: ``employee_table`` absent
means the department falls back to the DMC unit, never a query error.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from rest_framework.test import APIClient

from unittest import mock

from apps.branch_portfolio import drawdown_queries as dq
from apps.branch_portfolio import legacy_queries as lq
from apps.branch_portfolio import staff_queries as sq
from apps.portfolio.models import Profile
from apps.staff_management.models import (
    BranchDepartmentCost, BranchFinalEmployeeDmcData, Drawdown,
)
from core import branch_codes

BM = "/branch_portfolio/"
STAFF = "/staff_management/"


class ScopeBuilderTests(SimpleTestCase):
    """The WHERE fragment that decides how much of the bank a caller can see."""

    def test_empty_code_list_matches_nothing(self):
        where, params = dq._scope([])
        self.assertEqual(where, "FALSE")
        self.assertEqual(params, [])

    def test_none_means_the_all_branch_rollup(self):
        where, params = dq._scope(None)
        self.assertEqual(where, "TRUE")
        self.assertEqual(params, [])

    def test_codes_restrict_to_those_unit_codes(self):
        where, params = dq._scope([230, 220])
        self.assertIn("unit_code = ANY(%s)", where)
        self.assertEqual(params, [[230, 220]])

    def test_dates_and_search_are_parameterised(self):
        where, params = dq._scope([230], date(2026, 1, 1), date(2026, 1, 31), "kanja")
        self.assertIn("drawdown_dt >= %s", where)
        self.assertIn("drawdown_dt <= %s", where)
        self.assertIn("ILIKE %s", where)
        # branch codes + 2 dates + one bind per searched column
        self.assertEqual(len(params), 1 + 2 + len(dq._SEARCH_COLUMNS))
        self.assertNotIn("kanja", where)  # never interpolated into the SQL

    def test_every_query_builder_goes_through_the_scope(self):
        """A new drawdown query that forgets _scope would be unscoped."""
        import inspect
        source = inspect.getsource(dq)
        for fn in ("def summary", "def page", "def by_product", "def by_seller", "def monthly"):
            body = source.split(fn, 1)[1].split("\ndef ", 1)[0]
            self.assertIn("_scope(", body, f"{fn} does not build its WHERE from _scope")


class BranchCodeResolutionTests(TestCase):
    """Name → unit code, from the live DMC roster plus the static fallback."""

    def setUp(self):
        branch_codes.reset_cache()
        self.addCleanup(branch_codes.reset_cache)

    def test_normalisation_ignores_the_branch_suffix_and_case(self):
        self.assertEqual(branch_codes.normalize_branch("  head office branch "), "HEAD OFFICE")
        self.assertEqual(branch_codes.normalize_branch("HEAD OFFICE"), "HEAD OFFICE")
        self.assertEqual(branch_codes.normalize_branch("Buruburu Branch"), "BURUBURU")
        self.assertEqual(branch_codes.normalize_branch(None), "")

    def test_static_fallback_resolves_a_branch_with_no_staff_rows(self):
        self.assertEqual(branch_codes.branch_codes_for("BURUBURU BRANCH"), [230])
        # Same branch, the spelling the warehouse CASE uses.
        self.assertEqual(branch_codes.branch_codes_for("HEAD OFFICE BRANCH"), [100])

    def test_live_dmc_rows_extend_the_map(self):
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=1, staff_name="A", staff_branch="KISII BRANCH", brn_code=777)
        branch_codes.reset_cache()
        self.assertEqual(branch_codes.branch_codes_for("KISII BRANCH"), [777])
        # A code the roster carries for an already-known branch is added, not lost.
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=2, staff_name="B", staff_branch="BURUBURU BRANCH", brn_code=231)
        branch_codes.reset_cache()
        self.assertEqual(branch_codes.branch_codes_for("BURUBURU BRANCH"), [230, 231])

    def test_an_unknown_branch_resolves_to_nothing(self):
        self.assertEqual(branch_codes.branch_codes_for("NO SUCH BRANCH"), [])
        self.assertEqual(branch_codes.branch_codes_for(""), [])

    def test_the_drawdown_table_is_a_source(self):
        """`drawdown` pairs unit_code with branch, so it maps codes the staff
        roster has never seen."""
        Drawdown.objects.create(unit_code=901, branch="KISII BRANCH")
        branch_codes.reset_cache()
        self.assertEqual(branch_codes.branch_codes_for("KISII BRANCH"), [901])

    def test_a_code_belongs_to_exactly_one_branch(self):
        """A handful of mislabelled rows must not hand one branch another
        branch's code — that is precisely how a scope leaks."""
        for _ in range(20):
            Drawdown.objects.create(unit_code=902, branch="NYERI BRANCH")
        Drawdown.objects.create(unit_code=902, branch="MOMBASA BRANCH")   # mislabelled
        branch_codes.reset_cache()

        # 510 is NYERI in the static map, so it keeps that too — the point is
        # that 902 lands in exactly one branch, not in both.
        self.assertEqual(branch_codes.branch_codes_for("NYERI BRANCH"), [510, 902])
        self.assertNotIn(902, branch_codes.branch_codes_for("MOMBASA BRANCH"))
        self.assertEqual(branch_codes.branch_name_for_code(902), "NYERI")

    def test_live_rows_win_over_the_static_fallback(self):
        """The static map is a gap filler; the bank's own data decides."""
        self.assertEqual(branch_codes.branch_codes_for("BURUBURU BRANCH"), [230])
        for _ in range(5):
            Drawdown.objects.create(unit_code=230, branch="RONGAI BRANCH")
        branch_codes.reset_cache()
        self.assertEqual(branch_codes.branch_codes_for("BURUBURU BRANCH"), [])
        self.assertIn(230, branch_codes.branch_codes_for("RONGAI BRANCH"))

    def test_hf_customer_branch_code_is_not_a_source(self):
        """It is not 1:1 with branch — on production one branch's codes matched
        32 branches and 99.6% of the book (tests_branch_scoping.py)."""
        self.assertNotIn(
            "hf_customer", [table for table, _, _ in branch_codes._LIVE_SOURCES])


class DepartmentRollupTests(SimpleTestCase):
    def test_headcount_active_and_exits(self):
        staff = [
            {"department": "Retail Banking", "active": True,  "exited": False, "role": "RM",     "in_hr_roster": True,  "org_unit": "BR-230", "grade": "5"},
            {"department": "Retail Banking", "active": True,  "exited": False, "role": "Teller", "in_hr_roster": True,  "org_unit": "BR-230", "grade": "3"},
            {"department": "Retail Banking", "active": False, "exited": True,  "role": "RM",     "in_hr_roster": False, "org_unit": "BR-231", "grade": "5"},
            {"department": "Credit",         "active": True,  "exited": False, "role": "Analyst","in_hr_roster": True,  "org_unit": "HO-CR",  "grade": "6"},
        ]
        rows = sq.rollup_by_department(staff)
        self.assertEqual([r["department"] for r in rows], ["Retail Banking", "Credit"])
        retail = rows[0]
        self.assertEqual(retail["headcount"], 3)
        self.assertEqual(retail["active"], 2)
        self.assertEqual(retail["exited"], 1)
        self.assertEqual(retail["distinct_roles"], 2)   # RM counted once
        self.assertEqual(retail["in_hr_roster"], 2)
        # The org units and grades behind the headcount are listed, not just counted.
        self.assertEqual(retail["org_units"], ["BR-230", "BR-231"])
        self.assertEqual(retail["grades"], ["3", "5"])

    def test_rollup_tolerates_rows_without_org_unit_or_grade(self):
        """Staff absent from the HR roster have neither; they must still count."""
        rows = sq.rollup_by_department([
            {"department": "Retail Banking", "active": True, "exited": False,
             "role": "RM", "in_hr_roster": False},
        ])
        self.assertEqual(rows[0]["headcount"], 1)
        self.assertEqual(rows[0]["org_units"], [])
        self.assertEqual(rows[0]["grades"], [])


class BranchAuthorisationTests(TestCase):
    """A caller with no branch must be denied, not handed the whole bank."""

    def setUp(self):
        branch_codes.reset_cache()
        self.addCleanup(branch_codes.reset_cache)
        self.user = get_user_model().objects.create_user(username="bm_none", password="pw12345")
        # The post_save signal already made the Profile; leave its branch blank.
        Profile.objects.filter(user=self.user).update(branch="")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_drawdowns_denied_without_a_branch(self):
        for path in ("drawdowns/summary/", "drawdowns/list/", "staff/departments/", "staff/list/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(BM + path).status_code, 403)

    def test_url_branch_does_not_let_an_unprivileged_user_drill_elsewhere(self):
        """The /<branch> form is EXCO-only; for everyone else it is ignored,
        so a user with no branch is still denied rather than served MOMBASA."""
        self.assertEqual(
            self.client.get(BM + "drawdowns/summary/MOMBASA BRANCH").status_code, 403)

    def test_staff_list_of_an_unresolvable_branch_is_empty_not_everyone(self):
        Profile.objects.filter(user=self.user).update(branch="NO SUCH BRANCH")
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=9, staff_name="Someone Else",
            staff_branch="MOMBASA BRANCH", brn_code=300, active=1)
        response = self.client.get(BM + "staff/list/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)


class BranchStaffAndCostTests(TestCase):
    """Headcount is real; cost is only ever what Finance loaded."""

    def setUp(self):
        branch_codes.reset_cache()
        self.addCleanup(branch_codes.reset_cache)
        self.user = get_user_model().objects.create_user(username="bm_bbr", password="pw12345")
        Profile.objects.filter(user=self.user).update(branch="BURUBURU BRANCH")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        # Two people at the branch — and one duplicate row for the first, which
        # is how the DMC tables really look (one row per role/sales code).
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=1001, staff_name="Grace Kanja", staff_branch="BURUBURU BRANCH",
            brn_code=230, staff_unit="Retail Banking", staff_role="RM", active=1, exit=0)
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=1001, staff_name="Grace Kanja", staff_branch="BURUBURU BRANCH",
            brn_code=230, staff_unit="Retail Banking", staff_role="PB RM", active=1, exit=0)
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=1002, staff_name="John Mwangi", staff_branch="BURUBURU BRANCH",
            brn_code=230, staff_unit="Credit", staff_role="Analyst", active=1, exit=0)
        # Somebody at another branch must never appear.
        BranchFinalEmployeeDmcData.objects.create(
            staff_pf_number=2001, staff_name="Away Person", staff_branch="MOMBASA BRANCH",
            brn_code=300, staff_unit="Retail Banking", staff_role="RM", active=1, exit=0)

    def test_duplicate_dmc_rows_do_not_inflate_headcount(self):
        """Grace has two roster rows; she is one person, not two."""
        response = self.client.get(BM + "staff/departments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["totals"]["headcount"], 2)
        self.assertEqual(response.data["branch"], "BURUBURU BRANCH")

    def test_other_branches_are_excluded(self):
        rows = self.client.get(BM + "staff/list/").data["results"]
        self.assertEqual({r["staff_name"] for r in rows}, {"Grace Kanja", "John Mwangi"})

    def test_no_cost_loaded_means_null_cost_never_a_derived_figure(self):
        response = self.client.get(BM + "staff/departments/")
        self.assertFalse(response.data["period"]["has_cost_data"])
        self.assertIsNone(response.data["totals"]["total_cost"])
        self.assertIsNone(response.data["totals"]["cost_per_head"])
        for dept in response.data["departments"]:
            self.assertIsNone(dept["total_cost"])
            self.assertIsNone(dept["cost_per_head"])

    def test_loaded_cost_is_reported_against_the_matching_department(self):
        BranchDepartmentCost.objects.create(
            branch="BURUBURU BRANCH", department="Retail Banking",
            year=2026, month=8, amount="1000000.00")
        response = self.client.get(BM + "staff/departments/?year=2026&month=8")
        self.assertTrue(response.data["period"]["has_cost_data"])
        retail = next(d for d in response.data["departments"] if d["department"] == "Retail Banking")
        self.assertEqual(str(retail["total_cost"]), "1000000.00")
        self.assertEqual(retail["headcount"], 1)
        self.assertEqual(str(retail["cost_per_head"]), "1000000.00")
        credit = next(d for d in response.data["departments"] if d["department"] == "Credit")
        self.assertIsNone(credit["total_cost"])

    def test_cost_matches_the_branch_across_spellings(self):
        """"HEAD OFFICE" and "HEAD OFFICE BRANCH" are the same branch."""
        Profile.objects.filter(user=self.user).update(branch="HEAD OFFICE BRANCH")
        BranchDepartmentCost.objects.create(
            branch="HEAD OFFICE", department="Finance", year=2026, month=8, amount="500000.00")
        response = self.client.get(BM + "staff/departments/?year=2026&month=8")
        self.assertTrue(response.data["period"]["has_cost_data"])
        # Nobody is posted there in this fixture, so it lands in unmatched cost
        # rather than being silently dropped from the total.
        self.assertEqual(str(response.data["totals"]["total_cost"]), "500000.00")
        self.assertEqual(str(response.data["totals"]["unmatched_cost"]), "500000.00")

    def test_another_branch_cost_is_not_visible(self):
        BranchDepartmentCost.objects.create(
            branch="MOMBASA BRANCH", department="Retail Banking",
            year=2026, month=8, amount="9000000.00")
        response = self.client.get(BM + "staff/departments/?year=2026&month=8")
        self.assertFalse(response.data["period"]["has_cost_data"])
        self.assertIsNone(response.data["totals"]["total_cost"])


class BranchDepartmentCostApiTests(TestCase):
    """Finance's capture endpoint: re-sending a month corrects it."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="fin", password="pw12345", email="fin@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _payload(self, **over):
        base = {"branch": "BURUBURU BRANCH", "department": "Retail Banking",
                "year": 2026, "month": 8, "amount": "1000000.00"}
        base.update(over)
        return base

    def test_create_then_resubmit_updates_rather_than_duplicating(self):
        first = self.client.post(STAFF + "branch-department-costs/", self._payload(), format="json")
        self.assertEqual(first.status_code, 201, first.content)

        second = self.client.post(
            STAFF + "branch-department-costs/", self._payload(amount="1200000.00"), format="json")
        self.assertEqual(second.status_code, 201, second.content)

        rows = BranchDepartmentCost.objects.all()
        self.assertEqual(rows.count(), 1)
        self.assertEqual(str(rows.first().amount), "1200000.00")
        self.assertEqual(rows.first().updated_by, "fin")

    def test_branch_is_normalised_on_write(self):
        self.client.post(
            STAFF + "branch-department-costs/", self._payload(branch=" buruburu  branch "), format="json")
        self.assertEqual(BranchDepartmentCost.objects.first().branch, "BURUBURU BRANCH")

    def test_month_must_be_a_real_month(self):
        bad = self.client.post(STAFF + "branch-department-costs/", self._payload(month=13), format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("month", bad.data)


class DrawdownSqlAgainstRealSchemaTests(TransactionTestCase):
    """Every drawdown query must actually compile against ``drawdown_daily``.

    ``drawdown_daily`` is a ``managed = False`` warehouse mirror, so a test
    database has no such table and a typo in a column name would only surface in
    production. Building the table here from the model Django already carries for
    it gives the five query functions a real schema to run against, and proves
    the branch scope filters rather than merely returning everything.
    """

    def setUp(self):
        from apps.staff_management.models import DrawdownDaily
        with connection.schema_editor() as editor:
            editor.create_model(DrawdownDaily)
        self.addCleanup(self._drop, DrawdownDaily)
        self._seed()

    @staticmethod
    def _drop(model):
        with connection.schema_editor() as editor:
            editor.delete_model(model)

    @staticmethod
    def _seed():
        rows = [
            # (unit_code, customer, salesperson, product, gross, net)
            (230, "Grace Kanja", "Jane Seller", "MORTGAGE",  5_000_000, 4_800_000),
            (230, "John Mwangi", "Jane Seller", "MORTGAGE",  3_000_000, 2_900_000),
            (230, "Ann Wanjiru", "Paul Seller", "PERSONAL",  1_000_000,   950_000),
            (300, "Away Person", "Zed Seller",  "MORTGAGE", 90_000_000, 89_000_000),
        ]
        with connection.cursor() as cur:
            for i, (unit, customer, seller, product, gross, net) in enumerate(rows, start=1):
                cur.execute(
                    """
                    INSERT INTO drawdown_daily (
                        id, drawdown_dt, drawdown_dt_1, account_number, cust_id,
                        customer_name, salesperson, id_product, product_desc,
                        loan_officer_id, loan_officer_name, final_interest,
                        loan_term_days, loan_term_months, unit_code,
                        net_drawdown, gross_drawdown, customer_segment,
                        fkgd_category, description, date_created
                    ) VALUES (
                        %s, current_date, current_date, %s, %s,
                        %s, %s, 1, %s,
                        'LO1', 'Officer One', 13.5,
                        360, 12, %s,
                        %s, %s, 'MASS',
                        1, 'seeded', now()
                    )
                    """,
                    [i, 1000 + i, 2000 + i, customer, seller, product, unit, net, gross],
                )

    def test_summary_totals_only_the_branch(self):
        data = dq.summary([230])
        self.assertEqual(data["drawdown_count"], 3)
        self.assertEqual(data["customers"], 3)
        self.assertEqual(float(data["gross_value"]), 9_000_000.0)
        self.assertEqual(float(data["net_value"]), 8_650_000.0)
        self.assertEqual(data["ytd_count"], 3)

    def test_summary_of_an_unresolvable_branch_is_empty_not_the_bank(self):
        data = dq.summary([])
        self.assertEqual(data["drawdown_count"], 0)
        self.assertEqual(float(data["gross_value"]), 0.0)

    def test_all_branch_rollup_sees_everything(self):
        self.assertEqual(dq.summary(None)["drawdown_count"], 4)

    def test_page_returns_its_slice_and_the_full_count(self):
        rows, total = dq.page([230], limit=2, offset=0)
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(dq.LIST_COLUMNS), set(rows[0].keys()))
        self.assertTrue(all(r["unit_code"] == 230 for r in rows))

    def test_page_search_narrows_within_the_branch(self):
        rows, total = dq.page([230], search="kanja")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["customer_name"], "Grace Kanja")
        # A hit that exists only in ANOTHER branch must not leak through search.
        _, leaked = dq.page([230], search="Away Person")
        self.assertEqual(leaked, 0)

    def test_breakdowns_and_trend_compile_and_scope(self):
        products = dq.by_product([230])
        self.assertEqual({p["product_desc"] for p in products}, {"MORTGAGE", "PERSONAL"})
        mortgage = next(p for p in products if p["product_desc"] == "MORTGAGE")
        self.assertEqual(float(mortgage["gross_value"]), 8_000_000.0)

        sellers = dq.by_seller([230])
        self.assertEqual({s["salesperson"] for s in sellers}, {"Jane Seller", "Paul Seller"})

        trend = dq.monthly([230], months=6)
        self.assertEqual(sum(t["drawdown_count"] for t in trend), 3)

    def test_the_list_endpoint_advertises_a_next_page(self):
        """DataTable's Export crawls until ``next`` is null.

        Returning a hard-coded null would silently cap every export at the first
        page of 10 — a bug this codebase has shipped before.
        """
        branch_codes.reset_cache()
        self.addCleanup(branch_codes.reset_cache)
        user = get_user_model().objects.create_user(username="bm_dd", password="pw12345")
        Profile.objects.filter(user=user).update(branch="BURUBURU BRANCH")
        client = APIClient()
        client.force_authenticate(user)

        first = client.get(BM + "drawdowns/list/?page_size=2")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["count"], 3)
        self.assertEqual(len(first.data["results"]), 2)
        self.assertIn("page=2", first.data["next"])
        self.assertIsNone(first.data["previous"])

        last = client.get(BM + "drawdowns/list/?page_size=2&page=2")
        self.assertEqual(len(last.data["results"]), 1)
        self.assertIsNone(last.data["next"])
        self.assertIsNotNone(last.data["previous"])


# ── Customer activity ────────────────────────────────────────────────────────
#
# Two things these have to pin, and they are the same two as everywhere else in
# this file.
#
# **One branch, never the bank.** These read ``transaction_diary``, the whole
# bank's transaction history. Every other branch endpoint lets a privileged
# caller fall through to an all-branch roll-up; this one must refuse, both
# because it was asked for per-branch and because the unscoped query is a table
# scan that would take the database with it.
#
# **The windows nest and the buckets do not.** 7/30/60/90 are the same question
# asked four ways - a customer active in the last 7 days is in all four counts.
# The dormancy buckets underneath them are exclusive and sum to the inactive
# count. A screen that added the four windows up would report more customers
# than the branch has.


class ActivityArgumentTests(SimpleTestCase):
    """The two numbers that go into an interval, before any database."""

    def test_only_the_offered_windows_are_accepted(self):
        for days in lq.ACTIVITY_WINDOWS:
            self.assertEqual(lq._clean_window(days), days)

    def test_anything_else_falls_back_to_thirty(self):
        for junk in ("45", 45, "", None, "; DROP TABLE", -1, 10_000):
            self.assertEqual(lq._clean_window(junk), 30)

    def test_the_lookback_never_undercuts_the_widest_window(self):
        """"Inactive" means "outside the 90 day window". A lookback shorter
        than 90 would make the inactive list disagree with the summary."""
        self.assertEqual(lq._clean_lookback(10), 90)
        self.assertEqual(lq._clean_lookback(None), lq.DEFAULT_LOOKBACK_DAYS)

    def test_the_lookback_is_capped(self):
        """One page view must not be able to ask for five years of the bank's
        transaction history."""
        self.assertEqual(lq._clean_lookback(99_999), 1825)


class BranchCustomerActivitySqlTests(TransactionTestCase):
    """The activity SQL, against real tables with real rows.

    ``hf_customer``, ``transaction_diary`` and ``retail_allocated_portfolio``
    are all ``managed = False`` warehouse mirrors, so a test database has none
    of them and a typo in a column name would only ever surface in production.
    Two are built from the models Django already carries; ``hf_customer`` is
    built by hand because its ``cust_id`` is introspected as
    ``numeric(65535, 65535)``, which Postgres will not create.
    """

    # Profile.branch says "BURUBURU BRANCH"; the warehouse writes "Buruburu".
    # Seeded deliberately mismatched, because that mismatch is what made this
    # report a real branch as having no customers at all. normalize_branch is
    # the estate's rule for reconciling the two and both sides must use it.
    HERE = "BURUBURU BRANCH"
    HERE_IN_WAREHOUSE = "Buruburu"
    AWAY = "MOMBASA BRANCH"
    AWAY_IN_WAREHOUSE = "MOMBASA  BRANCH"

    def setUp(self):
        from apps.gceo_dashboard.models import TransactionDiary
        from apps.portfolio.models import RetailAllocatedPortfolio

        with connection.schema_editor() as editor:
            editor.create_model(TransactionDiary)
            editor.create_model(RetailAllocatedPortfolio)
        self.addCleanup(self._drop_models, (RetailAllocatedPortfolio,
                                            TransactionDiary))
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE hf_customer (
                    cust_id numeric PRIMARY KEY,
                    latin_surname text, segment text, banking_segment text,
                    branch text, branch_code text, active boolean,
                    total_depost_balance numeric, total_loans numeric,
                    total_revenue numeric
                )
            """)
        self.addCleanup(self._drop_hf_customer)
        self._seed()

    @staticmethod
    def _drop_models(models):
        with connection.schema_editor() as editor:
            for model in models:
                editor.delete_model(model)

    @staticmethod
    def _drop_hf_customer():
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS hf_customer")

    def _seed(self):
        # (cust_id, name, branch AS THE WAREHOUSE SPELLS IT, days since)
        people = [
            (1, "Ann Yesterday",   self.HERE_IN_WAREHOUSE,   1),
            (2, "Ben Lastweek",    self.HERE_IN_WAREHOUSE,   5),
            (3, "Cate Fortnight",  self.HERE_IN_WAREHOUSE,  14),
            (4, "Dan Twomonths",   self.HERE_IN_WAREHOUSE,  45),
            (5, "Eve Quarter",     self.HERE_IN_WAREHOUSE,  75),
            (6, "Fred Halfyear",   self.HERE_IN_WAREHOUSE, 150),
            (7, "Gina Lastyear",   self.HERE_IN_WAREHOUSE, 300),
            (8, "Hank Never",      self.HERE_IN_WAREHOUSE, None),
            (9, "Ivy Elsewhere",   self.AWAY_IN_WAREHOUSE,   1),
        ]
        with connection.cursor() as cur:
            for cust_id, name, branch, days in people:
                cur.execute(
                    "INSERT INTO hf_customer (cust_id, latin_surname, branch,"
                    " segment, total_depost_balance, total_loans, total_revenue)"
                    " VALUES (%s, %s, %s, 'MASS', %s, 0, 0)",
                    [cust_id, name, branch, cust_id * 1000])
                if days is None:
                    continue
                cur.execute(
                    "INSERT INTO transaction_diary (fk_customercust_id, tmstamp)"
                    " VALUES (%s, now() - (%s * INTERVAL '1 day'))",
                    [cust_id, days])
                # A second, OLDER transaction. The figure is the MOST RECENT
                # one, so this must not change any answer.
                cur.execute(
                    "INSERT INTO transaction_diary (fk_customercust_id, tmstamp)"
                    " VALUES (%s, now() - (%s * INTERVAL '1 day'))",
                    [cust_id, days + 200])

    # ── the summary ──────────────────────────────────────────────────────────

    def test_the_windows_nest(self):
        """7 ⊆ 30 ⊆ 60 ⊆ 90. Ann (1d) is in all four; Eve (75d) only in 90."""
        summary = lq.branch_customer_activity(self.HERE)
        counts = {w["days"]: w["customers"] for w in summary["windows"]}
        self.assertEqual(counts, {7: 2, 30: 3, 60: 4, 90: 5})
        self.assertTrue(summary["windows_are_cumulative"])

    def test_another_branch_is_not_counted(self):
        """Ivy transacted yesterday and belongs to Mombasa."""
        summary = lq.branch_customer_activity(self.HERE)
        self.assertEqual(summary["customers"], 8)
        self.assertEqual(
            lq.branch_customer_activity(self.AWAY)["customers"], 1)

    def test_inactive_is_the_book_less_the_ninety_day_window(self):
        summary = lq.branch_customer_activity(self.HERE)
        active_90 = next(w["customers"] for w in summary["windows"]
                         if w["days"] == 90)
        self.assertEqual(summary["inactive"],
                         summary["customers"] - active_90)
        self.assertEqual(summary["inactive"], 3)  # Fred, Gina, Hank

    def test_the_dormancy_buckets_are_exclusive_and_sum_to_inactive(self):
        """Unlike the windows above them. The payload says which is which and
        a screen that got it the wrong way round would double-count."""
        summary = lq.branch_customer_activity(self.HERE)
        self.assertEqual(sum(b["customers"] for b in summary["dormancy"]),
                         summary["inactive"])
        by_label = {b["label"]: b["customers"] for b in summary["dormancy"]}
        self.assertEqual(by_label["91-180 days"], 1)    # Fred at 150
        self.assertEqual(by_label["181-365 days"], 1)   # Gina at 300
        self.assertEqual(by_label["Over 365 days"], 0)

    def test_a_customer_who_never_transacted_is_counted_as_inactive(self):
        """Hank has no row in transaction_diary at all. He is the most
        inactive customer the branch has, not an absent one."""
        summary = lq.branch_customer_activity(self.HERE)
        labels = {b["label"]: b["customers"] for b in summary["dormancy"]}
        self.assertEqual(labels[f"No transaction in "
                                f"{lq.DEFAULT_LOOKBACK_DAYS} days"], 1)

    def test_only_the_most_recent_transaction_counts(self):
        """Every seeded customer also has a transaction 200 days older. If the
        query took the earliest, or counted rows, every answer would move."""
        summary = lq.branch_customer_activity(self.HERE)
        self.assertEqual(summary["customers"], 8)

    # ── the lists ────────────────────────────────────────────────────────────

    def test_the_active_list_respects_its_window(self):
        rows, total = lq.branch_customer_activity_page(
            self.HERE, state="active", days=30)
        self.assertEqual(total, 3)
        self.assertEqual([r["customer_name"] for r in rows],
                         ["Ann Yesterday", "Ben Lastweek", "Cate Fortnight"])
        self.assertTrue(all(r["days_since"] <= 30 for r in rows))

    def test_the_inactive_list_puts_the_longest_silent_first(self):
        """Including the customer who has never appeared - which is who the
        branch is actually trying to find."""
        rows, total = lq.branch_customer_activity_page(
            self.HERE, state="inactive", days=90)
        self.assertEqual(total, 3)
        self.assertEqual(rows[0]["customer_name"], "Hank Never")
        self.assertIsNone(rows[0]["last_txn"])
        self.assertIsNone(rows[0]["days_since"])
        self.assertEqual([r["customer_name"] for r in rows[1:]],
                         ["Gina Lastyear", "Fred Halfyear"])

    def test_the_list_is_paginated_without_running_the_scan_twice(self):
        rows, total = lq.branch_customer_activity_page(
            self.HERE, state="active", days=90, limit=2, offset=0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(total, 5)       # the full count, from one query
        self.assertNotIn("total_rows", rows[0])

    def test_search_matches_a_name_and_is_parameterised(self):
        rows, total = lq.branch_customer_activity_page(
            self.HERE, state="active", days=90, search="lastweek")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["customer_name"], "Ben Lastweek")

    def test_a_customer_allocated_twice_is_listed_once(self):
        """retail_allocated_portfolio has no unique cust_id. Joined raw it
        multiplies the customer - the fan-out this codebase shipped once on
        the RM list and must not ship again here."""
        from apps.portfolio.models import RetailAllocatedPortfolio

        for rm in ("Older RM", "Newer RM"):
            RetailAllocatedPortfolio.objects.create(
                cust_id=1, customer_name="Ann Yesterday", rm_name=rm,
                sales_code="SC1")
        rows, total = lq.branch_customer_activity_page(
            self.HERE, state="active", days=7)
        self.assertEqual(total, 2)
        self.assertEqual(sum(1 for r in rows if r["cust_id"] == 1), 1)

    def test_the_warehouse_spelling_is_reconciled_with_the_profile_one(self):
        """The bug behind a branch reporting zero customers.

        ``Profile.branch`` is "BURUBURU BRANCH" and the warehouse writes
        "Buruburu". Compared raw these match nothing, and the screen then says
        a real branch has no customers - which reads as a fact and is not one.
        """
        self.assertEqual(
            lq.branch_customer_activity(self.HERE)["customers"], 8)
        self.assertEqual(
            lq.branch_customer_activity("buruburu")["customers"], 8)
        self.assertEqual(
            lq.branch_customer_activity("  Buruburu Branch ")["customers"], 8)

    def test_extra_whitespace_in_the_warehouse_is_reconciled_too(self):
        """Mombasa is seeded as "MOMBASA  BRANCH", two spaces."""
        self.assertEqual(
            lq.branch_customer_activity(self.AWAY)["customers"], 1)

    def test_the_sql_key_agrees_with_normalize_branch(self):
        """The two sides of the comparison are computed in different
        languages. If they ever disagree the join silently returns nothing,
        so they are checked against each other rather than assumed."""
        from core.branch_codes import normalize_branch

        spellings = ["BURUBURU BRANCH", "Buruburu", "  head office branch ",
                     "HEAD OFFICE", "MOMBASA  BRANCH", "Kisumu Branch",
                     "HF WHIZZ", "hf whizz branch"]
        with connection.cursor() as cur:
            for name in spellings:
                cur.execute(
                    f"SELECT {lq._BRANCH_KEY} FROM (SELECT %s AS branch) hc",
                    [name])
                self.assertEqual(cur.fetchone()[0], normalize_branch(name),
                                 f"SQL and Python disagree on {name!r}")

    def test_a_blank_branch_matches_nothing_not_everything(self):
        """"No branch" must never be read as "every branch" - an empty key
        would otherwise compare equal to a customer whose branch is blank."""
        self.assertEqual(lq.branch_customer_activity("")["customers"], 0)
        self.assertEqual(lq.branch_customer_activity("   ")["customers"], 0)
        self.assertEqual(lq.branch_customer_activity_page(""), ([], 0))

    def test_the_empty_payload_has_the_same_shape_as_a_real_one(self):
        """A screen that tells them apart by which keys are present is a
        screen that will get it wrong."""
        real = lq.branch_customer_activity(self.HERE)
        empty = lq.branch_customer_activity("")
        self.assertEqual(set(real), set(empty))
        self.assertEqual([w["days"] for w in empty["windows"]],
                         list(lq.ACTIVITY_WINDOWS))

    def test_an_unknown_branch_matches_nothing_rather_than_everything(self):
        summary = lq.branch_customer_activity("NO SUCH BRANCH")
        self.assertEqual(summary["customers"], 0)
        rows, total = lq.branch_customer_activity_page("NO SUCH BRANCH")
        self.assertEqual((rows, total), ([], 0))


class BranchCustomerActivityScopeTests(TestCase):
    """Who may ask, and for which branch."""

    def setUp(self):
        User = get_user_model()
        self.bm = User.objects.create_user("bm_activity", password="x")
        Profile.objects.update_or_create(
            user=self.bm, defaults={"branch": "BURUBURU BRANCH"})
        self.client = APIClient()
        self.client.force_authenticate(self.bm)

        self.boss = User.objects.create_user("ceo_activity", password="x",
                                             is_superuser=True)
        Profile.objects.update_or_create(user=self.boss, defaults={"branch": ""})
        self.boss_client = APIClient()
        self.boss_client.force_authenticate(self.boss)

    def test_a_privileged_caller_naming_no_branch_is_refused(self):
        """Every other branch endpoint falls through to an all-branch roll-up.
        This one must not: unscoped, it is a scan of the bank's entire
        transaction history for an answer nobody asked for."""
        response = self.boss_client.get(
            BM + "customers/activity/summary/")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("branch", response.data)

    def test_a_branch_manager_cannot_drill_into_another_branch(self):
        """The URL branch is ignored for anyone who is not EXCO/CEO - the same
        rule as the customer routes, and for the same reason."""
        with mock.patch.object(lq, "branch_customer_activity",
                               return_value={}) as query:
            self.client.get(BM + "customers/activity/summary/MOMBASA BRANCH")
        query.assert_called_once()
        self.assertEqual(query.call_args[0][0], "BURUBURU BRANCH")

    def test_a_privileged_caller_may_name_one(self):
        with mock.patch.object(lq, "branch_customer_activity",
                               return_value={}) as query:
            response = self.boss_client.get(
                BM + "customers/activity/summary/MOMBASA BRANCH")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(query.call_args[0][0], "MOMBASA BRANCH")

    def test_a_query_failure_is_answered_not_swallowed(self):
        """A bare 500 reaches the screen as "not loaded" and leaves nobody
        anything to act on. The reason is carried instead."""
        with mock.patch.object(
                lq, "branch_customer_activity",
                side_effect=lq.ActivityQueryFailed("the database stopped it")):
            response = self.boss_client.get(
                BM + "customers/activity/summary/MOMBASA BRANCH")
        self.assertEqual(response.status_code, 503, response.content)
        self.assertIn("the database stopped it", response.data["detail"])

    def test_the_list_answers_a_failure_the_same_way(self):
        with mock.patch.object(
                lq, "branch_customer_activity_page",
                side_effect=lq.ActivityQueryFailed("timed out")):
            response = self.boss_client.get(
                BM + "customers/activity/list/MOMBASA BRANCH")
        self.assertEqual(response.status_code, 503, response.content)
        self.assertIn("timed out", response.data["detail"])

    def test_the_summary_does_not_pay_for_columns_it_discards(self):
        """The summary only COUNTS. Running it through the full book made it
        dedupe 365,000 retail_allocated_portfolio rows on every page view for
        a name and an RM it then threw away."""
        self.assertNotIn("retail_allocated_portfolio", lq._BOOK_KEYS_SQL)
        self.assertIn("retail_allocated_portfolio", lq._BOOK_SQL)

    def test_signing_in_is_required(self):
        response = APIClient().get(BM + "customers/activity/summary/")
        self.assertIn(response.status_code, (401, 403))
