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

    def _open_month_with_a_proven_feed(self, **feed):
        from unittest.mock import patch

        from . import bo_live_feeds

        bo.save_file("scorecards", book())
        bo.save_file("actuals", ACTUALS)
        bo.save_file(bo_live_feeds.STORE_KIND, {"CASA": dict({
            "kind": "code_count", "sheet": "CASA", "codes": ["1"], "rows": "all",
            "cumulative": True, "month": "2026-09"}, **feed)})
        with patch.object(bo_live_feeds, "live_value", return_value=30.0):
            return bo.live_card("BCK3783", None, datetime.date(2026, 10, 31))

    def test_only_a_proven_line_reads_live_and_the_card_says_how_many(self):
        card = self._open_month_with_a_proven_feed()
        opening, training, _ = [ln for p in card["perspectives"] for ln in p["lines"]]
        # October's own target (4 x 10), and the card's formula read the figure.
        self.assertEqual((opening["ytd_target"], opening["ytd_actual"]), (40.0, 30.0))
        self.assertAlmostEqual(opening["score"], 30 / 40)
        self.assertEqual(opening["as_at"], "live, as at 31 Oct 2026")
        self.assertIn("(Sep 2026)", training["as_at"])
        self.assertEqual(card["live_lines"], 1)
        self.assertIn("1 of 3 lines read today's figures", card["how_scored"])
        self.assertIn("2 show the desk's latest figure (up to September 2026)",
                      card["how_scored"])

    def test_nothing_proven_says_so_rather_than_calling_the_card_live(self):
        bo.save_file("scorecards", book())
        bo.save_file("actuals", ACTUALS)
        card = bo.live_card("BCK3783", None, datetime.date(2026, 10, 31))
        self.assertEqual(card["live_lines"], 0)
        self.assertIn("0 of 3 lines read today's figures", card["how_scored"])

    def test_a_feed_proven_for_another_role_leaves_this_person_on_the_desk(self):
        card = self._open_month_with_a_proven_feed(roles=["BOM"])
        opening = card["perspectives"][0]["lines"][0]
        self.assertEqual(opening["ytd_actual"], 26)
        self.assertIn("(Sep 2026)", opening["as_at"])
        self.assertEqual(card["live_lines"], 0)

    def test_a_proven_trail_figure_reaches_the_card_by_name_too(self):
        from unittest.mock import patch

        from . import bo_live_feeds

        with patch.object(bo_live_feeds, "_iapply_live", return_value=30.0) as read:
            bo.save_file("scorecards", book())
            bo.save_file("actuals", ACTUALS)
            bo.save_file(bo_live_feeds.STORE_KIND, {"CASA": {
                "kind": "iapply", "sheet": "CASA", "measure": "apps_per_day", "span": "month",
                "identity": "code", "cumulative": False, "month": "2026-09"}})
            card = bo.live_card("BCK3783", None, datetime.date(2026, 10, 31))
        self.assertEqual(card["perspectives"][0]["lines"][0]["ytd_actual"], 30.0)
        self.assertEqual(read.call_args.args[2], "Bob Waigwa")

    def test_a_figure_the_cards_formula_does_not_find_is_not_called_live(self):
        from unittest.mock import patch

        with patch.object(bo, "_put_template", return_value=True):
            card = self._open_month_with_a_proven_feed()
        opening = card["perspectives"][0]["lines"][0]
        self.assertEqual(opening["ytd_actual"], 26)
        self.assertIn("(Sep 2026)", opening["as_at"])
        self.assertEqual(card["live_lines"], 0)

    def test_a_person_is_found_by_code_first_and_then_by_name(self):
        grids = template({"CASA": {"Bob Waigwa": [1], "New Joiner": [2]}})
        grids["CASA"][2][1] = "BCK3783"
        # Code wins over a name on someone else's row.
        self.assertEqual(bo._template_row(grids, "CASA", "BCK3783", 0, "Bob Waigwa")[2],
                         "New Joiner")
        self.assertEqual(bo._template_row(grids, "CASA", "NOPE", 0, "bob waigwa")[2],
                         "Bob Waigwa")
        self.assertIsNone(bo._template_row(grids, "CASA", "NOPE"))

    def test_a_feed_proven_for_this_role_reads_live(self):
        card = self._open_month_with_a_proven_feed(roles=["Teller"])
        self.assertEqual(card["perspectives"][0]["lines"][0]["ytd_actual"], 30.0)

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

    def test_only_a_proven_rm_line_reads_the_warehouse(self):
        """April is open. New Customers was found to give the desk's figures,
        so it reads the warehouse against April's targets; Trade Finance was
        found to differ, and April is not a month the desk filled, so it reads
        April's warehouse figure too and the card says how far apart they were."""
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
        # April is a month the desk did not fill, so it is scored on April's
        # warehouse figure even though Trade Finance matched only 50% - and the
        # card says how far apart the two were (decided 9 Nov 2026).
        self.assertEqual(trade["ytd_actual"], 99.0)
        self.assertIn("differs from the desk's", trade["as_at"])

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
        from . import sales_live_feeds

        bo.save_file(sales_live_feeds.STORE_KIND, {"tradefinanceincome|tradefinance": {
            "name": "Trade Finance", "match": 0.95, "live": True, "month": "2026-03"}})
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


