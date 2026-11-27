"""Which HFDI sheets are live, on which of the properties report's rules, and
why the others are not.

    python manage.py hfdi_live_check

Runs the same proof the live card uses (hfdi_live.proof) on the loaded HFDI
workbook and template, fresh. Read-only; counts only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Show which HFDI template sheets are live and why the others are not."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=datetime.date.today().year)

    def handle(self, *args, **opts):
        from django.core.cache import cache

        from apps.staff_management import hfdi_live
        from apps.staff_management import workbook_cards as wc

        year = opts["year"]
        spec = wc.SPECS[wc.HFDI]
        book, actuals = wc.saved(spec.files[0], year), wc.saved(spec.files[1], year)
        if not book or not actuals:
            raise CommandError("Load the HFDI Master Scorecard and its template first.")
        run = wc.ib_run_month(book)
        found = hfdi_live.proof(book, actuals, year)
        cache.set(f"hfdi_live_proof:v1:{year}:{run}", found, 3600)
        codes = hfdi_live.code_map()
        people = [h for h in wc.holders(book) if h.sheet in book["cards"]]
        from apps.staff_management.live_scorecard import name_tokens

        coded = sum(1 for h in people if frozenset(name_tokens(h.name)) in codes)
        self.stdout.write(f"HFDI {year}, the desk's month {run}: {coded} of {len(people)} "
                          f"people matched to a sales code on hfdi_employee_data")
        for sheet in hfdi_live.CANDIDATES:
            state = "LIVE" if found.get(sheet) else "desk's figure"
            self.stdout.write(f"  {sheet:22} {state:14} {found['_detail'].get(sheet, '')}")
        unmatched = [h.name for h in people if frozenset(name_tokens(h.name)) not in codes]
        if unmatched:
            self.stdout.write(f"\n  {len(unmatched)} people have no sales code by name on "
                              f"hfdi_employee_data: their lines stay the desk's figures.")
