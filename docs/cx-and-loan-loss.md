# Customer experience, and where Loan Loss comes from

Two questions, one answer each. The first needed building; the second turned
out to need nothing but a check.

---

## 1. Customer experience — the two lines that used to wait for an e-mail

### What was wrong

Every RM scorecard carries two customer lines:

| Card line | Target | Weight |
|---|---|---|
| Portfolio Coverage (engagement) | 80% | 5% |
| Portfolio NPS / NPS / Portfolo NPS | 60% | 5–10% |

Neither could be scored. The figures existed — the CX team produce
`RM Contactability, Satisfaction & Segment NPS & CES Q<n> <year>.xlsx` each
quarter and circulate it by e-mail — but nothing in the platform read them, so
both lines showed **"Not measured here"** on every card. Between 10% and 15% of
most cards was unscoreable for want of a spreadsheet somebody had to be asked
for.

### What exists now

`cx_rm_metric` and `cx_segment_metric` (migration
`staff_management/0035_cx_metrics`), plus **Administration → Scorecards →
Customer experience** (`/management/scorecards/customer-experience`), which is
where the CX team keep the figures. Editing comes first on that screen; the
upload is for a first load and for a quarter CX would rather paste in bulk.

Nothing has to be retyped for the first load. The reader takes CX's own
workbook exactly as they save it:

| sheet | column | feeds |
|---|---|---|
| `Contactability` | `RM Name`, `%Contactability` | Portfolio Coverage (engagement) |
| `Satisfaction` | `RM Name`, `% CSAT` | the NPS line |
| `NPS & CES Summary` | segment, `NPS`, `CES` | nothing — see below |

Code: `apps/staff_management/cx_metrics.py` (the reader and what the card
reads), `cx_views.py` (four endpoints under
`staff_management/scorecard-automation/cx/`), `manage.py load_cx_survey`, and
the two registrations in `live_scorecard.py`.

### Four decisions, not four numbers

**The NPS line is fed by CSAT.** The line on the card is called Portfolio NPS;
the figure behind it is the RM's own CSAT from the Satisfaction sheet, which is
what the business scores — the actuals template the cards are built from calls
that sheet `NPS`. The per-segment NPS in CX's summary sheet is a different
measure and is **not per RM**, so it cannot settle a personal card. It is
stored under its own name, shown on the screen with that warning attached, and
read by no scorecard line. Calling CSAT "NPS" in the database would have hidden
the difference.

**"TSC- Give full marks" is a rule.** Four RMs in the Q2 file carry that text
where a percentage would be — TSC-scheme RMs, whose customers CX do not survey.
Parsed as 0 they score nought on a measure that does not apply to them; written
as 1.0 the rule becomes indistinguishable from a measured 100%. So the figures
stay NULL, a `full_marks` flag is set, and the card scores the line at exactly
full marks with the reason in place of the as-at date.

The desk's own cards corroborate this. Vincent Ogare (PB RM, VOO4330) is one of
the four, and his Q3 card carries an actual of exactly **1.0000** on both lines
— somebody implemented "give full marks" by writing 100% in.

**Both lines stop at full marks, not 120%.** This is the one decision the cards
do not settle, so here is the count. Six card lines across the eight Q3 cards
score a survey measure above its target:

| card | line | target | actual | raw | the card wrote |
|---|---|---|---|---|---|
| Ultimate_RM | Portfolio NPS | 0.60 | 1.0000 | 1.667 | **1.000** |
| Diaspora | Portfolio NPS | 0.60 | 0.9095 | 1.516 | **1.000** |
| Personal_Banking | Portfolio Coverage | 0.80 | 1.0000 | 1.250 | **1.000** |
| Personal_Banking | NPS | 0.60 | 1.0000 | 1.667 | 1.200 |
| Commercial | Portfolio NPS | 0.60 | 0.6667 | 1.111 | 1.111 |
| Mortgage_Business | Portfolio NPS | 0.60 | 1.0000 | 1.667 | 1.667 |

