"""Collections dashboard SQL helpers — ported VERBATIM from the old
backend's core/core.py (current-book, month-by-month trends, bucket, and
customer-collection-data). Read-only raw queries over the shared warehouse
tables (loans, loans_history). Only the imports differ from the source."""
from apps.portfolio.models import Loans
from apps.gceo_dashboard.models import LoansHistory
from apps.collections_team_leaders.models import LoanRepayments
from .models import Collection


def current_book_summary(account_officer):
    """Retrieve a summary of loans for a specific account officer.

    This function queries the database to gather information about loans
    managed by the specified account officer, including the number of
    customers, number of loans, and total loan outstanding value.

    Args:
        account_officer (str): The name of the account officer for whom
            the loan summary is to be retrieved.

    Returns:
        list: A list of dictionaries, each containing the following keys:
            - delay_officer (str): The name of the delay officer.
            - number_of_customers (int): The total number of customers.
            - number_of_loans (int): The total number of loans.
            - loan_outstanding_value (float): The total outstanding loan value
              in euros.
    """
    delay_data = Loans.objects.raw('''
                select 1 id,
                        delay_officer,
                        count(distinct cust_id) as number_of_customers,
                        count(distinct loan_account_no) as number_of_loans,
                        sum(euro_book_balance) as loan_outstanding_value
                from loans
                where lower(trim(delay_officer))= lower(%s)
                group by delay_officer
            ''', [account_officer])
    collections_data_summary = [ {"delay_officer": x.delay_officer,
                 "number_of_customers": x.number_of_customers, 
                 "number_of_loans": x.number_of_loans,
                 "loan_outstanding_value":x.loan_outstanding_value} for x in delay_data]
            
    return collections_data_summary


def all_current_book_summary():
    delay_data = Loans.objects.raw('''
                select 1 id,
                delay_officer,
                 count(distinct cust_id) as number_of_customers,
                 count(distinct loan_account_no) as number_of_loans,
                 sum(euro_book_balance) as loan_outstanding_value
from loans
group by delay_officer
            ''')
    collections_data_summary = [ {"delay_officer": x.delay_officer,
                 "number_of_customers": x.number_of_customers, 
                 "number_of_loans": x.number_of_loans,
                 "loan_outstanding_value":x.loan_outstanding_value
                 } for x in delay_data]
            
    return collections_data_summary


