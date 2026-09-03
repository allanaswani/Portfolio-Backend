"""Guards for the HR employee-master upload (``employee-data/upload-csv/``).

This endpoint is a port of the data team's
``cleaning_and_updating_staff_information.py``, so the tests pin the script's
contract rather than a convenient one:

* ``full_list`` **inserts only** — a person already on the roster is left alone,
  which is what makes re-uploading last month's workbook safe;
* ``exits`` / ``promotions`` update **ten columns and no others** — a promotion
  file must not overwrite an email or a date of birth;
* ``age``, ``service_years``, ``exit``, ``promotion``, ``new``, ``grade`` and
  ``division`` are DERIVED, never taken from the sheet;
* nobody is ever deleted;
* the same workbook maintains ``hfdi_employee_data``.

``employee_table`` is a ``managed = False`` warehouse mirror, so a test database
has no such table. It is built here from the model Django already carries for it,
so the loader runs against a real schema — which is also what proves its column
names exist.
"""

import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.gceo_dashboard.models import EmployeeTable
from apps.hfdi.models import HfdiEmployeeData
from apps.staff_management import employee_master_views as emv

URL = "/staff_management/employee-data/upload-csv/"

# HR's own header row, in HR's own spelling.
HEADER = emv.WORKBOOK_COLUMNS


def employees():
    """Read employee_table back through the SAME alias the loader writes.

    The router reads unmanaged models from ``datawarehouse`` and writes them to
    ``default``; on production the two aliases are one database, but in a test
    they are not, so an unpinned read here would assert against the wrong one.
    """
    return EmployeeTable.objects.using(emv.employee_db())


def workbook(sheets, name="staff.xlsx"):
    """An .xlsx of ``{sheet_name: [row dict, ...]}``, columns in HR's order."""
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet, rows in sheets.items():
            frame = pd.DataFrame(rows, columns=HEADER)
            frame.to_excel(writer, sheet_name=sheet, index=False)
    buf.seek(0)
    buf.name = name
    return buf


def person(staffid, name, **overrides):
    row = {column: None for column in HEADER}
    row.update({"staffid": staffid, "name": name})
    row.update(overrides)
    return row


class WorkbookShapeTests(SimpleTestCase):
    """The template has to match the file HR actually produces."""

    def test_the_header_is_hrs_spelling_not_the_databases(self):
        # The source workbook misspells this one; renaming it would silently
        # stop the column matching.
        self.assertIn("date of employement", emv.WORKBOOK_COLUMNS)
        for column in ("staffid", "idno", "org unit", "service yrs", "effective date"):
            self.assertIn(column, emv.WORKBOOK_COLUMNS)

    def test_every_header_maps_to_a_real_employee_table_column(self):
        model_fields = {f.name for f in EmployeeTable._meta.concrete_fields}
        for column in emv.WORKBOOK_COLUMNS:
            mapped = emv.normalize_header(column)
            self.assertIn(mapped, model_fields, f"{column} -> {mapped}")

    def test_the_three_sheets_are_the_scripts_three_sheets(self):
        self.assertEqual(emv.SHEETS, ("full_list", "exits", "promotions"))

    def test_sheet_names_are_matched_loosely(self):
        for raw in ("full_list", "Full List", " FULL-LIST "):
            self.assertEqual(emv.normalize_sheet_name(raw), "full_list")

    def test_the_update_touches_only_the_scripts_ten_columns(self):
        self.assertEqual(sorted(emv.UPDATE_COLUMNS), sorted([
            "exit", "staff_exit_date", "promotion", "promotion_date",
            "service_code", "department", "unit", "org_unit", "grade", "job_title",
        ]))


