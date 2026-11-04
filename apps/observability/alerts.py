"""Deciding when something needs a person, and telling them what to do.

The rule is that **a mail means somebody has to act**. An alert people learn to
ignore is worse than none, because the one that mattered goes unread with it.

* Every immediate mail says what happened, what it affects, what the system
  already did, and exactly what to do next - see :func:`incident`.
* Whatever cleared by itself, or needs no decision, goes to the morning digest
  instead: a slow response, a burst of errors that stopped, a table that came
  back, deletions and role changes.
* A "resolved" mail goes only to close something that was mailed. "Server errors
  are back to 2.15%" told the reader about a problem they had never been told
  of, and asked nothing of them.

Every check still reduces to a **state** for a **key**, and mails only when that
state CHANGES, so a persisting problem mails once.

The kinds, each with its own recipient list (:class:`AlertRecipient`):

* ``downtime``          — a monitored service is down, or server errors have
                          stayed high across two checks.
* ``data_health``       — warehouse tables newly missing, empty or stale, in one
                          mail, or the warehouse refusing connections.
* ``sensitive_change``  — deletions and sensitive edits, in the daily digest.
* ``daily_digest``      — one summary a day, sent regardless of state.

The database being down is :mod:`apps.observability.outage`, since none of this
can read its recipients then.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import AlertRecipient, AlertState, MonitoredService, ServiceProbe

# An error rate above this, over a window with enough traffic to mean anything,
# is treated as an incident. Below MIN_REQUESTS the percentage is noise — two
# failures out of three requests at 3am is not an outage.
ERROR_RATE_PERCENT = 5.0
ERROR_RATE_MIN_REQUESTS = 50
# The last 15 minutes, not the last hour: an hour's figure goes on reporting a
# problem for most of an hour after it has stopped.
ERROR_RATE_WINDOW_HOURS = 0.25
# Automatically-fixed problems waiting for the digest are AlertState rows under
# this prefix. See manage.py host_alert.
SELF_FIXED_PREFIX = "selffixed:"

# Consecutive failed probes before a service is called down. One timeout is a
# blip; three in a row is the service.
PROBE_FAILURES_BEFORE_DOWN = 3

# The bank is HFCB - the same prefix family as "[HFCB Design]" and "[HFCB
# Service Desk]". "HF" alone is the old name.
SUBJECT_PREFIX = "[HFCB Portfolio]"


# ── State ────────────────────────────────────────────────────────────────────

def transition(key, state, detail=""):
    """Record ``key``'s state. Returns True only if it CHANGED.

    The caller mails on True and stays silent on False, which is the whole
    mechanism that stops a persisting problem mailing on every run.
    """
    now = timezone.now()
    with transaction.atomic():
        row, created = AlertState.objects.select_for_update().get_or_create(
            key=key, defaults={"state": state, "detail": detail, "since": now},
        )
        if created:
            # A brand-new key that is already healthy is not an event — it is
            # the first time anybody looked.
            changed = state != "ok"
            if changed:
                row.last_notified_at = now
                row.save(update_fields=["last_notified_at"])
            return changed

        if row.state == state:
            row.detail = detail
            row.save(update_fields=["detail"])
            return False

        row.state = state
        row.detail = detail
        row.since = now
        row.last_notified_at = now
        row.save(update_fields=["state", "detail", "since", "last_notified_at"])
        return True


def previous_state(key):
    """The state ``key`` is in now, or None if it has never been looked at."""
    return AlertState.objects.filter(key=key).values_list("state", flat=True).first()


# ── Writing ──────────────────────────────────────────────────────────────────

def incident(what, impact, done, action, evidence=""):
    """An alert's body: the same four questions in the same order, every time,
    so the reader can tell at a glance whether it is theirs to do."""
    parts = [f"What happened:\n{what}", f"Impact:\n{impact}",
             f"What the system did:\n{done}",
             f"What you need to do:\n{action}"]
    if evidence:
        parts.append(f"Details:\n{evidence}")
    return "\n\n".join(p.strip() for p in parts) + "\n"


def as_html(body):
    """Plain alert text as the mail client shows it. A line ending in a colon
    that opens a paragraph is that paragraph's heading."""
    import html as html_module

    paragraphs = []
    for block in body.strip().split("\n\n"):
        lines = [html_module.escape(line) for line in block.split("\n")]
        if len(lines) > 1 and lines[0].endswith(":"):
            lines[0] = f"<b>{lines[0]}</b>"
        paragraphs.append(f'<p style="margin:0 0 14px">{"<br/>".join(lines)}</p>')
    return ('<!DOCTYPE html><html><body style="font-family:Calibri,Arial,'
            f'sans-serif;font-size:14px;color:#1F2D33">{"".join(paragraphs)}'
            '</body></html>')


