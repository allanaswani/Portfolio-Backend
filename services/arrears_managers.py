"""
Loan-arrears query managers — VERBATIM port of the OLD backend's core.core
manager classes (LoansArrearsSummaryManager, LoansArrearsDPDBucketSummaryManager,
LoansProductArrearsSummaryManager, LoansArrearsAccountsListManager).

All queries read the LIVE `loans` table (never loans_history) exactly as the old
backend did, joined per scope:
  * no-arg method            -> whole bank (CEO)
  * *_by_rm_code(rm_code)    -> rap.sales_code
  * *_by_branch(branch)      -> branch_final_employee_dmc_data.staff_branch (LIKE)
  * *_by_segment(segment)    -> loans_mom_ifrs_movement / hf_customer segment CASE

Copied unchanged from the old backend so the response shapes match what the
frontend arrears tables are built against. Instantiate directly, e.g.
    LoansArrearsAccountsListManager().accounts_in_arrears_by_segment(seg)
The classes subclass models.Manager only because the original did; they are used
standalone and only ever touch `connection`.
"""
from django.db import connection, models


class LoansArrearsSummaryManager(models.Manager):
    """
    Manager class for handling high-level summary for loans arrears.
    """

    def high_level_summary(self):
        """
        Returns high-level for the loans portfolio:
            - total_outstanding_loan_amount
            - total_arrears_amount
            - customers_in_arrears
            - percent_portfolio_in_arrears
            - loan_loss
            - max_provisions_eom_date
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                with loan_provisions as (
                    select 
                        sum(mov.pl_charge - mov.int_adj) as loan_loss,
                        max(mov.eom_date) as max_provisions_eom_date
                    from loans_mom_ifrs_movement mov where EXTRACT(YEAR FROM mov.eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ),
                loan_arrears as (
                    SELECT
                        SUM(euro_book_balance) AS total_outstanding_loan_amount,
                        SUM(total_arrears) AS total_arrears_amount,
                        COUNT(DISTINCT CASE WHEN total_arrears > 0 THEN cust_id END) AS customers_in_arrears,
                        CASE
                            WHEN SUM(euro_book_balance) > 0 THEN (SUM(total_arrears) / SUM(euro_book_balance))
                            ELSE 0
                        END AS percent_portfolio_in_arrears
                    FROM loans
                )
                select 
                    total_outstanding_loan_amount,
                    total_arrears_amount,
                    customers_in_arrears,
                    percent_portfolio_in_arrears,
                    loan_loss,
                    max_provisions_eom_date
                from loan_arrears, loan_provisions;
            """)
            result = cursor.fetchone()
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, result)) if result else {}

    def high_level_summary_by_rm_code(self, rm_code):
        """
        Returns high-level for the loans portfolio filtered by RM code.
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                with loan_provisions as (
                    select 
                        sum(mov.pl_charge - mov.int_adj) as loan_loss,
                        max(mov.eom_date) as max_provisions_eom_date
                    from loans_mom_ifrs_movement mov 
                    INNER JOIN retail_allocated_portfolio rap ON rap.cust_id::varchar = mov.cust_code_strategy
                    where EXTRACT(YEAR FROM mov.eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                    AND LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
                ),
                loan_arrears as (
                    SELECT
                        SUM(euro_book_balance) AS total_outstanding_loan_amount,
                        SUM(total_arrears) AS total_arrears_amount,
                        COUNT(DISTINCT CASE WHEN total_arrears > 0 THEN lns.cust_id END) AS customers_in_arrears,
                        CASE
                            WHEN SUM(euro_book_balance) > 0 THEN (SUM(total_arrears) / SUM(euro_book_balance))
                            ELSE 0
                        END AS percent_portfolio_in_arrears
                    FROM loans lns
                    INNER JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                    where LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
                )
                select 
                    total_outstanding_loan_amount,
                    total_arrears_amount,
                    customers_in_arrears,
                    percent_portfolio_in_arrears,
                    loan_loss,
                    max_provisions_eom_date
                from loan_arrears, loan_provisions
            """, [rm_code, rm_code])
            result = cursor.fetchone()
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, result)) if result else {}

    def high_level_summary_by_branch(self, branch):
        """
        Returns high-level for the loans portfolio filtered by customer branch.
        """
        # Prepare the LIKE pattern with proper formatting
        branch_pattern = f"%{branch.strip()}%"
        with connection.cursor() as cursor:
            cursor.execute("""
                with loan_provisions as (
                    select 
                        sum(mov.pl_charge - mov.int_adj) as loan_loss,
                        max(mov.eom_date) as max_provisions_eom_date
                    from loans_mom_ifrs_movement mov 
                    INNER JOIN branch_final_employee_dmc_data bfedd 
                        ON 
                            -- Remap mov.branch2 to match bfedd.staff_branch naming
                            CASE
                                WHEN UPPER(TRIM(mov.branch2)) = 'BURUBURU' THEN 'BURUBURU BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'ELDORET' THEN 'ELDORET BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'EMBU BRANCH' THEN 'EMBU BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'GILL HOUSE' THEN 'HARAMBEE AVE BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'HEAD OFFICE' THEN 'HEAD OFFICE BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'HURLINGHAM BRANCH' THEN 'HURLINGHAM BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'KISUMU' THEN 'KISUMU BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'KITENGELA' THEN 'KITENGELA BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'KOMAROCK' THEN 'KOMAROCK BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'MACHAKOS' THEN 'MACHAKOS BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'MERU' THEN 'MERU BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'MOMBASA' THEN 'MOMBASA BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'NAIVASHA' THEN 'NAIVASHA BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'NAKURU' THEN 'NAKURU BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'NANYUKI' THEN 'NANYUKI BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'NYALI' THEN 'NYALI BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'NYERI' THEN 'NYERI BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'REHANI' THEN 'REHANI BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'RIVERROAD' THEN 'RIVERROAD BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'RONGAI' THEN 'RONGAI BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'SAMEER BUSINESS PARK' THEN 'SAMEER BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'THIKA' THEN 'THIKA BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'THIKA ROAD MALL-TRM' THEN 'TRM BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'WESTLANDS' THEN 'WESTLANDS BRANCH'
                                WHEN UPPER(TRIM(mov.branch2)) = 'SPECIAL ASSETS' THEN 'SPECIAL ASSETS BRANCH'
                                ELSE UPPER(TRIM(mov.branch2))
                            END = UPPER(TRIM(bfedd.staff_branch))
                    WHERE LOWER(TRIM(bfedd.staff_branch)) LIKE LOWER(%s)
                ),
                loan_arrears as (
                    SELECT
                        SUM(euro_book_balance) AS total_outstanding_loan_amount,
                        SUM(total_arrears) AS total_arrears_amount,
                        COUNT(DISTINCT CASE WHEN total_arrears > 0 THEN lns.cust_id END) AS customers_in_arrears,
                        CASE
                            WHEN SUM(euro_book_balance) > 0 THEN (SUM(total_arrears) / SUM(euro_book_balance))
                            ELSE 0
                        END AS percent_portfolio_in_arrears
                    FROM loans lns
                    INNER JOIN branch_final_employee_dmc_data bfedd 
                        ON bfedd.brn_code = lns.branch
                    WHERE LOWER(TRIM(bfedd.staff_branch)) LIKE LOWER(%s)
                )
                select 
                    total_outstanding_loan_amount,
                    total_arrears_amount,
                    customers_in_arrears,
                    percent_portfolio_in_arrears,
                    loan_loss,
                    max_provisions_eom_date
                from loan_arrears, loan_provisions
            """, [branch_pattern, branch_pattern])
            result = cursor.fetchone()
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, result)) if result else {}

    def high_level_summary_by_segment(self, segment):
        """
        Returns high-level for the loans portfolio filtered by customer segment.
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                with loan_provisions as (
                    select 
                        sum(mov.pl_charge - mov.int_adj) as loan_loss,
                        max(mov.eom_date) as max_provisions_eom_date
                    from loans_mom_ifrs_movement mov 
                    WHERE
                        CASE
                            WHEN UPPER(TRIM(mov.segment)) = 'FI' THEN 'FINANCIAL INSTITUTIONS'
                            WHEN UPPER(TRIM(mov.segment)) = 'IB' THEN 'INSTITUTIONAL BANKING'
                            WHEN UPPER(TRIM(mov.segment)) = 'PERSONAL' THEN 'PB'
                            WHEN UPPER(TRIM(mov.segment)) = 'BUSINESS BANKING' THEN 'BUSINESS BANKING'
                            WHEN UPPER(TRIM(mov.segment)) = 'COMMERCIAL' THEN 'COMMERCIAL'
                            WHEN UPPER(TRIM(mov.segment)) = 'VIRTUAL' THEN 'VIRTUAL'
                            ELSE UPPER(TRIM(mov.segment))
                        END = UPPER(%s)
                ),
                loan_arrears as (
                    SELECT
                        SUM(euro_book_balance) AS total_outstanding_loan_amount,
                        SUM(total_arrears) AS total_arrears_amount,
                        COUNT(DISTINCT CASE WHEN total_arrears > 0 THEN lns.cust_id END) AS customers_in_arrears,
                        CASE
                            WHEN SUM(euro_book_balance) > 0 THEN (SUM(total_arrears) / SUM(euro_book_balance))
                            ELSE 0
                        END AS percent_portfolio_in_arrears
                    FROM loans lns
                    INNER JOIN hf_customer c 
                        ON c.cust_id = lns.cust_id
                    WHERE LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
                )
                select 
                    total_outstanding_loan_amount,
                    total_arrears_amount,
                    customers_in_arrears,
                    percent_portfolio_in_arrears,
                    loan_loss,
                    max_provisions_eom_date
                from loan_arrears, loan_provisions
            """, [segment, segment])
            result = cursor.fetchone()
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, result)) if result else {}

