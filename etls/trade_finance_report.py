#!/usr/bin/env python
# coding: utf-8

# In[ ]:





# In[1]:


import numpy as np
import pandas as pd
import csv
import xlsxwriter
import calendar
import os

from datetime import (datetime as dt, date,timedelta)
from calendar import monthrange
from pandas import DataFrame as df


# In[2]:


import app_settings as app  # type: ignore


import psycopg2 as psql


# In[3]:


# Step 1: Create the directory if it does not exist
path = os.path.join(os.getcwd(), "attachments", "tradefinance")
if not os.path.exists(path):
    os.makedirs(path)

# Step 2: Change the current working directory to the new directory
os.chdir(path)
print("Current working directory:", os.getcwd())

# Step 3: Delete all files in the directory
# Note: This does not delete subdirectories, only files
for file_name in os.listdir(path):
    file_path = os.path.join(path, file_name)
    if os.path.isfile(file_path):
        os.remove(file_path)
        print(f"Deleted file: {file_path}")

from psycopg2.pool import SimpleConnectionPool

# Create a connection pool
connection_pool = SimpleConnectionPool(
    1, 10,  # Min and max connections
    dbname=app.postgres['db'],
    user=app.postgres['user'],
    password=app.postgres['password'],
    host=app.postgres['host'],
    port=app.postgres['port']
)


# In[ ]:





# In[4]:


p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

#mobile loans
role_count_map_query = '''
select * from branch_employee_dmc_data

'''
overall_sales_person_mapping = pd.read_sql_query(role_count_map_query , p_conn)

p_conn.close()

# overall_sales_person_mapping = pd.read_excel("branch_employee_dmc_data.xlsx")
keep_columns =['active','staff_name','sales_code','staff_zone','staff_role','brn_code','staff_branch','target_trade_finance_income','target_trade_finance_value','start_date','exit_date','employment_date']
overall_sales_person_mapping=overall_sales_person_mapping[keep_columns]
overall_sales_person_mapping.head()
overall_sales_person_mapping.columns


# In[5]:


# role mapping for the data to ensure no duplicates
role_mapping = overall_sales_person_mapping.sort_values(by=['sales_code','active'], ascending=[True,False])
role_mapping =role_mapping.drop_duplicates(subset='sales_code', keep='first')
# role_mapping = role_mapping[['sales_code','staff_name','active']]
role_mapping


# In[ ]:





# In[6]:


"""## Formulas"""


#Getting reporting date
today = dt.now()

def get_reporting_date(today):
    # if today is not the end month date, return report date as previous Friday
    # if last day of the month is Friday, report date is that Friday
    # if last day of the month is not Friday, report date is last day of the month
    # if last day of the month is Sunday, report date will be the previous Friday

    next_month = today.replace(day=28) + timedelta(days =4) # get the last day of the current month(every month has atleast 28 days
    current_month_last_day = next_month - timedelta(days = next_month.day)

    if today.day <= 7 and today.weekday() < 4:  # First week (before Friday)
        previous_month_end = today - timedelta(days=today.day)
        if previous_month_end.weekday() == 4:  # Friday
            reporting_date = previous_month_end
        elif previous_month_end.weekday() == 6:  # Sunday
            reporting_date = previous_month_end - timedelta(days=2)
        else:
            reporting_date = previous_month_end


    elif today.date() == current_month_last_day.date():
        if current_month_last_day.weekday() == 4: # check whether it's on Friday
            reporting_date = current_month_last_day
        elif current_month_last_day.weekday() == 6: # check if it's on sunday
            reporting_date = current_month_last_day - timedelta(days = 2) # ensure reporting date is Friday
        else:
            reporting_date = current_month_last_day

    else:
# this checks when last was Friday and adding the 7 ensures the number is non-negative
        days_since_friday = (today.weekday()-4+7)%7
        reporting_date = today - timedelta( days=days_since_friday)

    formatted_date = reporting_date.strftime('%d-%b-%Y')
    report_month_number = reporting_date.month
    year = reporting_date.year
    report_month = reporting_date.strftime('%b')

    return formatted_date , report_month_number, report_month,year


formatted_date, report_month_number, report_month, year =get_reporting_date(today)

formatted_date

today = dt.now()
# today

#get the last day of the month
def get_last_day_of_month(year,report_month_number):


 last_day_of_month = calendar.monthrange(year,report_month_number)[1]
 return (year,report_month_number,last_day_of_month)

last_day_of_month = get_last_day_of_month(year,report_month_number)
last_day_of_month

date_obj = date(*last_day_of_month)  # convert to %d-%m-%Y
formatted_last_day_of_month = date_obj.strftime('%d-%m-%Y')

formatted_last_day_of_month

#Get months of the reporting year
months = [dt(year - 1, 12, 1).strftime('%b-%y')] + [dt(year, i, 1).strftime('%b-%y') for i in range(1, 13)]
months

month_column_order = months[1:report_month_number+1]
month_column_order



#Getting reporting date
# today = date.today()

# def get_reporting_date():
#   if today.weekday() == 1:   #Monday is 0
#      reporting_date = today- timedelta(days=4)

#   else:
#    reporting_date = today- timedelta(days =1)  #returns previous day as reporting date

#   formatted_date = reporting_date.strftime('%d-%b-%Y')  #format the date to dd-mmm-yyyy

#   return formatted_date

# formatted_date =get_reporting_date()

# formatted_date

# merged_roles_table

# year_to_date_fraction

def year_to_date_fraction(ytd_date):
  start_year = date(ytd_date.year,1,1)
  end_year = date(ytd_date.year+1,1,1)

  total_days = (end_year - start_year).days
  elapsed_days = (ytd_date - start_year).days

  fraction = elapsed_days/ total_days

  return fraction

# formatted_date =get_reporting_date()

ytd_date = dt.strptime(formatted_date, "%d-%b-%Y").date()
fraction = year_to_date_fraction(ytd_date)
fraction



def calculation_formulas(df):
    column_name = f'{report_month}-{year}'
    if column_name in df.columns:
        df['month_actuals'] = df[column_name]
    
    # if report_month in df.columns:
    #     df['month_actuals'] = df[report_month]

    else:
        df['month_actuals'] = 0

    if 'annual_targets' in df.columns:

        df['monthly_targets'] = df['annual_targets'] / 12
        df['month_score'] = (df['month_actuals'] / df['monthly_targets']).clip(lower= 0,upper=1.2)
        df['ytd_target'] = df['annual_targets'] * fraction
        df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(lower=0,upper=1.2)
        df['ytd_score_uncapped'] = (df['ytd_cumulative'] / df['ytd_target']).clip(lower=0)
        
    else:
        df['annual_targets'] =0
        df['monthly_targets'] =0
        df['month_score']=0
        df['ytd_score'] =0

    return df



def total_row(df):
    total_row = df.sum(numeric_only =True)
    month_ratio = (df['month_actuals'].sum() / df['monthly_targets'].sum())
    total_row['month_score'] = min(max(month_ratio,0),1.2)
    year_ratio = (df['ytd_cumulative'].sum() / df['ytd_target'].sum())
    total_row['ytd_score'] = min(max(year_ratio,0),1.2)
    total_row['ytd_score_uncapped'] = max(year_ratio,0)
    total_row = pd.DataFrame(total_row).T
    total_row = total_row.fillna(" ")
    # total_row.index = ['total']
    df = pd.concat([df, total_row],axis = 0)

    return df



def rank_performance(dataframe,sort_column):
    # Exclude the Total row
    df_without_last_row = dataframe.iloc[:-1].copy()
    df_without_last_row['rank'] = df_without_last_row[sort_column].rank(ascending=False, method='dense')

    # Sort the new DataFrame by 'rank'

    sorted_df = df_without_last_row.sort_values(by='rank')
    sorted_df['rank'] = pd.to_numeric(sorted_df['rank'], errors='coerce')
    sorted_df['rank'] = sorted_df['rank'].astype(float).astype(int)

    # Get the Total row
    last_row = dataframe.iloc[-1:]

    # Reattach the Total row to the sorted DataFrame
    result_df = pd.concat([sorted_df, last_row])
    result_df = result_df.reindex(['rank']+[column for column in result_df.columns if column not in ['rank']], axis=1)

    return result_df



def roles_calculation_formulas(df):
    column_name = f'{report_month}-{year}'
    if column_name in df.columns:
        df['month_actuals'] = df[column_name]

    else:
        df['month_actuals'] = 0

    df['ytd_target'] = df['annual_targets'] * fraction
    df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(lower=0,upper=1.2)
    df['ytd_score_uncapped'] = (df['ytd_cumulative'] / df['ytd_target']).clip(lower=0)

    return df



def roles_value_calculation_formulas(df):

    df['ytd_target'] = df['annual_targets'] * fraction
    df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(lower=0,upper=1.2)

    return df



def roles_total_row(df):
    total_row = df.sum(numeric_only =True)
    year_ratio = (df['ytd_cumulative'].sum() / df['ytd_target'].sum())
    total_row['ytd_score'] = min(max(year_ratio,0),1.2)
    total_row['ytd_score_uncapped'] = max(year_ratio,0)
    total_row = pd.DataFrame(total_row).T
    total_row = total_row.fillna(" ")
    # total_row.index = ['total']
    df = pd.concat([df, total_row],axis = 0)

    return df


# In[ ]:





# In[7]:


def month_to_date_fraction(mtd_date):

  total_days = monthrange(mtd_date.year,mtd_date.month)[1]
  current_day = mtd_date.day

  fraction = current_day/ total_days

  return fraction

mtd_date = dt.strptime(formatted_date, "%d-%b-%Y").date()

mtd_fraction= month_to_date_fraction(mtd_date)
mtd_fraction


# In[8]:


# def calculate_annual_targets(group, monthly_target_columns, mtd_date):
#     """
#     group: all rows for one staff (same code)
#     """
#     annual_targets = {}

#     #For DSR roles
#     if group.iloc[0]['staff_role'] in ['PB DSR', 'SME DSR']:
#         row = group.iloc[0]  # only one role per year is assumed
#         employment_date = pd.to_datetime(row['employment_date'])

#         for target_column in monthly_target_columns:
#             monthly_target = row[target_column]
#             total_weighted_target = 0

#             for month in range(1, 13):  # Jan to Dec
#                 report_month_date = pd.Timestamp(year=mtd_date.year, month=month, day=1)

#                 if report_month_date < employment_date:
#                     target_weight = 0
#                 else:
#                     months_since_employment = (
#                         (report_month_date.year - employment_date.year) * 12
#                         + (report_month_date.month - employment_date.month)
#                     )

#                     if months_since_employment <= 6:
#                         target_weight = 0.5  # half targets for <= 6 months
#                     else:
#                         target_weight = 1.0  # full targets after

#                 actual_month_target = target_weight * monthly_target
#                 total_weighted_target += actual_month_target

#             annual_targets[f'annual_{target_column}'] = total_weighted_target

#     # For non-DSRs (to handle promotions)
#     else:
#         report_year = mtd_date.year
#         for target_column in monthly_target_columns:
#             annual_targets[f'annual_{target_column}'] = 0  

#         # loop through each role entry for that staff (promotions)
#         for _, row in group.iterrows():
#             start_date = pd.to_datetime(row['start_date'])
#             end_date = (
#                 pd.to_datetime(row['exit_date'])
#                 if pd.notnull(row['exit_date'])
#                 else pd.Timestamp(year=report_year, month=12, day=31)
#             )

#             # restrict interval to current reporting year
#             role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#             role_end   = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))

#             if role_start > role_end:
#                 continue  # not active this year

#             # count active months inclusive
#             months_active = (role_end.year - role_start.year) * 12 + (role_end.month - role_start.month) + 1

#             for target_column in monthly_target_columns:
#                 monthly_target = row[target_column] if pd.notnull(row[target_column]) else 0
#                 annual_targets[f'annual_{target_column}'] += monthly_target * months_active

#     return pd.Series(annual_targets)


# In[9]:


def calculate_annual_targets(group, monthly_target_columns, mtd_date):
    annual_targets = {}
    report_year = mtd_date.year

    for col in monthly_target_columns:
        annual_targets[f'annual_{col}'] = 0

    for _, row in group.iterrows():
        start_date = pd.to_datetime(row['start_date'])

        end_date = (
            pd.to_datetime(row['exit_date'])
            if pd.notnull(row['exit_date'])
            else pd.Timestamp(year=report_year, month=12, day=31)
        )
        
        role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
        role_end   = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))


        if role_start > role_end:
            continue

        months_active = ((role_end.year - role_start.year) * 12 + (role_end.month - role_start.month)+ 1)

        for col in monthly_target_columns:
            monthly_target = row.get(col, 0)
            if pd.isna(monthly_target):
                monthly_target = 0

            annual_targets[f'annual_{col}'] += monthly_target * months_active

    return pd.Series(annual_targets)


# In[10]:


# annual_targets_df =filtered_overall_sales_person_mapping.apply(calculate_annual_targets, monthly_target_columns = monthly_target_column, axis=1 )
# filtered_overall_sales_person_mapping = pd.concat([filtered_overall_sales_person_mapping,annual_targets_df], axis=1)


# In[11]:


# Apply the function to each row
monthly_target_columns =['target_trade_finance_income','target_trade_finance_value']

annual_targets_df = (
    overall_sales_person_mapping
    .sort_values(['sales_code','start_date'])
    .groupby('sales_code')
    .apply(calculate_annual_targets, monthly_target_columns=monthly_target_columns, mtd_date=mtd_date)
    .reset_index()
)

filtered_sales_person_targets_with_annual_targets = pd.merge(
    overall_sales_person_mapping,
    annual_targets_df,
    on='sales_code',
    how='left'
)


# In[12]:


filtered_sales_person_targets_with_annual_targets[filtered_sales_person_targets_with_annual_targets['sales_code']=='AKL3116']


# In[13]:


def sales_persons_year_to_date_fraction(df, year, formatted_date):
    df['start_date'] = pd.to_datetime(df['start_date'])
    formatted_date = pd.to_datetime(formatted_date, dayfirst=True)
    start_of_year = pd.Timestamp(f"{year}-01-01")
    end_of_year   = pd.Timestamp(f"{year}-12-31")

    # Get earliest start_date per code, capped at start_of_year
    effective_start = (
        df.groupby('sales_code')['start_date']
          .transform(lambda x: max(min(x), start_of_year))
    )

    def get_ytd_fraction(start_date):
        total_days = (end_of_year - start_date).days
        if total_days <= 0:
            return 1.0 if formatted_date >= end_of_year else 0.0
        elapsed_days = (formatted_date - start_date).days
        return max(0.0, min(elapsed_days / total_days, 1.0))

    df['ytd_fraction'] = effective_start.apply(get_ytd_fraction)
    return df
    
