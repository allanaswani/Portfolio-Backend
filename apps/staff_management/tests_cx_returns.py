"""The back-office CRM and KYC lines read the CX team's two returns.

Checked against the real files on 12 Nov 2026: every August figure on the BO
template's CRM (28) and KYC (99) sheets is the running total these rules give.
"""
import datetime
import io

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from . import cx_returns as cx
from . import workbook_cards as bo
from .tests_workbook_cards import book, template


def crm_logs():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2026"
    ws.append([None, "Branch", "CRM LOG IN CREDITIALS", "Jan", "Feb", "March", "April",
               "May", "June", "July", "Aug", "Sept", "Oct", "Nov ", "Dec",
               "CUMULATIVE 2026", "MONTHLY TARGET"])
    ws.append([2, "Eldoret", "HENRY SEREM ", 214, 57, 109, 88, 65, 47, 126, 92, 90, 42,
               None, None, 930, 100])
    ws.append([4, "Harambee", "CHRISTOPHER SHEMA", None, None, None, None, "TSC", 160,
               188, 164, 207, 31, None, None, 750, 100])
    ws.append([24, "TRM", "PETER DABASO", 69, 85, 46, 22, 106, 379, 122, 121, 70, 40,
               None, None, 1060, 100])
    ws.append([8, "Komarock", "RAHAB WAMBUI", 91, 0, 0, 0, 0, 12, 160, 205, 147, 256,
               None, None, 871, 100])
    ws.append([None, "Komarock", "JACKSON NJAGI", None, 111, 93, 150, 74, 80, None, 4, 3,
               0, None, None, 515, 100])
    ws.append([None, None, "TOTAL", 1, 2, 3])
    return _bytes(wb)


def data_update():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2026 Monthly"
    ws.append(["BRANCH DATA UPDATE EXERCISE "])
    ws.append(["RECEIVED FORMS - YEAR 2026"])
    ws.append(["NO", "BRANCH NAME", "January", "February", "March", "April", "May",
               "June", "July", "August", "September", "October", "November",
               "December", "CUMULATIVE 2026", "TARGET ANNUAL", "MONTHLY TARGET"])
    ws.append([1, "BURU BURU", 15, 28, 25, 20, 15, 16, 24, 27, 18, 24, None, None, 212,
               360, 30])
    ws.append([5, "HURLINGAM", 18, 19, 20, 29, 11, 14, 27, 21, 25, 24])
    ws.append([7, "KITENGELA", 21, 28, 25, 28, 17, 14, 30, 14, 19, 18])
    ws.append([None, "AMUTHAMA", 4, 10, 7, 0, 4, 1, 11, 3, 1, 4])
    ws.append([None, "TOTAL", 324, 492])
    # The second sheet (the month's old/new comparison) is not the return.
    other = wb.create_sheet("Sheet1")
    other.append([None, "Branch", "Old Data", "New Data", "Current Monthly Score"])
    return _bytes(wb)


def _bytes(wb):
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


class ReadTests(TestCase):
    def test_crm_logs_is_read_per_person_and_text_is_no_figure(self):
        found = cx.read(crm_logs())
        self.assertEqual((found["kind"], found["year"]), ("crm", 2026))
        self.assertEqual([r["label"] for r in found["rows"]],
                         ["HENRY SEREM", "CHRISTOPHER SHEMA", "PETER DABASO",
                          "RAHAB WAMBUI", "JACKSON NJAGI"])
        self.assertEqual(found["skipped"], ["CHRISTOPHER SHEMA 05: TSC"])

    def test_data_update_is_read_per_branch_from_the_monthly_sheet(self):
        found = cx.read(data_update())
        self.assertEqual((found["kind"], found["year"]), ("kyc", 2026))
        self.assertEqual(found["rows"][0]["months"]["10"], 24)
        self.assertNotIn("TOTAL", [r["label"] for r in found["rows"]])

    def test_another_workbook_is_refused(self):
        wb = openpyxl.Workbook()
        wb.active.append(["Name", "Value"])
        with self.assertRaises(ValueError):
            cx.read(_bytes(wb))


