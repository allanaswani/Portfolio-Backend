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

import calendar
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


#: The most any line can score. 120% on all eight cards, for every line where
#: a card shows a figure above its target - except the two customer-survey
#: lines, which stop at full marks. See ``Source.cap``.
SCORE_CAP = 1.2


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
    #: The most this line may score. 1.2 everywhere but the customer-survey
    #: lines - see the CX registrations below for the count that decided it.
    cap: float = SCORE_CAP
    #: Why this line cannot be scored, when it cannot.
    pending: str = ""
    #: What to say when the figure IS there but no target is. The generic
    #: message blames the DMC row, which is wrong for a line whose target is
    #: missing for a reason of its own - the dormancy rate being the case this
    #: was added for.
    no_target_reason: str = ""


#: A line nothing here can compute, and what to DO about it.
#:
#: The old wording stopped at "measured outside the warehouse", which is true
#: and leaves the reader at a dead end - it reads as "this will never work".
#: These lines are not broken: they are counts somebody keeps (covenants
#: reviewed, accounts planned, leave cleared, an audit score), and there is a
#: screen for exactly that. Naming it turns a dead end into one action.
_NOT_IN_WAREHOUSE = (
    "No system here holds this one — it is a count somebody keeps, like the "
    "audit return, the learning system or a branch's own tally. Administration "
    "enters it under Scorecards → Figures to load, and it then shows here "
    "marked as entered rather than measured.")

#: Weighted Sales has a source - it is a score off the Weighted Sales
#: Dashboard, not a tally anybody keeps - so it gets its own wording rather
#: than the "no system here holds this one" line, which is untrue of it and
#: sends whoever reads it to a screen that cannot fix it.
_WEIGHTED_SALES_PENDING = (
    "This is your productivity on the Weighted Sales Dashboard, which scores "
    "eleven sales lines together. The dashboard is not yet read into this "
    "card, so the figure is not shown rather than estimated.")

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

# "Renewals and other banca products" — the RESIDUAL of the book, and that
# is what makes it safe to count.
#
# This line used to be refused, on the grounds that no column records which
# products are "other" and that the cards carrying it already have a life line
# and a non-life line, so reading it as either would double-count one of them.
# That was the wrong way round. What "other" MEANS does not have to be named
# to be measured: the two lines beside it count the premiums they can
# classify, and this line is everything they do not. total - life - non_life
# cannot double-count either of them, whatever "other" turns out to be, and
# the three together come to the whole book exactly once.
#
# In practice the residual is the premiums on products with no
# ``premium_types_mapping`` row - which the reader was already counting and
# reporting as "counted in the total only". That count had nowhere to go.
_register(
    ["bancassurance_premiums", "other_bancassurance_premiums"],
    Source(target_field="target_banca_value", actual_key="banca_other"))

# ── Active customers, and digital adoption ───────────────────────────────────
# Both are a COUNT over the RM's own book, and both state their target as a
# rate on the person's own prior-year count - "Increase by active customers
# 20%", "Increase portfolio by 50%". The signed cards carry the prior year in
# the 2025 FY column (42 -> 50.4 at 20%; 197 -> 287.29 at 50%), which is the
# same shape as "grow by 43% of the Dec book balance" and goes through the
# same rate_on_base rung. Migration 0044 sets those rates.
#
# These were reported as having no feed. They have one, and it is the
# lake's own: delta.gold_db.active_channels, mirrored into Postgres by
# ``active_channels``. See that module for why it is a mirror and not a
# read on the card path.
# NOT bo_active_customers: that is the BRANCH's active-customer count, and a
# branch manager has no allocated book for this reader to count over. It stays
# on the back-office template, which carries a figure per branch.
# No ``target_field``. ``target_active_new_customers`` is on the BRANCH table
# only, so naming it here would send somebody looking for a column that was
# never going to carry an RM's own figure. The target is the rate the card
# states on the person's own prior-year count - migration 0044 - and the
# ladder reaches it directly.
_register(
    ["active_customers"],
    Source(actual_key="active_customers", counted=True))
_register(
    ["digital_adoption"],
    Source(actual_key="digital_adoption", counted=True))

#: Which reader produces each rate-target BASE.
#:
#: A base is a by-product: ``deposit_growth`` returns the growth AND the
#: December book it grew from, because one read answers both. So a card whose
#: target is "grow by 43% of the Dec book balance" needs that reader to run
#: even if nothing on the card reads ``deposit_growth`` itself. Without this
#: the skip in ``live_actuals`` would quietly remove the base and the line
#: would report that it has no target.
_READERS_BEHIND_A_BASE = {
    "december_deposit_book": {"deposit_growth"},
    "december_loan_book": {"asset_growth"},
    "last_year_active_customers": {"active_customers"},
    "last_year_digital_customers": {"digital_adoption"},
    # NOT "loan_loss": the base is produced by its own reader, registered
    # under "_last_year_loan_loss". Mapping it to the wrong key removed that
    # reader from every card and the line reported "no base to work from".
    "last_year_loan_loss": {"_last_year_loan_loss"},
}

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
# Training was the one line on EVERY card that nothing could score - seven
# sales roles here, five on personal_banking_training and all ten back-office
# roles on bo_training_hours below. It is read from HR's monthly training
# return now; see :mod:`apps.staff_management.training`, which reproduces all
# four calibration cards exactly.
# Capped at full marks, and here the cards are UNANIMOUS: two of them score a
# training line above its target - Business Banking at 36 hours against 32 and
# Commercial-Trade at 69 against 32 - and both wrote exactly 1.0. No training
# line on any card scores above full marks. (Contrast the survey lines above,
# where the same cap had to be argued from a 6-to-5 count.)
_register(
    ["business_banking_training", "personal_banking_training"],
    Source(target_field="target_training_hours", counted=True,
           actual_key="training_hours", cap=1.0))

# ─────────────────────────────────────────────────────────────────────────────
# The back-office (non-sales) cards
# ─────────────────────────────────────────────────────────────────────────────
#
# Ten cards: branch operations managers, customer service officers, tellers,
# cash tellers and the retail back office. Seeded by migration 0031 from
# ``2026_BO_Non_Sales_Scorecards - Q2 with_updated_targets.xlsb``.
#
# Every code is keyed on the FEED its card names, so ``bo_nps`` is the NPS
# sheet and ``bo_kyc`` is the KYC sheet. That makes this list short: one entry
# per feed, not one per card line.
#
# These are OPERATIONS staff, and most of what they are measured on is a
# control or a service measure rather than a balance: audit scores, turnaround,
# KYC cleanup, complaints logged, operation losses, cash management. Almost
# none of that is in a warehouse table, which is why so many of these are
# loaded rather than computed - and that is a statement about where the data
# lives, not a gap in this card.

# ── what the platform already measures ───────────────────────────────────
# Provisions: the same loan-loss figure the RM card scores, and the same
# direction. The BOM's card calls it NPL Management.
_register(["bo_pl_charge"],
          Source(actual_key="loan_loss", higher_is_better=False))

# New and funded accounts, off the new-account return the RM card now uses.
_register(["bo_casa", "bo_new_customers"],
          Source(actual_key="new_accounts", counted=True))

# Loan turnaround, from iApply. ``bo_branch_loan_tat`` is a number of days
# against an SLA, and lower is better; the diaspora card's Weighted_TAT line is
# the share inside the standard.
_register(["bo_branch_loan_tat"],
          Source(actual_key="tat_days", higher_is_better=False))
_register(["bo_weighted_tat"], Source(actual_key="tat_within_sla"))

# Property, from both returns - the HFDI sales return and affordable housing.
_register(["bo_hfcb_properties_volume"],
          Source(actual_key="property_units", counted=True))
_register(["bo_hfcb_properties_value"], Source(actual_key="property_value"))

# Bancassurance. The cards split VIC three ways and name a sheet for each, and
# the life/non-life pair is the axis premium_types_mapping can express - the
# same reading as the RM cards, and the same open question about whether VIC
# means Britam rather than life.
_register(["bo_vic"], Source(actual_key="banca_total"))
_register(["bo_vic_life"], Source(actual_key="banca_life"))
_register(["bo_vic_non_life"], Source(actual_key="banca_non_life"))

# ── measured, but not for a person ───────────────────────────────────────
# Account-opening turnaround, from iApply's ACCOUNTS trail.
#
# These were refused on the grounds that iApply carries LOAN turnaround and
# pointing an account-opening line at it would put a loan figure against an
# account-opening target. That is true of
# ``iapply_loan_approvals_data_dump``, which is where tat_days reads. It is
# NOT true of ``iapply_accounts_tat``, the account application trail, which
# is what the desk's own accounts-TAT report reads - see
# ``apps.staff_management.account_opening``.
#
# A number of DAYS, and lower is better: the cards say "PB AO TAT OF 1 Day".
# The turnaround is per APPLICATION, so a branch's figure is not dragged by
# an application that went round the houses.
_register(["bo_account_opening_pb"],
          Source(actual_key="ao_tat_pb", higher_is_better=False))
_register(["bo_account_opening_bb"],
          Source(actual_key="ao_tat_bb", higher_is_better=False))
_register(["bo_account_opening_ub"],
          Source(actual_key="ao_tat_ub", higher_is_better=False))
# SME and business banking are the same population - ``core.segments`` reads
# BUSINESS BANKING, SME, SMALL ENTERPRISES and MEDIUM ENTERPRISES as one
# segment - so this line differs from the BB one only in its target, five
# days against one, which is already on the card.
_register(["bo_account_opening_sme"],
          Source(actual_key="ao_tat_sme", higher_is_better=False))

