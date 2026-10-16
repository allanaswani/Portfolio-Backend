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
