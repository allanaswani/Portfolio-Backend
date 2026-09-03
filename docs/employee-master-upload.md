# Employee master upload (`employee-data/upload-csv/`)

Administration → Staff Management → **All Employees** → *Upload Employee Data (CSV)*.

`POST /staff_management/employee-data/upload-csv/` — multipart, field `file`.
Gated on the `staff_mgt` group (or superuser), the same gate the old backend's
`DataManagementPermissions` used.

This is the path the old backend served with
`staff_management.views.UploadAndProcessEmployeeData`; the button now posts here
instead of to the roles/departments-only overlay endpoint.

## What changed from the old view, and why

The old view saved the file into `../etls/temp_files` and ran
`bash ../etls/initiate_update_employee_information.sh <file>`, returning the
script's stdout. That worked because the old backend ran on the ETL host.

This backend runs in a container with neither the `etls` tree nor the data
team's python3.6, so a verbatim port would answer *"Failed to execute processing
script"* on every upload. The script's job was to load the file into
`employee_table`; the port does that load itself, against the same database.

(The queue-a-request-file pattern in `core/script_trigger.py` is for the report
scripts, which email their own output. It is the wrong shape here — the button
has to report how many rows landed.)

## Semantics

| Rule | Effect |
|---|---|
| Upsert on `staff_id` | A re-upload updates the same person; never a duplicate. |
| Blank cell | Leaves the stored value alone. |
| Column absent from the CSV | Never written. |
| Person absent from the CSV | Never touched, never deleted. |
| Row with no `staff_id` | Skipped and counted, not imported. |
| Bad row | Reported in `errors[]`; the rest of the file still imports. |

`staff_id` is canonicalised (`4022`, `4022.0`, `4022.00000` are one person), and
headers are matched tolerantly — case, spacing, a BOM, and HR's own spellings
(`PF Number`, `Full Name`, `Date Of Employment`, `Exit Date`, …) all resolve.

Response:

```json
{"created": 0, "updated": 0, "unchanged": 0, "skipped": 0,
 "overlay_created": 0, "overlay_updated": 0, "errors": [], "error_count": 0}
```

## Columns

`GET /staff_management/employee-data/template/` returns the authoritative list.
The frontend keeps a copy in `CSVUploadModal` `TEMPLATES.employee_master_data`
for its offline header check; `tests_employee_master.py` pins the backend list
against `EmployeeTable`'s own fields so a new warehouse column cannot quietly
fall out of the template.

```
staff_id, name, national_id, email, gender, service_code, division, department,
unit, org_unit, grade, job_title, date_of_birth, age, date_of_employment,
service_years, exit, staff_exit_date, promotion, promotion_date, new,
hfdi_erp_id, standard_department, current_role, previous_role
```

The last three do **not** exist in `employee_table` — they are the hand-maintained
columns and go to the managed `employee_roster_overlay` companion, so one file
maintains the whole page. The overlay endpoints (`/ceo/employees/overlay/` and
`/ceo/employees/overlay/upload/`) are unchanged and still work on their own.

## Two production quirks handled in the view

* **`employee_table.id` may have no sequence or identity default.** Postgres then
  substitutes NULL on insert and the write 500s while reads keep working — the
  shape of the hfdi target bug (`docs/hfdi-targets-id-sequence-fix.sql`). The view
  checks `information_schema` once per upload and supplies the id itself when the
  column has no default.
* **Reads and writes are pinned to one alias.** The router reads unmanaged models
  from `datawarehouse` and writes them to `default`. On production both point at
  the same physical database, but a read-then-write upsert split across two
  aliases is only accidentally correct, so `employee_db()` pins both.
