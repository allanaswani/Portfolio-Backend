"""
Fixed-deposit query managers — VERBATIM port of the OLD backend's core.core
managers (FixedDepositListManager, FixedDepositRateBandManager,
FixedDepositOverallSummary).

FD accounts are identified the old-backend way: JOIN accounts.type ->
product_mapping.product_description WHERE product_mapping.product_map = 'FD'
(NOT accounts.product_type ILIKE '%FD%', which matched nothing -> zeros).

Scoping:
  * *_by_rm_code(sales_code)  -> rap.sales_code
  * *_by_branch(branch)       -> accounts.current_branch (LOWER/TRIM)
  * *_by_segment(segment)     -> hf_customer.banking_segment
  * *_overall / no-arg        -> whole bank (CEO)

Instantiate directly, e.g. FixedDepositListManager().fixed_deposits_list_by_rm_code(sc).
Subclass models.Manager only because the original did; used standalone, touches
only `connection`.
"""
from django.db import connection, models


class FixedDepositListManager(models.Manager):
    """
    Manager class for handling queries related to fixed deposit accounts.
    """

    def fixed_deposits_list_by_rm_code(self, sales_code):
        """
        Fetches a list of customer fixed deposit accounts managed by a specific RM.

        Args:
            sales_code (str): The sales code of the relationship manager.

        Returns:
            list: A list of dictionaries containing fixed deposit account details.
        """
        query = '''
            SELECT 
                accs.account_no, 
                accs.account_name, 
                accs.type, 
                accs.interest_rate, 
                accs.current_balance, 
                accs.expiry_date::date, 
                accs.current_branch, 
                rap.rm_name,
                accs.cust_id
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            INNER JOIN retail_allocated_portfolio rap 
                ON rap.cust_id = accs.cust_id
            WHERE rap.sales_code = %s
                AND pm.product_map = 'FD'
                -- AND accs.expiry_date > CURRENT_DATE
            ORDER BY accs.expiry_date ASC
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [sales_code])
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            # Log the error (optional: replace with a logging framework)
            print(f"Error fetching fixed deposits by RM code: {e}")
            return []

    def fixed_deposits_list_by_branch_name(self, branch_name):
        """
        Fetches a list of customer fixed deposit accounts managed at a specific branch.

        Args:
            branch_name (str): The branch name of the account.

        Returns:
            list: A list of dictionaries containing fixed deposit account details.
        """
        query = '''
            SELECT 
                accs.account_no, 
                accs.account_name, 
                accs.type, 
                accs.interest_rate, 
                accs.current_balance, 
                accs.expiry_date::date, 
                c.banking_segment, 
                rap.rm_name,
                accs.cust_id
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            LEFT JOIN retail_allocated_portfolio rap 
                ON rap.cust_id = accs.cust_id
            INNER JOIN hf_customer c 
                ON c.cust_id = accs.cust_id
            WHERE LOWER(TRIM(accs.current_branch)) = LOWER(TRIM(%s))
                AND pm.product_map = 'FD'
                -- AND accs.expiry_date > CURRENT_DATE
            ORDER BY accs.expiry_date ASC
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [branch_name])
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            # Log the error (optional: replace with a logging framework)
            print(f"Error fetching fixed deposits by branch name: {e}")
            return []

    def fixed_deposits_list_by_segment(self, segment):
        """
        Fetches a list of customer fixed deposit accounts managed in a specific segment.

        Args:
            segment (str): The segment of the customer.

        Returns:
            list: A list of dictionaries containing fixed deposit account details.
        """
        query = '''
            SELECT 
                accs.account_no, 
                accs.account_name, 
                accs.type, 
                accs.interest_rate, 
                accs.current_balance, 
                accs.expiry_date::date, 
                accs.current_branch, 
                rap.rm_name,
                accs.cust_id
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            LEFT JOIN retail_allocated_portfolio rap 
                ON rap.cust_id = accs.cust_id
            LEFT JOIN hf_customer c 
                ON c.cust_id = accs.cust_id
            WHERE LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
                AND pm.product_map = 'FD'
                -- AND accs.expiry_date > CURRENT_DATE
            ORDER BY accs.expiry_date ASC
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [segment])
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            # Log the error (optional: replace with a logging framework)
            print(f"Error fetching fixed deposits by segment: {e}")
            return []

    def fixed_deposits_list_overall(self):
        """
        Fetches a list of customer fixed deposit accounts.

        Returns:
            list: A list of dictionaries containing fixed deposit account details.
        """
        query = '''
            SELECT 
                accs.account_no, 
                accs.account_name, 
                accs.type, 
                accs.interest_rate, 
                accs.current_balance, 
                accs.expiry_date::date, 
                accs.current_branch, 
                rap.rm_name,
                accs.cust_id
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            LEFT JOIN retail_allocated_portfolio rap 
                ON rap.cust_id = accs.cust_id
            INNER JOIN hf_customer c 
                ON c.cust_id = accs.cust_id
            WHERE pm.product_map = 'FD'
                -- AND accs.expiry_date > CURRENT_DATE
            ORDER BY accs.expiry_date ASC
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            # Log the error (optional: replace with a logging framework)
            print(f"Error fetching all fixed deposits: {e}")
            return []