class BackOfficeProofTests(TestCase):
    """A back-office line goes live only by reproducing the desk's figures."""

    MEASURES = {"A1": {"rows": 430, "original": 430, "reversed": 4, "days": 10},
                "A2": {"rows": 200, "original": 200, "reversed": 1, "days": 5},
                "A3": {"rows": 330, "original": 330, "reversed": 3, "days": 11}}

    def test_transactions_per_day_worked_is_found(self):
        from . import bo_live_feeds as f

        desk = [("A1", 43.0), ("A2", 40.0), ("A3", 30.0)]
        share, ratio = f.best_ratio(desk, self.MEASURES, 21)
        self.assertEqual((share, ratio["num"], ratio["den"]), (1.0, "rows", "days"))

    def test_an_error_rate_is_found(self):
        from . import bo_live_feeds as f

        self.assertAlmostEqual(f._ratio(self.MEASURES["A1"], "reversed", "rows", 21), 4 / 430)

    def test_figures_nothing_explains_are_not_proven(self):
        from . import bo_live_feeds as f

        self.assertIsNone(f.best_ratio([("A1", 7777.0), ("A2", 8888.0)], self.MEASURES, 21))

    def test_a_person_with_no_days_gives_no_figure_rather_than_nought(self):
        from . import bo_live_feeds as f

        self.assertIsNone(f._ratio({"rows": 5, "days": 0}, "rows", "days", 21))

    def test_weekdays_leave_out_the_weekend(self):
        import datetime as dt

        from . import bo_live_feeds as f

        self.assertEqual(f._weekdays(dt.date(2026, 8, 1), dt.date(2026, 9, 1)), 21)

    def test_a_branch_feed_is_read_by_branch(self):
        from unittest.mock import patch

        from . import bb_live_feeds, bo_live_feeds as f

        feed = {"kind": "bb_branch", "feed": {"kind": "ifrs", "sheet": "PL_Charge"}}
        with patch.object(bb_live_feeds, "live_value", return_value=12.0) as read:
            self.assertEqual(f.live_value(feed, "A1", None, branch="Meru"), 12.0)
        read.assert_called_once_with(feed["feed"], "Meru", None)

    def test_a_small_rate_must_really_be_close(self):
        from . import bo_live_feeds as f

        self.assertFalse(f._close(0.003, 0.012))
        self.assertTrue(f._close(0.003, 0.00301))
        self.assertTrue(f._close(43.0, 43.1))
        self.assertFalse(f._close(43.0, 44.0))
        self.assertFalse(f._close(5.0, None))

    def test_everybody_having_the_same_figure_proves_nothing(self):
        from . import bo_live_feeds as f

        self.assertFalse(f._varied([1.0, 1.0, 1.0, 1.0, 1.0]))
        self.assertTrue(f._varied([1.0, 2.0, 3.0]))

    def test_every_feed_can_be_described_in_words(self):
        from . import bo_live_feeds as f

        self.assertIn("day worked", f.describe({"kind": "ratio", "label": "rows per day worked"}))
        self.assertIn("(Teller)", f.describe({"kind": "ratio", "label": "x", "roles": ["Teller"]}))
        self.assertIn("branch figure", f.describe({"kind": "bb_branch", "feed": {"label": "IFRS"}}))


