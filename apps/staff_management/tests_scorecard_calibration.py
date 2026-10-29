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
    # PAR used to live here. It no longer does: the seven cards are unanimous
    # that it is a pass/fail threshold at 2.5%, so it is scored that way and
    # all seven now reproduce exactly. That is what this file is for - a
    # difference that turns out to be a rule gets implemented and removed.

    # ── Capped at 1.0 on some cards, 1.2 on others ───────────────────────
    # The two Training entries used to live here. They no longer do: the two
    # cards that score a training line above its target BOTH wrote 1.0, which
    # makes the cap a rule rather than a disagreement, so it is implemented
    # and they reproduce. That is what this file is for.
    ("Business_Banking", "Leave magement"): "capped at 1.0 on this card",
    ("Diaspora", "Leave magement"): "capped at 1.0 on this card",
    # -- The two customer-survey lines, now scored live -------------------
    # These are capped at 1.0 rather than 1.2 - see CX_CAP below for the
    # count. Three of the cards that scored one of these above target now
    # reproduce exactly (Personal_Banking coverage, Ultimate_RM and Diaspora
    # NPS), which is why they are no longer listed here. Three do not:
    ("Mortgage_Business", "Portfolio NPS"):
        "the only card that applied NO cap at all here - 1.0 against a 0.6 "
        "target scores 1.667, where three other cards cap the same measure "
        "at 1.0 and a fourth at 1.2",
    ("Personal_Banking", "NPS"):
        "capped at 1.2 on this card, where three cards cap the same measure "
        "at 1.0 - including the coverage line on THIS card, two lines above",
    ("Commercial", "Portfolio NPS"):
        "0.6667 against 0.6 scores 1.1111 on this card, uncapped. The only "
        "survey line anywhere between 1.0 and 1.2, and the one line a cap of "
        "1.0 costs - and it costs 0.6% of this card, a 5%-weighted line "
        "scoring 1.0 where the card gave it 1.1111",
    ("Commercial", "Loan Loss"):
        "capped at 1.0 on this card, where Commercial_trade caps the same "
        "measure at 1.2",

    # ── Smaller-is-better lines this tool does not score ─────────────────
    ("Mortgage_Business", "TAT (Loan)"):
        "the only card carrying this line, and it caps a zero-day turnaround "
        "at 1.0 where the same arithmetic gives 1.2 elsewhere. Zero days also "
        "means no applications, which this tool reports as no figure rather "
        "than as perfect performance",
    ("Mortgage_Business", "Errors"):
        "application errors, measured outside the warehouse",
    # ("Diaspora", "Audit") used to be here. It reproduces now: the audit
    # score is read from Internal Audit's branch return, scored
    # lower-is-better and capped at full marks, and 1.6337 against a target
    # of 1.65 gives the 1.0 the card states.

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


#: The lines that stop at full marks rather than running on to 120%. Keyed on
#: the cards own wording, because this file reads the cards and not the seeded
#: KPI codes.
#:
#: Two survey lines, training and the audit score. The survey pair is a
#: judgement call on a 6-to-5 count (see the test below); training is not -
#: both cards that score it above target wrote exactly 1.0 and none goes
#: higher anywhere - and the audit score has one calibration point which also
#: wrote exactly 1.0 for an actual that beat its target.
FULL_MARKS_LINES = {"nps", "portfolio nps", "portfolo nps",
                    "portfolio coverage (engagement)", "training", "audit"}

#: Lines where SMALLER is better. The audit score is a grade - "Annual audit
#: score of 1.65" means 1.65 or better, and better means smaller - and PAR is
#: a limit. Everything else on the cards is a quantity to grow.
LOWER_IS_BETTER_LINES = {"audit"}
#: Kept under its old name as well: the survey-cap test reads it by name.
CX_LINES = {"nps", "portfolio nps", "portfolo nps",
            "portfolio coverage (engagement)"}
CX_CAP = 1.0


