"""The Scheme scorecards reproduce what was signed - to the last digit.

``fixtures/scheme_actuals_2026_06.json`` is every cell the cards read from
``2026_Actuals_Scheme_Scorecards.xlsx`` (June 2026). The expected totals are the
template's own ``Monthly_Summ_2026`` June column, which is what went out.
"""

import datetime
import json
from pathlib import Path

from django.test import TestCase

from . import scheme_cards as sc

FIXTURE = Path(__file__).parent / "fixtures" / "scheme_actuals_2026_06.json"

#: The template's List sheet: (code, name, role, prorate_new).
ROSTER = [
    ("GO3528", "George Ochieng", "SCHEMES RM", 0),
    ("KN4028", "Kipkirui Norman", "SCHEMES RM", 0),
    ("DK4239", "Dennis Kimathi", "SCHEMES RM", 2),
    ("PK3816", "Phiedis Kyengo", "PROJECT ADMIN", 0),
    ("BJ3384", "Benedicto Juma", "SCHEMES ADMIN", 0),
    ("NN3533", "Nicodemus Ngila", "HEAD OF SCHEMES", 0),
    ("PMM3540", "Philip Manyengo", "SCHEMES RM", 0),
]

#: Monthly_Summ_2026, June - the signed figures.
SIGNED_JUNE = {
    "George Ochieng": 0.5998556527562399,
    "Kipkirui Norman": 0.598734695222285,
    "Dennis Kimathi": 0.7732390023772422,
    "Phiedis Kyengo": 0.6194991699505658,
    "Benedicto Juma": 0.6090879145393105,
    "Nicodemus Ngila": 0.5675717000160081,
    "Philip Manyengo": 0.2069047619047619,
}


def june_actuals():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheets = {name: {int(n): row for n, row in rows.items()}
              for name, rows in data["sheets"].items()}
    revenue = {int(m): v for m, v in data["revenue_2026"].items()}
    return sc.Actuals(sheets, revenue)


class SignedJuneTests(TestCase):

    def test_every_signed_total_is_reproduced_exactly(self):
        actuals = june_actuals()
        for code, name, role, joined in ROSTER:
            with self.subTest(name):
                card = sc.CARDS[sc.ROLE_SHEETS[sc._fold(role)]]
                total = sc.compute_card(card, name, 6, joined, actuals)["total"]
                # Exact, not approximate: this is the signed number.
                self.assertEqual(total, SIGNED_JUNE[name])

    def test_benedictos_card_moves_when_collections_is_loaded(self):
        """His signed 0.6091 is the card without the collections line; the
        template now has 0.9 typed there, and that card reads 0.6541."""
        card = sc.CARDS["SCHEMES_ADMIN"]
        total = sc.compute_card(
            card, "Benedicto Juma", 6, 0, june_actuals(),
            {"scheme_collections_timeliness": 0.9})["total"]
        self.assertEqual(total, 0.6540879145393105)

    def test_the_heads_revenue_is_scored_and_left_out_of_his_total(self):
        result = sc.compute_card(sc.CARDS["HOD_SCHEMES"], "Nicodemus Ngila",
                                 6, 0, june_actuals())
        revenue = result["lines"][0]
        self.assertEqual(revenue["kpi"], "scheme_revenue")
        self.assertFalse(revenue["counted"])
        self.assertGreater(revenue["weighted"], 0)
        self.assertAlmostEqual(result["weight"], 1.0, places=9)

    def test_revenue_is_summed_the_way_excel_sums_it(self):
        """Left to right. Python 3.12's sum() compensates and lands
        0.0000002 away from the 160,923,357.61999992 on the signed card."""
        self.assertEqual(june_actuals().revenue_ytd(6), 160923357.61999992)

    def test_a_name_the_block_does_not_hold_is_na(self):
        self.assertEqual(
            june_actuals().lookup("NPS", 3, 9, "Nobody Here", 6), sc.NA)


