"""Show how the Retail Back Office analysts appear in iApply, and what each
reading of their TAT lines gives against the desk's own figures.

    python manage.py rbo_tat_explain [--month 2026-09]

Prints, per analyst on the workbook's List (every holder of a TAT / RTS /
category line):
  * every ActionUserName and ActionUser in iapply_loan_tat that carries the
    person's surname, with how many actions each has in the month;
  * for each TAT line, the desk's figure and what every reading gives.
Reads only; changes nothing.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Explain the retail back office analysts' iApply TAT lines."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="YYYY-MM; default the workbook's run month")

    def handle(self, *args, **opts):
        from django.db import connection

        from apps.staff_management import rbo_live_feeds as rlf
        from apps.staff_management import workbook_cards as wc

        spec = wc.SPECS[wc.RETAIL_BO]
        year = datetime.date.today().year
        book, actuals = wc.saved(spec.files[0], year), wc.saved(spec.files[1], year)
        if book is None or actuals is None:
            raise CommandError("Load the retail back office scorecards workbook first.")
        if opts.get("month"):
            year, month = (int(p) for p in opts["month"].split("-"))
        else:
            month = wc.rbo_run_month(book)
        w = self.stdout.write

        # Who holds an iApply line, from the cards themselves.
        feeds_by_sheet = {}
        for sheet, card in book["cards"].items():
            for key, tokens in card["f"].items():
                r, c = (int(x) for x in key.split(","))
                feed = wc._txt(wc._at(card["grid"], r, spec.cols["feed"]))
                if c == spec.cols["actual"] and feed in rlf.IAPPLY_FEEDS:
                    feeds_by_sheet.setdefault(sheet, set()).add(feed)
        people = [h for h in wc.holders(book, keep_off=True) if h.sheet in feeds_by_sheet]
        first = datetime.date(year, month, 1)
        after = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        w(f"Month {year}-{month:02d}; {len(people)} people hold an iApply line.\n")

        users = rlf.iapply_users(year, month, wait=True) or {}
        w(f"The role view has {len(users)} ActionUserName(s) acting in the month.\n")
        for holder in people:
            surname = holder.name.split()[-1]
            w(f"== {holder.sales_code}  {holder.name}  ({holder.sheet})")
            with connection.cursor() as cur:
                cur.execute(
                    'SELECT "ActionUserName", "ActionUser", count(*) FROM iapply_loan_tat '
                    'WHERE ("ActionUserName" ILIKE %s OR "ActionUser" ILIKE %s) '
                    'AND "ActionDate"::text >= %s AND "ActionDate"::text < %s '
                    'GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12',
                    [f"%{surname}%", f"%{surname}%", first.isoformat(), after.isoformat()])
                found = cur.fetchall()
            if not found:
                w(f"   iApply: nobody with '{surname}' in ActionUserName or ActionUser in the month")
            for name, login, n in found:
                w(f"   iApply: ActionUserName={name!r}  ActionUser={login!r}  actions={n}")
            every = {}
            for m in range(1, month + 1):
                every.update(rlf.iapply_users(year, m, wait=True) or {})
            login, how = rlf.login_for(holder.sales_code, holder.name, every)
            w(f"   sign-in used: {login or 'NONE'} - {how}")
            for feed in sorted(feeds_by_sheet[holder.sheet]):
                row = wc._template_row(actuals, feed, holder.sales_code, 0, holder.name)
                desk = row[6 + month - 1] if row and len(row) > 6 + month - 1 else None
                readings = []
                for definition in rlf.DEFINITIONS.get(feed, rlf.IAPPLY_DEFINITIONS):
                    v, _label, why = rlf.iapply_value(feed, holder.name, year, month,
                                                      definition, wait=True,
                                                      code=holder.sales_code)
                    readings.append(f"{definition}={'-' if v is None else f'{v:,.2f}'}")
                w(f"   {feed:<14} desk {('-' if desk is None else desk)!s:>8}   " + "  ".join(readings))
            w("")
