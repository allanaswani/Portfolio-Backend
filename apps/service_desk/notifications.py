"""Email for the service desk.

Two rules shape all of it.

**Mail the person who is waiting.** A requester hears when their query is
received, answered, resolved and closed — that is the whole point, since the
complaint was never knowing. Handlers hear when something lands in the queue or
is about to breach. Nobody is copied on their own action: an email telling you
what you just did is the kind of mail that teaches people to filter the sender.

**Never let mail break the work.** Every send is wrapped. A ticket saved but
whose confirmation bounced is a ticket that exists; an exception thrown out of
``resolve()`` because Office365 was slow would roll the resolution back, and the
handler would do it twice.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Q
from django.utils import timezone

from .models import DeskSettings
from .rbac import AGENT_GROUP, MANAGER_GROUP
from .worktime import describe

log = logging.getLogger(__name__)

SUBJECT_PREFIX = "[HF Service Desk]"

#: Groups whose members work the queue. Superusers are included separately —
#: at this bank the Strategy team who run this desk are platform superusers, and
#: requiring them to also join a group would mean the queue emails nobody on
#: day one.
HANDLER_GROUPS = [MANAGER_GROUP, AGENT_GROUP, "business_performance"]
MANAGER_ONLY_GROUPS = [MANAGER_GROUP, "business_performance"]


def send(to, subject, body, reply_to=None):
    """Send one message. Returns how many addresses it went to; never raises."""
    addresses = sorted({str(a).strip() for a in (to or []) if a and "@" in str(a)})
    if not addresses:
        return 0
    try:
        EmailMultiAlternatives(
            subject=f"{SUBJECT_PREFIX} {subject}"[:250],
            body=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=addresses,
            reply_to=[reply_to] if reply_to else None,
            connection=get_connection(fail_silently=False),
        ).send()
        return len(addresses)
    except Exception as exc:  # noqa: BLE001 — mail must never break the desk
        log.warning("service desk mail failed (%s): %s", subject, exc)
        return 0


def _emails(predicate, exclude=None):
    try:
        people = (get_user_model().objects
                  .filter(is_active=True).filter(predicate)
                  .exclude(email="").distinct())
        out = {p.email.strip() for p in people if p.email}
    except Exception:  # noqa: BLE001 — never break a transition over a lookup
        return []
    if exclude is not None and getattr(exclude, "email", None):
        out.discard(exclude.email.strip())
    return sorted(out)


def handler_addresses(exclude=None):
    return _emails(Q(groups__name__in=HANDLER_GROUPS) | Q(is_superuser=True), exclude)


def manager_addresses(exclude=None):
    return _emails(Q(groups__name__in=MANAGER_ONLY_GROUPS) | Q(is_superuser=True), exclude)


def requester_addresses(ticket, exclude=None):
    out = set()
    if ticket.requester_email:
        out.add(ticket.requester_email.strip())
    if ticket.raised_by_id and getattr(ticket.raised_by, "email", ""):
        out.add(ticket.raised_by.email.strip())
    if exclude is not None and getattr(exclude, "email", None):
        out.discard(exclude.email.strip())
    return sorted(a for a in out if a)


def _owner_or_queue(ticket, exclude=None):
    """Whoever owns it, or the whole queue while nobody does."""
    if ticket.assigned_to_id and getattr(ticket.assigned_to, "email", ""):
        return [ticket.assigned_to.email]
    return handler_addresses(exclude=exclude)


def _when(moment):
    return timezone.localtime(moment).strftime("%a %d %b, %H:%M") if moment else "—"


def _frontend_url(ticket):
    base = str(getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
    return f"{base}/service-desk/{ticket.reference}" if base else ""


def _header(ticket):
    lines = [
        f"Reference : {ticket.reference}",
        f"Subject   : {ticket.subject}",
        f"Category  : {ticket.category.name if ticket.category else 'Uncategorised'}",
        f"Priority  : {ticket.get_priority_display()}",
        f"Status    : {ticket.get_status_display()}",
    ]
    if ticket.assigned_to_id:
        who = ticket.assigned_to.get_full_name() or ticket.assigned_to.username
        lines.append(f"Handler   : {who}")
    return "\n".join(lines)


def _footer(ticket):
    url = _frontend_url(ticket)
    tail = f"\n\nOpen it here: {url}" if url else ""
    return (
        f"{tail}\n\n--\nHF Group Service Desk\n"
        "Reply on the ticket rather than to this address, so the answer stays "
        "with the query."
    )


def _actor_name(actor):
    if actor is None or not getattr(actor, "is_authenticated", False):
        return "The desk"
    return actor.get_full_name() or actor.username


# ── The messages ─────────────────────────────────────────────────────────────

def ticket_raised(ticket, actor=None):
    """To the requester: we have it. To the queue: it is here."""
    desk = DeskSettings.get()

    if desk.notify_requester:
        promise = (f"\nWe aim to resolve this by {_when(ticket.resolution_due_at)}.\n"
                   if ticket.resolution_due_at else "")
        send(
            requester_addresses(ticket),
            f"{ticket.reference} received — {ticket.subject}",
            f"Your query has been logged with the Strategy & Business "
            f"Performance desk.\n\n{_header(ticket)}\n{promise}\n"
            f"You will be emailed when it is answered and again when it is "
            f"resolved, so you do not have to chase it."
            f"{_footer(ticket)}",
        )

    respond_by = (f"\n\nRespond by {_when(ticket.response_due_at)}."
                  if ticket.response_due_at else "")
    send(
        handler_addresses(exclude=actor),
        f"New: {ticket.reference} — {ticket.subject}",
        f"A query has been raised.\n\n{_header(ticket)}\n\n"
        f"{(ticket.body or '')[:1500]}{respond_by}{_footer(ticket)}",
    )


def ticket_replied(ticket, comment, author=None):
    """A visible message goes to the other side, never back to its author."""
    if comment.is_internal:
        return
    from .rbac import is_handler

    body = (f"{_actor_name(author)} wrote on {ticket.reference}:\n\n"
            f"{comment.body[:2000]}\n\n{_header(ticket)}{_footer(ticket)}")

    if is_handler(author):
        send(requester_addresses(ticket, exclude=author),
             f"{ticket.reference} — a reply from the desk", body)
    else:
        send(_owner_or_queue(ticket, exclude=author),
             f"{ticket.reference} — the requester replied", body)


def ticket_assigned(ticket, actor=None):
    if not DeskSettings.get().notify_assignee:
        return
    if not (ticket.assigned_to_id and getattr(ticket.assigned_to, "email", "")):
        return
    if actor is not None and ticket.assigned_to_id == getattr(actor, "id", None):
        return  # they picked it up themselves; they know
    send(
        [ticket.assigned_to.email],
        f"{ticket.reference} is yours — {ticket.subject}",
        f"This query has been assigned to you.\n\n{_header(ticket)}\n\n"
        f"{(ticket.body or '')[:1500]}\n\n"
        f"Resolve by {_when(ticket.resolution_due_at)}.{_footer(ticket)}",
    )


def ticket_resolved(ticket, actor=None):
    """The email that closes the loop the original complaint is about."""
    days = DeskSettings.get().auto_close_after_days
    send(
        requester_addresses(ticket, exclude=actor),
        f"{ticket.reference} resolved — {ticket.subject}",
        f"The desk has marked your query resolved.\n\n{_header(ticket)}\n\n"
        f"What was done:\n{(ticket.resolution_note or 'No note was left.')[:2000]}\n\n"
        f"If that answers it, confirm and we are done. If it does not, reopen it "
        f"— it comes straight back to us with its full history, so you do not "
        f"start again.\n\n"
        f"If we hear nothing it closes on its own after {days} working day(s), "
        f"recorded as unconfirmed.{_footer(ticket)}",
    )


def ticket_closed(ticket, actor=None):
    if ticket.confirmed_by_requester:
        return  # they closed it themselves; telling them is noise
    send(
        requester_addresses(ticket, exclude=actor),
        f"{ticket.reference} closed — {ticket.subject}",
        f"This query has been closed.\n\n{_header(ticket)}\n\n"
        f"It can still be reopened for {DeskSettings.get().reopen_window_days} "
        f"days if it was not actually answered.{_footer(ticket)}",
    )


def ticket_reopened(ticket, actor=None):
    send(
        _owner_or_queue(ticket, exclude=actor),
        f"{ticket.reference} reopened — {ticket.subject}",
        f"The requester says this was not resolved.\n\n{_header(ticket)}\n\n"
        f"Reopened {ticket.reopened_count} time(s).{_footer(ticket)}",
    )


def breach_warning(ticket, kind="resolution"):
    """Before it breaches, not after. After is a report; before is a chance."""
    due = ticket.response_due_at if kind == "response" else ticket.resolution_due_at
    send(
        _owner_or_queue(ticket),
        f"Due soon: {ticket.reference} — {ticket.subject}",
        f"This query is close to its {kind} target.\n\n{_header(ticket)}\n\n"
        f"Target: {_when(due)}\n"
        f"Open for: {describe(ticket.working_seconds_open())} of working time."
        f"{_footer(ticket)}",
    )


def breached(ticket, kind="resolution"):
    """Managers only.

    A breach is a management fact, not a nag for the handler — who is usually
    already aware, and is the person who could not get to it.
    """
    due = ticket.response_due_at if kind == "response" else ticket.resolution_due_at
    send(
        manager_addresses(),
        f"SLA breached: {ticket.reference} — {ticket.subject}",
        f"This query has passed its {kind} target.\n\n{_header(ticket)}\n\n"
        f"Target was: {_when(due)}\n"
        f"Raised: {_when(ticket.created_at)}\n"
        f"Open for: {describe(ticket.working_seconds_open())} of working time."
        f"{_footer(ticket)}",
    )
