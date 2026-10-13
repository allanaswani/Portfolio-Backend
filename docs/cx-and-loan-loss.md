# Customer experience, training hours, and where Loan Loss comes from

Three questions. Two needed building; the third turned out to need nothing but
a check.

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

### The target — it was never a DMC column

The card used to say:

> `branch_employee_dmc_data` has no `target_loan_provisions` column, your
> role's card carries no target for this line either, and nobody has allocated
> you one. It is a column for the DMC load to add.

True, and the wrong conclusion. Reading the four cards that carry the line
with numbers on it shows the desk **derives** the target, the same way every
time:

| card | prior year | growth | this year | rate |
|---|---|---|---|---|
| Commercial | −9,245,965.64 | +1,849,193.13 | −7,396,772.51 | 80% |
| Commercial_trade | −20,053,060.49 | +4,010,612.10 | −16,042,448.39 | 80% |
| Ultimate_RM | −4,537,193.86 | +3,024,795.91 | −1,512,397.95 | 33.3% |
| Personal_Banking | −5,031,576.71 | −670,876.89 | −5,702,453.60 | 113.3% |

`prior year + growth = this year` on all four, to the cent. The year's target
is **the person's own prior-year provision times a rate the role sets** —
Commercial and Commercial-Trade are told to cut provisions by a fifth,
Ultimate by two thirds, Personal Banking is allowed 13.3% more.

That is the shape Asset Growth already uses, so migration
`0036_loan_loss_target_rate` seeds it the same way: `target_basis =
"rate_on_base"`, the rate in `kpi_target`, against a new base
`last_year_loan_loss` that `portfolio_service.rm_loan_loss` reads off
`loans_mom_ifrs_movement` for the year before.

Two things deliberately not done:

* **The branch table's column is not used.** `target_loan_provisions` does
  exist — on `branch_final_employee_dmc_data`, one row per *branch*. Giving an
  RM the whole branch's allowance would be an order of magnitude too loose,
  and because the line is scored smaller-is-better the error *flatters*: it
  would show as full marks. The branch row is still read whole for somebody
  with no per-person row (a BBM), where it is genuinely their own target.
* **No rate is invented for a role whose card states none.** Business Banking,
  Diaspora and Mortgage Business carry no numbered Loan Loss line among the
  eight cards, so they get nothing and keep saying so.

If the prior year cannot be read — `loans_mom_ifrs_movement` is ETL-fed and may
not go back a year — the line now says *that*, naming the rate and the base,
instead of sending somebody to add a DMC column that was never going to carry
it.

`target_pbt_revenue` is a separate and still-open gap: Operating Profit and
Income Contribution take their target off the Figures-to-load screen.


---

## 3. Training hours — a line on every card, scored at last

### What was wrong

A training line sits on **all 22 cards**: `business_banking_training` on seven
sales roles, `personal_banking_training` on five, and `bo_training_hours` on all
ten back-office roles. Not one could be scored. The card said "Training hours
are recorded in the learning system, not here", which was true and was also the
end of the conversation.

They are recorded in `2026 Training Returns Template - <Mon>_<yy>.xlsx`, which
HR circulate monthly: one row per person, one column per month, hours in the
cells. Ten sheets — eight of people (`Staff_Training_Returns` plus one per desk)
and two of pivoted averages, which are derived and skipped by name.

### What exists now

`sc_training_return` (migration `0037_training_returns`), `training.py`,
`manage.py load_training_returns`, two endpoints under
`scorecard-automation/training/`, and **Administration → Scorecards → Training
returns**.

Upload-and-view, not edit-in-place — the opposite choice from the CX screen and
deliberately so: this return is a system extract of 289 people across twelve
months. That is not a form, and retyping it would be a worse record than the
file.

### It reproduces the cards

Four of the eight calibration cards name an RM who appears on the August 2026
return. The Jan–Aug sum gives the card's own stated actual **exactly on all
four**, and the pro-rated target matches the card's stated YTD target on all
four too:

| card | on the return | hours | card's actual | target | card's target | score | card |
|---|---|---|---|---|---|---|---|
| Business_Banking | CM4236 | 36.0 | 36.0 | 32.0 | 32.0 | 1.000 | 1.000 |
| Diaspora | EK4188 | 38.5 | 38.5 | 40.0 | 40.0 | 0.9625 | 0.9625 |
| Commercial | JM4191 | 29.0 | 29.0 | 32.0 | 32.0 | 0.90625 | 0.90625 |
| Commercial_trade | GW3961 | 69.0 | 69.0 | 32.0 | 32.0 | 1.000 | 1.000 |

### Three decisions

**The PF number is the key, not the sales code.** The roster has Charles
Muchiri as `CMM4236`; the return has him as `CM4236`. Both say 4236. Matched on
the code alone he has no training figure at all — and on a card that is
indistinguishable from an RM who did none. `live_scorecard.pf_for` finds the PF
off the DMC row, or the HR record for a back-office person who has no DMC row.

**The as-at is the month the return reaches, not the person's own last
figure.** This decides a score. Juspher Muriithi's 29 hours run out in June;
sliced to June his target is 23.8 and he scores 122%, sliced to August it is 32
and he scores 90.6% — which is what his card says. A blank month *inside* the
return is no training that month; a blank month *beyond* it is not reported yet.
Slicing to the person's own last figure would reward exactly the people who
stopped training.

