"""Give every Administration Trade Finance row its register entry.

The register and ``trade_finance_data`` are meant to be one set of
transactions seen two ways. Two things pulled them apart:

* the one-off backfill mirrored the rows that existed at the time, and nothing
  mirrored rows loaded afterwards;
* the Trade Finance upload replaces a whole year: it deletes that year's rows
  and inserts the file. A deleted row's register entry keeps its data, but its
  link goes (``on_delete=SET_NULL``), and the re-inserted row is a new row that
  no entry points at.

So after an upload, Administration listed every row and the register listed
only what it was given by hand (77 against 856 on 12 Nov 2026).

:func:`mirror_trade_finance` closes the gap and is safe to run at any time.
Each unlinked TF row is first RE-LINKED to the entry it was a copy of: an
entry with no TF row, the same reference and the same issue date, when exactly
one such entry exists. Otherwise a new entry is created. Nothing is deleted and
no TF row is changed.
"""

from datetime import date, datetime

from django.db import transaction

#: Formats seen in ``trade_finance_data.issue_date`` / ``expiry_date`` (text
#: columns filled by hand and by uploads). Day-first before month-first: the
#: desk writes Kenyan dates.
DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d/%m/%y",
)


def parse_tf_date(value):
    """A TF text date -> ``date``, or ``None`` when it is not a date."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:19] if "%H" in fmt else text, fmt).date()
        except ValueError:
            continue
    return None


def _entry_from_tf(tf, products):
    """An unsaved register entry carrying the TF row's values."""
    from .models import TradeRegisterEntry, _dec

    open_ended = str(tf.expiry_date or "").strip().upper() == "OPEN ENDED"
    name = (tf.product_type or "").strip().upper()
    product = products.get(name) or products.get(name.split(" - ")[0].strip())
    return TradeRegisterEntry(
        tf=tf,
        originating_branch=tf.originating_branch or "",
        rm_name=tf.rm_name or "",
        rm_code=tf.rm_code or "",
        guarantee_ref=tf.guarantee_ref or "",  # the historical reference, as is
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
        issue_date=parse_tf_date(tf.issue_date),
        is_open_ended=open_ended,
        expiry_date=None if open_ended else parse_tf_date(tf.expiry_date),
        security_type=tf.security_type or "",
        cash_cover_amount=_dec(tf.cash_cover_amount),
        cash_cover_percentage=_dec(tf.cash_cover_percentage),
        # Trade Finance has no cover currency; the entry's own save would
        # take the transaction's, so do the same here.
        cash_cover_currency=(tf.currency or "KES")
        if _dec(tf.cash_cover_amount) is not None else "",
        other_security=tf.other_security or "",
        month=str(tf.month or ""),
        year=str(tf.year or ""),
    )


def mirror_trade_finance(limit=0):
    """Link or create a register entry for every TF row without one.

    -> ``{"created", "relinked", "skipped", "skipped_ids"}``. A row is skipped
    only when its issue date cannot be read; ``skipped_ids`` names them so the
    desk can correct the date in Administration and run this again.
    """
    from apps.staff_management.models import TradeFinanceData

    from .models import TradeProduct, TradeRegisterEntry

    products = {p.name.upper(): p for p in TradeProduct.objects.all()}
    linked = TradeRegisterEntry.objects.exclude(tf__isnull=True).values_list(
        "tf_id", flat=True)
    rows = TradeFinanceData.objects.exclude(pk__in=linked).order_by("pk")
    if limit:
        rows = rows[:limit]

    created = relinked = 0
    skipped_ids = []
    for tf in rows.iterator():
        issue = parse_tf_date(tf.issue_date)
        if issue is None:
            skipped_ids.append(tf.pk)
            continue
        ref = (tf.guarantee_ref or "").strip()
        with transaction.atomic():
            orphans = list(TradeRegisterEntry.objects.select_for_update().filter(
                tf__isnull=True, guarantee_ref=ref, issue_date=issue)[:2]) if ref else []
            if len(orphans) == 1:
                entry = orphans[0]
                TradeRegisterEntry.objects.filter(pk=entry.pk).update(tf=tf)
                entry.tf_id = tf.pk
                entry.apply_from_trade_finance(tf)
                relinked += 1
                continue
            entry = _entry_from_tf(tf, products)
            # The plain Model.save: the entry's own save() would derive fields
            # and write back to the TF row this is a copy of.
            super(TradeRegisterEntry, entry).save()
            created += 1
    return {"created": created, "relinked": relinked,
            "skipped": len(skipped_ids), "skipped_ids": skipped_ids}