def total_collection_trends_summary():
    delay_data = LoansHistory.objects.raw('''
                with end_month_dates as
(
  SELECT
     date_trunc('month', eom_date)::date,
     max(eom_date)::date as max_month_eod
  FROM
     loans_history
  WHERE 1=1
     and eom_date >= date_trunc('month', CURRENT_DATE - '12 months'::interval)
     -----and eom_date >= '2023-01-01'
  GROUP BY
     date_trunc('month', eom_date)
),
monthly_data as (
select loan_account_no,
       lah.cust_id,
       loan_product,
       delay_officer,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end as bucket,
sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '-1 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_prev_dec,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '0 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_jan,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '1 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_feb,
       sum(
  case
     when
        date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '2 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_mar,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '3 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_apr,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '4 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_may,
        sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '5 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_june,
        sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '6 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_july,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '7 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_aug,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '8 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_sept,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '9 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_oct,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '10 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_nov,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '11 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_dec



from loans_history lah
    left join customers c on lah.cust_id = c.cust_id
where eom_date::date in (select max_month_eod from end_month_dates)
-------and id_product != 40060 ----MOBILE LOAN
group by loan_account_no,
       lah.cust_id,
       loan_product,
       delay_officer,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end)
select 1 as id,
bucket,
sum(bal_prev_dec   ) as bal_prev_dec   ,
sum(bal_jan  ) as bal_jan  ,
sum(bal_feb  ) as bal_feb  ,
sum(bal_mar  ) as bal_mar  ,
sum(bal_apr  ) as bal_apr  ,
sum(bal_may  ) as bal_may  ,
sum(bal_june ) as bal_june ,
sum(bal_july ) as bal_july ,
sum(bal_aug  ) as bal_aug  ,
sum(bal_sept ) as bal_sept ,
sum(bal_oct  ) as bal_oct  ,
sum(bal_nov  ) as bal_nov  ,
sum(bal_dec) as bal_dec,
sum(CASE
         WHEN bal_prev_dec <> 0 AND bal_jan <> 0 THEN bal_jan - bal_prev_dec
         ELSE 0
       END) AS col_jan,
     sum(CASE
         WHEN bal_jan <> 0 AND bal_feb <> 0 THEN bal_feb - bal_jan
         ELSE 0
       END) AS col_feb,
       sum(CASE
         WHEN bal_mar <> 0 AND bal_feb <> 0 THEN bal_mar - bal_feb
         ELSE 0
       END) AS col_mar,
       sum(CASE
         WHEN bal_apr  <> 0 AND bal_mar <> 0 THEN bal_apr - bal_mar
         ELSE 0
       END) AS col_apr,
       sum(CASE
         WHEN bal_may  <> 0 AND bal_apr <> 0 THEN bal_may - bal_apr
         ELSE 0
       END) AS col_may,
       sum(CASE
         WHEN bal_june  <> 0 AND bal_may <> 0 THEN bal_june - bal_may
         ELSE 0
       END) AS col_june,
       sum(CASE
         WHEN bal_july  <> 0 AND bal_june <> 0 THEN bal_july - bal_june
         ELSE 0
       END) AS col_july,
       sum(CASE
         WHEN bal_aug  <> 0 AND bal_july <> 0 THEN bal_aug - bal_july
         ELSE 0
       END) AS col_aug,
        sum(CASE
         WHEN bal_sept  <> 0 AND bal_aug <> 0 THEN bal_sept - bal_aug
         ELSE 0
       END) AS col_sept,
       sum(CASE
         WHEN bal_sept  <> 0 AND bal_aug <> 0 THEN bal_sept - bal_aug
         ELSE 0
       END) AS col_sept,
       sum(CASE
         WHEN bal_oct  <> 0 AND bal_sept <> 0 THEN bal_oct - bal_sept
         ELSE 0
       END) AS col_oct,
       sum(CASE
         WHEN bal_nov  <> 0 AND bal_oct <> 0 THEN bal_nov - bal_oct
         ELSE 0
       END) AS col_nov,
       sum(CASE
         WHEN bal_dec  <> 0 AND bal_nov <> 0 THEN bal_dec - bal_nov
         ELSE 0
       END) AS col_dec

from monthly_data
group by bucket
            ''')
    collections_data_summary = [ {
'bucket': x.bucket,
'bal_prev_dec': x.bal_prev_dec,
'bal_jan': x.bal_jan,
'bal_feb': x.bal_feb,
'bal_mar': x.bal_mar,
'bal_apr': x.bal_apr,
'bal_may': x.bal_may,
'bal_june': x.bal_june,
'bal_july': x.bal_july,
'bal_aug': x.bal_aug,
'bal_sept': x.bal_sept,
'bal_oct': x.bal_oct,
'bal_nov': x.bal_nov,
'bal_dec': x.bal_dec,
'col_jan': x.col_jan,
'col_feb': x.col_feb,
'col_mar': x.col_mar,
'col_apr': x.col_apr,
'col_may': x.col_may,
'col_june': x.col_june,
'col_july': x.col_july,
'col_aug': x.col_aug,
'col_sept': x.col_sept,
'col_sept': x.col_sept,
'col_oct': x.col_oct,
'col_nov': x.col_nov,
'col_dec': x.col_dec,


                 } for x in delay_data]
            
    return collections_data_summary


