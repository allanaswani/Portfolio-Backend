"""HFDI Master Scorecard: staff_list keyed by staff_id, mapping as its
Constants, Excel table references (sales_roles_targets[]) in the target
formulas, active rows only, a template whose January is column E. A small
workbook built here, the real engine."""
import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook
from openpyxl.worksheet.table import Table

from . import workbook_cards as wc

URL = "/staff_management/scorecard-automation/manual-figures/bo-actuals/"
ACTUAL = ('=+VLOOKUP($C$2,INDIRECT("[Scorecard_Actual_Template_2026.xlsx]"&$M7&"!" '
          '&"$B:$P"),$O$1,0)')


def master():
    wb = Workbook()
    sl = wb.active
    sl.title = "staff_list"
    sl.append(["staff_id", "staff_name", "role", "primary_project", "employment_date",
               "Vintage", "begin", "months_in_year", "email", "team_leader", "email2",
               "sales_manager", "email3", "active"])
    sl.append([101, "Pat Advisor", "Property Advisor", "Fahari", None, None, None, 12,
               None, "Tim Lead", None, None, None, 1])
    sl.append([102, "Old Leaver", "Property Advisor", "Fahari", None, None, None, 12,
               None, "Tim Lead", None, None, None, 0])
    t = wb.create_sheet("targets")
    t.append([])
    t.append(["role", "a", "b", "Own Project Sales"])
    t.append(["Property Advisor", 0, 0, 12])
    t.add_table(Table(displayName="sales_roles_targets", ref="A2:D3"))
    m = wb.create_sheet("mapping")
    m["A1"], m["B1"], m["A3"], m["B3"], m["A4"], m["B4"] = (
        "Year", 2026, "Month_column", "=B4+3", "Month_count", 10)
    s = wb.create_sheet("Monthly_Summ")
    for _ in range(5):
        s.append([])
    s.append(["staff_id", "staff_name", "role", "primary_project", "Jan"])
    s.append([101, "Pat Advisor", "Property Advisor", "Fahari"] + [None] * 9 + [0.5])
    card = wb.create_sheet("Property_Advisor")
    card["B2"], card["C2"], card["J2"] = "Staff Name:", "x", "=J9"
    card["N1"], card["O1"] = "=mapping!$B$4", "=mapping!$B$3"
    card["B6"], card["C6"], card["D6"], card["E6"] = "Perspective", "KPI", "Measure", "Weight"
    card["C7"], card["D7"], card["E7"] = "Sales", "-Own Project Sales", 1
    card["F7"] = "=VLOOKUP(\"Property Advisor\",sales_roles_targets[],4,0)"
    card["G7"] = "=F7*($N$1/12)"
    card["H7"], card["M7"] = ACTUAL, "own_project_sales"
    card["I7"], card["J7"] = "=IFERROR(MIN(H7/G7,1.2),0)", "=I7*E7"
    card["B9"], card["J9"] = "Total", "=SUM(J7:J7)"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def template():
    wb = Workbook()
    head = ["Employee Code", "Employee Name", "staff_role", "Primary Project"] + [
        m for m in ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())]
    for i, sheet in enumerate(sorted(wc.HFDI_TEMPLATE_SHEETS)):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = sheet
        ws.append(head)
        # own_project_sales: 5 by October (target 12 x 10/12 = 10 -> 50%).
        ws.append([101, "Pat Advisor", "Property Advisor", "Fahari"]
                  + [m / 2 for m in range(1, 11)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class HfdiTests(TestCase):
    def test_read_and_proof(self):
        data = master()
        self.assertTrue(wc.is_hfdi_workbook(data))
        self.assertFalse(wc.is_ib_workbook(data))
        book = wc.read_hfdi(data)
        self.assertEqual(book["problems"], [])            # the table reference resolved
        self.assertEqual(wc.ib_run_month(book), 10)       # mapping B4
        self.assertEqual(wc.book_year(book), 2026)        # mapping B1
        self.assertEqual([h.sales_code for h in wc.holders(book)], ["101"])   # active only
        actuals = wc.read_actuals(io.BytesIO(template()))
        self.assertEqual(wc.actuals_book(actuals), wc.HFDI)
        self.assertEqual(wc.template_months(actuals, first=4), list(range(1, 11)))
        proof = wc.ib_proof(book, actuals)
        self.assertEqual(len(proof), 1)
        self.assertTrue(proof[0]["same"], proof)          # 5 / 10 = 0.5, desk 0.5

    def test_probe_sets_each_sheet_beside_its_reader(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        wc.save_file(wc.SPECS[wc.HFDI].files[0], wc.read_hfdi(master()), "m.xlsm", "t", year=2026)
        wc.save_file(wc.SPECS[wc.HFDI].files[1], wc.read_actuals(io.BytesIO(template())),
                     "t.xlsx", "t", year=2026)
        # own_project_sales for Pat at October is 5; the reader gives 5.
        got = {"property_units": {"value": 5}, "property_value": {"value": 0}}
        out = StringIO()
        with mock.patch("apps.staff_management.live_scorecard.live_actuals", return_value=got):
            call_command("hfdi_feed_probe", "--year", "2026", stdout=out)
        text = out.getvalue()
        self.assertIn("1 active people, the desk's month 10", text)
        self.assertRegex(text, r"own_project_sales\s+property units .*\s+1\s+1\s+1 ")

    def test_load_and_card(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient

        from .live_scorecard import build_card

        client = APIClient()
        client.force_authenticate(User.objects.create_superuser("root.admin", password="x"))
        for name, data, extra in (("Master Scorecard - 2026.xlsm", master(), {}),
                                  ("Scorecard_Actual_Template_2026.xlsx", template(),
                                   {"year": "2026"})):
            r = client.post(URL, {"file": SimpleUploadedFile(name, data), "apply": "1",
                                  **extra}, format="multipart")
            self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("1 of 1 cards the desk scored for month 10 recompute", r.data["detail"])
        card = build_card("101", as_at=datetime.date(2026, 10, 31))
        self.assertAlmostEqual(card["performance_score"], 0.5)
        self.assertEqual(build_card("101", as_at=datetime.date(2026, 11, 30))["reason"],
                         "hfdi_month_not_loaded")
