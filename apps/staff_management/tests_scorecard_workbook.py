"""Reading the desk's scorecard workbook.

Written against ``Portfolio Management - Q3 2026_scorecards.xlsb``: eleven
role sheets, one named person's card on each, a feed key in column M, and a
``List`` sheet of 91 people.

``pyxlsb`` reads .xlsb and cannot write one, so there is no fixture workbook
here. What is tested instead is everything that decides what gets written -
the mapping, the three-way split, and the rules about who a figure belongs to
- by handing :func:`plan` the structure :func:`read_workbook` produces. The
reader itself was run against the real file, and the numbers in
``TheRealWorkbookTests`` are what it returned.
"""

import datetime

from django.test import TestCase

from . import scorecard_workbook as W
from .models import BranchEmployeeDmcData
from .scorecard_automation.models import (
    ScEmployeeKpiTarget, ScEmployeePerformanceActual,
)


def a_card(sheet="Commercial", name="Juspher Muriithi", code="JM4191",
           lines=()):
    return {
        "sheet": sheet, "staff_name": name, "title": "COMMERCIAL RM",
        "branch": "H/Q", "manager": "Floyd Mathias", "period": "Q3_Aug_26",
        "stated_score": 0.495, "sales_code": code,
        "manager_email": "floyd.mathias@hfcb.co.ke",
        "copy_email": "anna.amasinde@hfcb.co.ke",
        "lines": list(lines),
    }


def a_line(description, feed_key, actual=None, target=None, weight=0.05,
           ytd_target=None):
    return {
        "description": description, "measure": "As per assigned Target",
        "weight": weight, "prev_fy": None, "growth": None,
        "annual_target": target, "ytd_target": ytd_target, "actual": actual,
        "feed_key": feed_key, "slug": W.DESCRIPTION_ALIASES.get(
            W.slug(description), W.slug(description)),
    }


class SmallRulesTests(TestCase):
    def test_a_description_slugs_to_the_shape_of_a_kpi_code(self):
        self.assertEqual(W.slug("Banking covenant tracking should be in "
                                "Iapply"),
                         "banking_covenant_tracking_should_be_in_iapply")
        self.assertEqual(W.slug("Portfolio Coverage (engagement)"),
                         "portfolio_coverage_engagement")
        self.assertEqual(W.slug("  Trade   Income  "), "trade_income")

    def test_the_workbooks_percentage_strings_are_not_numbers(self):
        """The 2026 FY column holds '>80%' as a label on some cards. Read as
        a number it would become a target of 80."""
        self.assertIsNone(W._number(">80%"))
        self.assertIsNone(W._number(""))
        self.assertIsNone(W._number(None))
        self.assertEqual(W._number(0.8), 0.8)
        self.assertEqual(W._number("1,234.5"), 1234.5)

    def test_booleans_are_not_figures(self):
        """A stray TRUE in a numeric column would otherwise score as 1."""
        self.assertIsNone(W._number(True))

    def test_the_alias_table_is_short_and_aliases_what_it_claims(self):
        """Every entry is a place where two spellings of one measure should
        eventually be made to agree. A long table would mean this had become
        a substitute for that rather than a bridge to it."""
        self.assertLessEqual(len(W.DESCRIPTION_ALIASES), 5)
        self.assertEqual(
            W.DESCRIPTION_ALIASES["active_customers_2_months_active"],
            "active_customers_two_month")


class MappingTests(TestCase):
    """The mapping is built from the seeded descriptions at run time, not
    from a hand-written table beside them that would drift."""

    def test_it_is_built_from_what_is_seeded(self):
        lookup = W.kpi_lookup()
        self.assertIn("commercial_rm", lookup)
        commercial = lookup["commercial_rm"]
        self.assertEqual(commercial["banking_covenant_tracking_should_be_in_"
                                    "iapply"],
                         "banking_covenant_tracking_should_be_in_iapply")
        self.assertEqual(commercial["portfolio_coverage_engagement"],
                         "portfolio_coverage_engagement")

    def test_a_kpi_code_also_looks_itself_up(self):
        """So a sheet that carries the code rather than the wording still
        resolves."""
        lookup = W.kpi_lookup()
        self.assertEqual(lookup["commercial_rm"]["loan_loss"], "loan_loss")


