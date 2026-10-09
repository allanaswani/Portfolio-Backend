"""An RM's scorecard built from what the system already holds.

No upload, and nothing to remember to run. Everything a card needs is already
in the platform, in three places:

**Who they are and what they are measured on** — ``branch_final_employee_dmc_data``
carries, per ``sales_code``: ``staff_role``, ``staff_branch``, ``team_leader``,
``active`` and ``start_date``. That is the roster. There is no second roster to
load.

**Their targets** — the same DMC rows carry ``target_deposits_value``,
``target_asset_growth_value``, ``target_loan_disbursement``,
``target_new_customers``, ``target_pbt_revenue``, ``target_banca_value``,
``target_trade_finance_income`` and the rest. These are the plan numbers the
business already sets; they are per person and already prorated by
``staff_management.targets.prorate``.

**Their actuals** — the warehouse, read per ``sales_code`` through the
functions /rm-portfolio already uses: ``rm_revenue`` for interest income,
interest expense, NFI, FTP and loan loss; ``rm_balances`` for the deposit and
loan position as at yesterday; ``rm_new_customers_ytd``; ``ppc``; and
``drawdown_daily`` for disbursements.

So the card is computed when it is asked for, from data that moves on its own.
Reload the page tomorrow and the deposit line has moved, because
``daily_balance_movement`` has.

**What this deliberately does not do.** A KPI whose actual exists nowhere in
the warehouse — NPS, mystery shopping, training hours, leave, covenant
tracking, branch audit — is returned as *pending* with the reason, never as a
zero. Scoring somebody nought on a number nobody has is worse than leaving the
line blank, and an RM can see at a glance which half of their card is live.

The weights and the grouping come from ``sc_role_kpi_mappings``, seeded from
the eight role cards, so a line carries the weight it carries on the card.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

#: What the DMC roster calls a role -> the seeded ScRole.role_code. Matched on
#: a folded form, because the same role is written several ways across the two
#: DMC tables ("SME RM", "Sme Rm", "SME  RM").
ROLE_ALIASES = {
    "sme rm": "sme_rm",
    "sme arm": "sme_arm",
    "sme bbc": "sme_bbc",
    "sme bbc rm": "sme_bbc",
    "pb rm": "pb_rm",
    "personal banking rm": "pb_rm",
    "pb arm": "pb_arm",
    "pb bbc": "pb_bbc",
    "ultimate rm": "ultimate_rm",
    "snr rm": "ultimate_rm",
    "diaspora rm": "diaspora_rm",
    "diaspora arm": "diaspora_arm",
    "mortgage business arm": "mortgage_business_arm",
    "mortgage arm": "mortgage_business_arm",
    "commercial rm": "commercial_rm",
    "commercial rm trade": "commercial_rm_trade",
    "commercial rm- trade": "commercial_rm_trade",
    "commercial trade rm": "commercial_rm_trade",
}


def fold(text):
    return " ".join(str(text or "").replace("-", " ").split()).strip().lower()


def role_code_for(staff_role):
    """The scorecard role for a DMC ``staff_role``, or None.

    None rather than a guess: being scored against the wrong card is worse
    than not being scored, and the page says which it is.
    """
    folded = fold(staff_role)
    if folded in ROLE_ALIASES:
        return ROLE_ALIASES[folded]
    # "SME RM - Nairobi" and the like: take the longest alias the role starts
    # with, so "sme bbc" wins over "sme" and nothing matches on a bare word.
    for alias in sorted(ROLE_ALIASES, key=len, reverse=True):
        if folded.startswith(alias + " ") or folded == alias:
            return ROLE_ALIASES[alias]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# What each KPI line is, in terms the system already has
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Source:
    """Where one KPI's target and actual come from."""

    #: Field on the DMC roster row holding the year's target.
    target_field: str = ""
    #: Key into what :func:`live_actuals` returns.
    actual_key: str = ""
    #: Larger is better. Loan loss and PAR are the exceptions.
    higher_is_better: bool = True
    #: Why this line cannot be scored, when it cannot.
    pending: str = ""


_NOT_IN_WAREHOUSE = (
    "This is measured outside the warehouse, so there is no live figure to "
    "show. It comes from the survey, HR or the branch's own return.")

