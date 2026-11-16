"""The Banca DSR cards: the desk's template formulas, reproduced and checked.

The real October 2026 workbooks were checked on the laptop: all 35 Banca DSRs
gave the desk's monthly_summary score to ten decimal places, and every cell of
the card cached in the template (Victoria Mwakisha) matched. These tests build
a small workbook with the same formulas.
"""
import datetime
import io

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import banca_cards as bc

LOOK = '=+VLOOKUP($C$2,INDIRECT("[2026_Insurance_Data_Actuals_Template.xlsx]"&$L{r}&"!" &"$C:$R"),$L$1,0)'
GROWTH = ('=($F{r}*(constants!$G$1-1)/(constants!$G$1^constants!$G$2-1)) * '
          'SUM(constants!$G$1^(constants!$B$2-ROW(INDIRECT("1:"&constants!$B$2))))')
JOIN = "=$F{r}*(constants!$B$2-$M{r})/(12-M{r})"
#: row -> (weight, F, G formula, actuals sheet)
ROWS = {7: (0.1, 24, JOIN, "life_volume"), 8: (0.05, 2000000, GROWTH, "life_excl_nawiri_imarika"),
        9: (0.03, 500000, GROWTH, "nawiri_imarika"), 10: (0.1, 500000, GROWTH, "hfcb_elimu_akiba"),
        11: (0.1, 0.85, "=F11", "life_persistency"), 12: (0.07, 2500000, JOIN, "gi_insurance"),
        13: (0.07, 500000, JOIN, "medical_insurance"), 14: (0.03, 0.9, "=F14", "gwp_collection"),
        16: (0.05, 6, JOIN, "disbursements"), 17: (0.25, 6, JOIN, "accounts"),
        18: (0.1, "=VLOOKUP($C$2,target!$B:$D,3,0)", JOIN, "properties_volume"),
        19: (0, "=F18*8200000", "=F19", "properties_value"),
        21: (0, 0.8, 0.8, "nps"), 22: (0.025, 0.7, "=F22", "nps"),
        24: (0.025, 40, "=$F24*(constants!$B$2-$M24)/(12-$M24)", "training"),
        25: (0, 80, "=F25", "staff_engagement")}
PEOPLE = [(1, "DSR1", "Ann One", 0), (2, "DSR2", "Ben Two", 7)]


def template(month=10, desk=None, break_formula=False):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    c = wb.create_sheet("constants")
    c["B1"], c["B2"], c["G1"], c["G2"] = "=$B$2+4", month, 1.5, 12
    t = wb.create_sheet("target")
    t.append(["sales_code", "rm_name", "branch", "propety_target"])
    t.append(["DSR1", "Ann One", "X", 3])
    lst = wb.create_sheet("list")
    lst.append(["Pf", "sales_code", "Name", "Role", "Category", "E-Mail", "cc", "cc2",
                "prorate", "Greet", "Reports to"])
    for pf, code, name, joined in PEOPLE:
        lst.append([pf, code, name, "BANCA DSR", "Insurance", "", "", "", joined, "", "Boss"])
    ms = wb.create_sheet("monthly_summary")
    ms.append(["Pf", "sales_code", "Name", "Role", "Category"] + [f"m{i}" for i in range(1, 13)])
    for pf, code, name, _ in PEOPLE:
        row = [pf, code, name, "BANCA DSR", "Insurance"] + [None] * 12
        if desk and code in desk:
            row[4 + month] = desk[code]
        ms.append(row)
    card = wb.create_sheet(bc.CARD_SHEET)
    card["C2"] = "Ann One"
    for r, (w, f, g, sheet) in ROWS.items():
        card.cell(r, 4, f"line {r}")
        card.cell(r, 5, w)
        card.cell(r, 6, f)
        card.cell(r, 7, g.format(r=r) if isinstance(g, str) else g)
        card.cell(r, 8, LOOK.format(r=r))
        card.cell(r, 9, f"=IFERROR(MIN(H{r}/G{r},1.2),0)")
        card.cell(r, 10, f"=I{r}*E{r}")
        card.cell(r, 12, sheet)
    card["B7"] = "Financials"
    card["E27"], card["J27"] = "=SUM(E7:E25)", "=SUM(J7:J26)/E27"
    if break_formula:
        card["I7"] = "=MIN(H7/G7,1.5)"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def actuals(month=10, ann=None, ben=None):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet in {s for *_x, s in ROWS.values()} - {"properties_value", "staff_engagement"}:
        ws = wb.create_sheet(sheet)
        ws.append(["Pf", "sales_code", "Name", "Role", "Category", "Measure"])
        for pf, code, name, _ in PEOPLE:
            row = [pf, code, name, "BANCA DSR", "Insurance", None] + [None] * 12
            given = (ann if code == "DSR1" else ben) or {}
            if sheet in given:
                row[5 + month] = given[sheet]
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load(t, a):
    f = openpyxl.load_workbook(io.BytesIO(t), data_only=False)
    v = openpyxl.load_workbook(io.BytesIO(t), data_only=True)
    return bc.read_template(f, v), bc.read_actuals(openpyxl.load_workbook(io.BytesIO(a))), v


