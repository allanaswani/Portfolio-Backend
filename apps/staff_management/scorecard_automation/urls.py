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

    # The signed-in person's own card, laid out as the card is.
    path("my-card/", views.ScorecardCardView.as_view()),

    # Signing freezes the figures; the download renders the signed copy when
    # there is one, and is marked unsigned when there is not.
    path("my-card/sign/", views.ScorecardSignView.as_view()),
    path("my-card/download/", views.ScorecardDownloadView.as_view()),

    # Loading the workbooks. Both read and report first; only a second call
    # with apply=true writes, and the actuals upload then runs the scorecard
    # itself so the RM's card is current without a second action.
    path("upload-actuals/", views.ScorecardActualsUploadView.as_view()),
    path("upload-allocation/", views.ScorecardAllocationUploadView.as_view()),

    # Automation actions
    path("missing_actuals/refresh/", views.RefreshMissingActualsView.as_view()),
    path("run/", views.RunMonthlyScorecardView.as_view()),
]
