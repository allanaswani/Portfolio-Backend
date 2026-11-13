"""Scorecard workbooks are kept per year: next year's KPIs never re-score this
year's cards (13 Nov 2026)."""
import datetime
import importlib

from django.test import TestCase

from . import workbook_cards as bo
from .models import BoWorkbookFile
from .tests_workbook_cards import book, template

NOV_2026 = datetime.date(2026, 11, 30)
JAN_2027 = datetime.date(2027, 1, 31)


class PerYearStorageTests(TestCase):
    def test_each_year_keeps_its_own_file(self):
        bo.save_file("scorecards", {"v": 2026}, year=2026)
        bo.save_file("scorecards", {"v": 2027}, year=2027)
        self.assertEqual(bo.saved("scorecards", 2026), {"v": 2026})
        self.assertEqual(bo.saved("scorecards", 2027), {"v": 2027})
        self.assertEqual(bo.stored_years("scorecards"), [2026, 2027])
        self.assertEqual(set(BoWorkbookFile.objects.values_list("kind", flat=True)),
                         {"scorecards@2026", "scorecards@2027"})

    def test_a_year_not_loaded_reads_the_latest_before_it(self):
        bo.save_file("actuals", {"v": 2026}, year=2026)
        # January 2027, before the 2027 template is loaded: still 2026's.
        self.assertEqual(bo.saved("actuals", 2027), {"v": 2026})
        bo.save_file("actuals", {"v": 2028}, year=2028)
        self.assertEqual(bo.saved("actuals", 2027), {"v": 2026})
        # Nothing earlier: the earliest there is.
        self.assertEqual(bo.saved("actuals", 2025), {"v": 2026})
        self.assertIsNone(bo.saved("sales_actuals", 2026))

    def test_other_kinds_are_one_row_as_before(self):
        bo.save_file("proration", {"a": 1}, year=2027)
        self.assertEqual(bo.saved("proration"), {"a": 1})
        self.assertTrue(BoWorkbookFile.objects.filter(kind="proration").exists())

    def test_next_years_workbook_does_not_rescore_this_years_card(self):
        bo.save_file("scorecards", book(), year=2026)
        bo.save_file("actuals", template({
            "CASA": {"Bob Waigwa": [0, 1, 2, 2, 3, 4, 12, 20, 22]},
            "Training_hours": {"Bob Waigwa": [0, 6, 11, 15, 18, 22, 22, 22, 40]},
            "NPS": {"Bob Waigwa": [0.5] * 9}}), year=2026)
        before = bo.live_card("BCK3783", None, NOV_2026)
        # 2027's workbook re-weights the first line.
        changed = book()
        changed["cards"]["TELLER_SCORECARD"]["grid"][9][4] = 0.9
        bo.save_file("scorecards", changed, year=2027)
        after = bo.live_card("BCK3783", None, NOV_2026)
        weight = before["perspectives"][0]["lines"][0]["weight"]
        self.assertIsNotNone(weight)
        self.assertEqual(weight, after["perspectives"][0]["lines"][0]["weight"])
        # ...while 2027's cards read 2027's weight.
        self.assertEqual(bo.saved("scorecards", JAN_2027.year)["cards"]
                         ["TELLER_SCORECARD"]["grid"][9][4], 0.9)


class MigrationTests(TestCase):
    def test_files_loaded_before_are_2026s(self):
        from django.apps import apps

        BoWorkbookFile.objects.create(kind="sales_scorecards", payload={"v": 1})
        BoWorkbookFile.objects.create(kind="proration", payload={})
        module = importlib.import_module(
            "apps.staff_management.migrations.0067_workbook_file_per_year")
        module.to_years(apps, None)
        self.assertEqual(bo.saved("sales_scorecards", 2026), {"v": 1})
        self.assertTrue(BoWorkbookFile.objects.filter(kind="proration").exists())
