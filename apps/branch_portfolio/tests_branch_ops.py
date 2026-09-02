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

from apps.branch_portfolio import drawdown_queries as dq
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
            {"department": "Retail Banking", "active": True,  "exited": False, "role": "RM",     "in_hr_roster": True},
            {"department": "Retail Banking", "active": True,  "exited": False, "role": "Teller", "in_hr_roster": True},
            {"department": "Retail Banking", "active": False, "exited": True,  "role": "RM",     "in_hr_roster": False},
            {"department": "Credit",         "active": True,  "exited": False, "role": "Analyst","in_hr_roster": True},
        ]
        rows = sq.rollup_by_department(staff)
        self.assertEqual([r["department"] for r in rows], ["Retail Banking", "Credit"])
        retail = rows[0]
        self.assertEqual(retail["headcount"], 3)
        self.assertEqual(retail["active"], 2)
        self.assertEqual(retail["exited"], 1)
        self.assertEqual(retail["distinct_roles"], 2)   # RM counted once
        self.assertEqual(retail["in_hr_roster"], 2)


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
