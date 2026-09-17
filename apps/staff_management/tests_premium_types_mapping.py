"""premium_types_mapping — what kind of product each insurance product is.

The key fact these guard is that `product` is unique CASE-INSENSITIVELY. The
supplied rows arrive spelled both ways in one file ("ipp" lowercase beside
"WHOLE LIFE" and "IDD" in capitals), so a plain unique constraint would accept
"IPP" as a second mapping and leave the lookup with two answers.
"""
import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.staff_management.models import PremiumTypeMapping

LIST = "/staff_management/premium-types-mapping/"
UPLOAD = "/staff_management/premium-types-mapping/upload-csv/"
HEADER = "product,vic_check,life_policy_check,premium_type,policy_category"


class SeedTests(TestCase):
    """Migration 0020 runs when the test database is built."""

    def test_the_three_supplied_products_are_there(self):
        self.assertEqual(PremiumTypeMapping.objects.count(), 3)
        self.assertEqual(
            sorted(PremiumTypeMapping.objects.values_list("product", flat=True)),
            ["IDD", "WHOLE LIFE", "ipp"],
        )

    def test_the_values_are_as_supplied(self):
        row = PremiumTypeMapping.objects.get(product="ipp")
        self.assertEqual(row.vic_check, "vic")
        self.assertEqual(row.life_policy_check, "life")
        self.assertEqual(row.premium_type, "non-motor")
        self.assertEqual(row.policy_category, "Life")

    def test_product_case_is_preserved_as_given(self):
        """Matching is case-insensitive; storage is not. "ipp" was supplied
        lowercase and is shown to people that way."""
        self.assertTrue(PremiumTypeMapping.objects.filter(product="ipp").exists())
        self.assertFalse(PremiumTypeMapping.objects.filter(product="IPP").exists())


class UniquenessTests(TestCase):
    def test_the_same_product_in_another_case_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PremiumTypeMapping.objects.create(product="IPP")

    def test_a_different_product_is_fine(self):
        PremiumTypeMapping.objects.create(product="TERM LIFE")
        self.assertEqual(PremiumTypeMapping.objects.count(), 4)


class ApiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="bancauser", password="x", email="banca@hfcb.co.ke")
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_list(self):
        r = self.client.get(LIST)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["count"], 3)

    def test_add_a_product(self):
        r = self.client.post(LIST, {
            "product": "TERM LIFE", "vic_check": "vic",
            "life_policy_check": "life", "premium_type": "non-motor",
            "policy_category": "Life",
        })
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(PremiumTypeMapping.objects.filter(product="TERM LIFE").exists())

    def test_adding_a_duplicate_is_a_400_not_a_500(self):
        """The constraint alone would raise IntegrityError and the client would
        see a 500 with no idea which product clashed."""
        r = self.client.post(LIST, {"product": "IpP"})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("already mapped", str(r.json()))
        self.assertIn("ipp", str(r.json()))

    def test_an_empty_product_is_rejected(self):
        r = self.client.post(LIST, {"product": "   "})
        self.assertEqual(r.status_code, 400, r.content)

    def test_product_is_trimmed(self):
        r = self.client.post(LIST, {"product": "  TERM LIFE  "})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["product"], "TERM LIFE")

    def test_edit_keeps_its_own_product(self):
        """Renaming nothing must not trip the uniqueness check against itself."""
        row = PremiumTypeMapping.objects.get(product="IDD")
        r = self.client.patch(f"/staff_management/premium-types-mapping/{row.pk}/",
                              {"product": "IDD", "premium_type": "motor"})
        self.assertEqual(r.status_code, 200, r.content)
        row.refresh_from_db()
        self.assertEqual(row.premium_type, "motor")

    def test_delete(self):
        row = PremiumTypeMapping.objects.get(product="IDD")
        r = self.client.delete(f"/staff_management/premium-types-mapping/{row.pk}/")
        self.assertEqual(r.status_code, 204, r.content)
        self.assertEqual(PremiumTypeMapping.objects.count(), 2)

    def test_it_needs_a_login(self):
        self.assertEqual(APIClient().get(LIST).status_code, 401)

    # ── CSV ────────────────────────────────────────────────────────────────

    def _upload(self, body):
        return self.client.post(
            UPLOAD,
            {"file": SimpleUploadedFile("m.csv", body.encode(), content_type="text/csv")},
            format="multipart",
        )

    def test_upload_adds_new_products(self):
        r = self._upload(f"{HEADER}\nTERM LIFE,vic,life,non-motor,Life\n")
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertTrue(PremiumTypeMapping.objects.filter(product="TERM LIFE").exists())

    def test_upload_updates_an_existing_product_instead_of_failing(self):
        self._upload(f"{HEADER}\nIDD,vic,life,motor,General\n")
        row = PremiumTypeMapping.objects.get(product__iexact="IDD")
        self.assertEqual(row.premium_type, "motor")
        self.assertEqual(row.policy_category, "General")
        self.assertEqual(PremiumTypeMapping.objects.count(), 3)

    def test_upload_matches_the_existing_product_ignoring_case(self):
        self._upload(f"{HEADER}\nIpP,vic,life,motor,General\n")
        self.assertEqual(PremiumTypeMapping.objects.count(), 3)
        self.assertEqual(
            PremiumTypeMapping.objects.get(product__iexact="ipp").premium_type, "motor")

    def test_upload_does_not_empty_the_table_first(self):
        """The policy and trade-finance uploads are replace-by-year loads. This
        one is a reference list — wiping it on every upload would unclassify
        every product the file did not happen to mention."""
        self._upload(f"{HEADER}\nTERM LIFE,vic,life,non-motor,Life\n")
        self.assertEqual(PremiumTypeMapping.objects.count(), 4)
        for product in ("ipp", "WHOLE LIFE", "IDD"):
            self.assertTrue(
                PremiumTypeMapping.objects.filter(product__iexact=product).exists(),
                f"{product} was lost by an upload that did not mention it",
            )
