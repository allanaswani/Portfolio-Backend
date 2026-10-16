"""Training hours, and the four cards they reproduce.

A training line sits on every one of the 22 scorecards and none of them could
be scored: the figures were in a workbook HR circulated by e-mail. These tests
are written against that workbook, ``2026 Training Returns Template -
Aug_26.xlsx`` — ten sheets, eight of people and two of pivoted averages, one
row per person and one column per month.

The headline check is :class:`ItReproducesTheCardsTests`: the four calibration
cards whose RM appears on the August return state an actual of 36.0, 38.5, 29.0
and 69.0, and the Jan–Aug sum gives all four to the digit.
"""

import datetime
import io

from django.contrib.auth.models import Group, User
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from . import training
from .live_scorecard import build_card, prorate_to, score_for
from .models import BranchEmployeeDmcData, ScTrainingReturn

MONTHS = [datetime.date(2026, m, 1) for m in range(1, 13)]


def a_return(people, sheet_name="Staff_Training_Returns", months=8,
             headers=("Branch", "StaffPF", "StaffCode", "Staff Name"),
             with_a_pivot=True, extra_rows=()):
    """A workbook shaped like HR's.

    ``people`` is ``(branch, pf, code, name, [hours per month])``. ``months``
    is how many month columns carry a header — the real file has twelve, with
    the later ones empty.
    """
    book = Workbook()
    book.remove(book.active)

    if with_a_pivot:
        # Two of the ten sheets are pivots of averages with no staff column.
        # They must be skipped, and skipped on purpose rather than by luck.
        pivot = book.create_sheet("Branch_Training_Returns")
        pivot.cell(row=3, column=2, value="Row Labels")
        pivot.cell(row=3, column=3, value="Average of Total")
        pivot.cell(row=4, column=2, value="Buruburu")
        pivot.cell(row=4, column=3, value=48.142857)

    sheet = book.create_sheet(sheet_name)
    for index, header in enumerate(headers, start=1):
        sheet.cell(row=1, column=index, value=header)
    for index, month in enumerate(MONTHS, start=len(headers) + 1):
        sheet.cell(row=1, column=index, value=datetime.datetime(
            month.year, month.month, 1))

    row = 2
    for branch, pf, code, name, hours in people:
        sheet.cell(row=row, column=1, value=branch)
        sheet.cell(row=row, column=2, value=pf)
        sheet.cell(row=row, column=3, value=code)
        sheet.cell(row=row, column=4, value=name)
        for index, value in enumerate(hours[:months], start=len(headers) + 1):
            if value is not None:
                sheet.cell(row=row, column=index, value=value)
        row += 1
    for cells in extra_rows:
        for column, value in cells.items():
            sheet.cell(row=row, column=column, value=value)
        row += 1

    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


class SmallRulesTests(TestCase):
    def test_a_pf_number_is_the_digits_however_it_is_written(self):
        """The return writes it as a number, the roster as an integer, and a
        stray space must not make them two people."""
        for written in (4236, "4236", " 4236 ", "4236.0", "PF4236"):
            with self.subTest(repr(written)):
                self.assertEqual(training.pf_of(written), "4236")

    def test_the_month_comes_off_the_file_name(self):
        self.assertEqual(
            training.month_of("2026 Training Returns Template - Aug_26.xlsx"),
            datetime.date(2026, 8, 1))
        self.assertEqual(training.month_of("Training Jan 2026.xlsx"),
                         datetime.date(2026, 1, 1))

    def test_a_blank_month_is_not_nought_hours_at_read_time(self):
        """A blank cell carries no figure, so no row is written for it. What
        it MEANS - no training, or not reported - depends on whether the
        return reaches that month, which is decided when the card is built."""
        self.assertIsNone(training._hours(None))
        self.assertIsNone(training._hours(""))
        self.assertEqual(training._hours(0), 0.0)
        self.assertEqual(training._hours(6.45), 6.45)
        self.assertEqual(training._hours("5.4"), 5.4)