# ── Sending ──────────────────────────────────────────────────────────────────

def send(kind, subject, body, html=None, attachments=()):
    """Mail one alert to everybody subscribed to ``kind``, which may be a list
    of kinds whose subscribers all get it, each once.

    ``body`` is the plain-text part. ``html`` is the part a mail client shows,
    made from ``body`` when not given. ``attachments`` is
    ``[(filename, bytes, mimetype)]``.

    Returns the number of recipients. Never raises: an alerting system that
    takes the cron job down with it when the mail server hiccups is worse than
    one that misses a message.
    """
    kinds = [kind] if isinstance(kind, str) else list(kind)
    recipients = sorted({a for k in kinds for a in AlertRecipient.for_kind(k)})
    if not recipients:
        return 0
    try:
        message = EmailMultiAlternatives(
            subject=f"{SUBJECT_PREFIX} {subject}",
            body=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=recipients,
        )
        message.attach_alternative(html or as_html(body), "text/html")
        for filename, content, mimetype in attachments:
            message.attach(filename, content, mimetype)
        message.send(fail_silently=False)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("Could not send %s alert", kind)
        return 0
    return len(recipients)


# ── Checks ───────────────────────────────────────────────────────────────────

def check_services():
    """Each monitored service: down, degraded or ok, from its recent probes."""
    sent = []
    for service in MonitoredService.objects.filter(is_active=True).exclude(health_url=""):
        recent = list(
            ServiceProbe.objects.filter(service=service)
            .order_by("-created_at")[:PROBE_FAILURES_BEFORE_DOWN]
        )
        if not recent:
            continue

        key = f"service:{service.slug}"
        if len(recent) >= PROBE_FAILURES_BEFORE_DOWN and not any(p.ok for p in recent):
            latest = recent[0]
            reason = latest.error or f"HTTP {latest.status_code}"
            detail = incident(
                f"{service.name} has failed its last {len(recent)} checks, two "
                f"minutes apart.",
                f"People cannot use {service.name}.",
                "Only checked. It keeps checking and will tell you when it "
                "answers again.",
                f"Open {service.health_url} to confirm, then look at that "
                f"service's container on its host: docker ps, and docker logs "
                f"on the one that is stopped or restarting.",
                f"Last result: {reason}",
            )
            if transition(key, "down", detail):
                sent.append(("downtime", f"ACTION NEEDED: {service.name} is DOWN",
                             detail))
        elif recent[0].ok and recent[0].duration_ms > service.slow_ms:
            # Slow but answering asks nothing of anybody.
            transition(key, "slow",
                       f"{service.name} answered in {recent[0].duration_ms} ms, "
                       f"over its {service.slow_ms} ms threshold.")
        elif recent[0].ok:
            was = previous_state(key)
            if transition(key, "ok", f"{service.name} is answering normally.") \
                    and was == "down":
                sent.append((
                    "downtime", f"Resolved: {service.name} has RECOVERED",
                    f"{service.name} is answering normally again "
                    f"({recent[0].duration_ms} ms). Nothing further is needed.\n",
                ))
    return sent


def failing_endpoints(hours, limit=5):
    """The paths behind the errors → [(method path, errors)], most first."""
    from django.db.models import Count

    from .metrics import METRIC_DB, window
    from .models import RequestMetric

    since, until = window(hours)
    rows = (RequestMetric.objects.using(METRIC_DB)
            .filter(created_at__gte=since, created_at__lte=until, is_error=True)
            .values("method", "path").annotate(n=Count("id")).order_by("-n")[:limit])
    return [(f"{r['method']} {r['path']}", r["n"]) for r in rows]


def check_error_rate(hours=ERROR_RATE_WINDOW_HOURS):
    """Server errors NOW, once there is enough traffic to judge.

    A first high reading is held back, because a burst can be gone by the next
    check ten minutes later and need nobody. Two in a row is a problem that is
    not fixing itself, and that mail names the failing pages and what to run. A
    burst that clears before then is in the digest and mails nobody.
    """
    from . import metrics

    data = metrics.overview(hours=hours)
    requests = data["requests"]
    rate = data["error_rate"]

    if requests < ERROR_RATE_MIN_REQUESTS:
        # Too little traffic for a percentage to mean anything. Deliberately
        # NOT recorded as "ok" — that would mail a recovery every quiet night.
        return []

    key = "error_rate"
    minutes = round(hours * 60)
    was = previous_state(key)
    if rate >= ERROR_RATE_PERCENT:
        if was not in ("rising", "high"):
            transition(key, "rising", f"{rate}% of {requests} requests in the "
                                      f"last {minutes} minutes failed.")
            return []
        endpoints = failing_endpoints(hours)
        detail = incident(
            f"{rate}% of the last {requests} requests failed with a server "
            f"error ({data['errors']} of them in {minutes} minutes), and it has "
            f"not cleared since the last check.",
            "People are seeing errors on the pages listed below.",
            "Only checked. Errors like this do not clear until their cause is "
            "fixed. It will tell you when they stop.",
            "On the host, read what is failing:\n"
            "docker logs --since 30m hf-backend 2>&1 | grep -E "
            "'Error|Traceback' | tail -40\n"
            "If it says connection refused, it is the database: "
            "systemctl status postgresql-12, and df -h /data.",
            "Failing most:\n" + "\n".join(f"{n}  {path}" for path, n in endpoints),
        )
        if transition(key, "high", detail):
            return [("downtime", f"ACTION NEEDED: {rate}% of requests are failing",
                     detail)]
    elif transition(key, "ok", f"Error rate back to {rate}%.") and was == "high":
        return [("downtime", "Resolved: server errors have stopped",
                 f"Server errors are down to {rate}% of the last {requests} "
                 f"requests. Nothing further is needed.\n")]
    return []


