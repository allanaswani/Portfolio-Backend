"""Email the desk's own report.

    0 8 * * 1 docker exec hf-backend python manage.py send_service_desk_report --days 7
    0 8 1 * * docker exec hf-backend python manage.py send_service_desk_report --days 30

Goes to the desk managers. Sent whether or not the week was good — a report
that only arrives when something is wrong is a report whose absence nobody
notices, and this one exists so that "queries are not being handled" becomes a
number somebody sees before it becomes a complaint.

``--dry-run`` prints it instead, which is how you check the figures before
anyone else reads them.
"""

from django.core.management.base import BaseCommand

from apps.service_desk import notifications, reports


class Command(BaseCommand):
    help = "Email the service desk report to the desk managers."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--to", default="",
            help="Comma-separated override, for testing a single address.")

    def handle(self, *args, **options):
        days = max(1, min(365, options["days"]))
        body = reports.digest_text(days=days)

        if options["dry_run"]:
            self.stdout.write(body)
            return

        if options["to"]:
            to = [a.strip() for a in options["to"].split(",") if a.strip()]
        else:
            to = notifications.manager_addresses()

        if not to:
            # Say so rather than exit 0 quietly. A reporting job that silently
            # sends to nobody is indistinguishable from one that is working.
            self.stdout.write(self.style.WARNING(
                "Nobody to send to: no active superuser or service desk manager "
                "has an email address on their account."))
            return

        period = "Weekly" if days == 7 else f"{days}-day"
        sent = notifications.send(to, f"{period} service desk report", body)
        self.stdout.write(f"report sent to {sent} recipient(s)")
