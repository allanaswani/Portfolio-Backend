"""Aggregations over :class:`~apps.observability.models.RequestMetric`.

Percentiles are computed by PostgreSQL (``percentile_cont``) rather than by
pulling durations into Python — the whole point of a p95 is that it is taken
over every request, and a day of traffic is not something to fetch into a web
process.
"""

from datetime import timedelta

from django.db import connections
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from .models import AppHeartbeat, RequestMetric

METRIC_DB = "default"


def window(hours=24):
    now = timezone.now()
    return now - timedelta(hours=hours), now


def percentiles(since, until, path=None):
    """p50 / p95 / p99 of ``duration_ms`` over the window, in milliseconds."""
    sql = """
        SELECT
            percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms),
            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms),
            percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)
        FROM observability_request_metric
        WHERE created_at >= %s AND created_at <= %s
    """
    params = [since, until]
    if path:
        sql += " AND path = %s"
        params.append(path)
    with connections[METRIC_DB].cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone() or (None, None, None)

    def _ms(value):
        return round(value) if value is not None else None

    return {"p50": _ms(row[0]), "p95": _ms(row[1]), "p99": _ms(row[2])}


def overview(hours=24):
    since, until = window(hours)
    qs = RequestMetric.objects.using(METRIC_DB).filter(
        created_at__gte=since, created_at__lte=until
    )
    totals = qs.aggregate(
        requests=Count("id"),
        errors=Count("id", filter=Q(is_error=True)),
        client_errors=Count("id", filter=Q(status_code__gte=400, status_code__lt=500)),
        avg_ms=Avg("duration_ms"),
        slowest=Max("duration_ms"),
        users=Count("username", distinct=True, filter=~Q(username="")),
    )
    requests = totals["requests"] or 0
    errors = totals["errors"] or 0
    return {
        "window_hours": hours,
        "since": since,
        "until": until,
        "requests": requests,
        "errors": errors,
        "client_errors": totals["client_errors"] or 0,
        "error_rate": round(errors / requests * 100, 2) if requests else 0.0,
        "avg_ms": round(totals["avg_ms"]) if totals["avg_ms"] is not None else None,
        "slowest_ms": totals["slowest"],
        "active_users": totals["users"] or 0,
        "throughput_per_min": round(requests / (hours * 60), 2) if hours else 0,
        **percentiles(since, until),
        "uptime": uptime(hours=hours),
    }


def timeseries(hours=24, buckets=48):
    """Latency and traffic per time bucket, for the Grafana-style graphs.

    The bucket is computed by flooring the epoch, which works on every
    PostgreSQL version — ``date_bin`` would need 14+.
    """
    since, until = window(hours)
    buckets = max(6, min(288, buckets))
    seconds = max(60, int(hours * 3600 / buckets))

    sql = """
        SELECT
            to_timestamp(floor(extract(epoch FROM created_at) / %s) * %s) AS bucket,
            COUNT(*)                                        AS requests,
            COUNT(*) FILTER (WHERE is_error)                AS errors,
            COUNT(*) FILTER (WHERE status_code >= 400
                             AND status_code < 500)         AS client_errors,
            AVG(duration_ms)                                AS avg_ms,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
        FROM observability_request_metric
        WHERE created_at >= %s AND created_at <= %s
        GROUP BY bucket
        ORDER BY bucket
    """
    with connections[METRIC_DB].cursor() as cursor:
        cursor.execute(sql, [seconds, seconds, since, until])
        rows = cursor.fetchall()

    return [
        {
            "t": row[0],
            "requests": row[1],
            "errors": row[2],
            "client_errors": row[3],
            "avg_ms": round(row[4]) if row[4] is not None else None,
            "p50": round(row[5]) if row[5] is not None else None,
            "p95": round(row[6]) if row[6] is not None else None,
            "error_rate": round(row[2] / row[1] * 100, 2) if row[1] else 0.0,
        }
        for row in rows
    ]


