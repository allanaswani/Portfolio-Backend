"""DSR seller-code logic: sequential code generation + PF autofill.

Rules (from the DSRs Seller Code Allocation listing):
* ``sales_code`` is ``DSR`` + a number and must NEVER repeat.
* The next code is ``DSR{max existing number + 1}`` — always a fresh number, so a
  code freed by a leaver is not reused (matching how the manual listing grew).
* ``pf_number`` is the unique person key: if a PF already has a code, we return the
  existing one instead of issuing another.
"""

import re

from apps.staff_management.models import DSRSalesCode

_CODE_RE = re.compile(r"DSR0*(\d+)", re.IGNORECASE)


def next_sales_code() -> str:
    """The next unused ``DSR###`` code = max existing number + 1."""
    max_n = 0
    for code in DSRSalesCode.objects.values_list("sales_code", flat=True):
        m = _CODE_RE.match(str(code).strip())
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"DSR{max_n + 1}"


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def autofill_from_roster(pf_number) -> dict:
    """Best-effort name/branch/department for a PF from the staff roster.

    Name + branch come from ``BranchFinalEmployeeDmcData`` (keyed on
    ``staff_pf_number``); department from ``employee_table`` when a matching row
    exists. Never raises — missing data just yields blanks for the user to fill.
    """
    out = {"salesperson": "", "branch": "", "department": ""}
    pf_int = _to_int(pf_number)

    try:
        from apps.staff_management.models import BranchFinalEmployeeDmcData as Dmc

        if pf_int is not None:
            row = (
                Dmc.objects.filter(staff_pf_number=pf_int)
                .values("staff_name", "staff_branch")
                .first()
            )
            if row:
                out["salesperson"] = (row.get("staff_name") or "").strip()
                out["branch"] = (row.get("staff_branch") or "").strip()
    except Exception:
        pass

    try:
        from apps.gceo_dashboard.models import EmployeeTable as Emp

        if pf_int is not None:
            er = (
                Emp.objects.filter(staff_id=pf_int)
                .values("name", "department")
                .first()
            )
            if er:
                out["salesperson"] = out["salesperson"] or (er.get("name") or "").strip()
                out["department"] = (er.get("department") or "").strip()
    except Exception:
        pass

    return out
