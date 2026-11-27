"""Which HFDI Master Scorecard lines the warehouse can give, person by person.

    python manage.py hfdi_feed_probe                  # the template loaded on the screen
    python manage.py hfdi_feed_probe --people 60

Every HFDI card line reads a sheet of Scorecard_Actual_Template_2026.xlsx
(A staff_id, B name, E..P January..December). For the month the desk last ran
(mapping B4), each template sheet below is set beside the reader the other
books' cards already use for that measure, for every active person on
staff_list: how many agree, and how many of those agreed on a figure other than
nought (agreeing only on noughts proves nothing). HFDI staff have no sales
codes, so readers keyed on a name or PF are the ones that can match.

A line goes live only when its reader gives the desk's figures. Read-only;
counts only, no names or amounts printed.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

#: template sheet -> [(reader keys summed, what it is)]
CANDIDATES = {
    "own_project_sales": [(("property_units",), "property units (HFDI sales return + CRM inventory)")],
    "project_cross_sales": [(("property_units",), "property units (HFDI sales return + CRM inventory)")],
    "sales_value": [(("property_value",), "property value (HFDI sales return + CRM inventory)")],
    "bancassurance_sale": [(("banca_total",), "bancassurance premiums, every product"),
                           (("vic_total",), "VIC (Britam) paid premiums")],
    "mortgage_sale": [(("mortgage_commercial", "mortgage_non_commercial"), "mortgage sales")],
    "bank_accounts": [(("new_accounts",), "new accounts"), (("focus_accounts",), "focus accounts")],
    "accounts_deposits": [(("deposit_growth",), "deposit growth")],
    "training": [(("training_hours",), "training return (by PF)")],
    "leave_mgt": [(("leave_cleared",), "leave cleared (Aruti, by PF)")],
}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class Command(BaseCommand):
    help = "Measure which HFDI template sheets a warehouse reader reproduces."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=datetime.date.today().year)
        parser.add_argument("--people", type=int, default=0,
                            help="check only the first N people (default all)")

    def handle(self, *args, **opts):
        from apps.staff_management import workbook_cards as wc
        from apps.staff_management.live_scorecard import live_actuals

        w = self.stdout.write
        year = opts["year"]
        spec = wc.SPECS[wc.HFDI]
        book, actuals = wc.saved(spec.files[0], year), wc.saved(spec.files[1], year)
        if not book or not actuals:
            raise CommandError(f"Load the {year} HFDI Master Scorecard and its actuals "
                               f"template on Scorecards -> Load the scorecard workbooks first.")
        month = wc.ib_run_month(book)
        as_at = datetime.date(year, month, 1).replace(day=28) + datetime.timedelta(days=4)
        as_at = as_at.replace(day=1) - datetime.timedelta(days=1)
        people = [h for h in wc.holders(book) if h.sheet in book["cards"]]
        if opts["people"]:
            people = people[:opts["people"]]
        w(f"HFDI {year}: {len(people)} active people, the desk's month {month} "
          f"(to {as_at}); template sheets {len(actuals)}")

        # The template's figure per sheet per person (by staff_id, else name).
        col = spec.template_first_month + month - 1
        tmpl = {}
        for sheet in CANDIDATES:
            grid = actuals.get(sheet) or []
            by = {}
            for row in grid[1:]:
                if len(row) <= col:
                    continue
                key_id = str(row[0]).replace(".0", "").strip() if row[0] is not None else ""
                key_name = str(row[1] or "").strip().lower()
                if _num(row[col]):
                    by[key_id] = by[key_name] = float(row[col])
            tmpl[sheet] = by

        wanted = {k for opts_ in CANDIDATES.values() for keys, _ in opts_ for k in keys}
        results = {(s, i): [0, 0, 0] for s, opts_ in CANDIDATES.items()
                   for i in range(len(opts_))}
        for n, h in enumerate(people, 1):
            try:
                got = live_actuals(h.sales_code, staff_name=h.name, staff_pf=h.pf,
                                   branch=str(h.branch or ""), wanted=wanted, as_at=as_at)
            except Exception as exc:  # noqa: BLE001 - next person
                w(f"  person {n}: not read ({type(exc).__name__})")
                continue
            for sheet, opts_ in CANDIDATES.items():
                desk = tmpl[sheet].get(h.sales_code, tmpl[sheet].get(h.name.strip().lower()))
                if desk is None:
                    continue
                for i, (keys, _label) in enumerate(opts_):
                    vals = [(got.get(k) or {}).get("value") for k in keys]
                    if any(v is None for v in vals):
                        continue
                    live = sum(float(v) for v in vals)
                    r = results[(sheet, i)]
                    r[0] += 1
                    if abs(live - desk) <= max(0.5, abs(desk) * 0.005):
                        r[1] += 1
                        if desk != 0:
                            r[2] += 1

        w("\nSHEET                    READER                                         "
          "compared  agree  agree-not-0")
        for sheet, opts_ in CANDIDATES.items():
            with_figures = sum(1 for h in people
                               if tmpl[sheet].get(h.sales_code,
                                                  tmpl[sheet].get(h.name.strip().lower()))
                               is not None)
            for i, (_keys, label) in enumerate(opts_):
                c, a, nz = results[(sheet, i)]
                w(f"{sheet:24} {label[:46]:46} {c:8} {a:6} {nz:12}   "
                  f"(desk figures for {with_figures})")
        w("\nA reader goes live on a sheet only where it agrees for the people the "
          "desk scored, on figures other than nought. Paste this output.")