def _rows_text(count):
    """A row count for a mail, or plain words when there is not one.

    ``None`` means the scan never got a count - formatting it as 0 would report
    an unmeasured table as an empty one.
    """
    return f"{count:,}" if isinstance(count, int) else "not measured"


def check_data_health():
    """Warehouse tables that went missing, empty or newly stale.

    One mail per table, keyed on the table, so a feed that breaks is reported
    once and its recovery is reported once — rather than the whole list being
    re-sent because one row in it changed.
    """
    from . import health

    sent = []
    rows = health.table_health()

    # The database itself could not be reached, so NOTHING was learned about any
    # table. Alerting per table here would mail thirty-two false "the ETL has
    # stopped" warnings and then, on recovery, thirty-two "has RECOVERED" ones.
    # It is one fault with one owner: send that, and leave every table's stored
    # state untouched because no new evidence was gathered about it.
    unreachable = [r for r in rows if r["status"] == "unreachable"]
    if unreachable:
        detail = (
            "The data-health scan could not open a connection to the warehouse, "
            "so none of the %d tables were checked.\n\n"
            "What the database said:\n%s\n\n"
            "This is NOT evidence that an ETL has stopped. Until it is cleared, "
            "nothing is being monitored.\n"
            % (len(unreachable), unreachable[0]["error"] or "no detail given")
        )
        if transition("database:warehouse", "unreachable", detail):
            sent.append(("data_health",
                         "ACTION NEEDED: the warehouse database is refusing "
                         "connections", detail))
        return sent

    was_down = previous_state("database:warehouse") == "unreachable"
    if transition("database:warehouse", "ok",
                  "The warehouse is answering again.") and was_down:
        sent.append(("data_health",
                     "Resolved: the warehouse database is reachable again",
                     "Connections are being accepted and the data-health scan is "
                     "running normally again. Nothing further is needed.\n"))

    newly_broken = []
    for row in rows:
        key = (f"table:{row['source']}:{row['table']}" if row.get("external")
               else f"table:{row['table']}")
        status = row["status"]

        if status in ("missing", "empty", "stale", "error"):
            if row.get("external"):
                # A check another system ran on itself (Customer 360's warehouse
                # tables, source dates, deployment settings). Its own detail says
                # what is wrong; the ETL wording below would be false for, say,
                # "LAN access".
                system = (MonitoredService.objects.filter(slug=row["source"])
                          .values_list("name", flat=True).first() or row["source"])
                detail = (
                    f"System: {system}\n"
                    f"Check: {row['label']}\n"
                    f"Status: {status}\n"
                    + (f"Current to: {row['last_seen']}\n" if row.get("last_seen") else "")
                    + (f"Detail: {row['error']}\n" if row["error"] else "")
                    + f"\nReported by {system} itself. Its admin Data health page "
                      "has the full picture.\n"
                )
                line = f"{system}: {row['label']} is {status}"
            else:
                detail = (
                    f"Table: {row['table']} ({row['label']}, {row['app_label']})\n"
                    f"Status: {status}\n"
                    f"Rows: {_rows_text(row['rows'])}\n"
                    f"Last refreshed: {row['last_seen'] or 'never'}\n"
                    + (f"Error: {row['error']}\n" if row["error"] else "")
                    + "\nAn empty or missing warehouse table means the ETL that fills "
                      "it has stopped. The pages that read it will render zeros "
                      "rather than an error.\n"
                )
                line = f"{row['table']} is {status}"
            if transition(key, status, detail):
                newly_broken.append((line, detail))
        elif status in ("ok", "warning"):
            # A table coming back needs nobody; it stops appearing in the digest.
            transition(key, "ok", f"{row['table']} is loading normally.")

    # One mail for one run, however many tables: an ETL that stops takes several
    # with it, and that is one thing to fix, not several mails to read.
    if len(newly_broken) == 1:
        sent.append(("data_health", f"ACTION NEEDED: {newly_broken[0][0]}",
                     newly_broken[0][1]))
    elif newly_broken:
        details = "\n".join(f"-- {line} --\n{detail}"
                            for line, detail in newly_broken)
        sent.append(("data_health",
                     f"ACTION NEEDED: {len(newly_broken)} data feeds need attention",
                     details))
    return sent


