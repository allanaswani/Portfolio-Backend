"""Load HR's monthly training return.

    manage.py load_training_returns "2026 Training Returns Template - Aug_26.xlsx"
    manage.py load_training_returns <file> --dry-run

The screen at Administration → Scorecards → Training returns does the same
thing. This is for the first load on a host and for a month somebody would
rather not push through a browser.

A training line sits on every one of the 22 cards and none of them could be
scored before this. The return is a full year to date each month, so loading
the newest file corrects every month in it.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load the monthly training return into sc_training_return."

    def add_arguments(self, parser):
        parser.add_argument("file", help="HR's .xlsx return.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Read and report what would be written, and write nothing.")

    def handle(self, **options):
        import pathlib

        from apps.staff_management import training

        write = self.stdout.write
        path = pathlib.Path(options["file"])

        try:
            with path.open("rb") as handle:
                rows, report = training.read_workbook(handle, path.name)
        except FileNotFoundError as exc:
            raise CommandError(f"{path} is not there.") from exc
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(
                f"That workbook could not be read: {exc}") from exc

        write("")
        write(f"  sheets read       {', '.join(report['sheets_read']) or '-'}")
        for skipped in report["sheets_skipped"]:
            # Two of the ten sheets are pivots of averages and are SUPPOSED to
            # be skipped. Naming them is how somebody tells that apart from a
            # sheet that failed to parse.
            write(f"  skipped           {skipped['sheet']} - {skipped['why']}")
        write(f"  people            {report['people']}")
        write(f"  month columns     {len(report['months'])}"
              + (f"  ({report['months'][0]} to {report['months'][-1]})"
                 if report["months"] else ""))
        write(f"  figures           {len(rows):,}")

        if report["no_identity"]:
            write(self.style.WARNING(
                f"  {report['no_identity']} row(s) carried hours but no PF "
                f"and no staff code, so they belong to nobody and were not "
                f"loaded. A cumulative-target row at the foot of a sheet "
                f"looks exactly like this, which is usually what they are."))
        if report["ignored_values"]:
            write(self.style.WARNING(
                f"  {len(report['ignored_values'])} cell(s) were not a "
                f"number:"))
            for item in report["ignored_values"][:10]:
                write(f"      {item['sheet']:<24} {item['person']:<28} "
                      f"{item['month']}  {item['value']!r}")

        if not rows:
            raise CommandError(
                "Nothing was read. The return needs a sheet with a StaffPF or "
                "staff-code column and a column per month.")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("--dry-run: nothing was written."))
            return

        written = training.save(rows, who="load_training_returns")
        write("")
        write(self.style.SUCCESS(f"  Saved {written:,} figure(s)."))

        found = training.coverage()
        write(f"  {found['people']} people, {found['hours']:,.1f} hours, "
              f"to {found['latest_month']:%B %Y}"
              if found["latest_month"] else "  nothing loaded")
        if found["without_a_pf"]:
            # The PF is the key that matches. A row without one can only be
            # found by its sales code, and that is the spelling that differs
            # between the return and the roster.
            write(self.style.WARNING(
                f"  {found['without_a_pf']} person(s) have no PF number on "
                f"the return, so they can only be matched on their sales "
                f"code - which is the spelling that goes wrong."))
        write("")
