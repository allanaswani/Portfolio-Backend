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
        parser.add_argument("--detail", action="store_true",
                            help="Every person compared: the desk's change and the source's.")

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
        cache.set(f"hfdi_live_proof:v2:{year}:{run}", found, 3600)
        codes = hfdi_live.code_map()
        people = [h for h in wc.holders(book) if h.sheet in book["cards"]]
        from apps.staff_management.live_scorecard import name_tokens

        coded = sum(1 for h in people if frozenset(name_tokens(h.name)) in codes)
        self.stdout.write(f"HFDI {year}, the desk's month {run}: {coded} of {len(people)} "
                          f"people matched to a sales code on hfdi_employee_data")
        for sheet in hfdi_live.CANDIDATES:
            state = "LIVE" if found.get(sheet) else "desk's figure"
            self.stdout.write(f"  {sheet:22} {state:14} {found['_detail'].get(sheet, '')}")
        if opts["detail"]:
            for rule, moved in (found["_detail"].get("_rows") or {}).items():
                self.stdout.write(f"\n  {rule}: code | desk's Sep->Oct change | source's | "
                                  f"desk's Oct figure")
                for code, desk, src, now in sorted(moved, key=lambda m: -abs(m[1] - m[2])):
                    flag = "" if abs(desk - src) <= max(0.5, abs(now) * hfdi_live.TOLERANCE) else "  DIFF"
                    self.stdout.write(f"    {code:10} {desk:>16,.2f} {src:>16,.2f} "
                                      f"{now:>16,.2f}{flag}")
        unmatched = [h.name for h in people if frozenset(name_tokens(h.name)) not in codes]
        if unmatched:
            self.stdout.write(f"\n  {len(unmatched)} people have no sales code by name on "
                              f"hfdi_employee_data: their lines stay the desk's figures.")