# Which changes the daily digest lists. Everything else is in the audit trail
# already; a list of every edit would be unreadable and so unread.
SENSITIVE_MODELS = {
    "dsrsalescode": "DSR seller code",
    "tradetariff": "Trade tariff rate",
    "tradeproduct": "Trade product pricing",
    "teamleaderbranch": "Team leader assignment",
    "dsrroleteamleader": "Role team-leader mapping",
    "alertrecipient": "Alert recipient",
    "monitoredservice": "Monitored service",
    "profile": "User profile",
}


def check_sensitive_changes(minutes=10):
    """Deletions anywhere, plus any change to a sensitive record.

    Read from the history tables the audit trail already reads, so this needs no
    second record of anything.
    """
    from . import audit

    since = timezone.now() - timedelta(minutes=minutes)
    rows = audit.feed(since=since, limit=200, with_changes=True)

    notable = []
    for row in rows:
        is_deletion = row["action"] == "deleted"
        sensitive = row["model"] in SENSITIVE_MODELS
        if is_deletion or sensitive:
            notable.append(row)
    if not notable:
        return []

    lines = []
    for row in notable:
        who = row["username"] or "system/job"
        what = SENSITIVE_MODELS.get(row["model"], row["model_label"])
        line = f"- {who} {row['action']} {what}: {row['object_label'] or row['object_id']}"
        for change in (row["changes"] or [])[:5]:
            line += f"\n    {change['field']}: {change['old']} -> {change['new']}"
        lines.append(line)

    body = (
        f"{len(notable)} sensitive change(s) in the last {minutes} minutes:\n\n"
        + "\n".join(lines)
        + "\n\nThe full trail is on Administration -> Audit Trail.\n"
    )
    # Not state-based: each batch is a distinct set of events, and a change that
    # already happened does not "recover".
    return [("sensitive_change",
             f"{len(notable)} sensitive change(s)", body)]


def check_external_reports():
    """A system that has stopped pushing its health.

    A pushed report older than ``health.EXTERNAL_STALE_MINUTES`` is shown as
    "unknown" on the Data health page, which is honest but silent: nothing mails
    when Customer 360's push stops, and its rows would then say nothing about
    anything. Silence must not read as health, so it is an alert of its own.
    """
    from django.db.models import Max

    from . import health
    from .models import ExternalTableHealth

    sent = []
    cutoff = timezone.now() - timedelta(minutes=health.EXTERNAL_STALE_MINUTES)
    for row in ExternalTableHealth.objects.values("source").annotate(latest=Max("reported_at")):
        source, latest = row["source"], row["latest"]
        name = (MonitoredService.objects.filter(slug=source).values_list("name", flat=True).first()
                or source)
        key = f"push:{source}"
        if latest < cutoff:
            detail = (
                f"{name} last reported its health at {latest:%Y-%m-%d %H:%M}.\n"
                f"Nothing has arrived for over {health.EXTERNAL_STALE_MINUTES // 60} hours, "
                "so its tables, source dates and settings are no longer being watched.\n\n"
                "On its server, check the hourly push job (crontab -l) and run it by hand:\n"
                "  docker exec c360-backend python manage.py push_monitoring\n"
            )
            if transition(key, "silent", detail):
                sent.append(("data_health",
                             f"ACTION NEEDED: {name} has stopped reporting its health",
                             detail))
        else:
            was = previous_state(key)
            if transition(key, "ok", f"{name} is reporting normally.") and was == "silent":
                sent.append(("data_health",
                             f"Resolved: {name} is reporting its health again",
                             f"{name} reported at {latest:%Y-%m-%d %H:%M}. Nothing "
                             f"further is needed.\n"))
    return sent


def run_all(sensitive_minutes=10):
    """Every immediate check. Returns the alerts that were sent."""
    alerts = []
    alerts += check_services()
    alerts += check_error_rate()
    alerts += check_data_health()
    alerts += check_external_reports()
    # Deletions and role changes are in the daily digest, which also goes to the
    # sensitive-change subscribers: they ask nothing of anybody the moment they
    # happen. ``sensitive_minutes`` stays so the existing cron line still works.

    delivered = []
    for kind, subject, body in alerts:
        count = send(kind, subject, body)
        delivered.append({"kind": kind, "subject": subject, "recipients": count})
    return delivered
