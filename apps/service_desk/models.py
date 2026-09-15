"""Service Desk — every query raised, who is handling it, and how long each step took.

The complaint behind this module is "some of our queries are not handled". That
is a complaint about accountability, not about volume, so the design answers
three questions and is shaped around answering them:

* **Where is my query?** A ticket has one owner and one status at all times, and
  the person who raised it can see both without asking anybody.
* **How long did each step take?** Every transition writes a ``TicketEvent`` with
  a timestamp and the working time since the previous step. The queue is not
  where a ticket goes to become invisible.
* **Who said it was handled?** A handler resolves; the requester confirms or
  reopens. Nobody closes their own work silently — that is the exact failure
  being reported.

Owned by Strategy & Business Performance: one queue, worked by that team. The
category carries the SLA targets anyway, so it also carries a queue name — the
day a second team takes some of this, that is a field to set, not a rebuild.

Durations are working time, not wall-clock. See ``worktime`` for why.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from .worktime import WorkWeek, add_business_seconds, business_seconds

USER = settings.AUTH_USER_MODEL


def _ref() -> str:
    """Short business reference, e.g. ``SD-9F3A1C2B``.

    Random rather than sequential on purpose: a sequential number tells every
    recipient how many queries the desk has ever had, and a gap in the sequence
    invites "what happened to SD-000412?" when the answer is a rolled-back
    transaction.
    """
    return f"SD-{uuid.uuid4().hex[:8].upper()}"


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ── Configuration ────────────────────────────────────────────────────────────

class Holiday(models.Model):
    """A day the desk is shut, so it is not counted against the SLA.

    Kenyan public holidays move (Eid, and any day the President gazettes), so
    this is a table somebody maintains rather than a hard-coded list that is
    wrong every year.
    """

    day = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    history = HistoricalRecords()

    class Meta:
        db_table = "service_desk_holiday"
        ordering = ["-day"]

    def __str__(self):
        return f"{self.day} — {self.name}"


class DeskSettings(models.Model):
    """When the desk is open, and how it behaves. One row.

    A singleton rather than Django settings because the working day is an
    operational decision the Strategy team should be able to change without a
    deployment.
    """

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    opens_minute = models.PositiveSmallIntegerField(
        default=8 * 60, help_text="Minutes from midnight. 480 = 08:00.")
    closes_minute = models.PositiveSmallIntegerField(
        default=17 * 60, help_text="Minutes from midnight. 1020 = 17:00.")
    # Monday–Friday. Stored as a string so a six-day week is an edit, not a
    # migration.
    workdays = models.CharField(
        max_length=20, default="0,1,2,3,4",
        help_text="Weekday numbers, Monday=0, comma separated.")

    # How long a resolved ticket waits for the requester to confirm before it
    # closes itself. Without this every resolved ticket stays open forever,
    # because most people never come back to confirm anything.
    auto_close_after_days = models.PositiveSmallIntegerField(default=3)
    # How long after closure a requester may still reopen. A ticket that can be
    # reopened years later is a ticket whose SLA figure never settles.
    reopen_window_days = models.PositiveSmallIntegerField(default=14)

    notify_requester = models.BooleanField(default=True)
    notify_assignee = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        db_table = "service_desk_settings"
        verbose_name = "Service desk settings"
        verbose_name_plural = "Service desk settings"

    def save(self, *args, **kwargs):
        self.singleton = 1
        return super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        """The row, creating it on first use. Never raises."""
        try:
            row, _ = cls.objects.get_or_create(singleton=1)
            return row
        except Exception:  # noqa: BLE001 — before migrate, or a dead connection
            return cls()

    def work_week(self) -> WorkWeek:
        try:
            days = frozenset(
                int(part) for part in str(self.workdays).split(",")
                if part.strip().isdigit()
            )
        except Exception:  # noqa: BLE001
            days = frozenset({0, 1, 2, 3, 4})
        try:
            holidays = frozenset(Holiday.objects.values_list("day", flat=True))
        except Exception:  # noqa: BLE001 — the calendar must not break the clock
            holidays = frozenset()
        return WorkWeek(
            start_minute=self.opens_minute,
            end_minute=self.closes_minute,
            workdays=days or frozenset({0, 1, 2, 3, 4}),
            holidays=holidays,
            tz=getattr(settings, "TIME_ZONE", "Africa/Nairobi"),
        )


class DeskRecipient(TimeStamped):
    """Somebody who should hear from the desk but has no login on the tool.

    The first design tied being notified to holding an account, on the
    assumption that anyone on the desk would have one. Several of the people who
    actually run this desk do not — and "create them a login so they can be
    emailed" is a worse answer than simply writing down the address.

    These addresses are added to the team's, never instead of it, so removing
    the last account does not silently stop the queue reaching anybody.
    """

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150, blank=True)

    #: New queries, replies and reopens — the day-to-day queue.
    queue = models.BooleanField(default=True)
    #: Breaches and the periodic report — what a desk manager needs to see.
    escalations = models.BooleanField(default=True)

    is_active = models.BooleanField(default=True)
    history = HistoricalRecords(table_name="service_desk_recipient_history")

    class Meta:
        db_table = "service_desk_recipient"
        ordering = ["email"]

    def __str__(self):
        return f"{self.name or self.email}"

    @classmethod
    def addresses(cls, kind="queue"):
        """Active addresses for one kind of mail. Never raises."""
        try:
            rows = cls.objects.filter(is_active=True)
            if kind == "escalations":
                rows = rows.filter(escalations=True)
            else:
                rows = rows.filter(queue=True)
            return sorted({r.email.strip() for r in rows if r.email})
        except Exception:  # noqa: BLE001 — before migrate, or a dead connection
            return []


class TicketCategory(TimeStamped):
    """What kind of query this is, and how quickly it is promised an answer.

    The SLA lives here rather than on the ticket so that changing the promise
    changes it for everything of that kind, and so that a ticket cannot be
    quietly given a softer target than its neighbours.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    description = models.CharField(max_length=300, blank=True)

    # The team that works this category. One queue today; this is what a second
    # team would be given, rather than a new assignment model.
    queue = models.CharField(max_length=60, default="strategy")

    # Working minutes, measured on the desk's calendar.
    response_minutes = models.PositiveIntegerField(
        default=4 * 60, help_text="Working minutes to first response.")
    resolution_minutes = models.PositiveIntegerField(
        default=2 * 9 * 60, help_text="Working minutes to resolution.")

    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "service_desk_category"
        ordering = ["name"]
        verbose_name_plural = "Ticket categories"

    def __str__(self):
        return self.name


