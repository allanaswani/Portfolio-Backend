from django.urls import path
from . import views

urlpatterns = [
    # KPI definitions
    path("kpis/", views.ScKpiListCreateView.as_view()),
    path("kpis/<int:pk>/", views.ScKpiDetailView.as_view()),

    # Roles
    path("roles/", views.ScRoleListCreateView.as_view()),
    path("roles/<int:pk>/", views.ScRoleDetailView.as_view()),

    # Role-KPI mappings
    path("role_kpi_mappings/", views.ScRoleKpiMappingListCreateView.as_view()),
    path("role_kpi_mappings/<int:pk>/", views.ScRoleKpiMappingDetailView.as_view()),

    # Performance actuals (inputs)
    path("performance_actuals/", views.ScEmployeePerformanceActualListCreateView.as_view()),
    path("performance_actuals/<int:pk>/", views.ScEmployeePerformanceActualDetailView.as_view()),

    # Computed monthly performance (outputs)
    path("monthly_performance/", views.ScEmployeeMonthlyPerformanceListView.as_view()),

    # Automation actions
    path("missing_actuals/refresh/", views.RefreshMissingActualsView.as_view()),
    path("run/", views.RunMonthlyScorecardView.as_view()),
]
