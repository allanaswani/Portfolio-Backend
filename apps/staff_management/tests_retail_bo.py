"""The Retail Back Office scorecards workbook (2026_Retail_Back_Office_
Scorecards - H1.xlsm): its cards run on their own formulas, the desk's typed
figures and the figures its run read off the template; it is refused unless
every card recomputes to the score the desk's run cached on it."""
import datetime
from unittest import mock

from django.test import TestCase

from . import workbook_cards as wc

t = wc.formula_tokens
INDIRECT = ('=ABS(+VLOOKUP($C$2,INDIRECT("[2026_Actual_Template_Retail_Back_office.xlsx]"'
            '&$K{n}&"!" &"$c:$R"),$P$1,0))')


def rbo_book(cached_crm=2.0, run_month=9):
    """One RO_COMMERCIAL card the workbook's way: a typed line (approvals),
    a template line (CRM), and a line reading INITIATIVES_SRM's total. Rows
    are 0-based; the grid holds the values the desk's run cached."""
    grid = [[None] * 16 for _ in range(12)]
    grid[1][2], grid[1][4] = "Terry Simpson", "RELATIONSHIP OFFICER - COMMERCIAL"
    grid[4][1] = "KPI"
    # row 6 (index 5): typed 170 approvals, FY 100
    grid[5][1], grid[5][2], grid[5][4], grid[5][5], grid[5][7] = (
        "Financial Perspective", "BS", 0.5, 100.0, 170.0)
    # row 7 (index 6): CRM off the template, FY 120
    grid[6][2], grid[6][4], grid[6][5], grid[6][7], grid[6][10] = (
        "CRM", 0.3, 120.0, cached_crm, "Commercial_CRM")
    # row 8 (index 7): the initiatives' total
    grid[7][2], grid[7][4], grid[7][5] = "Key Initiatives", 0.2, 0.2
    grid[10][0] = "Reviewee Name:"
    f = {"0,15": t("=Constants!$B$1")}                     # P1
    for r in (5, 6, 7):
        n = r + 1
        f[f"{r},6"] = t(f"=$F{n}*((Constants!$B$2-$L{n})/12)")
        f[f"{r},8"] = t(f"=IFERROR(IF(H{n}/G{n}>1.2,1.2,H{n}/G{n}),0)")
        f[f"{r},9"] = t(f"=I{n}*E{n}")
        f[f"{r},11"] = t(f"=VLOOKUP($C$2,List!$C:$K,9,0)")
    f["6,7"] = t(INDIRECT.format(n=7))
    f["7,7"] = t("=INITIATIVES_SRM!$I$6")
    f["1,8"] = t("=SUM(J6:J8)")                            # I2
    # Its cached values, as the run for Terry in month 9 left them.
    ytd = {5: 100 * run_month / 12, 6: 120 * run_month / 12, 7: 0.2 * run_month / 12}
    initiative = min(0.1 / (1 * run_month / 12), 1.2) * 0.2   # see the sheet below
    act = {5: 170.0, 6: cached_crm, 7: initiative}
    total = 0.0
    for r in (5, 6, 7):
        grid[r][6] = ytd[r]
        grid[r][8] = min(act[r] / ytd[r], 1.2)
        grid[r][9] = grid[r][8] * grid[r][4]
        total += grid[r][9]
    grid[7][7] = initiative
    grid[1][8] = total
    # INITIATIVES_SRM: one initiative, weight 0.2 (D), FY 1 (E), F its YTD
    # target by month, G typed achievement 0.1, H score, I weighted.
    ini = [[None] * 10 for _ in range(7)]
    ini[4][3], ini[4][4], ini[4][6] = 0.2, 1.0, 0.1
    fi = {"4,5": t("=E5*Constants!$B$2/12"),
          "4,7": t("=IFERROR(IF(G5/F5>1.2,1.2,G5/F5),0)"),
          "4,8": t("=H5*D5"),
          "5,8": t("=SUM(I5:I5)")}
    lst = [["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch",
            "staff_zone", "reports_to", "reports_role", "email_cc", "email_to",
            "prorate_new", "prorate_role_change", "prorate_promotion",
            "prorate_acting_other"],
           [3966, "TS3966", "Terry Simpson", "RELATIONSHIP OFFICER - COMMERCIAL",
            "Head Office", "Head Office", "Floyd Mathias", "HEAD", "", "", 0, 0, 0, 0],
           [3521, "SN3521", "Sarah Nzeli", "RELATIONSHIP OFFICER - COMMERCIAL",
            "Head Office", "Head Office", "Floyd Mathias", "HEAD", "", "", 0, 0, 0, 0]]
    summary = [["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch",
                "staff_zone"] + [None] * 12,
               # June recorded; "October" a copy of June, after the run month.
               [3966, "TS3966", "Terry Simpson", "RO", "HO", "HO",
                None, None, None, None, None, 0.7, None, None, None, 0.7]]
    book = {"book": wc.RETAIL_BO,
            "cards": {"RO_COMMERCIAL": {"grid": grid, "f": f},
                      "INITIATIVES_SRM": {"grid": ini, "f": fi}},
            "tables": {"List": lst, "Monthly_Summary": summary,
                       "Constants": [["Month_column", run_month + 4.0],
                                     ["Month_count", float(run_month)],
                                     [None], [None], ["Year", 2026.0]]},
            "problems": []}
    return book


