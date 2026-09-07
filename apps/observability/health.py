"""Is the data actually there? — the check behind the Data Health dashboard.

The warehouse mirrors are ``managed = False`` models: the ETLs fill them and
this application only reads them. When an ETL stops, nothing in the app
complains — the page just renders zeros, and the only way anyone finds out is a
user asking why a chart is empty. That has happened more than once (the loan
trend charts were empty for weeks because the loan branch of the Trino ETL was
commented out).

So: for every unmanaged model, report whether its table exists, roughly how
many rows it holds, and how recently it was refreshed.

Row counts come from PostgreSQL's own ``reltuples`` planner statistic, not
``COUNT(*)`` — thirty-six sequential counts over warehouse-sized tables would
make the dashboard slower than the problem it reports. The estimate is labelled
as one, and a zero estimate is confirmed with a ``LIMIT 1`` probe so "empty" is
never guessed (``reltuples`` is -1 on a table that has never been analysed).
"""

import time

from django.apps import apps as django_apps
from django.core.cache import cache
from django.db import connections, models, router, transaction
from django.utils import timezone

# Column names that mean "when was this row last refreshed", best first.
FRESHNESS_CANDIDATES = [
    "updated_at", "last_updated", "modified_at", "created_at", "date_created",
    "report_date", "snapshot_date", "as_of_date", "business_date", "value_date",
    "run_date", "load_date", "date", "txn_date", "transaction_date",
]

# How stale is stale. A table refreshed less often than daily is judged on the
# looser threshold; there is no schedule metadata to read, so the dashboard
# reports the age and lets the reader judge, with these only colouring the row.
WARN_DAYS = 2
STALE_DAYS = 7

# ── Why this scan is on a leash ───────────────────────────────────────────────
# The first version of this had no timeouts and hung until gunicorn killed the
# worker, which the proxy then reported as a 500 — with no exception anywhere,
# because there never was one. The cause is MAX(date_column): on a warehouse
# table of tens of millions of rows with no index on that column, PostgreSQL
# reads the whole table. Thirty-six of those is not a page load, it is a batch
# job.
#
# So every probe is capped by the server, and the scan as a whole is capped
# too. A table that cannot answer within its slice is reported as unmeasured —
# which is a true statement about that table, and infinitely more useful than a
# page that never loads.
PROBE_TIMEOUT_MS = 2500      # per statement, enforced by PostgreSQL
TOTAL_BUDGET_SECONDS = 25    # for the whole scan, enforced here
CACHE_KEY = "observability:data-health"
CACHE_SECONDS = 300          # the answer changes on ETL timescales, not per click


def _freshness_field(model):
    """The best date/datetime column on the model, or None."""
    by_name = {
        f.name: f for f in model._meta.fields
        if isinstance(f, (models.DateField, models.DateTimeField))
    }
    for name in FRESHNESS_CANDIDATES:
        if name in by_name:
            return by_name[name]
    # No conventional name — fall back to the only date column, if there is one.
    if len(by_name) == 1:
        return next(iter(by_name.values()))
    return None


def _estimate_rows(cursor, table):
    """(exists, estimated_rows, is_estimate)."""
    cursor.execute("SELECT to_regclass(%s)", [table])
    row = cursor.fetchone()
    if not row or row[0] is None:
        return False, 0, False

    cursor.execute(
        "SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(%s)", [table]
    )
    found = cursor.fetchone()
    estimate = int(found[0]) if found and found[0] is not None else -1

    if estimate > 0:
        return True, estimate, True

    # reltuples is 0 or -1: either genuinely empty, or never analysed. One cheap
    # probe settles it, and a small table can then be counted exactly.
    cursor.execute(f'SELECT 1 FROM "{table}" LIMIT 1')
    if cursor.fetchone() is None:
        return True, 0, False
    cursor.execute(f'SELECT COUNT(*) FROM (SELECT 1 FROM "{table}" LIMIT 100000) s')
    counted = cursor.fetchone()[0]
    return True, counted, counted >= 100000


def _last_seen(cursor, table, column):
    """MAX(column), or None if it could not be answered in time.

    Deliberately raw SQL on the same cursor the row count used, so it inherits
    that cursor's statement_timeout. Through the ORM it would open its own
    connection with no cap, which is exactly how this scan came to hang.
    """
    cursor.execute(f'SELECT MAX("{column}") FROM "{table}"')
    row = cursor.fetchone()
    return row[0] if row else None


def _classify(exists, rows, age_days):
    if not exists:
        return "missing"
    if rows == 0:
        return "empty"
    if age_days is None:
        return "unknown"
    if age_days >= STALE_DAYS:
        return "stale"
    if age_days >= WARN_DAYS:
        return "warning"
    return "ok"


