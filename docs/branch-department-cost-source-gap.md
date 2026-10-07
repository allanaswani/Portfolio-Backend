# Per-branch departmental cost: where the number comes from

## The finding

**There is no cost data anywhere in the data warehouse.** This was checked
across every model in the repo before the branch Employees & Costs page was
built:

* no `salary`, `staff_cost`, `payroll`, `cost_centre` or `budget` column exists
  on any model in `apps/`;
* the only `expense` column in the schema is `transaction_diary.expense_amount`,
  which is **interest expense per transaction** — not an operating cost, and not
  attributable to a department;
* the "Operating Expenses" and "Costs per Department" slides on the CEO deck are
  **hard-coded constants in the frontend**
  (`app/(dashboard)/gceo/page.tsx`, `costsExpenseLines` and `costsDeptData`).
  They are annual/monthly figures for 18 departments (ICT, RETAIL, FINANCE, HR,
  …) and **carry no branch dimension at all**.

So a branch manager's "cost per department at my branch" cannot be derived from
anything that exists. Apportioning the organisation-wide figure by branch
headcount would produce a number nobody measured and Finance could not defend.

## What was built instead

`staff_management.BranchDepartmentCost` (table `branch_department_cost`,
migration `0012_branchdepartmentcost`) is a capture point:

| column | meaning |
| --- | --- |
| `branch` | branch NAME, matched suffix-insensitively on read ("HEAD OFFICE" == "HEAD OFFICE BRANCH") |
| `department` | canonical name from `apps/gceo_dashboard/departments.py` |
| `year`, `month` | the period the figure covers |
| `amount` | total cost booked to that department at that branch |
| `staff_cost`, `other_cost` | optional split of `amount` |

Unique on `(branch, department, year, month)` — re-sending a month **corrects**
it rather than stacking a second row that would double the department's cost.

Endpoints (`/staff_management/`):

* `branch-department-costs/` — list + upsert-on-POST
* `branch-department-costs/<pk>/` — retrieve / update / delete
* `branch-department-costs/upload-csv/` — bulk load, same upsert key

CSV columns: `branch,department,year,month,amount,staff_cost,other_cost,notes`
(the last three optional). The UI is **Administration → Costs & Expense
Mapping**, first tab.

## The companion table: which expense line a GL account belongs to

`staff_management.OperatingExpenseMapping` (table `operating_expense_mapping`,
migrations `0022` and `0023`) is the second tab on the same screen, and it
answers the other half of the question. `BranchDepartmentCost` says how much a
department spent; this says **which expense line a general-ledger account rolls
up to**.

It came from Finance's `Operating_expenses_mapping.xlsx`: 249 GL accounts, each
tagged with an expense type (24 of them — "Staff costs", "ICT Expense",
"Motor vehicle maintenance", …), the operating-expense line Finance names it
by, and an outflow type.

| column | meaning |
| --- | --- |
| `gl` | the account code, unique, stored as **text** — it is an identifier, never arithmetic |
| `expense_type` | the roll-up line, e.g. `Staff costs` |
| `operating_expense` | the expense line as Finance names it, e.g. `Software` |
| `outflow_type` | `Controllable` (146), `Installed` (71, an already-committed fixed outflow) or blank (32) |
| `actual_gl_name` | the GL's own name where it differs from the expense line (blank for 22) |

Same reasoning as the cost table: **nothing in the warehouse carries this
classification.** GL postings have account codes, the expense slides have
category names, and this sheet was the only thing joining the two — while it
lived in one person's Downloads folder, no report could use it.

Endpoints (`/staff_management/`):

* `operating-expense-mappings/` — list + upsert-on-POST (key: `gl`)
* `operating-expense-mappings/<pk>/` — retrieve / update / delete
* `operating-expense-mappings/upload-csv/` — bulk load, **takes the .xlsx**

Required columns: `gl,expense_type,operating_expense`. `outflow_type` and
`actual_gl_name` are optional because they are blank for some accounts in
Finance's own sheet.

Three decisions worth knowing:

* **`gl` is unique but is not the primary key.** A mistyped account has to be
  correctable in place; if `gl` were the key, an edit would mean delete and
  re-add, losing the row's history.
* **A re-upload is a correction, not a replacement.** Accounts the new sheet
  does not mention are **left alone**. Treating an absent row as a deletion
  would let somebody's filtered export silently empty the mapping.
