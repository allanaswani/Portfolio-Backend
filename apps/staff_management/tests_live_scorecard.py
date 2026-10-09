"""The card built from what the system already holds.

No upload, no roster to load, nothing to run: the role and the targets come
from the branch DMC roster the business already maintains, and the actuals are
read from the warehouse when the page asks for them.
"""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from .live_scorecard import build_card, role_code_for, score_for
from .models import BranchFinalEmployeeDmcData


class RoleResolutionTests(TestCase):
    """A role is matched or it is not. Being scored against the wrong card is
    worse than not being scored."""

    def test_the_roster_spellings_resolve(self):
        for written, expected in [
            ("SME RM", "sme_rm"), ("sme  rm", "sme_rm"), ("SME BBC", "sme_bbc"),
            ("PB ARM", "pb_arm"), ("Ultimate RM", "ultimate_rm"),
            ("COMMERCIAL RM", "commercial_rm"),
            ("COMMERCIAL RM- TRADE", "commercial_rm_trade"),
            ("Mortgage Business ARM", "mortgage_business_arm"),
        ]:
            with self.subTest(written):
                self.assertEqual(role_code_for(written), expected)

    def test_a_longer_spelling_still_matches_its_own_role(self):
        """'SME BBC' must not be taken for 'SME RM' by matching a prefix."""
        self.assertEqual(role_code_for("SME BBC Nairobi"), "sme_bbc")

    def test_an_unknown_role_is_not_guessed_at(self):
        for written in ("Branch Manager", "Teller", "", None, "Head of SME"):
            with self.subTest(repr(written)):
                self.assertIsNone(role_code_for(written))


class ScoreTests(TestCase):
    def test_actual_over_target_capped_at_120(self):
        self.assertAlmostEqual(score_for(50, 100, True), 0.5)
        self.assertAlmostEqual(score_for(100, 100, True), 1.0)
        self.assertAlmostEqual(score_for(200, 100, True), 1.2, msg="capped")

    def test_a_shortfall_never_goes_negative(self):
        self.assertEqual(score_for(-40, 100, True), 0.0)

    def test_smaller_is_better_inverts(self):
        """Loan loss: half the expected loss is better than target."""
        self.assertAlmostEqual(score_for(50, 100, False), 1.2)
        self.assertAlmostEqual(score_for(200, 100, False), 0.5)

    def test_no_target_means_no_score_rather_than_a_division(self):
        self.assertIsNone(score_for(100, None, True))
        self.assertIsNone(score_for(100, 0, True))

    def test_no_actual_means_no_score_rather_than_a_zero(self):
        """Scoring somebody nought on a figure nobody has is worse than
        leaving the line blank."""
        self.assertIsNone(score_for(None, 100, True))


class CardFromTheSystemTests(TestCase):
    """End to end, with only the DMC roster in place - no uploads."""

    def setUp(self):
        self.user = User.objects.create_user("fj", password="x")
        Profile.objects.update_or_create(
            user=self.user,
            defaults={"sales_code": "FJ4145", "branch": "Nyeri",
                      "segment": "SME"})
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def roster(self, **kwargs):
        defaults = dict(
            staff_pf_number=4145, staff_name="Fridah Jabani",
            sales_code="FJ4145", staff_role="SME BBC", staff_branch="Nyeri",
            staff_unit="Nyeri", active=1,
            target_deposits_value=38_400_000,
            target_new_customers=12,
            target_loan_disbursement=108_000_000,
            target_pbt_revenue=15_000_000,
        )
        defaults.update(kwargs)
        return BranchFinalEmployeeDmcData.objects.create(**defaults)

    def test_on_none_of_the_rosters_the_card_says_so(self):
        """Three rosters are tried - the sales DMC roster, the back-office role
        history, and the HR record - so the reason names all three rather than
        only the one somebody happens to know about."""
        card = build_card("FJ4145")
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "not_on_any_roster")

    def test_a_role_with_no_card_is_named_rather_than_guessed(self):
        self.roster(staff_role="Branch Manager")
        card = build_card("FJ4145")
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "role_has_no_card")

    def test_the_roster_alone_produces_a_card(self):
        """The seeded role mappings supply the lines and weights; the DMC row
        supplies the role and the targets. Nothing was uploaded."""
        self.roster()
        card = build_card("FJ4145")
        self.assertTrue(card["has_card"], card)
        self.assertTrue(card["live"])
        self.assertEqual(card["staff"]["sales_code"], "FJ4145")
        self.assertEqual(card["staff"]["branch"], "Nyeri")
        self.assertTrue(card["perspectives"], "the card has no lines")
        self.assertGreater(
            card["scored_lines"] + card["pending_lines"], 10,
            "an SME BBC card should carry its full set of lines")

    def test_targets_come_from_the_dmc_row_and_are_prorated(self):
        self.roster()
        card = build_card("FJ4145")
        lines = [ln for group in card["perspectives"] for ln in group["lines"]]
        deposits = [ln for ln in lines if ln["kpi_code"] in
                    ("grow_deposits", "deposit_growth",
                     "deposit_growth_liab_growth_ntb_liab", "deposits_portfolio")]
        self.assertTrue(deposits, "no deposit line on the card")
        target = deposits[0]["ytd_target"]
        self.assertIsNotNone(target, "the DMC target was not picked up")
        self.assertLess(target, 38_400_000, "a YTD target is less than the year")
        self.assertGreater(target, 0)

    def test_a_line_with_no_warehouse_figure_is_pending_not_zero(self):
        self.roster()
        card = build_card("FJ4145")
        lines = [ln for group in card["perspectives"] for ln in group["lines"]]
        pending = [ln for ln in lines if ln["pending"]]
        self.assertTrue(pending, "nothing is pending, which cannot be right "
                                 "on an empty warehouse")
        for line in pending:
            self.assertIsNone(line["score"],
                              f"{line['kpi_code']} is pending but carries a score")
            self.assertIsNone(line["weighted_score"])

    def test_the_endpoint_serves_it_without_anything_being_loaded(self):
        self.roster()
        response = self.client.get(
            "/staff_management/scorecard-automation/my-card/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["has_card"], response.data)

    def test_somebody_with_no_sales_code_is_told_which_problem_it_is(self):
        other = User.objects.create_user("nocode", password="x")
        Profile.objects.update_or_create(user=other, defaults={"sales_code": ""})
        client = APIClient()
        client.force_authenticate(other)
        response = client.get("/staff_management/scorecard-automation/my-card/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["has_card"])
        self.assertEqual(response.data["reason"], "no_sales_code")
