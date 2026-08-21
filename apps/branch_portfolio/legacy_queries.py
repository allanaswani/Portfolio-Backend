"""Verbatim ports of the OLD backend's branch customer raw-SQL queries.

The redesigned frontend targets the OLD backend's exact response shapes, so these
reproduce the old `core.core` query functions 1:1 (same SQL, same output columns).
They run against the same physical tables (hf_customer, retail_allocated_portfolio,
revenue), so the SQL is copied unchanged. See apps/branch_portfolio/views.py for the
views that consume them and serialize with SegmentCustomerSerializer.
"""
from django.db import connection

from apps.portfolio.models import HfCustomer, RetailAllocatedPortfolio
from apps.gceo_dashboard.models import Revenue


def branch_new_customers_ytd(branch):
    """Count of a branch's customers who OPENED an account this year →
    {branch, new_customers}. Verbatim port of old core.branch_new_customers_ytd
    (accounts + customers.open_date; NOT hf_customer.date_time_created, which the
    view previously used and got wrong counts / zeros)."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT current_branch AS branch,
                   COUNT(DISTINCT hc.cust_id) AS new_customers
            FROM accounts a
            LEFT JOIN hf_customer hc ON a.cust_id = hc.cust_id
            LEFT JOIN customers c ON a.cust_id = c.cust_id
            WHERE current_branch = %s
              AND date_trunc('year', c.open_date) = date_trunc('year', now())
            GROUP BY current_branch
            """,
            [branch],
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows[0] if rows else {"branch": branch, "new_customers": 0}


def branch_customers(branch):
    """All customers whose hf_customer.branch matches EXACTLY (old: customer_list)."""
    return HfCustomer.objects.raw('''
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name, total_revenue,
                   total_depost_balance, total_loans, active,
                   Row_number() OVER (partition BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM   hf_customer AS pn
                   LEFT OUTER JOIN (
                       SELECT DISTINCT ON (cust_id) *
                       FROM retail_allocated_portfolio
                       WHERE cust_id IS NOT NULL
                       ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
                   ) rap ON pn.cust_id = rap.cust_id
            WHERE  pn.branch = %s)
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    ''', [branch])


def branch_customers_allocated(branch):
    """Customers allocated to an RM in the branch (old: branch_customers_allocated)."""
    branch_pattern = f"%{branch.strip()}%"
    return HfCustomer.objects.raw('''
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name, total_revenue,
                   total_depost_balance, total_loans, active,
                   Row_number() OVER (partition BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM   retail_allocated_portfolio AS rap
                   LEFT OUTER JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE  1=1 AND lower(trim(pn.branch)) LIKE lower(trim(%s)))
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    ''', [branch_pattern])


def branch_customers_not_allocated(branch):
    """Branch customers NOT allocated to any RM (old: branch_customers_not_allocated)."""
    branch_pattern = f"%{branch.strip()}%"
    return HfCustomer.objects.raw('''
        WITH retail_allocation AS (
            SELECT pn.cust_id, latin_surname as customer_name, sales_code, rm_name,
                   total_revenue, total_depost_balance, total_loans, active,
                   Row_number() OVER (partition BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM   retail_allocated_portfolio AS rap
                   RIGHT JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE  1=1 AND rap.cust_id is null AND lower(trim(pn.branch)) LIKE lower(trim(%s)))
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    ''', [branch_pattern])


def branch_customer_per_segment(branch):
    """Customers grouped by banking/main/segment with total & active counts
    (old: branch_customer_per_segment). Rows carry: banking_segment, main_segment,
    segment, total_customers, active_customers."""
    return RetailAllocatedPortfolio.objects.raw('''
        SELECT 1 AS id, banking_segment,
            CASE
                WHEN hf_customer.segment IN ('FINANCIAL INSTITUTIONS','INSTITUTIONAL BANKING','INTERNAL ACCOUNTS','PROJECT FINANCE','SCHEME') THEN 'banking'
                WHEN hf_customer.segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES') THEN 'BUSINESS BANKING'
                WHEN hf_customer.segment IN ('PRIVATE', 'ULTIMATE') THEN 'ULTIMATE'
                WHEN hf_customer.segment IN ('MASS', 'STANDARD') THEN 'PB'
                WHEN hf_customer.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL'
                ELSE 'others'
            END AS main_segment,
            CASE WHEN hf_customer.segment IS NULL THEN 'unsegmented' ELSE hf_customer.segment END AS segment,
            COUNT(DISTINCT hf_customer.cust_id) AS total_customers,
            COUNT(DISTINCT hf_customer.cust_id) FILTER (WHERE hf_customer.active = TRUE) AS active_customers
        FROM hf_customer
        LEFT JOIN (
            SELECT DISTINCT ON (cust_id) *
            FROM retail_allocated_portfolio
            WHERE cust_id IS NOT NULL
            ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
        ) rap ON hf_customer.cust_id = rap.cust_id
        WHERE 1 = 1 AND hf_customer.branch = %s
        GROUP BY banking_segment,
            CASE
                WHEN hf_customer.segment IN ('FINANCIAL INSTITUTIONS','INSTITUTIONAL BANKING','INTERNAL ACCOUNTS','PROJECT FINANCE','SCHEME') THEN 'banking'
                WHEN hf_customer.segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES') THEN 'BUSINESS BANKING'
                WHEN hf_customer.segment IN ('PRIVATE', 'ULTIMATE') THEN 'ULTIMATE'
                WHEN hf_customer.segment IN ('MASS', 'STANDARD') THEN 'PB'
                WHEN hf_customer.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL'
                ELSE 'others'
            END,
            CASE WHEN hf_customer.segment IS NULL THEN 'unsegmented' ELSE hf_customer.segment END
    ''', [branch])


def branch_revenues_query(branch):
    """YTD revenue by income category for the branch (old: branch_revenues_query).
    Rows carry: income_category, value."""
    return Revenue.objects.raw('''
        SELECT 1 as id, income_category, sum(sum_dc) as value
        FROM revenue r
            LEFT JOIN hf_customer hf ON hf.cust_id = r.cust_id
        WHERE date_trunc('year',tmstamp) = date_trunc('year',now())
            AND branch = %s
        GROUP BY income_category
    ''', [branch])
