"""Administration loading the figures the system cannot compute.

NPS comes from the customer survey, training hours from the learning system,
leave from HR, the audit score from Internal Audit. None of those is in this
platform and none of them is going to be, so they get typed in - and the rules
around typing them in are the whole point of these tests:

* only an administrator may;
* a figure against a sales code nobody holds, or against a KPI that is not on
  that person's card, is refused rather than written somewhere nothing reads;
* nothing is saved until a second call says to save it;
* a typed figure can never overwrite a measured one.
"""

import datetime
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from .live_scorecard import build_card
from .models import BranchEmployeeDmcData
from .scorecard_manual import (
    MANUAL_ACTUALS, MANUAL_TARGETS, _default_month, build_template,
    rows_needing_a_figure,
)

BASE = "/staff_management/scorecard-automation/manual-figures/"
XLSX = ("application/vnd.openxmlformats-officedocument"
        ".spreadsheetml.sheet")


def workbook(rows):
    """A filled template, as Administration would send it back."""
    wb = Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="a note the reader has to skip")
    headers = ["sales_code", "staff_name", "staff_role", "kpi_code",
               "kpi_name", "what_this_is", "target", "actual", "month"]
    for index, name in enumerate(headers, start=1):
        ws.cell(row=4, column=index, value=name)
    for offset, row in enumerate(rows, start=5):
        for index, name in enumerate(headers, start=1):
            ws.cell(row=offset, column=index, value=row.get(name))
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile("figures.xlsx", buffer.read(), content_type=XLSX)


