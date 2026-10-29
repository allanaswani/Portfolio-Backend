"""Find which warehouse counts give the desk's back-office figures.

    docker exec hf-backend python manage.py bo_feed_probe --month 2026-09

Compares, for a month the desk has closed, each teller's transaction counts
in transaction_diary with the figure on the back-office actuals template,
and switches on - for the live card - every sheet the warehouse reproduces.
See apps/staff_management/bo_live_feeds.py.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prove back-office live feeds against the actuals template."

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True,
                            help="YYYY-MM, a month the template has")

    def handle(self, *args, **options):
        from apps.staff_management import bo_live_feeds

        try:
            when = datetime.datetime.strptime(options["month"], "%Y-%m")
        except ValueError:
            raise CommandError(f"{options['month']!r} is not YYYY-MM")
        bo_live_feeds.probe(when.year, when.month, out=self.stdout.write)
