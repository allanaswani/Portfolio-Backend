"""Generate portfolio insights.

Replaces the old Celery beat job (``run-insight-pipeline``, every 6 h). Run from
host cron, e.g.:

    0 */6 * * * cd /app && python manage.py run_insights_pipeline
"""

from django.core.management.base import BaseCommand

from apps.insights.services import run_pipeline


class Command(BaseCommand):
    help = "Generate portfolio insights and persist them to the Insight table."

    def handle(self, *args, **options):
        count = run_pipeline()
        self.stdout.write(self.style.SUCCESS(f"Generated {count} insights."))