Note rows 3 and 4: **the same card capped one survey line at 1.0 and the other
at 1.2.** There is no rule to reproduce.

Counted over all nine numeric survey lines on the cards, a cap of **1.0
reproduces six**, 1.2 reproduces five, and no cap reproduces five. 1.0 wins by
one line. What settles it is not the one line — it is that 1.0 is the only cap
more than one card applied here, and that the instruction for an RM the measure
does not apply to is "give **full marks**" rather than give 120%.

The three cards 1.0 does not match are named in
`tests_scorecard_calibration.KNOWN_DIFFERENCES`, and
`test_the_cap_count_is_what_this_file_claims` counts the table above off the
cards so the claim cannot rot. The whole decision is two numbers — `Source.cap`
on the two registrations in `live_scorecard.py` and `CX_CAP` in that test file —
so the desk can have the other answer whenever it wants it.

This took the calibration from **95 to 96 of the 109** card lines reproduced
exactly.

**A name that matches nobody is reported, never guessed at.** CX's file is
keyed on the RM's name and carries no sales code, so every name is resolved
against all three rosters on the way in — the branch DMC roster, the
back-office roster, and the HR record — and a name no roster knows is kept,
flagged, and put at the top of the screen. It matters because **a name CX spell
differently from the roster is an RM with no score, and on the card that looks
exactly like an RM CX did not survey.** Whitespace is folded for matching
("Winfred Kivuva  " in the Q2 file has two trailing spaces) but the original
string is what the row is keyed on, so a correction finds its own row again.

### Smaller things that would have gone wrong

* **Both sheets carry pivot tables from column 11 onwards**, and one of their
  headers is also `RM Name`. The reader takes the *first* matching column;
  taking the last picks up "Grand Total" as an RM.
* **CX write 0.8 and a person types 80.** One parser handles both, used by the
  workbook route and the typed route alike — a second set of rules in the
  endpoint is a second set to get wrong, which it duly was until a test caught
  it.
* **A period can hold segment figures and no RM rows.** `latest_period()` asks
  both tables; asking only the RM table made such a period invisible.
* **A partial correction leaves the rest of the quarter alone.** CX send a
  two-row fix; replacing the period would blank 71 RMs' scores.
* **The as-at date is the period's end**, not the day it was typed. A Q2 score
  is a Q2 score whenever CX get round to it. Both lines are in
  `FULL_YEAR_TARGETS`, so the target is not pro-rated — 60% is 60% in March.
* **The figures are not carried forward.** A quarter with no row for an RM
  says so rather than presenting last quarter's number as this one.
* **A typed figure with no period joins the period already loaded**, not the
  quarter we happen to be in. Defaulting to today would open a new period on
  the first typed figure, and because a card reads the *newest* period, that
  one row would shadow the loaded quarter for all 73 RMs.
* **The signed download prints the rule**, not a blank beside a 100% score:
  a full-marks line writes "Full marks by rule — this measure does not apply"
  in the actual column. That document is what a line manager signs.
* **A typed figure still works.** `nps` and `portfolio_coverage_engagement`
  stay in `MANUAL_ACTUALS`, so Administration can still load a figure for a
  quarter CX have not got to. CX's own figure wins once it is there, because
  the measured figure always wins.

### Who may change a figure

Superuser, or the `staff_mgt` / `Management` / `hr` / **`cx`** groups.
Deliberately **not** `is_staff`, which is legacy noise in this estate.

`cx` is new and is the point of the exercise: it is registered in
`core/roles.py` and carries its own one-screen nav block, so a CX user can
maintain these figures without being an administrator of anything else. An
administrator grants it from the Users screen.

Reading is open to any signed-in user — an RM should be able to see the figure
they are scored on.

---

## 2. Loan Loss — already right, and here is the proof

### The question

