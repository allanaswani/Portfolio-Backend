"""One upload of the scorecard workbook loads everything in it.

The workbook has 47 sheets. The loader read ten of them - the role cards -
and ignored "Summary Allocation", which is a row per PERSON carrying their
own targets: 99 people across 24 measures, Direct Portfolio Contribution
among them for 90.

The reader for that sheet already existed, and so did an endpoint. Nothing in
the browser ever called it, so the cards said "no target is set" for a figure
sitting in a workbook somebody had already uploaded.
"""

import pathlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import BranchEmployeeDmcData
from .scorecard_automation.models import ScEmployeeKpiTarget, ScKpi

WORKBOOK = pathlib.Path(
    r"C:\Users\washingtone.amolo\Downloads"
    r"\Portfolio Management - Q3 2026_scorecards.xlsb")

UPLOAD = ("/staff_management/scorecard-automation/manual-figures/workbook/")


class TheAllocationSheetIsReadTests(TestCase):
    """Against the real workbook, where it is on this machine."""

    def setUp(self):
        if not WORKBOOK.exists():
            self.skipTest("the scorecard workbook is not on this machine")

        self.user = get_user_model().objects.create_user(
            username="wb_admin", password="x", is_superuser=True,
            is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, apply=False):
        with WORKBOOK.open("rb") as handle:
            return self.client.post(
                UPLOAD, {"file": handle, "apply": "true" if apply else "false",
                         "year": 2026}, format="multipart")

    def test_some_kpi_names_a_column_on_that_sheet(self):
        """Migration 0027 seeded these. Without one, the sheet is never
        read and the failure is silent."""
        named = ScKpi.objects.filter(is_active=True).exclude(
            allocation_column="")
        self.assertTrue(named.exists())
        self.assertTrue(
            named.filter(kpi_code="direct_portfolio_contribution").exists(),
            "Direct Portfolio Contribution should take a per-person target")

    def test_the_preview_reports_the_allocation_without_writing(self):
        res = self.post(apply=False)
        self.assertEqual(res.status_code, 200, res.data)
        allocation = res.data["report"]["allocation"]
        # 99 people where the role cards cover ten.
        self.assertGreater(allocation["people"], 50)
        self.assertGreater(allocation["targets"], 500)
        self.assertIn("direct_portfolio_contribution", allocation["by_kpi"])
        self.assertEqual(ScEmployeeKpiTarget.objects.count(), 0,
                         "a preview must write nothing")

    def test_applying_writes_the_per_person_targets(self):
        res = self.post(apply=True)
        self.assertEqual(res.status_code, 200, res.data)
        written = ScEmployeeKpiTarget.objects.filter(
            kpi_code="direct_portfolio_contribution", year=2026)
        self.assertGreater(written.count(), 50)
        # And the base beside it, which is what a rate target is applied to.
        self.assertTrue(written.exclude(base_value=None).exists())

    def test_the_target_reaches_somebodys_card(self):
        """The whole point: a line that said "no target is set" now has
        one, for somebody the role cards never covered."""
        from .live_scorecard import build_card

        self.post(apply=True)

        target = (ScEmployeeKpiTarget.objects
                  .filter(kpi_code="direct_portfolio_contribution", year=2026)
                  .exclude(kpi_target=None).first())
        self.assertIsNotNone(target)

        # Put that person on the roster so a card can be built for them.
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=1, staff_name="Allocated Person",
            sales_code=target.sales_code, staff_role="COMMERCIAL RM",
            staff_branch="H/Q", staff_unit="H/Q", active=1)

        card = build_card(target.sales_code)
        lines = {ln["kpi_code"]: ln
                 for group in card["perspectives"] for ln in group["lines"]}
        line = lines["direct_portfolio_contribution"]
        self.assertIsNotNone(line["annual_target"])
        self.assertAlmostEqual(float(line["annual_target"]),
                               float(target.kpi_target), places=2)
        self.assertIn("allocated", line["target_source"])

    def test_the_role_cards_still_load_beside_it(self):
        """The allocation is additional, not instead of."""
        res = self.post(apply=True)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertGreaterEqual(len(res.data["report"]["cards"]), 10)