filtered_sales_person_targets_with_annual_targets = sales_persons_year_to_date_fraction(filtered_sales_person_targets_with_annual_targets,year,formatted_date)


# In[14]:


filtered_sales_person_targets_with_annual_targets.head(3)


# In[15]:


# def calculate_annual_targets(row, monthly_target_columns):
#     start_date = row['start_date']

#     annual_targets = {}

#     for target_column in monthly_target_columns:
#         monthly_targets = row[target_column]
#         months_remaining = 12 - (start_date.month) +1
#         annual_targets['annual' + '_' + target_column] = monthly_targets * months_remaining  # each persons targets depend on how many months they have in the year

#     return pd.Series(annual_targets)


# In[16]:


columns_to_keep= ['active','staff_name','sales_code','staff_zone','staff_role','brn_code','staff_branch','target_trade_finance_value',
                  'annual_target_trade_finance_value','annual_target_trade_finance_income','target_trade_finance_income']
#select active employees
filtered_overall_sales_person_mapping =filtered_sales_person_targets_with_annual_targets[filtered_sales_person_targets_with_annual_targets['active']==1][columns_to_keep]
# filtered_overall_sales_person_mapping

filtered_overall_sales_person_mapping=filtered_overall_sales_person_mapping.drop(columns={'active'}).fillna(0)
filtered_overall_sales_person_mapping.head()

# Convert 'start_date' to datetime
# filtered_overall_sales_person_mapping['start_date'] = pd.to_datetime(filtered_overall_sales_person_mapping['start_date'])
filtered_overall_sales_person_mapping[filtered_overall_sales_person_mapping['staff_role']=='COMMERCIAL RM']


# In[17]:


# filtered_overall_sales_person_mapping.shape


# In[18]:


# filtered_overall_sales_person_mapping = filtered_overall_sales_person_mapping.drop(columns={'start_date','target_trade_finance_income'}).fillna(0)

filtered_overall_sales_person_mapping['brn_code'] = filtered_overall_sales_person_mapping['brn_code'].astype(int)


# In[19]:


"""#### branch mapping"""

# branch_map= pd.read_excel("branch_map.xlsx")
# branch_map = branch_map.to_dict(orient='records')

branch = [{'branch_1': 'BURUBURU',
  'code': 230,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'ELDORET', 'code': 410, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'EMBU', 'code': 25, 'region': 'REGION 2', 'rm': ''},
 {'branch_1': 'EMBU BRANCH', 'code': 25, 'region': 'REGION 2', 'rm': ''},
 {'branch_1': 'GILLHOUSE',
  'code': 220,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'HARAMBEE',
  'code': 220,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'HO', 'code': 100, 'region': 'HO', 'rm': 'HO'},
 {'branch_1': 'HURLINGHAM',
  'code': 19,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'KISUMU', 'code': 600, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'KITENGELA',
  'code': 16,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'KOMAROCK', 'code': 23, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'MACHAKOS', 'code': 24, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'MERU', 'code': 520, 'region': 'REGION 2', 'rm': ''},
 {'branch_1': 'MOMBASA',
  'code': 300,
  'region': 'REGION 2',
  'rm': ''},
 {'branch_1': 'NAIVASHA', 'code': 17, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'NAKURU', 'code': 400, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'NANYUKI',
  'code': 22,
  'region': 'REGION 2',
  'rm': ''},
 {'branch_1': 'NYERI',
  'code': 510,
  'region': 'REGION 2',
  'rm': ''},
 {'branch_1': 'REHANI', 'code': 200, 'region': 'REGION 3', 'rm': ''},
 {'branch_1': 'RIVER ROAD',
  'code': 20,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'RIVERROAD',
  'code': 20,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'RONGAI',
  'code': 250,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'SAMEER',
  'code': 270,
  'region': 'REGION 1',
  'rm': ''},
 {'branch_1': 'THIKA',
  'code': 500,
  'region': 'REGION 2',
  'rm': ''},
 {'branch_1': 'TRM', 'code': 260, 'region': 'REGION 2', 'rm': ''},
 {'branch_1': 'WESTLANDS',
  'code': 280,
  'region': 'REGION 1',
  'rm': ''}]

branch_map = pd.DataFrame(branch)

p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

branch_mapping_query = '''
select * from branch_final_employee_dmc_data

'''
overall_branch_mapping = pd.read_sql_query(branch_mapping_query , p_conn)

p_conn.close()

# overall_branch_mapping = pd.read_excel("branch_final_employee_dmc_data.xlsx")
overall_branch_mapping.head()

columns_to_keep= ['staff_branch','brn_code','staff_zone','target_trade_finance_income','target_trade_finance_value']
filtered_overall_branch_mapping =overall_branch_mapping[columns_to_keep]
filtered_overall_branch_mapping.head()


# In[77]:


"""### data cleaning & manipulation"""

# Get the current year
# Check if today's date is before 20th January of the current year to account for a grace period in time taken to migrate the tables in produciton to the new year
current_year = (dt.now().year - 1) if (dt.now().month == 1 and dt.now().day < 10) else dt.now().year

# SQL query to fetch sales report data for the current year
p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

trade_transactions_query = f'''
    SELECT 
        originating_branch,rm_name,rm_code,guarantee_ref,product_type,
        customer_id,segment,our_customer as our_applicant_customer,beneficiary,currency,
        amount_fcy,issue_date,expiry_date,commission_lcy as commission,month,fx_rate,year,security_type,cash_cover_amount,cash_cover_percentage,other_security
    FROM trade_finance_data 
    WHERE year IN ('{current_year}');
'''
trade_transactions = pd.read_sql_query(trade_transactions_query , p_conn)

p_conn.close()
# trade_transactions= pd.read_excel("trade_finance_dt.xlsx")#compiled data year to date from raw data
trade_transactions['rm_code']


# In[20]:


trade_transactions['customer_id']= trade_transactions['customer_id'].fillna(0).astype(int)

trade_transactions['issue_date'].fillna(0)
trade_transactions['expiry_date'].fillna(0)

# trade_transactions['issue_date']= pd.to_datetime(trade_transactions['issue_date'], format = '%Y-%b-%d', errors ='coerce').dt.strftime('%d-%b-%Y')
# trade_transactions['expiry_date']= pd.to_datetime(trade_transactions['expiry_date'], format = '%Y-%b-%d', errors ='coerce').dt.strftime('%d-%b-%Y')
trade_transactions['issue_date']= pd.to_datetime(trade_transactions['issue_date'])
trade_transactions['expiry_date']= pd.to_datetime(trade_transactions['expiry_date'])



#correct names/remove spaces/ clean product type column
trade_transactions.loc[trade_transactions['product_type'] == 'BID BOND', 'product_type'] = 'BIDBONDS'
trade_transactions.loc[trade_transactions['product_type'] == 'BIDBOND', 'product_type'] = 'BIDBONDS'
trade_transactions.loc[trade_transactions['product_type'] == 'PAYMENT GTE', 'product_type'] = 'PAYMENT GUARANTEE'
trade_transactions.loc[trade_transactions['product_type'] == 'PERFORMANCEBOND', 'product_type'] = 'PERFORMANCE BOND'
trade_transactions.loc[trade_transactions['product_type'] == 'PERFORMANCE BOND ', 'product_type'] = 'PERFORMANCE BOND'
trade_transactions.loc[trade_transactions['product_type'] == 'CREDITPAYMENTGUARANTEE', 'product_type'] = 'CREDIT PAYMENT GUARANTEE'
trade_transactions.loc[trade_transactions['product_type'] == 'PAYMENTGUARANTEE', 'product_type'] = 'PAYMENT GUARANTEE'
trade_transactions.loc[trade_transactions['product_type'] == 'ADVANCEPAYMENTGUARANTEE', 'product_type'] = 'ADVANCE PAYMENT GUARANTEE'
trade_transactions.loc[trade_transactions['product_type'] == 'GENERALGUARANTEE', 'product_type'] = 'GENERAL GUARANTEE'
trade_transactions.loc[trade_transactions['product_type'] == 'EXPORTLC', 'product_type'] = 'EXPORT LC'



#rename SME and/or BUSINESS BANKING to BB
trade_transactions.loc[trade_transactions['segment'] == 'SME', 'segment'] = 'BB'
trade_transactions.loc[trade_transactions['segment'] == 'BUSINESS BANKING', 'segment'] = 'BB'
trade_transactions.loc[trade_transactions['segment'] == 'CORPORATE', 'segment'] = 'COMMERCIAL'



#rename branch name
trade_transactions.loc[trade_transactions['originating_branch'] == 'HARAMBEE AVENUE', 'originating_branch'] = 'HARAMBEE'

# trade_transactions.drop_duplicates(inplace =True)

trade_transactions.dtypes


# In[21]:


"""#### add required columns"""

trade_transactions['amount_lcy'] = (trade_transactions['amount_fcy'] * trade_transactions['fx_rate']).apply(lambda x: format(x,'.0f'))
trade_transactions.head(2)

trade_transactions = pd.merge(trade_transactions,branch_map,left_on ='originating_branch',right_on ='branch_1',how = 'left')
# trade_transactions.head(2)

filtered_overall_branch_mapping.columns

trade_transactions = pd.merge(trade_transactions,filtered_overall_branch_mapping,left_on ='code',right_on ='brn_code',how = 'left')
trade_transactions = trade_transactions.drop(columns=['branch_1','code','target_trade_finance_income','target_trade_finance_value','rm'], inplace =False)
# trade_transactions.head()

trade_transactions.rename(columns={'staff_role':'role','staff_branch':'branch','brn_code':'branch_code'}, inplace= True)
trade_transactions.columns


# In[22]:


# trade_transactions= pd.merge(trade_transactions,rm_map, on='rm_name', how= 'left')
# trade_transactions.columns


# In[23]:


trade_transactions= pd.merge(trade_transactions,role_mapping, left_on='rm_code',right_on= 'sales_code', how= 'left')
trade_transactions.columns


# In[ ]:





# In[ ]:





# In[24]:


# trade_transactions= pd.merge(trade_transactions,filtered_overall_sales_person_mapping, left_on= 'rm_code', right_on='sales_code', how= 'left')
# trade_transactions.head(1)


# In[25]:


trade_transactions.drop(columns=['staff_zone_y','brn_code','staff_branch','rm_code','target_trade_finance_income','target_trade_finance_value'], inplace= True)

trade_transactions.rename(columns={'staff_zone_x':'zone','sales_code':'rm_code','staff_role':'role'}, inplace =True)
trade_transactions.columns


# In[26]:


trade_transactions['commission']= pd.to_numeric(trade_transactions['commission'],errors= 'coerce')    #convert to numeric
trade_transactions['amount_lcy']=pd.to_numeric(trade_transactions['amount_lcy'],errors= 'coerce')



rate = (trade_transactions['commission'] / trade_transactions['amount_lcy']) * 100

# for infinite values replace with 0
trade_transactions['est_rate'] = np.where(
    np.isinf(rate) | (rate < 0),
    '0',
    rate.round(1).astype(str)
) + '%'



trade_transactions['month_name'] = pd.to_datetime(trade_transactions['month'].astype(str) + f'-{year}', format = '%m-%Y').dt.strftime('%b-%Y')
trade_transactions['month_name']

trade_transactions.columns

# new_column_order=['originating_branch', 'rm_name', 'guarantee_ref', 'product_type',
#        'customer_id', 'segment', 'our_applicant_customer', 'beneficiary',
#        'currency', 'amount_fcy', 'fx_rate', 'amount_lcy', 'issue_date', 'expiry_date','rm_code', 'commission','month',
#                   'est_rate','security_type','cash_cover_amount','cash_cover_percentage','other_security',
#                   'month_name','staff_name','role', 'branch', 'branch_code', 'zone','region' ]
# trade_transactions= trade_transactions[new_column_order]

# trade_transactions.columns


# In[27]:
# ── 1. Canonical column order — single source of truth ───────────────────────
new_column_order = [
    'originating_branch', 'rm_name', 'guarantee_ref', 'product_type',
    'customer_id', 'segment', 'our_applicant_customer', 'beneficiary',
    'currency', 'amount_fcy', 'fx_rate', 'amount_lcy',
    'issue_date', 'expiry_date', 'commission', 'est_rate',
    'security_type', 'cash_cover_amount', 'cash_cover_percentage', 'other_security',
    'rm_code', 'staff_name', 'role',          # <-- role kept
    'month', 'month_name', 'year',            # <-- year kept
    'branch', 'branch_code', 'zone', 'region',
]

trade_transactions = trade_transactions[new_column_order]


trade_transactions['month_name']


# In[28]:


# # -------------------------------
# # Write the trade summary data to the database
# # -------------------------------
# weighted_sales_branch_trade_data_dump_db_columns = [
#     { "col_name": "originating_branch", "data_type": "varchar(20)"},
#     { "col_name": "rm_name", "data_type": "varchar(100)"},
#     { "col_name": "guarantee_ref", "data_type": "varchar(100)"},
#     { "col_name": "product_type", "data_type": "varchar(50)"},
#     { "col_name": "customer_id", "data_type": "numeric"},
#     { "col_name": "segment", "data_type": "varchar(20)"},
#     { "col_name": "our_applicant_customer", "data_type": "varchar(200)"},
#     { "col_name": "beneficiary", "data_type": "varchar(200)"},
#     { "col_name": "currency", "data_type": "varchar(20)"},
#     { "col_name": "amount_fcy", "data_type": "numeric"},
#     { "col_name": "fx_rate", "data_type": "numeric"},
#     { "col_name": "amount_lcy", "data_type": "numeric"},
#     { "col_name": "issue_date", "data_type": "varchar(50)"},
#     { "col_name": "expiry_date", "data_type": "varchar(50)"},
#     { "col_name": "commission", "data_type": "numeric"},
#     { "col_name": "est_rate", "data_type": "varchar(20)"},
#     { "col_name": "security_type", "data_type": "varchar(100)"},
#     { "col_name": "cash_cover_amount", "data_type": "numeric"},
#     { "col_name": "cash_cover_percentage", "data_type": "varchar(20)"},
#     { "col_name": "other_security", "data_type": "varchar(200)"},
#     { "col_name": "rm_code", "data_type": "varchar(50)"},
#     { "col_name": "staff_name", "data_type": "varchar(200)"},
#     { "col_name": "month", "data_type": "numeric"},
#     { "col_name": "month_name", "data_type": "varchar(3)"},
#     { "col_name": "year", "data_type": "numeric"},
#     { "col_name": "branch", "data_type": "varchar(50)"},
#     { "col_name": "branch_code", "data_type": "numeric"},
#     { "col_name": "zone", "data_type": "varchar(10)"},
#     { "col_name": "region", "data_type": "varchar(10)"},