def _row(model, table, alias, field, exists, count, is_estimate, last_seen,
         age_days, error, status=None):
    """One table's verdict, in the shape the dashboard reads."""
    return {
        "app_label": model._meta.app_label,
        "model": model._meta.model_name,
        "label": str(model._meta.verbose_name).title(),
        "table": table,
        "database": alias,
        "exists": exists,
        "rows": count,
        "rows_are_estimate": is_estimate,
        "freshness_column": field.name if field else None,
        "last_seen": last_seen,
        "age_days": age_days,
        "status": status or ("error" if error else _classify(exists, count, age_days)),
        "error": error,
    }


def warehouse_models():
    """The unmanaged models — the tables the ETLs are responsible for."""
    out = [m for m in django_apps.get_models() if not m._meta.managed]
    out.sort(key=lambda m: (m._meta.app_label, m._meta.db_table))
    return out


def table_health(app_label=None, use_cache=True):
    """One row per warehouse table: existence, size, freshness, verdict.

    Never raises, and never runs unbounded. A scan that reports on thirty-six
    tables must not be all-or-nothing — the one table that cannot be read is
    usually the very thing the reader opened this page to find out about.

    Cached: this probes every warehouse table, and what it reports changes on
    ETL timescales, not per page load. Pass ``use_cache=False`` to force a
    fresh scan (the Refresh button does).
    """
    cache_key = f"{CACHE_KEY}:{app_label or 'all'}"
    if use_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    now = timezone.now()
    today = now.date()
    started = time.monotonic()
    rows = []

    for model in warehouse_models():
        if app_label and model._meta.app_label != app_label:
            continue
        table = model._meta.db_table
        try:
            alias = router.db_for_read(model) or "default"
        except Exception:  # noqa: BLE001 — a router that objects to this model
            alias = "default"
        try:
            field = _freshness_field(model)
        except Exception:  # noqa: BLE001
            field = None

        exists, count, is_estimate = False, 0, False
        last_seen = None
        error = ""

        # Out of time: report the rest honestly rather than keep the reader
        # waiting for a page that will be killed before it arrives.
        if time.monotonic() - started > TOTAL_BUDGET_SECONDS:
            rows.append(_row(model, table, alias, field, False, 0, False, None, None,
                             "not probed — the scan ran out of time", "skipped"))
            continue

        # Every table is probed inside its own guard, and the guard catches
        # Exception rather than DatabaseError: Django's InterfaceError is a
        # SIBLING of DatabaseError, not a subclass, so a dropped connection
        # escaped it. A table that cannot be read is a row that SAYS so.
        try:
            # SET LOCAL only takes effect inside a transaction — outside one
            # PostgreSQL ignores it with a warning, which would leave the cap
            # silently absent, which is how this hung in the first place. The
            # transaction also reverts the setting for us, so no stray
            # statement_timeout leaks onto a pooled connection.
            with transaction.atomic(using=alias), connections[alias].cursor() as cursor:
                # PostgreSQL enforces the cap. Without it a MAX() over an
                # unindexed column on a large table runs until the worker is
                # killed, and the page 500s with no exception to show for it.
                cursor.execute(f"SET LOCAL statement_timeout = {PROBE_TIMEOUT_MS}")
                exists, count, is_estimate = _estimate_rows(cursor, table)

                if exists and count and field is not None:
                    # Freshness is its own probe: losing it should cost the row
                    # its age, not its whole entry.
                    try:
                        last_seen = _last_seen(cursor, table, field.column)
                    except Exception as exc:  # noqa: BLE001
                        error = (
                            f"{field.name}: {type(exc).__name__}: {exc}"
                            if "timeout" not in str(exc).lower()
                            else f"{field.name}: too slow to measure "
                                 f"(no index on this column)"
                        )[:300]
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"[:300]

        age_days = None
        if last_seen is not None:
            try:
                seen_date = last_seen.date() if hasattr(last_seen, "date") else last_seen
                age_days = (today - seen_date).days
            except Exception:  # noqa: BLE001 — a column that is not really a date
                age_days = None

        rows.append(_row(model, table, alias, field, exists, count, is_estimate,
                         last_seen, age_days, error))

    rows.sort(key=lambda r: (
        {"missing": 0, "error": 1, "empty": 2, "stale": 3, "warning": 4,
         "unknown": 5, "skipped": 6, "ok": 7}.get(r["status"], 9),
        r["table"],
    ))
    try:
        cache.set(cache_key, rows, CACHE_SECONDS)
    except Exception:  # noqa: BLE001 — a cache backend must never break the scan
        pass
    return rows


def summarise(rows):
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    healthy = counts.get("ok", 0) + counts.get("warning", 0)
    return {
        "tables": len(rows),
        "healthy": healthy,
        "problems": len(rows) - healthy - counts.get("unknown", 0),
        "by_status": counts,
        "total_rows": sum(r["rows"] for r in rows),
    }