* **`outflow_type` is not a choices field.** Finance owns that vocabulary, and
  a new word in next year's sheet has to upload rather than fail validation.
  The form offers the two observed values as suggestions, not as a constraint.

Each edit keeps its before-image (`simple_history`), because re-tagging one GL
moves money between expense lines in every report that reads the table.

### Excel uploads, not just CSV

`core/csv_upload.py` now accepts `.xlsx` / `.xlsm` as well as `.csv`, for
**every** uploader built on `AmendingCsvUploadView`. The upload modal had always
advertised `.csv, .xlsx, .xls` and sent whatever was picked, while the backend
answered `File must be a CSV` — so an Excel upload failed at the last step,
after the on-screen validation had passed it.

Three things the workbook reader has to get right, all of which have their own
test:

* a 9-digit GL stored as a number comes back as `170150001.0`, which would be a
  different account from `170150001`; the float tail is dropped;
* a date cell comes back as `datetime(2026, 10, 7, 0, 0)`, whose `str()` is
  `"2026-10-07 00:00:00"` — a format no parser in `parse_date` matches, so
  midnight datetimes are rendered as plain ISO dates;
* a worksheet's reported extent runs past its last record (deleting rows in
  Excel leaves the dimension behind), so entirely blank rows are dropped
  instead of arriving as a few hundred blank failures in the results ZIP.

The legacy binary `.xls` is **not** readable by openpyxl, so it is named in the
error (`open it and Save As .xlsx`) rather than accepted and then failing deep
in the parser.

## What a branch manager sees before Finance loads a month

`/branch_portfolio/staff/departments/` returns real headcount with
`has_cost_data: false` and `null` in every cost column, and the page renders a
notice saying so. **No figure is estimated.** That is deliberate: a blank cell
is honest, an apportioned one is not.

## Headcount, by contrast, is real

Headcount is derived, not captured. It joins two existing sources on the PF
number (`apps/branch_portfolio/staff_queries.py`):

* branch posting — `branch_final_employee_dmc_data` / `branch_employee_dmc_data`
  (`staff_branch`, `brn_code`), ~808 customer-facing staff;
* department — `employee_table` (`department`, `division`, `grade`), ~1,271 HR
  rows, which has **no branch column**, joined on
  `employee_table.staff_id = staff_pf_number`.

The DMC tables hold more than one row per person (one per role/sales code), so
the query dedupes with `DISTINCT ON` before counting — without that, headcount
inflates by the number of roles each person holds. Every returned row carries
`department_source` (`overlay` / `hr_roster` / `dmc_unit`) so it is always
visible where a department name came from.

## If a branch shows nothing

`drawdown_daily` has no branch column — only `unit_code`. The branches do carry
codes, but they live in several tables, so `core/branch_codes.py` combines them:

1. **`drawdown`** — the ETL-built sibling of `drawdown_daily`, which carries
   `unit_code` and `branch` side by side. Primary source: it is the warehouse's
   own pairing for exactly the data being scoped.
2. the DMC staff rosters (`brn_code` ↔ `staff_branch`).
3. the static `BRANCH_CODE_CASE` list from the CEO dashboard, for codes no live
   table knows.

`hf_customer.branch_code` is deliberately excluded — it is not 1:1 with
`hf_customer.branch`; on production one branch's codes matched 32 branches and
99.6% of the book (`tests_branch_scoping.py`).

**Each code is assigned to exactly one branch**, by majority vote across live
rows, so a handful of mislabelled rows can never hand one branch another
branch's book. If a branch still resolves to no code the endpoints return
**nothing**, never the whole bank, and the page shows an amber notice.

Inspect the live mapping instead of guessing:

```bash
docker exec hf-backend python manage.py branch_codes              # the whole map
docker exec hf-backend python manage.py branch_codes --branch "MOMBASA BRANCH"
docker exec hf-backend python manage.py branch_codes --conflicts  # codes two branches claim
docker exec hf-backend python manage.py branch_codes --unmapped   # unit_codes on no branch page
```

`--unmapped` is the one to run after deploying: it lists any `unit_code` in
`drawdown_daily` that resolves to no branch, with its row count and value, so
drawdowns that would be invisible to every branch page are visible to you.
