"""The five modules the assistant had no tool for.

The assistant is one agent behind nineteen entry points, with no per-module
scope: the module pages differ only in their suggestion chips. So a module with
no tool is one the assistant cannot answer about - and it does not say so, it
reasons from whatever else it has.

Service Desk, Referrals, Commercial Pipeline, Design Briefs and the Trade
Register were in that position. These tests exist mainly to prove the queries
are valid against the real schema: every one of these tools failed on a
developer database that was behind on migrations, and ``run_tool`` swallows that
into ``{"error": ...}`` by design, so a broken query looks exactly like an empty
table unless something asserts the difference.
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.agent.agent_tools import run_tool, tool_definitions
from apps.referrals.models import Referral

NEW_TOOLS = {
    "get_service_desk_summary": [
        "total_tickets", "by_status", "by_priority",
        "open_past_resolution_due", "unassigned", "kb_articles", "tickets",
    ],
    "get_referrals_summary": [
        "total_referrals", "by_status", "by_branch", "converted", "contacted",
        "unallocated", "flagged_possible_duplicate", "referrals",
    ],
    "get_commercial_pipeline": [
        "total_entries", "by_kind", "by_segment", "entries",
    ],
    "get_design_briefs_summary": [
        "total_briefs", "by_status", "by_department", "unassigned",
        "sent_back_for_rework", "briefs",
    ],
    "get_trade_register_summary": [
        "total_entries", "by_product_type", "by_action", "by_branch",
        "commission_total_kes", "excise_duty_total_kes", "entries",
    ],
}


class ToolsAreOfferedTests(TestCase):
    def test_all_five_are_offered_to_the_model(self):
        names = [d["name"] for d in tool_definitions()]
        for name in NEW_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, names)

    def test_every_offered_tool_has_a_description_and_schema(self):
        for d in tool_definitions():
            with self.subTest(tool=d["name"]):
                self.assertTrue(d.get("description"), "no description")
                self.assertEqual(d["input_schema"]["type"], "object")

    def test_no_duplicate_tool_names(self):
        names = [d["name"] for d in tool_definitions()]
        self.assertEqual(len(names), len(set(names)), f"duplicates in {names}")


class QueriesAreValidAgainstTheSchemaTests(TestCase):
    """An empty table must return zeros, never an error.

    This is the test that would have caught the real failure mode: a column that
    does not exist produces ``{"error": ...}``, which is indistinguishable from
    "nothing to report" to the model, and therefore to the reader.
    """

    def test_each_tool_succeeds_on_an_empty_database(self):
        for name, keys in NEW_TOOLS.items():
            with self.subTest(tool=name):
                out = json.loads(run_tool(name, {}))
                self.assertNotIn(
                    "error", out,
                    msg=f"{name} failed instead of reporting an empty table: "
                        f"{out.get('error')}",
                )
                for key in keys:
                    self.assertIn(key, out, msg=f"{name} is missing '{key}'")

    def test_an_empty_database_reports_zero_not_nothing(self):
        out = json.loads(run_tool("get_referrals_summary", {}))
        self.assertEqual(out["total_referrals"], 0)
        self.assertEqual(out["referrals"], [])

    def test_the_limit_argument_is_accepted_and_clamped(self):
        for name in NEW_TOOLS:
            with self.subTest(tool=name):
                out = json.loads(run_tool(name, {"limit": 10_000}))
                self.assertNotIn("error", out)


class ReferralsToolCountsTests(TestCase):
    """One module exercised with real rows, to prove the aggregates aggregate."""

    @classmethod
    def setUpTestData(cls):
        agent = User.objects.create_user(username="tele1", password="x")
        # Distinct national_id and phone per referral on purpose: the module
        # auto-flags possible duplicates on save when an identity repeats, so
        # sharing them here would flag rows this test did not intend to flag and
        # the duplicate count would measure the fixture rather than the tool.
        Referral.objects.create(customer_name="A", status="unallocated",
                                branch="KISII BRANCH",
                                pf_number="PF1", national_id="11111111", phone="0700000001")
        Referral.objects.create(customer_name="B", status="allocated",
                                branch="KISII BRANCH", assigned_to=agent,
                                pf_number="PF2", national_id="22222222", phone="0700000002")
        Referral.objects.create(customer_name="C", status="allocated",
                                branch="NYERI BRANCH", assigned_to=agent,
                                pf_number="PF3", national_id="33333333", phone="0700000003")

    def test_totals_and_breakdowns(self):
        out = json.loads(run_tool("get_referrals_summary", {}))
        self.assertEqual(out["total_referrals"], 3)
        self.assertEqual(out["by_status"]["allocated"], 2)
        self.assertEqual(out["by_status"]["unallocated"], 1)
        self.assertEqual(out["by_branch"]["KISII BRANCH"], 2)
        self.assertEqual(out["unallocated"], 1)
        # Three distinct identities, so nothing is flagged.
        self.assertEqual(out["flagged_possible_duplicate"], 0)

    def test_the_duplicate_count_reflects_the_module_s_own_flagging(self):
        """``is_possible_duplicate`` is derived, not settable.

        The module recomputes it on save, so passing it to ``create()`` is
        silently discarded - which is why this creates a real collision instead.
        """
        Referral.objects.create(customer_name="A again", status="unallocated",
                                branch="KISII BRANCH", pf_number="PF1",
                                national_id="11111111", phone="0700000001")
        out = json.loads(run_tool("get_referrals_summary", {}))
        self.assertEqual(out["total_referrals"], 4)
        self.assertGreaterEqual(
            out["flagged_possible_duplicate"], 1,
            msg="a repeated national_id/phone should be flagged by the module",
        )

    def test_the_status_filter_narrows_the_list_but_not_the_totals(self):
        out = json.loads(run_tool("get_referrals_summary", {"status": "allocated"}))
        # The listing follows the filter...
        self.assertEqual(len(out["referrals"]), 2)
        # ...while the headline total stays the whole module, so a filtered
        # answer cannot be read as the bank's total.
        self.assertEqual(out["total_referrals"], 3)

    def test_the_limit_caps_the_listing(self):
        out = json.loads(run_tool("get_referrals_summary", {"limit": 1}))
        self.assertEqual(len(out["referrals"]), 1)
        self.assertEqual(out["total_referrals"], 3)

    def test_an_unknown_status_returns_an_empty_list_not_an_error(self):
        out = json.loads(run_tool("get_referrals_summary", {"status": "nonsense"}))
        self.assertNotIn("error", out)
        self.assertEqual(out["referrals"], [])
