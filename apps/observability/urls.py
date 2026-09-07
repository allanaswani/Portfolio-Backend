from django.urls import path

from . import views as v

urlpatterns = [
    # Audit trail — reads the simple_history tables that already exist.
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
]
