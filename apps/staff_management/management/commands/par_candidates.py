"""Which PAR definition gives the desk's figures? Reads only.

    manage.py par_candidates --month 2026-09

No ETL script computes PAR per RM, and the card's reader matched 15% of the
desk's September figures. This tries each plausible definition over the
``loans`` table at the month end, per RM, and counts how many of the desk's
non-zero PAR figures (the sales actuals template's PAR sheet) it reproduces:

* whose loans: the RM's allocated customers (retail_allocated_portfolio), or
  the loans' account_officer;
* overdue part: total_arrears, or the balance of loans 1+, 31+ or 91+ days in
  arrears;
* against: capital_balance, total_capital_balance or euro_book_balance.

The loan officer's book on the lake (eom_loans) was tried from a laptop first:
the best definition matched 4 of 68.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import connection

BOOKS = {
    "allocated customers": """
        SELECT DISTINCT TRIM(sales_code) AS code, cust_id::text AS cust
        FROM retail_allocated_portfolio WHERE sales_code IS NOT NULL""",
    "account officer": None,
}
OVERDUE = {
    "total_arrears": "COALESCE(l.total_arrears, 0)",
    "balance 1+ days": "CASE WHEN COALESCE(l.days_in_arrears, 0) > 0 THEN {bal} ELSE 0 END",
    "balance 31+ days": "CASE WHEN COALESCE(l.days_in_arrears, 0) > 30 THEN {bal} ELSE 0 END",
    "balance 91+ days": "CASE WHEN COALESCE(l.days_in_arrears, 0) > 90 THEN {bal} ELSE 0 END",
}
BALANCES = ("capital_balance", "total_capital_balance", "euro_book_balance")


class Command(BaseCommand):
    help = "Find the PAR definition that reproduces the desk's figures."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="2026-09")

    def handle(self, **options):
        from apps.staff_management.workbook_cards import SALES, SPECS, saved

        year, month = (int(p) for p in options["month"].split("-"))
        actuals = saved(SPECS[SALES].files[1]) or {}
        desk = {}
        for row in (actuals.get("PAR") or [])[1:]:
            v = row[5 + month] if len(row) > 5 + month else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v and row[1]:
                desk[str(row[1]).replace(" ", "").upper()] = float(v)
        self.stdout.write(f"Desk PAR figures for {year}-{month:02d}: {len(desk)}")

        end = (datetime.date(year, month, 28) + datetime.timedelta(days=4)).replace(day=1)
        with connection.cursor() as cur:
            cur.execute("SELECT MAX(eom_date)::date FROM loans WHERE eom_date < %s", [end])
            at = cur.fetchone()[0]
            cur.execute("SELECT MIN(eom_date)::date, MAX(eom_date)::date, "
                        "COUNT(DISTINCT eom_date::date) FROM loans")
            span = cur.fetchone()
        self.stdout.write(f"loans holds {span[2]} dates, {span[0]} to {span[1]}; "
                          f"reading {at}")
        if at is None:
            self.stdout.write("No loans rows on or before that month end.")
            return

        results = []
        for book, book_sql in BOOKS.items():
            for over_name, over_tpl in OVERDUE.items():
                for bal in BALANCES:
                    over = over_tpl.format(bal=f"COALESCE(l.{bal}, 0)")
                    if book_sql:
                        sql = f"""
                            WITH b AS ({book_sql})
                            SELECT UPPER(REPLACE(b.code, ' ', '')),
                                   SUM({over}), SUM(COALESCE(l.{bal}, 0))
                            FROM loans l JOIN b ON b.cust = l.cust_id::text
                            WHERE l.eom_date::date = %s GROUP BY 1"""
                    else:
                        sql = f"""
                            SELECT UPPER(REPLACE(TRIM(l.account_officer), ' ', '')),
                                   SUM({over}), SUM(COALESCE(l.{bal}, 0))
                            FROM loans l WHERE l.eom_date::date = %s GROUP BY 1"""
                    with connection.cursor() as cur:
                        cur.execute(sql, [at])
                        got = {k: (o / b if b else None) for k, o, b in cur.fetchall()}
                    both = [k for k in desk if got.get(k) is not None]
                    exact = sum(1 for k in both
                                if abs(got[k] - desk[k]) <= max(0.005 * desk[k], 0.0005))
                    near = sum(1 for k in both if abs(got[k] - desk[k]) <= 0.1 * desk[k])
                    eg = ", ".join(f"{k} {desk[k]:.4f}/{got[k]:.4f}" for k in both[:2])
                    results.append((exact, near, len(both), book, over_name, bal, eg))
        for exact, near, n, book, over, bal, eg in sorted(results, reverse=True)[:10]:
            self.stdout.write(f"{exact:3}/{n:<3} exact, {near:3} within 10%  "
                              f"{book} | {over} / {bal}   e.g. {eg}")
