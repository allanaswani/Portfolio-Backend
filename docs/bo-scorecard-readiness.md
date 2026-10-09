# Back-office scorecards: what the two workbooks say, and where they disagree

Read out of:

* `2026_BO_Non_Sales_Scorecards - Q2 with_updated_targets.xlsb` — 10 role cards,
  the roster, and the summaries
* `2026_BO_Actual_Template.xlsx` — 37 sheets, one per actuals feed

by `manage.py extract_bo_scorecards <workbook> --actuals <template>`, into
`docs/bo-scorecard-kpi-map.csv` (132 KPI lines) and
`docs/bo-scorecard-roster.csv` (101 people).

**Seeded by migration 0031**: 10 roles, 51 KPIs, 132 mappings, every card's
weights summing to exactly 1.000. Guarded by
`apps/staff_management/tests_bo_scorecards.py`.

What is NOT done is the roster — which of these 101 people holds which card —
and section 5 still lists the places the two workbooks disagree. A line
pointing at a sheet that does not exist cannot be getting its figure from
there in the manual process either, so those are questions rather than
defaults: the 16 KPIs behind them are seeded **inactive** with what the card
claims.

---

## 1. This workbook states its own KPI → actuals mapping

The RM workbook does not, which is why establishing it took a calibration pass
and why 19 RM KPIs are still seeded inactive. **The back-office cards carry the
actuals sheet per line**, in the column after `Comments`:

| Card line | Names |
|---|---|
| Active Clients | `Active_Customers` |
| NPL Management | `PL_Charge` |
| Dormancy Reactivation | `RE_activation` |
| NPS | `NPS` |
| TAT (AO) — PB and BB | `Account_Opening_PB`, `Account_Opening_BB` |
| TAT (Loan) | `Branch_Loan_TAT` |
| Branch Audit, resolution, compliance | `Branch_Audit`, `Branch_Audit_Resolution`, `Branch_Audit_Compliance` |
| Operation Losses | `Operation_Lossess` |
| Team Productivity | `Sales_Productivity` |
| Training hours | `Training_hours` |

So there is nothing to infer for 123 of the 132 lines.

Seven of the ten cards label that column `column_name`. Three — BOMCSO,
CASHTELLER_SCORECARD and TL_RBO_SCORECARD — stop their header at `Comments` but
still put the sheet name in the next column. The extractor falls back to the
position **and then checks every name against the template's real sheet names**,
which is what makes reading it positionally safe rather than a guess.

## 2. Three things that were wrong while reading it

Each would have put a wrong number on somebody's card, and each is now a test.

**The Target column is empty on nine of the ten cards.** Only BOM_SCORECARD
heads column 5 "Target" and puts the annual figure there; the other nine head
it **PM** — per month. Reading only "Target" left **120 of the 132 lines with
no target at all**. The per-month figure is multiplied by 12 on the way in,
because `kpi_target` means a yearly figure everywhere else in this system and
special-casing the pro-ration for these cards would have been worse.

**A KPI is keyed on its FEED, not its measure.** Keying on the measure split
NPS into two codes over a trailing disambiguator and split KYC over a typo on
one card ("clenup"), while lumping three different account-opening measures
together. Keyed on the feed, 51 KPIs cover all 132 lines, and the code is also
what somebody later asking "where does this number come from" would search for.

**A role cannot hold the same KPI twice**, and the cash-centre teller card has
two lines both reading `Branch_Audit` — one labelled "Branch Audit", one "Cash
Management". The first seed attempt died on the unique constraint. For a feed
that any single card doubles up on, the measure goes into the code; worked out
from the data rather than listed, and applied to every card using that feed so
the code stays stable.

## 3. Pro-ration, and what counts as a threshold

The YTD target is the annual figure sliced to the elapsed year for an accrual,
and **not sliced at all** for a threshold. Which is which is read off the card
rather than decided from the KPI's name:

* the per-month figure and the YTD figure are the **same number** — NPS 0.6
  against 0.6, branch audit 1 against 1 — so the line is a standard that holds
  all year; or