class LoansArrearsDPDBucketSummaryManager(models.Manager):
    """
    Manager class for handling DPD bucket summaries for loans arrears.
    """

    def dpd_bucket_summary(self):
        """
        Returns overall DPD bucket summary for all loans.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    mov_latest.current_grade,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                ORDER BY lns.days_in_arrears ASC,
                    CASE mov_latest.current_grade
                        WHEN 'NORMAL' THEN 1
                        WHEN 'WATCH' THEN 2
                        WHEN 'SUBSTD' THEN 3
                        WHEN 'DOUBTFUL' THEN 4
                        WHEN 'LOSS' THEN 5
                        WHEN 'AUCTION SHORTFALLS' THEN 6
                        WHEN 'N_A' THEN 7
                        ELSE 8
                    END ASC
            )
            SELECT 
                bd.current_grade,
                sum(bd.euro_book_balance) AS total_outstanding,
                sum(bd.total_arrears) AS total_arrears,
                sum(bd.loan_loss) AS ytd_loan_loss
            FROM bucket_data bd
            GROUP BY bd.current_grade
            ORDER BY 
                CASE bd.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    ELSE 6
                END
        """
        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def dpd_bucket_summary_by_rm_code(self, rm_code):
        """
        Returns DPD bucket summary filtered by RM code.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    mov_latest.current_grade,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                AND LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
                ORDER BY lns.days_in_arrears ASC,
                    CASE mov_latest.current_grade
                        WHEN 'NORMAL' THEN 1
                        WHEN 'WATCH' THEN 2
                        WHEN 'SUBSTD' THEN 3
                        WHEN 'DOUBTFUL' THEN 4
                        WHEN 'LOSS' THEN 5
                        WHEN 'AUCTION SHORTFALLS' THEN 6
                        WHEN 'N_A' THEN 7
                        ELSE 8
                    END ASC
            )
            SELECT 
                bd.current_grade,
                sum(bd.euro_book_balance) AS total_outstanding,
                sum(bd.total_arrears) AS total_arrears,
                sum(bd.loan_loss) AS ytd_loan_loss
            FROM bucket_data bd
            GROUP BY bd.current_grade
            ORDER BY 
                CASE bd.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    ELSE 6
                END
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [rm_code])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def dpd_bucket_summary_by_branch(self, branch):
        """
        Returns DPD bucket summary filtered by branch.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    mov_latest.current_grade,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                AND LOWER(TRIM(bfedd.staff_branch)) LIKE LOWER(%s)
                ORDER BY lns.days_in_arrears ASC,
                    CASE mov_latest.current_grade
                        WHEN 'NORMAL' THEN 1
                        WHEN 'WATCH' THEN 2
                        WHEN 'SUBSTD' THEN 3
                        WHEN 'DOUBTFUL' THEN 4
                        WHEN 'LOSS' THEN 5
                        WHEN 'AUCTION SHORTFALLS' THEN 6
                        WHEN 'N_A' THEN 7
                        ELSE 8
                    END ASC
            )
            SELECT 
                bd.current_grade,
                sum(bd.euro_book_balance) AS total_outstanding,
                sum(bd.total_arrears) AS total_arrears,
                sum(bd.loan_loss) AS ytd_loan_loss
            FROM bucket_data bd
            GROUP BY bd.current_grade
            ORDER BY 
                CASE bd.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    ELSE 6
                END;
        """
        branch_pattern = f"%{branch.strip()}%"
        with connection.cursor() as cursor:
            cursor.execute(query, [branch_pattern])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def dpd_bucket_summary_by_segment(self, segment):
        """
        Returns DPD bucket summary filtered by customer segment.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    mov_latest.current_grade,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                AND LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
                ORDER BY lns.days_in_arrears ASC,
                    CASE mov_latest.current_grade
                        WHEN 'NORMAL' THEN 1
                        WHEN 'WATCH' THEN 2
                        WHEN 'SUBSTD' THEN 3
                        WHEN 'DOUBTFUL' THEN 4
                        WHEN 'LOSS' THEN 5
                        WHEN 'AUCTION SHORTFALLS' THEN 6
                        WHEN 'N_A' THEN 7
                        ELSE 8
                    END ASC
            )
            SELECT 
                bd.current_grade,
                sum(bd.euro_book_balance) AS total_outstanding,
                sum(bd.total_arrears) AS total_arrears,
                sum(bd.loan_loss) AS ytd_loan_loss
            FROM bucket_data bd
            GROUP BY bd.current_grade
            ORDER BY 
                CASE bd.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    ELSE 6
                END;
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [segment])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

