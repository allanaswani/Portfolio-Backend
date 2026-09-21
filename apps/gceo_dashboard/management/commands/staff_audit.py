"""What employee_table actually contains, and why the Staff & HR tiles disagree.

    manage.py staff_audit

The slide showed 913 total staff and 527 people with under a year of service,
while reporting 204 new hires in the same year. Those cannot all be true. This
prints the counts each tile is built from, side by side, so the disagreement is
a number rather than an argument.

It writes nothing.
"""
from django.core.management.base import BaseCommand
from django.db import connection

from apps.gceo_dashboard.staff_scope import (
    CURRENT_STAFF_SQL, LEFT_SQL, PERSON_KEY_SQL,
)


class Command(BaseCommand):
    help = "Reconcile the Staff & HR tiles against employee_table."

    def handle(self, *a, **o):
        w = self.stdout.write
        with connection.cursor() as cur:
            def one(sql):
                cur.execute(sql)
                return cur.fetchone()[0]

            w("")
            w("employee_table")
            w("=" * 62)
            rows   = one("SELECT count(*) FROM employee_table")
            ids    = one("SELECT count(DISTINCT staff_id) FROM employee_table")
            no_id  = one("SELECT count(*) FROM employee_table "
                         "WHERE staff_id IS NULL OR BTRIM(staff_id::text) = ''")
            people = one(f"SELECT count(DISTINCT {PERSON_KEY_SQL}) FROM employee_table")
            w(f"  rows                         {rows:>8}")
            w(f"  distinct staff_id            {ids:>8}"
              "   <- all a DISTINCT staff_id count can see")
            w(f"  rows with NO staff_id        {no_id:>8}"
              + ("   <- SILENTLY DROPPED by that count" if no_id else ""))
            w(f"  people (staff_id, else row)  {people:>8}"
              "   <- what the tiles count now")
            dupes = rows - no_id - ids
            if dupes > 0:
                w(f"  duplicate staff_id rows      {dupes:>8}")

            w("")
            w("How each definition of 'current staff' counts")
            w("-" * 62)
            defs = [
                ("exit = 0, distinct        (old Total Staff tile)",
                 "SELECT count(DISTINCT staff_id) FROM employee_table WHERE exit = 0"),
                ("exit <> 1, rows           (old Department/Grade charts)",
                 "SELECT count(id) FROM employee_table WHERE exit IS DISTINCT FROM 1"),
                ("exit = 0, rows            (old Years of service)",
                 "SELECT count(*) FROM employee_table WHERE exit = 0"),
                ("both markers, DISTINCT staff_id  (my first fix, still short)",
                 f"SELECT count(DISTINCT staff_id) FROM employee_table WHERE {CURRENT_STAFF_SQL}"),
                ("both markers, people             (what they all use now)",
                 f"SELECT count(DISTINCT {PERSON_KEY_SQL}) FROM employee_table "
                 f"WHERE {CURRENT_STAFF_SQL}"),
            ]
            for label, sql in defs:
                w(f"  {label:<52}{one(sql):>8}")

            w("")
            w("Why they differ")
            w("-" * 62)
            checks = [
                ("exit IS NULL",
                 "SELECT count(*) FROM employee_table WHERE exit IS NULL"),
                ("left per staff_exit_date but exit is not 1",
                 "SELECT count(*) FROM employee_table "
                 "WHERE staff_exit_date IS NOT NULL AND exit IS DISTINCT FROM 1"),
                ("exit = 1 but no staff_exit_date",
                 "SELECT count(*) FROM employee_table "
                 "WHERE exit = 1 AND staff_exit_date IS NULL"),
            ]
            for label, sql in checks:
                w(f"  {label:<52}{one(sql):>8}")

            w("")
            w("Service years — the 527 that does not agree with 204 new hires")
            w("-" * 62)
            cur.execute(f"""
                SELECT
                    count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)) FILTER (WHERE service_years IS NULL),
                    count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)) FILTER (WHERE service_years = 0),
                    count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)) FILTER (WHERE service_years > 0 AND service_years < 1),
                    count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)) FILTER (WHERE date_of_employment IS NULL),
                    count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)) FILTER (WHERE new = 1),
                    count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)) FILTER (WHERE new = 1
                        AND date_trunc('year', date_of_employment) = date_trunc('year', now()))
                FROM employee_table
                WHERE {CURRENT_STAFF_SQL}
            """)
            sy_null, sy_zero, sy_frac, doe_null, new_any, new_year = cur.fetchone()
            w(f"  service_years IS NULL                       {sy_null:>8}")
            w(f"  service_years = 0                           {sy_zero:>8}"
              "   <- these land in '< 1 yr'")
            w(f"  service_years between 0 and 1               {sy_frac:>8}")
            w(f"  date_of_employment IS NULL                  {doe_null:>8}"
              "   <- cannot have a real service length")
            w(f"  flagged new = 1 (any year)                  {new_any:>8}")
            w(f"  flagged new = 1 AND employed this year      {new_year:>8}"
              "   <- the New Hires tile")

            w("")
            w("Departments (current staff, counted once each)")
            w("-" * 62)
            cur.execute(f"""
                SELECT COALESCE(NULLIF(BTRIM(department), ''), '(blank)'),
                       count(DISTINCT COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text))
                FROM employee_table WHERE {CURRENT_STAFF_SQL}
                GROUP BY 1 ORDER BY 2 DESC
            """)
            dept = cur.fetchall()
            total = sum(c for _, c in dept)
            for name, c in dept:
                w(f"  {name[:46]:<46}{c:>8}")
            w(f"  {'TOTAL':<46}{total:>8}   ({len(dept)} departments)")
            w("")