class StoredCardTests(TestCase):
    """Loaded, stored, and shown on the person's own card."""

    def setUp(self):
        actuals = june_actuals()
        cards = []
        for code, name, role, joined in ROSTER:
            sheet = sc.ROLE_SHEETS[sc._fold(role)]
            person = sc.RosterRow(code, name, role, sheet, joined)
            cards.append((person, sc.compute_card(
                sc.CARDS[sheet], name, 6, joined, actuals)))
        sc.store(cards, datetime.date(2026, 6, 1), loaded_by="test")

    def test_the_card_is_the_stored_one(self):
        from .live_scorecard import build_card, resolve_person

        self.assertEqual(resolve_person("DK4239").role_code, "scheme_rm")
        card = build_card("DK4239", as_at=datetime.date(2026, 6, 30))
        self.assertTrue(card["has_card"], card)
        self.assertTrue(card["scheme"])
        self.assertEqual(card["performance_score"],
                         round(SIGNED_JUNE["Dennis Kimathi"], 4))
        self.assertEqual(card["staff"]["role_code"], "scheme_rm")
        lines = [ln for p in card["perspectives"] for ln in p["lines"]]
        self.assertEqual(len(lines), len(sc.CARDS["SCHEMES_RM"].lines))

    def test_a_month_not_loaded_says_so(self):
        from .live_scorecard import build_card

        card = build_card("DK4239", as_at=datetime.date(2026, 5, 31))
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "scheme_month_not_loaded")

    def test_the_heads_card_marks_revenue_outside_the_total(self):
        from .live_scorecard import build_card

        card = build_card("NN3533", as_at=datetime.date(2026, 6, 30))
        revenue = next(ln for p in card["perspectives"] for ln in p["lines"]
                       if ln["kpi_code"] == "scheme_revenue")
        self.assertFalse(revenue["counted_in_total"])
        self.assertIn("Outside the card's total", revenue["diagnostic"])


class WrongMonthTests(TestCase):
    """June workbooks computed as September: every figure read as an empty
    cell, and Dennis Kimathi's 77.3% card showed 15%."""

    def test_a_month_the_workbook_does_not_hold_is_refused(self):
        actuals = june_actuals()
        names = [name for _c, name, _r, _j in ROSTER]
        held = sc.months_with_figures(actuals, names)
        self.assertIn(6, held)
        self.assertNotIn(9, held)
        # The header rows carry all twelve month dates; they must not count.
        self.assertNotIn(12, held)

    def test_dennis_in_september_would_have_been_the_15_percent_card(self):
        """What the refusal prevents, so the rule is not loosened later."""
        total = sc.compute_card(sc.CARDS["SCHEMES_RM"], "Dennis Kimathi", 9,
                                2, june_actuals())["total"]
        self.assertAlmostEqual(total, 0.15, places=9)


class EveryMonthTests(TestCase):
    """One load stores every month the workbook holds, so an admin can open
    any of them - and a month the desk only partly filled says so."""

    def test_june_is_still_exactly_as_signed_among_all_months(self):
        actuals = june_actuals()
        names = [name for _c, name, _r, _j in ROSTER]
        held = sorted(sc.months_with_figures(actuals, names))
        self.assertEqual(held[-1], 6)
        for code, name, role, joined in ROSTER:
            card = sc.CARDS[sc.ROLE_SHEETS[sc._fold(role)]]
            self.assertEqual(
                sc.compute_card(card, name, 6, joined, actuals)["total"],
                SIGNED_JUNE[name])

    def test_a_partly_filled_month_is_flagged_on_the_card(self):
        from .models import SchemeScorecard

        result = sc.compute_card(sc.CARDS["SCHEMES_RM"], "Dennis Kimathi", 1,
                                 2, june_actuals())
        empty = sum(1 for ln in result["lines"] if ln["empty"])
        self.assertGreater(empty, 0)
        record = SchemeScorecard(sales_code="DK4239", staff_name="Dennis",
                                 sheet="SCHEMES_RM",
                                 month=datetime.date(2026, 1, 1),
                                 card=result, total=result["total"])
        payload = sc.card_payload(record)
        self.assertIn(f"{empty} of 16 lines had no figure for January",
                      payload["coverage_note"])
        flagged = [ln for p in payload["perspectives"] for ln in p["lines"]
                   if ln["as_at"].startswith("no figure entered")]
        self.assertEqual(len(flagged), empty)

    def test_asking_for_a_month_not_loaded_says_which_month_it_shows(self):
        from .models import SchemeScorecard

        result = sc.compute_card(sc.CARDS["SCHEMES_RM"], "Dennis Kimathi", 6,
                                 2, june_actuals())
        record = SchemeScorecard(sales_code="DK4239", staff_name="Dennis",
                                 sheet="SCHEMES_RM",
                                 month=datetime.date(2026, 6, 1),
                                 card=result, total=result["total"])
        payload = sc.card_payload(record, asked=datetime.date(2026, 9, 30))
        self.assertIn("Nothing is loaded for September 2026",
                      payload["showing_other_month"])
        self.assertEqual(sc.card_payload(record, asked=datetime.date(
            2026, 6, 30))["showing_other_month"], "")


