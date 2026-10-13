"""Customer experience: reading CX's file, and the two card lines it feeds.

The workbook these are written against is CX's own, ``RM Contactability,
Satisfaction & Segment NPS & CES Q2 2026.xlsx``: 73 RM rows in each of two
sheets, four of them carrying the text "TSC- Give full marks" instead of a
percentage, pivot tables sitting to the right of the data in both sheets, and
nine rows of per-segment NPS and CES in a third.

Each test below is a thing that was got wrong, or would be got wrong by the
obvious implementation.
"""

import datetime
import io

from django.contrib.auth.models import Group, User
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from . import cx_metrics
from .live_scorecard import build_card, score_for
from .models import BranchEmployeeDmcData, CxRmMetric, CxSegmentMetric


def a_workbook(contactability=None, satisfaction=None, segments=None,
               pivots=True):
    """A workbook shaped like CX's, including the parts that mislead a reader.

    ``pivots`` adds the pivot tables that sit to the right of the data in both
    of CX's sheets. They have their own headers, and one of them is also
    called "RM Name" - which is why the reader takes the FIRST matching
    column and not the last.
    """
    book = Workbook()
    book.remove(book.active)

    for title, header, rows in (
        ("Contactability", "%Contactability", contactability or []),
        ("Satisfaction", "% CSAT", satisfaction or []),
    ):
        sheet = book.create_sheet(title)
        sheet.cell(row=1, column=1, value="RM Name")
        sheet.cell(row=1, column=2, value=header)
        sheet.cell(row=1, column=3, value="commercial_check")
        if pivots:
            sheet.cell(row=1, column=11, value="RM Name")
            sheet.cell(row=1, column=12, value=header)
            sheet.cell(row=2, column=11, value="Grand Total")
            sheet.cell(row=2, column=12, value=0.99)
        for index, (name, value) in enumerate(rows, start=2):
            sheet.cell(row=index, column=1, value=name)
            sheet.cell(row=index, column=2, value=value)

    sheet = book.create_sheet("NPS & CES Summary")
    sheet.cell(row=1, column=1, value="Segment")
    sheet.cell(row=1, column=2, value="NPS")
    sheet.cell(row=1, column=3, value="CES")
    for index, (segment, nps, ces) in enumerate(segments or [], start=2):
        sheet.cell(row=index, column=1, value=segment)
        sheet.cell(row=index, column=2, value=nps)
        sheet.cell(row=index, column=3, value=ces)

    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


class SmallRulesTests(TestCase):
    def test_the_period_is_read_off_the_file_name(self):
        """CX name the file after the quarter, so nobody should have to type
        it in as well."""
        self.assertEqual(
            cx_metrics.period_of(
                "RM Contactability, Satisfaction & Segment NPS & CES "
                "Q2 2026.xlsx"),
            "2026-Q2")
        self.assertEqual(cx_metrics.period_of("2026-Q3"), "2026-Q3")
        self.assertEqual(cx_metrics.period_of("2026-06"), "2026-06")

    def test_a_name_with_no_period_falls_back_to_the_quarter_we_are_in(self):
        self.assertEqual(
            cx_metrics.period_of("final v3.xlsx",
                                 today=datetime.date(2026, 5, 20)),
            "2026-Q2")

    def test_trailing_space_in_a_name_does_not_cost_somebody_their_score(self):
        """CX's Q2 file has "Winfred Kivuva  " with two trailing spaces. On a
        strict match that is a different person from the one on the roster,
        and the RM ends the quarter with no survey figure and no reason."""
        self.assertEqual(cx_metrics.fold_name("Winfred Kivuva  "),
                         cx_metrics.fold_name("Winfred  KIVUVA"))

    def test_eighty_and_nought_point_eight_both_mean_eighty_percent(self):
        """CX write 0.8. Somebody typing into the screen writes 80. Scoring
        80 against a 0.8 target reads as 8,000% and caps the line."""
        self.assertAlmostEqual(cx_metrics._number(0.8), 0.8)
        self.assertAlmostEqual(cx_metrics._number(80), 0.8)
        self.assertAlmostEqual(cx_metrics._number("73%"), 0.73)
        self.assertIsNone(cx_metrics._number(""))
        self.assertIsNone(cx_metrics._number(None))

    def test_a_period_end_is_the_quarter_end_not_the_day_it_was_typed(self):
        from .live_scorecard import cx_period_end

        self.assertEqual(cx_period_end("2026-Q2"), datetime.date(2026, 6, 30))
        self.assertEqual(cx_period_end("2026-Q4"), datetime.date(2026, 12, 31))
        self.assertEqual(cx_period_end("2026-02"), datetime.date(2026, 2, 28))
        self.assertIsNone(cx_period_end("nonsense"))


