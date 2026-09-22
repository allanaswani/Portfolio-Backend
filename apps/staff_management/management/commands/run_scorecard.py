"""Generate the monthly scorecard, from cron rather than by hand.

    manage.py run_scorecard                  # the month that just closed
    manage.py run_scorecard --current        # the month in progress
    manage.py run_scorecard --year 2026 --month 8
    manage.py run_scorecard --dry-run        # compute nothing, just report
    manage.py run_scorecard --force          # write even with no targets

It REFUSES to write when the period has no targets, because every pillar then
scores 0 and everybody grades E - a table full of grade E looks exactly like
real, catastrophic performance, and this runs from cron, so a single missing
target file would otherwise become a permanent daily record of the whole bank
failing. --force overrides that.

Until now the engine could only be reached by POSTing to
``staff_management/employee-monthly-performance/run-scorecard/``. Nothing in
the deployment ever sent that POST - host cron runs ``precompute_slides`` and
``run_insights_pipeline`` and nothing else - so the scorecard only ever moved
when a person remembered to trigger it, and the table stopped at whatever month
that last happened in. This is the same engine, callable from cron.

Note the default period. A scorecard for the month in progress is scored
against a full month's target with a partial month's actuals, so everybody
looks like they are failing until the last day. Run without arguments and you
get the month that has actually closed, which is the one worth grading.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


def _previous_month(today):
    """First day of the month before ``today``."""
    return date(today.year - 1, 12, 1) if today.month == 1 \
        else date(today.year, today.month - 1, 1)


class Command(BaseCommand):
    help = "Compute the monthly employee scorecard (cron-friendly)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int)
        parser.add_argument("--month", type=int)
        parser.add_argument(
            "--current", action="store_true",
            help="Score the month in progress instead of the one that closed.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be scored without writing anything.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Write even when the period has no targets (scores will be 0).",
        )

    def handle(self, *a, **o):
        from apps.staff_management.views import _compute_scorecard

        today = timezone.now().date()
        if o["year"] or o["month"]:
            if not (o["year"] and o["month"]):
                raise CommandError("--year and --month go together.")
            period = date(o["year"], o["month"], 1)
        elif o["current"]:
            period = date(today.year, today.month, 1)
        else:
            period = _previous_month(today)

        w = self.stdout.write
        w(f"Scorecard period: {period:%B %Y}")

        # Without targets for the period every pillar scores 0 and everybody
        # grades E, because _score() returns 0 whenever the target is not
        # positive. Writing that is worse than writing nothing: a table full of
        # grade E is indistinguishable from real, terrible performance, and this
        # runs from cron every morning - so one missing target file would quietly
        # become a permanent record of the whole bank failing.
        #
        # So it refuses by default. --force is there for the case where somebody
        # genuinely wants the zero rows.
        from apps.portfolio_management_enrichment.models import RmTarget
        targets = RmTarget.objects.filter(
            month__year=period.year, month__month=period.month
        ).count()
        w(f"  RmTarget rows for this period: {targets}")

        if not targets and not o["force"]:
            w("")
            w("  REFUSING TO WRITE. With no targets every pillar divides by zero,")
            w("  so every employee would be recorded at 0.00 / grade E - which")
            w("  reads exactly like real failure and would overwrite whatever is")
            w("  already there.")
            w("  Load this period's targets, then run again. Use --force if the")
            w("  zero rows are genuinely what you want.")
            return

        if o["dry_run"]:
            w("  --dry-run: nothing written.")
            return

        results, created, updated = _compute_scorecard(
            period.year, period.month, period
        )
        w(f"  employees processed : {len(results)}")
        w(f"  rows created        : {created}")
        w(f"  rows updated        : {updated}")

        graded = sum(1 for r in results if (r.total_score or 0) > 0)
        w(f"  rows with a score above zero: {graded}")
        if results and not graded:
            # Silence here would look like success. It is not.
            w("")
            w("  EVERY row scored zero. That is not a computation failure - it")
            w("  is what happens when there are no targets for the period, so")
            w("  check RmTarget for this month before believing these grades.")