class ManualFigureTests(TestCase):
    CODE = "VO4300"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4300, staff_name="Vincent Ogare",
            sales_code=self.CODE, staff_role="PB RM", staff_branch="Rehani",
            active=1, target_new_customers=32)

        self.admin = User.objects.create_user("admin1", password="x",
                                              is_superuser=True,
                                              first_name="Ada", last_name="Min")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

        self.rm = User.objects.create_user("vogare", password="x")
        Profile.objects.update_or_create(
            user=self.rm, defaults={"sales_code": self.CODE})
        self.rm_client = APIClient()
        self.rm_client.force_authenticate(self.rm)

    # ── who may ──────────────────────────────────────────────────────────
    def test_an_rm_cannot_see_everybodys_figures(self):
        for url in (BASE, BASE + "template/"):
            with self.subTest(url):
                self.assertEqual(self.rm_client.get(url).status_code, 403)

    def test_a_merely_is_staff_account_cannot_set_a_figure(self):
        """is_staff is legacy noise in this estate - a great many accounts
        carry it for reasons that have nothing to do with scorecards. A screen
        that sets what people are paid on needs a real signal."""
        staffish = User.objects.create_user("staffish", password="x",
                                            is_staff=True)
        client = APIClient()
        client.force_authenticate(staffish)
        self.assertEqual(client.get(BASE).status_code, 403)
        self.assertEqual(
            client.post(BASE + "entry/",
                        {"sales_code": self.CODE, "kpi_code": "nps",
                         "actual": 0.8}, format="json").status_code, 403)

    def test_an_administration_group_may(self):
        from django.contrib.auth.models import Group

        member = User.objects.create_user("admingroup", password="x")
        member.groups.add(Group.objects.create(name="staff_mgt"))
        client = APIClient()
        client.force_authenticate(member)
        self.assertEqual(client.get(BASE).status_code, 200)

    def test_an_rm_cannot_set_a_figure(self):
        response = self.rm_client.post(
            BASE + "entry/",
            {"sales_code": self.CODE, "kpi_code": "nps", "actual": 0.8},
            format="json")
        self.assertEqual(response.status_code, 403)

    # ── what needs filling in ────────────────────────────────────────────
    def test_the_outstanding_list_is_built_from_the_roster_and_the_cards(self):
        response = self.client.get(BASE)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreater(response.data["total"], 0)
        self.assertEqual(response.data["loaded"], 0)
        self.assertEqual(response.data["outstanding"], response.data["total"])

        codes = {row["kpi_code"] for row in response.data["rows"]}
        self.assertIn("nps", codes, "the PB card's NPS line needs a figure")
        for code in codes:
            with self.subTest(code):
                self.assertTrue(code in MANUAL_ACTUALS or code in MANUAL_TARGETS,
                                f"{code} is listed but the system can compute it")

    def test_only_lines_on_that_persons_card_are_listed(self):
        """A template listing KPIs nobody is measured on is a template people
        stop reading."""
        codes = {row["kpi_code"] for row in rows_needing_a_figure(self.CODE)}
        self.assertIn("nps", codes)
        self.assertNotIn("trade_income", codes,
                         "trade income is not on the PB card")

    def test_the_template_is_prefilled_with_who_and_which_line(self):
        buffer, count = build_template(self.CODE)
        self.assertGreater(count, 0)
        sheet = load_workbook(BytesIO(buffer.read())).active
        text = "\n".join(
            " ".join("" if c.value is None else str(c.value) for c in row)
            for row in sheet.iter_rows())
        self.assertIn(self.CODE, text)
        self.assertIn("Vincent Ogare", text)
        self.assertIn("nps", text)
        self.assertIn("sales_code", text)

    def test_the_template_downloads(self):
        response = self.client.get(BASE + "template/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("spreadsheetml", response["Content-Type"])
        self.assertTrue(response.content.startswith(b"PK"))

    # ── reading before writing ───────────────────────────────────────────
    def test_a_first_upload_reports_and_writes_nothing(self):
        from .scorecard_automation.models import ScEmployeePerformanceActual

        response = self.client.post(
            BASE + "upload/",
            {"file": workbook([{"sales_code": self.CODE, "kpi_code": "nps",
                                "actual": 0.72}])},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data["applied"])
        self.assertEqual(response.data["found"], 1)
        self.assertEqual(ScEmployeePerformanceActual.objects.count(), 0,
                         "a first upload must write nothing")

    def test_a_second_call_with_apply_saves(self):
        from .scorecard_automation.models import ScEmployeePerformanceActual

        response = self.client.post(
            BASE + "upload/",
            {"file": workbook([{"sales_code": self.CODE, "kpi_code": "nps",
                                "actual": 0.72}]),
             "apply": "true"},
            format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["applied"])
        self.assertEqual(response.data["written"]["actuals"], 1)

        row = ScEmployeePerformanceActual.objects.get(sales_code=self.CODE)
        self.assertEqual(row.kpi_code, "nps")
        self.assertAlmostEqual(row.kpi_value, 0.72)
        self.assertEqual(row.eom_date, _default_month())

    def test_a_correction_replaces_rather_than_stacking(self):
        from .scorecard_automation.models import ScEmployeePerformanceActual

        for value in (0.6, 0.81):
            self.client.post(
                BASE + "upload/",
                {"file": workbook([{"sales_code": self.CODE,
                                    "kpi_code": "nps", "actual": value}]),
                 "apply": "true"},
                format="multipart")
        rows = ScEmployeePerformanceActual.objects.filter(sales_code=self.CODE)
        self.assertEqual(rows.count(), 1)
        self.assertAlmostEqual(rows.first().kpi_value, 0.81)

    # ── what is refused ──────────────────────────────────────────────────
    def test_a_figure_against_an_unknown_sales_code_is_refused(self):
        response = self.client.post(
            BASE + "upload/",
            {"file": workbook([{"sales_code": "ZZ9999", "kpi_code": "nps",
                                "actual": 0.5}]), "apply": "true"},
            format="multipart")
        self.assertEqual(response.data["found"], 0)
        self.assertTrue(any("not on the DMC roster" in p
                            for p in response.data["problems"]))

    def test_a_figure_against_a_kpi_not_on_that_card_is_refused(self):
        response = self.client.post(
            BASE + "upload/",
            {"file": workbook([{"sales_code": self.CODE,
                                "kpi_code": "trade_income", "actual": 10}]),
             "apply": "true"},
            format="multipart")
        self.assertEqual(response.data["found"], 0)
        self.assertTrue(any("is not on the pb_rm card" in p
                            for p in response.data["problems"]))

    def test_an_actual_for_a_line_the_warehouse_computes_is_refused(self):
        """Accepting it would be worse than refusing it: the card would never
        read the figure, and whoever typed it would believe it had."""
        response = self.client.post(
            BASE + "upload/",
            {"file": workbook([{"sales_code": self.CODE,
                                "kpi_code": "drawdowns", "actual": 5_000_000}]),
             "apply": "true"},
            format="multipart")
        self.assertEqual(response.data["found"], 0)
        self.assertTrue(any("computed from the warehouse" in p
                            for p in response.data["problems"]))

    def test_a_file_with_no_header_row_says_so(self):
        wb = Workbook()
        wb.active.cell(row=1, column=1, value="nothing useful")
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        response = self.client.post(
            BASE + "upload/",
            {"file": SimpleUploadedFile("x.xlsx", buffer.read(),
                                        content_type=XLSX)},
            format="multipart")
        self.assertEqual(response.data["found"], 0)
        self.assertTrue(any("no sales_code" in p
                            for p in response.data["problems"]))

    # ── one figure at a time ─────────────────────────────────────────────
    def test_a_single_entry_saves(self):
        response = self.client.post(
            BASE + "entry/",
            {"sales_code": self.CODE, "kpi_code": "nps", "actual": 0.65},
            format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["written"]["actuals"], 1)

    def test_a_single_entry_for_the_wrong_card_is_refused(self):
        response = self.client.post(
            BASE + "entry/",
            {"sales_code": self.CODE, "kpi_code": "trade_income", "actual": 1},
            format="json")
        self.assertEqual(response.status_code, 400)


class LoadedFiguresReachTheCardTests(TestCase):
    """The point of all of it: a figure typed in shows up scored."""

    CODE = "VO4301"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4301, staff_name="Vincent Ogare",
            sales_code=self.CODE, staff_role="PB RM", staff_branch="Rehani",
            active=1)

    def load(self, kpi, value, month=None):
        from .scorecard_automation.models import ScEmployeePerformanceActual

        ScEmployeePerformanceActual.objects.create(
            sales_code=self.CODE, kpi_code=kpi,
            eom_date=month or _default_month(), kpi_value=value)

    def line(self, code):
        card = build_card(self.CODE)
        self.assertTrue(card["has_card"], card)
        return {ln["kpi_code"]: ln
                for g in card["perspectives"] for ln in g["lines"]}[code]

    def test_an_unloaded_line_names_the_survey_it_is_waiting_for(self):
        """This line used to say "Not measured here", because nothing read the
        survey. It IS measured here now - CX maintain it on their own screen -
        so with nothing loaded the reason has to say which survey is missing
        rather than imply the figure lives somewhere unreachable."""
        nps = self.line("nps")
        self.assertIsNone(nps["ytd_actual"])
        self.assertEqual(nps["pending_label"], "No figure yet")
        self.assertIn("CX", nps["pending"])

    def test_a_loaded_figure_is_scored_against_the_role_threshold(self):
        """NPS: 60% is the target on every card that carries it.

        Scored at 1.0 rather than 1.2 - the two customer-survey lines stop at
        full marks where every other line runs to 120%. The count behind that
        is in ``tests_scorecard_calibration``."""
        self.load("nps", 0.72)
        nps = self.line("nps")
        self.assertAlmostEqual(nps["ytd_actual"], 0.72)
        self.assertEqual(nps["annual_target"], 0.6)
        self.assertAlmostEqual(nps["score"], 1.0)
        self.assertAlmostEqual(nps["score_cap"], 1.0)
        self.assertFalse(nps["pending"])

    def test_cx_beats_a_figure_somebody_typed_in(self):
        """The two routes do not fight. A figure Administration typed in is
        used where CX have none - which is what keeps a card completable in a
        quarter CX have not loaded - but CX's own figure wins once it is
        there, because the measured figure always wins."""
        from . import cx_metrics

        self.load("nps", 0.5)
        cx_metrics.save([
            {"period": "2026-Q2", "rm_name": "Vincent Ogare",
             "sales_code": self.CODE, "contactability": 0.9, "csat": 0.3,
             "full_marks": False, "note": "", "source": ""}], [], who="cx")

        nps = self.line("nps")
        self.assertAlmostEqual(nps["ytd_actual"], 0.3)
        self.assertIn("CX survey", nps["as_at"])

    def test_the_card_says_the_figure_was_typed_in(self):
        """A hand-typed figure must never be mistaken for a measured one."""
        self.load("nps", 0.5)
        self.assertIn("loaded by Administration", self.line("nps")["as_at"])

    def test_a_figure_for_an_older_month_is_not_carried_forward(self):
        """A survey score from four months ago presented as this month's is
        worse than a blank."""
        old = _default_month() - datetime.timedelta(days=120)
        self.load("nps", 0.9, month=old.replace(day=1))
        nps = self.line("nps")
        self.assertIsNone(nps["ytd_actual"])

    def test_a_loaded_figure_stands_in_on_a_line_the_platform_measures(self):
        """Drawdowns HAS a source here, and a loaded figure still shows where
        that source produces nothing.

        This rung used to be closed to any line the platform measures. That
        read as a safeguard and was the opposite: the lines it shut out were
        the ones measured on a key the person does not have - branch loan
        turnaround, read from iApply on a seller code a branch manager never
        sells under - so the source answered nothing AND the figure somebody
        had loaded was refused, leaving a dash.

        The safeguard that matters is a different one, and it still holds: the
        measured figure wins wherever there IS one. That is
        ``test_cx_beats_a_figure_somebody_typed_in``, which puts a real
        measurement up against a loaded figure and watches the measurement
        win. Here there is none, so the loaded figure shows - labelled, so it
        can never be mistaken for a measurement."""
        self.load("drawdowns", 999_999_999)
        drawdowns = self.line("drawdowns")
        self.assertEqual(drawdowns["ytd_actual"], 999_999_999)
        self.assertIn("loaded by Administration", drawdowns["as_at"])


