"""Write one "the app was alive" tick for the current minute.

Run from cron on the host, every minute:

    * * * * * docker exec hf-backend python manage.py record_heartbeat

Uptime on the Data Health dashboard is measured from these ticks. Without the
cron entry the dashboard reports that uptime is not being measured rather than
inventing a number from request traffic — a quiet night has no traffic and no
downtime, and the two must not be confused.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.observability.models import AppHeartbeat


class Command(BaseCommand):
    help = "Record an uptime heartbeat for the current minute."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prune-days", type=int, default=90,
            help="Delete heartbeats older than this many days (0 to keep all).",
        )

    def handle(self, *args, **options):
        minute = timezone.now().replace(second=0, microsecond=0)
        _, created = AppHeartbeat.objects.get_or_create(minute=minute)

        pruned = 0
        days = options["prune_days"]
        if days:
            cutoff = timezone.now() - timedelta(days=days)
            pruned, _ = AppHeartbeat.objects.filter(minute__lt=cutoff).delete()

        self.stdout.write(
            f"heartbeat {minute.isoformat()} "
            f"{'recorded' if created else 'already present'}"
            + (f", pruned {pruned}" if pruned else "")
        )
