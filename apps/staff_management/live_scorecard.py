"""An RM's scorecard built from what the system already holds.

No upload, and nothing to remember to run. Everything a card needs is already
in the platform, in three places:

**Who they are and what they are measured on** — the DMC roster carries, per
``sales_code``: ``staff_role``, ``staff_branch``, ``team_leader``, ``active``
and ``start_date``. There is no second roster to load.

**Their targets** — ``branch_employee_dmc_data``, the PER-PERSON DMC table.
Every ``target_*`` column on it is read, and the columns are asked of the
database rather than of the Django model, because that table is ETL-fed and the
file can carry a column this repo has not declared. See :func:`_target_columns`.

**Their actuals** — read per ``sales_code`` from the tables the rest of the
platform already reads: ``daily_balance_movement`` and
``loan_daily_balance_movement`` for deposit and asset GROWTH;
``portfolio_rm_revenue`` + ``cust_monthly_ftp`` + ``loans_mom_ifrs_movement``
for income and loan loss; ``drawdown_daily`` for disbursements;
``insurance_policies`` joined to ``premium_types_mapping`` for bancassurance
premiums; ``trade_finance_data`` for trade income and trade volume.

So the card is computed when it is asked for, from data that moves on its own.
Reload the page tomorrow and the deposit line has moved, because
``daily_balance_movement`` has.

Three rules that were got wrong before and are worth stating
────────────────────────────────────────────────────────────

**1. The targets come off the per-person table, not the branch one.** There are
two DMC tables and they are a different grain —
``branch_final_employee_dmc_data`` is ONE ROW PER BRANCH. Reading it for an RM
scored an SME RM against a 14 million disbursement target where their own card
says 270 million. ``targets.py`` has encoded the right order since August.

**2. Each line's target is pro-rated to that line's own as-at date.** A balance
as at 30 September against a target pro-rated to 9 October charges the RM nine
days of plan they were never given the chance to earn. This also reproduces the
manual card: on the eight Q3 cards the YTD target is the annual figure times
8/12, and 31 August is day 243 of 365 — 0.6658 against 0.6667, a difference of
one part in 750.

**3. A figure that is missing is not zero.** A KPI whose actual exists nowhere
— NPS, mystery shopping, training hours, leave, covenant tracking, branch audit
— is returned as *pending* with the reason. So is a target the individual plan
does not carry. Scoring somebody nought on a number nobody has is worse than
leaving the line blank, and the person can see at a glance which half of their
card is live.

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

    #: Column on the DMC roster holding the year's target.
    target_field: str = ""
    #: Key into what :func:`live_actuals` returns.
    actual_key: str = ""
    #: Larger is better. Loan loss and the provision lines are the exceptions.
    higher_is_better: bool = True
    #: Counted in whole units rather than money, so the pro-rated target is a
    #: whole number too — "589.578 new customers" means nothing.
    counted: bool = False
    #: Pass or fail against the target rather than scored in proportion to it.
    #: PAR is the one line the cards treat this way, and the seven that carry
    #: it are unanimous: at or under 2.5% scores full marks, over it scores
    #: nothing, and there is no middle value anywhere.
    threshold: bool = False
    #: Why this line cannot be scored, when it cannot.
    pending: str = ""


_NOT_IN_WAREHOUSE = (
    "This is measured outside the warehouse — the survey, HR, the audit return "
    "or a branch's own count — so there is no live figure to show.")

#: Seeded kpi_code -> Source. The codes are slugs of the cards' own wording, so
#: several codes mean the same measure on different cards and share a source.
SOURCES = {}


def _register(codes, source):
    for code in codes:
        SOURCES[code] = source


# ── Balance sheet: GROWTH, not position ──────────────────────────────────────
# Every deposit line on every card is a growth line ("Grow by 43% of the Dec
# book Balance"), and target_deposits_value is a growth target — the old tool
# compared it against the YTD movement, not the balance.
_register(
    ["grow_deposits", "deposit_growth", "deposit_growth_liab_growth_ntb_liab",
     "deposits_portfolio", "deposits_portfolio_ntb"],
    Source(target_field="target_deposits_value", actual_key="deposit_growth"))

_register(
    ["asset_growth"],
    Source(target_field="target_asset_growth_value", actual_key="asset_growth"))

# Energy & Water is a SECTOR cut of deposits. The sector is not on the balance
# table, so the RM's total growth would be the wrong number for it.
_register(
    ["deposits_energy_water"],
    Source(target_field="target_deposits_value",
           pending="This line is the Energy & Water sector only. The balance "
                   "tables carry no sector, so the figure cannot be cut out of "
                   "the RM's total deposit growth."))

# ── Disbursements ────────────────────────────────────────────────────────────
_register(
    ["drawdowns", "net_loan_disbursments", "net_asset_disbursements",
     "diaspora_net_disbursements", "ultimate_rm_net_disbursements"],
    Source(target_field="target_loan_disbursement", actual_key="drawdowns"))

# The two mortgage lines are the market-rate / non-market-rate split, and the
# DMC roster carries a target for each. The ACTUAL needs the same split, and
# drawdown_daily carries no rate classification, so the target is shown and the
# figure is not invented.
_register(
    ["net_mortgage_sales_10_commercial_rate_mortgages"],
    Source(target_field="target_mortgage_mrkt_rate",
           pending="The target is the market-rate mortgage plan. Splitting the "
                   "ACTUAL the same way needs a market/non-market rate flag on "
                   "the drawdown, which drawdown_daily does not carry."))
_register(
    ["net_mortgage_sales_10_non_commercial_rate_mortgages"],
    Source(target_field="target_mortgage_non_mrkt_rate",
           pending="The target is the non-market-rate mortgage plan. Splitting "
                   "the ACTUAL the same way needs a market/non-market rate flag "
                   "on the drawdown, which drawdown_daily does not carry."))

# ── Customers ────────────────────────────────────────────────────────────────
_register(
    ["new_business_banking_customers", "personal_banking_new_customers"],
    Source(target_field="target_new_customers", actual_key="new_customers",
           counted=True))

# These two are new customers ABOVE A TURNOVER FLOOR, and the one on the
# Ultimate card is new customers holding more than two products. The roster
# target is the plain new-customer count, so scoring the plain count against it
# would pass unqualified customers off as qualified ones.
# The turnover floor is the point of these two lines, and it is answerable:
# daily_sales_accounts_with_cto carries the customer's CREDIT TURNOVER
# (cust_cto) beside the account it opened. Counted distinct on the customer -
# one customer opening three accounts is one new customer.
_register(
    ["new_customer_min_turnover_of_10m"],
    Source(actual_key="new_customers_10m", counted=True))
_register(
    ["new_customer_min_turnover_of_50m"],
    Source(actual_key="new_customers_50m", counted=True))
_register(
    ["ultimate_rm_new_customers"],
    Source(target_field="target_new_customers", counted=True,
           pending="This line counts new customers holding more than two "
                   "active products. Product count per new customer is not on "
                   "the new-customer feed."))

_register(
    ["active_customers"],
    Source(target_field="target_active_new_customers", counted=True,
           pending="\"Active\" here is two months of activity on the account. "
                   "The warehouse has the customer list but no activity flag "
                   "to apply that test to."))

_register(
    ["cross_sell_new_casa_accounts_focus_accounts"],
    Source(target_field="target_focus_accounts", actual_key="new_accounts",
           counted=True))

# ── Income ───────────────────────────────────────────────────────────────────
# Two different formulas, and the cards state both:
#   Direct Portfolio Contribution = GII - IE + NFI
#   Income Contribution / Operating Profit = GII - IE + NFI (+/-) FTP - Loan Loss
_register(
    ["direct_portfolio_contribution"],
    Source(target_field="target_pbt_revenue",
           actual_key="direct_portfolio_contribution"))
_register(
    ["income_contribution", "income_contribution_portfolio_ntb",
     "operating_profit"],
    Source(target_field="target_pbt_revenue", actual_key="income_contribution"))

# ── Loan loss / provisions — coming in UNDER is good ─────────────────────────
_register(
    ["loan_loss", "reduce_p_l_provisions_nil_provisions_loan_loss",
     "reduce_p_l_provisions_nill_provisions_loan_loss"],
    Source(target_field="target_loan_provisions", actual_key="loan_loss",
           higher_is_better=False))

# ── Trade finance ────────────────────────────────────────────────────────────
# Income and VOLUME are different columns on both sides. They were previously
# both pointed at the income target, which scored a volume of hundreds of
# millions against a commission target of a few million.
_register(
    ["trade_income"],
    Source(target_field="target_trade_finance_income",
           actual_key="trade_income"))
_register(
    ["trade_finance_volume", "trade_volume"],
    Source(target_field="target_trade_finance_value",
           actual_key="trade_volume"))

# ── Bancassurance ────────────────────────────────────────────────────────────
# The cards split banca two ways and say which is which in the measure of
# success: the "VIC Premiums" lines read "life policies as per assigned
# target", and the "Group Synergies" lines read "non-life as per assigned
# Target". The DMC roster carries exactly that split —
# target_banca_life / target_banca_non_life — and premium_types_mapping
# classifies each product with life_policy_check = "life". So the life /
# non-life axis is the one both sides can express, and it is the one used.
_register(
    ["business_banking_vic_premiums", "personal_banking_vic_premiums",
     "vic_premium"],
    Source(target_field="target_banca_life", actual_key="banca_life"))
_register(
    ["group_synergies_20_0", "group_synergies_25_0",
     "commercial_trade_group_synergies_23_0",
     "personal_banking_group_synergies_23_0"],
    Source(target_field="target_banca_non_life", actual_key="banca_non_life"))
_register(
    ["commercial_vic_premiums"],
    Source(target_field="target_banca_value", actual_key="banca_total"))

# "Renewals and other banca products" — "other" than what is not defined by any
# column, and on the cards that carry it there is already a life line and a
# non-life line, so reading it as either would double-count one of them.
_register(
    ["bancassurance_premiums", "other_bancassurance_premiums"],
    Source(target_field="target_banca_value",
           pending="This line is renewals and \"other\" banca products. Which "
                   "products are \"other\" is not recorded — the cards beside "
                   "it already count life and non-life — so counting anything "
                   "here would double one of those lines."))

# ── Property (HFCB Properties) ───────────────────────────────────────────────
# The roster carries the unit plan. The CRM's amounts-sold feed has no
# customer id, phone or e-mail, so a sale cannot be tied back to an RM; that is
# an upstream gap recorded in docs/property-holdings-etl-gap.md.
# The HFDI sales return the weighted-sales dashboard is built from records the
# staff member who sold each unit, so a unit CAN be tied to a person - by name
# rather than by code, which is why the reader checks the name is on the return
# at all before reporting a nil as a nil.
_register(
    ["number_of_property"],
    Source(target_field="target_properties", actual_key="property_units",
           counted=True))
_register(
    ["value_of_property_sales"],
    Source(actual_key="property_value"))

# ── Staff engagement ─────────────────────────────────────────────────────────
_register(
    ["business_banking_training", "personal_banking_training"],
    Source(target_field="target_training_hours", counted=True,
           pending="Training hours are recorded in the learning system, not "
                   "here."))

#: Everything else the warehouse has no figure for. Listed rather than left to
#: fall through, so the reason on the card is specific.
for _code in (
    "nps", "portfolio_nps", "portfolo_nps", "portfolio_coverage_engagement",
    "leave_management", "audit", "errors",
    "banking_covenant_tracking_should_be_in_iapply",
    "tooling_and_account_planning_all_customers", "digital_adoption",
    "weighted_sales", "weighted_sales_dashboard",
    "portfolio_management_aum_dec_previous_year",
):
    SOURCES.setdefault(_code, Source(pending=_NOT_IN_WAREHOUSE))

#: PAR is a ratio against a threshold, not an amount against a plan. The roster
#: carries an NPL amount (``target_npl``), which is a different measure, so
#: nothing is scored rather than scoring a percentage against a shilling value.
#: PAR is a RATIO against a threshold, and the threshold is 2.5% on all seven
#: cards that carry it - which is a role target, not a DMC column. The ratio
#: itself is arrears over book, both out of `loans` over this RM's allocated
#: customers. Smaller is better.
SOURCES["par"] = Source(actual_key="par", higher_is_better=False,
                        threshold=True)

#: Turnaround is in iApply: total_bank_tat is the bank's own time, which is
#: what the card measures - `tat` includes waiting on the customer, and holding
#: an RM to that is holding them to somebody else's delay.
SOURCES["tat_loan"] = Source(actual_key="tat_days", higher_is_better=False)
for _code in ("weigted_tat",
              "weigted_tat_sla_service_standards_query_response_time"):
    SOURCES[_code] = Source(actual_key="tat_within_sla")


# ─────────────────────────────────────────────────────────────────────────────
# Reading the warehouse
# ─────────────────────────────────────────────────────────────────────────────


def last_closed_month_end(today=None):
    """The last date a monthly warehouse feed can honestly be current to.

    The income, premium and trade feeds are monthly loads with no row date, so
    a figure from them is year-to-date to the end of the last CLOSED month. The
    target is pro-rated to the same date, which is what makes the two
    comparable — and what makes the result agree with the card the desk sends.
    """
    today = today or datetime.date.today()
    first = today.replace(day=1)
    return first - datetime.timedelta(days=1)


def _drawdowns_ytd(sales_code, year):
    """Net drawdowns this year for one RM → (value, as-at date).

    ``drawdown_daily`` stamps the seller two ways — ``salesperson`` and
    ``loan_officer_id`` — and which is populated varies, so both are tried
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
    return float(row[0] or 0), row[1]


