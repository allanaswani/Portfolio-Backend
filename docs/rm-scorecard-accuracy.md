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

### The target ladder

A line's target is looked for in three places, most specific first. **An
explicit figure for this person always beats a derived one.**

1. **the person's own column on the per-person DMC row** — the individual plan;
2. **a target allocated to them by hand** (`sc_employee_kpi_targets`);
3. **the role's own target** (`sc_role_kpi_mappings.kpi_target`), which is
   either a threshold everybody on the card shares, or a **rate on one of this
   person's own figures**.

That third rung needed cleaning up before it could be trusted. Migration 0027
filled `kpi_target` from the eight calibration cards, which for the FINANCIAL
lines meant one named RM's own closing balance:

    sme_rm         asset_growth     14,729,931.79   <- Charles Muchiri's book
    pb_rm          asset_growth  2,009,063,440.79   <- Vincent Ogare's book
    commercial_rm  asset_growth  1,752,701,010.45   <- Juspher Muriithi's book

Read as a role target, every SME RM in the bank would have been scored against
Charles Muchiri's balance. Migration 0029 cleared all 99 of those and kept the
98 that genuinely are one number for everybody on the card: PAR 2.5%, NPS 60%,
coverage 80%, audit 1.65, errors 5%, TAT 7 days, weighted TAT 100%, training
48/60 hours, covenants 12, tooling 12, property 2/3/1.25 units and
16.4m/24.6m/10.25m, and the 10M/50M new-customer counts.

**Asset Growth keeps a target, as a rate on the person's own base.** Every card
states it in the RM's own measure of success — "Grow by 43% of the Dec book
Balance" — and the December book is in the warehouse, per RM. So the rate lives
in `kpi_target` with `target_basis = "rate_on_base"`, and the card works the
target out from that person's own opening balance. The rates are the ones the
cards state: 43% Business Banking, 38% Personal Banking, 36% Ultimate, 21%
Commercial, 100% Diaspora.

