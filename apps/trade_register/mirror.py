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

import re
from datetime import date, datetime

from django.db import transaction

#: Formats seen in ``trade_finance_data.issue_date`` / ``expiry_date`` (text
#: columns filled by hand and by uploads). Day-first before month-first: the
#: desk writes Kenyan dates.
DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d/%m/%y",
    # The desk's upload writes 2025-Sep-02 (785 of the 856 rows on 12 Nov
    # 2026), and September sometimes as "Sept" - normalised before parsing.
    "%Y-%b-%d",
)


def parse_tf_date(value):
    """A TF text date -> ``date``, or ``None`` when it is not a date."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = re.sub(r"(?i)-sept-", "-Sep-", str(value).strip())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:19] if "%H" in fmt else text, fmt).date()
        except ValueError:
            continue
    return None


def action_of(ref):
    """``(action, parent_ref)`` from a reference's action suffix.

    The desk writes an action on an existing instrument as the instrument's
    reference plus a suffix (``HFC/GTE/240521/02 - EXT``), see
    :mod:`.references`. A reference without a known suffix is an issuance."""
    from . import references as refs

    ref = (ref or "").strip()
    base = refs.base_reference(ref)
    suffix = ref[len(base):].strip(" -").strip().upper()
    known = set(refs.ACTIONS) | set(refs.LEGACY_ACTIONS)
    if suffix and suffix in known and suffix != refs.ACTION_ISSUANCE:
        return suffix, base
    return refs.ACTION_ISSUANCE, ""


def link_parents():
    """Point every action that has no parent at the issuance it acts on.
    -> how many were linked."""
    from . import references as refs
    from .models import TradeRegisterEntry

    issued = {}
    for pk, ref in (TradeRegisterEntry.objects
                    .filter(action=refs.ACTION_ISSUANCE)
                    .order_by("id").values_list("pk", "guarantee_ref")):
        issued.setdefault((ref or "").strip(), pk)
    linked = 0
    for pk, parent_ref in (TradeRegisterEntry.objects
                           .exclude(action=refs.ACTION_ISSUANCE)
                           .filter(parent__isnull=True)
                           .exclude(parent_ref="")
                           .values_list("pk", "parent_ref")):
        parent = issued.get(parent_ref.strip())
        if parent and parent != pk:
            TradeRegisterEntry.objects.filter(pk=pk).update(parent_id=parent)
            linked += 1
    return linked


def _untouched(entry):
    """True when no person has saved this entry since it was mirrored."""
    return not entry.history.filter(history_user__isnull=False).exists()


def repair_mirrored():
    """Undo what the 12 Nov 2026 mirror got wrong, on entries nobody has edited.

    * reporting date = the day it was mirrored -> the issue date;
    * cash cover currency copied from the transaction -> blank (not stated);
    * an action suffix read as an issuance -> its action and parent reference.

    Only entries the mirror made (no ``created_by``, linked to a TF row) are
    touched, and of those only ones no person has saved since.
    -> ``{"reporting_date", "cover_currency", "action"}`` counts.
    """
    from django.utils import timezone

    from . import references as refs
    from .models import TradeRegisterEntry

    fixed = {"reporting_date": 0, "cover_currency": 0, "action": 0}
    rows = (TradeRegisterEntry.objects
            .filter(created_by__isnull=True, tf__isnull=False)
            .order_by("pk"))
    for entry in rows.iterator():
        if not _untouched(entry):
            continue
        updates = {}
        made = timezone.localtime(entry.created_at).date() if entry.created_at else None
        if (entry.reporting_date == made and entry.issue_date
                and entry.reporting_date != entry.issue_date):
            updates["reporting_date"] = entry.issue_date
            fixed["reporting_date"] += 1
        if entry.cash_cover_currency and entry.cash_cover_currency == entry.currency:
            updates["cash_cover_currency"] = ""
            fixed["cover_currency"] += 1
        action, parent_ref = action_of(entry.guarantee_ref)
        if entry.action == refs.ACTION_ISSUANCE and action != refs.ACTION_ISSUANCE:
            updates.update(action=action, parent_ref=parent_ref)
            fixed["action"] += 1
        if updates:
            # A queryset update: bookkeeping, not a business change, and the
            # TF row stays exactly as the desk loaded it.
            TradeRegisterEntry.objects.filter(pk=entry.pk).update(**updates)
    return fixed


def file_expired():
    """Run the daily expiry filing now, so mirrored long-expired rows leave
    the active diary straight away rather than at 01:00."""
    from io import StringIO

    from django.core.management import call_command

    call_command("archive_expired_trade_items", stdout=StringIO())


def _entry_from_tf(tf, products):
    """An unsaved register entry carrying the TF row's values."""
    from .models import TradeRegisterEntry, _dec

    open_ended = str(tf.expiry_date or "").strip().upper() == "OPEN ENDED"
    name = (tf.product_type or "").strip().upper()
    product = products.get(name) or products.get(name.split(" - ")[0].strip())
    action, parent_ref = action_of(tf.guarantee_ref)
    issue = parse_tf_date(tf.issue_date)
    return TradeRegisterEntry(
        tf=tf,
        action=action,
        parent_ref=parent_ref,
        # Trade Finance has no reporting date. The model's default is the day
        # the entry is made, which put every mirrored row of every year into
        # this week's register; the issue date is the transaction's own date.
        reporting_date=issue,
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
        issue_date=issue,
        is_open_ended=open_ended,
        expiry_date=None if open_ended else parse_tf_date(tf.expiry_date),
        security_type=tf.security_type or "",
        cash_cover_amount=_dec(tf.cash_cover_amount),
        cash_cover_percentage=_dec(tf.cash_cover_percentage),
        # Trade Finance does not say which currency the cover is held in, so
        # it is left blank for the desk to pick - never assumed to be the
        # transaction's (a USD letter of credit is often covered in KES).
        cash_cover_currency="",
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
    if created or relinked:
        link_parents()
        file_expired()
    return {"created": created, "relinked": relinked,
            "skipped": len(skipped_ids), "skipped_ids": skipped_ids}
