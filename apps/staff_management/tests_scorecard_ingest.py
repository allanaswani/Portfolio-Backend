"""Reading the RM actuals workbook.

Every assertion here corresponds to something that was established by
reproducing a figure a real scorecard states, and that a plainer reader would
have got wrong:

* a month column is a YTD running total, so the ACTUAL is that cell and never a
  sum — on the real file, summing Jan–Aug for one VIC line gives 9,601,603
  against a true 2,076,987;
* a sheet can be several 18-column blocks wide, and the card picks one —
  Banca_Assurance_Income is six blocks, and the Commercial card's VIC line is
  block 4, where block 1 reads 2,410;
* some lines negate what the sheet stores — PL_Charge holds a loan loss
  positive and every card shows it negative.
"""

import datetime
import io
from dataclasses import dataclass

from django.test import TestCase

from .scorecard_ingest import read_actuals, read_allocation

AUG = datetime.date(2026, 8, 1)


@dataclass
class Kpi:
    """Just enough of ScKpi for the parser, which takes definitions rather
    than querying, so it can be tested without a database."""

    kpi_code: str
    actuals_sheet: str = ""
    actuals_block: int = None
    negate: bool = False
    not_configured_reason: str = ""


def workbook(sheets):
    """``{sheet: [row, ...]}`` -> an .xlsx in memory."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "actuals.xlsx"
    return buf


def block(code_rows, months=None, first_month=1):
    """One 18-column block: the header, then a row per person."""
    head = ["Staff PF-Number", "Staff Sales Code", "Staff - Name", "Role",
            "Branch", "Zone"]
    head += [datetime.datetime(2026 + (m - 1) // 12, (m - 1) % 12 + 1, 1)
             for m in range(first_month, first_month + 12)]
    out = [head]
    for code, values in code_rows:
        out.append([1, code, "A Person", "RM", "Branch", "Zone"] + list(values))
    return out


def side_by_side(*blocks):
    """Lay blocks out across the sheet with two blank columns between, which
    is how the real workbook spaces them."""
    width = max(len(b) for b in blocks)
    rows = []
    for i in range(width):
        row = []
        for n, b in enumerate(blocks):
            if n:
                row += ["", ""]
            row += list(b[i]) if i < len(b) else [""] * 18
        rows.append(row)
    return rows


class ActualsReaderTests(TestCase):
    def read(self, sheets, kpis, month=AUG):
        return read_actuals(workbook(sheets), month, kpis)

    # ── the cumulative rule ──────────────────────────────────────────────
    def test_the_actual_is_the_review_months_cell_not_a_sum(self):
        """The columns are running totals. This is the rule that, got wrong,
        overstates a real VIC line by 4.6x."""
        running = [0, 0, 0, 1_685_325, 1_685_325, 2_076_983, 2_076_983,
                   2_076_987, None, None, None, None]
        result = self.read(
            {"Banca": block([("JM4191", running)])},
            [Kpi("vic", actuals_sheet="Banca", actuals_block=1)])
        self.assertEqual(result.total, 1)
        self.assertEqual(result.rows[0].value, 2_076_987)
        self.assertNotEqual(result.rows[0].value, sum(v for v in running[:8]))

    def test_an_earlier_review_month_reads_that_months_cell(self):
        running = [10, 20, 30, 40, 50, 60, 70, 80, None, None, None, None]
        result = self.read(
            {"S": block([("A1", running)])},
            [Kpi("k", actuals_sheet="S", actuals_block=1)],
            month=datetime.date(2026, 3, 31))
        self.assertEqual(result.rows[0].value, 30, "March, not August")

    def test_the_month_is_matched_on_the_header_date_not_the_position(self):
        """A sheet that starts at February still reads August correctly."""
        values = list(range(1, 13))        # Feb=1 ... Jan(next)=12
        result = self.read(
            {"S": block([("A1", values)], first_month=2)},
            [Kpi("k", actuals_sheet="S", actuals_block=1)])
        self.assertEqual(result.rows[0].value, 7, "the column headed Aug 2026")

    # ── blocks ──────────────────────────────────────────────────────────
    def test_the_configured_block_is_the_one_read(self):
        b1 = block([("JM4191", [0] * 7 + [2_410] + [None] * 4)])
        b2 = block([("JM4191", [0] * 7 + [2_000_215] + [None] * 4)])
        b3 = block([("JM4191", [0] * 7 + [76_772] + [None] * 4)])
        b4 = block([("JM4191", [0] * 7 + [2_076_987] + [None] * 4)])
        sheet = side_by_side(b1, b2, b3, b4)
        for n, expected in ((1, 2_410), (2, 2_000_215), (3, 76_772),
                            (4, 2_076_987)):
            with self.subTest(block=n):
                result = self.read(
                    {"Banca": sheet},
                    [Kpi("vic", actuals_sheet="Banca", actuals_block=n)])
                self.assertEqual(result.rows[0].value, expected)

    def test_one_sheet_can_feed_several_kpis_from_different_blocks(self):
        """Which is how life, non-life and the total come off one sheet."""
        sheet = side_by_side(
            block([("A1", [0] * 7 + [100] + [None] * 4)]),
            block([("A1", [0] * 7 + [250] + [None] * 4)]))
        result = self.read(
            {"Banca": sheet},
            [Kpi("life", actuals_sheet="Banca", actuals_block=1),
             Kpi("non_life", actuals_sheet="Banca", actuals_block=2)])
        got = {r.kpi_code: r.value for r in result.rows}
        self.assertEqual(got, {"life": 100, "non_life": 250})

    def test_a_block_the_sheet_does_not_have_is_reported_not_guessed(self):
        result = self.read(
            {"S": block([("A1", [1] * 12)])},
            [Kpi("k", actuals_sheet="S", actuals_block=4)])
        self.assertEqual(result.total, 0)
        self.assertTrue(any("block 4" in u for u in result.unreadable),
                        result.unreadable)

    # ── sign ────────────────────────────────────────────────────────────
    def test_negate_flips_the_stored_sign(self):
        result = self.read(
            {"PL_Charge": block([("JM4191", [0] * 7 + [1_882_000] + [None] * 4)])},
            [Kpi("loan_loss", actuals_sheet="PL_Charge", actuals_block=1,
                 negate=True)])
        self.assertEqual(result.rows[0].value, -1_882_000)

    # ── what is NOT read ────────────────────────────────────────────────
    def test_a_blank_cell_is_not_a_zero(self):
        """A missing figure is a question for the desk, not a score of nought
        for the RM. The engine records it as a missing actual."""
        result = self.read(
            {"S": block([("A1", [None] * 12)])},
            [Kpi("k", actuals_sheet="S", actuals_block=1)])
        self.assertEqual(result.total, 0)

    def test_a_real_zero_is_read(self):
        result = self.read(
            {"S": block([("A1", [0] * 12)])},
            [Kpi("k", actuals_sheet="S", actuals_block=1)])
        self.assertEqual(result.rows[0].value, 0)

    def test_an_unconfigured_kpi_is_skipped_with_its_reason(self):
        result = self.read(
            {"S": block([("A1", [5] * 12)])},
            [Kpi("k", actuals_sheet="S", actuals_block=1,
                 not_configured_reason="block never established")])
        self.assertEqual(result.total, 0)
        self.assertTrue(any("block never established" in s
                            for s in result.skipped), result.skipped)

    def test_a_kpi_with_no_sheet_is_skipped(self):
        result = self.read({"S": block([("A1", [5] * 12)])}, [Kpi("k")])
        self.assertEqual(result.total, 0)
        self.assertTrue(result.skipped)

    def test_a_missing_sheet_is_reported(self):
        result = self.read(
            {"S": block([("A1", [1] * 12)])},
            [Kpi("k", actuals_sheet="Nowhere", actuals_block=1)])
        self.assertTrue(any("Nowhere" in u for u in result.unreadable))

    def test_the_sheet_name_is_matched_whatever_its_case(self):
        """The cards say Trade_Finance_Income; the sheet is
        Trade_Finance_income. An exact match would drop the line."""
        result = self.read(
            {"Trade_Finance_income": block([("A1", [0] * 7 + [121_000] + [None] * 4)])},
            [Kpi("trade", actuals_sheet="Trade_Finance_Income", actuals_block=1)])
        self.assertEqual(result.rows[0].value, 121_000)

    def test_every_person_on_the_sheet_is_read(self):
        result = self.read(
            {"S": block([("A1", [1] * 12), ("B2", [2] * 12), ("C3", [3] * 12)])},
            [Kpi("k", actuals_sheet="S", actuals_block=1)])
        self.assertEqual(result.total, 3)
        self.assertEqual(result.people, 3)


class AllocationReaderTests(TestCase):
    """The per-person targets, matched by column NAME so the sheet can grow."""

    def sheet(self):
        blank = [""] * 10
        group = ["", "", "", "", "", "", "DEPOSITS", "", "", ""]
        header = ["Branch", "SALES CODE", "Name", "Role", "BRANCH", "Count",
                  "deposit_base", "Deposit Growth", "Portfolio Deposits",
                  "New_Cust"]
        # Row 1 is a spacer in the real sheet; groups on row 2, headers on row 3.
        return [blank, group, header,
                ["Nanyuki", "AMN3416", "Anne", "SME BBC", "Upcountry", 338,
                 46_240_000, 38_400_000, 26_880_000, 12],
                ["Rongai", "BKA3327", "Benard", "SME BBC", "Nairobi", 261,
                 23_020_000, 38_400_000, 26_880_000, 8]]

    def test_targets_are_read_per_person_with_their_base(self):
        rows, warnings = read_allocation(workbook({"Summary Allocation": self.sheet()}))
        got = {(r["sales_code"], r["kpi_code"]): r for r in rows}
        deposits = got[("AMN3416", "deposit_growth_retail")]
        self.assertEqual(deposits["kpi_target"], 38_400_000)
        self.assertEqual(deposits["base_value"], 46_240_000,
                         "deposit_base is the card's 2025 FY")
        self.assertEqual(got[("BKA3327", "deposit_growth_retail")]["base_value"],
                         23_020_000, "each person carries their own base")

    def test_a_singly_named_column_is_found(self):
        rows, _ = read_allocation(workbook({"Summary Allocation": self.sheet()}))
        got = {(r["sales_code"], r["kpi_code"]): r["kpi_target"] for r in rows}
        self.assertEqual(got[("AMN3416", "new_customers")], 12)

    def test_a_column_the_sheet_lacks_is_reported_not_assumed_zero(self):
        """A target of zero would score every RM at nought or divide by
        nothing. Saying so is the only safe answer."""
        _, warnings = read_allocation(workbook({"Summary Allocation": self.sheet()}))
        self.assertTrue(any("asset_growth" in w for w in warnings), warnings)

    def test_a_missing_sheet_is_reported(self):
        rows, warnings = read_allocation(workbook({"Something else": self.sheet()}))
        self.assertEqual(rows, [])
        self.assertTrue(warnings)