class AccountOpeningTrailProofTests(TestCase):
    """RBO lines measure who actioned a step, as the accounts-TAT report does."""

    def _months(self, **month):
        from . import bo_live_feeds as f

        return {8: {**dict.fromkeys(f.IAPPLY_FIELDS, 0.0), **month}}

    def test_each_measure_is_the_reports_arithmetic(self):
        from . import bo_live_feeds as f

        m = self._months(apps=90, actions=300, days=10, returned=9, pb_time=20, pb_steps=10,
                         bb_time=9, bb_steps=3)
        read = lambda name: f.iapply_value(m, name, "month", 8, None, 2026)  # noqa: E731
        self.assertEqual(read("tat_pb"), 2.0)
        self.assertEqual(read("tat_bb"), 3.0)
        self.assertEqual(read("apps_per_day"), 9.0)
        self.assertEqual(read("returned_of_apps"), 0.1)
        self.assertEqual(read("apps_per_weekday"), 90 / 21)

    def test_a_running_average_counts_from_the_sheets_first_month(self):
        from . import bo_live_feeds as f

        m = {5: {"pb_time": 100.0, "pb_steps": 1.0}, 6: {"pb_time": 4.0, "pb_steps": 2.0},
             7: {"pb_time": 2.0, "pb_steps": 2.0}}
        self.assertEqual(f.iapply_value(m, "tat_pb", "running", 7, 6, 2026), 1.5)
        self.assertEqual(f.iapply_value(m, "tat_pb", "month", 7, 6, 2026), 1.0)
        self.assertEqual(f.iapply_value(m, "tat_pb", "ytd", 7, 6, 2026), 106 / 5)

    def _people(self):
        names = {"ann one": "AA1", "ben two": "BB2", "cy three": "CC3", "di four": "DD4",
                 "ed five": "EE5", "flo six": "FF6"}
        by_user = {c: {7: {"pb_time": 2.0 * (n + 1), "pb_steps": 2.0},
                       8: {"pb_time": 6.0 * (n + 1), "pb_steps": 2.0}}
                   for n, c in enumerate(names.values())}
        return names, by_user

    def test_the_right_definition_is_found_and_checked_on_the_month_before(self):
        from . import bo_live_feeds as f

        names, by_user = self._people()
        desk = {n: 3.0 * (i + 1) for i, n in enumerate(names)}
        prior = {n: 1.0 * (i + 1) for i, n in enumerate(names)}
        share, feed, seen = f.prove_iapply(desk, prior, list(names.items()), by_user, 2026, 8, 7)
        self.assertEqual((share, seen), (1.0, 6))
        self.assertEqual((feed["measure"], feed["span"], feed["identity"]),
                         ("tat_pb", "month", "code"))

    def test_a_match_that_fails_the_month_before_is_not_a_match(self):
        from . import bo_live_feeds as f

        names, by_user = self._people()
        desk = {n: 3.0 * (i + 1) for i, n in enumerate(names)}
        prior = {n: 77.0 for n in names}
        found = f.prove_iapply(desk, prior, list(names.items()), by_user, 2026, 8, 7)
        self.assertIsNone(found)

    def test_a_sign_in_name_is_tried_when_the_code_finds_nobody(self):
        from . import bo_live_feeds as f

        self.assertEqual(f._iapply_key("BN4018", "Brian Njenga", "username"), "BRIAN.NJENGA")
        names, by_user = self._people()
        renamed = {f._iapply_key("", n, "username"): by_user[c] for n, c in names.items()}
        desk = {n: 3.0 * (i + 1) for i, n in enumerate(names)}
        _, feed, _ = f.prove_iapply(desk, {}, list(names.items()), renamed, 2026, 8, 7)
        self.assertEqual(feed["identity"], "username")

    def test_the_trail_writes_an_initial_and_a_name(self):
        from . import bo_live_feeds as f

        self.assertEqual(f.login_map(["eunice gititi"], {"EGITITI": {}}),
                         {"eunice gititi": "EGITITI"})
        # The surname may come first on the List, and a middle name may be the one used.
        self.assertEqual(f.login_map(["kuria john mwangi"], {"JKURIA": {}}),
                         {"kuria john mwangi": "JKURIA"})

    def test_a_sign_in_two_people_could_hold_goes_to_neither(self):
        from . import bo_live_feeds as f

        self.assertEqual(f.login_map(["john kuria", "jane kuria"], {"JKURIA": {}}), {})

    def test_a_person_with_two_possible_sign_ins_is_left_out(self):
        from . import bo_live_feeds as f

        self.assertEqual(f.login_map(["john kuria"], {"JKURIA": {}, "KJOHN": {}}), {})

    def _logins(self):
        names, by_user = self._people()
        written = {"ann one": "AONE", "ben two": "BTWO", "cy three": "CTHREE",
                   "di four": "DFOUR", "ed five": "EFIVE", "flo six": "FSIX"}
        return names, {written[n]: by_user[c] for n, c in names.items()}

    def test_the_proof_finds_people_by_their_sign_in(self):
        from . import bo_live_feeds as f

        names, trail = self._logins()
        desk = {n: 3.0 * (i + 1) for i, n in enumerate(names)}
        share, feed, _ = f.prove_iapply(desk, {}, list(names.items()), trail, 2026, 8, 7)
        self.assertEqual((share, feed["identity"]), (1.0, "login"))
        self.assertEqual(feed["logins"]["ben two"], "BTWO")

    def test_a_card_reads_only_the_sign_in_the_proof_checked(self):
        from unittest.mock import patch

        from django.core.cache import cache

        from . import bo_live_feeds as f

        names, trail = self._logins()
        rows = [(u, m, *[v.get(k, 0.0) for k in f.IAPPLY_FIELDS])
                for u, months in trail.items() for m, v in months.items()]
        feed = {"kind": "iapply", "measure": "tat_pb", "span": "month", "identity": "login",
                "logins": {"ben two": "BTWO"}}
        day = datetime.date(2026, 8, 31)
        cache.delete(f"bo_iapply:{day.isoformat()}")
        with patch.object(f, "_iapply_rows", return_value=rows):
            self.assertEqual(f._iapply_live(feed, "BB2", "Ben Two", day), 6.0)
            self.assertIsNone(f._iapply_live(feed, "AA1", "Ann One", day))
        cache.delete(f"bo_iapply:{day.isoformat()}")

    def test_the_query_runs_on_the_real_engine(self):
        """The table's shape, as accounts_tat.py names it: text dates, mixed ids."""
        from django.db import connection

        from . import bo_live_feeds as f

        if connection.vendor != "postgresql":
            self.skipTest("the trail query is PostgreSQL")
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS iapply_accounts_tat")
            cur.execute("DROP TABLE IF EXISTS customers")
            cur.execute('''CREATE TABLE iapply_accounts_tat ("ApplicationId" varchar(40),
                "Customerid" varchar(40), "CreationDate" varchar(40),
                "ActionDate" timestamp, "StatusTo" varchar(80),
                "ActionUser" varchar(40), "ActionUserName" varchar(80))''')
            cur.execute("CREATE TABLE customers (cust_id bigint, segment varchar(60))")
            cur.execute("INSERT INTO customers VALUES (1, 'MASS'), (2, 'SMALL ENTERPRISES')")
            for row in (
                    ("A", "1", "2026-08-01 08:00:00", "2026-08-02 08:00:00", "RBO", "bn4018", "Brian Njenga"),
                    ("A", "1", "2026-08-01 08:00:00", "2026-08-05 08:00:00", "Stored", "BN4018", "Brian Njenga"),
                    ("B", "C-2", "bad date", "2026-08-03 08:00:00", "RBO", "BN4018", "Returned to CSO"),
                    ("C", "2", "2026-08-01 08:00:00", "2026-08-04 08:00:00", "RBO", "BN4018", "Brian Njenga")):
                cur.execute('''INSERT INTO iapply_accounts_tat ("ApplicationId", "Customerid",
                    "CreationDate", "ActionDate", "StatusTo", "ActionUser", "ActionUserName")
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''', row)
        out = f._iapply_by_user(f._iapply_rows(2026, datetime.date(2026, 9, 1), 30000))
        got = out["BN4018"][8]
        self.assertEqual((got["apps"], got["actions"], got["returned"]), (3.0, 4.0, 1.0))
        # A's first step is one day; its closing step counts for nothing.
        self.assertEqual((got["pb_time"], got["pb_steps"]), (1.0, 1.0))
        self.assertEqual((got["bb_time"], got["bb_steps"]), (3.0, 1.0))