def delay_officer_collection_trends_summary(account_officer):
    delay_data = LoansHistory.objects.raw('''
                with end_month_dates as
(
  SELECT
     1 as id,
     date_trunc('month', eom_date)::date,
     max(eom_date)::date as max_month_eod
  FROM
     loans_history
  WHERE 1=1
     and eom_date >= date_trunc('month', CURRENT_DATE - '12 months'::interval)
     -----and eom_date >= '2023-01-01'
  GROUP BY
     date_trunc('month', eom_date)
),
monthly_data as (
select 1 as id,
       loan_account_no,
       lah.cust_id,
       loan_product,
       delay_officer,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end as bucket,
sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '-1 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_prev_dec,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '0 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_jan,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '1 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_feb,
       sum(
  case
     when
        date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '2 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_mar,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '3 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_apr,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '4 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_may,
        sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '5 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_june,
        sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '6 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_july,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '7 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_aug,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '8 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_sept,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '9 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_oct,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '10 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_nov,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '11 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_dec



from loans_history lah
    left join customers c on lah.cust_id = c.cust_id
where eom_date::date in (select max_month_eod from end_month_dates)
-------and id_product != 40060 ----MOBILE LOAN
and lower(trim(delay_officer))= lower(%s)
group by loan_account_no,
       lah.cust_id,
       loan_product,
       delay_officer,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end)
select 
1 as id,
bucket,
sum(bal_prev_dec   ) as bal_prev_dec   ,
sum(bal_jan  ) as bal_jan  ,
sum(bal_feb  ) as bal_feb  ,
sum(bal_mar  ) as bal_mar  ,
sum(bal_apr  ) as bal_apr  ,
sum(bal_may  ) as bal_may  ,
sum(bal_june ) as bal_june ,
sum(bal_july ) as bal_july ,
sum(bal_aug  ) as bal_aug  ,
sum(bal_sept ) as bal_sept ,
sum(bal_oct  ) as bal_oct  ,
sum(bal_nov  ) as bal_nov  ,
sum(bal_dec) as bal_dec,
sum(CASE
         WHEN bal_prev_dec <> 0 AND bal_jan <> 0 THEN bal_jan - bal_prev_dec
         ELSE 0
       END) AS col_jan,
     sum(CASE
         WHEN bal_jan <> 0 AND bal_feb <> 0 THEN bal_feb - bal_jan
         ELSE 0
       END) AS col_feb,
       sum(CASE
         WHEN bal_mar <> 0 AND bal_feb <> 0 THEN bal_mar - bal_feb
         ELSE 0
       END) AS col_mar,
       sum(CASE
         WHEN bal_apr  <> 0 AND bal_mar <> 0 THEN bal_apr - bal_mar
         ELSE 0
       END) AS col_apr,
       sum(CASE
         WHEN bal_may  <> 0 AND bal_apr <> 0 THEN bal_may - bal_apr
         ELSE 0
       END) AS col_may,
       sum(CASE
         WHEN bal_june  <> 0 AND bal_may <> 0 THEN bal_june - bal_may
         ELSE 0
       END) AS col_june,
       sum(CASE
         WHEN bal_july  <> 0 AND bal_june <> 0 THEN bal_july - bal_june
         ELSE 0
       END) AS col_july,
       sum(CASE
         WHEN bal_aug  <> 0 AND bal_july <> 0 THEN bal_aug - bal_july
         ELSE 0
       END) AS col_aug,
        sum(CASE
         WHEN bal_sept  <> 0 AND bal_aug <> 0 THEN bal_sept - bal_aug
         ELSE 0
       END) AS col_sept,
       sum(CASE
         WHEN bal_sept  <> 0 AND bal_aug <> 0 THEN bal_sept - bal_aug
         ELSE 0
       END) AS col_sept,
       sum(CASE
         WHEN bal_oct  <> 0 AND bal_sept <> 0 THEN bal_oct - bal_sept
         ELSE 0
       END) AS col_oct,
       sum(CASE
         WHEN bal_nov  <> 0 AND bal_oct <> 0 THEN bal_nov - bal_oct
         ELSE 0
       END) AS col_nov,
       sum(CASE
         WHEN bal_dec  <> 0 AND bal_nov <> 0 THEN bal_dec - bal_nov
         ELSE 0
       END) AS col_dec

from monthly_data
group by bucket
            ''',[account_officer])
    collections_data_summary = [ {
'bucket': x.bucket,
'bal_prev_dec': x.bal_prev_dec,
'bal_jan': x.bal_jan,
'bal_feb': x.bal_feb,
'bal_mar': x.bal_mar,
'bal_apr': x.bal_apr,
'bal_may': x.bal_may,
'bal_june': x.bal_june,
'bal_july': x.bal_july,
'bal_aug': x.bal_aug,
'bal_sept': x.bal_sept,
'bal_oct': x.bal_oct,
'bal_nov': x.bal_nov,
'bal_dec': x.bal_dec,
'col_jan': x.col_jan,
'col_feb': x.col_feb,
'col_mar': x.col_mar,
'col_apr': x.col_apr,
'col_may': x.col_may,
'col_june': x.col_june,
'col_july': x.col_july,
'col_aug': x.col_aug,
'col_sept': x.col_sept,
'col_sept': x.col_sept,
'col_oct': x.col_oct,
'col_nov': x.col_nov,
'col_dec': x.col_dec,


                 } for x in delay_data]
            
    return collections_data_summary