class ReadingTheReturnTests(TestCase):
    def test_one_row_per_person_per_month_with_a_figure(self):
        stream = a_return([
            ("Buruburu", 1886, "CMM1886", "Christopher Kibugi",
             [4, 7, 8, 4, 4, 7, 4, 5]),
        ])
        rows, report = training.read_workbook(stream, "Aug_26.xlsx")

        self.assertEqual(len(rows), 8, "eight months carry a figure")
        self.assertEqual(report["people"], 1)
        self.assertEqual(rows[0]["staff_pf"], "1886")
        self.assertEqual(rows[0]["sales_code"], "CMM1886")
        self.assertEqual(rows[0]["branch"], "Buruburu")

    def test_the_pivot_sheets_are_skipped_and_said_so(self):
        """Two of the ten sheets are averages. Skipping them quietly would
        make a sheet that failed to parse look the same as one that was never
        meant to be read."""
        stream = a_return([("B", 1, "A1", "A", [4])], with_a_pivot=True)
        _, report = training.read_workbook(stream)

        self.assertIn("Staff_Training_Returns", report["sheets_read"])
        self.assertEqual(
            [s["sheet"] for s in report["sheets_skipped"]],
            ["Branch_Training_Returns"])
        self.assertIn("month", report["sheets_skipped"][0]["why"])

    def test_the_desk_sheets_spell_the_headers_differently(self):
        """``Staff_Training_Returns`` says StaffPF/StaffCode/Staff Name; the
        seven desk sheets say staff_pf/sales_code/sales_person."""
        stream = a_return(
            [("Diaspora", 4188, "EK4188", "Edward Kosgei", [0, 10.5, 2.5])],
            sheet_name="Diaspora",
            headers=("Branch", "staff_pf", "sales_code", "sales_person"))
        rows, report = training.read_workbook(stream)

        self.assertIn("Diaspora", report["sheets_read"])
        self.assertEqual(report["people"], 1)
        self.assertEqual({r["sales_code"] for r in rows}, {"EK4188"})

    def test_a_cumulative_target_row_is_counted_not_loaded(self):
        """The desk sheets carry a row of 4, 8, 12 … 48 at the foot - the
        cumulative target. It has hours and no person, and attributing it to
        anybody would add 48 hours to somebody's year."""
        stream = a_return(
            [("Diaspora", 4188, "EK4188", "Edward Kosgei", [0, 10.5])],
            extra_rows=[{5: 4, 6: 8, 7: 12, 8: 16}])
        rows, report = training.read_workbook(stream)

        self.assertEqual(report["no_identity"], 1)
        self.assertEqual(report["people"], 1)
        self.assertEqual(len(rows), 2, "only the person's own two months")

    def test_an_average_row_is_not_a_person(self):
        stream = a_return([
            ("Diaspora", 4188, "EK4188", "Edward Kosgei", [5]),
            ("", None, None, "Average", [5]),
        ])
        _, report = training.read_workbook(stream)
        self.assertEqual(report["people"], 1)

    def test_a_cell_that_is_not_a_number_is_reported(self):
        stream = a_return([("B", 1886, "A1", "Someone", ["n/a", 7])])
        rows, report = training.read_workbook(stream)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(report["ignored_values"]), 1)
        self.assertEqual(report["ignored_values"][0]["value"], "n/a")


class SavingTests(TestCase):
    def rows(self, hours):
        return [{"month": datetime.date(2026, m, 1), "staff_pf": "4236",
                 "sales_code": "CM4236", "staff_name": "Charles Muchiri",
                 "branch": "Machakos", "staff_role": "SME RM",
                 "hours": h, "source": "test"}
                for m, h in enumerate(hours, start=1)]

    def test_reloading_a_month_corrects_it_rather_than_doubling_it(self):
        training.save(self.rows([5, 6]), who="hr")
        training.save(self.rows([5, 9]), who="hr")

        self.assertEqual(ScTrainingReturn.objects.count(), 2)
        hours, _, _ = training.ytd_hours("CM4236", "4236", 2026)
        self.assertAlmostEqual(hours, 14.0)

    def test_a_month_the_new_file_omits_is_left_alone(self):
        """HR send a corrected single month. Clearing the rest would wipe the
        year to date for everybody."""
        training.save(self.rows([5, 6, 4]), who="hr")
        training.save(self.rows([5]), who="hr")

        hours, _, _ = training.ytd_hours("CM4236", "4236", 2026)
        self.assertAlmostEqual(hours, 15.0, msg="February and March vanished")


