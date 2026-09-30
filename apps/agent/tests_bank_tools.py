"""The scope boundary, tested as a boundary.

These tools answer questions about any customer in the bank, so the only thing
worth testing hard is who is allowed to see whom. A prompt asking the model to
be careful is not a control; a queryset filter is, and that is what these
assert.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from apps.agent import bank_tools as bt
from apps.business_performance.models import BankingSectorPosition
from apps.portfolio_management_enrichment.models import CustomerAllocationBase as CAB


def user(username, *, sales_code="", segment="", branch="", group=None, su=False):
    u = get_user_model().objects.create_user(username=username, password="x",
                                             is_superuser=su)
    # A post_save receiver on User already made the Profile and cached it on
    # this instance. update_or_create() would write the row but leave that
    # cached object stale, so the tools would read an empty sales code.
    prof = u.profile
    prof.sales_code, prof.segment, prof.branch = sales_code, segment, branch
    prof.save()
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


def customer(cust_id, name, *, rm_code, segment, branch, aum):
    """CustomerAllocationBase has no blank-able columns; fill them all."""
    return CAB.objects.create(
        group_id=cust_id, cust_id=cust_id, customer_name=name,
        segment=segment, main_segment_prev=segment, main_segment=segment,
        customer_branch_name=branch, cust_branch=branch,
        proposed_segment=segment,
        aum_group=Decimal(aum), aum_cust_id=Decimal(aum),
        rm_code_prev=rm_code, rm_name_prev="Prev RM", rm_role_prev="RM",
        rm_branch_prev=branch, rm_segment_prev=segment,
        rank_branch=1, rank_rm_code=1,
        rm_code=rm_code, rm_name=f"RM {rm_code}", rm_role="RM",
        rm_branch_name=branch, rm_branch_code="270",
        rm_active_status="ACTIVE", source="test",
        # These three carry no default on the model and are NOT NULL.
        active_one_month=Decimal("0"), active_two_month=Decimal("0"),
        active_three_month=Decimal("0"),
    )


class ScopeTests(TestCase):
    def setUp(self):
        customer("1001", "Technomasters Limited", rm_code="CM001",
                 segment="COMMERCIAL", branch="SAMEER", aum="10000000")
        customer("1002", "Estina Green Limited", rm_code="CM002",
                 segment="COMMERCIAL", branch="SAMEER", aum="7500000")
        customer("1003", "Highlands Dairy", rm_code="PB900",
                 segment="PERSONAL BANKING", branch="NAKURU", aum="2500000")

    # ── who sees whom ────────────────────────────────────────────────
    def test_an_officer_sees_only_their_own_customers(self):
        res = bt.get_customer(user=user("o1", sales_code="CM001"), query="Limited")
        self.assertEqual(res["found"], 1)
        self.assertEqual(res["customers"][0]["customer_name"], "Technomasters Limited")

    def test_an_officer_asking_for_someone_elses_customer_is_told_nothing(self):
        res = bt.get_customer(user=user("o2", sales_code="CM001"), query="1002")
        self.assertEqual(res["found"], 0)
        self.assertNotIn("customers", res)

    def test_a_team_leader_sees_the_whole_segment(self):
        tl = user("tl1", sales_code="CM900", segment="COMMERCIAL",
                  group="tl_portfolio")
        self.assertEqual(bt.get_customer(user=tl, query="Limited")["found"], 2)
        # but not the other segment
        self.assertEqual(bt.get_customer(user=tl, query="Highlands")["found"], 0)

    def test_a_branch_manager_sees_their_branch(self):
        bm = user("bm1", sales_code="BR1", branch="SAMEER",
                  group="branch_portfolio")
        self.assertEqual(bt.get_branch_performance(user=bm)["branches"], 1)

    def test_management_sees_any_customer(self):
        for group in ("ceo", "exco", "portfolio_mgt", "business_performance"):
            with self.subTest(group=group):
                boss = user(f"boss_{group}", group=group)
                self.assertEqual(bt.get_customer(user=boss, query="1003")["found"], 1)

    def test_a_superuser_sees_any_customer(self):
        self.assertEqual(
            bt.get_customer(user=user("root", su=True), query="1003")["found"], 1)

    def test_an_account_with_nothing_to_scope_by_is_refused_not_widened(self):
        """The dangerous failure is falling back to everything."""
        res = bt.get_customer(user=user("nobody"), query="Limited")
        self.assertEqual(res["error"], "out_of_scope")
        self.assertNotIn("customers", res)

    def test_an_anonymous_caller_gets_nothing(self):
        res = bt.get_customer(user=None, query="Limited")
        self.assertEqual(res["error"], "out_of_scope")

    def test_a_segment_is_matched_through_synonyms_not_by_equality(self):
        """BUSINESS BANKING and SME are the same segment; '=' would miss."""
        customer("1004", "Skillman Construction", rm_code="BB100",
                 segment="BUSINESS BANKING", branch="THIKA", aum="4000000")
        tl = user("tl_sme", sales_code="BB900", segment="SME",
                  group="tl_portfolio")
        self.assertEqual(bt.get_customer(user=tl, query="Skillman")["found"], 1)

    # ── branch performance ───────────────────────────────────────────
    def test_branch_performance_aggregates_and_ranks(self):
        res = bt.get_branch_performance(user=user("root2", su=True))
        self.assertEqual(res["branches"], 2)
        top = res["results"][0]
        self.assertEqual(top["branch"], "SAMEER")
        self.assertEqual(top["customers"], 2)
        self.assertEqual(top["aum"], 17500000.0)

    def test_branch_performance_is_scoped_like_the_customer_lookup(self):
        res = bt.get_branch_performance(user=user("o3", sales_code="CM001"))
        self.assertEqual(res["scope"], "rm")
        self.assertEqual(res["results"][0]["customers"], 1)


class MarketPositionTests(TestCase):
    def test_it_says_so_plainly_when_nothing_is_loaded(self):
        """An empty chart would read as 'we have no competitors'."""
        res = bt.get_market_position()
        self.assertEqual(res["error"], "no_sector_data")
        self.assertIn("CBK", res["detail"])

    def test_it_ranks_and_finds_our_own_row(self):
        BankingSectorPosition.objects.create(
            period="2026-Q2", bank_name="Big Bank", total_deposits=Decimal("900"))
        BankingSectorPosition.objects.create(
            period="2026-Q2", bank_name="HF Group", is_us=True,
            total_deposits=Decimal("300"))
        BankingSectorPosition.objects.create(
            period="2026-Q2", bank_name="Mid Bank", total_deposits=Decimal("500"))

        res = bt.get_market_position(metric="deposits")
        self.assertEqual(res["period"], "2026-Q2")
        self.assertEqual([r["bank_name"] for r in res["results"]],
                         ["Big Bank", "Mid Bank", "HF Group"])
        self.assertEqual(res["our_rank"], 3)
        self.assertEqual(res["our_value"], 300.0)

    def test_the_latest_period_is_used_when_none_is_named(self):
        BankingSectorPosition.objects.create(
            period="2026-Q1", bank_name="HF Group", is_us=True,
            total_deposits=Decimal("100"))
        BankingSectorPosition.objects.create(
            period="2026-Q2", bank_name="HF Group", is_us=True,
            total_deposits=Decimal("300"))
        self.assertEqual(bt.get_market_position()["period"], "2026-Q2")

    def test_a_bank_with_no_figure_for_that_metric_is_left_out_not_zeroed(self):
        BankingSectorPosition.objects.create(
            period="2026-Q2", bank_name="Reports Nothing")
        BankingSectorPosition.objects.create(
            period="2026-Q2", bank_name="HF Group", is_us=True,
            total_deposits=Decimal("300"))
        res = bt.get_market_position(metric="deposits")
        self.assertEqual([r["bank_name"] for r in res["results"]], ["HF Group"])

    def test_an_unknown_metric_is_refused(self):
        self.assertIn("error", bt.get_market_position(metric="vibes"))


class RegistryTests(TestCase):
    def test_the_new_tools_are_offered_to_the_model(self):
        from apps.agent.agent_tools import tool_definitions

        names = {t["name"] for t in tool_definitions()}
        self.assertLessEqual(
            {"get_customer", "get_branch_performance", "get_market_position"},
            names)

    def test_the_lake_tools_are_absent_until_a_host_is_configured(self):
        """Configuration is the control: no host, no tool to try and fail."""
        from django.test import override_settings

        from apps.agent.agent_tools import tool_definitions

        with override_settings(TRINO_HOST=""):
            self.assertNotIn("trino_customer_accounts",
                             {t["name"] for t in tool_definitions()})
        with override_settings(TRINO_HOST="10.21.18.65"):
            self.assertIn("trino_customer_accounts",
                          {t["name"] for t in tool_definitions()})

    def test_a_scoped_tool_receives_the_user_through_run_tool(self):
        """The whole boundary depends on run_tool passing the user along."""
        import json

        from apps.agent.agent_tools import run_tool

        out = json.loads(run_tool("get_customer", {"query": "x"},
                                  user=user("scoped_probe")))
        self.assertEqual(out["error"], "out_of_scope")

    def test_a_lake_tool_refuses_if_the_host_was_removed_after_definition(self):
        import json

        from django.test import override_settings

        from apps.agent.agent_tools import run_tool

        with override_settings(TRINO_HOST=""):
            out = json.loads(run_tool("trino_customer_accounts", {"cust_id": "1"}))
        self.assertIn("not configured", out["error"])
