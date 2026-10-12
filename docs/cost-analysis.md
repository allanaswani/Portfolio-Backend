# Operating costs: where they come from now

## What this replaced

The CEO deck's cost section was two hard-coded constants in
`app/(dashboard)/gceo/page.tsx`:

* `costsExpenseLines` — ten expense lines with annual amounts
* `costsDeptData` — eighteen departments × nine months (`jan`…`sep`)

Stale, no branch split, and April read **10,670** for ICT — which is a
part-month of postings presented as a month. There was also a note in this
repo's own memory saying there was *no cost data anywhere in the warehouse*.
That note was **wrong**, and this is the correction.

## The cost data was never missing

`delta.gold_db.sap_cost_data` holds SAP document postings with a **cost centre**
and a **GL account** on every line. What was missing were the two mappings that
turn a posting into a department figure:

| Needed | Where it is now |
|---|---|
| cost centre → department, and which are branches | `sap_cost_centre` — **new**, migration 0034, 84 centres from the Finance notebook |
| GL account → expense line | `operating_expense_mapping` — **already there** since migration 0023, 249 accounts, and nothing was reading it for this |

All ten of the hard-coded expense-line names were already in that GL mapping's
`actual_gl_name`. There is a test that fails if one of them ever stops being
there, because that line would silently vanish from the real report and
somebody would say the new figures are wrong.

## Sources

* `trino_cost_extraction_query.txt` — Finance's extraction query, kept verbatim
  in `cost_ingest.TRINO_QUERY`.
* `cost_analysis_sap_report.ipynb` — Finance's analysis. Every rule in
  `cost_analysis.py` is lifted from it and quoted where applied.

## The rules, and why each one matters

Taken from the notebook, not invented. Each changes the answer.

1. **A credit is negative.** `amount` = `lcy_amount`, negated when SAP's
   `SHKZG` is `H`. The extract gives the magnitude either way. Without the
   sign, a credit *adds* to a cost instead of reducing it and every total is
   out by twice the credits.
2. **The date is not on the posting.** It comes from `assignment_number` as
   `YYYYMMDD`, falling back to `reference_document_number`. Neither is
   reliably populated alone. An impossible date (31 September appears in the
   data) falls through rather than raising — the notebook's `errors='coerce'`.
3. **An operating expense is a 7-series GL, minus three.** `705190002` loan
   loss charges, `701010014` lease liability interest, `705190006` interest
   adjustments. In the notebook these are three numbers in an `if` with a
   comment; they are now rows in `sap_cost_exclusion` with their reasons, where
   they can be seen and changed. Counting them would inflate every department
   with charges that belong in impairment and interest.
4. **It must also have a GL mapping row.** The notebook's
   `operating_expenses()` overwrites `operating_expense` to
   `non_operating expense` off the 7-series and then filters it out.
5. **An unmapped cost centre is dropped, not bucketed.** So is `BRANCH GROWTH`,
   a holding cost centre rather than a place (seeded `is_reportable = False`).
   A cost with nowhere to go must not land in a department that did not spend
   it — so it is **counted and named** on the screen instead.
6. **A branch is grouped by NAME, not by cost centre code.** Several branches
   have two codes — Kisumu 18 and 600, Eldoret 21 and 410, Hurlingham 19 and
   210, Mombasa 300 and 310. Grouping on the code would report each of those
   twice, at half its cost. 27 branch cost centres, 22 distinct branch names.
7. **Each extract is a full snapshot for its date.** That is why Finance's
   query ends `WHERE d.dt = m.max_dt`, why a load *replaces* its snapshot, and
   why a file carrying two extract dates is refused rather than half-deleted.

## Getting the data in

```bash
# From the lake — the one that should run on a schedule
manage.py load_sap_costs

# From a file, for a correction or when the lake is unreachable
manage.py load_sap_costs --file extract.xlsx

# Read and report, write nothing
manage.py load_sap_costs --dry-run
```

The command prints what it kept, what it skipped and why, and then **what it
cannot place** — unmapped cost centres and unmapped 7-series GLs, with the
amount each is carrying. That is the one failure that silently shrinks every
department total and looks exactly like a quiet month.

Trino needs `TRINO_HOST`, `TRINO_PORT`, `TRINO_USER`, `TRINO_PASSWORD` in the
environment. Without them the command says so and points at the upload instead,
rather than failing obscurely.

## The screen

**Administration → Cost Analysis** (`/management/cost-analysis`)

* **The report** — cost by department × month, by branch × month, by expense
  line and by company, for the current and previous fiscal year.
* **Cost centres** — the mapping, editable. Change a department and the report
  follows.
* **Load an extract** — pull from the lake, or upload a file. Read-and-report
  first; only a second call with `apply=true` writes.

The health tiles sit above the report, and anything that cannot be placed is
named with what it carries.

## Endpoints

