# Deployment Guide — hf_group_backend

_Last updated: 2026-07-03._

This is the **single, authoritative** guide for deploying the new backend to production.
Read the two boxes below, then run **Part 2 (The Runbook)** top to bottom.

## What this deployment is

- **Full replace.** The old backend is **retired**; **all** users move to the new backend.
- **Same database.** The new backend runs against the **same production database** the old
  system already uses — so no user or business data is copied or lost (see Part 1).
- **Same port (9000).** The new backend starts on the **exact port the old one used**, so
  there is **no new firewall port and nothing to request from Security**.
- **Containerized.** The prod host is **RHEL with system Python 3.6**, which cannot run this
  app (Django 6 needs Python ≥ 3.12) and cannot be upgraded. We run the app in a **container**
  (Python 3.13 inside); the host's Python is irrelevant. Commands use **`podman`** (ships with
  RHEL; it's a drop-in for `docker` — swap the name if you use Docker).

> ### ⛔ The two rules you must not break
> 1. **Never run a plain `python manage.py migrate` against prod.** 46 of the new tables
>    already exist in the prod DB; a plain migrate dies on *"relation already exists"*. Use
>    the **adoption** procedure in Step 6. **Rehearse it on a clone first (Step 5).**
> 2. **Secrets live only on the server**, in `/etc/hf/prod.env` (Step 3). Never commit them,
>    never put them in the image, and **never reuse the old backend's `SECRET_KEY`** (it's
>    exposed in the old code and is the JWT signing key — reusing it lets anyone forge logins).

> ### ✍️ Fill in these two server-specific values before you start
> Everything below uses these placeholders — confirm the real values on the server once:
>
> | Placeholder | What it is | How to find it |
> |---|---|---|
> | `<PROD_DB>` | The existing prod database that holds the old system's tables (auth, business data). The old backend named it **`datawarehouse`** — confirm. | `sudo -u postgres psql -c "\l"` — pick the DB that contains `auth_user`. |
> | `<old-backend>.service` | The systemd unit currently running the old backend on :9000. | `systemctl list-units \| grep -Ei 'gunicorn\|django\|portfolio'` |

---

## Part 1 — Why no users or data are lost (read once, for confidence)

The new backend points `default` at **`<PROD_DB>`** — the *same* physical database the old
backend uses. Therefore:

- **Every existing row stays put.** `auth_user`, `auth_group`, and all business tables are the
  *same* tables. The migrations only ever **CREATE new tables** — there is not a single
  drop/rename/delete-column op in the entire migration set (verified).
- **Users keep their passwords.** Django stores PBKDF2 hashes; the new backend reads the same
  `auth_user` rows, so existing logins just work. The only visible effect of the fresh
  `SECRET_KEY` is that everyone logs in **once** after cutover (old JWTs stop validating).
- **Nothing to "copy".** Because it's the same DB, users are already present — the
  `migrate_legacy_auth` command (for a *different*-DB scenario) is **not** used here.
- **The scorecard table is safe.** The legacy `employee_monthly_performance` table is left
  untouched; the redesigned model uses a new `employee_monthly_performance_v2` table
  (see Appendix B), so historical rows are preserved.

---

## Part 2 — The Runbook (do these in order)

### Step 1 — Prerequisites on the server
- `podman` installed (`podman --version`).
- Network access from the host to the prod **PostgreSQL** and **Redis**.
- The app code on the host and the `<PROD_DB>` / `<old-backend>.service` values confirmed above.

### Step 2 — Get the code and build the image
```bash
git clone <repo-url> hf_group_backend && cd hf_group_backend   # or scp the folder over
podman build -t hf-backend:latest .
```
The image ships **all 18 apps** (incl. `mortgages`, `client_briefs`, `agent`, `analytics`,
`insights`, `slideshow`) with every model + migration, runs `collectstatic` at build (WhiteNoise
serves admin/DRF/Swagger CSS), and contains **no secrets**.

> **Airgapped host?** Build on a machine with internet, then move the image:
> ```bash
> podman save -o hf-backend.tar hf-backend:latest   # on the build machine
> podman load -i hf-backend.tar                      # on the server
> ```

### Step 3 — Create the prod env file `/etc/hf/prod.env`
```bash
sudo mkdir -p /etc/hf
sudo cp .env.example /etc/hf/prod.env

# Generate a FRESH SECRET_KEY (on the server, so it never transits chat/git/logs):
podman run --rm hf-backend:latest \
  python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

sudo nano /etc/hf/prod.env     # edit the values per the table below
sudo chmod 600 /etc/hf/prod.env
```
Set these values (everything else can keep template defaults):

