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

    def test_archive_is_copied_to_the_share_without_overwriting(self):
        share = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(share, ignore_errors=True))
        with patch.dict(os.environ, {"SCORECARD_SHARE_DIR": share}):
            sa.archive_card("2026-10", PERSON, card())
            self.assertEqual(sa.sync_share(out=lambda *_: None)["copied"], 3)   # xlsx, json, manifest
            copy = os.path.join(share, "2026", "Oct 26", "Back office",
                                "BCK3783 - Bob Waigwa.json")
            with open(copy) as f:
                self.assertEqual(json.load(f)["performance_score"], 0.8)
            # Nothing new: nothing copied.
            self.assertEqual(sa.sync_share(out=lambda *_: None)["copied"], 0)
            # A second version: its two files plus the grown manifest.
            sa.archive_card("2026-10", PERSON, card(score=0.9))
            self.assertEqual(sa.sync_share(out=lambda *_: None)["copied"], 3)
            with open(os.path.join(share, "2026", "Oct 26", "manifest.csv"),
                      newline="") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 2)
        # No share mounted: the archive stays on the server, nothing fails.
        with patch.dict(os.environ, {"SCORECARD_SHARE_DIR": os.path.join(share, "absent")}):
            self.assertIsNone(sa.sync_share(out=lambda *_: None)["share"])

    def test_share_month_folders_follow_the_teams_layout(self):
        self.assertEqual(sa.share_month_folder("2026-10"), os.path.join("2026", "Oct 26"))
        self.assertEqual(sa.share_month_folder("2027-01"), os.path.join("2027", "Jan 27"))

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

    def test_auto_send_can_be_paused(self):
        with patch.dict(os.environ, {"SCORECARD_AUTO_SEND": "0"}):
            out = sa.run(today=datetime.date(2026, 11, 6), out=lambda *_: None)
        self.assertEqual((out["archived"], self.sent), (1, []))

    def test_final_day_archives_everything_and_reports(self):
        with patch.object(sa, "notify_administration") as notify:
            out = sa.run(today=datetime.date(2026, 11, 10), out=lambda *_: None)
        self.assertTrue(out["final"])
        self.assertEqual(out["archived"], 2)          # the incomplete one too
        self.assertEqual(self.sent, [("BCK3783", "2026-10")])   # but not sent
        notify.assert_called_once()


