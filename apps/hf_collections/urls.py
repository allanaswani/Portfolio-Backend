from django.urls import path
from . import views

urlpatterns = [
    path("collections/", views.CollectionListCreateView.as_view()),
    path("collections/summary/", views.CollectionsFeedbackSummaryView.as_view()),
    path("collections/search/", views.CollectionSearchView.as_view()),
    path("collections/<int:pk>/", views.CollectionDetailView.as_view()),

    # Dashboard (ported from the old backend)
    path("current_book_collection_summary/", views.CurrentBookCollectionSummaryView.as_view()),
    path("total_book_month_by_month_api/", views.TotalBookMonthByMonthView.as_view()),
    path("customer_collection_data_current_book_data_api/", views.CustomerCollectionDataCurrentBookView.as_view()),
    path("collections_contactibility_summary/", views.CollectionsContactibilitySummaryView.as_view()),
    path("collections_officer_feedback_summ_by_collection_status/", views.CollectionsOfficerFeedbackByStatusView.as_view()),
    path("collections_officer_feedback_summ_contactability/", views.CollectionsOfficerFeedbackContactabilityView.as_view()),
]