| Key | Prod value |
|---|---|
| `SECRET_KEY` | the fresh value you just generated — **never** the old backend key |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | the real host/domain (e.g. `ceo.hfgroup.co.ke`), not `*` |
| `DB_ENGINE` / `DB_HOST` / `DB_PORT` | `django.db.backends.postgresql` / `127.0.0.1` / `5432` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | **`<PROD_DB>`** and its prod credentials — this is the existing prod DB |
| `DW_HOST` / `DW_PORT` | `127.0.0.1` / `5432` |
| `DW_NAME` / `DW_USER` / `DW_PASSWORD` | **`<PROD_DB>`** and its credentials — **same physical DB** (the read-only warehouse tables live there too) |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `EMAIL_*` | real Office365 SMTP creds — **OTP login depends on this** (Appendix C) |
| `ANTHROPIC_API_KEY` | real key if the AI agent is used, else blank |

> `--network=host` (Step 8) makes the container share the host network, so `127.0.0.1`
> reaches the host's Postgres/Redis. **Both** `DB_*` and `DW_*` point at `<PROD_DB>` — the
> router sends managed-table traffic and read-only warehouse traffic to the same database.

### Step 4 — Back up the prod database (mandatory rollback point)
```bash
pg_dump -Fc -h 127.0.0.1 -U <db_user> <PROD_DB> -f hf_prod_$(date +%F_%H%M).dump

# Verify the backup actually restores before going further:
createdb -U <db_user> hf_restore_test
pg_restore -U <db_user> -d hf_restore_test hf_prod_YYYY-MM-DD_HHMM.dump
dropdb -U <db_user> hf_restore_test
```
**Do not proceed until a restore has actually succeeded.**

### Step 5 — Rehearse the migration on a clone (NOT on prod)
This is what catches surprises safely. Restore the backup into a scratch DB and run Step 6
against **it** first:
```bash
createdb -U <db_user> hf_stage
pg_restore -U <db_user> -d hf_stage hf_prod_YYYY-MM-DD_HHMM.dump
```
Temporarily point a copy of the env file at the clone (`DB_NAME=hf_stage`, `DW_NAME=hf_stage`)
and run Step 6 with `--env-file /etc/hf/stage.env`. **Write down exactly which statements you
run** so real prod matches the clone. Only when the clone is clean do you touch prod.

### Step 6 — Adopt existing tables, create only the new ones
Every command runs inside the container. Substitute the clone env file in Step 5.
```bash
# helper: run any manage.py command in the container
alias hf='podman run --rm --network=host --env-file /etc/hf/prod.env hf-backend:latest python manage.py'

hf showmigrations                     # inspect current state
hf migrate --fake-initial             # see below
```
`--fake-initial` does two things automatically:
- **All-new apps** (`mortgages`, `client_briefs`, `agent`, `analytics`, `insights`, `slideshow`):
  none of their tables exist yet → it **creates** them normally.
- **All-existing apps** (their `0001` tables are all already in prod): it marks them applied
  **without** running any DDL — i.e. it *adopts* them.

**Mixed apps error** with *"relation already exists"* — their `0001` creates *both* tables that
already exist *and* brand-new ones, so Django can't auto-fake it. `staff_management` is the known
case (existing `employee_monthly_performance` + new `scorecard_*` and `_v2`). Fix each such app
like this:
```bash
# 1. Adopt the app's initial into migration state WITHOUT running DDL:
hf migrate staff_management 0001 --fake

# 2. Create ONLY the genuinely-new tables from that app. Dump its SQL and apply
#    just the CREATE statements for tables that don't exist yet:
hf sqlmigrate staff_management 0001 > /tmp/sm.sql
#    From /tmp/sm.sql copy the CREATE TABLE/INDEX blocks for ONLY these five:
#      scorecard_roles, scorecard_kpis, scorecard_role_kpi_mappings,
#      scorecard_performance_actuals, employee_monthly_performance_v2
#    into /tmp/new_tables.sql  (do NOT include employee_monthly_performance — it exists)
psql -h 127.0.0.1 -U <db_user> -d <PROD_DB> -f /tmp/new_tables.sql

# 3. Fake the app's remaining migrations (they only touch already-adopted tables,
#    incl. 0006 which "renames" to _v2 — you already created _v2 directly):
hf migrate staff_management --fake
```
Repeat that pattern for **any** other app the clone flags with *"relation already exists"*.
Idempotent data seeds (`mortgages.0002_seed_mortgage_groups`, role seeds) use `get_or_create` and
are safe to run/re-run.

Finish and confirm:
```bash
hf showmigrations        # every migration must show [X]
```
Then spot-check in psql that existing tables' **row counts are unchanged**, the legacy
`employee_monthly_performance` is intact, and `employee_monthly_performance_v2` exists and is empty.

### Step 7 — Re-seed scorecard config
The new `scorecard_*` tables are empty. Load roles / KPIs / mappings, then run the scorecard
recompute so `employee_monthly_performance_v2` fills in. (Use the scorecard config screens in the
frontend, or the seed endpoints under `staff_management/`.)

