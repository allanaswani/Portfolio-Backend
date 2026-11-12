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
        # The desk's upload format, as found on 785 production rows.
        self.assertEqual(parse_tf_date("2025-Sep-02"), date(2025, 9, 2))
        self.assertEqual(parse_tf_date("2026-Sept-07"), date(2026, 9, 7))
        self.assertEqual(parse_tf_date("2030-Jul-31"), date(2030, 7, 31))

    def test_upload_format_rows_are_mirrored_with_their_dates(self):
        tf = _tf(issue_date="2026-Sept-07", expiry_date="2027-Mar-31")
        oe = _tf(guarantee_ref="HF1", issue_date="2025-Feb-11", expiry_date="Open ended")
        out = mirror_trade_finance()
        self.assertEqual((out["created"], out["skipped"]), (2, 0))
        e = TradeRegisterEntry.objects.get(tf=tf)
        self.assertEqual((e.issue_date, e.expiry_date), (date(2026, 9, 7), date(2027, 3, 31)))
        e = TradeRegisterEntry.objects.get(tf=oe)
        self.assertTrue(e.is_open_ended)
        self.assertIsNone(e.expiry_date)


class FinanceViewListsTheWholeBookTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("tf", "tf@example.com", "x")
        self.client.force_authenticate(self.user)

    def test_archived_all_includes_expired(self):
        _tf(expiry_date="2099-12-31")
        _tf(guarantee_ref="HFCB/GTE/250102/02", expiry_date="2099-12-31")
        mirror_trade_finance()
        TradeRegisterEntry.objects.filter(
            guarantee_ref="HFCB/GTE/250102/02").update(is_archived=True)
        url = "/trade_register/entries/"
        active = self.client.get(url).json()
        everything = self.client.get(url, {"archived": "all"}).json()
        self.assertEqual(active["count"], 1)
        self.assertEqual(everything["count"], 2)


class CashCoverCurrencyTests(APITestCase):
    def test_cover_currency_is_never_assumed(self):
        product = TradeProduct.objects.get(code="14116")
        base = dict(
            product=product, originating_branch="X", rm_name="R", segment="C",
            our_customer="Z", currency="USD", amount_fcy=1000, fx_rate=130,
            customer_id=1, issue_date=date(2026, 11, 6),
        )
        # A cover amount with no currency stated stays unstated: a USD letter
        # of credit covered in shillings must not read as USD.
        same = TradeRegisterEntry.objects.create(cash_cover_amount=500, **base)
        self.assertEqual(same.cash_cover_currency, "")
        other = TradeRegisterEntry.objects.create(
            cash_cover_amount=115000, cash_cover_currency="KES", **base)
        other.refresh_from_db()
        self.assertEqual(other.cash_cover_currency, "KES")
        none = TradeRegisterEntry.objects.create(**base)
        self.assertEqual(none.cash_cover_currency, "")


class MirroredEntriesReadAsTheirOwnDatesTests(APITestCase):
    """12 Nov 2026: every mirrored row showed as reported that day, in USD
    cover and as an issuance, whatever its reference said."""

    def test_new_entries_take_the_issue_date_and_their_action(self):
        _tf(guarantee_ref="HFC/GTE/240521/02", issue_date="2024-May-21",
            expiry_date="2099-12-31", currency="USD", cash_cover_amount=1000)
        _tf(guarantee_ref="HFC/GTE/240521/02 - EXT", issue_date="2025-Apr-07",
            expiry_date="2099-12-31", currency="USD")
        _tf(guarantee_ref="HFCB/GTE/250102/09", expiry_date="2025-06-30")
        mirror_trade_finance()
        original = TradeRegisterEntry.objects.get(guarantee_ref="HFC/GTE/240521/02")
        self.assertEqual(original.reporting_date, date(2024, 5, 21))
        self.assertEqual(original.action, "ISSUANCE")
        self.assertEqual(original.cash_cover_currency, "")
        ext = TradeRegisterEntry.objects.get(guarantee_ref="HFC/GTE/240521/02 - EXT")
        self.assertEqual((ext.action, ext.parent_ref, ext.parent_id),
                         ("EXT", "HFC/GTE/240521/02", original.pk))
        self.assertEqual(ext.reporting_date, date(2025, 4, 7))
        # Long expired: filed straight away, not left on this week's diary.
        expired = TradeRegisterEntry.objects.get(guarantee_ref="HFCB/GTE/250102/09")
        self.assertTrue(expired.is_archived)

    def test_repair_fixes_untouched_entries_only(self):
        from django.utils import timezone

        from .mirror import repair_mirrored

        a = _tf(guarantee_ref="HFC/GTE/240521/02 - EXT", issue_date="2025-Apr-07",
                expiry_date="2099-12-31", currency="USD", cash_cover_amount=5)
        b = _tf(guarantee_ref="HFCB/GTE/250102/05", expiry_date="2099-12-31",
                currency="USD", cash_cover_amount=5)
        mirror_trade_finance()
        today = timezone.localdate()
        # What the first mirror wrote.
        TradeRegisterEntry.objects.update(reporting_date=today,
                                          cash_cover_currency="USD",
                                          action="ISSUANCE", parent_ref="")
        # Somebody has since saved b by hand: theirs stands.
        user = User.objects.create_user("desk")
        entry_b = TradeRegisterEntry.objects.get(tf=b)
        entry_b._history_user = user
        entry_b.save()
        fixed = repair_mirrored()
        self.assertEqual(fixed, {"reporting_date": 1, "cover_currency": 1, "action": 1})
        entry_a = TradeRegisterEntry.objects.get(tf=a)
        self.assertEqual(
            (entry_a.reporting_date, entry_a.cash_cover_currency, entry_a.action),
            (date(2025, 4, 7), "", "EXT"))
        entry_b.refresh_from_db()
        self.assertEqual(entry_b.reporting_date, today)
