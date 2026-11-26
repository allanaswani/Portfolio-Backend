"""The archive counts people, not files: a card re-archived after its figures
changed is a version of the same card. archive_versions says what changed."""
import io

from django.core.management import call_command
from django.test import TestCase

from . import scorecard_archive as sa
from .tests_scorecard_archive import PERSON, ArchiveTests, card


class ArchiveVersionTests(TestCase):
    def setUp(self):
        ArchiveTests.setUp(self)
        sa.archive_card("2026-10", PERSON, card(score=0.8))
        sa.archive_card("2026-10", PERSON, card(score=0.85))            # v2: score
        sa.archive_card("2026-10", PERSON, card(score=0.85, pending=True))  # v3: a line
        other = {"book": "Back office", "code": "ZZ1", "name": "Zed"}
        one = card(score=0.7)
        one["staff"] = {"sales_code": "ZZ1", "name": "Zed"}
        sa.archive_card("2026-10", other, one)
        sa.archive_card("2026-10", {"book": "retail_back_office", "code": "RB1",
                                    "name": "Rob"}, card(score=0.6))

    def test_months_counts_people_and_versions_apart(self):
        month = sa.months()[0]
        self.assertEqual(month["cards"], 3)
        self.assertEqual(month["versions"], 5)
        books = {b["name"]: (b["cards"], b["versions"]) for b in month["workbooks"]}
        self.assertEqual(books, {"Back office": (2, 4), "Retail back office": (1, 1)})

    def test_only_the_newest_version_is_latest(self):
        mine = [c for c in sa.month_cards("2026-10") if c["name"].startswith("BCK3783")]
        self.assertEqual(sorted((c["version"], c["latest"]) for c in mine),
                         [(1, False), (2, False), (3, True)])

    def test_the_command_says_what_changed(self):
        out = io.StringIO()
        call_command("archive_versions", "--period", "2026-10", stdout=out)
        text = out.getvalue()
        self.assertIn("3 people; versions per person: 1 version(s): 2, 3 version(s): 1", text)
        self.assertIn("re-archives that moved the score: 1; that did not: 1", text)
        self.assertRegex(text, r"\s1  line pending")
        out = io.StringIO()
        call_command("archive_versions", "--period", "2026-10", "--code", "BCK3783", stdout=out)
        self.assertIn("BCK3783 v1 -> v2", out.getvalue())
        self.assertIn("score 0.8 -> 0.85", out.getvalue())
