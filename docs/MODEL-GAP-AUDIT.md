# Model Gap Audit — Old Backend → New Backend

_Generated: 2026-06-09. Source of truth: parsed every `models.py` in
`hf_group_project-master` (old) vs `hf_group_backend/apps` (new), keyed by
`db_table`, with field-level diffs on shared tables._

This is the **migration-safety** audit: which production tables and fields the
new backend does **not** yet implement, so we don't lose data or break the
frontend during cut-over.

---

## Headline

- Old backend models: **90** across 11 apps.
- New backend models: **66** across 15 apps.
- **36 old tables have no model in the new backend.**
- **12 new tables did not exist in the old backend** (greenfield redesigns).
- Field-level gaps on shared tables: **1** model (12 columns).

The 36 missing tables fall into **5 categories** below. Not all are "port it
verbatim" — three apps were *redesigned* into unrelated tables, which is the
biggest migration risk because the **old production data has nowhere to land**.

---

## STATUS (2026-06-09)

- **Category A — DONE.** All 19 legacy staff_management models ported to
  `apps/staff_management/models.py` (exact `db_table`/`managed`/fields), with
  serializers, views (`legacy_views.py`), URLs, migration
  `0002_dailydormancyconvertedaccount_and_more`, and 9 new tests (30/30 project
  tests pass). `managed=True` tables got full CRUD + CSV; `managed=False`
  warehouse tables got read-only list/detail.
- **Deferred — CSV upload to `managed=False` warehouse tables** (`products`,
  `merchant-bank-tills-manual`, `weighted-sales-daily-accounts`,
  `weighted-sales-dormancy-converted`, `retail-allocated-portfolio`): the DB
  router **blocks writes** to unmanaged tables, so these uploads need a decided
  write target (make the table app-managed, or write explicitly via the
  warehouse connection). Not wired to avoid silent failures.
- **Category B/D/E still pending:** legacy scorecard port (+ `employee_monthly_performance`
  table conflict), exco/enrichment/rights divergent ports, hfdi 12-column fix.
- **Agent → Claude:** pending (decision made, not yet implemented).

---

## Category A — Genuine unported tables (staff_management). DONE.

These exist in the old backend, hold/serve real data, and the frontend calls
them (see `frontend_endpoint_gap.md`: 44 missing `staff_management` endpoints).
No equivalent in the new backend. `managed` flag must be copied **exactly**.

| Old model | db_table | managed | Frontend resource |
|---|---|---|---|
| BranchEmployeeDmcData | `branch_employee_dmc_data` | True | `branch_employee_dmc_data` |
| BranchFinalEmployeeDmcData | `branch_final_employee_dmc_data` | True | `branch_final_employee_dmc_data` |
| Drawdown | `drawdown` | True | `drawdowns/upload-csv` |
| DrawdownDaily | `drawdown_daily` | **False** (warehouse) | `drawdown-daily` |
| InsurancePolicy | `insurance_policies` | True | `insurance-policy` (+upload) |
| TradeFinanceData | `trade_finance_data` | True | `trade-finance` (+upload) |
| CustMonthlyFtp | `cust_monthly_ftp` | True | (FTP cost basis for RM KPI) |
| DailySalesAccountsWithCto | `daily_sales_accounts_with_cto` | **False** | `weighted-sales-daily-accounts` |
| DailyDormancyConvertedAccount | `daily_dormancy_converted_accounts` | **False** | `weighted-sales-dormancy-converted` |
| MerchantBankTillManualData | `weighted_sales_seller_bank_till_data_dump_manual` | **False** | `merchant-bank-tills-manual` (+upload) |
| IapplyLoanApproval | `iapply_loan_approvals_data_dump` | **False** | (iApply approvals) |
| Product | `product_mapping` | **False** | `products` (+upload) |
| StaffEmployeeData | `staff_employee_data` | True | `employee-summary` |
| LeaveRecord | `staff_leave_records` | True | `leave-records` (+upload) |
| EmployeeRoleHistory | `employee_role_history` | True | `role-history` (+upload) |
| RmKPIBaseSummary | `rm_kpi_base_summary` | True | `rm-kpi-base-summary` (+refresh/upload) |
| MissingEmployeeActual | `missing_employee_actuals` | True | (missing-actuals support) |
| TelesalesStaff | `telesales_staff_list` | True | (telesales) |
| TelesalesDormantTillsAllocation | `telesales_dormant_tills_allocation` | True | (telesales) |