# ── the control and service measures ─────────────────────────────────────
# Each names the return it comes from, because "measured elsewhere" without
# saying where is what sends somebody asking three people.
for _code, _where in (
    ("bo_nps", "the customer survey"),
    ("bo_crm", "the CRM complaint log"),
    ("bo_kyc", "the KYC cleanup return"),
    ("bo_branch_audit_branch_audit", "Internal Audit"),
    ("bo_branch_audit_resolution", "Internal Audit - repeat findings resolved"),
    ("bo_branch_audit_compliance", "Internal Audit - compliance score"),
    ("bo_diaspora_audit", "Internal Audit - the diaspora return"),
    ("bo_branch_audit_cash_management", "Internal Audit - cash management"),
    ("bo_cash_management", "the cash management return"),
    ("bo_operation_lossess", "the operational loss and fraud register"),
    ("bo_trx_errors", "the transaction error return"),
    ("bo_rbo_account_errors", "the back-office returns register"),
    ("bo_trx_productivity", "the teller transaction count"),
    ("bo_sales_productivity", "the team productivity return"),
    ("bo_training_hours", "the learning system"),
    ("bo_leave_management", "HR"),
    ("bo_events", "the branch events return"),
    ("bo_branch_rtgs", "the RTGS channel return"),
    ("bo_digital_activation", "the digital activation return"),
    ("bo_digital_customers", "the digital onboarding return"),
    ("bo_re_activation", "the dormancy reactivation return"),
    ("bo_active_customers", "the active-customer count"),
):
    SOURCES[_code] = Source(pending=(
        f"Measured in {_where}, which is not a table this platform reads. "
        f"Administration loads it on the Figures to load screen."))

# ── the lines whose own card does not say where the figure comes from ────
# Migration 0031 seeds these inactive and records what each card claims. They
# are listed here as well so the card gives a reason rather than falling
# through to a generic one, and so the invariant test keeps holding.
for _code, _why in (
    ("bo_account_errors",
     "the card names a sheet called Account_Errors, which the actuals "
     "template does not have. Trx_Errors and RBO_Account_Errors both exist "
     "and either could be meant, so neither is assumed."),
    ("bo_bbm_financials",
     "the card names BBM_Financials, which is not one of the template's 37 "
     "feeds."),
    ("bo_deposit_growth",
     "the card names Deposit_Growth, and the template has no deposits sheet "
     "at all."),
    ("bo_cost",
     "the card names Cost. There is no operating-cost data anywhere in this "
     "warehouse, so this cannot come from a feed as things stand."),
    ("bo_npl",
     "the card names NPL. PL_Charge is what every other NPL line on these "
     "cards reads, and the difference is not explained."),
    ("bo_rbo_monthly_summ",
     "the card names RBO_Monthly_Summ, which is a summary sheet in the "
     "scorecard workbook rather than a feed."),
    ("bo_npl_reduce_p_l_provisions_from_diaspora",
     "diaspora provisions specifically. The provision figure is not cut by "
     "diaspora anywhere this platform reads."),
    ("bo_customer_feedback_nil_client_complaints",
     "client complaints, which are a return somebody keeps."),
    ("bo_customer_feedback_achieve_5_client_compliments",
     "client compliments, which are a return somebody keeps."),
    ("bo_customer_feedback_achieve_3_ultimate_banking_client_co",
     "Ultimate Banking client compliments, a return somebody keeps."),
    ("bo_customer_feedback_achieve_3_diaspora_banking_client_co",
     "Diaspora Banking client compliments, a return somebody keeps."),
    ("bo_customer_journey_document_and_approve_the_customer_ser",
     "whether the customer service journey has been documented and approved "
     "- a yes or no somebody records, not a figure."),
    ("bo_tds_track_ub_term_deposit_renewals",
     "Ultimate Banking term-deposit renewals tracked."),
    ("bo_term_deposits_track_diaspora_term_deposit_renewals_ret",
     "Diaspora term-deposit renewals tracked."),
    ("bo_tools_achieve_tat_of_1_day_for_mobile_banking_onboardi",
     "mobile banking onboarding turnaround, which is not in iApply."),
):
    SOURCES[_code] = Source(pending=(
        f"No live source: {_why} Administration loads it on the Figures to "
        f"load screen."))

# ── Dormancy ─────────────────────────────────────────────────────────────────
# Five back-office cards carry this at 8-10%. The reactivations ARE in the
# warehouse - one row per account brought back, with a branch code and a date -
# so the figure is read and shown.
#
# It is NOT scored, and that is the honest answer rather than a gap. The cards
# measure a "Branch Dormancy score", which is a RATE: the BOM card states 0.53,
# the CSO card 0.31, the Ultimate CSO card 0.19. A rate needs a denominator -
# the accounts that were dormant to begin with - and the only dormancy table in
# this estate holds the CONVERTED accounts, which is the numerator. There is no
# dormant-account base anywhere, and ``accounts.account_status`` is a
# current-state column, so it cannot say what was dormant in January either.
#
# So the count is shown with its own as-at and the line says what is missing.
# Scoring a count of reactivations against a target of 0.384 would read as
# 31,000%, and inventing the denominator would be worse than either.
_register(
    ["bo_re_activation"],
    Source(actual_key="dormancy_reactivations", counted=True,
           no_target_reason=(
               "This line is a RATE on your card - accounts reactivated "
               "against accounts that were dormant. The reactivations are "
               "counted here, but the dormant base they are measured against "
               "is not held anywhere this platform reads, so the rate cannot "
               "be worked out. Administration can enter the score under "
               "Scorecards \u2192 Figures to load.")))

# ── Internal Audit ───────────────────────────────────────────────────────────
# Nine lines across eight roles, and not one of them could be scored: the
# figures arrive as a short table from Internal Audit and nothing held it.
#
# **The score is LOWER-IS-BETTER.** 1.65 is a grade, not a quantity - "Annual
# audit score of 1.65" means achieve 1.65 or better, and better is smaller.
# The Diaspora card settles it: 1.6337 against a target of 1.65 scores full
# marks, and read the other way round the branches with the worst audits would
# come top.
#
# **Capped at full marks.** That card is the only calibration point this line
# has, and it wrote exactly 1.0 for an actual that beat its target. A graded
# control score is not a sales target: beating it by a hundredth should not pay
# 120%. Scored in proportion rather than pass/fail, so a near miss reads as a
# near miss - 1.70 against 1.65 is 97%, not nought.
_register(
    ["audit", "bo_branch_audit_branch_audit", "bo_diaspora_audit"],
    Source(actual_key="audit_score", higher_is_better=False, cap=1.0))

# Implementation of what the audit asked for: 85% or better, and better is
# larger. No card states a score for this line, so it keeps the ordinary cap.
_register(
    ["bo_branch_audit_resolution"],
    Source(actual_key="audit_implementation"))

# ── Customer experience: the survey lines ────────────────────────────────────
# Both of these used to be unscoreable, because the figures arrived as an Excel
# the CX team e-mailed round. They now live in ``cx_rm_metric``, which CX
# maintain themselves - see :mod:`apps.staff_management.cx_metrics`.
#
# **The NPS line is fed by CSAT.** The line on the card is called Portfolio
# NPS; the figure behind it is the RM's own CSAT from CX's Satisfaction sheet,
# which is what the business scores. The per-segment NPS in CX's summary sheet
# is a different measure and is not per RM, so it cannot score a personal card.
#
# **Both stop at full marks, not 120%.** Six card lines across the eight Q3
# cards score a survey measure ABOVE its target, and the cards do not agree
# what to do about it: three wrote exactly 1.0 (Ultimate_RM NPS, Diaspora NPS,
# Personal_Banking coverage), one wrote 1.2 (Personal_Banking NPS, two lines
# below a coverage line the same card capped at 1.0), one applied no cap and
# wrote 1.667 (Mortgage_Business NPS), and one landed at 1.111 under no cap
# (Commercial NPS).
#
# Counted over all nine numeric survey lines, a cap of 1.0 reproduces six, 1.2
# reproduces five and no cap reproduces five - so 1.0 wins, but by one line.
# What settles it is that 1.0 is the only cap more than one card applied here,
# and that the instruction for an RM the measure does not apply to is "give
# FULL MARKS" rather than give 120%. ``tests_scorecard_calibration`` counts
# this off the cards and names the three it does not match; changing this
# number and ``CX_CAP`` there is the whole of the other decision.
_register(
    ["nps", "portfolio_nps", "portfolo_nps"],
    Source(actual_key="cx_csat", cap=1.0))
_register(
    ["portfolio_coverage_engagement"],
    Source(actual_key="cx_contactability", cap=1.0))

# The back-office training line reads the same return as the sales cards. All
# ten back-office roles carry it, and the return's main sheet covers tellers,
# branch operations managers and customer service officers by name and PF.
# There is no DMC row behind a back-office card, so the target comes off the
# role's own card rather than a roster column.
SOURCES["bo_training_hours"] = Source(actual_key="training_hours",
                                      counted=True, cap=1.0)

#: Everything else the warehouse has no figure for. Listed rather than left to
#: fall through, so the reason on the card is specific.
for _code in (
    "leave_management", "audit", "errors",
    "banking_covenant_tracking_should_be_in_iapply",
    "tooling_and_account_planning_all_customers", "digital_adoption",
    "portfolio_management_aum_dec_previous_year",
):
    SOURCES.setdefault(_code, Source(pending=_NOT_IN_WAREHOUSE))

