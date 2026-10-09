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
_register(
    ["new_customer_min_turnover_of_10m"],
    Source(target_field="target_new_customers", counted=True,
           pending="This line counts only new customers with a minimum "
                   "turnover of 10M. Turnover is not on the new-customer "
                   "feed, so the qualifying count cannot be taken from here."))
_register(
    ["new_customer_min_turnover_of_50m"],
    Source(target_field="target_new_customers", counted=True,
           pending="This line counts only new customers with a minimum "
                   "turnover of 50M. Turnover is not on the new-customer "
                   "feed, so the qualifying count cannot be taken from here."))
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
    Source(target_field="target_focus_accounts", counted=True,
           pending="Focus-account cross-sell is counted off the CASA opening "
                   "return, which is not one of the tables this platform "
                   "reads."))

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
_register(
    ["number_of_property"],
    Source(target_field="target_properties", counted=True,
           pending="The unit plan is on the roster, but the property sales "
                   "feed carries no customer identifier, so a sale cannot be "
                   "tied to an RM. See docs/property-holdings-etl-gap.md."))
_register(
    ["value_of_property_sales"],
    Source(pending="The roster plans property in UNITS, not value, and the "
                   "sales feed cannot be tied to an RM. See "
                   "docs/property-holdings-etl-gap.md."))

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
    "leave_management", "audit", "errors", "tat_loan", "weigted_tat",
    "weigted_tat_sla_service_standards_query_response_time",
    "banking_covenant_tracking_should_be_in_iapply",
    "tooling_and_account_planning_all_customers", "digital_adoption",
    "weighted_sales", "weighted_sales_dashboard",
    "portfolio_management_aum_dec_previous_year",
):
    SOURCES.setdefault(_code, Source(pending=_NOT_IN_WAREHOUSE))

#: PAR is a ratio against a threshold, not an amount against a plan. The roster
#: carries an NPL amount (``target_npl``), which is a different measure, so
#: nothing is scored rather than scoring a percentage against a shilling value.
SOURCES.setdefault("par", Source(
    pending="PAR is a portfolio-at-risk RATIO measured against a threshold. "
            "The roster carries an NPL amount, not a PAR percentage, so there "
            "is nothing here to score the ratio against."))


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


def _figure(value, as_at=None, label=None, problem=None, failed=False):
    """One figure, with its own as-at and its own reason for being absent.

    ``failed`` separates "the read broke" from "there is honestly nothing
    there". Both leave the line unscored, but only the first is a fault to
    chase, and telling somebody the warehouse is broken when their opening
    balance simply was never loaded sends them to the wrong person.
    """
    return {"value": value, "as_at": as_at, "as_at_label": label,
            "problem": problem, "failed": failed}


def live_actuals(sales_code):
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
    def growth(table):
        g = svc.rm_growth(table, sales_code)
        return _figure(g["growth"], g["as_at"], g["as_at_label"], g["problem"])

    attempt("deposit_growth", lambda: growth("daily_balance_movement"))
    attempt("asset_growth", lambda: growth("loan_daily_balance_movement"))

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


def score_for(actual, target, higher_is_better):
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

    actuals = live_actuals(sales_code)

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

        raw_target = targets.get(field) if field else None
        fy_target = (float(raw_target)
                     if raw_target not in (None, "") else None)
        # Absent from the table is a different problem from NULL in the row,
        # and the two need different people to fix them.
        target_missing = (bool(field) and not target_problem
                          and field not in target_columns)

        figure = actuals.get(source.actual_key) if source.actual_key else None
        unwired = bool(source.actual_key) and figure is None
        actual = figure["value"] if figure else None
        as_at = figure["as_at"] if figure else None
        as_at_label = figure["as_at_label"] if figure else None
        problem = figure["problem"] if figure else None
        failed = bool(figure.get("failed")) if figure else False

        ytd_target = prorate_to(fy_target, as_at, counted=source.counted)

        # The missing TARGET is reported ahead of a failed read, because a line
        # with no target cannot be scored whatever the actual turns out to be,
        # and because the two are fixed by different people: a missing target
        # column is the DMC load, a failed read is the warehouse.
        pending = pending_label = ""
        if source.pending:
            pending, pending_label = source.pending, "Not measured here"
        elif field and target_problem:
            pending = (f"Your targets could not be read from the DMC roster: "
                       f"{target_problem}")
            pending_label = "Targets unreadable"
        elif target_missing:
            pending = (f"{target_table or 'The DMC roster'} has no {field} "
                       f"column, so this line has no target to score against. "
                       f"It is a column for the DMC load to add.")
            pending_label = "No target column"
        elif field and fy_target is None:
            pending = (f"{field} is blank on your DMC row, so there is no "
                       f"target to score this line against.")
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
            # The year's figure as the roster holds it, beside the pro-rated
            # one, and the column it came from. A target an order of magnitude
            # out then shows on the card instead of silently capping the score
            # at 120% and being presented as an achievement.
            "annual_target": fy_target,
            "target_field": field,
            "target_source": target_table if fy_target is not None else "",
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