class FindingThePersonTests(TestCase):
    """The return and the roster do not always spell a sales code the same
    way, and the PF number is what saves it."""

    def setUp(self):
        training.save([{
            "month": datetime.date(2026, 1, 1), "staff_pf": "4236",
            "sales_code": "CM4236", "staff_name": "CHARLES MUCHIRI",
            "branch": "Machakos", "staff_role": "SME RM", "hours": 5.0,
            "source": "test"}], who="hr")

    def test_the_pf_number_finds_somebody_the_code_cannot(self):
        """The roster has Charles Muchiri as CMM4236 and the return has
        CM4236. On the code alone he has no training figure at all, which is
        indistinguishable from an RM who did none."""
        hours, _, problem = training.ytd_hours("CMM4236", "4236", 2026)
        self.assertAlmostEqual(hours, 5.0)
        self.assertEqual(problem, "")

        missed, _, why = training.ytd_hours("CMM4236", "", 2026)
        self.assertIsNone(missed, "the code alone should not have matched")
        self.assertIn("not on the training return", why)

    def test_the_code_still_works_when_there_is_no_pf(self):
        hours, _, _ = training.ytd_hours("CM4236", "", 2026)
        self.assertAlmostEqual(hours, 5.0)

    def test_somebody_absent_is_told_so_rather_than_scored_nought(self):
        """Three cards show 0.0 for an RM the return does not mention, which
        is the desk filling a blank. Nought hours and absent from the return
        are different statements, and only one of them is the RM's fault."""
        hours, as_at, problem = training.ytd_hours("NOBODY1", "9999", 2026)
        self.assertIsNone(hours)
        self.assertIsNone(as_at)
        self.assertIn("not on the training return", problem)
        self.assertIn("January 2026", problem)

    def test_with_nothing_loaded_the_reason_names_the_screen(self):
        ScTrainingReturn.objects.all().delete()
        hours, _, problem = training.ytd_hours("CM4236", "4236", 2026)
        self.assertIsNone(hours)
        self.assertIn("no training return has been loaded", problem)


class TheAsAtIsTheReturnsNotThePersonsTests(TestCase):
    """The difference decides somebody's score, so it gets its own case."""

    def setUp(self):
        for code, pf, hours in (("A1", "1", [5, 5, 5, 5, 5, 4]),
                                ("B2", "2", [5, 5, 5, 5, 5, 5, 5, 5])):
            training.save([{
                "month": datetime.date(2026, m, 1), "staff_pf": pf,
                "sales_code": code, "staff_name": code, "branch": "",
                "staff_role": "", "hours": h, "source": "test"}
                for m, h in enumerate(hours, start=1)], who="hr")

    def test_somebody_who_stopped_in_june_is_still_measured_to_august(self):
        """Juspher Muriithi's 29 hours run out in June. Slicing his target to
        June scores him 122%; slicing it to the month the return REACHES
        scores him 90.6%, which is what his card says."""
        hours, as_at, _ = training.ytd_hours("A1", "1", 2026)
        self.assertAlmostEqual(hours, 29.0)
        self.assertEqual(as_at, datetime.date(2026, 8, 31),
                         "the as-at is the return's last month, not theirs")

        target = prorate_to(48, as_at, counted=True)
        self.assertAlmostEqual(target, 32.0)
        self.assertAlmostEqual(score_for(hours, target, True, cap=1.0),
                               0.90625)

    def test_everybody_is_measured_to_the_same_date(self):
        _, mine, _ = training.ytd_hours("A1", "1", 2026)
        _, theirs, _ = training.ytd_hours("B2", "2", 2026)
        self.assertEqual(mine, theirs)


