"""Which attribution of mobile-app registrations reproduces the desk's
Digital_Customers sheet? Read-only; prints evidence, changes nothing.

    manage.py check_digital_onboarding [--year 2026] [--show 15]

The count is ``routine_registration_data.py``'s: ``mobile_customers_table``
joined to ``customers`` on national ID (leading zeros and spaces stripped),
one row per ``cust_id`` at its EARLIEST registration (no duplicates), branch
not HF WHIZZ / DUMMY UNIT. That report has no officer column, so who a
registration belongs to has to come from elsewhere. Each candidate below is
scored against the desk's running totals, month by month:

  opened_by_first   accounts.opened_by of the customer's first account
  opened_by_new     the same, only customers whose first account opened this
                    year (a new customer onboarded)
  opened_by_any     any account's opened_by (a customer can count for more
                    than one person)

People are found by their template code and the AD logins the desk keys their
account-opening rows on (as load_whizz_onboarding does).
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import connection

BASE = """
WITH reg AS (
    SELECT c.cust_id, MIN(m.datecreated) AS registered
    FROM mobile_customers_table m
    JOIN customers c
      ON REPLACE(trim(LEADING '0' FROM trim(m.docunumber)), ' ', '')
       = REPLACE(trim(LEADING '0' FROM trim(c.national_id)), ' ', '')
    WHERE c.branch IS NOT NULL AND c.branch NOT IN ('HF WHIZZ', 'DUMMY UNIT')
    GROUP BY c.cust_id
), firsts AS (
    SELECT DISTINCT ON (a.cust_id) a.cust_id, a.opened_by, a.open_date
    FROM accounts a
    ORDER BY a.cust_id, a.open_date, a.account_no
)
"""

CANDIDATES = {
    "opened_by_first": BASE + """
        SELECT upper(trim(f.opened_by)), extract(month FROM r.registered)::int, count(*)
        FROM reg r JOIN firsts f ON f.cust_id = r.cust_id
        WHERE r.registered >= %(start)s AND r.registered < %(end)s
        GROUP BY 1, 2""",
    "opened_by_new": BASE + """
        SELECT upper(trim(f.opened_by)), extract(month FROM r.registered)::int, count(*)
        FROM reg r JOIN firsts f ON f.cust_id = r.cust_id
        WHERE r.registered >= %(start)s AND r.registered < %(end)s
          AND f.open_date >= %(start)s
        GROUP BY 1, 2""",
    "opened_by_any": BASE + """
        SELECT o.who, extract(month FROM r.registered)::int, count(*)
        FROM reg r
        JOIN (SELECT DISTINCT cust_id, upper(trim(opened_by)) AS who FROM accounts) o
          ON o.cust_id = r.cust_id
        WHERE r.registered >= %(start)s AND r.registered < %(end)s
        GROUP BY 1, 2""",
}


def weighted_candidates(year, out):
    """Registrations credited as the weighted sales report credits accounts.

    ``daily_sales_accounts_with_cto`` (accounts opened this year) - the report's
    accounts data - names the seller (``sale_code``, the report's four hand
    corrections) of every customer onboarded this year; a customer belongs to
    the seller on its FIRST row (``cust_cif`` duplicated, table order), STAFF
    and INTERNAL ACCOUNTS out. A registered customer (unique cust_id, earliest
    registration) is then credited to that seller:

      weighted_reg_month   counted in the month it registered (this year)
      weighted_both_month  counted once both have happened: the later of the
                           customer's open month and its registration month
      weighted_new_rule    as weighted_both_month, only customers the report
                           counts as New Customers (new, funded, not closed)
    """
    import numpy as np
    import pandas as pd

    from apps.staff_management.weighted_sales_new_customers import (
        RENAMES, SALE_CODE_FIXES)

    start, end = datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1)
    with connection.cursor() as cur:
        cur.execute(BASE + "SELECT cust_id, registered FROM reg", {})
        reg = {int(c): r for c, r in cur.fetchall() if c is not None and r is not None}
        cur.execute("SELECT * FROM daily_sales_accounts_with_cto "
                    "WHERE acc_open_date >= %s ORDER BY ctid", [start])
        names = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=names)
    df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns=RENAMES)
    df["sale_code"] = (df["sale_code"].astype(str).str.replace(" ", "", regex=False)
                       .replace(SALE_CODE_FIXES).str.strip().str.upper())
    df = df[(df["customer_segment"] != "STAFF")
            & (df["customer_segment"] != "INTERNAL ACCOUNTS")].fillna(0)
    new = df["total_accounts_before_current_year"] == 0
    funded = ((pd.to_numeric(df["cust_cto"], errors="coerce").fillna(0) > 0)
              | (pd.to_numeric(df["current_year_bal"], errors="coerce").fillna(0) > 0))
    first = ~df["cust_cif"].duplicated()
    opened = pd.to_datetime(df["cust_open_date"], errors="coerce")
    cif = pd.to_numeric(df["cust_cif"], errors="coerce")
    df = df.assign(_cif=cif, _opened=opened, _new_rule=new & funded
                   & (df["account_status"] != "CLOSED"))[first]

    matched = 0
    found = {"weighted_reg_month": {}, "weighted_both_month": {}, "weighted_new_rule": {}}
    for code, c, op, new_rule in df[["sale_code", "_cif", "_opened", "_new_rule"]].values:
        if pd.isna(c) or int(c) not in reg:
            continue
        matched += 1
        registered = pd.Timestamp(reg[int(c)])
        if registered.tzinfo is not None:
            registered = registered.tz_localize(None)
        if start <= registered.date() < end:
            m = found["weighted_reg_month"].setdefault(code, {})
            m[registered.month] = m.get(registered.month, 0) + 1
        if pd.isna(op) or op.year != year:
            continue
        both = max(op, registered)
        if both.year != year:
            continue
        for label, wanted in (("weighted_both_month", True), ("weighted_new_rule", new_rule)):
            if wanted:
                m = found[label].setdefault(code, {})
                m[both.month] = m.get(both.month, 0) + 1
    out.write(f"weighted accounts: {df.shape[0]} customers onboarded {year}, "
              f"{matched} of them registered on the app\n")
    return found


class Command(BaseCommand):
    help = "Score attributions of mobile-app registrations against the desk."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=datetime.date.today().year)
        parser.add_argument("--show", type=int, default=15,
                            help="People to print per candidate.")

    def handle(self, *args, **opts):
        from apps.staff_management.management.commands.load_whizz_onboarding import logins_for
        from apps.staff_management.workbook_cards import saved

        year = opts["year"]
        actuals = saved("actuals") or {}
        people = []
        for row in (actuals.get("Digital_Customers") or [])[1:]:
            if len(row) < 7 or not row[1]:
                continue
            desk = [(m, row[5 + m]) for m in range(1, 13)
                    if len(row) > 5 + m and isinstance(row[5 + m], (int, float))]
            if desk:
                code, name = str(row[1]).strip(), str(row[2] or "").strip()
                keys = {k.strip().upper() for k in (code, *logins_for(actuals, name)) if k}
                people.append((code, name, keys, desk))
        self.stdout.write(f"{len(people)} people with desk figures on Digital_Customers")

        params = {"start": datetime.date(year, 1, 1), "end": datetime.date(year + 1, 1, 1)}
        with connection.cursor() as cur:
            cur.execute(BASE + "SELECT count(*), count(*) FILTER (WHERE registered >= %(start)s "
                        "AND registered < %(end)s) FROM reg", params)
            total, this_year = cur.fetchone()
        self.stdout.write(f"registrations (unique cust_id): {total} in all, {this_year} in {year}\n")

        results = {}
        for label, sql in CANDIDATES.items():
            with connection.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            by = {}
            for who, month, n in rows:
                by.setdefault(who or "", {})[month] = n
            results[label] = by
        results.update(weighted_candidates(year, self.stdout))

        for label, by in results.items():
            agree = differ = found = 0
            lines = []
            for code, name, keys, desk in people:
                mine = [by[k] for k in keys if k in by]
                if not mine:
                    continue
                found += 1
                got = [sum(sum(n for mm, n in d.items() if mm <= m) for d in mine)
                       for m, _ in desk]
                same = sum(1 for (_, d), g in zip(desk, got) if abs(d - g) < 1e-9)
                agree += same
                differ += len(desk) - same
                lines.append(f"    {code:<9} {name[:22]:<22} desk {[int(d) for _, d in desk]}"
                             f"  this {got}")
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"{label}: people found {found}/{len(people)}, "
                f"months agreeing {agree}, differing {differ}"))
            for line in lines[:opts["show"]]:
                self.stdout.write(line)
            self.stdout.write("")
