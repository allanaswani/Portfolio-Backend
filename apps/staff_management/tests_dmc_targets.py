"""Tests for the DMC target rollup.

The thing worth guarding is the double-counting rule: a branch's deposit target
sits on its BBM row *and*, split up, across its RMs' rows. Summing both would
roughly double every branch, zone and bank figure on screen, and it is the kind
of bug nobody notices because the number still looks plausible.
"""

from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.staff_management import targets as tgt
from apps.staff_management.models import (
    BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
)

YEAR = 2026
START = date(YEAR, 1, 1)


def branch_row(**kw):
    base = dict(staff_role="BBM", active=1, exit=0, start_date=START)
    base.update(kw)
    return BranchFinalEmployeeDmcData.objects.create(**base)


def staff_row(**kw):
    base = dict(staff_role="RM", active=1, staff_exit=0, start_date=START)
    base.update(kw)
    return BranchEmployeeDmcData.objects.create(**base)


class RollupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Two branches, each with a BBM row carrying the whole branch target …
        branch_row(staff_branch="ALPHA BRANCH", brn_code=100, staff_zone="Zone A",
                   team_leader="Zonal One", target_deposits_value=1_000,
                   target_pbt_revenue=500, target_new_customers=50)
        branch_row(staff_branch="BETA BRANCH", brn_code=200, staff_zone="Zone B",
                   team_leader="Zonal Two", target_deposits_value=2_000,
                   target_pbt_revenue=700, target_new_customers=70)
        # … and RM rows underneath, whose targets sum to the same branch figure.
        staff_row(sales_code="RM1", staff_branch="ALPHA BRANCH", brn_code=100,
                  staff_zone="Zone A", team_leader="TL One",
                  target_deposits_value=600, target_new_customers=30,
                  target_properties=5)
        staff_row(sales_code="RM2", staff_branch="ALPHA BRANCH", brn_code=100,
                  staff_zone="Zone A", team_leader="TL One",
                  target_deposits_value=400, target_new_customers=20,
                  target_properties=3)
        staff_row(sales_code="RM3", staff_branch="BETA BRANCH", brn_code=200,
                  staff_zone="Zone B", team_leader="TL Two",
                  target_deposits_value=2_000, target_new_customers=70,
                  target_properties=9)

    def annual(self, out, key):
        return out["targets"][key]["annual"]

    # ── the double-counting rule ──────────────────────────────────────────────
    def test_branch_uses_the_branch_row_not_the_sum_of_its_rms(self):
        out = tgt.rollup("branch", "ALPHA BRANCH", year=YEAR)
        # 1_000 from the BBM row — NOT 1_000 + 600 + 400.
        self.assertEqual(self.annual(out, "deposits"), 1_000)
        self.assertEqual(out["targets"]["deposits"]["source"],
                         "branch_final_employee_dmc_data")

    def test_bank_counts_each_branch_once(self):
        out = tgt.rollup("bank", year=YEAR)
        self.assertEqual(self.annual(out, "deposits"), 3_000)

    def test_zone_filters_the_branch_table(self):
        out = tgt.rollup("zone", "Zone B", year=YEAR)
        self.assertEqual(self.annual(out, "deposits"), 2_000)

    def test_branch_accepts_the_numeric_code(self):
        self.assertEqual(
            tgt.rollup("branch", "200", year=YEAR)["targets"]["deposits"]["annual"],
            2_000,
        )

    # ── the staff table ───────────────────────────────────────────────────────
    def test_rm_reads_its_own_row(self):
        out = tgt.rollup("rm", "RM1", year=YEAR)
        self.assertEqual(self.annual(out, "deposits"), 600)
        self.assertEqual(out["targets"]["deposits"]["source"],
                         "branch_employee_dmc_data")

    def test_team_leader_sums_its_rms(self):
        out = tgt.rollup("team_leader", "TL One", year=YEAR)
        self.assertEqual(self.annual(out, "deposits"), 1_000)

    def test_rm_has_no_branch_only_metric(self):
        """target_pbt_revenue exists only on the branch table, so an RM has none
        — and must not silently inherit the whole branch's."""
        out = tgt.rollup("rm", "RM1", year=YEAR)
        self.assertIsNone(self.annual(out, "pbt_revenue"))

    def test_branch_borrows_staff_only_metrics(self):
        """target_properties exists only on the staff table, so the branch scope
        falls through to summing its RMs — there is nothing to double-count."""
        out = tgt.rollup("branch", "ALPHA BRANCH", year=YEAR)
        self.assertEqual(self.annual(out, "properties"), 8)
        self.assertEqual(out["targets"]["properties"]["source"],
                         "branch_employee_dmc_data")

    # ── row hygiene ───────────────────────────────────────────────────────────
    def test_exited_and_inactive_rows_are_dropped(self):
        branch_row(staff_branch="GAMMA BRANCH", brn_code=300, staff_zone="Zone A",
                   target_deposits_value=9_999, active=0)
        branch_row(staff_branch="DELTA BRANCH", brn_code=400, staff_zone="Zone A",
                   target_deposits_value=8_888, exit=1)
        self.assertEqual(tgt.rollup("bank", year=YEAR)["targets"]["deposits"]["annual"],
                         3_000)

    def test_unknown_year_falls_back_rather_than_showing_zeros(self):
        """The tables are upserted in place, so a year that was never loaded has
        no rows. Returning zeros would read as 'we missed every target'."""
        out = tgt.rollup("bank", year=1999)
        self.assertEqual(out["targets"]["deposits"]["annual"], 3_000)
        self.assertFalse(out["year_filtered"])

    def test_unknown_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            tgt.rollup("planet")

    def test_scope_needing_a_value_returns_nulls_when_given_none(self):
        out = tgt.rollup("branch", "", year=YEAR)
        self.assertIsNone(self.annual(out, "deposits"))

    # ── proration ─────────────────────────────────────────────────────────────
    def test_proration_matches_the_legacy_doy_over_365_formula(self):
        """The old tool computed the YTD target as
        ``target * EXTRACT(DOY FROM CURRENT_DATE) / 365``. Keep the same shape so
        branch managers see the same number they always did."""
        on = date(2026, 7, 2)                       # day 183 of a non-leap year
        out = tgt.rollup("bank", year=YEAR, today=on)
        dep = out["targets"]["deposits"]
        self.assertAlmostEqual(dep["ytd"], 3_000 * 183 / 365, places=6)
        self.assertAlmostEqual(dep["mtd"], 3_000 / 12, places=6)
        self.assertAlmostEqual(dep["qtd"], (3_000 / 4) * (1 / 3), places=6)

    def test_a_null_target_stays_null_rather_than_becoming_zero(self):
        """A missing target must render as '—', not as a target of zero, which
        would score every branch at infinite achievement."""
        out = tgt.rollup("rm", "RM1", year=YEAR)
        self.assertIsNone(out["targets"]["forex"]["annual"])
        self.assertIsNone(out["targets"]["forex"]["ytd"])

    # ── catalogue integrity ───────────────────────────────────────────────────
    def test_every_catalogue_column_exists_on_at_least_one_table(self):
        have = (tgt._columns(BranchFinalEmployeeDmcData)
                | tgt._columns(BranchEmployeeDmcData))
        missing = [col for _, col, _, _, _, _ in tgt.CATALOGUE if col not in have]
        self.assertEqual(missing, [], f"catalogue references unknown columns: {missing}")

    def test_ceiling_metrics_are_marked_down(self):
        for key in ("npl", "loan_provisions"):
            self.assertEqual(tgt.META[key]["direction"], "down")

    def test_growth_targets_are_marked_as_movement(self):
        """Comparing these against a balance instead of a YTD movement is the
        single easiest way to make every branch look catastrophic."""
        for key in ("deposits", "asset_growth"):
            self.assertEqual(tgt.META[key]["basis"], "movement")


class DmcTargetsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        branch_row(staff_branch="ALPHA BRANCH", brn_code=100, staff_zone="Zone A",
                   target_deposits_value=1_000)
        branch_row(staff_branch="BETA BRANCH", brn_code=200, staff_zone="Zone B",
                   target_deposits_value=2_000)
        cls.ceo = User.objects.create_user("ceo_user", password="x")
        cls.ceo.groups.add(Group.objects.create(name="ceo"))
        cls.bm = User.objects.create_user("bm_user", password="x")
        cls.bm.profile.branch = "ALPHA BRANCH"
        cls.bm.profile.save()

    def get(self, user, **params):
        client = APIClient()
        client.force_authenticate(user=user)
        return client.get("/staff_management/dmc-targets/", params)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get("/staff_management/dmc-targets/").status_code, 401)

    def test_no_scope_falls_back_to_the_callers_own_branch(self):
        res = self.get(self.bm)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["scope"], "branch")
        self.assertEqual(res.data["value"], "ALPHA BRANCH")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 1_000)

    def test_a_branch_manager_cannot_read_another_branch(self):
        res = self.get(self.bm, scope="branch", value="BETA BRANCH")
        self.assertEqual(res.data["value"], "ALPHA BRANCH")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 1_000)

    def test_ceo_may_read_any_scope(self):
        res = self.get(self.ceo, scope="branch", value="BETA BRANCH")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 2_000)

    def test_bad_scope_is_a_400(self):
        self.assertEqual(self.get(self.ceo, scope="planet").status_code, 400)

    def test_scopes_endpoint_lists_what_is_loaded(self):
        client = APIClient()
        client.force_authenticate(user=self.ceo)
        res = client.get("/staff_management/dmc-targets/scopes/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["branches"], ["ALPHA BRANCH", "BETA BRANCH"])
        self.assertEqual(res.data["row_counts"]["branch_final_employee_dmc_data"], 2)


class TeamLeaderBranchScopeTests(TestCase):
    """A team leader's plan is the sum of the branches they own.

    TL Portfolio is segment-scoped while the DMC tables are branch-shaped, so
    there is no column to join on. TeamLeaderBranch is the bank's own mapping
    and is what links the two.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.staff_management.models import TeamLeaderBranch

        branch_row(staff_branch="ALPHA BRANCH", brn_code=100, staff_zone="Zone A",
                   team_leader="Zonal One", target_deposits_value=1_000,
                   target_new_customers=50)
        branch_row(staff_branch="BETA BRANCH", brn_code=200, staff_zone="Zone B",
                   team_leader="Zonal Two", target_deposits_value=2_000,
                   target_new_customers=70)
        branch_row(staff_branch="GAMMA BRANCH", brn_code=300, staff_zone="Zone C",
                   team_leader="Zonal Two", target_deposits_value=4_000)
        # Jane owns two of the three branches.
        TeamLeaderBranch.objects.create(branch="ALPHA BRANCH", team_leader="Jane Wanjiru")
        TeamLeaderBranch.objects.create(branch="BETA BRANCH",  team_leader="Jane Wanjiru")
        TeamLeaderBranch.objects.create(branch="GAMMA BRANCH", team_leader="Peter Otieno")
        # An RM row so the fallback path has something to find.
        staff_row(sales_code="RM9", staff_branch="ALPHA BRANCH", brn_code=100,
                  team_leader="Legacy TL", target_deposits_value=77)

    def test_tl_plan_is_the_sum_of_their_branches(self):
        out = tgt.rollup("team_leader", "Jane Wanjiru", year=YEAR)
        self.assertEqual(out["targets"]["deposits"]["annual"], 3_000)   # 1000 + 2000
        self.assertEqual(out["resolved_via"], "team_leader_branches")
        self.assertEqual(out["branches"], ["ALPHA BRANCH", "BETA BRANCH"])

    def test_a_tl_does_not_see_a_branch_they_do_not_own(self):
        out = tgt.rollup("team_leader", "Peter Otieno", year=YEAR)
        self.assertEqual(out["targets"]["deposits"]["annual"], 4_000)

    def test_branch_name_spelling_is_normalised_before_matching(self):
        """The TL sheet and the DMC file spell branches differently; matching raw
        strings would silently return zero targets."""
        from apps.staff_management.models import TeamLeaderBranch

        TeamLeaderBranch.objects.create(branch="SAMEER", team_leader="Short Name TL")
        branch_row(staff_branch="SAMEER BUSINESS PARK BRANCH", brn_code=270,
                   target_deposits_value=555)
        out = tgt.rollup("team_leader", "Short Name TL", year=YEAR)
        self.assertEqual(out["targets"]["deposits"]["annual"], 555)

    def test_unmapped_tl_falls_back_to_the_dmc_column(self):
        out = tgt.rollup("team_leader", "Legacy TL", year=YEAR)
        self.assertEqual(out["resolved_via"], "dmc_team_leader_column")
        self.assertEqual(out["targets"]["deposits"]["annual"], 77)

    def test_inactive_mapping_rows_are_ignored(self):
        from apps.staff_management.models import TeamLeaderBranch

        TeamLeaderBranch.objects.filter(branch="BETA BRANCH").update(active=False)
        out = tgt.rollup("team_leader", "Jane Wanjiru", year=YEAR)
        self.assertEqual(out["targets"]["deposits"]["annual"], 1_000)


class CountTargetRoundingTests(TestCase):
    """Counts must be whole units.

    Pro-rating an annual count leaves it fractional (897 x 247/365 = 589.578) and
    the tile then reads "YTD target 589.578 customers", which is nonsense to a
    branch manager. Money keeps its precision.
    """

    @classmethod
    def setUpTestData(cls):
        branch_row(staff_branch="ALPHA BRANCH", brn_code=100,
                   target_new_customers=897, target_deposits_value=598_520_834)

    def test_count_targets_are_whole_numbers(self):
        out = tgt.rollup("branch", "ALPHA BRANCH", year=YEAR, today=date(2026, 9, 4))
        nc = out["targets"]["new_customers"]
        for window in ("annual", "ytd", "qtd", "mtd"):
            self.assertEqual(nc[window], round(nc[window]),
                             f"{window} target {nc[window]} is fractional")

    def test_money_targets_keep_their_precision(self):
        out = tgt.rollup("branch", "ALPHA BRANCH", year=YEAR, today=date(2026, 9, 4))
        dep = out["targets"]["deposits"]
        self.assertAlmostEqual(dep["ytd"], 598_520_834 * 247 / 365, places=4)


class RmOwnTargetsTests(TestCase):
    """An RM must be scored against their OWN plan, not their branch's.

    Two things used to get in the way:

    * ``_own_scope`` preferred ``profile.branch`` over ``profile.sales_code``,
      so an RM whose profile carried a branch (most of them) got the whole
      branch's plan on their dashboard while every actual on that page came
      from their sales code alone.
    * a BBM's personal row lives on the *branch* table, so at ``rm`` scope the
      staff table had no row for them and every shared metric came back NULL.
    """

    @classmethod
    def setUpTestData(cls):
        # The branch plan, on the BBM's row — the BBM has a sales code too.
        branch_row(staff_branch="ALPHA BRANCH", brn_code=100, staff_zone="Zone A",
                   sales_code="BBM1", target_deposits_value=1_000,
                   target_pbt_revenue=500, target_new_customers=50)
        # …and one of that branch's RMs, with their own slice of it.
        staff_row(sales_code="RM1", staff_branch="ALPHA BRANCH", brn_code=100,
                  staff_zone="Zone A", target_deposits_value=600,
                  target_new_customers=30)

        rm_group = Group.objects.create(name="portfolio_mgt")
        cls.rm = User.objects.create_user("rm_user", password="x")
        cls.rm.groups.add(rm_group)
        cls.rm.profile.branch = "ALPHA BRANCH"      # RMs carry a branch as well
        cls.rm.profile.sales_code = "RM1"
        cls.rm.profile.save()

        cls.bbm = User.objects.create_user("bbm_user", password="x")
        cls.bbm.groups.add(rm_group)
        cls.bbm.profile.sales_code = "BBM1"
        cls.bbm.profile.save()

    def get(self, user, **params):
        client = APIClient()
        client.force_authenticate(user=user)
        return client.get("/staff_management/dmc-targets/", params)

    # ── scope resolution ──────────────────────────────────────────────────────
    def test_an_rm_defaults_to_their_own_sales_code_not_their_branch(self):
        res = self.get(self.rm, year=YEAR)
        self.assertEqual(res.data["scope"], "rm")
        self.assertEqual(res.data["value"], "RM1")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 600)

    def test_scope_rm_without_a_value_fills_in_the_callers_own(self):
        """The RM dashboard names the scope; the backend names whose."""
        res = self.get(self.rm, scope="rm", year=YEAR)
        self.assertEqual(res.data["value"], "RM1")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 600)

    def test_an_rm_may_still_ask_for_their_own_branch(self):
        """``branch`` is a scope they own, so it is not swapped out from under
        them — and it returns the branch row, not their slice of it."""
        res = self.get(self.rm, scope="branch", value="ALPHA BRANCH", year=YEAR)
        self.assertEqual(res.data["scope"], "branch")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 1_000)

    def test_a_bare_branch_scope_still_resolves_for_a_branch_manager(self):
        """No portfolio_mgt group and no sales code: unchanged from before."""
        bm = User.objects.create_user("bm2", password="x")
        bm.profile.branch = "ALPHA BRANCH"
        bm.profile.save()
        res = self.get(bm, year=YEAR)
        self.assertEqual(res.data["scope"], "branch")
        self.assertEqual(res.data["targets"]["deposits"]["annual"], 1_000)

    # ── the BBM fall-through ──────────────────────────────────────────────────
    def test_a_bbm_reads_their_own_branch_table_row_at_rm_scope(self):
        out = tgt.rollup("rm", "BBM1", year=YEAR)
        self.assertEqual(out["targets"]["deposits"]["annual"], 1_000)
        self.assertEqual(out["targets"]["deposits"]["source"],
                         "branch_final_employee_dmc_data")
        # branch-only metrics come through on the same row
        self.assertEqual(out["targets"]["pbt_revenue"]["annual"], 500)

    def test_the_fall_through_never_reaches_another_persons_row(self):
        """RM1 has no row on the branch table, so the branch-only metrics stay
        NULL — they must not inherit the branch plan sitting on the BBM's row."""
        out = tgt.rollup("rm", "RM1", year=YEAR)
        self.assertIsNone(out["targets"]["pbt_revenue"]["annual"])
        self.assertEqual(out["targets"]["deposits"]["annual"], 600)

    def test_the_branch_scope_is_unaffected(self):
        """The fall-through must not start summing both tables."""
        out = tgt.rollup("branch", "ALPHA BRANCH", year=YEAR)
        self.assertEqual(out["targets"]["deposits"]["annual"], 1_000)   # not 1_600
        self.assertEqual(out["targets"]["new_customers"]["annual"], 50)  # not 80
