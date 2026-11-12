"""The register holds every Administration Trade Finance row (77 vs 856)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from rest_framework.test import APITestCase

from apps.staff_management.models import TradeFinanceData

from .mirror import mirror_trade_finance, parse_tf_date
from .models import TradeProduct, TradeRegisterEntry


def _tf(**kw):
    base = dict(
        originating_branch="NAKURU BRANCH", rm_name="RM", rm_code="R1",
        guarantee_ref="HFCB/GTE/250102/01", product_type="BID BOND GUARANTEE",
        customer_id=1, segment="COMMERCIAL", our_customer="CUSTOMER",
        beneficiary="B", currency="KES", amount_fcy=1000, issue_date="2025-01-02",
        expiry_date="2025-06-30", commission_lcy=2500, month="01", fx_rate=1,
        year="2025",
    )
    base.update(kw)
    return TradeFinanceData.objects.create(**base)


class MirrorTradeFinanceTests(APITestCase):
    def test_every_unlinked_row_gets_an_entry_once(self):
        a, b = _tf(), _tf(guarantee_ref="HF90001", issue_date="03/02/2025")
        out = mirror_trade_finance()
        self.assertEqual((out["created"], out["relinked"], out["skipped"]), (2, 0, 0))
        self.assertEqual(TradeRegisterEntry.objects.get(tf=b).issue_date, date(2025, 2, 3))
        entry = TradeRegisterEntry.objects.get(tf=a)
        self.assertEqual((entry.month, entry.year), ("01", "2025"))
        # Run again: nothing new.
        self.assertEqual(mirror_trade_finance()["created"], 0)
        self.assertEqual(TradeRegisterEntry.objects.count(), 2)

    def test_reupload_relinks_instead_of_duplicating(self):
        tf = _tf()
        mirror_trade_finance()
        entry = TradeRegisterEntry.objects.get(tf=tf)
        # The upload replaces the year: the row goes, the entry loses its link.
        TradeFinanceData.objects.filter(year="2025").delete()
        entry.refresh_from_db()
        self.assertIsNone(entry.tf_id)
        new = _tf(commission_lcy=3000)
        out = mirror_trade_finance()
        self.assertEqual((out["created"], out["relinked"]), (0, 1))
        entry.refresh_from_db()
        self.assertEqual(entry.tf_id, new.pk)
        self.assertEqual(entry.commission, Decimal("3000"))
        self.assertEqual(TradeRegisterEntry.objects.count(), 1)

    def test_unreadable_issue_date_is_reported_not_guessed(self):
        bad = _tf(issue_date="TBA")
        out = mirror_trade_finance()
        self.assertEqual(out["skipped_ids"], [bad.pk])
        self.assertFalse(TradeRegisterEntry.objects.exists())

    def test_command_runs_the_mirror(self):
        _tf()
        call_command("backfill_trade_register", verbosity=0)
        self.assertEqual(TradeRegisterEntry.objects.count(), 1)

    def test_date_formats(self):
        self.assertEqual(parse_tf_date("12-Nov-2026"), date(2026, 11, 12))
        self.assertEqual(parse_tf_date("2026-11-12 00:00:00"), date(2026, 11, 12))
        self.assertIsNone(parse_tf_date("OPEN ENDED"))


class FinanceViewListsTheWholeBookTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tf", "tf@example.com", "x")
        self.client.force_authenticate(self.user)

    def test_archived_all_includes_expired(self):
        _tf()
        _tf(guarantee_ref="HFCB/GTE/250102/02")
        mirror_trade_finance()
        TradeRegisterEntry.objects.filter(
            guarantee_ref="HFCB/GTE/250102/02").update(is_archived=True)
        url = "/trade_register/entries/"
        active = self.client.get(url).json()
        everything = self.client.get(url, {"archived": "all"}).json()
        self.assertEqual(active["count"], 1)
        self.assertEqual(everything["count"], 2)


class CashCoverCurrencyTests(APITestCase):
    def test_cover_currency_defaults_to_the_transaction_and_can_differ(self):
        product = TradeProduct.objects.get(code="14116")
        base = dict(
            product=product, originating_branch="X", rm_name="R", segment="C",
            our_customer="Z", currency="USD", amount_fcy=1000, fx_rate=130,
            customer_id=1, issue_date=date(2026, 11, 6),
        )
        same = TradeRegisterEntry.objects.create(cash_cover_amount=500, **base)
        self.assertEqual(same.cash_cover_currency, "USD")
        other = TradeRegisterEntry.objects.create(
            cash_cover_amount=115000, cash_cover_currency="KES", **base)
        other.refresh_from_db()
        self.assertEqual(other.cash_cover_currency, "KES")
        none = TradeRegisterEntry.objects.create(**base)
        self.assertEqual(none.cash_cover_currency, "")
