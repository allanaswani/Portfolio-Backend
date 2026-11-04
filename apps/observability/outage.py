"""Telling somebody when the database itself is down.

Every other alert reads its recipients and its state from the database, so on
3 Nov 2026, with PostgreSQL stopped for half an hour, nothing could be sent:
the job that should have said so crashed on connecting, and the first anyone
heard from it was a "recovered" mail afterwards.

So this keeps what it needs in a small file beside the job: the people to tell,
copied there on every healthy run, and how long the database has been refusing.
One refused run is a blip - a restart, or a moment under load - and is not worth
a mail, so it mails on the second, ten minutes later.
"""

import json
import logging
import os
import tempfile

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Refused runs in a row before anybody is told.
RUNS_BEFORE_MAIL = 2
SUBJECT_PREFIX = "[HFCB Portfolio]"


def _path():
    return getattr(settings, "ALERT_STATE_FILE", "") or os.path.join(
        tempfile.gettempdir(), "hfcb_alert_state.json")


def _read():
    try:
        with open(_path(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _write(state):
    try:
        with open(_path(), "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError:
        logger.exception("could not write %s", _path())


def recipients():
    """Who to tell when the recipient list cannot be read."""
    return _read().get("recipients") or list(
        getattr(settings, "ALERT_FALLBACK_EMAILS", []) or [])


def mail(subject, body):
    """Send without touching the database → how many it reached."""
    to = recipients()
    if not to:
        logger.error("nobody to tell: %s", subject)
        return 0
    try:
        send_mail(subject=f"{SUBJECT_PREFIX} {subject}", message=body,
                  from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                  recipient_list=to, fail_silently=False)
    except Exception:  # noqa: BLE001 - the job must end cleanly either way
        logger.exception("could not send: %s", subject)
        return 0
    return len(to)


def database_refused(error):
    """A run could not connect. Returns the alert sent, or None."""
    state = _read()
    now = timezone.now().isoformat()
    state["refused_runs"] = state.get("refused_runs", 0) + 1
    state.setdefault("refused_since", now)
    subject = None
    if state["refused_runs"] >= RUNS_BEFORE_MAIL and not state.get("mailed"):
        subject = "ACTION NEEDED: the database is down"
        body = (
            "What happened:\n"
            f"PostgreSQL on the warehouse host has refused connections since "
            f"{state['refused_since']}.\n\n"
            "Impact:\n"
            "Nobody can log in and no page that reads data will load. ETLs "
            "writing to it are failing.\n\n"
            "What the system did:\n"
            "Nothing it can do starts a database. The application reconnects "
            "by itself as soon as PostgreSQL is back. This job checks again "
            "every ten minutes and will tell you when it is.\n\n"
            "What you need to do, on the database host:\n"
            "1. systemctl status postgresql-12 --no-pager | head -15\n"
            "2. df -h /data\n"
            '3. tail -40 "$(ls -t /data/db_data/pgsql/12/data/data/log/*.log '
            '| head -1)"\n'
            "If /data is full, free space outside the data directory first. "
            "Do not delete anything in pg_wal or base. Then:\n"
            "4. systemctl start postgresql-12\n\n"
            f"What the connection said:\n{str(error).strip()[:600]}\n")
        if mail(subject, body):
            state["mailed"] = True
    _write(state)
    return subject if state.get("mailed") and subject else None


def database_answered(current_recipients):
    """A run connected. Remembers who to tell, and closes any outage it mailed
    about. Returns the alert sent, or None."""
    state = _read()
    was_mailed = state.get("mailed")
    since = state.get("refused_since")
    state = {"recipients": sorted(set(current_recipients))
             or state.get("recipients", [])}
    _write(state)
    if not was_mailed:
        return None
    subject = "Resolved: the database is back"
    mail(subject,
         "What happened:\n"
         f"PostgreSQL refused connections from {since} until this check, at "
         f"{timezone.now().isoformat()}.\n\n"
         "What you need to do:\nNothing further for the outage itself. Check "
         "why it stopped, if you have not already, so it does not recur.\n")
    return subject
