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

    def _proven_card(self, reading, proven=True):
        from unittest.mock import patch

        from . import scheme_live_feeds as f
        from .workbook_cards import save_file

        record = self._card("George Ochieng", "SCHEMES_RM", 6,
                            "scheme_commercial_disbursement", 300.0, "GO3528")
        if proven:
            save_file(f.STORE_KIND, {"scheme_commercial_disbursement": {"live": True}})
        with patch.object(f, "live_value", return_value=reading), \
                patch.object(sc, "_warehouse",
                             side_effect=lambda c, n, keys, a: {k: None for k in keys}):
            return sc.live_payload(record, datetime.date(2026, 10, 31))

    @staticmethod
    def _lines(card):
        return {ln["kpi_code"]: ln for p in card["perspectives"] for ln in p["lines"]}

    def test_an_open_month_reads_the_proven_line_and_carries_the_desks_others(self):
        card = self._proven_card(500_000_000.0)
        lines = self._lines(card)
        line = lines["scheme_commercial_disbursement"]
        self.assertEqual(line["ytd_actual"], 500_000_000.0)
        self.assertEqual(line["as_at"], "live, as at 31 Oct 2026")
        # 750m a year, ten months: 625m.
        self.assertAlmostEqual(line["ytd_target"], 625_000_000.0)
        self.assertAlmostEqual(line["score"], 0.8)
        # The desk's June sign-ups, against June's target (15 x 6/12 = 7.5).
        signups = lines["scheme_sign_ups"]
        self.assertEqual(signups["ytd_actual"], 6.0)
        self.assertEqual(signups["as_at"], "the desk's latest figure (Jun 2026)")
        self.assertAlmostEqual(signups["ytd_target"], 7.5)
        # Everything else has no figure: waiting, not counted.
        self.assertEqual(card["pending_lines"], 14)
        self.assertEqual(lines["scheme_training"]["pending_label"], "Waiting for data")
        self.assertAlmostEqual(card["performance_score"], 0.8 * 0.2 + 0.8 * 0.2)

    def test_a_reading_below_the_desks_figure_keeps_the_desks(self):
        line = self._lines(self._proven_card(10.0))["scheme_commercial_disbursement"]
        self.assertEqual(line["ytd_actual"], 300.0)
        self.assertEqual(line["as_at"], "the desk's latest figure (Jun 2026)")

    def test_nothing_proven_carries_the_desks_figure(self):
        line = self._lines(self._proven_card(None, proven=False))[
            "scheme_commercial_disbursement"]
        self.assertEqual(line["ytd_actual"], 300.0)
        self.assertIn("(Jun 2026)", line["as_at"])

    def test_the_stored_month_itself_is_never_replaced(self):
        from . import scheme_live_feeds as f
        from .workbook_cards import save_file

        record = self._card("George Ochieng", "SCHEMES_RM", 6,
                            "scheme_commercial_disbursement", 300.0, "GO3528")
        save_file(f.STORE_KIND, {"scheme_commercial_disbursement": {"live": True}})
        self.assertIsNone(sc.live_payload(record, datetime.date(2026, 6, 30)))


