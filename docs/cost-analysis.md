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

## Still open

1. **Trino was not reachable from the development machine** when this was
   built, so `sap_cost_data`'s column *types* were not re-verified against the
   live table. The column *names* come from Finance's own query, which runs
   against it. The first `load_sap_costs --dry-run` on the host confirms it.
2. **The `dt` the query derives comes from the source file name**, as
   `dd-mm-yyyy` or `dd-mm-yy`. A file named any other way lands with no
   snapshot date and is reported rather than guessed at.
3. **`cost_department_2` is only used to mark branches.** The notebook carries
   it for a second reporting level that nothing here reads yet.
4. **The notebook also produces a month-on-month view** with conditional
   formatting. The same figures are on the screen; the MoM colouring is not.
