from django.urls import path
from . import views
from . import reallocation_views as rv

urlpatterns = [
    # ══ Reallocation workflow (exact frontend-contract paths) ══════════════════
    # Transfer actions on a customer
    path("customer/<str:cust_id>/transfer/", rv.InitiateTransfer.as_view()),
    path("customer/<str:cust_id>/tl_reallocate/", rv.TeamLeaderInitiateCustomerRMTransfer.as_view()),
    path("customer/<str:cust_id>/transfer/<int:transfer_id>/approve/", rv.ApproveTransfer.as_view()),
    path("customer/<str:cust_id>/transfer/<int:transfer_id>/team-leader-approve/", rv.TeamLeaderApproveTransfer.as_view()),
    path("customer/<str:cust_id>/transfer/<int:transfer_id>/reject/", rv.RejectTransfer.as_view()),
    path("customer/<str:cust_id>/transfer-history/", rv.TransferHistory.as_view()),
    path("customer/<str:cust_id>/", rv.CustomerAllocationByCustIdView.as_view()),

    # Worklists
    path("transfer/open/", rv.OpenTransferHistoryView.as_view()),
    path("transfers/from/", rv.FromOpenTransferHistoryView.as_view()),
    path("transfers/to/", rv.ToOpenTransferHistoryView.as_view()),
    path("transfers/approved/", rv.ApprovedTransferHistoryView.as_view()),
    path("transfers/rejected/", rv.RejectedTransferHistoryView.as_view()),
    path("transfers/tl_reallocations/", rv.TLReallocationTransferHistoryView.as_view()),

    # Lookups
    path("filter-customer/", rv.FilterCustomerAllocationBaseView.as_view()),
    path("rm_list/", rv.RmAllocationListView.as_view()),

    # Feedback (transfer records) CRUD + history
    path("feedback/<int:pk>/", rv.TransferFeedbackDetailView.as_view()),
    path("feedback/<int:pk>/history/", rv.TransferFeedbackHistoryView.as_view()),

    # Bulk load + EXCO strategy override
    path("api/csv-upload/", rv.CustomerAllocationBaseCSVUploadView.as_view()),
    path("api/update-portfolio-allocation/", rv.PortfolioAllocationUpdateView.as_view()),

    path("customer_enrichment/", views.CustomerEnrichmentListCreateView.as_view()),
    path("customer_enrichment/<int:pk>/", views.CustomerEnrichmentDetailView.as_view()),
    path("rm_targets/", views.RmTargetListCreateView.as_view()),
    path("rm_targets/<int:pk>/", views.RmTargetDetailView.as_view()),

    # Customer–RM reallocation
    path("customer_allocation_base/", views.CustomerAllocationBaseListCreateView.as_view()),
    path("customer_allocation_base/search/", views.CustomerAllocationBaseSearchAPIView.as_view()),
    path("customer_allocation_base/upload-csv/", views.CustomerAllocationBaseCSVUploadView.as_view()),
    path("customer_allocation_base/<int:pk>/", views.CustomerAllocationBaseDetailView.as_view()),

    path("rm_allocation_list/", views.RmAllocationListListCreateView.as_view()),
    path("rm_allocation_list/search/", views.RmAllocationListSearchAPIView.as_view()),
    path("rm_allocation_list/upload-csv/", views.RmAllocationListCSVUploadView.as_view()),
    path("rm_allocation_list/<int:pk>/", views.RmAllocationListDetailView.as_view()),

    path("movement_approvers/", views.TeamLeaderMovementApproversListCreateView.as_view()),
    path("movement_approvers/search/", views.TeamLeaderMovementApproversSearchAPIView.as_view()),
    path("movement_approvers/upload-csv/", views.TeamLeaderMovementApproversCSVUploadView.as_view()),
    path("movement_approvers/<int:pk>/", views.TeamLeaderMovementApproversDetailView.as_view()),

    path("customer_transfer_history/", views.CustomerTransferHistoryListCreateView.as_view()),
    path("customer_transfer_history/search/", views.CustomerTransferHistorySearchAPIView.as_view()),
    path("customer_transfer_history/<int:pk>/", views.CustomerTransferHistoryDetailView.as_view()),
]
