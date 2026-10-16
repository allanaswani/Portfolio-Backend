"""Active Customers and Digital Adoption, from the lake's own feed.

``delta.gold_db.active_channels`` is the bank's existing answer to both
questions: a row per customer per product per transaction type per month,
carrying ``cust_status`` and ``digital_cust_status``. These cards were being
reconstructed from raw transactions instead, which is how they ended up slow
enough to time out - the work had already been done upstream.

Where this reads from, and why
──────────────────────────────
The lake, on a schedule, into ``sc_customer_monthly_activity``; the card then
reads Postgres. NOT the lake on the card path: the scorecard is rebuilt on
every page view, and a heavy read there runs past the worker timeout and
hands the browser a dead connection, which renders as a blank page. That
mistake has already been made once on these two lines.

What "active" means here
────────────────────────
Attendance. A customer appears in the feed for a month because they
transacted in it, and 349,500 of the lake's 350,323 rows say "Active
Customer" - so the flag is not a status so much as a record of having turned
up. The card asks for "two months active", which is attendance in a month AND
in the month before it, and that is what :func:`two_month_active` counts.

Digital is per ROW, not per customer: an MPESA credit is digital and the
interest posting beside it is not. So a customer is digitally active in a
month when ANY of their rows that month is. The aggregation is done in Trino,
which turns 350,000 lake rows into 134,000 before any of it crosses the wire.

What this feed does not have
────────────────────────────
At the time of writing it holds Jan, Feb, Mar and Apr 2026 and nothing else -
no 2025 at all. The cards state their target as a rate on the person's own
PRIOR-YEAR count ("increase by 20%"), and that base cannot come from a feed
that does not go back a year. Until it does, the target has to come from the
workbook, which carries the year's figure per person. The card says which of
the two it used, and :func:`coverage` reports what the feed actually spans so
nobody has to guess whether a blank line is a gap or a stale load.
"""

from __future__ import annotations

import datetime

#: Aggregated in the lake, deliberately. The raw table is a row per customer
#: per product per transaction type; this is a row per customer per month,
#: which is what the card needs and a third of the volume.
TRINO_QUERY = """
    SELECT trx_month,
           CAST(cust_id AS BIGINT) AS cust_id,
           MAX(CASE WHEN cust_status = 'Active Customer'
                    THEN 1 ELSE 0 END) AS active,
           MAX(CASE WHEN digital_cust_status = 'Active Customer'
                    THEN 1 ELSE 0 END) AS digital_active
    FROM delta.gold_db.active_channels
    WHERE cust_id IS NOT NULL
    GROUP BY trx_month, CAST(cust_id AS BIGINT)
"""

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def parse_month(value):
    """``"Apr-26"`` → ``date(2026, 4, 1)``, or None.

    The lake holds the month as text. Two-digit years are read as 2000s,
    which is safe for a transaction feed that starts this century and ends
    before the next one.
    """
    text = str(value or "").strip().lower().replace("/", "-").replace(" ", "-")
    if "-" not in text:
        return None
    name, _, year = text.partition("-")
    month = _MONTHS.get(name[:3])
    if month is None or not year.isdigit():
        return None
    year = int(year)
    if year < 100:
        year += 2000
    try:
        return datetime.date(year, month, 1)
    except ValueError:
        return None


def fetch_from_trino():
    """Run the aggregate against the lake → list of dicts.

    Credentials come from the environment, never from this file:
    ``TRINO_HOST``, ``TRINO_PORT``, ``TRINO_USER``, ``TRINO_PASSWORD``.
    The same shape as ``cost_ingest.fetch_from_trino``, including the quote
    stripping - ``docker --env-file`` takes quotes literally, so a password
    written with them reaches Trino with them and comes back 401.
    """
    import os

    import trino
    import urllib3
    from trino.auth import BasicAuthentication

    # The lake's certificate is not one this host trusts, so the connection
    # passes verify=False. urllib3 warns once per REQUEST and the client
    # polls for results, so one load would print the warning a dozen times
    # and bury the figures. Silenced for this call only.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    host = os.environ.get("TRINO_HOST")
    if not host:
        raise RuntimeError(
            "TRINO_HOST is not set, so the lake cannot be reached. The "
            "TRINO_* variables go in the environment file.")

    user = (os.environ.get("TRINO_USER") or "").strip().strip("'\"")
    password = (os.environ.get("TRINO_PASSWORD") or "").strip().strip("'\"")
    if not user or not password:
        raise RuntimeError(
            "TRINO_USER or TRINO_PASSWORD is not set, so the lake cannot be "
            "reached. Both go in the environment file alongside TRINO_HOST.")

    connection = trino.dbapi.connect(
        host=host,
        port=int(os.environ.get("TRINO_PORT", "8443")),
        user=user,
        auth=BasicAuthentication(user, password),
        catalog=os.environ.get("TRINO_CATALOG", "delta"),
        http_scheme=os.environ.get("TRINO_HTTP_SCHEME", "https"),
        verify=False,
    )
    cursor = connection.cursor()
    cursor.execute(TRINO_QUERY)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def plan(rows):
    """Lake rows → ``(entries, report)``. Writes nothing.

    A row whose month cannot be parsed is reported rather than dropped
    quietly: a month label the lake changes the shape of would otherwise
    silently empty these two lines.
    """
    entries, report = [], {"read": len(rows), "unreadable_month": [],
                           "months": set(), "customers": set()}

    for row in rows:
        month = parse_month(row.get("trx_month"))
        if month is None:
            label = str(row.get("trx_month"))
            if label not in report["unreadable_month"]:
                report["unreadable_month"].append(label)
            continue
        cust_id = row.get("cust_id")
        if cust_id in (None, ""):
            continue
        entries.append({
            "cust_id": int(cust_id),
            "month": month,
            "active": bool(row.get("active")),
            "digital_active": bool(row.get("digital_active")),
        })
        report["months"].add(month)
        report["customers"].add(int(cust_id))

    report["months"] = sorted(report["months"])
    report["customers"] = len(report["customers"])
    report["to_write"] = len(entries)
    return entries, report


