"""The back-office cards, computed from the workbook's own formulas.

Against the real files (2026_BO_Non_Sales_Scorecards - Q2 with_updated_targets
.xlsb over 2026_BO_Actual_Template.xlsx) every one of the 108 September cards
the desk's macro recorded on Monthly_Summ comes out exactly - Bob Waigwa's
92.58% among them. These tests hold the evaluator to the same rules on a
small card of their own, built the way the reader builds one.
"""

import datetime

from django.test import TestCase

from . import workbook_cards as bo

CARD = "TELLER_SCORECARD"


def ref(r, c, sheet=None):
    return ["r", sheet, r, c]


def area(r1, c1, r2, c2, sheet=None):
    return ["a", sheet, r1, c1, r2, c2]


def n(v):
    return ["n", v]


def book():
    """A teller card of three lines, as read_scorecards would return it.

    Rows are 0-based: row 9 is the card's row 10.
    """
    grid = [[None] * 16 for _ in range(14)]
    grid[7][1] = "Perspective"
    grid[9][1] = "Financials 10.0%"
    for r, measure, weight, pm, feed in (
            (9, "Account Opening", 0.5, 4.0, "CASA"),
            (10, "Training hours", 0.3, 48.0, "Training_hours"),
            (11, "NPS", 0.2, 0.6, "NPS")):
        grid[r][2], grid[r][4], grid[r][5], grid[r][11] = (measure, weight,
                                                           pm, feed)
    grid[12][1] = "TOTAL SCORE:"

    def actual(r):
        # +VLOOKUP($C$2, INDIRECT("[t.xlsx]"&$L10&"!"&"$c:$R"), $O$1, 0)
        return [ref(1, 2), n("[t.xlsx]"), ref(r, 11), ["b", "&"], n("!"),
                ["b", "&"], n("$c:$R"), ["b", "&"], ["f", "INDIRECT", 1],
                ref(0, 14), n(0.0), ["f", "VLOOKUP", 4], ["u", "+"]]

    capped = lambda r, cap: [  # noqa: E731 - IF(H/G>cap, cap, H/G)
        ref(r, 7), ref(r, 6), ["b", "/"], n(cap), ["b", ">"], n(cap),
        ref(r, 7), ref(r, 6), ["b", "/"], ["f", "IF", 3]]
    f = {
        "0,14": [ref(0, 1, "Constants")],                       # O1
        # G10 = F10*('Constants'!$B$2 - M10): monthly × months elapsed
        "9,6": [ref(9, 5), ref(1, 1, "Constants"), ref(9, 12), ["b", "-"],
                ["b", "*"]],
        # G11 = F11*(('Constants'!$B$2 - M11)/12): annual × months/12
        "10,6": [ref(10, 5), ref(1, 1, "Constants"), ref(10, 12), ["b", "-"],
                 n(12.0), ["b", "/"], ["b", "*"]],
        "11,6": [ref(11, 5)],                                    # a level
        "9,7": actual(9), "10,7": actual(10), "11,7": actual(11),
        "9,8": capped(9, 1.2), "10,8": capped(10, 1.0),
        "11,8": capped(11, 1.2),
        # M = prorate, from the List: VLOOKUP($C$2, List!C:O, 13, 0)
        **{f"{r},12": [ref(1, 2), area(0, 2, 1048575, 14, "List"), n(13.0),
                       n(0.0), ["f", "VLOOKUP", 4]] for r in (9, 10, 11)},
        **{f"{r},9": [ref(r, 8), ref(r, 4), ["b", "*"]] for r in (9, 10, 11)},
        # J6 = SUM(J10:J12)/1 - tAttrSum, the compact SUM
        "5,9": [area(9, 9, 11, 9), ["f", "SUM", 1]],
    }
    list_grid = [["StaffPF-Number", "StaffSalesCode", "Staff - Name", "Role",
                  "Branch"] + [None] * 10,
                 [3783.0, "BCK3783", "Bob Waigwa", "Teller", "Kitengela"]
                 + [None] * 9 + [0.0],
                 [9999.0, "NEW9999", "New Joiner", "Teller", "Kitengela"]
                 + [None] * 9 + [6.0]]
    summ = [["PF", "SalesCode", "Name", "Role", "Branch", "Zone"]
            + [None] * 12,
            [3783.0, "BCK3783", "x", "Teller", "Kitengela", "Zone A",
             0.5] + [None] * 11]
    return {"cards": {CARD: {"grid": grid, "f": f}},
            "tables": {"List": list_grid,
                       "Constants": [["Month_column", 13.0],
                                     ["Month_count", 9.0], [None], [None],
                                     ["Year", 2026.0]],
                       "Monthly_Summ": summ},
            "problems": []}


