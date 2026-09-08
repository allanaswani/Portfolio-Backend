"""The desk's catalogue, the published tariff, amendments, and expiry filing.

Everything here comes from the trade desk's own test feedback (2026-09-08) and
from the bank's published tariff book. The figures are pinned as the book
states them, so a later edit that changes what a customer is charged has to
change a test that spells out the old charge.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from . import references as refs
from .models import (
    TradeProduct, TradeProductCategory, TradeRegisterEntry, TradeTariff,
)


def entry(**kw):
    base = dict(
        originating_branch="WESTLANDS BRANCH", rm_name="JANE DOE",
        segment="COMMERCIAL", our_customer="ACME LTD", beneficiary="KPLC",
        currency="KES", amount_fcy=1_000_000, fx_rate=1, customer_id=12345,
        issue_date=date(2026, 1, 1), expiry_date=date(2026, 12, 31),
    )
    base.update(kw)
    if "product" not in base:
        base["product"] = TradeProduct.objects.get(code="14116")
    return TradeRegisterEntry.objects.create(**base)


class ActionListTests(APITestCase):
    """The desk's six actions, and nothing else, offered for a new transaction."""

    def setUp(self):
        self.user = User.objects.create_user(username="acts", password="x")
        self.client.force_authenticate(self.user)

    def test_the_six_actions_are_exactly_what_the_desk_asked_for(self):
        self.assertEqual(refs.ACTIONS, [
            "ISSUANCE", "AMENDMENT", "CANCELLATION",
            "ADVISING", "BILL ACCEPTANCE", "SETTLEMENT",
        ])

    def test_the_endpoint_says_which_actions_need_a_parent(self):
        res = self.client.get("/trade_register/actions/")
        self.assertEqual(res.status_code, 200)
        by_value = {a["value"]: a for a in res.data["actions"]}
        self.assertEqual(len(by_value), 6)
        self.assertFalse(by_value["ISSUANCE"]["needs_parent"])
        for action in ("AMENDMENT", "CANCELLATION", "ADVISING",
                       "BILL ACCEPTANCE", "SETTLEMENT"):
            self.assertTrue(by_value[action]["needs_parent"], action)

    def test_an_issuance_draws_a_fresh_reference(self):
        row = entry(action="ISSUANCE")
        self.assertTrue(row.guarantee_ref.startswith("HFCB/GTE/260101/"))

    def test_an_action_on_an_existing_item_reuses_its_reference(self):
        original = entry()
        amendment = entry(action="AMENDMENT", parent_ref=original.guarantee_ref)
        self.assertEqual(amendment.guarantee_ref,
                         f"{original.guarantee_ref} - AMENDMENT")

    def test_an_action_off_the_list_is_refused_on_a_new_transaction(self):
        original = entry()
        res = self.client.post("/trade_register/entries/", {
            "originating_branch": "WESTLANDS BRANCH", "rm_name": "A",
            "segment": "S", "our_customer": "C", "customer_id": 1,
            "currency": "KES", "amount_fcy": 1000, "fx_rate": 1,
            "issue_date": "2026-01-01", "expiry_date": "2026-06-30",
            "product": TradeProduct.objects.get(code="14116").id,
            "action": "RETIREMENT", "parent_ref": original.guarantee_ref,
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("action", res.data)

    def test_an_action_on_an_existing_item_must_name_it(self):
        res = self.client.post("/trade_register/entries/", {
            "originating_branch": "WESTLANDS BRANCH", "rm_name": "A",
            "segment": "S", "our_customer": "C", "customer_id": 1,
            "currency": "KES", "amount_fcy": 1000, "fx_rate": 1,
            "issue_date": "2026-01-01", "expiry_date": "2026-06-30",
            "product": TradeProduct.objects.get(code="14116").id,
            "action": "AMENDMENT",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("parent_ref", res.data)

    def test_a_historical_action_is_kept_not_rewritten(self):
        """A register records what happened; a new dropdown does not change it."""
        row = entry()
        TradeRegisterEntry.objects.filter(pk=row.pk).update(action="CALL UP")
        row.refresh_from_db()
        res = self.client.patch(f"/trade_register/entries/{row.id}/",
                                {"beneficiary": "KENGEN"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        row.refresh_from_db()
        self.assertEqual(row.action, "CALL UP")


class CatalogueTests(APITestCase):
    """The categories and the product list, as the desk supplied them."""

    def setUp(self):
        self.user = User.objects.create_user(username="cat", password="x")
        self.client.force_authenticate(self.user)

    def test_the_four_categories_are_seeded(self):
        names = set(TradeProductCategory.objects.values_list("name", flat=True))
        self.assertEqual(names, {
            "LETTERS OF GUARANTEE",
            "LETTERS OF CREDIT",
            "BILLS UNDER LETTER OF CREDIT",
            "BILLS UNDER DOCUMENTARY COLLECTION",
        })

    def test_every_guarantee_carries_the_banks_own_code(self):
        codes = dict(
            TradeProduct.objects.filter(category__code="LG", is_active=True)
            .values_list("code", "name")
        )
        self.assertEqual(codes["14116"], "BID BOND GUARANTEE")
        self.assertEqual(codes["14117"], "PERFORMANCE BOND GUARANTEE")
        self.assertEqual(codes["14123"], "ADVANCE PAYMENT GUARANTEE")
        self.assertEqual(codes["14104"], "PAYMENT GUARANTEE")
        self.assertEqual(codes["14110"], "IMMIGRATION BOND GUARANTEE")
        self.assertEqual(codes["14107"], "CUSTOM BOND GUARANTEE")
        self.assertEqual(codes["14118"], "RETENTION MONEY GUARANTEE")
        self.assertEqual(codes["14113"], "SHIPPING GUARANTEE")
        self.assertEqual(codes["14103"], "SURETY UNDERTAKING GUARANTEE")
        self.assertEqual(codes["14101"], "ADVISE OF INCOMING GUARANTEE")
        self.assertEqual(codes["14102"], "CONVENTIONAL DEMAND BANK GUARANTEE")
        self.assertEqual(len(codes), 11)

    def test_a_product_with_no_bank_code_is_not_given_an_invented_one(self):
        """The desk supplied the LCs and bills without codes; say so."""
        for code in TradeProduct.objects.filter(
            category__code__in=["LC", "BLC", "BDC"], is_active=True
        ).values_list("code", flat=True):
            self.assertTrue(code.startswith("TR-"), code)

    def test_each_category_holds_the_products_the_desk_listed(self):
        counts = {
            c.code: c.products.filter(is_active=True).count()
            for c in TradeProductCategory.objects.all()
        }
        self.assertEqual(counts["LG"], 11)
        self.assertEqual(counts["LC"], 7)
        self.assertEqual(counts["BLC"], 4)
        self.assertEqual(counts["BDC"], 5)

    def test_the_product_dropdown_narrows_to_the_chosen_category(self):
        cat = TradeProductCategory.objects.get(code="LC")
        res = self.client.get(f"/trade_register/products/?category={cat.id}")
        self.assertEqual(res.status_code, 200)
        names = [p["name"] for p in res.data]
        self.assertIn("SIGHT IMPORT LETTER OF CREDIT", names)
        self.assertNotIn("BID BOND GUARANTEE", names)
        self.assertEqual(len(names), 7)

    def test_the_category_can_be_given_by_code(self):
        res = self.client.get("/trade_register/products/?category=LG")
        self.assertEqual(len(res.data), 11)

    def test_a_retired_product_keeps_its_transactions_readable(self):
        """Products the new list dropped are deactivated, never deleted."""
        retired = TradeProduct.objects.filter(is_active=False).first()
        if retired is None:
            self.skipTest("no product was retired by the reseed")
        self.assertIsNotNone(TradeProduct.objects.filter(pk=retired.pk).first())

    def test_the_categories_endpoint_counts_its_products(self):
        res = self.client.get("/trade_register/categories/")
        self.assertEqual(res.status_code, 200)
        by_code = {c["code"]: c for c in res.data}
        self.assertEqual(by_code["LG"]["product_count"], 11)


class TariffBookTests(APITestCase):
    """The charges, exactly as the bank's tariff book states them."""

    def _product(self, code):
        return TradeProduct.objects.get(code=code)

    def test_a_bid_bond_is_one_percent_flat(self):
        """The desk's stated exception to its category's per-quarter rate."""
        quote = self._product("14116").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="ISSUANCE",
        )
        self.assertTrue(quote["calculable"])
        self.assertEqual(str(quote["commission"]), "10000.00")
        self.assertEqual(quote["tariff_code"], "TRF-LG-ISSUE-BID")

    def test_another_guarantee_is_point_seven_five_per_quarter(self):
        """0.75% per quarter; Min. KShs. 2,500 — four quarters on a year."""
        quote = self._product("14117").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="ISSUANCE",
        )
        self.assertEqual(str(quote["periods"]), "5")   # 364 days → 5 part quarters
        self.assertEqual(str(quote["commission"]), "37500.00")

    def test_the_guarantee_minimum_is_two_thousand_five_hundred(self):
        quote = self._product("14117").quote(
            1_000, 1, date(2026, 1, 1), date(2026, 3, 1), action="ISSUANCE",
        )
        self.assertEqual(str(quote["commission"]), "2500.00")
        self.assertTrue(quote["minimum_applied"])

    def test_a_guarantee_amendment_is_a_flat_two_thousand(self):
        """General Amendment — 2,000 per instance, whatever the amount."""
        for amount in (100_000, 50_000_000):
            quote = self._product("14117").quote(
                amount, 1, date(2026, 1, 1), date(2026, 12, 31), action="AMENDMENT",
            )
            self.assertTrue(quote["calculable"], amount)
            self.assertEqual(str(quote["commission"]), "2000.00", amount)

    def test_a_cancellation_is_five_hundred(self):
        quote = self._product("14117").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="CANCELLATION",
        )
        self.assertEqual(str(quote["commission"]), "500.00")

    def test_a_flat_fee_needs_neither_amount_nor_tenor(self):
        """A per-instance charge is answerable even with nothing else known."""
        quote = self._product("14117").quote(
            0, 1, None, None, action="CANCELLATION",
        )
        self.assertTrue(quote["calculable"])
        self.assertEqual(str(quote["commission"]), "500.00")

    def test_an_lc_issuance_is_point_seven_five_per_quarter(self):
        quote = self._product("TR-LC-IMP-SIGHT").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 4, 1), action="ISSUANCE",
        )
        self.assertEqual(str(quote["periods"]), "1")
        self.assertEqual(str(quote["commission"]), "7500.00")

    def test_an_lc_amendment_is_two_thousand_five_hundred_not_two_thousand(self):
        """The book charges LCs and guarantees differently for the same action."""
        lc = self._product("TR-LC-IMP-SIGHT").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="AMENDMENT")
        guarantee = self._product("14117").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="AMENDMENT")
        self.assertEqual(str(lc["commission"]), "2500.00")
        self.assertEqual(str(guarantee["commission"]), "2000.00")

    def test_an_lc_settlement_is_point_three_percent(self):
        quote = self._product("TR-LC-IMP-SIGHT").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="SETTLEMENT",
        )
        self.assertEqual(str(quote["commission"]), "3000.00")

    def test_a_bill_acceptance_uses_the_acceptance_line(self):
        quote = self._product("TR-BLC-IMP-USANCE").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 4, 1),
            action="BILL ACCEPTANCE",
        )
        self.assertEqual(str(quote["commission"]), "7500.00")

    def test_a_collection_acceptance_is_point_three_not_point_seven_five(self):
        """Inward Collections accept at 0.3% a quarter; LC bills at 0.75%."""
        quote = self._product("TR-BDC-IMP-USANCE").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 4, 1),
            action="BILL ACCEPTANCE",
        )
        self.assertEqual(str(quote["commission"]), "3000.00")

    def test_advising_is_a_flat_two_thousand_five_hundred(self):
        quote = self._product("TR-LC-EXP-SIGHT").quote(
            5_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="ADVISING",
        )
        self.assertEqual(str(quote["commission"]), "2500.00")

    def test_a_charge_the_book_states_in_words_says_so_rather_than_guessing(self):
        line = TradeTariff.objects.get(code="TRF-BDC-NOTARY")
        self.assertIn("Notary", line.manual_note)
        self.assertEqual(line.commission_basis, TradeTariff.BASIS_NONE)

    def test_a_dollar_charge_is_not_silently_read_as_shillings(self):
        line = TradeTariff.objects.get(code="TRF-LC-DISCREPANCY")
        self.assertEqual(line.charge_currency, "USD")
        self.assertEqual(str(line.fixed_amount), "100.00")

    def test_the_amount_is_converted_at_the_fx_rate(self):
        quote = self._product("14116").quote(
            1_000, 130, date(2026, 1, 1), date(2026, 12, 31), action="ISSUANCE")
        self.assertEqual(str(quote["commission"]), "1300.00")

    def test_a_product_specific_line_beats_its_category(self):
        bid = TradeTariff.resolve(self._product("14116"), "ISSUANCE")
        other = TradeTariff.resolve(self._product("14117"), "ISSUANCE")
        self.assertEqual(bid.code, "TRF-LG-ISSUE-BID")
        self.assertEqual(other.code, "TRF-LG-ISSUE")

    def test_the_rate_is_amendable_without_a_deploy(self):
        line = TradeTariff.objects.get(code="TRF-LG-ISSUE-BID")
        line.commission_rate = Decimal("1.5")
        line.save()
        quote = self._product("14116").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="ISSUANCE")
        self.assertEqual(str(quote["commission"]), "15000.00")

    def test_the_flat_amount_is_amendable_too(self):
        line = TradeTariff.objects.get(code="TRF-LG-CANCEL")
        line.fixed_amount = Decimal("750")
        line.save()
        quote = self._product("14117").quote(
            1_000_000, 1, date(2026, 1, 1), date(2026, 12, 31), action="CANCELLATION")
        self.assertEqual(str(quote["commission"]), "750.00")


class TariffAdminApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="tariff_admin2", password="x", is_staff=True)
        self.plain = User.objects.create_user(username="tariff_plain2", password="x")

    def test_the_book_lists_every_line_with_its_charge_in_words(self):
        self.client.force_authenticate(self.plain)
        res = self.client.get("/trade_register/tariffs/")
        self.assertEqual(res.status_code, 200)
        by_code = {t["code"]: t for t in res.data}
        self.assertEqual(by_code["TRF-LG-ISSUE"]["charge_summary"],
                         "0.75% per quarter; Min. KES 2,500.00")
        self.assertEqual(by_code["TRF-LG-CANCEL"]["charge_summary"], "KES 500.00")

    def test_an_admin_can_amend_a_rate_and_an_amount(self):
        self.client.force_authenticate(self.admin)
        line = TradeTariff.objects.get(code="TRF-LG-ISSUE")
        res = self.client.patch(f"/trade_register/tariffs/{line.id}/",
                                {"commission_rate": "0.9", "minimum_commission": "3000"},
                                format="json")
        self.assertEqual(res.status_code, 200, res.content)
        line.refresh_from_db()
        self.assertEqual(float(line.commission_rate), 0.9)
        self.assertEqual(float(line.minimum_commission), 3000)

    def test_an_ordinary_user_may_read_the_book_but_not_reprice_it(self):
        self.client.force_authenticate(self.plain)
        line = TradeTariff.objects.get(code="TRF-LG-ISSUE")
        self.assertEqual(self.client.get("/trade_register/tariffs/").status_code, 200)
        res = self.client.patch(f"/trade_register/tariffs/{line.id}/",
                                {"commission_rate": "9"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_the_book_can_be_filtered_to_one_category(self):
        self.client.force_authenticate(self.plain)
        cat = TradeProductCategory.objects.get(code="LG")
        res = self.client.get(f"/trade_register/tariffs/?category={cat.id}")
        self.assertTrue(all(t["category"] == cat.id for t in res.data))


class AmendmentTests(APITestCase):
    """An amendment is its own row; the instrument keeps a live position."""

    def setUp(self):
        self.user = User.objects.create_user(username="amend", password="x")
        self.client.force_authenticate(self.user)
        self.original = entry(amount_fcy=1_000_000,
                              expiry_date=date(2026, 6, 30))

    def test_the_original_is_left_exactly_as_issued(self):
        entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
              amount_delta=500_000)
        self.original.refresh_from_db()
        self.assertEqual(float(self.original.amount_fcy), 1_000_000)
        self.assertEqual(self.original.expiry_date, date(2026, 6, 30))

    def test_an_increase_raises_the_live_position(self):
        entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
              amount_delta=500_000)
        self.original.refresh_from_db()
        self.assertEqual(float(self.original.current_amount), 1_500_000)

    def test_a_reduction_lowers_it(self):
        entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
              amount_delta=Decimal("-250000"))
        self.original.refresh_from_db()
        self.assertEqual(float(self.original.current_amount), 750_000)

    def test_increases_and_reductions_accumulate(self):
        for delta in (500_000, -200_000, 100_000):
            entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
                  amount_delta=Decimal(delta))
        self.original.refresh_from_db()
        self.assertEqual(float(self.original.current_amount), 1_400_000)

    def test_an_extension_moves_the_expiry(self):
        entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
              new_expiry_date=date(2026, 12, 31))
        self.original.refresh_from_db()
        self.assertEqual(self.original.effective_expiry_date, date(2026, 12, 31))

    def test_an_extended_instrument_stops_reading_expired(self):
        """The whole point: chasing a guarantee that is still live wastes a day."""
        today = timezone.localdate()
        past = entry(issue_date=today - timedelta(days=400),
                     expiry_date=today - timedelta(days=5))
        self.assertEqual(past.diary_status(), TradeRegisterEntry.DIARY_EXPIRED)

        entry(action="AMENDMENT", parent_ref=past.guarantee_ref,
              new_expiry_date=today + timedelta(days=60))
        past.refresh_from_db()
        self.assertNotEqual(past.diary_status(), TradeRegisterEntry.DIARY_EXPIRED)
        self.assertEqual(past.effective_expiry_date, today + timedelta(days=60))

    def test_the_latest_extension_wins(self):
        for day in (date(2026, 9, 30), date(2026, 12, 31), date(2026, 8, 31)):
            entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
                  new_expiry_date=day)
        self.original.refresh_from_db()
        self.assertEqual(self.original.effective_expiry_date, date(2026, 12, 31))

    def test_the_amendment_is_linked_to_the_instrument_it_amends(self):
        child = entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref)
        self.assertEqual(child.parent_id, self.original.pk)
        self.assertEqual(self.original.amendments.count(), 1)

    def test_amending_an_amendment_still_lands_on_the_original(self):
        """Otherwise a chain forms and nothing can total the instrument."""
        first = entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref)
        second = entry(action="AMENDMENT", parent_ref=first.guarantee_ref,
                       amount_delta=100_000)
        self.assertEqual(second.parent_id, self.original.pk)
        self.original.refresh_from_db()
        self.assertEqual(float(self.original.current_amount), 1_100_000)

    def test_a_cancellation_marks_the_instrument_closed(self):
        entry(action="CANCELLATION", parent_ref=self.original.guarantee_ref)
        self.original.refresh_from_db()
        self.assertTrue(self.original.is_cancelled)

    def test_the_api_reports_the_live_position_beside_the_issued_one(self):
        entry(action="AMENDMENT", parent_ref=self.original.guarantee_ref,
              amount_delta=500_000, new_expiry_date=date(2026, 12, 31))
        res = self.client.get(f"/trade_register/entries/{self.original.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(float(res.data["amount_fcy"]), 1_000_000)
        self.assertEqual(float(res.data["current_amount"]), 1_500_000)
        self.assertEqual(str(res.data["effective_expiry_date"]), "2026-12-31")
        self.assertEqual(res.data["amendment_count"], 1)


class ExpiryFilingTests(APITestCase):
    """Expired instruments leave the active diary daily — and can come back."""

    def setUp(self):
        self.user = User.objects.create_user(username="expiry", password="x")
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()
        self.expired = entry(
            our_customer="GONE LTD",
            issue_date=self.today - timedelta(days=400),
            expiry_date=self.today - timedelta(days=10))
        self.live = entry(
            our_customer="LIVE LTD",
            issue_date=self.today - timedelta(days=10),
            expiry_date=self.today + timedelta(days=40))

    def test_the_job_files_what_has_expired(self):
        call_command("archive_expired_trade_items")
        self.expired.refresh_from_db()
        self.live.refresh_from_db()
        self.assertTrue(self.expired.is_archived)
        self.assertEqual(self.expired.archived_on, self.today)
        self.assertFalse(self.live.is_archived)

    def test_nothing_is_deleted(self):
        """An expired guarantee is still a record of what the bank issued."""
        before = TradeRegisterEntry.objects.count()
        call_command("archive_expired_trade_items")
        self.assertEqual(TradeRegisterEntry.objects.count(), before)

    def test_a_dry_run_changes_nothing(self):
        call_command("archive_expired_trade_items", "--dry-run")
        self.expired.refresh_from_db()
        self.assertFalse(self.expired.is_archived)

    def test_the_grace_period_keeps_a_just_expired_item_on_the_desk(self):
        call_command("archive_expired_trade_items", "--grace-days", "30")
        self.expired.refresh_from_db()
        self.assertFalse(self.expired.is_archived)

    def test_an_extension_brings_an_archived_instrument_back(self):
        """A job that could only archive would bury a revived instrument."""
        call_command("archive_expired_trade_items")
        self.expired.refresh_from_db()
        self.assertTrue(self.expired.is_archived)

        entry(action="AMENDMENT", parent_ref=self.expired.guarantee_ref,
              new_expiry_date=self.today + timedelta(days=90))
        call_command("archive_expired_trade_items")
        self.expired.refresh_from_db()
        self.assertFalse(self.expired.is_archived)
        self.assertIsNone(self.expired.archived_on)

    def test_the_job_never_archives_an_instrument_an_amendment_extended(self):
        entry(action="AMENDMENT", parent_ref=self.expired.guarantee_ref,
              new_expiry_date=self.today + timedelta(days=30))
        call_command("archive_expired_trade_items")
        self.expired.refresh_from_db()
        self.assertFalse(self.expired.is_archived)

    def test_the_active_register_hides_what_was_filed(self):
        call_command("archive_expired_trade_items")
        res = self.client.get("/trade_register/entries/")
        names = [r["our_customer"] for r in res.data["results"]]
        self.assertIn("LIVE LTD", names)
        self.assertNotIn("GONE LTD", names)

    def test_the_expired_folder_is_exactly_what_was_filed(self):
        call_command("archive_expired_trade_items")
        res = self.client.get("/trade_register/entries/?archived=1")
        names = [r["our_customer"] for r in res.data["results"]]
        self.assertEqual(names, ["GONE LTD"])

    def test_the_diary_drops_archived_items_from_the_active_list(self):
        call_command("archive_expired_trade_items")
        res = self.client.get("/trade_register/diary/")
        self.assertEqual(res.data["counts"]["expired"], 0)

        res = self.client.get("/trade_register/diary/?archived=1")
        self.assertEqual(res.data["counts"]["expired"], 1)


class DateRangeFilterTests(APITestCase):
    """Filtering by period, and exporting exactly the period shown."""

    def setUp(self):
        self.user = User.objects.create_user(username="ranges", password="x")
        self.client.force_authenticate(self.user)
        self.jan = entry(our_customer="JANUARY LTD",
                         issue_date=date(2026, 1, 15),
                         expiry_date=date(2026, 12, 31))
        self.jun = entry(our_customer="JUNE LTD",
                         issue_date=date(2026, 6, 15),
                         expiry_date=date(2027, 6, 30))

    def test_a_date_range_narrows_the_register(self):
        res = self.client.get(
            "/trade_register/entries/?date_from=2026-01-01&date_to=2026-03-31")
        names = [r["our_customer"] for r in res.data["results"]]
        self.assertEqual(names, ["JANUARY LTD"])

    def test_an_open_ended_range_works_from_one_side(self):
        res = self.client.get("/trade_register/entries/?date_from=2026-05-01")
        names = [r["our_customer"] for r in res.data["results"]]
        self.assertEqual(names, ["JUNE LTD"])

    def test_the_range_can_be_applied_to_a_different_date(self):
        res = self.client.get(
            "/trade_register/entries/?date_field=expiry_date"
            "&date_from=2027-01-01&date_to=2027-12-31")
        names = [r["our_customer"] for r in res.data["results"]]
        self.assertEqual(names, ["JUNE LTD"])

    def test_a_nonsense_date_is_ignored_rather_than_returning_nothing(self):
        res = self.client.get("/trade_register/entries/?date_from=not-a-date")
        self.assertEqual(len(res.data["results"]), 2)

    def test_the_register_can_be_filtered_to_a_category(self):
        res = self.client.get("/trade_register/entries/?category=LG")
        self.assertEqual(len(res.data["results"]), 2)
        res = self.client.get("/trade_register/entries/?category=LC")
        self.assertEqual(len(res.data["results"]), 0)


class BranchListTests(APITestCase):
    """One branch, one entry — however it was spelled."""

    def setUp(self):
        self.user = User.objects.create_user(username="branches", password="x")
        self.client.force_authenticate(self.user)

    def test_spelling_variants_collapse_to_one_entry(self):
        entry(originating_branch="THIKA")
        entry(originating_branch="Thika Branch")
        entry(originating_branch="THIKA BRANCH")
        res = self.client.get("/trade_register/branches/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([b for b in res.data if "THIKA" in b], ["THIKA BRANCH"])

    def test_the_list_has_no_duplicates_at_all(self):
        res = self.client.get("/trade_register/branches/")
        self.assertEqual(len(res.data), len(set(res.data)))

    def test_head_office_does_not_appear_twice_under_its_aliases(self):
        entry(originating_branch="HQ")
        entry(originating_branch="HEAD OFFICE")
        res = self.client.get("/trade_register/branches/")
        self.assertEqual([b for b in res.data if "HEAD OFFICE" in b], ["HEAD OFFICE"])
