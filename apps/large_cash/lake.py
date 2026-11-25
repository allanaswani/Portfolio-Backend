"""Large cash transactions, read off the lake.

Source: ``delta.gold_db.fact_dep_trx_recording`` - the same table the
transaction diary ETL (transaction_diary_trino.sql) reads. Read straight from
the lake rather than from ``transaction_diary``, whose load since mid-September
2026 has written dates as year 0026, skipped days and carried a fraction of the
rows.

Rules, each checked against the lake (25 Nov 2026):

* **Cash** is the bank's own cash justifications: 31001 DEPOSIT CASH,
  31004 CASH DEPOSIT MACHINE (CDM), 31002 CASH DEPOSIT FROM ATM (in), and
  32001 CASH WITHDRAWAL, 31615 OTC CASH WITHDRAWAL, 31617 COUNTER CHEQUE
  WITHDRAWAL - cash paid over the counter against a cheque (out). PETTY CASH
  JC (31809) is an internal journal, not a customer's cash, and ATM card
  withdrawals never reach the threshold (largest since August: 78,556).
* **KES 500,000 and above**, foreign-currency cash at its KES equivalent:
  the row's own fixing rate (o_fixing_rate, KES per unit; 0 on a shilling
  account). The largest foreign cash since October was USD 20,000 - KES 2.6m,
  under 500,000 in its own currency.
* **One row per transaction**: the raw table repeats rows on some days (31 Oct
  2026: 1.77m raw, 363k distinct), so rows are grouped on the bank's own
  transaction key - date, unit, user, user serial, internal serial.
* **Reversed** when the extract marks it reversed or a reversal
  (fst_demand_extrait REVERSE_FLAG / REVERSED_TRX_FLAG = '1'), the diary
  ETL's own rule. Kept and marked, not dropped, and left out of the totals.
"""
from __future__ import annotations

import datetime
import decimal
import logging
import threading

log = logging.getLogger(__name__)

THRESHOLD_KES = 500_000
DEPOSITS = {31001: "DEPOSIT CASH", 31004: "CASH DEPOSIT MACHINE (CDM)",
            31002: "CASH DEPOSIT FROM ATM"}
WITHDRAWALS = {32001: "CASH WITHDRAWAL", 31615: "OTC CASH WITHDRAWAL",
               31617: "COUNTER CHEQUE WITHDRAWAL"}
CASH_CODES = {**DEPOSITS, **WITHDRAWALS}
#: How far back a first load reads, and the most days one run reads.
FIRST_LOAD_DAYS = 31
MAX_DAYS_PER_RUN = 62
#: The lake fills a day in over more than one run, so the newest days are
#: read again each time.
REREAD_DAYS = 3
REFRESH_EVERY_SECONDS = 3600

_KES = "CASE WHEN d.o_fixing_rate > 0 THEN abs(d.i_amount) * d.o_fixing_rate ELSE abs(d.i_amount) END"

SQL = f"""
SELECT d.transaction_date AS trx_date,
       cast(d.transaction_unit AS integer) AS unit,
       d.transaction_user AS teller,
       cast(d.transaction_user_serial_number AS bigint) AS user_sn,
       cast(d.tun_internal_sn AS bigint) AS internal_sn,
       max(d.timestamp) AS posted_at,
       max(d.transaction_unit_name) AS branch,
       max(d.transaction_user_name) AS teller_name,
       max(cast(cast(d.account_number AS bigint) AS varchar)) AS account_number,
       max(cast(cast(d.customer_id AS bigint) AS varchar)) AS customer_id,
       max(a.designation) AS account_name,
       max(cast(d.justific_id AS integer)) AS justific_id,
       max(d.currency_name) AS currency,
       max(abs(d.i_amount)) AS amount,
       max({_KES}) AS amount_kes,
       max(d.channel_description) AS channel,
       max(d.i_comments) AS comments,
       coalesce(bool_or(f.reverse_flag = '1' OR f.reversed_trx_flag = '1'), false) AS reversed
FROM delta.gold_db.fact_dep_trx_recording d
LEFT JOIN delta.gold_db.deposit_account a ON d.account_number = a.account_number
LEFT JOIN delta.gold_db.fst_demand_extrait f
       ON d.transaction_date = f.trx_date
      AND cast(d.transaction_unit AS integer) = cast(f.trx_unit AS integer)
      AND d.transaction_user_serial_number = f.trx_sn
      AND d.transaction_user = f.trx_usr
      AND d.tun_internal_sn = f.tun_internal_sn
WHERE d.transaction_date BETWEEN DATE '{{start}}' AND DATE '{{end}}'
  AND d.justific_id IN ({", ".join(str(c) for c in sorted(CASH_CODES))})
  AND {_KES} >= {THRESHOLD_KES}
GROUP BY 1, 2, 3, 4, 5
"""

LATEST_SQL = """
SELECT max(transaction_date) FROM delta.gold_db.fact_dep_trx_recording
WHERE transaction_date >= current_date - INTERVAL '45' DAY
"""


def _connect():
    from apps.staff_management.cost_ingest import _connect as connect

    return connect()


def lake_latest_day():
    """The newest transaction date the lake holds → date or None."""
    cur = _connect().cursor()
    cur.execute(LATEST_SQL)
    row = cur.fetchone()
    value = row[0] if row else None
    return value if isinstance(value, datetime.date) else None


def _dec(value):
    if value is None:
        return decimal.Decimal("0")
    return decimal.Decimal(str(value)).quantize(decimal.Decimal("0.01"))


def _text(value, limit):
    return ("" if value is None else str(value).strip())[:limit]