class RunningTotalTests(TestCase):
    def setUp(self):
        cx.save(cx.read(crm_logs()))
        cx.save(cx.read(data_update()))

    def test_crm_is_the_persons_running_total(self):
        # The template's Eldoret figures: 214, 271, 380 ... 798 at August.
        self.assertEqual(cx.running_total("crm", 2026, 1, names=("Henry Serem",)), 214)
        self.assertEqual(cx.running_total("crm", 2026, 8, names=("Henry Serem",)), 798)
        self.assertEqual(cx.running_total("crm", 2026, 10, names=("Henry Serem",)), 930)
        # Nothing in December yet: the total so far, not a nought.
        self.assertEqual(cx.running_total("crm", 2026, 12, names=("Henry Serem",)), 930)

    def test_a_spelling_slip_is_matched_only_at_the_persons_branch(self):
        name = ("Peter Ibrae Dabasso",)
        self.assertEqual(cx.running_total("crm", 2026, 8, names=name, branches=("TRM",)), 950)
        self.assertIsNone(cx.running_total("crm", 2026, 8, names=name, branches=("Nakuru",)))
        self.assertIsNone(cx.running_total("crm", 2026, 8, names=name))

    def test_someone_not_on_the_return_has_no_figure(self):
        self.assertIsNone(cx.running_total("crm", 2026, 10, names=("Felix Saigon",),
                                           branches=("Komarock",)))

    def test_kyc_is_the_branchs_running_total(self):
        # Buru Buru on the template: 15, 43, 68, 88, 103, 119, 143, 170.
        self.assertEqual(cx.running_total("kyc", 2026, 8, branches=("Buruburu",)), 170)
        self.assertEqual(cx.running_total("kyc", 2026, 10, branches=("Buruburu Branch",)), 212)
        self.assertEqual(cx.running_total("kyc", 2026, 8, branches=("Hurlingham",)), 159)

    def test_the_first_branch_the_return_has_wins(self):
        # The template puts Anne Muthama at "AMUTHAMA", her own row.
        self.assertEqual(cx.running_total("kyc", 2026, 8, branches=("AMUTHAMA", "Rehani")), 40)


class CardTests(TestCase):
    def test_the_october_card_reads_the_kyc_return(self):
        scorecards = book()
        # The card's first line reads the KYC sheet instead of CASA.
        scorecards["cards"]["TELLER_SCORECARD"]["grid"][9][11] = "KYC"
        actuals = template({
            "KYC": {"Bob Waigwa": [21, 49, 74, 102, 119, 133, 163, 177, 196]},
            "Training_hours": {"Bob Waigwa": [0, 6, 11, 15, 18, 22, 22, 22, 40]},
            "NPS": {"Bob Waigwa": [0.5] * 9},
        })
        bo.save_file("scorecards", scorecards)
        bo.save_file("actuals", actuals)
        cx.save(cx.read(data_update()))
        card = bo.live_card("BCK3783", None, datetime.date(2026, 10, 31))
        line = card["perspectives"][0]["lines"][0]
        # Kitengela's forms to October: 214.
        self.assertEqual(line["ytd_actual"], 214)
        self.assertIn("Data update (KYC)", line["as_at"])


class ScreenTests(TestCase):
    def test_an_administrator_loads_either_return(self):
        admin = User.objects.create_superuser("cx", "cx@example.com", "x")
        client = APIClient()
        client.force_authenticate(admin)
        url = "/staff_management/scorecard-automation/cx-returns/"
        up = data_update()
        up.name = "Data Update - 2026.xlsx"
        r = client.post(url, {"file": up}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.data["kind"], r.data["rows"], r.data["latest_month"]),
                         ("kyc", 4, 10))
        listed = client.get(url).data["returns"]
        self.assertEqual([(x["kind"], x["year"]) for x in listed], [("kyc", 2026)])
