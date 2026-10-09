"""Every scorecard the platform holds, who holds it, and what it can answer.

The cards were seeded and then existed only in the database: there was nowhere
to look at them. This is that place - for the person configuring them, not for
the person being measured.

Three questions it answers, which are the three people ask:

* **what cards are there** - 22 of them now, twelve sales and ten back office,
  with each line's weight, target and feed;
* **who holds which** - across all three rosters, because a teller is on none
  of the sales ones;
* **how much of a card can actually be scored** - measured from the warehouse,
  loadable by Administration, or stranded.

It reads. Nothing here writes.
"""

from __future__ import annotations

from collections import defaultdict

#: Cards whose role codes start with this are the back-office (non-sales) set.
BO_PREFIX = "bo_"


def _coverage(kpi_code, source, has_target):
    """What can be done with one line: ``measured``, ``loadable`` or
    ``stranded``.

    The distinction is the whole point of the screen. "Pending" lumps together
    a figure nobody has loaded yet with one nobody can ever load, and those go
    to different people.
    """
    from .scorecard_manual import MANUAL_ACTUALS, MANUAL_TARGETS

    if not has_target and kpi_code not in MANUAL_TARGETS:
        return "stranded"
    if source is not None and not source.pending and source.actual_key:
        return "measured"
    if kpi_code in MANUAL_ACTUALS:
        return "loadable"
    return "stranded"


def cards(role_code=""):
    """Every configured card, or one of them in full.

    Without ``role_code``: a row per card with its line count, total weight and
    coverage. With one: that card's lines, in the order they appear on it.
    """
    from .live_scorecard import FULL_YEAR_TARGETS, SOURCES
    from .scorecard_automation.models import (
        ScKpi, ScRole, ScRoleKpiMapping)
    from .scorecard_manual import MANUAL_ACTUALS, MANUAL_TARGETS

    wanted = (role_code or "").strip()
    mappings = ScRoleKpiMapping.objects.all().order_by("role_code", "kpi_order")
    if wanted:
        mappings = mappings.filter(role_code=wanted)
    mappings = list(mappings)

    kpis = {k.kpi_code: k for k in ScKpi.objects.all()}
    names = dict(ScRole.objects.values_list("role_code", "role_name"))
    holders = _holder_counts()

    per_role = defaultdict(list)
    for mapping in mappings:
        per_role[mapping.role_code].append(mapping)

    out = []
    for code, lines in sorted(per_role.items()):
        counts = defaultdict(float)
        detail = []
        for mapping in lines:
            kpi = kpis.get(mapping.kpi_code)
            source = SOURCES.get(mapping.kpi_code)
            has_target = mapping.kpi_target is not None
            state = _coverage(mapping.kpi_code, source, has_target)
            weight = float(mapping.kpi_weight or 0)
            counts[state] += weight
            if wanted:
                detail.append({
                    "kpi_order": mapping.kpi_order,
                    "kpi_code": mapping.kpi_code,
                    "kpi_name": (kpi.kpi_name if kpi else mapping.kpi_code),
                    "perspective": mapping.mapping_category,
                    "weight": weight,
                    # This role's own wording, which is what is on their card.
                    "measure_of_success": (
                        getattr(mapping, "kpi_description", "")
                        or (kpi.kpi_description if kpi else "")),
                    "target": mapping.kpi_target,
                    "target_basis": getattr(mapping, "target_basis", ""),
                    "target_base": getattr(mapping, "target_base", ""),
                    "full_year": mapping.kpi_code in FULL_YEAR_TARGETS,
                    "feed": (kpi.actuals_sheet if kpi else ""),
                    "coverage": state,
                    "loadable_actual": mapping.kpi_code in MANUAL_ACTUALS,
                    "loadable_target": mapping.kpi_code in MANUAL_TARGETS,
                    "is_active": bool(kpi.is_active) if kpi else False,
                    "not_configured_reason": (
                        kpi.not_configured_reason if kpi else ""),
                    "pending": source.pending if source else "",
                })
        total = sum(counts.values())
        card = {
            "role_code": code,
            "role_name": names.get(code, code),
            "family": "back office" if code.startswith(BO_PREFIX) else "sales",
            "lines": len(lines),
            "total_weight": round(total, 5),
            "holders": holders.get(code, 0),
            "measured_weight": round(counts["measured"], 5),
            "loadable_weight": round(counts["loadable"], 5),
            "stranded_weight": round(counts["stranded"], 5),
        }
        if wanted:
            card["kpis"] = detail
        out.append(card)
    return out