def total_accounts_by_bucket_book_summary():
    delay_data = Loans.objects.raw('''
                select 1 id,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end as bucket,
                 count(distinct cust_id) as number_of_customers,
                 count(distinct loan_account_no) as number_of_loans,
                 sum(euro_book_balance) as loan_outstanding_value
from loans
group by
         case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end
            ''')
    collections_data_summary = [ {"bucket": x.bucket,
                 "number_of_customers": x.number_of_customers, 
                 "number_of_loans": x.number_of_loans,
                 "loan_outstanding_value":x.loan_outstanding_value} for x in delay_data]
            
    return collections_data_summary


def total_accounts_by_bucket_book_summary_account_officer(account_officer):
    delay_data = Loans.objects.raw('''
                select 1 id,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end as bucket,
                 count(distinct cust_id) as number_of_customers,
                 count(distinct loan_account_no) as number_of_loans,
                 sum(euro_book_balance) as loan_outstanding_value
from loans
where lower(trim(delay_officer))= lower(%s)
group by
         case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end
            ''',[account_officer])
    collections_data_summary = [ {"bucket": x.bucket,
                 "number_of_customers": x.number_of_customers, 
                 "number_of_loans": x.number_of_loans,
                 "loan_outstanding_value":x.loan_outstanding_value} for x in delay_data]
            
    return collections_data_summary


def customer_collection_data_current_book_data():
    delay_data = Loans.objects.raw('''
                SELECT
                    1 AS id,
                    l.cust_id,
                    l.account_no,
                    c.firstname,
                    c.lastname,
                    l.delay_officer,
                    rap.sales_code,
                    rap.rm_name,
                    case
                        when l.branch::text='230'  then 'BURUBURU BRANCH'
                        when l.branch::text='410'  then 'ELDORET BRANCH'
                        when l.branch::text='25'  then 'EMBU BRANCH'
                        when l.branch::text='220'  then 'HARAMBEE AVE BRANCH'
                        when l.branch::text='100'  then 'HEAD OFFICE'
                        when l.branch::text ='109' then 'HF WHIZZ'
                        when l.branch::text='19'  then 'HURLINGHAM BRANCH'
                        when l.branch::text='19'  then 'KENYATTA BRANCH'
                        when l.branch::text='600'  then 'KISII BRANCH'
                        when l.branch::text='600'  then 'KISUMU BRANCH'
                        when l.branch::text='16'  then 'KITENGELA BRANCH'
                        when l.branch::text='23'  then 'KOMAROCK BRANCH'
                        when l.branch::text='24'  then 'MACHAKOS BRANCH'
                        when l.branch::text='520'  then 'MERU BRANCH'
                        when l.branch::text='300'  then 'MOMBASA BRANCH'
                        when l.branch::text='17'  then 'NAIVASHA BRANCH'
                        when l.branch::text='400'  then 'NAKURU BRANCH'
                        when l.branch::text ='22' then 'NANYUKI BRANCH'
                        when l.branch::text='300'  then 'NYALI BRANCH'
                        when l.branch::text='510'  then 'NYERI BRANCH'
                        when l.branch::text ='200' then 'REHANI BRANCH'
                        when l.branch::text='100'  then 'RETAIL MORTGAGE SALES'
                        when l.branch::text='20'  then 'RIVERROAD BRANCH'
                        when l.branch::text='250'  then 'RONGAI BRANCH'
                        when l.branch::text='270'  then 'SAMEER BRANCH'
                        when l.branch::text ='500' then 'THIKA BRANCH'
                        when l.branch::text ='260' then 'TRM BRANCH'
                        when l.branch::text='280'  then 'WESTLANDS BRANCH'
                        else 'HEAD OFFICE'
                    end as branch_name,
                    CONCAT(c.firstname, ' ', c.lastname) AS latin_surname,
                    count(distinct l.cust_id) as number_of_customers,
                    count(distinct l.loan_account_no) as number_of_loans,
                    sum(l.euro_book_balance) as loan_outstanding_value,
                    max(days_in_arrears) as days_past_due,
                    max(total_arrears) as total_in_arrears,
                    max(overdue_days) as overdue_days
                FROM
                    loans l
                LEFT JOIN
                    customers c ON l.cust_id = c.cust_id
                LEFT JOIN
                    retail_allocated_portfolio rap ON c.cust_id = rap.cust_id
                GROUP BY
                    l.cust_id,
                    l.account_no,
                    c.firstname,
                    c.lastname,
                    l.delay_officer,
                    rap.sales_code,
                    case
                        when l.branch::text='230'  then 'BURUBURU BRANCH'
                        when l.branch::text='410'  then 'ELDORET BRANCH'
                        when l.branch::text='25'  then 'EMBU BRANCH'
                        when l.branch::text='220'  then 'HARAMBEE AVE BRANCH'
                        when l.branch::text='100'  then 'HEAD OFFICE'
                        when l.branch::text ='109' then 'HF WHIZZ'
                        when l.branch::text='19'  then 'HURLINGHAM BRANCH'
                        when l.branch::text='19'  then 'KENYATTA BRANCH'
                        when l.branch::text='600'  then 'KISII BRANCH'
                        when l.branch::text='600'  then 'KISUMU BRANCH'
                        when l.branch::text='16'  then 'KITENGELA BRANCH'
                        when l.branch::text='23'  then 'KOMAROCK BRANCH'
                        when l.branch::text='24'  then 'MACHAKOS BRANCH'
                        when l.branch::text='520'  then 'MERU BRANCH'
                        when l.branch::text='300'  then 'MOMBASA BRANCH'
                        when l.branch::text='17'  then 'NAIVASHA BRANCH'
                        when l.branch::text='400'  then 'NAKURU BRANCH'
                        when l.branch::text ='22' then 'NANYUKI BRANCH'
                        when l.branch::text='300'  then 'NYALI BRANCH'
                        when l.branch::text='510'  then 'NYERI BRANCH'
                        when l.branch::text ='200' then 'REHANI BRANCH'
                        when l.branch::text='100'  then 'RETAIL MORTGAGE SALES'
                        when l.branch::text='20'  then 'RIVERROAD BRANCH'
                        when l.branch::text='250'  then 'RONGAI BRANCH'
                        when l.branch::text='270'  then 'SAMEER BRANCH'
                        when l.branch::text ='500' then 'THIKA BRANCH'
                        when l.branch::text ='260' then 'TRM BRANCH'
                        when l.branch::text='280'  then 'WESTLANDS BRANCH'
                        else 'HEAD OFFICE'
                    end,
                    rap.rm_name
            ''')
    collections_data_summary = [ {
                "cust_id": x.cust_id,
                "account_no": x.account_no,
                "firstname": x.firstname, 
                "lastname": x.lastname,
                "delay_officer":x.delay_officer,
                "sales_code":x.sales_code,
                "rm_name":x.rm_name,
                "branch_name": x.branch_name,
                "latin_surname":x.latin_surname,
                "number_of_customers":x.number_of_customers,
                "number_of_loans":x.number_of_loans,
                "loan_outstanding_value":x.loan_outstanding_value,
                "days_past_due":x.days_past_due,
                "total_in_arrears":x.total_in_arrears,
                "overdue_days":x.overdue_days
                 } for x in delay_data]
            
    return collections_data_summary


