"""
Portfolio service layer — encapsulates all raw SQL queries from old backend's core/core.py.
Views call these functions; no logic lives in views.
"""
from datetime import datetime
from decimal import Decimal

from django.db import connection
from django.db.models.functions import Lower, Trim
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
            -- pn.latin_surname is selected EXPLICITLY (not left to Django deferred
            -- loading): the frontend customer tables read latin_surname, and under
            -- the multi-DB router a deferred load on this RawQuerySet comes back
            -- null, which the UI renders as "-". Selecting it keeps the name present.
            SELECT rap.cust_id, pn.latin_surname, customer_name, sales_code, total_revenue,
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


def customers_revenue_list_for_rm(sales_code):
    """Per-customer REVENUE breakdown for an RM's book — the actual payload the
    /portfolio/customers/revenue-list/ page expects:
    cust_id, customer_name, interest_income, interest_expenses, nfi, ftp,
    loan_loss, total_revenue, revenue_date.

    Verbatim port of old core.customers_revenue_list_for_rm(). Do NOT confuse with
    customers() above — that returns deposit/loan BALANCES (total_depost_balance,
    total_loans) and was wrongly wired to this endpoint, which made every revenue
    column render as zero on the frontend."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                rap.cust_id,
                rap.customer_name,
                COALESCE(SUM(CASE WHEN r.income_category = 'interest_income' THEN r.sum_dc END), 0) AS interest_income,
                COALESCE(SUM(CASE WHEN r.income_category = 'interest_expenses' THEN r.sum_dc END), 0) AS interest_expenses,
                COALESCE(SUM(CASE WHEN r.income_category = 'nfi' THEN r.sum_dc END), 0) AS nfi,
                COALESCE(f.total_ftp, 0) AS ftp,
                COALESCE(ll.loan_loss, 0) AS loan_loss,
                (
                    COALESCE(SUM(CASE WHEN r.income_category = 'interest_income' THEN r.sum_dc END), 0) +
                    COALESCE(SUM(CASE WHEN r.income_category = 'interest_expenses' THEN r.sum_dc END), 0) +
                    COALESCE(SUM(CASE WHEN r.income_category = 'nfi' THEN r.sum_dc END), 0) +
                    COALESCE(f.total_ftp, 0) +
                    COALESCE(ll.loan_loss, 0)
                ) AS total_revenue,
                CURRENT_DATE AS revenue_date
            FROM retail_allocated_portfolio rap
            LEFT JOIN revenue r
                ON rap.cust_id = r.cust_id
                AND date_trunc('year', r.tmstamp) = date_trunc('year', now())
            LEFT JOIN (
                SELECT cust_cif, SUM(total_ftp) AS total_ftp
                FROM cust_monthly_ftp
                WHERE current_year = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY cust_cif
            ) f ON rap.cust_id = f.cust_cif
            LEFT JOIN (
                SELECT cust_code_strategy::int AS cust_id, -SUM(COALESCE(pl_charge, 0) - COALESCE(int_adj, 0)) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                AND cust_code_strategy ~ '^[0-9]+$'
                GROUP BY cust_code_strategy
            ) ll ON rap.cust_id = ll.cust_id
            WHERE rap.sales_code = %s
            GROUP BY rap.cust_id, rap.customer_name, f.total_ftp, ll.loan_loss
            ORDER BY total_revenue DESC
        """, [sales_code])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


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


def rm_customers_ytd(sales_code):
    """Total distinct customers ALLOCATED to an RM → {sales_code, current_customers}.
    Verbatim port of old core.rm_customers_ytd (feeds current_customers/). The old
    endpoint returned this single dict, NOT a list of customer objects."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT sales_code, COUNT(DISTINCT cust_id) AS current_customers
            FROM retail_allocated_portfolio
            WHERE sales_code = %s
            GROUP BY sales_code
            """,
            [sales_code],
        )
        row = cursor.fetchone()
    # Old backend indexed [0] and would 500 for an RM with no customers; return 0 instead.
    if not row:
        return {"sales_code": sales_code, "current_customers": 0}
    return {"sales_code": row[0], "current_customers": row[1]}


def rm_new_customers_ytd(sales_code):
    """Count of the RM's customers who OPENED an account this year →
    {sales_code, new_customers}. Verbatim port of old core.rm_new_customers_ytd
    (accounts.opened_by joined to customers.open_date). NOT hf_customer.date_time_created."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.opened_by, COUNT(DISTINCT a.cust_id) AS new_customers_ytd
            FROM accounts a
            LEFT JOIN customers c ON a.cust_id = c.cust_id
            WHERE a.opened_by = %s
              AND date_trunc('year', c.open_date) = date_trunc('year', now())
            GROUP BY a.opened_by
            """,
            [sales_code],
        )
        row = cursor.fetchone()
    if not row:
        return {"sales_code": sales_code, "new_customers": 0}
    return {"sales_code": row[0], "new_customers": row[1]}


