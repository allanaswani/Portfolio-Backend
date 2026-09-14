"""Every transition a ticket can make, and the timing each one records.

All state changes go through here rather than through ``ticket.save()`` in a
view. There is one reason: each transition has to write its ``TicketEvent`` with
the elapsed and working time since the previous step, and a rule that lives in
four views is a rule that is right in three of them.

Each function returns the ticket, and is safe to call twice — taking a ticket
that is already yours, or resolving one already resolved, is a no-op rather than
a second event and a second email.
"""

from django.db import transaction
from django.utils import timezone

from .models import DeskSettings, Ticket, TicketComment, TicketEvent
from .worktime import business_seconds


def _label(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return "system / job"
    return user.get_full_name() or user.username


def record(ticket, kind, actor=None, note="", from_status="", to_status="", at=None):
    """Append one step to the timeline, timed from the step before it.

    The gap is measured from the previous event rather than from the ticket's
    creation, so the timeline reads as durations per step — which is what
    "it has been sitting for a week" needs in order to be answered with where.
    """
    at = at or timezone.now()
    previous = ticket.events.order_by("-at", "-id").first()
    since = previous.at if previous else ticket.created_at
    wall, working = 0, 0
    if since:
        wall = max(0, int((at - since).total_seconds()))
        working = business_seconds(since, at, ticket.week)
    return TicketEvent.objects.create(
        ticket=ticket, kind=kind, actor=actor if getattr(actor, "pk", None) else None,
        actor_label=_label(actor), note=note or "",
        from_status=from_status or "", to_status=to_status or "",
        at=at, seconds_since_previous=wall, working_seconds_since_previous=working,
    )


def _touch_first_response(ticket, actor, now):
    """The first time the desk says anything to the requester.

    Measured on the first handler action that the requester can see — not on
    assignment. Being put in somebody's queue is not an answer, and counting it
    as one is how a response-time figure becomes flattering and useless.
    """
    from .rbac import is_handler

    if ticket.first_response_at or not is_handler(actor):
        return False
    ticket.first_response_at = now
    return True


@transaction.atomic
def create(*, subject, body="", category=None, priority=Ticket.PRIORITY_NORMAL,
           raised_by=None, on_behalf_of="", requester_email="",
           requester_department="", requester_branch="", actor=None):
    """Raise a ticket. The clock starts here."""
    ticket = Ticket(
        subject=subject.strip(), body=body or "", category=category,
        priority=priority, raised_by=raised_by,
        on_behalf_of=on_behalf_of or "",
        requester_email=(requester_email or getattr(raised_by, "email", "") or "").strip(),
        requester_department=requester_department or "",
        requester_branch=requester_branch or "",
    )
    ticket.save()
    record(ticket, TicketEvent.KIND_CREATED, actor=actor or raised_by,
           to_status=ticket.status,
           note=f"Raised on behalf of {on_behalf_of}" if on_behalf_of else "")
    return ticket


@transaction.atomic
def assign(ticket, to_user, actor=None, note=""):
    """Give the ticket an owner. Idempotent."""
    if ticket.assigned_to_id == getattr(to_user, "id", None):
        return ticket
    now = timezone.now()
    was = ticket.status
    ticket.assigned_to = to_user
    if ticket.assigned_at is None:
        ticket.assigned_at = now
    if ticket.status == Ticket.STATUS_NEW:
        ticket.status = Ticket.STATUS_ASSIGNED
    ticket.save()
    record(ticket, TicketEvent.KIND_ASSIGNED, actor=actor, at=now,
           from_status=was, to_status=ticket.status,
           note=note or f"Assigned to {_label(to_user)}")
    return ticket


@transaction.atomic
def set_status(ticket, status, actor=None, note=""):
    """Move a ticket between the working statuses.

    Resolution, closure and reopening have their own functions — they carry
    consequences (emails, confirmation, the SLA verdict) that must not be
    reachable by patching a status field.
    """
    allowed = {Ticket.STATUS_ASSIGNED, Ticket.STATUS_IN_PROGRESS, Ticket.STATUS_ON_HOLD}
    if status not in allowed or ticket.status == status:
        return ticket
    now = timezone.now()
    was = ticket.status

    # Coming off hold: bank the waiting time. The desk is measured on its own
    # delay, not on how long the requester took to reply.
    if was in Ticket.PAUSED_STATUSES and ticket.on_hold_since:
        ticket.on_hold_seconds += business_seconds(ticket.on_hold_since, now, ticket.week)
        ticket.on_hold_since = None
    if status in Ticket.PAUSED_STATUSES:
        ticket.on_hold_since = now

    if status == Ticket.STATUS_IN_PROGRESS and ticket.started_at is None:
        ticket.started_at = now

    ticket.status = status
    _touch_first_response(ticket, actor, now)
    ticket.save()
    record(ticket, TicketEvent.KIND_STATUS, actor=actor, at=now,
           from_status=was, to_status=status, note=note)
    return ticket


@transaction.atomic
def comment(ticket, author, body, is_internal=False):
    """Add a message. A visible one counts as the desk's first response."""
    now = timezone.now()
    row = TicketComment.objects.create(
        ticket=ticket, author=author, body=body, is_internal=bool(is_internal))
    # An internal note is not an answer to the requester, so it must not stop
    # the response clock — that would let the desk meet its SLA by talking to
    # itself.
    if not is_internal and _touch_first_response(ticket, author, now):
        ticket.save(update_fields=["first_response_at", "updated_at"])
    record(ticket, TicketEvent.KIND_COMMENT, actor=author, at=now,
           note=("[internal] " if is_internal else "") + body[:500])
    return row


@transaction.atomic
def resolve(ticket, actor=None, note=""):
    """The desk says it is answered. The requester has not agreed yet."""
    if ticket.status in (Ticket.STATUS_RESOLVED, *Ticket.CLOSED_STATUSES):
        return ticket
    now = timezone.now()
    was = ticket.status
    if was in Ticket.PAUSED_STATUSES and ticket.on_hold_since:
        ticket.on_hold_seconds += business_seconds(ticket.on_hold_since, now, ticket.week)
        ticket.on_hold_since = None
    ticket.status = Ticket.STATUS_RESOLVED
    ticket.resolved_at = now
    ticket.resolution_note = note or ticket.resolution_note
    _touch_first_response(ticket, actor, now)
    ticket.save()
    record(ticket, TicketEvent.KIND_RESOLVED, actor=actor, at=now,
           from_status=was, to_status=ticket.status, note=note)
    return ticket


@transaction.atomic
def confirm(ticket, actor=None, satisfaction=None, note=""):
    """The requester agrees it was answered. Only now is it closed."""
    if ticket.status not in (Ticket.STATUS_RESOLVED,):
        return ticket
    now = timezone.now()
    was = ticket.status
    ticket.status = Ticket.STATUS_CLOSED
    ticket.closed_at = now
    ticket.closed_by = actor if getattr(actor, "pk", None) else None
    ticket.confirmed_by_requester = True
    if satisfaction is not None:
        try:
            ticket.satisfaction = max(1, min(5, int(satisfaction)))
        except (TypeError, ValueError):
            pass
    ticket.save()
    record(ticket, TicketEvent.KIND_CLOSED, actor=actor, at=now,
           from_status=was, to_status=ticket.status,
           note=note or "Confirmed by the requester")
    return ticket


@transaction.atomic
def auto_close(ticket, at=None):
    """Close a resolved ticket the requester never came back to.

    Recorded as NOT confirmed. Most people never return to confirm anything, so
    without this every resolved ticket stays open forever — but counting an
    auto-close as agreement would let silence be read as satisfaction, and
    silence is what this module was built because of.
    """
    if ticket.status != Ticket.STATUS_RESOLVED:
        return ticket
    now = at or timezone.now()
    was = ticket.status
    ticket.status = Ticket.STATUS_CLOSED
    ticket.closed_at = now
    ticket.confirmed_by_requester = False
    ticket.save()
    days = DeskSettings.get().auto_close_after_days
    record(ticket, TicketEvent.KIND_CLOSED, actor=None, at=now,
           from_status=was, to_status=ticket.status,
           note=f"Closed automatically — resolved {days} day(s) ago with no reply "
                f"from the requester. Not confirmed.")
    return ticket


@transaction.atomic
def reopen(ticket, actor=None, note=""):
    """The answer did not answer it. The ticket comes back with its history."""
    if not ticket.can_reopen():
        return ticket
    now = timezone.now()
    was = ticket.status
    ticket.status = Ticket.STATUS_IN_PROGRESS
    ticket.resolved_at = None
    ticket.closed_at = None
    ticket.closed_by = None
    ticket.confirmed_by_requester = None
    ticket.reopened_count += 1
    ticket.last_reopened_at = now
    ticket.save()
    record(ticket, TicketEvent.KIND_REOPENED, actor=actor, at=now,
           from_status=was, to_status=ticket.status,
           note=note or "Reopened by the requester")
    return ticket


@transaction.atomic
def cancel(ticket, actor=None, note=""):
    """Withdrawn. Not a success and not a failure, and excluded from the SLA."""
    if ticket.status in Ticket.CLOSED_STATUSES:
        return ticket
    now = timezone.now()
    was = ticket.status
    ticket.status = Ticket.STATUS_CANCELLED
    ticket.closed_at = now
    ticket.closed_by = actor if getattr(actor, "pk", None) else None
    ticket.save()
    record(ticket, TicketEvent.KIND_CLOSED, actor=actor, at=now,
           from_status=was, to_status=ticket.status, note=note or "Cancelled")
    return ticket
