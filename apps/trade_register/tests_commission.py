"""Commission pricing, product lookup and the currency list.

Commission used to be typed on every transaction with nothing to check it
against, currencies were a hard-coded list of ten in the frontend bundle, and a
product code told the form nothing. These pin the replacements — and, above all,
that a figure the desk typed deliberately is never quietly overwritten.
"""

from datetime import date

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import TradeCurrency, TradeProduct, TradeRegisterEntry


class CommissionPricingTests(APITestCase):
    """What a product charges, and when it declines to guess."""

    def setUp(self):
        self.product = TradeProduct.objects.get(code="14116")

    def _priced(self, basis, rate, minimum=0):
        self.product.commission_basis = basis
        self.product.commission_rate = rate
        self.product.minimum_commission = minimum
        self.product.save()
        return self.product

    def test_a_product_with_no_pricing_calculates_nothing(self):
        """A product the book does not reach is typed, not guessed.

        Every seeded product is now priced through its category, so this needs
        a product outside the book — which is exactly what a newly added one is
        until somebody prices it.
        """
        unpriced = TradeProduct.objects.create(
            code="TR-TEST-UNPRICED", name="UNPRICED TEST PRODUCT",
            ref_family="guarantee", category=None,
        )
        quote = unpriced.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31))
        self.assertFalse(quote["calculable"])
        self.assertIsNone(quote["commission"])

    def test_a_flat_rate_is_a_percentage_of_the_amount(self):
        self._priced(TradeProduct.BASIS_FLAT, "0.5")
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30))
        self.assertTrue(quote["calculable"])
        self.assertEqual(str(quote["commission"]), "5000.00")

    def test_the_amount_is_converted_at_the_fx_rate(self):
        """Commission has always been reported in local currency."""
        self._priced(TradeProduct.BASIS_FLAT, "1")
        quote = self.product.quote(1_000, 130, date(2026, 1, 1), date(2026, 6, 30))
        self.assertEqual(str(quote["commission"]), "1300.00")

    def test_a_part_quarter_is_charged_as_a_whole_one(self):
        self._priced(TradeProduct.BASIS_PER_QUARTER, "0.5")
        # 100 days: a quarter and a bit, so two.
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 4, 11))
        self.assertEqual(str(quote["periods"]), "2")
        self.assertEqual(str(quote["commission"]), "10000.00")

    def test_exactly_one_quarter_is_one_quarter(self):
        self._priced(TradeProduct.BASIS_PER_QUARTER, "0.5")
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 4, 1))
        self.assertEqual(str(quote["periods"]), "1")

    def test_a_per_annum_rate_is_pro_rated_over_the_tenor(self):
        self._priced(TradeProduct.BASIS_PER_ANNUM, "2")
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31))
        # 364 days of a 365-day year, at 2% of a million.
        self.assertAlmostEqual(float(quote["commission"]), 19945.21, places=1)

    def test_the_minimum_is_a_floor_not_a_replacement(self):
        self._priced(TradeProduct.BASIS_FLAT, "0.5", minimum=5000)
        small = self.product.quote(100_000, 1, date(2026, 1, 1), date(2026, 6, 30))
        self.assertEqual(str(small["commission"]), "5000.00")
        self.assertTrue(small["minimum_applied"])

        large = self.product.quote(10_000_000, 1, date(2026, 1, 1), date(2026, 6, 30))
        self.assertEqual(str(large["commission"]), "50000.00")
        self.assertFalse(large["minimum_applied"])

    def test_an_open_ended_instrument_has_no_tenor_to_price_per_quarter(self):
        """Say so rather than invent a tenor."""
        self._priced(TradeProduct.BASIS_PER_QUARTER, "0.5")
        quote = self.product.quote(
            1_000_000, 1, date(2026, 1, 1), None, is_open_ended=True
        )
        self.assertFalse(quote["calculable"])
        self.assertIn("expiry", quote["explanation"].lower())

    def test_a_missing_expiry_does_not_silently_price_one_quarter(self):
        self._priced(TradeProduct.BASIS_PER_QUARTER, "0.5")
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), None)
        self.assertFalse(quote["calculable"])

    def test_an_expiry_before_the_issue_date_is_not_a_negative_tenor(self):
        self._priced(TradeProduct.BASIS_PER_QUARTER, "0.5")
        quote = self.product.quote(1_000_000, 1, date(2026, 6, 1), date(2026, 1, 1))
        self.assertFalse(quote["calculable"])


