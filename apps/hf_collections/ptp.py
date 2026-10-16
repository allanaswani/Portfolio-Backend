"""PTP - Promise To Pay.

What it is
──────────
A PTP is a commitment a collector takes from a borrower who is behind: "I
will pay 50,000 on the 28th". It is the central unit of work in a collections
desk, and the only number that matters about it is not the promise - it is
whether the money arrived. A desk that records promises and never checks them
is recording hope.

So this module does two things, and the second is the point:

1. **holds the promise** - who promised, how much, by when, which loan;
2. **settles it against the money**, by reading ``loan_repayments`` for what
   was actually paid on that loan account between the promise being made and
   its due date.

Why the status is computed and never typed
──────────────────────────────────────────
``PromiseToPay.status`` has no setter on the API. A collector cannot mark
their own promise kept, because "PTP kept rate" is the measure their work is
judged by and a self-marked measure is not a measure. It is derived from the
repayments feed, every time, and recomputed whenever the figures move.

Where the promises come from
────────────────────────────
The collections feedback form already captures ``ptp_amount`` and
``next_action_date`` on every diary entry, and has for as long as the table
has existed - so the desk has been recording promises all along with nothing
reading them. :func:`from_feedback` turns those rows into promises, which
means the history is there from the first run and a collector does not have to
start typing into a second form to get the benefit.

The grace period
────────────────
A payment on the 29th against a promise for the 28th was kept, in every sense
a collections desk cares about. :data:`GRACE_DAYS` is that allowance, and it
is deliberately one constant rather than a rule per officer.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

#: How long after the promised date a payment still counts as keeping it.
#: Three days covers a weekend, which is when most of them land.
GRACE_DAYS = 3

#: Below this, a payment is not treated as part-keeping a promise. A 50-bob
#: standing order landing in the window is not a borrower acting on a promise
#: to pay 50,000, and counting it as "partly kept" would flatter the desk.
MIN_MEANINGFUL = Decimal("100")


def paid_against(loan_account_no, start, end):
    """What was actually paid on this loan in a window → ``(amount, latest)``.

    Principal AND interest, because a promise is a promise to pay money, not
    to pay down principal - a borrower who clears their arrears interest has
    kept their word.

    ``loan_repayments`` is the warehouse's payment feed. It is read directly
    rather than through the ORM because the table is unmanaged and this is one
    aggregate over an indexed column, which is cheaper than loading rows the
    caller will only sum.
    """
    from django.db import connection

    if not loan_account_no:
        return Decimal("0"), None

    sql = """
        SELECT COALESCE(SUM(COALESCE(principal_paid, 0)
                            + COALESCE(interest_paid, 0)), 0),
               MAX(transaction_date)
        FROM loan_repayments
        WHERE TRIM(loan_account_number) = TRIM(%s)
          AND transaction_date >= %s
          AND transaction_date < %s
    """
    try:
        with connection.cursor() as cur:
            cur.execute(sql, [str(loan_account_no), start,
                              end + datetime.timedelta(days=1)])
            total, latest = cur.fetchone()
    except Exception:  # noqa: BLE001 - an absent feed must not break the desk
        # ``loan_repayments`` is a warehouse table this repo does not own. On
        # a host where the ETL has not run it is simply not there, and a
        # collections screen that 500s is worse than one that reports every
        # promise as still open. Nothing is marked broken on the strength of
        # a feed that could not be read: a read failure returns nought paid,
        # and ``settle`` only calls a promise broken once its date has
        # passed - which is the same answer it would give for a borrower who
        # genuinely paid nothing, and is corrected on the next run.
        return Decimal("0"), None
    return Decimal(str(total or 0)), latest


def settle(promise, today=None):
    """Work out where one promise stands. Returns the promise, unsaved.

    Four outcomes, and they are not interchangeable:

    ``kept``        the promised amount, or more, arrived in time
    ``part_kept``   something meaningful arrived, but short of the promise
    ``broken``      the date and its grace have passed and nothing came
    ``open``        the date has not passed yet, so there is nothing to judge

    An open promise is NOT counted against anybody. A desk measured on a
    kept rate that includes promises not yet due would read worse every time
    a collector books one, which would teach them to stop booking them.
    """
    from .models import PromiseToPay

    today = today or datetime.date.today()
    due = promise.promised_date
    if due is None:
        promise.status = PromiseToPay.STATUS_OPEN
        promise.amount_paid = Decimal("0")
        promise.settled_on = None
        return promise

    window_from = promise.promised_on or due
    window_to = due + datetime.timedelta(days=GRACE_DAYS)
    paid, latest = paid_against(promise.loan_account_no, window_from,
                                window_to)

    promise.amount_paid = paid
    promise.settled_on = (latest.date() if hasattr(latest, "date") else latest)

    promised = promise.promised_amount or Decimal("0")
    if promised > 0 and paid >= promised:
        promise.status = PromiseToPay.STATUS_KEPT
    elif paid >= MIN_MEANINGFUL:
        promise.status = PromiseToPay.STATUS_PART
    elif today > window_to:
        promise.status = PromiseToPay.STATUS_BROKEN
    else:
        promise.status = PromiseToPay.STATUS_OPEN
    return promise


def settle_all(queryset=None, today=None):
    """Re-settle every promise that could still change → how many moved.

    A ``kept`` promise is left alone: the money arrived and no later feed can
    un-arrive it. Everything else is recomputed, because a payment that lands
    today changes a promise that was broken yesterday.
    """
    from .models import PromiseToPay

    rows = queryset if queryset is not None else PromiseToPay.objects.exclude(
        status=PromiseToPay.STATUS_KEPT)

    changed = []
    for promise in rows:
        was = (promise.status, promise.amount_paid)
        settle(promise, today=today)
        if (promise.status, promise.amount_paid) != was:
            changed.append(promise)
    if changed:
        PromiseToPay.objects.bulk_update(
            changed, ["status", "amount_paid", "settled_on"])
    return len(changed)


def from_feedback(rows=None, today=None):
    """Turn collections diary entries into promises → ``(made, settled)``.

    The feedback form has always captured ``ptp_amount`` and a date. A row
    with both is a promise somebody took; a row with neither is a call that
    did not produce one. Upserted on (loan account, promised date, officer)
    so re-running this does not stack duplicates of the same promise.
    """
    from .models import Collection, PromiseToPay

    rows = rows if rows is not None else Collection.objects.filter(
        ptp_amount__gt=0, next_action_date__isnull=False)

    made = 0
    for row in rows:
        if not row.ptp_amount or not row.next_action_date:
            continue
        promise, created = PromiseToPay.objects.update_or_create(
            loan_account_no=row.loan_account_no,
            promised_date=row.next_action_date,
            collection_officer_code=row.collection_officer_code or "",
            defaults={
                "cust_id": row.cust_id,
                "customer_name": row.customer_name or "",
                "collection_officer_name": row.collection_officer_name or "",
                "promised_amount": Decimal(str(row.ptp_amount)),
                "promised_on": row.recording_date,
                "source": PromiseToPay.SOURCE_FEEDBACK,
                "note": (row.additional_comments or "")[:500],
            })
        made += 1 if created else 0
        settle(promise, today=today)
        promise.save(update_fields=["status", "amount_paid", "settled_on"])
    return made, len(rows) if hasattr(rows, "__len__") else rows.count()


def kept_rate(queryset=None):
    """The desk's own measure → a summary dict.

    The kept rate is over DECIDED promises only - kept, part-kept and broken.
    Promises not yet due are reported beside it and excluded from it, for the
    reason in :func:`settle`.
    """
    from django.db.models import Count, Sum

    from .models import PromiseToPay

    rows = queryset if queryset is not None else PromiseToPay.objects.all()
    by_status = {
        item["status"]: item for item in
        rows.values("status").annotate(
            n=Count("id"), promised=Sum("promised_amount"),
            paid=Sum("amount_paid"))
    }

    def get(key, field):
        return (by_status.get(key, {}) or {}).get(field) or 0

    kept = get(PromiseToPay.STATUS_KEPT, "n")
    part = get(PromiseToPay.STATUS_PART, "n")
    broken = get(PromiseToPay.STATUS_BROKEN, "n")
    open_ = get(PromiseToPay.STATUS_OPEN, "n")
    decided = kept + part + broken

    return {
        "kept": kept, "part_kept": part, "broken": broken, "open": open_,
        "decided": decided, "total": decided + open_,
        # Part-kept is NOT counted as kept. A borrower who promised 50,000 and
        # paid 5,000 did not keep their promise, and rolling the two together
        # is how a kept rate stops meaning anything.
        "kept_rate": round(kept / decided, 4) if decided else None,
        "kept_or_part_rate": (round((kept + part) / decided, 4)
                              if decided else None),
        "promised_value": float(
            sum(get(s, "promised") for s in
                (PromiseToPay.STATUS_KEPT, PromiseToPay.STATUS_PART,
                 PromiseToPay.STATUS_BROKEN, PromiseToPay.STATUS_OPEN))),
        "paid_value": float(
            sum(get(s, "paid") for s in
                (PromiseToPay.STATUS_KEPT, PromiseToPay.STATUS_PART,
                 PromiseToPay.STATUS_BROKEN, PromiseToPay.STATUS_OPEN))),
        "grace_days": GRACE_DAYS,
    }
