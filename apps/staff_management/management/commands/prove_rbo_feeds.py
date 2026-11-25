"""Prove the Retail Back Office card's live lines against the desk's figures.

    python manage.py prove_rbo_feeds [--year 2026]

Each individual line's reader is run for the month the workbook was last run
and compared, person by person, with the figure on the desk's own card. A
line that gives the desk's figure for (nearly) everyone reads live from the
next month on. Prints every comparison; stores the result.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prove the retail back office card's live lines against the desk's figures."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int)

    def handle(self, *args, **opts):
        from apps.staff_management import rbo_live_feeds

        try:
            result = rbo_live_feeds.prove(opts.get("year"), out=self.stdout.write)
        except RuntimeError as exc:
            raise CommandError(str(exc))
        live = sorted(f for f, r in result.items() if r["live"])
        self.stdout.write(f"\nLive: {', '.join(live) or 'none'}.")
        self.stdout.write(f"Not live: {', '.join(sorted(set(result) - set(live))) or 'none'}.")