class WhatGetsWrittenTests(TestCase):
    CODE = "JM4191"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4191, staff_name="Juspher Muriithi",
            sales_code=self.CODE, staff_role="COMMERCIAL RM",
            staff_branch="H/Q", staff_unit="H/Q", active=1)

    def test_a_line_the_platform_cannot_measure_is_written(self):
        """The whole point. Covenant tracking and account planning are counts
        somebody keeps, the workbook has them, and nothing else does."""
        cards = [a_card(lines=[
            a_line("Banking covenant tracking should be in Iapply",
                   "covenant_tracking", actual=2.0),
            a_line("Tooling and account planning all customers",
                   "tooling_n_account_planning", actual=3.0),
        ])]
        entries, report = W.plan(cards)
        written = {(e["kpi_code"], e["value"]) for e in entries}
        self.assertIn(
            ("banking_covenant_tracking_should_be_in_iapply", 2.0), written)
        self.assertIn(
            ("tooling_and_account_planning_all_customers", 3.0), written)
        self.assertEqual(report["unmapped"], [])

    def test_a_line_the_platform_measures_is_written_as_a_fallback(self):
        """A line the balance tables hold is still taken from the workbook -
        and is reported as sitting behind a live source.

        Refusing it sounded like the safe choice and was not: the card prefers
        its own measurement wherever it has one, so the loaded figure can only
        ever fill a blank, and refusing it left a dash on every line measured
        on a key the person does not have."""
        cards = [a_card(lines=[
            a_line("Grow Deposits", "Deposit_Growth_Retail",
                   actual=-11_367_780.96),
        ])]
        entries, report = W.plan(cards)
        self.assertEqual(
            [(e["kpi_code"], e["value"]) for e in entries
             if e["kind"] == "actual"],
            [("grow_deposits", -11_367_780.96)])
        self.assertEqual(report["behind_a_live_source"], 1)

    def test_a_target_the_dmc_load_has_no_column_for_is_written(self):
        """And it is the ANNUAL figure, not the year-to-date one beside it."""
        cards = [a_card(lines=[
            a_line("Loan Loss", "PL_Charge", target=-7_396_772.51,
                   ytd_target=-4_931_181.67),
        ])]
        entries, _ = W.plan(cards)
        self.assertIn(("target", "loan_loss", -7_396_772.51),
                      [(e["kind"], e["kpi_code"], e["value"])
                       for e in entries])
        self.assertNotIn(-4_931_181.67, [e["value"] for e in entries])

    def test_active_customers_resolves_through_the_alias(self):
        """The workbook says "(2 months active)", the seeded card says "(two
        Month)". Neither is wrong, and without the alias this line was
        reported as unmapped and the figure dropped."""
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4236, staff_name="Charles Muchiri",
            sales_code="CMM4236", staff_role="SME RM", staff_branch="Machakos",
            staff_unit="Machakos", active=1)
        cards = [a_card(sheet="Business_Banking", name="Charles Muchiri",
                        code="CMM4236", lines=[
                            a_line("Active Customers (2 months active)",
                                   "Active_Customers", actual=81.0)])]
        entries, report = W.plan(cards)
        self.assertEqual(report["unmapped"], [])
        self.assertIn(("active_customers", 81.0),
                      [(e["kpi_code"], e["value"]) for e in entries])

    def test_a_line_that_cannot_be_mapped_is_reported_not_guessed(self):
        """A guess would score somebody on the wrong line of their own
        card."""
        cards = [a_card(lines=[
            a_line("Something Nobody Has Seen", "mystery_feed", actual=7.0)])]
        entries, report = W.plan(cards)
        self.assertEqual(entries, [])
        self.assertEqual(len(report["unmapped"]), 1)
        self.assertEqual(report["unmapped"][0]["feed_key"], "mystery_feed")

    def test_a_card_with_no_sales_code_reaches_nobody_and_says_so(self):
        cards = [a_card(name="Michael Oyoo Odhiambo", code="")]
        entries, report = W.plan(cards)
        self.assertEqual(entries, [])
        self.assertEqual(len(report["no_person"]), 1)
        self.assertIn("List sheet", report["no_person"][0]["why"])

    def test_a_code_no_roster_knows_is_reported_differently(self):
        """Two different problems with two different owners: a gap in the
        workbook's List sheet, and a code this platform does not hold."""
        cards = [a_card(code="ZZ9999")]
        _, report = W.plan(cards)
        self.assertIn("no card on this platform",
                      report["no_person"][0]["why"])

    def test_a_blank_figure_writes_nothing(self):
        cards = [a_card(lines=[
            a_line("Banking covenant tracking should be in Iapply",
                   "covenant_tracking", actual=None)])]
        entries, _ = W.plan(cards)
        self.assertEqual(entries, [])