class FormulaTests(TestCase):
    def test_each_target_rule_and_score(self):
        tpl, act, _ = load(template(), actuals(ann={"life_volume": 10, "accounts": 3,
                                                    "life_excl_nawiri_imarika": 2_000_000,
                                                    "life_persistency": 0.9}))
        ann = next(p for p in tpl["people"] if p.sales_code == "DSR1")
        lines = {ln["row"]: ln for ln in bc.compute_card(tpl, act, ann, 10)["lines"]}
        self.assertAlmostEqual(lines[7]["ytd_target"], 24 * 10 / 12)       # joiner, M=0
        self.assertAlmostEqual(lines[7]["score"], 10 / 20)
        growth = 2_000_000 * 0.5 / (1.5 ** 12 - 1) * sum(1.5 ** (10 - i) for i in range(1, 11))
        self.assertAlmostEqual(lines[8]["ytd_target"], growth)
        self.assertAlmostEqual(lines[8]["score"], 1.2)                      # capped
        self.assertAlmostEqual(lines[11]["score"], 0.9 / 0.85)
        self.assertAlmostEqual(lines[18]["fy_target"], 3)                   # target sheet
        self.assertEqual(lines[19]["error"], "#REF!")                       # no such sheet
        self.assertEqual(lines[19]["score"], 0.0)
        self.assertTrue(lines[12]["empty"])

    def test_a_joiner_target_uses_the_lists_prorate(self):
        tpl, act, _ = load(template(), actuals(ben={"accounts": 2}))
        ben = next(p for p in tpl["people"] if p.sales_code == "DSR2")
        lines = {ln["row"]: ln for ln in bc.compute_card(tpl, act, ben, 10)["lines"]}
        self.assertAlmostEqual(lines[17]["ytd_target"], 6 * (10 - 7) / (12 - 7))
        self.assertEqual(lines[18]["fy_target"], None)          # not on the target sheet
        self.assertEqual(lines[18]["score"], 0.0)

    def test_a_changed_template_formula_is_refused(self):
        with self.assertRaisesRegex(bc.BancaCardError, "I7"):
            load(template(break_formula=True), actuals())


class DeskCheckTests(TestCase):
    def _cards(self, desk):
        tpl, act, v = load(template(desk=desk), actuals(ann={"accounts": 3}, ben={"accounts": 1}))
        return bc.compute_months(tpl, act, bc.desk_scores(v))

    def test_the_desks_own_score_must_be_reproduced(self):
        by_month, bad = self._cards(None)
        right = {p.sales_code: c["total"] for p, c in by_month[10]}
        by_month, bad = self._cards(right)
        self.assertEqual(bad, [])
        _, bad = self._cards({"DSR1": right["DSR1"] + 0.01})
        self.assertEqual(len(bad), 1)
        self.assertIn("DSR1", bad[0])


