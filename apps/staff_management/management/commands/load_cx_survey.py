"""Load the CX survey workbook from the command line.

    manage.py load_cx_survey "RM Contactability, Satisfaction & Segment NPS & CES Q2 2026.xlsx"
    manage.py load_cx_survey <file> --dry-run
    manage.py load_cx_survey <file> --period 2026-Q2

The screen at Administration → Scorecards → Customer experience does the same
thing and is where CX work. This is for the first load on a host, and for a
quarter somebody would rather not push through a browser.

The period is read off the file name, because CX name the file after the
quarter. ``--period`` is for a file saved as "final v3".
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load CX's contactability and satisfaction workbook."

    def add_arguments(self, parser):
        parser.add_argument("file", help="CX's .xlsx workbook.")
        parser.add_argument(
            "--period", default="",
            help="2026-Q2 or 2026-06. Read off the file name when left out.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Read and report, and write nothing.")

    def handle(self, **options):
        import pathlib

        from apps.staff_management import cx_metrics

        write = self.stdout.write
        path = pathlib.Path(options["file"])

        try:
            with path.open("rb") as handle:
                rm_rows, segments, report = cx_metrics.read_workbook(
                    handle, path.name)
        except FileNotFoundError as exc:
            raise CommandError(f"{path} is not there.") from exc
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(f"That workbook could not be read: {exc}") from exc

        if options["period"]:
            period = cx_metrics.period_of(options["period"])
            for row in rm_rows + segments:
                row["period"] = period
            report["period"] = period

        write("")
        write(f"  period            {report['period']}")
        write(f"  sheets read       {', '.join(report['sheets_read']) or '-'}")
        if report["sheets_missing"]:
            write(self.style.WARNING(
                f"  sheets missing    {', '.join(report['sheets_missing'])}"))
        write(f"  RMs               {report['rm_names']}")
        write(f"  with contactability  "
              f"{sum(1 for r in rm_rows if r['contactability'] is not None)}")
        write(f"  with CSAT            "
              f"{sum(1 for r in rm_rows if r['csat'] is not None)}")
        write(f"  segments          {report['segments']}")

        if report["full_marks"]:
            # Not a warning: it is the business's own rule, and it is right
            # that it shows.
            write("")
            write(f"  {len(report['full_marks'])} RM(s) marked \"give full "
                  f"marks\" - the measure does not apply to them, and their "
                  f"survey lines will score 100% with the reason on the card:")
            for name in report["full_marks"]:
                write(f"      {name}")

        if report["unmatched_names"]:
            # This IS a warning. A name CX spell differently from the roster
            # is an RM who ends the quarter with no survey figure, and it
            # looks exactly like an RM CX did not survey.
            write("")
            write(self.style.WARNING(
                f"  {len(report['unmatched_names'])} name(s) match nobody on "
                f"any roster, so they reach no card. Check the spelling, or "
                f"set the sales code on the screen:"))
            for name in report["unmatched_names"]:
                write(f"      {name!r}")

        if report["ignored_values"]:
            write("")
            write(self.style.WARNING(
                f"  {len(report['ignored_values'])} cell(s) were neither a "
                f"number nor \"give full marks\":"))
            for item in report["ignored_values"][:10]:
                write(f"      {item['sheet']:<16} {item['rm_name']:<28} "
                      f"{item['value']!r}")

        if not rm_rows and not segments:
            raise CommandError(
                "Nothing was read. The workbook needs a Contactability or "
                "Satisfaction sheet with an 'RM Name' column.")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("--dry-run: nothing was written."))
            return

        written = cx_metrics.save(rm_rows, segments, who="load_cx_survey")
        write("")
        write(self.style.SUCCESS(
            f"  Saved {written['rm']} RM figure(s) and "
            f"{written['segments']} segment figure(s) for "
            f"{report['period']}."))

        found = cx_metrics.coverage(report["period"])
        write(f"  {found['matched']} of {found['rm_rows']} reach a card.")
        write("")
