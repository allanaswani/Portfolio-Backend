"""The card built from what the system already holds.

No upload, no roster to load, nothing to run: the role and the targets come
from the branch DMC roster the business already maintains, and the actuals are
read from the warehouse when the page asks for them.
"""

import datetime
from unittest import mock

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

    def test_the_card_is_labelled_with_its_own_month(self):
        """The month the card is FOR, not the date of whichever line came last.

        ``build_card`` assigned the per-line figure date straight over its own
        ``as_at`` parameter, so the payload was built from whatever the LAST
        KPI line carried. On a real September card the last line is PAR, whose
        IFRS feed stops at July 2025, and the card footed itself "Performance
        score for July 2025" while every line above it said 30 Sep 2026.
        """
        self.roster()
        september = datetime.date(2026, 9, 30)
        card = build_card("FJ4145", as_at=september)
        self.assertEqual(card["period"]["label"], "September 2026")
        self.assertEqual(card["period"]["as_at"], september.isoformat())

    def test_a_named_month_slices_every_target_to_that_month(self):
        """A "YTD target for September" belongs to September.

        Pro-rating each line to its own feed's date put three of Abed Lelgo's
        September lines outside September: loan loss to 1 Jul 2025 (half a
        year, on a card claiming three quarters), VIC to 15 Oct and loan
        disbursements to 22 Oct. The target must not move with the feed.
        """
        self.roster()
        card = build_card("FJ4145", as_at=datetime.date(2026, 9, 30))
        lines = [ln for group in card["perspectives"] for ln in group["lines"]]
        nine_twelfths = 38_400_000 * 9 / 12
        deposits = [ln for ln in lines if ln["kpi_code"] in
                    ("grow_deposits", "deposit_growth",
                     "deposit_growth_liab_growth_ntb_liab", "deposits_portfolio")]
        self.assertTrue(deposits, "no deposit line on the card")
        target = deposits[0]["ytd_target"]
        self.assertIsNotNone(target)
        # Nine months of the year, to the shilling - not ten, and not six.
        self.assertAlmostEqual(target, nine_twelfths, delta=1.0)

    def test_a_live_card_still_slices_to_each_lines_own_date(self):
        """The rule only changes for a NAMED month. A live card keeps the
        desk's own rule, which the eight real cards were calibrated against:
        a figure three weeks old is not judged against a target that assumes
        today."""
        self.roster()
        card = build_card("FJ4145")          # no as_at - the live card
        self.assertEqual(
            card["period"]["label"],
            datetime.date.today().strftime("%B %Y"))
        self.assertIsNone(card["period"]["as_at"])

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

    # ── the month picker ─────────────────────────────────────────────────
    #
    # download/ and card-for/ honoured ?month=; this view did not, and always
    # built the live card. So the picker on the page moved the downloaded
    # workbook and left every figure on screen exactly as it was - "I go to
    # other months and nothing changes", which is precisely what it did.

    URL = "/staff_management/scorecard-automation/my-card/"

    def test_a_month_is_passed_through_to_the_card(self):
        self.roster()
        with mock.patch(
                "apps.staff_management.live_scorecard.build_card",
                return_value={"has_card": False, "reason": "x"}) as built:
            self.client.get(self.URL + "?month=2026-07")
        self.assertEqual(built.call_args.kwargs.get("as_at"),
                         datetime.date(2026, 7, 31),
                         "the card must be built for the month END asked for")

    def test_no_month_still_builds_the_live_card(self):
        self.roster()
        with mock.patch(
                "apps.staff_management.live_scorecard.build_card",
                return_value={"has_card": False, "reason": "x"}) as built:
            self.client.get(self.URL)
        self.assertIsNone(built.call_args.kwargs.get("as_at"))

    def test_a_month_that_has_not_closed_is_refused(self):
        """A card for the month you are standing in shows a few days of
        actuals against a target pro-rated to the same few days, which reads
        as a collapse in performance rather than an incomplete month."""
        self.roster()
        today = datetime.date.today()
        response = self.client.get(self.URL + f"?month={today:%Y-%m}")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("month", response.data)

    def test_a_bad_month_is_refused_rather_than_ignored(self):
        self.roster()
        response = self.client.get(self.URL + "?month=bogus")
        self.assertEqual(response.status_code, 400, response.content)

    def test_the_card_says_which_month_it_is(self):
        """So the page cannot show one month and label it another."""
        self.roster()
        response = self.client.get(self.URL + "?month=2026-07")
        if response.data.get("has_card"):
            self.assertEqual(response.data["month"], "2026-07-31")

    def test_somebody_nothing_identifies_is_told_which_problem_it_is(self):
        """An empty profile is no longer the end of the search.

        This used to assert ``no_sales_code``, and that reason was the bug:
        it named the ONE identifier that is set for people who carry a sales
        book and for nobody else, so every back-office card holder was sent to
        fix a profile field that was never going to be filled in for them. The
        card now looks for the person on the back-office roster and the HR
        roster as well, and only when none of those knows them does it say so -
        naming everything it tried, so the answer can be handed to whoever can
        act on it. See ``live_scorecard.resolve_sales_code_for_user``.
        """
        other = User.objects.create_user("nocode", password="x")
        Profile.objects.update_or_create(user=other, defaults={"sales_code": ""})
        client = APIClient()
        client.force_authenticate(other)
        response = client.get("/staff_management/scorecard-automation/my-card/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["has_card"])
        self.assertEqual(response.data["reason"], "not_identified")
        self.assertIn("your profile", response.data["tried"])
        self.assertIn("the back-office roster", response.data["tried"])


class PortfolioAumTests(TestCase):
    """AUM is the deposit book plus the loan book.

    The card used to tell people this was "a count somebody keeps" and to
    have Administration type it in - on a figure that is the sum of two
    numbers the same card already computes for its deposit-growth and
    asset-growth lines. The only thing missing was the addition.
    """

    def actuals(self, deposits, loans, as_at=None):
        from .live_scorecard import live_actuals

        def fake(table, sales_code, as_at=None):
            return deposits if table == "daily_balance_movement" else loans

        with mock.patch("services.portfolio_service.rm_growth", fake):
            return live_actuals("FJ4145", wanted={"portfolio_aum"},
                                as_at=as_at)

    @staticmethod
    def half(position, base, when):
        return {"position": position, "base": base,
                "growth": None if position is None or base is None
                else position - base,
                "as_at": when, "as_at_label": "", "problem": None}

    def test_the_two_books_are_added(self):
        out = self.actuals(
            self.half(300_000_000.0, 250_000_000.0, datetime.date(2026, 9, 30)),
            self.half(200_000_000.0, 180_000_000.0, datetime.date(2026, 9, 30)))
        self.assertEqual(out["portfolio_aum"]["value"], 500_000_000.0)
        self.assertEqual(out["_bases"]["december_aum_book"], 430_000_000.0)
        self.assertIn("deposit book + loan book", out["portfolio_aum"]["as_at_label"])

    def test_the_as_at_is_the_older_of_the_two(self):
        """The sum is only as complete as the half furthest behind. Dating it
        to the newer reading would claim a currency it does not have."""
        out = self.actuals(
            self.half(300_000_000.0, 250_000_000.0, datetime.date(2026, 9, 30)),
            self.half(200_000_000.0, 180_000_000.0, datetime.date(2026, 7, 31)))
        self.assertEqual(out["portfolio_aum"]["as_at"],
                         datetime.date(2026, 7, 31))

    def test_one_book_missing_is_not_an_AUM(self):
        """Deposits alone reported as AUM would understate the book by the
        whole loan portfolio, and the number would look plausible."""
        out = self.actuals(
            self.half(300_000_000.0, 250_000_000.0, datetime.date(2026, 9, 30)),
            self.half(None, None, None))
        self.assertIsNone(out["portfolio_aum"]["value"])
        self.assertIn("cannot be added", out["portfolio_aum"]["problem"])

    def test_the_base_needs_both_closings(self):
        out = self.actuals(
            self.half(300_000_000.0, 250_000_000.0, datetime.date(2026, 9, 30)),
            self.half(200_000_000.0, None, datetime.date(2026, 9, 30)))
        self.assertEqual(out["portfolio_aum"]["value"], 500_000_000.0)
        self.assertNotIn("december_aum_book", out["_bases"])