def template(values):
    """{sheet: {name: [Jan … Dec]}} → the actuals template's grids."""
    out = {}
    for sheet, people in values.items():
        grid = [["PF", "Code", "Staff - Name", "Role", "Branch", "Zone"]
                + [f"2026-{m:02d}-01" for m in range(1, 13)]]
        for name, months in people.items():
            grid.append([1.0, "X", name, "Teller", "Kitengela", "Zone A"]
                        + months + [None] * (12 - len(months)))
        out[sheet] = grid
    return out


ACTUALS = template({
    "CASA": {"Bob Waigwa": [2, 4, 6, 8, 10, 12, 14, 20, 26],
             "New Joiner": [0, 0, 0, 0, 0, 0, 1, 2, 3]},
    "Training_hours": {"Bob Waigwa": [0, 6, 11, 15, 18, 22, 22, 22, 40],
                       "New Joiner": [0, 0, 0, 0, 0, 0, 0, 0, 5]},
    "NPS": {"Bob Waigwa": [0.5] * 8 + [0.7241379310344828]},
})


def holder(name):
    return next(h for h in bo.holders(book()) if h.name == name)


class EvaluatorTests(TestCase):

    def test_the_month_picks_the_template_column_and_the_target(self):
        card = bo.compute(book(), ACTUALS, holder("Bob Waigwa"), 9)
        opening, training, nps = card["lines"]
        self.assertEqual((opening["ytd_target"], opening["actual"]),
                         (36.0, 26))
        self.assertAlmostEqual(opening["score"], 26 / 36)
        # 48 a year, nine months gone: 36. 40 hours is over - capped at 100%.
        self.assertEqual((training["ytd_target"], training["actual"]),
                         (36.0, 40))
        self.assertEqual(training["score"], 1.0)
        self.assertEqual(nps["score"], 1.2)
        self.assertAlmostEqual(card["total"],
                               0.5 * 26 / 36 + 0.3 * 1.0 + 0.2 * 1.2)

        august = bo.compute(book(), ACTUALS, holder("Bob Waigwa"), 8)
        self.assertEqual(august["lines"][0]["ytd_target"], 32.0)
        self.assertEqual(august["lines"][0]["actual"], 20)

    def test_a_joiner_is_prorated_from_the_list(self):
        card = bo.compute(book(), ACTUALS, holder("New Joiner"), 9)
        # Six months before joining: 4 × (9 - 6) = 12.
        self.assertEqual(card["lines"][0]["ytd_target"], 12.0)

    def test_a_name_the_template_lacks_is_the_workbooks_own_na(self):
        card = bo.compute(book(), ACTUALS, holder("New Joiner"), 9)
        self.assertEqual(card["lines"][2]["actual"], {"e": "#N/A"})
        self.assertEqual(card["total"], {"e": "#N/A"})

    def test_months_ignore_a_stray_figure(self):
        stray = template({"CASA": {"Bob Waigwa": [1, 2, 3, 0, 0, 0, 0, 0, 0,
                                                  1]},
                          "KYC": {f"P{i}": [1, 1, 1] for i in range(10)}})
        self.assertEqual(bo.template_months(stray), [1, 2, 3])

    def test_excel_comparisons(self):
        self.assertTrue(bo._compare("<", 5.0, "a"))       # text after numbers
        self.assertTrue(bo._compare("=", "Bob", "bob"))   # no case
        self.assertTrue(bo._compare("=", None, 0.0))      # blank is 0
        self.assertEqual(bo._round("ROUNDUP", 2.01, 0), 3.0)


