# Property Holdings — per-branch scoping is blocked upstream (ETL fix needed)

**Status:** the backend + UI ship an **org-wide** "Property Holdings / amounts sold" view
(`branch_portfolio: property_holdings/{summary,by_project,list}/`, page
`/bm-portfolio/property-holdings`). It is **not** scoped to a branch yet. This note is
the fix the data team needs to make so it *can* be.

## What the feature does today

Reads two CRM ERP warehouse tables (loaded by
`datawarehouse-etls/hfcb_properties_reports/extraction_from_crm_code.py`):

| Table | Gives us |
|---|---|
| `hfdi_crm_project_clients_data` | one row per client-held unit — `client_name`, `project_name`, `unit_name`, and (empty) `client_idno` / `client_phone` / `client_email` |
| `hfdi_crm_project_units_data` | one row per unit — `hs_name`, **`unit_value`** (the price / "amount sold"), `hs_type` |

The join `clients(project_name, unit_name) → units(project_name, hs_name)` attaches the
sale amount. Verified live: **6,431 holdings, 5,882 priced** (91% coverage). Amounts are
real Decimals.

## Why it can't be per-branch

The requested design was: *show each branch the property holdings of ITS bank customers*.
The only way to tie a CRM property client to a bank branch is to match the client to the
bank customer book (`hf_customer`, which has `id_no`, `mobile_tel`, and `branch`).

**Every candidate join key on the CRM clients table is empty.** Verified live:

```
SELECT count(*), count(nullif(btrim(client_idno),'')),
       count(nullif(btrim(client_phone),'')),
       count(nullif(btrim(client_email),''))
FROM hfdi_crm_project_clients_data;
-- (6431, 0, 0, 0)
```

`client_idno` / `client_phone` / `client_email` are `TO_BASE64(AES_DECRYPT(...))` columns
in the extraction SQL (`scripts/hfcb_properties_scripts/erp_scripts/test_scripts/project_clients_data.sql`),
but they land **blank** in the warehouse — the decrypt/encode is producing empty strings
(likely a wrong/absent `@encryption_key`, or the source columns are null). With no
identifier, holdings cannot be attributed to a branch. (The only branch-linkable property
table, `hfdi_customers_hfc_mortgages` via `bank_rm`, is **75 rows with an 8% RM-name
match** — too thin to use.)

This is the same class of upstream gap as `loan_daily_balance_movement` being empty — a
data-pipeline problem, **not** a backend bug.

## The fix (data team, in `extraction_from_crm_code.py`)

Populate a real customer identifier on `hfdi_crm_project_clients_data` — **national ID is
best** (matches `hf_customer.id_no`), phone is an acceptable fallback (matches
`hf_customer.mobile_tel`, format `2547XXXXXXXX`).

1. Confirm `@encryption_key` (session var `SET @encryption_key = ...`) is set to the SAME
   key the CRM DB encrypted `client_idno` / `client_phone` with. A wrong/missing key makes
   `AES_DECRYPT` return NULL → `TO_BASE64(NULL)` → blank. This is the most likely cause.
2. Store the **plaintext** national ID / phone (not base64) so no decode is needed on read.
   If base64 must stay, the backend can decode with
   `convert_from(decode(client_idno,'base64'),'UTF8')`.
3. Backfill the table once, then it stays fresh on the normal schedule.

## The backend change once IDs land (small)

In `apps/branch_portfolio/views.py`, the three `BranchPropertyHoldings*` views share
`_PROPERTY_HOLDINGS_FROM`. Add a join + branch filter:

```sql
JOIN hf_customer h ON btrim(h.id_no) = btrim(cl.client_idno)
WHERE h.branch = %s        -- from _branch_filter(profile) via the existing auth guard
```

and pass `_branch_filter(profile)` (already used by every other branch view — BM sees only
their branch, EXCO/CEO can drill any). Then drop the org-wide amber notice in the page. No
frontend restructure needed; the same endpoints just start returning branch-scoped rows.