def customer_collection_data_current_book_data_not_rm(delay_officer):
    delay_data = Loans.objects.raw('''
                SELECT
                    1 AS id,
                    l.cust_id,
                    l.account_no,
                    c.firstname,
                    c.lastname,
                    l.delay_officer,
                    rap.sales_code,
                    rap.rm_name,
                    case
                        when l.branch::text='230'  then 'BURUBURU BRANCH'
                        when l.branch::text='410'  then 'ELDORET BRANCH'
                        when l.branch::text='25'  then 'EMBU BRANCH'
                        when l.branch::text='220'  then 'HARAMBEE AVE BRANCH'
                        when l.branch::text='100'  then 'HEAD OFFICE'
                        when l.branch::text ='109' then 'HF WHIZZ'
                        when l.branch::text='19'  then 'HURLINGHAM BRANCH'
                        when l.branch::text='19'  then 'KENYATTA BRANCH'
                        when l.branch::text='600'  then 'KISII BRANCH'
                        when l.branch::text='600'  then 'KISUMU BRANCH'
                        when l.branch::text='16'  then 'KITENGELA BRANCH'
                        when l.branch::text='23'  then 'KOMAROCK BRANCH'
                        when l.branch::text='24'  then 'MACHAKOS BRANCH'
                        when l.branch::text='520'  then 'MERU BRANCH'
                        when l.branch::text='300'  then 'MOMBASA BRANCH'
                        when l.branch::text='17'  then 'NAIVASHA BRANCH'
                        when l.branch::text='400'  then 'NAKURU BRANCH'
                        when l.branch::text ='22' then 'NANYUKI BRANCH'
                        when l.branch::text='300'  then 'NYALI BRANCH'
                        when l.branch::text='510'  then 'NYERI BRANCH'
                        when l.branch::text ='200' then 'REHANI BRANCH'
                        when l.branch::text='100'  then 'RETAIL MORTGAGE SALES'
                        when l.branch::text='20'  then 'RIVERROAD BRANCH'
                        when l.branch::text='250'  then 'RONGAI BRANCH'
                        when l.branch::text='270'  then 'SAMEER BRANCH'
                        when l.branch::text ='500' then 'THIKA BRANCH'
                        when l.branch::text ='260' then 'TRM BRANCH'
                        when l.branch::text='280'  then 'WESTLANDS BRANCH'
                        else 'HEAD OFFICE'
                    end as branch_name,
                    CONCAT(c.firstname, ' ', c.lastname) AS latin_surname,
                    count(distinct l.cust_id) as number_of_customers,
                    count(distinct l.loan_account_no) as number_of_loans,
                    sum(l.euro_book_balance) as loan_outstanding_value,
                    max(days_in_arrears) as days_past_due,
                    max(total_arrears) as total_in_arrears,
                    max(overdue_days) as overdue_days
                FROM
                    loans l
                LEFT JOIN
                    customers c ON l.cust_id = c.cust_id
                LEFT JOIN
                    retail_allocated_portfolio rap ON c.cust_id = rap.cust_id
                WHERE 1=1
                AND NOT lower(trim(l.delay_officer)) = lower(%s)
                AND overdue_days > 0                   
                GROUP BY
                    l.cust_id,
                    l.account_no,
                    c.firstname,
                    c.lastname,
                    l.delay_officer,
                    rap.sales_code,
                    case
                        when l.branch::text='230'  then 'BURUBURU BRANCH'
                        when l.branch::text='410'  then 'ELDORET BRANCH'
                        when l.branch::text='25'  then 'EMBU BRANCH'
                        when l.branch::text='220'  then 'HARAMBEE AVE BRANCH'
                        when l.branch::text='100'  then 'HEAD OFFICE'
                        when l.branch::text ='109' then 'HF WHIZZ'
                        when l.branch::text='19'  then 'HURLINGHAM BRANCH'
                        when l.branch::text='19'  then 'KENYATTA BRANCH'
                        when l.branch::text='600'  then 'KISII BRANCH'
                        when l.branch::text='600'  then 'KISUMU BRANCH'
                        when l.branch::text='16'  then 'KITENGELA BRANCH'
                        when l.branch::text='23'  then 'KOMAROCK BRANCH'
                        when l.branch::text='24'  then 'MACHAKOS BRANCH'
                        when l.branch::text='520'  then 'MERU BRANCH'
                        when l.branch::text='300'  then 'MOMBASA BRANCH'
                        when l.branch::text='17'  then 'NAIVASHA BRANCH'
                        when l.branch::text='400'  then 'NAKURU BRANCH'
                        when l.branch::text ='22' then 'NANYUKI BRANCH'
                        when l.branch::text='300'  then 'NYALI BRANCH'
                        when l.branch::text='510'  then 'NYERI BRANCH'
                        when l.branch::text ='200' then 'REHANI BRANCH'
                        when l.branch::text='100'  then 'RETAIL MORTGAGE SALES'
                        when l.branch::text='20'  then 'RIVERROAD BRANCH'
                        when l.branch::text='250'  then 'RONGAI BRANCH'
                        when l.branch::text='270'  then 'SAMEER BRANCH'
                        when l.branch::text ='500' then 'THIKA BRANCH'
                        when l.branch::text ='260' then 'TRM BRANCH'
                        when l.branch::text='280'  then 'WESTLANDS BRANCH'
                        else 'HEAD OFFICE'
                    end,
                    rap.rm_name
            ''', [delay_officer])
    collections_data_summary = [ {
                "cust_id": x.cust_id,
                "account_no": x.account_no,
                "firstname": x.firstname, 
                "lastname": x.lastname,
                "delay_officer":x.delay_officer,
                "sales_code":x.sales_code,
                "rm_name":x.rm_name,
                "branch_name": x.branch_name,
                "latin_surname":x.latin_surname,
                "number_of_customers":x.number_of_customers,
                "number_of_loans":x.number_of_loans,
                "loan_outstanding_value":x.loan_outstanding_value,
                "days_past_due":x.days_past_due,
                "total_in_arrears":x.total_in_arrears,
                "overdue_days":x.overdue_days
                 } for x in delay_data]
            
    return collections_data_summary