class WholeBackOfficeProofTests(TestCase):
    """The whole proof, start to finish, over a diary of six tellers."""

    PEOPLE = {"AA1": ("Ann One", "Meru", 100, 10), "BB2": ("Ben Two", "Thika", 200, 8),
              "CC3": ("Cy Three", "Nyeri", 300, 12), "DD4": ("Di Four", "Embu", 110, 11),
              "EE5": ("Ed Five", "Kisii", 90, 6), "FF6": ("Flo Six", "Nakuru", 400, 20)}

    def setUp(self):
        from . import bo_live_feeds

        self.f = bo_live_feeds
        grids = book()
        grids["tables"]["List"] = grids["tables"]["List"][:1] + [
            [float(i), code, who[0], "Teller", who[1]] + [None] * 9 + [0.0]
            for i, (code, who) in enumerate(self.PEOPLE.items())]
        self.book = grids

    def _load(self, productivity):
        rows = {who[0]: [0] * 7 + [value] for who, value in productivity}
        charge = {who[0]: [0] * 7 + [float(n + 1) * 1000]
                  for n, who in enumerate(self.PEOPLE.values())}
        bo.save_file("scorecards", self.book)
        bo.save_file("actuals", template({"Trx_Productivity": rows, "PL_Charge": charge}))

    def _diary(self, sql, params, timeout_ms):
        if "trx_code, max(trx_name)" in sql:
            return [(c, "T1", "TELLER", w[2], w[2]) for c, w in self.PEOPLE.items()]
        if "transaction_ref" in sql:
            names = list(self.f.MEASURES)
            out = []
            for c, w in self.PEOPLE.items():
                values = dict.fromkeys(names, w[2])
                values.update(days=w[3], reversed=1)
                out.append((c, *[values[n] for n in names]))
            return out
        return [(c, w[3], w[2]) for c, w in self.PEOPLE.items()]

    def _prove(self, **patches):
        from unittest.mock import patch

        from . import bb_live_feeds

        log = []
        totals = patches.get("totals", {})
        with (patch.object(self.f, "_rows", side_effect=self._diary)), \
                patch.object(bb_live_feeds, "_totals", return_value=totals), \
                patch.object(bb_live_feeds, "_branch_total",
                             side_effect=lambda t, branch, feed: t.get(branch)):
            found = self.f.probe(2026, 8, out=log.append)
        return found, log

    def test_a_sheet_that_matches_goes_live_and_one_that_stops_is_dropped(self):
        self._load([(w, w[2] / w[3]) for w in self.PEOPLE.values()])
        found, _ = self._prove()
        feed = found["Trx_Productivity"]
        self.assertEqual((feed["kind"], feed["den"], feed["match"]), ("ratio", "days", 1.0))
        self.assertIn("Trx_Productivity", self.f.proven())

        # The next month's desk figures no longer follow the diary.
        self._load([(w, 1000.0 + n) for n, w in enumerate(self.PEOPLE.values())])
        found, log = self._prove()
        self.assertNotIn("Trx_Productivity", found)
        self.assertNotIn("Trx_Productivity", self.f.proven())
        self.assertTrue(any("back to the desk's figure: Trx_Productivity" in x for x in log))

    def test_a_branch_sheet_can_go_live_from_the_branch_managers_reading(self):
        self._load([(w, 1000.0 + n) for n, w in enumerate(self.PEOPLE.values())])
        totals = {w[1]: float(n + 1) * 1000 for n, w in enumerate(self.PEOPLE.values())}
        found, _ = self._prove(totals=totals)
        feed = found["PL_Charge"]
        self.assertEqual((feed["kind"], feed["match"]), ("bb_branch", 1.0))
        self.assertEqual(feed["feed"]["sheet"], "PL_Charge")

    def test_nothing_is_proven_when_nothing_matches(self):
        self._load([(w, 1000.0 + n) for n, w in enumerate(self.PEOPLE.values())])
        found, _ = self._prove()
        self.assertEqual(found, {})


class TheProofMustNotCompareTheDeskWithItselfTests(TestCase):
    def setUp(self):
        self.assertEqual(bo.rebuild(book(), ACTUALS, loaded_by="test"), 2 * 9)
        bo.save_file("scorecards", book())
        bo.save_file("actuals", ACTUALS)

    def test_a_closed_month_asked_for_the_warehouse_is_not_the_stored_card(self):
        from .live_scorecard import _engine_card

        as_at = datetime.date(2026, 9, 30)
        self.assertIn("workbook_card", _engine_card("BCK3783", as_at=as_at))
        self.assertNotIn("workbook_card",
                         _engine_card("BCK3783", as_at=as_at, warehouse_only=True))

    def test_an_old_result_from_the_desk_against_itself_is_not_live(self):
        from . import bo_live_feeds as f

        bo.save_file(f.ENGINE_STORE_KIND, {"casa|accountopening": {
            "name": "Account Opening", "match": 1.0, "live": True}})
        self.assertFalse(f.engine_proven()["casa|accountopening"]["live"])

    def test_a_real_result_stays_live(self):
        from . import bo_live_feeds as f

        bo.save_file(f.ENGINE_STORE_KIND, {"casa|accountopening": {
            "name": "Account Opening", "match": 1.0, "live": True, "warehouse_read": True}})
        self.assertTrue(f.engine_proven()["casa|accountopening"]["live"])


