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


def team_leader_for_branch(branch) -> str:
    """The team leader who owns ``branch`` (by canonical name), or ''."""
    from apps.staff_management.branches import normalize_branch
    from apps.staff_management.models import TeamLeaderBranch

    canon = normalize_branch(branch)
    if not canon:
        return ""
    try:
        row = (
            TeamLeaderBranch.objects.filter(branch=canon, active=True)
            .values_list("team_leader", flat=True)
            .first()
        )
        return row or ""
    except Exception:
        return ""


def autofill_from_roster(pf_number) -> dict:
    """Best-effort name/branch/department/team_leader for a PF from the staff roster.

    Name + branch come from ``BranchFinalEmployeeDmcData`` (keyed on
    ``staff_pf_number``); department from ``employee_table``; team leader from the
    branch→TL mapping. Never raises — missing data just yields blanks to fill.
    """
    out = {"salesperson": "", "branch": "", "department": "", "team_leader": ""}
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

    # Canonicalise the branch and derive the team leader from the branch→TL map.
    if out["branch"]:
        from apps.staff_management.branches import normalize_branch
        out["branch"] = normalize_branch(out["branch"])
        out["team_leader"] = team_leader_for_branch(out["branch"])

    return out
