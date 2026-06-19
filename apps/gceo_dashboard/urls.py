from django.urls import path
from . import views

urlpatterns = [
    # Deposit movement
    path("monthly_movement/",           views.MonthlyMovementView.as_view()),
    path("loan_monthly_movement/",       views.LoanMonthlyMovementView.as_view()),
    path("latest-monthly/",              views.LatestMonthlyView.as_view()),
    path("latest-daily/",                views.LatestDailyView.as_view()),
    path("deposit_movement/",            views.DepositMovementView.as_view()),
    path("deposit_movement_daily/",      views.DepositMovementDailyView.as_view()),
    path("segment_daily_movement",       views.SegmentDailyMovementView.as_view()),
    path("daily_movement",               views.DailyMovementView.as_view()),
    path("deposit_movement_daily_current_day_percentag_growth", views.DepositGrowthPctView.as_view()),
    path("deposit_movement_by_segment",  views.DepositMovementBySegmentView.as_view()),

    # Loan movement
    path("loan_movement_by_segment/",    views.LoanMovementBySegmentView.as_view()),
    path("loans_movement_by_segment_trend", views.LoansBySegmentTrendView.as_view()),
    path("mobile_loans/",                views.MobileLoansView.as_view()),

    # Balance
    path("daily_balance_movement/",      views.DailyBalanceMovementView.as_view()),
    path("loan_daily_balance_movement/", views.LoanDailyBalanceMovementView.as_view()),

    # Customers
    path("customer_total/",              views.CustomerTotalView.as_view()),
    path("bank_customers_active",        views.ActiveCustomersView.as_view()),
    path("new_customer_base",            views.NewCustomerBaseView.as_view()),
    path("ytd_customer_base",            views.YtdCustomerBaseView.as_view()),
    path("new_customers_trends",         views.NewCustomerTrendsView.as_view()),
    path("customers_active_month_on_month", views.ActiveCustomersMoMView.as_view()),
    path("customers_active_digital_channles_month_on_month", views.DigitalChannelsMoMView.as_view()),
    path("customers/",                   views.CeoCustomersView.as_view()),

    # Digital channels
    path("transacting_activity/",        views.TransactingActivityView.as_view()),
    path("digital_customers/",           views.DigitalCustomersView.as_view()),
    path("digital_active_30_days",       views.DigitalActive30View.as_view()),

    # Revenue / Income
    path("nfi_income_movement",          views.NFIIncomeMovementView.as_view()),
    path("intrest_income_movement",      views.InterestIncomeMovementView.as_view()),
    path("intrest_expense_income_movement", views.InterestExpenseMovementView.as_view()),
    path("nfi_income_movement_trend",    views.NFITrendsView.as_view()),
    path("intrest_income_movement_trends", views.InterestIncomeTrendsView.as_view()),
    path("intrest_expense_income_movement_trends", views.InterestExpenseTrendsView.as_view()),
    path("target_tracker_nfi_expense_income", views.TargetTrackerNFIView.as_view()),
    path("revenue/",                     views.RevenueView.as_view()),

    # Product analytics
    path("product_per_customer_by_segment", views.ProductPerCustomerView.as_view()),
    path("product_inf_focus",            views.ProductINFFocusView.as_view()),

    # Staff
    path("staff_information/",           views.StaffInformationView.as_view()),
    path("staff_gender/",                views.StaffGenderView.as_view()),
    path("staff_department/",            views.StaffDepartmentView.as_view()),
    path("staff_grade/",                 views.StaffGradeView.as_view()),
    path("staff_years_service/",         views.StaffYearsServiceView.as_view()),
    path("staff_staff_projections/",     views.StaffProjectionsView.as_view()),
    path("staff_service_type_api/",      views.StaffServiceTypeView.as_view()),

    # Fixed Deposits
    path("fixed_deposits/list/",         views.CeoFixedDepositListView.as_view()),
    path("fixed_deposits/rate_bands/",   views.CeoFixedDepositRateBandsView.as_view()),
    path("fixed_deposits/expiry_timeline/", views.CeoFixedDepositExpiryView.as_view()),

    # Loan Arrears
    path("loans-arrears/",               views.CeoLoansArrearsView.as_view()),
    path("loans-arrears/summary/",       views.CeoLoansArrearsSummaryView.as_view()),
    path("loans-arrears/dpd_bucket/",    views.CeoLoansArrearsDPDView.as_view()),
    path("loans-arrears/loan_products/", views.CeoLoansArrearsProductsView.as_view()),

    # Branches & RMs
    path("branch_list/",                 views.BranchListView.as_view()),
    path("rmlist/",                      views.RMListView.as_view()),
    path("branch_deposit_trends/",       views.BranchDepositTrendsView.as_view()),
    path("branch_loan_trends/",          views.BranchLoanTrendsView.as_view()),
    path("top_customer_inflow/",         views.TopCustomerInflowView.as_view()),
    path("top_customer_outflow/",        views.TopCustomerOutflowView.as_view()),
    path("rm_ytd_movement/",             views.RMYTDMovementView.as_view()),

    # Transactions
    path("transactions/",                views.TransactionDiaryView.as_view()),
]