class LiveReaderTests(TestCase):
    """banca_live_feeds follows the insurance weighted sales report's rules."""

    def _fake(self):
        import pandas as pd

        policies = pd.DataFrame([
            # r_number, insured, product, starting_date, total, paid, code
            ("R1", "X", "LIFEPLUS INSURANCE", datetime.date(2026, 3, 5), 1000, 900, "DSR1"),
            ("R1", "X", "LIFEPLUS INSURANCE", datetime.date(2026, 4, 5), 1000, 100, "DSR1"),
            ("R2", "Y", "NAWIRI", datetime.date(2026, 10, 2), 500, 500, "DSR1"),
            ("R3", "Z", "HFCB ELIMU", datetime.date(2026, 11, 2), 300, 300, "DSR1"),
            ("R4", "W", "Medical", datetime.date(2026, 6, 1), 200, 150, "DSR 1"),
            ("R5", "V", "Motor", datetime.date(2026, 6, 1), 400, 400, "NOTONROSTER"),
        ], columns=["r_number", "insured", "product", "starting_date", "total_premiums",
                    "paid_premiums", "code"])
        types = pd.DataFrame([("LIFEPLUS INSURANCE", "life"), ("NAWIRI", "life"),
                              ("HFCB ELIMU", "life"), ("Medical", "non-life"),
                              ("Motor", "non-life")],
                             columns=["product", "life_policy_check"])
        accounts = pd.DataFrame([
            ("DSR1", "MASS", 10, 5000, 0, "ACTIVE", datetime.date(2026, 5, 1)),
            ("DSR1", "MASS", 10, 1000, 0, "ACTIVE", datetime.date(2026, 5, 1)),   # CTO < 2k
            ("DSR1", "STAFF", 10, 5000, 0, "ACTIVE", datetime.date(2026, 5, 1)),
            ("DSR1", "MASS", 10, 5000, 0, "CLOSED", datetime.date(2026, 5, 1)),
        ], columns=["sale_code", "customer_segment", "cust_cto", "account_cto",
                    "curr_24_bal", "account_status", "acc_open_date"])
        drawdowns = pd.DataFrame([
            ("DSR1", "MASS", "TERM LOAN", datetime.date(2026, 7, 1), 100.0),
            ("DSR1", "STAFF", "TERM LOAN", datetime.date(2026, 7, 1), 100.0),
            ("DSR1", "MASS", "TERM LOAN", datetime.date(2026, 11, 3), 100.0),
        ], columns=["salesperson", "customer_segment", "description", "drawdown_dt",
                    "net_drawdown"])

        def frame(sql, params=None):
            if "insurance_policies" in sql:
                return policies.copy()
            if "premium_types_mapping" in sql:
                return types.copy()
            if "daily_sales_accounts_with_cto" in sql:
                return accounts.copy()
            return drawdowns.copy()
        return frame

    def test_the_reports_rules(self):
        from unittest.mock import patch

        from . import banca_live_feeds as f

        with patch.object(f, "_frame", side_effect=self._fake()), \
                patch.object(f, "_roster_codes", return_value={"DSR1"}):
            got = f.figures(datetime.date(2026, 10, 31))
        self.assertEqual(got["life_volume"]["DSR1"], 2)       # R1 once, R2
        self.assertEqual(got["life_excl_nawiri_imarika"]["DSR1"], 1000)
        self.assertEqual(got["nawiri_imarika"]["DSR1"], 500)
        self.assertNotIn("DSR1", got["hfcb_elimu_akiba"])    # November
        self.assertEqual(got["medical_insurance"]["DSR1"], 150)   # "DSR 1" -> DSR1
        self.assertEqual(got["accounts"]["DSR1"], 1)
        self.assertEqual(got["disbursements"]["DSR1"], 1)
        self.assertNotIn("NOTONROSTER", got["gi_insurance"])
        # GWP over the whole year: (900+100+500+300+150) / (1000+1000+500+300+200)
        self.assertAlmostEqual(got["gwp_collection"]["DSR1"], round(1950 / 3000 * 100, 2) / 100)


class ProbeTests(TestCase):
    def test_numpy_figures_are_stored_as_json(self):
        """16 Nov 2026: a numpy bool from the GWP ratio crashed the save."""
        from unittest.mock import patch

        import numpy as np

        from . import banca_live_feeds as f
        from .models import BancaScorecard

        BancaScorecard.objects.create(
            sales_code="DSR1", staff_name="Ann One", month=datetime.date(2026, 10, 1),
            card={"lines": [{"sheet": "gwp_collection", "actual": 0.95},
                            {"sheet": "accounts", "actual": 3}]})
        with patch.object(f, "figures", return_value={
                "gwp_collection": {"DSR1": np.float64(0.95)},
                "accounts": {"DSR1": np.float64(3.0)}}):
            found = f.probe(2026, 10, out=lambda *_: None)
        self.assertIs(found["gwp_collection"]["live"], True)
        self.assertEqual(set(f.proven()), {"gwp_collection", "accounts", "nawiri_imarika"})