class ReadingTheWorkbookTests(TestCase):
    def test_both_sheets_land_on_one_row_per_rm(self):
        stream = a_workbook(
            contactability=[("Anne Mwaura", 0.8), ("Abed Lelgo", 0.3333)],
            satisfaction=[("Anne Mwaura", 0.73), ("Abed Lelgo", 0.3333)],
            segments=[("SME", 0.2158, None), ("OVERALL NPS", 0.4963, None)])
        rows, segments, report = cx_metrics.read_workbook(stream, "Q2 2026.xlsx")

        self.assertEqual(report["period"], "2026-Q2")
        self.assertEqual(len(rows), 2, "one row per RM, not one per sheet")
        anne = next(r for r in rows if r["rm_name"] == "Anne Mwaura")
        self.assertAlmostEqual(anne["contactability"], 0.8)
        self.assertAlmostEqual(anne["csat"], 0.73)
        self.assertEqual(len(segments), 2)
        self.assertTrue(
            next(s for s in segments if s["segment"] == "OVERALL NPS")
            ["is_overall"],
            "the overall row is not a segment and must not be read as one")

    def test_the_pivot_tables_to_the_right_are_not_read_as_data(self):
        """Both of CX's sheets carry a pivot from column 11 onwards, and one of
        its headers is also "RM Name". Reading the last match instead of the
        first picks up "Grand Total" as an RM."""
        stream = a_workbook(contactability=[("Anne Mwaura", 0.8)],
                            satisfaction=[("Anne Mwaura", 0.73)], pivots=True)
        rows, _, report = cx_metrics.read_workbook(stream)
        self.assertEqual([r["rm_name"] for r in rows], ["Anne Mwaura"])
        self.assertEqual(report["rm_names"], 1)

    def test_give_full_marks_is_kept_as_a_rule_and_not_as_a_number(self):
        """Four RMs in CX's Q2 file carry "TSC- Give full marks" where a
        percentage would be. Parsed as 0 they score nought on a measure that
        does not apply to them; written as 1.0 the rule becomes
        indistinguishable from a measured 100%."""
        stream = a_workbook(
            contactability=[("Vincent Ogare", "TSC- Give full marks")],
            satisfaction=[("Vincent Ogare", "TSC- Give full marks")])
        rows, _, report = cx_metrics.read_workbook(stream)

        row = rows[0]
        self.assertTrue(row["full_marks"])
        self.assertIsNone(row["contactability"])
        self.assertIsNone(row["csat"])
        self.assertIn("full marks", row["note"].lower())
        self.assertEqual(report["full_marks"], ["Vincent Ogare"])

    def test_a_total_row_is_not_an_rm(self):
        stream = a_workbook(
            contactability=[("Anne Mwaura", 0.8), ("Grand Total", 0.5)])
        rows, _, _ = cx_metrics.read_workbook(stream)
        self.assertEqual([r["rm_name"] for r in rows], ["Anne Mwaura"])

    def test_a_value_that_is_neither_a_number_nor_the_rule_is_reported(self):
        """Not dropped quietly: an unreadable cell is an RM with no figure,
        and somebody has to know which cell to go and look at."""
        stream = a_workbook(contactability=[("Anne Mwaura", "pending")])
        rows, _, report = cx_metrics.read_workbook(stream)
        self.assertIsNone(rows[0]["contactability"])
        self.assertEqual(
            [item["rm_name"] for item in report["ignored_values"]],
            ["Anne Mwaura"])

    def test_a_missing_sheet_is_named_rather_than_silently_skipped(self):
        book = Workbook()
        book.remove(book.active)
        sheet = book.create_sheet("Contactability")
        sheet.cell(row=1, column=1, value="RM Name")
        sheet.cell(row=1, column=2, value="%Contactability")
        sheet.cell(row=2, column=1, value="Anne Mwaura")
        sheet.cell(row=2, column=2, value=0.8)
        buffer = io.BytesIO()
        book.save(buffer)
        buffer.seek(0)

        _, _, report = cx_metrics.read_workbook(buffer)
        self.assertIn("Contactability", report["sheets_read"])
        self.assertIn("Satisfaction", report["sheets_missing"])
        self.assertIn("NPS & CES Summary", report["sheets_missing"])


