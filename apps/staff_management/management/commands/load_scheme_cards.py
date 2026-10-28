"""Compute and store the Scheme scorecards for one month.

    manage.py load_scheme_cards --template "Scheme_Scorecards - Template 2026 V3.xlsm" \\
        --actuals 2026_Actuals_Scheme_Scorecards.xlsx --month 2026-06
    manage.py load_scheme_cards ... --apply
    manage.py load_scheme_cards --delete-month 2026-09 --apply

Every month the actuals workbook holds is computed and stored, so any month
can be opened afterwards; --month limits it to one, refused if the workbook
holds nothing for it. --delete-month removes the cards
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
                            help="YYYY-MM: only this month; default every month "
                                 "the actuals workbook holds")
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
        period = sc.template_period(template)
        year = period.year if period else datetime.date.today().year
        only = None
        if opts["month"]:
            try:
                asked = datetime.datetime.strptime(
                    opts["month"][:7], "%Y-%m").date()
            except ValueError:
                raise CommandError(
                    f"{opts['month']!r} is not a month (YYYY-MM)")
            year, only = asked.year, asked.month
        try:
            by_month, unplaced = sc.compute_months(
                template, actuals,
                lambda m: sc.loaded_figures(datetime.date(year, m, 1)),
                only=only)
        except sc.SchemeCardError as exc:
            raise CommandError(str(exc))

        for month, cards in by_month.items():
            self.stdout.write(
                f"Scheme scorecards - {datetime.date(year, month, 1):%b %Y}")
            for person, result in cards:
                total = result["total"]
                shown = (f"{total:.4%}" if isinstance(total, float)
                         else str(total))
                empty = sum(1 for ln in result["lines"] if ln.get("empty"))
                missing = [ln["kpi"] for ln in result["lines"]
                           if ln["score"] is None and ln["weighted"] is None]
                self.stdout.write(
                    f"  {person.sales_code:8} {person.name:22} "
                    f"{person.sheet:14} {shown:>9}"
                    + (f"   {empty} line(s) with no figure that month"
                       if empty else "")
                    + (f"   not loaded: {', '.join(missing)}"
                       if missing else ""))
        for number, name, role in unplaced:
            self.stdout.write(f"  List row {number}: {name} ({role}) - no "
                              f"Scheme card for that role, or no sales code")

        if not opts["apply"]:
            self.stdout.write("Nothing written. Add --apply to store them.")
            return
        stored = sum(
            sc.store(cards, datetime.date(year, month, 1),
                     loaded_by="load_scheme_cards")
            for month, cards in by_month.items())
        self.stdout.write(self.style.SUCCESS(
            f"Stored {stored} card(s) across {len(by_month)} month(s)."))
