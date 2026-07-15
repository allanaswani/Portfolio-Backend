"""Fortnightly overdue-files report + escalation (§3.4).

Run every two weeks (cron / Celery beat). It emails the current overdue list to
Head of Operations, and — for any file that has been overdue past a second
two-week grace window without being returned — escalates to the same recipients
and stamps ``escalated_at`` so it is not re-escalated on the next run.

    python manage.py registry_overdue_report [--to ops@hfgroup.co.ke] [--dry-run]

Recipients default to the ``REGISTRY_OVERDUE_RECIPIENTS`` env/setting (comma
separated). With no recipients and no --to, the report is printed only.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.registry.models import MovementCard, OVERDUE_DAYS

# A file overdue for a further fortnight past its due date without response is
# escalated (§3.4: "does not respond to request, within two weeks, escalate").
ESCALATION_GRACE_DAYS = 14


def _name(user):
    return (user.get_full_name().strip() or user.username) if user else "—"


class Command(BaseCommand):
    help = "Email the fortnightly registry overdue-files report and escalate stragglers."

    def add_arguments(self, parser):
        parser.add_argument("--to", default="", help="Comma-separated recipient override.")
        parser.add_argument("--dry-run", action="store_true", help="Print, do not email.")

    def handle(self, *args, **opts):
        now = timezone.now()
        overdue = list(
            MovementCard.objects
            .select_related("file", "borrower")
            .filter(returned_at__isnull=True, due_at__lt=now)
            .order_by("due_at")
        )

        recipients = self._recipients(opts["to"])
        lines = [
            f"Registry overdue-files report — {now:%Y-%m-%d %H:%M}",
            f"Overdue threshold: {OVERDUE_DAYS} days. {len(overdue)} file(s) overdue.",
            "",
        ]
        to_escalate = []
        for c in overdue:
            flag = ""
            if (now - c.due_at).days >= ESCALATION_GRACE_DAYS and c.escalated_at is None:
                to_escalate.append(c)
                flag = "  ** ESCALATE **"
            lines.append(
                f"- {c.file.file_no} | {c.file.customer_name} | held by "
                f"{_name(c.borrower)} ({c.department or 'n/a'}) | "
                f"{c.days_overdue}d overdue{flag}"
            )

        body = "\n".join(lines)
        self.stdout.write(body)

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no email sent."))
            return

        if not recipients:
            self.stdout.write(self.style.WARNING(
                "No recipients configured (REGISTRY_OVERDUE_RECIPIENTS / --to) — printed only."
            ))
            return

        subject = f"[Registry] {len(overdue)} overdue file(s) — {len(to_escalate)} to escalate"
        send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", ""),
            recipients,
            fail_silently=False,
        )

        if to_escalate:
            stamp = timezone.now()
            for c in to_escalate:
                c.escalated_at = stamp
            MovementCard.objects.bulk_update(to_escalate, ["escalated_at"])

        self.stdout.write(self.style.SUCCESS(
            f"Emailed {len(recipients)} recipient(s); escalated {len(to_escalate)} file(s)."
        ))

    def _recipients(self, override):
        if override:
            return [a.strip() for a in override.split(",") if a.strip()]
        configured = getattr(settings, "REGISTRY_OVERDUE_RECIPIENTS", "")
        return [a.strip() for a in str(configured).split(",") if a.strip()]