class LoansProductArrearsSummaryManager(models.Manager):
    """
    Manager class for handling arrears summary by loan product.
    """

    def product_arrears_summary(self):
        """
        Returns arrears summary by product for all loans.

        Args:
            limit (int): Number of top products to return (default 10).

        Returns:
            list: List of dicts with product_description and total_arrears_amount.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    pm.product_description,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
            ),
            data AS (
                SELECT 
                    1 as id,
                    bd.product_description,
                    sum(bd.total_arrears) AS total_arrears_amount
                FROM bucket_data bd
                GROUP BY bd.product_description
            )
            SELECT * FROM data
            WHERE total_arrears_amount > 0
            ORDER BY total_arrears_amount DESC
            LIMIT 10;
        """
        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def product_arrears_summary_by_rm_code(self, rm_code):
        """
        Returns arrears summary by product filtered by RM code.

        Args:
            rm_code (str): Relationship manager code.
            limit (int): Number of top products to return (default 10).

        Returns:
            list: List of dicts with product_description and total_arrears_amount.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    pm.product_description,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                AND LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
            ),
            data AS (
                SELECT 
                    1 as id,
                    bd.product_description,
                    sum(bd.total_arrears) AS total_arrears_amount
                FROM bucket_data bd
                GROUP BY bd.product_description
            )
            SELECT * FROM data
            WHERE total_arrears_amount > 0
            ORDER BY total_arrears_amount DESC
            LIMIT 10;
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [rm_code])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def product_arrears_summary_by_branch(self, branch):
        """
        Returns arrears summary by product filtered by branch.

        Args:
            branch (str): Branch name.
            limit (int): Number of top products to return (default 10).

        Returns:
            list: List of dicts with product_description and total_arrears_amount.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    pm.product_description,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                AND LOWER(TRIM(bfedd.staff_branch)) LIKE LOWER(%s)
            ),
            data AS (
                SELECT 
                    1 as id,
                    bd.product_description,
                    sum(bd.total_arrears) AS total_arrears_amount
                FROM bucket_data bd
                GROUP BY bd.product_description
            )
            SELECT * FROM data
            WHERE total_arrears_amount > 0
            ORDER BY total_arrears_amount DESC
            LIMIT 10;
        """
        branch_pattern = f"%{branch.strip()}%"
        with connection.cursor() as cursor:
            cursor.execute(query, [branch_pattern])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def product_arrears_summary_by_segment(self, segment):
        """
        Returns arrears summary by product filtered by customer segment.

        Args:
            segment (str): Customer segment.
            limit (int): Number of top products to return (default 10).

        Returns:
            list: List of dicts with product_description and total_arrears_amount.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            ),
            bucket_data AS (
                SELECT
                    pm.product_description,
                    lns.euro_book_balance,
                    lns.total_arrears,
                    COALESCE(mov_sum.loan_loss, 0) AS loan_loss
                FROM loans lns
                LEFT JOIN mov_sum
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
                LEFT JOIN mov_latest
                    ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
                LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
                LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
                LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
                LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
                WHERE lns.days_in_arrears > 0
                AND LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
            ),
            data AS (
                SELECT 
                    1 as id,
                    bd.product_description,
                    sum(bd.total_arrears) AS total_arrears_amount
                FROM bucket_data bd
                GROUP BY bd.product_description
            )
            SELECT * FROM data
            WHERE total_arrears_amount > 0
            ORDER BY total_arrears_amount DESC
            LIMIT 10;
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [segment])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

