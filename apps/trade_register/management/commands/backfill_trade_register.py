"""Backfill register entries from the existing ``trade_finance_data`` rows.

The Administration Trade Finance table already holds the historical transactions
(loaded from Esther's workbook via CSV). This command creates a linked
``TradeRegisterEntry`` for each TF row that doesn't have one yet, so the register
shows the full history and future edits stay in sync.

Idempotent: rows already linked (``tf.register_entry`` exists) are skipped. It
does not overwrite or delete anything on the TF side.

    python manage.py backfill_trade_register
"""

from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.staff_management.models import TradeFinanceData

from ...models import TradeProduct, TradeRegisterEntry, _dec


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value)[:19], fmt).date()
        except ValueError:
            continue
    return None


class Command(BaseCommand):
    help = "Create register entries mirroring existing trade_finance_data rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Only process the first N unlinked TF rows (0 = all).",
        )

    def handle(self, *args, **opts):
        # Map product name → product for a best-effort product FK.
        products = {p.name.upper(): p for p in TradeProduct.objects.all()}
        linked_tf_ids = set(
            TradeRegisterEntry.objects.exclude(tf__isnull=True).values_list("tf_id", flat=True)
        )
        qs = TradeFinanceData.objects.exclude(pk__in=linked_tf_ids).order_by("pk")
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        created = skipped = 0
        for tf in qs.iterator():
            issue = _parse_date(tf.issue_date)
            if issue is None:
                skipped += 1
                continue
            open_ended = str(tf.expiry_date or "").strip().upper() == "OPEN ENDED"
            # Match product by exact name, else by the base name before any " - ".
            name = (tf.product_type or "").strip().upper()
            product = products.get(name) or products.get(name.split(" - ")[0].strip())

            with transaction.atomic():
                entry = TradeRegisterEntry(
                    tf=tf,
                    originating_branch=tf.originating_branch or "",
                    rm_name=tf.rm_name or "",
                    rm_code=tf.rm_code or "",
                    guarantee_ref=tf.guarantee_ref or "",  # keep historical ref as-is
                    product=product,
                    product_type=tf.product_type or "",
                    customer_id=tf.customer_id or 0,
                    segment=tf.segment or "",
                    our_customer=tf.our_customer or "",
                    beneficiary=tf.beneficiary or "",
                    currency=tf.currency or "KES",
                    amount_fcy=_dec(tf.amount_fcy, 0),
                    fx_rate=_dec(tf.fx_rate, 0),
                    commission=_dec(tf.commission_lcy, 0),
                    issue_date=issue,
                    is_open_ended=open_ended,
                    expiry_date=None if open_ended else _parse_date(tf.expiry_date),
                    security_type=tf.security_type or "",
                    cash_cover_amount=_dec(tf.cash_cover_amount),
                    cash_cover_percentage=_dec(tf.cash_cover_percentage),
                    other_security=tf.other_security or "",
                )
                # product_type is derived from product on save when a product is
                # matched; keep the original TF label when it isn't.
                if product is None:
                    entry.product_type = tf.product_type or ""
                super(TradeRegisterEntry, entry).save()  # skip re-sync back to TF
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Backfill complete: {created} entries created, {skipped} skipped (unparseable issue date)."
        ))
