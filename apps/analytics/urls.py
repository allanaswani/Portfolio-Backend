from django.urls import path
from . import views

urlpatterns = [
    path("snapshots/", views.AnalyticsSnapshotListView.as_view()),
    path("portfolio_summary/", views.PortfolioSummaryView.as_view()),
    path("deposits_by_segment/", views.DepositsBySegmentView.as_view()),
    path("loans_by_product/", views.LoansByProductView.as_view()),
    path("staff_summary/", views.StaffSummaryView.as_view()),
]
