"""DMC performance targets — the numbers the bank actually plans against.

Where the targets live
──────────────────────
Two ETL/CSV-fed tables in ``apps.staff_management.models`` carry a ``target_*``
column per KPI. They are **different grains** and must never be summed together
for the same metric:

* ``branch_final_employee_dmc_data`` (model :class:`BranchFinalEmployeeDmcData`)
  — 22 rows in production, one per **branch**, held by that branch's BBM. Its
  CSV upload upserts on ``staff_branch`` alone, which is what keeps it one row
  per branch. This is the **branch/zone/bank** target source: summing it counts
  every branch exactly once.
* ``branch_employee_dmc_data`` (model :class:`BranchEmployeeDmcData`) — ~786
  rows, one per **sales staff member**, upserted on
  ``(staff_pf_number, sales_code, staff_role)``. This is the **RM / team-leader**
  target source.

(Row counts verified against production in August 2026 — 22 + 786 = the 808
customer-facing staff behind the old "All Employees" figure.)

Both tables hold *annual* targets for one planning cycle, keyed by
``start_date`` (e.g. 2026-01-01 for the 2026 plan).

The double-counting rule
────────────────────────
A branch's deposit target appears **both** on its BBM row and, split up, across
its RMs' rows. Adding them would roughly double the figure. So each scope reads
one primary table, and only borrows the *other* table for metrics its primary
does not carry at all:

===========  ====================  ==========================================
scope        primary source        why
===========  ====================  ==========================================
bank         branch (22 rows)      every branch counted once
zone         branch                ditto, filtered on ``staff_zone``
branch       branch                the single authoritative branch row
team_leader  staff                 a TL owns RMs, not branches
rm           staff                 the individual's own row
===========  ====================  ==========================================

Direction
─────────
Most targets are "hit or beat it" (``up``). Provisions and NPL are ceilings —
coming in *under* is good (``down``) — so achievement for those is inverted by
the caller (see ``direction`` in the catalogue and ``lib/perf.ts`` on the
frontend). Getting this backwards would paint a well-run branch red.

Provenance
──────────
This is not a new invention — the *old* portfolio tool already read these
columns, and three target↔actual pairings are copied from it verbatim so the
new dashboards agree with what branch managers used to see
(``_old_codebase_ref/hf_group_project/core/core.py``):

* ``BranchYTDDepositGrowthTarget`` — ``target_deposits_value`` as the FY target,
  ``* EXTRACT(DOY FROM CURRENT_DATE) / 365`` as the YTD target, compared against
  **deposit YTD movement** (current balance − last December's balance).
* ``BranchYTDAssetGrowthTarget`` — ``target_asset_growth_value`` the same way,
  against **loan-book YTD movement**.
* ``BranchYTDRevenuePerformance`` — ``target_pbt_revenue`` pro-rated
  ``* max_month / 12``, against YTD ``pbt_after_provisions_without_hq_cost``.

Neither growth-target endpoint was ported when branch_portfolio was migrated,
which is why the new KPI tiles had no targets to show.
"""

from datetime import date

from django.db.models import Count, Sum