def _premiums_ytd(sales_code, year):
    """Bancassurance premiums for one RM this year, split life / non-life.

    ``insurance_policies.product`` is free text, so the life classification
    comes from ``premium_types_mapping`` — the table that decides it once per
    product. A product with no mapping row is counted in the TOTAL but in
    neither half, because guessing which half it belongs in is how a premium
    ends up scored against the wrong line.

    The sales person is stamped in three different columns across the loads
    (``code``, ``rm``, ``sales_person``), so all three are matched.
    """
    from django.db import connection

    sql = """
        SELECT
            COALESCE(SUM(p.premiums), 0) AS total,
            COALESCE(SUM(CASE WHEN LOWER(TRIM(COALESCE(m.life_policy_check, '')))
                                   = 'life' THEN p.premiums END), 0) AS life,
            COALESCE(SUM(CASE WHEN m.product IS NOT NULL
                               AND LOWER(TRIM(COALESCE(m.life_policy_check, '')))
                                   <> 'life' THEN p.premiums END), 0) AS non_life,
            COUNT(*) FILTER (WHERE m.product IS NULL) AS unmapped,
            MAX(p.starting_date) FILTER (
                WHERE p.starting_date <= CURRENT_DATE) AS latest
        FROM insurance_policies p
        LEFT JOIN premium_types_mapping m
               ON LOWER(TRIM(m.product)) = LOWER(TRIM(p.product))
        WHERE TRIM(p.year) = %s
          AND UPPER(TRIM(%s)) IN (UPPER(TRIM(COALESCE(p.code, ''))),
                                  UPPER(TRIM(COALESCE(p.rm, ''))),
                                  UPPER(TRIM(COALESCE(p.sales_person, ''))))
    """
    code = sales_code.strip()
    with connection.cursor() as cur:
        cur.execute(sql, [str(year), code])
        total, life, non_life, unmapped, latest = cur.fetchone()
    return (float(total or 0), float(life or 0), float(non_life or 0),
            int(unmapped or 0), latest)


