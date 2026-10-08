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


def board_user(username="agent_tools_root"):
    """Somebody who may see every module these tools read.

    Four of the five tools are bank-wide and ignore the user entirely. Design
    Briefs is gated on Marketing's two groups, so these tests - which are about
    whether the QUERIES are valid, not about who may run them - pass a user who
    is through that door. Who gets through it is tested in GatedToolTests.
    """
    return User.objects.create_user(
        username=username, password="x", is_superuser=True, is_staff=True)

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
    @classmethod
    def setUpTestData(cls):
        cls.user = board_user()

    def test_all_five_are_offered_to_the_model(self):
        names = [d["name"] for d in tool_definitions(self.user)]
        for name in NEW_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, names)

    def test_every_offered_tool_has_a_description_and_schema(self):
        for d in tool_definitions(self.user):
            with self.subTest(tool=d["name"]):
                self.assertTrue(d.get("description"), "no description")
                self.assertEqual(d["input_schema"]["type"], "object")

    def test_no_duplicate_tool_names(self):
        names = [d["name"] for d in tool_definitions(self.user)]
        self.assertEqual(len(names), len(set(names)), f"duplicates in {names}")


class QueriesAreValidAgainstTheSchemaTests(TestCase):
    """An empty table must return zeros, never an error.

    This is the test that would have caught the real failure mode: a column that
    does not exist produces ``{"error": ...}``, which is indistinguishable from
    "nothing to report" to the model, and therefore to the reader.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = board_user()

    def test_each_tool_succeeds_on_an_empty_database(self):
        for name, keys in NEW_TOOLS.items():
            with self.subTest(tool=name):
                out = json.loads(run_tool(name, {}, user=self.user))
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
                out = json.loads(run_tool(name, {"limit": 10_000}, user=self.user))
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


class GatedToolTests(TestCase):
    """The assistant must not be a second way into a module with a door.

    Design Briefs is Marketing's, gated on ``marketing_admin`` /
    ``marketing_designer``. Without this, somebody the board refuses could ask
    the assistant "give me the design briefs overview" and read every
    department's briefs, designers and release dates anyway - the module page
    would say no and the chat box would say yes.

    The other four tools are bank-wide by design and deliberately stay open.
    """

    GATED = "get_design_briefs_summary"

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group
        from apps.design_briefs import rbac

        cls.nobody = User.objects.create_user(username="agent_nobody", password="x")
        cls.designer = User.objects.create_user(username="agent_designer", password="x")
        cls.designer.groups.add(
            Group.objects.get_or_create(name=rbac.DESIGNER_GROUP)[0])
        cls.root = board_user("agent_gate_root")

    def test_it_is_not_offered_to_somebody_who_is_not_on_the_board(self):
        self.assertNotIn(self.GATED,
                         [d["name"] for d in tool_definitions(self.nobody)])

    def test_it_is_refused_even_if_the_model_names_it_anyway(self):
        """Withholding the definition is a prompt-level control on its own."""
        out = json.loads(run_tool(self.GATED, {}, user=self.nobody))
        self.assertIn("error", out)
        self.assertNotIn("total_briefs", out)

    def test_a_caller_that_forgets_the_user_gets_nothing_rather_than_everything(self):
        self.assertNotIn(self.GATED, [d["name"] for d in tool_definitions()])
        self.assertIn("error", json.loads(run_tool(self.GATED, {})))

    def test_a_designer_is_offered_it_and_may_run_it(self):
        self.assertIn(self.GATED,
                      [d["name"] for d in tool_definitions(self.designer)])
        self.assertNotIn("error", json.loads(run_tool(self.GATED, {}, user=self.designer)))

    def test_a_superuser_may_run_it(self):
        self.assertNotIn("error", json.loads(run_tool(self.GATED, {}, user=self.root)))

    def test_the_other_four_stay_open_to_everybody(self):
        for name in NEW_TOOLS:
            if name == self.GATED:
                continue
            with self.subTest(tool=name):
                self.assertIn(name, [d["name"] for d in tool_definitions(self.nobody)])
                self.assertNotIn("error", json.loads(run_tool(name, {}, user=self.nobody)))
