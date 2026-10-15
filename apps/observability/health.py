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
from datetime import timedelta

from django.apps import apps as django_apps
from django.core.cache import cache
from django.db import connections, models, router, transaction
from django.utils import timezone

# Column names that mean "when was this row last refreshed", best first.
#
# ``etl_date_updated`` leads the list because it is the only column in this
# warehouse that the ETL itself stamps - every other candidate is a business
# date that happens to correlate with loading. It was missing, and that alone
# left four of the biggest feeds unmonitored: the picker only falls back to an
# unnamed column when there is exactly ONE date column on the table, and
# ``daily_balance_movement`` has two (``open_date`` and ``etl_date_updated``),
# so it answered "no date column" and the dashboard could not have told anyone
# that feed had stopped.
#
# Thirteen of the fifteen "Undated" tables turned out to be this: a date column
# that was there under a name nobody had written down. The spellings below -
# ``updated``, ``creation_date``, ``trx_date``, ``date_created_at``,
# ``tmstamp`` - are the same handful of ideas as the names already here, and
# ``eom_date`` is a month-end key, which the cadence rules then judge monthly.
#
# Three tables genuinely carry no date column at all - ``ceo_deposit_movement``,
# ``portfolio_rm_revenue`` and ``security_detail`` - and they stay Undated,
# which is the honest answer for them. Row count is all this can watch there.
FRESHNESS_CANDIDATES = [
    "etl_date_updated",
    "updated_at", "last_updated", "modified_at", "updated",
    "created_at", "date_created", "creation_date", "date_created_at",
    "report_date", "snapshot_date", "as_of_date", "business_date", "value_date",
    "run_date", "load_date", "eom_date", "entry_month", "sale_month",
    "date", "txn_date", "transaction_date", "trx_date", "tmstamp",
]

# ── How stale is stale, and why one threshold was not enough ─────────────────
#
# This started as a flat seven days for every table, and that was wrong for
# three of the five tables it then reported as stale:
#
#   ceo_loan_movement_monthly_by_segment   14 days on dates_eom
#   portfolio_rm_deposit_trends            14 days on dates_eom
#   product_mapping                        55 days on date_created
#
# None of those is a stopped ETL. ``dates_eom`` is a month END: on the 15th of
# October the newest value a monthly feed can possibly hold is 30 September,
# which is a fortnight old and perfectly correct - a month-end table is
# ALWAYS between two and five weeks "old" and crosses seven days every month.
# And ``product_mapping`` is reference data whose date column records when a
# product was ADDED, so its age measures how long since the bank launched
# something, not whether the table is loaded.
#
# Three false alarms out of five is worse than no dashboard: it teaches people
# that the red rows are noise, and then the one real stopped feed on the list
# gets ignored with them. So freshness is now judged against the table's own
# cadence.
WARN_DAYS = 2
STALE_DAYS = 7

#: A month-end key. The value IS the period, not the moment of loading, so a
#: monthly table is judged on whether it has the last CLOSED month.
MONTH_END_COLUMNS = {
    "dates_eom", "date_eom", "eom_date", "eom", "month_end", "month_ending",
    "period_end", "reporting_month", "month", "entry_month", "sale_month",
}

#: Grace after a month closes before the feed is late. The warehouse loads a
#: month end within a few days of it; a fortnight means it did not.
MONTH_END_WARN_DAYS = 10
MONTH_END_STALE_DAYS = 20

#: Date columns that record when a row was CREATED rather than refreshed. On a
#: reference table that is a launch date, and ageing it says nothing.
CREATION_COLUMNS = {"date_created", "created_at", "created"}

#: Table-name endings that mean reference data somebody maintains by hand.
REFERENCE_SUFFIXES = ("_mapping", "_mappings", "_lookup", "_types", "_codes",
                      "_categories", "_config", "_settings")


