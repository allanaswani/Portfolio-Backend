# RM scorecard: what each line is scored from, and what it is not

The companion to `docs/rm-scorecard-live.md`, which explains how the card is
built. This one is the audit trail: for every line on every card, where the
target comes from, where the actual comes from, and — where a line is not
scored — the reason, so nobody has to guess whether a blank is a bug.

Everything here is enforced by tests:

* `apps/staff_management/tests_scorecard_calibration.py` — the tool's score
  against the score the real Q3 2026 cards award, line by line.
* `apps/staff_management/tests_scorecard_accuracy.py` — the target table, the
  pro-ration, and the sign-off.

---

## 1. The targets come off the per-person table

There are **two** DMC tables and they are a different grain. Reading the wrong
one is the single biggest error this card has had.

| Table | Rows | Upserted on | What it is |
|---|---|---|---|
| `branch_employee_dmc_data` | ~786 | (pf number, sales code, role) | **one row per sales person — an individual's plan** |
| `branch_final_employee_dmc_data` | 22 | `staff_branch` | one row per **branch**, held by that branch's BBM |

The per-person table leads. The branch table is read **only** when the
per-person table has no row for that sales code at all — the BBM case, where
their personal row *is* the branch row.

It is never used to fill a gap in somebody's individual plan. Handing an RM
their branch's revenue target would read as a couple of percent and paint a
fully performing RM red.

`targets.py` has encoded this rule since August (`_PRIMARY["rm"] = "staff"`).
The card was reading the other way round, which scored an SME RM against a
14.4m disbursement target where their own card says 270m.

**The columns are asked of the database, not of the Django model.** Both tables
are ETL-fed and the file can carry a column this repo has not declared yet;
reading the model's field list would report "no target set" for a target
sitting right there in the row. See `_table_target_columns`.

The card states which table its targets came from, and every line states its
column and its annual figure, so any number on it can be traced to a row.

## 2. Each line's target is pro-rated to that line's own as-at date

Not to today. A deposit balance as at 30 September compared against a target
sliced to 9 October charges the RM nine days of plan they never had the chance
to earn.

This also reproduces the manual card. On all eight Q3 cards the YTD target is
the annual figure times 8/12, with actuals to 31 August — and 31 August is day
243 of 365, so day-of-year and months/12 agree to one part in 750.

A monthly feed with no row date (income, premiums, trade) is dated to the end
of the **last closed month**, because that is the freshest it can honestly be.
Balances carry their own date off the freshness ladder (yesterday, the day
before, then the last closed month end).

## 3. The scoring rule

    score = clamp(1 + (actual - target) / |target|, 0, 1.2)

which is plain `actual / target` whenever the target is positive, and still
means what it should when the target is **negative** — one Personal Banking
card carries an income contribution target of -73.3m against an actual of
-37.2m and scores it 120%, where a bare ratio reads 0.51.

Provisions and loan loss invert on magnitudes: `|target| / |actual|`, with nil
provisions scoring the cap rather than dividing by zero.

**This reproduces 88 of the 109 lines across the eight cards exactly.** The 21
it does not are all listed in `tests_scorecard_calibration.KNOWN_DIFFERENCES`
with the reason. None is a rule this gets wrong — they are places the eight
cards **disagree with each other**:

* NPS is capped at 1.0 on two cards and left to run to 1.667 on a third.
* Loan loss is capped at 1.0 on one card and 1.2 on another.
* PAR is pass/fail against 2.5% on all seven cards that carry it — full marks
  at or under, nothing over — which is not a ratio at all.
* One card lets a shrunken book score **-211%**. A negative score on a 0-120%
  scale cannot be explained to the person carrying it and no other card has
  one, so this tool floors at 0 and the shortfall shows as the zero it is.

Where the manual process has no single answer, one rule is applied to
everybody. That is the only version that can be defended to the person whose
bonus depends on it.

## 4. Line by line

### Scored live

| Line(s) | Target column | Actual |
|---|---|---|
| Grow Deposits, Deposit Growth, Deposits (Portfolio / + NTB) | `target_deposits_value` | `daily_balance_movement`: balance now minus last December's close |
| Asset Growth | `target_asset_growth_value` | `loan_daily_balance_movement`, same way |
| Drawdowns, Net Loan / Asset / Net Disbursements | `target_loan_disbursement` | `drawdown_daily.net_drawdown` YTD, matched on `salesperson` **or** `loan_officer_id` |
| New Business Banking / Personal Banking Customers | `target_new_customers` | `rm_new_customers_ytd` |
| Direct Portfolio Contribution | `target_pbt_revenue` | GII - IE + NFI |
| Income Contribution, Operating Profit | `target_pbt_revenue` | GII - IE + NFI + FTP - loan loss |
| Loan Loss, Reduce P&L provisions | `target_loan_provisions` | provision charged, floored at nil; **lower is better** |
| Trade Income | `target_trade_finance_income` | `trade_finance_data.commission_lcy` |
| Trade Volume, Trade Finance Volume | `target_trade_finance_value` | `trade_finance_data.amount_fcy * fx_rate` |
| VIC Premiums | `target_banca_life` | life premiums — `insurance_policies` joined to `premium_types_mapping` on `life_policy_check = 'life'` |
| Group Synergies (20/23/25%) | `target_banca_non_life` | non-life premiums, same join |
| VIC Premiums (Commercial, "All insurance") | `target_banca_value` | all premiums |

