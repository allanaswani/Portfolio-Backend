"""Every transition a design brief can make, and the step each one records.

All state changes go through here rather than through ``brief.save()`` in a
view, for the reason ``apps.service_desk.workflow`` gives: each transition has
to write its ``BriefEvent``, and a rule that lives in six views is a rule that
is right in five of them. There is deliberately no PATCH that can set
``status`` — a status nobody recorded a step for is the failure this board
exists to prevent.

Transitions are idempotent where that is meaningful: starting work already
started, or approving an approved brief, is a no-op rather than a second event.

An invalid transition raises ``TransitionError``, which the views turn into a
400 naming what was wrong. It is not silently ignored: a designer who presses
Submit on somebody else's brief needs to be told, not left wondering.
"""

from django.db import transaction
from django.utils import timezone

from .models import BriefEvent, DesignBrief


class TransitionError(Exception):
    """A step that is not allowed from where the brief currently is."""


def _label(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return "system / job"
    return user.get_full_name() or user.username


def record(brief, kind, actor=None, note="", from_status="", to_status="", at=None):
    """Append one step to the brief's timeline."""
    return BriefEvent.objects.create(
        brief=brief,
        kind=kind,
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        actor_name=_label(actor),
        note=note or "",
        from_status=from_status or "",
        to_status=to_status or "",
        at=at or timezone.now(),
    )


@transaction.atomic
def create(*, design_item, department, addressed_to, raised_by=None, brief="",
           item_type="other", priority=DesignBrief.PRIORITY_NORMAL,
           release_date=None):
    """Raise a brief. It starts in ``new`` with no designer, by design.

    Nothing here auto-assigns. Who does the work is the department admin's
    decision, and a brief that allocated itself would make the board a record
    of what the software guessed rather than of what the team agreed.
    """
    obj = DesignBrief.objects.create(
        design_item=design_item,
        department=department,
        addressed_to=addressed_to,
        raised_by=raised_by if (raised_by and raised_by.is_authenticated) else None,
        brief=brief or "",
        item_type=item_type or "other",
        priority=priority or DesignBrief.PRIORITY_NORMAL,
        release_date=release_date,
        status=DesignBrief.STATUS_NEW,
    )
    record(obj, BriefEvent.KIND_RAISED, actor=raised_by,
           to_status=obj.status,
           note=f"Raised by {obj.department} for {obj.addressed_to}.")
    return obj


@transaction.atomic
def assign(brief, designer, actor=None, note=""):
    """Allocate, or reallocate, the brief to a designer.

    Allowed on a closed brief only after it has been reopened — reassigning
    archived work would change the department's own record of who made what.
    """
    if brief.is_closed:
        raise TransitionError(
            "This brief is closed. Reopen it before assigning a designer.")
    if designer is None:
        raise TransitionError("No designer given.")
    if brief.assigned_designer_id == designer.id:
        return brief  # already theirs — no second event

    was = brief.assigned_designer
    kind = BriefEvent.KIND_REASSIGNED if was else BriefEvent.KIND_ASSIGNED
    from_status = brief.status

    brief.assigned_designer = designer
    brief.assigned_by = actor if (actor and actor.is_authenticated) else None
    brief.assigned_at = timezone.now()
    # Only a brief that has not been started moves to "assigned". One that is
    # already in progress or in rework keeps its status: reassigning mid-flight
    # must not quietly reset how far the work had got.
    if brief.status == DesignBrief.STATUS_NEW:
        brief.status = DesignBrief.STATUS_ASSIGNED
    brief.save(update_fields=[
        "assigned_designer", "assigned_by", "assigned_at", "status", "updated_at"])

    detail = f"Assigned to {_label(designer)}"
    if was:
        detail = f"Reassigned from {_label(was)} to {_label(designer)}"
    record(brief, kind, actor=actor, from_status=from_status,
           to_status=brief.status,
           note=(note or detail))
    return brief


@transaction.atomic
def start(brief, actor=None, note=""):
    """The designer has picked the work up."""
    if brief.is_closed:
        raise TransitionError("This brief is closed.")
    if brief.assigned_designer_id is None:
        raise TransitionError(
            "Nobody is assigned to this brief yet — the department admin "
            "assigns a designer first.")
    if brief.status == DesignBrief.STATUS_IN_PROGRESS:
        return brief
    if brief.status not in DesignBrief.DESIGNER_STATUSES:
        raise TransitionError(
            f"Cannot start a brief that is '{brief.get_status_display()}'.")

    from_status = brief.status
    brief.status = DesignBrief.STATUS_IN_PROGRESS
    if brief.started_at is None:
        brief.started_at = timezone.now()
    brief.save(update_fields=["status", "started_at", "updated_at"])
    record(brief, BriefEvent.KIND_STARTED, actor=actor, note=note,
           from_status=from_status, to_status=brief.status)
    return brief


@transaction.atomic
def submit(brief, actor=None, note=""):
    """The designer says it is done. It now waits on the requester."""
    if brief.is_closed:
        raise TransitionError("This brief is closed.")
    if brief.status == DesignBrief.STATUS_SUBMITTED:
        return brief
    if brief.status not in DesignBrief.DESIGNER_STATUSES:
        raise TransitionError(
            f"Cannot submit a brief that is '{brief.get_status_display()}'.")

    from_status = brief.status
    brief.status = DesignBrief.STATUS_SUBMITTED
    brief.submitted_at = timezone.now()
    brief.save(update_fields=["status", "submitted_at", "updated_at"])
    record(brief, BriefEvent.KIND_SUBMITTED, actor=actor, note=note,
           from_status=from_status, to_status=brief.status)
    return brief


@transaction.atomic
def request_rework(brief, actor=None, reason=""):
    """The requester was not satisfied. Back to the designer, and counted.

    A reason is required. "Rework" with no reason is the single most useless
    row this board could hold: the designer learns only that it was wrong.
    """
    if brief.is_closed:
        raise TransitionError(
            "This brief is closed. Reopen it if it needs more work.")
    if brief.status != DesignBrief.STATUS_SUBMITTED:
        raise TransitionError(
            "Rework can only be requested on a brief that has been submitted "
            f"for review. This one is '{brief.get_status_display()}'.")
    reason = (reason or "").strip()
    if not reason:
        raise TransitionError("Say what needs changing — a reason is required.")

    from_status = brief.status
    brief.status = DesignBrief.STATUS_REWORK
    brief.rework_count = (brief.rework_count or 0) + 1
    brief.last_rework_at = timezone.now()
    brief.last_rework_reason = reason
    brief.save(update_fields=[
        "status", "rework_count", "last_rework_at", "last_rework_reason",
        "updated_at"])
    record(brief, BriefEvent.KIND_REWORK, actor=actor, note=reason,
           from_status=from_status, to_status=brief.status)
    return brief


@transaction.atomic
def approve(brief, actor=None, satisfaction=None, note=""):
    """The requester accepted it. The brief closes and is archived.

    ``actor`` may not be the assigned designer, even when that person is also
    an admin. A department signing off its own output is exactly the gap this
    board is meant to close, so it is refused here rather than left to the
    honesty of whoever is clicking.
    """
    if brief.status == DesignBrief.STATUS_APPROVED:
        return brief
    if brief.status == DesignBrief.STATUS_CANCELLED:
        raise TransitionError("This brief was cancelled.")
    if brief.status != DesignBrief.STATUS_SUBMITTED:
        raise TransitionError(
            "Only a brief that has been submitted for review can be approved. "
            f"This one is '{brief.get_status_display()}'.")
    if (actor is not None and brief.assigned_designer_id
            and getattr(actor, "id", None) == brief.assigned_designer_id):
        raise TransitionError(
            "The designer who made this cannot also approve it. The person who "
            "raised the brief, or the department admin, signs it off.")
    if satisfaction is not None and not (1 <= int(satisfaction) <= 5):
        raise TransitionError("Satisfaction must be between 1 and 5.")

    now = timezone.now()
    from_status = brief.status
    brief.status = DesignBrief.STATUS_APPROVED
    brief.approved_by = actor if (actor and actor.is_authenticated) else None
    brief.approved_at = now
    brief.satisfaction = int(satisfaction) if satisfaction is not None else None
    brief.closing_note = note or ""
    brief.archived_at = now  # closed means archived; the row is never deleted
    brief.save(update_fields=[
        "status", "approved_by", "approved_at", "satisfaction", "closing_note",
        "archived_at", "updated_at"])
    record(brief, BriefEvent.KIND_APPROVED, actor=actor, note=note,
           from_status=from_status, to_status=brief.status)
    return brief


@transaction.atomic
def cancel(brief, actor=None, reason=""):
    """Withdraw the brief. Closed and archived, but not a failure.

    Counted separately from approval so the department's "delivered" figure is
    not inflated by work that was called off.
    """
    if brief.status == DesignBrief.STATUS_CANCELLED:
        return brief
    if brief.status == DesignBrief.STATUS_APPROVED:
        raise TransitionError("This brief was already approved.")

    now = timezone.now()
    from_status = brief.status
    brief.status = DesignBrief.STATUS_CANCELLED
    brief.closing_note = reason or ""
    brief.archived_at = now
    brief.save(update_fields=["status", "closing_note", "archived_at", "updated_at"])
    record(brief, BriefEvent.KIND_CANCELLED, actor=actor, note=reason,
           from_status=from_status, to_status=brief.status)
    return brief


@transaction.atomic
def reopen(brief, actor=None, reason=""):
    """Bring an archived brief back onto the board. Admin only (see rbac).

    It returns to the designer's court rather than to ``new``: the work exists,
    somebody made it, and the point of reopening is that it needs changing. The
    rework counter is incremented, because that is what this is.
    """
    if not brief.is_closed:
        raise TransitionError("This brief is already open.")
    reason = (reason or "").strip()
    if not reason:
        raise TransitionError("Say why it is being reopened — a reason is required.")

    from_status = brief.status
    brief.status = (DesignBrief.STATUS_REWORK if brief.assigned_designer_id
                    else DesignBrief.STATUS_NEW)
    brief.archived_at = None
    brief.approved_by = None
    brief.approved_at = None
    if brief.assigned_designer_id:
        brief.rework_count = (brief.rework_count or 0) + 1
        brief.last_rework_at = timezone.now()
        brief.last_rework_reason = reason
    brief.save(update_fields=[
        "status", "archived_at", "approved_by", "approved_at", "rework_count",
        "last_rework_at", "last_rework_reason", "updated_at"])
    record(brief, BriefEvent.KIND_REOPENED, actor=actor, note=reason,
           from_status=from_status, to_status=brief.status)
    return brief


@transaction.atomic
def add_note(brief, actor=None, note=""):
    """A comment on the brief. Changes no state, but is on the timeline."""
    note = (note or "").strip()
    if not note:
        raise TransitionError("Nothing to add.")
    return record(brief, BriefEvent.KIND_NOTE, actor=actor, note=note,
                  from_status=brief.status, to_status=brief.status)


@transaction.atomic
def record_edit(brief, actor=None, changed=None):
    """Note that the brief's own wording or dates were changed, and what."""
    changed = changed or []
    if not changed:
        return None
    return record(brief, BriefEvent.KIND_EDITED, actor=actor,
                  note="Changed: " + ", ".join(sorted(changed)),
                  from_status=brief.status, to_status=brief.status)
