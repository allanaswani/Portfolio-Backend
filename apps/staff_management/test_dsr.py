"""Tests for the DSR seller-code allocation logic."""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .dsr import next_sales_code
from .models import DSRSalesCode

User = get_user_model()


class DSRSalesCodeTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user(username="plain", password="x")

    def test_next_code_from_empty_is_dsr1(self):
        self.assertEqual(next_sales_code(), "DSR1")

    def test_next_code_is_max_plus_one(self):
        DSRSalesCode.objects.create(pf_number="1", sales_code="DSR302")
        DSRSalesCode.objects.create(pf_number="2", sales_code="DSR539")
        DSRSalesCode.objects.create(pf_number="3", sales_code="DSR100")
        self.assertEqual(next_sales_code(), "DSR540")

    def test_allocate_new_pf_creates_sequential_code(self):
        DSRSalesCode.objects.create(pf_number="9", sales_code="DSR539")
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/dsr-sales-codes/allocate/",
                               {"pf_number": "4026", "salesperson": "Test DSR"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(res.data["already_allocated"])
        self.assertEqual(res.data["record"]["sales_code"], "DSR540")
        self.assertEqual(res.data["record"]["pf_number"], "4026")

    def test_allocate_existing_pf_returns_existing_not_new(self):
        DSRSalesCode.objects.create(pf_number="4026", sales_code="DSR303", salesperson="Lucy")
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/dsr-sales-codes/allocate/",
                               {"pf_number": "4026"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["already_allocated"])
        self.assertEqual(res.data["record"]["sales_code"], "DSR303")
        self.assertEqual(DSRSalesCode.objects.filter(pf_number="4026").count(), 1)

    def test_non_admin_cannot_allocate(self):
        self.client.force_authenticate(self.plain)
        res = self.client.post("/staff_management/dsr-sales-codes/allocate/",
                               {"pf_number": "4026"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_lookup_existing_pf(self):
        DSRSalesCode.objects.create(pf_number="4026", sales_code="DSR303", salesperson="Lucy")
        self.client.force_authenticate(self.plain)
        res = self.client.get("/staff_management/dsr-sales-codes/lookup/?pf_number=4026")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["allocated"])
        self.assertEqual(res.data["record"]["sales_code"], "DSR303")

    def test_lookup_new_pf_previews_next_code(self):
        DSRSalesCode.objects.create(pf_number="9", sales_code="DSR539")
        self.client.force_authenticate(self.plain)
        res = self.client.get("/staff_management/dsr-sales-codes/lookup/?pf_number=7777")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["allocated"])
        self.assertEqual(res.data["next_sales_code"], "DSR540")

    def test_sales_code_unique_enforced(self):
        DSRSalesCode.objects.create(pf_number="1", sales_code="DSR303")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DSRSalesCode.objects.create(pf_number="2", sales_code="DSR303")