#: Weighted Sales is NOT "a count somebody keeps", which is what it used to
#: say here, and the generic message sent people to the wrong screen.
#:
#: It is a productivity SCORE off the Weighted Sales Dashboard, and the
#: workbook spells out both halves of it:
#:
#: * the "Weighted Sales Dashboard" sheet defines it - eleven component lines
#:   (New Customers, Focus Accounts Vol, Other Accounts Vol, New Account Value,
#:   Funding rate, Short/Long term Approval and Disbursement, Dormancy,
#:   Merchants sign ups, Tills sign up, Nyumba Yangu Account Val, Banca
#:   Premiums), each weighted and each with its own PER-MONTH target, and the
#:   weights differ by role: Branch, DSR, BBC and RM each have a column. The
#:   weights sum to 1.0;
#: * the per-person figure is on the role summary sheets. On
#:   ``SME_BBC_RM_Summary`` column 8 is this person's weighted, capped Weighted
#:   Sales contribution and the perspective is worth 30%, so column 8 / 0.30 is
#:   their productivity. Francis Miriti's five perspective scores
#:   (0.0763 + 0.3049 + 0.05 + 0.1346 + 0.0679) sum to his printed total of
#:   0.6336, which is what confirms column 8 is that and not something else.
#:
#: Most of the eleven components already have a reader in this module - new
#: accounts and their value and funding off ``daily_sales_accounts_with_cto``,
#: dormancy off ``daily_dormancy_converted_accounts``, premiums off the
#: insurance feed - so computing it here is a real option rather than a
#: rewrite. It is not done yet, and until it is the card should say which of
#: the two it is waiting for rather than naming a screen that will not fix it.
SOURCES.setdefault("weighted_sales", Source(pending=_WEIGHTED_SALES_PENDING))
SOURCES.setdefault("weighted_sales_dashboard",
                   Source(pending=_WEIGHTED_SALES_PENDING))

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
    """Bancassurance premiums for one RM this year → total, life, non-life,
    and the residual.

    ``insurance_policies.product`` is free text, so the life classification
    comes from ``premium_types_mapping`` — the table that decides it once per
    product. A product with no mapping row is counted in the TOTAL but in
    neither half, because guessing which half it belongs in is how a premium
    ends up scored against the wrong line.

    Those unclassified premiums are the "renewals and other banca products"
    line, which is why the residual is returned rather than only reported:
    ``total - life - non_life`` is what neither classified line counts, so the
    three partition the book and none of them can double another.

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
    total = float(total or 0)
    life = float(life or 0)
    non_life = float(non_life or 0)
    # Clamped at nought: a credit note can in principle push the residual
    # negative, and a negative "other" would be read as the RM having sold
    # something back rather than as an artefact of the arithmetic.
    other = max(total - life - non_life, 0.0)
    return total, life, non_life, other, int(unmapped or 0), latest


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


#: The two unit-level property feeds, both keyed on the staff member's NAME.
#:
#: They are the SAME DATA in two shapes, and that is the thing to get right
#: here. Column for column:
#:
#:   weighted_dashboard_manual_sales_table   project_name, unit_name,
#:       unit_status, staff_name, payment_mode, lead_id, unit_value,
#:       total_payments, prev_year_paid_amounts, curr_year_paid_amounts,
#:       perc_paid, booking_date, sale_month, etl_date_updated
#:
#:   hfdi_projects_inventory_sales_data      project_name, unit_name,
#:       unit_status, staff_name, unit_value, payment_mode, booking_date,
#:       sale_month, total_payments, perc_paid, perc_paid_prev_month,
#:       prev_year_paid_amounts, curr_year_paid_amounts, jan_paid_amount …
#:
#: One is the HFDI sales return the weighted-sales dashboard is built from; the
#: other is the HFCB Properties CRM inventory. **Adding them would count every
#: unit twice**, so they are UNIONed and de-duplicated on (project, unit).
PROPERTY_UNIT_TABLES = (
    "weighted_dashboard_manual_sales_table",
    "hfdi_projects_inventory_sales_data",
)


#: Postgres expressions for the first and last word of a name. Kept because
#: they are cheap to filter on; the decision is made on the token SET below.
_FIRST = "UPPER(split_part(TRIM({0}), ' ', 1))"
_LAST = "UPPER(regexp_replace(TRIM({0}), '^.*\\s', ''))"


def name_tokens(name):
    """A name as a set of words, upper case, punctuation dropped.

    Order is deliberately thrown away, and the affordable-housing return is
    why. Its ``assisted_by`` column holds names as whoever typed them:
    ``Mugambi  stephen`` with two spaces, ``Evans  oduor``, ``Stanley mwangi
    ithage``. Some are written surname first and some given name first, in the
    same column of the same file.

    Comparing the first and last words fails on every reversed one - STEPHEN
    MUGAMBI against Mugambi stephen shares both words and matches neither end
    - so the words themselves are what get compared.
    """
    import re as _re

    cleaned = _re.sub(r"[^A-Za-z ]", " ", str(name or "").upper())
    return {word for word in cleaned.split() if len(word) > 1}


def names_agree(one, other):
    """Do two spellings name the same person?

    True when the word sets are equal, or when one is contained in the other
    and they share at least TWO words. Two is the floor on purpose: one shared
    word makes every Joseph in the bank the same Joseph.

    This is a comparison, not a decision - the caller still requires the match
    to be unique before using it.
    """
    mine, theirs = name_tokens(one), name_tokens(other)
    if not mine or not theirs:
        return False
    if mine == theirs:
        return True
    return len(mine & theirs) >= 2 and (mine <= theirs or theirs <= mine)


def resolve_feed_name(tables, column, name):
    """How a feed spells this person's name → ``(spelling, how, candidates)``.

    The roster and the property feeds do not agree on middle names. The DMC
    roster carries the full legal name because HR does — ``ABED KIPKOECH
    LELGO``, whose sales code AKL3116 is built from all three initials — and
    the HFDI and CRM returns carry what the salesperson types, which is
    ``Abed Lelgo``. Matched exactly, those are two different people, and the
    card then says he sold nothing.

    So: the exact spelling first, and failing that the one candidate whose
    FIRST and LAST words both match. ``how`` is ``"exact"``, ``"first-last"``
    or ``""``.

    The uniqueness test is what keeps this safe. If two people in the feed
    share a first and last name — which happens, and is precisely when
    guessing is most expensive — nothing is matched and both are returned in
    ``candidates`` for a human to settle. Crediting one person's property
    sales to another is worse than crediting them to nobody.
    """
    from django.db import connection

    name = " ".join((name or "").split()).strip()
    present = [t for t in tables if _table_columns(t)]
    if not name or not present:
        return "", "", []

    parts = [f'SELECT DISTINCT TRIM("{column}") AS nm FROM "{t}" '
             f'WHERE "{column}" IS NOT NULL AND TRIM("{column}") <> \'\''
             for t in present]
    sql = f"""
        WITH names AS ({' UNION '.join(parts)})
        SELECT nm, (UPPER(nm) = UPPER(%s)) AS is_exact
        FROM names
        WHERE UPPER(nm) = UPPER(%s)
           OR {_FIRST.format('nm')} = {_FIRST.format('%s')}
           OR {_LAST.format('nm')} = {_LAST.format('%s')}
           OR {_FIRST.format('nm')} = {_LAST.format('%s')}
           OR {_LAST.format('nm')} = {_FIRST.format('%s')}
    """
    with connection.cursor() as cur:
        cur.execute(sql, [name] * 6)
        rows = cur.fetchall()

    if not rows:
        return "", "", []
    exact = [nm for nm, is_exact in rows if is_exact]
    if exact:
        return exact[0], "exact", [nm for nm, _ in rows]

    # The SQL above is a cheap filter on the two ends of the name. The
    # decision is made here on the words themselves, because the
    # affordable-housing return writes some names surname-first - see
    # names_agree.
    agreed = [nm for nm, _ in rows if names_agree(nm, name)]
    distinct = sorted({" ".join(nm.split()).upper() for nm in agreed})
    if len(distinct) == 1:
        return agreed[0], "same words", [nm for nm, _ in rows]
    return "", "", [nm for nm, _ in rows]


def _table_rows(table):
    """Roughly how many rows a table holds, or 0 if it is absent.

    Deliberately an estimate from the planner statistic rather than a count:
    this is asked of three warehouse tables on every card build, and the
    question is only ever "does this feed hold anything", which an estimate
    answers as well as a scan.
    """
    from django.db import connection

    if not _table_columns(table):
        return 0
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT GREATEST(reltuples::bigint, 0) FROM pg_class "
                "WHERE relname = %s", [table])
            row = cur.fetchone()
            estimate = int(row[0]) if row else 0
            if estimate:
                return estimate
            # reltuples is -1 on a table that has never been analysed, and 0
            # on a genuinely empty one. One cheap probe settles it.
            cur.execute(f'SELECT 1 FROM "{table}" LIMIT 1')
            return 1 if cur.fetchone() else 0
    except Exception:  # noqa: BLE001 - an unreadable feed counts as absent
        return 0


def _property_sales_ytd(staff_name, year):
    """HFDI and CRM property this person sold → (units, value, seen, latest).

    Read across BOTH unit-level feeds and de-duplicated, because they hold the
    same units in two shapes — see :data:`PROPERTY_UNIT_TABLES`. Summing them
    would double every unit and every shilling, which on a line scored against
    a target of two units would read as four.

    De-duplicated on ``(project_name, unit_name)`` folded, keeping the most
    recently sold copy. A row whose ``unit_name`` is blank is NOT collapsed —
    two different units sharing an empty name are still two units, and merging
    them would under-count instead.

    Both feeds are keyed on the staff member's NAME rather than a code, which
    is the whole reason for ``seen``: a name spelt differently on the roster
    than on the feed reads as nil sales, and so does somebody who genuinely
    sold nothing. Those two must never look the same on a scorecard, so the
    name is looked for across every year before a nil is reported as a nil.

    A table that is not present is skipped rather than fatal: the CRM feed is
    an unmanaged mirror and is absent from a test database.
    """
    from django.db import connection

    name = " ".join((staff_name or "").split()).strip()
    if not name:
        return None, None, False, None

    present = [table for table in PROPERTY_UNIT_TABLES
               if _table_columns(table)]
    if not present:
        return None, None, False, None

    # How these feeds spell him, which is not always how the roster does.
    spelling, _how, _candidates = resolve_feed_name(
        PROPERTY_UNIT_TABLES, "staff_name", name)
    if spelling:
        name = spelling

    branches, params = [], []
    for index, table in enumerate(present):
        branches.append(f"""
            SELECT UPPER(TRIM(COALESCE(project_name, ''))) AS project,
                   UPPER(TRIM(COALESCE(unit_name, ''))) AS unit,
                   unit_value,
                   COALESCE(sale_month, booking_date) AS sold_on,
                   {index} AS feed,
                   ROW_NUMBER() OVER () AS rn
            FROM {table}
            WHERE UPPER(TRIM(COALESCE(staff_name, ''))) = UPPER(TRIM(%s))
        """)
        params.append(name)

    sql = f"""
        WITH everything AS ({' UNION ALL '.join(branches)}),
        keyed AS (
            SELECT *,
                   CASE WHEN unit = '' THEN 'row:' || feed || ':' || rn
                        ELSE 'unit:' || project || '|' || unit END AS dedupe
            FROM everything
        ),
        one_per_unit AS (
            SELECT DISTINCT ON (dedupe) dedupe, unit_value, sold_on
            FROM keyed
            ORDER BY dedupe, sold_on DESC NULLS LAST, feed
        )
        SELECT COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM sold_on) = %s),
               COALESCE(SUM(unit_value) FILTER (
                   WHERE EXTRACT(YEAR FROM sold_on) = %s), 0),
               COUNT(*),
               MAX(sold_on) FILTER (WHERE EXTRACT(YEAR FROM sold_on) = %s)
        FROM one_per_unit
    """
    with connection.cursor() as cur:
        cur.execute(sql, params + [year, year, year])
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


def _dormancy_ytd(brn_code, year):
    """Accounts reactivated in this branch this year → ``(count, as_at)``.

    ``daily_dormancy_converted_accounts`` is one row per account that was
    brought back from dormancy, carrying ``brn_code`` and
    ``reactivation_date``. Counted by branch because the card's line is a
    BRANCH measure - it sits on the branch operations manager, the customer
    service officers and the cash centre teller.

    ``action_user`` is on the table too, and is deliberately not used: there
    is nothing here to say whether it holds a sales code, a PF number or a
    Windows login, and attributing a reactivation to the wrong person is
    worse than attributing it to the branch, which is who the card measures.

    Returns ``(None, None)`` when the branch has no code, because counting
    nought reactivations for a branch nobody can identify would read as a
    branch that reactivated nothing.
    """
    from django.db import connection

    code = str(brn_code or "").strip()
    if not code:
        return None, None

    sql = """
        SELECT COUNT(*), MAX(reactivation_date)
        FROM daily_dormancy_converted_accounts
        WHERE TRIM(brn_code::text) = TRIM(%s)
          AND EXTRACT(YEAR FROM reactivation_date) = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [code, year])
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