class CorrectedCardTests(TestCase):
    """20 Nov 2026, option A: the signed June cards stay as the desk scored
    them; from July each line measures what its name says."""

    RMS = [name for _c, name, role, _j in ROSTER if role == "SCHEMES RM"]

    def setUp(self):
        actuals = june_actuals()
        cards = []
        for code, name, role, joined in ROSTER:
            sheet = sc.ROLE_SHEETS[sc._fold(role)]
            cards.append((sc.RosterRow(code, name, role, sheet, joined),
                          sc.compute_card(sc.CARDS[sheet], name, 6, joined, actuals)))
        sc.store(cards, datetime.date(2026, 6, 1), loaded_by="test")

    def _live(self, code, figures, as_at=datetime.date(2026, 10, 31)):
        """``figures``: {(code, key): value} the warehouse gives."""
        from unittest.mock import patch

        def warehouse(c, name, keys, at):
            out = {}
            for k in keys:
                value = figures.get((c, k))
                out[k] = (None if value is None else
                          {"value": value, "as_at": at, "as_at_label": f"{k} to {at:%b %Y}",
                           "problem": None})
            return out

        with patch.object(sc, "_warehouse", side_effect=warehouse):
            return sc.live_payload(sc.stored_for(code, as_at=as_at), as_at)

    @staticmethod
    def _lines(card):
        return {ln["kpi_code"]: ln for p in card["perspectives"] for ln in p["lines"]}

    def test_june_stays_exactly_as_signed(self):
        self.assertIs(sc.card_for("SCHEMES_RM", 2026, 6), sc.CARDS["SCHEMES_RM"])
        self.assertIs(sc.card_for("SCHEMES_RM", 2026, 7), sc.CORRECTED["SCHEMES_RM"])
        self.assertIsNone(sc.live_payload(sc.stored_for("DK4239"), datetime.date(2026, 6, 30)))

    def test_each_corrected_line_reads_what_it_says(self):
        rm = {ln.kpi: ln for ln in sc.CORRECTED["SCHEMES_RM"].lines}
        self.assertEqual(rm["scheme_value_of_property"].actual, ("warehouse", "property_value"))
        self.assertEqual(rm["scheme_number_of_property"].actual, ("warehouse", "property_units"))
        self.assertEqual(rm["scheme_vic_life"].actual, ("warehouse", "vic_life_count"))
        self.assertEqual(rm["scheme_vic_non_life"].actual, ("warehouse", "vic_non_life_count"))
        self.assertEqual(rm["scheme_deposit_growth"].actual, ("warehouse", "deposit_growth"))
        # Weights, targets and proration are the workbook's own.
        self.assertEqual([ln.weight for ln in sc.CORRECTED["SCHEMES_RM"].lines],
                         [ln.weight for ln in sc.CARDS["SCHEMES_RM"].lines])
        admin = {ln.kpi: ln for ln in sc.CORRECTED["PROJECT_ADMIN"].lines}
        self.assertEqual(admin["scheme_fid"].score, ("pass", 0.03))
        self.assertEqual(admin["scheme_audit"].score, ("audit_band",))
        head = {ln.kpi: ln for ln in sc.CORRECTED["HOD_SCHEMES"].lines}
        self.assertEqual(head["scheme_deposit_growth"].actual, ("team", "deposit_growth"))
        self.assertEqual(head["scheme_rm_productivity"].actual[0], "team_avg")

    def test_the_heads_productivity_is_the_rms_average(self):
        actuals = june_actuals()
        result = sc.compute_card(sc.CORRECTED["HOD_SCHEMES"], "Nicodemus Ngila", 6, 0,
                                 actuals, team=self.RMS)
        line = next(ln for ln in result["lines"] if ln["kpi"] == "scheme_rm_productivity")
        found = [actuals.cell("Scheme_RM_Productivity", 3, 9, n, 6) for n in self.RMS]
        found = [v for v in found if isinstance(v, float)]
        self.assertTrue(found)
        self.assertAlmostEqual(line["actual"], sum(found) / len(found))
        self.assertGreater(line["actual"], 0)

    def test_an_rms_october_reads_the_warehouse_and_carries_the_desks_returns(self):
        card = self._live("DK4239", {("DK4239", "training_hours"): 30.0,
                                     ("DK4239", "property_value"): 8_200_000.0})
        lines = self._lines(card)
        training = lines["scheme_training"]
        self.assertEqual(training["ytd_actual"], 30.0)
        self.assertEqual(training["as_at"], "live - training_hours to Oct 2026")
        # 40 a year, joined in month 2: (10 - 2) / 12 of 40.
        self.assertAlmostEqual(training["ytd_target"], 40 * 8 / 12)
        value = lines["scheme_value_of_property"]
        self.assertEqual(value["ytd_actual"], 8_200_000.0)
        # The desk's June audit score, scored against June's band.
        self.assertIn("(Jun 2026)", lines["scheme_audit"]["as_at"])
        # No figure for leave or VIC: waiting, not counted.
        self.assertEqual(lines["scheme_leave"]["pending_label"], "Waiting for data")
        self.assertIsNone(lines["scheme_leave"]["weighted_score"])
        self.assertEqual(card["period"]["label"], "October 2026")
        self.assertIn("2026-10", card["months_loaded"])

    def test_the_heads_deposit_growth_adds_up_the_rms(self):
        codes = [c for c, _n, role, _j in ROSTER if role == "SCHEMES RM"]
        figures = {(c, "deposit_growth"): 100.0 * (i + 1) for i, c in enumerate(codes)}
        lines = self._lines(self._live("NN3533", figures))
        deposits = lines["scheme_deposit_growth"]
        self.assertEqual(deposits["ytd_actual"], 1000.0)
        self.assertIn("the 4 Scheme RMs' figures added together", deposits["as_at"])
        # The template's own faults are not carried into October.
        self.assertEqual(lines["scheme_strategic_initiatives"]["pending_label"],
                         "Waiting for data")
        self.assertEqual(lines["scheme_rm_productivity"]["pending_label"],
                         "Waiting for data")

    def test_a_team_short_of_one_rm_waits_and_names_them(self):
        codes = [c for c, _n, role, _j in ROSTER if role == "SCHEMES RM"]
        figures = {(c, "deposit_growth"): 1.0 for c in codes[1:]}
        deposits = self._lines(self._live("NN3533", figures))["scheme_deposit_growth"]
        self.assertIsNone(deposits["ytd_actual"])
        self.assertIn("George Ochieng", deposits["pending"])


