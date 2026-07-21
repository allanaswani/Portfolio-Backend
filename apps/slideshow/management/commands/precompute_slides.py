"""Recompute dashboard slides.

Replaces the old Celery beat job (``precompute-slides``, every 5 min). Run from
host cron, e.g.:

    */5 * * * * cd /app && python manage.py precompute_slides
"""

from django.core.management.base import BaseCommand

from apps.slideshow.services import precompute_all_slides


class Command(BaseCommand):
    help = "Precompute all dashboard slides and store them in the Slide table."

    def handle(self, *args, **options):
        count = precompute_all_slides()
        self.stdout.write(self.style.SUCCESS(f"Recomputed {count} slides."))
