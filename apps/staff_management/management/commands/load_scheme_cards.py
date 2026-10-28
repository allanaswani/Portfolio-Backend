"""Compute and store the Scheme scorecards for one month.

    manage.py load_scheme_cards --template "Scheme_Scorecards - Template 2026 V3.xlsm" \\
        --actuals 2026_Actuals_Scheme_Scorecards.xlsx --month 2026-06
    manage.py load_scheme_cards ... --apply
    manage.py load_scheme_cards --delete-month 2026-09 --apply

The month defaults to the template's own (Constants!B4). A month the actuals
workbook holds no figures for is refused. --delete-month removes the cards
stored for a month that should never have been loaded.

Reports every card first and writes only with --apply. The cards are the
template's formulas over the actuals workbook, exactly - see
``apps.staff_management.scheme_cards``.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compute the Scheme scorecards for a month from the desk's workbooks."

    def add_arguments(self, parser):
        parser.add_argument("--template", default="",
                            help="Scheme_Scorecards - Template 2026 V3.xlsm")
        parser.add_argument("--actuals", default="",
                            help="2026_Actuals_Scheme_Scorecards.xlsx")
        parser.add_argument("--delete-month", default="",
                            help="YYYY-MM: remove the cards stored for it")
        parser.add_argument("--month", default="",
                            help="YYYY-MM; defaults to the template's own "
                                 "review month (Constants!B4)")
        parser.add_argument("--apply", action="store_true",
                            help="write the cards; without it, only report")

    def handle(self, *args, **opts):
        import openpyxl

        from apps.staff_management import scheme_cards as sc
        from apps.staff_management.models import SchemeScorecard

        if opts["delete_month"]:
            try:
                gone = datetime.datetime.strptime(
                    opts["delete_month"][:7], "%Y-%m").date()
            except ValueError:
                raise CommandError(
                    f"{opts['delete_month']!r} is not a month (YYYY-MM)")
            rows = SchemeScorecard.objects.filter(month=gone)
            self.stdout.write(f"{rows.count()} Scheme card(s) stored for "
                              f"{gone:%b %Y}: "
                              + ", ".join(rows.values_list("sales_code",
                                                           flat=True)))
            if not opts["apply"]:
                self.stdout.write("Nothing removed. Add --apply.")
                return
            removed, _ = rows.delete()
            self.stdout.write(self.style.SUCCESS(f"Removed {removed}."))
            return

        if not (opts["template"] and opts["actuals"]):
            raise CommandError("Give --template and --actuals.")
        template = openpyxl.load_workbook(opts["template"], data_only=True,
                                          read_only=True)
        actuals = openpyxl.load_workbook(opts["actuals"], data_only=True,
                                         read_only=True)
        if opts["month"]:
            try:
                month_start = datetime.datetime.strptime(
                    opts["month"][:7], "%Y-%m").date()
            except ValueError:
                raise CommandError(
                    f"{opts['month']!r} is not a month (YYYY-MM)")
        else:
            month_start = sc.template_period(template)
            if month_start is None:
                raise CommandError("The template does not say its month; "
                                   "give --month YYYY-MM.")
        try:
            cards, unplaced, _month = sc.compute_all(
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
