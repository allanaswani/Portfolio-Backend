# RM scorecards in the tool, instead of in the inbox

What it would take to stop emailing `Portfolio Management - Q<n> <year>_scorecards.xlsb`
and let each RM open their own card with current numbers.

Everything below was read out of the two files, not assumed:

* `Portfolio Management - Q3 2026_scorecards.xlsb` — 47 sheets; the scorecards,
  the roster and the targets.
* `2026_Actual_Template.xlsx` — 65 sheets, one per KPI; the actuals that get
  pasted in each month.

The extracted configuration is in **`docs/rm-scorecard-kpi-map.csv`** — 132 KPI
lines across the 8 RM role cards, each with its perspective, weight and the
actuals sheet its ACTUAL is drawn from.

---

## 1. The engine is already here

This is the part worth knowing before planning any work. `apps/staff_management/scorecard_automation`
(the `sc_*` tables) already models the workbook almost column for column.

| Scorecard sheet column | `sc_employee_monthly_performance` |
|---|---|
| COUNT | `kpi_order` |
| KPI (the perspective + its %) | `mapping_category` |
| KPI Description | `kpi_name` / `kpi_description` |
| Weight | `kpi_weight` |
| 2025 FY | `prev_year_value` |
| 2026 FY | `curr_year_value` |
| YTD Target | `ytd_target` |
| ACTUAL | `ytd_actual` |
| % SCORE | `ytd_score` |
| Weighted Score | `ytd_weighted_score` |

The rest of the chain exists too:

* `sc_kpi_definitions` carries `score_cap`, `is_increasing`,
  `kpi_calculation_mode` (actual_over_target / growth_on_growth /
  percentage_of_target / tiered_range) and `kpi_rating_type` (nps / prorate) —
  which is exactly the set of behaviours the workbook's formulas show.
* `kpi_calculations/` implements `actual_over_target`, `growth_on_growth`,
  `inverse_growth` and `tiered_range`.
* `services.py` has role history (`get_current_role`), per-person proration
  (`get_employee_target_proration_details`), leave months, target resolution and
  `run_monthly_kpi_scorecard` for all / one / a role / a department.
* `/staff_management/monthly-performance-detail/self/` already returns **the
  signed-in user's own rows**, scoped on `portfolio_profile.sales_code`.
* `/rm-portfolio/scorecard-performance` already consumes it, and
  `/management/scorecards/kpi-engine` already edits the configuration.

**So this is not a build-from-scratch job.** The engine runs; its three input
tables are empty, and nothing can fill them except one-row-at-a-time POSTs.

### The arithmetic checks out

Taking the `Commercial` sheet (Juspher Muriithi, Q3_Aug_26) and recomputing from
the cells: the 17 weighted scores sum to **0.4952**, which is the Performance
Score the sheet itself shows. So the model is:

```
% SCORE        = clamp(ACTUAL / YTD Target, 0, 1.2)
Weighted Score = Weight x % SCORE
Performance    = sum(Weighted Score)
```

The 1.2 cap is visible where Net Loan Disbursements runs 752.7M against a 520M
YTD target — a ratio of 1.447, scored 1.2.

`YTD Target` is the FY figure prorated 8/12 for most lines (Trade Income
9.6M → 6.4M; New Customers 12 → 8; Training 48 → 32), **but Asset Growth and
Grow Deposits prorate the GROWTH column instead** (Deposits: GROWTH 417.6M ×
8/12 = 278.4M, which is what the sheet shows — not the 513.5M FY figure).

---

## 2. What has to be added

### a. A way to load the actuals — the real blocker

`sc_employee_performance_actual_values` (`sales_code`, `kpi_code`, `eom_date`,
`kpi_value`) can only be written one row at a time through
`performance_actuals/`. The actuals arrive as a 65-sheet workbook.

**The import is NOT mechanical, and this is the part that would have gone
wrong.** Two things about those sheets are not visible from their headers, and
both were established by reproducing figures the cards already state.

**1. The month columns hold YTD cumulative values, not monthly amounts.**

Juspher Muriithi's VIC premium column runs Apr 1,685,325 → May 1,685,325 →
Jun 2,076,983 → Jul 2,076,983 → **Aug 2,076,987**, and the card's ACTUAL for
Q3_Aug_26 is **2,076,987** — the August cell. Summing Jan–Aug gives 9,601,603,
which is **4.6x too high**. So:

```
ACTUAL for a review month = that month's cell, as-is.  Never a sum.
```

**2. The wide sheets are several stacked tables, and the card picks one.**

A sheet is not always 18 columns. `Banca_Assurance_Income` is 118 — six repeats
of the same `PF | Sales Code | Name | Role | Branch | Zone | Jan..Dec` block at
columns 1-18, 21-38, 41-58, 61-78, 81-98 and 101-118, with no labels anywhere.
They are composites of each other: for Juspher at August, block 4 = block 2 +
block 3 (2,000,215 + 76,772 = 2,076,987) and block 6 = block 4 + block 5.