def cadence_of(table, column):
    """``"monthly"``, ``"reference"`` or ``"daily"`` for one table.

    Read off the table and column NAMES, because there is no schedule
    metadata anywhere in this estate to read instead. That is a guess, but a
    far better one than assuming every feed is daily - and the cadence is put
    on the row so the dashboard can show which rule it applied rather than
    just a colour.
    """
    name = (column or "").strip().lower()
    if name in MONTH_END_COLUMNS:
        return "monthly"
    table = (table or "").strip().lower()
    if name in CREATION_COLUMNS and table.endswith(REFERENCE_SUFFIXES):
        return "reference"
    return "daily"

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


# ── Why a refused connection is not a missing table ──────────────────────────
# On 2026-10-06 the warehouse hit its connection ceiling, and this page reported
# all thirty-two tables as "No table, 0 rows, error". Every one of them was
# present and full. The scan had never looked: each probe failed at the connect
# step, and the row still carried the initial exists=False, rows=0 — values that
# were never measured but read on screen, and in the export, as findings.
#
# Two rules come out of that, and they are the whole of this change:
#   1. A failure to CONNECT is a fact about the database, not about the table.
#      It is reported once, and the remaining tables are not probed - thirty-two
#      identical connect failures are thirty-two timeouts for one answer.
#   2. Anything the scan did not measure is reported as blank, never as zero or
#      false. "I could not look" and "I looked and it is not there" are
#      different findings and must not render identically.
CONNECTION_FAILURE_MARKERS = (
    "too many clients",            # max_connections exhausted - what we hit
    "could not connect",
    "connection failed",
    "connection refused",
    "server closed the connection",
    "terminating connection",
    "no connection to the server",
    "connection already closed",
    "the connection is closed",
    "could not translate host name",
    "no pg_hba.conf entry",
    "password authentication failed",
    "database system is starting up",
    "database system is shutting down",
)

# Statuses that mean the scan measured nothing. Their rows must not claim a row
# count or an existence verdict.
UNMEASURED_STATUSES = ("unreachable", "skipped", "error")


def _is_unreachable(exc):
    """Did this fail because the DATABASE could not be reached?

    Distinguished from a table-level failure, which is worth reporting per
    table. A statement timeout is deliberately NOT in here: that connection was
    fine, the query was too slow, and the next table may well answer.
    """
    from django.db import InterfaceError

    if isinstance(exc, InterfaceError):
        # Django's InterfaceError is a sibling of DatabaseError, not a subclass,
        # and means the connection object itself is unusable.
        return True
    text = str(exc).lower()
    return any(m in text for m in CONNECTION_FAILURE_MARKERS)


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


def _classify(exists, rows, age_days, cadence="daily"):
    if not exists:
        return "missing"
    if rows == 0:
        return "empty"
    if cadence == "reference":
        # Reference data that somebody maintains by hand. Its date column is a
        # launch date, so age carries no information about whether the table is
        # loaded - and colouring it red month after month is how a dashboard
        # trains people to stop reading it. Reported as what it is.
        return "reference"
    if age_days is None:
        return "unknown"
    warn, stale = ((MONTH_END_WARN_DAYS, MONTH_END_STALE_DAYS)
                   if cadence == "monthly" else (WARN_DAYS, STALE_DAYS))
    if cadence == "monthly":
        # Judged on the last CLOSED month, not on today. A month-end table is
        # inherently two to five weeks old and must not go red for it.
        age_days = max(0, age_days - _days_since_month_closed())
    if age_days >= stale:
        return "stale"
    if age_days >= warn:
        return "warning"
    return "ok"


def _days_since_month_closed(today=None):
    """How long ago the most recent month end was.

    The baseline a monthly feed is measured from: on 15 October the newest
    month end that exists is 30 September, so a monthly table holding it is
    nought days late, not fifteen.
    """
    today = today or timezone.localdate()
    return today.day