def fetch(start, end):
    """Every large cash transaction from ``start`` to ``end`` (dates) → list
    of dicts, as the model stores them."""
    cur = _connect().cursor()
    cur.execute(SQL.format(start=start.isoformat(), end=end.isoformat()))
    cols = [c[0] for c in cur.description]
    out = []
    for raw in cur.fetchall():
        r = dict(zip(cols, raw))
        code = int(r["justific_id"])
        posted = r["posted_at"]
        if isinstance(posted, datetime.datetime) and posted.tzinfo is None:
            from django.utils import timezone

            posted = timezone.make_aware(posted)
        out.append({
            "trx_date": r["trx_date"], "unit": int(r["unit"] or 0),
            "teller": _text(r["teller"], 40), "user_sn": int(r["user_sn"] or 0),
            "internal_sn": int(r["internal_sn"] or 0),
            "posted_at": posted if isinstance(posted, datetime.datetime) else None,
            "branch": _text(r["branch"], 120),
            "teller_name": _text(r["teller_name"], 200),
            "account_number": _text(r["account_number"], 40),
            "customer_id": _text(r["customer_id"], 40),
            "account_name": _text(r["account_name"], 300),
            "justific_id": code,
            "transaction_type": CASH_CODES.get(code, str(code)),
            "direction": "deposit" if code in DEPOSITS else "withdrawal",
            "currency": _text(r["currency"], 60),
            "amount": _dec(r["amount"]), "amount_kes": _dec(r["amount_kes"]),
            "channel": _text(r["channel"], 120), "comments": _text(r["comments"], 500),
            "reversed": bool(r["reversed"]),
        })
    return out


def save(rows, start, end, loaded_by=""):
    """Replace ``start``..``end`` with ``rows``; record every day read, with
    or without large cash → how many rows."""
    from django.db import transaction

    from .models import LargeCashDay, LargeCashTransaction

    with transaction.atomic():
        LargeCashTransaction.objects.filter(trx_date__range=(start, end)).delete()
        LargeCashTransaction.objects.bulk_create(
            [LargeCashTransaction(**r) for r in rows], batch_size=1000)
        day = start
        while day <= end:
            mine = [r for r in rows if r["trx_date"] == day and not r["reversed"]]
            LargeCashDay.objects.update_or_create(day=day, defaults={
                "transactions": len(mine),
                "total_kes": sum((r["amount_kes"] for r in mine), decimal.Decimal("0")),
                "loaded_by": loaded_by})
            day += datetime.timedelta(days=1)
    return len(rows)


def days_to_read(latest, today=None):
    """(start, end) of what a run reads, or None: from the last day read
    (less REREAD_DAYS) - or FIRST_LOAD_DAYS back - to the lake's newest day,
    at most MAX_DAYS_PER_RUN days."""
    from .models import LargeCashDay

    if latest is None:
        return None
    last = LargeCashDay.objects.order_by("-day").values_list("day", flat=True).first()
    if last is None:
        start = latest - datetime.timedelta(days=FIRST_LOAD_DAYS - 1)
    else:
        start = min(last, latest) - datetime.timedelta(days=REREAD_DAYS - 1)
    start = max(start, latest - datetime.timedelta(days=MAX_DAYS_PER_RUN - 1))
    return start, latest


def refresh(loaded_by="refresh", start=None, end=None):
    """Read the days due (or ``start``..``end``) → a report dict."""
    latest = lake_latest_day()
    if start is None or end is None:
        span = days_to_read(latest)
        if span is None:
            return {"read": 0, "lake_latest": None, "detail": "The lake has no "
                    "transactions in the last 45 days."}
        start, end = span
    rows = fetch(start, end)
    saved = save(rows, start, end, loaded_by=loaded_by)
    return {"read": saved, "start": start.isoformat(), "end": end.isoformat(),
            "lake_latest": latest.isoformat() if latest else None}


_LOCK_KEY = "large_cash:refreshing"
_DONE_KEY = "large_cash:refreshed"
_ERROR_KEY = "large_cash:error"


def last_error():
    """Why the last read of the lake failed, or "" - shown on the page so a
    copy that stopped moving says why rather than looking like quiet days."""
    from django.core.cache import cache

    try:
        return cache.get(_ERROR_KEY) or ""
    except Exception:  # noqa: BLE001
        return ""


def forget_recent():
    from django.core.cache import cache

    try:
        cache.delete(_DONE_KEY)
    except Exception:  # noqa: BLE001
        pass


def refresh_in_background():
    """Start a refresh behind the page if none ran in the last hour and none is
    running → "started" / "running" / "recent". The page never waits on it."""
    from django.core.cache import cache

    try:
        if cache.get(_DONE_KEY):
            return "recent"
        if not cache.add(_LOCK_KEY, "1", timeout=1800):
            return "running"
    except Exception:  # noqa: BLE001 - no cache: refresh, the lock is moot
        pass

    def run():
        from django.db import connection

        try:
            refresh(loaded_by="auto-refresh")
            cache.set(_DONE_KEY, "1", REFRESH_EVERY_SECONDS)
            cache.delete(_ERROR_KEY)
        except Exception as exc:  # noqa: BLE001
            log.exception("large cash refresh failed")
            try:
                cache.set(_DONE_KEY, "1", 600)   # try again in ten minutes
                cache.set(_ERROR_KEY, f"{type(exc).__name__}: {exc}"[:400], 86400)
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                cache.delete(_LOCK_KEY)
            except Exception:  # noqa: BLE001
                pass
            connection.close()

    threading.Thread(target=run, name="large-cash-refresh", daemon=True).start()
    return "started"