His card's "VIC Premiums — All insurance" takes **block 4**. Block 1 would have
given 2,410. So the block is part of the KPI's definition, not a detail.

Block counts for the sheets the RM cards use: `Banca_Assurance_Income` 6,
`Revenue_Contribution` 5, `Plot_Sales_Value` / `Plot_Sales_Volume` /
`Asset_Drawdown` 3, `Trade_Finance_income` 2, the rest 1.

**3. Some lines negate the sheet's value.** `PL_Charge` stores Juspher's loan
loss as **+1,882,000**; the card shows **-1,882,000**. Same magnitude, opposite
sign, on all four cards that use it.

So a KPI definition needs three more facts — `actuals_sheet`, `actuals_block`
and `negate` — and the importer reads the review month's cell from that block.

The upload itself should be the two-step the pipeline upload uses: read and
report first, write only on a second call, because it replaces everybody's
numbers at once.

### What calibration established

`docs/rm-scorecard-kpi-map.csv` holds all 132 lines with, for each, the
perspective, weight, the actuals sheet, **the block, whether it negates**, and
the card's own 2025 FY / GROWTH / 2026 FY / YTD Target / ACTUAL / % SCORE /
Weighted Score. Each of the 8 role sheets contains one real person's card, so
each line could be tested against a figure that is already known to be right.

| | Lines | |
|---|---|---|
| Block identified by matching the card's stated ACTUAL | 72 | evidence |
| Same, with the sign flipped | 4 | evidence |
| Sheet has only one block, so block 1 is certain | 10 | certain |
| **Pinned** | **86** | |
| ACTUAL is zero on a multi-block sheet — cannot tell blocks apart | 31 | unresolved |
| Card's person is not in the `List` roster | 15 | unresolved |

The 31 unresolved lines need only **14 block definitions** named, because they
cluster:

* `Plot_Sales_Volume` and `Plot_Sales_Value` — 3 blocks each, 14 lines. Nobody
  on any of the 8 cards sold property, so every block reads zero.
* `Banca_Assurance_Income` — 6 blocks, 12 lines. Partly pinned: block 4 is VIC
  on the Commercial card and block 5 is "Other Bancassurance Premiums" on
  Commercial_trade, but PB, Ultimate and Mortgage split VIC into separate life
  and non-life lines whose own figures are zero.
* `Asset_Drawdown` — 3 blocks, 4 lines (block 1 is pinned for Commercial's "Net
  Loan Disbursments"; PB's "Drawdowns" and Mortgage's two commercial /
  non-commercial lines are zero).
* `Trade_Finance_income` — 2 blocks, 1 line.

The 15 are the whole **Home Loan Specialist** card: it is made out for *Michael
Oyoo Odhiambo*, who is **not in the `List` roster**, so there is no sales code
to look his actuals up by.

**Nothing has been assumed for any of those 46 lines.** Defaulting them to
block 1 would put Banca premiums 860x out on the Commercial card, so they stay
unconfigured until someone names the blocks, and a KPI that is not configured
should read "not configured" on the card rather than show a figure.

### b. The role configuration, loaded rather than typed

8 RM role cards, 132 KPI lines, already extracted to
`docs/rm-scorecard-kpi-map.csv`:

| Role sheet | Role title | KPI lines | Weight total |
|---|---|---|---|
| Business_Banking | SME RM | 18 | 1.0250 |
| Personal_Banking | PB RM | 19 | 1.0250 |
| Ultimate_RM | — | 18 | 1.0250 |
| Diaspora | — | 16 | 1.0250 |
| Home_Loan_Specialist | — | 15 | **1.0500** |
| Mortgage_Business | — | 13 | 1.0250 |
| Commercial | COMMERCIAL RM | 17 | 1.0250 |
| Commercial_trade | — | 16 | 1.0250 |

(1.0 plus a 0.025 bonus line. Home_Loan_Specialist totals 1.05 — worth a look.)

Entering 132 lines by hand on the kpi-engine screen is how a configuration ends
up subtly wrong, so this wants a seed or an importer off that CSV.

### c. The roster link

The `List` sheet is the driver, and it is already keyed the way the platform is:

```
sales_code | name | role | branch | BBM | e-mail1 | Zone | e-mail2 | prorate_new | new/role_change
```

**91 people, 12 roles** — all RM-grade, which is what makes "start with the RMs"
a clean first slice:

| Role | People | | Role | People |
|---|---|---|---|---|
| SME RM | 17 | | SME ARM | 6 |
| PB ARM | 13 | | PB RM | 6 |
| SME BBC | 11 | | COMMERCIAL RM | 4 |
| Mortgage Business ARM | 11 | | DIASPORA RM | 3 |
| PB BBC | 9 | | DIASPORA ARM | 2 |
| Ultimate RM | 7 | | COMMERCIAL RM- TRADE | 2 |

