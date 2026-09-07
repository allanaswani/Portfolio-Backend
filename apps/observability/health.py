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

from django.apps import apps as django_apps
from django.db import DatabaseError, connections, models, router
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


def warehouse_models():
    """The unmanaged models — the tables the ETLs are responsible for."""
    out = [m for m in django_apps.get_models() if not m._meta.managed]
    out.sort(key=lambda m: (m._meta.app_label, m._meta.db_table))
    return out


def table_health(app_label=None):
    """One row per warehouse table: existence, size, freshness, verdict."""
    now = timezone.now()
    today = now.date()
    rows = []

    for model in warehouse_models():
        if app_label and model._meta.app_label != app_label:
            continue
        table = model._meta.db_table
        alias = router.db_for_read(model) or "default"
        field = _freshness_field(model)

        exists, count, is_estimate = False, 0, False
        last_seen = None
        error = ""
        try:
            with connections[alias].cursor() as cursor:
                exists, count, is_estimate = _estimate_rows(cursor, table)
            if exists and count and field is not None:
                last_seen = (
                    model.objects.using(alias)
                    .exclude(**{f"{field.name}__isnull": True})
                    .aggregate(m=models.Max(field.name))["m"]
                )
        except DatabaseError as exc:
            error = str(exc)[:200]

        age_days = None
        if last_seen is not None:
            seen_date = last_seen.date() if hasattr(last_seen, "date") else last_seen
            age_days = (today - seen_date).days

        rows.append({
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
            "status": "error" if error else _classify(exists, count, age_days),
            "error": error,
        })

    rows.sort(key=lambda r: (
        {"missing": 0, "error": 1, "empty": 2, "stale": 3,
         "warning": 4, "unknown": 5, "ok": 6}.get(r["status"], 9),
        r["table"],
    ))
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
