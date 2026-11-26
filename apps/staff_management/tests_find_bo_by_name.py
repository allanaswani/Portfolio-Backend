"""A back-office person on the workbook List only (no DMC row, no
staff_employee_data row) is found by name by accounts_opened_compare and
scorecard_card - both used to stop at the sales tables."""
import datetime as dt
import io
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from .management.commands.card_doctor import _by_name
from .models import BoScorecard


class FindBoByNameTests(TestCase):
    def setUp(self):
        BoScorecard.objects.create(book="back_office", sales_code="ZQT1234",
                                   staff_name="ZEBEDEE QUILLON TESTER", sheet="CSO_SCORECARD",
                                   branch="Kisumu", month=dt.date(2026, 9, 1))

    def test_by_name_reads_the_workbook_list(self):
        self.assertEqual(_by_name("Zebedee Tester"), [("ZQT1234", "ZEBEDEE QUILLON TESTER")])

    def test_scorecard_card_finds_him_by_name(self):
        card = {"has_card": True, "perspectives": [], "performance_score": 0.5,
                "scored_lines": 1, "pending_lines": 0}
        out = io.StringIO()
        with mock.patch("apps.staff_management.live_scorecard.build_card",
                        return_value=card) as built:
            call_command("scorecard_card", "Zebedee Tester", stdout=out)
        self.assertEqual(built.call_args[0][0], "ZQT1234")
        text = out.getvalue()
        self.assertIn("ZEBEDEE QUILLON TESTER", text)
        self.assertIn("ZQT1234", text)
        self.assertIn("back-office scorecards workbook", text)

    def test_compare_resolves_the_name_to_his_code(self):
        from .management.commands.accounts_opened_compare import Command
        self.assertEqual(Command()._code("Zebedee Tester"), ("ZQT1234", "ZEBEDEE QUILLON TESTER"))
        self.assertEqual(Command()._code("ZQT1234")[0], "ZQT1234")

    def test_unknown_person_says_so(self):
        with self.assertRaises(CommandError):
            call_command("scorecard_card", "Nobody Here", stdout=io.StringIO())
