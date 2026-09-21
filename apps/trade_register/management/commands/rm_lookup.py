"""Why a person is, or is not, offered in the Trade Register's RM picker — and
why their sales code does or does not fill in.

    manage.py rm_lookup "Eric Mukami"
    manage.py rm_lookup Juspher
    manage.py rm_lookup --missing-codes          # everyone the picker shows with no code

The picker reads three tables and merges them:

    employee_table        the HR roster, excluding anyone with an exit marker
    dsr_sales_codes       DSR allocations
    staff_employee_data   sales staff

A name can be absent for reasons that look identical on screen and are not:
they are on no list at all, or they are on the roster but flagged as exited, or
they are spelled differently from what was typed. A sales code can be blank for
a different reason again: the code lives in the sales tables keyed on PF NUMBER,
so a roster record whose PF does not match the sales tables gets a name with no
code beside it. This prints which of those it is.
"""
from django.core.management.base import BaseCommand
from django.db import router as db_router
from django.db.models import Q

from apps.gceo_dashboard.models import EmployeeTable
from apps.staff_management.models import DSRSalesCode, StaffEmployeeData


def _pf(value):
    """PF number as an int, or None. Mirrors the view's own coercion."""
    if value is None:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = "Explain why an RM is missing from the trade register picker, or has no code."

    def add_arguments(self, parser):
        parser.add_argument("name", nargs="?", help="Whole or part of a name.")
        parser.add_argument(
            "--missing-codes", action="store_true",
            help="List everyone the picker offers who has no sales code.",
        )
        parser.add_argument("--limit", type=int, default=40)

    def handle(self, *a, **o):
        self.alias = db_router.db_for_write(EmployeeTable) or "default"
        if o["missing_codes"]:
            return self._missing_codes(o["limit"])
        if not o["name"]:
            self.stderr.write('Give a name, or --missing-codes.')
            return
        self._one(o["name"])

    # ── one person ───────────────────────────────────────────────────────────

    def _one(self, name):
        w = self.stdout.write
        w("")
        w(f'Searching for "{name}"')
        w("=" * 68)

        roster = list(
            EmployeeTable.objects.using(self.alias)
            .filter(name__icontains=name)
            .values("staff_id", "name", "job_title", "department",
                    "staff_exit_date", "exit")[:20]
        )
        w("")
        w(f"employee_table (HR roster): {len(roster)} match(es)")
        for r in roster:
            pf = _pf(r["staff_id"])
            exited = r["staff_exit_date"] is not None or r["exit"] == 1
            w(f"  {r['name']}")
            w(f"     PF {pf}   {r['job_title'] or '-'}   {r['department'] or '-'}")
            if exited:
                # This is the one that surprises people: the record is there,
                # the picker just will not offer it.
                w(f"     EXCLUDED from the picker: exit_date="
                  f"{r['staff_exit_date']} exit={r['exit']}")
            else:
                w("     offered by the picker")
            code = self._code_for(pf)
            if code:
                w(f"     sales code {code[0]}  (from {code[1]})")
            elif pf is None:
                w("     NO CODE: staff_id is not a usable PF number, so the "
                  "sales tables cannot be keyed")
            else:
                w(f"     NO CODE: PF {pf} is not in dsr_sales_codes or "
                  "staff_employee_data")

        dsr = list(DSRSalesCode.objects.filter(salesperson__icontains=name)
                   .values_list("salesperson", "sales_code", "pf_number")[:20])
        w("")
        w(f"dsr_sales_codes: {len(dsr)} match(es)")
        for n, code, pf in dsr:
            w(f"  {n}  code={code}  PF={pf}")

        staff = list(StaffEmployeeData.objects.filter(staff_name__icontains=name)
                     .values_list("staff_name", "sales_code", "staff_pf_number",
                                  "is_active")[:20])
        w("")
        w(f"staff_employee_data: {len(staff)} match(es)")
        for n, code, pf, active in staff:
            w(f"  {n}  code={code}  PF={pf}  active={active}"
              + ("" if active else "   (inactive - not merged in)"))

        if not roster and not dsr and not staff:
            w("")
            w("NOT IN ANY OF THE THREE TABLES.")
            w("The picker can only offer people one of these lists carries, so")
            w("this person has to be added to the HR roster upload or the sales")
            w("tables before the desk can pick them. Check the spelling first -")
            w("the search above is a substring match, so try a shorter fragment.")
        w("")

    def _code_for(self, pf):
        """(code, source) for a PF number, using the same precedence as the view."""
        if pf is None:
            return None
        hit = (DSRSalesCode.objects.filter(pf_number=str(pf))
               .values_list("sales_code", flat=True).first())
        if hit:
            return hit, "dsr_sales_codes"
        hit = (StaffEmployeeData.objects.filter(staff_pf_number=pf)
               .values_list("sales_code", flat=True).first())
        if hit:
            return hit, "staff_employee_data"
        return None

    # ── everyone with no code ────────────────────────────────────────────────

    def _missing_codes(self, limit):
        w = self.stdout.write
        rows = list(
            EmployeeTable.objects.using(self.alias)
            .exclude(name__isnull=True).exclude(name="")
            .filter(staff_exit_date__isnull=True).exclude(exit=1)
            .order_by("name")
            .values("staff_id", "name", "job_title")[:2000]
        )
        missing = []
        for r in rows:
            pf = _pf(r["staff_id"])
            if self._code_for(pf) is None:
                missing.append((r["name"], pf, r["job_title"] or "-"))

        w("")
        w(f"{len(missing)} of {len(rows)} current staff have no sales code, so the")
        w("picker offers their name with the code column blank:")
        w("")
        for name, pf, title in missing[:limit]:
            w(f"  {(name or '')[:34]:<34} PF {str(pf):<8} {title[:26]}")
        if len(missing) > limit:
            w(f"  ... and {len(missing) - limit} more")
        w("")
        w("A blank code is a PF that is on the HR roster but not in")
        w("dsr_sales_codes or staff_employee_data. Either the person genuinely")
        w("has no code, or their PF differs between HR and the sales tables.")
        w("")