def save(entries, batch=5000):
    """Write the mirror → how many rows were written.

    Upserted on (cust_id, month), so a reload corrects rather than stacks.
    Only the months present in ``entries`` are touched: a partial load must
    not delete the months it did not fetch.
    """
    from django.db import transaction

    from .models import CustomerMonthlyActivity

    written = 0
    with transaction.atomic():
        for start in range(0, len(entries), batch):
            chunk = entries[start:start + batch]
            CustomerMonthlyActivity.objects.bulk_create(
                [CustomerMonthlyActivity(**item) for item in chunk],
                update_conflicts=True,
                update_fields=["active", "digital_active", "loaded_at"],
                unique_fields=["cust_id", "month"])
            written += len(chunk)
    return written


def coverage():
    """What the mirror actually spans → a dict.

    So a blank line can be told apart from a stale load without anybody
    guessing. ``complete_pairs`` is what the card can actually answer, since
    "two months active" needs a month AND the one before it.
    """
    from django.db.models import Count, Max, Min

    from .models import CustomerMonthlyActivity

    rows = CustomerMonthlyActivity.objects.all()
    span = rows.aggregate(first=Min("month"), last=Max("month"),
                          rows=Count("id"))
    months = sorted(rows.values_list("month", flat=True).distinct())
    pairs = [m for m in months
             if _previous(m) in set(months)]
    return {
        "rows": span["rows"] or 0,
        "first_month": span["first"], "last_month": span["last"],
        "months": months,
        "complete_pairs": pairs,
        "latest_pair": pairs[-1] if pairs else None,
    }


def _previous(month):
    """The first of the month before this one."""
    return (month.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)


def two_month_active(sales_code, year, digital=False):
    """Customers on this RM's book active in TWO consecutive months.

    → ``{year: (count, as_at)}`` for every year the mirror covers, or
    ``{"error": reason}`` when it cannot be read.

    The same return shape the previous reader used, so the card is unchanged
    by the swap. The latest qualifying pair WITHIN each year is reported,
    which is how a figure read in the first days of a month does not collapse
    to nought because the new month has barely started.
    """
    from django.db import connection, transaction

    from services import portfolio_service as svc

    flag = "AND a.digital_active AND b.digital_active" if digital else ""

    sql = f"""
        WITH book AS ({svc.RM_BOOK}
        )
        SELECT EXTRACT(YEAR FROM a.month)::int AS yr,
               a.month,
               COUNT(DISTINCT a.cust_id)       AS active_both_months
        FROM sc_customer_monthly_activity a
        JOIN sc_customer_monthly_activity b
          ON b.cust_id = a.cust_id
         AND b.month = (a.month - INTERVAL '1 month')::date
        JOIN book k ON k.cust_id = a.cust_id
        WHERE a.active AND b.active
          {flag}
        GROUP BY 1, 2
        ORDER BY 1, 2 DESC
    """

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [sales_code.strip()])
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 - a missing mirror must not
        # blank a card, and the reason tells whoever reads it whether the
        # feed has never been loaded or something else went wrong.
        text = str(exc).lower()
        if "does not exist" in text or "undefined" in text:
            return {"error": ("the customer activity mirror has not been "
                              "created yet - run migrate, then "
                              "load_active_channels")}
        return {"error": "the customer activity feed could not be read"}

    out = {}
    for yr, month, count in rows:
        # The first row for each year is its latest pair, because the query
        # orders the months descending within the year.
        if yr in out:
            continue
        last_day = (month.replace(day=28) + datetime.timedelta(days=4))
        last_day = last_day.replace(day=1) - datetime.timedelta(days=1)
        out[int(yr)] = (int(count or 0), last_day)
    return out
