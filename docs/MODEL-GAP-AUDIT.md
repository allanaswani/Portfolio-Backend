# Model Gap Audit — Old Backend → New Backend

_Last refreshed: **2026-07-01**. Source of truth: AST-parsed every `models.py` in
`_old_codebase_ref/hf_group_project` (old) vs `hf_group_backend/apps` (new), keyed
by `db_table`, with field-level diffs on shared tables._

This is the **migration-safety** audit: which production tables and fields the new
backend does **not** implement, so we don't lose data or break the frontend during
cut-over.

> History: the original audit (2026-06-09) reported **36 missing tables**. Nearly all
> have since been ported (staff_management legacy models, scorecard engine, exco
> hierarchy, enrichment reallocation, hfdi AFH tables, CSV uploaders). This refresh
> reflects the **current** state after that work.

---

## Headline (2026-07-01)

- Old backend models: **87** (83 with an explicit `db_table`).
- New backend models: **101** (100 with an explicit `db_table`).
- **Missing tables: 6** — but only **2** are genuinely unported (see below).
- **Column gaps on shared tables: 1** (intentional redesign; was 3, 2 now fixed).
- **23 new tables** did not exist in the old backend (greenfield: mortgages,
  agent, analytics, insights, client_briefs, slideshow, scorecard redesign,
  `sc_*` engine, warehouse `*_upload` mirrors).

**Bottom line: no data-loss gaps in any table the new backend *manages*.** The two
remaining missing tables are the redesigned rights-issue app (product decision), and
the one remaining column gap is a deliberate schema redesign.

---

## Missing tables — 6 (only 2 are real)

| Old table | Old model | Status in new backend |
|---|---|---|
| `kpi_definitions` | KPI | ✅ Re-created as `sc_kpi_definitions` (ScKpi) + `scorecard_kpis` (ScorecardKPI) |
| `orgnization_roles` | Role | ✅ Re-created as `sc_organization_roles` (ScRole) + `scorecard_roles` (ScorecardRole) |
| `role_kpi_mappings` | RoleKPIMapping | ✅ Re-created as `sc_role_kpi_mappings` + `scorecard_role_kpi_mappings` |
| `employee_performance_actual_values` | EmployeePerformanceActual | ✅ Re-created as `sc_employee_performance_actual_values` + `scorecard_performance_actuals` |
| **`security_detail`** | SecurityDetail | ❌ **NOT ported** — rights-issue redesigned to `hf_rights_issue_applications` (incompatible schema) |
| **`customer_feedback_rights_issue`** | CustomerFeedbackRightsIssue | ❌ **NOT ported** |

**The 4 scorecard tables** aren't really missing — they were **deliberately renamed**
(the old names collide with the redesigned scorecard, and again with the parallel
`sc_*` engine). Structure is fully covered. ⚠️ **Caveat:** the new `sc_*`/`scorecard_*`
tables **start empty** — if old prod held live KPI/role config, that **data** was not
migrated. These are config tables (usually re-seeded, not migrated); confirm with the
scorecard owner.

**The 2 rights-issue tables** are the only genuinely unported tables. See Category D.

---

## Column gaps on shared tables — 1 remaining (was 3)

All three original gaps were on `managed = False` **warehouse-read** tables — the
physical columns still exist in the warehouse DB; the new ORM model simply didn't
declare them (an **exposure** gap, **zero data loss**).

| Table (managed=False) | Missing columns | Status |
|---|---|---|
| `hfdi_projects_inventory_sales_data` | 12 monthly `jan_paid_amount … dec_paid_amount` | ✅ **FIXED 2026-07-01** — added to `apps/hfdi/models.py` |
| `employee_table` (gceo_dashboard) | `hfdi_erp_id`, `staff_exit_date`, `promotion_date` | ✅ **FIXED 2026-07-01** — added to `apps/gceo_dashboard/models.py` |
| `employee_monthly_performance` | 18 cols (`kpi_code`, `kpi_name`, `ytd_*`, `eom_date`, …) | ⚠️ **Intentional** — see note |

Both fixes were safe: the tables are unmanaged, so `makemigrations` produces **no
changes** (nothing touches the DB); both serializers are `fields = "__all__"`, so the
columns auto-expose in the API. `manage.py check` clean.

**`employee_monthly_performance` is by design.** The new backend reused this `db_table`
for the **simplified redesigned** scorecard (fewer columns). The rich legacy schema
(`kpi_code`, `ytd_*`, etc.) now lives in **`sc_employee_monthly_performance`** (the
parallel `sc_*` engine). The two scorecard systems coexist until one is retired, so
this is not a gap to "fix" — it's a decision already made.

