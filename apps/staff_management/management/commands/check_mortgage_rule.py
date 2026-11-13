"""Which drawdowns does the desk count as a Mortgage ARM's mortgage sales?

    manage.py check_mortgage_rule --month 2026-09
    manage.py check_mortgage_rule --month 2026-09 --save

For every holder of the two "Net Mortgage sales" lines in the sales
scorecards workbook, the desk's year to date for the month beside the
warehouse's, two ways:

* A - MORTGAGE products only (product_mapping.loan_category), the drawdown
  report's Mortgage sheets;
* B - those plus SECURED loans of any category (a secured business loan).

Michael Odhiambo, Sep 2026: non-commercial 64,678,411 on both the desk and
A, but commercial 120,200,000 on the desk against 80,200,000 on A - and he
drew 80,000,000 of secured business loans. ``--save`` keeps B for the cards
only when B matches more holders than A. Prints; writes only with --save.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

TOLERANCE = 0.02


def _close(desk, got):
    return abs(desk - got) <= max(1.0, TOLERANCE * abs(desk))


class Command(BaseCommand):
    help = "Prove which drawdowns the desk counts in the mortgage lines."

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True, help="YYYY-MM the desk filled")
        parser.add_argument("--save", action="store_true",
                            help="keep rule B for the cards if it matches better")

    def handle(self, *args, **o):
        from apps.staff_management import live_scorecard as ls
        from apps.staff_management.workbook_cards import (
            SALES, SPECS, _key, compute, holders, save_file, saved)

        try:
            when = datetime.datetime.strptime(o["month"], "%Y-%m").date()
        except ValueError:
            raise CommandError(f"{o['month']!r} is not YYYY-MM")
        end = (when.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) \
            - datetime.timedelta(days=1)
        spec = SPECS[SALES]
        book, actuals = saved(spec.files[0], when.year), saved(spec.files[1], when.year)
        if book is None or actuals is None:
            raise CommandError("Load the sales scorecards workbook and actuals template first.")
        w = self.stdout.write
        score = {"A": 0, "B": 0}
        tested = 0
        for h in holders(book):
            if not h.sales_code:
                continue
            try:
                lines = compute(book, actuals, h, when.month)["lines"]
            except Exception:  # noqa: BLE001 - not every sheet computes for every month
                continue
            desk = {}
            for wl in lines:
                k = _key(wl["measure"] or "")
                if "netmortgagesales" not in k:
                    continue
                desk["non" if "noncommercial" in k else "com"] = wl["actual"]
            if not desk or not any(isinstance(v, (int, float)) and v for v in desk.values()):
                continue
            got = {}
            for rule, secured in (("A", False), ("B", True)):
                rows = ls.mortgage_drawdowns(h.sales_code, when.year, up_to=end,
                                             secured_loans=secured)
                got[rule] = (sum(r["net"] for r in rows if r["market"]),
                             sum(r["net"] for r in rows if not r["market"]))
            tested += 1
            marks = []
            for rule in ("A", "B"):
                ok = all(_close(float(desk[part] or 0), got[rule][i])
                         for i, part in enumerate(("com", "non")) if part in desk)
                score[rule] += ok
                marks.append(f"{rule}{' ok' if ok else '   '}")
            w(f"{h.sales_code:<10} {str(h.name)[:24]:<24} desk "
              f"{float(desk.get('com') or 0):>14,.0f} {float(desk.get('non') or 0):>14,.0f} | "
              f"A {got['A'][0]:>14,.0f} {got['A'][1]:>14,.0f} | "
              f"B {got['B'][0]:>14,.0f} {got['B'][1]:>14,.0f}  {' '.join(marks)}")
        if not tested:
            w(f"No holder of the mortgage lines has a desk figure for {when:%b %Y}.")
            return
        w(f"\n{tested} holder(s), {when:%b %Y}: A (mortgage products) matched "
          f"{score['A']}, B (plus secured loans) matched {score['B']}.")
        better = score["B"] > score["A"]
        if o["save"]:
            save_file(ls.MORTGAGE_RULE_KIND,
                      {"secured_loans": better, "month": o["month"],
                       "A": score["A"], "B": score["B"], "tested": tested},
                      f"check {o['month']}", "check_mortgage_rule")
            w("Cards now count " + ("MORTGAGE products plus SECURED loans."
                                     if better else "MORTGAGE products only."))
