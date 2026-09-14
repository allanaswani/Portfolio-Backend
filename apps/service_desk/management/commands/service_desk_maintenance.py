"""The jobs that keep the desk honest when nobody is looking.

    */15 * * * * docker exec hf-backend python manage.py service_desk_maintenance

Three things, all of which exist because a queue left alone drifts:

* **Auto-close** resolved tickets the requester never came back to, recorded as
  unconfirmed. Without it every resolved ticket stays open forever, because most
  people never return to confirm anything.
* **Warn** before a target is missed, to whoever can still do something about it.
  After the fact is a report; before it is a chance.
* **Escalate** a breach to the managers, once. Once is the important word: a
  breach that re-mails every fifteen minutes is a breach everybody filters.

Nothing here is destructive and everything is idempotent, so running it twice —
or running it after an outage, against a backlog — does not double-send.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.service_desk import notifications, reports, workflow
from apps.service_desk.models import DeskSettings, Ticket, TicketEvent
from apps.service_desk.worktime import business_seconds

#: How close to the target counts as "due soon".
WARN_WITHIN_MINUTES = 60


def _already(ticket, marker):
    """Has this exact notice already gone out for this ticket?

    Recorded as an SLA event on the ticket rather than as a flag column: it is
    part of the ticket's history, and it means the check is a query rather than
    another field to migrate.
    """
    return ticket.events.filter(kind=TicketEvent.KIND_SLA, note=marker).exists()


def _mark(ticket, marker):
    workflow.record(ticket, TicketEvent.KIND_SLA, actor=None, note=marker)


class Command(BaseCommand):
    help = "Auto-close, warn and escalate. Safe to run repeatedly."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        now = timezone.now()
        desk = DeskSettings.get()
        week = desk.work_week()

        closed = self.auto_close(desk, week, now, dry)
        warned = self.warn(now, dry)
        escalated = self.escalate(now, dry)

        self.stdout.write(
            f"auto-closed {closed}, warned {warned}, escalated {escalated}"
            + (" (dry run)" if dry else ""))

    def auto_close(self, desk, week, now, dry):
        """Close what was resolved and never answered."""
        count = 0
        needed = desk.auto_close_after_days * week.seconds_per_day
        for ticket in Ticket.objects.filter(
                status=Ticket.STATUS_RESOLVED, resolved_at__isnull=False):
            # Measured in working time, like everything else: resolved on Friday
            # afternoon must not auto-close over a weekend nobody could reply in.
            if business_seconds(ticket.resolved_at, now, week) < needed:
                continue
            count += 1
            if not dry:
                workflow.auto_close(ticket, at=now)
        return count

    def warn(self, now, dry):
        """Tell whoever owns it that a target is about to pass."""
        count = 0
        soon = now + timedelta(minutes=WARN_WITHIN_MINUTES)
        queue = (Ticket.objects.filter(status__in=reports.OPEN_STATUSES)
                 .select_related("category", "assigned_to"))

        for ticket in queue:
            # Response first: an unanswered ticket is the one the requester is
            # actually sitting in front of.
            if (not ticket.first_response_at and ticket.response_due_at
                    and ticket.response_due_at <= soon
                    and not _already(ticket, "warned:response")):
                count += 1
                if not dry:
                    notifications.breach_warning(ticket, kind="response")
                    _mark(ticket, "warned:response")

            if (ticket.resolution_due_at and ticket.resolution_due_at <= soon
                    and not _already(ticket, "warned:resolution")):
                count += 1
                if not dry:
                    notifications.breach_warning(ticket, kind="resolution")
                    _mark(ticket, "warned:resolution")
        return count

    def escalate(self, now, dry):
        """A breach goes to the managers, once."""
        count = 0
        queue = (Ticket.objects.filter(status__in=reports.OPEN_STATUSES)
                 .select_related("category", "assigned_to"))

        for ticket in queue:
            if (not ticket.first_response_at and ticket.response_due_at
                    and now > ticket.response_due_at
                    and not _already(ticket, "breached:response")):
                count += 1
                if not dry:
                    notifications.breached(ticket, kind="response")
                    _mark(ticket, "breached:response")

            if (ticket.resolution_due_at and now > ticket.resolution_due_at
                    and not _already(ticket, "breached:resolution")):
                count += 1
                if not dry:
                    notifications.breached(ticket, kind="resolution")
                    _mark(ticket, "breached:resolution")
        return count
