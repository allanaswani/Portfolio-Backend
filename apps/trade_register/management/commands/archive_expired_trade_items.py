"""File expired instruments out of the active diary, once a day.

    0 1 * * * docker exec hf-backend python manage.py archive_expired_trade_items

An instrument whose term has run out is not something the desk still has to
watch — but it is emphatically still a record of what the bank issued, so this
sets a flag. **Nothing is deleted.** The active diary hides archived rows; the
Expired folder is exactly those rows.

The date it reads is the instrument's EFFECTIVE expiry: an amendment that
extended the term moves it, and archiving on the original date would file a
guarantee that is still perfectly live.

It also un-archives: if an expired instrument is later extended by an
amendment, it belongs back in the active diary, and a job that could only ever
archive would leave it filed away.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.trade_register.models import TradeRegisterEntry


class Command(BaseCommand):
    help = "Move expired trade instruments out of the active diary."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would move without changing anything.",
        )
        parser.add_argument(
            "--grace-days", type=int, default=0,
            help="Keep an instrument in the active diary this many days past "
                 "expiry (the desk often still has work to do on it).",
        )

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry = options["dry_run"]
        grace = max(0, options["grace_days"])

        to_archive, to_restore = [], []
        # select_related on the amendments is not possible (they are a reverse
        # set), so prefetch them: effective_expiry_date reads them per row and
        # this is otherwise one query per instrument.
        qs = TradeRegisterEntry.objects.prefetch_related("amendments").all()
        for entry in qs.iterator(chunk_size=500):
            days = entry.days_to_expiry(today)
            expired = days is not None and days < -grace
            if expired and not entry.is_archived:
                to_archive.append(entry.pk)
            elif not expired and entry.is_archived:
                # Extended, or its expiry corrected — it belongs back on the
                # active diary. Without this an extension would never bring an
                # instrument back and the desk would stop seeing it.
                to_restore.append(entry.pk)

        if dry:
            self.stdout.write(
                f"[dry-run] would archive {len(to_archive)} and restore "
                f"{len(to_restore)} (as at {today}, grace {grace}d)"
            )
            return

        with transaction.atomic():
            if to_archive:
                # A queryset update, so simple_history does not write a row per
                # instrument for what is bookkeeping rather than a business
                # change — and so the mirrored Trade Finance row is not touched.
                TradeRegisterEntry.objects.filter(pk__in=to_archive).update(
                    is_archived=True, archived_on=today,
                )
            if to_restore:
                TradeRegisterEntry.objects.filter(pk__in=to_restore).update(
                    is_archived=False, archived_on=None,
                )

        self.stdout.write(
            f"archived {len(to_archive)}, restored {len(to_restore)} (as at {today})"
        )
