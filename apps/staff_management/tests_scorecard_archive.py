"""Monthly scorecard archive (evidence outside the database) and the automatic
send once a month's card is complete."""
import csv
import datetime
import json
import os
import shutil
import tempfile
from unittest.mock import patch

from django.test import TestCase

from . import scorecard_archive as sa

PERSON = {"book": "Back office", "code": "BCK3783", "name": "Bob Waigwa"}


def card(score=0.8, pending=False):
    return {"has_card": True, "performance_score": score,
            "staff": {"sales_code": "BCK3783", "name": "Bob Waigwa"},
            "period": {"label": "October 2026"},
            "perspectives": [{"lines": [
                {"kpi_name": "CASA", "pending": False},
                {"kpi_name": "Digital Onboarding", "pending": pending}]}]}


class ArchiveTests(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["SCORECARD_ARCHIVE_DIR"] = self.dir
        self.addCleanup(lambda: (os.environ.pop("SCORECARD_ARCHIVE_DIR", None),
                                 shutil.rmtree(self.dir, ignore_errors=True)))
        patcher = patch("apps.staff_management.scorecard_signoff.build_card_workbook",
                        side_effect=lambda c, s=None: __import__("io").BytesIO(
                            json.dumps(c, sort_keys=True).encode()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_files_are_written_once_and_never_overwritten(self):
        first = sa.archive_card("2026-10", PERSON, card())
        self.assertTrue(first["written"])
        folder = os.path.join(self.dir, "2026-10", "Back office")
        self.assertTrue(os.path.exists(os.path.join(folder, "BCK3783 - Bob Waigwa.xlsx")))
        # The same card again: nothing new.
        self.assertFalse(sa.archive_card("2026-10", PERSON, card())["written"])
        # A changed card: a second version beside the first, the first kept.
        second = sa.archive_card("2026-10", PERSON, card(score=0.9))
        self.assertTrue(second["written"])
        self.assertIn("(v2 ", second["file"])
        with open(os.path.join(folder, "BCK3783 - Bob Waigwa.json")) as f:
            self.assertEqual(json.load(f)["performance_score"], 0.8)
        with open(os.path.join(self.dir, "2026-10", "manifest.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["version"] for r in rows], ["1", "2"])
        self.assertEqual(len(rows[0]["xlsx_sha256"]), 64)

    def test_complete_means_no_line_waiting(self):
        self.assertTrue(sa.is_complete(card()))
        self.assertFalse(sa.is_complete(card(pending=True)))
        self.assertEqual(sa.waiting_lines(card(pending=True)), ["Digital Onboarding"])


class TimelineTests(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["SCORECARD_ARCHIVE_DIR"] = self.dir
        self.addCleanup(lambda: (os.environ.pop("SCORECARD_ARCHIVE_DIR", None),
                                 shutil.rmtree(self.dir, ignore_errors=True)))
        self.sent = []
        for target, value in (
                ("people", lambda: [PERSON, {"book": "Back office", "code": "X1", "name": "Ann Other"}]),
                ("card_for", lambda code, period: (card(pending=(code == "X1")), None)),
                ("archive_card", lambda period, person, c, s=None, now=None: {"file": "f", "sha256": "h", "written": True}),
        ):
            p = patch.object(sa, target, side_effect=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch("apps.staff_management.scorecard_email.send_card",
                  side_effect=lambda c, s=None, **k: self.sent.append((c["staff"]["sales_code"], k["period"])))
        p.start()
        self.addCleanup(p.stop)

    def test_nothing_before_the_fifth(self):
        out = sa.run(today=datetime.date(2026, 11, 3), out=lambda *_: None)
        self.assertEqual((out["archived"], self.sent), (0, []))

    def test_from_the_fifth_complete_cards_are_archived_and_sent_once(self):
        out = sa.run(today=datetime.date(2026, 11, 6), out=lambda *_: None)
        self.assertEqual(out["period"], "2026-10")
        self.assertEqual(self.sent, [("BCK3783", "2026-10")])
        self.assertEqual(out["archived"], 1)          # the incomplete one waits
        self.assertEqual([c for c, _, _ in out["incomplete"]], ["X1"])
        with patch.object(sa, "already_sent", return_value=True):
            sa.run(today=datetime.date(2026, 11, 7), out=lambda *_: None)
        self.assertEqual(len(self.sent), 1)

    def test_final_day_archives_everything_and_reports(self):
        with patch.object(sa, "notify_administration") as notify:
            out = sa.run(today=datetime.date(2026, 11, 10), out=lambda *_: None)
        self.assertTrue(out["final"])
        self.assertEqual(out["archived"], 2)          # the incomplete one too
        self.assertEqual(self.sent, [("BCK3783", "2026-10")])   # but not sent
        notify.assert_called_once()