# ── Metric catalogue ─────────────────────────────────────────────────────────
# (key, column, unit, label, direction, basis). ``column`` is the identical
# field name on whichever DMC table carries it — the two models were compared
# field by field to build this list, so a key maps to at most one column per
# table. ``basis`` says what kind of actual the target must be compared to:
#   movement — YTD change in a balance (this year minus last December)
#   flow     — accumulated over the year (disbursement, premiums, new customers)
#   level    — a ceiling on a stock figure (NPL, provisions)
# Comparing a "movement" target against a balance would read ~2% and paint an
# on-plan branch red, so the frontend must honour this field.
CATALOGUE = [
    # money — growth
    ("deposits",                     "target_deposits_value",              "currency", "Deposit Growth",               "up", "movement"),
    ("savings",                      "target_savings_value",               "currency", "Savings Value",                "up", "flow"),
    ("loan_disbursement",            "target_loan_disbursement",           "currency", "Loan Disbursement",            "up", "flow"),
    ("retail_loan_disbursement",     "target_retail_loan_disbursement",    "currency", "Retail Loan Disbursement",     "up", "flow"),
    ("commercial_loan_disbursement", "target_commercial_loan_disbursement","currency", "Commercial Loan Disbursement", "up",   "flow"),
    ("asset_growth",                 "target_asset_growth_value",          "currency", "Asset Growth (loan book)",     "up", "movement"),
    ("pbt_revenue",                  "target_pbt_revenue",                 "currency", "PBT Revenue",                  "up", "flow"),
    ("loan_approvals",               "target_loan_approvals",              "currency", "Loan Approvals",               "up", "flow"),
    ("banca_value",                  "target_banca_value",                 "currency", "Bancassurance Premium",        "up", "flow"),
    ("banca_life",                   "target_banca_life",                  "currency", "Banca — Life",                 "up", "flow"),
    ("banca_non_life",               "target_banca_non_life",              "currency", "Banca — Non-Life",             "up", "flow"),
    ("banca_motor",                  "target_banca_motor",                 "currency", "Banca — Motor",                "up", "flow"),
    ("banca_non_motor",              "target_banca_non_motor",             "currency", "Banca — Non-Motor",            "up", "flow"),
    ("trade_finance_income",         "target_trade_finance_income",        "currency", "Trade Finance Income",         "up", "flow"),
    ("trade_finance_value",          "target_trade_finance_value",         "currency", "Trade Finance Value",          "up", "flow"),
    ("forex",                        "target_forex",                       "currency", "Forex Income",                 "up", "flow"),
    ("tills_value",                  "target_tills_value",                 "currency", "Tills Value",                  "up", "flow"),
    ("mortgage_mrkt_rate",           "target_mortgage_mrkt_rate",          "currency", "Mortgage — Market Rate",       "up", "flow"),
    ("mortgage_non_mrkt_rate",       "target_mortgage_non_mrkt_rate",      "currency", "Mortgage — Non-Market Rate",   "up", "flow"),
    # counts — growth
    ("new_customers",                "target_new_customers",               "number",   "New Customers",                "up", "flow"),
    ("active_new_customers",         "target_active_new_customers",        "number",   "Active New Customers",         "up", "flow"),
    ("focus_accounts",               "target_focus_accounts",              "number",   "Focus Accounts",               "up", "flow"),
    ("dormancy_activations",         "target_dormancy_activations",        "number",   "Dormancy Activations",         "up", "flow"),
    ("tills_volume",                 "target_tills_volume",                "number",   "Tills Volume",                 "up", "flow"),
    ("bank_tills_volume",            "target_bank_tills_volume",           "number",   "Bank Tills Volume",            "up", "flow"),
    ("saf_tills_volume",             "target_saf_tills_volume",            "number",   "Safaricom Tills Volume",       "up", "flow"),
    ("tills_transactions",           "target_tills_transactions",          "number",   "Till Transactions",            "up", "flow"),
    ("active_tills",                 "target_active_tills",                "number",   "Active Tills",                 "up", "flow"),
    ("properties",                   "target_properties",                  "number",   "Property Sales",               "up", "flow"),
    ("training_hours",               "target_training_hours",              "number",   "Training Hours",               "up", "flow"),
    # ceilings — coming in UNDER target is good
    ("loan_provisions",              "target_loan_provisions",             "currency", "Loan Provisions",              "down", "level"),
    ("npl",                          "target_npl",                         "currency", "NPL",                          "down", "level"),
]

META = {key: {"key": key, "column": col, "unit": unit, "label": label,
              "direction": dirn, "basis": basis}
        for key, col, unit, label, dirn, basis in CATALOGUE}

SCOPES = ("bank", "zone", "branch", "team_leader", "rm")

# Which table leads for each scope — see the module docstring.
_PRIMARY = {"bank": "branch", "zone": "branch", "branch": "branch",
            "team_leader": "staff", "rm": "staff"}


def _models():
    from apps.staff_management.models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
    )
    return {"branch": BranchFinalEmployeeDmcData, "staff": BranchEmployeeDmcData}