Deposits and loans measure **GROWTH**, not position. A position passed off as
growth would credit every RM with their entire opening book and read several
hundred percent on day one.

A **flow** that finds no rows is a genuine zero — an RM who disbursed nothing
scores nothing, which is what the cards do. A **balance** that finds no rows is
*not* zero; it is a load failure, and the line goes pending rather than
reporting a shrunken book.

### Target wired, actual not available

| Line | Why |
|---|---|
| Net Mortgage sales — (non-)commercial rate | `target_mortgage_mrkt_rate` / `target_mortgage_non_mrkt_rate` are there, but `drawdown_daily` carries no market/non-market rate flag to split the actual the same way |
| New Customer (Min Turnover 10M / 50M) | turnover is not on the new-customer feed, so the *qualifying* count cannot be taken |
| New customers (> 2 active products), Ultimate | product count per new customer is not on the feed |
| Active Customers (2 months active) | the customer list is there; no activity flag to apply the two-month test to |
| Cross-sell new CASA (focus accounts) | counted off the CASA opening return, not a table this platform reads |
| Number of Property | unit plan is on the roster; the sales feed carries no customer identifier, so a sale cannot be tied to an RM — see `docs/property-holdings-etl-gap.md` |
| Training | `target_training_hours` is there; hours are in the learning system |
| Deposits (Energy & Water) | a **sector** cut, and the balance tables carry no sector |

### Not measured here at all

NPS, Portfolio NPS, Portfolio Coverage, Weighted Sales (dashboard), Digital
Adoption, Weighted TAT, TAT (Loan), Errors, Audit, Leave management, Banking
covenant tracking, Tooling and account planning, Portfolio Management AUM,
Value of Property Sales — the survey, HR, the audit return or a branch's own
count.

**PAR** is its own case: it is a ratio against a threshold, and the roster
carries an NPL *amount*, not a PAR percentage. Scoring a percentage against a
shilling value would be meaningless, so it is left unscored.

**Bancassurance Premiums / Other Bancassurance Premiums** are "renewals and
other banca products". Which products are "other" is recorded nowhere, and the
cards carrying this line already count life and non-life beside it, so reading
it as either would double one of those lines.

## 5. How much of a card scores live

Share of each card's weight that is scored from live data today:

| Role | Scored live |
|---|---|
| Commercial RM — Trade | 61% |
| Diaspora RM / ARM | 61% |
| Commercial RM | 60% |
| SME RM / ARM / BBC | 56% |
| PB RM / ARM / BBC | 55% |
| Ultimate RM | 53% |
| Mortgage Business ARM | 10% |

The Mortgage Business card is nearly all pending because 40% of it is the two
mortgage rate-split lines, which need a rate flag on the drawdown.

## 6. Signing

A live card cannot be signed. It is computed from feeds that move every night,
so a signature on it would attest to a document that reads differently an hour
later — and the point of the signature is that both sides agree on what the
figures **were**.

So signing freezes it. `sc_scorecard_signoffs` holds one row per person per
month (`YYYY-MM`, the month that has closed), carrying the complete card as it
stood. Afterwards the page serves that copy, not live figures, and the download
renders from it.

Two signatures, one row:

* the owner signs their **own** card — the sales code is resolved from their
  profile, so there is no parameter to forget to check;
* the line manager counter-signs, and only the person the roster names as their
  team leader is accepted. A manager cannot counter-sign a card the owner has
  not signed (409), because there would be nothing to counter-sign.

Endpoints:

    GET  /staff_management/scorecard-automation/my-card/
    POST /staff_management/scorecard-automation/my-card/sign/      {role, comment}
    GET  /staff_management/scorecard-automation/my-card/download/  -> .xlsx

The download is a spreadsheet, because a spreadsheet is what the desk sends:
the header block, each perspective with the same six columns, the total, then
the signature block. A pending line prints its **reason** where the figure
would go, not a zero — a zero reads as "achieved nothing", which is a different
statement from "nobody has this figure". An unsigned download says so on the
sheet.

## 7. Still to settle with the desk

1. **The two banca lines' axis.** The lines are *named* VIC / Group Synergies
   but *described* "life policies" / "non-life". The DMC roster and
   `premium_types_mapping` both carry the life/non-life split, so that is the
   axis used. If VIC is meant to be the Britam-product split instead — the
   vocabulary used on the commercial pipeline — these two lines are reading the
   wrong half and the mapping needs changing.
2. **The caps the cards disagree on**: NPS (1.0 or 1.2), loan loss (1.0 or
   1.2), and whether a negative growth line may take a card negative.
3. **PAR**: 2.5% is consistent across all seven cards. Is it a fixed bank-wide
   threshold, or is it meant to be per person? It is on no roster column.
4. **Which targets belong on the per-person table.**
   `target_asset_growth_value` and `target_pbt_revenue` are only on the branch
   table in this repo's model. If the production per-person table carries them,
   they are picked up automatically, because the columns are read from the
   database. If it does not, the Asset Growth and Operating Profit lines will
   say "No target column" — and those two are 10-15% of most cards.