def _trade_ytd(sales_code, year):
    """Trade finance commission and volume for one RM this year.

    Volume is the facility amount brought to shillings with the rate recorded
    on the row, because the register is kept in the facility's own currency and
    the target is a shilling figure.
    """
    from django.db import connection

    sql = """
        SELECT COALESCE(SUM(commission_lcy), 0),
               COALESCE(SUM(amount_fcy * COALESCE(NULLIF(fx_rate, 0), 1)), 0)
        FROM trade_finance_data
        WHERE TRIM(year) = %s
          AND UPPER(TRIM(COALESCE(rm_code, ''))) = UPPER(TRIM(%s))
    """
    with connection.cursor() as cur:
        cur.execute(sql, [str(year), sales_code.strip()])
        commission, volume = cur.fetchone()
    return float(commission or 0), float(volume or 0)


def _property_sales_ytd(staff_name, year):
    """HFDI property this person sold → (units, value, on_the_return, latest).

    ``weighted_dashboard_manual_sales_table`` is the HFDI sales return the
    weighted-sales dashboard is built from: one row per unit, carrying
    ``staff_name``, ``unit_value`` and ``sale_month``. It is keyed on the
    staff member's NAME, not a code, which is the whole reason for
    ``on_the_return``: a name that is spelt differently on the DMC roster than
    on the return reads as nil sales, and nil sales is also what somebody who
    sold nothing reads as. Those two must not look the same on a scorecard, so
    the name is looked for across every year before a nil is reported as a nil.
    """
    from django.db import connection

    name = " ".join((staff_name or "").split()).strip()
    if not name:
        return None, None, False, None

    sql = """
        SELECT COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM COALESCE(
                   sale_month, booking_date)) = %s),
               COALESCE(SUM(unit_value) FILTER (WHERE EXTRACT(YEAR FROM
                   COALESCE(sale_month, booking_date)) = %s), 0),
               COUNT(*),
               MAX(COALESCE(sale_month, booking_date)) FILTER (
                   WHERE EXTRACT(YEAR FROM COALESCE(
                       sale_month, booking_date)) = %s)
        FROM weighted_dashboard_manual_sales_table
        WHERE UPPER(TRIM(COALESCE(staff_name, ''))) = UPPER(TRIM(%s))
    """
    with connection.cursor() as cur:
        cur.execute(sql, [year, year, year, name])
        units, value, ever, latest = cur.fetchone()
    return (int(units or 0), float(value or 0), bool(ever), latest)


