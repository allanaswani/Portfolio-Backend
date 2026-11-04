"""Run the immediate alert checks and mail anything that changed.

    */10 * * * * docker exec hf-backend python manage.py run_alert_checks

Every check reduces to a state for a key, and mail goes out only when that
state CHANGES and somebody has something to do - see
``apps.observability.alerts``.

The database is tried first. When it refuses, nothing else here can run, and
``apps.observability.outage`` tells people without it.
"""

from django.core.management.base import BaseCommand

from apps.observability import alerts


class Command(BaseCommand):
    help = "Check for downtime, data-health and sensitive-change alerts; email them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sensitive-minutes", type=int, default=10,
            help="Not used: sensitive changes are now in the daily digest. "
                 "Accepted so the existing cron line keeps working.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be sent, and send nothing.",
        )

    def handle(self, *args, **options):
        from django.db import OperationalError, connection

        from apps.observability import outage

        try:
            connection.ensure_connection()
        except OperationalError as exc:
            sent = outage.database_refused(exc)
            self.stdout.write(
                f"the database refused: {sent or 'not mailing yet'}")
            return
        sent = outage.database_answered(
            alerts.AlertRecipient.for_kind(alerts.AlertRecipient.KIND_DOWNTIME))
        if sent:
            self.stdout.write(sent)

        if options["dry_run"]:
            pending = []
            pending += alerts.check_services()
            pending += alerts.check_error_rate()
            pending += alerts.check_data_health()
            if not pending:
                self.stdout.write("[dry-run] nothing to send")
                return
            for kind, subject, _body in pending:
                recipients = alerts.AlertRecipient.for_kind(kind)
                self.stdout.write(
                    f"[dry-run] {kind}: {subject} -> {len(recipients)} recipient(s)")
            # NOTE: the checks above have already recorded the new states, so a
            # dry run "uses up" the transition. It is a diagnostic, not a
            # rehearsal — say so rather than let somebody be surprised.
            self.stdout.write(self.style.WARNING(
                "state was still recorded; the next real run will not resend these"))
            return

        delivered = alerts.run_all(sensitive_minutes=options["sensitive_minutes"])
        if not delivered:
            self.stdout.write("no alerts")
            return
        for item in delivered:
            self.stdout.write(
                f"{item['kind']}: {item['subject']} -> {item['recipients']} recipient(s)")
