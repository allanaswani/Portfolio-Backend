"""Load who reports to whom from the scorecard workbooks and the rosters.

    manage.py load_reporting_lines "BB_Scorecards.xlsb" "Portfolio.xlsb" --apply
    manage.py load_reporting_lines --rosters --apply

Without --apply it only reports. See apps/staff_management/reporting_lines.py.
"""

from django.core.management.base import BaseCommand

from apps.staff_management import reporting_lines as lines


class Command(BaseCommand):
    help = "Load reporting lines from scorecard workbooks and the rosters."

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="*", help="Workbooks or sheets to read.")
        parser.add_argument("--rosters", action="store_true",
                            help="Also read the DMC roster and the DSR list.")
        parser.add_argument("--apply", action="store_true", help="Save the result.")

    def handle(self, *args, **options):
        apply = options["apply"]
        for path in options["files"]:
            with open(path, "rb") as held:
                upload = _Named(held, path)
                source, found = lines.lines_from_rows(lines.read_rows(upload))
            found = lines.use_branch_manager_page(found)
            kinds = sorted({line["line_kind"] for line in found})
            counts = lines.save(found, source, apply=apply,
                                kinds=kinds if source == "upload" else None)
            self.stdout.write(f"{path}: {source}, {len(found)} lines, {kinds}, {counts}")
        if options["rosters"]:
            found = lines.lines_from_rosters()
            counts = lines.save(found, "rosters", apply=apply)
            self.stdout.write(f"rosters: {len(found)} lines, {counts}")
        if not apply:
            self.stdout.write("Nothing saved. Add --apply to save.")


class _Named:
    """A file object with the name read_rows looks at."""

    def __init__(self, held, name):
        self._held, self.name = held, name

    def __getattr__(self, attr):
        return getattr(self._held, attr)