class PropertyDefinitionTests(TestCase):
    """What each definition asks the warehouse for; the proof decides which is right."""

    def _sql(self, **options):
        from unittest.mock import patch

        from . import bb_live_feeds as f

        with patch.object(f, "_rows", return_value=[]) as rows:
            f._totals(dict({"kind": "property", "measure": "volume"}, **options), 2026, 9, 1000)
        return rows.call_args[0][0]

    def test_the_first_definition_is_unchanged(self):
        sql = self._sql()
        self.assertIn("COALESCE(sale_month, booking_date)", sql)
        self.assertIn("hfdi_projects_inventory_sales_data", sql)
        self.assertNotIn("employee_table", sql)

    def test_the_reports_rule_does_not_count_a_booking_as_a_sale(self):
        self.assertNotIn("booking_date", self._sql(dated="sale"))

    def test_the_weighted_report_reads_its_own_table(self):
        sql = self._sql(dated="sale", source="weighted")
        self.assertIn("hfdi_weighted_dashboard_sales_data", sql)
        self.assertNotIn("hfdi_projects_inventory_sales_data", sql)
        self.assertNotIn("booking_date", sql)

    def test_the_seller_can_be_found_through_their_pf(self):
        sql = self._sql(dated="sale", seller="pf")
        self.assertIn("FROM employee_table e", sql)
        self.assertIn("FLOOR(d.staff_pf_number::numeric) = FLOOR(e.staff_id::numeric)", sql)

    def test_every_definition_runs_on_the_real_engine(self):
        from django.db import connection

        from . import bb_live_feeds as f

        if connection.vendor != "postgresql":
            self.skipTest("the property query is PostgreSQL")
        columns = ("project_name varchar(80), unit_name varchar(80), staff_name varchar(80), "
                   "unit_value numeric, sale_month date")
        with connection.cursor() as cur:
            for table in ("weighted_dashboard_manual_sales_table", "employee_table",
                          "hfdi_projects_inventory_sales_data", "branch_employee_dmc_data",
                          "hfdi_weighted_dashboard_sales_data"):
                cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            cur.execute(f"CREATE TABLE weighted_dashboard_manual_sales_table ({columns}, booking_date date)")
            cur.execute(f"CREATE TABLE hfdi_projects_inventory_sales_data ({columns}, booking_date date)")
            # The weighted report's table is deliberately given no booking date.
            cur.execute(f"CREATE TABLE hfdi_weighted_dashboard_sales_data ({columns})")
            cur.execute("CREATE TABLE employee_table (staff_id numeric, name varchar(80))")
            cur.execute("""CREATE TABLE branch_employee_dmc_data (staff_pf_number integer,
                           staff_name varchar(80), staff_branch varchar(80))""")
            cur.execute("INSERT INTO employee_table VALUES (4018, 'Brian Njenga')")
            # The roster spells them differently, so only the PF finds them.
            cur.execute("INSERT INTO branch_employee_dmc_data VALUES (4018, 'B. Njenga', 'THIKA')")
            for table in ("hfdi_projects_inventory_sales_data", "weighted_dashboard_manual_sales_table"):
                cur.execute(f"""INSERT INTO {table} VALUES
                    ('P', '1', 'Brian Njenga', 100, '2026-08-10', '2026-08-01'),
                    ('P', '2', 'Brian Njenga', 100, NULL, '2026-08-01')""")
            cur.execute("""INSERT INTO hfdi_weighted_dashboard_sales_data VALUES
                    ('P', '1', 'Brian Njenga', 100, '2026-08-10')""")
        thika = f.branch_key("THIKA")
        for key in ("Plot_Sales_Volume", "Plot_Sales_Value"):
            for _label, kind, options in f.DEFINITIONS[key]:
                f._totals({"kind": kind, **options}, 2026, 9, 30000)
        read = lambda **o: f._totals(  # noqa: E731
            {"kind": "property", "measure": "volume", **o}, 2026, 9, 30000)
        self.assertEqual(read(), {})  # the name differs on the roster
        self.assertEqual(read(seller="pf"), {thika: 2.0})  # a booking counted as a sale
        self.assertEqual(read(seller="pf", dated="sale"), {thika: 1.0})
        self.assertEqual(read(seller="pf", dated="sale", source="weighted"), {thika: 1.0})

    def test_every_listed_definition_builds(self):
        from . import bb_live_feeds as f

        for key in ("Plot_Sales_Volume", "Plot_Sales_Value"):
            self.assertEqual(len(f.DEFINITIONS[key]), 4)
            for _label, kind, options in f.DEFINITIONS[key]:
                self.assertIn("one_per_unit", self._sql(**{"kind": kind, **options}))


class BranchProofTests(TestCase):
    """The branch proof, over a template and a warehouse of its own."""

    DEFINITIONS = {"Plot_Sales_Volume": [("units", "property", {"zeros": True})]}

    def _prove(self, desk, warehouse, month=10):
        from unittest.mock import patch

        from . import bb_live_feeds as f

        people = [type("H", (), {"sales_code": f"C{i}", "branch": f"B{i}"})()
                  for i in range(len(desk))]
        rows = [["x"] * 6 + ["m"] * 12] + [
            [1, f"C{i}", "n", "r", "b", "z"] + [0.0] * (month - 1) + [v]
            for i, v in enumerate(desk)]
        actuals = {"Plot_Sales_Volume": rows}
        log = []
        with patch.object(f, "DEFINITIONS", self.DEFINITIONS), \
                patch.object(f, "_branch_managers", return_value=(people, actuals)), \
                patch.object(f, "_totals", return_value={}), \
                patch.object(f, "_branch_total",
                             side_effect=lambda t, branch, feed: warehouse[int(branch[1:])]):
            found = f.probe(2026, month, out=log.append)
        return found, log

    def test_a_month_of_noughts_proves_nothing(self):
        """October: 22 blank branches, 19 of them nought in the warehouse too."""
        found, log = self._prove([0.0] * 22, [0.0] * 19 + [1.0] * 3)
        self.assertEqual(found, {})
        self.assertIn("skipped", log[0])

    def test_real_figures_that_match_go_live(self):
        found, _ = self._prove([1.0, 2.0, 3.0, 0.0], [1.0, 2.0, 3.0, 0.0])
        self.assertIn("Plot_Sales_Volume", found)

    def test_a_sheet_that_stops_passing_is_dropped(self):
        from . import bb_live_feeds as f

        bo.save_file(f.STORE_KIND, {"Plot_Sales_Volume": {"kind": "property", "sheet": "x"}})
        _, log = self._prove([100.0, 200.0, 300.0], [1.0, 2.0, 3.0])
        self.assertNotIn("Plot_Sales_Volume", f.proven())
        self.assertTrue(any("back to the desk's figure" in x for x in log))

    def test_a_month_not_filled_in_leaves_what_was_proven(self):
        from . import bb_live_feeds as f

        bo.save_file(f.STORE_KIND, {"Plot_Sales_Volume": {"kind": "property", "sheet": "x", "match": 0.9}})
        self._prove([0.0] * 5, [0.0] * 5)
        self.assertIn("Plot_Sales_Volume", f.proven())

    def test_close_on_the_median_alone_is_not_enough(self):
        """Every branch 5% off: the median is well inside the old 10%, none within 2%."""
        from . import bb_live_feeds as f

        found, log = self._prove([100.0, 200.0, 300.0], [105.0, 210.0, 315.0])
        self.assertEqual(found, {})
        self.assertNotIn("Plot_Sales_Volume", f.proven())
        self.assertTrue(any("median branch 5.0% off" in x and "not good enough" in x for x in log))

    def test_a_result_that_passed_on_the_median_stops_counting_at_once(self):
        from . import bb_live_feeds as f

        bo.save_file(f.STORE_KIND, {
            "Active_Customers": {"kind": "active", "sheet": "x", "match": 0.59, "median": 0.019},
            "Deposit_Growth": {"kind": "deposits", "sheet": "y", "match": 1.0, "median": 0.0}})
        self.assertEqual(list(f.proven()), ["Deposit_Growth"])


