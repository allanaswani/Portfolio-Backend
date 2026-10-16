from django.urls import path
from . import views

urlpatterns = [
    path("collections/", views.CollectionListCreateView.as_view()),
    path("collections/summary/", views.CollectionsFeedbackSummaryView.as_view()),
    path("collections/search/", views.CollectionSearchView.as_view()),
    path("collections/<int:pk>/", views.CollectionDetailView.as_view()),

    # PTP - Promise To Pay. The status is settled against loan_repayments and
    # is not writable: a collector cannot mark their own promise kept.
    path("ptp/", views.PromiseToPayListCreateView.as_view()),
    path("ptp/summary/", views.PromiseToPaySummaryView.as_view()),
    path("ptp/refresh/", views.PromiseToPayRefreshView.as_view()),
    path("ptp/<int:pk>/", views.PromiseToPayDetailView.as_view()),

    # One customer, whole: bio, contacts, loans, product, collateral, bucket.
    path("customer/<int:cust_id>/", views.CustomerProfileView.as_view()),

    # What an officer is carrying and what they have brought in. Assignment
    # is loans.delay_officer - core banking's own field, already a sales code.
    path("officer/contribution/", views.OfficerContributionView.as_view()),
    path("officer/leaderboard/", views.OfficerLeaderboardView.as_view()),

    # Allocating the customers core banking left unassigned. Reports first;
    # writes only with confirm, and never into the warehouse table.
    path("allocation/", views.CollectionAllocationView.as_view()),

    # Dashboard (ported from the old backend)
    path("current_book_collection_summary/", views.CurrentBookCollectionSummaryView.as_view()),
    path("total_book_month_by_month_api/", views.TotalBookMonthByMonthView.as_view()),
    path("customer_collection_data_current_book_data_api/", views.CustomerCollectionDataCurrentBookView.as_view()),
    path("collections_contactibility_summary/", views.CollectionsContactibilitySummaryView.as_view()),
    path("collections_officer_feedback_summ_by_collection_status/", views.CollectionsOfficerFeedbackByStatusView.as_view()),
    path("collections_officer_feedback_summ_contactability/", views.CollectionsOfficerFeedbackContactabilityView.as_view()),
]
