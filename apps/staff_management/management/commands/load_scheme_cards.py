"""Compute and store the Scheme scorecards for one month.

    manage.py load_scheme_cards --template "Scheme_Scorecards - Template 2026 V3.xlsm" \\
        --actuals 2026_Actuals_Scheme_Scorecards.xlsx --month 2026-06
    manage.py load_scheme_cards ... --apply

Reports every card first and writes only with --apply. The cards are the
template's formulas over the actuals workbook, exactly - see
``apps.staff_management.scheme_cards``.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compute the Scheme scorecards for a month from the desk's workbooks."

    def add_arguments(self, parser):
        parser.add_argument("--template", required=True,
                            help="Scheme_Scorecards - Template 2026 V3.xlsm")
        parser.add_argument("--actuals", required=True,
                            help="2026_Actuals_Scheme_Scorecards.xlsx")
        parser.add_argument("--month", required=True, help="YYYY-MM")
        parser.add_argument("--apply", action="store_true",
                            help="write the cards; without it, only report")

    def handle(self, *args, **opts):
        import openpyxl

        from apps.staff_management import scheme_cards as sc

        try:
            month_start = datetime.datetime.strptime(
                opts["month"][:7], "%Y-%m").date()
        except ValueError:
            raise CommandError(f"{opts['month']!r} is not a month (YYYY-MM)")

        template = openpyxl.load_workbook(opts["template"], data_only=True,
                                          read_only=True)
        actuals = openpyxl.load_workbook(opts["actuals"], data_only=True,
                                         read_only=True)
        try:
            cards, unplaced = sc.compute_all(
                template, actuals, month_start.month,
                sc.loaded_figures(month_start))
        except sc.SchemeCardError as exc:
            raise CommandError(str(exc))

        self.stdout.write(f"Scheme scorecards - {month_start:%b %Y}")
        for person, result in cards:
            total = result["total"]
            shown = f"{total:.4%}" if isinstance(total, float) else str(total)
            missing = [ln["kpi"] for ln in result["lines"]
                       if ln["score"] is None and ln["weighted"] is None]
            self.stdout.write(
                f"  {person.sales_code:8} {person.name:22} {person.sheet:14} "
                f"{shown:>9}"
                + (f"   not loaded: {', '.join(missing)}" if missing else ""))
        for number, name, role in unplaced:
            self.stdout.write(f"  List row {number}: {name} ({role}) - no "
                              f"Scheme card for that role, or no sales code")

        if not opts["apply"]:
            self.stdout.write("Nothing written. Add --apply to store them.")
            return
        stored = sc.store(cards, month_start, loaded_by="load_scheme_cards")
        self.stdout.write(self.style.SUCCESS(f"Stored {stored} card(s)."))
