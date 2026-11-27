"""Where in the warehouse the IB actuals template's account figures come from.

    python manage.py ib_feed_probe /app/etl_requests/2026_IB_Actual_Template_v2.xlsx

Every IB card line is a SUMIFS over the template's Portfolio sheet: one row
per IB account (ACC_NUM, RM_CODE, the desk's LEGACY CAT) with its month-end
balances (DEC_25_BAL .. DEC_26_BAL), interest expense, rate and NFI. Before
any IB line reads the warehouse, the warehouse has to give the desk's own
figures for a closed month. This finds the candidates and measures them:

1. the template's accounts and their October balance / interest expense;
2. every warehouse table with an account-number column, and how many of the
   template's accounts it holds;
3. for the tables holding most of them: which numeric column, on which
   date column at 31 October 2026, equals the template's October balance
   account by account (to the shilling) - and how many accounts agree.

Counts and column names only: no customer name or amount is printed.
Read-only.
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

ACCOUNT_COLUMNS = ("acc_num", "account_number", "acc_no", "accnum", "account_no",
                   "foracid", "cust_ac_no", "acct_no", "account")
DATE_HINTS = ("date", "dt", "as_at", "asat", "eod", "month", "period")


def _portfolio(path):
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Portfolio" not in wb.sheetnames:
            raise CommandError("no Portfolio sheet - is this the IB actuals template?")
        rows = list(wb["Portfolio"].iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
    head = [str(v or "").strip().upper() for v in rows[0]]
    want = {"ACC_NUM": None, "RM_CODE": None, "LEGACY CAT": None, "OCT_26_BAL": None,
            "SEP_26_BAL": None, "OCT_26_EXP": None, "OCT_26_RATE": None}
    for i, h in enumerate(head):
        if h in want and want[h] is None:
            want[h] = i
    missing = [k for k, v in want.items() if v is None]
    if missing:
        raise CommandError(f"Portfolio has no column {', '.join(missing)}")
    out = []
    for r in rows[1:]:
        acc = str(r[want["ACC_NUM"]] or "").strip()
        if acc and acc.replace(".0", "").isdigit():
            out.append({k: r[i] for k, i in want.items()} | {"ACC_NUM": acc.replace(".0", "")})
    return out


class Command(BaseCommand):
    help = "Find and measure the warehouse source of the IB template's account figures."

    def add_arguments(self, parser):
        parser.add_argument("template", help="path to the IB actuals template (.xlsx)")
        parser.add_argument("--tables", type=int, default=5,
                            help="how many best-covering tables to measure (default 5)")

    def handle(self, *args, **opts):
        w = self.stdout.write
        accounts = _portfolio(opts["template"])
        accs = sorted({a["ACC_NUM"] for a in accounts})
        oct_bal = {a["ACC_NUM"]: a["OCT_26_BAL"] for a in accounts
                   if isinstance(a["OCT_26_BAL"], (int, float))}
        w(f"TEMPLATE: {len(accs)} accounts, {len(oct_bal)} with an October balance, "
          f"{len({a['RM_CODE'] for a in accounts})} RM codes, legacy tags: "
          f"{sorted({str(a['LEGACY CAT']) for a in accounts})}")

        with connection.cursor() as cur:
            cur.execute("""SELECT table_schema, table_name, column_name
                           FROM information_schema.columns
                           WHERE lower(column_name) = ANY(%s)
                             AND table_schema NOT IN ('pg_catalog', 'information_schema')""",
                        [list(ACCOUNT_COLUMNS)])
            candidates = cur.fetchall()
        w(f"\nTABLES WITH AN ACCOUNT COLUMN: {len(candidates)}")
        coverage = []
        for schema, table, col in candidates:
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = 60000")
                    cur.execute(f'SELECT COUNT(DISTINCT "{col}"::text) FROM "{schema}"."{table}" '
                                f'WHERE trim("{col}"::text) = ANY(%s)', [accs])
                    n = cur.fetchone()[0]
            except Exception as exc:  # noqa: BLE001 - next table
                w(f"  {schema}.{table}.{col}: not read ({type(exc).__name__})")
                continue
            if n:
                coverage.append((n, schema, table, col))
        coverage.sort(reverse=True)
        for n, schema, table, col in coverage[:25]:
            w(f"  {n:6} of {len(accs)}  {schema}.{table}.{col}")

        target = datetime.date(2026, 10, 31)
        w(f"\nOCTOBER BALANCE CHECK (31 Oct 2026, to the shilling), best {opts['tables']} tables:")
        for n, schema, table, col in coverage[:opts["tables"]]:
            with connection.cursor() as cur:
                cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                               WHERE table_schema = %s AND table_name = %s""", [schema, table])
                cols = cur.fetchall()
            dates = [c for c, t in cols if t in ("date", "timestamp without time zone",
                                                 "timestamp with time zone")
                     or any(h in c.lower() for h in DATE_HINTS)]
            nums = [c for c, t in cols if t in ("numeric", "double precision", "real",
                                                "bigint", "integer") and c != col]
            w(f"  {schema}.{table}: {len(dates)} date-like, {len(nums)} numeric columns")
            for d in dates[:4]:
                for v in nums[:40]:
                    try:
                        with transaction.atomic(), connection.cursor() as cur:
                            cur.execute("SET LOCAL statement_timeout = 60000")
                            cur.execute(
                                f'SELECT trim("{col}"::text), SUM("{v}") FROM "{schema}"."{table}" '
                                f'WHERE trim("{col}"::text) = ANY(%s) AND "{d}"::date = %s '
                                f'GROUP BY 1', [accs, target])
                            got = dict(cur.fetchall())
                    except Exception:  # noqa: BLE001 - not a date / not comparable
                        continue
                    if not got:
                        continue
                    agree = sum(1 for a, b in oct_bal.items()
                                if a in got and got[a] is not None
                                and abs(Decimal(str(got[a])) - Decimal(str(b))) < 1)
                    if agree:
                        w(f"    {d} = 31 Oct, {v}: {agree} of {len(oct_bal)} accounts agree "
                          f"({len(got)} found)")
        w("\nPaste this output: an IB line goes live only on a column that agrees.")
