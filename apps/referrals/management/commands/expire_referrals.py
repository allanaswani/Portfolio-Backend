"""Retention / auto-expiry for referrals — run from host cron (Celery was removed).

Policy (confirmed with the business):

* A referral **not converted within 90 days** of capture is a dead lead and is
  purged (any status other than ``converted`` — unallocated, allocated, contacted,
  rejected, expired).
* A **converted** referral is retained for **1 year** from its conversion date, then
  cleared.

Deletions are auditable: ``simple_history`` writes a delete row to
``referrals_history`` for every purged referral.

Usage::

    python manage.py expire_referrals            # apply
    python manage.py expire_referrals --dry-run   # report only, change nothing

Suggested host cron (mirrors the registry/ETL host jobs), daily at 02:15::

    15 2 * * * cd /app && /app/.venv/bin/python manage.py expire_referrals >> /var/log/referrals_retention.log 2>&1
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.referrals.models import Referral

UNCONVERTED_TTL_DAYS = 90
CONVERTED_RETENTION_DAYS = 365


class Command(BaseCommand):
    help = "Purge stale referrals: unconverted after 90 days, converted after 1 year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be purged without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()

        unconverted_cutoff = now - timedelta(days=UNCONVERTED_TTL_DAYS)
        converted_cutoff = now - timedelta(days=CONVERTED_RETENTION_DAYS)

        # Dead leads: never converted and older than the unconverted TTL.
        stale_unconverted = Referral.objects.exclude(
            status=Referral.STATUS_CONVERTED
        ).filter(created_at__lt=unconverted_cutoff)

        # Converted leads whose retention window has elapsed. Fall back to
        # created_at if converted_at was never stamped (defensive).
        stale_converted = Referral.objects.filter(
            status=Referral.STATUS_CONVERTED
        ).filter(converted_at__lt=converted_cutoff) | Referral.objects.filter(
            status=Referral.STATUS_CONVERTED, converted_at__isnull=True,
            created_at__lt=converted_cutoff,
        )
        stale_converted = stale_converted.distinct()

        n_unconverted = stale_unconverted.count()
        n_converted = stale_converted.count()

        if dry_run:
            self.stdout.write(
                f"[dry-run] would purge {n_unconverted} unconverted (>{UNCONVERTED_TTL_DAYS}d) "
                f"and {n_converted} converted (>{CONVERTED_RETENTION_DAYS}d) referrals."
            )
            return

        with transaction.atomic():
            # Re-filter by id inside the transaction so the two querysets can't
            # overlap or race with rows changing under us.
            deleted_unconverted, _ = Referral.objects.filter(
                pk__in=list(stale_unconverted.values_list("pk", flat=True))
            ).delete()
            deleted_converted, _ = Referral.objects.filter(
                pk__in=list(stale_converted.values_list("pk", flat=True))
            ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {deleted_unconverted} unconverted and {deleted_converted} "
                f"converted referral rows."
            )
        )
