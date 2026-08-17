from django.urls import path
from . import views

urlpatterns = [
    # Customers
    path("customers/",                    views.BranchCustomerListView.as_view()),
    path("customers/search/",             views.BranchCustomerListSearchView.as_view()),
    path("customers/top/",                views.BranchTopCustomersView.as_view()),
    path("customers_allocated/",          views.BranchCustomerListAllocatedView.as_view()),
    path("customers_allocated/search/",   views.BranchCustomerListAllocatedSearchView.as_view()),
    path("customers_not_allocated/",      views.BranchCustomerListNotAllocatedView.as_view()),
    path("customers_not_allocated/search/", views.BranchCustomerListNotAllocatedSearchView.as_view()),
    path("customer_totals/",              views.BranchTotalCustomersView.as_view()),
    path("customer_per_segment/",         views.BranchCustomerPerSegmentView.as_view()),
    # EXCO/CEO drill-down into ANY branch by name (legacy BranchDash parity).
    path("customer_per_segment/<str:branch>", views.BranchCustomerPerSegmentView.as_view()),
    path("new_customers/",                views.BranchNewCustomersView.as_view()),

    # RM
    path("rmlist/",                       views.BranchRMListView.as_view()),

    # Deposits
    path("deposit_trends/",               views.BranchDepositTrendsView.as_view()),
    path("monthly_deposit_trends/",       views.BranchMonthlyDepositTrendsView.as_view()),
    path("deposit_portfolio/",            views.BranchDepositPortfolioView.as_view()),

    # Loans
    path("loan_trends/",                  views.BranchLoanTrendsView.as_view()),
    path("monthly_loan_trends/",          views.BranchMonthlyLoanTrendsView.as_view()),
    path("loan_portfolio/",               views.BranchLoanPortfolioView.as_view()),

    # Revenue
    path("branch_revenue/",               views.BranchRevenueView.as_view()),
    path("overall_ytd_revenue_performance/", views.BranchYTDRevenuePerformanceView.as_view()),

    # Movements
    path("rm_deposit_movement_ytd/",      views.BranchRMDepositMovementYTDView.as_view()),
    path("rm_deposit_movement_ytd/<str:branch>", views.BranchRMDepositMovementYTDView.as_view()),
    path("top_customers_inflow_dtd/",     views.BranchTopInflowDTDView.as_view()),
    path("top_customers_inflow_dtd/<str:branch>",  views.BranchTopInflowDTDView.as_view()),
    path("top_customers_outflow_dtd/",    views.BranchTopOutflowDTDView.as_view()),
    path("top_customers_outflow_dtd/<str:branch>", views.BranchTopOutflowDTDView.as_view()),
    path("top_customers_inflow_ytd/",     views.BranchTopInflowYTDView.as_view()),
    path("top_customers_outflow_ytd/",    views.BranchTopOutflowYTDView.as_view()),

    # PPC / Summary
    path("ppc/",                          views.BranchPPCView.as_view()),
    path("dashboard_summary/",            views.BranchDashboardSummaryView.as_view()),

    # NPL & Arrears
    path("npl_summary/",                  views.BranchNPLSummaryView.as_view()),
    path("loans-arrears/summary/",        views.BranchLoansArrearsSummaryView.as_view()),
    path("loans-arrears/list/",           views.BranchLoansArrearsListView.as_view()),
    path("loans-arrears/list/search/",    views.BranchLoansArrearsListSearchView.as_view()),
    path("loans-arrears/dpd_bucket/",     views.BranchLoansArrearsDPDView.as_view()),
    path("loans-arrears/loan_products/",  views.BranchLoansArrearsProductsView.as_view()),

    # Fixed Deposits
    path("fixed_deposits/list/",          views.BranchFixedDepositListView.as_view()),

    # Feedback / Prospects
    path("branch_feedback/",              views.BranchFeedbackView.as_view()),
    path("feedback/",                     views.BranchFeedbackView.as_view()),
    path("prospects/",                    views.BranchProspectsView.as_view()),

    # Profile
    path("profile/",                      views.BranchProfileView.as_view()),

    # Property Holdings ("amounts sold" — org-wide today, see views.py note)
    path("property_holdings/summary/",    views.BranchPropertyHoldingsSummaryView.as_view()),
    path("property_holdings/by_project/", views.BranchPropertyHoldingsByProjectView.as_view()),
    path("property_holdings/list/",       views.BranchPropertyHoldingsListView.as_view()),
]