#: Seeded kpi_code -> Source. The codes are slugs of the cards' own wording, so
#: several codes mean the same measure on different cards and share a source.
SOURCES = {}


def _register(codes, source):
    for code in codes:
        SOURCES[code] = source


_register(
    ["grow_deposits", "deposit_growth", "deposit_growth_liab_growth_ntb_liab",
     "deposits_portfolio", "deposits_portfolio_ntb", "deposits_energy_water"],
    Source(target_field="target_deposits_value", actual_key="deposit_growth"))

_register(
    ["asset_growth"],
    Source(target_field="target_asset_growth_value", actual_key="asset_growth"))

_register(
    ["drawdowns", "net_loan_disbursments", "net_asset_disbursements",
     "diaspora_net_disbursements", "ultimate_rm_net_disbursements",
     "net_mortgage_sales_10_commercial_rate_mortgages",
     "net_mortgage_sales_10_non_commercial_rate_mortgages"],
    Source(target_field="target_loan_disbursement", actual_key="drawdowns"))

_register(
    ["new_business_banking_customers", "personal_banking_new_customers",
     "new_customer_min_turnover_of_10m", "new_customer_min_turnover_of_50m",
     "ultimate_rm_new_customers"],
    Source(target_field="target_new_customers", actual_key="new_customers"))

_register(
    ["direct_portfolio_contribution", "income_contribution",
     "income_contribution_portfolio_ntb", "operating_profit"],
    Source(target_field="target_pbt_revenue", actual_key="income_contribution"))

_register(
    ["trade_income", "trade_finance_volume", "trade_volume"],
    Source(target_field="target_trade_finance_income",
           actual_key="trade_income"))

_register(
    ["loan_loss", "reduce_p_l_provisions_nil_provisions_loan_loss",
     "reduce_p_l_provisions_nill_provisions_loan_loss"],
    Source(target_field="", actual_key="loan_loss", higher_is_better=False))

_register(["active_customers"],
          Source(target_field="target_active_new_customers",
                 actual_key="active_customers"))

#: Everything the warehouse has no figure for. Listed rather than left to fall
#: through, so the reason on the card is specific.
for _code in (
    "nps", "portfolio_nps", "portfolo_nps", "portfolio_coverage_engagement",
    "business_banking_training", "personal_banking_training",
    "leave_management", "audit", "errors", "tat_loan", "weigted_tat",
    "weigted_tat_sla_service_standards_query_response_time",
    "banking_covenant_tracking_should_be_in_iapply",
    "tooling_and_account_planning_all_customers", "digital_adoption",
    "weighted_sales", "weighted_sales_dashboard", "par",
    "number_of_property", "value_of_property_sales",
    "commercial_vic_premiums", "personal_banking_vic_premiums",
    "business_banking_vic_premiums", "vic_premium", "bancassurance_premiums",
    "other_bancassurance_premiums", "cross_sell_new_casa_accounts_focus_accounts",
    "portfolio_management_aum_dec_previous_year",
    "commercial_trade_group_synergies_23_0", "group_synergies_20_0",
    "group_synergies_25_0", "personal_banking_group_synergies_23_0",
):
    SOURCES.setdefault(_code, Source(pending=_NOT_IN_WAREHOUSE))


# ─────────────────────────────────────────────────────────────────────────────
# Reading the warehouse
# ─────────────────────────────────────────────────────────────────────────────


def _drawdowns_ytd(sales_code, year):
    """Net drawdowns this year for one RM.

    ``drawdown_daily`` stamps the seller two ways - ``salesperson`` and
    ``loan_officer_id`` - and which is populated varies, so both are tried
    rather than assuming one.
    """
    from django.db import connection

    sql = """
        SELECT COALESCE(SUM(net_drawdown), 0), MAX(drawdown_dt)
        FROM drawdown_daily
        WHERE EXTRACT(YEAR FROM drawdown_dt) = %s
          AND (TRIM(salesperson) ILIKE %s OR TRIM(loan_officer_id) ILIKE %s)
    """
    with connection.cursor() as cur:
        cur.execute(sql, [year, sales_code.strip(), sales_code.strip()])
        row = cur.fetchone()
    value = float(row[0] or 0)
    return value, (f"as at {row[1]:%-d %b}" if row[1] else None)