def _row(model, table, alias, field, exists, count, is_estimate, last_seen,
         age_days, error, status=None):
    """One table's verdict, in the shape the dashboard reads."""
    measured = (status or "") not in UNMEASURED_STATUSES
    return {
        "app_label": model._meta.app_label,
        "model": model._meta.model_name,
        "label": str(model._meta.verbose_name).title(),
        "table": table,
        "database": alias,
        # Blank, not zero. A row the scan could not read has no row count and
        # no existence verdict, and printing 0/false there is how a full
        # warehouse came to look like an empty one.
        "exists": exists if measured else None,
        "rows": count if measured else None,
        "rows_are_estimate": is_estimate if measured else False,
        "freshness_column": field.name if field else None,
        "last_seen": last_seen,
        "age_days": age_days,
        # Which rule was applied, so the dashboard can say "monthly feed, one
        # month behind" instead of a bare colour - and so a reader can tell a
        # cadence this guessed wrong from a feed that really has stopped.
        "cadence": cadence_of(table, field.name if field else ""),
        # An explicit status wins; otherwise classify on what was measured.
        # Note that an error alone no longer forces "error": a table whose rows
        # were counted but whose date column was too slow to read is present
        # and populated, and calling that broken data would alert the team
        # about four healthy tables, every day, forever. It is "unknown" —
        # freshness could not be judged — with the reason attached.
        "status": status or _classify(
            exists, count, age_days,
            cadence_of(table, field.name if field else "")),
        "error": error,
    }


def warehouse_models(app_label=None):
    """The unmanaged models — the tables the ETLs are responsible for.

    One model per PHYSICAL table. Four warehouse tables are mapped twice
    (``hf_customer``, ``accounts``, ``accounts_history`` by both portfolio and
    gceo_dashboard; ``employee_table`` by gceo_dashboard and staff_management),
    and without this the dashboard listed each of them twice, counted 36 tables
    where there are 32, and probed every duplicate a second time for an answer
    it already had. Two rows saying the same table is stale reads as two
    problems.

    Where a table is mapped twice the mapping with a usable date column wins —
    it is the one that can answer "when was this last refreshed", which is the
    question the page exists for. Failing that, the more complete mapping.
    """
    out = [m for m in django_apps.get_models() if not m._meta.managed]
    if app_label:
        out = [m for m in out if m._meta.app_label == app_label]

    best = {}
    for model in out:
        table = model._meta.db_table
        current = best.get(table)
        if current is None or _mapping_rank(model) > _mapping_rank(current):
            best[table] = model

    chosen = list(best.values())
    chosen.sort(key=lambda m: (m._meta.app_label, m._meta.db_table))
    return chosen


def _mapping_rank(model):
    """How good a stand-in this model is for its table. Higher wins."""
    try:
        has_date = _freshness_field(model) is not None
    except Exception:  # noqa: BLE001
        has_date = False
    return (1 if has_date else 0, len(model._meta.fields))


# How long a pushed report stays trustworthy. A service that stops pushing has
# stopped telling us anything, which is itself worth showing — silence must not
# read as health.
EXTERNAL_STALE_MINUTES = 180


