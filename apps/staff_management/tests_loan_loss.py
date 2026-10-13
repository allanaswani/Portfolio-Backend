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
                self.assertEqual(SOURCES[code].actual_key, "loan_loss")

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
        # Four statements carry it - the customer list, the customer revenue
        # read, the RM revenue read the card itself uses, and the
        # top-customers read - and they have to agree with each other.
        self.assertEqual(
            len(found), 4,
            "the loan-loss expression appears in a different number of "
            "statements than it did. If one was added, it must carry the "
            "same arithmetic; if one was dropped, something stopped "
            "reporting a provision.")

    def test_the_source_table_is_the_ifrs_movement(self):
        text = self.SERVICE.read_text(encoding="utf-8")
        self.assertIn("loans_mom_ifrs_movement", text)
        # The year filter, without which the line would be since inception.
        self.assertIn("cust_code_strategy", text)