class CleanerTests(SimpleTestCase):
    """The derivations, straight out of the script."""

    def clean(self, rows):
        import pandas as pd
        return emv.clean_staff_list(pd.DataFrame(rows, columns=HEADER))

    def test_a_row_with_no_name_is_dropped(self):
        rows = self.clean([person(1, "Grace Kanja"), person(2, None)])
        self.assertEqual([r["name"] for r in rows], ["Grace Kanja"])

    def test_age_and_service_years_are_recomputed_not_read(self):
        rows = self.clean([person(
            1, "Grace Kanja", **{"date of birth": "1990-01-01",
                                 "date of employement": "2020-01-01",
                                 "age": 999, "service yrs": 999})])
        self.assertNotEqual(rows[0]["age"], 999)
        self.assertNotEqual(rows[0]["service_years"], 999)
        self.assertGreater(rows[0]["age"], 30)
        self.assertGreaterEqual(rows[0]["service_years"], 5)

    def test_grade_is_mapped_then_padded_to_two_digits(self):
        rows = self.clean([
            person(1, "A", grade="O2"), person(2, "B", grade="UNC"),
            person(3, "C", grade="5"),  person(4, "D", grade="10"),
        ])
        self.assertEqual([r["grade"] for r in rows], ["02", "01", "05", "10"])

    def test_division_follows_the_department_for_hfbi_and_hfdi(self):
        rows = self.clean([
            person(1, "A", department="HFDI", division="Retail"),
            person(2, "B", department="HFBI", division="Retail"),
            person(3, "C", department="Retail Banking", division="Retail"),
        ])
        self.assertEqual([r["division"] for r in rows], ["HFDI", "HFBI", "Retail"])

    def test_the_flags_come_from_the_dates(self):
        rows = self.clean([
            person(1, "Exited", **{"staff_exit_date": "2026-02-01"}),
            person(2, "Promoted", **{"effective date": "2026-03-01"}),
            person(3, "Neither"),
        ])
        self.assertEqual([r["exit"] for r in rows], [1, 0, 0])
        self.assertEqual([r["promotion"] for r in rows], [0, 1, 0])

    def test_new_is_set_only_for_this_years_hires(self):
        import datetime as dt
        this_year = dt.date.today().year
        rows = self.clean([
            person(1, "Fresh", **{"date of employement": f"{this_year}-02-01"}),
            person(2, "Old",   **{"date of employement": "2015-02-01"}),
        ])
        self.assertEqual([r["new"] for r in rows], [1, 0])

    def test_a_missing_optional_column_does_not_abort_the_sheet(self):
        """The script would KeyError and abandon the file, telling nobody why."""
        import pandas as pd
        rows = emv.clean_staff_list(pd.DataFrame([{"staffid": 1, "name": "Grace"}]))
        self.assertEqual(rows[0]["staff_id"], 1)
        self.assertIsNone(rows[0]["department"])

    def test_a_sheet_with_no_name_column_is_reported_not_silently_empty(self):
        import pandas as pd
        with self.assertRaises(ValueError):
            emv.clean_staff_list(pd.DataFrame([{"staffid": 1}]))

    def test_staff_id_shapes_collapse_to_one_key(self):
        for raw in ("4022", "4022.0", " 4022.00000 ", "4,022", 4022.0):
            self.assertEqual(emv.canon_staff_id(raw), 4022)
        for blank in ("", "  ", "nan", None):
            self.assertIsNone(emv.canon_staff_id(blank))


