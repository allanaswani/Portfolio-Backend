"""Guards for the HR employee-master upload (``employee-data/upload-csv/``).

The rule this endpoint has to keep is that an upload can only ever ADD to what
HR already has. It keys on ``staff_id`` so a re-upload updates in place; a blank
cell leaves the stored value alone; and nobody who is absent from the file is
touched. Get any of those wrong and one partial extract silently wipes columns
across the whole 1,271-row roster.

``employee_table`` is a ``managed = False`` warehouse mirror, so a test database
has no such table. It is built here from the model Django already carries for it
so the writes run against a real schema rather than a mock — which is also what
proves the column names in the loader exist.
"""

import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.gceo_dashboard.models import EmployeeRosterOverlay, EmployeeTable
from apps.staff_management import employee_master_views as emv

URL = "/staff_management/employee-data/upload-csv/"


def employees():
    """Read employee_table back through the SAME alias the loader writes.

    The router reads unmanaged models from ``datawarehouse`` and writes them to
    ``default``; on production the two aliases are one database, but in a test
    they are not, so an unpinned read here would assert against the wrong one.
    """
    return EmployeeTable.objects.using(emv.employee_db())

FULL_HEADER = ",".join(emv.TEMPLATE_COLUMNS)


def csv_file(text, name="employees.csv"):
    buf = io.BytesIO(text.encode("utf-8"))
    buf.name = name
    return buf


class TemplateColumnTests(SimpleTestCase):
    """The template has to carry every field the roster page shows."""

    def test_every_employee_table_column_is_in_the_template(self):
        skip = {"id", "updated_at"}
        model_columns = [
            f.name for f in EmployeeTable._meta.concrete_fields if f.name not in skip
        ]
        missing = [c for c in model_columns if c not in emv.TEMPLATE_COLUMNS]
        self.assertEqual(missing, [], f"template is missing {missing}")

    def test_the_three_hand_maintained_columns_are_in_the_template(self):
        # standard_department / current_role / previous_role live in the overlay,
        # not in employee_table — one upload must still maintain both tables.
        for col in ("standard_department", "current_role", "previous_role"):
            self.assertIn(col, emv.TEMPLATE_COLUMNS)

    def test_staff_id_leads_and_nothing_repeats(self):
        self.assertEqual(emv.TEMPLATE_COLUMNS[0], "staff_id")
        self.assertEqual(len(emv.TEMPLATE_COLUMNS), len(set(emv.TEMPLATE_COLUMNS)))


class ParsingTests(SimpleTestCase):
    def test_staff_id_shapes_collapse_to_one_key(self):
        for raw in ("4022", "4022.0", " 4022.00000 ", "4,022"):
            self.assertEqual(emv.canon_staff_id(raw), "4022")
        self.assertEqual(emv.canon_staff_id(""), "")
        self.assertEqual(emv.canon_staff_id(None), "")

    def test_dates_parse_in_the_shapes_excel_exports(self):
        for raw in ("2020-01-15", "15/01/2020", "15-Jan-2020", "15 Jan 2020"):
            parsed = emv.parse_date(raw)
            self.assertIsNotNone(parsed, raw)
            self.assertEqual((parsed.year, parsed.month, parsed.day), (2020, 1, 15))
        for blank in ("", "  ", "NaT", "-", "not a date"):
            self.assertIsNone(emv.parse_date(blank))

    def test_flags_accept_yes_no_as_well_as_1_0(self):
        self.assertEqual(emv.parse_int("Yes"), 1)
        self.assertEqual(emv.parse_int("no"), 0)
        self.assertEqual(emv.parse_int("1"), 1)
        self.assertEqual(emv.parse_int("1,200"), 1200)
        self.assertIsNone(emv.parse_int(""))

    def test_headers_are_matched_tolerantly(self):
        self.assertEqual(emv.normalize_header(" Staff ID "), "staff_id")
        self.assertEqual(emv.normalize_header("PF Number"), "staff_id")
        self.assertEqual(emv.normalize_header("Date Of Employment"), "date_of_employment")
        self.assertEqual(emv.normalize_header("Exit Date"), "staff_exit_date")