def live_actuals(sales_code):
    """Every figure the warehouse can give for this RM, with its own as-at.

    Each read is wrapped: one unavailable table must not take the whole card
    down, and a line with no figure says so rather than reading zero.
    """
    from services import portfolio_service as svc

    year = datetime.date.today().year
    out = {}

    def attempt(key, fn):
        # Each read gets its own savepoint. Postgres aborts the whole
        # transaction on a failed statement, so without this one missing
        # warehouse table takes down every later read as well - the card would
        # go blank because of a single absent column.
        from django.db import transaction

        try:
            with transaction.atomic():
                out[key] = fn()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            out[key] = (None, None, str(exc))

    def balances():
        data = svc.rm_balances(sales_code)
        return data, None, None

    attempt("_balances", balances)
    data = out.pop("_balances")[0] or {}

    # Deposits and loans are a POSITION, and the card measures GROWTH. Without
    # an opening balance the growth cannot be worked out, so the position is
    # reported and the line stays pending rather than passing a balance off as
    # a growth figure.
    out["deposit_position"] = (
        data.get("total_deposit_balance"), data.get("deposits_as_at"), None)
    out["asset_position"] = (
        data.get("total_loans"), data.get("loans_as_at"), None)

    def revenue():
        rows = svc.rm_revenue(sales_code)
        by_category = {}
        for row in rows:
            key = (row.get("income_category") or "").strip().lower()
            by_category[key] = by_category.get(key, 0) + float(row.get("value") or 0)
        return by_category, "this year to date", None

    attempt("_revenue", revenue)
    categories = out.pop("_revenue")[0] or {}
    gii = categories.get("interest_income", 0)
    ie = categories.get("interest_expenses", 0)
    nfi = categories.get("nfi", 0)
    out["income_contribution"] = (gii - ie + nfi, "this year to date", None)
    out["loan_loss"] = (categories.get("loan_loss", 0), "this year to date", None)

    attempt("new_customers",
            lambda: ((svc.rm_new_customers_ytd(sales_code) or {}).get(
                "new_customers", 0), "this year to date", None))
    attempt("drawdowns",
            lambda: (*_drawdowns_ytd(sales_code, year), None))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The card
# ─────────────────────────────────────────────────────────────────────────────

SCORE_CAP = 1.2

#: KPIs counted in whole units rather than money, so their prorated target is
#: a whole number too.
_COUNT_KPIS = {"new_customers", "active_customers"}


def roster_row(sales_code):
    """This RM's DMC row - the roster the business already maintains."""
    from .models import BranchEmployeeDmcData, BranchFinalEmployeeDmcData

    for model in (BranchFinalEmployeeDmcData, BranchEmployeeDmcData):
        row = (model.objects.filter(sales_code__iexact=sales_code.strip())
               .order_by("-id").first())
        if row is not None:
            return row
    return None


def _target(row, field):
    if not field or row is None:
        return None
    value = getattr(row, field, None)
    return float(value) if value not in (None, "") else None


def score_for(actual, target, higher_is_better):
    """clamp(actual / target, 0, 1.2), inverted where smaller is better."""
    if actual is None or not target:
        return None
    if higher_is_better:
        raw = actual / target
    else:
        raw = (target / actual) if actual else SCORE_CAP
    return max(0.0, min(SCORE_CAP, raw))