def _afh_property_ytd(sales_code, staff_name, year):
    """Affordable-housing units this person assisted → (units, value, known).

    The second half of the property line, and the half that reaches bank
    staff. The HFDI sales return names the property ADVISOR who sold the unit;
    affordable housing names whoever ASSISTED the buyer, which is how a branch
    RM earns the Group Synergies credit.

    The chain is the bank's own: ``affordable_housing_applications.assisted_by``
    is free text typed into the form, and ``afh_seller_mapping`` is the table
    that resolves it to a member of staff - the same join the affordable
    housing report uses (``hfcb_properties_reports/afh_applications.py``). The
    mapping is matched on the staff id against the sales code or the PF number,
    and on the name, because which of those the mapping carries varies.

    ``known`` says whether this person is on the mapping at all, for the same
    reason the HFDI reader checks the name: somebody missing from the mapping
    reads as nil, and so does somebody who assisted nobody.
    """
    from django.db import connection

    name = " ".join((staff_name or "").split()).strip()
    code = sales_code.strip()
    sql = """
        WITH me AS (
            SELECT LOWER(TRIM(afh_name)) AS afh_name
            FROM afh_seller_mapping
            WHERE UPPER(TRIM(COALESCE(staff_id, ''))) = UPPER(%s)
               OR UPPER(TRIM(COALESCE(name, ''))) = UPPER(%s)
        )
        SELECT COUNT(*) FILTER (
                   WHERE EXTRACT(YEAR FROM a.timestamp) = %s),
               COALESCE(SUM(a.unit_price) FILTER (
                   WHERE EXTRACT(YEAR FROM a.timestamp) = %s), 0),
               (SELECT COUNT(*) FROM me)
        FROM affordable_housing_applications a
        JOIN me ON me.afh_name = LOWER(TRIM(COALESCE(a.assisted_by, '')))
    """
    with connection.cursor() as cur:
        cur.execute(sql, [code, name, year, year])
        units, value, mapped = cur.fetchone()
    return int(units or 0), float(value or 0), bool(mapped)


def _new_accounts_ytd(sales_code, year, turnover_floor=None):
    """New customers this person opened this year → (count, latest open date).

    ``daily_sales_accounts_with_cto`` is the new-account return, one row per
    account, carrying ``sale_code``, the customer's open date and - the part
    nothing was using - ``cust_cto``, the customer's CREDIT TURNOVER.

    That is what makes "New Customer (Min Turnover of 10M)" answerable: pass
    ``turnover_floor`` and only customers at or above it are counted. Counted
    DISTINCT on the customer, because one customer opening three accounts is
    one new customer.
    """
    from django.db import connection

    floor_clause = "AND cust_cto >= %s" if turnover_floor else ""
    params = [year, sales_code.strip()]
    if turnover_floor:
        params.append(turnover_floor)
    sql = f"""
        SELECT COUNT(DISTINCT cust_cif), MAX(cust_open_date)
        FROM daily_sales_accounts_with_cto
        WHERE EXTRACT(YEAR FROM cust_open_date) = %s
          AND UPPER(TRIM(COALESCE(sale_code, ''))) = UPPER(TRIM(%s))
          {floor_clause}
    """
    with connection.cursor() as cur:
        cur.execute(sql, params)
        count, latest = cur.fetchone()
    return int(count or 0), latest


def _tat_ytd(sales_code, year, sla_days=7):
    """Loan turnaround for this person's applications this year.

    → ``(average_days, share_within_sla, applications, latest)``

    ``iapply_loan_approvals_data_dump`` carries ``seller_code`` and
    ``total_bank_tat`` - the BANK's own turnaround, which is the one the card
    measures. ``tat`` includes time spent waiting on the customer, and holding
    an RM to that would be holding them to somebody else's delay.

    Both figures are returned because the cards ask for both: "TAT (Loan)" is
    a number of days against a 7-day target, and "Weigted TAT" is the share of
    applications inside the standard against a 100% target.
    """
    from django.db import connection

    sql = """
        SELECT AVG(total_bank_tat), COUNT(*),
               COUNT(*) FILTER (WHERE total_bank_tat <= %s),
               MAX(creation_date)
        FROM iapply_loan_approvals_data_dump
        WHERE EXTRACT(YEAR FROM creation_date) = %s
          AND UPPER(TRIM(COALESCE(seller_code, ''))) = UPPER(TRIM(%s))
          AND total_bank_tat IS NOT NULL
    """
    with connection.cursor() as cur:
        cur.execute(sql, [sla_days, year, sales_code.strip()])
        average, total, within, latest = cur.fetchone()
    if not total:
        return None, None, 0, None
    return (float(average), float(within) / float(total), int(total),
            latest.date() if hasattr(latest, "date") else latest)


def _par(sales_code):
    """Portfolio at risk for this person → (ratio, book, latest).

    Arrears balance over total balance, both taken from ``loans`` over the
    customers allocated to this RM in ``retail_allocated_portfolio``. ONE
    table, ONE key, deliberately: the RM's live balance comes from
    ``loan_daily_balance_movement`` on ``rm_code``, which is a different book
    from the allocation, and a ratio whose numerator and denominator came from
    two different books would not be a ratio of anything.

    ``retail_allocated_portfolio`` has no unique customer, so the allocation is
    de-duplicated before it is joined - without that, a customer allocated
    twice counts twice and the ratio moves.

    ``euro_book_balance`` is the outstanding value, despite the name. It is the
    column collections calls ``loan_outstanding_value`` and the one the branch
    NPL figure is summed from, so PAR here cannot disagree with the NPL on the
    branch screens.
    """
    from django.db import connection

    sql = """
        WITH mine AS (
            SELECT DISTINCT cust_id
            FROM retail_allocated_portfolio
            WHERE cust_id IS NOT NULL
              AND UPPER(TRIM(COALESCE(sales_code, ''))) = UPPER(TRIM(%s))
        )
        SELECT COALESCE(SUM(l.euro_book_balance), 0),
               COALESCE(SUM(l.euro_book_balance)
                        FILTER (WHERE l.days_in_arrears > 0), 0)
        FROM loans l
        JOIN mine ON mine.cust_id = l.cust_id
    """
    with connection.cursor() as cur:
        cur.execute(sql, [sales_code.strip()])
        book, arrears = cur.fetchone()
    book = float(book or 0)
    if not book:
        return None, None
    return float(arrears or 0) / book, book


def _figure(value, as_at=None, label=None, problem=None, failed=False):
    """One figure, with its own as-at and its own reason for being absent.

    ``failed`` separates "the read broke" from "there is honestly nothing
    there". Both leave the line unscored, but only the first is a fault to
    chase, and telling somebody the warehouse is broken when their opening
    balance simply was never loaded sends them to the wrong person.
    """
    return {"value": value, "as_at": as_at, "as_at_label": label,
            "problem": problem, "failed": failed}


