"""The expiry diary, customer autofill, excise duty and the tariff mapping.

Four things the trade desk asked for, and the rules that keep each of them
honest: the diary must not hide an item because its expiry was never recorded;
the customer lookup must not invent a segment; excise must follow the fee that
was actually charged, override and all; and mapping a product to a tariff must
not silently reprice anything that already exists.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import TradeProduct, TradeRegisterEntry, TradeTariff


def entry(**kw):
    base = dict(
        originating_branch="WESTLANDS", rm_name="JANE DOE", segment="COMMERCIAL",
        our_customer="ACME LTD", beneficiary="KPLC", currency="KES",
        amount_fcy=1_000_000, fx_rate=1, customer_id=12345,
        issue_date=date(2026, 1, 1), expiry_date=date(2026, 12, 31),
    )
    base.update(kw)
    if "product" not in base:
        base["product"] = TradeProduct.objects.get(code="GTE-BID")
    return TradeRegisterEntry.objects.create(**base)


class TariffMappingTests(APITestCase):
    """A tariff line prices every product mapped to it."""

    def setUp(self):
        self.tariff = TradeTariff.objects.get(code="TRF-GTE")
        self.product = TradeProduct.objects.get(code="GTE-BID")

    def test_the_seed_maps_products_to_their_tariff_line(self):
        self.assertEqual(self.product.tariff, self.tariff)
        self.assertEqual(
            TradeProduct.objects.get(code="ILC-SIGHT").tariff.code, "TRF-ILC"
        )
        self.assertEqual(
            TradeProduct.objects.get(code="ELC-SIGHT").tariff.code, "TRF-ELC"
        )

    def test_the_seed_prices_nothing(self):
        """Seeding a made-up rate would put wrong money on real transactions."""
        for tariff in TradeTariff.objects.all():
            self.assertEqual(tariff.commission_basis, TradeTariff.BASIS_NONE)
            self.assertEqual(tariff.commission_rate, Decimal("0"))
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31))
        self.assertFalse(quote["calculable"])

    def test_pricing_the_tariff_prices_every_product_on_it(self):
        self.tariff.commission_basis = TradeTariff.BASIS_FLAT
        self.tariff.commission_rate = "0.5"
        self.tariff.save()

        for code in ("GTE-BID", "GTE-PBG", "GTE-SBLC"):
            product = TradeProduct.objects.get(code=code)
            quote = product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30))
            self.assertTrue(quote["calculable"], code)
            self.assertEqual(str(quote["commission"]), "5000.00", code)
            self.assertEqual(quote["source"], "tariff")
            self.assertEqual(quote["tariff_code"], "TRF-GTE")

    def test_a_rate_set_on_the_product_beats_the_tariff(self):
        """A product rate is a deliberate exception to the general line.

        If the mapping overruled it, somebody would set a rate, watch nothing
        happen, and have no way to see why.
        """
        self.tariff.commission_basis = TradeTariff.BASIS_FLAT
        self.tariff.commission_rate = "0.5"
        self.tariff.save()
        self.product.commission_basis = TradeProduct.BASIS_FLAT
        self.product.commission_rate = "1"
        self.product.save()

        quote = TradeProduct.objects.get(pk=self.product.pk).quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30)
        )
        self.assertEqual(str(quote["commission"]), "10000.00")
        self.assertEqual(quote["source"], "product")
        # It still belongs to its tariff family, and says so.
        self.assertEqual(quote["tariff_code"], "TRF-GTE")

    def test_mapping_a_product_to_a_tariff_never_reprices_it(self):
        self.product.tariff = None
        self.product.commission_basis = TradeProduct.BASIS_FLAT
        self.product.commission_rate = "1"
        self.product.save()
        before = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30))

        self.tariff.commission_basis = TradeTariff.BASIS_FLAT
        self.tariff.commission_rate = "0.5"
        self.tariff.save()
        self.product.tariff = self.tariff
        self.product.save()
        after = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30))

        self.assertEqual(str(before["commission"]), str(after["commission"]))

    def test_a_product_with_no_tariff_still_uses_its_own_rate(self):
        """How every product behaved before tariffs existed."""
        self.product.tariff = None
        self.product.commission_basis = TradeProduct.BASIS_FLAT
        self.product.commission_rate = "1"
        self.product.save()
        quote = self.product.quote(1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30))
        self.assertEqual(str(quote["commission"]), "10000.00")
        self.assertEqual(quote["source"], "product")

    def test_the_explanation_names_the_tariff_it_was_charged_under(self):
        self.tariff.commission_basis = TradeTariff.BASIS_FLAT
        self.tariff.commission_rate = "0.5"
        self.tariff.save()
        quote = TradeProduct.objects.get(pk=self.product.pk).quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 6, 30)
        )
        self.assertIn("TRF-GTE", quote["explanation"])

    def test_the_entry_records_which_tariff_it_was_charged_under(self):
        row = entry()
        self.assertEqual(row.tariff_code, "TRF-GTE")


class ExciseDutyTests(APITestCase):
    """Duty is owed on the fee that was actually charged."""

    def setUp(self):
        self.tariff = TradeTariff.objects.get(code="TRF-GTE")
        self.tariff.commission_basis = TradeTariff.BASIS_FLAT
        self.tariff.commission_rate = "0.5"
        self.tariff.save()
        self.product = TradeProduct.objects.get(code="GTE-BID")

    def test_excise_is_a_percentage_of_the_commission(self):
        row = entry()
        self.assertEqual(str(row.commission), "5000.00")
        self.assertEqual(str(row.excise_duty), "1000.00")   # 20% of 5,000

    def test_excise_follows_an_overridden_commission(self):
        """The duty is on what was charged, not on what the tariff would say."""
        row = entry(commission=2000, commission_override=True)
        self.assertEqual(str(row.commission), "2000")
        self.assertEqual(str(row.excise_duty), "400.00")

    def test_changing_the_amount_moves_both_the_fee_and_the_duty(self):
        row = entry()
        row.amount_fcy = 2_000_000
        row.save()
        row.refresh_from_db()
        self.assertEqual(float(row.commission), 10000.0)
        self.assertEqual(float(row.excise_duty), 2000.0)

    def test_no_commission_means_no_duty(self):
        other = TradeProduct.objects.get(code="ELC-SIGHT")
        other.tariff = None
        other.save()
        row = entry(product=other, commission=0)
        self.assertEqual(str(row.excise_duty), "0.00")

    def test_the_rate_is_editable_not_compiled_in(self):
        """A Finance Act change must be an edit, not a deploy."""
        self.tariff.excise_rate = "16"
        self.tariff.save()
        row = entry()
        self.assertEqual(str(row.commission), "5000.00")
        self.assertEqual(str(row.excise_duty), "800.00")

    def test_a_product_off_the_tariff_book_still_charges_the_statutory_rate(self):
        product = TradeProduct.objects.get(code="GTE-PBG")
        product.tariff = None
        product.commission_basis = TradeProduct.BASIS_FLAT
        product.commission_rate = "0.5"
        product.save()
        row = entry(product=product)
        self.assertEqual(str(row.excise_duty), "1000.00")

    def test_the_api_exposes_duty_and_the_total_billed(self):
        user = User.objects.create_user(username="excise", password="x")
        self.client.force_authenticate(user)
        row = entry()
        res = self.client.get(f"/trade_register/entries/{row.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(float(res.data["excise_duty"]), 1000.0)
        self.assertEqual(float(res.data["total_charge"]), 6000.0)
        self.assertEqual(res.data["tariff_code"], "TRF-GTE")

    def test_a_client_cannot_post_a_duty_that_does_not_match_the_fee(self):
        user = User.objects.create_user(username="excise2", password="x")
        self.client.force_authenticate(user)
        row = entry()
        res = self.client.patch(f"/trade_register/entries/{row.id}/",
                                {"excise_duty": "1"}, format="json")
        self.assertEqual(res.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(str(row.excise_duty), "1000.00")


class DiaryStatusTests(APITestCase):
    """Which shelf of the diary a record sits on."""

    def setUp(self):
        self.today = timezone.localdate()

    def test_a_past_expiry_is_expired(self):
        row = entry(issue_date=self.today - timedelta(days=400),
                    expiry_date=self.today - timedelta(days=1))
        self.assertEqual(row.diary_status(), TradeRegisterEntry.DIARY_EXPIRED)
        self.assertEqual(row.days_to_expiry(), -1)

    def test_expiring_today_is_not_yet_expired(self):
        row = entry(expiry_date=self.today)
        self.assertEqual(row.diary_status(), TradeRegisterEntry.DIARY_DUE_7)

    def test_the_horizons_are_seven_thirty_and_ninety_days(self):
        cases = [
            (5, TradeRegisterEntry.DIARY_DUE_7),
            (20, TradeRegisterEntry.DIARY_DUE_30),
            (60, TradeRegisterEntry.DIARY_DUE_90),
            (200, TradeRegisterEntry.DIARY_LIVE),
        ]
        for days, expected in cases:
            row = entry(expiry_date=self.today + timedelta(days=days))
            self.assertEqual(row.diary_status(), expected, f"{days} days")

    def test_an_open_ended_instrument_never_expires(self):
        row = entry(is_open_ended=True)
        self.assertEqual(row.diary_status(), TradeRegisterEntry.DIARY_OPEN_ENDED)
        self.assertIsNone(row.days_to_expiry())

    def test_an_undated_item_is_surfaced_not_filed_as_live(self):
        """Neither open-ended nor dated is a gap in the register, not a live item."""
        row = entry(expiry_date=None)
        self.assertEqual(row.diary_status(), TradeRegisterEntry.DIARY_UNDATED)


class DiaryEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="diary", password="x")
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()

        self.expired = entry(our_customer="EXPIRED LTD",
                             issue_date=self.today - timedelta(days=400),
                             expiry_date=self.today - timedelta(days=10))
        self.soon = entry(our_customer="SOON LTD",
                          expiry_date=self.today + timedelta(days=3))
        self.later = entry(our_customer="LATER LTD",
                           expiry_date=self.today + timedelta(days=20))
        self.far = entry(our_customer="FAR LTD",
                         expiry_date=self.today + timedelta(days=300))
        self.open_ended = entry(our_customer="OPEN LTD", is_open_ended=True)

    def test_the_diary_groups_the_watchlist(self):
        res = self.client.get("/trade_register/diary/")
        self.assertEqual(res.status_code, 200)
        counts = res.data["counts"]
        self.assertEqual(counts["expired"], 1)
        self.assertEqual(counts["due_7"], 1)
        self.assertEqual(counts["due_30"], 1)
        self.assertEqual(counts["open_ended"], 1)

    def test_items_far_in_the_future_are_left_out_by_default(self):
        res = self.client.get("/trade_register/diary/")
        names = [r["our_customer"] for r in res.data["buckets"]["live"]]
        self.assertNotIn("FAR LTD", names)

    def test_they_can_be_asked_for(self):
        res = self.client.get("/trade_register/diary/?include_live=1")
        names = [r["our_customer"] for r in res.data["buckets"]["live"]]
        self.assertIn("FAR LTD", names)

    def test_the_window_is_adjustable(self):
        res = self.client.get("/trade_register/diary/?window=7")
        names = [r["our_customer"] for bucket in res.data["buckets"].values()
                 for r in bucket]
        self.assertIn("SOON LTD", names)
        self.assertNotIn("LATER LTD", names)

    def test_an_expired_item_carries_how_long_ago(self):
        res = self.client.get("/trade_register/diary/")
        row = res.data["buckets"]["expired"][0]
        self.assertEqual(row["days_to_expiry"], -10)
        self.assertEqual(row["diary_label"], "Expired")

    def test_the_diary_needs_a_signed_in_user(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/trade_register/diary/").status_code, (401, 403))


class CustomerLookupTests(APITestCase):
    """Typing the customer id fills in the name and segment."""

    # hf_customer is an unmanaged warehouse mirror, so the test database has no
    # such table. It cannot be built with schema_editor either: the model
    # declares numeric(65535, 65535), which is past what PostgreSQL accepts and
    # only survives because Django never issues DDL for an unmanaged model. So
    # the columns this lookup reads are created by hand, as
    # branch_portfolio/tests_arrears_fanout.py does for the same table.
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hf_customer (
                    cust_id numeric PRIMARY KEY,
                    latin_surname text,
                    segment text,
                    banking_segment text,
                    branch text
                )
            """)

    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS hf_customer")
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username="cust", password="x")
        self.client.force_authenticate(self.user)
        # Inserted by hand for the same reason the table is: an ORM create()
        # would write every column the model declares, and only the five the
        # lookup reads exist here.
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO hf_customer "
                "(cust_id, latin_surname, segment, banking_segment, branch) "
                "VALUES (%s, %s, %s, %s, %s)",
                [778899, "ACME HOLDINGS LTD", "SME", "BUSINESS BANKING", "WESTLANDS"],
            )

    def test_a_customer_id_returns_the_name_and_segment(self):
        res = self.client.get("/trade_register/customer-lookup/?customer_id=778899")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["found"])
        self.assertEqual(res.data["name"], "ACME HOLDINGS LTD")
        self.assertEqual(res.data["segment"], "BUSINESS BANKING")

    def test_both_segment_columns_are_returned_rather_than_collapsed(self):
        """They are different columns and they disagree; do not pick silently."""
        res = self.client.get("/trade_register/customer-lookup/?customer_id=778899")
        self.assertEqual(res.data["banking_segment"], "BUSINESS BANKING")
        self.assertEqual(res.data["portfolio_segment"], "SME")

    def test_an_unknown_id_is_a_404_not_a_blank_customer(self):
        res = self.client.get("/trade_register/customer-lookup/?customer_id=1")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.data["found"])

    def test_a_decimal_id_resolves_to_the_same_customer(self):
        res = self.client.get("/trade_register/customer-lookup/?customer_id=778899.0")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["found"])

    def test_nonsense_is_rejected_rather_than_searched_for(self):
        res = self.client.get("/trade_register/customer-lookup/?customer_id=abc")
        self.assertEqual(res.status_code, 400)

    def test_the_id_is_required(self):
        self.assertEqual(
            self.client.get("/trade_register/customer-lookup/").status_code, 400
        )