```
GET  staff_management/costs/summary/          ?snapshot=YYYY-MM-DD&year=YYYY
GET  staff_management/costs/snapshots/
GET  staff_management/costs/postings/         filterable, the rows behind a figure
POST staff_management/costs/upload/           {file, apply}
POST staff_management/costs/load-from-lake/
     staff_management/costs/cost-centres/     list / create / patch / delete
     staff_management/costs/subsidiaries/
     staff_management/costs/exclusions/
```

Reading the summary needs only a signed-in user, because the CEO deck reads it.
Changing a mapping or loading an extract needs superuser or the `staff_mgt`,
`Management` or `finance` group — **not** `is_staff`, which is legacy noise in
this estate and carried by a great many accounts.

## The CEO deck

The two constants are **kept as a fallback** rather than deleted. Until the
first extract is loaded the deck has nothing else, and showing dashes where a
figure has always been would be a worse regression than showing the old one.
Once an extract is loaded the real figures win, and the panel says which of the
two it is looking at — *"SAP extract of 2026-09-10"* or *"No SAP extract loaded
— showing the previous hard-coded figures"*.

The month columns are now **derived from the data** rather than fixed at
`jan`…`sep`, so a ten-month extract shows ten months.

## Why the mirror is at posting grain

`sap_cost_posting` is one row per SAP document *item*, not a pre-aggregated
monthly table. A department total nobody can break down into the postings
behind it is a figure nobody can defend — and the same rows answer the
department view, the branch view, the expense-line view and the subsidiary view
without a second load. `costs/postings/` is filterable so any figure on the
screen can be traced to its documents.

## Verified against the live table, 2026-10-12

The whole chain was run end to end against `delta.gold_db.sap_cost_data`, not
just type-checked:

| | |
|---|---|
| rows in the table | 1,979,137 across 63 source files |
| the query returned | **44,769** rows, extract date **2026-10-08** |
| read / kept / skipped | 44,769 / 44,769 / **0** |
| postings with no usable date | **0** |
| fiscal years present | 2026 only |
| entry months present | 12 — 2025-11 through 2026-10 |
| of those, 7-series | 21,518 postings, 4,176,806,819 |
| on an **excluded** GL | **373,402,868** |
| held out (BRANCH GROWTH) | −23,713,445 |
| **reaches a department total** | 20,667 postings, **3,824,145,751** across 18 departments |

Two things that confirms, which were assumptions until it ran:

**The three GL exclusions are doing real work.** 373 million sits on loan-loss,
lease-interest and interest-adjustment accounts inside the 7-series. Without
rule 3 every department total would be inflated by that, which is roughly a
tenth of the whole figure.

**All 24 columns exist and the types are what the loader assumes.** 97 columns
in all. `zuonr`, `hzuon`, `hkont` and `kostl` are **integers** in the lake, not
varchars, and `gjahr` is a **varchar** year — all handled, and the zero skipped
rows prove it.

### The source file names, which the date depends on

63 files, in four shapes:

* `BSEG_dd-mm-yy` — most of them, e.g. `BSEG_08-10-26`
* `BSEG_dd-mm-2026` and `BSEG_dd-mm-2026.xls` — four-digit year
* `BSEG 10-12-25` — a space instead of an underscore, still matched
* **`BSEG_2025`, `BSEG_2026`, `BSEG_Apr_2026` — no date at all**

Those last three get a NULL `dt`, so `WHERE d.dt = m.max_dt` excludes them —
correctly, since an undated file cannot be "the newest extract". Worth knowing
because it means **three files totalling 76,585 rows are invisible to this
report by design.** If any of them is meant to be loaded it needs a dated name.

### Seven cost centres are not in the mapping

Found on 7-series postings in the current extract, carrying 2,971,645 between
them — 0.08% of the total, and named on the screen rather than absorbed:

| Cost centre | Postings | Amount |
|---|---|---|
| 72019 | 1 | 2,209,210 |
| 72003 | 12 | 462,815 |
| 72004 | 1 | 104,439 |
| 72028 | 3 | 87,600 |
| 72027 | 6 | 48,905 |
| 72005 | 1 | 35,482 |
| 76007 | 2 | 23,194 |

The `72xxx` block is almost certainly HFCB-Properties (72001, 72002, 72006,
72007, 72009, 72010, 72012, 72016 and 72020 all are) and `76007` almost
certainly HFCB-Group. **They have not been added**, because "almost certainly"
is not a mapping and each needs its own name — which project is 72019? One row
each on Administration → Cost Analysis → Cost centres settles it, and until
then the screen says what they carry.

## Still open

1. **`cost_department_2` is only used to mark branches.** The notebook carries
   it for a second reporting level that nothing here reads yet.
2. **The notebook also produces a month-on-month view** with conditional
   formatting. The same figures are on the screen; the colouring is not.
3. **Trino is intermittent from a laptop** — a `DESCRIBE` and a 44,769-row pull
   both got through, and two attempts in between timed out on TCP connect. The
   host reaches it reliably, which is where the scheduled load runs.
