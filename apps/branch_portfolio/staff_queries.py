"""Branch-scoped staff reads — who works at a branch, and in which department.

There is no single table that answers "the employees of BURUBURU BRANCH, by
department". Two halves have to be joined:

* **Which branch a person is posted to** lives only in the sales/branch DMC
  tables (``branch_final_employee_dmc_data``, ``branch_employee_dmc_data``).
  They carry ``staff_branch`` / ``brn_code`` — and roughly 808 customer-facing
  staff, not the whole company.
* **Which department a person belongs to** lives only in the HR roster
  (``employee_table``, ~1,271 rows). It has ``department`` / ``division`` /
  ``grade`` but **no branch column at all**.

The bridge is the PF number: ``employee_table.staff_id`` (a numeric) is the same
identifier as ``branch_*_employee_dmc_data.staff_pf_number``. That join is what
makes a per-branch, per-department view possible.

Two fan-out traps are handled explicitly, both previously seen in production:

* the DMC tables hold MORE THAN ONE ROW PER PERSON (one per role/sales code), so
  a plain join double-counts headcount. Deduped with ``DISTINCT ON``;
* ``employee_table`` can hold repeat rows for one ``staff_id``. Also deduped.

Department name follows the same chain the admin roster page uses — the
per-employee overlay override first, then the HR department, then the DMC
``staff_unit`` — and every row reports which of those it came from in
``department_source`` so nothing is silently invented.

``employee_table`` and ``employee_roster_overlay`` are joined only when they
actually exist. ``employee_table`` is a ``managed = False`` warehouse mirror, so
it is absent from a test database and can be absent in production too (this
deployment has known schema drift). Missing means the department falls back to
the DMC unit; it must never mean the whole query errors out.
"""

from django.db import connection

from apps.gceo_dashboard.departments import standardize_department
from core.branch_codes import normalize_branch

_HR_TABLE = "employee_table"
_OVERLAY_TABLE = "employee_roster_overlay"

# Matches a branch by NAME (suffix-insensitive, so "HEAD OFFICE" == "HEAD OFFICE
# BRANCH") OR by any of its numeric codes.
_BRANCH_PREDICATE = (
    r"(regexp_replace(upper(btrim(staff_branch)), '\s+BRANCH$', '') = %s"
    r" OR brn_code = ANY(%s))"
)

# Both DMC tables spell the exit flag differently — `exit` on the final table,
# `staff_exit` on the other — so the UNION normalises it to `exited`.
_BASE_CTES = """
WITH dmc AS (
    SELECT id, staff_pf_number, staff_name, staff_unit, staff_role, staff_branch,
           staff_email, brn_code, sales_code, employment_date, exit_date,
           COALESCE("exit", 0)     AS exited,
           COALESCE(active, 0)     AS active
    FROM   branch_final_employee_dmc_data
    WHERE  {branch_predicate}
    UNION ALL
    SELECT id, staff_pf_number, staff_name, staff_unit, staff_role, staff_branch,
           staff_email, brn_code, sales_code, employment_date, exit_date,
           COALESCE(staff_exit, 0) AS exited,
           COALESCE(active, 0)     AS active
    FROM   branch_employee_dmc_data
    WHERE  {branch_predicate}
),
one_per_staff AS (
    -- One row per person. Prefer a non-exited row, then the most recent id.
    SELECT DISTINCT ON (staff_pf_number) *
    FROM   dmc
    WHERE  staff_pf_number IS NOT NULL
    ORDER  BY staff_pf_number, exited ASC, id DESC
)"""

_HR_CTE = """,
hr AS (
    SELECT DISTINCT ON (staff_id)
           staff_id, department, division, unit, org_unit, grade, job_title,
           gender, service_years, date_of_employment,
           COALESCE("exit", 0) AS hr_exited
    FROM   employee_table
    WHERE  staff_id IS NOT NULL
    ORDER  BY staff_id, id DESC
)"""

_HR_SELECT = """
    hr.department AS hr_department, hr.division, hr.unit AS hr_unit,
    hr.org_unit, hr.grade, hr.job_title, hr.gender, hr.service_years,
    hr.date_of_employment, hr.hr_exited"""

# Same column names and types, so the row dict is identical either way.
_HR_SELECT_ABSENT = """
    NULL::text AS hr_department, NULL::text AS division, NULL::text AS hr_unit,
    NULL::text AS org_unit, NULL::text AS grade, NULL::text AS job_title,
    NULL::text AS gender, NULL::int AS service_years,
    NULL::timestamp AS date_of_employment, 0 AS hr_exited"""

_HR_JOIN = "\nLEFT JOIN  hr ON hr.staff_id = s.staff_pf_number"

_OVERLAY_SELECT = """
    o.standard_department AS overlay_department,
    o.current_role        AS overlay_role"""

_OVERLAY_SELECT_ABSENT = """
    NULL::text AS overlay_department,
    NULL::text AS overlay_role"""

_OVERLAY_JOIN = "\nLEFT JOIN  employee_roster_overlay o ON o.staff_id = s.staff_pf_number::text"


