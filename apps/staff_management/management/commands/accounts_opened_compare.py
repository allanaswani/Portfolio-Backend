"""Why "accounts opened / new customers" differs between the scorecard, the
weighted dashboard and the portfolio tool, for one person, month by month.

    python manage.py accounts_opened_compare "Fredrick Anampiu" --months 2026-10 2026-11
    python manage.py accounts_opened_compare FA1234

Prints, per month (January to that month, as the card counts):
  * the card's customer/account lines and their figure (build_card);
  * the weighted sales report's rule over daily_sales_accounts_with_cto
    (funded, new to the bank this year, not closed, first row) - the figure the
    card's New Customers line follows and the desk's dashboard is built from;
  * every customer on the new-account return under the code, no filters;
  * the portfolio tool: accounts.opened_by this year (its tile is the length
    of its list, which groups by customer, account name AND branch);
and for the last month, how many customers each rule drops and how many the
two sources disagree on. Counts only: no customer names are printed.
"""
import calendar
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PATTERN = ("account", "customer", "casa")


def _month_end(y, m, today):
    end = datetime.date(y, m, calendar.monthrange(y, m)[1])
    return min(end, today)


class Command(BaseCommand):
    help = "Compare accounts opened / new customers across card, weighted dashboard and portfolio tool."

    def add_arguments(self, parser):
        parser.add_argument("who", help="sales code, or part of the person's name")
        parser.add_argument("--months", nargs="+", default=None,
                            help="YYYY-MM ... (default: last month and this month)")

    def _code(self, who):
        from apps.staff_management.live_scorecard import resolve_person
        from apps.staff_management.management.commands.card_doctor import _by_name

        # Every roster the card itself uses (workbook Lists, DMC, role
        # history, staff_employee_data): back-office staff are on no sales table.
        person = resolve_person(who.strip())
        if person is not None:
            return who.strip().upper(), person.name or ""
        rows = _by_name(who)
        if not rows:
            raise CommandError(f"{who!r} is on no roster, as a code or as a name")
        if len({r[0].strip().upper() for r in rows}) > 1:
            listing = "\n".join(f"  {c}  {n}" for c, n in rows)
            raise CommandError(f"More than one match - run again with the sales code:\n{listing}")
        return rows[0][0].strip().upper(), rows[0][1]

    def handle(self, *args, **opts):
        import pandas as pd

        from apps.staff_management import live_scorecard as ls
        from apps.staff_management import weighted_sales_new_customers as wnc
        from services import portfolio_service as svc

        code, name = self._code(opts["who"])
        today = datetime.date.today()
        if opts["months"]:
            months = [tuple(int(x) for x in s.split("-")) for s in opts["months"]]
        else:
            prev = today.replace(day=1) - datetime.timedelta(days=1)
            months = [(prev.year, prev.month), (today.year, today.month)]
        w = self.stdout.write
        w(f"{name}  ({code})   run {today}")

        frames = {}
        for y in {y for y, _ in months}:
            names, rows = wnc._rows(y, 300_000)
            frames[y] = pd.DataFrame(rows, columns=names)

        for y, m in months:
            as_at = _month_end(y, m, today)
            w(f"\n=== {calendar.month_name[m]} {y}  (January to {as_at}) ===")
            try:
                card = ls.build_card(code, as_at=as_at)
                found = False
                for p in card.get("perspectives", []):
                    for line in p.get("lines", []):
                        label = f"{line.get('kpi_code')} {line.get('kpi_name')}".lower()
                        if any(k in label for k in PATTERN):
                            found = True
                            w(f"  CARD  {line.get('kpi_name')} [{line.get('kpi_code')}]: "
                              f"{line.get('ytd_actual')}  (as at {line.get('as_at') or '-'})")
                if not found:
                    w("  CARD  no customer/account line on this person's card")
            except Exception as exc:  # noqa: BLE001 - say why, keep comparing
                w(f"  CARD  could not be built: {exc}")

            ytd = wnc.count_by_seller(frames[y], y, m).get(code, 0)
            prior = wnc.count_by_seller(frames[y], y, m - 1).get(code, 0) if m > 1 else 0
            w(f"  WEIGHTED RULE (funded, new, not closed, first row): {ytd} YTD; "
              f"{ytd - prior} opened in the month")

            df = frames[y].copy()
            df.columns = [str(c).lower() for c in df.columns]
            df["sale_code"] = (df["sale_code"].astype(str).str.replace(" ", "", regex=False)
                               .replace(wnc.SALE_CODE_FIXES).str.upper())
            opened = pd.to_datetime(df["cust_open_date"], errors="coerce")
            mine = df[(df["sale_code"] == code) & (opened.dt.year == y) & (opened.dt.month <= m)]
            w(f"  NEW-ACCOUNT RETURN, no filters: {mine['cust_cif'].nunique()} customers, "
              f"{len(mine)} accounts under {code}")

        y, m = months[-1]
        w(f"\n=== Why they differ ({calendar.month_name[m]} {y} YTD) ===")
        df = frames[y].copy()
        df.columns = [str(c).lower() for c in df.columns]
        df = df.rename(columns=wnc.RENAMES)
        df["sale_code"] = (df["sale_code"].astype(str).str.replace(" ", "", regex=False)
                           .replace(wnc.SALE_CODE_FIXES).str.upper())
        df = df.fillna(0)
        first = ~df["cust_cif"].duplicated()
        opened = pd.to_datetime(df["cust_open_date"], errors="coerce")
        mine = (df["sale_code"] == code) & (opened.dt.year == y) & (opened.dt.month <= m)
        funded = ((pd.to_numeric(df["cust_cto"], errors="coerce").fillna(0) > 0)
                  | (pd.to_numeric(df["current_year_bal"], errors="coerce").fillna(0) > 0))
        # The report judges each customer on its FIRST row in the table (after
        # STAFF / INTERNAL rows are removed), so each customer gets exactly one
        # reason: the first rule its first row fails. The reasons add up.
        seg_out = df["customer_segment"].isin(["STAFF", "INTERNAL ACCOUNTS"])
        cust = set(df.loc[mine, "cust_cif"].astype(str))
        kept = df[~seg_out]
        first_rows = kept[~kept["cust_cif"].duplicated()].set_index(kept["cust_cif"].astype(str)[~kept["cust_cif"].duplicated()])
        reasons = {}
        for cif in cust:
            if cif not in first_rows.index:
                reasons[cif] = "staff / internal-accounts segment"
                continue
            r = first_rows.loc[cif]
            r_open = pd.to_datetime(r["cust_open_date"], errors="coerce")
            r_funded = (pd.to_numeric(r["cust_cto"], errors="coerce") or 0) > 0 or \
                       (pd.to_numeric(r["current_year_bal"], errors="coerce") or 0) > 0
            if r["sale_code"] != code or r_open.year != y or r_open.month > m:
                reasons[cif] = "first row is another seller or outside the period"
            elif r["total_accounts_before_current_year"] != 0:
                reasons[cif] = "already a customer before this year"
            elif not r_funded:
                reasons[cif] = "not funded (no balance, no turnover) today"
            elif r["account_status"] == "CLOSED":
                reasons[cif] = "first account is CLOSED"
            else:
                reasons[cif] = "COUNTED"
        w(f"  {len(cust)} customers on the return under {code}, one reason each:")
        for label in ("COUNTED", "staff / internal-accounts segment", "already a customer before this year",
                      "not funded (no balance, no turnover) today", "first account is CLOSED",
                      "first row is another seller or outside the period"):
            w(f"    {sum(1 for v in reasons.values() if v == label):5}  {label}")

        with connection.cursor() as cur:
            cur.execute("""SELECT DISTINCT a.cust_id::text FROM accounts a
                           LEFT JOIN customers c ON a.cust_id = c.cust_id
                           WHERE a.opened_by = %s
                             AND date_trunc('year', c.open_date) = date_trunc('year', now())""", [code])
            portfolio = {r[0] for r in cur.fetchall()}
        tile = len(svc.rm_new_customers_ytd_list(code))
        w(f"\n  PORTFOLIO TOOL (accounts.opened_by, year to today {today}): "
          f"{len(portfolio)} distinct customers; its tile shows {tile} rows")
        allyear = set(df.loc[(df["sale_code"] == code) & (opened.dt.year == y), "cust_cif"].astype(str))
        w(f"    on both sources: {len(portfolio & allyear)}; only opened_by={code}: "
          f"{len(portfolio - allyear)}; only sale_code={code} on the return: {len(allyear - portfolio)}")
        w("\nThe desk's dashboard is this weighted rule run on the day they ran it: 'funded' is that"
          "\nday's balance, so a customer funded or emptied since then moves the count.")
