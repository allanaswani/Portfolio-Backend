"""Outward-facing lookups: what may leave the bank, and what may not.

Most of these are about refusing. The assistant composes its own search string,
so a prompt instruction is guidance rather than a control — the control is here,
server-side, and it has to hold against a model that did not read the warning.
"""

import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.agent import agent_tools, web_lookup

KEY = "sk-test-not-a-real-key"


class SwitchedOffTests(TestCase):
    """No key means the tools do not exist at all."""

    @override_settings(TINYFISH_API_KEY="")
    def test_the_external_tools_are_not_offered_to_the_model(self):
        """It cannot try and fail at something it was never told about."""
        names = {t["name"] for t in agent_tools.tool_definitions()}
        self.assertNotIn("search_the_web", names)
        self.assertNotIn("fetch_web_page", names)

    @override_settings(TINYFISH_API_KEY="")
    def test_the_bank_tools_are_still_all_there(self):
        names = {t["name"] for t in agent_tools.tool_definitions()}
        self.assertIn("get_portfolio_dashboard", names)
        self.assertIn("get_trade_finance_summary", names)

    @override_settings(TINYFISH_API_KEY="")
    def test_calling_one_anyway_reaches_no_third_party(self):
        with patch("apps.agent.web_lookup._request") as called:
            out = json.loads(agent_tools.run_tool("search_the_web", {"query": "cbk rate"}))
        called.assert_not_called()
        self.assertIn("error", out)

    @override_settings(TINYFISH_API_KEY=KEY)
    def test_a_key_turns_them_on(self):
        names = {t["name"] for t in agent_tools.tool_definitions()}
        self.assertIn("search_the_web", names)
        self.assertIn("fetch_web_page", names)


@override_settings(TINYFISH_API_KEY=KEY)
class LeakGuardTests(TestCase):
    """Nothing that identifies a person or an account may leave the bank."""

    def assertRefused(self, query):
        with patch("apps.agent.web_lookup._request") as called:
            result = web_lookup.search(query)
        called.assert_not_called()
        self.assertEqual(result.get("error"), "refused", query)

    def test_a_customer_number_is_refused(self):
        self.assertRefused("deposit balance for customer 1110801")

    def test_a_bare_long_number_is_refused(self):
        """It may be an account, an ID or a CIF — none of them may go out."""
        self.assertRefused("what is 34399249")

    def test_a_field_name_is_refused_even_without_a_number(self):
        self.assertRefused("look up the cust_id for this client")
        self.assertRefused("what is the KRA PIN process")

    def test_an_id_or_pin_shape_is_refused(self):
        self.assertRefused("verify A012345678B")

    def test_an_email_address_is_refused(self):
        self.assertRefused("who is stacy.mwenda@hfgroup.co.ke")

    def test_a_phone_number_is_refused(self):
        self.assertRefused("whose number is 0712345678")
        self.assertRefused("whose number is +254712345678")

    def test_a_trade_finance_reference_is_refused(self):
        """It names a customer's instrument."""
        self.assertRefused("status of HFCB/GTE/260630/01")

    def test_a_url_carrying_an_identifier_is_refused_too(self):
        with patch("apps.agent.web_lookup._request") as called:
            result = web_lookup.fetch_page("https://example.com/customer/1110801")
        called.assert_not_called()
        self.assertEqual(result.get("error"), "refused")

    def test_the_refusal_says_what_to_do_instead(self):
        """A refusal the model cannot act on just gets retried identically."""
        result = web_lookup.search("balance for customer 1110801")
        self.assertIn("internal tools", result["reason"])
        self.assertIn("PUBLIC", result["reason"])

    def test_an_ordinary_public_question_goes_through(self):
        for query in ("current CBK central bank rate",
                      "Kenya Finance Act 2026 summary",
                      "Equity Bank half year results",
                      "what is a letter of credit"):
            self.assertIsNone(web_lookup.check_query(query), query)


