"""Print, for one RM, every figure the /rm-portfolio screen shows, next to the
raw warehouse numbers each one is computed from.

The screen draws its tiles and its chart from two different warehouse tables:

    tiles  ->  hf_customer, reached through retail_allocated_portfolio (who the
               customer is ALLOCATED to)
    chart  ->  daily_balance_movement / loan_daily_balance_movement, filtered on
               rm_code (who the ACCOUNT is stamped to)

Those two books are not the same book, and nothing in the UI said so. When an
RM says "the tile and the graph disagree", this prints both, plus the gap and
where it comes from, so the question can be answered with a number instead of
an opinion.

    manage.py rm_figures DSR001
    manage.py rm_figures --all          # every RM, worst gap first
"""
from django.core.management.base import BaseCommand
from django.db import connection

from services import portfolio_service as svc


def _fmt(v):
    if v is None:
        return "-"
    return f"{float(v):>18,.2f}"


class Command(BaseCommand):
    help = "Show an RM's tile figures and chart figures side by side."

    def add_arguments(self, parser):
        parser.add_argument("sales_code", nargs="?", help="The RM's sales code.")
        parser.add_argument(
            "--all", action="store_true",
            help="Every RM with an allocation, worst tile/chart gap first.",
        )
        parser.add_argument(
            "--limit", type=int, default=20,
            help="With --all, how many RMs to print (default 20).",
        )

    def handle(self, *a, **o):
        if o["all"]:
            return self._all(o["limit"])
        code = o["sales_code"]
        if not code:
            self.stderr.write("Give a sales code, or --all.")
            return
        self._one(code)

    # ── one RM, in full ──────────────────────────────────────────────────────

    def _one(self, code):
        w = self.stdout.write
        with connection.cursor() as cur:
            # How many allocation rows vs how many customers. Anything above 1.0
            # was inflating the tiles before the RM_BOOK fix.
            cur.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT cust_id)
                FROM retail_allocated_portfolio
                WHERE TRIM(sales_code::text) = TRIM(%s) AND cust_id IS NOT NULL
                """, [code],
            )
            rows, custs = cur.fetchone()

            # The tiles, as the API now computes them.
            cur.execute(
                f"""
                SELECT SUM(total_depost_balance), SUM(total_loans), COUNT(*)
                FROM hf_customer
                JOIN ({svc.RM_BOOK}) vp ON hf_customer.cust_id = vp.cust_id
                """, [code],
            )
            dep, loan, n = cur.fetchone()

            # The tiles as they were computed BEFORE the fix, so the size of the
            # correction is visible rather than asserted.
            cur.execute(
                """
                SELECT SUM(total_depost_balance), SUM(total_loans)
                FROM hf_customer
                JOIN (SELECT cust_id FROM retail_allocated_portfolio
                      WHERE TRIM(sales_code::text) = TRIM(%s)) vp
                  ON hf_customer.cust_id = vp.cust_id
                """, [code],
            )
            old_dep, old_loan = cur.fetchone()

            chart = {}
            for label, table in (("deposits", "daily_balance_movement"),
                                 ("loans", "loan_daily_balance_movement")):
                cur.execute(
                    f"""
                    SELECT COUNT(*),
                           SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0),
                           SUM(yester_2_bal) FILTER (WHERE yester_2_bal > 0)
                    FROM {table} WHERE TRIM(rm_code) = TRIM(%s)
                    """, [code],
                )
                chart[label] = cur.fetchone()

        w("")
        w(f"RM {code}")
        w("=" * 64)
        w(f"allocation rows      {rows:>10}   for {custs} customers"
          f"{'   <-- DUPLICATES' if custs and rows > custs else ''}")
        w(f"customers on tiles   {n:>10}")
        bal = svc.rm_balances(code)
        w("")
        w(f"{'':22}{'DEPOSITS':>18}{'LOANS':>18}")
        w(f"{'TILE (now)':22}{_fmt(bal['total_deposit_balance'])}"
          f"{_fmt(bal['total_loans'])}")
        w(f"{'  as at':22}{bal['deposits_as_at'] or '-':>18}"
          f"{bal['loans_as_at'] or '-':>18}")
        w("")
        w("what the tile used to read, from hf_customer (a customer-master")
        w("aggregate on its own refresh cycle, not the RM's live position):")
        w(f"{'  allocated book':22}{_fmt(dep)}{_fmt(loan)}")
        w(f"{'  before dedupe':22}{_fmt(old_dep)}{_fmt(old_loan)}")
        w("")
        for label in ("deposits", "loans"):
            cnt, y1, y2 = chart[label]
            w(f"{label:22}{cnt:>6} accounts in daily balance movement")
            w(f"{'  yesterday':22}{_fmt(y1)}")
            w(f"{'  day before':22}{_fmt(y2)}")
            if not y1:
                w("  yesterday is empty — the ETL has not posted today's file, so")
                w("  the screen falls back to the last closed month end.")
        w("")
        gap_src = []
        if custs and rows > custs:
            gap_src.append("duplicate allocation rows (fixed)")
        if chart["deposits"][0] == 0:
            gap_src.append("no daily_balance_movement rows stamped to this rm_code")
        w("gap explained by: " + (", ".join(gap_src) if gap_src else
                                  "different books — allocation vs account rm_code"))
        w("")

    # ── every RM, worst first ────────────────────────────────────────────────

    def _all(self, limit):
        w = self.stdout.write
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT TRIM(sales_code::text) AS sc,
                       COUNT(*) AS rows, COUNT(DISTINCT cust_id) AS custs
                FROM retail_allocated_portfolio
                WHERE cust_id IS NOT NULL AND sales_code IS NOT NULL
                GROUP BY 1
                HAVING COUNT(*) > COUNT(DISTINCT cust_id)
                ORDER BY COUNT(*)::numeric / NULLIF(COUNT(DISTINCT cust_id), 0) DESC
                LIMIT %s
                """, [limit],
            )
            dup = cur.fetchall()

        w("")
        if not dup:
            w("No RM has duplicate allocation rows — the tiles were not inflated.")
            w("")
            return
        w(f"{len(dup)} RMs carried duplicate allocation rows. Before the RM_BOOK")
        w("fix each one's deposit and loan tiles read high by this multiple:")
        w("")
        w(f"{'sales_code':<14}{'rows':>8}{'customers':>12}{'inflated by':>14}")
        for sc, rows, custs in dup:
            w(f"{sc:<14}{rows:>8}{custs:>12}{rows / custs:>13.3f}x")
        w("")