def _columns(model):
    """The ``target_*`` fields this model actually has."""
    return {f.name for f in model._meta.fields if f.name.startswith("target_")}


def tl_branches(team_leader):
    """The branches a team leader owns, from the ``team_leader_branches`` map.

    TL Portfolio is *segment*-scoped while the DMC tables are branch-shaped, so
    there is no column to join on. ``TeamLeaderBranch`` is the bank's own
    branch→TL mapping and is the authoritative link: a TL's plan is the sum of
    their branches' plans.

    Returns the canonical (normalised) names — see
    :mod:`apps.staff_management.branches` for why raw names cannot be compared
    directly ("SAMEER" vs "SAMEER BUSINESS PARK BRANCH").
    """
    from apps.staff_management.models import TeamLeaderBranch
    from apps.staff_management.branches import normalize_branch

    if not team_leader:
        return []
    names = TeamLeaderBranch.objects.filter(
        team_leader__iexact=str(team_leader).strip(), active=True,
    ).values_list("branch", flat=True)
    return sorted({normalize_branch(n) for n in names if n})


def _dmc_rows_for_branches(model, canonical_names):
    """Raw ``staff_branch`` values on ``model`` whose canonical form is in
    ``canonical_names``. The DMC file and the TL sheet spell branches
    differently, so both sides are normalised before matching."""
    from apps.staff_management.branches import normalize_branch

    if not canonical_names:
        return []
    wanted = set(canonical_names)
    raw = _active(model.objects.all(), model).values_list("staff_branch", flat=True)
    return sorted({r for r in raw if r and normalize_branch(r) in wanted})


def _active(qs, model):
    """Current staff only. The two tables spell the exit flag differently:
    ``exit`` on the branch table, ``staff_exit`` on the staff table."""
    names = {f.name for f in model._meta.fields}
    if "active" in names:
        qs = qs.filter(active=1)
    for flag in ("exit", "staff_exit"):
        if flag in names:
            qs = qs.exclude(**{flag: 1})
    return qs


def _scoped(model, scope, value, tl_branch_names=None):
    """Filter a DMC table down to one scope. Returns ``None`` when the scope
    needs a value and none was given.

    ``tl_branch_names`` — when a team leader resolved through the
    ``team_leader_branches`` map, both tables are filtered to that TL's branches
    rather than to the DMC file's own ``team_leader`` column.
    """
    qs = _active(model.objects.all(), model)
    if scope == "bank":
        return qs
    if not value:
        return None
    v = str(value).strip()
    if scope == "zone":
        return qs.filter(staff_zone__iexact=v)
    if scope == "branch":
        # Callers pass either the branch name or its numeric code.
        if v.isdigit():
            return qs.filter(brn_code=int(v))
        return qs.filter(staff_branch__iexact=v)
    if scope == "team_leader":
        if tl_branch_names:
            rows = _dmc_rows_for_branches(model, tl_branch_names)
            return qs.filter(staff_branch__in=rows) if rows else qs.none()
        return qs.filter(team_leader__iexact=v)
    if scope == "rm":
        return qs.filter(sales_code__iexact=v)
    return None


def _year_scoped(qs, year):
    """Restrict to one planning cycle, keyed on ``start_date``.

    The tables are upserted in place, so historic cycles may simply not be
    there. Rather than return a screen of zeros for a year that was never
    loaded, fall back to the unfiltered rows and report that in ``year_filtered``.
    """
    if not year:
        return qs, False
    filtered = qs.filter(start_date__year=year)
    if filtered.exists():
        return filtered, True
    return qs, False


# ── Proration ────────────────────────────────────────────────────────────────
# Targets are annual. Comparing a January actual against a full-year target
# would read 8% and paint everything red, so each window gets its slice of the
# year. This mirrors ``targetForGrain`` in the frontend's lib/perf.ts — the two
# must stay in step, so both use the same day-of-year arithmetic.

