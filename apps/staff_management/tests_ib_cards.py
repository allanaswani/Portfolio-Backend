"""Institutional Banking scorecards: the workbook's own formulas over its
actuals template, proven against the score its macro recorded, loaded on the
same screen as the other books; a month the template does not have is no
card, never a made-up one. A small workbook built here, the real engine."""
import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from . import workbook_cards as wc

URL = "/staff_management/scorecard-automation/manual-figures/bo-actuals/"
ACTUAL = ('=+VLOOKUP($C$2,INDIRECT("[2026_IB_Actual_Template_v2.xlsx]"&$M6&"!" '
          '&"$c:$R"),$M$5+4,0)')
PEOPLE = [(1, "AA1", "Amy Able", "IB RM"), (2, "BB2", "Ben Bold", "IB RM"),
          (3, "CC3", "Cy Clear", "IB RM"),
          (4, "HH4", "Hana Head", "HEAD OF INSTITUTIONAL BANKING")]
#: October revenue YTD per person (target 12 a year -> 10 by October).
REVENUE = {"AA1": 5, "BB2": 8, "CC3": 15, "HH4": 30}


def scorecards():
    wb = Workbook()
    ws = wb.active
    ws.title = "List"
    ws.append(["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch",
               "staff_zone", "reports_to"])
    for pf, code, name, role in PEOPLE:
        ws.append([pf, code, name, role, "Head Office", "Head Office", "Boss"])
    c = wb.create_sheet("Constants")
    c["A1"], c["B1"], c["A2"], c["B2"], c["A5"], c["B5"] = (
        "Month_column", "=$B$2+4", "Month_count", 10, "Year", 2026)
    s = wb.create_sheet("Monthly_Summary")
    s.append(["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch",
              "staff_zone"] + [f"m{i}" for i in range(1, 13)])
    # The desk recorded October (column P): Amy 50% (her card), Ben 99% (not
    # what this template gives), Hana 100% (capped 120% x 1 = 1.2? no: weight
    # 1, score capped at 1.2 -> 1.2); Cy has no row.
    for code, name, score in (("AA1", "Amy Able", 0.5), ("BB2", "Ben Bold", 0.99),
                              ("HH4", "Hana Head", 1.2)):
        s.append([0, code, name, "", "", ""] + [None] * 9 + [score])
    for sheet in ("IB_RM", "HOD_IB"):
        card = wb.create_sheet(sheet)
        card["A1"], card["C2"], card["K2"] = f"2026 {sheet}", "x", "=L8"
        card["B5"], card["C5"], card["M5"] = "KPI", "KPI Description", "=Constants!B2"
        card["B6"], card["C6"], card["F6"], card["H6"] = "Financials", "Revenue", 1, 12
        card["I6"], card["J6"] = "=H6*($M$5/12)", ACTUAL
        card["K6"], card["L6"], card["M6"] = "=IF((J6/I6)>1.2,1.2,(J6/I6))", "=K6*F6", "Revenue"
        card["L8"] = "=SUM(L6:L6)"
        card["A10"] = "Reviewee Name:"
    wb.create_sheet("INITIATIVES_HOD")["A1"] = "not read by any card"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def template():
    wb = Workbook()
    head = ["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch",
            "staff_zone"] + [f"m{i}" for i in range(1, 13)]
    ws = wb.active
    ws.title = "Revenue"
    ws.append(head)
    for pf, code, name, role in PEOPLE:
        # Jan..Oct a running total ending at REVENUE; Nov/Dec leftovers.
        ws.append([pf, code, name, role, "Head Office", "Head Office"]
                  + [REVENUE[code] * m / 10 for m in range(1, 11)] + [-999, -999])
    for sheet in ("Deposit_Growth", "Deposit_Mix", "Interest_Expense_Rate",
                  "Client_Retention"):
        wb.create_sheet(sheet).append(head)
    raw = wb.create_sheet("Portfolio")
    raw.append(["CUST_CIF", "ACC_NUM"] + ["x"] * 20)
    for i in range(30):
        raw.append([i, i] + [123456] * 20)     # numbers in "month" columns
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class IbReadTests(TestCase):
    def test_the_workbook_and_template_are_recognised(self):
        data = scorecards()
        self.assertTrue(wc.is_ib_workbook(data))
        self.assertFalse(wc.is_retail_bo_workbook(data))
        book = wc.read_ib(data)
        self.assertEqual(sorted(book["cards"]), ["HOD_IB", "IB_RM"])   # not INITIATIVES
        self.assertEqual(wc.ib_run_month(book), 10)
        actuals = wc.read_actuals(io.BytesIO(template()))
        self.assertEqual(wc.actuals_book(actuals), wc.IB)
        self.assertNotIn("Portfolio", actuals)
        # The leftovers look like months to a count of figures; the desk's
        # run month (10) is what bounds the cards.
        self.assertEqual(wc.template_months(actuals), list(range(1, 13)))
        months = sorted({m for _h, m, _c in wc.compute_all(book, actuals)})
        self.assertEqual(months, list(range(1, 11)))

    def test_the_proof_sets_each_card_beside_the_desks_score(self):
        book = wc.read_ib(scorecards())
        actuals = wc.read_actuals(io.BytesIO(template()))
        proof = {p["sales_code"]: p for p in wc.ib_proof(book, actuals)}
        self.assertEqual({k: v["sheet"] for k, v in proof.items()},
                         {"AA1": "IB_RM", "BB2": "IB_RM", "CC3": "IB_RM", "HH4": "HOD_IB"})
        self.assertTrue(proof["AA1"]["same"])                 # 5 / 10
        self.assertAlmostEqual(proof["AA1"]["computed"], 0.5)
        self.assertFalse(proof["BB2"]["same"])                # 0.8, desk 0.99
        self.assertTrue(proof["HH4"]["same"])                 # capped at 1.2
        self.assertIsNone(proof["CC3"]["desk"])               # no summary row


class IbLoadAndCardTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_superuser("root.admin", password="x"))

    def post(self, name, data, **extra):
        return self.client.post(URL, {"file": SimpleUploadedFile(name, data), "apply": "1",
                                      **extra}, format="multipart")

    def test_load_then_october_is_the_stored_card_and_november_waits(self):
        from .live_scorecard import build_card, resolve_person

        r = self.post("IB_Scorecards.xlsm", scorecards())
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("Load the 2026 IB actuals template", r.data["detail"])
        r = self.post("2026_IB_Actual_Template_v2.xlsx", template(), year="2026")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("2 of 3 cards the desk scored for month 10 recompute", r.data["detail"])
        self.assertIn("BB2 Ben Bold: desk 99.0000%", r.data["detail"])
        self.assertIn("CC3 Cy Clear: no score on Monthly_Summary", r.data["detail"])

        # The account sheet is kept for ib_feed_probe - nothing to copy by hand.
        self.assertEqual(len(wc.saved(wc.IB_PORTFOLIO_KIND, 2026)), 31)
        self.assertEqual(resolve_person("AA1").roster, wc.IB_ROSTER)
        october = build_card("AA1", as_at=datetime.date(2026, 10, 31))
        self.assertTrue(october["has_card"])
        self.assertAlmostEqual(october["performance_score"], 0.5)
        # The template's November column holds leftovers (-999): never a card.
        november = build_card("AA1", as_at=datetime.date(2026, 11, 30))
        self.assertFalse(november["has_card"])
        self.assertEqual(november["reason"], "ib_month_not_loaded")