class LoansArrearsAccountsListManager(models.Manager):
    """
    Manager class for listing loan accounts in arrears with customer and product details.
    """

    def accounts_in_arrears(self):
        """
        Returns a list of accounts in arrears with customer, product, and RM details.

        Returns:
            list: List of dicts with customer and loan account details.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            )
            SELECT
                lns.cust_id,
                c.latin_surname,
                lns.loan_account_no,
                bfedd.staff_branch AS monitoring_branch,
                pm.product_description,
                COALESCE(mov_sum.loan_loss, 0) AS loan_loss,
                mov_latest.prev_ifrs,
                mov_latest.current_ifrs,
                mov_latest.movt_in_ifrs,
                mov_latest.current_grade,
                lns.euro_book_balance,
                lns.installment_amount,
                lns.total_arrears,
                lns.days_in_arrears,
                lns.last_transaction_date,
                lns.next_installment_date,
                lns.delay_officer,
                be.full_name AS delay_officer_name,
                rap.rm_name
            FROM loans lns
            LEFT JOIN mov_sum
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
            LEFT JOIN mov_latest
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
            LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
            LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
            LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
            LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
            LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
            WHERE lns.days_in_arrears > 0
            ORDER BY lns.days_in_arrears ASC,
                CASE mov_latest.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    WHEN 'AUCTION SHORTFALLS' THEN 6
                    WHEN 'N_A' THEN 7
                    ELSE 8
                END ASC;
        """
        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def accounts_in_arrears_by_rm_code(self, rm_code):
        """
        Returns a list of accounts in arrears filtered by RM code.

        Args:
            rm_code (str): Relationship manager code.

        Returns:
            list: List of dicts with customer and loan account details.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            )
            SELECT
                lns.cust_id,
                c.latin_surname,
                lns.loan_account_no,
                bfedd.staff_branch AS monitoring_branch,
                pm.product_description,
                COALESCE(mov_sum.loan_loss, 0) AS loan_loss,
                mov_latest.prev_ifrs,
                mov_latest.current_ifrs,
                mov_latest.movt_in_ifrs,
                mov_latest.current_grade,
                lns.euro_book_balance,
                lns.installment_amount,
                lns.total_arrears,
                lns.days_in_arrears,
                lns.last_transaction_date,
                lns.next_installment_date,
                lns.delay_officer,
                be.full_name AS delay_officer_name,
                rap.rm_name
            FROM loans lns
            LEFT JOIN mov_sum
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
            LEFT JOIN mov_latest
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
            LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
            LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
            LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
            LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
            LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
            WHERE lns.days_in_arrears > 0
              AND LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
            ORDER BY lns.days_in_arrears ASC,
                CASE mov_latest.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    WHEN 'AUCTION SHORTFALLS' THEN 6
                    WHEN 'N_A' THEN 7
                    ELSE 8
                END ASC;
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [rm_code])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def accounts_in_arrears_by_branch(self, branch):
        """
        Returns a list of accounts in arrears filtered by branch.

        Args:
            branch (str): Branch name.

        Returns:
            list: List of dicts with customer and loan account details.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            )
            SELECT
                lns.cust_id,
                c.latin_surname,
                lns.loan_account_no,
                bfedd.staff_branch AS monitoring_branch,
                pm.product_description,
                COALESCE(mov_sum.loan_loss, 0) AS loan_loss,
                mov_latest.prev_ifrs,
                mov_latest.current_ifrs,
                mov_latest.movt_in_ifrs,
                mov_latest.current_grade,
                lns.euro_book_balance,
                lns.installment_amount,
                lns.total_arrears,
                lns.days_in_arrears,
                lns.last_transaction_date,
                lns.next_installment_date,
                lns.delay_officer,
                be.full_name AS delay_officer_name,
                rap.rm_name
            FROM loans lns
            LEFT JOIN mov_sum
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
            LEFT JOIN mov_latest
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
            LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
            LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
            LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
            LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
            LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
            WHERE lns.days_in_arrears > 0
              AND LOWER(TRIM(bfedd.staff_branch)) LIKE LOWER(%s)
            ORDER BY lns.days_in_arrears ASC,
                CASE mov_latest.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    WHEN 'AUCTION SHORTFALLS' THEN 6
                    WHEN 'N_A' THEN 7
                    ELSE 8
                END ASC;
        """
        branch_pattern = f"%{branch.strip()}%"
        with connection.cursor() as cursor:
            cursor.execute(query, [branch_pattern])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

    def accounts_in_arrears_by_segment(self, segment):
        """
        Returns a list of accounts in arrears filtered by customer segment.

        Args:
            segment (str): Customer segment.

        Returns:
            list: List of dicts with customer and loan account details.
        """
        query = """
            WITH mov_sum AS (
                SELECT
                    REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                    SUM(pl_charge + int_adj) AS loan_loss
                FROM loans_mom_ifrs_movement
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                GROUP BY REGEXP_REPLACE(TRIM(lns_account), '^0+', '')
            ),
            mov_latest AS (
                SELECT DISTINCT ON (loan_account_no)
                    loan_account_no,
                    prev_ifrs,
                    current_ifrs,
                    movt_in_ifrs,
                    current_grade
                FROM (
                    SELECT
                        REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS loan_account_no,
                        prev_ifrs,
                        current_ifrs,
                        movt_in_ifrs,
                        current_grade,
                        eom_date
                    FROM loans_mom_ifrs_movement
                    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                ) sub
                ORDER BY loan_account_no, eom_date DESC
            )
            SELECT
                lns.cust_id,
                c.latin_surname,
                lns.loan_account_no,
                bfedd.staff_branch AS monitoring_branch,
                pm.product_description,
                COALESCE(mov_sum.loan_loss, 0) AS loan_loss,
                mov_latest.prev_ifrs,
                mov_latest.current_ifrs,
                mov_latest.movt_in_ifrs,
                mov_latest.current_grade,
                lns.euro_book_balance,
                lns.installment_amount,
                lns.total_arrears,
                lns.days_in_arrears,
                lns.last_transaction_date,
                lns.next_installment_date,
                lns.delay_officer,
                be.full_name AS delay_officer_name,
                rap.rm_name
            FROM loans lns
            LEFT JOIN mov_sum
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_sum.loan_account_no
            LEFT JOIN mov_latest
                ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov_latest.loan_account_no
            LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
            LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = lns.cust_id
            LEFT JOIN hf_customer c ON lns.cust_id = c.cust_id
            LEFT JOIN branch_final_employee_dmc_data bfedd ON bfedd.brn_code = lns.branch
            LEFT JOIN bank_employee be ON trim(be.bank_id) = trim(lns.delay_officer)
            WHERE lns.days_in_arrears > 0
              AND LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
            ORDER BY lns.days_in_arrears ASC,
                CASE mov_latest.current_grade
                    WHEN 'NORMAL' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'SUBSTD' THEN 3
                    WHEN 'DOUBTFUL' THEN 4
                    WHEN 'LOSS' THEN 5
                    WHEN 'AUCTION SHORTFALLS' THEN 6
                    WHEN 'N_A' THEN 7
                    ELSE 8
                END ASC;
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [segment])
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]

