"""
Portfolio service layer — encapsulates all raw SQL queries from old backend's core/core.py.
Views call these functions; no logic lives in views.
"""
from datetime import datetime

from apps.portfolio.models import (
    HfCustomer, RetailAllocatedPortfolio, Prospects, Feedback, Loans,
    Accounts, AccountsHistory, PortfolioRmDepositTrends, PortfolioRmRevenue,
    LoansMomIFRSMovement,
)

# Grace-period year resolution mirrored from old backend
_now = datetime.now()
current_year = (_now.year - 1) if (_now.month == 1 and _now.day < 10) else _now.year
previous_year = current_year - 1


def customers(sales_code):
    return HfCustomer.objects.raw(
        """
        WITH retail_allocation AS (
            SELECT rap.cust_id, customer_name, sales_code, total_revenue,
                   total_depost_balance, total_loans, active,
                   ROW_NUMBER() OVER (PARTITION BY rap.cust_id ORDER BY rap.cust_id ASC) AS rn
            FROM retail_allocated_portfolio AS rap
            INNER JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE TRIM(rap.sales_code) = %s
        )
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
        """,
        [sales_code],
    )


def branch_customers(branch):
    return HfCustomer.objects.raw(
        """
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name,
                   total_revenue, total_depost_balance, total_loans, active,
                   ROW_NUMBER() OVER (PARTITION BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM hf_customer AS pn
            LEFT OUTER JOIN retail_allocated_portfolio AS rap ON pn.cust_id = rap.cust_id
            WHERE pn.branch = %s
        )
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
        """,
        [branch],
    )


def rM_total_customers(sales_code):
    qs = RetailAllocatedPortfolio.objects.raw(
        """
        SELECT 1 id, sales_code,
               COUNT(DISTINCT hf_customer.cust_id) FILTER (WHERE hf_customer.active = TRUE) AS active_customers,
               COUNT(DISTINCT hf_customer.cust_id) AS total_customers
        FROM hf_customer
        LEFT JOIN retail_allocated_portfolio rap ON hf_customer.cust_id = rap.cust_id
        WHERE sales_code = %s
        GROUP BY sales_code
        """,
        [sales_code],
    )
    rows = list(qs)
    if not rows:
        return {"id": 1, "sales_code": sales_code, "active_customers": 0, "total_customers": 0}
    x = rows[0]
    return {
        "id": x.id,
        "sales_code": x.sales_code,
        "active_customers": x.active_customers,
        "total_customers": x.total_customers,
    }


def rm_deposit_trends(sales_code):
    return list(PortfolioRmDepositTrends.objects.filter(sales_code=sales_code).values())


def rm_revenue(sales_code):
    return list(PortfolioRmRevenue.objects.filter(sales_code=sales_code).values())


def customer_loans(cust_id):
    return Loans.objects.filter(cust_id=cust_id)


def customer_accounts(cust_id):
    return Accounts.objects.filter(cust_id=cust_id)


def customer_accounts_history(cust_id):
    return AccountsHistory.objects.filter(cust_id=cust_id)


def customer_feedback(cust_id):
    return Feedback.objects.filter(cust_id=cust_id)


def customer_fixed_deposits(sales_code):
    return Accounts.objects.filter(
        sales_code__iexact=sales_code,
        product_type__icontains="FD",
    ) if hasattr(Accounts, "sales_code") else Accounts.objects.filter(
        product_type__icontains="FD"
    )


def loans_mom_ifrs_movement_by_sales_code(sales_code):
    # Return all IFRS movement records — filtering by RM happens via cust_code_strategy
    return LoansMomIFRSMovement.objects.filter(cust_code_strategy=sales_code)


def loans_arrears_by_sales_code(sales_code):
    return Loans.objects.filter(
        account_officer=sales_code,
        days_in_arrears__gt=0,
    )