def rm_new_customers_ytd_list(sales_code):
    """List of the RM's customers who opened an account this year →
    [{cust_id, account_name, current_balance, open_date, opening_branch}].
    Verbatim port of old core.rm_new_customers_ytd_list."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.cust_id,
                   a.account_name,
                   SUM(a.current_balance) AS current_balance,
                   MIN(a.open_date) AS open_date,
                   a.opening_branch
            FROM accounts a
            LEFT JOIN hf_customer hc ON a.cust_id = hc.cust_id
            LEFT JOIN customers c ON a.cust_id = c.cust_id
            WHERE a.opened_by = %s
              AND date_trunc('year', c.open_date) = date_trunc('year', now())
            GROUP BY a.cust_id, a.account_name, a.opening_branch
            """,
            [sales_code],
        )
        cols = [c[0] for c in cursor.description]
        return [_json_safe(dict(zip(cols, row))) for row in cursor.fetchall()]


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


def deposit_trends_per_customer(cust_id):
    """Per-customer deposit balance trend rows — verbatim intent of old
    core.depost_trends_per_customer: daily_balance_movement filtered by cust_cif,
    same month-balance shape as deposit_trends_data (the RM version). The old
    /customers/<pk>/deposits endpoint returned THIS trend series, not a
    product_type-filtered account list (product_type never held 'SA'/'CA'/'FD',
    so that filter returned nothing)."""
    ybl = str(current_year - 2)[-2:]
    py = str(previous_year)[-2:]
    cy = str(current_year)[-2:]
    sql = f"""
        SELECT id::text, cust_cif::text, acc_num::text, brn_code::text, prod_id::text,
               customer_segment::text, segment_code::text,
               dec_{ybl}_bal::text,
               mar_{py}_bal::text, jun_{py}_bal::text, sep_{py}_bal::text, dec_{py}_bal::text,
               jan_{cy}_bal::text, feb_{cy}_bal::text, mar_{cy}_bal::text, apr_{cy}_bal::text,
               may_{cy}_bal::text, jun_{cy}_bal::text, jul_{cy}_bal::text, aug_{cy}_bal::text,
               sep_{cy}_bal::text, oct_{cy}_bal::text, nov_{cy}_bal::text, dec_{cy}_bal::text,
               yester_2_bal::text, yester_1_bal::text, rm_code::text, diaspora_check::text,
               open_date::text, sale_code::text, full_name::text
        FROM daily_balance_movement
        WHERE cust_cif = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [cust_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def loan_trends_per_customer(cust_id):
    """Per-customer loan balance trend rows (old core.loan_trends_per_customer):
    loan_daily_balance_movement filtered by cust_cif. The old /customers/<pk>/loans
    endpoint returned THIS trend series, not raw Loans records."""
    ybl = str(current_year - 2)[-2:]
    py = str(previous_year)[-2:]
    cy = str(current_year)[-2:]
    sql = f"""
        SELECT id::text, cust_cif::text, acc_num::text, brn_code::text, prod_id::text,
               customer_segment::text, segment_code::text,
               dec_{ybl}_bal::text,
               mar_{py}_bal::text, jun_{py}_bal::text, sep_{py}_bal::text, dec_{py}_bal::text,
               jan_{cy}_bal::text, feb_{cy}_bal::text, mar_{cy}_bal::text, apr_{cy}_bal::text,
               may_{cy}_bal::text, jun_{cy}_bal::text, jul_{cy}_bal::text, aug_{cy}_bal::text,
               sep_{cy}_bal::text, oct_{cy}_bal::text, nov_{cy}_bal::text, dec_{cy}_bal::text,
               yester_2_bal::text, yester_1_bal::text, rm_code::text, diaspora_check::text,
               open_date::text, sale_code::text, full_name::text
        FROM loan_daily_balance_movement
        WHERE cust_cif = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [cust_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def cust_revenues(cust_id):
    """Customer income breakdown by category → [{id, income_category, value}]
    (old core.cust_revenues): revenue categories + computed ftp + loan_loss.
    Feeds /customers/<pk>/data (which previously returned {accounts, loans})."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT 1 id, income_category, SUM(sum_dc) AS value
            FROM revenue
            WHERE cust_id = %s
              AND date_trunc('year', tmstamp) = date_trunc('year', now())
            GROUP BY income_category
            UNION ALL
            SELECT 1 id, 'ftp' AS income_category, COALESCE(SUM(total_ftp), 0) AS value
            FROM cust_monthly_ftp
            WHERE cust_cif = %s
              AND current_year = EXTRACT(YEAR FROM CURRENT_DATE)
            UNION ALL
            SELECT 1 id, 'loan_loss' AS income_category,
                   -SUM(COALESCE(pl_charge, 0) - COALESCE(int_adj, 0)) AS value
            FROM loans_mom_ifrs_movement
            WHERE cust_code_strategy::int = %s
              AND EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
              AND cust_code_strategy ~ '^[0-9]+$'
            """,
            [cust_id, cust_id, cust_id],
        )
        cols = [c[0] for c in cur.description]
        return [_json_safe(dict(zip(cols, row))) for row in cur.fetchall()]


