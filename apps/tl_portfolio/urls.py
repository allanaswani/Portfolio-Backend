from django.urls import path
from . import views

urlpatterns = [
    # Customers
    path("customers/",                          views.TlCustomerListView.as_view()),
    path("customer_list_paginated/",            views.TlCustomerListPaginatedView.as_view()),
    path("customers/<int:pk>/",                 views.TlCustomerDetailView.as_view()),
    path("new_customers/",                      views.TlNewCustomersView.as_view()),
    path("new_customers_list/",                 views.TlNewCustomerListView.as_view()),
    path("customers_allocated/",                views.TlAllocatedCustomersView.as_view()),
    path("customers_unallocated/",              views.TlUnallocatedCustomersView.as_view()),

    # Summary
    path("customer_totals/",                    views.TlTotalCustomersView.as_view()),
    path("total_summary/",                      views.TlTotalSummaryView.as_view()),
    path("ppc/",                                views.TlPPCView.as_view()),

    # RM
    path("rmlist/",                             views.TlRMListView.as_view()),

    # Revenue
    path("segment_revenue/",                    views.TlSegmentRevenueView.as_view()),

    # Deposits
    path("deposit_trends/",                     views.TlDepositTrendsView.as_view()),
    path("monthly_deposit_trends/",             views.TlMonthlyDepositTrendsView.as_view()),

    # Loans
    path("loan_trends/",                        views.TlLoanTrendsView.as_view()),
    path("monthly_loan_trends/",                views.TlMonthlyLoanTrendsView.as_view()),

    # Movements
    path("rm_deposit_movement_ytd/",            views.TlRMDepositMovementYTDView.as_view()),
    path("top_customers_inflow_dtd/",           views.TlTopInflowDTDView.as_view()),
    path("top_customers_outflow_dtd/",          views.TlTopOutflowDTDView.as_view()),
    path("top_customers_inflow_ytd/",           views.TlTopInflowYTDView.as_view()),
    path("top_customers_outflow_ytd/",          views.TlTopOutflowYTDView.as_view()),

    # Arrears
    path("loans-arrears/summary/",              views.TlLoansArrearsSummaryView.as_view()),
    path("loans-arrears/list/",                 views.TlLoansArrearsListView.as_view()),
    path("loans-arrears/dpd_bucket/",           views.TlLoansArrearsDPDView.as_view()),
    path("loans-arrears/loan_products/",        views.TlLoansArrearsProductsView.as_view()),

    # Fixed Deposits
    path("fixed_deposits/list/",                views.TlFixedDepositListView.as_view()),

    # Feedback
    path("feedback/",                           views.TlFeedbackListView.as_view()),
    path("feedback_by_segment/",                views.TlSegmentFeedbackView.as_view()),
    path("feedback_by_lead/",                   views.TlFeedbackByLeadView.as_view()),
    path("contactability/",                     views.TlContactabilityView.as_view()),

    # Prospects
    path("prospects/",                          views.TlSegmentProspectsView.as_view()),

    # Profile
    path("profile/",                            views.TlProfileView.as_view()),
]