All other shared models match field-for-field.

---

## Category D — Domain rewrites (rights-issue is the only one still open)

Three apps were originally flagged as rebuilt around new tables. Two are now ported
**additively** (old tables re-created alongside the redesign); one remains open.

**exco_innitiatives** — ✅ **PORTED.** Old strategic hierarchy re-created:
`exco_owners`, `exco_strategic_thrust`, `exco_strategic_initiatives`,
`exco_strategic_milestones` (StrategicExcoOwner→Thrust→Initiative→Milestone). The flat
`exco_initiatives` (ExcoInitiative) coexists.

**portfolio_management_enrichment** — ✅ **PORTED.** Old reallocation engine re-created:
`customer_allocation_base`, `rm_allocation_list`, `customer_movment_approval_list`,
`portfolio_customer_transfer_history` (all `managed=True`). The new
`portfolio_customer_enrichment` / `portfolio_rm_targets` coexist.

**hf_rights_issue** — ❌ **STILL OPEN (highest remaining risk).** The old app had:
- `security_detail` (SecurityDetail — ~100 fields of shareholder/security data;
  `pal_no`, `rights_taken`, `hf_customer`, …)
- `customer_feedback_rights_issue` (CustomerFeedbackRightsIssue)

The new app was redesigned around **`hf_rights_issue_applications`**
(RightsIssueApplication — `application_number`, `applicant_name`, `cds_account`,
`rights_entitlement`, …) with **no overlapping keys**. A faithful port would require
recreating the deprecated `security_detail` model. There is also **no rights-issue
CSV-upload hook on the frontend**. **Decision needed:** recreate the legacy tables for
data continuity, or treat the redesign as a clean break and migrate/park the old data.

---

## Greenfield tables (new, no old equivalent) — informational

Mortgages (`mortgage_*` incl. `mortgage_repayment_schedule`), agent
(`agent_conversations`), analytics (`analytics_snapshots`), insights
(`portfolio_insights`), client_briefs (`client_briefs`), slideshow
(`slideshow_slides`); the redesigned scorecard (`scorecard_*`); the parallel KPI
engine (`sc_*`); enrichment (`portfolio_customer_enrichment`, `portfolio_rm_targets`);
and the warehouse manual-upload mirrors (`daily_sales_accounts_with_cto_upload`,
`daily_dormancy_converted_accounts_upload`, `merchant_bank_till_manual_upload`,
`retail_allocated_portfolio_upload`).

---

## Remaining actions

1. **hf_rights_issue** — product decision on `security_detail` +
   `customer_feedback_rights_issue` (recreate vs. clean break).
2. **Scorecard config data** — confirm whether old `kpi_definitions` /
   `orgnization_roles` / `role_kpi_mappings` / `employee_performance_actual_values`
   held live prod data needing migration into the new `sc_*` / `scorecard_*` tables
   (vs. re-seeding).

   **Checked 2026-07-01 — local is a dead end, must query PROD.** None of these old
   tables exist in any locally reachable database: the local `postgres` DB (old app's
   configured DB) is **completely empty (0 tables)**; `datawarehouse`/`datawarehouse1`
   don't have them; and the new `sc_*`/`scorecard_*` tables are all **0 rows** (not
   seeded locally). The old data lives **only on prod** (`ceo.hfgroup.co.ke`), not
   reachable from a dev box. **Do NOT conclude "empty local = safe."** Run this on the
   **prod** DB to settle it:

   ```sql
   SELECT 'kpi_definitions' t, count(*) FROM kpi_definitions
   UNION ALL SELECT 'orgnization_roles', count(*) FROM orgnization_roles
   UNION ALL SELECT 'role_kpi_mappings', count(*) FROM role_kpi_mappings
   UNION ALL SELECT 'employee_performance_actual_values', count(*) FROM employee_performance_actual_values
   UNION ALL SELECT 'security_detail', count(*) FROM security_detail
   UNION ALL SELECT 'customer_feedback_rights_issue', count(*) FROM customer_feedback_rights_issue;
   ```

   Decision rule: config tables (`kpi_definitions`/`orgnization_roles`/`role_kpi_mappings`)
   are **re-seedable** via `staff_management/setup-defaults/` (`SeedDefaultKPIConfigView`)
   + the `seed_roles` command — re-seed rather than migrate. Only
   `employee_performance_actual_values` (historical actuals, not config) is worth
   migrating into `sc_employee_performance_actual_values` if that history matters.
   `security_detail` / `customer_feedback_rights_issue` non-empty → folds into action #1.

_All other tables/columns are accounted for. The AI agent app has been switched from
OpenAI to Claude (see `apps/agent`)._