def ppc_per_customer(cust_id):
    """Products-per-customer number → {ppc} (old core.ppc_per_customer). Previously
    the view returned {cust_id, ppc: {product_type: count}} which the UI can't read."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT round(sum((case when fd >= 1 then 1 else 0 end) +
                             (case when ca >= 1 then 1 else 0 end) +
                             (case when sa::numeric >= 1 then 1 else 0 end) +
                             (case when mortagage >= 1 then 1 else 0 end)), 2) AS ppc
            FROM hf_customer AS hf
            LEFT JOIN retail_allocated_portfolio rap ON hf.cust_id = rap.cust_id
            WHERE hf.cust_id = %s
            """,
            [cust_id],
        )
        row = cur.fetchone()
    return {"ppc": row[0] if row and row[0] is not None else 0}


def customer_focus_chart(cust_id):
    """Customer focus chart → [{product_type, dates_eom, current_balance}]
    (old core: portfolio_cust_deposit_trends). Previously returned {counts, totals}."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT product_type, dates_eom, value AS current_balance "
            "FROM portfolio_cust_deposit_trends WHERE cust_id = %s",
            [cust_id],
        )
        cols = [c[0] for c in cur.description]
        return [_json_safe(dict(zip(cols, row))) for row in cur.fetchall()]


def _json_safe(row):
    # portfolio_rm_revenue.value is DecimalField(65535, 65535); a NaN/inf in that
    # warehouse column makes DRF's strict JSON renderer raise ValueError. Null those
    # out so the response serialises; finite decimals pass through untouched.
    return {
        k: (None if isinstance(v, Decimal) and not v.is_finite() else v)
        for k, v in row.items()
    }


def rm_revenue(sales_code):
    """RM revenue breakdown by income_category — verbatim port of old core.revenue().
    Rows are (sales_code, income_category, value): the STORED portfolio_rm_revenue
    categories (interest_income / interest_expenses / nfi) UNION the COMPUTED ftp
    (cust_monthly_ftp) and loan_loss (loans_mom_ifrs_movement) rows.

    The previous version returned only portfolio_rm_revenue.values(), so the ftp and
    loan_loss categories were absent and rendered as zeros on the frontend."""
    query = """
        WITH valid_portfolio AS (
            SELECT cust_id
            FROM retail_allocated_portfolio
            WHERE sales_code = %s
        ),
        valid_loans AS (
            SELECT *
            FROM loans_mom_ifrs_movement l
            WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
            AND cust_code_strategy ~ '^[0-9]+$'
        )
        SELECT *
        FROM portfolio_rm_revenue
        WHERE sales_code = %s

        UNION ALL

        SELECT
            %s AS sales_code,
            'ftp' AS income_category,
            COALESCE(SUM(ftp.total_ftp), 0) AS value
        FROM cust_monthly_ftp ftp
        JOIN valid_portfolio vp ON ftp.cust_cif = vp.cust_id
        WHERE ftp.current_year = EXTRACT(YEAR FROM CURRENT_DATE)

        UNION ALL

        SELECT
            %s AS sales_code,
            'loan_loss' AS income_category,
            -SUM(COALESCE(l.pl_charge, 0) - COALESCE(l.int_adj, 0)) AS value
        FROM valid_loans l
        JOIN valid_portfolio vp ON l.cust_code_strategy::int = vp.cust_id
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [sales_code, sales_code, sales_code, sales_code])
        columns = [col[0] for col in cursor.description]
        return [_json_safe(dict(zip(columns, row))) for row in cursor.fetchall()]


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
    # Match the OLD backend exactly (core.core LoansArrears*ByRmCode):
    #   LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
    #   WHERE lns.days_in_arrears > 0
    #     AND LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
    # A loan belongs to an RM when the loan's CUSTOMER is allocated to that RM in
    # retail_allocated_portfolio — NOT via loans.account_officer (that column is not
    # the RM allocation key; filtering on it returns zero rows, which is why every
    # arrears widget rendered empty). sales_code is CHAR-padded in the warehouse, so
    # trim + lower both sides.
    cust_ids = (
        RetailAllocatedPortfolio.objects
        .annotate(_sc=Lower(Trim("sales_code")))
        .filter(_sc=(sales_code or "").strip().lower())
        .values("cust_id")
    )
    return (
        Loans.objects
        .filter(cust_id__in=cust_ids, days_in_arrears__gt=0)
        .order_by("days_in_arrears")  # deterministic order for pagination (old backend: days_in_arrears ASC)
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