Worth knowing before trusting it: **on three of those five cards the desk's own
assigned figure does not equal the stated rate times the stated base** (Personal
Banking's works out at 3.1%, Ultimate's at 23%, Commercial's at 10%). The stated
rate is what the card tells the RM they are measured on, so that is what is
used — and a `target_asset_growth_value` on the per-person DMC load overrides it
the moment one exists.

A target of **nought** is not a target. It is how the cards say a line does not
apply to a role (Mortgage Business carries a property target of 0), so it is
treated as absent rather than divided by.

**Thresholds are not pro-rated.** NPS of 60% does not become 45% because it is
September, and PAR's 2.5% ceiling does not loosen. `FULL_YEAR_TARGETS` lists
them.

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

**PAR is scored as a threshold, not a ratio.** All seven cards that carry it
are unanimous — at or under 2.5% is full marks, over it is nothing, and there
is no middle value anywhere — so scoring it in proportion would hand partial
credit for a limit that was broken.

**This reproduces 95 of the 109 lines across the eight cards exactly.** The 14
it does not are all listed in `tests_scorecard_calibration.KNOWN_DIFFERENCES`
with the reason. None is a rule this gets wrong — they are places the eight
cards **disagree with each other**:

* NPS is capped at 1.0 on two cards and left to run to 1.667 on a third.
* Loan loss is capped at 1.0 on one card and 1.2 on another.
* Training and leave are capped at 1.0 on three cards.
* One card lets a shrunken book score **-211%**. A negative score on a 0-120%
  scale cannot be explained to the person carrying it and no other card has
  one, so this tool floors at 0 and the shortfall shows as the zero it is.

A difference that turns out to be a *rule* gets implemented and removed from
that list. PAR was the first: it accounted for seven of the original 21.

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
| Number of Property | role target: 2 / 3 / 1.25 units | `weighted_dashboard_manual_sales_table` — units this staff member sold this year |
| Value of Property Sales | role target: 16.4m / 24.6m / 10.25m | same table, sum of `unit_value` |
| New Customer (Min Turnover 10M / 50M) | role target: 12 | `daily_sales_accounts_with_cto` — distinct customers opened this year by this `sale_code` with `cust_cto` at or above the floor |
| Cross-sell new CASA (focus accounts) | `target_focus_accounts` | same table, distinct new customers |
| TAT (Loan) | role target: 7 days | `iapply_loan_approvals_data_dump` — average `total_bank_tat` for this `seller_code`; **lower is better** |
| Weigted TAT / Weigted TAT (SLA) | role target: 100% | same table — share of applications inside the 7-day standard |
| PAR | role target: 2.5% | `loans` over this RM's allocated customers — arrears balance over total balance; **threshold, lower is better** |
| Asset Growth (where the DMC column is absent) | rate on the person's own December book | `loan_daily_balance_movement` growth |
| Number of Property, Value of Property Sales (affordable housing half) | role target | `affordable_housing_applications` joined to `afh_seller_mapping` on `assisted_by` |

Deposits and loans measure **GROWTH**, not position. A position passed off as
growth would credit every RM with their entire opening book and read several
hundred percent on day one.

A **flow** that finds no rows is a genuine zero — an RM who disbursed nothing
scores nothing, which is what the cards do. A **balance** that finds no rows is
*not* zero; it is a load failure, and the line goes pending rather than
reporting a shrunken book.

Four of those sources were already in this database and connected to nothing:

* **`weighted_dashboard_manual_sales_table`** — the HFDI sales return the
  weighted-sales dashboard is built from, one row per unit, carrying
  `staff_name`, `unit_value` and `sale_month`. It is keyed on a **name**, not a
  code, so the reader checks the name appears on the return at all before
  reporting a nil as a nil: a name spelt differently there reads exactly like
  somebody who sold nothing, and those two must not look the same on a
  scorecard.
* **`daily_sales_accounts_with_cto`** — the new-account return, carrying
  `sale_code` and, unused until now, `cust_cto`, the customer's **credit
  turnover**. That is what makes "minimum turnover of 10M" answerable.
* **`iapply_loan_approvals_data_dump`** — `seller_code` and `total_bank_tat`.
  The bank's *own* turnaround is used, not `tat`, which includes time waiting on
  the customer; holding an RM to that would be holding them to somebody else's
  delay.
* **`loans` + `retail_allocated_portfolio`** — PAR, from one table on one key.
  The RM's live balance comes from `loan_daily_balance_movement` on `rm_code`,
  which is a different book from the allocation, and a ratio whose numerator and
  denominator came from two different books would not be a ratio of anything.
  The allocation is de-duplicated first — it has no unique customer.

**Property comes off TWO returns, and this matters.** The HFDI sales return
names the advisor who **sold** a unit; `affordable_housing_applications` names
whoever **assisted** the buyer. A branch RM earns the Group Synergies credit the
second way, which is why reading only the first told most of them they were not
on the return at all. The chain is the bank's own, the same join
`hfcb_properties_reports/afh_applications.py` uses: `assisted_by` is free text
typed into the form, and `afh_seller_mapping` resolves it to a member of staff,
matched on the staff id against the sales code and on the name. A person has to
be findable on at least one of the two returns before a nil is reported as a
nil.

### Target wired, actual not available

| Line | Why |
|---|---|
| Net Mortgage sales — (non-)commercial rate | `target_mortgage_mrkt_rate` / `target_mortgage_non_mrkt_rate` are there, but `drawdown_daily` carries no market/non-market rate flag to split the actual the same way |
| New customers (> 2 active products), Ultimate | product count per new customer is not on the feed |
| Active Customers (2 months active) | the customer list is there; no activity flag to apply the two-month test to |
| Training | `target_training_hours` is there; hours are in the learning system |
| Deposits (Energy & Water) | a **sector** cut, and the balance tables carry no sector |

### Not measured here at all

NPS, Portfolio NPS, Portfolio Coverage, Weighted Sales (dashboard), Digital
Adoption, Errors, Audit, Leave management, Banking covenant tracking, Tooling
and account planning, Portfolio Management AUM — the survey, HR, the audit
return or a branch's own count.

**Bancassurance Premiums / Other Bancassurance Premiums** are "renewals and
other banca products". Which products are "other" is recorded nowhere, and the
cards carrying this line already count life and non-life beside it, so reading
it as either would double one of those lines.

## 5. The figures an administrator loads

Everything above is computed. What is left is measured somewhere this platform
cannot reach — the customer survey (NPS), the learning system (training hours),
HR (leave), Internal Audit, the branch's own engagement count, iApply covenant
tracking, account-planning reviews — plus the handful of targets the DMC load
has no column for. Those have nowhere to come from except a person typing them
in, so there is now a screen where a person types them in:

**Administration → Scorecards → Figures to load**
(`/management/scorecards/manual-figures`)

* The template is **generated from the roster**, not kept as a file: one row
  per person per line that actually needs a figure, with their name, sales
  code, role and KPI already filled in. A blank template somebody has to match
  up by hand is how a figure ends up against the wrong sales code.
* **Read first, write second.** The first upload reports what it found and
  saves nothing; only a second call with `apply=true` writes.
* A figure against a sales code nobody holds, or against a KPI that is not on
  that person's card, is **refused** rather than written somewhere nothing
  reads. So is an actual for a line the warehouse computes — accepting it would
  be worse than refusing it, because the card would never read the figure and
  whoever typed it would believe it had.
* **The warehouse always wins.** A loaded figure is used only where the system
  has nothing of its own, so a stale upload can never overwrite a live number —
  and the card labels it "loaded by Administration for <month>", so a typed
  figure is never mistaken for a measured one.
* A figure is for the month that has **closed**, and an older one is **not
  carried forward**: a survey score from four months ago presented as this
  month's is worse than a blank.
* Admin and superusers only, and the two tables it writes
  (`sc_employee_kpi_targets`, `sc_employee_performance_actual_values`) both
  already existed with nothing writing to them.

`ScEmployeePerformanceActual.save` had to be repaired to make this work: it
called `update_change_reason` *before* `super().save()`, so it looked for a
history record the save had not created yet and raised `'NoneType' object has
no attribute 'history_change_reason'`. Until that was reordered, **no row in
that table could be updated at all** — only inserted. The requirement is kept;
only the order changed.

## 6. How much of a card is covered

| Role | Measured automatically | Loaded by Administration | Nowhere |
|---|---|---|---|
| Commercial RM — Trade | 81% | 19% | 0% |
| Diaspora RM / ARM | 81% | 19% | 0% |
| Commercial RM | 76% | 24% | 0% |
| SME RM / ARM / BBC | 72% | 28% | 0% |
| PB RM / ARM / BBC | 71% | 29% | 0% |
| Ultimate RM | 66% | 34% | 0% |
| Mortgage Business ARM | 44% | 56% | 0% |

Every line of every card now has somewhere to come from. The Mortgage Business
card leans hardest on the upload because 40% of it is the two mortgage
rate-split lines, and splitting those automatically needs a market/non-market
rate flag on the drawdown.

## 7. Signing

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

## 8. What the lake does and does not hold

`delta.gold_db`, 231 tables, searched by column rather than by guessing at
table names. Worth recording so nobody searches it again:

* **There is no targets table.** Every `target` or `budget` column in the lake
  belongs to something else — FX recording, currency dimensions, savings goals,
  campaign budgets. The DMC tables in Postgres remain the only per-person plan.
* **Only four tables are keyed to a staff member**: `rpt_ceo_deposit_trends`,
  `rpt_ceo_loan_trends` and `rpt_ceo_loan_trends_bkp` on `rm_code`, and
  `trade_register_entry` on `rm_code`. `usr.ak_seller_code` is the fifth.
* `rpt_ceo_loan_trends` carries `dec_1y_bal`, which is the same opening balance
  the Postgres mirror holds as `dec_25_bal` — that is where the growth
  calculation came from.
* **`hfbi_policy_data`** (bancassurance) carries `policy_sales_person`,
  `policy_insurer` and `policy_class`, which would settle the VIC question
  below — `policy_insurer` shows Britam, Pioneer and Geminia, confirming VIC is
  an **insurer** split while life/non-life is a **class** split, so the two are
  definitely different axes. It is **not usable as it stands**: the
  `documents` array column contains commas and quotes, and the delta files are
  mis-split as a result, so values appear in the wrong columns on most rows.
  That is an upstream ingestion fault, not something to work around in a
  scorecard.
* **`sql_cto_values`** holds credit turnover per CIF per month in the lake; the
  Postgres mirror `daily_sales_accounts_with_cto` carries the same thing per
  account with the seller's code, which is why the turnover lines are answered
  from Postgres and not from here.

The card is computed in Postgres, so a lake table is only useful once the ETL
mirrors it. Nothing in this module reads Trino at request time: a page that
depends on a second database is a page that goes blank when that database is
busy.

## 9. Still to settle with the desk

1. **The two banca lines' axis.** The lines are *named* VIC / Group Synergies
   but *described* "life policies" / "non-life". The DMC roster and
   `premium_types_mapping` both carry the life/non-life split, so that is the
   axis used. The lake's `policy_insurer` confirms VIC is an insurer split
   (Britam, against Pioneer and Geminia) and therefore a different question. If
   the cards mean the insurer split, these two lines are reading the wrong half.
2. **The caps the cards disagree on**: NPS (1.0 or 1.2), loan loss (1.0 or
   1.2), training and leave (1.0 on three cards), and whether a negative growth
   line may take a card negative.
3. **Asset Growth**: the stated rate (43/38/36/21/100%) against the desk's own
   assigned figure, which differs on three of the five cards. Adding
   `target_asset_growth_value` to the per-person DMC load settles it for good
   and overrides the rate automatically; so does loading it on the
   Figures-to-load screen.
4. **`target_pbt_revenue` and `target_loan_provisions`** are on the branch DMC
   table and not the per-person one. Operating Profit, Income Contribution,
   Direct Portfolio Contribution and Loan Loss are 15-20% of most cards, and
   until the DMC load carries those two columns they come off the
   Figures-to-load screen. Two columns in the ETL would make them automatic.
   They are **not** taken from the branch row: a branch revenue target handed
   to one RM reads as a couple of percent and paints a fully performing RM red.
5. **The `weighted_dashboard_manual_sales_table` name match.** It is keyed on
   `staff_name`, so an RM whose name is spelt differently there will see "on
   neither return" rather than a figure. A seller code on that return would
   remove the whole class of problem — the affordable-housing side already has
   one, through `afh_seller_mapping.staff_id`.

## 10. A separate finding: the affordable-housing upload drops rows

Not fixed here, because it is another module's validation and not mine to
loosen without a decision — but it bears directly on the property line, so it
is recorded.

`AffordableHousingApplicationSerializer` rejects a **blank** value in six
fields: `assisted_by`, `typology`, `project_name`, `mode_of_payment`,
`need_deposit_assitance` and `status`. The model declares all six
`null=False, blank=False`.

Verified against the serializer directly: a row with those blank comes back
invalid on all six. So any row in an affordable-housing export with a blank in
one of them is refused by `affordable-housing-applications/upload-csv/` rather
than loaded — and `assisted_by` blank is a perfectly ordinary case (a walk-in
with nobody named), as is `status` on a new application.

`apps.hfdi.tests.AffordableHousingCsvUploadTests.test_application_upload_amends_and_upserts`
has been failing for this reason: its row leaves five of the six blank, so
nothing is written and the test's `objects.get(...)` raises `DoesNotExist`.
The same test also asserts `obj.timestamp == "2024-03-05T14:30:00"` — a string
— against a `DateTimeField`, so it has a second problem behind the first.

**Why it matters here:** the scorecard's property line reads
`affordable_housing_applications`. In production that table is filled by the
ETL (`hfcb_properties_reports/afh_applications.py` reads it, so something
upstream writes it), not by this endpoint, so the line is not starved today.
But anyone loading a correction through the screen will lose rows without
being told which, and whichever of the six fields can genuinely be blank
should be `blank=True` on the model.
