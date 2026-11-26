"""proration_check says which entries the card reads, shows the card with and
without them, and says when the month is signed (seeded workbook, real
entries, the real command)."""
import io
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from . import workbook_cards as bo
from .tests_proration import prorated_book, save_entries
from .tests_workbook_cards import ACTUALS


def fake_card(code, as_at=None):
    """The target follows the entries in force, like the real card."""
    prorated = bool(bo.proration().get(code))
    return {"has_card": True, "performance_score": 0.9 if prorated else 0.7,
            "perspectives": [{"lines": [
                {"kpi_name": "Account Opening", "ytd_target": 20.0 if prorated else 36.0},
                {"kpi_name": "NPS", "ytd_target": 0.6}]}]}


class ProrationCheckTests(TestCase):
    def setUp(self):
        cache.clear()
        bo.save_file("scorecards", prorated_book(column="prorate_new"))
        bo.save_file("actuals", ACTUALS)

    def run_check(self):
        out = io.StringIO()
        with mock.patch("apps.staff_management.live_scorecard.build_card", side_effect=fake_card):
            call_command("proration_check", "BCK3783", "--month", "2026-09", stdout=out)
        return out.getvalue()

    def test_a_column_the_card_reads_moves_the_target(self):
        save_entries({"BCK3783": [{"id": "a", "reason": "joined", "from": "2026-03"}]})
        bo.rescore("BCK3783")
        text = self.run_check()
        self.assertIn("PRORATION ENTRIES: 1", text)
        self.assertIn("card reads: prorate_new", text)
        self.assertNotIn("does not read", text)
        self.assertIn("score with entries 90.00% | without 70.00%", text)
        self.assertIn("1 line(s) changed by the proration", text)
        self.assertIn("SIGNED FOR 2026-09: no", text)

    def test_an_acting_entry_on_a_card_that_does_not_read_it_is_called_out(self):
        save_entries({"BCK3783": [{"id": "a", "reason": "acting",
                                   "from": "2026-01", "to": "2026-04"}]})
        bo.rescore("BCK3783")
        text = self.run_check()
        self.assertIn("(months out by 2026-09: 4)", text)
        self.assertIn("the acting entry fills prorate_acting_other, which this card "
                      "does not read: it changes nothing on this card", text)

    def test_a_signed_month_is_the_frozen_copy(self):
        from .scorecard_automation.models import ScorecardSignoff

        save_entries({"BCK3783": [{"id": "a", "reason": "joined", "from": "2026-03"}]})
        bo.rescore("BCK3783")
        ScorecardSignoff.objects.create(sales_code="BCK3783", period="2026-09",
                                        signed_at=timezone.now(),
                                        card={"performance_score": 0.5})
        text = self.run_check()
        self.assertIn("SIGNED FOR 2026-09: YES", text)
        self.assertIn("signed copy score: 50.00%", text)