* the target is written as a **limit** — "< 2 Days", "<20%", "<5%" — in which
  case it is a ceiling by construction, and its number is in the YTD column
  rather than the target column, which is where it is taken from.

28 of the 51 codes are thresholds on that test. Six codes are ones the cards
**disagree** about, and the majority was taken: NPS (9 cards say threshold, 1
says accrual), operation losses (6/1), branch audit (5/1), reactivation (4/1),
CASA (2 say threshold, 4 say accrual → accrual), events (1/1 → accrual).

Separately, the cards do not agree on how many months have elapsed: for the
same Q2_Jun_2026 period, BOMCSO multiplies a monthly CRM target by 6 and CSO
multiplies the same measure by 2. One consistent rule — the elapsed year — is
applied to everybody, as it is on the RM cards.

## 4. The ten cards and the roster

| Card | Lines | Weight |
|---|---|---|
| CSM_DB_SCORECARD | 17 | 1.000 |
| BOM_SCORECARD | 15 | 1.000 |
| CASHTELLER_SCORECARD | 15 | 1.000 |
| CSO_UB_SCORECARD | 15 | 1.000 |
| CSO_SCORECARD | 13 | 1.000 |
| CASH_TELLER_SCORECARD | 12 | 1.000 |
| TELLER_SCORECARD | 12 | 1.000 |
| BOMCSO | 11 | 1.000 |
| RBO_SCORECARD | 11 | 1.000 |
| TL_RBO_SCORECARD | 11 | 1.000 |

Every card's weights sum to exactly 1.000, which is a good sign that the
extraction is complete rather than partial.

The `List` sheet is the roster — `StaffPF-Number`, `StaffSalesCode`,
`Staff - Name`, `Role`, `Branch`, `Zone`, `BM` (the line manager), the e-mail
routing, and four `prorate_*` factors for joiners, role changes, promotions and
acting cover. 101 people:

| Role | People |
|---|---|
| Teller | 41 |
| BOM | 25 |
| CSO | 25 |
| RBO | 6 |
| CSM_DB, CSO_UB, Cash_Center, TL_RBO | 1 each |

Note that **the roster's roles are not the card sheet names** — `Teller` has to
be resolved to `TELLER_SCORECARD` or `CASHTELLER_SCORECARD` or
`CASH_TELLER_SCORECARD`, and there are three teller cards. Which teller holds
which card is the first thing to settle; `Cash_Center` suggests the cash-centre
teller takes `CASHTELLER_SCORECARD`, but that is an inference and the desk
should confirm it rather than have it guessed.

There is also a `BMs` sheet with no KPI table, skipped.

## 5. Where the two workbooks disagree — nine lines

These name an actuals sheet that **is not in the template**:

| Named by a card | Probably means | Confidence |
|---|---|---|
| `HFDI_Volume` | `HFCB_Properties_Volume` | high — same measure, renamed |
| `HFDI_Value` | `HFCB_Properties_Value` | high — and that template sheet is named by no card |
| `Account_Errors` | `Trx_Errors` or `RBO_Account_Errors` | low — two candidates |
| `Account_Opening_sme` | a fourth account-opening sheet | none — PB, BB and UB exist; SME does not |
| `BBM_Financials` | the branch manager's financials | none |
| `Deposit_Growth` | a deposits feed | none — no deposit sheet in the template |
| `Cost` | a cost feed | none — and there is no cost data anywhere in the warehouse |
| `NPL` | `PL_Charge` | medium — `PL_Charge` is what the other cards use for NPL |
| `RBO_Monthly_Summ` | a summary sheet in the scorecard workbook, not an actuals feed | — |

And four template sheets are named by **no** card: `CSAT`, `Drawdown`,
`HFCB_Properties_Value`, `SLA`. Two of those are the other half of the rename
above; `CSAT` and `SLA` look like feeds nothing currently reads.

## 6. Nine lines name no sheet at all