class CommissionOnEntryTests(APITestCase):
    """The calculation applied to a real transaction, and the override."""

    def setUp(self):
        self.product = TradeProduct.objects.get(code="14116")
        self.product.commission_basis = TradeProduct.BASIS_FLAT
        self.product.commission_rate = "0.5"
        self.product.save()

    def _entry(self, **kw):
        base = dict(
            originating_branch="WESTLANDS", rm_name="JANE DOE", segment="COMMERCIAL",
            our_customer="ACME LTD", beneficiary="KPLC", currency="KES",
            amount_fcy=1_000_000, fx_rate=1, customer_id=12345,
            issue_date=date(2026, 8, 13), expiry_date=date(2026, 12, 31),
            product=self.product,
        )
        base.update(kw)
        return TradeRegisterEntry.objects.create(**base)

    def test_commission_is_worked_out_on_save(self):
        entry = self._entry()
        self.assertEqual(str(entry.commission), "5000.00")

    def test_a_typed_commission_survives_a_later_edit(self):
        """A negotiated figure must not be quietly overwritten."""
        entry = self._entry(commission=1234, commission_override=True)
        self.assertEqual(str(entry.commission), "1234")
        entry.beneficiary = "KENGEN"
        entry.save()
        entry.refresh_from_db()
        self.assertEqual(float(entry.commission), 1234.0)

    def test_clearing_the_override_puts_the_product_price_back(self):
        entry = self._entry(commission=1234, commission_override=True)
        entry.commission_override = False
        entry.save()
        entry.refresh_from_db()
        self.assertEqual(float(entry.commission), 5000.0)

    def test_changing_the_amount_reprices_the_transaction(self):
        entry = self._entry()
        entry.amount_fcy = 2_000_000
        entry.save()
        entry.refresh_from_db()
        self.assertEqual(float(entry.commission), 10000.0)

    def test_a_product_without_pricing_leaves_the_typed_figure_alone(self):
        unpriced = TradeProduct.objects.create(
            code="TR-TEST-UNPRICED-2", name="UNPRICED TEST PRODUCT 2",
            ref_family="guarantee", category=None,
        )
        entry = self._entry(product=unpriced, commission=777)
        self.assertEqual(float(entry.commission), 777.0)

    def test_the_worked_commission_reaches_trade_finance(self):
        entry = self._entry()
        self.assertIsNotNone(entry.tf)
        self.assertEqual(float(entry.tf.commission_lcy), 5000.0)

    def test_the_api_shows_the_working_beside_the_figure(self):
        user = User.objects.create_user(username="deskquote", password="x")
        self.client.force_authenticate(user)
        entry = self._entry()
        res = self.client.get(f"/trade_register/entries/{entry.id}/")
        self.assertEqual(res.status_code, 200)
        quote = res.data["commission_quote"]
        self.assertTrue(quote["calculable"])
        self.assertEqual(quote["commission"], "5000.00")
        self.assertIn("0.5", quote["explanation"])


class CommissionEditViaApiTests(APITestCase):
    """Correcting a transaction the desk got wrong."""

    def setUp(self):
        self.user = User.objects.create_user(username="deskedit", password="x")
        self.client.force_authenticate(self.user)
        self.product = TradeProduct.objects.get(code="14116")
        self.product.commission_basis = TradeProduct.BASIS_FLAT
        self.product.commission_rate = "0.5"
        self.product.save()
        self.entry = TradeRegisterEntry.objects.create(
            originating_branch="WESTLANDS", rm_name="JANE DOE", segment="COMMERCIAL",
            our_customer="ACME LTD", beneficiary="KPLC", currency="KES",
            amount_fcy=1_000_000, fx_rate=1, customer_id=12345,
            issue_date=date(2026, 8, 13), expiry_date=date(2026, 12, 31),
            product=self.product,
        )

    def test_wrong_data_can_be_corrected(self):
        res = self.client.patch(
            f"/trade_register/entries/{self.entry.id}/",
            {"our_customer": "ACME HOLDINGS LTD"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.our_customer, "ACME HOLDINGS LTD")

    def test_a_rate_the_desk_disagrees_with_can_be_overridden_through_the_api(self):
        res = self.client.patch(
            f"/trade_register/entries/{self.entry.id}/",
            {"commission": "3200", "commission_override": True}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.entry.refresh_from_db()
        self.assertEqual(float(self.entry.commission), 3200.0)
        self.assertTrue(self.entry.commission_override)

    def test_the_correction_is_kept_in_the_audit_trail(self):
        self.client.patch(
            f"/trade_register/entries/{self.entry.id}/",
            {"beneficiary": "KENGEN"}, format="json",
        )
        history = list(
            TradeRegisterEntry.history.filter(id=self.entry.id).order_by("history_date")
        )
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[-1].beneficiary, "KENGEN")


class ProductLookupTests(APITestCase):
    """Typing a product code fills the rest in."""

    def setUp(self):
        self.user = User.objects.create_user(username="desk", password="x")
        self.client.force_authenticate(self.user)
        self.product = TradeProduct.objects.get(code="14116")
        self.product.commission_basis = TradeProduct.BASIS_FLAT
        self.product.commission_rate = "0.5"
        self.product.save()

    def test_a_code_resolves_to_the_product_name(self):
        res = self.client.get("/trade_register/product-lookup/?code=14116")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["found"])
        self.assertEqual(res.data["product"]["name"], self.product.name)

    def test_the_code_is_matched_regardless_of_case(self):
        # A numeric code cannot show this; use one with letters in it.
        res = self.client.get("/trade_register/product-lookup/?code=tr-lc-sblc")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["found"])

    def test_an_unknown_code_is_a_404_not_a_silent_blank(self):
        res = self.client.get("/trade_register/product-lookup/?code=NOPE")
        self.assertEqual(res.status_code, 404)

    def test_the_lookup_also_quotes_the_commission(self):
        res = self.client.get(
            "/trade_register/product-lookup/"
            "?code=14116&amount_fcy=1000000&fx_rate=1"
            "&issue_date=2026-01-01&expiry_date=2026-06-30"
        )
        self.assertEqual(res.data["quote"]["commission"], "5000.00")
        self.assertTrue(res.data["quote"]["calculable"])

    def test_the_quote_explains_itself(self):
        res = self.client.get(
            "/trade_register/product-lookup/?code=14116&amount_fcy=1000000&fx_rate=1"
        )
        self.assertIn("0.5", res.data["quote"]["explanation"])

    def test_asking_for_nothing_is_a_400(self):
        self.assertEqual(
            self.client.get("/trade_register/product-lookup/").status_code, 400
        )