def _rule(description):
    """(higher_is_better, threshold, cap) for one card line's own wording."""
    text = description.strip().lower()
    # PAR is the one line scored as a threshold rather than a ratio.
    if text == "par":
        return False, True, 1.2
    cap = CX_CAP if text in FULL_MARKS_LINES else 1.2
    return text not in LOWER_IS_BETTER_LINES, False, cap


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
            higher, threshold, cap = _rule(row["kpi_description"])
            mine = score_for(actual, target, higher, threshold=threshold,
                             cap=cap)
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
        reproduced = 0
        for row, target, actual, stated in _lines():
            higher, threshold, cap = _rule(row["kpi_description"])
            mine = score_for(actual, target, higher, threshold=threshold,
                             cap=cap)
            if abs(mine - stated) < 0.005:
                reproduced += 1
        self.assertGreaterEqual(
            reproduced, 99,
            "99 of the 109 card lines that state both a target and an actual")

    def test_par_is_pass_or_fail_at_two_and_a_half_percent(self):
        """Seven cards, seven consistent outcomes and no middle value: at or
        under 2.5% is full marks, over it is nothing. Scoring it in proportion
        would hand partial credit for a limit that was broken."""
        from .live_scorecard import SOURCES

        source = SOURCES["par"]
        self.assertTrue(source.threshold)
        self.assertFalse(source.higher_is_better)
        self.assertAlmostEqual(
            score_for(0.009554, 0.025, False, threshold=True), 1.2)
        self.assertAlmostEqual(
            score_for(0.0, 0.025, False, threshold=True), 1.2)
        self.assertAlmostEqual(
            score_for(0.026044, 0.025, False, threshold=True), 0.0,
            msg="just over the limit is still over it")
        self.assertAlmostEqual(
            score_for(0.4116, 0.025, False, threshold=True), 0.0)

    def test_a_negative_target_is_scored_by_distance_not_by_ratio(self):
        """One Personal Banking card: an income contribution target of -73.3m
        against an actual of -37.2m, which the card scores 120%. A bare ratio
        reads 0.51 and would mark a line that beat its plan as a half-miss."""
        self.assertAlmostEqual(
            score_for(-37_206_824.7, -73_297_195.3, True), 1.2)

    def test_the_lines_the_cards_disagree_on_are_not_scored_live(self):
        """The remaining capped-at-1.0 lines are measures that live outside the
        warehouse, so the disagreement does not reach anybody's score today.

        If a future change starts scoring one of them, this fails - on purpose.
        The cap has to be decided with the desk BEFORE the line goes live,
        which is exactly what happened with PAR: the seven cards turned out to
        agree that it is a pass/fail threshold, so it was implemented that way
        and taken off this list."""
        # "errors" came off this list when it went live, the way PAR did:
        # every card states it as a ceiling ("< 5 %"), so it is pass/fail -
        # see test_errors_is_a_pass_fail_ceiling below. "leave_management"
        # came off when Aruti's leave report was wired: its target is 1
        # (all leave cleared) and a share of leave cleared cannot pass 1, so
        # full marks is the only cap - the Scheme cards cap it there too.
        outside = set()
        for code in sorted(outside):
            with self.subTest(code):
                self.assertIn(code, SOURCES, f"{code} lost its Source entry")
                self.assertTrue(
                    SOURCES[code].pending,
                    f"{code} is now scored live, but the eight cards do not "
                    f"agree on how to cap it - decide the cap first")

    def test_errors_is_a_pass_fail_ceiling(self):
        """Errors went live off iApply's returned applications. The cards
        agree on its shape - "< 5 %" on every one - so, like PAR, it is a
        threshold: under it full marks, over it nothing."""
        self.assertTrue(SOURCES["errors"].threshold)
        self.assertFalse(SOURCES["errors"].higher_is_better)

    def test_the_survey_lines_are_live_and_stop_at_full_marks(self):
        """The CX lines came OFF the list above, and this is the decision that
        let them.

        Six card lines score a survey measure above its target. Three wrote
        exactly 1.0 (Ultimate_RM NPS, Diaspora NPS, Personal_Banking
        coverage), one wrote 1.2 (Personal_Banking NPS), one applied no cap
        and wrote 1.667 (Mortgage_Business NPS), and one landed at 1.111 under
        no cap at all (Commercial NPS).

        So no cap reproduces every card, and the counts are close: of the nine
        numeric survey lines on the cards, a cap of 1.0 reproduces six, a cap
        of 1.2 reproduces five, and no cap at all reproduces five. 1.0 wins by
        one line.

        What settles it is not the one line. It is that 1.0 is the only cap
        more than one card actually applied to these lines, and that the
        business's own instruction for an RM the measure does not apply to is
        "give FULL MARKS" rather than give 120%. The three cards 1.0 does not
        match are named in KNOWN_DIFFERENCES above, and the whole decision is
        two numbers - ``Source.cap`` on the two registrations in
        ``live_scorecard`` and ``CX_CAP`` here - so the desk can have the
        other answer whenever it wants it.
        """
        from .live_scorecard import SOURCES

        for code in ("nps", "portfolio_nps", "portfolo_nps",
                     "portfolio_coverage_engagement"):
            with self.subTest(code):
                source = SOURCES[code]
                self.assertFalse(
                    source.pending,
                    f"{code} should be scored from what CX maintain")
                self.assertEqual(source.cap, CX_CAP)
                self.assertTrue(source.actual_key.startswith("cx_"))

        # 1.0 against a 0.6 target is full marks, not 167%.
        self.assertAlmostEqual(score_for(1.0, 0.6, True, cap=CX_CAP), 1.0)
        # Below target is still scored in proportion - the cap is a ceiling,
        # not a pass mark.
        self.assertAlmostEqual(
            score_for(0.2727272727, 0.6, True, cap=CX_CAP), 0.4545, places=4)

    def test_training_is_live_and_the_cards_agree_on_its_cap(self):
        """Training came off that list too, and on better evidence than the
        survey lines.

        Two cards score a training line above its target - Business Banking 36
        hours against 32, Commercial-Trade 69 against 32 - and both wrote
        exactly 1.0. No training line anywhere scores above full marks. So the
        cap is a rule the cards agree on, not a judgement call, which is why
        the two entries that used to sit in KNOWN_DIFFERENCES for this are
        gone.

        The figures come from HR's monthly return. All four cards whose RM is
        on the August 2026 return reproduce their stated ACTUAL exactly -
        36.0, 38.5, 29.0 and 69.0 - which is checked in tests_training.
        """
        from .live_scorecard import SOURCES

        for code in ("business_banking_training", "personal_banking_training",
                     "bo_training_hours"):
            with self.subTest(code):
                source = SOURCES[code]
                self.assertFalse(source.pending,
                                 f"{code} should read the training return")
                self.assertEqual(source.actual_key, "training_hours")
                self.assertEqual(source.cap, 1.0)

        # 36 hours against a 32-hour target is full marks, not 112.5%.
        self.assertAlmostEqual(score_for(36.0, 32.0, True, cap=1.0), 1.0)
        self.assertAlmostEqual(score_for(69.0, 32.0, True, cap=1.0), 1.0)
        # Below target is still proportional.
        self.assertAlmostEqual(score_for(29.0, 32.0, True, cap=1.0), 0.90625)
        self.assertAlmostEqual(score_for(38.5, 40.0, True, cap=1.0), 0.9625)

    def test_no_training_line_on_any_card_scores_above_full_marks(self):
        """The claim the cap rests on, counted off the cards."""
        above = []
        for row, target, actual, stated in _lines():
            if row["kpi_description"].strip().lower() != "training":
                continue
            if stated > 1.0001:
                above.append(f"{row['role_sheet']}: {stated}")
        self.assertEqual(above, [])

    def test_the_audit_score_is_live_lower_is_better_and_capped(self):
        """It came off the not-scored-live list because the figures now exist:
        Internal Audit's branch return holds the score and the implementation
        rate, and nine lines across eight roles read it.

        Three decisions, all of which the one calibration point agrees with.
        The score is **lower-is-better** - 1.65 is a grade, and "Annual audit
        score of 1.65" means achieve 1.65 or better; read the other way round
        the branches with the worst audits would come top. It is **capped at
        full marks**, because a graded control score is not a sales target and
        beating it by a hundredth should not pay 120%. And it is scored **in
        proportion rather than pass/fail**, so 1.70 against 1.65 reads as 97%
        and not as nought.
        """
        from .live_scorecard import SOURCES

        for code in ("audit", "bo_branch_audit_branch_audit",
                     "bo_diaspora_audit"):
            with self.subTest(code):
                source = SOURCES[code]
                self.assertFalse(source.pending)
                self.assertEqual(source.actual_key, "audit_score")
                self.assertFalse(source.higher_is_better)
                self.assertEqual(source.cap, 1.0)

        # The Diaspora card: 1.6337 against 1.65 scores 1.0.
        self.assertAlmostEqual(
            score_for(1.633636363636363, 1.65, False, cap=1.0), 1.0)
        # A near miss is a near miss.
        self.assertAlmostEqual(score_for(1.70, 1.65, False, cap=1.0),
                               1.65 / 1.70, places=4)

    def test_implementation_is_the_other_way_up(self):
        """Same return, opposite direction: 85% or better, and better is
        larger. No card states a score for it, so it keeps the ordinary cap."""
        from .live_scorecard import SOURCES

        source = SOURCES["bo_branch_audit_resolution"]
        self.assertEqual(source.actual_key, "audit_implementation")
        self.assertTrue(source.higher_is_better)
        self.assertEqual(source.cap, 1.2)

    def test_the_cap_count_is_what_this_file_claims(self):
        """Reads the cards and counts, so the six-against-five above is not a
        number somebody once wrote in a comment and nobody checked again."""
        tally = {1.0: 0, 1.2: 0, 1.6667: 0}
        lines = 0
        for row, target, actual, stated in _lines():
            if row["kpi_description"].strip().lower() not in CX_LINES:
                continue
            lines += 1
            for cap in tally:
                if abs(score_for(actual, target, True, cap=cap)
                       - stated) < 0.005:
                    tally[cap] += 1
        self.assertEqual(lines, 9, "the cards carry nine numeric survey lines")
        self.assertEqual(tally[1.0], 6, "the cap this tool applies")
        self.assertEqual(tally[1.2], 5, "the cap every other line uses")
        self.assertEqual(tally[1.6667], 5, "no cap at all")
        self.assertGreater(
            tally[1.0], max(tally[1.2], tally[1.6667]),
            "1.0 is only the chosen cap while it reproduces the most lines")