def live_actuals(sales_code, staff_name=""):
    """Every figure the warehouse can give for this RM.

    Each entry is ``{"value", "as_at", "as_at_label", "problem"}``. ``as_at``
    is a real date, because the target is pro-rated to it.

    Every read is wrapped in its own savepoint. Postgres aborts the whole
    transaction on a failed statement, so without one a single missing
    warehouse column takes down every later read as well and the card goes
    blank.
    """
    from services import portfolio_service as svc

    today = datetime.date.today()
    year = today.year
    monthly = last_closed_month_end(today)
    # %-d is a glibc extension and raises on Windows, so the day is formatted
    # by hand - this module is imported by the test suite on both.
    monthly_label = f"as at {monthly.day} {monthly:%b %Y}"
    out = {}

    def attempt(key_or_fn, fn=None):
        from django.db import transaction

        keys = ([key_or_fn] if isinstance(key_or_fn, str) else list(key_or_fn))
        try:
            with transaction.atomic():
                result = fn()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            for key in keys:
                out[key] = _figure(None, problem=str(exc), failed=True)
            return
        if isinstance(key_or_fn, str):
            out[key_or_fn] = result
        else:
            out.update(result)

    # ── Deposit and asset GROWTH ──────────────────────────────────────────
    # The opening balance is kept as well as the growth: it is the BASE a rate
    # target is applied to ("Grow by 43% of the Dec book Balance"), so the one
    # read answers both halves of the line.
    bases = {}

    def growth(table, base_name):
        g = svc.rm_growth(table, sales_code)
        if g["base"] is not None:
            bases[base_name] = g["base"]
        return _figure(g["growth"], g["as_at"], g["as_at_label"], g["problem"])

    attempt("deposit_growth",
            lambda: growth("daily_balance_movement", "december_deposit_book"))
    attempt("asset_growth",
            lambda: growth("loan_daily_balance_movement",
                           "december_loan_book"))

    # ── Income ────────────────────────────────────────────────────────────
    def revenue():
        rows = svc.rm_revenue(sales_code)
        by_category = {}
        for row in rows:
            key = (row.get("income_category") or "").strip().lower()
            by_category[key] = by_category.get(key, 0) + float(row.get("value") or 0)
        gii = by_category.get("interest_income", 0)
        ie = by_category.get("interest_expenses", 0)
        nfi = by_category.get("nfi", 0)
        ftp = by_category.get("ftp", 0)
        # rm_revenue already returns loan_loss NEGATED - a provision CHARGE
        # arrives as a negative number. So adding it here IS subtracting the
        # loss, which is what "(+/-)FTP - Loan Loss" on the card means.
        loss = by_category.get("loan_loss", 0)
        return {
            "direct_portfolio_contribution": _figure(
                gii - ie + nfi, monthly, monthly_label),
            "income_contribution": _figure(
                gii - ie + nfi + ftp + loss, monthly, monthly_label),
            # The card's Loan Loss line is the provision CHARGED, which is the
            # negation again, floored at nil: a net RELEASE is not a negative
            # provision, it is nil provisions, which is the line's own target.
            "loan_loss": _figure(max(0.0, -loss), monthly, monthly_label),
        }

    attempt(("direct_portfolio_contribution", "income_contribution",
             "loan_loss"), revenue)

    # ── Customers ─────────────────────────────────────────────────────────
    # This one counts accounts.opened_by against customers.open_date, which are
    # live tables - the count includes an account opened this morning. So it is
    # as at TODAY, and the target is sliced to today to match. Dating it to the
    # last closed month would compare a figure that includes this month against
    # a target that does not.
    attempt("new_customers", lambda: _figure(
        (svc.rm_new_customers_ytd(sales_code) or {}).get("new_customers", 0),
        today, "as at today"))

    # ── Disbursements ─────────────────────────────────────────────────────
    def drawdowns():
        value, as_at = _drawdowns_ytd(sales_code, year)
        return _figure(value, as_at,
                       f"as at {as_at.day} {as_at:%b %Y}" if as_at else None)

    attempt("drawdowns", drawdowns)

    # ── Bancassurance ─────────────────────────────────────────────────────
    def premiums():
        total, life, non_life, unmapped, latest = _premiums_ytd(
            sales_code, year)
        # The as-at comes off the newest policy on the book rather than the
        # calendar: the premium load is monthly, and dating it to today would
        # slice the target past the figure.
        at = latest or monthly
        label = f"as at {at.day} {at:%b %Y}"
        if unmapped:
            label += (f" - {unmapped} polic{'y' if unmapped == 1 else 'ies'} "
                      f"with no product classification, counted in the total "
                      f"only")
        return {
            "banca_total": _figure(total, at, label),
            "banca_life": _figure(life, at, label),
            "banca_non_life": _figure(non_life, at, label),
        }

    attempt(("banca_total", "banca_life", "banca_non_life"), premiums)

    # ── Trade finance ─────────────────────────────────────────────────────
    def trade():
        commission, volume = _trade_ytd(sales_code, year)
        return {"trade_income": _figure(commission, monthly, monthly_label),
                "trade_volume": _figure(volume, monthly, monthly_label)}

    attempt(("trade_income", "trade_volume"), trade)

    # ── HFDI property, which is the Group Synergies perspective ───────────
    def property_sales():
        """Group Synergies property, from BOTH returns.

        The HFDI sales return names the advisor who SOLD a unit; affordable
        housing names whoever ASSISTED the buyer. A branch RM earns the
        synergy credit the second way, which is why reading only the first
        told most of them they were not on the return.

        A person has to be findable on at least one of the two before a nil is
        reported as a nil: missing from both reads exactly like assisting
        nobody, and those must not look the same on a scorecard.
        """
        hfdi_units, hfdi_value, on_return, latest = _property_sales_ytd(
            staff_name, year)
        afh_units, afh_value, mapped = _afh_property_ytd(
            sales_code, staff_name, year)

        if not on_return and not mapped:
            why = (f"{staff_name or sales_code} is on neither the HFDI sales "
                   f"return nor the affordable-housing seller mapping, so a "
                   f"nil here cannot be told apart from a name spelt "
                   f"differently on one of them")
            return {"property_units": _figure(None, problem=why),
                    "property_value": _figure(None, problem=why)}

        units = (hfdi_units or 0) + afh_units
        value = (hfdi_value or 0) + afh_value
        at = latest or monthly
        where = " and ".join(
            part for part in (
                "HFDI sales" if on_return else "",
                "affordable housing" if mapped else "") if part)
        label = f"{where}, as at {at.day} {at:%b %Y}"
        return {"property_units": _figure(units, at, label),
                "property_value": _figure(value, at, label)}

    attempt(("property_units", "property_value"), property_sales)

    # ── New customers, and the two turnover-qualified counts ──────────────
    def new_accounts():
        out_ = {}
        for key, floor in (("new_accounts", None),
                           ("new_customers_10m", 10_000_000),
                           ("new_customers_50m", 50_000_000)):
            count, latest = _new_accounts_ytd(sales_code, year, floor)
            at = latest or monthly
            out_[key] = _figure(count, at, f"as at {at.day} {at:%b %Y}")
        return out_

    attempt(("new_accounts", "new_customers_10m", "new_customers_50m"),
            new_accounts)

    # ── Loan turnaround, from iApply ──────────────────────────────────────
    def turnaround():
        days, within, applications, latest = _tat_ytd(sales_code, year)
        if not applications:
            why = ("no loan applications with a recorded bank turnaround for "
                   "this sales code this year")
            return {"tat_days": _figure(None, problem=why),
                    "tat_within_sla": _figure(None, problem=why)}
        at = latest or monthly
        label = (f"{applications} application"
                 f"{'' if applications == 1 else 's'}, as at "
                 f"{at.day} {at:%b %Y}")
        return {"tat_days": _figure(days, at, label),
                "tat_within_sla": _figure(within, at, label)}

    attempt(("tat_days", "tat_within_sla"), turnaround)

    # ── Portfolio at risk ─────────────────────────────────────────────────
    def par():
        ratio, book = _par(sales_code)
        if ratio is None:
            return _figure(None, problem="no loans in your allocated book to "
                                         "measure arrears against")
        return _figure(ratio, today,
                       f"arrears over a book of {book:,.0f}")

    attempt("par", par)

    # Not a figure anybody is scored on - the bases a rate target multiplies.
    out["_bases"] = bases
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Targets
# ─────────────────────────────────────────────────────────────────────────────