def build_card(sales_code, profile=None):
    """The whole card for one RM, computed now."""
    from apps.staff_management.targets import prorate
    from .scorecard_automation.models import ScRole, ScRoleKpiMapping

    row = roster_row(sales_code)
    if row is None:
        return {"has_card": False, "reason": "not_on_dmc_roster",
                "sales_code": sales_code,
                "detail": "Your sales code is not on the branch DMC roster, "
                          "which is where roles and targets come from. "
                          "Administration maintains that list."}

    role_code = role_code_for(row.staff_role)
    if role_code is None:
        return {"has_card": False, "reason": "role_has_no_card",
                "sales_code": sales_code,
                "detail": f"There is no scorecard for the role "
                          f"{row.staff_role or 'on your roster row'!r}. The "
                          f"cards cover the RM, ARM and BBC roles."}

    mappings = list(ScRoleKpiMapping.objects.filter(role_code=role_code)
                    .order_by("kpi_order"))
    if not mappings:
        return {"has_card": False, "reason": "role_not_configured",
                "sales_code": sales_code,
                "detail": f"The {role_code} card has no KPI lines configured."}

    actuals = live_actuals(sales_code)
    role = ScRole.objects.filter(role_code=role_code).first()

    # The seeded definitions carry the card's own wording. Without them a line
    # renders as its slug - "Group Synergies 20 0" - which is not what anybody
    # is measured on.
    from .scorecard_automation.models import ScKpi

    named = {k.kpi_code: k for k in ScKpi.objects.filter(
        kpi_code__in=[m.kpi_code for m in mappings])}

    perspectives, seen = [], {}
    total = 0.0
    live_lines = pending_lines = 0

    for mapping in mappings:
        source = SOURCES.get(mapping.kpi_code, Source(pending=_NOT_IN_WAREHOUSE))
        weight = float(mapping.kpi_weight or 0)

        fy_target = _target(row, source.target_field)
        # prorate() returns every window a dashboard compares against; the
        # card is a year-to-date document, so it is the ytd one. Counts are
        # prorated as whole units - "589.578 new customers" means nothing.
        unit = "number" if source.actual_key in _COUNT_KPIS else "currency"
        ytd_target = (prorate(fy_target, unit=unit)["ytd"]
                      if fy_target is not None else None)

        actual = as_at = problem = None
        unwired = False
        if source.actual_key:
            if source.actual_key in actuals:
                actual, as_at, problem = actuals[source.actual_key]
            else:
                # The KPI names a source this build does not compute yet.
                # Saying "the warehouse could not be read" would send somebody
                # looking for a database fault that does not exist.
                unwired = True

        pending = pending_label = ""
        if source.pending:
            pending, pending_label = source.pending, "Not measured here"
        elif unwired:
            pending = (
                "There is no live source wired for this line yet. The figure "
                "exists in the business; it is not yet read from here.")
            pending_label = "No source yet"
        elif problem:
            pending = f"The warehouse could not be read for this line: {problem}"
            pending_label = "Could not read"
        elif fy_target is None:
            pending = ("No target is set for this line on the DMC roster, so "
                       "there is nothing to score against.")
            pending_label = "No target set"
        elif actual is None:
            pending = "The warehouse has no figure for this line yet."
            pending_label = "No figure yet"

        score = None if pending else score_for(
            actual, ytd_target, source.higher_is_better)
        weighted = None if score is None else weight * score
        if weighted is not None:
            total += weighted
            live_lines += 1
        else:
            pending_lines += 1

        name = mapping.mapping_category or "Other"
        if name not in seen:
            seen[name] = {"perspective": name, "weight": 0.0, "lines": []}
            perspectives.append(seen[name])
        seen[name]["weight"] += weight
        seen[name]["lines"].append({
            "kpi_order": mapping.kpi_order,
            "kpi_code": mapping.kpi_code,
            "kpi_name": (named[mapping.kpi_code].kpi_name
                         if mapping.kpi_code in named
                         else mapping.kpi_code.replace("_", " ").title()),
            "measure_of_success": (named[mapping.kpi_code].kpi_description
                                   if mapping.kpi_code in named else ""),
            "weight": weight,
            "ytd_target": ytd_target,
            # The year's figure as the DMC roster holds it. Shown beside the
            # prorated one so a target that looks an order of magnitude out
            # can be spotted by the person it belongs to, rather than being
            # silently capped at 120% and presented as an achievement.
            "annual_target": fy_target,
            "target_field": source.target_field,
            "ytd_actual": actual,
            "score": score,
            "weighted_score": weighted,
            "as_at": as_at,
            "pending": pending,
            "pending_label": pending_label,
        })

    return {
        "has_card": True,
        "live": True,
        "staff": {
            "sales_code": sales_code,
            "name": row.staff_name or "",
            "title": (role.role_name if role else role_code),
            "branch": row.staff_branch or row.staff_unit or "",
            "team_leader": getattr(row, "team_leader", "") or "",
        },
        "period": {"label": datetime.date.today().strftime("%B %Y")},
        "performance_score": round(total, 4),
        "scored_lines": live_lines,
        "pending_lines": pending_lines,
        "perspectives": perspectives,
    }
