from django.urls import path
from . import views
from .. import audit_views, cx_views, training_views, workbook_views

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
    # Signing is one button beside a long page and people press it before they
    # meant to. Withdrawing is allowed while the signature is still only
    # yours - see the view for why that is where the line is.
    path("my-card/unsign/", views.ScorecardUnsignView.as_view()),
    path("my-card/download/", views.ScorecardDownloadView.as_view()),

    # Loading the workbooks. Both read and report first; only a second call
    # with apply=true writes, and the actuals upload then runs the scorecard
    # itself so the RM's card is current without a second action.
    path("upload-actuals/", views.ScorecardActualsUploadView.as_view()),
    path("upload-allocation/", views.ScorecardAllocationUploadView.as_view()),

    # Administration: the figures the system cannot compute - the survey, the
    # learning system, HR, Audit - plus any target the DMC load has no column
    # for. Admin only, because this is what everybody is measured on.
    path("manual-figures/", views.ScorecardManualRowsView.as_view()),
    path("manual-figures/template/", views.ScorecardManualTemplateView.as_view()),
    path("manual-figures/upload/", views.ScorecardManualUploadView.as_view()),
    path("manual-figures/entry/", views.ScorecardManualEntryView.as_view()),

    # The desk's own scorecard workbook. The command needs the file on the
    # host, and the workbook lives on somebody's laptop - which is the step
    # that stops it being used. This is the upload.
    path("manual-figures/workbook/",
         workbook_views.ScorecardWorkbookUploadView.as_view()),
    # The back-office template: a row per person per measure, so one upload
    # fills every back-office card rather than ten.
    path("manual-figures/bo-actuals/",
         workbook_views.BoActualsUploadView.as_view()),

    # The CX team's own screen. Contactability and CSAT used to arrive as an
    # Excel somebody e-mailed round, which is why two lines on every RM card
    # were unscoreable; this is where CX keep them instead.
    path("cx/", cx_views.CxMetricsView.as_view()),
    path("cx/upload/", cx_views.CxUploadView.as_view()),
    path("cx/entry/", cx_views.CxEntryView.as_view()),
    path("cx/segments/", cx_views.CxSegmentsView.as_view()),

    # HR's monthly training return. A training line sits on all 22 cards and
    # none of them could be scored before this - the figures were in a
    # workbook that went round by e-mail.
    path("training/", training_views.TrainingReturnsView.as_view()),
    path("training/upload/", training_views.TrainingUploadView.as_view()),

    # Internal Audit's branch return. Nine card lines across eight roles read
    # it, and none of them could be scored - the figures arrived as a short
    # table in a mail. Takes a paste as readily as a file: it is eight rows.
    path("audit/", audit_views.AuditReturnsView.as_view()),
    path("audit/upload/", audit_views.AuditUploadView.as_view()),
    path("audit/entry/", audit_views.AuditEntryView.as_view()),

    # Administration: what cards exist, who holds them, and anyone's card.
    # The cards were seeded and then lived only in the database; these are
    # where to look at them.
    path("cards/", views.ScorecardCatalogueView.as_view()),
    path("roster/", views.ScorecardRosterView.as_view()),
    path("card-for/", views.ScorecardForPersonView.as_view()),

    # Automation actions
    path("missing_actuals/refresh/", views.RefreshMissingActualsView.as_view()),
    path("run/", views.RunMonthlyScorecardView.as_view()),
]