### Step 8 — Cut over: stop the old backend, start the container on :9000
```bash
# Point the frontend at this backend first (Appendix D), then flip:
sudo systemctl stop <old-backend>.service
sudo systemctl disable <old-backend>.service

podman run -d --name hf-backend --restart=always \
  --network=host \
  --env-file /etc/hf/prod.env \
  -e PORT=9000 \
  hf-backend:latest
```
> Rootless podman binds :9000 fine (≥1024). Only ports <1024 need extra config.

### Step 9 — Create the Mortgages + admin accounts
The four role groups (`mortgage_officer`, `mortgage_manager`, `mortgage_finance`,
`mortgage_admin`) are **auto-created** by migration `mortgages.0002_seed_mortgage_groups`.
Frontend nav appears purely by **group membership**.
1. **Bootstrap a system admin** if you don't already have one in the DB:
   `hf createsuperuser`. A superuser automatically sees **Administration → Users & Roles** in the
   frontend.
2. **Create each user** from that screen (it calls `POST /auth/users/`):
   ```json
   { "username": "jane.doe", "email": "jane@hfgroup.co.ke",
     "first_name": "Jane", "last_name": "Doe", "groups": ["mortgage_admin"] }
   ```
   - `groups` are by **role name** (`mortgage_admin` / `_officer` / `_manager` / `_finance`).
   - **Leave `password` blank** → the API generates one and returns it **once** as
     `generated_password`; share it, the user changes it on first login.
3. **Existing staff** who need mortgage access: just edit their user to add the group.

### Step 10 — Verify
```bash
curl -s http://127.0.0.1:9000/api/docs/ >/dev/null && echo "backend up"
hf check --deploy         # review security warnings
hf showmigrations         # all [X]
```
In a browser: log in → OTP email arrives → dashboards load → existing modules work →
Mortgages: create a Product, upload a CSV, create a Lead, approve → disburse → schedule
renders → record a payment. Confirm existing tables' row counts match the pre-deploy snapshot.

### Step 11 — Rollback (only if something is wrong)
Because the migration only **added** tables and never touched legacy data, rollback is fast:
```bash
podman stop hf-backend
sudo systemctl enable --now <old-backend>.service
```
The old backend still works against the same DB. Only if a shared table was somehow corrupted
(shouldn't happen — the new backend never rewrites legacy schema) do you restore the Step 4 backup
into a scratch DB, diff, and repair the affected rows — **never** blanket-restore over the live DB.

---

## Appendix A — The 46 tables that already exist in prod (adopted, never re-created)
```
affordable_housing_applications, affordable_housing_projects_pipeline,
affordable_housing_registrations, afh_seller_mapping, auth_otp,
branch_employee_dmc_data, branch_final_employee_dmc_data, cust_monthly_ftp,
customer_allocation_base, customer_movment_approval_list, drawdown,
employee_monthly_performance (⚠ diverged — see Appendix B), employee_role_history,
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

## Appendix B — What each table category does on migrate

| Category | Count | On migrate | Risk |
|---|---|---|---|
| **Greenfield managed** (all `mortgage_*`, `sc_*`, `scorecard_*`, `*_upload` mirrors, `agent_conversations`, `analytics_snapshots`, `client_briefs`, `portfolio_insights`, `portfolio_rm_targets`, `portfolio_customer_enrichment`, `exco_initiatives`, `hf_rights_issue_applications`, `slideshow_slides`, `employee_monthly_performance_v2`) | 24 | **Created cleanly** — additive | 🟢 Low |
| **Colliding managed** (Appendix A — names already in prod) | 46 | Must be **adopted** (Step 6) | 🔴 handled by Step 6 |
| **Unmanaged** (`managed=False`, warehouse reads) | 31 | **No DDL emitted** | 🟢 None |

**The `employee_monthly_performance` landmine (resolved).** The legacy prod table has an
*incompatible* column set to the redesigned scorecard model, which would 500 the first scorecard
query if adopted directly. Fixed: the redesigned model owns a **new** `employee_monthly_performance_v2`
table (migration `0006`). The legacy table is left untouched (rows preserved, just not read by the
new ORM); `_v2` is created empty in Step 6 and filled by the Step 7 recompute.

## Appendix C — OTP / email (login depends on it)
Login is `POST /auth/api/token/` then an OTP flow that emails a 6-digit code via Office365 SMTP.
Dev uses the console backend, so **email has never run end-to-end**. Before cutover, send a real
OTP to a test user on prod and confirm it arrives. With `DEBUG=False`, **SMTP must work** or users
cannot log in (the OTP is also stored in `auth_otp`, but users rely on the email).

## Appendix D — Point the frontend at this backend
In `portfolio-management-frontend`, set the API URL to the new backend and rebuild (Next.js reads
env at build time):
```
NEXT_PUBLIC_API_URL=https://<new-backend-host>/
```
(Trailing slash, no leading space.)
