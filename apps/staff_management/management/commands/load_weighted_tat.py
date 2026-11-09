"""Load the desk's monthly Weighted TAT Dashboard from the command line.

    manage.py load_weighted_tat "Weighted TAT Dashboard - 30 Sept 2026.xlsx"

The Live feeds screen does the same thing. The month is read off the file.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Load a Weighted TAT Dashboard so its month's Weighted TAT lines read it."

    def add_arguments(self, parser):
        parser.add_argument("file")

    def handle(self, **options):
        from apps.staff_management import weighted_tat

        with open(options["file"], "rb") as stream:
            found = weighted_tat.read(stream)
        weighted_tat.save(found, options["file"].replace("\\", "/").split("/")[-1],
                          "command")
        self.stdout.write(f"{found['month']:%B %Y}: {len(found['people'])} people, "
                          f"{len(found['branches'])} branches. {'; '.join(found['sheets'])}"
                          + (f" Skipped (no number, e.g. #REF!): {found['skipped']}"
                             if found["skipped"] else ""))
