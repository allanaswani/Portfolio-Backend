from django.urls import path
from . import views

urlpatterns = [
    path("loan-repayments/", views.LoanRepaymentsListView.as_view()),
    path("loan-repayments/<int:pk>/", views.LoanRepaymentsDetailView.as_view()),

    # Dashboard (ported from the old backend, team-leader scoped)
    path("current_book_rm_summary/", views.TLCurrentBookRmSummaryView.as_view()),
    path("team_leader_current_book_rm_summary_api/", views.TLTeamLeaderCurrentBookRmSummaryView.as_view()),
    path("total_book_month_by_month_api/", views.TLTotalBookMonthByMonthView.as_view()),
    path("total_book_by_bucket_collection_summary/", views.TLTotalBookByBucketSummaryView.as_view()),
    path("customer_collection_data_current_book_data_api/", views.TLCustomerCollectionDataView.as_view()),
    # Frontend calls this one WITHOUT a trailing slash — match it exactly.
    path("repayment_data_eom_api_per_delay_officer_team_leader", views.TLRepaymentDataEomView.as_view()),
    path("collections/", views.TLCollectionsFeedbackView.as_view()),
]
