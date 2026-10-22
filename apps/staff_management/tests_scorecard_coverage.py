"""The coverage report's two bits of arithmetic.

The report itself is a read-only count over real cards, so there is nothing
to assert about its numbers - they are whatever production is. What CAN be
wrong is how it classifies a line, because that is the whole point of it:
"no target" goes to Administration, "neither" comes back to me, and swapping
those two sends the wrong person after the wrong fault.
"""

import datetime

from django.test import SimpleTestCase

from .management.commands.scorecard_coverage import Command, month_end


class WhatKindOfDashTests(SimpleTestCase):

    def verdict(self, **line):
        return Command.verdict(line)

    def test_a_target_and_a_figure_is_fine(self):
        self.assertEqual(
            self.verdict(ytd_target=100, ytd_actual=90), ("ok", ""))

    def test_a_nought_actual_is_still_a_figure(self):
        """Nought is a measurement. A line reading nought against a target is
        a person who sold nothing, not a line that failed to read."""
        self.assertEqual(
            self.verdict(ytd_target=100, ytd_actual=0), ("ok", ""))

    def test_a_nought_target_is_still_a_target_to_this_report(self):
        """``build_card`` decides whether nought means "no plan"; by the time
        a line reaches here that decision is made, and this must not take it
        again or the two disagree."""
        self.assertEqual(
            self.verdict(ytd_target=0, ytd_actual=5), ("ok", ""))

    def test_no_target_is_named_as_such_and_carries_the_cards_reason(self):
        verdict, why = self.verdict(
            ytd_target=None, ytd_actual=42,
            pending_label="No target is set")
        self.assertEqual(verdict, "no target")
        self.assertEqual(why, "No target is set")

    def test_a_target_with_nothing_read_is_no_actual(self):
        verdict, why = self.verdict(
            ytd_target=100, ytd_actual=None, pending_label="No figure yet")
        self.assertEqual(verdict, "no actual")
        self.assertEqual(why, "No figure yet")

    def test_neither_side_present_is_its_own_verdict(self):
        """This is the one that is mine to fix - the line is not wired at
        all - so it must never be reported as a missing plan."""
        verdict, _ = self.verdict(ytd_target=None, ytd_actual=None)
        self.assertEqual(verdict, "neither")

    def test_the_diagnostic_is_used_when_there_is_no_label(self):
        _, why = self.verdict(
            ytd_target=None, ytd_actual=None,
            diagnostic="relation insurance_policies does not exist")
        self.assertEqual(why, "relation insurance_policies does not exist")


class TheMonthEndTests(SimpleTestCase):

    def test_a_month_resolves_to_its_last_day(self):
        self.assertEqual(month_end("2026-09"), datetime.date(2026, 9, 30))

    def test_february_is_not_assumed_to_be_thirty_days(self):
        self.assertEqual(month_end("2026-02"), datetime.date(2026, 2, 28))

    def test_december_does_not_roll_into_month_thirteen(self):
        self.assertEqual(month_end("2026-12"), datetime.date(2026, 12, 31))
