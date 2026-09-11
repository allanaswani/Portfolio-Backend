from django.urls import path

from . import alert_views as av
from . import views as v
from .ingest import IngestView

urlpatterns = [
    # Audit trail — reads the simple_history tables that already exist, plus
    # the events other systems push to ingest/.
    path("audit/feed/",     v.AuditFeedView.as_view()),
    path("audit/models/",   v.AuditModelsView.as_view()),
    path("audit/summary/",  v.AuditSummaryView.as_view()),
    path("audit/record/",   v.AuditRecordHistoryView.as_view()),

    # Data health — is every warehouse table present, populated and fresh.
    path("data-health/",    v.DataHealthView.as_view()),

    # Performance / uptime — from the request-metrics middleware + heartbeats.
    path("performance/overview/",  v.PerformanceOverviewView.as_view()),
    path("performance/series/",    v.PerformanceSeriesView.as_view()),
    path("performance/endpoints/", v.PerformanceEndpointsView.as_view()),
    path("performance/errors/",    v.PerformanceErrorsView.as_view()),
    path("performance/uptime/",    v.UptimeView.as_view()),
    path("performance/active-users/", v.ActiveUsersView.as_view()),

    # Other systems — Customer 360 and anything else worth watching.
    path("services/",               av.MonitoredServiceListView.as_view()),
    path("services/status/",        av.ServiceStatusView.as_view()),
    path("services/<int:pk>/",      av.MonitoredServiceDetailView.as_view()),
    path("services/<int:pk>/token/", av.MonitoredServiceTokenView.as_view()),

    # Alerting — who is told, what is currently wrong, and a way to prove the
    # mail path works before an outage is the thing that tests it.
    path("alerts/recipients/",           av.AlertRecipientListView.as_view()),
    path("alerts/recipients/<int:pk>/",  av.AlertRecipientDetailView.as_view()),
    path("alerts/state/",                av.AlertStateListView.as_view()),
    path("alerts/test/",                 av.AlertTestView.as_view()),

    # Where another system posts its own audit events and table health.
    # Authenticated by a service token, not a user session.
    path("ingest/", IngestView.as_view()),
]
