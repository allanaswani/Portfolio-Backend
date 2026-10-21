"""Loan loss: the arithmetic the card scores, pinned to Finance's workbook.

Nothing in the scorecard changed for this line - the platform has computed it
correctly since before the question was asked. These tests exist so that stays
true, and so the claim "this is what the workbook does" is checked rather than
asserted. The numbers are read off the worked example,
``3. FS_MOM_IFRS_MOVEMENT_Branch & TREND (with Special Assets) (1).xlsb``.
"""

import pathlib

from django.test import SimpleTestCase

from . import loan_loss
from .live_scorecard import SOURCES, score_for


class TheWorkbooksArithmeticTests(SimpleTestCase):
    def test_net_is_the_charge_less_the_interest_adjustment(self):
        """The first row of the example's Aug 2026 sheet, to the digit. This
        is the whole measure: ``NET`` = ``P&L_Charge`` − ``Int. Adj``."""
        self.assertAlmostEqual(
            loan_loss.monthly_loss(7180415.670671493, 213299.13991357503),
            6967116.530757918, places=6)
        self.assertAlmostEqual(
            loan_loss.monthly_loss(3572829.1014112607, 388661.9028503353),
            3184167.198560925, places=6)

    def test_a_blank_adjustment_is_a_nought_and_not_a_missing_charge(self):
        """The workbook leaves the cell empty where there was no adjustment.
        Treating it as missing would drop the charge beside it."""
        self.assertAlmostEqual(
            loan_loss.monthly_loss(4109665.400000004, None),
            4109665.400000004, places=6)
        self.assertEqual(loan_loss.monthly_loss(None, None), 0.0)

    def test_a_month_can_be_a_release_and_that_is_a_negative(self):
        """``CUSTOMER SUMMARY_2026``, cif 52285, February: a charge of
        42,588.40 against an adjustment of 45,959.73 is a net RELEASE of
        3,371.33, and the workbook writes it negative."""
        self.assertAlmostEqual(
            loan_loss.monthly_loss(42588.40000000037, 45959.73),
            -3371.3299999996307, places=6)

    def test_the_whole_year_is_the_months_added_up(self):
        """``YTD Loan Loss`` is the twelve monthly columns summed, which is
        also ``YTD P&L Charge`` − ``YTD Int. Adj``. cif 52285's first three
        months: 2,236,031.00, −3,371.33, −472,387.00."""
        months = [(2284088.4710941273, 48057.46999999999),
                  (42588.40000000037, 45959.73),
                  (-424043.0700000003, 48343.929999999986)]
        by_month = sum(loan_loss.monthly_loss(*pair) for pair in months)
        in_one_go = loan_loss.monthly_loss(
            sum(pair[0] for pair in months), sum(pair[1] for pair in months))
        self.assertAlmostEqual(by_month, in_one_go, places=6)
        self.assertAlmostEqual(by_month, 1760272.671094127, places=6)


class WhoTheCustomerBelongsToTests(SimpleTestCase):
    """The only place the two sides can differ, and the reason to say so out
    loud rather than present a per-RM figure as settled."""

    def test_the_workbooks_own_markers_are_not_people(self):
        for label in ("Unmanaged", "unmanaged", "#N/A", "#VALUE!",
                      "Grand Total", "", None):
            with self.subTest(repr(label)):
                self.assertFalse(loan_loss.is_an_rm(label))

    def test_a_sales_code_is_a_person_whether_or_not_it_has_letters(self):
        """``rm_summary`` carries both: 92 labels are a full code and 15 are
        the digits alone."""
        for label in ("AKL3116", "LJB1656", "YO3927", "3914", "4072"):
            with self.subTest(label):
                self.assertTrue(loan_loss.is_an_rm(label))

    def test_special_assets_must_never_reach_a_card(self):
        """19,929,220.94 of the example's year sits on the literal text
        ``Unmanaged``, chiefly SPECIAL ASSETS - 7.7m on one customer in
        January alone. Attributing that to whoever happens to be nearest
        would put a fifth of a branch's provision on one person."""
        self.assertFalse(loan_loss.is_an_rm("Unmanaged"))
        self.assertIn("unmanaged", loan_loss.NOT_AN_RM)