class ItReproducesTheCardsTests(TestCase):
    """The four calibration cards whose RM is on the August 2026 return.

    Figures read off that workbook; the stated actuals read off the cards.
    """

    #: (card, roster code, PF, months Jan–Aug, the card's stated actual)
    CARDS = [
        ("Business_Banking", "CMM4236", "4236", "CM4236",
         [5, 6, 4, 6, 0, 4, 5, 6], 36.0),
        ("Diaspora", "EK4188", "4188", "EK4188",
         [0, 10.5, 2.5, 6.5, 4.5, 5.5, 2, 7], 38.5),
        ("Commercial", "JM4191", "4191", "JM4191",
         [5, 4, 4, 4, 4, 8, 0, 0], 29.0),
        ("Commercial_trade", "GW3961", "3961", "GW3961",
         [8, 8, 8, 8, 8, 8, 8, 13], 69.0),
    ]

    def test_the_months_add_up_to_what_the_card_states(self):
        for card, roster_code, pf, return_code, months, stated in self.CARDS:
            with self.subTest(card):
                self.assertAlmostEqual(
                    sum(months), stated, places=2,
                    msg=f"{card}: the return's months do not make the card's "
                        f"actual")

    def test_each_card_reproduces_end_to_end(self):
        for card, roster_code, pf, return_code, months, stated in self.CARDS:
            with self.subTest(card):
                ScTrainingReturn.objects.all().delete()
                training.save([{
                    "month": datetime.date(2026, m, 1), "staff_pf": pf,
                    "sales_code": return_code, "staff_name": card,
                    "branch": "", "staff_role": "", "hours": h,
                    "source": "test"}
                    for m, h in enumerate(months, start=1)], who="hr")

                hours, as_at, problem = training.ytd_hours(
                    roster_code, pf, 2026)
                self.assertEqual(problem, "")
                self.assertAlmostEqual(hours, stated, places=2)
                self.assertEqual(as_at, datetime.date(2026, 8, 31))


class TheCardReadsItTests(TestCase):
    CODE = "CMM4236"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4236, staff_name="Charles Muchiri",
            sales_code=self.CODE, staff_role="SME RM",
            staff_branch="Machakos", staff_unit="Machakos", active=1,
            target_training_hours=48)

    def line(self):
        card = build_card(self.CODE)
        self.assertTrue(card["has_card"], card)
        lines = {ln["kpi_code"]: ln
                 for group in card["perspectives"] for ln in group["lines"]}
        return lines["business_banking_training"]

    def test_without_a_return_the_card_names_the_screen(self):
        line = self.line()
        self.assertIsNone(line["score"])
        self.assertIn("training return", line["pending"])

    def test_the_hours_reach_the_card_through_the_pf_number(self):
        """The roster says CMM4236, the return says CM4236. The PF is 4236 on
        both, and ``pf_for`` is what bridges them."""
        training.save([{
            "month": datetime.date(2026, m, 1), "staff_pf": "4236",
            "sales_code": "CM4236", "staff_name": "CHARLES MUCHIRI",
            "branch": "Machakos", "staff_role": "SME RM", "hours": h,
            "source": "test"}
            for m, h in enumerate([5, 6, 4, 6, 0, 4, 5, 6], start=1)],
            who="hr")

        line = self.line()
        self.assertAlmostEqual(line["ytd_actual"], 36.0)
        self.assertAlmostEqual(line["ytd_target"], 32.0,
                               msg="48 hours sliced to 31 August")
        self.assertAlmostEqual(line["score"], 1.0,
                               msg="36 against 32 is full marks, not 112.5%")
        self.assertAlmostEqual(line["score_cap"], 1.0)
        self.assertIn("training return", line["as_at"])

    def test_the_pf_is_found_on_the_dmc_row(self):
        from .live_scorecard import pf_for, roster_row

        self.assertEqual(pf_for(self.CODE, roster_row(self.CODE)), "4236")
        self.assertEqual(pf_for("", None), "")


class TheScreenTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.hr = User.objects.create_user("hr1", password="x")
        self.hr.groups.add(Group.objects.get_or_create(name="hr")[0])
        self.rm = User.objects.create_user("rm1", password="x")
        Profile.objects.update_or_create(
            user=self.rm, defaults={"sales_code": "CMM4236"})

    BASE = "/staff_management/scorecard-automation/training/"

    def test_an_rm_may_see_the_hours_they_are_scored_on(self):
        self.client.force_authenticate(self.rm)
        response = self.client.get(self.BASE)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["may_load"])
        self.assertIn("month the RETURN reaches",
                      response.data["how_it_is_read"])

    def test_an_rm_may_not_load_their_own_hours(self):
        self.client.force_authenticate(self.rm)
        response = self.client.post(
            self.BASE + "upload/",
            {"file": a_return([("B", 1, "A1", "A", [99])])},
            format="multipart")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ScTrainingReturn.objects.count(), 0)

    def test_is_staff_alone_does_not_open_it(self):
        staffer = User.objects.create_user("s1", password="x", is_staff=True)
        self.client.force_authenticate(staffer)
        response = self.client.post(
            self.BASE + "upload/",
            {"file": a_return([("B", 1, "A1", "A", [4])])},
            format="multipart")
        self.assertEqual(response.status_code, 403)

    def test_an_upload_reports_before_it_writes(self):
        self.client.force_authenticate(self.hr)
        stream = a_return([("Buruburu", 1886, "CMM1886", "Christopher K.",
                            [4, 7, 8])])
        stream.name = "2026 Training Returns Template - Aug_26.xlsx"
        response = self.client.post(
            self.BASE + "upload/", {"file": stream}, format="multipart")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["applied"])
        self.assertEqual(ScTrainingReturn.objects.count(), 0,
                         "a first upload must write nothing")
        self.assertEqual(response.data["report"]["people"], 1)
        self.assertEqual(response.data["figures"], 3)

    def test_the_second_call_writes_and_reports_coverage(self):
        self.client.force_authenticate(self.hr)
        stream = a_return([("Buruburu", 1886, "CMM1886", "Christopher K.",
                            [4, 7, 8])])
        stream.name = "2026 Training Returns Template - Aug_26.xlsx"
        response = self.client.post(
            self.BASE + "upload/", {"file": stream, "apply": "true"},
            format="multipart")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["applied"])
        self.assertEqual(ScTrainingReturn.objects.count(), 3)
        self.assertEqual(response.data["coverage"]["people"], 1)

    def test_something_that_is_not_a_workbook_is_refused(self):
        self.client.force_authenticate(self.hr)
        response = self.client.post(
            self.BASE + "upload/", {"file": io.BytesIO(b"nope")},
            format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_the_rows_carry_each_persons_year_to_date(self):
        training.save([{
            "month": datetime.date(2026, m, 1), "staff_pf": "1886",
            "sales_code": "CMM1886", "staff_name": "Christopher K.",
            "branch": "Buruburu", "staff_role": "TELLER", "hours": h,
            "source": "test"} for m, h in enumerate([4, 7, 8], start=1)],
            who="hr")
        self.client.force_authenticate(self.rm)
        response = self.client.get(self.BASE)

        rows = response.data["rows"]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["hours"], 19.0)
        self.assertEqual(rows[0]["branch"], "Buruburu")