class UploadTests(TransactionTestCase):
    """End-to-end against a real ``employee_table``."""

    def setUp(self):
        with connection.schema_editor() as editor:
            editor.create_model(EmployeeTable)
        self.addCleanup(self._drop_employee_table)

        User = get_user_model()
        self.admin = User.objects.create_user("hradmin", password="x")
        self.admin.groups.add(Group.objects.create(name="staff_mgt"))
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    @staticmethod
    def _drop_employee_table():
        with connection.schema_editor() as editor:
            editor.delete_model(EmployeeTable)

    def post(self, text):
        return self.client.post(URL, {"file": csv_file(text)}, format="multipart")

    # ── the happy path ───────────────────────────────────────────────────────
    def test_a_full_row_lands_in_every_column(self):
        row = {c: "" for c in emv.TEMPLATE_COLUMNS}
        row.update({
            "staff_id": "4022", "name": "Grace Kanja", "national_id": "12345678",
            "email": "grace@hfgroup.co.ke", "gender": "F", "service_code": "SC1",
            "division": "Retail", "department": "Retail Banking", "unit": "Branch",
            "org_unit": "BR-230", "grade": "5", "job_title": "Relationship Manager",
            "date_of_birth": "1990-05-04", "age": "36",
            "date_of_employment": "15/01/2020", "service_years": "6",
            "exit": "0", "promotion": "1", "promotion_date": "01/07/2025",
            "new": "0", "hfdi_erp_id": "77",
            "standard_department": "Retail Banking",
            "current_role": "Relationship Manager", "previous_role": "Teller",
        })
        text = FULL_HEADER + "\n" + ",".join(row[c] for c in emv.TEMPLATE_COLUMNS) + "\n"

        resp = self.post(text)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["created"], 1)
        self.assertEqual(resp.data["error_count"], 0, resp.data["errors"])

        emp = employees().get()
        self.assertEqual(int(emp.staff_id), 4022)
        self.assertEqual(emp.name, "Grace Kanja")
        self.assertEqual(emp.department, "Retail Banking")
        self.assertEqual(emp.org_unit, "BR-230")
        self.assertEqual(emp.grade, "5")
        self.assertEqual(emp.job_title, "Relationship Manager")
        self.assertEqual(emp.age, 36)
        self.assertEqual(emp.service_years, 6)
        self.assertEqual(emp.hfdi_erp_id, 77)
        self.assertEqual(emp.date_of_employment.date().isoformat(), "2020-01-15")
        self.assertEqual(emp.promotion_date.isoformat(), "2025-07-01")

        # The three hand-maintained columns went to the overlay, not employee_table.
        overlay = EmployeeRosterOverlay.objects.get(staff_id="4022")
        self.assertEqual(overlay.standard_department, "Retail Banking")
        self.assertEqual(overlay.previous_role, "Teller")
        self.assertEqual(overlay.updated_by, "hradmin")

    # ── the rules that protect existing HR data ──────────────────────────────
    def test_reupload_updates_in_place_and_never_duplicates(self):
        first = f"{FULL_HEADER}\n" + "4022," + ",".join(
            ["Grace Kanja"] + [""] * (len(emv.TEMPLATE_COLUMNS) - 2)) + "\n"
        self.post(first)
        self.assertEqual(employees().count(), 1)

        second = "staff_id,name,grade\n4022,Grace Kanja Mwangi,6\n"
        resp = self.post(second)
        self.assertEqual(resp.data["updated"], 1)
        self.assertEqual(resp.data["created"], 0)
        self.assertEqual(employees().count(), 1)

        emp = employees().get()
        self.assertEqual(emp.name, "Grace Kanja Mwangi")
        self.assertEqual(emp.grade, "6")

    def test_a_blank_cell_leaves_the_stored_value_alone(self):
        """A partial extract must not wipe the columns it does not carry."""
        self.post("staff_id,name,department,grade\n4022,Grace Kanja,Retail Banking,5\n")

        # Same person, department blank, only the grade filled in.
        resp = self.post("staff_id,name,department,grade\n4022,Grace Kanja,,6\n")
        self.assertEqual(resp.data["updated"], 1)

        emp = employees().get()
        self.assertEqual(emp.department, "Retail Banking")  # untouched
        self.assertEqual(emp.grade, "6")

    def test_nobody_absent_from_the_file_is_removed(self):
        self.post("staff_id,name\n4022,Grace Kanja\n5001,John Mwangi\n")
        self.assertEqual(employees().count(), 2)

        self.post("staff_id,name\n4022,Grace Kanja\n")
        self.assertEqual(employees().count(), 2)

    def test_a_column_absent_from_the_csv_is_never_written(self):
        self.post("staff_id,name,job_title\n4022,Grace Kanja,Relationship Manager\n")
        self.post("staff_id,name\n4022,Grace Kanja\n")
        self.assertEqual(employees().get().job_title, "Relationship Manager")

    def test_an_unchanged_row_reports_unchanged_rather_than_updated(self):
        self.post("staff_id,name,grade\n4022,Grace Kanja,5\n")
        resp = self.post("staff_id,name,grade\n4022,Grace Kanja,5\n")
        self.assertEqual(resp.data["unchanged"], 1)
        self.assertEqual(resp.data["updated"], 0)

    def test_rows_with_no_staff_id_are_skipped_not_imported(self):
        resp = self.post("staff_id,name\n,Nobody\n4022,Grace Kanja\n")
        self.assertEqual(resp.data["skipped"], 1)
        self.assertEqual(resp.data["created"], 1)
        self.assertEqual(employees().count(), 1)

    def test_one_bad_row_does_not_abort_the_import(self):
        text = ("staff_id,name,age\n"
                "4022,Grace Kanja,36\n"
                "ABC,Bad Row,x\n"          # staff_id is not a number
                "5001,John Mwangi,41\n")
        resp = self.post(text)
        self.assertEqual(resp.data["created"], 2)
        self.assertEqual(resp.data["error_count"], 1)
        self.assertEqual(resp.data["errors"][0]["row"], 3)
        self.assertEqual(employees().count(), 2)

    def test_headers_from_hrs_own_export_still_match(self):
        resp = self.post("Staff ID,Full Name,Date Of Employment,Exit Date\n"
                         "4022,Grace Kanja,15/01/2020,\n")
        self.assertEqual(resp.data["created"], 1, resp.data)
        emp = employees().get()
        self.assertEqual(emp.name, "Grace Kanja")
        self.assertEqual(emp.date_of_employment.date().isoformat(), "2020-01-15")

    # ── request-level guards ─────────────────────────────────────────────────
    def test_a_csv_without_staff_id_is_rejected_whole(self):
        resp = self.post("name,department\nGrace Kanja,Retail Banking\n")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("staff_id", resp.data["error"])
        self.assertEqual(employees().count(), 0)

    def test_no_file_and_non_csv_are_rejected(self):
        self.assertEqual(self.client.post(URL, {}, format="multipart").status_code, 400)
        resp = self.client.post(
            URL, {"file": csv_file("staff_id\n4022\n", name="employees.xlsx")},
            format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_only_staff_management_may_upload(self):
        User = get_user_model()
        outsider = User.objects.create_user("someone", password="x")
        client = APIClient()
        client.force_authenticate(outsider)
        resp = client.post(URL, {"file": csv_file("staff_id,name\n4022,Grace\n")},
                           format="multipart")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(employees().count(), 0)

    def test_anonymous_is_rejected(self):
        client = APIClient()
        resp = client.post(URL, {"file": csv_file("staff_id,name\n4022,Grace\n")},
                           format="multipart")
        self.assertIn(resp.status_code, (401, 403))
