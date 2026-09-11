"""Deciding when something is worth an email, and sending it.

The hard part of alerting is not sending mail — it is not sending it. An alert
that arrives every five minutes while a table stays empty is an alert people
filter into a folder, and then the one that mattered is in that folder too.

So every check here reduces to a **state** for a **key**, and mail goes out only
when that state CHANGES. "The warehouse feed went empty" is news; "the warehouse
feed is still empty" is not. Recovery is news too, which is why a check that
clears is mailed once as well — otherwise nobody ever learns it is over.

Four kinds, each with its own recipient list (:class:`AlertRecipient`):

* ``downtime``          — this app or a monitored service stopped answering,
                          or server errors crossed a threshold.
* ``data_health``       — a warehouse table went missing, empty, or newly stale.
* ``sensitive_change``  — a deletion, a role change, a rate change.
* ``daily_digest``      — one summary a day, sent regardless of state.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import AlertRecipient, AlertState, MonitoredService, ServiceProbe

# An error rate above this, over a window with enough traffic to mean anything,
# is treated as an incident. Below MIN_REQUESTS the percentage is noise — two
# failures out of three requests at 3am is not an outage.
ERROR_RATE_PERCENT = 5.0
ERROR_RATE_MIN_REQUESTS = 50

# Consecutive failed probes before a service is called down. One timeout is a
# blip; three in a row is the service.
PROBE_FAILURES_BEFORE_DOWN = 3

SUBJECT_PREFIX = "[HF Portfolio]"


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


# ── Sending ──────────────────────────────────────────────────────────────────

def send(kind, subject, body):
    """Mail one alert to everybody subscribed to ``kind``.

    Returns the number of recipients. Never raises: an alerting system that
    takes the cron job down with it when the mail server hiccups is worse than
    one that misses a message.
    """
    recipients = AlertRecipient.for_kind(kind)
    if not recipients:
        return 0
    try:
        send_mail(
            subject=f"{SUBJECT_PREFIX} {subject}",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=False,
        )
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
            detail = (
                f"{service.name} has failed its last {len(recent)} checks.\n"
                f"URL: {service.health_url}\n"
                f"Last result: {reason}\n"
            )
            if transition(key, "down", detail):
                sent.append(("downtime", f"{service.name} is DOWN", detail))
        elif recent[0].ok and recent[0].duration_ms > service.slow_ms:
            detail = (
                f"{service.name} answered in {recent[0].duration_ms} ms, over its "
                f"{service.slow_ms} ms threshold.\nURL: {service.health_url}\n"
            )
            if transition(key, "slow", detail):
                sent.append(("downtime", f"{service.name} is responding slowly", detail))
        elif recent[0].ok:
            if transition(key, "ok", f"{service.name} is answering normally."):
                sent.append((
                    "downtime", f"{service.name} has RECOVERED",
                    f"{service.name} is answering normally again "
                    f"({recent[0].duration_ms} ms).\n",
                ))
    return sent


def check_error_rate(hours=1):
    """Server errors over the last hour, once there is enough traffic to judge."""
    from . import metrics

    data = metrics.overview(hours=hours)
    requests = data["requests"]
    rate = data["error_rate"]

    if requests < ERROR_RATE_MIN_REQUESTS:
        # Too little traffic for a percentage to mean anything. Deliberately
        # NOT recorded as "ok" — that would mail a recovery every quiet night.
        return []

    key = "error_rate"
    if rate >= ERROR_RATE_PERCENT:
        detail = (
            f"{rate}% of the last {requests} requests failed with a server error "
            f"({data['errors']} of them), over the last {hours}h.\n"
        )
        if transition(key, "high", detail):
            return [("downtime", f"Error rate is {rate}%", detail)]
    elif transition(key, "ok", f"Error rate back to {rate}%."):
        return [("downtime", "Error rate has recovered",
                 f"Server errors are back to {rate}% of {requests} requests.\n")]
    return []


def check_data_health():
    """Warehouse tables that went missing, empty or newly stale.

    One mail per table, keyed on the table, so a feed that breaks is reported
    once and its recovery is reported once — rather than the whole list being
    re-sent because one row in it changed.
    """
    from . import health

    sent = []
    for row in health.table_health():
        key = f"table:{row['table']}"
        status = row["status"]

        if status in ("missing", "empty", "stale", "error"):
            detail = (
                f"Table: {row['table']} ({row['label']}, {row['app_label']})\n"
                f"Status: {status}\n"
                f"Rows: {row['rows']:,}\n"
                f"Last refreshed: {row['last_seen'] or 'never'}\n"
                + (f"Error: {row['error']}\n" if row["error"] else "")
                + "\nAn empty or missing warehouse table means the ETL that fills "
                  "it has stopped. The pages that read it will render zeros "
                  "rather than an error.\n"
            )
            if transition(key, status, detail):
                sent.append((
                    "data_health",
                    f"{row['table']} is {status}",
                    detail,
                ))
        elif status in ("ok", "warning"):
            if transition(key, "ok", f"{row['table']} is loading normally."):
                sent.append((
                    "data_health",
                    f"{row['table']} has RECOVERED",
                    f"{row['table']} is loading again — {row['rows']:,} rows, last "
                    f"refreshed {row['last_seen']}.\n",
                ))
    return sent


# Which changes are worth waking somebody for. Everything else is in the audit
# trail already; a mail per edit would be unreadable and so unread.
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


def run_all(sensitive_minutes=10):
    """Every immediate check. Returns the alerts that were sent."""
    alerts = []
    alerts += check_services()
    alerts += check_error_rate()
    alerts += check_data_health()
    alerts += check_sensitive_changes(minutes=sensitive_minutes)

    delivered = []
    for kind, subject, body in alerts:
        count = send(kind, subject, body)
        delivered.append({"kind": kind, "subject": subject, "recipients": count})
    return delivered
