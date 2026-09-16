"""The assistant answering about the RIGHT person's book.

A relationship manager asked "tell me about my portfolio across my customers"
and was told they had one borrower and no loans. That answer came from the
mortgage module: a different product, a bank-wide view, and one test record.

Two faults, and only one was the prompt. Nothing read the person's actual
book, and no tool was scoped to whoever was asking — ``_role_context`` merely
*asked* the model to tailor its emphasis, which is a request, not a boundary.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.agent import agent_tools, rm_tools


def person(username, sales_code=None):
    """A user with a sales code on their profile.

    apps.portfolio creates a Profile on post_save, so one already exists here.
    Edit that instance rather than creating another: user.profile caches the
    signal's object, so writing a second row leaves the accessor stale and
    every scoping assertion passes for the wrong reason.
    """
    user = get_user_model().objects.create_user(username=username, password="x")
    if sales_code is not None:
        user.profile.sales_code = sales_code
        user.profile.save()
    return user


class ToolSurfaceTests(TestCase):
    def test_the_users_own_book_is_offered_first(self):
        """The model picks by description; putting the personal tools first
        is the cheapest way to make 'my portfolio' land on the right one."""
        names = [t["name"] for t in agent_tools.tool_definitions()]
        self.assertEqual(names[0], "get_my_portfolio")
        self.assertIn("get_my_customers", names)
        self.assertIn("get_my_loans", names)

    def test_the_mortgage_tool_now_says_it_is_the_mortgage_book(self):
        """It was called get_portfolio_dashboard, so the model reasonably
        picked it for any question containing the word portfolio."""
        by_name = {t["name"]: t for t in agent_tools.tool_definitions()}
        self.assertIn("get_mortgage_dashboard", by_name)
        self.assertIn("MORTGAGE", by_name["get_mortgage_dashboard"]["description"].upper())

    def test_the_old_name_still_executes(self):
        """A conversation already in flight must not break mid-answer."""
        self.assertIn("get_portfolio_dashboard", agent_tools._DISPATCH)


class ScopingTests(TestCase):
    def test_the_sales_code_comes_from_the_signed_in_user(self):
        user = person("rm1", sales_code="DSR001")
        self.assertEqual(rm_tools.sales_code_of(user), "DSR001")

    def test_no_profile_means_no_code_rather_than_an_error(self):
        self.assertIsNone(rm_tools.sales_code_of(person("rm2")))

    def test_a_blank_code_is_not_a_code(self):
        self.assertIsNone(rm_tools.sales_code_of(person("rm3", sales_code="  ")))

    def test_an_anonymous_caller_gets_nothing(self):
        self.assertIsNone(rm_tools.sales_code_of(None))

    def test_without_a_code_it_refuses_instead_of_widening(self):
        """Bank-wide figures returned to somebody who asked about their own
        book look like their own book. That is worse than an error."""
        out = rm_tools.my_portfolio(user=person("rm4"))
        self.assertEqual(out["error"], "no_sales_code")
        self.assertIn("do not substitute", out["detail"].lower())

    def test_every_personal_tool_refuses_without_a_code(self):
        nobody = person("rm5")
        for fn in (rm_tools.my_portfolio, rm_tools.my_customers, rm_tools.my_loans):
            self.assertEqual(fn(user=nobody).get("error"), "no_sales_code",
                             fn.__name__)

    def test_the_queries_are_keyed_on_that_users_code(self):
        user = person("rm6", sales_code="DSR777")
        with patch("apps.agent.rm_tools.svc") as svc:
            svc.customers.return_value = []
            rm_tools.my_customers(user=user)
        svc.customers.assert_called_once_with("DSR777")

    def test_the_answer_says_it_is_scoped(self):
        """So the model cannot present a personal figure as a bank figure."""
        user = person("rm7", sales_code="DSR001")
        with patch("apps.agent.rm_tools.svc") as svc:
            svc.customers.return_value = []
            out = rm_tools.my_customers(user=user)
        self.assertIn("own book", out["scope"])


class DispatchTests(TestCase):
    def test_run_tool_passes_the_user_through(self):
        """Asserted through the effect rather than the call.

        DISPATCH binds the function object at import, so patching the module
        attribute never reaches it — and a test that patched the name would
        pass while the dispatch table called something else entirely.
        """
        user = person("rm8", sales_code="DSR808")
        with patch("apps.agent.rm_tools.svc") as svc:
            svc.customers.return_value = []
            agent_tools.run_tool("get_my_customers", {}, user=user)
        svc.customers.assert_called_once_with("DSR808")

    def test_a_personal_tool_called_with_no_user_refuses(self):
        """Any path that forgets to pass the user must fail closed."""
        import json

        out = json.loads(agent_tools.run_tool("get_my_portfolio", {}))
        self.assertEqual(out.get("error"), "no_sales_code")

    def test_a_failing_warehouse_read_does_not_raise(self):
        import json

        user = person("rm9", sales_code="DSR001")
        with patch("apps.agent.rm_tools.svc") as svc:
            svc.customers.side_effect = Exception("warehouse down")
            raw = agent_tools.run_tool("get_my_customers", {}, user=user)
        self.assertIn("error", json.loads(raw))

    def test_one_broken_block_does_not_lose_the_others(self):
        """A portfolio answer with three of four figures beats no answer."""
        user = person("rm10", sales_code="DSR001")
        with patch("apps.agent.rm_tools.svc") as svc:
            svc.rM_total_customers.side_effect = Exception("no table")
            svc.rm_revenue.return_value = {"total": 5}
            svc.loans_arrears_by_sales_code.return_value = []
            svc.rm_new_customers_ytd.return_value = 3
            out = rm_tools.my_portfolio(user=user)
        self.assertIn("error", out["customers"])
        self.assertEqual(out["revenue"], {"total": 5})
        self.assertEqual(out["new_customers_ytd"], 3)


class PromptTests(TestCase):
    """The prompt is the other half of the fix, and it is easy to erode."""

    def prompt(self):
        from apps.agent.prompt import SYSTEM_PROMPT

        return SYSTEM_PROMPT

    def test_it_tells_the_model_to_decide_whose_data_first(self):
        self.assertIn("WHOSE DATA", self.prompt())

    def test_it_names_the_personal_tools(self):
        text = self.prompt()
        for name in ("get_my_portfolio", "get_my_customers", "get_my_loans"):
            self.assertIn(name, text)

    def test_it_forbids_answering_a_personal_question_bank_wide(self):
        self.assertIn("worst", self.prompt())
        self.assertIn("somebody else", self.prompt())

    def test_it_forbids_naming_tools_to_the_reader(self):
        """'The business insights tool returned no records' is machine talk."""
        self.assertIn("Never name tools", self.prompt())

    def test_it_says_the_current_month_is_not_closed(self):
        self.assertIn("never closed", self.prompt())

    def test_it_contains_no_stray_escape_sequences(self):
        """An earlier edit wrote literal backslash-n into the text."""
        self.assertNotIn("\\n", self.prompt())
