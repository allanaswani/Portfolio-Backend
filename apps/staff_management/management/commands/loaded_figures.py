"""What has been LOADED for somebody, and what the warehouse says instead.

    manage.py loaded_figures FM4424
    manage.py loaded_figures --zeros
    manage.py loaded_figures --zeros --delete

A loaded figure now beats the warehouse, which is what makes a signed card
authoritative. The cost is that a WRONG loaded figure is invisible: the card
simply shows it, and the figure the warehouse found is not on the page.

That happened. Faith Muthinja's card fell to 27.8% because loaded noughts
were sitting on top of VIC Premiums (warehouse 468,067.25) and Net
Disbursements (warehouse 36,663,806.28). The card is guarded now - a loaded
nought can no longer displace a figure the warehouse found - but the rows are
still in the table, and they will still win on any line the warehouse cannot
read.

``--zeros`` lists every loaded nought across everybody, which is the shape
the problem takes: a template saved with its empty cells intact. ``--delete``
removes them, and only them.

ASCII only in the output: a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show, and optionally clear, the figures loaded for a person."

    def add_arguments(self, parser):
        parser.add_argument("sales_code", nargs="?", default="",
                            help="Whose figures to list.")
        parser.add_argument("--zeros", action="store_true",
                            help="Every loaded nought, across everybody.")
        parser.add_argument("--delete", action="store_true",
                            help="With --zeros, remove them. Nothing else is "
                                 "touched.")
        parser.add_argument("--month", default="",
                            help="YYYY-MM. Default: the last closed month, "
                                 "which is the only one a card reads.")

    def handle(self, **options):
        from apps.staff_management.live_scorecard import last_closed_month_end
        from apps.staff_management.scorecard_automation.models import (
            ScEmployeePerformanceActual)

        write = self.stdout.write

        if options["month"]:
            year, month = options["month"].split("-")
            when = datetime.date(int(year), int(month), 1)
        else:
            when = last_closed_month_end(datetime.date.today()).replace(day=1)

        write("")
        write(f"  month   {when:%B %Y}   (a card reads only the last closed "
              f"month)")

        rows = ScEmployeePerformanceActual.objects.filter(eom_date=when)

        # ── every loaded nought ───────────────────────────────────────────
        if options["zeros"]:
            zeros = rows.filter(kpi_value=0).order_by("sales_code", "kpi_code")
            total = zeros.count()
            write(f"  loaded noughts   {total}")
            write("")
            for row in zeros[:60]:
                write(f"      {(row.sales_code or '?'):<12} {row.kpi_code}")
            if total > 60:
                write(f"      ... and {total - 60} more")

            if not total:
                write("")
                return

            if not options["delete"]:
                write("")
                write("  Nothing was changed. Add --delete to remove these, "
                      "and only these.")
                return

            removed, _ = zeros.delete()
            write("")
            write(self.style.SUCCESS(
                f"  Removed {removed} loaded nought(s). Every other loaded "
                f"figure is untouched, and the cards recompute when they are "
                f"opened."))
            write("")
            return

        # ── one person ────────────────────────────────────────────────────
        code = options["sales_code"].strip()
        if not code:
            write("")
            write("  Give a sales code, or --zeros.")
            write("")
            return

        mine = rows.filter(sales_code__iexact=code).order_by("kpi_code")
        write(f"  {code}   {mine.count()} loaded figure(s)")
        write("")
        for row in mine:
            origin = (getattr(row, "source", "") or "").strip() or "unknown"
            flag = "  <- a nought" if row.kpi_value == 0 else ""
            write(f"      {row.kpi_code:<44} {row.kpi_value:>16,.2f}  "
                  f"{origin}{flag}")
        write("")
        write("  signed-card  beats the warehouse - the agreed record.")
        write("  anything else, including 'unknown', only fills a line the "
              "warehouse could not read.")
        write("  a nought outranks nothing at all, whatever it came from.")
        write("")
