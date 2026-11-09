"""Weighted TAT is read from the desk's monthly Weighted TAT Dashboard."""
import datetime
import io

import openpyxl
from django.test import TestCase


def dashboard():
    """A dashboard in the desk's shape: a role sheet and a Branch sheet with a
    zone table above the branch table."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DIASPORA_RM"
    ws.append([])
    ws.append([None, datetime.datetime(2026, 9, 1)])
    ws.append([])
    ws.append(["STAFF INFORMATION"] + [None] * 5 + ["TAT SLA CRM"] + [None] * 3 + ["WEIGHTED SCORES"])
    ws.append(["Rank", "SALES\nCODE", "SALESPERSON", "Branch", "Role", "Zone",
               "FY", "Monthly \nTarget", "Current Month Actual", "Monthly % Score", "% W. Score"])
    ws.append([1, "DN3998", "Doris Njuki", "HO", "DIASPORA RM", "HO", 1, 1, 0.9, 1, 0.775])
    ws.append([2, "XX1", "Broken", "HO", "DIASPORA RM", "HO", 1, 1, 0.9, 1, "#REF!"])
    br = wb.create_sheet("Branch")
    br.append([])
    br.append([None, datetime.datetime(2026, 9, 1)])
    br.append(["Zone", None, None, None, None, "WEIGHTED SCORES"])
    br.append(["Rank", "Zone", "Zone", "Zone", "Role", "% W. Score"])
    br.append([1, "Zone A", "Zone A", "Zone A", "Branch", 0.55])
    br.append([])
    br.append(["STAFF INFORMATION", None, None, None, None, "WEIGHTED SCORES"])
    br.append(["Branch", "Branch", "Branch", "Branch", "AREA", "% W. Score"])
    br.append([21, "Thika", "THIKA BRANCH", 500, "Zone A", 0.325])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


class WeightedTatTests(TestCase):
    def test_people_and_branches_are_read_and_broken_cells_skipped(self):
        from .weighted_tat import read

        found = read(dashboard())
        self.assertEqual(found["month"], datetime.date(2026, 9, 1))
        self.assertEqual(found["people"], {"DN3998": 0.775})
        self.assertEqual(found["branches"], {"thika": 0.325})      # not the zone table
        self.assertEqual(found["skipped"], {"DIASPORA_RM": 1})     # #REF! is no figure
        self.assertEqual(found["sla"]["DN3998"], 1)

    def test_a_saved_month_is_read_by_code_or_branch(self):
        from .weighted_tat import read, save, score

        save(read(dashboard()), "dashboard.xlsx", "test")
        sept = datetime.date(2026, 9, 30)
        self.assertEqual(score(sept, code="DN 3998"), 0.775)
        self.assertEqual(score(sept, branch="THIKA BRANCH"), 0.325)
        self.assertIsNone(score(datetime.date(2026, 10, 31), code="DN3998"))

    def test_the_screen_loads_it(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient

        admin = User.objects.create_superuser("wt", "wt@x.ke", "pw")
        client = APIClient()
        client.force_authenticate(admin)
        upload = dashboard()
        upload.name = "Weighted TAT Dashboard - 30 Sept 2026.xlsx"
        url = "/staff_management/scorecard-automation/weighted-tat/"
        resp = client.post(url, {"file": upload}, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual((resp.data["month"], resp.data["people"], resp.data["branches"]),
                         ("2026-09", 1, 1))
        listed = client.get(url).data["months"]
        self.assertEqual(listed[0]["month"], "2026-09")


class EtlScoresTests(TestCase):
    def test_the_etls_table_is_read_first(self):
        from django.db import connection

        from .weighted_tat import read, save, score

        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS weighted_tat_scores (
                report_month date, kind varchar(10), key varchar(60), weighted_score double precision)""")
            cur.execute("INSERT INTO weighted_tat_scores VALUES ('2026-10-01', 'person', 'DN3998', 0.85), "
                        "('2026-10-01', 'branch', 'THIKA', 0.4)")
        october = datetime.date(2026, 10, 31)
        self.assertEqual(score(october, code="DN3998"), 0.85)
        self.assertEqual(score(october, branch="THIKA BRANCH"), 0.4)
        # A month the ETL has not computed falls back to a loaded dashboard.
        save(read(dashboard()), "dashboard.xlsx", "test")
        self.assertEqual(score(datetime.date(2026, 9, 30), code="DN3998"), 0.775)