`sales_code` already lives on `portfolio_profile`, so the join to a login
exists. What is missing is each person's `role_code` (which card applies) and
`prorate_new` (why a joiner's YTD target is not a clean 8/12).

`BBM` and the two e-mail columns are the manual distribution list — the thing
being replaced.

---

## 3. What "realtime" can honestly mean

The actuals are **monthly per-person snapshots**, not live feeds. Of the 32
sheets the RM cards draw on, they split three ways:

* **The warehouse can already compute these daily** — deposits, drawdowns,
  revenue contribution, new customers, asset growth, portfolio AUM, CASA. The
  SQL for them already exists in `apps/portfolio` and `apps/staff_management`.
* **Only the workbook has these** — training hours, leave management, NPS,
  mystery shopping / contactability, covenant tracking, tooling and account
  planning, branch audit, CES. They originate in other teams' spreadsheets.
* **Derived** — PAR, PL charge, NPL, weighted TAT.

So the honest promise is: *live for what the warehouse holds, and as of the last
upload for the rest* — with the as-of date shown per KPI on the card rather than
one date for the whole page. The repo already does this kind of freshness ladder
for RM balances.

---

## 4. Open questions — things I could not determine and will not guess

The `.xlsb` stores cached values, not formulas, so three rules could not be
derived:

1. **Loan Loss.** Actual -1.882M against a -4.931M YTD target scores exactly
   **1** — not the raw ratio (0.38) and not the 1.2 cap. The rule for a
   lower-is-better money KPI is therefore something specific.
2. **PAR.** 0.0878 against a 0.025 target scores **0**. Some threshold applies
   rather than a ratio.
3. **VIC Premiums (Commercial).** YTD Target is **4.48M** where FY × 8/12 would
   be 8.15M. Rows 34–35 of that sheet hold a life / non-life split (6.112M each,
   actuals 0.406M and 4.074M) that sums to the 4.48M. So this target is built
   from that split, not prorated.

A copy of the workbook saved as **.xlsx** would make those formulas readable and
settle all three, and would also name the 14 blocks above. Otherwise someone
who maintains the workbook needs to state them — it is a short list.

Also to confirm:

* **PB's NPL line** sits under a perspective headed `( 5% )` but carries
  `Weight = 0`, so it scores 0.9193 and contributes nothing. Deliberate, or a
  mistake in the sheet?
* **`Account_Errors` and `Plot_Sales`** are referenced by the Home Loan
  Specialist card but **do not exist** in `2026_Actual_Template.xlsx`.
* **`Trade_Finance_Income` vs `Trade_Finance_income`** — the Commercial and
  Commercial_trade cards use the capitalised spelling; the actuals sheet is
  lower-case. An exact-match importer would silently drop Commercial's trade
  income, so the lookup has to fold case.
* **`SME_BBC_RM_OLD`** is the 2022 card and **`Banking_Income`** still carries
  2023 month headers. Both look retired; confirm before anyone wires them.
* **Michael Oyoo Odhiambo** has a Home Loan Specialist card but is not in the
  `List` roster. Either he is missing from the roster or the card is stale.
* Several sheets the cards depend on are **empty for 2026** in the template as
  supplied — `CASA`, `Contactability`, `PAR`, `Loan_Approvals`,
  `Loan_Application_Errors`, `sector_deposits` all have nothing on row 2. If
  that is how they arrive each month, those KPIs will score 0 for everybody.


---

## 5. Built so far

**`ScEmployeeKpiTarget`** (`sc_employee_kpi_targets`) — the one structural gap.
`ScRoleKpiMapping.kpi_target` is per role, which is right for the KPIs where
everyone on a card carries the same number (48 training hours, NPS 60%, PAR
2.5%) but cannot express the financial targets: those are allocated per person
in the workbook's **`Summary Allocation`** sheet (99 sales codes x 78 columns,
grouped DEPOSITS / LOANS / AUM / TOTAL INCOME CONTRIBUTION / NPL / EXPENSE
MANAGEMENT / FTP / CREDIT SERVICE FEES / LOAN LOSS / NFI). On the Commercial
card one RM's deposit growth target is **4.35x his own base** — plainly not a
role rate.

`StaffEmployeeService.get_kpi_target_values` now prefers a row for that person
and year, falling back to the role's target when there is none, so nothing
already configured changes behaviour. The row can also carry the scorecard's
"2025 FY" base. Six tests cover the precedence, the fallback, the
other-person and other-year cases, and the one-target-per-person-per-year
constraint.

Still to build: the three KPI-definition fields (`actuals_sheet`,
`actuals_block`, `negate`), the actuals and allocation importers, the seed of
the 86 pinned lines, and the RM page in the card's own shape.