def external_rows(app_label=None):
    """Tables another system reported, in the same shape as a scanned one."""
    from .models import ExternalTableHealth

    qs = ExternalTableHealth.objects.all()
    if app_label:
        qs = qs.filter(source__iexact=app_label)

    cutoff = timezone.now() - timedelta(minutes=EXTERNAL_STALE_MINUTES)
    out = []
    for row in qs:
        stale_report = row.reported_at < cutoff
        out.append({
            "app_label": row.source,
            "model": row.table,
            "label": row.label or row.table,
            "table": row.table,
            "database": f"{row.source} (reported)",
            "exists": row.status != "missing",
            "rows": row.rows,
            "rows_are_estimate": row.rows_are_estimate,
            "freshness_column": None,
            "last_seen": row.last_seen,
            "age_days": row.age_days,
            # A report nobody has refreshed for hours is not evidence of health.
            "status": "unknown" if stale_report else row.status,
            "error": (
                f"Last reported {row.reported_at:%Y-%m-%d %H:%M} — the service "
                "has stopped pushing."
                if stale_report else row.error
            ),
            "external": True,
            "source": row.source,
            "reported_at": row.reported_at,
        })
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
        # Guarded because the cache backend is a table in the very database this
        # scan exists to report on: when that database refuses connections, the
        # cache read raises, and an unguarded read would take the page down with
        # the exact finding the reader came for.
        try:
            cached = cache.get(cache_key)
        except Exception:  # noqa: BLE001
            cached = None
        if cached is not None:
            return cached

    now = timezone.now()
    today = now.date()
    started = time.monotonic()
    rows = []
    # alias -> why it cannot be reached. Filled on the first connect failure so
    # the rest of its tables are answered from it instead of re-failing.
    dead = {}

    # Deduplicated AFTER the app filter, so narrowing to one app still picks
    # that app's mapping of a shared table rather than dropping the table.
    for model in warehouse_models(app_label=app_label):
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
        # "could not read the table at all" and "read it fine, could not date
        # it" are different findings and must not share a verdict. Only the
        # first is an error.
        unreadable = False

        # This database has already refused us. Answer from that, rather than
        # queue another connect attempt behind the same closed door.
        if alias in dead:
            rows.append(_row(model, table, alias, field, None, None, False,
                             None, None, dead[alias], "unreachable"))
            continue

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
            if _is_unreachable(exc):
                # Not this table's fault, and not this table's verdict.
                dead[alias] = error
                rows.append(_row(model, table, alias, field, None, None, False,
                                 None, None, error, "unreachable"))
                continue
            unreadable = True

        age_days = None
        if last_seen is not None:
            try:
                seen_date = last_seen.date() if hasattr(last_seen, "date") else last_seen
                age_days = (today - seen_date).days
            except Exception:  # noqa: BLE001 — a column that is not really a date
                age_days = None

        rows.append(_row(model, table, alias, field, exists, count, is_estimate,
                         last_seen, age_days, error,
                         status="error" if unreadable else None))

    # Tables in OTHER systems, as those systems last reported them. Customer
    # 360 owns its own database, so it pushes rather than being scanned — but
    # it belongs on the same screen, because "is the data there" is one question
    # across the estate, not one per system.
    # Also guarded: these rows live in a local table, so losing the database
    # loses them too — and the scanned verdicts above are still worth showing.
    try:
        rows += external_rows(app_label=app_label)
    except Exception:  # noqa: BLE001
        pass

    rows.sort(key=lambda r: (
        {"unreachable": -1, "missing": 0, "error": 1, "empty": 2, "stale": 3,
         "warning": 4, "unknown": 5, "skipped": 6, "ok": 7,
         # Reference data is not a problem and not a feed. It sorts last,
         # after healthy, because nobody needs to look at it.
         "reference": 8}.get(r["status"], 9),
        r["table"],
    ))
    # A scan that could not reach the database is not an answer worth keeping
    # for five minutes: the ceiling clears in seconds and the reader would still
    # be staring at the failure, pressing Refresh, getting the cache back.
    if not dead:
        try:
            cache.set(cache_key, rows, CACHE_SECONDS)
        except Exception:  # noqa: BLE001 — a cache must never break the scan
            pass
    return rows


def summarise(rows):
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    # Reference data counts as healthy: it is loaded, it is just not a feed,
    # so leaving it out would make the headline "54 healthy of 80" when
    # nothing is wrong with the rest.
    healthy = (counts.get("ok", 0) + counts.get("warning", 0)
               + counts.get("reference", 0))
    # Tables whose state was never established. Counting them as problems would
    # report a database outage as thirty-two broken ETLs and send the team
    # looking in the wrong place.
    not_judged = (counts.get("unknown", 0) + counts.get("skipped", 0)
                  + counts.get("unreachable", 0))
    unreachable = counts.get("unreachable", 0)
    return {
        "tables": len(rows),
        "healthy": healthy,
        "problems": len(rows) - healthy - not_judged,
        "by_status": counts,
        # None where a row was never measured, so this is a sum of what we know.
        "total_rows": sum(r["rows"] or 0 for r in rows),
        "unreachable": unreachable,
        "database_unreachable": bool(unreachable),
        # The reason, once, for the banner. Every unreachable row carries the
        # same one.
        "unreachable_reason": next(
            (r["error"] for r in rows if r["status"] == "unreachable"), ""),
    }