class SavingTests(TestCase):
    CODE = "JM4191"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4191, staff_name="Juspher Muriithi",
            sales_code=self.CODE, staff_role="COMMERCIAL RM",
            staff_branch="H/Q", staff_unit="H/Q", active=1)
        self.month = datetime.date(2026, 8, 1)

    def entries(self, value=2.0):
        return [{"kind": "actual", "sales_code": self.CODE,
                 "kpi_code": "banking_covenant_tracking_should_be_in_iapply",
                 "value": value, "sheet": "Commercial", "line": "x"},
                {"kind": "target", "sales_code": self.CODE,
                 "kpi_code": "loan_loss", "value": -4_931_181.67,
                 "sheet": "Commercial", "line": "y"}]

    def test_it_writes_both_kinds(self):
        written = W.save(self.entries(), who="test", month=self.month)
        self.assertEqual(written, {"actuals": 1, "targets": 1})
        self.assertEqual(ScEmployeePerformanceActual.objects.count(), 1)
        self.assertEqual(ScEmployeeKpiTarget.objects.count(), 1)

    def test_a_second_load_corrects_rather_than_duplicating(self):
        W.save(self.entries(2.0), who="test", month=self.month)
        W.save(self.entries(5.0), who="test", month=self.month)
        self.assertEqual(ScEmployeePerformanceActual.objects.count(), 1)
        self.assertEqual(
            float(ScEmployeePerformanceActual.objects.get().kpi_value), 5.0)


class TheRealWorkbookTests(TestCase):
    """What the reader returned from the real file, recorded so a change that
    moves it fails here rather than in somebody's card.

    Not a fixture test - pyxlsb cannot write an .xlsb - but the figures below
    came from running the reader against
    ``Portfolio Management - Q3 2026_scorecards.xlsb`` on 15 October 2026.
    """

    def test_the_sheets_that_carry_a_card_are_the_ones_we_read(self):
        for sheet in ("Business_Banking", "Personal_Banking", "Ultimate_RM",
                      "Diaspora", "Home_Loan_Specialist", "Mortgage_Business",
                      "Commercial", "Commercial_trade", "SNR_MGR_ULTIMATE",
                      "BDM_Mortgages"):
            self.assertIn(sheet, W.ROLE_SHEETS)

    def test_the_target_written_is_the_ANNUAL_one(self):
        """ScEmployeeKpiTarget holds a year's target and the card pro-rates
        it. Loading the workbook's YTD figure would have it pro-rated a
        second time: Business Banking's operating profit is 6,245,102 for the
        year and 4,163,401 to August, and loading the latter would have
        scored that person against 2.8m."""
        self.assertEqual(W.COL_ANNUAL_TARGET, 7)
        self.assertEqual(W.COL_YTD_TARGET, 8)
        self.assertLess(W.COL_ANNUAL_TARGET, W.COL_YTD_TARGET)

    def test_the_columns_are_where_the_workbook_puts_them(self):
        """Read off row 5 of a role sheet: COUNT | KPI | KPI Description |
        Measure of Success | Weight | 2025 FY | GROWTH | 2026 FY |
        YTD Target | ACTUAL | % SCORE | Weighted | feed key."""
        self.assertEqual(W.COL_DESCRIPTION, 2)
        self.assertEqual(W.COL_WEIGHT, 4)
        self.assertEqual(W.COL_YTD_TARGET, 8)
        self.assertEqual(W.COL_ACTUAL, 9)
        self.assertEqual(W.COL_FEED_KEY, 12)
        self.assertEqual(W.FIRST_LINE, 5)