class CurrencyListTests(APITestCase):
    """Currencies come from a table, so a missing one is an edit not a deploy."""

    def setUp(self):
        self.user = User.objects.create_user(username="ccy", password="x")
        self.client.force_authenticate(self.user)

    def test_the_seeded_list_is_far_wider_than_the_old_hard_coded_ten(self):
        res = self.client.get("/trade_register/currencies/")
        self.assertEqual(res.status_code, 200)
        codes = [row["code"] for row in res.data]
        self.assertGreater(len(codes), 30)
        for expected in ("KES", "USD", "EUR", "GBP"):
            self.assertIn(expected, codes)

    def test_the_east_african_currencies_are_there(self):
        res = self.client.get("/trade_register/currencies/")
        codes = [row["code"] for row in res.data]
        for expected in ("UGX", "TZS", "RWF", "ETB", "SSP"):
            self.assertIn(expected, codes)

    def test_the_gulf_trade_currencies_are_there(self):
        res = self.client.get("/trade_register/currencies/")
        codes = [row["code"] for row in res.data]
        for expected in ("AED", "SAR", "QAR", "KWD"):
            self.assertIn(expected, codes)

    def test_the_local_currency_sorts_first(self):
        res = self.client.get("/trade_register/currencies/")
        self.assertEqual(res.data[0]["code"], "KES")

    def test_an_added_currency_appears_without_a_code_change(self):
        TradeCurrency.objects.create(code="ZWL", name="Zimbabwean Dollar", sort_order=70)
        res = self.client.get("/trade_register/currencies/")
        self.assertIn("ZWL", [row["code"] for row in res.data])

    def test_a_deactivated_currency_is_withdrawn(self):
        TradeCurrency.objects.filter(code="JPY").update(is_active=False)
        res = self.client.get("/trade_register/currencies/")
        self.assertNotIn("JPY", [row["code"] for row in res.data])


class ProductPricingAdminTests(APITestCase):
    """Who may change what the desk charges."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="ratesadmin", password="x", is_staff=True
        )
        self.plain = User.objects.create_user(username="rateplain", password="x")
        self.product = TradeProduct.objects.get(code="14116")

    def test_an_admin_can_change_a_rate(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(
            f"/trade_register/products/{self.product.id}/",
            {"commission_basis": "flat", "commission_rate": "0.75"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.product.refresh_from_db()
        self.assertEqual(float(self.product.commission_rate), 0.75)

    def test_an_ordinary_user_may_read_but_not_reprice(self):
        self.client.force_authenticate(self.plain)
        self.assertEqual(
            self.client.get(f"/trade_register/products/{self.product.id}/").status_code,
            200,
        )
        res = self.client.patch(
            f"/trade_register/products/{self.product.id}/",
            {"commission_rate": "9"}, format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_a_rate_change_is_kept_in_the_audit_trail(self):
        self.client.force_authenticate(self.admin)
        self.client.patch(
            f"/trade_register/products/{self.product.id}/",
            {"commission_rate": "0.9"}, format="json",
        )
        history = list(TradeProduct.history.filter(id=self.product.id))
        self.assertTrue(history)
        self.assertEqual(float(history[0].commission_rate), 0.9)
