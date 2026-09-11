"""Run the immediate alert checks and mail anything that changed.

    */10 * * * * docker exec hf-backend python manage.py run_alert_checks

Every check reduces to a state for a key, and mail goes out only when that
state CHANGES — see ``apps.observability.alerts``. Running this every ten
minutes therefore does not produce an email every ten minutes; it produces one
when something breaks, and one when it comes back.

``--sensitive-minutes`` must match the schedule, or sensitive changes are
either missed or reported twice. It defaults to 10 for a ten-minute cron.
"""

from django.core.management.base import BaseCommand

from apps.observability import alerts


class Command(BaseCommand):
    help = "Check for downtime, data-health and sensitive-change alerts; email them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sensitive-minutes", type=int, default=10,
            help="Look this far back for sensitive changes. Match the cron interval.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be sent, and send nothing.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            pending = []
            pending += alerts.check_services()
            pending += alerts.check_error_rate()
            pending += alerts.check_data_health()
            pending += alerts.check_sensitive_changes(
                minutes=options["sensitive_minutes"])
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