# ]

# weighted_sales_branch_trade_data_dump_tables_def = [
#     {
#         "data_df": trade_transactions,
#         "table_name": "weighted_sales_branch_trade_data_dump",
#         "columns_with_data_types": weighted_sales_branch_trade_data_dump_db_columns,
#     },
# ]

# app.etl_write_to_postgres_db(weighted_sales_branch_trade_data_dump_tables_def,connection_pool.getconn(),3000)


# ── 2. DB schema — must exactly mirror COLUMN_ORDER ──────────────────────────
weighted_sales_branch_trade_data_dump_db_columns = [
    {"col_name": "originating_branch",      "data_type": "varchar(20)"},
    {"col_name": "rm_name",                 "data_type": "varchar(100)"},
    {"col_name": "guarantee_ref",           "data_type": "varchar(100)"},
    {"col_name": "product_type",            "data_type": "varchar(50)"},
    {"col_name": "customer_id",             "data_type": "numeric"},
    {"col_name": "segment",                 "data_type": "varchar(20)"},
    {"col_name": "our_applicant_customer",  "data_type": "varchar(200)"},
    {"col_name": "beneficiary",             "data_type": "varchar(200)"},
    {"col_name": "currency",                "data_type": "varchar(20)"},
    {"col_name": "amount_fcy",              "data_type": "numeric"},
    {"col_name": "fx_rate",                 "data_type": "numeric"},
    {"col_name": "amount_lcy",              "data_type": "numeric"},
    {"col_name": "issue_date",              "data_type": "varchar(50)"},
    {"col_name": "expiry_date",             "data_type": "varchar(50)"},
    {"col_name": "commission",              "data_type": "numeric"},
    {"col_name": "est_rate",                "data_type": "varchar(20)"},
    {"col_name": "security_type",           "data_type": "varchar(100)"},
    {"col_name": "cash_cover_amount",       "data_type": "numeric"},
    {"col_name": "cash_cover_percentage",   "data_type": "varchar(20)"},
    {"col_name": "other_security",          "data_type": "varchar(200)"},
    {"col_name": "rm_code",                 "data_type": "varchar(50)"},
    {"col_name": "staff_name",              "data_type": "varchar(200)"},
    {"col_name": "role",                    "data_type": "varchar(50)"},   # <-- ADDED
    {"col_name": "month",                   "data_type": "numeric"},
    {"col_name": "month_name",              "data_type": "varchar(10)"},   # 'Jan-2026' needs >3 chars
    {"col_name": "year",                    "data_type": "numeric"},       # <-- ADDED
    {"col_name": "branch",                  "data_type": "varchar(50)"},
    {"col_name": "branch_code",             "data_type": "numeric"},
    {"col_name": "zone",                    "data_type": "varchar(10)"},
    {"col_name": "region",                  "data_type": "varchar(10)"},
]

# ── 3. Validation guard — catches this class of bug before hitting the DB ─────
db_cols   = [c["col_name"] for c in weighted_sales_branch_trade_data_dump_db_columns]
df_cols   = list(trade_transactions.columns)

in_db_not_df  = set(db_cols)  - set(df_cols)
in_df_not_db  = set(df_cols)  - set(db_cols)
order_matches = db_cols == df_cols

if in_db_not_df or in_df_not_db or not order_matches:
    raise ValueError(
        f"\nSchema mismatch — fix before writing to DB:"
        f"\n  In DB schema but not DataFrame : {in_db_not_df}"
        f"\n  In DataFrame but not DB schema : {in_df_not_db}"
        f"\n  Column order matches           : {order_matches}"
    )

# ── 4. Write ──────────────────────────────────────────────────────────────────
weighted_sales_branch_trade_data_dump_tables_def = [
    {
        "data_df": trade_transactions,
        "table_name": "weighted_sales_branch_trade_data_dump",
        "columns_with_data_types": weighted_sales_branch_trade_data_dump_db_columns,
    }
]

app.etl_write_to_postgres_db(
    weighted_sales_branch_trade_data_dump_tables_def,
    connection_pool.getconn(),
    3000
)


# In[29]:


# trade_transactions.drop_duplicates(inplace =True)

trade_transactions.shape

"""## Product tables"""

def product_type_vol(dataframe, index, month_column_name, value_column_name):
    vol_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 


    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in vol_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['total'])
        
    vol_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'count', margins = True, margins_name='total')
    vol_amt = vol_amt.fillna(0).reset_index()

    for month in vol_month_order:
        if  month not in vol_amt.columns:
            vol_amt[month]=0
          
    vol_amt['ytd_cumulative'] = vol_amt[past_and_reporting_months].sum(axis=1)                          
    vol_amt =vol_amt[[index] + past_and_reporting_months +['ytd_cumulative']]  

    return vol_amt

product_vol_table = product_type_vol(trade_transactions, index = 'product_type', value_column_name = 'amount_lcy', month_column_name='month_name')

product_vol_table


# In[30]:


def product_type_val(dataframe, index, month_column_name, value_column_name):
    val_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 


    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in val_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['total'])
        
    value_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    value_amt = value_amt.fillna(0).reset_index()

    for month in val_month_order:
        if  month not in value_amt.columns:
            value_amt[month]=0
          
    value_amt['ytd_cumulative'] = value_amt[past_and_reporting_months].sum(axis=1)                          
    value_amt =value_amt[[index] + past_and_reporting_months +['ytd_cumulative']]  

    return value_amt

product_value_table = product_type_val(trade_transactions, index = 'product_type', value_column_name = 'amount_lcy', month_column_name='month_name')

product_value_table


# In[31]:


def product_type_income(dataframe, index, month_column_name, value_column_name):
    inc_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 


    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in inc_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['total'])
        
    income_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    income_amt = income_amt.fillna(0).reset_index()

    for month in inc_month_order:
        if  month not in income_amt.columns:
            income_amt[month]=0
          
    income_amt['ytd_cumulative'] = income_amt[past_and_reporting_months].sum(axis=1)                          
    income_amt =income_amt[[index] + past_and_reporting_months +['ytd_cumulative']]  

    return income_amt

product_income_table = product_type_income(trade_transactions, index = 'product_type', value_column_name = 'commission', month_column_name='month_name')

product_income_table


# In[32]:


"""## Segment tables"""


# In[33]:


segment_targets = [{'segment':'BB','annual_target_trade_finance_value':2082500000,'annual_target_trade_finance_income':31237500},
                   {'segment':'COMMERCIAL','annual_target_trade_finance_value':4550000000,'annual_target_trade_finance_income':68250000}]

segment_targets_table = pd.DataFrame(segment_targets).reset_index(drop=True)
segment_targets_table


# In[ ]:





# In[34]:


def segment_type_vol(dataframe, index, segment_column_name, value_column_name):
  segment_vol_amt = pd.pivot_table(dataframe, columns= segment_column_name, index = index, values = value_column_name, aggfunc = 'count', margins = True, margins_name='total')
  segment_vol_amt = segment_vol_amt.fillna(0)
  segment_vol_amt = segment_vol_amt.reset_index()

  return segment_vol_amt

segment_vol_table = segment_type_vol(trade_transactions, index = 'month_name', value_column_name = 'month', segment_column_name='segment')
segment_vol_table= segment_vol_table.drop(columns = 'total')
segment_vol_table