def _two_month_active(sales_code, year, upto=None, digital=False):
    """Customers of this RM active in TWO consecutive months.

    → ``{year: (count, as_at)}``, or ``{"error": reason}``.

    Two feeds, the better one first.

    1. ``registration_activity`` - the desk's own routine registration data,
       a 1/0 flag per customer per month. It is the better answer because it
       reaches back to December 2025, so the PRIOR-YEAR count that a "grow
       by 20%" target is applied to can actually be read.
    2. ``active_channels`` - the lake's feed, through a Postgres mirror. It
       only reaches January 2026, so it can give this year's figure and
       never last year's.

    The second is tried when the first is not on this database at all. A
    feed that IS there and answers nothing is left to answer nothing: that
    is a real figure, and falling through to another feed would quietly
    report a different measure under the same name.

    Before either, this reconstructed the measure from ``transaction_diary``
    with a self-join over the bank's whole transaction history, per line per
    year - work both feeds had already done, and slow enough on the real
    table that the lines reported "that figure could not be read".
    """
    from . import active_channels, registration_activity

    found = registration_activity.two_month_active(
        sales_code, year, digital=digital)
    if "error" not in found:
        return found

    # Only when the registration data is absent, not when it is empty.
    if "not on this database" not in found["error"]:
        return found
    return active_channels.two_month_active(sales_code, year, digital=digital)


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