STAFF_TABLE = "branch_employee_dmc_data"
BRANCH_TABLE = "branch_final_employee_dmc_data"


def _table_columns(table):
    """Every column the TABLE actually has, asked of the database.

    Not taken from the Django model. Both DMC tables are ETL-fed and the file
    can carry a column this repo has not declared yet; reading the model's
    field list would then report "no target set" for a target that is sitting
    right there in the row. It also runs the other way: a production table can
    be MISSING something the model declares — these tables have no ``id``
    sequence on some hosts — and naming a column that is not there fails the
    whole statement, which would blank the card rather than one line.

    pg_attribute via to_regclass, the same call everything else in this
    codebase uses for a warehouse table.
    """
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT attname FROM pg_attribute "
            "WHERE attrelid = to_regclass(%s) AND attnum > 0 "
            "AND NOT attisdropped", [table])
        return {r[0].lower() for r in cur.fetchall()}



def roster_target_row(sales_code):
    """This person's target row → ``(values, table, columns)``.

    ``values`` maps every ``target_*`` column on that table to its value for
    this sales code; ``columns`` is what the table carries, so a target that is
    absent can be told apart from one that is NULL.

    **The per-person table leads.** There are two DMC tables and they are a
    different grain:

    * ``branch_employee_dmc_data`` — ~786 rows, ONE PER SALES PERSON, upserted
      on (pf number, sales code, role). This is an individual's plan.
    * ``branch_final_employee_dmc_data`` — 22 rows, ONE PER BRANCH, upserted on
      ``staff_branch`` alone and held by that branch's BBM.

    The branch table is read only when the per-person table has no row for this
    sales code at all — which is the BBM case, where their personal row IS the
    branch row. It is never used to fill a gap in somebody's individual plan:
    handing an RM their branch's revenue target would read as a few percent and
    paint a fully performing RM red.
    """
    from django.db import connection

    code = sales_code.strip()
    for table in (STAFF_TABLE, BRANCH_TABLE):
        present = _table_columns(table)
        columns = {c for c in present if c.startswith("target_")}
        if not columns:
            continue
        ordered = sorted(columns)
        # Newest row last-in wins, but only where there is an id to order by:
        # these tables have no id sequence on some hosts, and naming a column
        # that is not there fails the statement and blanks the whole card.
        order = " ORDER BY id DESC" if "id" in present else ""
        sql = (f"SELECT {', '.join(ordered)} FROM {table} "
               f"WHERE UPPER(TRIM(sales_code)) = UPPER(TRIM(%s))"
               f"{order} LIMIT 1")
        with connection.cursor() as cur:
            cur.execute(sql, [code])
            row = cur.fetchone()
        if row is not None:
            return dict(zip(ordered, row)), table, columns
    return {}, "", set()


def roster_row(sales_code):
    """The row that names this person's role, branch and team leader.

    The per-person table first, for the same reason targets are read from it
    first; the branch table behind it so a BBM still gets a card.
    """
    from .models import BranchEmployeeDmcData, BranchFinalEmployeeDmcData

    for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData):
        row = (model.objects.filter(sales_code__iexact=sales_code.strip())
               .order_by("-id").first())
        if row is not None:
            return row
    return None


#: KPIs whose target is NOT pro-rated: a threshold is a threshold all year.
#: NPS of 60% does not become 45% because it is September, and PAR's 2.5%
#: ceiling does not loosen. Pro-rating these is the one thing that would make
#: a threshold line meaningless.
FULL_YEAR_TARGETS = {
    "par", "nps", "portfolio_nps", "portfolo_nps",
    "portfolio_coverage_engagement", "audit", "errors",
    "tat_loan", "weigted_tat",
    "weigted_tat_sla_service_standards_query_response_time",
    "weighted_sales", "weighted_sales_dashboard", "leave_management",
}

#: What a ``target_base`` names, in terms of what the warehouse can give.
#: Each is one of this person's OWN figures - the point of a rate target is
#: that the number is theirs, not the role's.
TARGET_BASES = {
    "december_loan_book": "asset_growth",
    "december_deposit_book": "deposit_growth",
}


