from django.urls import path
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

    # Employees
    path("employees/", views.HfdiEmployeeDataListCreateView.as_view()),
    path("employees/<int:pk>/", views.HfdiEmployeeDataDetailView.as_view()),
    path("employee_sales/", views.HfdiEmployeeDataSalesRecordListCreateView.as_view()),
    path("employee_sales/<int:pk>/", views.HfdiEmployeeDataSalesRecordDetailView.as_view()),
    path("scorecard/", views.HfdiScorecardListCreateView.as_view()),
    path("scorecard/<int:pk>/", views.HfdiScorecardDetailView.as_view()),

    # Dashboard data
    path("weighted_sales/", views.WeightedDashboardManualSalesListView.as_view()),
    path("mortgages/", views.HfdiCustomersHfcMortgagesListView.as_view()),
    path("daily_collections/", views.HfdiProjectsDailyCollectionsDataListView.as_view()),
    path("inventory_sales/", views.HfdiProjectsInventorySalesDataListView.as_view()),

    # Affordable housing
    path("affordable_housing/", views.AffordableHousingApplicationListCreateView.as_view()),
    path("affordable_housing/<int:pk>/", views.AffordableHousingApplicationDetailView.as_view()),
]
