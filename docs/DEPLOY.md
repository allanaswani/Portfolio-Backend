# Deployment Runbook — hf_group_backend (shared prod DB, side-by-side pilot)

_Last updated: 2026-07-01._

**Scenario this runbook is written for** (confirmed with the team):
- The new backend will run against the **same production database** the current
  (old) system uses — **not** a fresh DB.
- Rollout is **side-by-side / pilot**: the new backend runs in parallel; only a
  subset of users/routes (recommended: the **Mortgages module**) move over first.
  The current frontend + old backend keep serving everyone else.

> ⚠️ **The golden rule:** on a shared prod DB you do **NOT** run a plain
> `python manage.py migrate`. It will fail on "relation already exists" because
> 46 of the new backend's tables reuse names that already exist in prod. Follow
> the adoption procedure in §3. **Always take a backup first (§2).**

---

## FULL-REPLACE CUTOVER (same-port, all users) — chosen strategy (2026-07-02)

The decision is to **retire the old backend and put all users on the new one**,
on the **same server port the old backend already uses**. Read this section first;
§§1–9 below are the detailed steps it references.

### A. The port is a non-issue — no Security ticket needed
A full replace runs **one** backend at a time. You **stop** the old service and
**start** the new one on the **exact same port** (the one already open in the
firewall). You are not opening a second port, so **there is nothing to request
from Security**. Rollback is symmetric: stop new, start old (§F).

### B. You do NOT lose users or their data — here's why
The new backend connects to the **same production database** the old one uses, so:
- **Every existing row stays put** — `auth_user`, `auth_group`, and all business
  tables are the *same* tables. The migrations only ever **CREATE new tables**;
  there is **not a single** drop/rename-column/delete op in the whole set (verified).
- **Users keep their passwords.** Django stores PBKDF2 hashes; the new backend
  reads the same `auth_user` rows, so existing credentials just work. The only
  visible effect of the new `SECRET_KEY` (§5) is that everyone logs in **once**
  after cutover (old JWTs stop validating). Harmless.
- **Nothing to "migrate" for users** when it's the *same* DB — they are already
  there. (The `migrate_legacy_auth` command is only for the *different-DB* case;
  not this one.)

> The historical `employee_monthly_performance` rows are also preserved — the
> redesigned scorecard now uses a separate `employee_monthly_performance_v2` table
> (see §0 landmine, resolved), so the legacy table is left fully intact.

### C. The migration for a full replace (rehearse on a clone — §3.1)
A plain `migrate` fails (§ golden rule). And `--fake-initial` alone is **not
enough** here because some apps are **mixed** — their initial migration creates
*both* tables that already exist in prod *and* brand-new ones (e.g.
`staff_management`: existing `employee_monthly_performance` + new `scorecard_*`,
`employee_monthly_performance_v2`). Django won't auto-fake a mixed initial, so it
tries to `CREATE` the existing table and errors "relation already exists".

Procedure (run on a **restored clone** first, §3.1, then repeat on real prod):
1. **Backup** (§2) — mandatory rollback point.
2. `python manage.py migrate --fake-initial` — adopts apps whose initial tables
   **all** already exist, and fully creates apps that are **all-new** (mortgages,
   client_briefs, agent, etc.).
3. For each app that errors **"relation already exists"** (the mixed apps, e.g.
   `staff_management`):
   - `python manage.py migrate <app> 0001 --fake` (adopt into state, **no DDL**).
   - Create only the **genuinely-new** tables from that app: run
     `python manage.py sqlmigrate <app> 0001` and execute **only** the
     `CREATE TABLE` statements for tables that don't yet exist — for
     `staff_management` those are `scorecard_roles`, `scorecard_kpis`,
     `scorecard_role_kpi_mappings`, `scorecard_performance_actuals`, and
     `employee_monthly_performance_v2`. **Do not** run the CREATE for tables that
     already exist.
   - `python manage.py migrate <app> --fake` for later migrations that only touch
     already-adopted tables (incl. `0006` — the v2 rename — since you created v2
     directly). Run non-fake for any later migration that adds *new* columns/tables.
   - **Write down exactly which statements you ran** so real-prod matches the clone.
