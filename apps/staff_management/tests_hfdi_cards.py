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

    def test_live_takes_the_rule_whose_change_gives_the_desks(self):
        import datetime
        from unittest import mock

        from django.core.cache import cache

        from . import hfdi_live
        from .live_scorecard import name_tokens

        cache.clear()
        self.addCleanup(cache.clear)
        book = wc.read_hfdi(master())
        actuals = wc.read_actuals(io.BytesIO(template()))
        # own_project_sales: the desk has Sep 4.5, Oct 5 for Pat. Rule A's
        # change Sep->Oct is +2 (wrong); rule B's is +0.5 (the desk's), and
        # it reads 8 by November.
        wrong = {"PA1": [0] * 8 + [1, 3, 3, 3]}
        right = {"PA1": [0] * 8 + [4.5, 5, 8, 8]}
        candidates = {"own_project_sales": [("rule A", lambda y: wrong),
                                            ("rule B", lambda y: right)]}
        holder = next(h for h in wc.holders(book) if h.sales_code == "101")
        with mock.patch.object(hfdi_live, "CANDIDATES", candidates), \
                mock.patch.object(hfdi_live, "code_map",
                                  return_value={frozenset(name_tokens("Pat Advisor")): "PA1"}):
            found = hfdi_live.proof(book, actuals, 2026)
            self.assertEqual(found["own_project_sales"][0], "rule B")
            self.assertIn("rule B: its change to Oct gives the desk's for all 1 people",
                          found["_detail"]["own_project_sales"])
            card = hfdi_live.live_hfdi_card(book, actuals, holder, datetime.date(2026, 11, 30))
        line = card["perspectives"][0]["lines"][0]
        self.assertEqual(line["ytd_actual"], 8.0)          # 5 + (8 - 5)
        self.assertIn("own_project_sales (rule B)", card["coverage_note"])

    def test_a_source_keyed_by_pf_needs_no_sales_code(self):
        import datetime
        from unittest import mock

        from django.core.cache import cache

        from . import hfdi_live

        cache.clear()
        self.addCleanup(cache.clear)
        book = wc.read_hfdi(master())
        actuals = wc.read_actuals(io.BytesIO(template()))
        by_pf = hfdi_live._by_pf(lambda y: {"101": [0] * 8 + [4.5, 5, 6, 6]})
        holder = next(h for h in wc.holders(book) if h.sales_code == "101")
        with mock.patch.object(hfdi_live, "CANDIDATES",
                               {"own_project_sales": [("seller summary", by_pf)]}), \
                mock.patch.object(hfdi_live, "code_map", return_value={}):   # no sales code
            found = hfdi_live.proof(book, actuals, 2026)
            self.assertTrue(found["own_project_sales"][2])       # by PF
            card = hfdi_live.live_hfdi_card(book, actuals, holder, datetime.date(2026, 11, 30))
        self.assertEqual(card["perspectives"][0]["lines"][0]["ytd_actual"], 6.0)   # 5 + (6 - 5)

    def test_partial_insurance_codes_as_the_report_resolves_them(self):
        from . import hfdi_live

        employees = {"EWK3561", "MM4251", "AB1111", "CD1111"}
        got = hfdi_live.resolve_partial_codes(
            {"3561", "3561.0", "MM4251", "1111", "9999", "XY3561"}, employees)
        # Four digits one employee code ends in: theirs. Shared digits, unknown
        # digits, a full code already an employee's, a lettered code: left.
        self.assertEqual(got, {"3561": "EWK3561", "3561.0": "EWK3561"})

    def test_the_sales_code_opens_the_staff_id_card(self):
        import datetime

        from django.db import connection

        from . import hfdi_live
        from .models import BoScorecard

        with connection.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS hfdi_employee_data "
                        "(sales_code varchar(20), staff_name varchar(100), active varchar(5))")
            cur.execute("SELECT column_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns WHERE table_name = 'hfdi_employee_data'")
            meta = cur.fetchall()
            cols = {r[0] for r in meta}
            values = {"sales_code": "LM4122", "staff_name": "LINDA MAKENA", "active": "1",
                      "staff_pf_number": 4122}
            # Every other required column the table has, a neutral value.
            for name, kind, nullable, default in meta:
                if name in values or nullable == "YES" or default is not None:
                    continue
                values[name] = (0 if kind in ("integer", "bigint", "smallint", "numeric",
                                              "double precision", "real")
                                else False if kind == "boolean"
                                else datetime.date(2026, 1, 1) if kind.startswith(("date", "timestamp"))
                                else "x")
            names = [c for c in values if c in cols]
            cur.execute(f"INSERT INTO hfdi_employee_data ({', '.join(names)}) "
                        f"VALUES ({', '.join(['%s'] * len(names))})", [values[c] for c in names])
        BoScorecard.objects.create(book="hfdi", sales_code="4122", staff_name="Linda Makena",
                                   sheet="Property_Advisor", month=datetime.date(2026, 10, 1))
        self.assertEqual(hfdi_live.hfdi_card_code("lm4122"), "4122")
        self.assertIsNone(hfdi_live.hfdi_card_code("ZZ9999"))   # not an HFDI code
        self.assertIsNone(hfdi_live.hfdi_card_code("4122"))     # already a staff_id

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
        # November: the card shows - no source proven here, so every line is
        # the desk's October figure, labelled so (5 against 11 months' target).
        november = build_card("101", as_at=datetime.date(2026, 11, 30))
        self.assertTrue(november["has_card"])
        self.assertAlmostEqual(november["performance_score"], 5 / 11, places=4)
        self.assertIn("Every line is the desk's October figure", november["coverage_note"])
        self.assertEqual(november["perspectives"][0]["lines"][0]["as_at"],
                         "the desk's October figure")