def _holder_counts():
    """How many people hold each card, across all three rosters."""
    from .live_scorecard import role_code_for
    from .models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData, EmployeeRoleHistory)

    counts, seen = defaultdict(int), set()
    for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData):
        for code, role_text in (model.objects.exclude(sales_code="")
                                .values_list("sales_code", "staff_role")):
            folded = (code or "").strip().upper()
            if not folded or folded in seen:
                continue
            role = role_code_for(role_text)
            if role is None:
                continue
            seen.add(folded)
            counts[role] += 1
    for code, role in (EmployeeRoleHistory.objects
                       .filter(role_code__startswith=BO_PREFIX)
                       .values_list("sales_code", "role_code")):
        folded = (code or "").strip().upper()
        if not folded or folded in seen:
            continue
        seen.add(folded)
        counts[role] += 1
    return counts


def roster(role_code="", search=""):
    """Who holds a card → one row per person, from whichever roster knows them.

    The roster is the thing that was missing: ten back-office cards are no use
    until the platform knows that EKN1329 is a branch operations manager, and
    that is on none of the sales tables.
    """
    from .live_scorecard import role_code_for
    from .models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData, EmployeeRoleHistory,
        StaffEmployeeData)
    from .scorecard_automation.models import ScRole

    wanted = (role_code or "").strip()
    needle = (search or "").strip().lower()
    names = dict(ScRole.objects.values_list("role_code", "role_name"))

    out, seen = [], set()
    for model, label in ((BranchEmployeeDmcData, "branch_employee_dmc_data"),
                         (BranchFinalEmployeeDmcData,
                          "branch_final_employee_dmc_data")):
        for row in model.objects.exclude(sales_code="").order_by("sales_code"):
            code = (row.sales_code or "").strip().upper()
            if not code or code in seen:
                continue
            role = role_code_for(row.staff_role)
            if role is None:
                continue
            seen.add(code)
            out.append({
                "sales_code": code,
                "staff_name": row.staff_name or "",
                "role_code": role,
                "role_name": names.get(role, role),
                "role_on_roster": row.staff_role or "",
                "branch": row.staff_branch or row.staff_unit or "",
                "line_manager": getattr(row, "team_leader", "") or "",
                "roster": label,
                "family": "sales",
            })

    staff = {(code or "").strip().upper(): (name, unit) for code, name, unit
             in StaffEmployeeData.objects.exclude(sales_code="")
             .values_list("sales_code", "staff_name", "staff_unit")}
    for entry in (EmployeeRoleHistory.objects
                  .filter(role_code__startswith=BO_PREFIX)
                  .order_by("sales_code")):
        code = (entry.sales_code or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        # Migration 0032 kept name, branch, zone and line manager in notes,
        # because employee_role_history has nowhere else for them. The HR
        # record wins where it has something.
        parts = [piece.strip() for piece in (entry.notes or "").split("|")]
        parts += [""] * (4 - len(parts))
        name, unit = staff.get(code, ("", ""))
        out.append({
            "sales_code": code,
            "staff_name": name or parts[0],
            "role_code": entry.role_code,
            "role_name": names.get(entry.role_code, entry.role_code),
            "role_on_roster": entry.role_code,
            "branch": unit or parts[1],
            "line_manager": parts[3],
            "roster": "employee_role_history",
            "family": "back office",
        })

    if wanted:
        out = [row for row in out if row["role_code"] == wanted]
    if needle:
        out = [row for row in out
               if needle in row["sales_code"].lower()
               or needle in (row["staff_name"] or "").lower()
               or needle in (row["branch"] or "").lower()]
    return sorted(out, key=lambda row: (row["role_code"], row["sales_code"]))


def cards_without_holders():
    """Cards nobody holds, which is a question rather than a fault.

    ``bo_cash_teller`` and ``bo_bom_cso`` have nobody on the workbook's own
    List sheet. Seeding them onto the 41 tellers or the 25 branch operations
    managers would have been a guess, so they are here instead.
    """
    from .scorecard_automation.models import ScRole, ScRoleKpiMapping

    configured = set(ScRoleKpiMapping.objects.values_list(
        "role_code", flat=True))
    holders = _holder_counts()
    names = dict(ScRole.objects.values_list("role_code", "role_name"))
    return [
        {"role_code": code,
         "role_name": names.get(code, code),
         "family": "back office" if code.startswith(BO_PREFIX) else "sales"}
        for code in sorted(configured) if not holders.get(code)
    ]