class TheCardIsTheBanksOwnDocumentTests(TestCase):
    """What goes out on a signed scorecard, and what must not.

    Each of these was asked for after somebody looked at a real card.
    """

    CODE = "FJ4145"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4145, staff_name="Fridah Jabani",
            sales_code=self.CODE, staff_role="SME BBC", staff_branch="Nyeri",
            staff_unit="Nyeri", active=1, target_training_hours=48,
            target_deposits_value=38_400_000)

    def sheet_text(self):
        from io import BytesIO

        from openpyxl import load_workbook

        from .scorecard_signoff import build_card_workbook

        book = load_workbook(BytesIO(
            build_card_workbook(build_card(self.CODE)).read()))
        return book, "\n".join(
            " ".join("" if c.value is None else str(c.value) for c in row)
            for row in book.active.iter_rows())

    def test_the_bank_is_hfcb(self):
        """HFC is the old name. It must not go out on a document somebody puts
        their signature to."""
        _, text = self.sheet_text()
        # The title line is the bank's own - "<year> <ROLE> OBJECTIVES" - so
        # the test is that HFCB appears on it and the old name does not.
        self.assertIn("HFCB", text)
        self.assertIn("OBJECTIVES", text)
        self.assertNotIn("HFC PERFORMANCE", text)
        self.assertNotIn("HFC ", text.replace("HFCB ", ""))

    def test_the_download_is_read_only(self):
        """A scorecard is a record. Left editable, the first thing that happens
        to a downloaded one is that a figure gets changed and the file is
        forwarded, and nothing then tells that copy from the signed one."""
        book, _ = self.sheet_text()
        self.assertTrue(book.active.protection.sheet)
        self.assertTrue(book.security.lockStructure)

    def test_the_tools_own_plumbing_is_not_on_the_sheet(self):
        """Lines scored and the warehouse table name used to print here. Both
        are this tool's internals, and on somebody's performance record they
        read as a statement about the person."""
        _, text = self.sheet_text()
        self.assertNotIn("Lines scored", text)
        self.assertNotIn("Targets from", text)
        self.assertNotIn("branch_employee_dmc_data", text)
        self.assertNotIn("branch_final_employee_dmc_data", text)

    def test_a_line_with_no_figure_still_says_why_on_the_sheet(self):
        """Removing the summary must not remove the explanation. The reason
        belongs on the line it is about, which is where it still is."""
        _, text = self.sheet_text()
        self.assertIn("Figures to load", text,
                      "an unmeasured line should name where its figure comes "
                      "from")

    def test_an_unmeasured_line_names_the_screen_rather_than_shrugging(self):
        """The old wording stopped at measured-outside-the-warehouse, which
        reads as this-will-never-work. These lines are counts somebody keeps,
        and there is a screen for them."""
        from .live_scorecard import _NOT_IN_WAREHOUSE

        self.assertIn("Figures to load", _NOT_IN_WAREHOUSE)

    def test_the_lines_the_user_asked_about_are_loadable(self):
        """Weighted Sales, covenant tracking and account planning have no feed
        and are not going to get one - they are counts somebody keeps. What
        matters is that there IS a route, the Figures to load screen, and that
        all of them are on it."""
        from .scorecard_manual import MANUAL_ACTUALS

        for code in ("weighted_sales", "weighted_sales_dashboard",
                     "banking_covenant_tracking_should_be_in_iapply",
                     "tooling_and_account_planning_all_customers",
                     "leave_management", "audit", "errors"):
            with self.subTest(code):
                self.assertIn(code, MANUAL_ACTUALS)


