"""Reconcile an RM's dormancy rate across every denominator at once.

Written because two teams reported 11% and 63% active for the same book
(Lucas Olwako, Sep 2026) and neither number was wrong — they were counting
different things. This prints all of them side by side so the conversation is
about the decision, not the arithmetic.

    python manage.py rm_dormancy --rm "LUCAS OLWAKO"
    python manage.py rm_dormancy --sales-code PNM3930 --idle-days 180

Four things move the answer, and the command shows each:

1. **Allocation rows vs distinct customers.** retail_allocated_portfolio has no
   unique cust_id, so counting rows double-counts anyone allocated twice. See
   the rm-list fan-out note in docs.
2. **Accounts vs customers.** Dormancy is an ACCOUNT attribute. A customer with
   four dormant accounts and one live one is an active customer with an 80%
   dormant account book. Both statements are true.
3. **Which "active".** account_status, is_transacting_account, and "moved in the
   last N days" are three different tests and they do not agree.
4. **Customers with no accounts at all.** They are allocations, but they cannot
   be active under any definition, and whether they sit in the denominator
   swings the percentage hard.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Reconcile dormancy for one RM across every way of counting it."

    def add_arguments(self, parser):
        parser.add_argument("--rm", help="RM name as it appears in retail_allocated_portfolio.")
        parser.add_argument("--sales-code", help="Sales code, if you have it.")
        parser.add_argument("--idle-days", type=int, default=180,
                            help="Days without a transaction before an account counts as idle (default 180).")

    def handle(self, *args, **o):
        rm, code, idle = o.get("rm"), o.get("sales_code"), o["idle_days"]
        if not rm and not code:
            raise CommandError("Give --rm or --sales-code.")

        where, params = [], []
        if rm:
            where.append("upper(rap.rm_name) LIKE upper(%s)")
            params.append(f"%{rm}%")
        if code:
            where.append("upper(rap.sales_code) = upper(%s)")
            params.append(code)
        clause = " AND ".join(where)

        with connection.cursor() as cur:
            def run(sql, extra=None):
                cur.execute(sql, params + (extra or []))
                return cur.fetchall()

            # 1 — the allocation base, rows vs distinct customers.
            rows, custs = run(f"""
                SELECT COUNT(*), COUNT(DISTINCT rap.cust_id)
                FROM retail_allocated_portfolio rap
                WHERE {clause} AND rap.cust_id IS NOT NULL
            """)[0]
            if not rows:
                raise CommandError("No allocations matched. Check the name spelling "
                                   "against retail_allocated_portfolio.rm_name.")

            self.stdout.write(self.style.MIGRATE_HEADING("\nAllocation base"))
            self._line("Allocation rows", rows)
            self._line("Distinct customers", custs)
            if rows != custs:
                self.stdout.write(self.style.WARNING(
                    f"  {rows - custs} duplicate allocation row(s). Any percentage "
                    f"computed over {rows} is inflated."))

            # 2 — how many of those customers actually hold accounts.
            with_acc, accounts = run(f"""
                SELECT COUNT(DISTINCT a.cust_id), COUNT(*)
                FROM accounts a
                WHERE a.cust_id IN (
                    SELECT DISTINCT rap.cust_id FROM retail_allocated_portfolio rap
                    WHERE {clause} AND rap.cust_id IS NOT NULL)
            """)[0]
            self._line("Customers holding accounts", with_acc)
            self._line("Customers with NO account", custs - with_acc)
            self._line("Accounts held", accounts)

            # 3 — the raw statuses, so nobody has to guess what "active" means.
            self.stdout.write(self.style.MIGRATE_HEADING("\nAccounts by account_status"))
            for status, n in run(f"""
                SELECT COALESCE(NULLIF(TRIM(a.account_status), ''), '(blank)') AS s, COUNT(*)
                FROM accounts a
                WHERE a.cust_id IN (
                    SELECT DISTINCT rap.cust_id FROM retail_allocated_portfolio rap
                    WHERE {clause} AND rap.cust_id IS NOT NULL)
                GROUP BY 1 ORDER BY 2 DESC
            """):
                self._line(status, n, accounts)

            # 4 — the same book under three definitions of "active".
            tests = [
                ("account_status contains ACTIVE", "upper(a.account_status) LIKE '%%ACTIVE%%'"),
                ("is_transacting_account", "a.is_transacting_account IS TRUE"),
                (f"moved in last {idle} days",
                 f"a.last_transaction_date >= current_date - INTERVAL '{idle} days'"),
            ]
            self.stdout.write(self.style.MIGRATE_HEADING("\nActive rate, by definition"))
            self.stdout.write("  Per account, then per customer (a customer counts "
                              "as active if ANY account passes).\n")
            for label, test in tests:
                acc_active, cust_active = run(f"""
                    SELECT COUNT(*) FILTER (WHERE {test}),
                           COUNT(DISTINCT a.cust_id) FILTER (WHERE {test})
                    FROM accounts a
                    WHERE a.cust_id IN (
                        SELECT DISTINCT rap.cust_id FROM retail_allocated_portfolio rap
                        WHERE {clause} AND rap.cust_id IS NOT NULL)
                """)[0]
                self.stdout.write(f"  {label}")
                self._line("    per account", acc_active, accounts)
                self._line("    per customer (of those holding accounts)", cust_active, with_acc)
                self._line("    per customer (of ALL allocations)", cust_active, custs)

        self.stdout.write(self.style.MIGRATE_HEADING("\nReading this"))
        self.stdout.write(
            "  A low per-account rate with a high per-customer rate is not a\n"
            "  contradiction: it means the customers are there but holding mostly\n"
            "  idle accounts. That is an account-cleanup question, not necessarily\n"
            "  a reallocation one. Decide which denominator the decision needs\n"
            "  BEFORE quoting a percentage.\n")

    def _line(self, label, n, base=None):
        pct = f"  ({n / base * 100:5.1f}%)" if base else ""
        self.stdout.write(f"  {label:<46} {n:>7,}{pct}")