> Also: `staff_management/retail-allocated-portfolio` (+upload) maps to
> **portfolio.RetailAllocatedPortfolio** (`retail_allocated_portfolio`, managed=False),
> which already exists in the new portfolio app — only the endpoint is missing.

## Category B — OLD scorecard config replaced by NEW scorecard tables. DIVERGENT.

The new backend reimplemented the scorecard with **different table names**, so
the old production scorecard config/data is orphaned:

| Old model → table | New model → table |
|---|---|
| Role → `orgnization_roles` | ScorecardRole → `scorecard_roles` |
| KPI → `kpi_definitions` | ScorecardKPI → `scorecard_kpis` |
| RoleKPIMapping → `role_kpi_mappings` | RoleKPIMapping → `scorecard_role_kpi_mappings` |
| EmployeePerformanceActual → `employee_performance_actual_values` | PerformanceActual → `scorecard_performance_actuals` |

**Risk:** if the org has live scorecard config/actuals in the old tables, the
new empty tables won't show it. Decision needed: migrate old → new, or point the
new models back at the old `db_table` names.

## Category C — Stub tables, likely never populated. LOW PRIORITY.

These old models had **no `db_table`** (Django default name) and no managed
flag — almost certainly unused scaffolding:

- `BranchAudit`, `BranchPerformanceScorecardData`, `BranchPerformanceMonthlyScorecard`

Verify they're empty in prod, then skip.

## Category D — Domain rewrites: old production tables NOT ported. HIGHEST DATA RISK.

Three whole apps were rebuilt around **brand-new, unrelated tables**. The old
tables (with real data + frontend endpoints) have **no model** in the new backend:

**exco_innitiatives** — old strategic-planning model (4 tables) → new single table:
- `exco_owners` (StrategicExcoOwner)
- `exco_strategic_thrust` (StrategicThrust)
- `exco_strategic_initiatives` (StrategicInitiative — incl. `co_owner_1..7`, comments, status)
- `exco_strategic_milestones` (StrategicMilestone — incl. proportion_complete, sensitivity, review_status)
- NEW backend instead has: `exco_initiatives` (ExcoInitiative) — a flat, unrelated table.

**portfolio_management_enrichment** — old allocation engine (4 tables) → new 2 tables:
- `customer_allocation_base` (CustomerAllocationBase)
- `rm_allocation_list` (RmAllocationList)
- `customer_movment_approval_list` (TeamLeaderMovementApprovers)
- `portfolio_customer_transfer_history` (CustomerTransferHistory)
- NEW backend instead has: `portfolio_customer_enrichment`, `portfolio_rm_targets` — unrelated.

**hf_rights_issue** — old rights-issue model (2 tables) → new single table:
- `security_detail` (SecurityDetail — ~100 fields of shareholder/security data)
- `customer_feedback_rights_issue` (CustomerFeedbackRightsIssue)
- NEW backend instead has: `hf_rights_issue_applications` (RightsIssueApplication) — unrelated.

## Category E — Field gaps on shared tables.

Only one shared model lost columns:

- **hfdi.HfdiProjectsInventorySalesData** (`hfdi_projects_inventory_sales_data`,
  managed=False) — new model is missing the 12 monthly paid-amount columns:
  `jan_paid_amount` … `dec_paid_amount` (DecimalField). Because the table is
  unmanaged (warehouse), the columns exist in the DB but the new model can't
  read them. Add them back.

All other shared models (hfdi ×17, portfolio ×12, gceo_dashboard ×18,
collections_team_leaders, hf_collections) match field-for-field.

---

## The AI agent

`apps/agent` is an **OpenAI-backed** chat assistant (`gpt-4o-mini`,
`AgentConversation` → `agent_conversations`, 3 endpoints: conversations
list/create, detail, chat). It is generic (one system prompt), not yet wired to
the portfolio data or per-role context. Open questions before frontend work:
provider (OpenAI vs Claude), grounding (should it see portfolio/KPI data), and
whether it's one assistant or role-specialised "agents".