class FeedProofScreenTests(TestCase):
    URL = "/staff_management/scorecard-automation/feed-proof/"

    def setUp(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_superuser("root.admin", password="x"))

    def test_nobody_else_may_open_or_run_it(self):
        from django.contrib.auth.models import User

        self.client.force_authenticate(User.objects.create_user("some.one"))
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.assertEqual(self.client.post(self.URL, {"book": "sales", "month": "2026-08"},
                                          format="json").status_code, 403)

    def test_a_bad_request_is_refused(self):
        for body in ({"book": "x", "month": "2026-08"}, {"book": "sales", "month": "soon"},
                     {"book": "sales", "month": "2026-13"}):
            self.assertEqual(self.client.post(self.URL, body, format="json").status_code, 400)

    def test_a_run_records_what_happened_even_when_it_fails(self):
        from unittest.mock import patch

        from . import feed_proof

        with patch.object(feed_proof, "_run_book", side_effect=RuntimeError("no warehouse")):
            state = feed_proof.run("sales", 2026, 8, "root.admin")
        self.assertEqual(state["state"], "failed")
        self.assertIn("no warehouse", state["log"][-1])
        self.assertEqual(feed_proof.status()["state"], "failed")

    def test_only_one_run_at_a_time(self):
        from unittest.mock import patch

        from . import feed_proof

        with patch.object(feed_proof, "status", return_value={
                "state": "running", "started_at": feed_proof._now().isoformat()}):
            self.assertFalse(feed_proof.start("sales", 2026, 8))
            self.assertEqual(self.client.post(self.URL, {"book": "sales", "month": "2026-08"},
                                              format="json").status_code, 409)

    def test_a_run_that_died_does_not_block_the_next(self):
        import datetime as dt

        from . import feed_proof

        old = (feed_proof._now() - dt.timedelta(hours=4)).isoformat()
        self.assertFalse(feed_proof._is_running({"state": "running", "started_at": old}))

    def test_the_screen_says_when_a_run_died(self):
        import datetime as dt

        from . import feed_proof
        from .workbook_cards import save_file

        old = (feed_proof._now() - dt.timedelta(hours=2)).isoformat()
        save_file(feed_proof.STATUS_KIND, {"state": "running", "started_at": old,
                                           "updated_at": old, "log": []})
        state = self.client.get(self.URL).json()["status"]
        self.assertEqual(state["state"], "stopped")
        self.assertIn("Run it again", state["log"][-1])

    def test_a_second_press_is_refused_once_a_run_has_started(self):
        from unittest.mock import patch

        from . import feed_proof

        with patch.object(feed_proof.threading, "Thread"):
            self.assertTrue(feed_proof.start("sales", 2026, 8, "root.admin"))
            self.assertFalse(feed_proof.start("sales", 2026, 8, "root.admin"))

    def _template_through_august(self):
        grid = template({"CASA": {f"P{i}": [1] * 8 for i in range(10)}})
        bo.save_file("actuals", grid)
        bo.save_file("sales_actuals", grid)

    def test_a_month_the_desk_has_not_loaded_is_refused(self):
        self._template_through_august()
        year = __import__("apps.staff_management.feed_proof", fromlist=["x"])._now().year
        response = self.client.post(self.URL, {"book": "sales", "month": f"{year}-10"},
                                    format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"Its latest month is {year}-08", response.json()["detail"])

    def test_the_screen_offers_only_the_months_the_desk_has(self):
        from . import feed_proof

        self._template_through_august()
        year = feed_proof._now().year
        months = self.client.get(self.URL).json()["months"]
        self.assertEqual(months["sales"][-1], f"{year}-08")
        self.assertEqual(months["back_office"], [f"{year}-{m:02d}" for m in range(1, 9)])
        self.assertEqual(months["scheme"], [])

    def test_too_few_to_compare_never_replaces_a_result(self):
        from unittest.mock import patch

        from . import sales_live_feeds as f

        bo.save_file(f.STORE_KIND, {"newcustomers|newcustomers": {
            "name": "New Customers", "match": 0.95, "live": True, "month": "2026-08"}})
        bo.save_file("sales_scorecards", {"tables": {}, "cards": {}})
        bo.save_file("sales_actuals", {})
        line = {"feed": "New_Customers", "measure": "New Customers", "initiative": ""}
        person = type("P", (), {"sales_code": "A1", "name": "A"})()
        with patch.object(f, "_people", return_value=[person]), \
                patch.object(f, "_pairs", return_value=[(line, 0, 5.0)]):
            f.probe(2026, 10, out=lambda *_: None)
        self.assertTrue(f.proven()["newcustomers|newcustomers"]["live"])

    def test_an_empty_diary_month_says_so_and_not_that_codes_are_wrong(self):
        from unittest.mock import patch

        from . import bo_live_feeds as f

        bo.save_file("scorecards", book())
        bo.save_file("actuals", ACTUALS)
        bo.save_file(f.STORE_KIND, {"CASA": {"kind": "ratio", "sheet": "CASA"}})
        log = []
        with patch.object(f, "_rows", return_value=[]):
            self.assertEqual(f.probe(2026, 10, out=log.append), {})
        self.assertIn("transaction_diary has no rows for October 2026", log[-1])
        self.assertIn("CASA", f.proven())

    def test_the_screen_shows_nothing_proven_yet(self):
        data = self.client.get(self.URL).json()
        self.assertEqual(data["summary"]["back_office"], [])