class TheCardScoresItTheRightWayRoundTests(SimpleTestCase):
    def test_the_line_is_smaller_is_better(self):
        """A provision is a cost. Scoring it like a sales target would reward
        the RM with the worst book on the list."""
        for code in ("loan_loss", "reduce_p_l_provisions_nil_provisions_loan_loss",
                     "reduce_p_l_provisions_nill_provisions_loan_loss"):
            with self.subTest(code):
                self.assertIn(code, SOURCES)
                self.assertFalse(SOURCES[code].higher_is_better)
                # It is READ now, not derived. The charge used to be inferred
                # from the income components as max(0, -loss); it is a column
                # on the IFRS movement book - pl_charge - and that is the
                # figure finance recognise. The income calculation keeps its
                # own internal "loan_loss", which is why the key differs.
                self.assertEqual(SOURCES[code].actual_key, "loan_loss_charge")

    def test_half_the_allowed_provision_scores_full_marks(self):
        self.assertAlmostEqual(score_for(50, 100, False), 1.2)
        self.assertAlmostEqual(score_for(100, 100, False), 1.0)
        self.assertAlmostEqual(score_for(200, 100, False), 0.5)

    def test_a_net_release_is_nil_provisions_and_not_a_negative(self):
        """The line is titled "Nil provisions" on most cards. A year that ends
        in a net release is the best outcome the line has, which is what the
        Commercial_trade card does - a release of 3,094,882 scores 1.2."""
        self.assertAlmostEqual(score_for(0.0, 100, False), 1.2)


class TheFormulaIsStillInTheQueryTests(SimpleTestCase):
    """A guard, not a unit test.

    The measure lives in SQL in ``services/portfolio_service.py``, and the
    card reads whatever that returns. If somebody simplifies the expression -
    drops the interest adjustment, or the COALESCE, or the negation - every
    Loan Loss line on every card moves and nothing else here would notice.
    """

    SERVICE = (pathlib.Path(__file__).resolve().parents[2]
               / "services" / "portfolio_service.py")

    def test_the_service_file_is_where_this_expects_it(self):
        self.assertTrue(self.SERVICE.exists(), f"{self.SERVICE} is missing")

    def test_the_charge_less_the_adjustment_is_still_what_is_summed(self):
        import re

        text = self.SERVICE.read_text(encoding="utf-8")
        # Some of the four statements alias the table, so the expression is
        # written both as ``pl_charge`` and as ``l.pl_charge``.
        found = re.findall(
            r"-SUM\(COALESCE\((?:\w+\.)?pl_charge, 0\) "
            r"- COALESCE\((?:\w+\.)?int_adj, 0\)\)", text)
        self.assertTrue(
            found,
            "the loan-loss expression has changed. It must stay the "
            "workbook's own arithmetic: P&L charge less interest adjustment, "
            "negated because this query returns income categories.")
        # Five statements carry it - the customer list, the customer revenue
        # read, the RM revenue read the card's ACTUAL uses, the top-customers
        # read, and rm_loan_loss, which reads the prior year because that is
        # what the card's TARGET is built on - and they have to agree with
        # each other.
        self.assertEqual(
            len(found), 5,
            "the loan-loss expression appears in a different number of "
            "statements than it did. If one was added, it must carry the "
            "same arithmetic; if one was dropped, something stopped "
            "reporting a provision.")

    def test_the_source_table_is_the_ifrs_movement(self):
        text = self.SERVICE.read_text(encoding="utf-8")
        self.assertIn("loans_mom_ifrs_movement", text)
        # The year filter, without which the line would be since inception.
        self.assertIn("cust_code_strategy", text)


