"""Where a printed role sheet disagrees with the allocation sheet.

Four lines were carried for a while as "unresolved - the tool does not
reproduce the printed card". They are resolved, and none of them was a fault
in this tool: in each one the printed role sheet applies a factor of its own
that the allocation sheet does not, and the sheets do not agree with each
other either.

The allocation sheet is the authoritative one - one row per person, one rule
for everybody, 20% growth on all 88 rows. The printed role sheets are built
from it by hand, and that is where the factors creep in. So the tool follows
the allocation sheet, and every place that lands differently from a printed
card is written down here with both numbers, because a difference somebody
chose is a decision that can be revisited and a difference nobody noticed is
a surprise on somebody's bonus.

All figures below are read off ``Portfolio Management - Q3 2026_scorecards.xlsb``
- the ``Summary Allocation`` sheet and the role sheet named in each case.

Nothing here asserts against the database. These are the workbook's own
numbers, checked against each other, so the record cannot quietly rot into
a claim that is no longer true of the file it describes.
"""

from django.test import SimpleTestCase

#: What the tool produces, from the allocation sheet, against what the
#: printed role sheet shows.
#:
#: (line, sheet, person, allocation figure, printed figure, factor, note)
DISAGREEMENTS = [
    (
        "Portfolio Management AUM", "Diaspora", "Edward Kosgei",
        388_367_161.76, 776_734_323.52, 2.0,
        "Starting AUM 194,183,580.88 plus AUMGrowth 194,183,580.88 is the "
        "allocation sheet's own '2026 AUM' column, 388,367,161.76. The "
        "Diaspora sheet takes that TOTAL as its '2025 FY' and grows it by "
        "100% a second time. The growth is applied twice.",
    ),
    (
        "VIC Premiums (life)", "Commercial", "Juspher Muriithi",
        6_111_588.66, 12_223_177.32, 2.0,
        "banca_life on the allocation row is 6,111,588.66. The Commercial "
        "sheet prints double it, which is banca_life PLUS banca_non_life - "
        "the group total - under the life line's name.",
    ),
    (
        "VIC Premiums (life)", "Personal_Banking", "Vincent Ogare",
        1_587_699.84, 1_058_466.56, 2 / 3,
        "The PB sheet prints the year's life target already sliced to eight "
        "months. The allocation column is the YEAR's figure, and this tool "
        "slices it per line to the date of the actual it is compared with.",
    ),
    (
        "VIC Premiums (life)", "Ultimate_RM", "Faith Muthinja",
        1_701_769.09, 709_070.46, 5 / 12,
        "The same again on the Ultimate sheet, but sliced to FIVE months "
        "rather than eight, on a card whose review period is the same "
        "Q3_Aug_26. The two sheets do not agree with each other.",
    ),
    (
        "Active Customers", "Personal_Banking", "Vincent Ogare",
        303.60, 286.73, None,
        "Both start from ACTIVE = 253 on the allocation row. The allocation "
        "grows it by 20%, as it grows every other line on all 88 rows; the "
        "PB sheet grows it by 13.333%, which is that 20% already sliced to "
        "eight months. The growth is pro-rated before the target is set, "
        "and then the target is pro-rated again.",
    ),
    (
        "Active Customers", "Ultimate_RM", "Faith Muthinja",
        98.40, 140.40, None,
        "The allocation row says ACTIVE = 82, so the year's target is 98.4. "
        "The Ultimate sheet starts from 117 instead. 117 is not on her "
        "allocation row at any column, so that sheet is reading a count "
        "from somewhere else.",
    ),
]

#: The growth the allocation sheet applies, on every one of its 88 rows.
ALLOCATION_GROWTH = 1.2


class TheSheetsDisagreeAndTheAllocationWinsTests(SimpleTestCase):

    def test_every_disagreement_states_both_numbers(self):
        """A record that names only one of the two is not a record."""
        for line, sheet, who, ours, printed, _, note in DISAGREEMENTS:
            with self.subTest(line=line, sheet=sheet):
                self.assertNotAlmostEqual(
                    ours, printed, delta=0.01,
                    msg=f"{line} on {sheet} is listed as a disagreement but "
                        f"the two figures are the same")
                self.assertTrue(note.strip(), "no reason recorded")

    def test_the_stated_factor_actually_relates_the_two(self):
        """So the explanation cannot drift away from the arithmetic."""
        for line, sheet, who, ours, printed, factor, _ in DISAGREEMENTS:
            if factor is None:
                continue
            with self.subTest(line=line, sheet=sheet):
                self.assertAlmostEqual(
                    ours * factor, printed, delta=0.02,
                    msg=f"{line} on {sheet}: {ours:,.2f} x {factor} is "
                        f"{ours * factor:,.2f}, not the printed "
                        f"{printed:,.2f}")

    def test_the_two_sheets_slice_the_same_line_differently(self):
        """The heart of it. Personal_Banking and Ultimate_RM print the same
        measure, for the same review period, at 8/12 and 5/12 of the year.
        No single rule reproduces both, which is why the tool applies its
        own to everybody."""
        by_sheet = {
            sheet: factor
            for line, sheet, _, _, _, factor, _ in DISAGREEMENTS
            if line == "VIC Premiums (life)" and factor is not None
        }
        self.assertAlmostEqual(by_sheet["Personal_Banking"], 2 / 3, places=6)
        self.assertAlmostEqual(by_sheet["Ultimate_RM"], 5 / 12, places=6)
        self.assertNotAlmostEqual(by_sheet["Personal_Banking"],
                                  by_sheet["Ultimate_RM"], places=3)

    def test_the_aum_difference_is_the_growth_applied_twice(self):
        """Not a rounding or a column choice - a doubling, which is what
        makes it safe to say the tool is right rather than merely different."""
        starting = 194_183_580.88
        growth = 194_183_580.88
        allocation_total = starting + growth
        self.assertAlmostEqual(allocation_total, 388_367_161.76, delta=0.01)
        # The Diaspora sheet's own "2025 FY" is that total, grown again.
        self.assertAlmostEqual(allocation_total * 2, 776_734_323.52,
                               delta=0.01)

    def test_the_allocation_growth_is_one_rate_for_everybody(self):
        """The reason the allocation sheet is the authoritative one: it does
        not vary per person. Every row on Summary Allocation grows by 20%."""
        self.assertAlmostEqual(ALLOCATION_GROWTH, 1.2, places=6)
        # Three people, three role sheets, one rate - read off the sheet.
        for base, target in ((8_798_657.048178162, 10_558_388.457813796),
                             (1_032_713.8818675963, 1_239_256.6582411155),
                             (9_618_462.685358651, 11_542_155.222430382)):
            with self.subTest(base=base):
                self.assertAlmostEqual(base * ALLOCATION_GROWTH, target,
                                       delta=0.01)
