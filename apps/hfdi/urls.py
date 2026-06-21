from django.urls import path
from core.script_trigger import ScriptTriggerAPIView
from . import views

urlpatterns = [
    # Projects
    path("projects/", views.ProjectListCreateView.as_view()),
    path("projects/<int:pk>/", views.ProjectDetailView.as_view()),

    # Targets (legacy model)
    path("targets/", views.TargetsListCreateView.as_view()),
    path("targets/<int:pk>/", views.TargetsDetailView.as_view()),

    # Sales (legacy model)
    path("sales/", views.SalesListCreateView.as_view()),
    path("sales/<int:pk>/", views.SalesDetailView.as_view()),

    # Obligations
    path("obligations/", views.ObligationSummaryListCreateView.as_view()),
    path("obligations/<int:pk>/", views.ObligationSummaryDetailView.as_view()),

    # CRM
    path("crm_projects/", views.CrmProjectListCreateView.as_view()),
    path("crm_projects/<int:pk>/", views.CrmProjectDetailView.as_view()),
    path("crm_sales/", views.CrmSalesRecordListCreateView.as_view()),
    path("crm_sales/<int:pk>/", views.CrmSalesRecordDetailView.as_view()),

    # Legacy
    path("legacy_projects/", views.LegacyProjectListCreateView.as_view()),
    path("legacy_projects/<int:pk>/", views.LegacyProjectDetailView.as_view()),
    path("legacy_sales/", views.LegacySalesRecordListCreateView.as_view()),
    path("legacy_sales/<int:pk>/", views.LegacySalesRecordDetailView.as_view()),

    # Manual finance
    path("manual_finance/", views.HfdiManualFinanceEntryListCreateView.as_view()),
    path("manual_finance/<int:pk>/", views.HfdiManualFinanceEntryDetailView.as_view()),

    # Performance targets
    path("performance_targets/", views.HfdiTargetsListCreateView.as_view()),
    path("performance_targets/<int:pk>/", views.HfdiTargetsDetailView.as_view()),

    # Employees (search + upload routes declared before <int:pk>)
    path("employees/", views.HfdiEmployeeDataListCreateView.as_view()),
    path("employees/search/", views.HfdiEmployeeDataSearchAPIView.as_view()),
    path("employees/upload-csv/", views.HfdiEmployeeDataCSVUploadView.as_view()),
    path("employees/<int:pk>/", views.HfdiEmployeeDataDetailView.as_view()),
    path("employee_sales/", views.HfdiEmployeeDataSalesRecordListCreateView.as_view()),
    path("employee_sales/search/", views.HfdiEmployeeDataSalesRecordSearchAPIView.as_view()),
    path("employee_sales/upload-csv/", views.HfdiEmployeeDataSalesRecordCSVUploadView.as_view()),
    path("employee_sales/<int:pk>/", views.HfdiEmployeeDataSalesRecordDetailView.as_view()),
    path("scorecard/", views.HfdiScorecardListCreateView.as_view()),
    path("scorecard/search/", views.HfdiScorecardSearchAPIView.as_view()),
    path("scorecard/upload-csv/", views.HfdiScorecardCSVUploadView.as_view()),
    path("scorecard/<int:pk>/", views.HfdiScorecardDetailView.as_view()),

    # Dashboard data — Weighted Dashboard (managed: full CRUD + search + upload)
    path("weighted_sales/", views.WeightedDashboardManualSalesListView.as_view()),
    path("weighted_sales/search/", views.WeightedDashboardManualSalesSearchAPIView.as_view()),
    path("weighted_sales/upload-csv/", views.WeightedDashboardManualSalesCSVUploadView.as_view()),
    path("weighted_sales/<int:pk>/", views.WeightedDashboardManualSalesDetailView.as_view()),

    # HFC Mortgages (managed: full CRUD + search + upload)
    path("mortgages/", views.HfdiCustomersHfcMortgagesListView.as_view()),
    path("mortgages/search/", views.HfdiCustomersHfcMortgagesSearchAPIView.as_view()),
    path("mortgages/upload-csv/", views.HfdiCustomersHfcMortgagesCSVUploadView.as_view()),
    path("mortgages/<int:pk>/", views.HfdiCustomersHfcMortgagesDetailView.as_view()),

    # Daily Collections + Inventory Sales (warehouse, read-only: list + search)
    path("daily_collections/", views.HfdiProjectsDailyCollectionsDataListView.as_view()),
    path("daily_collections/search/", views.HfdiProjectsDailyCollectionsDataSearchAPIView.as_view()),
    path("inventory_sales/", views.HfdiProjectsInventorySalesDataListView.as_view()),
    path("inventory_sales/search/", views.HfdiProjectsInventorySalesDataSearchAPIView.as_view()),

    # Affordable housing applications (+ search + upload)
    path("affordable_housing/", views.AffordableHousingApplicationListCreateView.as_view()),
    path("affordable_housing/search/", views.AffordableHousingApplicationSearchAPIView.as_view()),
    path("affordable_housing/upload-csv/", views.AffordableHousingApplicationCSVUploadView.as_view()),
    path("affordable_housing/<int:pk>/", views.AffordableHousingApplicationDetailView.as_view()),

    # Affordable housing registrations
    path("affordable_housing_registrations/", views.AffordableHousingRegistrationsListCreateView.as_view()),
    path("affordable_housing_registrations/search/", views.AffordableHousingRegistrationsSearchAPIView.as_view()),
    path("affordable_housing_registrations/upload-csv/", views.AffordableHousingRegistrationsCSVUploadView.as_view()),
    path("affordable_housing_registrations/<int:pk>/", views.AffordableHousingRegistrationsDetailView.as_view()),

    # Affordable housing projects pipeline
    path("affordable_housing_pipeline/", views.AffordableHousingProjectsPipelineListCreateView.as_view()),
    path("affordable_housing_pipeline/search/", views.AffordableHousingProjectsPipelineSearchAPIView.as_view()),
    path("affordable_housing_pipeline/upload-csv/", views.AffordableHousingProjectsPipelineCSVUploadView.as_view()),
    path("affordable_housing_pipeline/<int:pk>/", views.AffordableHousingProjectsPipelineDetailView.as_view()),

    # AFH seller mapping
    path("afh_seller_mapping/", views.AFHSellerMappingListCreateView.as_view()),
    path("afh_seller_mapping/search/", views.AFHSellerMappingSearchAPIView.as_view()),
    path("afh_seller_mapping/upload-csv/", views.AFHSellerMappingCSVUploadView.as_view()),
    path("afh_seller_mapping/<int:pk>/", views.AFHSellerMappingDetailView.as_view()),

    # ══════════════════════════════════════════════════════════════════════════
    # Frontend-contract aliases — exact paths the portfolio-management-frontend
    # hooks call (these mirror the OLD backend's URL scheme). They point at the
    # same views as the canonical routes above so the existing frontend works.
    # ══════════════════════════════════════════════════════════════════════════

    # Affordable housing applications
    path("affordable-housing-applications/", views.AffordableHousingApplicationListCreateView.as_view()),
    path("affordable-housing-applications/search/", views.AffordableHousingApplicationSearchAPIView.as_view()),
    path("affordable-housing-applications/upload-csv/", views.AffordableHousingApplicationCSVUploadView.as_view()),
    path("affordable-housing-applications/trigger-script/", ScriptTriggerAPIView.as_view()),
    path("affordable-housing-applications/<int:pk>/", views.AffordableHousingApplicationDetailView.as_view()),

    # Affordable housing registrations
    path("affordable-housing-registrations/", views.AffordableHousingRegistrationsListCreateView.as_view()),
    path("affordable-housing-registrations/search/", views.AffordableHousingRegistrationsSearchAPIView.as_view()),
    path("affordable-housing-registrations/upload-csv/", views.AffordableHousingRegistrationsCSVUploadView.as_view()),
    path("affordable-housing-registrations/<int:pk>/", views.AffordableHousingRegistrationsDetailView.as_view()),

    # Affordable housing projects pipeline
    path("affordable-housing-projects-pipeline/", views.AffordableHousingProjectsPipelineListCreateView.as_view()),
    path("affordable-housing-projects-pipeline/search/", views.AffordableHousingProjectsPipelineSearchAPIView.as_view()),
    path("affordable-housing-projects-pipeline/upload-csv/", views.AffordableHousingProjectsPipelineCSVUploadView.as_view()),
    path("affordable-housing-projects-pipeline/<int:pk>/", views.AffordableHousingProjectsPipelineDetailView.as_view()),

    # AFH seller mapping
    path("afh-seller-mapping/", views.AFHSellerMappingListCreateView.as_view()),
    path("afh-seller-mapping/search/", views.AFHSellerMappingSearchAPIView.as_view()),
    path("afh-seller-mapping/upload-csv/", views.AFHSellerMappingCSVUploadView.as_view()),
    path("afh-seller-mapping/<int:pk>/", views.AFHSellerMappingDetailView.as_view()),

    # HFC mortgages (frontend path)
    path("hfdi_customers_hfc_mortgages/", views.HfdiCustomersHfcMortgagesListView.as_view()),
    path("hfdi_customers_hfc_mortgages/search/", views.HfdiCustomersHfcMortgagesSearchAPIView.as_view()),
    path("hfdi_customers_hfc_mortgages/upload-csv/", views.HfdiCustomersHfcMortgagesCSVUploadView.as_view()),
    path("hfdi_customers_hfc_mortgages/<int:pk>/", views.HfdiCustomersHfcMortgagesDetailView.as_view()),

    # Weighted dashboard manual sales (frontend path)
    path("weighted-dashboard-manual-sales/", views.WeightedDashboardManualSalesListView.as_view()),
    path("weighted-dashboard-manual-sales/search/", views.WeightedDashboardManualSalesSearchAPIView.as_view()),
    path("weighted-dashboard-manual-sales/upload-csv/", views.WeightedDashboardManualSalesCSVUploadView.as_view()),
    path("weighted-dashboard-manual-sales/<int:pk>/", views.WeightedDashboardManualSalesDetailView.as_view()),

    # Daily collections + inventory sales (frontend paths) + inventory trigger-script
    path("hfdi_projects_daily_collections_data/", views.HfdiProjectsDailyCollectionsDataListView.as_view()),
    path("hfdi_projects_daily_collections_data/search/", views.HfdiProjectsDailyCollectionsDataSearchAPIView.as_view()),
    path("hfdi_projects_inventory_sales_data/", views.HfdiProjectsInventorySalesDataListView.as_view()),
    path("hfdi_projects_inventory_sales_data/search/", views.HfdiProjectsInventorySalesDataSearchAPIView.as_view()),
    path("hfdi_projects_inventory_sales_data/trigger-script/", ScriptTriggerAPIView.as_view()),

    # Employees (frontend paths)
    path("hfdi_employee_data/", views.HfdiEmployeeDataListCreateView.as_view()),
    path("hfdi_employee_data/search/", views.HfdiEmployeeDataSearchAPIView.as_view()),
    path("hfdi_employee_data/<int:pk>/", views.HfdiEmployeeDataDetailView.as_view()),

    # Employee sales (frontend uses /upload/, not /upload-csv/)
    path("hfdi_employee_sales_data/", views.HfdiEmployeeDataSalesRecordListCreateView.as_view()),
    path("hfdi_employee_sales_data/search/", views.HfdiEmployeeDataSalesRecordSearchAPIView.as_view()),
    path("hfdi_employee_sales_data/upload/", views.HfdiEmployeeDataSalesRecordCSVUploadView.as_view()),
    path("hfdi_employee_sales_data/<int:pk>/", views.HfdiEmployeeDataSalesRecordDetailView.as_view()),

    # Employee scorecard performance (frontend uses /upload/)
    path("hfdi_employee_scorecard_performance_data/", views.HfdiScorecardListCreateView.as_view()),
    path("hfdi_employee_scorecard_performance_data/search/", views.HfdiScorecardSearchAPIView.as_view()),
    path("hfdi_employee_scorecard_performance_data/upload/", views.HfdiScorecardCSVUploadView.as_view()),
    path("hfdi_employee_scorecard_performance_data/<int:pk>/", views.HfdiScorecardDetailView.as_view()),

    # ── CRUD aliases (frontend paths → existing model views) ──────────────────
    path("hfdi_target_feedback/", views.TargetsListCreateView.as_view()),
    path("hfdi_target_feedback/<int:pk>/", views.TargetsDetailView.as_view()),
    path("hfdi_sales_data/", views.SalesListCreateView.as_view()),
    path("hfdi_sales_data/<int:pk>/", views.SalesDetailView.as_view()),
    path("obligation_summary/", views.ObligationSummaryListCreateView.as_view()),
    path("obligation_summary/<int:pk>/", views.ObligationSummaryDetailView.as_view()),
    path("hfdi_crm_projects/", views.CrmProjectListCreateView.as_view()),
    path("hfdi_crm_projects/<int:pk>/", views.CrmProjectDetailView.as_view()),
    path("hfdi_crm_sales-records/", views.CrmSalesRecordListCreateView.as_view()),
    path("hfdi_crm_sales-records/<int:pk>/", views.CrmSalesRecordDetailView.as_view()),
    path("hfdi_sales_legacy/", views.LegacySalesRecordListCreateView.as_view()),
    path("hfdi_sales_legacy/<int:pk>/", views.LegacySalesRecordDetailView.as_view()),
    path("hfdi_manual_finance-entries/", views.HfdiManualFinanceEntryListCreateView.as_view()),
    path("hfdi_manual_finance-entries/<int:pk>/", views.HfdiManualFinanceEntryDetailView.as_view()),
    path("hfdi-targets/", views.HfdiTargetsListCreateView.as_view()),
    path("hfdi-targets/<int:pk>/", views.HfdiTargetsDetailView.as_view()),

    # ── Dashboard aggregation / chart endpoints ───────────────────────────────
    path("hfdi_sales_months_recorded/", views.HfdiSalesMonthsRecordedView.as_view()),
    path("projects_monthly_performance_hfdi_list/", views.ProjectsMonthlyPerformanceView.as_view()),
    path("hfdi_api_sales_data_monthly_volume_sumary_api_data/", views.HfdiMonthlyVolumeSummaryView.as_view()),
    path("hfdi_api_sales_data_monthly_value_sumary_api_data/", views.HfdiMonthlyValueSummaryView.as_view()),
    path("hfdi_api_sales_data_monthly_ytd_income_sumary_api_data/", views.HfdiMonthlyYtdIncomeSummaryView.as_view()),
    path("hfdi-ytd_performance_hfdi_list/", views.HfdiYtdPerformanceView.as_view()),
    path("hfdi-ytd_performance_hfdi_list_per_project/", views.HfdiYtdPerformancePerProjectView.as_view()),
    path("hfdi-combined-projects-list/", views.CombinedProjectsView.as_view()),
]
