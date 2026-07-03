# HF Group Backend — Setup & Deployment Guide

> ## 🚀 Deploying to production? Read **[`docs/DEPLOY.md`](docs/DEPLOY.md)** first.
> The prod server runs **RHEL with Python 3.6** (cannot run this app directly) and the
> new backend shares the **existing production database**. Deployment is **containerized
> (podman/Docker)** with a careful migration-adoption step — a plain `manage.py migrate`
> will break prod. Follow the **▶ DEPLOYER QUICK RUNBOOK** at the top of `docs/DEPLOY.md`
> top to bottom. The sections below (§1–§12) are for **local development** only.

## Stack

| Layer | Technology |
|---|---|
| Framework | Django 6.0.5 + Django REST Framework |
| Runtime | Python 3.13 (containerized for prod — see `Dockerfile`) |
| Database | PostgreSQL (psycopg3) — two aliases: app DB + read-only warehouse |
| Auth | JWT via `djangorestframework-simplejwt` |
| Async / WebSockets | Django Channels + Daphne + Redis |
| Task queue | Celery + Redis |
| Static files | WhiteNoise (served by the app process) |
| API docs | drf-spectacular (Swagger at `/api/docs/`) |
| Server | Gunicorn (WSGI) or Daphne (ASGI); prod runs in a container on port 9000 |

---

## 1. Prerequisites (local development)

- Python 3.12 or 3.13 (Django 6 requires ≥ 3.12)
- PostgreSQL running and accessible
- Redis running on `localhost:6379` (used by Celery, Channels, and cache)

> **Production prerequisites are different** (podman, prod env file, DB backup) — see
> the runbook in `docs/DEPLOY.md`, not this list.

---

## 2. Environment File