4. `python manage.py showmigrations` → everything `[X]`.
5. **Spot-check existing tables' row counts are unchanged** vs a pre-migration
   snapshot. `employee_monthly_performance` (legacy) untouched; `_v2` exists & empty.
6. **Re-seed scorecard config** (the new `scorecard_*` tables are empty): load
   roles / KPIs / mappings, then run the scorecard recompute to fill
   `employee_monthly_performance_v2`.

### D. Creating the Mortgages accounts (including the admin)
The four role groups — `mortgage_officer`, `mortgage_manager`, `mortgage_finance`,
`mortgage_admin` — are **auto-created** by migration `mortgages.0002_seed_mortgage_groups`
(idempotent). Frontend nav lights up purely by **group membership**. To make the
accounts:
1. **Bootstrap a system admin** (needed to call the admin API): either reuse an
   existing superuser already in the shared DB, or
   `python manage.py createsuperuser`.
2. **Create each mortgage user** via the admin Users API (or the frontend Users
   screen, which calls it) — `POST /auth/users/` as that admin:
   ```json
   { "username": "jane.doe", "email": "jane@hfgroup.co.ke",
     "first_name": "Jane", "last_name": "Doe", "groups": ["mortgage_admin"] }
   ```
   - `groups` are written **by role name** — use `mortgage_admin` for the module
     admin, `mortgage_officer` / `mortgage_manager` / `mortgage_finance` for the rest.
   - **Omit `password`** and the API generates a strong one and returns it **once**
     as `generated_password` — share it with the user, who changes it on first login.
   - `GET /auth/roles/` lists all assignable groups for the dropdown.
3. **Existing staff** who should get mortgage access: just PATCH their user to add
   the mortgage group — no new account needed.

> Note: `mortgage_admin` is a **navigation/role** group, *not* Django `is_staff`.
> Creating users stays with `is_staff`/superuser accounts; the module admin manages
> mortgages, not system users.

### E. The same-port swap (real prod, after the clone succeeds)
1. Deploy the new backend code + prod env (§1, §5); `collectstatic`.
2. Run the §C adoption against **real prod**, using the statements recorded on the clone.
3. Point the served **frontend** at this backend (§7) and rebuild it.
4. **Flip the service:** stop the old backend service, start the new one **on the
   same port** (systemd — see §E commands once you paste the server output).
5. Verify (§8): login → OTP → dashboards; existing modules load; Mortgages works.