def endpoints(hours=24, limit=40):
    """Slowest endpoints by p95 — where the loading speed actually goes."""
    since, until = window(hours)
    sql = """
        SELECT path,
               COUNT(*)                          AS requests,
               AVG(duration_ms)                  AS avg_ms,
               MAX(duration_ms)                  AS max_ms,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
               COUNT(*) FILTER (WHERE is_error)  AS errors
        FROM observability_request_metric
        WHERE created_at >= %s AND created_at <= %s
        GROUP BY path
        ORDER BY p95 DESC NULLS LAST
        LIMIT %s
    """
    with connections[METRIC_DB].cursor() as cursor:
        cursor.execute(sql, [since, until, limit])
        rows = cursor.fetchall()
    return [
        {
            "path": row[0],
            "requests": row[1],
            "avg_ms": round(row[2]) if row[2] is not None else None,
            "max_ms": row[3],
            "p95_ms": round(row[4]) if row[4] is not None else None,
            "errors": row[5],
            "error_rate": round(row[5] / row[1] * 100, 2) if row[1] else 0.0,
        }
        for row in rows
    ]


def status_codes(hours=24):
    since, until = window(hours)
    rows = (
        RequestMetric.objects.using(METRIC_DB)
        .filter(created_at__gte=since, created_at__lte=until)
        .values("status_code").annotate(count=Count("id")).order_by("status_code")
    )
    return [{"status_code": r["status_code"], "count": r["count"]} for r in rows]


def recent_errors(hours=24, limit=100):
    since, until = window(hours)
    rows = (
        RequestMetric.objects.using(METRIC_DB)
        .filter(created_at__gte=since, created_at__lte=until, status_code__gte=400)
        .order_by("-created_at")[:limit]
    )
    return [
        {
            "path": r.path,
            "method": r.method,
            "status_code": r.status_code,
            "duration_ms": r.duration_ms,
            "username": r.username or None,
            "when": r.created_at,
        }
        for r in rows
    ]


def uptime(hours=24):
    """Uptime from heartbeat coverage, or ``measured: False`` when there are none.

    A minute with a heartbeat is a minute the process was alive. Without the
    cron entry that writes them there is nothing to measure, and the dashboard
    says so instead of reporting a number nobody can stand behind. Request
    traffic is NOT a substitute: a quiet night has no requests and no downtime.
    """
    since, until = window(hours)
    expected = max(1, int((until - since).total_seconds() // 60))
    observed = (
        AppHeartbeat.objects.using(METRIC_DB)
        .filter(minute__gte=since, minute__lte=until).count()
    )
    if observed == 0:
        return {
            "measured": False,
            "percent": None,
            "expected_minutes": expected,
            "observed_minutes": 0,
            "downtime_minutes": None,
            "note": "No heartbeats recorded — schedule 'manage.py record_heartbeat' every minute.",
        }
    percent = min(100.0, round(observed / expected * 100, 3))
    return {
        "measured": True,
        "percent": percent,
        "expected_minutes": expected,
        "observed_minutes": observed,
        "downtime_minutes": max(0, expected - observed),
        "note": "",
    }


def uptime_by_day(days=14):
    """One uptime figure per day, for the availability strip."""
    now = timezone.now()
    days = max(1, min(90, days))
    since = now - timedelta(days=days)
    sql = """
        SELECT date_trunc('day', minute) AS day, COUNT(*)
        FROM observability_heartbeat
        WHERE minute >= %s
        GROUP BY day ORDER BY day
    """
    with connections[METRIC_DB].cursor() as cursor:
        cursor.execute(sql, [since])
        seen = {row[0].date(): row[1] for row in cursor.fetchall()}

    out = []
    for offset in range(days, -1, -1):
        day = (now - timedelta(days=offset)).date()
        minutes = seen.get(day, 0)
        # Today is only as long as it has been so far.
        expected = 1440 if day != now.date() else max(1, now.hour * 60 + now.minute)
        out.append({
            "day": day,
            "minutes": minutes,
            "expected": expected,
            "percent": min(100.0, round(minutes / expected * 100, 2)) if minutes else 0.0,
            "measured": minutes > 0,
        })
    return out
