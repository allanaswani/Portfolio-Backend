from django.urls import include, path
from . import views
from . import legacy_views as lv

urlpatterns = [
    # ── Legacy scorecard automation engine (parallel subsystem, sc_* tables) ──
    path("scorecard-automation/", include("apps.staff_management.scorecard_automation.urls")),

    # ── Existing staff endpoints ──────────────────────────────────────────────
    path("branch_managers/",  views.BranchManagersListView.as_view()),
    path("sales_staff/",      views.SalesStaffListView.as_view()),
    path("all_staff/",        views.AllStaffListView.as_view()),
    path("staff/<int:pk>/",   views.StaffDetailView.as_view()),

    # ── All staff (frontend calls this "employees/") ──────────────────────────
    path("employees/",        views.AllStaffListView.as_view()),

    # ── Scorecard config: list/create, CSV upload, then detail ────────────────
    path("roles/",                       views.ScorecardRoleListCreateView.as_view()),
    path("roles/upload-csv/",            views.ScorecardRoleCsvUploadView.as_view()),
    path("roles/<int:pk>/",              views.ScorecardRoleDetailView.as_view()),
    path("kpis/",                        views.ScorecardKPIListCreateView.as_view()),
    path("kpis/upload-csv/",             views.ScorecardKPICsvUploadView.as_view()),
    path("kpis/<int:pk>/",               views.ScorecardKPIDetailView.as_view()),
    path("role-kpi-mappings/",           views.RoleKPIMappingListCreateView.as_view()),
    path("role-kpi-mappings/upload-csv/", views.RoleKPIMappingCsvUploadView.as_view()),
    path("role-kpi-mappings/<int:pk>/",  views.RoleKPIMappingDetailView.as_view()),

    # ── Performance actuals ───────────────────────────────────────────────────
    path("performance-actuals/",                               views.PerformanceActualListView.as_view()),
    path("performance-actuals/missing-actuals/",               views.MissingActualsView.as_view()),
    path("performance-actuals/missing-actuals-role-summary/",  views.MissingActualsRoleSummaryView.as_view()),

    # ── Monthly performance (list + automation) ───────────────────────────────
    path("employee-monthly-performance/",                      views.EmployeeMonthlyPerfListView.as_view()),
    path("employee-monthly-performance/run-scorecard/",        views.RunScorecardAllView.as_view()),
    path("employee-monthly-performance/run-scorecard/role/",   views.RunScorecardByRoleView.as_view()),
    path("employee-monthly-performance/run-scorecard/department/", views.RunScorecardByDeptView.as_view()),

    # ── Summaries ─────────────────────────────────────────────────────────────
    path("monthly-performance-summary/employees/",   views.PerfSummaryEmployeesView.as_view()),
    path("monthly-performance-summary/department/",  views.PerfSummaryDeptView.as_view()),
    path("monthly-performance-summary/role/",        views.PerfSummaryRoleView.as_view()),
    path("monthly-performance-summary/org-unit/",    views.PerfSummaryOrgUnitView.as_view()),
    path("rm-kpi-base-summary/",                     views.RMKPIBaseSummaryView.as_view()),

    # ── Scorecard setup ───────────────────────────────────────────────────────
    path("setup-defaults/",                          views.SeedDefaultKPIConfigView.as_view()),

    # ── Automation trigger scripts ────────────────────────────────────────────
    path("insurance-policy/trigger-script/",         views.TriggerInsuranceScriptView.as_view()),
    path("drawdowns/trigger-script/",                views.TriggerDrawdownsScriptView.as_view()),
    path("trade-finance/trigger-script/",            views.TriggerTradeFinanceScriptView.as_view()),
    path("weighted-sales/trigger-script/",           views.TriggerWeightedSalesScriptView.as_view()),

    # ══ Ported legacy staff_management resources ══════════════════════════════
    # NOTE: for each resource, the `upload-csv` / action paths are declared
    # BEFORE the `<int:pk>` detail path so they are not captured as a pk.

    # Branch DMC target data (managed → full CRUD + CSV)
    path("branch_employee_dmc_data/upload-csv/", lv.BranchEmployeeDmcCsvUploadView.as_view()),
    path("branch_employee_dmc_data/<int:pk>/",   lv.BranchEmployeeDmcDetailView.as_view()),
    path("branch_employee_dmc_data/",            lv.BranchEmployeeDmcListCreateView.as_view()),
    path("branch_final_employee_dmc_data/upload-csv/", lv.BranchFinalEmployeeDmcCsvUploadView.as_view()),
    path("branch_final_employee_dmc_data/<int:pk>/",   lv.BranchFinalEmployeeDmcDetailView.as_view()),
    path("branch_final_employee_dmc_data/",            lv.BranchFinalEmployeeDmcListCreateView.as_view()),

    # Drawdowns (managed Drawdown + warehouse DrawdownDaily read-only)
    path("drawdowns/upload-csv/",   lv.DrawdownCsvUploadView.as_view()),
    path("drawdowns/<int:pk>/",     lv.DrawdownDetailView.as_view()),
    path("drawdowns/",              lv.DrawdownListCreateView.as_view()),
    path("drawdown-daily/<int:pk>/", lv.DrawdownDailyDetailView.as_view()),
    path("drawdown-daily/",         lv.DrawdownDailyListView.as_view()),

    # Insurance policies (managed → full CRUD + CSV)
    path("insurance-policy/upload-csv/", lv.InsurancePolicyCsvUploadView.as_view()),
    path("insurance-policy/<int:pk>/",   lv.InsurancePolicyDetailView.as_view()),
    path("insurance-policy/",            lv.InsurancePolicyListCreateView.as_view()),

    # Trade finance (managed → full CRUD + CSV)
    path("trade-finance/upload-csv/", lv.TradeFinanceCsvUploadView.as_view()),
    path("trade-finance/<int:pk>/",   lv.TradeFinanceDetailView.as_view()),
    path("trade-finance/",            lv.TradeFinanceListCreateView.as_view()),

    # Customer monthly FTP (managed → full CRUD + CSV)
    path("cust-monthly-ftp/upload-csv/", lv.CustMonthlyFtpCsvUploadView.as_view()),
    path("cust-monthly-ftp/<int:pk>/",   lv.CustMonthlyFtpDetailView.as_view()),
    path("cust-monthly-ftp/",            lv.CustMonthlyFtpListCreateView.as_view()),

    # Leave records (managed → full CRUD + CSV)
    path("leave-records/upload-csv/", lv.LeaveRecordCsvUploadView.as_view()),
    path("leave-records/<int:pk>/",   lv.LeaveRecordDetailView.as_view()),
    path("leave-records/",            lv.LeaveRecordListCreateView.as_view()),

    # Role history (managed → full CRUD + CSV)
    path("role-history/upload-csv/", lv.EmployeeRoleHistoryCsvUploadView.as_view()),
    path("role-history/<int:pk>/",   lv.EmployeeRoleHistoryDetailView.as_view()),
    path("role-history/",            lv.EmployeeRoleHistoryListCreateView.as_view()),

    # RM KPI base summary (managed → detail + refresh + CSV; list is the computed view above)
    path("rm-kpi-base-summary/refresh/",    lv.RmKPIBaseSummaryRefreshView.as_view()),
    path("rm-kpi-base-summary/upload-csv/", lv.RmKPIBaseSummaryCsvUploadView.as_view()),
    path("rm-kpi-base-summary/<int:pk>/",   lv.RmKPIBaseSummaryDetailView.as_view()),

    # Missing actuals + employee summary
    path("missing-actuals/",  lv.MissingEmployeeActualListView.as_view()),
    path("employee-summary/", lv.EmployeeSummaryView.as_view()),

    # Telesales (managed → full CRUD + CSV; sales-people/upload-csv → telesales staff)
    path("sales-people/upload-csv/", lv.TelesalesStaffCsvUploadView.as_view()),
    path("sales-people/<int:pk>/",   lv.TelesalesStaffDetailView.as_view()),
    path("sales-people/",            lv.TelesalesStaffListCreateView.as_view()),
    path("telesales-dormant-tills/upload-csv/", lv.TelesalesDormantTillsCsvUploadView.as_view()),
    path("telesales-dormant-tills/<int:pk>/",   lv.TelesalesDormantTillsDetailView.as_view()),
    path("telesales-dormant-tills/",            lv.TelesalesDormantTillsListCreateView.as_view()),

    # Warehouse reads (read-only — writes blocked by the DB router)
    path("products/<int:pk>/",                  lv.ProductDetailView.as_view()),
    path("products/",                           lv.ProductListView.as_view()),
    path("merchant-bank-tills-manual/<int:pk>/", lv.MerchantBankTillManualDetailView.as_view()),
    path("merchant-bank-tills-manual/",          lv.MerchantBankTillManualListView.as_view()),
    path("weighted-sales-daily-accounts/",       lv.DailySalesAccountsWithCtoListView.as_view()),
    path("weighted-sales-dormancy-converted/",   lv.DailyDormancyConvertedAccountListView.as_view()),
    path("iapply-loan-approvals/",               lv.IapplyLoanApprovalListView.as_view()),
    path("retail-allocated-portfolio/<int:pk>/", lv.RetailAllocatedPortfolioDetailView.as_view()),
    path("retail-allocated-portfolio/",          lv.RetailAllocatedPortfolioListView.as_view()),

    # Manual CSV uploads of warehouse datasets → managed *_upload mirror tables.
    # upload-csv/ = write target (legacy results-ZIP); uploads/ = read the mirror.
    path("merchant-bank-tills-manual/upload-csv/",        lv.MerchantBankTillManualUploadCsvView.as_view()),
    path("merchant-bank-tills-manual/uploads/",           lv.MerchantBankTillManualUploadListView.as_view()),
    path("weighted-sales-daily-accounts/upload-csv/",     lv.DailySalesAccountsWithCtoUploadCsvView.as_view()),
    path("weighted-sales-daily-accounts/uploads/",        lv.DailySalesAccountsWithCtoUploadListView.as_view()),
    path("weighted-sales-dormancy-converted/upload-csv/", lv.DailyDormancyConvertedAccountUploadCsvView.as_view()),
    path("weighted-sales-dormancy-converted/uploads/",    lv.DailyDormancyConvertedAccountUploadListView.as_view()),
    path("retail-allocated-portfolio/upload-csv/",        lv.RetailAllocatedPortfolioUploadCsvView.as_view()),
    path("retail-allocated-portfolio/uploads/",           lv.RetailAllocatedPortfolioUploadListView.as_view()),
]
