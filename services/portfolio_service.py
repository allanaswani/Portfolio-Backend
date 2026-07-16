"""
Portfolio service layer — encapsulates all raw SQL queries from old backend's core/core.py.
Views call these functions; no logic lives in views.
"""
from datetime import datetime

from django.db import connection
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


def deposit_trends_data(sales_code):
    """RM deposit trends — per-account deposit balance rows for an RM's book, with
    the month-end balance columns the frontend aggregator expects (customer_segment +
    mon_YY_bal + yester_1/2_bal). Verbatim port of old core.deposit_trends_data();
    the old deposit_trends/ endpoint serves THIS, not portfolio_rm_deposit_trends."""
    ybl = str(current_year - 2)[-2:]
    py = str(previous_year)[-2:]
    cy = str(current_year)[-2:]
    sql = f"""
        SELECT id::text, cust_cif::text, acc_num::text, brn_code::text, prod_id::text,
               customer_segment::text, financial_sector::text, activity_sector::text, segment_code::text,
               dec_{ybl}_bal::text,
               mar_{py}_bal::text, jun_{py}_bal::text, sep_{py}_bal::text, dec_{py}_bal::text,
               jan_{cy}_bal::text, feb_{cy}_bal::text, mar_{cy}_bal::text, apr_{cy}_bal::text,
               may_{cy}_bal::text, jun_{cy}_bal::text, jul_{cy}_bal::text, aug_{cy}_bal::text,
               sep_{cy}_bal::text, oct_{cy}_bal::text, nov_{cy}_bal::text, dec_{cy}_bal::text,
               yester_2_bal::text, yester_1_bal::text, rm_code::text, diaspora_check::text,
               open_date::text, sale_code::text, full_name::text
        FROM daily_balance_movement
        WHERE trim(rm_code) = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [sales_code])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def rm_revenue(sales_code):
    return list(PortfolioRmRevenue.objects.filter(sales_code=sales_code).values())


def loan_trends_data(sales_code):
    """RM loan trends — per-account loan balance rows for an RM's book, with the
    month-end balance columns the frontend aggregator expects (customer_segment +
    mon_YY_bal + yester_1/2_bal). Verbatim port of old core.loan_trends_data()."""
    ybl = str(current_year - 2)[-2:]
    py = str(previous_year)[-2:]
    cy = str(current_year)[-2:]
    sql = f"""
        SELECT id::text, cust_cif::text, acc_num::text, brn_code::text, prod_id::text,
               customer_segment::text, financial_sector::text, activity_sector::text, segment_code::text,
               dec_{ybl}_bal::text,
               mar_{py}_bal::text, jun_{py}_bal::text, sep_{py}_bal::text, dec_{py}_bal::text,
               jan_{cy}_bal::text, feb_{cy}_bal::text, mar_{cy}_bal::text, apr_{cy}_bal::text,
               may_{cy}_bal::text, jun_{cy}_bal::text, jul_{cy}_bal::text, aug_{cy}_bal::text,
               sep_{cy}_bal::text, oct_{cy}_bal::text, nov_{cy}_bal::text, dec_{cy}_bal::text,
               yester_2_bal::text, yester_1_bal::text, rm_code::text, diaspora_check::text,
               open_date::text, sale_code::text, full_name::text
        FROM loan_daily_balance_movement
        WHERE trim(rm_code) = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [sales_code])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


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


def ppc(sales_code):
    """RM products-per-customer → {ppc} (old core.ppc)."""
    qs = RetailAllocatedPortfolio.objects.raw('''
        WITH ppc_calc AS (
            SELECT DISTINCT ON (hf.cust_id) hf.cust_id AS cust, fd, ca, internal, mobile, mortagage, sa
            FROM hf_customer hf
            LEFT JOIN phone_number pn ON hf.cust_id = pn.cust_id
            LEFT JOIN retail_allocated_portfolio rap ON hf.cust_id = rap.cust_id
            WHERE 1 = 1 AND rap.sales_code = %s
        )
        SELECT 1 AS id,
               Count(DISTINCT cust) AS number_of_customers,
               SUM((CASE WHEN fd >= 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN ca >= 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN sa::NUMERIC >= 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN (mortagage >= 1) THEN 1 ELSE 0 END))::NUMERIC
               / NULLIF(Count(cust)::NUMERIC, 0) AS ppc
        FROM ppc_calc
    ''', [sales_code])
    rows = list(qs)
    return {"ppc": rows[0].ppc} if rows else {"ppc": 0}


def top_ftp_customers_for_rm(sales_code):
    """Top-10 customers by FTP revenue for an RM → [{cust_cif, customer_name, revenue_value}]."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT ftp.cust_cif, rap.customer_name, ftp.total_ftp AS revenue_value
            FROM cust_monthly_ftp ftp
            JOIN retail_allocated_portfolio rap ON ftp.cust_cif = rap.cust_id
            WHERE rap.sales_code = %s
              AND ftp.current_year = EXTRACT(YEAR FROM CURRENT_DATE)
            ORDER BY ftp.total_ftp DESC
            LIMIT 10
        """, [sales_code])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def top_loan_loss_customers_for_rm(sales_code):
    """Top-10 customers by loan loss for an RM → [{cust_code_strategy, customer_name, revenue_value}]."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT l.cust_code_strategy, l.customer_name,
                   -SUM(COALESCE(l.pl_charge, 0) - COALESCE(l.int_adj, 0)) AS revenue_value
            FROM loans_mom_ifrs_movement l
            JOIN retail_allocated_portfolio rap ON l.cust_code_strategy = CAST(rap.cust_id AS VARCHAR)
            WHERE rap.sales_code = %s
              AND EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
              AND cust_code_strategy ~ '^[0-9]+$'
            GROUP BY l.cust_code_strategy, l.customer_name
            ORDER BY revenue_value ASC
            LIMIT 10
        """, [sales_code])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def top_10_customers_per_income_category_for_rm(sales_code):
    """Top-10 customers per income_category for an RM → {category: [{cust_id, customer_name, revenue_value}]}."""
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT income_category FROM revenue")
        categories = [row[0] for row in cur.fetchall()]
        result = {}
        for category in categories:
            order = "ASC" if category == "interest_expenses" else "DESC"
            cur.execute(f"""
                SELECT r.cust_id, rap.customer_name, SUM(r.sum_dc) AS revenue_value
                FROM revenue r
                JOIN retail_allocated_portfolio rap ON r.cust_id = rap.cust_id
                WHERE rap.sales_code = %s AND r.income_category = %s
                GROUP BY r.cust_id, rap.customer_name
                ORDER BY revenue_value {order}
                LIMIT 10
            """, [sales_code, category])
            cols = [c[0] for c in cur.description]
            result[category] = [dict(zip(cols, row)) for row in cur.fetchall()]
        return result