class FixedDepositRateBandManager(models.Manager):
    """
    Manager class for handling queries related to fixed deposit rate bands.
    """

    def rate_bands_by_rm_code(self, sales_code):
        """
        Fetches the distribution of fixed deposit accounts by interest rate bands for a specific RM.

        Args:
            sales_code (str): The sales code of the relationship manager.

        Returns:
            list: A list of dictionaries containing rate band details:
                - rate_band (str): The interest rate band (e.g., "< 5%", "5% - 8%").
                - rate_band_order (int): The order of the rate band for sorting.
                - amount (float): The total balance for the rate band.
        """
        query = '''
            SELECT
                CASE 
                    WHEN interest_rate <= 5 THEN '< 5'
                    WHEN interest_rate <= 8 THEN '5 - 8'
                    WHEN interest_rate <= 10 THEN '8 - 10'
                    WHEN interest_rate <= 13 THEN '10 - 13'
                    WHEN interest_rate <= 15 THEN '13 - 15'
                    ELSE '> 15'
                END AS rate_band,
                CASE
                    WHEN interest_rate <= 5 THEN 1
                    WHEN interest_rate <= 8 THEN 2
                    WHEN interest_rate <= 10 THEN 3
                    WHEN interest_rate <= 13 THEN 4
                    WHEN interest_rate <= 15 THEN 5
                    ELSE 6
                END AS rate_band_order,
                SUM(accs.current_balance) AS amount
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            INNER JOIN retail_allocated_portfolio rap 
                ON rap.cust_id = accs.cust_id
            WHERE LOWER(TRIM(rap.sales_code)) = LOWER(TRIM(%s))
            AND pm.product_map = 'FD'
            GROUP BY rate_band, rate_band_order
            ORDER BY rate_band_order
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [sales_code])
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            print(f"Error fetching fixed deposit rate bands by rm: {e}")
            return []

    def rate_bands_by_branch(self, branch_name):
        """
        Fetches the distribution of fixed deposit accounts by interest rate bands for a specific branch.

        Args:
            branch_name (str): The branch name.

        Returns:
            list: A list of dictionaries containing rate band details:
                - rate_band (str): The interest rate band (e.g., "< 5%", "5% - 8%").
                - rate_band_order (int): The order of the rate band for sorting.
                - amount (float): The total balance for the rate band.
        """
        query = '''
            SELECT
                CASE 
                    WHEN interest_rate <= 5 THEN '< 5'
                    WHEN interest_rate <= 8 THEN '5 - 8'
                    WHEN interest_rate <= 10 THEN '8 - 10'
                    WHEN interest_rate <= 13 THEN '10 - 13'
                    WHEN interest_rate <= 15 THEN '13 - 15'
                    ELSE '> 15'
                END AS rate_band,
                CASE
                    WHEN interest_rate <= 5 THEN 1
                    WHEN interest_rate <= 8 THEN 2
                    WHEN interest_rate <= 10 THEN 3
                    WHEN interest_rate <= 13 THEN 4
                    WHEN interest_rate <= 15 THEN 5
                    ELSE 6
                END AS rate_band_order,
                SUM(accs.current_balance) AS amount
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            WHERE LOWER(TRIM(accs.current_branch)) = LOWER(TRIM(%s))
              AND pm.product_map = 'FD'
            GROUP BY rate_band, rate_band_order
            ORDER BY rate_band_order
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [branch_name])
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            print(f"Error fetching fixed deposit rate bands by branch: {e}")
            return []

    def rate_bands_by_segment(self, segment):
        """
        Fetches the distribution of fixed deposit accounts by interest rate bands for a specific segment.

        Args:
            segment (str): The segment of the customer.

        Returns:
            list: A list of dictionaries containing rate band details:
                - rate_band (str): The interest rate band (e.g., "< 5%", "5% - 8%").
                - rate_band_order (int): The order of the rate band for sorting.
                - amount (float): The total balance for the rate band.
        """
        query = '''
            SELECT
                CASE 
                    WHEN interest_rate <= 5 THEN '< 5'
                    WHEN interest_rate <= 8 THEN '5 - 8'
                    WHEN interest_rate <= 10 THEN '8 - 10'
                    WHEN interest_rate <= 13 THEN '10 - 13'
                    WHEN interest_rate <= 15 THEN '13 - 15'
                    ELSE '> 15'
                END AS rate_band,
                CASE
                    WHEN interest_rate <= 5 THEN 1
                    WHEN interest_rate <= 8 THEN 2
                    WHEN interest_rate <= 10 THEN 3
                    WHEN interest_rate <= 13 THEN 4
                    WHEN interest_rate <= 15 THEN 5
                    ELSE 6
                END AS rate_band_order,
                SUM(accs.current_balance) AS amount
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            INNER JOIN hf_customer c 
                ON c.cust_id = accs.cust_id
            WHERE LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
              AND pm.product_map = 'FD'
            GROUP BY rate_band, rate_band_order
            ORDER BY rate_band_order
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [segment])
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            print(f"Error fetching fixed deposit rate bands by segment: {e}")
            return []

    def rate_bands_by_overall(self):
        """
        Fetches the overall distribution of fixed deposit accounts by interest rate bands.

        Returns:
            list: A list of dictionaries containing rate band details:
        """
        query = '''
            SELECT
                CASE 
                    WHEN interest_rate <= 5 THEN '< 5'
                    WHEN interest_rate <= 8 THEN '5 - 8'
                    WHEN interest_rate <= 10 THEN '8 - 10'
                    WHEN interest_rate <= 13 THEN '10 - 13'
                    WHEN interest_rate <= 15 THEN '13 - 15'
                    ELSE '> 15'
                END AS rate_band,
                CASE
                    WHEN interest_rate <= 5 THEN 1
                    WHEN interest_rate <= 8 THEN 2
                    WHEN interest_rate <= 10 THEN 3
                    WHEN interest_rate <= 13 THEN 4
                    WHEN interest_rate <= 15 THEN 5
                    ELSE 6
                END AS rate_band_order,
                SUM(accs.current_balance) AS amount
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            WHERE pm.product_map = 'FD'
            GROUP BY rate_band, rate_band_order
            ORDER BY rate_band_order
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            print(f"Error fetching overall fixed deposit rate bands: {e}")
            return []


