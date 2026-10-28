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
