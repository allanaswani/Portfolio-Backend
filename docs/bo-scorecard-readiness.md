# Back-office scorecards: what the two workbooks say, and where they disagree

Read out of:

* `2026_BO_Non_Sales_Scorecards - Q2 with_updated_targets.xlsb` — 10 role cards,
  the roster, and the summaries
* `2026_BO_Actual_Template.xlsx` — 37 sheets, one per actuals feed

by `manage.py extract_bo_scorecards <workbook> --actuals <template>`, into
`docs/bo-scorecard-kpi-map.csv` (132 KPI lines) and
`docs/bo-scorecard-roster.csv` (101 people).

Nothing is seeded yet. This is the groundwork, and it records the nine places
the two workbooks do not agree — those need an answer before any of it is
scored, because a line pointing at a sheet that does not exist cannot be
getting its figure from there in the manual process either.

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

## 2. The two pro-ration rules already hold here

On these Q2_Jun_2026 cards the YTD target is:

* the annual figure **× 6/12** for every money and count line
  (−434,037 → −217,019; 2 → 1; 4 → 2; 48 → 24);
* **unchanged** for every threshold — NPS 0.6, audit 1.0, audit resolution
  0.85, compliance 0.9, productivity 0.8, operation losses 0.0.

That is the same pair of rules the RM card follows: pro-rate to the elapsed
year, and never pro-rate a threshold. The `ytd_over_annual` column in the CSV
records what each card actually did, so this is read off rather than assumed.

Each card also carries `month_count` in its header (10 on these), which is
worth confirming the meaning of — the figures are consistent with 6/12, not
10/12.

## 3. The ten cards and the roster

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

## 4. Where the two workbooks disagree — nine lines

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

## 5. Nine lines name no sheet at all

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

## 6. What the platform can already answer

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

## 7. What it would take

1. **Settle the nine disagreements** in section 4 and the three teller cards in
   section 3. Those are questions for the desk, not inferences to make.
2. **Seed the 10 cards** the way migration 0027 seeded the RM ones — roles, KPI
   definitions, weights and perspectives, from `bo-scorecard-kpi-map.csv`. The
   mapping is declared here, so no calibration pass is needed and nothing
   should be seeded inactive.
3. **Resolve the roster's roles to cards**, and decide whether the back-office
   roster comes from `List` or from the DMC tables. These 101 people are
   branch operations staff, and `branch_employee_dmc_data` is a SALES roster —
   a teller may well not be on it, in which case `List` has to be loaded as its
   own roster rather than derived.
4. **Point each line at its source**, reusing `live_scorecard.SOURCES` — the
   `Source` dataclass, the target ladder, the pro-ration and the scoring rule
   all apply unchanged.
5. **Extend `MANUAL_ACTUALS`** with the outside-the-warehouse sheets, which
   makes them loadable on the screen that already exists.