# class FixedDepositExpiryTimelineManager(models.Manager):
#     """
#     Manager class for handling queries related to fixed deposit expiry timeline bands.
#     """

def expiry_timeline_band_by_rm_code(sales_code):
    """
    Fetches the distribution of fixed deposit accounts by expiry timeline bands for a specific RM.

    Args:
        sales_code (str): The sales code of the relationship manager.

    Returns:
        list: A list of dictionaries containing expiry timeline band details:
            - expiry_timeline_band (str): The expiry timeline band (e.g., "1 Week", "1 Month").
            - expiry_timeline_band_order (int): The order of the expiry timeline band for sorting.
            - amount (float): The total balance for the expiry timeline band.
    """
    query = '''
        SELECT
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 'Expired'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN '1 Week'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN '2 Weeks'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN '1 Month'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN '2 Months'
                ELSE '> 2 Months'
            END AS expiry_timeline_band,
            SUM(accs.current_balance) AS amount,
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 1
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN 2
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN 3
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN 4
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN 5
                ELSE 6
            END AS expiry_timeline_band_order
        FROM accounts accs
        INNER JOIN product_mapping pm 
            ON accs.type = pm.product_description
        INNER JOIN retail_allocated_portfolio rap 
            ON rap.cust_id = accs.cust_id
        WHERE rap.sales_code = %s
            AND pm.product_map = 'FD'
        GROUP BY expiry_timeline_band, expiry_timeline_band_order
        ORDER BY expiry_timeline_band_order
    '''
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, [sales_code])
            result = cursor.fetchall()

        # Convert the result to a list of dictionaries
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        print(f"Error fetching expiry timeline bands by RM code: {e}")
        return []