def team_leader_current_book_summary():
    delay_data = Loans.objects.raw('''
                SELECT
                    1 AS id,
                    l.delay_officer,
                    count(distinct l.cust_id) as number_of_customers,
                    count(distinct l.loan_account_no) as number_of_loans,
                    sum(l.euro_book_balance) as loan_outstanding_value,
                    max(days_in_arrears) as days_past_due,
                    max(total_arrears) as total_in_arrears,
                    max(overdue_days) as overdue_days
                FROM
                    loans l
                GROUP BY
                    l.delay_officer
            ''')
    collections_data_summary = [ {"delay_officer": x.delay_officer,
                 "number_of_customers": x.number_of_customers, 
                 "number_of_loans": x.number_of_loans,
                 "loan_outstanding_value":x.loan_outstanding_value,
                 "days_past_due":x.days_past_due,
                 "total_total_arrears":x.total_in_arrears,
                 "overdue_days":x.overdue_days
                 } for x in delay_data]
            
    return collections_data_summary


def team_leader_delay_officer_collection_trends_summary():
    delay_data = LoansHistory.objects.raw('''
                with end_month_dates as
(
  SELECT
     1 as id,
     date_trunc('month', eom_date)::date,
     max(eom_date)::date as max_month_eod
  FROM
     loans_history
  WHERE 1=1
     and eom_date >= date_trunc('month', CURRENT_DATE - '12 months'::interval)
     -----and eom_date >= '2023-01-01'
  GROUP BY
     date_trunc('month', eom_date)
),
monthly_data as (
select 1 as id,
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end as bucket,
sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '-1 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_prev_dec,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '0 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_jan,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '1 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_feb,
       sum(
  case
     when
        date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '2 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_mar,
       sum(
  case
     when
        date_trunc('month', eom_date::date )= ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '3 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_apr,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '4 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_may,
        sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '5 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_june,
        sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '6 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_july,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '7 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_aug,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '8 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_sept,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '9 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_oct,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '10 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_nov,
       sum( case
     when
       date_trunc('month', eom_date::date ) = ( date_trunc('month', (date (date_trunc('year', current_date)::date)::date)) + INTERVAL '11 month' )::date
     then
        euro_book_balance
     else
        0
  end
) as bal_dec



from loans_history lah
    left join customers c on lah.cust_id = c.cust_id
where eom_date::date in (select max_month_eod from end_month_dates)
-------and id_product != 40060 ----MOBILE LOAN
group by 
       case when overdue_days < 0 then 'normal'
            when overdue_days < 30 then 'pre_deliquency'
            when overdue_days <= 60 then '30-60'
            when overdue_days <= 90 then '61-90'
            else  'npl'   end)
select 
1 as id,
bucket,
sum(bal_prev_dec   ) as bal_prev_dec   ,
sum(bal_jan  ) as bal_jan  ,
sum(bal_feb  ) as bal_feb  ,
sum(bal_mar  ) as bal_mar  ,
sum(bal_apr  ) as bal_apr  ,
sum(bal_may  ) as bal_may  ,
sum(bal_june ) as bal_june ,
sum(bal_july ) as bal_july ,
sum(bal_aug  ) as bal_aug  ,
sum(bal_sept ) as bal_sept ,
sum(bal_oct  ) as bal_oct  ,
sum(bal_nov  ) as bal_nov  ,
sum(bal_dec) as bal_dec,
sum(CASE
         WHEN bal_prev_dec <> 0 AND bal_jan <> 0 THEN bal_jan - bal_prev_dec
         ELSE 0
       END) AS col_jan,
     sum(CASE
         WHEN bal_jan <> 0 AND bal_feb <> 0 THEN bal_feb - bal_jan
         ELSE 0
       END) AS col_feb,
       sum(CASE
         WHEN bal_mar <> 0 AND bal_feb <> 0 THEN bal_mar - bal_feb
         ELSE 0
       END) AS col_mar,
       sum(CASE
         WHEN bal_apr  <> 0 AND bal_mar <> 0 THEN bal_apr - bal_mar
         ELSE 0
       END) AS col_apr,
       sum(CASE
         WHEN bal_may  <> 0 AND bal_apr <> 0 THEN bal_may - bal_apr
         ELSE 0
       END) AS col_may,
       sum(CASE
         WHEN bal_june  <> 0 AND bal_may <> 0 THEN bal_june - bal_may
         ELSE 0
       END) AS col_june,
       sum(CASE
         WHEN bal_july  <> 0 AND bal_june <> 0 THEN bal_july - bal_june
         ELSE 0
       END) AS col_july,
       sum(CASE
         WHEN bal_aug  <> 0 AND bal_july <> 0 THEN bal_aug - bal_july
         ELSE 0
       END) AS col_aug,
        sum(CASE
         WHEN bal_sept  <> 0 AND bal_aug <> 0 THEN bal_sept - bal_aug
         ELSE 0
       END) AS col_sept,
       sum(CASE
         WHEN bal_sept  <> 0 AND bal_aug <> 0 THEN bal_sept - bal_aug
         ELSE 0
       END) AS col_sept,
       sum(CASE
         WHEN bal_oct  <> 0 AND bal_sept <> 0 THEN bal_oct - bal_sept
         ELSE 0
       END) AS col_oct,
       sum(CASE
         WHEN bal_nov  <> 0 AND bal_oct <> 0 THEN bal_nov - bal_oct
         ELSE 0
       END) AS col_nov,
       sum(CASE
         WHEN bal_dec  <> 0 AND bal_nov <> 0 THEN bal_dec - bal_nov
         ELSE 0
       END) AS col_dec

from monthly_data
group by bucket
            ''')
    collections_data_summary = [ {
'bucket': x.bucket,
'bal_prev_dec': x.bal_prev_dec,
'bal_jan': x.bal_jan,
'bal_feb': x.bal_feb,
'bal_mar': x.bal_mar,
'bal_apr': x.bal_apr,
'bal_may': x.bal_may,
'bal_june': x.bal_june,
'bal_july': x.bal_july,
'bal_aug': x.bal_aug,
'bal_sept': x.bal_sept,
'bal_oct': x.bal_oct,
'bal_nov': x.bal_nov,
'bal_dec': x.bal_dec,
'col_jan': x.col_jan,
'col_feb': x.col_feb,
'col_mar': x.col_mar,
'col_apr': x.col_apr,
'col_may': x.col_may,
'col_june': x.col_june,
'col_july': x.col_july,
'col_aug': x.col_aug,
'col_sept': x.col_sept,
'col_sept': x.col_sept,
'col_oct': x.col_oct,
'col_nov': x.col_nov,
'col_dec': x.col_dec,


                 } for x in delay_data]
            
    return collections_data_summary