class RetailBackOfficeTests(TestCase):

    def setUp(self):
        for name, value in (("proration", {}), ("no_card", {})):
            patcher = mock.patch.object(wc, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_desks_run_is_its_figures_and_every_card_recomputes(self):
        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        # Terry's CRM at September, in the template's own layout.
        row = actuals["Commercial_CRM"][1]
        self.assertEqual(row[:3], [3966, "TS3966", "Terry Simpson"])
        self.assertEqual(row[6 + 8], 2.0)
        proof = wc.rbo_proof(book, actuals)
        self.assertEqual(len(proof), 1)
        self.assertTrue(proof[0]["same"], proof)

    def test_a_card_that_does_not_recompute_is_shown_as_different(self):
        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        book["cards"]["RO_COMMERCIAL"]["grid"][1][8] = 0.99   # not what it gives
        self.assertFalse(wc.rbo_proof(book, actuals)[0]["same"])

    def test_only_months_up_to_the_desks_run_are_its_scores(self):
        recorded = wc.recorded_scores(rbo_book())
        self.assertEqual(recorded, {("TS3966", 6): 0.7})   # not "October"

    def test_the_initiatives_sheet_follows_the_month(self):
        """INITIATIVES_SRM's YTD target is E*months/12: evaluated with the
        card, not its cached September value."""
        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        terry = next(h for h in wc.holders(book) if h.sales_code == "TS3966")
        sep = wc.compute(book, actuals, terry, 9)["lines"][2]
        jun = wc.compute(book, actuals, terry, 6)["lines"][2]
        self.assertAlmostEqual(sep["actual"], min(0.1 / 0.75, 1.2) * 0.2)
        self.assertAlmostEqual(jun["actual"], min(0.1 / 0.5, 1.2) * 0.2)

    def test_somebody_the_desk_did_not_run_has_no_figure_not_a_zero(self):
        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        sarah = next(h for h in wc.holders(book) if h.sales_code == "SN3521")
        card = wc.compute(book, actuals, sarah, 9)
        crm = card["lines"][1]
        self.assertEqual(crm["actual"], {"e": "#N/A"})

    def test_an_open_month_scores_the_desks_figures_at_its_own_month(self):
        """November, nothing live: the typed approvals and the template's CRM
        are the desk's year to date to September, scored at September's
        target - the card is the desk's September card."""
        from .live_scorecard import build_card

        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        spec = wc.SPECS[wc.RETAIL_BO]
        wc.save_file(spec.files[0], book, year=2026)
        wc.save_file(spec.files[1], actuals, year=2026)
        self.assertEqual(wc.rebuild(book, actuals), 2)
        sep = build_card("TS3966", as_at=datetime.date(2026, 9, 30))
        self.assertAlmostEqual(sep["performance_score"],
                               round(book["cards"]["RO_COMMERCIAL"]["grid"][1][8], 4))
        nov = build_card("TS3966", as_at=datetime.date(2026, 11, 25))
        self.assertTrue(nov["live"])
        lines = [ln for p in nov["perspectives"] for ln in p["lines"]]
        approvals, crm = lines[0], lines[1]
        self.assertEqual((approvals["ytd_target"], approvals["ytd_actual"]), (75.0, 170))
        self.assertIn("year to date to Sep 2026", approvals["as_at"])
        self.assertEqual((crm["ytd_target"], crm["ytd_actual"]), (90.0, 2.0))
        self.assertAlmostEqual(nov["performance_score"], sep["performance_score"])
        self.assertEqual(nov["staff"]["role_code"], "rbo_ro_commercial")


class RetailBackOfficeFeedTests(TestCase):
    """The individual lines' live figures (rbo_live_feeds)."""

    def setUp(self):
        for name, value in (("proration", {}), ("no_card", {})):
            patcher = mock.patch.object(wc, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_role_view_by_the_user_who_acted(self):
        """Per ActionUserName: mean of the non-zero step times, returns from
        DecisionType, turnaround per the desk's product category (SME split at
        20m)."""
        from . import rbo_live_feeds as rlf

        sep = datetime.datetime
        # app, action, created, loaded, to, from, user, NAME, code, seller,
        # branch, DecisionType, ProductCategory, ApprovedAmount, segment
        rows = [
            ("A1", sep(2026, 9, 3), sep(2026, 9, 1), sep(2026, 9, 3, 1), "BBM Review",
             "CCA Processing", "CCA mm", "Mwanzi Musyoka", "C1", "S", 200,
             "Approve", "BL", "25000000", "SME"),
            ("A1", sep(2026, 9, 9), sep(2026, 9, 1), sep(2026, 9, 9, 1),
             "STORED Archived - Disbursed", "BBM Review", "BBM x", "Someone Else",
             "C1", "S", 200, "Approve", "BL", "25000000", "SME"),
            ("A2", sep(2026, 9, 5), sep(2026, 9, 1), sep(2026, 9, 5, 1),
             "RM Processing Application Returned by CCA", "CCA Processing", "CCA mm",
             "Mwanzi Musyoka", "C2", "S", 200, "Return", "AF", "900000", "PB"),
        ]
        users = rlf.user_month(rows, 2026, 9)
        mm = users["MWANZI MUSYOKA"]["own"]
        # The report also files the generated current-status row under the name.
        self.assertEqual(users["MWANZI MUSYOKA"]["all"]["rts"], 2)
        self.assertEqual(mm["rts"], 1)
        self.assertEqual(mm["by_category"]["sme>=20m"], 2.0)          # 1 to 3 Sep
        self.assertEqual(mm["by_category"]["Asset Finance loans"], 4.0)
        self.assertEqual(mm["tat"], 3.0)
        with mock.patch.object(rlf, "iapply_users", return_value=users):
            self.assertEqual(rlf.iapply_value("RTS", "Mwanzi Musyoka", 2026, 9)[0], 1.0)
            self.assertEqual(rlf.iapply_value("SME_above_20M", "Mwanzi Musyoka", 2026, 9)[0], 2.0)
            v, _label, why = rlf.iapply_value("TOTAL_TAT", "Henry Kilonzi", 2026, 9)
            self.assertIsNone(v)                          # no action: not 0 days
            self.assertIn("no iApply action", why)

    def test_the_mapping_is_the_desks(self):
        from . import rbo_live_feeds as rlf

        self.assertEqual(rlf._category("CL", None), "Unsecured Business Loans")
        self.assertEqual(rlf._category("SP", "19999999"), "sme<20m")
        self.assertEqual(rlf._category("BL", "20000000"), "sme>=20m")
        self.assertEqual(rlf._category("HL", None), "Secured Personal")
        self.assertIsNone(rlf._category("ZZ", None))

    def _live(self, proven, got=(5.0, "CX return", "")):
        from . import rbo_live_feeds as rlf
        from .live_scorecard import build_card

        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        spec = wc.SPECS[wc.RETAIL_BO]
        wc.save_file(spec.files[0], book, year=2026)
        wc.save_file(spec.files[1], actuals, year=2026)
        wc.rebuild(book, actuals)
        with mock.patch.object(rlf, "proven", return_value=proven), \
                mock.patch.object(rlf, "value", return_value=got):
            cards = {c: build_card(c, as_at=datetime.date(2026, 11, 25))
                     for c in ("TS3966", "SN3521")}
        return {c: [ln for p in card["perspectives"] for ln in p["lines"]][1]
                for c, card in cards.items()}

    def test_a_proven_line_reads_live(self):
        crm = self._live({"Commercial_CRM": {"live": True, "matched": 1, "people": 1,
                                             "definition": None, "month": "2026-09"}})
        self.assertEqual(crm["TS3966"]["ytd_actual"], 5.0)
        self.assertIn("matched the desk's figure for 1 of 1", crm["TS3966"]["as_at"])

    def test_an_unproven_line_reads_but_cannot_score_below_the_desk(self):
        unproven = {"Commercial_CRM": {"live": False, "matched": 0, "people": 1,
                                       "definition": None, "month": "2026-09"}}
        # Read 5 CRM logs: above Terry's desk 2, so it is his figure; Sarah,
        # whom the desk has none for, gets it too.
        crm = self._live(unproven)
        self.assertEqual(crm["TS3966"]["ytd_actual"], 5.0)
        self.assertEqual(crm["SN3521"]["ytd_actual"], 5.0)
        self.assertIn("0 of 1 people matched", crm["SN3521"]["as_at"])
        # Read 1: below Terry's desk 2 on a reading not yet proven - the
        # desk's stands and the card says what was read.
        crm = self._live(unproven, got=(1.0, "CX return", ""))
        self.assertEqual(crm["TS3966"]["ytd_actual"], 2.0)
        self.assertIn("reads 1", crm["TS3966"]["as_at"])
        self.assertEqual(crm["SN3521"]["ytd_actual"], 1.0)

    def test_no_figure_waits_with_the_reason(self):
        crm = self._live({}, got=(None, "", "no row for this name on the CX return"))
        self.assertIsNone(crm["SN3521"]["score"])
        self.assertIn("no row for this name", crm["SN3521"]["pending"])

    def test_the_proof_keeps_the_reading_that_gives_the_desks_figures(self):
        from . import rbo_live_feeds as rlf

        book = rbo_book()
        actuals = wc.rbo_desk_actuals(book)
        spec = wc.SPECS[wc.RETAIL_BO]
        wc.save_file(spec.files[0], book, year=2026)
        wc.save_file(spec.files[1], actuals, year=2026)
        # Terry's desk CRM for September is 2: a reader giving 2 is live,
        # one giving 3 is not.
        with mock.patch.object(rlf, "value", return_value=(2.0, "x", "")):
            result = rlf.prove(2026, out=lambda *_: None)
        self.assertTrue(result["Commercial_CRM"]["live"])
        self.assertEqual(rlf.proven()["Commercial_CRM"]["month"], "2026-09")
        with mock.patch.object(rlf, "value", return_value=(3.0, "x", "")):
            result = rlf.prove(2026, out=lambda *_: None)
        self.assertFalse(result["Commercial_CRM"]["live"])

        # An iApply line: the definition that matches is the one kept.
        def by_definition(feed, holder, year, month, definition=None, wait=False):
            return ({"year/own": 2.0}.get(definition, 9.0), "x", "")

        actuals["RTS"] = [actuals["Commercial_CRM"][0],
                          list(actuals["Commercial_CRM"][1])]
        wc.save_file(spec.files[1], actuals, year=2026)
        with mock.patch.object(rlf, "value", side_effect=by_definition):
            result = rlf.prove(2026, out=lambda *_: None)
        self.assertEqual(result["RTS"]["definition"], "year/own")
        self.assertTrue(result["RTS"]["live"])