def role_target(mapping, bases):
    """The role's target for one line → (value, how it was arrived at).

    Third rung of the ladder, and the narrowest. It is only ever reached when
    the person has no figure of their own, and it means one of two things:

    * an absolute that is genuinely the same for everybody on the card - PAR
      2.5%, NPS 60%, 48 training hours, 2 property units;
    * a RATE on one of the person's own figures, where the card states the
      target that way: "Grow by 43% of the Dec book Balance". The rate is the
      role's, the base is theirs, so the target still comes out per person.

    Migration 0029 cleared every other role target, because 0027 had filled
    them from the eight calibration cards and for the financial lines that
    meant one named RM's own closing balance. Read as a role target, every SME
    RM in the bank would have been scored against Charles Muchiri's book.
    """
    target = mapping.kpi_target
    if target is None:
        return None, ""
    basis = getattr(mapping, "target_basis", "") or ""
    if not basis:
        return float(target), "the target on your role's card"

    if basis == "rate_on_base":
        base_name = getattr(mapping, "target_base", "") or ""
        base = bases.get(base_name)
        if base is None:
            return None, ""
        return float(target) * base, (
            f"{float(target) * 100:.0f}% of your {base_name.replace('_', ' ')} "
            f"of {base:,.0f}, as your card states it")
    return None, ""


def prorate_to(annual, as_at=None, counted=False):
    """An annual target sliced to the date the ACTUAL is as at.

    Elapsed days of the year, which is the same arithmetic ``targets.prorate``
    uses and — measured at a month end, which is when the desk builds the card
    — the same answer as the card's own months/12.

    Counts are rounded to whole units. Money is not.
    """
    if annual is None:
        return None
    as_at = as_at or datetime.date.today()
    if isinstance(as_at, datetime.datetime):
        as_at = as_at.date()
    day_of_year = (as_at - datetime.date(as_at.year, 1, 1)).days + 1
    leap = as_at.year % 4 == 0 and (as_at.year % 100 != 0 or as_at.year % 400 == 0)
    sliced = float(annual) * (day_of_year / (366 if leap else 365))
    return float(round(sliced)) if counted else sliced


# ─────────────────────────────────────────────────────────────────────────────
# The card
# ─────────────────────────────────────────────────────────────────────────────

SCORE_CAP = 1.2


def score_for(actual, target, higher_is_better, threshold=False):
    """How far a line got, clamped to 0 … 1.2.

    ``1 + (actual - target) / abs(target)``, which is plain ``actual / target``
    whenever the target is positive, and still means what it should when the
    target is NEGATIVE. That case is real: one Personal Banking card carries an
    income contribution target of -73.3m against an actual of -37.2m, and the
    card scores it 120% — the RM lost half as much as the plan allowed. A bare
    ratio reads 0.51 there and would mark a line that beat its plan as a
    half-miss.

    Checked line by line against the eight Q3 2026 cards: this reproduces 88 of
    the 109 lines that state both a target and an actual, and every one of the
    21 it does not is pinned in
    ``tests_scorecard_calibration.CardCalibrationTests`` with the reason. They
    are not a rule this gets wrong — they are places the eight cards disagree
    with EACH OTHER. NPS is capped at 1.0 on two cards and left to run to 1.667
    on a third; loan loss is capped at 1.0 on one and 1.2 on another. Where
    there is no single manual answer, one rule applied to everybody is the only
    version that can be defended to the person whose bonus depends on it.
    """
    if actual is None or not target:
        return None
    if threshold:
        # Met or not met. Scoring a threshold in proportion would hand partial
        # credit for a limit that was broken.
        met = actual >= target if higher_is_better else actual <= target
        return SCORE_CAP if met else 0.0
    if higher_is_better:
        raw = 1 + (actual - target) / abs(target)
    else:
        # Smaller is better, measured on magnitudes: nil is the best possible
        # outcome, not a division by zero. The provision lines are literally
        # titled "Nil provisions".
        raw = SCORE_CAP if not actual else (abs(target) / abs(actual))
    return max(0.0, min(SCORE_CAP, raw))


