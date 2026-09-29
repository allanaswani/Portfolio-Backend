"""Load the Commercial Pipeline workbook into the app.

    python manage.py import_commercial_pipeline "/path/Commercial Pipeline ....xlsx"
    python manage.py import_commercial_pipeline <file> --apply

A dry run unless --apply is given, because it writes to a live table and the
first thing anybody wants is to see what it read.

The parsing lives in ``apps.commercial_pipeline.importer`` because the same
workbook is uploaded through the page, and two copies of the column mapping
would eventually disagree. This command is the path for somebody who already
has a shell on the host; the upload is the path for everybody else, which is
most of the people who keep this spreadsheet.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.commercial_pipeline.importer import parse_workbook
from apps.commercial_pipeline.models import PipelineEntry as P


class Command(BaseCommand):
    help = "Load the Commercial Pipeline workbook into the pipeline table."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the .xlsx file.")
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without it nothing is saved.")
        parser.add_argument("--replace", action="store_true",
                            help="Clear previously imported rows first, so "
                                 "re-running does not duplicate them.")

    def handle(self, *args, **o):
        try:
            entries, warnings, skipped = parse_workbook(o["path"])
        except ImportError:
            raise CommandError("openpyxl is needed: pip install openpyxl")
        except Exception as exc:
            raise CommandError(f"Could not read that file: {exc}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nWhat this read"))
        by_kind = {}
        for e in entries:
            label = e.get_kind_display()
            by_kind[label] = by_kind.get(label, 0) + 1
        for label, count in sorted(by_kind.items()):
            self.stdout.write(f"  {label:<20} {count:>4}")
        self.stdout.write(f"  {'rows without a customer':<20} {skipped:>4} (skipped)")

        if warnings:
            self.stdout.write(self.style.WARNING(
                f"\n{len(warnings)} thing(s) needing a human eye:"))
            for w in warnings[:40]:
                self.stdout.write(f"  {w}")
            if len(warnings) > 40:
                self.stdout.write(f"  ... and {len(warnings) - 40} more")

        if not o["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN - nothing written. {len(entries)} row(s) would be "
                f"created. Re-run with --apply."))
            return

        with transaction.atomic():
            if o["replace"]:
                # Only rows that came from a workbook: created_by is null on
                # those and set on anything an RM typed in the app.
                gone = P.objects.filter(created_by__isnull=True).delete()[0]
                self.stdout.write(f"\nRemoved {gone} previously imported row(s).")
            P.objects.bulk_create(entries, batch_size=200)

        self.stdout.write(self.style.SUCCESS(f"\nCreated {len(entries)} row(s)."))
