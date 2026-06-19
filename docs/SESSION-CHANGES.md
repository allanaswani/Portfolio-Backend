# HF Group Backend — Revamp Work Log

_Last updated: 2026-06-08_

This document records everything implemented during the new-backend revamp:
the migration-safe role system, the admin user-management feature (replacing the
Django admin UI), the frontend↔backend endpoint gap analysis, and the first
increment of the `staff_management` port. It also explains **how to run and view
the new Users screen locally**.

---

## 1. How to run & view it locally

### Prerequisites
- PostgreSQL 18 running locally with the `hf_group_app` database (already created
  and migrated in a previous session).
- The Python interpreter that has Django 5.1.7 installed. On this machine that is
  the old project's venv, which resolves as plain `python`:
  `C:\Users\washingtone.amolo\Desktop\HF_GROUP\hf_group_project-master\.venv\Scripts\python.exe`

### Start the backend (port 9000)
```powershell
cd C:\Users\washingtone.amolo\Desktop\HF_GROUP\hf_group_backend
python manage.py seed_roles        # ensures the 14 roles exist (idempotent)
python manage.py runserver 9000
```
The frontend's API base URL points at `:9000`, so the backend **must** run on
port 9000 for local viewing.

### Start the frontend (port 3000)
```powershell
cd C:\Users\washingtone.amolo\Desktop\HF_GROUP\portfolio-management-frontend
npm run dev
```
Then open **http://localhost:3000**.

> `lib/api.ts` now auto-detects `localhost`/`127.0.0.1` and talks to
> `http://127.0.0.1:9000/`. To point elsewhere, set `NEXT_PUBLIC_API_URL` in
> `.env.local`. CORS is open in the backend's development settings.

### Log in and open the Users screen
1. Log in with the superuser: **`admin` / `Admin@2024`**.
2. The app requests an OTP on login. In development, email uses the **console
   backend**, so the OTP is printed in the **backend terminal**. Enter it on the
   verify-OTP screen.
3. In the sidebar, open **Administration → Users & Roles**
   (route `/management/users`). The superuser sees all modules.

From there you can create users, assign roles, reset passwords, and
activate/deactivate — no Django admin needed.

---

## 2. Migration-safe roles (no user/role loss)

**Problem found:** roles in this system are Django **Groups** (`ceo`, `exco`,
`portfolio_mgt`, `tl_portfolio`, `branch_portfolio`, `collection_mgt`,
`tl_collection`, `rights_issue`, `TLrights_issue`, `hfdi_admin`). The new
backend had replaced these with a different model (`admin/manager/officer/
customer`) derived from `is_staff`/`is_superuser`, so a migrated `ceo`/`exco`
user (who is neither) was silently downgraded to **officer**.

**Fixes:**
- **`core/roles.py`** (new) — single source of truth: 10 legacy roles + 4
  new-feature roles (`staff_mgt`, `exco_initiatives`, `exco_initiatives_admin`,
  `hfdi_officer`) = **14 roles**, plus a documented `ROLE_TO_TIER` mapping and
  `tier_for_groups()` helper.
- **`core/permissions.py`** — `get_user_role()` now derives the tier from the
  user's legacy groups (via `tier_for_groups`) instead of downgrading them.
  Added legacy group-name permission classes (`InGroup(...)`, `CeoPermissions`,
  `ExcoPermissions`, etc.) mirroring the old `request.user.groups.filter(name=…)`
  gates. Both systems run side by side; legacy groups are never discarded.
- **`apps/portfolio/serializers.py`** — `UserSerializer` (served by
  `userprofile/`) now returns `groups`, `is_superuser`, and flattened
  `sales_code`/`branch`/`segment`. The frontend's `hasPermission()` reads exactly
  `user.groups` + `user.is_superuser`; without this, every migrated user lost all
  role-based navigation even though their roles existed in the DB.

## 3. User/role migration commands

- **`apps/authentication/management/commands/seed_roles.py`** — idempotently
  creates all 14 roles in the `default` DB.
- **`apps/authentication/management/commands/migrate_legacy_auth.py`** — copies
  `auth_user`, `auth_group`, `auth_user_groups`, and `portfolio_profile` from the
  legacy `datawarehouse` DB into `default`. Properties:
  - Idempotent (matches on username / group name via `update_or_create`).
  - Copies password hashes **verbatim** (no re-hash — users keep their passwords).
  - **Signal-safe** — mutes the `apps.portfolio` Profile `post_save` handler that
    would otherwise email every migrated user a hardcoded password.
  - `--dry-run` reports the plan; `--source` / `--target` configurable.

> **Source data lives on production.** Locally the `datawarehouse`/`datawarehouse1`
> databases have **0 users / 0 groups**; only `hf_group_app` has data. To run the
> real migration, point `DW_*` in `.env` at the production datawarehouse, then:
> `python manage.py seed_roles` → `migrate_legacy_auth --dry-run` → `migrate_legacy_auth`.

## 4. Admin user management API (replaces Django admin)

In `apps/authentication` (mounted at `auth/`), gated by `IsAdministrator`
(staff **or** superuser):

| Method | Endpoint | Purpose |
|---|---|---|
| GET / POST | `auth/users/` | List (`?search=`, `?role=`, `?is_active=`) / create |
| GET / PATCH / DELETE | `auth/users/<id>/` | Retrieve / update / **soft-delete** (deactivates) |
| POST | `auth/users/<id>/set-password/` | Reset password (returns it) |
| GET | `auth/roles/` | All 14 roles (name, description, tier, member_count) |

- Create accepts `groups` (role names), `is_staff`, `is_active`, profile fields.
- `password` optional — if omitted, a strong one is generated and returned once
  as `generated_password`.
