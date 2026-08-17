from django.urls import path
from . import views

urlpatterns = [
    path("snapshots/", views.AnalyticsSnapshotListView.as_view()),
    path("portfolio_summary/", views.PortfolioSummaryView.as_view()),
    path("deposits_by_segment/", views.DepositsBySegmentView.as_view()),
    path("loans_by_product/", views.LoansByProductView.as_view()),
    path("staff_summary/", views.StaffSummaryView.as_view()),

    # Usage analytics (Administration): tracking ingest + admin-only aggregates
    path("activity/track/",        views.ActivityTrackView.as_view()),
    path("activity/last-logins/",  views.ActivityLastLoginsView.as_view()),
    path("activity/top-pages/",    views.ActivityTopPagesView.as_view()),
    path("activity/summary/",      views.ActivitySummaryView.as_view()),
    path("activity/recent/",       views.ActivityRecentView.as_view()),
]