class DecidedSheetTests(TestCase):
    def test_nawiri_is_live_by_decision_without_the_desk_floor(self):
        """16 Nov 2026: Nawiri & Imarika reads the warehouse (the desk's sheet is a
        copy of Elimu & Akiba) - even a card stored before cards kept growth."""
        from unittest.mock import patch

        from . import banca_live_feeds as f
        from .live_scorecard import build_card
        from .models import BancaScorecard

        tpl, act, _ = load(template(), actuals(ann={"nawiri_imarika": 9238}))
        ann = next(p for p in tpl["people"] if p.sales_code == "DSR1")
        card = bc.compute_card(tpl, act, ann, 10)
        card.pop("growth")                       # stored before 3365165
        BancaScorecard.objects.create(sales_code="DSR1", staff_name="Ann One",
                                      month=datetime.date(2026, 10, 1), card=card,
                                      total=card["total"])
        from django.core.cache import cache
        cache.clear()
        with patch.object(f, "figures", return_value={"nawiri_imarika": {"DSR1": 3000.0}}):
            live = build_card("DSR1", as_at=datetime.date(2026, 11, 30))
        self.assertTrue(live["live"])
        line = next(ln for p in live["perspectives"] for ln in p["lines"]
                    if ln["kpi_code"].startswith("banca_nawiri"))
        self.assertEqual(line["ytd_actual"], 3000.0)          # not the desk's 9,238
        growth = 500000 * 0.5 / (1.5 ** 12 - 1) * sum(1.5 ** (11 - i) for i in range(1, 12))
        self.assertAlmostEqual(line["ytd_target"], growth)


class StoredCardTests(TestCase):
    def test_upload_stores_and_the_card_page_shows_it(self):
        from .live_scorecard import build_card

        user = get_user_model().objects.create_user("admin1", password="x", is_staff=True,
                                                    is_superuser=True)
        client = APIClient()
        client.force_authenticate(user)
        url = "/staff_management/scorecard-automation/upload-scheme/"

        def post(apply):
            data = {"template": io.BytesIO(template()), "actuals": io.BytesIO(
                actuals(ann={"accounts": 3}))}
            data["template"].name, data["actuals"].name = "Banca.xlsm", "Ins.xlsx"
            if apply:
                data["apply"] = "true"
            return client.post(url, data, format="multipart")

        shown = post(False)
        self.assertEqual(shown.status_code, 200, shown.content)
        self.assertEqual(shown.json()["book"], "banca")
        stored = post(True)
        self.assertEqual(stored.status_code, 201, stored.content)
        self.assertEqual(stored.json()["saved"], 2)
        card = build_card("DSR1", as_at=datetime.date(2026, 10, 31))
        self.assertTrue(card["has_card"])
        self.assertTrue(card["banca"])
        expected = 3 / (6 * 10 / 12) * 0.25          # accounts line only
        self.assertAlmostEqual(card["performance_score"], round(expected, 4))

        # November, with the accounts sheet proven: read live, scored at November.
        from unittest.mock import patch

        from . import banca_live_feeds as f
        from .workbook_cards import save_file

        save_file(f.STORE_KIND, {"accounts": {"match": 1.0, "live": True}})
        from django.core.cache import cache
        cache.clear()          # the live read is cached per day
        with patch.object(f, "figures", return_value={"accounts": {"DSR1": 5.0}}):
            live = build_card("DSR1", as_at=datetime.date(2026, 11, 30))
        self.assertTrue(live["live"])
        line = next(ln for p in live["perspectives"] for ln in p["lines"]
                    if ln["kpi_code"].startswith("banca_accounts"))
        self.assertEqual(line["ytd_actual"], 5.0)
        self.assertAlmostEqual(line["ytd_target"], 6 * 11 / 12)
        self.assertIn("live", line["as_at"])
        # A live reading below the desk's running total keeps the desk's.
        with patch.object(f, "figures", return_value={"accounts": {"DSR1": 1.0}}):
            from django.core.cache import cache
            cache.clear()
            live = build_card("DSR1", as_at=datetime.date(2026, 11, 30))
        line = next(ln for p in live["perspectives"] for ln in p["lines"]
                    if ln["kpi_code"].startswith("banca_accounts"))
        self.assertEqual(line["ytd_actual"], 3.0)
