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
(the last three optional). The UI is **Administration → Branch Dept. Costs**.

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

`drawdown_daily` has no branch column — only `unit_code`. `core/branch_codes.py`
resolves a branch name to its set of codes from the live DMC roster
(`brn_code` ↔ `staff_branch`) plus a static fallback transcribed from
`BRANCH_CODE_CASE` in the CEO dashboard. If a branch resolves to no code the
endpoints return **nothing**, never the whole bank, and the page shows an amber
notice. The fix is to give that branch at least one staff row carrying its
`brn_code`.