class RunningTotalInTheLatestMonthTests(TestCase):
    """A running total cannot fall: a nought after a figure in the desk's latest
    month is a cell the desk had not filled, not a fall (Naomi Kagiri, Thika:
    Value of Property Sales 29m Jul, 38m Aug, 0 Sep on the 30 Oct template)."""

    @staticmethod
    def _sheet(sept_naomi, sept_other=5):
        head = ["PF", "Code", "Name", "Role", "Branch", "Zone"] + list(range(1, 13))
        naomi = [1466, "NWK1466", "Naomi Kagiri", "BM", "Thika", "Zone A",
                 0, 0, 0, 0, 0, 0, 29_000_000, 38_000_000, sept_naomi, 0, 0, 0]
        other = [1, "AB1", "Other", "BM", "Embu", "Zone B",
                 0, 0, 0, 0, 0, 0, 1, 2, sept_other, 0, 0, 0]
        return {"Plot_Sales_Value": [head, naomi, other]}

    def _naomi(self, actuals, month):
        from .workbook_cards import _carry_forward

        _carry_forward(actuals, "Plot_Sales_Value", month)
        return actuals["Plot_Sales_Value"][1][5 + month]

    def test_a_nought_after_a_figure_keeps_the_figure(self):
        self.assertEqual(self._naomi(self._sheet(0), 9), 38_000_000)
        self.assertEqual(self._naomi(self._sheet(0), 11), 38_000_000)

    def test_a_figure_the_desk_entered_stands(self):
        self.assertEqual(self._naomi(self._sheet(40_000_000), 9), 40_000_000)


class StoredCardRunningTotalTests(TestCase):
    """The stored (closed-month) card applies the running-total rule too: the
    desk's own workbook scored Naomi Kagiri's September Value of Property Sales
    at 38m while the uploaded template still had 0 in September."""

    def test_an_unfilled_running_total_takes_the_last_figure(self):
        from .workbook_cards import running_totals_filled

        head = ["PF", "Code", "Name", "Role", "Branch", "Zone"] + list(range(1, 13))
        row = [1466, "NWK1466", "Naomi", "BM", "Thika", "Zone A",
               0, 0, 0, 0, 0, 0, 29, 38, 0, 0, 0, 0]
        rate = [1466, "NWK1466", "Naomi", "BM", "Thika", "Zone A",
                0, 0, 0, 0, 0, 0, 0.5, 0.6, 0, 0, 0, 0]
        actuals = {"Plot_Sales_Value": [head, row], "PAR": [head, rate]}
        filled = running_totals_filled(actuals, 9)
        self.assertEqual(filled["Plot_Sales_Value"][1][14], 38)
        # Not a running total: the desk's nought stands, and the original is untouched.
        self.assertEqual(filled["PAR"][1][14], 0)
        self.assertEqual(actuals["Plot_Sales_Value"][1][14], 0)

    def test_a_filled_running_total_shows_the_recomputed_score(self):
        """The desk's recorded 73.8% predates Naomi's 38m year to date; the
        recomputed 75.6% is shown and the card says why."""
        import datetime as _dt

        from .workbook_cards import card_payload

        rec = type("R", (), {})()
        rec.book, rec.total, rec.recorded = "branch_business", 0.756, 0.738
        rec.card = {"lines": [], "filled_running_totals": ["Value of Property Sales"]}
        rec.month, rec.sales_code, rec.staff_name = _dt.date(2026, 9, 1), "NWK1466", "Naomi"
        rec.sheet, rec.branch = "BM_Scorecard", "Thika"
        payload = card_payload(rec)
        self.assertEqual(payload["performance_score"], 0.756)
        self.assertIn("before Value of Property Sales", payload["coverage_note"])
        # Without a filled line the desk's recorded score still wins.
        rec.card = {"lines": []}
        self.assertEqual(card_payload(rec)["performance_score"], 0.738)


class CarriedLineRescoredTests(TestCase):
    def test_the_rescore_month_keeps_the_running_total(self):
        """The live card re-scores a carried line at the month its figure is
        from; that month's unfilled running total must not turn it to 0."""
        from .workbook_cards import running_totals_filled

        head = ["PF", "Code", "Name", "Role", "Branch", "Zone"] + list(range(1, 13))
        row = [1466, "NWK1466", "Naomi", "BM", "Thika", "Zone A",
               0, 0, 0, 0, 0, 0, 29, 38, 0, 38, 0, 0]
        filled = running_totals_filled({"Plot_Sales_Value": [head, row]}, 9)
        self.assertEqual(filled["Plot_Sales_Value"][1][14], 38)