| Card | Measure | Key initiative |
|---|---|---|
| CSO_UB | Customer Feedback | 3 Ultimate Banking client compliments |
| CSO_UB | TDs | Track UB term-deposit renewals |
| CSM_DB | Term Deposits | Track Diaspora term-deposit renewals |
| CSM_DB | NPL | Reduce P&L provisions (from Diaspora) |
| CSM_DB | Customer Journey | Document and approve the customer service journey |
| CSM_DB | Customer Feedback | 3 Diaspora Banking client compliments |
| TELLER | Customer feedback | Nil client complaints |
| TELLER | Customer feedback | 5 client compliments |
| RBO | Tools | TAT of 1 day for mobile banking |

Client compliments and complaints, a documented customer journey, and
term-deposit renewal tracking are all returns somebody keeps rather than feeds —
they belong on the **Figures to load** screen the RM cards already use.

## 7. What the platform can already answer

Against the 33 valid sheet names, these have a source in this database today:

| Actuals sheet | Source already wired or readable |
|---|---|
| `PL_Charge` | `loans_mom_ifrs_movement` — the loan-loss figure the RM card uses |
| `Active_Customers` | not yet — no two-month activity flag (same gap as the RM card) |
| `CASA`, `New_Customers` | `daily_sales_accounts_with_cto` on `sale_code` |
| `RE_activation` | `daily_dormancy_converted_accounts` — has `action_user` and `reactivation_date` |
| `Branch_Loan_TAT`, `Weighted_TAT`, `Account_Opening_*` | `iapply_loan_approvals_data_dump` — `seller_code` and `total_bank_tat`; account-opening TAT needs the account-opening feed, not iApply |
| `HFCB_Properties_Volume` / `_Value` | `weighted_dashboard_manual_sales_table` + affordable housing, as the RM card now does |
| `VIC`, `VIC_Life`, `VIC_Non_Life` | `insurance_policies` + `premium_types_mapping` |
| `Drawdown` | `drawdown_daily` |
| `Digital_Activation`, `Digital_Customers` | the digital feeds — per channel only, never a cross-channel total |
| `NPS`, `CSAT`, `SLA`, `CRM`, `KYC`, `Training_hours`, `Leave_management`, `Branch_Audit*`, `Events`, `Operation_Lossess`, `Cash_management`, `Trx_*`, `Branch_RTGS`, `Sales_Productivity`, `Diaspora_Audit`, `RBO_Account_Errors` | measured outside this platform — the Figures to load screen |

So roughly a third of the back-office lines are computable from what is already
here, and the rest are an upload — which is the same shape the RM cards ended
up in, and the machinery for both already exists.

## 8. What is left

**Done**: the 10 cards, their 51 KPIs, 132 mappings with per-role weights,
targets and wording, the threshold rule, and a source decision for every one of
the 51 — so no back-office line can reach a card without somebody having
decided what it is.

**The roster is the next piece, and it needs a decision.** These 101 people are
branch OPERATIONS staff; `branch_employee_dmc_data` is a SALES roster, so a
teller may well not be on it. `staff_employee_data` carries both `sales_code`
and `job_title`, which is the obvious bridge — resolve the card from the job
title the way `role_code_for` resolves an RM's. That needs checking against
production before it is built, because if the operations staff are not in that
table either, `List` has to be loaded as its own roster and the "no uploads"
rule does not survive contact with this group.

Also still open:

1. **The nine disagreements** in section 5 and the three teller cards in
   section 4. Questions for the desk, not inferences to make.
2. **Account-opening turnaround.** Three lines (PB, BB, UB) are a branch
   service measure. iApply carries LOAN turnaround, which is a different
   thing, so these are left unscored rather than pointed at it.
3. **Extend `MANUAL_ACTUALS`** with the back-office control measures — audit
   scores, KYC cleanup, complaints logged, operation losses, cash management,
   productivity — which makes them loadable on the Figures to load screen that
   already exists. The source entries name the return each comes from, so the
   list is already written; it just has to be moved.