class WhenTheSheetIsNotThereTests(TestCase):
    """A workbook without that sheet still loads its cards."""

    def test_a_missing_sheet_costs_its_own_section_only(self):
        from unittest.mock import patch

        from . import workbook_views

        request = type("R", (), {"data": {"year": "2026"}})()
        upload = type("U", (), {"seek": lambda self, n: None})()

        with patch.object(workbook_views, "_allocation_year",
                          return_value=2026):
            with patch("apps.staff_management.scorecard_ingest."
                       "read_allocation",
                       side_effect=RuntimeError("no such sheet")):
                summary, year = workbook_views._read_allocation(
                    request, upload)

        self.assertEqual(summary["targets"], 0)
        self.assertEqual(year, 2026)
        self.assertIn("no such sheet", summary["why"])


class TheTargetIsTheYearNotTheGrowthTests(TestCase):
    """Against the real workbook, and against the printed cards beside it.

    ``Summary Allocation`` lays every measure out in three columns - a base,
    a growth, and the two added. The reader took the GROWTH and stored the
    base beside it, unused, because the card reads ``kpi_target`` and nothing
    else. Abed Lelgo's Direct Portfolio Contribution would have loaded as
    33.5m rather than 201m: understated by his whole opening book, which
    makes everybody look like they are three times over target.
    """

    def setUp(self):
        if not WORKBOOK.exists():
            self.skipTest("the scorecard workbook is not on this machine")

    def read(self):
        from .scorecard_ingest import read_allocation

        definitions = list(ScKpi.objects.filter(is_active=True)
                           .exclude(allocation_column=""))
        rows, _warnings = read_allocation(str(WORKBOOK), definitions)
        return {(r["sales_code"].upper(), r["kpi_code"]): r for r in rows}

    def test_abeds_contribution_is_the_year_not_the_increment(self):
        row = self.read()[("AKL3116", "direct_portfolio_contribution")]
        self.assertAlmostEqual(row["base_value"], 167_574_340.56, places=1)
        # base + growth, which is the sheet's own third column.
        self.assertAlmostEqual(row["kpi_target"], 201_089_208.68, places=1)

    def test_loan_loss_comes_out_negative_as_the_card_prints_it(self):
        """It is held positive on that sheet. ``negate`` was only ever
        consulted by the actuals reader; applying it here reproduces the
        printed card to the cent."""
        row = self.read()[("JM4191", "loan_loss")]
        self.assertLess(row["kpi_target"], 0)
        self.assertAlmostEqual(row["kpi_target"], -7_396_772.51, places=0)

    def test_a_column_with_no_base_is_left_as_the_years_figure(self):
        row = self.read()[("JM4191", "net_loan_disbursments")]
        self.assertIsNone(row["base_value"])
        self.assertAlmostEqual(row["kpi_target"], 780_000_000.0, places=0)

    def test_it_reproduces_the_printed_cards_far_more_often_than_before(self):
        """24 of the 40 lines that appear on both a printed card and the
        allocation sheet now agree to the shilling. Before the fix it was
        the handful with no base column. The rest are lines where the two
        sheets carry genuinely different numbers - a revision, not a
        formula."""
        from . import scorecard_workbook as w

        allocation = self.read()
        cards, _report = w.read_workbook(str(WORKBOOK))
        lookup = w.kpi_lookup()

        exact = compared = 0
        for card in cards:
            code = (card["sales_code"] or "").upper()
            if not code:
                continue
            role, slugs = max(
                lookup.items(),
                key=lambda kv: sum(1 for ln in card["lines"]
                                   if ln["slug"] in kv[1]))
            for line in card["lines"]:
                kpi = slugs.get(line["slug"])
                row = allocation.get((code, kpi))
                if row is None or line["annual_target"] is None:
                    continue
                compared += 1
                if abs(row["kpi_target"] - line["annual_target"]) < 1:
                    exact += 1

        self.assertGreater(compared, 30, "nothing was compared")
        self.assertGreaterEqual(
            exact, 20,
            f"only {exact} of {compared} lines reproduce the printed card")
