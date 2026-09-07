"""Keep the request-metrics table from growing without bound.

One row per served request adds up. Thirty days is enough for every window the
dashboard offers (the longest is 30 days) and keeps the table small enough that
the percentile queries stay fast.

    0 3 * * * docker exec hf-backend python manage.py prune_request_metrics
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.observability.models import RequestMetric


class Command(BaseCommand):
    help = "Delete request metrics older than --days (default 30)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        days = max(1, options["days"])
        cutoff = timezone.now() - timedelta(days=days)
        # Delete in batches so a long-neglected table does not lock for minutes.
        total = 0
        while True:
            ids = list(
                RequestMetric.objects.filter(created_at__lt=cutoff)
                .values_list("id", flat=True)[:10000]
            )
            if not ids:
                break
            deleted, _ = RequestMetric.objects.filter(id__in=ids).delete()
            total += deleted
        self.stdout.write(f"pruned {total} request metrics older than {days} days")