class RosterOverridesListTests(TestCase):
    """The branch roster corrects a List row the desk has not updated."""

    def _book(self, book_kind, rows):
        return {"book": book_kind, "tables": {"List": [["h"] * 9] + rows}, "cards": {}}

    def test_back_office_role_and_branch_follow_the_roster(self):
        from unittest import mock

        from . import workbook_cards as wc

        book = self._book("back_office", [
            [3227, "JKK3227", "Joseph Kinuthia", "BOM", "Naivasha"],
            [1, "UB1", "Ultimate CSO", "CSO_UB", "Westlands"],
        ])
        roster = {"JKK3227": ("Joseph Kinuthia", "CSO", "EMBU BRANCH", 3227),
                  "UB1": ("Ultimate CSO", "CSO", "WESTLANDS BRANCH", 1)}
        with mock.patch.object(wc, "roster_roles", return_value=roster):
            joseph, ub = wc.holders(book)
        self.assertEqual((joseph.role, joseph.sheet, joseph.branch),
                         ("CSO", "CSO_SCORECARD", "Embu"))
        self.assertEqual((ub.role, ub.sheet), ("CSO_UB", "CSO_UB_SCORECARD"))

    def test_back_office_role_follows_the_hr_job_title(self):
        """Felix Saigon (PF 3789), promoted to Branch Service Ambassador on
        1 Mar 2026, was still a Teller on the desk's List."""
        from unittest import mock

        from . import workbook_cards as wc

        book = self._book("back_office", [
            [3789, "FS3789", "Felix Saigon", "Teller", "Komarock"],
            [10, "CC10", "Cash Centre", "Cash_Center", "Hurlingham"],
            [11, "NB11", "No BSA card yet", "Teller", "Thika"],
        ])
        book["cards"] = {"BSA_SCORECARD": {}, "TELLER_SCORECARD": {},
                         "CASH_TELLER_SCORECARD": {}}
        hr = {"3789": "BSA", "10": "Teller"}
        with mock.patch.object(wc, "roster_roles", return_value={}), \
                mock.patch.object(wc, "hr_roles", return_value=hr):
            felix, cash, other = wc.holders(book)
        self.assertEqual((felix.role, felix.sheet), ("BSA", "BSA_SCORECARD"))
        # A Cash_Center teller whose HR title says Teller stays on its card.
        self.assertEqual((cash.role, cash.sheet), ("Cash_Center", "CASH_TELLER_SCORECARD"))
        self.assertEqual(other.role, "Teller")
        # No BSA card in the workbook: nothing to move to.
        book["cards"].pop("BSA_SCORECARD")
        with mock.patch.object(wc, "roster_roles", return_value={}), \
                mock.patch.object(wc, "hr_roles", return_value=hr):
            self.assertEqual(wc.holders(book)[0].role, "Teller")

    def test_branch_managers_come_from_the_list_only(self):
        """The branch table still named Dennis Geni (left 10 March 2026) for
        Naivasha; a roster BBM missing from the List gets no card."""
        from unittest import mock

        from . import workbook_cards as wc

        book = self._book("branch_business", [[1452, "NJK1452", "Nelly Kibet", "Naivasha"]])
        roster = {"DG3727": ("Dennis Geni", "BBM", "NAIVASHA BRANCH", 3727)}
        with mock.patch.object(wc, "roster_roles", return_value=roster):
            got = [h.sales_code for h in wc.holders(book)]
        self.assertEqual(got, ["NJK1452"])

class CardWithoutStoredMonthTests(TestCase):
    def test_a_holder_the_desk_never_sent_a_card_still_gets_the_live_card(self):
        """Dennis Geni: on the roster as Naivasha's BBM, never on the desk's
        branch-manager List, so no stored month - the live card finds him."""
        from unittest import mock

        from . import workbook_cards as wc

        book = sales_book()
        bo.save_file("sales_scorecards", book)
        bo.save_file("sales_actuals", SALES_ACTUALS)
        holder = wc.holders(book)[0]
        with mock.patch.object(wc, "holders", return_value=[holder]):
            card = wc.live_card(holder.sales_code, {"perspectives": []},
                                datetime.date(2026, 4, 30))
        self.assertIsNotNone(card)
        self.assertEqual(card["staff"]["sales_code"], holder.sales_code)


class RosterBranchTableTests(TestCase):
    def test_a_branch_manager_only_on_the_branch_table_is_on_the_roster(self):
        from django.core.cache import cache
        from django.db import connection

        from .workbook_cards import roster_roles

        cache.delete("workbook_roster_roles")
        from django.db import models as dm

        from .models import BranchFinalEmployeeDmcData

        fields = {"sales_code": "DG3727", "staff_name": "Dennis Geni", "staff_role": "BBM",
                  "staff_branch": "NAIVASHA BRANCH", "staff_pf_number": 3727, "active": 1}
        for f in BranchFinalEmployeeDmcData._meta.concrete_fields:
            if f.name in fields or f.name == "id" or f.null or f.has_default()                     or getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
                continue
            fields[f.name] = 0 if isinstance(f, (dm.IntegerField, dm.FloatField,
                                                  dm.DecimalField)) else "x"
        BranchFinalEmployeeDmcData.objects.create(**fields)
        self.assertEqual(roster_roles()["DG3727"],
                         ("Dennis Geni", "BBM", "NAIVASHA BRANCH", 3727))


class NoCardListTests(TestCase):
    """Julie Ambundo (JMA1138) moved from Kisumu BOM to CX Manager at head
    office; the desk's back-office workbook still carries her as a BOM."""

    def setUp(self):
        from django.core.cache import cache

        from apps.staff_management import workbook_cards as wc

        cache.clear()
        wc.save_file(wc.NO_CARD, {"JMA1138": {"from": "2026-10",
                                              "reason": "CX Manager, Head Office"}})

    def test_off_from_the_month_on_and_on_before_it(self):
        import datetime

        from apps.staff_management import workbook_cards as wc

        self.assertIsNotNone(wc.off_card("JMA1138", datetime.date(2026, 10, 31)))
        self.assertIsNotNone(wc.off_card("jma 1138", datetime.date(2026, 11, 1)))
        self.assertIsNone(wc.off_card("JMA1138", datetime.date(2026, 9, 30)))
        self.assertIsNone(wc.off_card("NJK1452", datetime.date(2026, 10, 31)))

    def test_the_card_says_there_is_none(self):
        import datetime

        from apps.staff_management.live_scorecard import build_card

        card = build_card("JMA1138", as_at=datetime.date(2026, 10, 31))
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "no_card")
        self.assertIn("CX Manager, Head Office", card["detail"])
