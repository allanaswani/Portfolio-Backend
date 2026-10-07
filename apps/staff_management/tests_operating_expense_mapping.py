"""operating_expense_mapping — which expense line each GL account rolls up to.

Finance kept this as ``Operating_expenses_mapping.xlsx``: 249 GL accounts, each
tagged with an expense type, an operating-expense line, and whether the spend is
Controllable or Installed. The facts worth guarding are:

* the spreadsheet seeds the table, so the screen opens populated;
* a GL is unique, and re-sending one **re-tags** it instead of adding a second
  row that would put the same money on two expense lines;
* the whole spreadsheet uploads **as the .xlsx**, with no Save-As-CSV step —
  that gate used to reject it after the browser had already accepted the file;
* a numeric GL that Excel hands over as ``170150001.0`` is the same account as
  ``170150001``, not a 250th one.
"""
import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.staff_management.models import OperatingExpenseMapping

LIST = "/staff_management/operating-expense-mappings/"
UPLOAD = "/staff_management/operating-expense-mappings/upload-csv/"
HEADER = ["gl", "expense_type", "operating_expense", "outflow_type", "actual_gl_name"]

SEEDED = 249


def workbook(rows, header=HEADER, *, blank_lead=0, trailing_blanks=0):
    """An .xlsx upload built the way Excel would hand one over.

    ``blank_lead`` puts empty rows above the header (an export with a title
    band) and ``trailing_blanks`` puts them below the data (what deleting rows
    in Excel leaves behind in the sheet's reported extent).
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(blank_lead):
        ws.append([None] * len(header))
    ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    for _ in range(trailing_blanks):
        ws.append([None] * len(header))
    buffer = io.BytesIO()
    wb.save(buffer)
    return SimpleUploadedFile(
        "Operating_expenses_mapping.xlsx", buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def csv_file(lines, header=",".join(HEADER)):
    body = "\n".join([header, *lines]) + "\n"
    return SimpleUploadedFile("mapping.csv", body.encode(), content_type="text/csv")


class SeedTests(TestCase):
    """Migration 0023 runs when the test database is built."""

    def test_the_spreadsheet_is_loaded(self):
        self.assertEqual(OperatingExpenseMapping.objects.count(), SEEDED)

    def test_the_duplicated_gl_was_seeded_once(self):
        """The sheet carries 230000023 twice, both rows identical."""
        self.assertEqual(OperatingExpenseMapping.objects.filter(gl="230000023").count(), 1)

    def test_values_are_as_supplied(self):
        row = OperatingExpenseMapping.objects.get(gl="170150001")
        self.assertEqual(row.expense_type, "ICT Expense")
        self.assertEqual(row.operating_expense, "Software")
        self.assertEqual(row.actual_gl_name, "IT Maintenance")

    def test_blank_cells_are_empty_strings_not_guesses(self):
        row = OperatingExpenseMapping.objects.get(gl="144000006")
        self.assertEqual(row.outflow_type, "")
        self.assertEqual(row.actual_gl_name, "")

    def test_outflow_vocabulary_is_only_what_finance_supplied(self):
        self.assertEqual(
            sorted(set(OperatingExpenseMapping.objects.values_list("outflow_type", flat=True))),
            ["", "Controllable", "Installed"],
        )

    def test_a_gl_cannot_be_stored_twice(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OperatingExpenseMapping.objects.create(
                gl="170150001", expense_type="ICT Expense", operating_expense="Software")


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="fin", password="pw12345", email="fin@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _payload(self, **over):
        base = {"gl": "999000001", "expense_type": "Office Expenses",
                "operating_expense": "Stationery", "outflow_type": "Controllable",
                "actual_gl_name": "Stationery and printing"}
        base.update(over)
        return base

    def test_list_returns_the_seeded_mapping_paginated(self):
        response = self.client.get(LIST)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], SEEDED)

    def test_anonymous_cannot_read_the_mapping(self):
        self.assertIn(APIClient().get(LIST).status_code, (401, 403))

    def test_create_then_resubmit_retags_rather_than_duplicating(self):
        first = self.client.post(LIST, self._payload(), format="json")
        self.assertEqual(first.status_code, 201, first.content)

        second = self.client.post(
            LIST, self._payload(expense_type="ICT Expense"), format="json")
        self.assertEqual(second.status_code, 201, second.content)

        rows = OperatingExpenseMapping.objects.filter(gl="999000001")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().expense_type, "ICT Expense")
        self.assertEqual(rows.first().updated_by, "fin")

    def test_excel_float_tail_is_the_same_account(self):
        self.client.post(LIST, self._payload(), format="json")
        self.client.post(LIST, self._payload(gl="999000001.0",
                                             expense_type="Staff costs"), format="json")
        rows = OperatingExpenseMapping.objects.filter(gl="999000001")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().expense_type, "Staff costs")

    def test_surrounding_space_is_the_same_account(self):
        self.client.post(LIST, self._payload(), format="json")
        self.client.post(LIST, self._payload(gl="  999000001  "), format="json")
        self.assertEqual(OperatingExpenseMapping.objects.filter(gl="999000001").count(), 1)

    def test_a_gl_can_be_corrected_in_place(self):
        """The reason gl is unique rather than the primary key: a mistyped
        account has to be fixable without deleting and re-adding the row."""
        row = OperatingExpenseMapping.objects.get(gl="170150001")
        response = self.client.patch(f"{LIST}{row.pk}/", {"gl": "170150002"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertEqual(row.gl, "170150002")
        self.assertEqual(row.operating_expense, "Software")
        self.assertEqual(row.updated_by, "fin")

    def test_an_edit_keeps_its_before_image(self):
        row = OperatingExpenseMapping.objects.get(gl="170150001")
        self.client.patch(f"{LIST}{row.pk}/", {"outflow_type": "Installed"}, format="json")
        self.assertEqual(
            row.history.order_by("history_date").values_list("outflow_type", flat=True).last(),
            "Installed",
        )

    def test_a_row_can_be_deleted(self):
        row = OperatingExpenseMapping.objects.get(gl="170150001")
        self.assertEqual(self.client.delete(f"{LIST}{row.pk}/").status_code, 204)
        self.assertFalse(OperatingExpenseMapping.objects.filter(gl="170150001").exists())

    def test_expense_type_is_required(self):
        bad = self.client.post(LIST, self._payload(expense_type=""), format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("expense_type", bad.data)

    def test_search_finds_an_account_by_any_text_column(self):
        for term in ("170150001", "ICT", "Software", "IT Maintenance"):
            response = self.client.get(LIST, {"search": term})
            self.assertGreaterEqual(response.data["count"], 1, term)

    def test_filter_by_outflow_type(self):
        response = self.client.get(LIST, {"outflow_type": "Installed"})
        self.assertEqual(response.data["count"], 71)


class XlsxUploadTests(TestCase):
    """The spreadsheet uploads as the .xlsx Finance already has."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="fin", password="pw12345", email="fin@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_an_xlsx_is_accepted_and_loaded(self):
        upload = workbook([
            ("606010001", "Office Expenses", "Cleaning", "Controllable", "Cleaning services"),
            ("606010002", "Office Expenses", "Security", "Installed", ""),
        ])
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertEqual(OperatingExpenseMapping.objects.get(gl="606010002").outflow_type,
                         "Installed")

    def test_a_numeric_gl_cell_does_not_arrive_as_a_float(self):
        """Excel stores a 9-digit code as a number. Written back as text that
        is "606010001.0", which would be a different account."""
        upload = workbook([(606010001, "Office Expenses", "Cleaning", "Controllable", "")])
        self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertTrue(OperatingExpenseMapping.objects.filter(gl="606010001").exists())
        self.assertFalse(OperatingExpenseMapping.objects.filter(gl="606010001.0").exists())

    def test_reupload_retags_the_whole_sheet_without_duplicating(self):
        before = OperatingExpenseMapping.objects.count()
        rows = [("170150001", "ICT Expense", "Software", "Installed", "IT Maintenance")]
        self.client.post(UPLOAD, {"file": workbook(rows)}, format="multipart")
        self.client.post(UPLOAD, {"file": workbook(rows)}, format="multipart")
        self.assertEqual(OperatingExpenseMapping.objects.count(), before)
        self.assertEqual(OperatingExpenseMapping.objects.get(gl="170150001").outflow_type,
                         "Installed")

    def test_accounts_absent_from_a_reupload_are_left_alone(self):
        """A filtered export must not be read as "delete everything else"."""
        self.client.post(
            UPLOAD,
            {"file": workbook([("170150001", "ICT Expense", "Software", "Installed", "")])},
            format="multipart")
        self.assertTrue(OperatingExpenseMapping.objects.filter(gl="144000006").exists())

    def test_blank_rows_above_and_below_the_data_are_ignored(self):
        before = OperatingExpenseMapping.objects.count()
        upload = workbook(
            [("606010003", "Office Expenses", "Water", "Installed", "")],
            blank_lead=2, trailing_blanks=25)
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(OperatingExpenseMapping.objects.count(), before + 1)

    def test_a_sheet_missing_a_required_column_is_refused_whole(self):
        upload = workbook([("606010004", "Office Expenses")],
                          header=["gl", "expense_type"])
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("operating_expense", str(response.data["error"]))

    def test_the_optional_columns_may_be_absent_entirely(self):
        upload = workbook([("606010005", "Office Expenses", "Postage")],
                          header=["gl", "expense_type", "operating_expense"])
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        row = OperatingExpenseMapping.objects.get(gl="606010005")
        self.assertEqual(row.outflow_type, "")
        self.assertEqual(row.actual_gl_name, "")

    def test_headers_in_finance_spelling_still_match(self):
        """Excel's own header row is title-cased with spaces, not snake_case."""
        upload = workbook(
            [("606010006", "Office Expenses", "Rates", "Installed", "Land rates")],
            header=["GL", "Expense Type", "Operating Expense", "Outflow Type", "Actual GL Name"])
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(OperatingExpenseMapping.objects.get(gl="606010006").actual_gl_name,
                         "Land rates")

    def test_a_csv_still_works(self):
        upload = csv_file(["606010007,Office Expenses,Telephone,Controllable,Telephone bills"])
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(OperatingExpenseMapping.objects.get(gl="606010007").operating_expense,
                         "Telephone")

    def test_the_legacy_xls_format_is_named_rather_than_silently_failing(self):
        upload = SimpleUploadedFile("mapping.xls", b"\xd0\xcf\x11\xe0legacy",
                                    content_type="application/vnd.ms-excel")
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn(".xlsx", str(response.data["error"]))

    def test_a_bad_row_fails_alone_and_the_rest_still_load(self):
        upload = workbook([
            ("606010008", "Office Expenses", "Fuel", "Controllable", ""),
            ("", "Office Expenses", "Nothing", "", ""),
            ("606010009", "Office Expenses", "Parking", "Controllable", ""),
        ])
        response = self.client.post(UPLOAD, {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(OperatingExpenseMapping.objects.filter(gl="606010008").exists())
        self.assertTrue(OperatingExpenseMapping.objects.filter(gl="606010009").exists())
        self.assertFalse(OperatingExpenseMapping.objects.filter(gl="").exists())
