"""One seller's mortgage sales by month, as the card reads them - to set
beside the drawdown report's Mortgage_Mrkt_Rate_Sales sheet.

    manage.py check_mortgage_sales MOO3776
    manage.py check_mortgage_sales MOO3776 --year 2026 --rows

The card follows drawdown_report_correct.py: SALESPERSON only (with the
report's code corrections), staff loans out, MORTGAGE by product_mapping,
market rate from 10%. Also printed: drawdowns where this code is only the
LOAN OFFICER, and mortgage-looking products product_mapping does not call
MORTGAGE - the two usual reasons a figure differs from someone's own count.
Writes nothing.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "A seller's mortgage drawdowns by month, as the card reads them."

    def add_arguments(self, parser):
        parser.add_argument("code")
        parser.add_argument("--year", type=int, default=datetime.date.today().year)
        parser.add_argument("--rows", action="store_true", help="every drawdown too")

    def handle(self, *args, **o):
        from apps.staff_management.live_scorecard import mortgage_drawdowns

        code, year, w = o["code"].strip().upper(), o["year"], self.stdout.write
        from apps.staff_management.live_scorecard import mortgage_counts_secured_loans

        rows = mortgage_drawdowns(code, year)
        self.stdout.write("Rule in use: MORTGAGE products" + (
            " plus SECURED loans (check_mortgage_rule)" if mortgage_counts_secured_loans()
            else " only"))
        months = {}
        for r in rows:
            m = months.setdefault(r["on"].month, [0.0, 0.0])
            m[0 if r["market"] else 1] += r["net"]
        w(f"{code} {year} - net mortgage drawdowns credited on SALESPERSON "
          f"(drawdown report rules)")
        w(f"{'month':<6}{'market >=10%':>18}{'non-market':>18}{'market YTD':>18}")
        ytd = 0.0
        for month in range(1, 13):
            if month not in months:
                continue
            mk, non = months[month]
            ytd += mk
            w(f"{datetime.date(year, month, 1):%b}   {mk:>18,.0f}{non:>18,.0f}{ytd:>18,.0f}")
        if o["rows"]:
            for r in rows:
                w(f"  {r['on']}  {r['net']:>16,.0f}  rate {r['rate']}  "
                  f"product {r['product']}  salesperson {r['salesperson']!r}  "
                  f"officer {r['loan_officer']!r}")

        with connection.cursor() as cur:
            cur.execute(r"""
                SELECT EXTRACT(MONTH FROM d.drawdown_dt)::int, SUM(d.net_drawdown)
                FROM drawdown_daily d
                JOIN product_mapping pm
                  ON regexp_replace(TRIM(pm.code::text), '\.0+$', '')
                   = regexp_replace(TRIM(d.id_product::text), '\.0+$', '')
                WHERE TRIM(pm.loan_category) = 'MORTGAGE'
                  AND EXTRACT(YEAR FROM d.drawdown_dt) = %s
                  AND UPPER(TRIM(d.loan_officer_id)) = %s
                  AND UPPER(TRIM(COALESCE(d.salesperson, ''))) <> %s
                GROUP BY 1 ORDER BY 1""", [year, code, code])
            officer = cur.fetchall()
            cur.execute(r"""
                SELECT d.id_product, MAX(d.product_desc), MAX(pm.loan_category),
                       COUNT(*), SUM(d.net_drawdown), MAX(pm.loan_security),
                       string_agg(to_char(d.drawdown_dt, 'DD Mon') || ' '
                                  || to_char(d.net_drawdown, 'FM999,999,999,990')
                                  || ' @' || COALESCE(d.final_interest::text, '?'),
                                  '; ' ORDER BY d.drawdown_dt)
                FROM drawdown_daily d
                LEFT JOIN product_mapping pm
                  ON regexp_replace(TRIM(pm.code::text), '\.0+$', '')
                   = regexp_replace(TRIM(d.id_product::text), '\.0+$', '')
                WHERE EXTRACT(YEAR FROM d.drawdown_dt) = %s
                  AND (UPPER(TRIM(d.salesperson)) = %s OR UPPER(TRIM(d.loan_officer_id)) = %s)
                GROUP BY 1 ORDER BY 5 DESC NULLS LAST""", [year, code, code])
            products = cur.fetchall()
        if officer:
            w("\nWhere this code is only the LOAN OFFICER (not credited, as in the report):")
            for month, total in officer:
                w(f"  {datetime.date(year, month, 1):%b}  {float(total or 0):>18,.0f}")
        w("\nEvery product this code drew this year (salesperson or officer):")
        for pid, desc, cat, n, total, security, each in products:
            w(f"  {pid!s:>8}  {str(desc or '')[:40]:<40} {str(cat or 'NOT MAPPED'):<12}"
              f" {str(security or ''):<10} {n:>4} drawdowns {float(total or 0):>18,.0f}")
            w(f"            {each}")