def live_actuals(sales_code, staff_name="", staff_pf="", branch="",
                 brn_code="", wanted=None):
    """Every figure the warehouse can give for this RM.

    ``wanted`` is the set of actual_keys the person's own card reads. A reader
    whose keys are ALL outside it is skipped, because running it would be a
    warehouse query for a line that is not on the page.

    This is not a micro-optimisation. Every reader used to run for every card
    - a teller's card paid for the trade-finance register, a commercial RM's
    paid for the dormancy feed - and once two reads over the whole
    transaction history joined the list, the slowest cards ran past the
    worker's 120-second limit. A killed worker returns no response at all, so
    the page renders blank rather than reporting anything. Passing ``None``
    keeps the old behaviour of reading everything, which is what the
    diagnostic commands want.

    ``staff_pf`` is the PF number off the roster row. It is needed because
    HR's training return keys on the PF and not always on the sales code -
    the roster has Charles Muchiri as CMM4236 and the return has CM4236.

    ``branch`` is needed for the audit lines, which are the one measure on
    the card that belongs to a place rather than a person. ``brn_code`` is
    the same idea for dormancy, which the warehouse keys on the code rather
    than the name.

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
        # Nothing on this card reads any of these, so there is nothing to go
        # and fetch. Absent from ``out`` is exactly what an unread key
        # already was for a card that did not carry it.
        if wanted is not None and not (set(keys) & wanted):
            return
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

    # ── Active customers, and digital adoption ────────────────────────────
    # The prior-year count is kept as a BASE as well as the figure, because
    # the target is a rate on it - exactly as the deposit and asset books are
    # handled above, and for the same reason: one read answers both halves.
    def two_month(key, base_name, digital):
        def read():
            # ONE read covers both years: this year for the figure, last
            # year for the base a rate target is applied to.
            found = _two_month_active(sales_code, year, digital=digital)
            if "error" in found:
                return _figure(None, problem=found["error"])

            prior = found.get(year - 1)
            if prior and prior[0]:
                bases[base_name] = float(prior[0])
            else:
                # Say WHY, rather than leaving the card to report only that
                # the figure "could not be read". The lake's feed does not
                # currently reach back a year, and the person reading this
                # needs to know that the answer is a workbook load or an ETL
                # backfill - not a retry.
                from . import active_channels

                span = active_channels.coverage()
                if span["rows"] and span["first_month"]:
                    base_problems[base_name] = (
                        f"the activity feed starts at "
                        f"{span['first_month']:%b %Y} and so does not reach "
                        f"{year - 1}. Until it does, this line's target comes "
                        f"from the scorecard workbook, which carries the "
                        f"{year} figure for each person")
                else:
                    base_problems[base_name] = (
                        "the customer activity feed has not been loaded yet "
                        "- run load_active_channels")

            this_year = found.get(year)
            if this_year is None:
                return _figure(0, monthly, (
                    f"no two consecutive months of activity on this book in "
                    f"{year}"))
            count, at = this_year
            at = at or monthly
            label = (f"active in {at:%b} and the month before, as at "
                     f"{at.day} {at:%b %Y}")
            if digital:
                label = f"on a digital channel, {label}"
            return _figure(count, at, label)
        return read

    attempt("active_customers",
            two_month("active_customers", "last_year_active_customers",
                      digital=False))
    attempt("digital_adoption",
            two_month("digital_adoption", "last_year_digital_customers",
                      digital=True))

    # ── Dormancy reactivations, by BRANCH ─────────────────────────────────
    def dormancy():
        count, latest = _dormancy_ytd(brn_code, year)
        if count is None:
            return _figure(None, problem=(
                "the roster records no branch code against your sales code, "
                "and this is a branch measure"))
        label = (f"reactivations to {latest:%d %b %Y}" if latest
                 else f"reactivations in {year}")
        return _figure(float(count), latest, label)

    attempt("dormancy_reactivations", dormancy)

    # ── Internal Audit, by BRANCH ─────────────────────────────────────────
    # The only measure here that is not personal. One row serves every person
    # in the branch, which is why a branch name spelt differently from the
    # roster takes the score away from all of them at once rather than from
    # one card - and why the match is exact or a UNIQUE prefix, never a loose
    # one. See apps.staff_management.audit_returns.
    def audit():
        from . import audit_returns

        found = audit_returns.for_branch(branch)
        if found is None:
            period = audit_returns.latest_period()
            if not period:
                why = ("Internal Audit's return has not been loaded yet. "
                       "Administration \u2192 Scorecards \u2192 Audit returns "
                       "is where that happens")
            elif not (branch or "").strip():
                why = ("the roster records no branch against your sales code, "
                       "and this is a branch measure")
            else:
                why = (f"the {period} audit return does not cover "
                       f"{branch}. It is keyed on the branch name, so this is "
                       f"either a branch Internal Audit did not report or a "
                       f"name spelt differently from the roster - the Audit "
                       f"returns screen names both")
            return {"audit_score": _figure(None, problem=why),
                    "audit_implementation": _figure(None, problem=why)}

        label = f"{found['branch']} audit, {found['period']}"
        return {
            "audit_score": _figure(
                found["audit_score"], None, label,
                problem=None if found["audit_score"] is not None else
                f"{label} carries no score"),
            "audit_implementation": _figure(
                found["implementation"], None, label,
                problem=None if found["implementation"] is not None else
                f"{label} carries no implementation rate"),
        }

    attempt(["audit_score", "audit_implementation"], audit)

    # ── Training hours, from HR's monthly return ──────────────────────────
    # The as-at is the last month the return covers FOR THIS PERSON, not
    # today: six months of hours scored against a full year's target is a
    # miss that belongs to the return, not to the person.
    def training():
        from . import training as returns

        hours, as_at, problem = returns.ytd_hours(sales_code, staff_pf, year)
        if hours is None:
            return _figure(None, problem=problem)
        label = (f"training return to {as_at:%b %Y}" if as_at
                 else "the training return")
        return _figure(hours, as_at, label)

    attempt("training_hours", training)

    # ── Last year's provision, which is this year's Loan Loss TARGET ──────
    # Not history. Every card that carries the Loan Loss line states its
    # target as a reduction on the person's OWN prior-year provision -
    # Commercial and Commercial-Trade at 20%, Ultimate at two thirds - so
    # this read is what gives that line a target at all. The per-person DMC
    # table has no provision column, and the branch table's one is the
    # BRANCH's allowance, which is not a person's.
    base_problems = {}

    def last_year_provision():
        value, problem = svc.rm_loan_loss(sales_code, year - 1)
        if value is None:
            base_problems["last_year_loan_loss"] = problem
        else:
            bases["last_year_loan_loss"] = value
        # Not a figure anybody is scored on - it is the base of a target - so
        # it is reported only through the target, never as an actual.
        return _figure(None, problem=problem or "")

    attempt("_last_year_loan_loss", last_year_provision)

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
        total, life, non_life, other, unmapped, latest = _premiums_ytd(
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
            # The residual, and the label says so: on a card that also
            # carries a life line and a non-life line, this is the rest of
            # the book and not a second reading of either.
            "banca_other": _figure(
                other, at,
                f"{label} - the premiums the life and non-life lines "
                f"beside this one do not count"),
        }

    attempt(("banca_total", "banca_life", "banca_non_life", "banca_other"),
            premiums)

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
            # Absent from all three. That used to be reported as "no figure",
            # on the ground that a name spelt differently reads the same as
            # somebody who sold nothing. It is time to be less cautious,
            # because the two can now be told apart:
            #
            #   * names are matched on their WORDS, in any order, so the
            #     middle-name and surname-first spellings that caused this
            #     no longer miss;
            #   * the feeds can be asked whether they hold anything at all.
            #
            # A feed carrying thousands of units that does not mention this
            # person means they sold none. Reporting that as "no figure"
            # leaves the line unscored for ever and quietly drags the card -
            # a nil they can challenge is better than a blank they cannot.
            #
            # The honest exception is a feed that is EMPTY. Then absence
            # proves nothing, and the old answer is still the right one.
            populated = any(
                _table_rows(table) for table in
                list(PROPERTY_UNIT_TABLES) + ["affordable_housing_applications"]
            )
            if not populated:
                why = ("no property feed holds any data at all, so this "
                       "cannot be told apart from sales nobody has loaded")
                return {"property_units": _figure(None, problem=why),
                        "property_value": _figure(None, problem=why)}

            label = (f"nil - {staff_name or sales_code} is on none of the "
                     f"three property feeds")
            return {"property_units": _figure(0.0, monthly, label),
                    "property_value": _figure(0.0, monthly, label)}

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

    # ── Account-opening turnaround, by segment ────────────────────────────
    # A different feed from the loan turnaround above, and a different
    # measure: iapply_accounts_tat is the ACCOUNT application trail.
    def account_opening():
        from . import account_opening as ao

        out_ = {}
        try:
            # One pass over the trail for all four segments: the table is
            # 611k rows and nothing indexes SellerCode, so a query per
            # segment meant four scans for every card built.
            found = ao.turnarounds(sales_code, year)
            for segment, (days, applications, latest) in found.items():
                key = f"ao_tat_{segment}"
                if not applications:
                    out_[key] = _figure(None, problem=(
                        f"no account-opening applications under this sales "
                        f"code in {year} for that segment"))
                    continue
                at = latest or monthly
                out_[key] = _figure(
                    days, at,
                    f"{applications} account"
                    f"{'' if applications == 1 else 's'} opened, average "
                    f"turnaround to {at.day} {at:%b %Y}")
        except ao.AccountOpeningUnavailable as exc:
            return {f"ao_tat_{seg}": _figure(None, problem=str(exc))
                    for seg in ("pb", "bb", "ub", "sme")}
        return out_

    attempt(("ao_tat_pb", "ao_tat_bb", "ao_tat_ub", "ao_tat_sme"),
            account_opening)

    # ── Portfolio at risk ─────────────────────────────────────────────────
    def par():
        ratio, book = _par(sales_code)
        if ratio is None:
            return _figure(None, problem="no loans in your allocated book to "
                                         "measure arrears against")
        return _figure(ratio, today,
                       f"arrears over a book of {book:,.0f}")

    attempt("par", par)

    # ── Customer experience, from what CX maintain ────────────────────────
    # Contactability and CSAT for one RM, for the newest period CX have
    # loaded. Quarterly, so the as-at is the quarter's own end rather than the
    # last closed month - the target is not pro-rated for these lines anyway
    # (they are in FULL_YEAR_TARGETS: 60% is 60% in March and in December).
    def cx():
        from . import cx_metrics

        row = cx_metrics.for_rm(sales_code)
        if row is None:
            period = cx_metrics.latest_period()
            if not period:
                why = ("the CX team have not loaded a survey period yet. "
                       "Administration → Scorecards → Customer "
                       "experience is where that happens.")
            else:
                why = (f"the CX survey for {period} does not include you. CX "
                       f"key their return on the RM's NAME, so this is either "
                       f"an RM they did not survey or a name spelt "
                       f"differently from the roster - the Customer "
                       f"experience screen names both.")
            return {"cx_contactability": _figure(None, problem=why),
                    "cx_csat": _figure(None, problem=why)}

        label = f"CX survey, {row['period']}"
        if row["full_marks"]:
            # Not a figure. CX have marked this RM one the measure does not
            # apply to, and the card honours that as a rule rather than
            # inventing a percentage for it.
            marked = _figure(None, cx_period_end(row["period"]),
                             f"{label} — {row['note'] or 'full marks'}")
            marked["full_marks"] = True
            return {"cx_contactability": dict(marked), "cx_csat": dict(marked)}

        as_at = cx_period_end(row["period"])
        return {
            "cx_contactability": _figure(
                row["contactability"], as_at, label,
                problem=None if row["contactability"] is not None else
                f"{label} has no contactability figure for you"),
            "cx_csat": _figure(
                row["csat"], as_at, label,
                problem=None if row["csat"] is not None else
                f"{label} has no CSAT figure for you"),
        }

    attempt(["cx_contactability", "cx_csat"], cx)

    # Not a figure anybody is scored on - the bases a rate target multiplies,
    # and why any of them could not be read.
    out.pop("_last_year_loan_loss", None)
    out["_bases"] = bases
    out["_base_problems"] = base_problems
    return out


def cx_period_end(period):
    """The last day of a CX period - ``2026-Q2`` or ``2026-06``.

    The as-at date a survey figure carries. It is the period's end, not the
    day it was loaded: a Q2 score is a Q2 score whenever CX get round to
    typing it in.
    """
    text = str(period or "")
    try:
        year = int(text[:4])
    except ValueError:
        return None
    rest = text[5:]
    if rest.upper().startswith("Q"):
        month = int(rest[1]) * 3
    else:
        try:
            month = int(rest)
        except ValueError:
            return None
    if not 1 <= month <= 12:
        return None
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, last)


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

    **Not even for a column the per-person table does not carry.** This was
    tried and reverted. ``target_pbt_revenue``, ``target_asset_growth_value``,
    ``target_loan_provisions`` and ``target_active_new_customers`` exist only
    on the branch table, and reading them across for anybody whose sales code
    appears there looked like it was rescuing 33 stranded lines. It was not:
    the branch row carries the BRANCH's figures - 900m of revenue where the
    RM's own disbursement plan is 270m - so every RM in that branch would have
    been scored against their whole branch. An absent column is not a gap to
    fill from a different grain; it means this platform does not hold that
    person's target, and the card says so. See
    ``test_a_branch_only_target_is_not_lent_to_an_rm``.

    Where those targets DO come from is the scorecard workbook, per person,
    and they are not a shared rate either: the three signed Q3 cards grow
    revenue by 8.33 %, 18.33 % and 20 % respectively.
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

#: The back-office thresholds, read off those cards rather than decided from a
#: KPI's name: a line whose PER-MONTH figure and YTD figure are the same number
#: - or whose target is written as a limit, "< 2 Days" - is a ceiling or a
#: standard that holds all year, not something that accrues. Migration 0031
#: carries the same list and explains how it was arrived at.
FULL_YEAR_TARGETS |= {
    "bo_account_opening_bb",
    "bo_account_opening_pb",
    "bo_account_opening_sme",
    "bo_account_opening_ub",
    "bo_active_customers",
    "bo_branch_audit_branch_audit",
    "bo_branch_audit_cash_management",
    "bo_branch_audit_compliance",
    "bo_branch_audit_resolution",
    "bo_branch_loan_tat",
    "bo_branch_rtgs",
    "bo_cash_management",
    "bo_customer_feedback_nil_client_complaints",
    "bo_customer_journey_document_and_approve_the_customer_ser",
    "bo_diaspora_audit",
    "bo_digital_activation",
    "bo_npl_reduce_p_l_provisions_from_diaspora",
    "bo_nps",
    "bo_operation_lossess",
    "bo_rbo_account_errors",
    "bo_rbo_monthly_summ",
    "bo_re_activation",
    "bo_sales_productivity",
    "bo_tds_track_ub_term_deposit_renewals",
    "bo_tools_achieve_tat_of_1_day_for_mobile_banking_onboardi",
    "bo_trx_errors",
    "bo_trx_productivity",
    "bo_weighted_tat",
}

#: Feeds that are NOT warehouse reads, and so are not overridden by a figure
#: somebody loaded.
#:
#: A loaded figure beats the warehouse, because a warehouse read can be
#: wrong and there was otherwise no way to correct it. These four are a
#: different thing entirely: each is another team's own return, maintained on
#: their own screen - CX keep the survey, HR the training hours, Internal
#: Audit the audit score. They are already somebody's considered figure, and
#: a second hand-typed one must not quietly replace them.
#:
#: The rule this preserves is in
#: ``tests_scorecard_manual.test_cx_beats_a_figure_somebody_typed_in``: a
#: typed figure is used where CX have none, which keeps a card completable in
#: a quarter CX have not loaded, and CX's own figure wins once it is there.
OWNER_MAINTAINED_KEYS = {
    "cx_csat",            # Customer experience screen
    "cx_contactability",  # Customer experience screen
    "training_hours",     # Training returns screen
    "audit_score",        # Audit returns screen
}

#: Lines whose YTD target is a slice of the GROWTH, not of the year-end level.
#:
#: The warehouse gives these lines a MOVEMENT as the actual - Abed Lelgo's
#: asset growth is -3,192,001.99 and Faith Muthinja's is -39,217,958.87, each
#: a change over the year, not a balance. Scoring a movement against a balance
#: is arithmetically meaningless: Abed's -3.2m was being put against
#: 1,736,021,628.99 and Faith's -39m against 465,452,137.67, and both can only
#: ever come out at 0%. The target has to be a movement too.
#:
#: The workbook agrees, to the cent. On the Commercial sheet (Juspher
#: Muriithi, Q3_Aug_26, so eight months of twelve elapsed):
#:
#:     Asset Growth   growth 160,510,204.00 x 8/12 = 107,006,802.67
#:     Grow Deposits  growth 417,600,000.00 x 8/12 = 278,400,000.00
#:
#: and those are exactly the YTD targets it prints. Prorating the LEVEL would
#: have given 1,168,467,340.30 and 342,361,375.98.
#:
#: Deliberately NOT here: Direct Portfolio Contribution, the income lines and
#: Loan Loss. Their actual is a cumulative flow, not a movement, and the same
#: sheet prorates them off the LEVEL - Juspher's DPC is 277,856,513.63 x 8/12
#: = 185,237,675.75, which is what it prints. Putting them in this set would
#: break the lines that currently work.
#:
#: The sheets are not perfectly consistent with each other: Commercial_trade
#: prorates its "Deposits(Portfolio)" off the level while Commercial prorates
#: "Grow Deposits" off the growth. The rule followed here is the one that
#: holds regardless - match the target to what the ACTUAL actually measures.
GROWTH_PRORATED = {
    "asset_growth",
    "deposit_growth",
    "deposit_growth_liab_growth_ntb_liab",
    "deposits_portfolio",
    "deposits_portfolio_ntb",
    "grow_deposits",
}

#: The only lines a NEGATIVE target makes sense on. Loan loss and provisions
#: are held positive on the sheets and printed negative, so a target below
#: nought is correct for them and nothing else.
#:
#: Faith Muthinja's card showed an Income Contribution target of
#: -39,917,032.92. A target to earn less than nothing cannot be met or missed,
#: and it came from adding a growth to a base that was itself negative. Her
#: signed card sets 4,168,000.50. A negative here is a broken input, not a
#: target, and the card says so rather than scoring against it.
MAY_BE_NEGATIVE = {
    "loan_loss",
    "reduce_p_l_provisions_nil_provisions_loan_loss",
    "reduce_p_l_provisions_nill_provisions_loan_loss",
    "reduce_p_l_provisions_nill_provisions_loan_los",
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


@dataclass(frozen=True)
class Person:
    """Who somebody is, and which card they hold."""

    sales_code: str = ""
    name: str = ""
    role_code: str = ""
    branch: str = ""
    team_leader: str = ""
    #: Which roster answered. On the card, so a figure can be traced to the
    #: list it came off.
    roster: str = ""
    #: The DMC row, when there is one. Back-office staff have none, and their
    #: targets come off the role's card instead.
    dmc_row: object = None


#: The ``List`` sheet's job titles for back-office staff, as
#: ``staff_employee_data.job_title`` spells them. Only used when the role
#: history has nothing - the roster is the authority, this is the fallback for
#: somebody who joined since it was loaded.
BO_TITLE_ALIASES = {
    "branch operations manager": "bo_bom",
    "bom": "bo_bom",
    "customer service officer": "bo_cso",
    "cso": "bo_cso",
    "customer service officer - ultimate banking": "bo_cso_ub",
    "customer service officer ultimate banking": "bo_cso_ub",
    "customer service manager - diaspora banking": "bo_csm_diaspora",
    "customer service manager diaspora banking": "bo_csm_diaspora",
    "teller": "bo_teller",
    "cash teller": "bo_cash_teller",
    "cash centre teller": "bo_cash_centre_teller",
    "cash center teller": "bo_cash_centre_teller",
    "cash_centre teller": "bo_cash_centre_teller",
    "cash_center teller": "bo_cash_centre_teller",
    "retail back office officer": "bo_rbo",
    "rbo": "bo_rbo",
    "team leader: account opening (retail back office)": "bo_tl_rbo",
    "team leader - retail back office": "bo_tl_rbo",
}


def bo_role_for(job_title):
    """The back-office card for an HR job title, or None. None rather than a
    guess, for the same reason :func:`role_code_for` returns None."""
    folded = fold(job_title)
    if folded in BO_TITLE_ALIASES:
        return BO_TITLE_ALIASES[folded]
    for alias in sorted(BO_TITLE_ALIASES, key=len, reverse=True):
        if folded.startswith(alias + " ") or folded == alias:
            return BO_TITLE_ALIASES[alias]
    return None


def resolve_person(sales_code):
    """Who this sales code belongs to and which card they hold, or None.

    Three rosters, most specific first, because one roster does not cover
    everybody:

    1. **the DMC roster** - sales staff, with their targets on the row. This
       answers for every RM, ARM and BBC and is tried first because it brings
       the targets with it.
    2. **``employee_role_history``** - who holds which card, which is where the
       back-office roster lives. A teller is not on the DMC roster at all: that
       table is the sales roster, keyed on sales code and carrying sales
       targets, and a teller has neither. Seeded from the workbook's own
       ``List`` sheet by migration 0032, and correctable through the API that
       was already there.
    3. **``staff_employee_data``** by job title - the fallback for somebody who
       joined since the roster was loaded. It carries both a sales code and a
       job title, which is the only bridge in this estate between a person and
       a non-sales role.

    Returns ``None`` when no roster knows the code, which the card reports as
    its own reason rather than as an empty page.
    """
    code = (sales_code or "").strip()
    if not code:
        return None

    # 1. the sales roster
    row = roster_row(code)
    if row is not None:
        role = role_code_for(row.staff_role)
        if role is not None:
            return Person(
                sales_code=code, name=row.staff_name or "", role_code=role,
                branch=row.staff_branch or row.staff_unit or "",
                team_leader=team_leader_of(row),
                roster="the branch DMC roster", dmc_row=row)

    # 2. the role history - the back-office roster
    from .models import EmployeeRoleHistory, StaffEmployeeData

    held = (EmployeeRoleHistory.objects
            .filter(sales_code__iexact=code, role_code__startswith="bo_")
            .order_by("-start_date").first())
    staff = StaffEmployeeData.objects.filter(sales_code__iexact=code).first()
    if held is not None:
        # The seeded rows keep name, branch, zone and line manager in notes,
        # because employee_role_history has nowhere else for them. Live data
        # from staff_employee_data wins where it exists.
        parts = [piece.strip() for piece in (held.notes or "").split("|")]
        parts += [""] * (4 - len(parts))
        return Person(
            sales_code=code,
            name=(getattr(staff, "staff_name", "") or parts[0] or ""),
            role_code=held.role_code,
            branch=(getattr(staff, "staff_unit", "") or parts[1] or ""),
            team_leader=parts[3] or "",
            roster="the back-office roster")

    # 3. the HR record, by job title
    if staff is not None:
        role = bo_role_for(staff.job_title)
        if role is not None:
            return Person(
                sales_code=code, name=staff.staff_name or "", role_code=role,
                branch=staff.staff_unit or staff.department or "",
                roster="your HR record")

    # Known to the DMC roster but holding a role no card covers - reported
    # separately from "nobody has heard of this code", because they are
    # different problems with different owners.
    if row is not None:
        return Person(sales_code=code, name=row.staff_name or "",
                      role_code="", branch=row.staff_branch or "",
                      roster="the branch DMC roster", dmc_row=row)
    if staff is not None:
        return Person(sales_code=code, name=staff.staff_name or "",
                      role_code="", branch=staff.staff_unit or "",
                      roster="your HR record")
    return None


def brn_code_for(sales_code, dmc_row=None):
    """This person's branch CODE, or ``""``.

    The warehouse keys dormancy on ``brn_code`` rather than the branch name.
    The DMC row carries it; a back-office person has no DMC row, so the code
    is looked up from any roster row sharing their branch - which is sound,
    because the measure being read is the branch's and not theirs.
    """
    from django.db import transaction

    from .models import BranchEmployeeDmcData, BranchFinalEmployeeDmcData

    if dmc_row is not None:
        found = str(getattr(dmc_row, "brn_code", "") or "").strip()
        if found:
            return found

    from .models import StaffEmployeeData

    try:
        with transaction.atomic():
            staff = StaffEmployeeData.objects.filter(
                sales_code__iexact=(sales_code or "").strip()).first()
            branch = str(getattr(staff, "staff_unit", "") or "").strip()
            if not branch:
                return ""
            for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData):
                row = (model.objects
                       .filter(staff_branch__iexact=branch)
                       .exclude(brn_code__isnull=True)
                       .values_list("brn_code", flat=True).first())
                if row:
                    return str(row).strip()
    except Exception:  # noqa: BLE001 - costs a figure, not the card
        return ""
    return ""


def team_leader_of(dmc_row):
    """The line manager's name off a DMC row, from either column.

    The per-person roster carries BOTH ``team_leader_name`` and
    ``team_leader``, with nothing in the schema to say which the ETL fills -
    and the branch roster carries only ``team_leader``. Reading one of them
    and stopping is how a card ends up with a blank line manager and nobody
    able to counter-sign it, which is a silent failure of the whole sign-off.

    ``team_leader_name`` is preferred because its name says it holds a name;
    ``team_leader`` is the fallback. If one of them turns out to hold a code
    rather than a name, the name column still wins and the code column simply
    never matches a signer - which is the safe way round.
    """
    if dmc_row is None:
        return ""
    for field in ("team_leader_name", "team_leader"):
        found = str(getattr(dmc_row, field, "") or "").strip()
        if found:
            return found
    return ""


def pf_for(sales_code, dmc_row=None):
    """This person's PF number, or ``""``.

    Needed because HR's training return keys on the PF rather than the sales
    code, and the two estates do not always spell a code the same way.

    The DMC row carries it when there is one. A back-office person has no DMC
    row - ``employee_role_history`` has no PF column either - so the HR record
    is asked next, and a teller the HR extract has not reached is matched on
    their sales code alone.
    """
    from django.db import transaction

    from .models import StaffEmployeeData

    if dmc_row is not None:
        found = str(getattr(dmc_row, "staff_pf_number", "") or "").strip()
        if found:
            return found
    code = (sales_code or "").strip()
    if not code:
        return ""
    try:
        # Its own savepoint: an absent HR table must cost a training figure,
        # not the whole card.
        with transaction.atomic():
            staff = StaffEmployeeData.objects.filter(
                sales_code__iexact=code).first()
    except Exception:  # noqa: BLE001 - reported by the line, not raised
        return ""
    return str(getattr(staff, "staff_pf_number", "") or "").strip()


def prorate_to(annual, as_at=None, counted=False):
    """An annual target sliced to the date the ACTUAL is as at.

    ELAPSED MONTHS, which is what the bank's own sheets use.

    This used to be elapsed days of the year, on the stated grounds that at a
    month end - when the desk builds the card - it came to the same answer as
    months/12. It does not. At 31 August, days give 243/365 = 0.665753 and
    months give 8/12 = 0.666667: a seventh of a percent, which on a
    1.75-billion asset-growth target is 146,585 shillings.

    The sheets settle it. Juspher Muriithi's Commercial card is Q3_Aug_26 and
    prints, to the cent:

        Trade Income    9,600,000.00 x 8/12 =   6,400,000.00
        DPC           277,856,513.63 x 8/12 = 185,237,675.75
        Asset Growth  160,510,204.00 x 8/12 = 107,006,802.67  (of the GROWTH)
        Grow Deposits 417,600,000.00 x 8/12 = 278,400,000.00  (of the GROWTH)

    Every one is months/12. None is days/365.

    Mid-month, the current month counts by the fraction of itself elapsed, so
    the slice still moves daily and lands exactly on months/12 at each month
    end - which is the only date the desk actually reads.

    Counts are rounded to whole units. Money is not.
    """
    if annual is None:
        return None
    as_at = as_at or datetime.date.today()
    if isinstance(as_at, datetime.datetime):
        as_at = as_at.date()
    import calendar
    in_month = calendar.monthrange(as_at.year, as_at.month)[1]
    months = (as_at.month - 1) + (as_at.day / in_month)
    sliced = float(annual) * (months / 12)
    return float(round(sliced)) if counted else sliced


# ─────────────────────────────────────────────────────────────────────────────
# The card
# ─────────────────────────────────────────────────────────────────────────────


def score_for(actual, target, higher_is_better, threshold=False,
              cap=SCORE_CAP):
    """How far a line got, clamped to 0 … ``cap`` (1.2 for almost every line).

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
        return cap if met else 0.0
    if higher_is_better:
        raw = 1 + (actual - target) / abs(target)
    else:
        # Smaller is better, measured on magnitudes: nil is the best possible
        # outcome, not a division by zero. The provision lines are literally
        # titled "Nil provisions".
        raw = cap if not actual else (abs(target) / abs(actual))
    return max(0.0, min(cap, raw))