def expiry_timeline_band_by_branch(branch_name):
    """
    Fetches the distribution of fixed deposit accounts by expiry timeline bands for a specific branch.

    Args:
        branch_name (str): The branch name.

    Returns:
        list: A list of dictionaries containing expiry timeline band details.
    """
    query = '''
        SELECT
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 'Expired'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN '1 Week'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN '2 Weeks'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN '1 Month'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN '2 Months'
                ELSE '> 2 Months'
            END AS expiry_timeline_band,
            SUM(accs.current_balance) AS amount,
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 1
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN 2
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN 3
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN 4
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN 5
                ELSE 6
            END AS expiry_timeline_band_order
        FROM accounts accs
        INNER JOIN product_mapping pm 
            ON accs.type = pm.product_description
        WHERE LOWER(TRIM(accs.current_branch)) = LOWER(TRIM(%s))
            AND pm.product_map = 'FD'
        GROUP BY expiry_timeline_band, expiry_timeline_band_order
        ORDER BY expiry_timeline_band_order
    '''
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, [branch_name])
            result = cursor.fetchall()

        # Convert the result to a list of dictionaries
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        print(f"Error fetching expiry timeline bands by branch: {e}")
        return []

def expiry_timeline_band_by_segment(segment):
    """
    Fetches the distribution of fixed deposit accounts by expiry timeline bands for a specific segment.

    Args:
        segment (str): The segment of the customer.

    Returns:
        list: A list of dictionaries containing expiry timeline band details.
    """
    query = '''
        SELECT
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 'Expired'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN '1 Week'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN '2 Weeks'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN '1 Month'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN '2 Months'
                ELSE '> 2 Months'
            END AS expiry_timeline_band,
            SUM(accs.current_balance) AS amount,
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 1
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN 2
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN 3
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN 4
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN 5
                ELSE 6
            END AS expiry_timeline_band_order
        FROM accounts accs
        INNER JOIN product_mapping pm 
            ON accs.type = pm.product_description
        INNER JOIN hf_customer c 
            ON c.cust_id = accs.cust_id
        WHERE LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))
            AND pm.product_map = 'FD'
        GROUP BY expiry_timeline_band, expiry_timeline_band_order
        ORDER BY expiry_timeline_band_order
    '''
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, [segment])
            result = cursor.fetchall()

        # Convert the result to a list of dictionaries
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        print(f"Error fetching expiry timeline bands by segment: {e}")
        return []

def expiry_timeline_band_overall():
    """
    Fetches the overall distribution of fixed deposit accounts by expiry timeline bands.

    Returns:
        list: A list of dictionaries containing expiry timeline band details.
    """
    query = '''
        SELECT
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 'Expired'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN '1 Week'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN '2 Weeks'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN '1 Month'
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN '2 Months'
                ELSE '> 2 Months'
            END AS expiry_timeline_band,
            SUM(accs.current_balance) AS amount,
            CASE
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date) THEN 1
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 week') THEN 2
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 weeks') THEN 3
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '1 month') THEN 4
                WHEN accs.expiry_date::date <= (CURRENT_DATE::date + INTERVAL '2 months') THEN 5
                ELSE 6
            END AS expiry_timeline_band_order
        FROM accounts accs
        INNER JOIN product_mapping pm 
            ON accs.type = pm.product_description
        WHERE pm.product_map = 'FD'
        GROUP BY expiry_timeline_band, expiry_timeline_band_order
        ORDER BY expiry_timeline_band_order
    '''
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()

        # Convert the result to a list of dictionaries
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        print(f"Error fetching overall expiry timeline bands: {e}")
        return []


class FixedDepositOverallSummary(models.Manager):
    """
    Manager class for handling queries related to fixed deposit summary.
    """

    def product_summary(self):
        """
        Fetches the overall distribution of fixed deposit accounts by product description.

        Returns:
            list: A list of dictionaries containing product description distribution.
        """
        query = '''
            SELECT
                accs.type,
                accs.currency,
                SUM(accs.current_balance) AS amount
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            WHERE pm.product_map = 'FD'
            GROUP BY accs.type, accs.currency
			ORDER BY amount DESC
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            print(f"Error fetching overall summary: {e}")
            return []

    def segment_summary(self):
        """
        Fetches the overall distribution of fixed deposit accounts by product description.

        Returns:
            list: A list of dictionaries containing product description distribution.
        """
        query = '''
            SELECT
                c.banking_segment,
                SUM(accs.current_balance) AS amount
            FROM accounts accs
            INNER JOIN product_mapping pm 
                ON accs.type = pm.product_description
            INNER JOIN hf_customer c 
                ON c.cust_id = accs.cust_id
            WHERE pm.product_map = 'FD'
            GROUP BY c.banking_segment
			ORDER BY amount DESC
        '''
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchall()

            # Convert the result to a list of dictionaries
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            print(f"Error fetching overall summary: {e}")
            return []