class MonthsWithNothingInThemTests(TestCase):
    """A stored month the desk gave no figures must not hide the real card."""

    def _card(self, month, signups, total):
        from .models import SchemeScorecard

        lines = [{"kpi": "scheme_revenue", "perspective": "Scheme Business", "description": "r",
                  "weight": 0.05, "fy_target": 1, "ytd_target": 1, "actual": 235903623.28,
                  "score": 0.67, "weighted": 0.03, "counted": False, "note": ""},
                 {"kpi": "scheme_sign_ups", "perspective": "Sales", "description": "s",
                  "weight": 0.1, "fy_target": 45, "ytd_target": 33, "actual": signups,
                  "score": 0.0, "weighted": 0.0, "counted": True, "note": ""}]
        return SchemeScorecard.objects.create(
            sales_code="NN3533", month=datetime.date(2026, month, 1),
            staff_name="Nicodemus Ngila", sheet="HOD_SCHEMES", joined=0,
            card={"lines": lines}, total=total)

    def setUp(self):
        self.june = self._card(6, 19.0, 0.5675717)
        self.september = self._card(9, 0.0, 0.1814538)

    def test_a_month_with_only_the_typed_revenue_has_no_desk_figures(self):
        self.assertFalse(sc.has_desk_figures(self.september))
        self.assertTrue(sc.has_desk_figures(self.june))

    def test_the_real_june_card_shows_instead(self):
        self.assertEqual(sc.stored_for("NN3533").month, datetime.date(2026, 6, 1))
        record = sc.stored_for("NN3533", as_at=datetime.date(2026, 10, 31))
        self.assertAlmostEqual(record.total, 0.5675717)

    def test_the_card_says_which_month_it_is(self):
        asked = datetime.date(2026, 10, 31)
        card = sc.card_payload(sc.stored_for("NN3533", as_at=asked), asked=asked)
        self.assertEqual(card["period"]["label"], "June 2026")
        self.assertIn("this is June 2026", card["showing_other_month"])

    def test_the_month_picker_leaves_it_out(self):
        self.assertEqual(sc.months_loaded("NN3533"), ["2026-06"])

    def test_nothing_real_says_nothing_is_loaded(self):
        self.june.delete()
        self.assertIsNone(sc.stored_for("NN3533"))
