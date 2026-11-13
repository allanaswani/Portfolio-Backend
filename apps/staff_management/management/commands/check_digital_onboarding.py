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

        for label, sql in CANDIDATES.items():
            with connection.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            by = {}
            for who, month, n in rows:
                by.setdefault(who or "", {})[month] = n
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