class WithdrawingASignatureTests(TestCase):
    """Signing is one button beside a long page, and people press it before
    they meant to. Without a way back the only remedy was editing the
    database, and a figure that can only be corrected in the database is a
    figure nobody can trust."""

    CODE = "FJ4145"
    BASE = "/staff_management/scorecard-automation/my-card/"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4145, staff_name="Fridah Jabani",
            sales_code=self.CODE, staff_role="SME BBC", staff_branch="Nyeri",
            staff_unit="Nyeri", active=1, team_leader_name="A Manager", team_leader="A Manager",
            target_deposits_value=38_400_000)
        self.user = User.objects.create_user("fj", password="x")
        Profile.objects.update_or_create(
            user=self.user, defaults={"sales_code": self.CODE})
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def sign(self):
        response = self.client.post(self.BASE + "sign/", {"role": "owner"})
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_you_can_take_back_a_signature_that_is_still_only_yours(self):
        self.sign()
        response = self.client.post(self.BASE + "unsign/", {})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["withdrawn"])
        self.assertFalse(response.data["signoff"]["signed"])
        self.assertTrue(response.data["signoff"]["withdrawn"])

    def test_the_card_goes_back_to_live_figures(self):
        self.sign()
        self.client.post(self.BASE + "unsign/", {})
        card = self.client.get(self.BASE).data
        self.assertTrue(card["live"], "an unsigned card must read live again")

    def test_the_copy_that_was_signed_is_kept(self):
        """Signed-then-withdrawn is part of the record. Deleting the frozen
        copy would hide it."""
        from .scorecard_automation.models import ScorecardSignoff

        self.sign()
        self.client.post(self.BASE + "unsign/", {"reason": "by mistake"})

        row = ScorecardSignoff.objects.get(sales_code=self.CODE)
        self.assertIsNone(row.signed_at)
        self.assertIsNotNone(row.withdrawn_at)
        self.assertEqual(row.withdrawn_reason, "by mistake")
        self.assertTrue(row.card, "the frozen card was deleted")

    def test_you_can_sign_again_afterwards(self):
        self.sign()
        self.client.post(self.BASE + "unsign/", {})
        again = self.sign()
        self.assertTrue(again.data["signoff"]["signed"])

    def test_withdrawing_what_was_never_signed_is_refused_plainly(self):
        response = self.client.post(self.BASE + "unsign/", {})
        self.assertEqual(response.status_code, 409)
        self.assertIn("nothing to withdraw", response.data["detail"])

    def test_once_the_manager_has_counter_signed_you_cannot_take_it_back(self):
        """Both of you have agreed a document at that point, and one side
        cannot quietly take it back."""
        self.sign()
        manager = User.objects.create_user(
            "mgr", password="x", first_name="A", last_name="Manager")
        boss = APIClient()
        boss.force_authenticate(manager)
        counter = boss.post(self.BASE + "sign/",
                            {"role": "manager", "sales_code": self.CODE})
        self.assertEqual(counter.status_code, 200, counter.data)

        response = self.client.post(self.BASE + "unsign/", {})
        self.assertEqual(response.status_code, 409)
        self.assertIn("counter-signed", response.data["detail"])

    def test_a_superuser_can_fix_a_genuine_mistake(self):
        """Somebody has to be able to, and it is recorded against their
        name."""
        self.sign()
        manager = User.objects.create_user(
            "mgr2", password="x", first_name="A", last_name="Manager")
        boss = APIClient()
        boss.force_authenticate(manager)
        boss.post(self.BASE + "sign/",
                  {"role": "manager", "sales_code": self.CODE})

        root = User.objects.create_superuser("root", "r@x.io", "x")
        Profile.objects.update_or_create(
            user=root, defaults={"sales_code": self.CODE})
        admin = APIClient()
        admin.force_authenticate(root)
        response = admin.post(self.BASE + "unsign/", {})
        self.assertEqual(response.status_code, 200, response.data)

    def test_you_cannot_withdraw_somebody_elses(self):
        """The sales code comes from the signed-in profile, as it does for
        signing, so there is no parameter to forget to check."""
        from .scorecard_automation.models import ScorecardSignoff

        self.sign()
        other = User.objects.create_user("other", password="x")
        Profile.objects.update_or_create(
            user=other, defaults={"sales_code": "XX9999"})
        theirs = APIClient()
        theirs.force_authenticate(other)

        response = theirs.post(self.BASE + "unsign/",
                               {"sales_code": self.CODE})
        self.assertEqual(response.status_code, 409,
                         "it should have looked at THEIR card, not Jabani's")
        self.assertIsNotNone(
            ScorecardSignoff.objects.get(sales_code=self.CODE).signed_at,
            "somebody else's signature was removed")