def segment_type_val(dataframe, index, segment_column_name, value_column_name):
  segment_val_amt = pd.pivot_table(dataframe, columns= segment_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
  segment_val_amt = segment_val_amt.fillna(0)
  segment_val_amt = segment_val_amt.reset_index()
  return segment_val_amt

segment_val_table = segment_type_val(trade_transactions, index = 'month_name', value_column_name = 'amount_lcy', segment_column_name='segment')
segment_val_table= segment_val_table.drop(columns = 'total')
segment_val_table



def segment_type_income(dataframe, index, segment_column_name, value_column_name):
  segment_income_amt = pd.pivot_table(dataframe, columns= segment_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
  segment_income_amt = segment_income_amt.fillna(0)
  segment_income_amt = segment_income_amt.reset_index()
  return segment_income_amt

segment_income_table = segment_type_income(trade_transactions, index = 'month_name', value_column_name = 'commission', segment_column_name='segment')

segment_income_table= segment_income_table.drop(columns = 'total')

segment_income_table = segment_income_table.sort_values(by = 'month_name')
segment_income_table = segment_income_table.rename(columns={'BB':'BB_inc','COMMERCIAL':'COMMERCIAL_inc'})
segment_income_table



segment_merge1 = pd.merge(segment_vol_table,segment_val_table, left_on= 'month_name', right_on= 'month_name', how = 'left',suffixes = ('_vol','_val'), sort = True)
segment_merge1

segment_table = pd.merge(segment_merge1, segment_income_table, on ='month_name')
month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
segment_table['month_name'] = pd.Categorical(segment_table['month_name'], categories = month_order, ordered = True)
ordered_segment_table = segment_table.sort_values(by ='month_name')
ordered_segment_table = ordered_segment_table.reset_index(drop = True)
ordered_segment_table

ordered_segment_table['TOTAL VOLUME']= ordered_segment_table['BB_vol']+ordered_segment_table['COMMERCIAL_vol']
ordered_segment_table['TOTAL VALUE']= ordered_segment_table['BB_val']+ordered_segment_table['COMMERCIAL_val']
ordered_segment_table['TOTAL INCOME']= ordered_segment_table['BB_inc']+ordered_segment_table['COMMERCIAL_inc']

ordered_segment_table.rename(columns={'month_name':'month'}, inplace= True)

column_order=['month','BB_vol','COMMERCIAL_vol','TOTAL VOLUME','BB_val',
              'COMMERCIAL_val','TOTAL VALUE','BB_inc','COMMERCIAL_inc','TOTAL INCOME']
ordered_segment_table=ordered_segment_table[column_order]
ordered_segment_table


# In[ ]:





# In[35]:


def segment_value(dataframe, index, month_column_name, value_column_name):
    value_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 


    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in value_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
        
    segment_val_amt = pd.pivot_table(dataframe, columns= month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    segment_val_amt = segment_val_amt.fillna(0).reset_index()

    for month in value_month_order:
        if  month not in segment_val_amt.columns:
            segment_val_amt[month]=0
          
    segment_val_amt['Total'] = segment_val_amt[past_and_reporting_months].sum(axis=1)                          
    segment_val_amt =segment_val_amt[[index] + past_and_reporting_months +['Total']]  

    return segment_val_amt

segment_value_table = segment_value(trade_transactions, index = 'segment', value_column_name = 'amount_lcy', month_column_name='month_name')
# segment_value_table= segment_value_table.drop(columns = 'Total')
segment_value_table


# In[36]:


segment_value_table_with_targets = pd.merge(segment_targets_table,segment_value_table, on ='segment', how = 'left')
segment_value_table_with_targets = segment_value_table_with_targets.fillna(0)
segment_value_table_with_targets.drop(columns= {'annual_target_trade_finance_income'}, inplace = True)
segment_value_table_with_targets.rename(columns= {'annual_target_trade_finance_value':'annual_targets','Total':'ytd_cumulative'}, inplace = True)

segment_value_table_with_targets = calculation_formulas(segment_value_table_with_targets)

segment_value_table_with_targets = total_row(segment_value_table_with_targets)


segment_value_table_with_targets = rank_performance(segment_value_table_with_targets,'ytd_score_uncapped')
segment_value_table_with_targets = segment_value_table_with_targets.reset_index(drop = True)
segment_value_table_with_targets = segment_value_table_with_targets.drop(columns={'ytd_score_uncapped'})


cols_to_front = ['rank','segment','annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in segment_value_table_with_targets.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

segment_value_table_with_targets= segment_value_table_with_targets[column_order]
segment_value_table_with_targets.head(2)


# In[ ]:





# In[37]:


def segment_revenue(dataframe, index, month_column_name, value_column_name):
    rev_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 


    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in rev_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
        
    segment_comm_amt = pd.pivot_table(dataframe, columns= month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    segment_comm_amt = segment_comm_amt.fillna(0).reset_index()

    for month in rev_month_order:
        if  month not in segment_comm_amt.columns:
            segment_comm_amt[month]=0
          
    segment_comm_amt['Total'] = segment_comm_amt[past_and_reporting_months].sum(axis=1)                          
    segment_comm_amt =segment_comm_amt[[index] + past_and_reporting_months +['Total']]  

    return segment_comm_amt

segment_revenue_table = segment_revenue(trade_transactions, index = 'segment', value_column_name = 'commission', month_column_name='month_name')

segment_revenue_table


# In[38]:


segment_revenue_table_with_targets = pd.merge(segment_targets_table,segment_revenue_table, on ='segment', how = 'left')
segment_revenue_table_with_targets = segment_revenue_table_with_targets.fillna(0)
segment_revenue_table_with_targets.drop(columns= {'annual_target_trade_finance_value'}, inplace = True)
segment_revenue_table_with_targets.rename(columns= {'annual_target_trade_finance_income':'annual_targets','Total':'ytd_cumulative'}, inplace = True)

segment_revenue_table_with_targets = calculation_formulas(segment_revenue_table_with_targets)

segment_revenue_table_with_targets = total_row(segment_revenue_table_with_targets)


segment_revenue_table_with_targets = rank_performance(segment_revenue_table_with_targets,'ytd_score_uncapped')
segment_revenue_table_with_targets = segment_revenue_table_with_targets.reset_index(drop = True)
segment_revenue_table_with_targets = segment_revenue_table_with_targets.drop(columns={'ytd_score_uncapped'})


cols_to_front = ['rank','segment','annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in segment_revenue_table_with_targets.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

segment_revenue_table_with_targets= segment_revenue_table_with_targets[column_order]
segment_revenue_table_with_targets.head(2)


# In[ ]:





# In[ ]:





# In[ ]:





# In[39]:


"""## Region, zone & branch tables

#### Branches
"""

branch_targets= pd.merge(filtered_overall_branch_mapping, branch_map,left_on ='brn_code', right_on = 'code',how= 'left')

branch_targets = branch_targets.drop(columns= ['branch_1','code','rm'])

order= ['staff_branch','brn_code','staff_zone','region','target_trade_finance_income','target_trade_finance_value']
branch_targets= branch_targets[order]

branch_targets.drop_duplicates(inplace =True)
# branch_targets = branch_targets.reset_index(drop=True)
branch_targets


# In[40]:


"""##### branch commission"""

def branch_month_comm(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    comm_amt = comm_amt.fillna(0).reset_index()

    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['total']]  
    return comm_amt

branch_month_comm_table = branch_month_comm(trade_transactions, month_column_name='month_name', index = 'branch',value_column_name = 'commission')

branch_month_comm_table



branch_commission_table = pd.merge(branch_targets,branch_month_comm_table, left_on ='staff_branch', right_on = 'branch', how = 'left')
branch_commission_table = branch_commission_table.fillna(0)
branch_commission_table.drop(columns= {'branch','brn_code','target_trade_finance_value'}, inplace = True)
branch_commission_table.rename(columns= {'staff_branch':'branch','staff_zone':'zone','target_trade_finance_income':'annual_targets','total':'ytd_cumulative'}, inplace = True)
branch_commission_table

branch_commission_table = calculation_formulas(branch_commission_table)

branch_commission_table = total_row(branch_commission_table)
branch_commission_table.tail()

branch_commission_table = rank_performance(branch_commission_table,'ytd_score_uncapped')
branch_commission_table = branch_commission_table.reset_index(drop = True)
branch_commission_table = branch_commission_table.drop(columns={'ytd_score_uncapped'})

branch_commission_table.columns

cols_to_front = ['rank','branch', 'zone', 'region','annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in branch_commission_table.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

branch_commission_table= branch_commission_table[column_order]
branch_commission_table.head(2)


# In[41]:


all_branches_df = branch_targets[['staff_branch']].reset_index(drop=True)
all_branches_df


# In[42]:


"""#####  branch sales volume"""

def branch_sales_vol(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
    sales_vol_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'count', margins = True, margins_name='total')
    sales_vol_amt = sales_vol_amt.fillna(0).reset_index()


    for month in sales_month_order:
        if  month not in sales_vol_amt.columns:
            sales_vol_amt[month]=0
          
    sales_vol_amt['total'] = sales_vol_amt[past_and_reporting_months].sum(axis=1)                          
    sales_vol_amt =sales_vol_amt[[index] + past_and_reporting_months +['total']]  

    return sales_vol_amt

branch_sales_vol_table = branch_sales_vol( trade_transactions, month_column_name='month_name', index = 'branch',value_column_name = 'amount_lcy')
branch_sales_vol_table = branch_sales_vol_table.rename(columns= {'total': 'ytd_cumulative'})
branch_sales_vol_table


# In[43]:


branch_sales_vol_table_without_total_row = branch_sales_vol_table.iloc[:-1]
# branch_sales_vol_table_total_row = branch_sales_vol_table.iloc[-1:]

branch_sales_vol_table = pd.merge(all_branches_df,branch_sales_vol_table_without_total_row, left_on='staff_branch', right_on ='branch', how= 'left').reset_index(drop=True).fillna(0)
# branch_sales_vol_table = branch_sales_vol_table.drop(columns={'branch'})
# branch_sales_vol_table = pd.concat([branch_sales_vol_table_df,branch_sales_vol_table_total_row])
# branch_sales_vol_table = branch_sales_vol_table.reset_index(drop=True)
branch_sales_vol_table


# In[ ]:





# In[44]:


branch_sales_vol_table = pd.merge(branch_sales_vol_table, branch_commission_table[['rank','branch']], left_on = 'staff_branch', right_on='branch', how = 'left')
branch_sales_vol_table = branch_sales_vol_table.fillna(0)
branch_sales_vol_table


# In[45]:


value_to_drop = [0]
branch_sales_vol_table = branch_sales_vol_table[~branch_sales_vol_table['staff_branch'].isin(value_to_drop)]


# In[46]:


vol_total_row = branch_sales_vol_table.sum(numeric_only =True)
vol_total_row = pd.DataFrame(vol_total_row).T
branch_sales_vol_table = pd.concat([branch_sales_vol_table, vol_total_row],axis = 0)

branch_sales_vol_table = branch_sales_vol_table.sort_values(by = 'rank')
branch_sales_vol_table.drop(columns={'rank','branch_x','branch_y','staff_branch'},inplace=True)
branch_sales_vol_table = branch_sales_vol_table.reset_index(drop=True)
branch_sales_vol_table


# In[47]:


"""##### branch sales value"""

def branch_sales_val(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
    sales_val_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    sales_val_amt = sales_val_amt.fillna(0).reset_index()

    for month in sales_month_order:
        if  month not in sales_val_amt.columns:
            sales_val_amt[month]=0
          
    sales_val_amt['total'] = sales_val_amt[past_and_reporting_months].sum(axis=1)                          
    sales_val_amt =sales_val_amt[[index] + past_and_reporting_months +['total']] 

    return sales_val_amt



sales_val_table = branch_sales_val( trade_transactions, month_column_name='month_name', index = 'branch',value_column_name = 'amount_lcy')
sales_val_table = sales_val_table.rename(columns= {'total': 'ytd_cumulative'})
sales_val_table



branch_sales_val= pd.merge(branch_targets,sales_val_table, left_on= 'staff_branch', right_on='branch', how= 'left')
branch_sales_val.drop_duplicates(inplace =True)
branch_sales_val = branch_sales_val.fillna(0)
branch_sales_val.head(1)

branch_sales_val.drop(columns=['branch','brn_code','staff_zone','region','target_trade_finance_income'], inplace = True)

branch_sales_val.rename(columns={'staff_branch':'branch','target_trade_finance_value':'annual_targets'}, inplace= True)
branch_sales_val.head(1)



branch_sales_val_table = calculation_formulas(branch_sales_val)
branch_sales_val_table

branch_sales_val_table= total_row(branch_sales_val_table)
branch_sales_val_table = branch_sales_val_table.reset_index(drop= True)
branch_sales_val_table

branch_sales_val_table = pd.merge(branch_sales_val_table, branch_commission_table[['rank','branch']], left_on = 'branch', right_on = 'branch', how = 'right')
branch_sales_val_table = branch_sales_val_table.sort_values(by = 'rank').fillna(0)
branch_sales_val_table.drop(columns={'rank','branch'},inplace=True)
branch_sales_val_table = branch_sales_val_table.reset_index(drop=True)
branch_sales_val_table = branch_sales_val_table.drop(columns={'ytd_score_uncapped'})



cols_to_front = ['annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in branch_sales_val_table.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

branch_sales_val_table= branch_sales_val_table[column_order]
branch_sales_val_table.head()

# remove the word 'BRANCH' from branch names
branch_commission_table['branch'] = branch_commission_table['branch'].str.replace(' BRANCH','')
branch_commission_table.head()


# In[48]:


"""#### Zones

##### zone commission
"""

def zone_month_comm(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    comm_amt = comm_amt.fillna(0).reset_index()

    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['total']]  

    return comm_amt

zone_month_comm_table = zone_month_comm(trade_transactions, month_column_name='month_name', index = 'zone',value_column_name = 'commission')
zone_month_comm_table = zone_month_comm_table.rename(columns={'total':'ytd_cumulative'})
zone_month_comm_table


# In[49]:


columns_to_keep = ['staff_zone','target_trade_finance_income','target_trade_finance_value']
zone_targets = branch_targets[columns_to_keep]

zone_targets = zone_targets.groupby('staff_zone')[['target_trade_finance_income','target_trade_finance_value']].sum().reset_index()
zone_targets

zone_commission_table = pd.merge(zone_targets,zone_month_comm_table, left_on ='staff_zone', right_on = 'zone', how = 'left')
zone_commission_table.drop(columns = ['zone','target_trade_finance_value'], inplace = True)
zone_commission_table.rename(columns = {'staff_zone':'zone','target_trade_finance_income':'annual_targets'}, inplace = True)


zone_commission_table



zone_commission_table = calculation_formulas(zone_commission_table)
zone_commission_table = total_row(zone_commission_table)
zone_commission_table = rank_performance(zone_commission_table,'ytd_score_uncapped')
zone_commission_table =zone_commission_table.drop(columns={'ytd_score_uncapped'})
cols_to_front = ['rank','zone','annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in zone_commission_table.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

zone_commission_table= zone_commission_table[column_order]
zone_commission_table.head()



"""##### zone sales volume"""

def zone_sales_vol(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
    sales_vol_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'count', margins = True, margins_name='total')
    sales_vol_amt = sales_vol_amt.fillna(0).reset_index()


    for month in sales_month_order:
        if  month not in sales_vol_amt.columns:
            sales_vol_amt[month]=0
          
    sales_vol_amt['total'] = sales_vol_amt[past_and_reporting_months].sum(axis=1)                          
    sales_vol_amt =sales_vol_amt[[index] + past_and_reporting_months +['total']]  

    return sales_vol_amt



zone_sales_vol_table = zone_sales_vol( trade_transactions, month_column_name='month_name', index = 'zone',value_column_name = 'amount_lcy')
zone_sales_vol_table = zone_sales_vol_table.rename(columns= {'total': 'ytd_cumulative'})
# remove HO
value_to_remove = ['HO']

zone_sales_vol_table = zone_sales_vol_table[~zone_sales_vol_table['zone'].isin(value_to_remove)]

zone_sales_vol_table

zone_sales_vol_table = pd.merge(zone_sales_vol_table, zone_commission_table[['rank','zone']], on = 'zone', how = 'left')
# zone_sales_vol_table = zone_sales_vol_table.sort_values(by = 'rank')
zone_sales_vol_table.drop(columns={'rank','zone','zone'}, inplace = True)

zone_sales_vol_table



"""##### zone sales value"""

def zone_sales_val(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
    sales_val_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    sales_val_amt = sales_val_amt.fillna(0).reset_index()

    for month in sales_month_order:
        if  month not in sales_val_amt.columns:
            sales_val_amt[month]=0
          
    sales_val_amt['total'] = sales_val_amt[past_and_reporting_months].sum(axis=1)                          
    sales_val_amt =sales_val_amt[[index] + past_and_reporting_months +['total']] 

    return sales_val_amt


sales_val_table = zone_sales_val( trade_transactions, month_column_name='month_name', index = 'zone',value_column_name = 'amount_lcy')
sales_val_table = sales_val_table.rename(columns= {'total': 'ytd_cumulative'})

sales_val_table



zone_sales_val_table= pd.merge(zone_targets,sales_val_table, left_on='staff_zone',right_on='zone', how = 'left')
zone_sales_val_table

zone_sales_val_table = zone_sales_val_table.rename(columns ={'target_trade_finance_value':'annual_targets'})
zone_sales_val_table = zone_sales_val_table.drop(columns ={'zone','target_trade_finance_income'})
zone_sales_val_table

zone_sales_val_table = calculation_formulas(zone_sales_val_table)
zone_sales_val_table = total_row(zone_sales_val_table)

zone_sales_val_table



zone_sales_val_table = pd.merge(zone_sales_val_table, zone_commission_table[['rank','zone']], left_on ='staff_zone',right_on = 'zone', how = 'left')
zone_sales_val_table = zone_sales_val_table.sort_values(by = 'rank')
zone_sales_val_table.drop(columns={'rank','zone','staff_zone','ytd_score_uncapped'}, inplace = True)

cols_to_front = ['annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in zone_sales_val_table.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

zone_sales_val_table= zone_sales_val_table[column_order]
zone_sales_val_table.head()


# In[ ]:





# In[50]:


"""#### Regions"""

region_rm_map=[
{'region':'REGION 1','rm':''},
{'region':'REGION 2','rm':''},
{'region':'REGION 3','rm':''},
]
region_rm = pd.DataFrame(list(region_rm_map))
region_rm

columns_to_keep = ['region','target_trade_finance_income','target_trade_finance_value']
region_targets = branch_targets[columns_to_keep]

region_targets = region_targets.groupby('region')[['target_trade_finance_income','target_trade_finance_value']].sum().reset_index()
region_targets

#add rm region heads
region_targets = pd.merge(region_targets,region_rm, on= 'region', how = 'left')
region_targets


# In[ ]:





# In[51]:


"""##### Regions commission"""

def Region_month_comm(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    comm_amt = comm_amt.fillna(0).reset_index()

    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['total']]  

    return comm_amt


region_month_comm_table = branch_month_comm(trade_transactions, month_column_name='month_name', index = 'region',value_column_name = 'commission')

region_month_comm_table

# region_targets

region_commission_table = pd.merge(region_targets,region_month_comm_table, on = 'region', how = 'left').fillna(0)

region_commission_table = region_commission_table.rename(columns ={'target_trade_finance_income':'annual_targets','total':'ytd_cumulative'})
region_commission_table = region_commission_table.drop(columns={'target_trade_finance_value'})


region_commission_table = calculation_formulas(region_commission_table)
region_commission_table = region_commission_table.fillna(0)
region_commission_table = total_row(region_commission_table)

region_commission_table = rank_performance(region_commission_table,'ytd_score_uncapped')
# print(region_commission_table)
region_commission_table =region_commission_table.drop(columns={'ytd_score_uncapped'})


cols_to_front = ['rank','region','rm','annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in region_commission_table.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

region_commission_table= region_commission_table[column_order]
region_commission_table.head()


# In[52]:


"""##### regions sales vol

"""

def region_sales_vol(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
    sales_vol_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'count', margins = True, margins_name='total')
    sales_vol_amt = sales_vol_amt.fillna(0).reset_index()


    for month in sales_month_order:
        if  month not in sales_vol_amt.columns:
            sales_vol_amt[month]=0
          
    sales_vol_amt['total'] = sales_vol_amt[past_and_reporting_months].sum(axis=1)                          
    sales_vol_amt =sales_vol_amt[[index] + past_and_reporting_months +['total']]  

    return sales_vol_amt



region_sales_vol_table = region_sales_vol( trade_transactions, month_column_name='month_name', index = 'region',value_column_name = 'amount_lcy')
region_sales_vol_table = region_sales_vol_table.rename(columns= {'total': 'ytd_cumulative'})
region_sales_vol_table


# In[53]:


region_sales_vol_table_without_total_row = region_sales_vol_table.iloc[:-1].copy()
region_sales_vol_table_total_row = region_sales_vol_table.iloc[-1:]

region_sales_vol_table_df = pd.merge(region_rm,region_sales_vol_table_without_total_row, on='region', how= 'left').reset_index(drop=True).fillna(0)
region_sales_vol_table_df = region_sales_vol_table_df.drop(columns={'rm'})
region_sales_vol_table = pd.concat([region_sales_vol_table_df,region_sales_vol_table_total_row])

region_sales_vol_table


# In[54]:


region_sales_vol_table = pd.merge(region_sales_vol_table, region_commission_table[['rank','region']], on='region', how = 'left')
region_sales_vol_table = region_sales_vol_table.sort_values(by = 'rank').fillna(0)
region_sales_vol_table.drop(columns={'rank','region'},inplace =True)
region_sales_vol_table = region_sales_vol_table.reset_index(drop=True)
region_sales_vol_table


# In[55]:


"""##### regions sales value

"""

def region_sales_val(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
        
    sales_val_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    sales_val_amt = sales_val_amt.fillna(0).reset_index()

    for month in sales_month_order:
        if  month not in sales_val_amt.columns:
            sales_val_amt[month]=0
          
    sales_val_amt['total'] = sales_val_amt[past_and_reporting_months].sum(axis=1)                          
    sales_val_amt =sales_val_amt[[index] + past_and_reporting_months +['total']] 

    return sales_val_amt



sales_val_table = region_sales_val( trade_transactions, month_column_name='month_name', index = 'region',value_column_name = 'amount_lcy')
sales_val_table = sales_val_table.rename(columns= {'total': 'ytd_cumulative'})

sales_val_table

region_sales_val_table = pd.merge(region_targets, sales_val_table,on='region', how ='left').fillna(0)
region_sales_val_table.drop(columns={'rm','target_trade_finance_income'}, inplace = True)
region_sales_val_table.rename(columns={'region':'region','target_trade_finance_value':'annual_targets'}, inplace = True)
region_sales_val_table

region_sales_val_table = calculation_formulas(region_sales_val_table)
region_sales_val_table = total_row(region_sales_val_table)

region_sales_val_table = pd.merge(region_sales_val_table, region_commission_table[['rank','region']], on = 'region', how = 'left')
region_sales_val_table = region_sales_val_table.sort_values(by = 'rank')
region_sales_val_table.drop(columns={'rank','region','ytd_score_uncapped'},inplace =True)
region_sales_val_table

cols_to_front = ['annual_targets','monthly_targets','month_actuals','month_score']
remaining_cols = [col for col in region_sales_val_table.columns if col not in cols_to_front]
column_order = cols_to_front + remaining_cols

region_sales_val_table= region_sales_val_table[column_order]
region_sales_val_table.head()


# In[71]:


"""## Role performance tables"""

def roles_comm(dataframe, index, month_column_name, value_column_name):

    comm_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
    
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    comm_amt = comm_amt.fillna(0).reset_index()


    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['total']]  

    return comm_amt

roles_commission_table = roles_comm(trade_transactions, month_column_name='month_name', index = 'rm_code',value_column_name = 'commission')

roles_commission_table.head()


# In[72]:


def roles_sales_vol(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
    
    vol_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'count', margins = True, margins_name='total')
    vol_amt = vol_amt.fillna(0).reset_index()

    for month in sales_month_order:
        if  month not in vol_amt.columns:
            vol_amt[month]=0
          
    vol_amt['total'] = vol_amt[past_and_reporting_months].sum(axis=1)                          
    vol_amt =vol_amt[[index] + past_and_reporting_months +['total']]  

    return vol_amt

roles_sales_vol_table = roles_sales_vol(trade_transactions, month_column_name='month_name', index = 'rm_code',value_column_name = 'commission')

roles_sales_vol_table.head()


# In[73]:


trade_transactions.columns


# In[56]:


def roles_sales_val(dataframe, index, month_column_name, value_column_name):
    sales_month_order = [f'{month}-{year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']] 
    current_month = dt.strptime(f'{report_month}-{year}','%b-%Y')
    past_and_reporting_months = [month for month in sales_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])
    
    val_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='total')
    val_amt = val_amt.fillna(0).reset_index()

    for month in sales_month_order:
        if  month not in val_amt.columns:
            val_amt[month]=0
          
    val_amt['total'] = val_amt[past_and_reporting_months].sum(axis=1)                          
    val_amt =val_amt[[index] + past_and_reporting_months +['total']] 

    return val_amt

roles_sales_val_table = roles_sales_val(trade_transactions, month_column_name='month_name', index = 'rm_code',value_column_name = 'amount_lcy')

roles_sales_val_table.head()


# In[57]:


filtered_overall_sales_person_mapping


# In[58]:


roles = ['COMMERCIAL RM','SME RM','SME ARM','SME BBC']

modified_tables=[]

for role in roles:
    roles_table = filtered_overall_sales_person_mapping[filtered_overall_sales_person_mapping['staff_role']== role]

    merged_roles_table = pd.merge(roles_table,roles_commission_table, left_on='sales_code', right_on='rm_code', how='left')

    merged_roles_table=merged_roles_table.fillna(0)
    merged_roles_table= merged_roles_table.drop(columns=['rm_code','brn_code','target_trade_finance_value','annual_target_trade_finance_value'])
    merged_roles_table= merged_roles_table.rename(columns={'total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_trade_finance_income':'annual_targets'},inplace = False)

    month_order = [f'{month}-{year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    present_columns = [col for col in month_order if col in merged_roles_table.columns]

    #calculations

    merged_roles_table = roles_calculation_formulas(merged_roles_table)
    merged_roles_table= roles_total_row(merged_roles_table)
    merged_roles_table= rank_performance(merged_roles_table,'ytd_score_uncapped')

    merged_roles_table['zone']= merged_roles_table['zone'].fillna('total')


    # replace branch with ''
    merged_roles_table['branch']= merged_roles_table['branch'].str.replace(' BRANCH','')


    column_order = ['rank','rm_name','rm_code','branch','zone','annual_targets','month_actuals']+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

    merged_roles_table=merged_roles_table[column_order].reset_index(drop=True)


    modified_tables.append(merged_roles_table)

modified_tables


# In[59]:


merged_roles_table


# In[60]:


# roles_sales_vol.columns

sales_vol_tables=[]

for role in roles:
    roles_table = filtered_overall_sales_person_mapping[filtered_overall_sales_person_mapping['staff_role']== role]
    roles_sales_vol = pd.merge(roles_table,roles_sales_vol_table, left_on ='sales_code', right_on='rm_code', how= 'left')
    roles_sales_vol= roles_sales_vol.drop(columns={'staff_name','staff_branch','brn_code','staff_role','staff_zone','annual_target_trade_finance_value',
                                                   'rm_code','target_trade_finance_value','annual_target_trade_finance_income','target_trade_finance_income'})
    roles_sales_vol=roles_sales_vol.fillna(0)

    # roles_sales_vol=pd.merge(roles_sales_vol,merged_roles_table[['rank','rm_code']], left_on='sales_code', right_on='rm_code', how='left')
    # roles_sales_vol= roles_sales_vol.sort_values(by='rank')
    # roles_sales_vol= roles_sales_vol.drop(columns={'sales_code','rank','rm_code'})
    roles_sales_vol= roles_sales_vol.rename(columns={'total':'ytd_cumulative'})

    total_rows=[]
    total_n={}
    total_n.update(roles_sales_vol.sum())
    total_rows.append(total_n)
    total_row_df = pd.DataFrame(total_rows, index=[0])
    roles_sales_vol = pd.concat([roles_sales_vol,total_row_df], ignore_index= True)

    sales_vol_tables.append(roles_sales_vol)



merged_sales_vol_tables =[]

for df1,df2 in zip(modified_tables,sales_vol_tables):
    combined_df = pd.merge(df2,df1[['rank','rm_code']], left_on='sales_code', right_on='rm_code', how='left')
    combined_df = combined_df.sort_values(by ='rank')
    combined_df= combined_df.drop(columns={'sales_code','rank','rm_code'})
    # combined_df= combined_df.rename(columns={'total':'ytd_cumulative'})

    merged_sales_vol_tables.append(combined_df)

# merged_sales_vol_tables

sales_val_tables=[]

# roles_sales_val.columns

for role in roles:
    roles_table = filtered_overall_sales_person_mapping[filtered_overall_sales_person_mapping['staff_role']== role]
    roles_sales_val = pd.merge(roles_table,roles_sales_val_table, left_on ='sales_code', right_on='rm_code', how= 'left')
    roles_sales_val= roles_sales_val.drop(columns={'staff_name','staff_branch','brn_code','staff_role','staff_zone','rm_code','annual_target_trade_finance_income'})
    roles_sales_val= roles_sales_val.fillna(0)


    # roles_sales_val=pd.merge(roles_sales_val,merged_roles_table[['rank','rm_code']], left_on='sales_code', right_on='rm_code', how='left')
    # roles_sales_val= roles_sales_val.sort_values(by='rank')
    roles_sales_val= roles_sales_val.rename(columns={'total':'ytd_cumulative','target_trade_finance_value':'monthly_targets','annual_target_trade_finance_value':'annual_targets'})

    # # roles_sales_val['annual_targets'] = merged_roles_table['annual_targets']  * 100

    roles_sales_val = calculation_formulas(roles_sales_val)
    roles_sales_val = total_row(roles_sales_val)
    # roles_sales_val= roles_sales_val.drop(columns={'sales_code','rank','rm_code'})
    roles_sales_val = roles_sales_val.reset_index(drop=True)
    roles_sales_val = roles_sales_val.drop(columns={'ytd_score_uncapped'})

    cols_to_front = ['annual_targets','monthly_targets','month_actuals','month_score']
    remaining_cols = [col for col in roles_sales_val.columns if col not in cols_to_front]
    column_order = cols_to_front + remaining_cols

    roles_sales_val= roles_sales_val[column_order]

    sales_val_tables.append(roles_sales_val)

# roles_sales_val

merged_sales_val_tables =[]

for df1,df2 in zip(modified_tables,sales_val_tables):
    combined_df = pd.merge(df2,df1[['rank','rm_code']], left_on='sales_code', right_on='rm_code', how='left')
    combined_df = combined_df.sort_values(by ='rank')
    combined_df= combined_df.drop(columns={'sales_code','rank','rm_code'})

    merged_sales_val_tables.append(combined_df)

merged_sales_val_tables


# In[61]:


"""## Analysis data"""

#for product chart
product_pt= trade_transactions.groupby('product_type', as_index=False).agg({'commission': 'sum'}).sort_values(by='commission', ascending=False)
product_pt

#for branch chart
branch_pt= trade_transactions.groupby('branch', as_index=False).agg({'amount_lcy': 'sum'}).sort_values(by='amount_lcy', ascending=False)
branch_pt

columns_to_keep={'rm_name':True,'ytd_score':True}
filtered_dfs = [df[df['rank'] == 1][list(columns_to_keep.keys())] for df in modified_tables]
top_rm_scores = pd.concat(filtered_dfs, ignore_index=True)
top_rm_scores

branch_commission_table.columns

columns_to_keep={'branch':True,'ytd_target':True,'ytd_cumulative':True,'ytd_score':True}
filtered_dfs = [branch_commission_table[branch_commission_table['rank'] == 1][list(columns_to_keep.keys())]]
top_branch = pd.concat(filtered_dfs, ignore_index=True)
top_branch

columns_to_keep={'rm_name':True,'ytd_score':True}
filtered_dfs = [df[df['rank'] == 1][list(columns_to_keep.keys())] for df in modified_tables]
top_rm_scores = pd.concat(filtered_dfs, ignore_index=True)
top_rm_scores

# get average scores per role from sheet
columns_to_keep={'ytd_score':True}
roles_df = [df[df['zone'] == 'total'][list(columns_to_keep.keys())]for df in modified_tables]
role_performance = pd.concat(roles_df, ignore_index=True)
role_performance.index= roles
role_performance

zone_commission_table.head()

columns_to_keep=['region','month_score']
region =region_commission_table[columns_to_keep]
region_scores =region.iloc[:-1]
region_scores

segment_columns_to_keep = ['month','BB_val','COMMERCIAL_val']
chart_segment_table = ordered_segment_table[segment_columns_to_keep]
chart_segment_table

chart_segment = chart_segment_table.iloc[:-1]
chart_segment = chart_segment.reset_index(drop=True)
chart_segment


# In[62]:


"""## Write sheets"""

file_name = f'Trade finance report - {formatted_date}.xlsx'

weekly_tradefinance_report_writer = pd.ExcelWriter(file_name, engine = 'xlsxwriter')
workbook = weekly_tradefinance_report_writer.book

dashboard_sheet_name = 'Dashboard'
branches_sheet_name = 'Branch_Performance'
team_sheet_name = 'Team_Performance'
segment_performance_sheet_name ='Segment_Performance'
segment_sheet_name = 'Segment_view'
product_sheet_name ='Product_view'
trade_data_sheet_name = 'Trade_finance_data'
analysis_sheet_name ='Analysis'

# add format types
# note: numbers should be aligned to the right & texts to the left

sheet_tab_colour = '#2AAFB8' #blue colour
font_size_format = workbook.add_format({'font_size':12})
header_format= workbook.add_format({'bold': True,'font_size':18,'align': 'center','font_color':'#FFFFFF','bg_color':'#1B4872'})
column_name_format= workbook.add_format({'text_wrap':True,'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#C69500','bg_color':'#1B4872'})  #C69500 is yellow, #1B4872 is blue
number_format = workbook.add_format({'num_format':'_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-', 'align': 'right','valign': 'vcenter' }) #align number to the right & center it
percent_format = workbook.add_format({'bold':True,'num_format':'0%' ,'align': 'right','valign': 'vcenter','bold':True})
million_format = workbook.add_format({'bold':True,'num_format':'#,##0.00,,"M"','align': 'right','valign': 'vcenter'})
bold_format = workbook.add_format({'bold': True})
text_format = workbook.add_format({'align': 'left','valign': 'vcenter'})
background_format = workbook.add_format({'bold': True,'bg_color':'#1B4872', 'font_color': '#000000'})
grey_format = workbook.add_format({'bold':True,'bg_color':'#F2F2F2'})
border_format = workbook.add_format({'border': 1})
wrap_text_format = workbook.add_format({'text_wrap': True})
blue_format = workbook.add_format({'text_wrap':True,'bold': True,'font_size':20,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#1B4872'})
total_format = workbook.add_format({'bold':True,'font_color':'#FFFFFF','bg_color':'#1B4872'})
fill_format = workbook.add_format({'bg_color':'#D9D9D9','align': 'right','num_format':'_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-'})
column_highlight_format = workbook.add_format({'bg_color':'#D9D9D9'})
date_format= workbook.add_format({'num_format':'dd-mmm-yyyy'})

# formatting for percentage performance

red_format = workbook.add_format({'bold': True,'bg_color':'#C0504D', 'font_color': '#000000','num_format':'0%'})
amber_format = workbook.add_format({'bold': True,'bg_color':'#C69500', 'font_color': '#000000','num_format':'0%'})
green_format = workbook.add_format({'bold': True,'bg_color':'#70AD47', 'font_color': '#000000','num_format':'0%'})
ytd_grey_format = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'font_color': '#000000', 'num_format': '0%'})

dashboard_worksheet = workbook.add_worksheet(dashboard_sheet_name)


# In[63]:


"""### Analysis sheet"""

# analysis_worksheet = workbook.add_worksheet(analysis_sheet_name)

product_pt.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 0, index=False, header= True)
branch_pt.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 4, index=False, header= True)
top_branch.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 7, index=False, header= True)
top_rm_scores.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 12, index=False, header= True)
role_performance.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 15, index=True, header= True)
region_scores.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 18, index=False, header= True)
chart_segment.to_excel(weekly_tradefinance_report_writer, sheet_name=analysis_sheet_name, startrow= 2, startcol= 20, index=False, header= True)

analysis_worksheet = weekly_tradefinance_report_writer.sheets[analysis_sheet_name]

analysis_worksheet.conditional_format(2,0,2,1,{'type':'no_errors','format':column_name_format})
analysis_worksheet.conditional_format(2, 4,2,5,{'type':'no_errors','format':column_name_format})
analysis_worksheet.conditional_format(2, 7,2,10,{'type':'no_errors','format':column_name_format})
analysis_worksheet.conditional_format(2, 12,2,13,{'type':'no_errors','format':column_name_format})
analysis_worksheet.conditional_format(2, 15,2,16,{'type':'no_errors','format':column_name_format})
analysis_worksheet.conditional_format(2, 18,2,19,{'type':'no_errors','format':column_name_format})
analysis_worksheet.conditional_format(2, 20,2,22,{'type':'no_errors','format':column_name_format})

analysis_worksheet.set_column(1,1,20.00,million_format)
analysis_worksheet.set_column(5,5,20.00,million_format)
analysis_worksheet.set_column(10,11,20.00,number_format)
analysis_worksheet.set_column(8,9,20.00,number_format)
analysis_worksheet.set_column(10,10,20.00,percent_format)
analysis_worksheet.set_column(13,13,20.00,percent_format)
analysis_worksheet.set_column(16,16,20.00,percent_format)
analysis_worksheet.set_column(18,18,20.00,percent_format)

# reporting_date = get_reporting_date()

analysis_worksheet.write('A1', 'Reporting date')
analysis_worksheet.write('B1', formatted_date)


analysis_worksheet.hide()


# In[64]:


"""### Dashboard

#### chart formats
"""

segment_chart = workbook.add_chart({"type":"column"})
product_chart = workbook.add_chart({"type":"column"})
branch_chart = workbook.add_chart({"type":"column"})
role_chart = workbook.add_chart({"type":"column"})
region_chart = workbook.add_chart({"type":"pie"})


bar_size = {'x_scale':1.2,'y_scale':1.1}
pie_size = {'x_scale':0.6,'y_scale':1.1}
legend = {'position':'bottom','font':{'bold': True,'size':8},'fill':{'color':'white'}}
title ={ 'size': 12,'font':'cambria','underline': True}

chart_area = {
    'border':{'color':'#1B4872'},
    'fill': {'color': '#D9D9D9'}
}

plot_area = {
    'fill':{'color':'#D9D9D9'},
                'positions':[90,100]

}

background_box = {'fill':{'color': '#1B4872'},'x_scale': 1,'y_scale':0.33,'border':{'none': True}}
text_box = {'fill':{'none': True},'font':{'color':'white','bold':True,'size':18,'align':'center'},'x_scale': 1,'y_scale':0.25,'border':{'none': True}}
vtext_box = {'fill':{'none': True},'font':{'color':'#1B4872','bold':True,'size':18,'align':'center'},'x_scale': 1,'y_scale':0.25,'border':{'none': True}}

#Top branch

branch_bg =  {'fill':{'color': '#D9D9D9'},'x_scale': 1.5,'y_scale':2.67, 'border':{'color':'#1B4872'}}
names = {
    'x_scale': 1.5,'y_scale':0.32,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

branch_header = {
    'x_scale': 1.5,'y_scale':0.32,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':24, 'bold':True}
}

branch_top = {
    'textlink': '=Analysis!H4',
    'x_scale': 1.5,'y_scale':0.3,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

branch_target = {
    'textlink': '=Analysis!I4',
    'x_scale': 1.5,'y_scale':0.3,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

branch_actual = {
    'textlink': '=Analysis!J4',
    'x_scale': 1.5,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

branch_score = {
    'textlink': '=Analysis!K4',
    'x_scale': 1.5,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

#Roles

roles_bg =  {'fill':{'color': '#1B4872'},'x_scale': 1,'y_scale':0.25,'border':{'none': True}}
role_title = {
    'x_scale': 1.2,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'none':True},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True,'underline':True}
}


commercial_rm = {
    'textlink': '=Analysis!M4',
    'x_scale': 1,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'color':'#1B4872'},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

commercial_score = {
    'textlink': '=Analysis!N4',
    'x_scale': 1,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'color':'#1B4872'},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

bb_rm = {
    'textlink': '=Analysis!M5',
    'x_scale': 1,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'color':'#1B4872'},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

bb_score = {
    'textlink': '=Analysis!N5',
    'x_scale': 1,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'color':'#1B4872'},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

bbc_rm = {
    'textlink': '=Analysis!M6',
    'x_scale': 1,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'color':'#1B4872'},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

bbc_score = {
    'textlink': '=Analysis!N6',
    'x_scale': 1,'y_scale':0.25,
    'align': {'vertical': 'middle','horizontal': 'center','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'border':{'color':'#1B4872'},
    'font': {'color': '#1B4872', 'name':'calibri', 'size':18, 'bold':True}
}

"""#### charts"""

segment_chart.add_series({
    'name':'Analysis!$V$3',
    'categories':'=Analysis!$U$4:$U15',
    'values':'=Analysis!$V$4:$V15',
    'fill':{'color':'#BFBFBF'},
    'gap': 80,
    'line':{'color':'#D9D9D9'},
    })


segment_chart.add_series({
    'name':'Analysis!$W$3',
    'categories':'=Analysis!$U$4:$U15',
    'values':'=Analysis!$W$4:$W15',
    'fill':{'color':'#1B4872'},
    'gap': 80,
    'line':{'color':'#D9D9D9'},
    })

segment_chart.set_size(bar_size)
segment_chart.set_title({'name':'Segment inflow trend', 'name_font' :title})
segment_chart.set_chartarea(chart_area)
segment_chart.set_plotarea(plot_area)

segment_chart.set_x_axis({'name_font':{'size': 11, 'bold':True}})
segment_chart.set_y_axis({'display_units': 'millions'})
segment_chart.set_legend(legend)
segment_chart.set_style(10)

#Product chart

product_chart.add_series({

    'name':'=Analysis!$A$3',
    'categories':'=Analysis!$A$4:$A$13',  #top 10 products
    'values':'=Analysis!$B$4:$B$13',
    'fill':{'color':'#1B4872'},
    'gap': 80,
    'line':{'color':'#D9D9D9'},
    'data_labels':{'value':True,'fill':{'color':'white'},'font':{'bold':True}},
    })


product_chart.set_size(bar_size)
product_chart.set_title({'name':'Product type',
                         'name_font' :title
                        })

product_chart.set_x_axis({'num_font':{'size': 6, 'bold':True}})
product_chart.set_y_axis({'visible': False})
product_chart.set_legend({'none': True})
product_chart.set_style(10)
product_chart.set_chartarea(chart_area)
product_chart.set_plotarea(plot_area)

#Branch chart


branch_chart.add_series({

    'name':'=Analysis!$E$3',
    'categories':'=Analysis!$E$4:$E$13',
    'values':'=Analysis!$F$4:$F$13',
    'fill':{'color':'#1B4872'},
    'gap': 80,
    'line':{'color':'#D9D9D9'},
    'data_labels':{'value':True, 'fill':{'color':'white'},'font':{'bold':True}}
    })


branch_chart.set_size(bar_size)
branch_chart.set_title({'name':'Top 10 branches(value)',  'name_font' :title})

branch_chart.set_x_axis({'num_font':{'size':7.2, 'bold':False}})
branch_chart.set_y_axis({'visible': False})
branch_chart.set_legend({'none':True})
branch_chart.set_style(10)
branch_chart.set_chartarea(chart_area)
branch_chart.set_plotarea(plot_area)


#Roles chart

role_chart.add_series({

    'name':'=Analysis!$P$3',
    'categories':'=Analysis!$P$4:$P$6',
    'values':'=Analysis!$Q$4:$Q$6',
    'fill':{'color':'#1B4872'},
    'gap': 80,
    'line':{'color':'#D9D9D9'},
    'data_labels':{'value':True, 'fill':{'color':'white'},'font':{'bold':True}}
    })


role_chart.set_size(bar_size)
role_chart.set_title({'name':'Roles income performance',  'name_font' :title})

role_chart.set_x_axis({'font':{'size': 11, 'bold':True}})
role_chart.set_y_axis({'visible': False})
role_chart.set_legend({'none':True})
role_chart.set_style(10)
role_chart.set_chartarea(chart_area)
role_chart.set_plotarea(plot_area)



#region pie chart

region_chart.add_series({
    'categories':'=Analysis!$S$4:$S$6',
    'values':'=Analysis!$T$4:$T$6',
    'points': [
        {'fill': {'color': '#1B4872'}},
        {'fill': {'color': '#1B4872'}},
        {'fill': {'color': '#2AAFB8'}}],
     'data_labels': {'category': False, 'value':True, 'num_format':'0%',
                    'position':'center', 'border':{'none':True},
                    'font':{'name':'calibri', 'size': 11, 'bold':True, 'color':'white'}
                    }

    })

# region_chart.add_series({
#     'categories':'=Analysis!$S$4:$S$6',
#     'values':'=Analysis!$T$4:$T$6',
#     'points': [
#         {'fill': {'color': '#1B4872'}},
#         {'fill': {'color': '#1B4872'}},
#         {'fill': {'color': '#2AAFB8'}}],
#      'data_labels': {'category': False, 'value':True, 'num_format':'0%',
#                     'position':'center', 'fill':{'color':'white'},'border':{'none':True},
#                     'font':{'name':'calibri', 'size': 11, 'bold':True, 'color':'black'}
#                     }

#     })

region_chart.set_title({'name':'Region Performance', 'name_font' :title })
region_chart.set_size(pie_size)
region_chart.set_legend(legend)
region_chart.set_chartarea(chart_area)
region_chart.set_plotarea(plot_area)


# In[65]:


"""#### dashboard"""

# dashboard_worksheet = weekly_tradefinance_report_writer.sheets[dashboard_sheet_name]

dashboard_worksheet.set_zoom(70)
dashboard_worksheet.hide_gridlines(2)
dashboard_worksheet.set_tab_color(sheet_tab_colour)


#insert the textboxes

dashboard_worksheet.insert_textbox('D1','',{'fill':{'color': '#1B4872'},'x_scale': 6.5,'y_scale':0.54,'border':{'none': True}})
dashboard_worksheet.insert_textbox('G1','TRADE FINANCE DASHBOARD',{'fill':{'none': True},'font':{'color':'white','bold':True,'size':40,'align':'center'},'x_scale': 4,'y_scale':0.54,'border':{'none': True}})

# reporting_date = get_reporting_date()
date_value = formatted_date

dashboard_worksheet.insert_textbox('A1','',{'fill':{'color': '#1B4872'},'x_scale': 1,'y_scale':0.54,'border':{'none': True}})
dashboard_worksheet.insert_textbox('A1',date_value,{'fill':{'none': True},'font':{'color':'white','bold':True,'size':26,'align':'center'},'x_scale': 1.3,'y_scale':0.5,'border':{'none': True}})


#top per role textbox
dashboard_worksheet.insert_textbox('A4','',{'fill':{'color': '#1B4872'},'x_scale': 7.5,'y_scale':1.3,'border':{'none': True}}) #blank textbox for all the roles
dashboard_worksheet.insert_textbox('A6','Top per role:',{'fill':{'none': True},'font':{'color':'white','bold':True,'size':18,'align':'center'},'x_scale': 1,'y_scale':0.4,'border':{'none': True}})


#top branch performance
dashboard_worksheet.insert_textbox('S12','',branch_bg)
dashboard_worksheet.insert_textbox('S12','Top branch:',branch_header)
dashboard_worksheet.insert_textbox('S14','',branch_top)
dashboard_worksheet.insert_textbox('S16','Ytd target:',names)
dashboard_worksheet.insert_textbox('S18','',branch_target)
dashboard_worksheet.insert_textbox('S20','Ytd actual:',names)
dashboard_worksheet.insert_textbox('S22','',branch_actual)
dashboard_worksheet.insert_textbox('S24','Ytd score:',names)
dashboard_worksheet.insert_textbox('S26','',branch_score)


#top per role

dashboard_worksheet.insert_textbox('E6','COMMERCIAL RM:',role_title)
dashboard_worksheet.insert_textbox('E8','',commercial_rm)
dashboard_worksheet.insert_textbox('E10','',commercial_score)
dashboard_worksheet.insert_textbox('K6','BB RM:',role_title)
dashboard_worksheet.insert_textbox('K8','',bb_rm)
dashboard_worksheet.insert_textbox('K10','',bb_score)
dashboard_worksheet.insert_textbox('Q6','BB BBC:',role_title)
dashboard_worksheet.insert_textbox('Q8','',bbc_rm)
dashboard_worksheet.insert_textbox('Q10','',bbc_score)

#charts
dashboard_worksheet.insert_chart('A12',segment_chart)
dashboard_worksheet.insert_chart('S28',region_chart)
dashboard_worksheet.insert_chart('J12',product_chart)
dashboard_worksheet.insert_chart('J28',branch_chart)
dashboard_worksheet.insert_chart('A28',role_chart)

dashboard_worksheet.protect()

"""### Branch performance sheet"""

commission_tables= [zone_commission_table,region_commission_table,branch_commission_table]
volume_tables= [zone_sales_vol_table,region_sales_vol_table,branch_sales_vol_table]
value_tables= [zone_sales_val_table,region_sales_val_table,branch_sales_val_table]


start_row=1

rows = np.cumsum([df.shape[0]+3 for df in commission_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]


for i,(row, df) in enumerate(zip(fin_rows, commission_tables)):
    if i == 2:
        start_col = 0
    elif i == 1:
        start_col = 1
    else:
        start_col = 2

    end_row = df.shape[0] + row
    end_col = df.shape[1]  + start_col -1

    df.to_excel(weekly_tradefinance_report_writer, sheet_name = branches_sheet_name, index = False, startrow = row, startcol=start_col)
    branches_worksheet = weekly_tradefinance_report_writer.sheets[branches_sheet_name]

    if 'month_score' in df.columns and 'ytd_score' in df.columns :
        mtd_percent_col = df.columns.get_loc('month_score')
        ytd_percent_col = df.columns.get_loc('ytd_score')
        # ytd_uncapped_percent_col = df.columns.get_loc('ytd_score_uncapped')

        for pct_col in (mtd_percent_col, ytd_percent_col):
            branches_worksheet.conditional_format(row+1,pct_col +start_col,end_row,pct_col+start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
            branches_worksheet.conditional_format(row+1,pct_col+start_col,end_row,pct_col+start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
            branches_worksheet.conditional_format(row+1,pct_col+start_col,end_row,pct_col+start_col,{'type': 'cell','criteria':'between', 'minimum': 0.8,'maximum': 1.0,  'format': amber_format})


    header_name = 'zone' if i == 0 else 'region & rm' if i == 1 else 'branches'

    branches_worksheet.merge_range(row-1,start_col,row-1,3,header_name,header_format)
    branches_worksheet.merge_range(row-1,4,row-1,end_col,'commission_earned',header_format)
    

    branches_worksheet.set_column(start_col,end_col,16.00,number_format)
    
    # uncapped_score_column_range = f'{xlsxwriter.utility.xl_col_to_name(end_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    # branches_worksheet.set_column(end_col,end_col, None, None, {'hidden': True})
    
    branches_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branches_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_name_format})
    branches_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    branches_worksheet.conditional_format(row,start_col,end_row,3,{'type': 'no_errors', 'format': grey_format})

for i,(row, df) in enumerate(zip(fin_rows, commission_tables)):
    if i == 2:
        start_col = 0
    elif i == 1:
        start_col = 1
    else:
        start_col = 2


    group_end_col =  df.shape[1]+start_col - 4
    group_end_col = max(group_end_col,8)
    column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # Group and hide columns
    branches_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    branches_worksheet.conditional_format(fin_rows[i]+1,start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# volume tables
rows = np.cumsum([df.shape[0]+3 for df in volume_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

volume_start_col= [commission_tables[i].shape[1]   if i == 2 else commission_tables[i].shape[1] + 1 if i == 1 else commission_tables[i].shape[1] + 2
                   for i in range(len(volume_tables))]

for i,(df, col) in enumerate( zip(volume_tables, volume_start_col)):
    df.to_excel(weekly_tradefinance_report_writer, sheet_name = branches_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,volume_tables)):
    end_row = df.shape[0]+row
    end_col = volume_start_col[i]+ df.shape[1]-1

    branches_worksheet.set_column(6,end_col,16.00,number_format)

    branches_worksheet.merge_range(fin_rows[i]-1,volume_start_col[i],fin_rows[i]-1,end_col,'sales_volume',blue_format)
    branches_worksheet.conditional_format(fin_rows[i],volume_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    branches_worksheet.conditional_format(fin_rows[i]+1,volume_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    branches_worksheet.conditional_format(end_row,volume_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    branches_worksheet.conditional_format(fin_rows[i]+1 , volume_start_col[i], end_row , end_col,{'type': 'cell','criteria': '>','value': 0,'format': fill_format})


# value tables
rows = np.cumsum([df.shape[0]+3 for df in value_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

value_start_col= [commission_tables[i].shape[1] +volume_tables[i].shape[1]   if i == 2
                  else commission_tables[i].shape[1] +volume_tables[i].shape[1] + 1 if i == 1
                  else commission_tables[i].shape[1] +volume_tables[i].shape[1] + 2 for i in range(len(value_tables))]

for i,(df, col) in enumerate( zip(value_tables, value_start_col)):
    df.to_excel(weekly_tradefinance_report_writer, sheet_name = branches_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,value_tables)):
    end_row = df.shape[0]+row
    end_col = value_start_col[i]+ df.shape[1]-1

    branches_worksheet.set_column(value_start_col[i],end_col,16.00,number_format)
    branches_worksheet.merge_range(fin_rows[i]-1,value_start_col[i],fin_rows[i]-1,end_col,'sales_value',header_format)
    branches_worksheet.conditional_format(fin_rows[i],value_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    branches_worksheet.conditional_format(fin_rows[i]+1,value_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    branches_worksheet.conditional_format(end_row,value_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

    if 'month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_percent_col = df.columns.get_loc('month_score')
        ytd_percent_col = df.columns.get_loc('ytd_score')
        # ytd_uncapped_percent_col = df.columns.get_loc('ytd_score_uncapped')

        for pct_col in (mtd_percent_col, ytd_percent_col):
            branches_worksheet.conditional_format(row+1,pct_col +value_start_col[i],end_row,pct_col+value_start_col[i],{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
            branches_worksheet.conditional_format(row+1,pct_col+value_start_col[i],end_row,pct_col+value_start_col[i],{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
            branches_worksheet.conditional_format(row+1,pct_col+value_start_col[i],end_row,pct_col+value_start_col[i],{'type': 'cell','criteria':'between', 'minimum': 0.8,'maximum': 1.0,  'format': amber_format})


for i , (row, df) in enumerate(zip(fin_rows, value_tables)):
    start_col = value_start_col[i]+4
    end_col =  df.shape[1]+value_start_col[i] - 4
    column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    # Group and hide columns
    branches_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    branches_worksheet.conditional_format(fin_rows[i]+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': number_format})



branches_worksheet.set_tab_color(sheet_tab_colour)
branches_worksheet.freeze_panes(2,4)
branches_worksheet.set_zoom(80)

"""### Roles performance sheet"""

# modified_tables,sales_vol_tables,sales_val_tables]

start_row = 1
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in modified_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, modified_tables)):
    df.to_excel(weekly_tradefinance_report_writer, sheet_name = team_sheet_name, index = False, startrow = row, startcol=start_col)

    team_worksheet = weekly_tradefinance_report_writer.sheets[team_sheet_name]


for i , (row, df) in enumerate(zip(fin_rows, modified_tables)):
    end_row = df.shape[0] + row
    end_col = start_col + df.shape[1] -1

    team_worksheet.merge_range(row-1,5,row-1,end_col,'commissions_earned',header_format)
    team_worksheet.set_column(start_col,4,18.00)
    team_worksheet.set_column(5,end_col-1,15.00,number_format)

    team_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    team_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_name_format})
    team_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    team_worksheet.conditional_format(row,start_col,end_row,4,{'type': 'no_errors', 'format': grey_format})

    if 'ytd_score' in df.columns:
        ytd_perc_col = df.columns.get_loc('ytd_score')

        team_worksheet.conditional_format(row+1,ytd_perc_col,end_row,ytd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        team_worksheet.conditional_format(row+1,ytd_perc_col,end_row,ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        team_worksheet.conditional_format(row+1,ytd_perc_col,end_row,ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for (row, title) in zip(fin_rows,roles):
    team_worksheet.merge_range(row-1,0,row-1,4, title, header_format)

for i , (row, df) in enumerate(zip(fin_rows, modified_tables)):
    group_end_col =  df.shape[1]+start_col - 4
    column_range = f'H:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # Group and hide columns
    team_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    team_worksheet.conditional_format(fin_rows[i]+1,start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# volume tables
volume_start_col= [modified_tables[i].shape[1] for i in range(len(merged_sales_vol_tables))]

for i,(df, col) in enumerate( zip(merged_sales_vol_tables, volume_start_col)):
    df.to_excel(weekly_tradefinance_report_writer, sheet_name = team_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (merged_sales_vol_tables):
    end_row = df.shape[0]+ fin_rows[i]
    end_col =  volume_start_col[i] + df.shape[1] -1

    team_worksheet.set_column(volume_start_col[i],end_col,8.00,number_format)
    team_worksheet.merge_range(fin_rows[i]-1,volume_start_col[i],fin_rows[i]-1,end_col,'sales_volume',blue_format)
    team_worksheet.conditional_format(fin_rows[i],volume_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    team_worksheet.conditional_format(fin_rows[i],volume_start_col[i],end_row-1,end_col,{'type': 'cell','criteria': '>','value': 0,'format': fill_format})

    team_worksheet.conditional_format(fin_rows[i]+1,volume_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    team_worksheet.conditional_format(end_row,volume_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})


# value tables
value_start_col= [modified_tables[i].shape[1] + merged_sales_vol_tables[i].shape[1] for i in range(len(merged_sales_val_tables))]

rows = np.cumsum([df.shape[0]+3 for df in merged_sales_val_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,(df, col) in enumerate( zip(merged_sales_val_tables, value_start_col)):
    df.to_excel(weekly_tradefinance_report_writer, sheet_name = team_sheet_name, index = False, startrow = fin_rows[i], startcol=col)


for i,df in enumerate (merged_sales_val_tables):
    end_row = df.shape[0]+fin_rows[i]
    end_col = value_start_col[i]+ df.shape[1]-1

    team_worksheet.merge_range(fin_rows[i]-1,value_start_col[i],fin_rows[i]-1,end_col,'sales_value',header_format)
    team_worksheet.set_column(value_start_col[i],end_col,16.00,number_format)

    team_worksheet.conditional_format(fin_rows[i]+1,value_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    team_worksheet.conditional_format(fin_rows[i],value_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    team_worksheet.conditional_format(end_row,value_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    team_worksheet.conditional_format(fin_rows[i]+1,value_start_col[i],end_row-1,value_start_col[i]+1,{'type': 'no_errors', 'format': grey_format})


    if 'ytd_score' in df.columns and 'month_score' in df.columns:
        ytd_perc_col = df.columns.get_loc('ytd_score')
        mtd_perc_col = df.columns.get_loc('month_score')

        for pct_col in (ytd_perc_col, mtd_perc_col):
            team_worksheet.conditional_format(fin_rows[i]+1,pct_col+value_start_col[i],end_row,pct_col+value_start_col[i],{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
            team_worksheet.conditional_format(fin_rows[i]+1,pct_col+value_start_col[i],end_row,pct_col+value_start_col[i],{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
            team_worksheet.conditional_format(fin_rows[i]+1,pct_col+value_start_col[i],end_row,pct_col+value_start_col[i],{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})


for i , (row, df) in enumerate(zip(fin_rows, merged_sales_val_tables)):
    start_col = value_start_col[i] + 4
    end_col =  df.shape[1]+value_start_col[i] - 4
    column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    team_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    team_worksheet.conditional_format(fin_rows[i]+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': number_format})

# for col_idx, column in enumerate(df.columns):
#     column_width = max(df[column].astype(str).apply(len).max(), len(column))
#     team_worksheet.set_column(col_idx, col_idx, column_width)

team_worksheet.set_tab_color(sheet_tab_colour)
team_worksheet.freeze_panes(2,5)
team_worksheet.set_zoom(80)


# In[66]:


segment_value_table_with_targets


# In[67]:


# segment performance
segment_performance_tables= [segment_value_table_with_targets, segment_revenue_table_with_targets]

start_col = 0
start_row = 1
start_row=1

rows = np.cumsum([df.shape[0]+3 for df in segment_performance_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]


for i,(row, df) in enumerate(zip(fin_rows, segment_performance_tables)):

    end_row = df.shape[0] + row
    end_col = df.shape[1]  + start_col -1

    df.to_excel(weekly_tradefinance_report_writer, sheet_name = segment_performance_sheet_name, index = False, startrow = row, startcol=start_col)
    segment_performance_worksheet = weekly_tradefinance_report_writer.sheets[segment_performance_sheet_name]

    if 'month_score' in df.columns and 'ytd_score' in df.columns :
        mtd_percent_col = df.columns.get_loc('month_score')
        ytd_percent_col = df.columns.get_loc('ytd_score')

        for pct_col in (mtd_percent_col, ytd_percent_col):
            segment_performance_worksheet.conditional_format(row+1,pct_col +start_col,end_row,pct_col+start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
            segment_performance_worksheet.conditional_format(row+1,pct_col+start_col,end_row,pct_col+start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
            segment_performance_worksheet.conditional_format(row+1,pct_col+start_col,end_row,pct_col+start_col,{'type': 'cell','criteria':'between', 'minimum': 0.8,'maximum': 1.0,  'format': amber_format})


    header_name = 'sales_value' if i == 0 else 'commission_earned' 

    segment_performance_worksheet.merge_range(row-1,4,row-1,end_col,header_name,header_format)
    

    segment_performance_worksheet.set_column(start_col,end_col,16.00,number_format)
    
    # uncapped_score_column_range = f'{xlsxwriter.utility.xl_col_to_name(end_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    # segment_performance_worksheet.set_column(end_col,end_col, None, None, {'hidden': True})
    
    segment_performance_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    segment_performance_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_name_format})
    segment_performance_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    segment_performance_worksheet.conditional_format(row,start_col,end_row,3,{'type': 'no_errors', 'format': grey_format})

for i,(row, df) in enumerate(zip(fin_rows, segment_performance_tables)):

    group_end_col =  df.shape[1]+start_col - 3
    group_end_col = max(group_end_col,8)
    column_range = f'G:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # Group and hide columns
    segment_performance_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    segment_performance_worksheet.conditional_format(fin_rows[i]+1,start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


segment_performance_worksheet.set_tab_color(sheet_tab_colour)
segment_performance_worksheet.freeze_panes(2,4)
segment_performance_worksheet.set_zoom(80)


# In[ ]:





# In[68]:


"""<!-- ### Product view -->"""

"""### Product view sheet"""

product_tables = [product_value_table,product_vol_table,product_income_table]

start_col = 0
start_row = 1


rows = np.cumsum([df.shape[0] + 3 for df in product_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,(row, df) in enumerate(zip(fin_rows, product_tables)):
    end_row = df.shape[0] + row
    end_col = df.shape[1]  + start_col -1

    df.to_excel(weekly_tradefinance_report_writer, sheet_name=product_sheet_name, startrow= row, startcol= start_col, index=False)
    product_worksheet = weekly_tradefinance_report_writer.sheets[product_sheet_name]

    product_worksheet.set_column(0,0,27.00,bold_format)
    product_worksheet.set_column(1,end_col,16.00)

    header_name = 'sales_value' if i==0 else 'sales_volume' if i ==1 else 'commision_earned'
    product_worksheet.write(row-1,start_col,header_name, column_name_format)


    product_worksheet.conditional_format(row,start_col,row,end_col, {'type': 'no_errors','format':column_name_format})
    product_worksheet.conditional_format(row+1,0,end_row,end_col, {'type': 'no_errors','format':border_format})
    product_worksheet.conditional_format(row+1,0,end_row,end_col, {'type': 'no_errors','format': number_format})
    product_worksheet.conditional_format(end_row,start_col,end_row,end_col, {'type': 'no_errors','format':total_format})

    blue_format =workbook.add_format({'bold':True,'bg_color':'#91CBF5'})
    product_worksheet.conditional_format(row+1,end_col,end_row-1,end_col, {'type': 'no_errors','format':blue_format})

product_worksheet.set_zoom(75)
product_worksheet.set_tab_color(sheet_tab_colour)
product_worksheet.freeze_panes(2,1)



"""### Segment sheet"""

#segment tables

df = ordered_segment_table

start_col = 0
start_row = 1
end_row = start_row + ordered_segment_table.shape[0]
end_col = ordered_segment_table.shape[1]

df.to_excel(weekly_tradefinance_report_writer, sheet_name=segment_sheet_name, startrow= start_row, startcol= start_col, index=False)
segment_worksheet = weekly_tradefinance_report_writer.sheets[segment_sheet_name]

segment_worksheet.set_column(0,end_col,16.00)

air_sup_blue= workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'middle','font_color':'#000000','bg_color':'#72A0C1'})

segment_worksheet.conditional_format(start_row+1,3,end_row,3, {'type': 'no_errors','format':air_sup_blue})
segment_worksheet.conditional_format(start_row+1,6,end_row,6, {'type': 'no_errors','format':air_sup_blue})
segment_worksheet.conditional_format(start_row+1,9,end_row,9, {'type': 'no_errors','format':air_sup_blue})

segment_worksheet.conditional_format(start_row,4,end_row,4,{'type': 'no_errors','format':bold_format})
segment_worksheet.conditional_format(start_row,8,end_row,8,{'type': 'no_errors','format':bold_format})
segment_worksheet.conditional_format(start_row,12,end_row,12,{'type': 'no_errors','format':bold_format})

segment_worksheet.conditional_format(start_row,0,start_row,end_col-1, {'type': 'no_errors','format':column_name_format})
segment_worksheet.conditional_format(end_row,0,end_row,end_col-1, {'type': 'no_errors','format':total_format})
segment_worksheet.conditional_format(start_row,0,end_row,end_col-1, {'type': 'no_errors','format':border_format})
segment_worksheet.conditional_format(start_row+1,1,end_row,end_col-1, {'type': 'no_errors','format': number_format})
segment_worksheet.conditional_format(start_row+1,0,end_row-1,0, {'type': 'no_errors','format':bold_format})

segment_worksheet.set_zoom(90)
segment_worksheet.set_tab_color(sheet_tab_colour)



"""### Transactions sheet"""

trade_transactions.to_excel(weekly_tradefinance_report_writer, sheet_name=trade_data_sheet_name, startrow= 0, startcol= 0, index=False)
print(trade_transactions.dtypes.to_string())

trade_transactions_worksheet = weekly_tradefinance_report_writer.sheets[trade_data_sheet_name]

trade_transactions_worksheet.set_zoom(70)
trade_transactions_worksheet.set_tab_color(sheet_tab_colour)

max_lengths = {col: len(col) for col in trade_transactions.columns}

start_row = 0
end_row =  start_row + trade_transactions.shape[0]
end_col = trade_transactions.shape[1] + start_col -1
top_header_format= workbook.add_format({'text_wrap':True,'bold': True,'font_size':12,'align': 'center','valign':'bottom',
                                        'font_color':'#C69500','bg_color':'#1B4872'})

trade_transactions_worksheet.conditional_format(start_row+1,10,end_row,11, {'type': 'no_errors','format':column_highlight_format})
trade_transactions_worksheet.conditional_format(start_row+1,22,end_row,end_col, {'type': 'no_errors','format':column_highlight_format})
# trade_transactions_worksheet.conditional_format(start_row+1,19,end_row,20, {'type': 'no_errors','format':column_highlight_format})

for col_num, col_name in enumerate(trade_transactions.columns):
    trade_transactions_worksheet.write(0, col_num, col_name, top_header_format)

for row_num, (index, row) in enumerate(trade_transactions.iterrows(), start = 1):
    for col_num, cell_value in enumerate(row):
        if pd.isna(cell_value):
            cell_value = ''
        trade_transactions_worksheet.write(row_num, col_num, cell_value)
        max_lengths[trade_transactions.columns[col_num]] = max(max_lengths[trade_transactions.columns[col_num]], len(str(cell_value)))

for col_num, col_name in enumerate(trade_transactions.columns):
    trade_transactions_worksheet.set_column(col_num, col_num, max_lengths[col_name] * 1.2)

start_row = 0
start_col = 0
max_col = trade_transactions.shape[1]-1
max_row = trade_transactions.shape[0]

trade_transactions_worksheet.set_column(12,13,None,date_format)

trade_transactions_worksheet.set_column(9,9,16.00,number_format)
trade_transactions_worksheet.set_column(11,11,16.00,number_format)
trade_transactions_worksheet.set_column(15,15,16.00,number_format)
trade_transactions_worksheet.set_column(17,17,16.00,number_format)
# trade_transactions_worksheet.set_column(18,18,16.00,percent_format)
trade_transactions_worksheet.set_column(20,20,16.00,percent_format)

trade_transactions_worksheet.conditional_format(0,0,max_row,max_col,{'type': 'no_errors','format':border_format})

trade_transactions_worksheet.freeze_panes(1,3)


# In[69]:


workbook.close()


# In[70]:


# Commented out IPython magic to ensure Python compatibility.
"""## Email styling"""

def color_ytd_percentage(val):
    if not isinstance(val, (int, float)):
        return ''
    if val < 0.80:
        return 'background-color: #C0504D; color: black'
    elif val < 1.00:
        return 'background-color: #C69500; color: black'
    return 'background-color: #70AD47; color: black'

def style_branch_commission(dataframe):
    format_dict = { col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ['rank','ytd_score'] }
    format_dict['ytd_score'] = '{:.0%}'
    format_dict['rank'] = '{:.0f}'
    def style_last_row(s):
        is_last_row = s.name == (len(dataframe) - 1)
        styles = [f'background-color: #1B4872; color: white; font-weight: bold' if is_last_row else '' for _ in s]
        return styles
    return dataframe.set_index(['rank','branch','zone','region']).style \
          .format(format_dict) \
          .map(color_ytd_percentage, subset=['ytd_score']) \
          .apply(style_last_row, axis=1) \
          .set_properties(**{
              'border': '1px solid black',
              'border-collapse': 'collapse',
              'border-spacing': '0'
          }) \
          .set_table_styles([{
              'selector': 'th',
              'props': [
                  ('border', '2px solid black'),
                  ('color', 'white'),
                  ('background-color', '#1B4872')
              ]
          }, {
              'selector': '',
              'props': [
                    ('border', '2px solid black'),
                    ('padding', '0 2px'),
                    ('font-size', '12px')
              ]
          }, {
              'selector': 'tbody > tr:last-child',
              'props': [
                  ('border', '1px solid black'),
                  ('color', 'white'),
                  ('background-color', '#1B4872'),
                  ('font-weight','bold')
              ]
          }])

style_branch_commission(branch_commission_table)

def style_branch_sales_val(dataframe):
    format_dict = { col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ['ytd_score'] }
    format_dict['ytd_score'] = '{:.0%}'
    # format_dict['rank'] = '{:.0f}'
    def style_last_row(s):
        is_last_row = s.name == (len(dataframe) - 1)
        styles = [f'background-color: #1B4872; color: white; font-weight: bold' if is_last_row else '' for _ in s]
        return styles
    return dataframe.set_index(['branch']).style \
          .format(format_dict) \
          .map(color_ytd_percentage, subset=['ytd_score']) \
          .apply(style_last_row, axis=1) \
          .set_properties(**{
              'border': '1px solid black',
              'border-collapse': 'collapse',
              'border-spacing': '0'
          }) \
          .set_table_styles([{
              'selector': 'th',
              'props': [
                  ('border', '2px solid black'),
                  ('color', 'white'),
                  ('background-color', '#1B4872')
              ]
          }, {
              'selector': '',
              'props': [
                    ('border', '2px solid black'),
                    ('padding', '0 2px'),
                    ('font-size', '12px')
              ]
          }, {
              'selector': 'tbody > tr:last-child',
              'props': [
                  ('border', '1px solid black'),
                  ('color', 'white'),
                  ('background-color', '#1B4872'),
                  ('font-weight','bold')
              ]
          }])

style_branch_sales_val(branch_sales_val)

def style_segment_table(dataframe):

    dataframe = dataframe.reset_index(drop=True)

    format_dict = { col: lambda x: f"{x:,.0f}" for col in dataframe.columns }
    # format_dict['ytd_score'] = '{:.0%}'
    # format_dict['rank'] = '{:.0f}'
    def style_last_row(s):
        is_last_row = s.name == (len(dataframe) - 1)
        styles = [f'background-color: #1B4872; color: white; font-weight: bold' if is_last_row else '' for _ in s]
        return styles
    return dataframe.set_index('month').style \
          .format(format_dict) \
          .apply(style_last_row, axis=1) \
          .set_properties(**{
              'border': '1px solid black',
              'border-collapse': 'collapse',
              'border-spacing': '0'
          }) \
          .set_table_styles([{
              'selector': 'th',
              'props': [
                  ('border', '2px solid black'),
                  ('color', 'white'),
                  ('background-color', '#1B4872')
              ]
          }, {
              'selector': '',
              'props': [
                    ('border', '2px solid black'),
                    ('padding', '0 2px'),
                    ('font-size', '12px')
              ]
          }, {
              'selector': 'tbody > tr:last-child',
              'props': [
                  ('border', '1px solid black'),
                  ('color', 'white'),
                  ('background-color', '#1B4872'),
                  ('font-weight','bold')
              ]
          }])

style_segment_table(ordered_segment_table)

styled_branch_commission=style_branch_commission(branch_commission_table)
styled_branch_sales_val= style_branch_sales_val(branch_sales_val)
styled_ordered_segment_table= style_segment_table(ordered_segment_table)

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from1 = 'Reports.Analytics@hfgroup.co.ke'
list_of_recipients = [
    'branch.managers@hfgroup.co.ke',
    'branch.operations@hfgroup.co.ke',
    'RetailManagementCommittee@hfgroup.co.ke',
    'Robert.Kibaara@hfgroup.co.ke',
    'Business.Banking@hfgroup.co.ke',
    'TransactionalBanking@hfgroup.co.ke',
    'SalesAdministration@hfgroup.co.ke',
    'SME_DSRS@hfgroup.co.ke',
    'Ultimate.banking@hfgroup.co.ke',
    'CommercialBanking@hfgroup.co.ke'
]


cc_list_of_recipients = [
    'TradeFinance@hfgroup.co.ke',
    'Strategy&BusinessPerformance@hfgroup.co.ke'
]


address_book = [  # ,'Patrick.Njunge@hfgroup.co.ke','Fridah.Mcharo@hfgroup.co.ke',','stephen.waswa@hfgroup.co.ke','Nathan.Kamau@hfgroup.co.ke']
    'stacy.kendi@hfgroup.co.ke',
    'allan.aswani@hfgroup.co.ke',
    'Reports.Analytics@hfgroup.co.ke',
#     'Patrick.Njunge@hfgroup.co.ke',
#     'Fridah.Mcharo@hfgroup.co.ke',
#     'Nathan.Okero@hfgroup.co.ke',
#     'stephen.waswa@hfgroup.co.ke',
#     'Strategy&BusinessPerformance@hfgroup.co.ke',
#     'David.Igweta@hfgroup.co.ke',
#     'RetailManagementCommittee@hfgroup.co.ke',
#     'Charles.Munuve@hfgroup.co.ke',
#     'Christopher.Opiyo@hfgroup.co.ke',
#     'Imelda.Muganda@hfgroup.co.ke',
#     'SalesTeamLeader@hfgroup.co.ke',
#     'Dorothy.Jumba@hfgroup.co.ke',
#     'branch.managers@hfgroup.co.ke',
#     'Schemes.Admin@hfgroup.co.ke',
#     'Elizabeth.Nyakundi@hfgroup.co.ke',
#     'SCHEMETEAM@hfgroup.co.ke',
#     'Credit.Analyst@hfgroup.co.ke'
    ]

##to = "Strategy&BusinessPerformance@hfgroup.co.ke"

# instance of MIMEMultipart
data = MIMEMultipart()

# storing the senders email address
data['From'] = from1

# storing the receivers email address
# data['To'] = ','.join(address_book)
data['To'] = ','.join(list_of_recipients)
data['CC'] = ','.join(cc_list_of_recipients)

# storing the subject
data['Subject'] = f'TRADE FINANCE INCOME DASHBOARD - {formatted_date}'

# string to store the body of the mail
body =     """
<span> Hello Team,</span>
<br/><br/>
<span>Please find attached Trade Finance Income Report.</span>
<br/><br/>
<ol>
<li><b><u>Summary of segment performance:</u></b><br/>{0}</li><br/>
<li><b><u>Income per branch:</u></b><br/>{1}</li><br/>
<li><b><u>Sales value per branch:</u></b><br/>{2}</li><br/>
</ol>
<br/>
<span>
Kind Regards, <br/>
Analytics and Business Performance
</span>
<br/><br/>
""".format(
            styled_ordered_segment_table.to_html(),
            styled_branch_commission.to_html(),
            styled_branch_sales_val.to_html()
          )
# attach the body with the msg instance
data.attach(MIMEText(body, 'html'))  # 'plain'
os.chdir(path)
FILES = os.listdir()
name = FILES
for i in range(len(FILES)):
# open the file to be sent
    filename = name[i]
    attachment = open(FILES[i], 'rb')
# instance of MIMEBase and named as p
    p = MIMEBase('application', 'octet-stream')
# To change the payload into encoded form
    p.set_payload(attachment.read())
# encode into base64
    encoders.encode_base64(p)
    p.add_header('Content-Disposition', 'attachment; filename= %s'
                 % filename)
# attach the instance 'p' to instance 'msg'
    data.attach(p)
# creates SMTP session
s = smtplib.SMTP(app.hf_email['host'], app.hf_email['port'])
# start TLS for security
s.starttls()
# Authentication
s.login(from1, app.hf_email['password'])
# Converts the Multipart msg into a string
text = data.as_string()
# sending the mail
# combine all email recipients
all_recipients = list_of_recipients + cc_list_of_recipients
s.sendmail(from1, all_recipients, text)
# terminating the session
s.quit()

print("Report Sent")
p_conn.close()


# In[ ]:




