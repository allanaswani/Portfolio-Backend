# Employee master upload (`employee-data/upload-csv/`)

Administration → Staff Management → **All Employees** → *Upload Employee Data*.

`POST /staff_management/employee-data/upload-csv/` — multipart, field `file`.
Gated on the `staff_mgt` group (or superuser), the gate the old backend's
`DataManagementPermissions` used. This is the path the old backend served with
`staff_management.views.UploadAndProcessEmployeeData`.

## Where the contract comes from

The old view saved the upload into `../etls/temp_files` and ran
`initiate_update_employee_information.sh`, a wrapper around the data team's
`cleaning_and_updating_staff_information.py` (`datawarehouse-etls`). **That
script is the contract**, and `apps/staff_management/employee_master_views.py` is
a port of it.

The shell-out could not come across: this backend runs in a container with
neither the `etls` tree nor the host's python3.6, so a verbatim port of the
*view* would answer *"Failed to execute processing script"* on every upload. The
queue-a-request-file pattern in `core/script_trigger.py` is for the report
scripts, which email their own output; this button has to report how many rows
landed, so it does the load itself.

## The file HR uploads

One `.xlsx` workbook, up to three sheets, all sharing the same header row. A lone
`.csv` is read as a single `full_list` sheet.

| Sheet | What it does |
|---|---|
| `full_list` | The whole company. **Inserts only** people not already in `employee_table`. Anyone already on the roster is left untouched, which is what makes re-uploading last month's file safe. |
| `exits` | Marks leavers. |
| `promotions` | Records role moves. |

`exits` and `promotions` are merged (the flags take the max, other columns the
first non-null) and UPDATE **ten columns and no others**:

```
exit, staff_exit_date, promotion, promotion_date,
service_code, department, unit, org_unit, grade, job_title
```

So a promotions file cannot overwrite an email or a date of birth. **Nobody is
ever deleted**, on any sheet.

## Columns

`GET /staff_management/employee-data/template/` returns the authoritative list.
The frontend keeps a copy in `CSVUploadModal` `TEMPLATES.employee_master_data`
for its offline header check; `tests_employee_master.py` pins every header to a
real `EmployeeTable` field.

```
staffid, name, idno, email, date of birth, age, gender, date of employement,
service code, service yrs, division, department, unit, org unit, grade,
job title, staff_exit_date, effective date
```

These are **HR's own headers, not the database's** — `date of employement` is
misspelled at source and stays that way, or the column stops matching. `staffid`
and `name` are the only ones that must carry a value; a row with no `name` is a
spacer line and is dropped. A missing optional column loads blank rather than
aborting the file (the script would `KeyError` and abandon the whole upload).

## Derived, not read

Ported verbatim from the script, so a file that loaded before loads the same way:

| Column | Rule |
|---|---|
| `age` | `(today − date of birth) // 365` — the sheet's own `age` is ignored |
| `service_years` | `(today − date of employement) // 365` |
| `exit` | 1 when `staff_exit_date` is present |
| `promotion` | 1 when `effective date` is present — and forced to 0 on a `full_list` insert |
| `new` | 1 when the employment date falls in the current year |
| `grade` | `O2→02, UNC→01, O3→03, Tempor→01, O1→01`, then padded to two digits |
| `division` | forced to `HFBI` / `HFDI` when that is the department, then renamed to its HFCB name: `HFBI→HFCB Insurance`, `HFDI→HFCB Properties`, `HFC→HFCB Limited`, `HF Group→HFCB Group` |
| `hfdi_erp_id` | 0 |

## hfdi_employee_data

The same workbook maintains it, as the script does: rows in the **`HFCB Properties`
division** (the renamed HFDI) that are not yet in `hfdi_employee_data` are
inserted (name proper-cased, `sales_code` = the PF number, `input_user` =
"Strategy Employee Update", `start_date` = 1 January for anyone hired before this
year else the 1st of the month *after* they joined — a part month is not a sales
month), and rows on the `exits` sheet are marked `active = 0` / `staff_exit = 1`.

The selection is on the renamed division, so `clean_staff_list` has to apply
`DIVISION_RENAME` before `_sync_hfdi` looks — otherwise nothing ever matches and
the sync silently reports zero.

## Response

```json
{"sheets": {"used": ["full_list"], "ignored": []},
 "inserted": 0, "already_present": 0, "updated": 0, "not_found": 0,
 "hfdi": {"inserted": 0, "exits_updated": 0},
 "errors": [], "error_count": 0}
```

## The three columns this file does not carry

`standard_department`, `current_role` and `previous_role` do not exist in
`employee_table` — they are maintained by hand in the `employee_roster_overlay`
companion, through the page's second button and the unchanged
`/ceo/employees/overlay/upload/` endpoint.

## Two production quirks handled here

* **`employee_table.id` may have no sequence or identity default.** Postgres then
  substitutes NULL on insert and the write 500s while reads keep working — the
  shape of the hfdi target bug (`docs/hfdi-targets-id-sequence-fix.sql`). The view
  checks `information_schema` once per upload and supplies the id itself when the
  column has no default.
* **Reads and writes are pinned to one alias.** The router reads unmanaged models
  from `datawarehouse` and writes them to `default`. On production both point at
  the same physical database, but "insert the people who are not already there"
  reads and writes in a single pass, which is only correct if both halves see the
  same table — so `employee_db()` pins both.