def CollectionsTLSummary():
    prospects_list = Collection.objects.raw('''
    WITH DATA AS
  (SELECT delay_officer
   FROM loans
   GROUP BY delay_officer)
SELECT pmp.*
FROM hf_collections_feedback pmp
LEFT JOIN DATA ON pmp.collection_officer_code = data.delay_officer
    ''')
    return prospects_list


def Repayment_data_eom_summary_data():
    custfeedback = LoanRepayments.objects.raw(""" 
            select 1 as id,
       delay_officer,
       lh.status,
       date_trunc('months',eom_date) as eom_dates,
       sum(principal_paid) as total_principal_paid,
       sum(interest_paid)  as total_interest_paid,
       sum(principal_paid+interest_paid) as total_principle_plus_intrest,
       max(total_drawndown_amount) as total_total_drawndown_amount,
       min(balance) as balance
from  loan_repayments lr
inner join loans_history lh on (lh.loan_account_no::numeric = lr.loan_account_number::numeric and  date_trunc('day',eom_date::date)::date= date_trunc('day',transaction_date::date)::date)
group by delay_officer,
       date_trunc('months',eom_date),
         lh.status                                    
                                                  """)
    customerfeedback = [{
            "id": x.id,
            "delay_officer": x.delay_officer,
            "status": x.status,
            "eom_dates": x.eom_dates,
            "total_principal_paid": x.total_principal_paid,
            "total_interest_paid": x.total_interest_paid,
            "total_principle_plus_intrest": x.total_principle_plus_intrest,
            "total_total_drawndown_amount": x.total_total_drawndown_amount,
            "balance": x.balance,
            "loan_account_number":x.loan_account_number,
            } for x in custfeedback]
    return customerfeedback


############# HFDI Dashboard APIs #########################3