def prorate(annual, today=None, unit="currency"):
    """Slice an annual target into the windows a dashboard compares against.

    ``unit="number"`` targets are counts — customers, accounts, tills, training
    hours. Pro-rating leaves them fractional (897 new customers x 247/365 =
    589.578) and the UI then renders "YTD target 589.578", which is meaningless
    to a branch manager. Counts are rounded to whole units; money is not.
    """
    if annual is None:
        return {"annual": None, "ytd": None, "qtd": None,
                "mtd": None, "daily": None, "weekly": None, "months_elapsed": None}
    today = today or date.today()
    day_of_year = (today - date(today.year, 1, 1)).days + 1
    leap = today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0)
    days_in_year = 366 if leap else 365
    quarter_month = (today.month - 1) % 3 + 1      # 1..3 within the current quarter
    a = float(annual)

    def shape(v):
        return float(round(v)) if unit == "number" else v

    return {
        "annual": shape(a),
        "ytd":    shape(a * (day_of_year / days_in_year)),
        "qtd":    shape((a / 4) * (quarter_month / 3)),
        "mtd":    shape(a / 12),
        "daily":  shape(a / days_in_year),
        "weekly": shape(a / 52),
        "months_elapsed": today.month,
    }


def rollup(scope, value=None, year=None, today=None):
    """Aggregate every catalogue metric for one scope.

    Returns ``{"scope", "value", "year", "year_filtered", "sources", "targets"}``
    where ``targets[key]`` is the metric's meta plus its annual figure and the
    pro-rated windows.
    """
    scope = (scope or "bank").strip().lower()
    if scope not in SCOPES:
        raise ValueError(f"unknown scope '{scope}' (expected one of {', '.join(SCOPES)})")

    models = _models()

    # A team leader is resolved through the branch→TL map when one exists: their
    # plan is the sum of their branches' plans, which comes off the branch table.
    # Only when that map has nothing for them do we fall back to the DMC file's
    # own `team_leader` column (which names each RM's line manager).
    tl_branch_names, resolved_via = [], None
    if scope == "team_leader":
        tl_branch_names = tl_branches(value)
        resolved_via = "team_leader_branches" if tl_branch_names else "dmc_team_leader_column"

    primary = "branch" if (scope == "team_leader" and tl_branch_names) else _PRIMARY[scope]
    secondary = "staff" if primary == "branch" else "branch"

    querysets, sources = {}, {}
    for name in (primary, secondary):
        model = models[name]
        qs = _scoped(model, scope, value, tl_branch_names=tl_branch_names)
        if qs is None:
            querysets[name] = None
            sources[name] = {"table": model._meta.db_table, "rows": 0,
                             "year_filtered": False, "used": False}
            continue
        qs, year_filtered = _year_scoped(qs, year)
        querysets[name] = qs
        sources[name] = {
            "table": model._meta.db_table,
            "rows": qs.aggregate(n=Count("id"))["n"] or 0,
            "year_filtered": year_filtered,
            "used": name == primary,
        }

    # One aggregate query per table rather than one per metric.
    totals = {}
    for name in (primary, secondary):
        qs = querysets[name]
        if qs is None:
            totals[name] = {}
            continue
        wanted = {col for _, col, _, _, _, _ in CATALOGUE} & _columns(models[name])
        totals[name] = qs.aggregate(**{col: Sum(col) for col in sorted(wanted)}) if wanted else {}

    targets = {}
    for key, col, unit, label, direction, basis in CATALOGUE:
        # The primary table wins whenever it carries the column at all; the
        # secondary only fills metrics the primary does not have. Never the same
        # metric from both — that is exactly what would double-count.
        source = None
        if col in totals.get(primary, {}):
            source = primary
        elif col in totals.get(secondary, {}):
            source = secondary
        raw = totals.get(source, {}).get(col) if source else None
        entry = {"key": key, "label": label, "unit": unit, "direction": direction,
                 "basis": basis, "column": col,
                 "source": sources[source]["table"] if source else None}
        entry.update(prorate(raw, today=today, unit=unit))
        targets[key] = entry

    return {
        "scope": scope,
        "value": value or "",
        "year": year,
        "year_filtered": any(s.get("year_filtered") for s in sources.values()),
        "resolved_via": resolved_via,
        "branches": tl_branch_names,
        "sources": sources,
        "targets": targets,
    }