def build_card(sales_code, profile=None):
    """The whole card for one RM, computed now."""
    from .scorecard_automation.models import ScKpi, ScRole, ScRoleKpiMapping

    person = resolve_person(sales_code)
    if person is None:
        return {"has_card": False, "reason": "not_on_any_roster",
                "sales_code": sales_code,
                "detail": "Your sales code is on none of the three rosters - "
                          "the branch DMC roster, the back-office roster, or "
                          "your HR record. Administration maintains those."}
    if not person.role_code:
        return {"has_card": False, "reason": "role_has_no_card",
                "sales_code": sales_code,
                "detail": f"There is no scorecard for your role on "
                          f"{person.roster}. The cards cover the RM, ARM and "
                          f"BBC roles on the sales side, and the branch "
                          f"operations, customer service, teller and back "
                          f"office roles."}

    role_code = person.role_code
    row = person.dmc_row

    mappings = list(ScRoleKpiMapping.objects.filter(role_code=role_code)
                    .order_by("kpi_order"))
    if not mappings:
        return {"has_card": False, "reason": "role_not_configured",
                "sales_code": sales_code,
                "detail": f"The {role_code} card has no KPI lines configured."}

    # Only the feeds this card has a line for. See ``live_actuals``: reading
    # all of them for every card is what pushed the slowest ones past the
    # worker timeout, and a killed worker renders as a blank page.
    wanted = set()
    for mapping in mappings:
        source = SOURCES.get(mapping.kpi_code)
        if source is not None and source.actual_key:
            wanted.add(source.actual_key)
    # The bases a rate target is applied to are produced by the SAME readers
    # as their figures, so a line whose target is "43% of your Dec book" needs
    # that reader to run even when its own actual is read elsewhere.
    for mapping in mappings:
        base = (getattr(mapping, "target_base", "") or "")
        wanted |= _READERS_BEHIND_A_BASE.get(base, set())

    actuals = live_actuals(sales_code, person.name, pf_for(sales_code, row),
                           person.branch, brn_code_for(sales_code, row),
                           wanted=wanted)

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
    base_problems = actuals.pop("_base_problems", {})

    # A target somebody allocated to this person by hand, which sits above the
    # role's and below their own DMC column.
    from .scorecard_automation.models import ScEmployeeKpiTarget

    allocations, allocation_bases = {}, {}
    try:
        with transaction.atomic():
            allocations, allocation_bases = {}, {}
            for row in ScEmployeeKpiTarget.objects.filter(
                    sales_code__iexact=sales_code.strip(),
                    year=datetime.date.today().year):
                allocations[row.kpi_code] = float(row.kpi_target)
                # The sheet's "2025 FY" column. Needed to recover the GROWTH -
                # the allocation stores the year's LEVEL, and a growth-measured
                # line has to be scored against the growth.
                base = getattr(row, "base_value", None)
                if base not in (None, ""):
                    allocation_bases[row.kpi_code] = float(base)
    except Exception:  # noqa: BLE001 - an absent table must not blank the card
        allocations, allocation_bases = {}, {}

    # Figures an administrator loaded for the lines the system cannot measure.
    # Read for the last CLOSED month, which is the month a manual return is
    # for; an older figure is not carried forward, because a survey score from
    # four months ago presented as this month's is worse than a blank.
    from .scorecard_automation.models import ScEmployeePerformanceActual

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
    # The WEIGHT behind those counts, not just how many lines. A line nobody
    # can measure contributes nothing to the total, so a card carrying three
    # of them is quietly scored out of less than it appears to be - Abed
    # Lelgo's Commercial RM card sums its lines to 102.5% of weight while
    # 12.5% of it has no source, and his 65.66% reads as though he failed
    # those lines rather than as though they could not be put to him. The
    # workbook does not leave them blank: on the Commercial sheet the same
    # three carry hand-entered figures. Until somebody enters his, the card
    # should at least say what it was able to score.
    scored_weight = unscored_weight = 0.0

    for mapping in mappings:
        source = SOURCES.get(mapping.kpi_code, Source(pending=_NOT_IN_WAREHOUSE))
        weight = float(mapping.kpi_weight or 0)
        field = source.target_field

        # ── the target ladder ─────────────────────────────────────────
        # 1. a per-person figure: the allocation sheet, or this person's own
        #    SIGNED CARD, whichever was loaded for them
        # 2. their column on the per-person DMC row
        # 3. the role's own target - a shared threshold, or a rate on one of
        #    this person's own figures
        #
        # The per-person figure LEADS, and that is a deliberate reversal. The
        # DMC column used to win, which meant a card could disagree with the
        # document its owner had signed and there was no way to correct it:
        # Faith Muthinja's deposits target read -682,993,663.92 where her
        # signed card says 35,000,000, and her Income Contribution read "no
        # target" where her card sets 4,168,000.50. The allocation sheet and
        # the signed cards are what the business agreed; the DMC load is an
        # ETL feed. Asked for directly on 2026-10-21.
        #
        # Nothing is hidden by this: ``target_source`` on every line says
        # which rung answered, so a figure that came from a card says so.
        raw_target = targets.get(field) if field else None

        # Whether the figure is a LEVEL or already a GROWTH depends entirely
        # on which rung answered, so the rung is remembered. A per-person
        # figure is the year's level; a DMC growth column is already a growth.
        # Is this line's target a RATE on one of the person's own figures?
        # It decides what the allocation sheet's value even means for this
        # line, so it has to be known before the ladder, not after it.
        rate_basis = (getattr(mapping, "target_basis", "") or "") == "rate_on_base"
        base_name = getattr(mapping, "target_base", "") or ""

        # On a rate line the sheet carries the BASE, never the target.
        #
        # "Increase by active customers 20%" is 20% of the size of this
        # person's own book, and the book size is on the allocation sheet as
        # ``Count``. Faith Muthinja's is 117, and her signed card reads
        # 2025 FY 117, GROWTH 23.4, 2026 FY 140.4 - which is 117 x 1.2. The
        # sheet has no column holding 140.4 anywhere; it holds the 117, and
        # the 20% comes from the role. Reading the sheet's number as a target
        # would have put 82 on her card, which is neither figure.
        #
        # The warehouse still leads: this fills the base only where no feed
        # could produce one, which is the usual case for a prior YEAR the
        # mirrors do not reach back to.
        line_bases = bases
        if rate_basis and base_name and bases.get(base_name) is None:
            from_sheet = allocations.get(mapping.kpi_code)
            if from_sheet is not None:
                line_bases = {**bases, base_name: from_sheet}

        fy_target, target_how, target_is_a_level = None, "", False
        allocated = allocations.get(mapping.kpi_code)
        if allocated is not None:
            fy_target = allocated
            target_how = "your own allocated target"
            target_is_a_level = True

        if fy_target is None and raw_target not in (None, ""):
            fy_target = float(raw_target)
            target_how = f"{field} on your {target_table} row"

        if fy_target is None:
            fy_target, target_how = role_target(mapping, line_bases)

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

        # A rule rather than a figure. CX mark some RMs "give full marks" on
        # the survey lines because the measure does not apply to them - TSC
        # scheme RMs, whose customers CX do not survey. That cannot go through
        # the actual ladder: there is no percentage, and inventing one would
        # make a decision somebody took indistinguishable from a measurement.
        full_marks = bool(figure.get("full_marks")) if figure else False

        # The actual ladder, and it is only two rungs: what the system can
        # measure, then what an administrator has loaded for the lines it did
        # not - the survey, the learning system, HR, Audit.
        #
        # The warehouse ALWAYS wins. A figure loaded by hand can never
        # overwrite a measured one, so a stale upload cannot quietly replace a
        # live number; and the card says which of the two it used, so a loaded
        # figure is never mistaken for a measured one.
        #
        # The rung is open to EVERY line, not only the ones nothing here can
        # measure. Restricting it to those sounded like a safety rail and was
        # the opposite: a line we measure on the wrong key - branch loan
        # turnaround, read from iApply on a seller code a branch manager does
        # not have - produced nothing AND refused the figure somebody had
        # loaded for it. Since the warehouse still wins wherever it answers,
        # opening the rung costs nothing and only ever fills a blank.
        warehouse_said = None

        # A loaded figure WINS, where there is one.
        #
        # This used to fill only a blank line, on the reasoning that a live
        # warehouse read beats a typed number. That reasoning fails on the
        # lines where the warehouse read is simply wrong: Faith Muthinja's
        # card showed Portfolio NPS at 100% where her signed card records
        # 42.9%, and her Reduce P&L provisions at nought where it records
        # -4,114,068.64. There was no way to correct either, because the
        # warehouse always won.
        #
        # A loaded figure is somebody's deliberate statement for a CLOSED
        # month - the query above reads only ``last_closed_month_end`` - so it
        # is the more considered of the two, not the staler. Where no figure
        # was loaded the warehouse is used exactly as before.
        #
        # What the warehouse said is kept rather than thrown away, so a
        # disagreement can be seen instead of silently resolved.
        owner_answered = (actual is not None
                          and source.actual_key in OWNER_MAINTAINED_KEYS)

        # A loaded ZERO does not override a figure the warehouse found.
        #
        # Nought is not a statement. It is what an empty cell becomes when a
        # template is saved, and these templates ship pre-filled with zeros -
        # so a loaded nought almost always means "nobody typed anything here",
        # not "this person sold nothing". Letting it win blanked lines the
        # warehouse had read perfectly well: Faith Muthinja's VIC Premiums
        # showed 0 against a warehouse figure of 468,067.25, her Net
        # Disbursements 0 against 36,663,806.28, and her card fell to 27.8%
        # on figures that were sitting right there. "why are you putting zeros
        # yet they are there and they are read".
        #
        # A loaded nought still fills a line the warehouse could NOT read,
        # which is the case it was always for. It simply cannot displace a
        # real figure.
        loaded = loaded_actuals.get(mapping.kpi_code)
        loaded_says_something = (loaded is not None
                                 and (loaded != 0 or actual is None))

        if loaded_says_something and not owner_answered:
            if actual is not None and actual != loaded:
                warehouse_said = actual
            actual = loaded
            as_at = loaded_as_at
            as_at_label = f"loaded by Administration for {loaded_as_at:%b %Y}"
            problem = None
            failed = False
            unwired = False

        # A target to earn less than nothing cannot be met or missed. It
        # comes of adding a growth to a base that was itself negative, and it
        # is a broken input rather than a target - so it is dropped here and
        # the line reports no target, instead of scoring against it.
        if (fy_target is not None and fy_target < 0
                and mapping.kpi_code not in MAY_BE_NEGATIVE):
            fy_target, target_how = None, ""

        # The GROWTH, where this line is measured as one - but ONLY where the
        # target that won is a LEVEL that has to be turned into one.
        #
        # The two rungs of the ladder mean different things, and this is the
        # whole of the bug it replaces. The ALLOCATION stores the year's level
        # beside the base it grew from, so its growth is the difference. The
        # DMC column does not: `target_deposits_value` and
        # `target_asset_growth_value` are ALREADY growth targets, never
        # balances. Subtracting an allocation base from a DMC growth mixes two
        # sources that were never the same quantity, and on Faith Muthinja's
        # card it produced a deposits target of -682,993,663.92 - against
        # which an actual of -14,450,155.80 scored 120%, rewarding her for
        # shrinking the book.
        #
        # So the subtraction is gated on the target being a level. A DMC
        # growth is prorated exactly as it stands.
        growth_target = None
        if (mapping.kpi_code in GROWTH_PRORATED and fy_target is not None
                and target_is_a_level):
            base_level = allocation_bases.get(mapping.kpi_code)
            if base_level is not None:
                growth_target = fy_target - base_level

        # A threshold holds all year; everything else is sliced to the date
        # its own actual is as at.
        #
        # A growth-measured line slices its GROWTH. The warehouse hands these
        # lines a movement as the actual, and a movement scored against a
        # balance can only come out at nought - see GROWTH_PRORATED, which
        # carries the workbook arithmetic this matches to the cent.
        full_year = mapping.kpi_code in FULL_YEAR_TARGETS
        to_slice = fy_target if growth_target is None else growth_target
        ytd_target = (to_slice if full_year
                      else prorate_to(to_slice, as_at,
                                      counted=source.counted))

        # The missing TARGET is reported ahead of a failed read, because a line
        # with no target cannot be scored whatever the actual turns out to be,
        # and because the two are fixed by different people: a missing target
        # column is the DMC load, a failed read is the warehouse.
        # A target the card states as a rate on one of this person's own
        # figures, where that figure could not be read. Reported ahead of the
        # DMC column, because the column is not what is missing: naming the
        # DMC load here would send somebody to add a column that was never
        # going to carry this line.
        # rate_basis and base_name are settled above, before the ladder.
        base_missing = (fy_target is None and rate_basis
                        and mapping.kpi_target is not None
                        and line_bases.get(base_name) is None)

        pending = pending_label = ""
        if full_marks:
            # Nothing is pending: the line is settled, and by whom shows in
            # the as-at label.
            pass
        elif source.pending and actual is None:
            pending, pending_label = source.pending, "Not measured here"
        elif base_missing:
            spelt = base_name.replace("_", " ")
            pending = (
                f"Your card sets this line at "
                f"{float(mapping.kpi_target) * 100:.0f}% of your {spelt}, and "
                f"that figure could not be read"
                + (f": {base_problems[base_name]}." if base_name in base_problems
                   else "."))
            pending_label = "No base to work from"
        elif field and target_problem:
            # The exception text is kept in ``diagnostic`` for whoever has to
            # fix it, and off the card. A Postgres error on somebody's
            # performance record tells them nothing and reads like a fault of
            # theirs.
            pending = ("Your targets could not be read just now. It is being "
                       "looked at - nothing here is a reflection on your "
                       "performance.")
            pending_label = "Targets unavailable"
        elif target_missing:
            # This used to name the warehouse table and ask for a column to be
            # added. True, and the wrong audience: it is on a document the
            # person signs, where a table name reads as a statement about them
            # and gives them nothing they can act on.
            pending = ("No target is set for this line yet. Administration "
                       "sets it under Scorecards \u2192 Figures to load.")
            pending_label = "No target set"
        elif fy_target is None:
            pending = source.no_target_reason or (
                "No target is set for this line yet. Administration sets it "
                "under Scorecards \u2192 Figures to load.")
            pending_label = "No target set"
        elif unwired:
            pending = ("There is no live source wired for this line yet. The "
                       "figure exists in the business; it is not yet read "
                       "from here.")
            pending_label = "No source yet"
        elif problem and failed:
            # Same again: the reason a read broke belongs with whoever fixes
            # it, not on a scorecard.
            pending = ("This figure could not be read just now. It is being "
                       "looked at - nothing here is a reflection on your "
                       "performance.")
            pending_label = "Temporarily unavailable"
        elif problem:
            # Not a fault - the figure honestly is not there, and the reason
            # says which piece is missing.
            pending = f"No figure for this line: {problem}."
            pending_label = "No figure yet"
        elif actual is None:
            pending = "The warehouse has no figure for this line yet."
            pending_label = "No figure yet"

        if full_marks:
            # Full marks, not 120%. The instruction is "give full marks",
            # which is the target met - not the target beaten.
            score = 1.0
        else:
            # This role's own cap wins where it has one. The cap is per role,
            # not per KPI: Faith Muthinja's Ultimate RM card scores VIC
            # Premiums at 200.0% where Abed Lelgo's Commercial RM card caps
            # the same measure at 120%.
            cap = getattr(mapping, "score_cap", None) or source.cap
            score = None if pending else score_for(
                actual, ytd_target, source.higher_is_better,
                threshold=source.threshold, cap=cap)
        weighted = None if score is None else weight * score
        if weighted is not None:
            total += weighted
            live_lines += 1
            scored_weight += weight
        else:
            pending_lines += 1
            unscored_weight += weight

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
            # This role's own wording first. One feed is read by several
            # roles against different numbers - CASA is "open 4 funded
            # accounts" on one card and "30 a day" on another - and the KPI's
            # own description is whichever role happened to be seeded first.
            "measure_of_success": (
                getattr(mapping, "kpi_description", "")
                or (named[mapping.kpi_code].kpi_description
                    if mapping.kpi_code in named else "")),
            "weight": weight,
            "ytd_target": ytd_target,
            # The year's figure as the roster holds it, beside the pro-rated
            # one, and the column it came from. A target an order of magnitude
            # out then shows on the card instead of silently capping the score
            # at 120% and being presented as an achievement.
            "annual_target": fy_target,
            # The "2025 FY" and "GROWTH" columns on the bank's own card.
            # Known only where the card states the target as a rate on one of
            # the person's own prior-year figures - "grow by 21% of the Dec
            # book" - which is the only place this platform holds a prior
            # year. Blank elsewhere, exactly as it is blank on most lines of
            # the printed card, rather than filled with a guess.
            "prior_year": (line_bases.get(base_name)
                           if (rate_basis and base_name)
                           else allocation_bases.get(mapping.kpi_code)),
            # The sheet's "GROWTH" column, where the line is measured as a
            # growth and the target therefore IS the growth.
            "growth_target": growth_target,
            "target_field": field,
            "target_source": target_how,
            "full_year_target": full_year,
            "ytd_actual": actual,
            # What the warehouse read, where a loaded figure overrode it and
            # the two disagreed. Kept so a disagreement can be seen and
            # chased rather than silently resolved; blank whenever they
            # agree, or when only one of them had a figure at all.
            "warehouse_said": warehouse_said,
            "score": score,
            "weighted_score": weighted,
            "as_at": as_at_label,
            "as_at_date": as_at.isoformat() if as_at else None,
            "higher_is_better": source.higher_is_better,
            # So the card can say why a line is at exactly 100% with no
            # figure beside it, instead of looking like a bug.
            "full_marks_rule": full_marks,
            "score_cap": getattr(mapping, "score_cap", None) or source.cap,
            "pending": pending,
            "pending_label": pending_label,
            # What actually went wrong, for whoever has to fix it. Separate
            # from ``pending`` so the person's own card and the signed
            # download can stay free of table names and SQL while the
            # Administration screens keep the detail.
            "diagnostic": (problem if (failed and problem)
                           else (target_problem if (field and target_problem)
                                 else "")),
        })

    return {
        "has_card": True,
        "live": True,
        "staff": {
            "sales_code": sales_code,
            "name": person.name,
            "title": (role.role_name if role else role_code),
            "role_code": role_code,
            "branch": person.branch,
            "team_leader": person.team_leader,
            # Which of the three rosters answered, so a card can be traced to
            # the list it came off.
            "roster": person.roster,
        },
        "period": {"label": datetime.date.today().strftime("%B %Y")},
        "target_source": target_table,
        "performance_score": round(total, 4),
        "scored_lines": live_lines,
        "pending_lines": pending_lines,
        # What the score is actually out of. ``performance_score`` is left
        # exactly as it was - a raw sum over the lines that scored, which is
        # what the workbook totals too - and these say what that sum could
        # have reached, so nobody reads a 65.66% as a 65.66% out of 100 when
        # an eighth of the weight was never on offer.
        "scored_weight": round(scored_weight, 4),
        "unscored_weight": round(unscored_weight, 4),
        "perspectives": perspectives,
    }