class StoredCardTests(TestCase):

    def setUp(self):
        stored = bo.rebuild(book(), ACTUALS, loaded_by="test")
        self.assertEqual(stored, 2 * 9)

    def test_the_card_page_shows_the_workbook_card(self):
        from .live_scorecard import build_card, resolve_person

        person = resolve_person("BCK3783")
        self.assertEqual(person.role_code, "bo_teller")
        self.assertEqual(person.branch, "Kitengela")
        card = build_card("BCK3783", as_at=datetime.date(2026, 9, 30))
        self.assertTrue(card["has_card"])
        self.assertAlmostEqual(card["performance_score"],
                               round(0.5 * 26 / 36 + 0.3 + 0.24, 4))
        lines = [ln for p in card["perspectives"] for ln in p["lines"]]
        self.assertEqual([ln["ytd_target"] for ln in lines], [36.0, 36.0, 0.6])
        self.assertEqual(card["coverage_note"], "")
        self.assertEqual(len(card["months_loaded"]), 9)

    def test_the_score_the_macro_recorded_wins_and_says_so(self):
        """January was recorded at 50% with that month's targets."""
        from .live_scorecard import build_card

        card = build_card("BCK3783", as_at=datetime.date(2026, 1, 31))
        self.assertEqual(card["performance_score"], 0.5)
        self.assertIn("recorded 50.0%", card["coverage_note"])

    def test_the_desks_september_figure_meets_septembers_target(self):
        """October is open and the desk's latest is September: each line
        shows September's year to date against September's target, not
        ten months of target."""
        bo.save_file("scorecards", book())
        bo.save_file("actuals", ACTUALS)
        card = bo.live_card("BCK3783", None, datetime.date(2026, 10, 31))
        lines = [ln for p in card["perspectives"] for ln in p["lines"]]
        opening, training = lines[0], lines[1]
        # 4 a month × 9 = 36, not 40; 48 a year × 9/12 = 36, not 40.
        self.assertEqual((opening["ytd_target"], opening["ytd_actual"]),
                         (36.0, 26))
        self.assertAlmostEqual(opening["score"], 26 / 36)
        self.assertEqual((training["ytd_target"], training["ytd_actual"]),
                         (36.0, 40))
        self.assertIn("(Sep 2026)", opening["as_at"])
        self.assertAlmostEqual(card["performance_score"],
                               round(0.5 * 26 / 36 + 0.3 + 0.24, 4))

    def test_a_month_before_any_card_says_so(self):
        from .live_scorecard import build_card

        # Outside the workbook's year: not a workbook card, stored or live.
        card = build_card("BCK3783", as_at=datetime.date(2025, 12, 31))
        self.assertNotIn("workbook_card", card)


def sales_book():
    """A Business_Banking card of two lines, the sales workbook's way:
    targets SUMIF'd off Summary Allocation by name, actuals by INDIRECT,
    the score in K2. Rows are 0-based."""
    sheet = "Business_Banking"
    grid = [[None] * 16 for _ in range(12)]
    grid[4][1] = "KPI"
    grid[5][1] = "Weighted sales (100.0%)"
    for r, measure, weight, feed in ((5, "New Customers", 0.6,
                                      "New_Customers"),
                                     (6, "Trade Finance", 0.4,
                                      "Trade_Finance_Income")):
        grid[r][2], grid[r][4], grid[r][12] = measure, weight, feed
    grid[10][0] = "Reviewee Name:"
    alloc = area(0, 2, 1048575, 2, "Summary Allocation")

    def actual(r):
        return [ref(1, 2), n("[2026_Actual_Template.xlsx]"), ref(r, 12),
                ["b", "&"], n("!"), ["b", "&"], n("$c:$R"), ["b", "&"],
                ["f", "INDIRECT", 1], ref(0, 13), n(0.0),
                ["f", "VLOOKUP", 4]]

    f = {
        "0,13": [ref(4, 1, "Constants")],                       # N1
        # H6 = SUMIF(alloc C, $C$2, alloc D)
        "5,7": [alloc, ref(1, 2), area(0, 3, 1048575, 3,
                                       "Summary Allocation"),
                ["f", "SUMIF", 3]],
        "6,7": [area(0, 4, 1048575, 4, "Summary Allocation"), alloc,
                ref(1, 2), ["f", "SUMIFS", 3]],
        # I = H/(12/months)
        "5,8": [ref(5, 7), n(12.0), ref(5, 1, "Constants"), ["b", "/"],
                ["b", "/"]],
        # an array formula: SUM(2^ROW(INDIRECT("1:"&months))) - 2+4+8 = 14
        "6,8": [["array"], n(2.0), n("1:"), ref(5, 1, "Constants"),
                ["b", "&"], ["f", "INDIRECT", 1], ["f", "ROW", 1],
                ["b", "^"], ["f", "SUM", 1]],
        "5,9": actual(5), "6,9": actual(6),
        **{f"{r},10": [ref(r, 9), ref(r, 8), ["b", "/"]] for r in (5, 6)},
        **{f"{r},11": [ref(r, 10), ref(r, 4), ["b", "*"]] for r in (5, 6)},
        "1,10": [area(5, 11, 6, 11), ["f", "SUM", 1]],          # K2
    }
    list_grid = [["sales_code", "name", "role", "branch", "BBM"],
                 ["CM1", "Charles Muchiri", "SME RM", "Machakos", "Boss"]]
    allocation = [["x", "y", "name", "new", "trade"],
                  [None, None, "Charles Muchiri", 24.0, 70.0]]
    summ = [[None]] * 4 + [["sales_code", "Name", "Role", "Branch"]
                           + [None] * 12,
                           ["CM1", "Charles Muchiri", "SME RM", "Machakos",
                            0.25]]
    return {"book": bo.SALES,
            "cards": {sheet: {"grid": grid, "f": f}},
            "tables": {"List": list_grid, "Summary Allocation": allocation,
                       "Constants": [["Year", 2026.0], [None], [None],
                                     [None], ["Month_column", 7.0],
                                     ["Month_count", 3.0]],
                       "Monthly_Summ": summ},
            "problems": []}


