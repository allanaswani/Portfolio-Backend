"""Back-office Dormancy, CASA and VIC volume, measured as the desk measures them."""
import datetime
from unittest.mock import patch

from django.test import TestCase

from . import bo_branch_measures as bm
from . import workbook_cards as bo
from .tests_workbook_cards import book, template

NOV = datetime.date(2026, 11, 30)
TODAY = datetime.date(2026, 11, 12)


class DormancyTests(TestCase):
    def test_desk_months_are_the_sheet_over_the_december_base(self):
        # The template's own figures: Buru Buru January 0.2924, August 0.3314.
        rate, _ = bm.dormancy(datetime.date(2026, 1, 31), ("Buruburu",), TODAY)
        self.assertAlmostEqual(rate, 1417 / 4846)
        self.assertAlmostEqual(round(bm.dormancy(datetime.date(2026, 8, 31),
                                                 ("Buruburu",), TODAY)[0], 4), 0.3314)
        # A segment: the Ultimate CSO's August 0.1994.
        self.assertAlmostEqual(round(bm.dormancy(datetime.date(2026, 8, 31),
                                                 ("ULTIMATE", "Rehani"), TODAY)[0], 4), 0.1994)

    def test_the_month_being_lived_through_reads_the_deposit_book(self):
        with patch.object(bm, "_live_dormant", return_value={"buruburu": 1659}):
            rate, how = bm.dormancy(NOV, ("Buruburu",), TODAY)
            self.assertAlmostEqual(rate, 1659 / 4846)
            self.assertIn("deposit book", how)
            # A segment has no live count matched to the desk yet.
            self.assertEqual(bm.dormancy(NOV, ("DIASPORA",), TODAY), (None, ""))
            # A past month the sheet does not hold is not made up from today.
            self.assertEqual(bm.dormancy(datetime.date(2026, 12, 31), ("Buruburu",),
                                         datetime.date(2027, 1, 5)), (None, ""))

    def test_every_spelling_of_a_branch_finds_it(self):
        for name in ("SAMEER BUSINESS PARK BRANCH", "SameerPark", "Harambee",
                     "THIKA ROAD MALL-TRM BRANCH", "RiverRoad"):
            self.assertIsNotNone(bm.dormancy(datetime.date(2026, 3, 31), (name,), TODAY)[0],
                                 name)


class CardTests(TestCase):
    def _card(self, feed, sheet_values, **patches):
        scorecards = book()
        scorecards["cards"]["TELLER_SCORECARD"]["grid"][9][11] = feed
        bo.save_file("scorecards", scorecards)
        bo.save_file("actuals", template({
            feed: {"Bob Waigwa": sheet_values},
            "Training_hours": {"Bob Waigwa": [0, 6, 11, 15, 18, 22, 22, 22, 40]},
            "NPS": {"Bob Waigwa": [0.5] * 9}}))
        return bo.live_card("BCK3783", None, NOV)["perspectives"][0]["lines"][0]

    def test_casa_counts_funded_non_take_on_accounts(self):
        with patch.object(bm, "funded_accounts", return_value={"BCK3783": 27}):
            line = self._card("CASA", [0, 1, 2, 2, 3, 4, 12, 20, 22])
        self.assertEqual(line["ytd_actual"], 27)
        self.assertIn("take-on and staff accounts left out", line["as_at"])

    def test_dormancy_reads_the_branch_rate(self):
        with patch.object(bm, "_live_dormant", return_value={"kitengela": 1500}), \
                patch.object(bm.datetime, "date", wraps=datetime.date) as d:
            d.today.return_value = TODAY
            line = self._card("RE_activation", [0.43] * 9)
        self.assertAlmostEqual(line["ytd_actual"], 1500 / 3741)
        self.assertIn("deposit book", line["as_at"])


