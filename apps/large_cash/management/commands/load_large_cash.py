"""Read the large cash transactions off the lake now, in the foreground.

    python manage.py load_large_cash                 # the days due
    python manage.py load_large_cash --start 2026-11-01 --end 2026-11-20

The dashboard also reads them itself, at most once an hour, behind the page.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.large_cash import lake


class Command(BaseCommand):
    help = "Load cash transactions of KES 500,000 and above from the lake."

    def add_arguments(self, parser):
        parser.add_argument("--start")
        parser.add_argument("--end")

    def handle(self, *args, **opts):
        try:
            start = datetime.date.fromisoformat(opts["start"]) if opts["start"] else None
            end = datetime.date.fromisoformat(opts["end"]) if opts["end"] else start
        except ValueError as exc:
            raise CommandError(f"Dates are YYYY-MM-DD: {exc}")
        report = lake.refresh(loaded_by="load_large_cash", start=start, end=end)
        self.stdout.write(
            f"Read {report.get('read', 0)} large cash transaction(s), "
            f"{report.get('start')} to {report.get('end')}. The lake's newest "
            f"day is {report.get('lake_latest')}.")
