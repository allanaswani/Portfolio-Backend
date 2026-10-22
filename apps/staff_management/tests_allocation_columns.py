"""Which allocation column each income line grows, pinned to the cards.

This file exists because this one decision has been changed three times -
0047 moved four codes onto one column on the evidence of a single card, 0051
moved one of them back, and 0055 moved two more - and each time the only
record of WHY was a migration docstring that nothing checks.

So the evidence is here as a table, read off the workbook's own role sheets
and the allocation row of the person each sheet is made out to:

    Portfolio Management - Q3 2026_scorecards.xlsb

``TOTAL INCOME CONTRIBUTION`` spans four columns - 17 last year's TARGET, 18
last year's ACTUAL, 19 the Growth (20% of column 18 on every one of the 88
rows), 20 the two added. The loader reads the growth RATE off column 18 and
applies it to whichever base the KPI names, so the base column alone decides
the target: base x 1.2.

If somebody moves one of these again, this fails and names the card that
disagrees, which is the part that was missing.
"""

from django.test import TestCase

from .scorecard_automation.models import ScKpi

GROUP = "TOTAL INCOME CONTRIBUTION"
LAST_YEARS_TARGET = f"{GROUP}/2024.0"
LAST_YEARS_ACTUAL = f"{GROUP}/2024 (Income+(FTP-LoanLoss))"

#: kpi_code -> (role sheet, person, the base column proved, card 2026 FY,
#:              col 17, col 18)
#: Every figure read off the workbook, not computed here.
EVIDENCE = {
    "operating_profit": (
        "Business_Banking", "Charles Muchiri", LAST_YEARS_ACTUAL,
        6_245_102.21, 4_301_254.93, 5_204_251.84),
    "income_contribution_portfolio_ntb": (
        "Ultimate_RM", "Faith Muthinja", LAST_YEARS_ACTUAL,
        11_542_155.22, -44_474_105.67, 9_618_462.685358651),
    "direct_portfolio_contribution": (
        "Commercial", "Juspher Muriithi", LAST_YEARS_TARGET,
        277_856_513.63, 231_547_094.69, 88_324_015.96),
}

#: Proved by sign and magnitude rather than to the cent - see 0055. Column 17
#: is positive where his card is negative, so it cannot be the base whatever
#: the exact arithmetic.
BY_SIGN = {
    "income_contribution": (
        "Personal_Banking", "Vincent Ogare", LAST_YEARS_ACTUAL,
        -146_594_390.60, 15_394_657.91, -169_147_373.77),
}

#: The growth the sheet applies, on all 88 rows of Summary Allocation.
RATE = 1.2


class TheIncomeBaseIsTheOneTheCardProvesTests(TestCase):

    def base_for(self, code):
        kpi = ScKpi.objects.filter(kpi_code=code).first()
        self.assertIsNotNone(kpi, f"{code} is not seeded")
        return (kpi.allocation_base_column or "").strip()

    def test_each_income_line_grows_the_column_its_card_proves(self):
        wrong = []
        for code, (sheet, who, column, _, _, _) in EVIDENCE.items():
            got = self.base_for(code)
            if got != column:
                wrong.append(f"{code}: grows {got!r}, but {who}'s {sheet} "
                             f"card proves {column!r}")
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_the_proved_column_times_the_growth_is_the_printed_target(self):
        """The arithmetic behind the table, so a wrong figure in it is caught
        rather than quietly justifying the wrong column."""
        for code, (sheet, who, column, card, col17, col18) in EVIDENCE.items():
            base = col17 if column == LAST_YEARS_TARGET else col18
            with self.subTest(code=code):
                self.assertAlmostEqual(
                    base * RATE, card, delta=0.01,
                    msg=f"{who}'s {sheet} card says {card:,.2f} and the "
                        f"column this test claims gives {base * RATE:,.2f}")

    def test_the_other_column_does_not_reproduce_the_card(self):
        """Without this the table would pass if BOTH columns happened to
        work, which would make it evidence of nothing."""
        for code, (sheet, who, column, card, col17, col18) in EVIDENCE.items():
            other = col18 if column == LAST_YEARS_TARGET else col17
            with self.subTest(code=code):
                self.assertNotAlmostEqual(
                    other * RATE, card, delta=0.01,
                    msg=f"both columns reproduce {who}'s card, so it cannot "
                        f"tell them apart")

    def test_income_contribution_is_on_the_column_with_the_right_sign(self):
        for code, (sheet, who, column, card, col17, col18) in BY_SIGN.items():
            with self.subTest(code=code):
                self.assertEqual(self.base_for(code), column)
                # The whole of the argument: one column has the card's sign
                # and order of magnitude, the other has neither.
                self.assertLess(card, 0)
                self.assertGreater(col17, 0, "col 17 was the seeded base and "
                                             "is positive where the card is "
                                             "negative")
                self.assertLess(col18, 0)

    def test_direct_portfolio_contribution_still_grows_last_years_target(self):
        """The one that is NOT on the actual. Pinned so a future tidy-up does
        not make all four consistent and wrong."""
        self.assertEqual(
            self.base_for("direct_portfolio_contribution"), LAST_YEARS_TARGET)

    def test_no_income_line_is_left_without_a_base(self):
        """A base column is what makes the growth a target rather than an
        increment - without one the loader stores 20% of last year as the
        whole year's target."""
        missing = sorted(
            code for code in list(EVIDENCE) + list(BY_SIGN)
            if not self.base_for(code))
        self.assertEqual(missing, [])
