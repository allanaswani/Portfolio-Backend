"""The monthly Referrals report: a short note, with the figures as an Excel workbook.

    0 7 1 * * docker exec hf-backend python manage.py send_referrals_report
    manage.py send_referrals_report --dry-run                     # print, send nothing
    manage.py send_referrals_report --dry-run --xlsx /tmp/r.xlsx  # and write the file
    manage.py send_referrals_report --month 2026-10               # a particular month

Default month: last month (Nairobi). Run from ONE host only (the old host,
128.2.1.25), or every recipient gets it twice.

Goes to everybody ticked for "Referrals Report" under Administration -> Alerts,
from the same reports address as the other reports. What it holds is described
in :mod:`apps.referrals.report`; supervisors can also download the same workbook
for any month from the Referrals screen.
"""

import re

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("E-mail last month's referrals (HFCB staff and Postbank) to the "
            "referrals-report recipients, with the figures as an Excel file.")

    def add_arguments(self, parser):
        parser.add_argument("--month", default="",
                            help="YYYY-MM; default last month (Nairobi)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--xlsx", default="",
                            help="with --dry-run, also write the workbook to "
                                 "this file to look at")

    def handle(self, *args, **options):
        import datetime

        from apps.observability import alerts, report_xlsx
        from apps.referrals import report

        if options["month"]:
            match = re.fullmatch(r"(\d{4})-(\d{2})", options["month"].strip())
            if not match or not 1 <= int(match.group(2)) <= 12:
                raise CommandError(f"{options['month']!r} is not YYYY-MM")
            year, month = int(match.group(1)), int(match.group(2))
        else:
            year, month = report.previous_month()

        body = report.build_body(year, month)
        workbook = report.workbook(year, month)
        if options["dry_run"]:
            self.stdout.write(body)
            if options["xlsx"]:
                with open(options["xlsx"], "wb") as out:
                    out.write(workbook)
                self.stdout.write(f"Workbook written to {options['xlsx']}")
            return
        label = datetime.date(year, month, 1).strftime("%B %Y")
        count = alerts.send(
            alerts.AlertRecipient.KIND_REFERRALS_REPORT,
            f"Referrals report - {label}", body,
            attachments=[(report.filename(year, month), workbook,
                          report_xlsx.XLSX_MIME)])
        self.stdout.write(f"referrals report sent to {count} recipient(s)")