def _table_exists(name):
    try:
        return name in set(connection.introspection.table_names())
    except Exception:
        return False


def _build_sql(branch_predicate):
    has_hr = _table_exists(_HR_TABLE)
    has_overlay = _table_exists(_OVERLAY_TABLE)

    sql = _BASE_CTES.format(branch_predicate=branch_predicate)
    if has_hr:
        sql += _HR_CTE
    sql += """
SELECT
    s.staff_pf_number, s.staff_name, s.staff_role, s.staff_unit, s.staff_branch,
    s.staff_email, s.brn_code, s.sales_code, s.employment_date, s.exit_date,
    s.exited, s.active,"""
    sql += (_HR_SELECT if has_hr else _HR_SELECT_ABSENT) + ","
    sql += (_OVERLAY_SELECT if has_overlay else _OVERLAY_SELECT_ABSENT)
    sql += "\nFROM       one_per_staff s"
    if has_hr:
        sql += _HR_JOIN
    if has_overlay:
        sql += _OVERLAY_JOIN
    sql += "\nORDER BY   s.staff_name"
    return sql


def _resolve_department(row):
    """Canonical department + where it came from.

    Chain: the admin overlay override → the HR roster department → the DMC
    ``staff_unit`` (all this roster knows for someone absent from HR).
    """
    overlay = (row.get("overlay_department") or "").strip()
    if overlay:
        return standardize_department(overlay), "overlay"
    hr = (row.get("hr_department") or "").strip()
    if hr:
        return standardize_department(hr), "hr_roster"
    unit = (row.get("staff_unit") or "").strip()
    if unit:
        return standardize_department(unit), "dmc_unit"
    return "Unassigned", "none"


def branch_staff(branch_name, codes, all_branches=False):
    """Every employee posted to the branch, one row each, with a department.

    ``all_branches`` is the EXCO/CEO roll-up; otherwise an unresolvable branch
    (blank name AND no codes) returns nothing rather than the whole company.
    """
    key = normalize_branch(branch_name)
    code_list = [int(c) for c in (codes or [])]

    if all_branches:
        predicate, params = "TRUE", []
    elif not key and not code_list:
        return []
    else:
        predicate = _BRANCH_PREDICATE
        params = [key, code_list]

    sql = _build_sql(predicate)
    # The predicate appears once per UNION arm, so its params go in twice.
    with connection.cursor() as cur:
        cur.execute(sql, params + params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    out = []
    for r in rows:
        department, source = _resolve_department(r)
        out.append({
            "staff_pf_number": r["staff_pf_number"],
            "staff_name":      r["staff_name"],
            "department":      department,
            "department_source": source,
            "division":        r["division"],
            # org_unit is the HR org unit — in this roster it is the closest
            # thing to a cost centre, so it is surfaced rather than dropped.
            # `unit` is the finer HR unit; `staff_unit` is what the branch/sales
            # roster calls the same person's unit and does not always agree.
            "org_unit":        r["org_unit"],
            "unit":            r["hr_unit"] or r["staff_unit"],
            "role":            (r["overlay_role"] or r["job_title"] or r["staff_role"] or ""),
            "grade":           r["grade"],
            "gender":          r["gender"],
            "branch":          r["staff_branch"],
            "brn_code":        r["brn_code"],
            "sales_code":      r["sales_code"],
            "email":           r["staff_email"],
            "employment_date": r["date_of_employment"] or r["employment_date"],
            "service_years":   r["service_years"],
            "exit_date":       r["exit_date"],
            # Exited if EITHER source says so — HR is authoritative for leavers,
            # but the DMC roster is what carries the branch posting.
            "exited":          bool(r["exited"]) or bool(r["hr_exited"]),
            "active":          bool(r["active"]),
            "in_hr_roster":    bool(r["hr_department"]) or bool(r["grade"]),
        })
    return out


def rollup_by_department(staff_rows):
    """Fold the per-employee rows into one row per department."""
    buckets = {}
    for s in staff_rows:
        b = buckets.setdefault(s["department"], {
            "department": s["department"],
            "headcount": 0, "active": 0, "exited": 0, "in_hr_roster": 0,
            "roles": set(), "org_units": set(), "grades": set(),
        })
        b["headcount"] += 1
        b["active"]    += 1 if s["active"] and not s["exited"] else 0
        b["exited"]    += 1 if s["exited"] else 0
        b["in_hr_roster"] += 1 if s["in_hr_roster"] else 0
        if s["role"]:
            b["roles"].add(s["role"])
        if s.get("org_unit"):
            b["org_units"].add(s["org_unit"])
        if s.get("grade"):
            b["grades"].add(s["grade"])

    rows = []
    for b in buckets.values():
        b["distinct_roles"] = len(b.pop("roles"))
        # Listed, not just counted: a branch manager reading a headcount wants
        # to see WHICH cost centres and grades sit behind it.
        b["org_units"] = sorted(b["org_units"])
        b["grades"] = sorted(b["grades"])
        rows.append(b)
    rows.sort(key=lambda r: (-r["headcount"], r["department"]))
    return rows