class SchemeLiveProofTests(TestCase):
    """Disbursements go live only by matching the desk, new customers included."""

    MAP = {"rows": [["1", "100", "DENNIS MUTEMBEI", 1], ["2", "200", "GEORGE OCHIENG", 1],
                    ["3", "900", "NON-SCHEME", 1], ["4", "900", "DENNIS MUTEMBEI", 1]]}
    #: Jan: (customer, employer code, rate, money). Feb adds a new customer on code 200.
    JAN = [("1", "100", 14.0, 100.0), ("2", "200", 14.0, 200.0), ("2", "200", 9.0, 50.0),
           ("3", "900", 14.0, 999.0)]
    FEB = [("5", "200", 14.0, 400.0)]

    def _card(self, name, sheet, month, kpi, actual, code):
        from .models import SchemeScorecard

        lines = [{"kpi": kpi, "perspective": "Disbursements", "description": "d", "weight": 0.2,
                  "fy_target": 750.0, "ytd_target": 62.5 * month, "actual": actual,
                  "score": 0.5, "weighted": 0.1, "counted": True, "note": "", "empty": False},
                 {"kpi": "scheme_sign_ups", "perspective": "Scheme Business", "description": "s",
                  "weight": 0.2, "fy_target": 15, "ytd_target": 15, "actual": 6.0, "score": 0.4,
                  "weighted": 0.08, "counted": True, "note": "", "empty": False}]
        return SchemeScorecard.objects.create(
            sales_code=code, month=datetime.date(2026, month, 1), staff_name=name, sheet=sheet,
            joined=0, card={"lines": lines}, total=0.18)

    def _desk(self, dennis=(100.0, 100.0), george=(200.0, 600.0)):
        for month in (1, 2):
            self._card("Dennis Kimathi", "SCHEMES_RM", month, "scheme_commercial_disbursement",
                       dennis[month - 1], "DK4239")
            self._card("George Ochieng", "SCHEMES_RM", month, "scheme_commercial_disbursement",
                       george[month - 1], "GO3528")

    def _prove(self, mapping=None):
        from unittest.mock import patch

        from . import scheme_live_feeds as f
        from .workbook_cards import save_file

        save_file(f.MAP_KIND, mapping or self.MAP)

        def diary(start, end, timeout):
            if start.month == 2:
                return self.FEB
            return self.JAN + (self.FEB if end >= datetime.date(2026, 3, 1) else [])

        log = []
        with patch.object(f, "_drawdowns", side_effect=diary):
            return f.probe(2026, 2, out=log.append), log

    def test_a_name_on_the_card_finds_the_extracts_rm(self):
        from . import scheme_live_feeds as f

        known = {"DENNIS MUTEMBEI": {}, "GEORGE OCHIENG": {}, "DSR": {}, "__all__": {}}
        self.assertEqual(f.rm_key("Dennis Kimathi", known), "DENNIS MUTEMBEI")
        self.assertIsNone(f.rm_key("Philip Manyengo", known))
        self.assertIsNone(f.rm_key("Dennis Other", {**known, "DENNIS TWO": {}}))

    def test_an_employer_code_that_meant_two_rms_places_nobody(self):
        from . import scheme_live_feeds as f

        customers, codes = f.build_map(self.MAP["rows"])
        self.assertNotIn("900", codes)
        self.assertEqual(codes["200"], "GEORGE OCHIENG")
        self.assertEqual(f.place("9", "900", customers, codes), None)
        self.assertEqual(f.place("4", "900", customers, codes), "DENNIS MUTEMBEI")

    def test_commercial_is_above_the_rate_and_non_scheme_is_out(self):
        from . import scheme_live_feeds as f

        figures = f.totals(self.JAN, f.build_map(self.MAP["rows"]))
        self.assertEqual(figures["GEORGE OCHIENG"], {"commercial": 200.0, "all": 250.0})
        self.assertNotIn("NON-SCHEME", figures)
        self.assertEqual(figures["__all__"]["all"], 350.0)

    def test_a_line_matching_every_month_and_new_customers_goes_live(self):
        self._desk()
        results, _ = self._prove()
        self.assertTrue(results["scheme_commercial_disbursement"]["live"])
        self.assertEqual(results["scheme_commercial_disbursement"]["match"], 1.0)

    def test_figures_that_differ_stay_on_the_desk(self):
        self._desk(george=(200.0, 777.0))
        results, log = self._prove()
        self.assertFalse(results["scheme_commercial_disbursement"]["live"])
        self.assertTrue(any("George Ochieng, month 2: desk 777" in x for x in log))

    def test_new_customers_being_missed_keeps_it_on_the_desk(self):
        """In-sample it all matches, but February's money is a customer on a code
        nobody had seen before February."""
        rows = [["1", "100", "DENNIS MUTEMBEI", 1], ["2", "200", "GEORGE OCHIENG", 1],
                ["5", "200X", "GEORGE OCHIENG", 2]]
        self.FEB = [("5", "200X", 14.0, 400.0)]
        self._desk()
        results, log = self._prove({"rows": rows})
        self.assertEqual(results["scheme_commercial_disbursement"]["match"], 1.0)
        self.assertFalse(results["scheme_commercial_disbursement"]["live"])
        self.assertTrue(any("new-customer test 0%" in x for x in log))

    def test_without_the_desks_list_it_says_what_to_do(self):
        from . import scheme_live_feeds as f

        log = []
        self.assertEqual(f.probe(2026, 2, out=log.append), {})
        self.assertIn("Load the Scheme template", log[0])

    def _proven_card(self, reading):
        from unittest.mock import patch

        from . import scheme_live_feeds as f
        from .workbook_cards import save_file

        record = self._card("George Ochieng", "SCHEMES_RM", 6,
                            "scheme_commercial_disbursement", 300.0, "GO3528")
        save_file(f.STORE_KIND, {"scheme_commercial_disbursement": {"live": True}})
        with patch.object(f, "live_value", return_value=reading):
            return sc.live_payload(record, datetime.date(2026, 10, 31))

    def test_an_open_month_reads_the_proven_line_and_says_which_others_are_the_desks(self):
        card = self._proven_card(500_000_000.0)
        lines = {ln["kpi_code"]: ln for p in card["perspectives"] for ln in p["lines"]}
        line = lines["scheme_commercial_disbursement"]
        self.assertEqual(line["ytd_actual"], 500_000_000.0)
        self.assertEqual(line["as_at"], "live, as at 31 Oct 2026")
        # 750m a year, ten months: 625m.
        self.assertAlmostEqual(line["ytd_target"], 625_000_000.0)
        self.assertAlmostEqual(line["score"], 0.8)
        self.assertEqual(lines["scheme_sign_ups"]["ytd_actual"], 6.0)
        self.assertIn("(Jun 2026)", lines["scheme_sign_ups"]["as_at"])
        self.assertIn("1 of 2 lines read today's figures", card["how_scored"])
        self.assertAlmostEqual(card["performance_score"], 0.18 - 0.1 + 0.8 * 0.2)

    def test_a_reading_below_the_desks_figure_leaves_the_stored_card(self):
        self.assertIsNone(self._proven_card(10.0))

    def test_nothing_proven_leaves_the_stored_card(self):
        record = self._card("George Ochieng", "SCHEMES_RM", 6,
                            "scheme_commercial_disbursement", 300.0, "GO3528")
        self.assertIsNone(sc.live_payload(record, datetime.date(2026, 10, 31)))

    def test_the_stored_month_itself_is_never_replaced(self):
        from . import scheme_live_feeds as f
        from .workbook_cards import save_file

        record = self._card("George Ochieng", "SCHEMES_RM", 6,
                            "scheme_commercial_disbursement", 300.0, "GO3528")
        save_file(f.STORE_KIND, {"scheme_commercial_disbursement": {"live": True}})
        self.assertIsNone(sc.live_payload(record, datetime.date(2026, 6, 30)))
