"""Find which RM card lines the warehouse gives the desk's figures for.

    docker exec hf-backend python manage.py sales_feed_probe --month 2026-09
    docker exec hf-backend python manage.py sales_feed_probe --month 2026-09 \
        --who AKL3116

Compares, for a month the desk has closed, every RM's card line on the
desk's actuals template with the same line read from the warehouse alone,
and switches on - for the live card - every line the warehouse reproduces.
See apps/staff_management/sales_live_feeds.py.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prove RM card lines against the sales actuals template."

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True,
                            help="YYYY-MM, a month the template has")
        parser.add_argument("--who", help="one RM's sales code or name: show "
                            "their desk figures beside the warehouse's "
                            "instead of probing")

    def handle(self, *args, **options):
        from apps.staff_management import sales_live_feeds

        try:
            when = datetime.datetime.strptime(options["month"], "%Y-%m")
        except ValueError:
            raise CommandError(f"{options['month']!r} is not YYYY-MM")
        if options["who"]:
            sales_live_feeds.explain(when.year, when.month, options["who"],
                                     out=self.stdout.write)
            return
        sales_live_feeds.probe(when.year, when.month, out=self.stdout.write)