> For **local dev** create a `.env` here by copying the template: `cp .env.example .env`
> and filling in values. **Never commit `.env`** (it's gitignored). Production secrets
> live in `/etc/hf/prod.env` on the server — see `docs/DEPLOY.md` §5.1.

Create `.env` in the project root (next to `manage.py`). Required keys:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=*

DB_ENGINE=django.db.backends.postgresql
DB_NAME=datawarehouse
DB_USER=datawarehouse
DB_PASSWORD=your-db-password
DB_HOST=127.0.0.1
DB_PORT=5432

REDIS_URL=redis://localhost:6379/0
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

If any package is missing (common on a fresh machine), install these explicitly:

```bash
pip install drf-spectacular celery channels channels-redis daphne structlog django-environ
```

---

## 4. Apply Migrations

> ⚠️ **Local/dev only.** Never run a plain `migrate` against the **production**
> database — it shares tables with the old system and will fail on "relation already
> exists". Production uses the migration-**adoption** procedure in `docs/DEPLOY.md` §3/§C.

Run this **every time new models are added** (including after pulling new code):

```bash
# Apply all migrations
python manage.py migrate

# Or migrate only the staff_management app (scorecard tables)
python manage.py migrate staff_management
```

To check migration status:

```bash
python manage.py showmigrations staff_management
# Should show: [X] 0001_initial
```

To create new migrations after changing models:

```bash
python manage.py makemigrations staff_management
python manage.py migrate staff_management
```

---

## 5. Run the Development Server

```bash
python manage.py runserver 0.0.0.0:9000
```

The frontend expects the backend on port **9000** in production (`ceo.hfgroup.co.ke:9000`).

---

## 6. Run in Production

### Option A — Gunicorn (WSGI, no WebSockets)

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:9000 --workers 4
```

### Option B — Daphne (ASGI, supports WebSockets)

```bash
daphne -b 0.0.0.0 -p 9000 config.asgi:application
```

### Celery Worker (required for background tasks)

```bash
celery -A tasks worker --loglevel=info
```

### Celery Beat (required for scheduled tasks — slideshow precompute, insights pipeline)

```bash
celery -A tasks beat --loglevel=info
```

---

## 7. URL Structure

All app endpoints are mounted at the root (no `/api/` prefix unless noted):

| Prefix | App |
|---|---|
| `auth/` | Authentication (login, refresh, password reset) |
| `portfolio/` | RM portfolio data |
| `tl_portfolio/` | Team Leader portfolio |
| `branch_portfolio/` | Branch Manager portfolio |
| `hf_collections/` | Collections |
| `collections_tl/` | Collections TL |
| `hfdi/` | HFDI |
| `staff_management/` | Staff + Scorecard (see §8) |
| `exco_innitiatives/` | EXCO initiatives |
| `hf_rights_issue/` | Rights issue |
| `portfolio_management_enrichment/` | RM targets, enrichment |
| `api/v1/analytics/` | Analytics (new) |
| `api/v1/insights/` | AI insights (new) |
| `api/v1/agent/` | AI agent (new) |
| `api/schema/` | OpenAPI schema |
| `api/docs/` | Swagger UI |
| `lexus/` | Django admin |

---

## 8. Scorecard Endpoints (`staff_management/`)

### Staff

| Method | URL | Description |
|---|---|---|
| GET | `staff_management/branch_managers/` | Branch managers list |
| GET | `staff_management/sales_staff/` | Sales staff list |
| GET | `staff_management/all_staff/` | All staff |
| GET | `staff_management/staff/<id>/` | Single staff record |

### Scorecard Config

| Method | URL | Description |
|---|---|---|
| GET/POST | `staff_management/roles/` | Scorecard roles |
| GET/POST | `staff_management/kpis/` | KPI definitions |
| GET/POST | `staff_management/role-kpi-mappings/` | Role ↔ KPI weights |

### Performance Actuals

| Method | URL | Description |
|---|---|---|
| GET | `staff_management/performance-actuals/` | All actuals (filterable) |
| GET | `staff_management/performance-actuals/missing-actuals/` | RMs with no actuals this month |
| GET | `staff_management/performance-actuals/missing-actuals-role-summary/` | Missing actuals by role |

### Monthly Performance

| Method | URL | Description |
|---|---|---|
| GET | `staff_management/employee-monthly-performance/` | Computed scores |
| **POST** | `staff_management/employee-monthly-performance/run-scorecard/` | **Run scorecard for all RMs** |
| **POST** | `staff_management/employee-monthly-performance/run-scorecard/role/` | **Run scorecard, group by role** |
| **POST** | `staff_management/employee-monthly-performance/run-scorecard/department/` | **Run scorecard, group by dept** |

POST body (optional — defaults to current month):
```json
{ "year": 2025, "month": 5 }
```

### Summaries

| Method | URL | Description |
|---|---|---|
| GET | `staff_management/monthly-performance-summary/employees/` | Per-employee scores |
| GET | `staff_management/monthly-performance-summary/department/` | Avg score by department |
| GET | `staff_management/monthly-performance-summary/role/` | Avg score by role |
| GET | `staff_management/monthly-performance-summary/org-unit/` | Avg score by org unit |
| GET | `staff_management/rm-kpi-base-summary/` | Top RMs by deposits + customers |

### Data Automation Triggers

| Method | URL | Description |
|---|---|---|
| **POST** | `staff_management/insurance-policy/trigger-script/` | Trigger insurance data script |
| **POST** | `staff_management/drawdowns/trigger-script/` | Trigger drawdowns script |
| **POST** | `staff_management/trade-finance/trigger-script/` | Trigger trade finance script |
| **POST** | `staff_management/weighted-sales/trigger-script/` | Trigger weighted sales script |

All endpoints require a Bearer JWT token (`Authorization: Bearer <token>`).

---

## 9. Scorecard Calculation Logic

The engine runs when a POST is sent to any `run-scorecard/` endpoint.

**Data sources:**
- RM list → `RetailAllocatedPortfolio` (distinct `sales_code` + `rm_name`)
- Deposit actuals → `PortfolioRmDepositTrends` (filtered by year + month, summed per RM)
- New customers → `PortfolioRmDepositTrends.number_of_customers` (same query)
- Revenue actuals → `PortfolioRmRevenue` (YTD, summed per RM)
- Targets → `RmTarget` (filtered by year + month)
- Employee metadata → `BranchEmployeeData` (role, department, org unit)

**Score formula:**
```
achievement %  = min(actual / target * 100, 110)   # capped at 110%
total_score    = deposits*0.40 + loans*0.30 + revenue*0.20 + new_customers*0.10
grade          = A (≥90) / B (≥80) / C (≥60) / D (≥50) / E (<50)
kpis_met       = count of KPIs where achievement ≥ 80%
```

Results are saved to the `employee_monthly_performance_v2` table using `update_or_create` (safe to re-run). *(The redesigned model owns a greenfield `_v2` table so it never collides with the legacy prod table of the old name — see `docs/DEPLOY.md` §0.)*

---

## 10. Database Tables Created by Migrations

| Table | Purpose |
|---|---|
| `scorecard_roles` | Role definitions (e.g. "Relationship Manager") |
| `scorecard_kpis` | KPI definitions (Deposits, Loans, Revenue, etc.) |
| `scorecard_role_kpi_mappings` | Which KPIs apply to which role and at what weight |
| `scorecard_performance_actuals` | Per-RM per-KPI actual vs target values per month |
| `employee_monthly_performance_v2` | Computed monthly score card per RM (greenfield; avoids the legacy prod table) |

The `employee_table` is an **unmanaged** table (Django reads it, does not create/alter it).

---

## 11. Common Issues & Fixes

### "No module named X" when running manage.py

```bash
pip install drf-spectacular celery channels channels-redis daphne structlog django-environ
```

### Migrations not applied on production server

SSH into the production server and run:
```bash
cd /path/to/hf_group_backend
source venv/bin/activate        # if using a virtualenv
python manage.py migrate staff_management
```

### 404 on automation endpoints

The URL prefix is `staff_management/` **not** `/api/staff_management/`. Example:
- Correct: `POST https://ceo.hfgroup.co.ke:9000/staff_management/employee-monthly-performance/run-scorecard/`
- Wrong: `POST https://ceo.hfgroup.co.ke:9000/api/staff_management/...`

### 401 on all endpoints (expected when not authenticated)

This is correct behaviour. The frontend attaches a JWT Bearer token automatically. If testing manually use:
```bash
curl -H "Authorization: Bearer <your_token>" -X POST \
  https://ceo.hfgroup.co.ke:9000/staff_management/employee-monthly-performance/run-scorecard/
```

### Redis not available

If Redis is not running, Celery and Channels will fail to start. Start Redis:
```bash
# Linux / WSL
redis-server

# Windows (if Redis is installed as a service)
net start Redis
```

---

## 12. Apps Overview

| App | What it does |
|---|---|
| `authentication` | JWT login, refresh, password reset |
| `portfolio` | RM-level portfolio: customers, loans, deposits, revenue, feedback, prospects |
| `tl_portfolio` | Team Leader views (aggregated RM data) |
| `branch_portfolio` | Branch Manager views |
| `hf_collections` | Collections portfolio |
| `collections_team_leaders` | Collections TL views |
| `hfdi` | HFDI data |
| `staff_management` | Staff directory + scorecard automation (see §8–10) |
| `exco_innitiatives` | EXCO strategic initiatives tracker |
| `hf_rights_issue` | Rights issue data |
| `portfolio_management_enrichment` | RM targets, enrichment data |
| `gceo_dashboard` | CEO-level aggregated views |
| `analytics` | Analytics API (v1) |
| `insights` | AI-generated insights pipeline |
| `agent` | AI agent / chat (WebSocket) |
| `slideshow` | Auto-generated slideshow data |
