"""The tool's scoring, checked line by line against the cards the desk sends.

``docs/rm-scorecard-kpi-map.csv`` carries, for every line of the eight Q3 2026
role cards, the target the card states, the actual it states and the percentage
score it awards. That makes it possible to ask the only question that matters
before anybody signs one of these: **does this tool give the same answer the
spreadsheet gave?**

For 88 of the 109 lines that state all three, it does, exactly.

The remaining 21 are listed here one by one, with why. None of them is a case
of this tool getting a rule wrong. They are places where **the eight cards
disagree with each other** — the same measure is capped at 1.0 on one card and
left to run to 1.667 on another — plus PAR, which is a pass/fail threshold
rather than a ratio. Where the manual process has no single answer, this tool
applies one rule to everybody, and this file is the record of exactly where
that lands differently, so the difference is a decision somebody took and can
revisit rather than a surprise on somebody's bonus.
"""

import csv
import pathlib

from django.test import SimpleTestCase

from .live_scorecard import SOURCES, score_for

MAP = (pathlib.Path(__file__).resolve().parents[2]
       / "docs" / "rm-scorecard-kpi-map.csv")

#: (role sheet, measure of success) -> why this tool differs from that card.
#: Every entry names the card it came off, because "the card" is eight
#: different documents and they do not agree.
KNOWN_DIFFERENCES = {
    # ── PAR is a threshold, not a ratio ──────────────────────────────────
    # 2.5% or under scores full marks, over it scores nothing: seven cards,
    # seven consistent pass/fail outcomes, and no middle value anywhere. It is
    # also the one line whose target is nowhere on the DMC roster (the roster
    # carries an NPL amount, not a PAR percentage), so this tool leaves it
    # unscored rather than scoring a percentage against a shilling value.
    ("Business_Banking", "PAR"): "pass/fail threshold, not scored here",
    ("Personal_Banking", "PAR"): "pass/fail threshold, not scored here",
    ("Ultimate_RM", "PAR"): "pass/fail threshold, not scored here",
    ("Diaspora", "PAR"): "pass/fail threshold, not scored here",
    ("Commercial", "PAR"): "pass/fail threshold, not scored here",
    ("Commercial_trade", "PAR"): "pass/fail threshold, not scored here",
    ("Mortgage_Business", "PAR"): "pass/fail threshold, not scored here",

    # ── Capped at 1.0 on some cards, 1.2 on others ───────────────────────
    ("Business_Banking", "Training"): "capped at 1.0 on this card",
    ("Commercial_trade", "Training"): "capped at 1.0 on this card",
    ("Business_Banking", "Leave magement"): "capped at 1.0 on this card",
    ("Diaspora", "Leave magement"): "capped at 1.0 on this card",
    ("Personal_Banking", "Portfolio Coverage (engagement)"):
        "capped at 1.0 on this card",
    ("Ultimate_RM", "Portfolio NPS"): "capped at 1.0 on this card",
    ("Diaspora", "Portfolio NPS"): "capped at 1.0 on this card",
    # The same measure, uncapped, on a different card. This is the clearest
    # evidence that there is no single manual rule to reproduce.
    ("Mortgage_Business", "Portfolio NPS"):
        "NOT capped on this card - scores 1.667 where two other cards cap the "
        "same measure at 1.0",
    ("Commercial", "Loan Loss"):
        "capped at 1.0 on this card, where Commercial_trade caps the same "
        "measure at 1.2",

    # ── Smaller-is-better lines this tool does not score ─────────────────
    ("Mortgage_Business", "TAT (Loan)"):
        "turnaround days, measured outside the warehouse",
    ("Mortgage_Business", "Errors"):
        "application errors, measured outside the warehouse",
    ("Diaspora", "Audit"): "audit score, measured outside the warehouse",

    # ── Two genuine judgement calls, both deliberate ─────────────────────
    ("Ultimate_RM", "Asset Growth"):
        "this card lets a shrunken book score -211%. A negative score on a "
        "0-120% scale cannot be explained to the person carrying it, and no "
        "other card has one, so this tool floors at 0 and the shortfall shows "
        "as the zero it is",
    ("Personal_Banking", "Reduce P&L provisions / Nill provisions (Loan Loss)"):
        "1.4% apart. This card's YTD targets are hand-entered at 6/12 of the "
        "year where the other seven are at 8/12, so its stated target and its "
        "stated score are not consistent with each other",
}


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _lines():
    with MAP.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            target = _number(row["card_ytd_target"])
            actual = _number(row["card_actual"])
            stated = _number(row["card_pct_score"])
            if target in (None, 0) or actual is None or stated is None:
                continue
            yield row, target, actual, stated


class CardCalibrationTests(SimpleTestCase):
    """Reads the recorded cards only — no database, no fixtures."""

    def test_the_map_is_there(self):
        self.assertTrue(MAP.exists(), f"{MAP} is missing")

    def test_every_line_either_reproduces_or_is_a_recorded_difference(self):
        """The test that stops a scoring change going out unnoticed.

        Change the rule and this fails on the lines it moved, which is the
        point: the figures are somebody's bonus.
        """
        unexplained = []
        for row, target, actual, stated in _lines():
            key = (row["role_sheet"], row["kpi_description"])
            mine = score_for(actual, target, True)
            if abs(mine - stated) < 0.005:
                self.assertNotIn(
                    key, KNOWN_DIFFERENCES,
                    f"{key} is listed as a difference but now reproduces - "
                    f"remove it from KNOWN_DIFFERENCES")
                continue
            if key not in KNOWN_DIFFERENCES:
                unexplained.append(
                    f"{row['role_sheet']} / {row['kpi_description']}: "
                    f"card says {stated:.4f}, this tool says {mine:.4f} "
                    f"(target {target:,.0f}, actual {actual:,.0f})")
        self.assertEqual(unexplained, [], "\n".join(unexplained))

    def test_most_of_the_cards_reproduce_exactly(self):
        """A guard on the headline claim. If a change drops this, the claim
        made to the business about this tool stops being true."""
        reproduced = sum(
            1 for _, target, actual, stated in _lines()
            if abs(score_for(actual, target, True) - stated) < 0.005)
        self.assertGreaterEqual(reproduced, 88)

    def test_a_negative_target_is_scored_by_distance_not_by_ratio(self):
        """One Personal Banking card: an income contribution target of -73.3m
        against an actual of -37.2m, which the card scores 120%. A bare ratio
        reads 0.51 and would mark a line that beat its plan as a half-miss."""
        self.assertAlmostEqual(
            score_for(-37_206_824.7, -73_297_195.3, True), 1.2)

    def test_the_lines_the_cards_disagree_on_are_not_scored_live(self):
        """The capped-at-1.0 lines are all measures that live outside the
        warehouse, so the disagreement does not reach anybody's score today.
        If a future change starts scoring one of them, this fails and the cap
        has to be decided first."""
        outside = {
            "nps", "portfolio_nps", "portfolo_nps",
            "portfolio_coverage_engagement", "business_banking_training",
            "personal_banking_training", "leave_management", "audit",
            "errors", "tat_loan", "par",
        }
        for code in sorted(outside):
            with self.subTest(code):
                self.assertIn(code, SOURCES, f"{code} lost its Source entry")
                self.assertTrue(
                    SOURCES[code].pending,
                    f"{code} is now scored live, but the eight cards do not "
                    f"agree on how to cap it - decide the cap first")
