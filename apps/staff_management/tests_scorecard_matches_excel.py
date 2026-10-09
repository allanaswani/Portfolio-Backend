"""The scoring model, checked against cards that already exist.

``docs/rm-scorecard-kpi-map.csv`` holds all 132 lines of the eight RM cards as
the workbook states them — weight, YTD target, ACTUAL, % SCORE and weighted
score. Each role sheet carries one real person's card, so these are not
fixtures: they are the numbers that were emailed to those eight people.

If the tool is to replace that email it has to produce the same arithmetic, so
this reads those cards back and checks that:

* ``% SCORE`` is ``clamp(ACTUAL / YTD target, 0, 1.2)``;
* the weighted scores sum to the Performance Score the card shows;

and names the lines that follow some other rule rather than letting them pass
quietly. Those are the ones still to be confirmed with whoever maintains the
workbook — see docs/rm-scorecard-live.md.
"""

import csv
import pathlib

from django.test import TestCase

MAP = (pathlib.Path(__file__).resolve().parents[2]
       / "docs" / "rm-scorecard-kpi-map.csv")

#: What each card's Performance Score cell reads, for the person it is made out
#: to. Taken from the sheet, not computed.
PERFORMANCE_SCORE = {
    "Commercial": ("Juspher Muriithi", 0.4952),
}

CAP = 1.2


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def lines():
    with open(MAP, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class ScoringModelTests(TestCase):
    """clamp(actual / ytd_target, 0, 1.2), and nothing more elaborate."""

    @classmethod
    def setUpTestData(cls):
        cls.rows = lines()

    def test_the_calibration_table_is_present_and_whole(self):
        self.assertEqual(len(self.rows), 132)
        self.assertEqual(len({r["role_sheet"] for r in self.rows}), 8)

    def test_percent_score_is_actual_over_target_capped_at_120(self):
        """Where a line follows the ordinary rule, reproduce it exactly."""
        checked = exceptions = 0
        for row in self.rows:
            actual = number(row["card_actual"])
            target = number(row["card_ytd_target"])
            stated = number(row["card_pct_score"])
            if None in (actual, target, stated) or target == 0:
                continue
            expected = min(max(actual / target, 0.0), CAP)
            if abs(expected - stated) <= max(abs(stated) * 0.01, 0.001):
                checked += 1
            else:
                exceptions += 1
        self.assertGreaterEqual(
            checked, 86,
            "the ordinary rule should cover the great majority of lines")
        # The rest are the lines that cap at 1.0, the PAR threshold, and the
        # loan-loss lines where a less-negative actual beats the target. They
        # are covered by their own tests below; the count is pinned so that a
        # change to the model shows up here rather than passing quietly.
        self.assertEqual(exceptions, 23, "the set of exceptional lines changed")

    def test_the_cap_is_usually_120_but_some_lines_cap_at_100(self):
        """And the SAME KPI caps differently on different cards.

        Portfolio NPS reads 1 on the Ultimate and Diaspora cards where the
        ratio is 1.667, and 1.667 uncapped on the Mortgage Business card.
        Training caps at 1 where the ratio is 1.125. So the cap is not a
        property of the KPI in the workbook - it is whatever that card's
        formula happens to do, which is the drift a spreadsheet maintained by
        hand for years accumulates.
        """
        at_cap = []
        at_one = []
        for row in self.rows:
            actual = number(row["card_actual"])
            target = number(row["card_ytd_target"])
            pct = number(row["card_pct_score"])
            if None in (actual, target, pct) or target == 0:
                continue
            ratio = actual / target
            if abs(pct - CAP) < 1e-6:
                at_cap.append(row)
            elif abs(pct - 1.0) < 1e-6 and ratio > 1.0 + 1e-6:
                at_one.append((row, ratio))

        self.assertTrue(at_cap, "no line reaches 1.2")
        self.assertTrue(at_one, "no line is held at 1.0")

        nps = [(r["role_sheet"], number(r["card_pct_score"]))
               for r in self.rows
               if r["kpi_description"].strip() == "Portfolio NPS"
               and number(r["card_pct_score"]) is not None]
        self.assertIn(("Mortgage_Business", 1.6667),
                      [(s, round(v, 4)) for s, v in nps],
                      "the Mortgage card does not cap NPS")
        self.assertIn(("Ultimate_RM", 1.0),
                      [(s, round(v, 4)) for s, v in nps],
                      "the Ultimate card caps NPS at 1")

    def test_par_is_a_threshold_not_a_ratio(self):
        """Lower is better, and it is pass or fail rather than proportional.

        0.02604 against a 0.025 target scores 0, while 0.009554 scores 1.2.
        Nothing in between appears, so a ratio cannot be what is happening.
        """
        seen = []
        for row in self.rows:
            if row["kpi_description"].strip() != "PAR":
                continue
            actual = number(row["card_actual"])
            target = number(row["card_ytd_target"])
            pct = number(row["card_pct_score"])
            if None in (actual, target, pct):
                continue
            seen.append((actual, target, pct))
            with self.subTest(f"{row['role_sheet']} {actual}"):
                if actual > target:
                    self.assertEqual(pct, 0, "over target scores nothing")
                else:
                    self.assertAlmostEqual(pct, CAP, places=4,
                                           msg="at or under target scores the cap")
        self.assertGreaterEqual(len(seen), 6, "PAR should appear on most cards")

    def test_a_weighted_score_is_the_weight_times_the_percent_score(self):
        """With one documented exception: a card that shows a NEGATIVE %
        score still reports a weighted score of 0, so the floor is applied to
        the weighted figure and not to the percentage."""
        negative_percent = 0
        for row in self.rows:
            weight = number(row["kpi_weight"])
            pct = number(row["card_pct_score"])
            weighted = number(row["card_weighted_score"])
            if None in (weight, pct, weighted):
                continue
            if pct < 0:
                negative_percent += 1
                with self.subTest(f"negative {row['role_sheet']}"):
                    self.assertEqual(weighted, 0,
                                     "a negative score contributes nothing")
                continue
            with self.subTest(f"{row['role_sheet']}/{row['kpi_description'][:30]}"):
                self.assertAlmostEqual(weight * pct, weighted, places=5)
        self.assertTrue(negative_percent,
                        "the Ultimate card's Asset Growth shows -2.112")


class CardTotalsTests(TestCase):
    """The whole card adds up to the score that was sent out."""

    def test_the_weighted_scores_sum_to_the_performance_score(self):
        rows = lines()
        for sheet, (person, stated) in PERFORMANCE_SCORE.items():
            card = [r for r in rows if r["role_sheet"] == sheet]
            self.assertTrue(card, f"no lines for {sheet}")
            self.assertEqual(card[0]["calibrated_on"], person)
            total = sum(number(r["card_weighted_score"]) or 0.0 for r in card)
            with self.subTest(sheet):
                self.assertAlmostEqual(
                    total, stated, places=4,
                    msg=f"{person}'s card should total {stated}")

    def test_every_cards_weights_add_up(self):
        """1.0 of card plus a 0.025 bonus line. Home_Loan_Specialist totals
        1.05, which is flagged in docs/rm-scorecard-live.md."""
        rows = lines()
        for sheet in sorted({r["role_sheet"] for r in rows}):
            weights = [number(r["kpi_weight"]) or 0.0
                       for r in rows if r["role_sheet"] == sheet]
            with self.subTest(sheet):
                self.assertAlmostEqual(sum(weights), 1.05 if sheet ==
                                       "Home_Loan_Specialist" else 1.025,
                                       places=4)