- User creation mutes the welcome-email signal (`core/signals.py`
  `muted_profile_signals`, shared with the migration command).

Serializers: `apps/authentication/serializers.py`.

## 5. Frontend Users screen

- **`app/(dashboard)/management/users/page.tsx`** — route `/management/users`,
  added to the Administration nav (`lib/roleNavConfig.tsx`, under `staff_mgt`).
  DataTable with create/edit modal, role multi-select checklist (live from
  `auth/roles/`), reset-password, activate/deactivate, and a one-time credentials
  modal showing the generated password.
- **`hooks/useUsers.ts`** — react-query hooks against `auth/users/` + `auth/roles/`.
- **`lib/api.ts`** — added local/env API base-URL resolution (see section 1).

## 6. Frontend → Backend endpoint gap

See **`docs/frontend_endpoint_gap.md`** (generated). The frontend's
`hooks/useAnalytics.ts` calls **259** endpoints; **153 (59%)** are satisfied,
**106** are missing.

**Why missing:** every missing endpoint **exists in the old backend**
(`hf_group_project-master`). The new backend is a *partial re-port* of the old
monolith — `portfolio`/`ceo`/`branch_portfolio` were ported nearly fully, but
`staff_management`, `hfdi`, and `collections_team_leaders` were only partially
ported. So this is **porting work, not net-new design**.

Missing by module: `hfdi` 41, `staff_management` 44 → **37 after this session**,
`collections_tl` 7, `hf_collections` 6, `tl_portfolio` 4, `ceo` 2, `portfolio` 2.

## 7. staff_management port — increment 1 (done)

Added endpoints for models that already exist in the new app (no schema risk):

- `staff_management/employees/` (alias to the existing all-staff list)
- `staff_management/roles/<id>/` (retrieve/update/delete) + `roles/upload-csv/`
- `staff_management/kpis/<id>/` + `kpis/upload-csv/`
- `staff_management/role-kpi-mappings/<id>/` + `role-kpi-mappings/upload-csv/`

Plus a reusable **`BaseCsvUploadView`** (bulk-create from a CSV `file` field;
falls back to per-row import and reports failed rows). Tested in
`apps/staff_management/tests.py`.

### staff_management — remaining (increment 2, not yet done)
These need **new models ported from the old backend** (`staff_management/
models.py`, 1,249 lines), each with the exact `db_table`/`managed` flag:

| Frontend resource | Old model → table | managed |
|---|---|---|
| `branch_employee_dmc_data` | BranchEmployeeDmcData → `branch_employee_dmc_data` | True |
| `branch_final_employee_dmc_data` | BranchFinalEmployeeDmcData → `branch_final_employee_dmc_data` | True |
| `drawdown-daily`, `drawdowns/upload-csv` | DrawdownDaily/Drawdown → `drawdown_daily`/`drawdown` | mixed |
| `insurance-policy` (+upload) | InsurancePolicy → `insurance_policies` | True |
| `trade-finance` (+upload) | TradeFinanceData → `trade_finance_data` | True |
| `leave-records` (+upload) | LeaveRecord → `staff_leave_records` | True |
| `products` (+upload) | Product → `product_mapping` | False |
| `merchant-bank-tills-manual` (+upload) | MerchantBankTillManualData → `weighted_sales_seller_bank_till_data_dump_manual` | False |
| `weighted-sales-daily-accounts` (+upload) | DailySalesAccountsWithCto → `daily_sales_accounts_with_cto` | False |
| `weighted-sales-dormancy-converted` (+upload) | DailyDormancyConvertedAccount → `daily_dormancy_converted_accounts` | False |
| `retail-allocated-portfolio` (+upload) | RetailAllocatedPortfolio → `retail_allocated_portfolio` (in portfolio app) | False |
| `role-history` (+upload) | EmployeeRoleHistory → `employee_role_history` | True |
| `rm-kpi-base-summary/<id>`, `/refresh`, `/upload-csv` | RmKPIBaseSummary → `rm_kpi_base_summary` | True |
| `employee-summary`, `sales-people/upload-csv` | aggregate / staff views | — |

> Note: the new backend already reimplemented the **scorecard** models
> (`scorecard_roles`, `scorecard_kpis`, `scorecard_role_kpi_mappings`) differently
> from the old (`orgnization_roles`, `kpi_definitions`, `role_kpi_mappings`). The
> `roles/`, `kpis/`, `role-kpi-mappings/` endpoints therefore operate on the NEW
> scorecard models, not the old tables.

## 8. Tests & verification

- `apps.authentication` — **16 tests pass** (role mapping, serializer contract,
  seed_roles, migrate_legacy_auth, admin user management).
- `apps.staff_management` — **5 tests pass** (role CRUD, CSV upload incl. bad-row
  reporting, auth required).
- `python manage.py check` — clean.
- Frontend `npx tsc --noEmit` — **0 errors** project-wide.

## 9. File inventory (this session)

**Backend created:** `core/roles.py`, `core/signals.py`,
`apps/authentication/serializers.py`,
`apps/authentication/management/commands/seed_roles.py`,
`apps/authentication/management/commands/migrate_legacy_auth.py`,
`apps/authentication/tests.py`, `apps/staff_management/tests.py`,
`docs/frontend_endpoint_gap.md`, `docs/SESSION-CHANGES.md`.

**Backend modified:** `core/permissions.py`, `apps/portfolio/serializers.py`,
`apps/authentication/views.py`, `apps/authentication/urls.py`,
`apps/staff_management/views.py`, `apps/staff_management/urls.py`.

**Frontend created:** `hooks/useUsers.ts`,
`app/(dashboard)/management/users/page.tsx`.

**Frontend modified:** `lib/roleNavConfig.tsx`, `lib/api.ts`.