def build_card(sales_code, profile=None):
    """The whole card for one RM, computed now."""
    from .scorecard_automation.models import ScKpi, ScRole, ScRoleKpiMapping

    row = roster_row(sales_code)
    if row is None:
        return {"has_card": False, "reason": "not_on_dmc_roster",
                "sales_code": sales_code,
                "detail": "Your sales code is not on the DMC roster, which is "
                          "where roles and targets come from. Administration "
                          "maintains that list."}

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

    actuals = live_actuals(sales_code, row.staff_name or "")

    # Reading the plan gets the same savepoint treatment as reading the
    # warehouse. A failure here used to come out as a blank page, and a blank
    # scorecard reads as "the tool lost my card" - every line saying it has no
    # target, with the error on it, is a page somebody can act on.
    from django.db import transaction

    target_problem = ""
    try:
        with transaction.atomic():
            targets, target_table, target_columns = roster_target_row(sales_code)
    except Exception as exc:  # noqa: BLE001 - reported on every line
        targets, target_table, target_columns = {}, "", set()
        target_problem = str(exc)

    bases = actuals.pop("_bases", {})

    # A target somebody allocated to this person by hand, which sits above the
    # role's and below their own DMC column.
    from .scorecard_automation.models import ScEmployeeKpiTarget

    allocations = {}
    try:
        with transaction.atomic():
            allocations = {
                row.kpi_code: float(row.kpi_target)
                for row in ScEmployeeKpiTarget.objects.filter(
                    sales_code__iexact=sales_code.strip(),
                    year=datetime.date.today().year)
            }
    except Exception:  # noqa: BLE001 - an absent table must not blank the card
        allocations = {}

    # Figures an administrator loaded for the lines the system cannot measure.
    # Read for the last CLOSED month, which is the month a manual return is
    # for; an older figure is not carried forward, because a survey score from
    # four months ago presented as this month's is worse than a blank.
    from .scorecard_automation.models import ScEmployeePerformanceActual
    from .scorecard_manual import MANUAL_ACTUALS

    # The row is keyed on the first of the month; the figure is AS AT its last
    # day, and that is the date the target is sliced to.
    loaded_as_at = last_closed_month_end(datetime.date.today())
    loaded_month = loaded_as_at.replace(day=1)
    loaded_actuals = {}
    try:
        with transaction.atomic():
            loaded_actuals = {
                row.kpi_code: float(row.kpi_value)
                for row in ScEmployeePerformanceActual.objects.filter(
                    sales_code__iexact=sales_code.strip(),
                    eom_date=loaded_month)
            }
    except Exception:  # noqa: BLE001 - an absent table must not blank the card
        loaded_actuals = {}

    role = ScRole.objects.filter(role_code=role_code).first()

    # The seeded definitions carry the card's own wording. Without them a line
    # renders as its slug - "Group Synergies 20 0" - which is not what anybody
    # is measured on.
    named = {k.kpi_code: k for k in ScKpi.objects.filter(
        kpi_code__in=[m.kpi_code for m in mappings])}

    perspectives, seen = [], {}
    total = 0.0
    live_lines = pending_lines = 0

    for mapping in mappings:
        source = SOURCES.get(mapping.kpi_code, Source(pending=_NOT_IN_WAREHOUSE))
        weight = float(mapping.kpi_weight or 0)
        field = source.target_field

        # ── the target ladder ─────────────────────────────────────────
        # 1. the person's own column on the per-person DMC row
        # 2. a per-person allocation somebody loaded for them
        # 3. the role's own target - a shared threshold, or a rate on one of
        #    this person's own figures
        # An explicit figure for this person always beats a derived one.
        raw_target = targets.get(field) if field else None
        fy_target = (float(raw_target)
                     if raw_target not in (None, "") else None)
        target_how = (f"{field} on your {target_table} row"
                      if fy_target is not None else "")

        if fy_target is None:
            allocated = allocations.get(mapping.kpi_code)
            if allocated is not None:
                fy_target, target_how = allocated, "your own allocated target"

        if fy_target is None:
            fy_target, target_how = role_target(mapping, bases)

        # A target of nought is not a target. It is how the cards say "this
        # line does not apply to this role" - Mortgage Business carries a
        # property target of 0 - and scoring against it would divide by zero.
        if fy_target == 0:
            fy_target, target_how = None, ""

        # Absent from the table is a different problem from NULL in the row,
        # and the two need different people to fix them. Neither matters once
        # the ladder has found a target.
        target_missing = (bool(field) and not target_problem
                          and fy_target is None
                          and field not in target_columns)

        figure = actuals.get(source.actual_key) if source.actual_key else None
        unwired = bool(source.actual_key) and figure is None
        actual = figure["value"] if figure else None
        as_at = figure["as_at"] if figure else None
        as_at_label = figure["as_at_label"] if figure else None
        problem = figure["problem"] if figure else None
        failed = bool(figure.get("failed")) if figure else False

        # The actual ladder, and it is only two rungs: what the system can
        # measure, then what an administrator has typed in for the lines it
        # cannot - the survey, the learning system, HR, Audit.
        #
        # The warehouse ALWAYS wins. A figure loaded by hand can never
        # overwrite a measured one, so a stale upload cannot quietly replace a
        # live number; and the card says which of the two it used, so a typed
        # figure is never mistaken for a measured one.
        if (actual is None and mapping.kpi_code in loaded_actuals
                and mapping.kpi_code in MANUAL_ACTUALS):
            actual = loaded_actuals[mapping.kpi_code]
            as_at = loaded_as_at
            as_at_label = f"loaded by Administration for {loaded_as_at:%b %Y}"
            problem = None
            failed = False
            unwired = False

        # A threshold holds all year; everything else is sliced to the date
        # its own actual is as at.
        full_year = mapping.kpi_code in FULL_YEAR_TARGETS
        ytd_target = (fy_target if full_year
                      else prorate_to(fy_target, as_at,
                                      counted=source.counted))

        # The missing TARGET is reported ahead of a failed read, because a line
        # with no target cannot be scored whatever the actual turns out to be,
        # and because the two are fixed by different people: a missing target
        # column is the DMC load, a failed read is the warehouse.
        pending = pending_label = ""
        if source.pending and actual is None:
            pending, pending_label = source.pending, "Not measured here"
        elif field and target_problem:
            pending = (f"Your targets could not be read from the DMC roster: "
                       f"{target_problem}")
            pending_label = "Targets unreadable"
        elif target_missing:
            pending = (f"{target_table or 'The DMC roster'} has no {field} "
                       f"column, your role's card carries no target for this "
                       f"line either, and nobody has allocated you one. It is "
                       f"a column for the DMC load to add.")
            pending_label = "No target column"
        elif fy_target is None:
            pending = ("Nothing sets a target for this line: your DMC row is "
                       "blank for it, no target is allocated to you, and your "
                       "role's card does not carry one.")
            pending_label = "No target set"
        elif unwired:
            pending = ("There is no live source wired for this line yet. The "
                       "figure exists in the business; it is not yet read "
                       "from here.")
            pending_label = "No source yet"
        elif problem and failed:
            pending = f"The warehouse could not be read for this line: {problem}"
            pending_label = "Could not read"
        elif problem:
            # Not a fault - the figure honestly is not there, and the reason
            # says which piece is missing.
            pending = f"No figure for this line: {problem}."
            pending_label = "No figure yet"
        elif actual is None:
            pending = "The warehouse has no figure for this line yet."
            pending_label = "No figure yet"

        score = None if pending else score_for(
            actual, ytd_target, source.higher_is_better,
            threshold=source.threshold)
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
            # The year's figure as the roster holds it, beside the pro-rated
            # one, and the column it came from. A target an order of magnitude
            # out then shows on the card instead of silently capping the score
            # at 120% and being presented as an achievement.
            "annual_target": fy_target,
            "target_field": field,
            "target_source": target_how,
            "full_year_target": full_year,
            "ytd_actual": actual,
            "score": score,
            "weighted_score": weighted,
            "as_at": as_at_label,
            "as_at_date": as_at.isoformat() if as_at else None,
            "higher_is_better": source.higher_is_better,
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
            "role_code": role_code,
            "branch": row.staff_branch or row.staff_unit or "",
            "team_leader": getattr(row, "team_leader", "") or "",
        },
        "period": {"label": datetime.date.today().strftime("%B %Y")},
        "target_source": target_table,
        "performance_score": round(total, 4),
        "scored_lines": live_lines,
        "pending_lines": pending_lines,
        "perspectives": perspectives,
    }
