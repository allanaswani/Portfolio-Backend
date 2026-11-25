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
        # Every line with a reader is READ LIVE on the cards from the month
        # after the desk's. "Proven" says only whether its reader gave the
        # desk's own figures for the desk's month - which decides whether it
        # may score anyone below the desk's figure.
        proven = sorted(f for f, r in result.items() if r["live"])
        zeros = sorted(f for f, r in result.items()
                       if not r["live"] and not r.get("evidence") and r["matched"] == r["people"])
        differ = sorted(set(result) - set(proven) - set(zeros))
        w = self.stdout.write
        w("\nEvery line above is read live on the cards from the month after the desk's.")
        w(f"Proven against the desk's figures: {', '.join(proven) or 'none'}.")
        w(f"Cannot be proven - the desk's figures are all 0: {', '.join(zeros) or 'none'}.")
        w(f"Differ from the desk's figures (an unproven reading never scores anybody "
          f"below the desk's own figure): {', '.join(differ) or 'none'}.")