class VicVolumeTests(TestCase):
    def test_paid_vic_policies_are_counted(self):
        from . import bb_live_feeds

        policies = [("B", "JJN3756", "vic_non_life", 12000.0),
                    ("B", "JJN3756", "vic_non_life", 8000.0),
                    ("B", "JJN3756", "vic_life", 0.0),        # nothing paid
                    ("B", "JJN3756", "non_vic", 50000.0)]     # not VIC
        with patch.object(bb_live_feeds, "_banca_policies", return_value=iter(policies)):
            row = bb_live_feeds.banca_by_seller(2026, 11, 1000)["JJN3756"]
        self.assertEqual((row["vic_life_n"], row["vic_non_life_n"]), (0, 2))

    def test_bo_vic_lines_read_counts_not_premiums(self):
        from .live_scorecard import SOURCES

        self.assertEqual(SOURCES["bo_vic"].actual_key, "vic_count")
        self.assertEqual(SOURCES["bo_vic_life"].actual_key, "vic_life_count")
        self.assertEqual(SOURCES["bo_vic_non_life"].actual_key, "vic_non_life_count")


class WhizzOnboardingTests(TestCase):
    def setUp(self):
        from . import whizz_onboarding as wo

        self.wo = wo
        wo.save(2026, wo.counts([
            ("lmutwa", 2026, 1, 2), ("LMUTWA", 2026, 2, 6), ("lmutwa", 2025, 12, 9),
            ("Tabitha  Muita", 2026, 1, 1), ("Tabitha Muita", 2026, 3, 2),
            ("BCK3783", 2026, 10, 4)], 2026))

    def test_a_login_names_the_officer(self):
        officers = self.wo.counts([
            ("christopher.shema@hfcb.co.ke", 2026, 1, 3),
            ("Christopher.Shema@hfcb.co.ke", 2026, 2, 1),
            ("82", 2026, 1, 6)], 2026)
        self.assertEqual(officers, {"CHRISTOPHER SHEMA": {"1": 3, "2": 1}, "82": {"1": 6}})
        self.assertEqual(self.wo.mine(officers, names=("Christopher Shema",)),
                         ["CHRISTOPHER SHEMA"])
        # Three names on the template, two in the login: still him.
        self.assertEqual(self.wo.mine({"LIZA KAMUNYU": {}}, names=("Liza Wamaitha Kamunyu",)),
                         ["LIZA KAMUNYU"])
        # A bare id names nobody.
        self.assertEqual(self.wo.mine({"82": {}}, codes=("XX9999",), names=("Somebody",)), [])

    def test_last_years_rows_are_not_this_years_count(self):
        officers = self.wo._loaded(2026)["officers"]
        self.assertEqual(officers["LMUTWA"], {"1": 2, "2": 6})
        self.assertEqual(officers["TABITHA MUITA"], {"1": 1, "3": 2})

    def test_found_by_login_name_or_code_and_never_a_nought(self):
        self.assertEqual(self.wo.running_total(2026, 2, codes=("LM3280", "LMUTWA"))[0], 8)
        self.assertEqual(self.wo.running_total(2026, 3, names=("Tabitha Muita",))[0], 3)
        self.assertEqual(self.wo.running_total(2026, 10, codes=("BCK3783",))[0], 4)
        self.assertEqual(self.wo.running_total(2026, 10, codes=("XX9999",),
                                               names=("Somebody Else",)), (None, None))

    def test_the_card_reads_it(self):
        from unittest.mock import patch as _p
        _p.object(bo, "WHIZZ_ON_CARDS", True).start()
        self.addCleanup(_p.stopall)
        scorecards = book()
        scorecards["cards"]["TELLER_SCORECARD"]["grid"][9][11] = "Digital_Customers"
        bo.save_file("scorecards", scorecards)
        bo.save_file("actuals", template({
            "Digital_Customers": {"Bob Waigwa": [0, 0, 0, 0, 0, 0, 0, 1, 2]},
            "Training_hours": {"Bob Waigwa": [0, 6, 11, 15, 18, 22, 22, 22, 40]},
            "NPS": {"Bob Waigwa": [0.5] * 9}}))
        line = bo.live_card("BCK3783", None, NOV)["perspectives"][0]["lines"][0]
        self.assertEqual(line["ytd_actual"], 4)
        self.assertIn("Whizz", line["as_at"])

    def test_check_compares_with_the_desk(self):
        from io import StringIO

        from django.core.management import call_command

        bo.save_file("actuals", template({
            "Digital_Customers": {"Bob Waigwa": [0, 0, 0, 0, 0, 0, 0, 0, 0, 4]}}))
        out = StringIO()
        call_command("load_whizz_onboarding", "--check", "--no-load", "--year", "2026",
                     stdout=out)
        self.assertIn("NOT IN REPORT", out.getvalue())  # the fixture's code is "X"