class NameResolutionTests(TestCase):
    """CX key their file on the RM's NAME. It carries no sales code, so a name
    that matches nobody is an RM with no score - and it looks exactly like an
    RM CX did not survey. Hence it is reported, never guessed at."""

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4330, staff_name="Vincent Ogare",
            sales_code="VOO4330", staff_role="PB RM", staff_branch="Nairobi",
            staff_unit="Nairobi", active=1)

    def test_a_name_on_the_roster_gets_its_sales_code(self):
        stream = a_workbook(contactability=[("vincent  OGARE ", 0.8)])
        rows, _, report = cx_metrics.read_workbook(stream)
        self.assertEqual(rows[0]["sales_code"], "VOO4330")
        self.assertEqual(report["unmatched_names"], [])

    def test_a_name_nobody_has_is_reported_and_kept(self):
        stream = a_workbook(contactability=[("Somebody Else", 0.8)])
        rows, _, report = cx_metrics.read_workbook(stream)
        self.assertEqual(rows[0]["sales_code"], "")
        self.assertEqual(report["unmatched_names"], ["Somebody Else"])

    def test_a_name_on_the_roster_in_a_role_with_no_card_is_not_matched(self):
        """A branch manager shares a name list with the RMs. Attaching a
        survey figure to somebody who holds no sales card puts the figure
        nowhere and reports a match that is not one."""
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=9999, staff_name="Brian Manager",
            sales_code="BM9999", staff_role="Branch Manager",
            staff_branch="Nairobi", staff_unit="Nairobi", active=1)
        stream = a_workbook(contactability=[("Brian Manager", 0.8)])
        rows, _, _ = cx_metrics.read_workbook(stream)
        self.assertEqual(rows[0]["sales_code"], "")


class SavingTests(TestCase):
    def test_a_second_load_corrects_rather_than_duplicates(self):
        rows = [{"period": "2026-Q2", "rm_name": "Anne Mwaura",
                 "sales_code": "AM1", "contactability": 0.8, "csat": 0.73,
                 "full_marks": False, "note": "", "source": "first.xlsx"}]
        cx_metrics.save(rows, [], who="cx")
        rows[0]["csat"] = 0.81
        cx_metrics.save(rows, [], who="cx")

        self.assertEqual(CxRmMetric.objects.count(), 1)
        self.assertAlmostEqual(CxRmMetric.objects.get().csat, 0.81)

    def test_a_partial_correction_leaves_the_others_alone(self):
        """CX send a two-row fix for a quarter they have already loaded.
        Replacing the period would blank 71 RMs' scores."""
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "A", "sales_code": "A1",
             "contactability": 0.5, "csat": 0.5, "full_marks": False,
             "note": "", "source": ""},
            {"period": "2026-Q2", "rm_name": "B", "sales_code": "B1",
             "contactability": 0.6, "csat": 0.6, "full_marks": False,
             "note": "", "source": ""},
        ], [], who="cx")
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "A", "sales_code": "A1",
             "contactability": 0.9, "csat": 0.9, "full_marks": False,
             "note": "", "source": ""},
        ], [], who="cx")

        self.assertEqual(CxRmMetric.objects.count(), 2)
        self.assertAlmostEqual(
            CxRmMetric.objects.get(rm_name="B").contactability, 0.6)

    def test_two_periods_sit_side_by_side(self):
        for period in ("2026-Q1", "2026-Q2"):
            cx_metrics.save([
                {"period": period, "rm_name": "A", "sales_code": "A1",
                 "contactability": 0.5, "csat": 0.5, "full_marks": False,
                 "note": "", "source": ""}], [], who="cx")
        self.assertEqual(CxRmMetric.objects.count(), 2)
        self.assertEqual(cx_metrics.latest_period(), "2026-Q2")

    def test_the_newest_period_is_what_a_card_reads(self):
        cx_metrics.save([
            {"period": "2026-Q1", "rm_name": "A", "sales_code": "A1",
             "contactability": 0.5, "csat": 0.5, "full_marks": False,
             "note": "", "source": ""},
            {"period": "2026-Q2", "rm_name": "A", "sales_code": "A1",
             "contactability": 0.9, "csat": 0.9, "full_marks": False,
             "note": "", "source": ""}], [], who="cx")
        found = cx_metrics.for_rm("A1")
        self.assertEqual(found["period"], "2026-Q2")
        self.assertAlmostEqual(found["csat"], 0.9)

    def test_coverage_names_what_is_not_matched(self):
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Matched", "sales_code": "A1",
             "contactability": 0.5, "csat": 0.5, "full_marks": False,
             "note": "", "source": ""},
            {"period": "2026-Q2", "rm_name": "Unmatched", "sales_code": "",
             "contactability": 0.5, "csat": None, "full_marks": False,
             "note": "", "source": ""}], [
            {"period": "2026-Q2", "segment": "SME", "nps": 0.2, "ces": None,
             "is_overall": False}], who="cx")

        found = cx_metrics.coverage()
        self.assertEqual(found["period"], "2026-Q2")
        self.assertEqual(found["rm_rows"], 2)
        self.assertEqual(found["matched"], 1)
        self.assertEqual(found["unmatched"], ["Unmatched"])
        self.assertEqual(found["with_contactability"], 2)
        self.assertEqual(found["with_csat"], 1)
        self.assertEqual(found["segments"], 1)

    def test_nothing_loaded_is_not_an_error(self):
        self.assertIsNone(cx_metrics.latest_period())
        self.assertIsNone(cx_metrics.for_rm("A1"))
        self.assertEqual(cx_metrics.coverage()["rm_rows"], 0)