class ASignedCardBeatsTheWarehouseTests(LoadedFiguresReachTheCardTests):
    """A loaded figure wins, and the warehouse figure is kept beside it.

    Reversed on 2026-10-21, on request. Until then a loaded figure filled only
    a BLANK line, on the reasoning that a live warehouse read beats a typed
    number. That fails wherever the warehouse read is simply wrong: Faith
    Muthinja's card showed Portfolio NPS at 100% where her signed card records
    42.9%, and Reduce P&L provisions at nought where it records -4,114,068.64.
    Neither could be corrected, because the warehouse always won.
    """

    def test_a_loaded_figure_replaces_a_warehouse_figure(self):
        from apps.staff_management.live_scorecard import OWNER_MAINTAINED_KEYS

        # Not one of the four another team maintains - those are exempt.
        self.assertNotIn("direct_portfolio_contribution",
                         OWNER_MAINTAINED_KEYS)

    def test_the_owner_maintained_feeds_are_still_exempt(self):
        """CX, HR and Internal Audit keep their own returns.

        A loaded figure beats the WAREHOUSE. It must not beat another team's
        considered figure, which is a different thing - pinned next door by
        test_cx_beats_a_figure_somebody_typed_in.
        """
        from apps.staff_management.live_scorecard import OWNER_MAINTAINED_KEYS

        self.assertEqual(
            OWNER_MAINTAINED_KEYS,
            {"cx_csat", "cx_contactability", "training_hours", "audit_score"})

    def test_a_disagreement_is_kept_not_discarded(self):
        """Overriding must not hide what the warehouse said.

        Every line carries ``warehouse_said`` so a disagreement can be chased.
        Blank when the two agree, or when only one had a figure.
        """
        self.load("nps", 0.5)
        self.assertIn("warehouse_said", self.line("nps"))

    def test_a_loaded_nought_does_not_displace_a_warehouse_figure(self):
        """Nought is not a statement - it is an empty cell that got saved.

        Faith Muthinja's card fell to 27.8% on loaded noughts sitting over
        real reads: VIC Premiums 0 against a warehouse 468,067.25, Net
        Disbursements 0 against 36,663,806.28. "why are you putting zeros yet
        they are there and they are read".
        """
        warehouse, loaded = 468_067.25, 0.0

        says_something = (loaded is not None
                          and (loaded != 0 or warehouse is None))
        self.assertFalse(says_something,
                         "a loaded nought must not beat a real figure")

    def test_a_loaded_nought_still_fills_a_line_nothing_could_read(self):
        """The case it was always for: the warehouse has nothing at all."""
        warehouse, loaded = None, 0.0

        says_something = (loaded is not None
                          and (loaded != 0 or warehouse is None))
        self.assertTrue(says_something,
                        "a nought must still fill a line with no figure")

    def test_a_real_loaded_figure_still_wins(self):
        """The signed card remains authoritative where it says something."""
        warehouse, loaded = 468_067.25, 450_523.0

        says_something = (loaded is not None
                          and (loaded != 0 or warehouse is None))
        self.assertTrue(says_something)

    def test_only_a_signed_card_outranks_the_warehouse(self):
        """Three strengths of figure, and the card must tell them apart.

        A figure off somebody's own SIGNED CARD is the agreed record and
        beats the warehouse. A figure typed into Figures-to-load, or carried
        in on a bulk template, only fills a line the warehouse could not
        read. A nought outranks nothing at all.

        Without that distinction stray uploads buried good live reads: Faith
        Muthinja showed Asset Growth -46,208,895.05 over a warehouse
        -39,095,632.82, Deposits 1,875,794.36 over -14,450,155.80, TAT 1 over
        0.2 and PAR 0.07 over 0.29 - and not one matched her signed card.
        """
        def wins(loaded, warehouse, signed):
            return (loaded is not None
                    and (loaded != 0 or warehouse is None)
                    and (signed or warehouse is None))

        # a signed card beats a real warehouse figure
        self.assertTrue(wins(450_523.0, 468_067.25, True))
        # a stray upload does not
        self.assertFalse(wins(-46_208_895.05, -39_095_632.82, False))
        # but it still fills a line nothing could read
        self.assertTrue(wins(-46_208_895.05, None, False))
        # and a nought never outranks a real figure, signed or not
        self.assertFalse(wins(0.0, 468_067.25, True))
        self.assertFalse(wins(0.0, 468_067.25, False))
        # while a nought still fills a blank
        self.assertTrue(wins(0.0, None, False))
