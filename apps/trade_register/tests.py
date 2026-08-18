from datetime import date

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.staff_management.models import TradeFinanceData

from .models import TradeProduct, TradeRegisterEntry
from . import references as refs


class ReferenceGeneratorTests(APITestCase):
    def setUp(self):
        # Products are seeded by migration 0002 — fetch them.
        self.bid = TradeProduct.objects.get(code="GTE-BID")
        self.elc = TradeProduct.objects.get(code="ELC-SIGHT")
        self.ilc = TradeProduct.objects.get(code="ILC-SIGHT")

    def _entry(self, product, **kw):
        base = dict(
            originating_branch="WESTLANDS", rm_name="JANE DOE", segment="COMMERCIAL",
            our_customer="ACME LTD", beneficiary="KPLC", currency="KES",
            amount_fcy=1000, customer_id=12345, issue_date=date(2026, 8, 13),
        )
        base.update(kw)
        return TradeRegisterEntry.objects.create(product=product, **base)

    def test_guarantee_ref_is_dated_and_resets_per_day(self):
        e1 = self._entry(self.bid)
        e2 = self._entry(self.bid)
        self.assertEqual(e1.guarantee_ref, "HFCB/GTE/260813/01")
        self.assertEqual(e2.guarantee_ref, "HFCB/GTE/260813/02")
        # A different day restarts the daily counter.
        e3 = self._entry(self.bid, issue_date=date(2026, 8, 14))
        self.assertEqual(e3.guarantee_ref, "HFCB/GTE/260814/01")

    def test_export_lc_uses_elc_prefix(self):
        e = self._entry(self.elc)
        self.assertEqual(e.guarantee_ref, "HFCB/ELC/260813/01")

    def test_import_lc_is_sequential_hf_number(self):
        e1 = self._entry(self.ilc)
        e2 = self._entry(self.ilc)
        self.assertTrue(e1.guarantee_ref.startswith("HF"))
        self.assertEqual(int(e2.guarantee_ref[2:]), int(e1.guarantee_ref[2:]) + 1)

    def test_generator_avoids_collision_with_legacy_tf_rows(self):
        # A historical TF row already used sequence 01 that day.
        TradeFinanceData.objects.create(
            originating_branch="X", rm_name="Y", guarantee_ref="HFCB/GTE/260813/01",
            product_type="BID BOND", customer_id=1, segment="C", our_customer="Z",
            beneficiary="B", currency="KES", amount_fcy=0, issue_date="2026-08-13",
            expiry_date="", commission_lcy=0, month="AUGUST", fx_rate=0, year="2026",
        )
        e = self._entry(self.bid)
        self.assertEqual(e.guarantee_ref, "HFCB/GTE/260813/02")

    def test_amendment_reuses_parent_reference(self):
        e = self._entry(self.bid, amendment_type="EXT", parent_ref="HFCB/GTE/260630/01")
        self.assertEqual(e.guarantee_ref, "HFCB/GTE/260630/01 - EXT")

    def test_manual_reference_is_kept(self):
        e = self._entry(self.ilc, guarantee_ref="HF99999")
        self.assertEqual(e.guarantee_ref, "HF99999")


class SyncTests(APITestCase):
    def setUp(self):
        self.bid = TradeProduct.objects.get(code="GTE-BID")

    def test_creating_entry_mirrors_to_trade_finance(self):
        e = TradeRegisterEntry.objects.create(
            product=self.bid, originating_branch="WESTLANDS", rm_name="JANE",
            segment="COMMERCIAL", our_customer="ACME", beneficiary="KPLC",
            currency="KES", amount_fcy=5000, customer_id=777,
            issue_date=date(2026, 8, 13),
        )
        self.assertIsNotNone(e.tf_id)
        tf = TradeFinanceData.objects.get(pk=e.tf_id)
        self.assertEqual(tf.guarantee_ref, e.guarantee_ref)
        self.assertEqual(tf.product_type, "BID BOND")
        self.assertEqual(str(tf.customer_id), "777")

    def test_editing_trade_finance_reflects_back_to_entry(self):
        e = TradeRegisterEntry.objects.create(
            product=self.bid, originating_branch="WESTLANDS", rm_name="JANE",
            segment="COMMERCIAL", our_customer="ACME", beneficiary="KPLC",
            currency="KES", amount_fcy=5000, customer_id=777,
            issue_date=date(2026, 8, 13),
        )
        tf = TradeFinanceData.objects.get(pk=e.tf_id)
        tf.our_customer = "ACME RENAMED"
        tf.save()
        e.refresh_from_db()
        self.assertEqual(e.our_customer, "ACME RENAMED")

    def _entry_with_beneficiary(self):
        return TradeRegisterEntry.objects.create(
            product=self.bid, originating_branch="WESTLANDS", rm_name="JANE",
            segment="COMMERCIAL", our_customer="ACME", beneficiary="KPLC",
            currency="KES", amount_fcy=5000, customer_id=777,
            issue_date=date(2026, 8, 13),
        )

    def test_blank_register_field_does_not_wipe_trade_finance(self):
        """Esther clears a field on the register → TF keeps the info we had."""
        e = self._entry_with_beneficiary()
        self.assertEqual(TradeFinanceData.objects.get(pk=e.tf_id).beneficiary, "KPLC")
        e.beneficiary = ""
        e.save()
        self.assertEqual(TradeFinanceData.objects.get(pk=e.tf_id).beneficiary, "KPLC")

    def test_blank_trade_finance_field_does_not_wipe_register(self):
        e = self._entry_with_beneficiary()
        tf = TradeFinanceData.objects.get(pk=e.tf_id)
        tf.beneficiary = ""
        tf.save()
        e.refresh_from_db()
        self.assertEqual(e.beneficiary, "KPLC")

    def test_new_record_populates_all_trade_finance_fields(self):
        """A brand-new register record creates the TF row with its fields."""
        e = self._entry_with_beneficiary()
        tf = TradeFinanceData.objects.get(pk=e.tf_id)
        self.assertEqual(tf.beneficiary, "KPLC")
        self.assertEqual(tf.originating_branch, "WESTLANDS")
        self.assertEqual(str(tf.amount_fcy), "5000.00")
        self.assertEqual(tf.issue_date, "2026-08-13")


class ApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", "u@x.com", "pw")
        self.client.force_authenticate(self.user)
        self.bid = TradeProduct.objects.get(code="GTE-BID")

    def test_create_entry_via_api_generates_reference(self):
        resp = self.client.post("/trade_register/entries/", {
            "originating_branch": "WESTLANDS", "rm_name": "JANE", "segment": "COMMERCIAL",
            "our_customer": "ACME", "beneficiary": "KPLC", "currency": "KES",
            "amount_fcy": "5000", "customer_id": 777, "product": self.bid.id,
            "issue_date": "2026-08-13",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["guarantee_ref"], "HFCB/GTE/260813/01")
        self.assertEqual(resp.data["product_type"], "BID BOND")

    def test_products_dropdown(self):
        resp = self.client.get("/trade_register/products/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(p["code"] == "GTE-BID" for p in resp.data))

    def test_reference_preview(self):
        resp = self.client.get(
            "/trade_register/reference-preview/",
            {"product": self.bid.id, "issue_date": "2026-08-13"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["reference"], "HFCB/GTE/260813/01")