Finance maintain `3. FS_MOM_IFRS_MOVEMENT_Branch & TREND (with Special
Assets).xlsb`. The worked example adds four sheets that turn it into a per-RM
figure. Does the scorecard's Loan Loss line agree?

### The chain in the workbook

The monthly file has ten sheets: `BRANCH SUMMARY_2026` and one per month, 36
columns, a row per loan account. The worked example has thirteen — it adds
`rm_summary`, `CUSTOMER SUMMARY_2026`, `BRANCH_SUMMARY_2026_by customer` and
`unique_cif`. Three steps:

1. **On a monthly sheet, `NET` = `P&L_Charge` − `Int. Adj`.** Exactly:
   `7,180,415.670671493 − 213,299.13991357503 = 6,967,116.530757918`.
2. **`CUSTOMER SUMMARY_2026` pivots that by customer and month** as
   `<Mon> P&L Charge`, `<Mon> Int. Adj` and `<Mon> Loan Loss` — the third again
   the first minus the second, across **12,058 customers × 8 months with no
   exceptions** — and totals them into `YTD Loan Loss`.
3. **`rm_summary` pivots that by `rm_code`** into "Sum of YTD Loan Loss", which
   is the figure a card carries.

### What the platform computes

`services/portfolio_service.py`, in four statements:

```sql
-SUM(COALESCE(pl_charge, 0) - COALESCE(int_adj, 0))
FROM loans_mom_ifrs_movement
WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
  AND cust_code_strategy ~ '^[0-9]+$'
```

grouped by customer and joined to the RM's allocated book. The same arithmetic,
negated because that query returns income categories (a provision charge is a
negative contribution to income) and negated back for the card. The card then
floors it at nil — a net *release* is not a negative provision, it is nil
provisions, which is the line's own target — and scores it smaller-is-better.

**No change was needed, and none was made.** What was added is
`apps/staff_management/tests_loan_loss.py`, which pins the arithmetic to the
workbook's own numbers and fails if that SQL expression is ever simplified.

### Where the two will differ, and why that is not a fault

Not the arithmetic. **Who the customer belongs to.** Of the example's
361,605,835.99 for the year:

| on | amount | |
|---|---|---|
| a label that is a sales code | 300,924,353.02 | 92 labels |
| a bare number (a code without its letters) | 18,513,091.47 | 15 labels |
| the literal text `Unmanaged` | 19,929,220.94 | no RM — chiefly SPECIAL ASSETS |
| `#N/A` | 27,477,075.10 | the workbook's own lookup failed |
| `#VALUE!` | −5,237,904.52 | the workbook's own lookup failed |

So **42,168,391.51 — 11.7% of the group's loan loss — is attributable to nobody
in the workbook**, and 22,239,170.57 of that is a broken lookup rather than a
deliberate exclusion. The Special Assets portion must never reach a card: cif
167313 alone carries 7.7m in January.

This platform maps a customer to an RM through `retail_allocated_portfolio` —
the allocation the business maintains — so it will attribute some of what the
workbook leaves on `#N/A`, and will never put the Special Assets book on a
person. A per-RM difference between the two is that mapping, not the measure.

`manage.py check_loan_loss <workbook> [--sales-code A,B]` prints the comparison
RM by RM, with the unattributed total named first. Run it on the host, where
the warehouse is; it needs the 13-sheet worked example, not the 10-sheet
monthly file.

### One risk worth stating

`loans_mom_ifrs_movement` is fed by the Trino ETL, and the Grade / YTD
loan-loss branch of that ETL has been thin before (see the arrears fan-out
note). If the table is behind, the card's figure is low and nothing in the card
can tell that apart from a good year. `check_loan_loss` against the current
workbook is the way to find out.

### Still outstanding on this line

`target_loan_provisions` is **not** a column on the per-person DMC table, so
the Loan Loss line's *target* still comes off the Figures-to-load screen. The
actual is measured; the plan is typed in until the DMC load carries that column
(the same gap as `target_pbt_revenue`).