SALES_ACTUALS = template({
    "New_Customers": {"Charles Muchiri": [2, 4, 6]},
    # The card asks for "Trade_Finance_Income"; Excel ignores the case.
    "Trade_Finance_income": {"Charles Muchiri": [5, 10, 14]},
    "Asset_Drawdown": {},
})


class SalesWorkbookTests(TestCase):

    def test_targets_actuals_and_the_array_formula(self):
        book = sales_book()
        holder = bo.holders(book)[0]
        self.assertEqual(holder.sheet, "Business_Banking")
        card = bo.compute(book, SALES_ACTUALS, holder, 3)
        customers, trade = card["lines"]
        self.assertEqual(customers["pm"], 24.0)          # SUMIF
        self.assertEqual(customers["ytd_target"], 6.0)   # 24 / (12/3)
        self.assertEqual(customers["actual"], 6)
        self.assertEqual(trade["pm"], 70.0)              # SUMIFS
        self.assertEqual(trade["ytd_target"], 14.0)      # 2+4+8
        self.assertEqual(trade["actual"], 14)            # case-blind sheet
        self.assertAlmostEqual(card["total"], 1.0)

    def test_a_closed_month_is_the_workbook_card_and_an_open_one_is_not(self):
        from .live_scorecard import build_card

        book = sales_book()
        self.assertEqual(bo.actuals_book(SALES_ACTUALS), bo.SALES)
        stored = bo.rebuild(book, SALES_ACTUALS, loaded_by="test")
        self.assertEqual(stored, 3)
        march = bo.stored_month("CM1", datetime.date(2026, 3, 1), bo.SALES)
        payload = bo.card_payload(march, asked=datetime.date(2026, 3, 31))
        self.assertEqual(payload["workbook_card"], bo.SALES)
        self.assertEqual(payload["staff"]["role_code"], "sme_rm")
        self.assertEqual(payload["months_loaded"],
                         ["2026-01", "2026-02", "2026-03"])
        # January was recorded at 25% by the desk's run.
        january = bo.stored_month("CM1", datetime.date(2026, 1, 1), bo.SALES)
        self.assertEqual(january.recorded, 0.25)
        self.assertIsNone(bo.stored_month("CM1", datetime.date(2026, 4, 1),
                                          bo.SALES))
        # Not on any roster here, so the open month has no live card - but
        # it is not the workbook's either.
        self.assertNotEqual(
            build_card("CM1", as_at=datetime.date(2026, 4, 30)).get(
                "workbook_card"), bo.SALES)

    def test_the_open_month_reads_the_warehouse_on_every_rm_line(self):
        """April is open. Both lines read the warehouse against April's
        targets - no template is waited for. New Customers was found to
        give the desk's figures, so it carries no note; Trade Finance was
        found to differ, and its card says so."""
        from . import sales_live_feeds
        from .scorecard_automation.models import ScKpi

        book = sales_book()
        bo.rebuild(book, SALES_ACTUALS, loaded_by="test")
        bo.save_file("sales_scorecards", book)
        bo.save_file("sales_actuals", SALES_ACTUALS)
        for code, name, sheet in (("nc", "New Customers", "New_Customers"),
                                  ("tf", "Trade Finance",
                                   "Trade_Finance_Income")):
            ScKpi.objects.create(kpi_code=code, kpi_name=name,
                                 score_cap=1.2, actuals_sheet=sheet)
        engine = {"perspectives": [{"lines": [
            {"kpi_code": "nc", "kpi_name": "New Customers",
             "ytd_actual": 9.0},
            {"kpi_code": "tf", "kpi_name": "Trade Finance",
             "ytd_actual": 99.0}]}]}
        bo.save_file(sales_live_feeds.STORE_KIND, {
            "newcustomers|newcustomers": {
                "name": "New Customers", "match": 0.95, "live": True,
                "month": "2026-03"},
            "tradefinanceincome|tradefinance": {
                "name": "Trade Finance", "match": 0.5, "live": False,
                "month": "2026-03"}})

        card = bo.live_card("CM1", engine, datetime.date(2026, 4, 30))
        customers, trade = [ln for p in card["perspectives"]
                            for ln in p["lines"]]
        # 24 a year, four months: 8; the warehouse's 9.
        self.assertEqual((customers["ytd_target"], customers["ytd_actual"]),
                         (8.0, 9.0))
        self.assertEqual(customers["as_at"], "live, as at 30 Apr 2026")
        self.assertEqual(trade["ytd_actual"], 99.0)
        self.assertIn("differs from the desk's (matched 50% of RMs for "
                      "Mar 2026)", trade["as_at"])

    def test_a_loss_goes_into_the_card_in_the_templates_sign(self):
        """PL_Charge stores a loan loss as a negative; the engine reads the
        charge as a positive. The card's formula reads the template's sign,
        so a positive charge scored as beating a negative target."""
        from .scorecard_automation.models import ScKpi

        book = sales_book()
        bo.rebuild(book, SALES_ACTUALS, loaded_by="test")
        bo.save_file("sales_scorecards", book)
        bo.save_file("sales_actuals", SALES_ACTUALS)
        ScKpi.objects.create(kpi_code="tf", kpi_name="Trade Finance",
                             score_cap=1.2, negate=True,
                             actuals_sheet="Trade_Finance_Income")
        # The fixture's sheet only grows, so the flipped figure must be above
        # the desk's 14 to be read: -20 from the engine is +20 on the card.
        engine = {"perspectives": [{"lines": [
            {"kpi_code": "tf", "kpi_name": "Trade Finance",
             "ytd_actual": -20.0}]}]}
        card = bo.live_card("CM1", engine, datetime.date(2026, 4, 30))
        trade = [ln for p in card["perspectives"] for ln in p["lines"]][1]
        self.assertEqual(trade["ytd_actual"], 20.0)

    def test_a_line_the_warehouse_has_nothing_for_keeps_the_desk(self):
        from .scorecard_automation.models import ScKpi

        book = sales_book()
        bo.rebuild(book, SALES_ACTUALS, loaded_by="test")
        bo.save_file("sales_scorecards", book)
        bo.save_file("sales_actuals", SALES_ACTUALS)
        ScKpi.objects.create(kpi_code="nc", kpi_name="New Customers",
                             score_cap=1.2, actuals_sheet="New_Customers")
        engine = {"perspectives": [{"lines": [
            {"kpi_code": "nc", "kpi_name": "New Customers",
             "ytd_actual": None}]}]}
        card = bo.live_card("CM1", engine, datetime.date(2026, 4, 30))
        customers = card["perspectives"][0]["lines"][0]
        # The desk's March 6 against March's target 6, said so.
        self.assertEqual((customers["ytd_target"], customers["ytd_actual"]),
                         (6.0, 6))
        self.assertIn("(Mar 2026)", customers["as_at"])

    def test_the_probe_compares_the_desk_with_the_warehouse(self):
        from . import sales_live_feeds

        self.assertTrue(sales_live_feeds.same(1_000_000.0, 1_000_400.0))
        self.assertFalse(sales_live_feeds.same(1_000_000.0, 1_002_000.0))
        self.assertTrue(sales_live_feeds.same(0.9167, 0.91667))
        self.assertFalse(sales_live_feeds.same(6.0, 5.0))
