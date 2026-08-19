"""Tests for the employee-roster overlay: department standardisation, the
staff_id-keyed upsert (no duplicates), the CSV upload, and admin permissions.

The roster GET itself reads ``employee_table`` (managed=False, not created in the
test DB), so these tests target the pure mapping and the managed overlay table —
which is where all the new, writable logic and risk lives.
"""

import io

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .departments import standardize_department
from .models import EmployeeRosterOverlay
from .views import _canon_staff_id

User = get_user_model()

UPSERT = "/ceo/employees/overlay/"
UPLOAD = "/ceo/employees/overlay/upload/"


class DepartmentMappingTests(APITestCase):
    def test_safe_normalisations(self):
        self.assertEqual(standardize_department("Retail Banking"), "Retail Banking")
        # double spaces collapsed, "And" -> "&"
        self.assertEqual(standardize_department("Company  Secretary And  Legal"), "Company Secretary & Legal")

    def test_innovation_cluster_merges(self):
        for raw in ("Innovation", "Innovation & Digital Transformation", "Digital Financial Services"):
            self.assertEqual(standardize_department(raw), "Innovation & Digital Transformation")

    def test_entity_as_department_flagged(self):
        self.assertEqual(standardize_department("HFDI"), "HFDI — Unassigned")
        self.assertEqual(standardize_department("HF Group"), "HF Group — Unassigned")

    def test_case_insensitive_and_unknown_passthrough(self):
        self.assertEqual(standardize_department("retail banking"), "Retail Banking")
        self.assertEqual(standardize_department("Brand New Dept"), "Brand New Dept")

    def test_blank_is_unassigned(self):
        self.assertEqual(standardize_department(""), "Unassigned")
        self.assertEqual(standardize_department(None), "Unassigned")


class CanonStaffIdTests(APITestCase):
    def test_decimal_float_and_string_all_canonicalise(self):
        self.assertEqual(_canon_staff_id("4022.0"), "4022")
        self.assertEqual(_canon_staff_id(4022), "4022")
        self.assertEqual(_canon_staff_id(" 4022 "), "4022")
        self.assertEqual(_canon_staff_id(""), "")
        self.assertEqual(_canon_staff_id(None), "")


class OverlayUpsertTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user(username="plain", password="x")

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(self.plain)
        res = self.client.post(UPSERT, {"staff_id": "4022", "previous_role": "Teller"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_missing_staff_id_400(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(UPSERT, {"previous_role": "Teller"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_create_then_update_is_idempotent_no_duplicate(self):
        self.client.force_authenticate(self.admin)
        r1 = self.client.post(UPSERT, {"staff_id": "4022.0", "previous_role": "Teller"}, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertTrue(r1.data["created"])

        # Same person again (different staff_id formatting) → update, not a new row.
        r2 = self.client.post(UPSERT, {"staff_id": "4022", "current_role": "Cash Officer"}, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.data["created"])
        self.assertEqual(EmployeeRosterOverlay.objects.filter(staff_id="4022").count(), 1)

        obj = EmployeeRosterOverlay.objects.get(staff_id="4022")
        self.assertEqual(obj.previous_role, "Teller")      # kept from first write
        self.assertEqual(obj.current_role, "Cash Officer")  # set by second write

    def test_updated_by_is_recorded(self):
        self.client.force_authenticate(self.admin)
        self.client.post(UPSERT, {"staff_id": "5", "current_role": "X"}, format="json")
        self.assertEqual(EmployeeRosterOverlay.objects.get(staff_id="5").updated_by, "admin")


class OverlayUploadTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user(username="plain", password="x")

    def _csv(self, text):
        return io.BytesIO(text.encode("utf-8"))

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(self.plain)
        f = self._csv("staff_id,previous_role\n1,Teller\n")
        res = self.client.post(UPLOAD, {"file": f}, format="multipart")
        self.assertEqual(res.status_code, 403)

    def test_upload_creates_and_reupload_updates_no_duplicates(self):
        self.client.force_authenticate(self.admin)
        # Header aliases: "Staff ID", "Previous Role".
        f = self._csv("Staff ID,Previous Role\n4022.0,Teller\n3199,Analyst\n")
        res = self.client.post(UPLOAD, {"file": f}, format="multipart")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["created"], 2)
        self.assertEqual(res.data["updated"], 0)

        # Re-upload one with a change → updated in place, still 2 rows total.
        f2 = self._csv("staff_id,previous_role\n4022,Senior Teller\n")
        res2 = self.client.post(UPLOAD, {"file": f2}, format="multipart")
        self.assertEqual(res2.data["created"], 0)
        self.assertEqual(res2.data["updated"], 1)
        self.assertEqual(EmployeeRosterOverlay.objects.count(), 2)
        self.assertEqual(EmployeeRosterOverlay.objects.get(staff_id="4022").previous_role, "Senior Teller")

    def test_rows_without_staff_id_or_overlay_fields_are_skipped(self):
        self.client.force_authenticate(self.admin)
        # row 1: no staff_id; row 2: staff_id but no overlay field → both skipped.
        f = self._csv("staff_id,current_role\n,Manager\n999,\n")
        res = self.client.post(UPLOAD, {"file": f}, format="multipart")
        self.assertEqual(res.data["skipped"], 2)
        self.assertEqual(res.data["created"], 0)
        self.assertEqual(EmployeeRosterOverlay.objects.count(), 0)

    def test_missing_file_400(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(UPLOAD, {}, format="multipart")
        self.assertEqual(res.status_code, 400)