### F. Rollback (full replace)
Because the migration only **added** tables and never touched legacy data, rollback
is: **stop the new service, start the old one back on the same port.** The old
backend still works against the same DB. Only if a shared table was corrupted
(shouldn't happen) do you restore from the §2 backup.

---

## 0. What is safe vs risky (read first)

| Category | Count | On `migrate` | Risk |
|---|---|---|---|
| **Greenfield managed tables** (all `mortgage_*`, `sc_*`, `scorecard_*`, `*_upload` mirrors, `agent_conversations`, `analytics_snapshots`, `client_briefs`, `portfolio_insights`, `portfolio_rm_targets`, `portfolio_customer_enrichment`, `exco_initiatives`, `hf_rights_issue_applications`, `slideshow_slides`,
`employee_monthly_performance_v2`) | 24 | **Created cleanly** — additive, invisible to old backend | 🟢 Low |
| **Colliding managed tables** (names already in prod — see §3.4) | 46 | `CreateModel` **errors** → must be **adopted** via `--fake-initial` | 🔴 High |
| **Unmanaged tables** (`managed=False`, warehouse reads) | 31 | **No DDL emitted** | 🟢 None |

**Special landmine — `employee_monthly_performance` (RESOLVED 2026-07-02):** it
collided, **and the new schema diverged** from the prod table, which would have
500'd the moment a scorecard view queried the adopted table. **Fixed:** the
redesigned model now owns its own greenfield table
**`employee_monthly_performance_v2`** (`apps/staff_management/models.py`, migration
`0006_alter_employeemonthlyperformance_table`). On the shared DB the legacy
`employee_monthly_performance` table is **left untouched** (its historical rows are
preserved, just not read by the new ORM); `_v2` is created empty and repopulated by
the scorecard recompute. So on a full replace this table is no longer a blocker —
it just moves into the "genuinely-new tables to create" set (see Full-replace §C).

---

## 1. Pre-flight checklist (all must be ✅ before touching prod)

- [ ] **Secrets/settings** on the prod host (NOT the repo `.env`, which is dev):
  - [ ] `DJANGO_SETTINGS_MODULE=config.settings.production`
  - [ ] `SECRET_KEY` = a **new** strong value (see §5). **Never** reuse the old
        exposed key from the legacy `settings.py`.
  - [ ] `DEBUG=False`
  - [ ] `ALLOWED_HOSTS` = the real host(s), e.g. `ceo.hfgroup.co.ke`
  - [ ] `CORS_ORIGIN_ALLOW_ALL=False` + explicit allowed origins / `CSRF_TRUSTED_ORIGINS`
  - [ ] DB + DW credentials point at the intended prod databases
  - [ ] `EMAIL_*` (office365 SMTP) correct — **OTP login depends on it (§6)**
- [ ] **Full DB backup taken** (§2) and its restore verified.
- [ ] **Migration adoption rehearsed on a prod clone** (§3) with zero errors.
- [ ] **Pilot frontend build** points at the **new backend URL** (§7), not
      localhost and not the old prod URL.
- [ ] **OTP send-test** passed against prod SMTP (§6).
- [ ] `python manage.py check --deploy` reviewed (§8).
- [ ] Rollback steps understood (§9).

---

## 2. Backup (mandatory — this is the rollback point)

```bash
# On the prod DB host, before ANY migration:
pg_dump -U <db_user> -h <db_host> -Fc hf_group_app > hf_group_app_$(date +%F_%H%M).dump
# Verify it restores into a scratch DB before proceeding:
createdb -U <db_user> hf_group_app_restore_test
pg_restore -U <db_user> -d hf_group_app_restore_test hf_group_app_YYYY-MM-DD_HHMM.dump
# (drop the scratch DB once verified)
```

Do not proceed to §3 until a restore has actually succeeded.

---

## 3. Migration adoption (the careful part)

### 3.1 Rehearse on a clone first
```bash
# Clone prod into a staging DB and run the adoption there FIRST.
createdb -U <db_user> hf_group_stage
pg_restore -U <db_user> -d hf_group_stage hf_group_app_YYYY-MM-DD_HHMM.dump
# Point the new backend at hf_group_stage (env DB_NAME=hf_group_stage) and run 3.2.
```

### 3.2 Adopt existing tables, create only the new ones
```bash
export DJANGO_SETTINGS_MODULE=config.settings.production
python manage.py migrate --fake-initial
```
`--fake-initial` marks an app's `0001_initial` as applied **without** running its
`CreateModel`s **when those tables already exist**, and actually creates the ones
that don't. It then runs all later migrations normally (seed groups, etc.).

### 3.3 Watch for these failure modes on the clone
- **"relation already exists"** → an initial migration **mixes** existing + new
  tables, so `--fake-initial` won't fake it. Resolve by splitting/faking that app
  explicitly: `python manage.py migrate <app> 0001 --fake`, then
  `python manage.py migrate <app>` for the rest. Record which apps needed this.
- **Idempotent seeds** (`mortgages.0002_seed_mortgage_groups`, `seed_roles`) are
  `get_or_create` — safe to re-run.
- After it completes: `python manage.py showmigrations` → everything `[X]`, and
  **spot-check that existing tables' row counts are unchanged**.

### 3.4 The 46 tables that must be adopted (already in prod)
```
affordable_housing_applications, affordable_housing_projects_pipeline,
affordable_housing_registrations, afh_seller_mapping, auth_otp,
branch_employee_dmc_data, branch_final_employee_dmc_data, cust_monthly_ftp,
customer_allocation_base, customer_movment_approval_list, drawdown,
employee_monthly_performance (⚠ diverged — see §0), employee_role_history,
exco_owners, exco_strategic_initiatives, exco_strategic_milestones,
exco_strategic_thrust, hf_collections_feedback, hfdi_crm_projects,
hfdi_crm_sales_data, hfdi_customers_hfc_mortgages, hfdi_employee_data,
hfdi_employee_sales_data, hfdi_employee_scorecard_performance_data,
hfdi_legacy_projects, hfdi_legacy_sales_data, hfdi_manual_sales_data,
hfdi_performance_target_feedback, hfdi_sales_data, hfdi_target_feedback,
insurance_policies, loans_mom_ifrs_movement, missing_employee_actuals,
obligation_summary, portfolio_customer_transfer_history,
portfolio_management_feedback, portfolio_management_prospects, projects,
rm_allocation_list, rm_kpi_base_summary, staff_employee_data,
staff_leave_records, telesales_dormant_tills_allocation, telesales_staff_list,
trade_finance_data, weighted_dashboard_manual_sales_table
```
(Regenerate this list anytime with `scratchpad/model_diff.py` logic — new managed
tables whose `db_table` also exists in the old codebase.)

### 3.5 Apply to real prod
Only after §3.2 succeeds cleanly on the clone, repeat the exact same steps
(with the resolutions recorded in §3.3) against the real prod DB, inside a
maintenance-safe window.

---

## 4. Shared-DB write safety (pilot scope)

On a shared DB, when the new backend **writes** to a colliding table (e.g. via a
CRUD endpoint on `portfolio_management_feedback`), it changes the **same rows**
the live users see. For the pilot, keep writes limited to **greenfield tables**:

- ✅ **Mortgages module** — every table is greenfield (`mortgage_*`). Fully additive,
  no shared-data write risk. **Recommended pilot surface.**
- ⚠️ Legacy/ported CRUD + CSV-upload write paths touch shared prod tables — keep
  these **read-only or dark** during the pilot until validated.

---

## 5. SECRET_KEY

Generate with:
```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```
Place the value in the **prod environment only** (secrets manager / server env),
as `SECRET_KEY=...`. **Do not** commit it or put it in any tracked file.

> A fresh `SECRET_KEY` invalidates all existing JWTs (it's the `SIGNING_KEY`), so
> every logged-in user is forced to log in once after cutover. Expected, harmless.

---

## 6. OTP / email (login depends on it)

Login calls `POST /auth/api/token/` then the OTP flow (`/auth/generate-otp/`),
which emails a 6-digit code via office365 SMTP. In dev the console backend is used,
so **email delivery has never run end-to-end**. Before the pilot:

- [ ] Send a real OTP to a test user on prod and confirm it arrives.
- [ ] If it fails, the send is wrapped in `except: pass` — check server logs; the
      OTP is also stored in the `auth_otp` table and (when `DEBUG`) printed. In
      prod `DEBUG=False`, so **SMTP must actually work** or users can't log in.

---

## 7. Frontend (pilot)

`portfolio-management-frontend/.env.local` currently points at
`http://127.0.0.1:9000/` (set for local training). For the pilot build it must be
the **new backend's hosted URL**, with a trailing slash and no leading space:
```
NEXT_PUBLIC_API_URL=https://<new-backend-host>/
```
Rebuild/redeploy the pilot frontend after changing it (Next.js reads env at build).

---

## 8. Post-deploy verification

```bash
python manage.py check --deploy          # security warnings
python manage.py showmigrations          # all [X]
```
- [ ] Existing tables' row counts unchanged (compare against a pre-deploy snapshot).
- [ ] `GET /api/docs/` loads; Mortgages endpoints listed.
- [ ] Log in as a pilot user (token → OTP → dashboard).
- [ ] Mortgages: create a Product, upload a CSV (template), create a Lead,
      approve → disburse → schedule renders, record a payment.
- [ ] Old backend + current users **unaffected** (sanity-check a couple of their
      operations).

---

## 9. Rollback

The new backend runs side-by-side, so rollback = **stop routing pilot users to it**
(revert the pilot frontend URL / take the new app-server out of rotation). The
greenfield tables it created are additive and harmless if left in place.

If a shared table was unexpectedly altered (should not happen — see §0), restore
from the §2 backup into a scratch DB, diff, and repair the affected rows. Do **not**
blanket-restore the whole prod DB unless the old backend is also down, or you'll
lose everything both systems wrote since the backup.
