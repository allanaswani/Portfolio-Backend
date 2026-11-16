"""Prove the Banca DSR live readers against a month the desk filled.

    docker exec hf-backend python manage.py banca_feed_probe --month 2026-10
    docker exec hf-backend python manage.py banca_feed_probe --month 2026-10 --who DSR476

For each insurance-template sheet the insurance report fills, the reader's
figure for every Banca DSR beside the desk's (the stored card of that month).
A sheet reads live on the cards once 70% of the DSRs agree; the result is
stored, and re-running replaces it. See apps/staff_management/banca_live_feeds.py.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prove the Banca DSR live readers against the desk's figures."

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True, help="YYYY-MM the desk filled")
        parser.add_argument("--who", help="one DSR's code or name: show every sheet")

    def handle(self, *args, **o):
        from apps.staff_management import banca_live_feeds

        try:
            when = datetime.datetime.strptime(o["month"], "%Y-%m")
        except ValueError:
            raise CommandError(f"{o['month']!r} is not YYYY-MM")
        banca_live_feeds.probe(when.year, when.month, out=self.stdout.write, who=o["who"])