class ArchiveScreenTests(TestCase):
    """The archive read back through the portal: months, cards, zip, one file."""

    def setUp(self):
        ArchiveTests.setUp(self)   # its temporary archive, not its tests
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        users = get_user_model()
        self.admin = users.objects.create_user("sc_admin", password="x", is_superuser=True)
        self.someone = users.objects.create_user("sc_someone", password="x", is_staff=True)
        self.api = APIClient()
        sa.archive_card("2026-10", PERSON, card())
        self.url = "/staff_management/scorecard-automation/archive/"

    def test_months_and_cards_are_listed(self):
        self.api.force_authenticate(self.admin)
        res = self.api.get(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        month = res.data["months"][0]
        self.assertEqual((month["period"], month["label"], month["cards"]),
                         ("2026-10", "October 2026", 1))
        res = self.api.get(self.url, {"period": "2026-10"})
        self.assertEqual(res.data["cards"][0]["file"], "Back office/BCK3783 - Bob Waigwa.xlsx")

    def test_month_zip_holds_every_file_under_the_share_layout(self):
        import io
        import zipfile

        self.api.force_authenticate(self.admin)
        res = self.api.get(self.url, {"period": "2026-10", "download": "1"})
        self.assertEqual(res.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
        self.assertIn("2026/Oct 26/Back office/BCK3783 - Bob Waigwa.xlsx", names)
        self.assertIn("2026/Oct 26/manifest.csv", names)

    def test_one_card_downloads_and_nothing_outside_the_month(self):
        self.api.force_authenticate(self.admin)
        res = self.api.get(self.url, {"period": "2026-10",
                                      "file": "Back office/BCK3783 - Bob Waigwa.xlsx"})
        self.assertEqual(res.status_code, 200)
        for bad in ("../../etc/passwd", "../2026-09/manifest.csv", "/etc/passwd"):
            res = self.api.get(self.url, {"period": "2026-10", "file": bad})
            self.assertEqual(res.status_code, 404, bad)
        self.assertEqual(self.api.get(self.url, {"period": "../x"}).status_code, 404)

    def test_only_scorecard_administrators(self):
        # is_staff is legacy noise: it does not open everybody's records.
        self.api.force_authenticate(self.someone)
        self.assertEqual(self.api.get(self.url).status_code, 403)


class GroupSummaryTests(TestCase):
    """Each group's summary: one group per role, only the people who hold a
    card now, the desk's months off its sheet, later months off the archived
    cards, blanks never filled in."""

    def setUp(self):
        ArchiveTests.setUp(self)
        hdr = ["PF-No", "SalesCode", "Staff - Name", "Role", "Branch", "Zone"] + [
            46023.0 + 30 * i for i in range(12)]
        desk = [0.7, 0.71, 0.72, 0.73, 0.74, 0.75, 0.76, 0.77, 0.78, None, None, None]
        self.bo_book = {"book": "back_office", "cards": {"TELLER_SCORECARD": {}, "BOM_SCORECARD": {}},
                        "tables": {
            "List": [["PF", "Code", "Name", "Role", "Branch"],
                     [1329, "BCK3783", "Bob Waigwa", "Teller", "Meru"],
                     [7, "BOM7", "Bea Manager", "BOM", "Meru"],
                     [8, "LFT8", "Gone Person", "Teller", "left"],
                     [9, "NEW9", "New Person", "Teller", "Meru"]],
            "Monthly_Summ": [hdr,
                             [1329.0, "BCK3783", "Bob Waigwa", "Teller", "Meru", "Zone A"] + desk,
                             [7.0, "BOM7", "Bea Manager", "BOM", "Meru", "Zone A"] + desk,
                             [8.0, "LFT8", "Gone Person", "Teller", "Meru", "Zone A"] + desk,
                             [99.0, "OLD99", "Never Holds", "Teller", "Meru", "Zone A"] + desk],
            "RBO_Monthly_Summ": [hdr],
        }}
        bb_hdr = ["pf-number", "sales_code", "Staff - Name", "Role", "branch"] + [None] * 12
        self.bb_book = {"book": "branch_business", "cards": {"BM_Scorecard": {}}, "tables": {
            "List": [["PF", "Code", "Name", "Branch"], [1, "AA1", "A", "X"], [2, "BB2", "B", "Y"]],
            "Branch_Monthly_Summary": [
                [], [], bb_hdr,
                [1.0, "AA1", "A", "BBM", "X"] + [0.5] * 9 + [None] * 3,
                [2.0, "BB2", "B", "BBM", "Y"] + [0.9] * 9 + [None] * 3,
                [3.0, "CC3", "Left Manager", "BBM", "Z"] + [0.6] * 9 + [None] * 3]}}
        sa.archive_card("2026-10", PERSON, card(score=0.81))

    def _saved(self, kind, year=None):
        return {"scorecards": self.bo_book, "bb_scorecards": self.bb_book}.get(kind)

    def _groups(self, upto):
        from . import scorecard_summaries as ss

        with patch("apps.staff_management.workbook_cards.saved", side_effect=self._saved),                 patch("apps.staff_management.workbook_cards.roster_roles", return_value={}),                 patch("apps.staff_management.workbook_cards.hr_roles", return_value={}):
            return {g["group"]: g for g in ss.group_summaries(2026, upto)}

    def test_one_group_per_role_and_only_card_holders(self):
        groups = self._groups(10)
        self.assertIn("Back office - Teller", groups)
        self.assertIn("Back office - BOM", groups)
        tellers = groups["Back office - Teller"]
        # Not the one who left, not a desk row that holds no card.
        self.assertEqual([r["code"] for r in tellers["rows"]], ["BCK3783"])
        self.assertEqual([r["code"] for r in groups["Back office - BOM"]["rows"]], ["BOM7"])
        # A card holder with no score yet is named, not a blank row.
        self.assertEqual(tellers["no_score"], ["New Person (NEW9)"])

    def test_desk_months_then_the_archived_month(self):
        row = self._groups(10)["Back office - Teller"]["rows"][0]
        self.assertEqual(row["identity"][:3], [1329, "BCK3783", "Bob Waigwa"])
        self.assertEqual(row["scores"][8], 0.78)          # Sep, the desk's
        self.assertEqual(row["scores"][9], 0.81)          # Oct, the archived card
        self.assertAlmostEqual(row["change"], 0.03)

    def test_a_month_with_neither_stays_blank(self):
        row = self._groups(11)["Back office - Teller"]["rows"][0]
        self.assertIsNone(row["scores"][10])
        self.assertIsNone(row["change"])

    def test_branch_managers_only_those_on_the_list_ranked(self):
        bms = self._groups(9)["Branch managers - BBM"]
        ranks = {r["code"]: r["rank"] for r in bms["rows"]}
        self.assertEqual(ranks, {"BB2": 1, "AA1": 2})

    def test_summaries_go_in_the_excel_and_the_zip(self):
        import io
        import zipfile

        from openpyxl import load_workbook

        from . import scorecard_summaries as ss

        with patch("apps.staff_management.workbook_cards.saved", side_effect=self._saved),                 patch("apps.staff_management.workbook_cards.roster_roles", return_value={}),                 patch("apps.staff_management.workbook_cards.hr_roles", return_value={}):
            wb = load_workbook(io.BytesIO(ss.summaries_workbook(2026, 10)))
            self.assertIn("BO - Teller", wb.sheetnames)
            self.assertIn("BM - BBM", wb.sheetnames)
            names = zipfile.ZipFile(io.BytesIO(sa.month_zip("2026-10"))).namelist()
        self.assertIn("2026/Oct 26/Group summaries - October 2026.xlsx", names)