@override_settings(TINYFISH_API_KEY=KEY)
class SearchTests(TestCase):
    RESPONSE = {
        "query": "cbk rate",
        "results": [
            {"position": 1, "title": "CBK Rate", "url": "https://centralbank.go.ke/",
             "site_name": "centralbank.go.ke", "snippet": "The Central Bank Rate is…"},
            {"position": 2, "title": "Other", "url": "https://example.com/",
             "site_name": "example.com", "snippet": "…"},
        ],
    }

    def test_results_come_back_flattened_for_the_model(self):
        with patch("apps.agent.web_lookup._request", return_value=self.RESPONSE):
            out = web_lookup.search("cbk rate")
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["results"][0]["title"], "CBK Rate")
        self.assertEqual(out["results"][0]["site"], "centralbank.go.ke")

    def test_it_says_the_answer_came_from_outside(self):
        """The user must be able to tell bank data from the open web."""
        with patch("apps.agent.web_lookup._request", return_value=self.RESPONSE):
            out = web_lookup.search("cbk rate")
        self.assertIn("external", out["source"])

    def test_the_limit_is_capped(self):
        with patch("apps.agent.web_lookup._request", return_value=self.RESPONSE):
            out = web_lookup.search("cbk rate", limit=9999)
        self.assertLessEqual(len(out["results"]), web_lookup.MAX_RESULTS)

    def test_a_nonsense_limit_does_not_raise(self):
        with patch("apps.agent.web_lookup._request", return_value=self.RESPONSE):
            out = web_lookup.search("cbk rate", limit="lots")
        self.assertTrue(out["results"])

    def test_the_service_being_down_degrades_one_tool(self):
        """The assistant answers from the bank's own data most of the time; a
        third party must not fail the whole reply."""
        with patch("apps.agent.web_lookup.urllib.request.urlopen",
                   side_effect=OSError("no route to host")):
            out = web_lookup.search("cbk rate")
        self.assertIn("error", out)
        self.assertNotIn("results", out)

    def test_run_tool_never_raises_on_it(self):
        with patch("apps.agent.web_lookup.urllib.request.urlopen",
                   side_effect=OSError("down")):
            raw = agent_tools.run_tool("search_the_web", {"query": "cbk rate"})
        self.assertIn("error", json.loads(raw))


@override_settings(TINYFISH_API_KEY=KEY)
class FetchTests(TestCase):
    def test_a_page_comes_back_as_text(self):
        with patch("apps.agent.web_lookup._request",
                   return_value={"title": "T", "content": "hello world"}):
            out = web_lookup.fetch_page("https://example.com/a")
        self.assertEqual(out["content"], "hello world")
        self.assertFalse(out["truncated"])

    def test_a_long_page_is_trimmed_and_says_so(self):
        """A whole article would crowd the bank's own data out of the context."""
        with patch("apps.agent.web_lookup._request",
                   return_value={"content": "x" * 50_000}):
            out = web_lookup.fetch_page("https://example.com/a")
        self.assertEqual(len(out["content"]), web_lookup.MAX_PAGE_CHARS)
        self.assertTrue(out["truncated"])

    def test_something_that_is_not_a_url_is_refused(self):
        with patch("apps.agent.web_lookup._request") as called:
            out = web_lookup.fetch_page("centralbank.go.ke")
        called.assert_not_called()
        self.assertIn("error", out)


@override_settings(TINYFISH_API_KEY=KEY)
class RequestShapeTests(TestCase):
    """What actually goes on the wire."""

    def test_the_key_travels_in_the_header_not_the_query_string(self):
        """A key in a URL lands in every proxy and access log between here and
        there."""
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"results": []}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            return FakeResponse()

        with patch("apps.agent.web_lookup.urllib.request.urlopen", fake_urlopen):
            web_lookup.search("cbk rate")

        self.assertNotIn(KEY, captured["url"])
        self.assertEqual(
            {k.lower(): v for k, v in captured["headers"].items()}.get("x-api-key"),
            KEY)


class FailureMessageTests(TestCase):
    """What a person reads when the assistant cannot answer.

    Every failure used to arrive as "temporarily unavailable", which sends the
    reader to check the network — and the most common cause is an account out
    of credit, which is not temporary and will not fix itself.
    """

    def explain(self, message):
        from apps.agent.views import _explain

        return _explain(Exception(message))

    def test_no_credit_says_so_plainly(self):
        out = self.explain(
            "Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': 'Your credit balance is too low "
            "to access the Anthropic API. Please go to Plans & Billing to "
            "upgrade or purchase credits.'}}")
        self.assertIn("run out of Anthropic credit", out)
        self.assertIn("Plans & Billing", out)
        self.assertNotIn("temporarily unavailable", out)

    def test_it_says_the_rest_of_the_application_is_fine(self):
        """Otherwise 'the assistant is down' reads as 'the tool is down'."""
        out = self.explain("Your credit balance is too low")
        self.assertIn("unaffected", out)

    def test_a_bad_key_points_at_the_key(self):
        out = self.explain("Error code: 401 - authentication_error: invalid x-api-key")
        self.assertIn("ANTHROPIC_API_KEY", out)

    def test_rate_limiting_says_to_wait(self):
        out = self.explain("Error code: 429 - rate_limit_error")
        self.assertIn("rate limited", out)

    def test_a_network_failure_names_the_network(self):
        out = self.explain("Connection error.")
        self.assertIn("outbound network", out)

    def test_anything_unrecognised_still_carries_the_detail(self):
        """A message the reader cannot act on is still better than none."""
        out = self.explain("something nobody anticipated")
        self.assertIn("something nobody anticipated", out)