class TheTargetComesFromThePersonsOwnPriorYearTests(SimpleTestCase):
    """The Loan Loss line used to have no target at all, and the card blamed a
    missing DMC column for it.

    That was the wrong conclusion. The target was never a DMC column: all four
    cards that carry the line with numbers on it derive it from the person's
    OWN prior-year provision, times a rate the role sets. These check the
    arithmetic against those four cards to the cent.
    """

    #: (card, prior year, this year's target, the rate that gets you there)
    CARDS = [
        ("Commercial", -9_245_965.63506646, -7_396_772.508053169, 0.80),
        ("Commercial_trade", -20_053_060.48668547, -16_042_448.389348377, 0.80),
        ("Ultimate_RM", -4_537_193.861367692, -1_512_397.9537892307, 1 / 3),
        ("Personal_Banking", -5_031_576.707000633, -5_702_453.601267383,
         1 + 0.670876894266751 / 5.031576707000633),
    ]

    def test_the_rate_on_the_prior_year_is_the_years_target(self):
        for card, prior, stated, rate in self.CARDS:
            with self.subTest(card):
                self.assertAlmostEqual(prior * rate, stated, places=2)

    def test_the_seeded_rates_are_the_ones_the_cards_state(self):
        from importlib import import_module

        module = import_module(
            "apps.staff_management.migrations.0036_loan_loss_target_rate")
        rates = module.RATES
        self.assertAlmostEqual(rates["commercial_rm"], 0.80)
        self.assertAlmostEqual(rates["commercial_rm_trade"], 0.80)
        self.assertAlmostEqual(rates["ultimate_rm"], 1 / 3, places=6)
        self.assertAlmostEqual(rates["pb_rm"], 1.1333, places=4)
        self.assertEqual(module.BASE, "last_year_loan_loss")

    def test_no_rate_is_invented_for_a_card_that_states_none(self):
        """Business Banking, Diaspora and Mortgage Business carry no numbered
        Loan Loss line among the eight cards. A rate borrowed from a
        neighbouring role would be somebody's bonus."""
        from importlib import import_module

        module = import_module(
            "apps.staff_management.migrations.0036_loan_loss_target_rate")
        for role in ("sme_rm", "sme_arm", "sme_bbc", "diaspora_rm",
                     "diaspora_arm", "mortgage_business_arm"):
            with self.subTest(role):
                self.assertNotIn(role, module.RATES)

    def test_the_branch_tables_column_is_not_the_persons_target(self):
        """``target_loan_provisions`` DOES exist - on the BRANCH table, one row
        per branch. Handing an RM the whole branch's allowance would be an
        order of magnitude too loose, and because this line is scored
        smaller-is-better the error flatters: it shows as full marks."""
        from .models import BranchEmployeeDmcData, BranchFinalEmployeeDmcData

        per_person = {f.column for f in BranchEmployeeDmcData._meta.fields}
        per_branch = {f.column for f in BranchFinalEmployeeDmcData._meta.fields}
        self.assertNotIn("target_loan_provisions", per_person)
        self.assertIn("target_loan_provisions", per_branch)


class ParIsTheGradedBookTests(SimpleTestCase):
    """PAR is non-performing gross over total gross, on the IFRS book.

    It used to be arrears over book out of ``loans`` - a different measure
    wearing the same name. The IFRS movement book carries the grade per loan
    per month, which is what the business means by portfolio at risk.

    Which grades count was confirmed on 2026-10-21: "SUBSTD, DOUBTFUL and
    LOSS only". The choice is not cosmetic. The book carries seven grades,
    and counting everything that is not NORMAL gives a bank-wide PAR of
    30.62% for September 2026 against a card threshold of 2.5%.
    """

    def test_only_three_grades_are_at_risk(self):
        from .live_scorecard import AT_RISK_GRADES

        self.assertEqual(tuple(AT_RISK_GRADES),
                         ("SUBSTD", "DOUBTFUL", "LOSS"))
        for not_at_risk in ("NORMAL", "WATCH", "AUCTION SHORTFALLS", "N_A"):
            self.assertNotIn(not_at_risk, AT_RISK_GRADES)

    def test_par_is_smaller_is_better_against_a_threshold(self):
        from .live_scorecard import SOURCES

        par = SOURCES["par"]
        self.assertEqual(par.actual_key, "par")
        self.assertFalse(par.higher_is_better)
        self.assertTrue(par.threshold)