**Training stops at full marks, and here the cards are unanimous.** Two cards
score a training line above its target — Business Banking 36 hours against 32,
Commercial-Trade 69 against 32 — and **both wrote exactly 1.0**. No training
line on any card scores above full marks. That is a rule rather than the
judgement call the survey cap needed, so the two `Training` entries that used to
sit in `KNOWN_DIFFERENCES` are gone: they reproduce now.

Calibration: **96 → 98 of 109**.

**Not being on the return is not nought hours.** Three cards show 0.0 for
somebody the return does not mention, which is the desk filling a blank. The
card now says "you are not on the training return, which covers up to
<month>" and names the PF matching as the likely cause.

### Two bugs the tests caught

* **`pf_of("4236.0")` returned `"42360"`.** openpyxl hands back a numeric cell
  as a float, `str(4236.0)` is `"4236.0"`, and dropping the non-digits gives a
  confident match against a different person — not a failed match, which would
  at least be visible.
* **A row with hours and no PF and no code was skipped before being counted.**
  The cumulative-target row at the foot of each desk sheet (4, 8, 12 … 48) looks
  exactly like a person whose identifying columns are blank, and the second of
  those is somebody's score. Now counted and reported, never loaded.

### Who may load one

Superuser, or `staff_mgt` / `Management` / `hr`. Not `cx` — the CX team
maintain the survey, not this. Not `is_staff`. Reading is open to any signed-in
user.


---

## 4. The card as a document

Everything in this section came off somebody looking at a real card, which is
why none of it was in the original design.

### The bank is HFCB

The sheet said `HFC PERFORMANCE SCORECARD`. HFC is the old name, and it must
not go out on a document somebody puts their signature to.

### The download is read-only

A scorecard is a record, and a signed one is a record somebody has put their
name to. Left editable, the first thing that happens to a downloaded card is
that a figure gets changed in it and the file is forwarded, and nothing then
distinguishes that copy from the one that was signed.

So the sheet carries Excel's own protection and the workbook structure is
locked. It is a **deterrent, not encryption** — a determined person can strip
it — and it carries **no password**, because what this stops is the accident,
which is the thing that actually happens, and a password nobody wrote down is
a support call. Selecting and copying stay on: people have to be able to read
the thing.

### The tool's own plumbing is off the card

`Lines scored: 14 of 19` and `Targets read from branch_employee_dmc_data` are
gone from the sheet and from the RM's page, along with the per-line target
source. They are internals — how many lines this managed to compute, and which
warehouse table it read — and on somebody's performance record they read as a
statement about the person. A table name on a bonus record also invites the
question of what else is in the table.

Nothing is hidden by it: a line with no figure still prints its own reason in
the ACTUAL column, which is the same information said honestly and attached to
the line it belongs to.

The **Administration catalogue keeps its coverage count**, because there it is
the whole point of the screen.

### Two pending reasons were worse than the summary

One named a warehouse table and asked for a column to be added to it. The
other printed a raw Postgres error, complete with `LINE 5:` and a caret — on a
document somebody signs. Both now say something a person can act on, and the
technical text moves to a new **`diagnostic`** key on the line, so whoever has
to fix it still has it and the card stays clean.

### A signature can be withdrawn

Signing is one button beside a long page, and people press it before they meant
to — which is exactly what happened in the first week. Until now the only
remedy was editing the database, and **a figure that can only be corrected in
the database is a figure nobody can trust.**

`my-card/unsign/`, a "Withdraw my signature" button, and
`manage.py unsign_scorecard <code> [--list]` for the case the screen refuses.
Migration `0038_signature_withdrawal`.

The rules are narrow on purpose:

* **your own card only** — the sales code comes from the signed-in profile, as
  it does for signing, so there is no parameter to forget to check;
* **not once the line manager has counter-signed** — at that point the two of
  you have agreed a document and one side cannot quietly take it back. A
  superuser can, because somebody has to be able to fix a genuine mistake, and
  it is recorded against their name;
* **the frozen copy is kept**, with `withdrawn_at` set. "This was signed and
  then withdrawn" is part of the record; deleting the copy would hide it.

### A real bug found on the way: nobody could counter-sign

The line manager was read from **one of the roster's two manager columns**.
`branch_employee_dmc_data` carries `team_leader_name` **and** `team_leader`,
with nothing in the schema to say which the ETL fills, and
`branch_final_employee_dmc_data` carries only `team_leader`.

Read one and stop, and a card shows a blank line manager and **nobody can
counter-sign it** — a silent failure of the whole sign-off, which looks like
the manager simply not having got round to it. `live_scorecard.team_leader_of`
now tries the name column first and falls back to the other. That is also the
safe way round if one of them turns out to hold a code rather than a name: the
name column wins, and the code column never matches a signer.

### Lines with no feed now name the screen

The old wording stopped at "measured outside the warehouse", which is true and
reads as *this will never work*. **Weighted Sales**, **banking covenant
tracking** and **tooling and account planning** have no feed and are not going
to get one — they are counts somebody keeps, like the audit return and leave.
All of them were already on the Figures-to-load screen; the reason now says so,
which turns a dead end into one action.