class HfdiReshapeTests(SimpleTestCase):
    def test_only_hfdi_rows_are_taken_and_the_name_is_cleaned(self):
        rows = [
            {"staff_id": 1, "name": "  grace   KANJA ", "department": "HFDI",
             "unit": "Sales", "job_title": "Agent", "date_of_employment": None,
             "staff_exit_date": None},
            {"staff_id": 2, "name": "John", "department": "Retail Banking",
             "unit": None, "job_title": None, "date_of_employment": None,
             "staff_exit_date": None},
        ]
        out = emv.clean_department_staff_list(rows, "HFDI")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["staff_name"], "Grace Kanja")
        self.assertEqual(out[0]["sales_code"], "1")
        self.assertEqual(out[0]["active"], 1)

    def test_an_exit_date_makes_the_hfdi_record_inactive(self):
        import datetime as dt
        rows = [{"staff_id": 1, "name": "Grace", "department": "HFDI", "unit": None,
                 "job_title": None, "date_of_employment": None,
                 "staff_exit_date": dt.date(2026, 2, 1)}]
        out = emv.clean_department_staff_list(rows, "HFDI")
        self.assertEqual((out[0]["active"], out[0]["staff_exit"]), (0, 1))

    def test_start_date_is_january_for_anyone_hired_before_this_year(self):
        import datetime as dt
        today = dt.date(2026, 6, 1)
        self.assertEqual(emv._hfdi_start_date(dt.date(2020, 5, 9), today), dt.date(2026, 1, 1))
        self.assertEqual(emv._hfdi_start_date(dt.date(2026, 5, 9), today), dt.date(2026, 5, 1))
        self.assertIsNone(emv._hfdi_start_date(None, today))


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

    def post(self, sheets, name="staff.xlsx"):
        return self.client.post(URL, {"file": workbook(sheets, name)}, format="multipart")

    # ── full_list ────────────────────────────────────────────────────────────
    def test_a_full_row_lands_in_every_column(self):
        resp = self.post({"full_list": [person(
            4022, "Grace Kanja", **{
                "idno": "12345678", "email": "grace@hfgroup.co.ke",
                "date of birth": "1990-05-04", "gender": "F",
                "date of employement": "2020-01-15", "service code": "SC1",
                "division": "Retail", "department": "Retail Banking",
                "unit": "Branch", "org unit": "BR-230", "grade": "5",
                "job title": "Relationship Manager"})]})

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["inserted"], 1)
        self.assertEqual(resp.data["error_count"], 0, resp.data["errors"])

        emp = employees().get()
        self.assertEqual(int(emp.staff_id), 4022)
        self.assertEqual(emp.name, "Grace Kanja")
        self.assertEqual(emp.national_id, "12345678")
        self.assertEqual(emp.email, "grace@hfgroup.co.ke")
        self.assertEqual(emp.department, "Retail Banking")
        self.assertEqual(emp.org_unit, "BR-230")
        self.assertEqual(emp.grade, "05")           # padded
        self.assertEqual(emp.job_title, "Relationship Manager")
        self.assertEqual(emp.date_of_employment.date().isoformat(), "2020-01-15")
        self.assertEqual(emp.hfdi_erp_id, 0)
        self.assertEqual(emp.exit, 0)

    def test_full_list_inserts_only_and_leaves_existing_people_alone(self):
        """Re-uploading last month's workbook must not rewrite the roster."""
        self.post({"full_list": [person(4022, "Grace Kanja", grade="5",
                                        **{"job title": "Relationship Manager"})]})
        resp = self.post({"full_list": [
            person(4022, "SOMEONE ELSE", grade="9", **{"job title": "Cleaner"}),
            person(5001, "John Mwangi"),
        ]})

        self.assertEqual(resp.data["inserted"], 1)          # only the new person
        self.assertEqual(resp.data["already_present"], 1)
        self.assertEqual(employees().count(), 2)

        emp = employees().get(staff_id=4022)
        self.assertEqual(emp.name, "Grace Kanja")           # untouched
        self.assertEqual(emp.job_title, "Relationship Manager")

    def test_nobody_absent_from_the_file_is_removed(self):
        self.post({"full_list": [person(4022, "Grace Kanja"),
                                 person(5001, "John Mwangi")]})
        self.post({"full_list": [person(4022, "Grace Kanja")]})
        self.assertEqual(employees().count(), 2)

    def test_a_duplicate_staff_id_inside_one_sheet_is_inserted_once(self):
        resp = self.post({"full_list": [person(4022, "Grace Kanja"),
                                        person(4022, "Grace Kanja")]})
        self.assertEqual(resp.data["inserted"], 1)
        self.assertEqual(employees().count(), 1)

    def test_promotion_is_never_set_from_the_full_list_sheet(self):
        resp = self.post({"full_list": [person(
            4022, "Grace Kanja", **{"effective date": "2026-03-01"})]})
        self.assertEqual(resp.data["inserted"], 1)
        emp = employees().get()
        self.assertEqual(emp.promotion, 0)
        self.assertIsNone(emp.promotion_date)

    # ── exits / promotions ───────────────────────────────────────────────────
    def test_the_exits_sheet_marks_the_person_exited(self):
        self.post({"full_list": [person(4022, "Grace Kanja")]})
        resp = self.post({"exits": [person(
            4022, "Grace Kanja", **{"staff_exit_date": "2026-02-01"})]})

        self.assertEqual(resp.data["updated"], 1)
        emp = employees().get()
        self.assertEqual(emp.exit, 1)
        self.assertEqual(emp.staff_exit_date.isoformat(), "2026-02-01")

    def test_the_promotions_sheet_moves_the_role(self):
        self.post({"full_list": [person(4022, "Grace Kanja",
                                        **{"job title": "Teller"})]})
        resp = self.post({"promotions": [person(
            4022, "Grace Kanja", **{"job title": "Relationship Manager",
                                    "effective date": "2026-03-01",
                                    "grade": "6", "org unit": "BR-230"})]})

        self.assertEqual(resp.data["updated"], 1)
        emp = employees().get()
        self.assertEqual(emp.job_title, "Relationship Manager")
        self.assertEqual(emp.grade, "06")
        self.assertEqual(emp.org_unit, "BR-230")
        self.assertEqual(emp.promotion, 1)
        self.assertEqual(emp.promotion_date.isoformat(), "2026-03-01")

    def test_an_update_touches_only_the_ten_columns(self):
        """A promotions file must not overwrite an email or a date of birth."""
        self.post({"full_list": [person(
            4022, "Grace Kanja", **{"email": "grace@hfgroup.co.ke",
                                    "date of birth": "1990-05-04"})]})
        self.post({"promotions": [person(
            4022, "WRONG NAME", **{"email": "wrong@example.com",
                                   "date of birth": "1970-01-01",
                                   "job title": "Relationship Manager",
                                   "effective date": "2026-03-01"})]})

        emp = employees().get()
        self.assertEqual(emp.name, "Grace Kanja")
        self.assertEqual(emp.email, "grace@hfgroup.co.ke")
        self.assertEqual(emp.date_of_birth.date().isoformat(), "1990-05-04")
        self.assertEqual(emp.job_title, "Relationship Manager")

    def test_a_person_in_both_sheets_keeps_both_flags(self):
        self.post({"full_list": [person(4022, "Grace Kanja")]})
        resp = self.post({
            "exits": [person(4022, "Grace Kanja", **{"staff_exit_date": "2026-04-01"})],
            "promotions": [person(4022, "Grace Kanja", **{"effective date": "2026-03-01"})],
        })
        self.assertEqual(resp.data["updated"], 1)
        emp = employees().get()
        self.assertEqual((emp.exit, emp.promotion), (1, 1))
        self.assertEqual(emp.staff_exit_date.isoformat(), "2026-04-01")
        self.assertEqual(emp.promotion_date.isoformat(), "2026-03-01")

    def test_an_update_for_somebody_not_on_the_roster_is_counted_not_inserted(self):
        resp = self.post({"exits": [person(9999, "Ghost",
                                           **{"staff_exit_date": "2026-02-01"})]})
        self.assertEqual(resp.data["not_found"], 1)
        self.assertEqual(employees().count(), 0)

    def test_all_three_sheets_in_one_pass(self):
        self.post({"full_list": [person(4022, "Grace Kanja")]})
        resp = self.post({
            "full_list":  [person(5001, "John Mwangi")],
            "exits":      [person(4022, "Grace Kanja", **{"staff_exit_date": "2026-02-01"})],
            "promotions": [person(4022, "Grace Kanja", **{"effective date": "2026-01-05"})],
        })
        self.assertEqual(resp.data["inserted"], 1)
        self.assertEqual(resp.data["updated"], 1)
        self.assertEqual(sorted(resp.data["sheets"]["used"]),
                         ["exits", "full_list", "promotions"])

    # ── hfdi_employee_data ───────────────────────────────────────────────────
    def test_the_same_workbook_maintains_hfdi_employee_data(self):
        resp = self.post({"full_list": [
            person(7001, "  amina   OMAR ", department="HFDI", unit="Sales",
                   **{"job title": "Sales Agent", "date of employement": "2020-03-04"}),
            person(4022, "Grace Kanja", department="Retail Banking"),
        ]})
        self.assertEqual(resp.data["hfdi"]["inserted"], 1)

        row = HfdiEmployeeData.objects.get()
        self.assertEqual(row.staff_pf_number, 7001)
        self.assertEqual(row.staff_name, "Amina Omar")
        self.assertEqual(row.staff_role, "Sales Agent")
        self.assertEqual(row.input_user, "Strategy Employee Update")
        self.assertEqual(row.active, 1)

    def test_an_hfdi_exit_deactivates_rather_than_duplicates(self):
        self.post({"full_list": [person(7001, "Amina Omar", department="HFDI")]})
        resp = self.post({"exits": [person(7001, "Amina Omar", department="HFDI",
                                           **{"staff_exit_date": "2026-02-01"})]})
        self.assertEqual(HfdiEmployeeData.objects.count(), 1)
        self.assertEqual(resp.data["hfdi"]["exits_updated"], 1)

        row = HfdiEmployeeData.objects.get()
        self.assertEqual((row.active, row.staff_exit), (0, 1))
        self.assertEqual(row.exit_date.isoformat(), "2026-02-01")

    # ── file-level guards ────────────────────────────────────────────────────
    def test_a_single_csv_is_read_as_a_full_list(self):
        text = ",".join(HEADER) + "\n" + "4022,Grace Kanja" + "," * (len(HEADER) - 2) + "\n"
        buf = io.BytesIO(text.encode("utf-8"))
        buf.name = "staff.csv"
        resp = self.client.post(URL, {"file": buf}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["inserted"], 1)

    def test_a_workbook_with_no_recognised_sheet_is_rejected_whole(self):
        resp = self.post({"Sheet1": [person(4022, "Grace Kanja")]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("full_list", resp.data["error"])
        self.assertEqual(employees().count(), 0)

    def test_an_unrecognised_sheet_alongside_a_good_one_is_reported_not_loaded(self):
        resp = self.post({"full_list": [person(4022, "Grace Kanja")],
                          "notes": [person(5001, "John Mwangi")]})
        self.assertEqual(resp.data["inserted"], 1)
        self.assertEqual(resp.data["sheets"]["ignored"], ["notes"])

    def test_no_file_and_a_wrong_extension_are_rejected(self):
        self.assertEqual(self.client.post(URL, {}, format="multipart").status_code, 400)
        resp = self.post({"full_list": [person(4022, "Grace Kanja")]}, name="staff.txt")
        self.assertEqual(resp.status_code, 400)

    def test_only_staff_management_may_upload(self):
        User = get_user_model()
        outsider = User.objects.create_user("someone", password="x")
        client = APIClient()
        client.force_authenticate(outsider)
        resp = client.post(URL, {"file": workbook({"full_list": [person(4022, "G")]})},
                           format="multipart")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(employees().count(), 0)

    def test_anonymous_is_rejected(self):
        resp = APIClient().post(
            URL, {"file": workbook({"full_list": [person(4022, "G")]})},
            format="multipart")
        self.assertIn(resp.status_code, (401, 403))
