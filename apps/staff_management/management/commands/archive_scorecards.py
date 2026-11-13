"""Archive every scorecard of a month to files and send the complete ones.

    manage.py archive_scorecards                  # the daily job (cron)
    manage.py archive_scorecards --period 2026-10 --final --no-send
                                                  # archive a past month as it stands

Daily cron on the host that serves the site, e.g. 06:30:

    30 6 * * * docker exec hf-backend python manage.py archive_scorecards \
        >> /data/apps/datascience/logs/archive_scorecards.log 2>&1

See apps/staff_management/scorecard_archive.py for the timeline and the files.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Archive the month's scorecards to files; e-mail each complete card once."

    def add_arguments(self, parser):
        parser.add_argument("--period", help="YYYY-MM (default: the month just closed)")
        parser.add_argument("--final", action="store_true",
                            help="Archive every card as it stands, complete or not.")
        parser.add_argument("--no-send", action="store_true", help="Archive only; e-mail nobody.")

    def handle(self, *args, **opts):
        from apps.staff_management import scorecard_archive as sa

        summary = sa.run(period=opts["period"], send=not opts["no_send"],
                         final=True if opts["final"] else None,
                         out=self.stdout.write)
        for code, name, why in summary["failed"]:
            self.stdout.write(f"  PROBLEM  {code:<10} {name}: {why}")