# ── The ticket ───────────────────────────────────────────────────────────────

class TicketQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(status__in=Ticket.CLOSED_STATUSES)

    def for_user(self, user):
        """What this person is allowed to see.

        A handler sees the queue; everyone else sees only what they raised or
        was raised for them. Enforced here as well as in the view, so a new
        endpoint cannot forget it.
        """
        from .rbac import is_handler

        if not user or not user.is_authenticated:
            return self.none()
        if is_handler(user):
            return self
        return self.filter(
            models.Q(raised_by=user) | models.Q(requester_email__iexact=user.email or "\x00")
        )


class Ticket(TimeStamped):
    # ── Lifecycle ────────────────────────────────────────────────────────────
    # Deliberately short. Every extra status is a state somebody has to decide
    # between, and a queue with eleven statuses is a queue where half the
    # tickets are in the wrong one.
    STATUS_NEW = "new"                    # raised, nobody has picked it up
    STATUS_ASSIGNED = "assigned"          # has an owner, not started
    STATUS_IN_PROGRESS = "in_progress"    # being worked
    STATUS_ON_HOLD = "on_hold"            # waiting on the requester — clock pauses
    STATUS_RESOLVED = "resolved"          # handler says done, awaiting confirmation
    STATUS_CLOSED = "closed"              # confirmed, or auto-closed
    STATUS_CANCELLED = "cancelled"        # withdrawn; not a failure, not a success

    STATUS = [
        (STATUS_NEW, "New"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_ON_HOLD, "Waiting on requester"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]
    CLOSED_STATUSES = {STATUS_CLOSED, STATUS_CANCELLED}
    #: While in these, the resolution clock does not run.
    PAUSED_STATUSES = {STATUS_ON_HOLD}

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"
    PRIORITY = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]
    #: Multiplies the category SLA. Urgent is not a different promise, it is the
    #: same promise sooner — one number to reason about instead of a matrix.
    PRIORITY_FACTOR = {
        PRIORITY_LOW: 2.0,
        PRIORITY_NORMAL: 1.0,
        PRIORITY_HIGH: 0.5,
        PRIORITY_URGENT: 0.25,
    }

    reference = models.CharField(max_length=20, unique=True, blank=True, db_index=True)
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    category = models.ForeignKey(
        TicketCategory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets")
    priority = models.CharField(max_length=10, choices=PRIORITY, default=PRIORITY_NORMAL)
    status = models.CharField(max_length=15, choices=STATUS, default=STATUS_NEW,
                              db_index=True)

    # ── Who wants an answer ──────────────────────────────────────────────────
    raised_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets_raised")
    # Queries that arrive by phone or email never reach a system, and those are
    # the ones most likely to go unhandled. A handler logs them against the
    # person who actually asked.
    on_behalf_of = models.CharField(max_length=150, blank=True)
    requester_email = models.EmailField(blank=True)
    requester_department = models.CharField(max_length=120, blank=True)
    requester_branch = models.CharField(max_length=120, blank=True)

    # ── Who is answering ─────────────────────────────────────────────────────
    assigned_to = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets_assigned")

    # ── Every step, timed ────────────────────────────────────────────────────
    # These are the fields the whole module exists for. Each is written once,
    # when the step happens, and never recomputed — a timestamp that can be
    # recalculated is a timestamp that can be quietly corrected.
    assigned_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Held time is accumulated rather than derived, because a ticket can be put
    # on hold and taken off it many times and only the running total matters.
    on_hold_since = models.DateTimeField(null=True, blank=True)
    on_hold_seconds = models.PositiveIntegerField(default=0)

    reopened_count = models.PositiveSmallIntegerField(default=0)
    last_reopened_at = models.DateTimeField(null=True, blank=True)

    # ── The promise, frozen at creation ──────────────────────────────────────
    # Copied from the category rather than read through it: repricing a
    # category must not retrospectively breach, or un-breach, tickets that were
    # raised under the old promise.
    response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    response_minutes = models.PositiveIntegerField(default=0)
    resolution_minutes = models.PositiveIntegerField(default=0)

    resolution_note = models.TextField(blank=True)
    # Who said it was answered. Recorded so that person can never also be the
    # one who agrees it was answered — a desk confirming its own work is the
    # exact failure this module exists to prevent, and it happened.
    resolved_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets_resolved")
    closed_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets_closed")
    # Filled when the requester confirms, so "the desk says done" and "the
    # person who asked agrees" are never the same fact.
    confirmed_by_requester = models.BooleanField(null=True, blank=True)
    satisfaction = models.PositiveSmallIntegerField(null=True, blank=True)

    history = HistoricalRecords(table_name="service_desk_ticket_history")
    objects = TicketQuerySet.as_manager()

    class Meta:
        db_table = "service_desk_ticket"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["raised_by", "-created_at"]),
            models.Index(fields=["resolution_due_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.subject}"

    # ── Creation ─────────────────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = _ref()
        new = self._state.adding
        if new and self.category_id and not self.resolution_due_at:
            self.apply_sla()
        return super().save(*args, **kwargs)

    def apply_sla(self, when=None):
        """Freeze this ticket's promise onto it."""
        when = when or timezone.now()
        category = self.category
        if category is None:
            return
        factor = self.PRIORITY_FACTOR.get(self.priority, 1.0)
        self.response_minutes = max(1, int(category.response_minutes * factor))
        self.resolution_minutes = max(1, int(category.resolution_minutes * factor))
        week = DeskSettings.get().work_week()
        self.response_due_at = add_business_seconds(when, self.response_minutes * 60, week)
        self.resolution_due_at = add_business_seconds(when, self.resolution_minutes * 60, week)

    # ── Measurement ──────────────────────────────────────────────────────────

    @property
    def week(self):
        return DeskSettings.get().work_week()

    def working_seconds_open(self, now=None):
        """Working time from raise to resolution, minus time spent waiting on
        the requester. The desk is not accountable for somebody else's silence."""
        now = now or timezone.now()
        end = self.resolved_at or (self.closed_at if self.status in self.CLOSED_STATUSES else now)
        gross = business_seconds(self.created_at, end, self.week)
        held = self.on_hold_seconds
        if self.on_hold_since and self.status in self.PAUSED_STATUSES:
            held += business_seconds(self.on_hold_since, now, self.week)
        return max(0, gross - held)

    def working_seconds_to_response(self):
        if not self.first_response_at:
            return None
        return business_seconds(self.created_at, self.first_response_at, self.week)

    @property
    def response_breached(self):
        """None while there is still time — unknown is not the same as met."""
        if self.first_response_at:
            return bool(self.response_due_at and self.first_response_at > self.response_due_at)
        if not self.response_due_at:
            return None
        if self.status in self.CLOSED_STATUSES:
            return True  # closed without anybody ever answering
        return timezone.now() > self.response_due_at or None

    @property
    def resolution_breached(self):
        if self.resolved_at:
            return bool(self.resolution_due_at and self.resolved_at > self.resolution_due_at)
        if not self.resolution_due_at or self.status in self.CLOSED_STATUSES:
            return None
        return timezone.now() > self.resolution_due_at or None

    @property
    def age_label(self):
        from .worktime import describe
        return describe(self.working_seconds_open())

    def can_reopen(self, now=None):
        now = now or timezone.now()
        if self.status != self.STATUS_CLOSED or not self.closed_at:
            return self.status == self.STATUS_RESOLVED
        window = DeskSettings.get().reopen_window_days
        return now <= self.closed_at + timedelta(days=window)


class TicketEvent(models.Model):
    """One step in a ticket's life, with the time it took to get here.

    This is the record that answers "it has been three weeks" with "it sat
    unassigned for nine working days, then was answered in two hours". The
    ticket's own timestamp fields carry the milestones; this carries the
    narrative, including the steps that have no milestone of their own.

    Append-only by convention: events are never edited, because the point of
    them is that they cannot be tidied up afterwards.
    """

    KIND_CREATED = "created"
    KIND_ASSIGNED = "assigned"
    KIND_STATUS = "status"
    KIND_COMMENT = "comment"
    KIND_RESOLVED = "resolved"
    KIND_REOPENED = "reopened"
    KIND_CLOSED = "closed"
    KIND_ESCALATED = "escalated"
    KIND_SLA = "sla"
    KIND = [
        (KIND_CREATED, "Raised"),
        (KIND_ASSIGNED, "Assigned"),
        (KIND_STATUS, "Status changed"),
        (KIND_COMMENT, "Comment"),
        (KIND_RESOLVED, "Resolved"),
        (KIND_REOPENED, "Reopened"),
        (KIND_CLOSED, "Closed"),
        (KIND_ESCALATED, "Escalated"),
        (KIND_SLA, "SLA"),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=15, choices=KIND)
    actor = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ticket_events")
    # A step taken by a cron (auto-close, escalation) has no actor. Recording
    # that as "system" is honest; leaving it blank reads as a bug.
    actor_label = models.CharField(max_length=150, blank=True)

    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15, blank=True)
    note = models.TextField(blank=True)

    at = models.DateTimeField(default=timezone.now, db_index=True)
    # Both clocks, stored not derived: the wall clock is what a person
    # remembers, the working clock is what the team is measured on, and
    # recomputing either later means recomputing it against today's calendar
    # rather than the one in force at the time.
    seconds_since_previous = models.PositiveIntegerField(default=0)
    working_seconds_since_previous = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "service_desk_event"
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["ticket", "at"])]

    def __str__(self):
        return f"{self.ticket_id} {self.kind} @ {self.at:%Y-%m-%d %H:%M}"


class TicketComment(TimeStamped):
    """A message on a ticket.

    ``is_internal`` keeps handler-to-handler notes off the requester's view. It
    is a real boundary, not a UI convenience — the serializer drops these rows
    for a non-handler rather than rendering them hidden.
    """

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ticket_comments")
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    history = HistoricalRecords(table_name="service_desk_comment_history")

    class Meta:
        db_table = "service_desk_comment"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.ticket_id}: {self.body[:40]}"