class TariffAdminTests(APITestCase):
    """Who may reprice a tariff line."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="tariffadmin", password="x", is_staff=True
        )
        self.plain = User.objects.create_user(username="tariffplain", password="x")
        self.tariff = TradeTariff.objects.get(code="TRF-GTE")

    def test_an_admin_can_reprice_a_line(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(f"/trade_register/tariffs/{self.tariff.id}/",
                                {"commission_basis": "flat", "commission_rate": "0.4"},
                                format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.tariff.refresh_from_db()
        self.assertEqual(float(self.tariff.commission_rate), 0.4)

    def test_an_ordinary_user_may_read_but_not_reprice(self):
        self.client.force_authenticate(self.plain)
        self.assertEqual(self.client.get("/trade_register/tariffs/").status_code, 200)
        res = self.client.patch(f"/trade_register/tariffs/{self.tariff.id}/",
                                {"commission_rate": "9"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_the_line_says_which_products_it_reaches(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get("/trade_register/tariffs/")
        row = next(r for r in res.data if r["code"] == "TRF-GTE")
        self.assertIn("GTE-BID", row["products"])

    def test_a_reprice_is_kept_in_the_audit_trail(self):
        self.client.force_authenticate(self.admin)
        self.client.patch(f"/trade_register/tariffs/{self.tariff.id}/",
                          {"excise_rate": "16"}, format="json")
        history = list(TradeTariff.history.filter(id=self.tariff.id))
        self.assertTrue(history)
        self.assertEqual(float(history[0].excise_rate), 16.0)