class TheCardReadsThemTests(TestCase):
    """The two lines that were unscoreable until this existed."""

    CODE = "VOO4330"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4330, staff_name="Vincent Ogare",
            sales_code=self.CODE, staff_role="PB RM",
            staff_branch="Nairobi", staff_unit="Nairobi", active=1)

    def lines(self):
        card = build_card(self.CODE)
        self.assertTrue(card["has_card"], card)
        return {line["kpi_code"]: line
                for group in card["perspectives"] for line in group["lines"]}

    def test_without_a_period_the_card_says_whose_job_that_is(self):
        lines = self.lines()
        coverage = lines["portfolio_coverage_engagement"]
        self.assertIsNone(coverage["score"])
        self.assertIn("CX", coverage["pending"])

    def test_an_rm_the_survey_missed_is_told_it_is_a_name_match(self):
        """The commonest cause by far: CX spell the name differently from the
        roster. Saying "no figure" sends the RM to the wrong person."""
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Somebody Else",
             "sales_code": "", "contactability": 0.8, "csat": 0.8,
             "full_marks": False, "note": "", "source": ""}], [], who="cx")
        coverage = self.lines()["portfolio_coverage_engagement"]
        self.assertIsNone(coverage["score"])
        self.assertIn("name", coverage["pending"].lower())

    def test_contactability_scores_the_coverage_line(self):
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": 0.6, "csat": 0.3,
             "full_marks": False, "note": "", "source": ""}], [], who="cx")

        coverage = self.lines()["portfolio_coverage_engagement"]
        self.assertAlmostEqual(coverage["ytd_actual"], 0.6)
        # 80% is the role target, and it is a full-year figure: 80% is 80% in
        # March as much as in December, so it is not pro-rated.
        self.assertAlmostEqual(coverage["ytd_target"], 0.8)
        self.assertTrue(coverage["full_year_target"])
        self.assertAlmostEqual(coverage["score"], 0.75)
        self.assertIn("CX survey", coverage["as_at"])

    def test_csat_scores_the_nps_line(self):
        """The line is called NPS and the figure behind it is CSAT. That is
        the business's own choice; what matters here is that it is the
        Satisfaction sheet that reaches it and not the segment NPS."""
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": 0.6, "csat": 0.3,
             "full_marks": False, "note": "", "source": ""}], [
            {"period": "2026-Q2", "segment": "PERSONAL BANKING", "nps": 0.196,
             "ces": None, "is_overall": False}], who="cx")

        lines = self.lines()
        nps = next(line for code, line in lines.items()
                   if code in ("nps", "portfolio_nps", "portfolo_nps"))
        self.assertAlmostEqual(nps["ytd_actual"], 0.3)
        self.assertAlmostEqual(nps["ytd_target"], 0.6)
        self.assertAlmostEqual(nps["score"], 0.5)

    def test_the_survey_lines_stop_at_full_marks(self):
        """Every other line runs to 120%. These two stop at 1.0 - the count
        behind that is in tests_scorecard_calibration."""
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": 1.0, "csat": 1.0,
             "full_marks": False, "note": "", "source": ""}], [], who="cx")

        coverage = self.lines()["portfolio_coverage_engagement"]
        # 1.0 against 0.8 is 1.25 uncapped, and 1.2 under the usual cap.
        self.assertAlmostEqual(coverage["score"], 1.0)
        self.assertAlmostEqual(coverage["score_cap"], 1.0)

    def test_give_full_marks_scores_exactly_full_marks_and_says_why(self):
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": None, "csat": None,
             "full_marks": True, "note": "TSC- Give full marks",
             "source": ""}], [], who="cx")

        lines = self.lines()
        coverage = lines["portfolio_coverage_engagement"]
        self.assertAlmostEqual(coverage["score"], 1.0)
        self.assertTrue(coverage["full_marks_rule"])
        self.assertEqual(coverage["pending"], "",
                         "a settled line is not pending")
        self.assertIsNone(coverage["ytd_actual"],
                          "the rule is not a measurement and must not look "
                          "like one")
        self.assertIn("full marks", coverage["as_at"].lower())

    def test_a_period_with_the_rm_but_no_figure_is_not_a_zero(self):
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": 0.6, "csat": None,
             "full_marks": False, "note": "", "source": ""}], [], who="cx")

        lines = self.lines()
        nps = next(line for code, line in lines.items()
                   if code in ("nps", "portfolio_nps", "portfolo_nps"))
        self.assertIsNone(nps["score"])
        self.assertIsNone(nps["ytd_actual"])
        self.assertIn("CSAT", nps["pending"])


class TheScreenTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.cx = User.objects.create_user("cx1", password="x")
        self.cx.groups.add(Group.objects.create(name="cx"))
        self.rm = User.objects.create_user("rm1", password="x")
        Profile.objects.update_or_create(
            user=self.rm, defaults={"sales_code": "VOO4330"})

    def test_an_rm_may_see_the_figure_they_are_scored_on(self):
        self.client.force_authenticate(self.rm)
        response = self.client.get("/staff_management/scorecard-automation/cx/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["may_edit"])

    def test_an_rm_may_not_set_their_own_survey_figure(self):
        self.client.force_authenticate(self.rm)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "2026-Q2", "rm_name": "Vincent Ogare", "csat": 1.0})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CxRmMetric.objects.count(), 0)

    def test_is_staff_alone_does_not_open_the_screen(self):
        """``is_staff`` is legacy noise in this estate - a great many accounts
        carry it for reasons that have nothing to do with CX."""
        staffer = User.objects.create_user("s1", password="x", is_staff=True)
        self.client.force_authenticate(staffer)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "2026-Q2", "rm_name": "Vincent Ogare", "csat": 1.0})
        self.assertEqual(response.status_code, 403)

    def test_the_cx_team_type_one_figure_in(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4330, staff_name="Vincent Ogare",
            sales_code="VOO4330", staff_role="PB RM", staff_branch="Nairobi",
            staff_unit="Nairobi", active=1)
        self.client.force_authenticate(self.cx)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "Q2 2026", "rm_name": "Vincent Ogare",
             "contactability": 80, "csat": "73%"})
        self.assertEqual(response.status_code, 201, response.data)

        row = CxRmMetric.objects.get()
        self.assertEqual(row.period, "2026-Q2")
        self.assertEqual(row.sales_code, "VOO4330",
                         "the name should have been resolved on the way in")
        self.assertAlmostEqual(row.contactability, 0.8)
        self.assertAlmostEqual(row.csat, 0.73)

    def test_typing_a_name_nobody_has_is_saved_and_said_out_loud(self):
        self.client.force_authenticate(self.cx)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "2026-Q2", "rm_name": "Nobody Here", "csat": 0.5})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data["row"]["matched"])
        self.assertIn("No roster", response.data["detail"])

    def test_marking_full_marks_clears_the_figures(self):
        self.client.force_authenticate(self.cx)
        self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "2026-Q2", "rm_name": "Vincent Ogare", "csat": 0.5})
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "full_marks": "true"})
        self.assertEqual(response.status_code, 200, response.data)

        row = CxRmMetric.objects.get()
        self.assertTrue(row.full_marks)
        self.assertIsNone(row.csat, "the rule and a figure cannot both hold")

    def test_a_figure_with_no_period_joins_the_one_already_loaded(self):
        """Defaulting to the quarter we are in would open a new period on the
        first typed figure - and because a card reads the NEWEST period, that
        one row would shadow the loaded quarter for all 73 RMs."""
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Anne Mwaura",
             "sales_code": "AM1", "contactability": 0.8, "csat": 0.73,
             "full_marks": False, "note": "", "source": ""}], [], who="cx")
        self.client.force_authenticate(self.cx)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"rm_name": "Vincent Ogare", "csat": 0.5})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["row"]["period"], "2026-Q2")
        self.assertEqual(
            set(CxRmMetric.objects.values_list("period", flat=True)),
            {"2026-Q2"}, "a second period was opened")

    def test_with_nothing_loaded_a_typed_figure_starts_this_quarter(self):
        self.client.force_authenticate(self.cx)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"rm_name": "Vincent Ogare", "csat": 0.5})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["row"]["period"],
                         cx_metrics.period_of(""))

    def test_a_figure_outside_nought_to_a_hundred_is_refused(self):
        self.client.force_authenticate(self.cx)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/entry/",
            {"period": "2026-Q2", "rm_name": "Vincent Ogare", "csat": 250})
        self.assertEqual(response.status_code, 400)

    def test_an_upload_reports_before_it_writes(self):
        self.client.force_authenticate(self.cx)
        stream = a_workbook(
            contactability=[("Anne Mwaura", 0.8)],
            satisfaction=[("Anne Mwaura", 0.73),
                          ("Vincent Ogare", "TSC- Give full marks")],
            segments=[("SME", 0.2158, None)])
        stream.name = "CX Q2 2026.xlsx"

        response = self.client.post(
            "/staff_management/scorecard-automation/cx/upload/",
            {"file": stream}, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["applied"])
        self.assertEqual(CxRmMetric.objects.count(), 0,
                         "a first upload must write nothing")
        self.assertEqual(response.data["report"]["rm_names"], 2)
        self.assertEqual(response.data["report"]["full_marks"],
                         ["Vincent Ogare"])

    def test_the_second_call_writes(self):
        self.client.force_authenticate(self.cx)
        stream = a_workbook(
            contactability=[("Anne Mwaura", 0.8)],
            satisfaction=[("Anne Mwaura", 0.73)],
            segments=[("SME", 0.2158, None), ("OVERALL NPS", 0.4963, None)])
        stream.name = "CX Q2 2026.xlsx"

        response = self.client.post(
            "/staff_management/scorecard-automation/cx/upload/",
            {"file": stream, "apply": "true"}, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["applied"])
        self.assertEqual(CxRmMetric.objects.count(), 1)
        self.assertEqual(CxSegmentMetric.objects.count(), 2)
        self.assertEqual(CxRmMetric.objects.get().period, "2026-Q2")

    def test_something_that_is_not_a_workbook_is_refused(self):
        self.client.force_authenticate(self.cx)
        response = self.client.post(
            "/staff_management/scorecard-automation/cx/upload/",
            {"file": io.BytesIO(b"not a workbook")}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_the_segments_are_served_with_the_warning_attached(self):
        cx_metrics.save([], [
            {"period": "2026-Q2", "segment": "SME", "nps": 0.2158,
             "ces": None, "is_overall": False}], who="cx")
        self.client.force_authenticate(self.rm)
        response = self.client.get(
            "/staff_management/scorecard-automation/cx/segments/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["rows"]), 1)
        self.assertIn("No scorecard line", response.data["detail"])


class TheDownloadSaysWhyTests(TestCase):
    """The signed copy is the document a line manager puts their name to, so a
    100% score with an empty actual beside it is not good enough."""

    CODE = "VOO4330"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4330, staff_name="Vincent Ogare",
            sales_code=self.CODE, staff_role="PB RM",
            staff_branch="Nairobi", staff_unit="Nairobi", active=1)
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": None, "csat": None,
             "full_marks": True, "note": "TSC- Give full marks",
             "source": ""}], [], who="cx")

    def test_a_line_settled_by_rule_prints_the_rule_not_a_blank(self):
        from io import BytesIO

        from openpyxl import load_workbook

        from .scorecard_signoff import build_card_workbook

        card = build_card(self.CODE)
        book = load_workbook(BytesIO(build_card_workbook(card).read()))
        text = "\n".join(
            " ".join("" if c.value is None else str(c.value) for c in row)
            for row in book.active.iter_rows())
        self.assertIn("Full marks by rule", text)
        self.assertIn("full marks", text.lower())
