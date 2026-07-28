 # Import packages
import pandas as pd
import numpy as np

from datetime import datetime
import datetime as dt

import calendar
from calendar import monthrange

import xlsxwriter

from dateutil import relativedelta
import psycopg2 as psql
import app_settings as app
import os
import shutil

# Step 1: Create the directory if it does not exist
path = os.path.join(os.getcwd(), "attachments", "drawdown_report")
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

# If you want to remove the entire directory and its contents, use shutil.rmtree
# shutil.rmtree(path)


# Data Mapping
# Segment
segment_data = [
 {'SEGMENT': 'FINANCIAL INSTITUTIONS', 'BANKING_SEGMENT': 'BUSINESS'},
 {'SEGMENT': 'MEDIUM ENTERPRISES', 'BANKING_SEGMENT': 'BUSINESS'},
 {'SEGMENT': 'SMALL ENTERPRISES', 'BANKING_SEGMENT': 'BUSINESS'},
 {'SEGMENT': 'INSTITUTIONAL BANKING', 'BANKING_SEGMENT': 'BUSINESS'},
 {'SEGMENT': 'PROJECT FINANCE', 'BANKING_SEGMENT': 'BUSINESS'},
 {'SEGMENT': 'LARGE ENTERPRISES', 'BANKING_SEGMENT': 'COMMERCIAL'},
 {'SEGMENT': 'DIASPORA', 'BANKING_SEGMENT': 'DIASPORA'},
 {'SEGMENT': 'NON RESIDENT KENYANS', 'BANKING_SEGMENT': 'DIASPORA'},
 {'SEGMENT': 'DIASPORA BUSINESS BANKING', 'BANKING_SEGMENT': 'DIASPORA'},
 {'SEGMENT': 'DIASPORA PERSONAL BANKING', 'BANKING_SEGMENT': 'DIASPORA'},
 {'SEGMENT': 'DIASPORA ULTIMATE BANKING', 'BANKING_SEGMENT': 'DIASPORA'},
 {'SEGMENT': 'MASS', 'BANKING_SEGMENT': 'PERSONAL'},
 {'SEGMENT': 'SCHEME', 'BANKING_SEGMENT': 'PERSONAL'},
 {'SEGMENT': 'STANDARD', 'BANKING_SEGMENT': 'PERSONAL'},
 {'SEGMENT': 'Un_Segmented', 'BANKING_SEGMENT': 'PERSONAL'},
 {'SEGMENT': 'New_Segmented', 'BANKING_SEGMENT': 'PERSONAL'},
 {'SEGMENT': 'PRIVATE', 'BANKING_SEGMENT': 'ULTIMATE'},
 {'SEGMENT': 'ULTIMATE', 'BANKING_SEGMENT': 'ULTIMATE'},
 {'SEGMENT': 'VIRTUAL', 'BANKING_SEGMENT': 'VIRTUAL'}
]
segment_map = pd.DataFrame(segment_data)

# Sector
sector_data = [
 {'FINANCIAL_SECTOR': 'WHOLESALE RETAIL TRADE, REST. HOTELS',  'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'MANUFACTURING', 'ECONOMIC_SECTOR': 'SECONDARY SECTOR'},
 {'FINANCIAL_SECTOR': 'AGRICULTURE AND FISHING',  'ECONOMIC_SECTOR': 'PRIMARY SECTOR'},
 {'FINANCIAL_SECTOR': 'SOCIAL, COMMUNITY & PERSONAL SERVICES',  'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'TRANSPORT & COMMUNICATION',  'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'BUILDING AND CONSTRUCTION',  'ECONOMIC_SECTOR': 'SECONDARY SECTOR'},
 {'FINANCIAL_SECTOR': 'EDUCATION INSTITUTIONS',  'ECONOMIC_SECTOR': 'QUATERMARY SECTOR'},
 {'FINANCIAL_SECTOR': 'PUBLIC ADMINISTRATION',  'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'OTHERS', 'ECONOMIC_SECTOR': 'OTHERS'},
 {'FINANCIAL_SECTOR': 'PROFESSIONAL SERVICES',  'ECONOMIC_SECTOR': 'QUATERMARY SECTOR'},
 {'FINANCIAL_SECTOR': 'HOSPITALITY', 'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'FINANCIAL INTERMEDIATION',  'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'REAL ESTATE', 'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'HEALTH', 'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'ANY OTHER ACTIVITIES N.E.S',  'ECONOMIC_SECTOR': 'OTHERS'},
 {'FINANCIAL_SECTOR': 'CONSUMER DURABLES',  'ECONOMIC_SECTOR': 'SECONDARY SECTOR'},
 {'FINANCIAL_SECTOR': 'ENERGY & WATER', 'ECONOMIC_SECTOR': 'PRIMARY SECTOR'},
 {'FINANCIAL_SECTOR': 'MINING AND QUARRYING',  'ECONOMIC_SECTOR': 'PRIMARY SECTOR'},
 {'FINANCIAL_SECTOR': 'FOREIGN TRADE', 'ECONOMIC_SECTOR': 'TERTIARY SECTOR'},
 {'FINANCIAL_SECTOR': 'DEFAULT', 'ECONOMIC_SECTOR': 'OTHERS'},
 {'FINANCIAL_SECTOR': 'LG FINSC', 'ECONOMIC_SECTOR': 'TERTIARY SECTOR'}
] 
sector_map = pd.DataFrame(sector_data)

# Product
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

product_map = '''
select * from product_mapping
                         
'''
product_map = pd.read_sql_query(product_map , conn)

conn.close()
# print(product_map.head(2))


# Branch
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

branch_map = '''
select * from branch_final_employee_dmc_data
                         
'''
branch_map = pd.read_sql_query(branch_map , conn)

conn.close()

branch_map = branch_map[['staff_branch', 'staff_zone','brn_code']]
branch_map.rename(columns = {'staff_branch':'BRANCH', 'staff_zone':'ZONE', 'brn_code':'CODE'}, inplace = True)
row = pd.DataFrame({
    'BRANCH': ['HEAD OFFICE'],
    'ZONE': ['HEAD OFFICE'],
    'CODE': [100]
})
branch_map = pd.concat([branch_map, row], ignore_index=True)
# branch_map.tail(2)

# Role
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

role_map = '''
select * from branch_employee_dmc_data where active = 1
                         
'''
role_map = pd.read_sql_query(role_map , conn)

conn.close()
role_map = role_map[['sales_code', 'staff_role','staff_name']]
# role_map.head()


# Role Count
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

#mobile loans
role_count_map = '''
select * from branch_employee_dmc_data where active = 1
                         
'''
role_count_map = pd.read_sql_query(role_count_map , conn)

conn.close()
def process_role_count_df(role_count_map, year):
    # Convert date columns to datetime
    role_count_map['start_date'] = pd.to_datetime(role_count_map['start_date'])
    role_count_map['exit_date'] = pd.to_datetime(role_count_map['exit_date'])

    # Create the `current_start_date` column
    default_date = pd.Timestamp(f'{year}-01-01')
    # If the `Exit Date` is missing, assign the default date to `current_start_date`
    role_count_map['current_start_date'] = role_count_map['exit_date'].fillna(default_date)
    # Final logic for using `current_start_date` or `Start Date`
    role_count_map['effective_start_date'] = role_count_map.apply(
        lambda row: row['current_start_date'] if row['start_date'].year != year else row['start_date'],
        axis=1)

    # Get unique roles present in the DataFrame
    unique_roles = role_count_map['staff_role'].unique()
    # Generate months for the current year
    year_months = pd.date_range(start = f'{year}-01-01', end = f'{year}-12-31', freq = 'M')
    # Initialize a dictionary to store cumulative counts for each role
    cumulative_counts = {role: [] for role in unique_roles}
    # Initialize the total counts of employees for each role
    total_counts = {role: 0 for role in unique_roles}
    # Iterate over the months and calculate cumulative counts for each role
    for month in year_months:
        for role in unique_roles:
            # Count employees of this role who started in this month
            started_this_month = role_count_map[(role_count_map['effective_start_date'].dt.year == year) &
                                                (role_count_map['effective_start_date'].dt.month == month.month) &
                                                (role_count_map['staff_role'] == role)].shape[0]

            # Count employees of this role who exited in this month
            exited_this_month = role_count_map[(role_count_map['staff_exit'] == 1) &
                                            (role_count_map['exit_date'].dt.year == year) &
                                            (role_count_map['exit_date'].dt.month == month.month) &
                                            (role_count_map['staff_role'] == role)].shape[0]

            # Adjust the total count based on exits for this role
            total_counts[role] = total_counts[role] + started_this_month - exited_this_month

            # Append the cumulative count to the list for this role
            cumulative_counts[role].append(total_counts[role])

    # Create a new DataFrame with the results
    role_count_map_df = pd.DataFrame({'Month': year_months.strftime('%b-%y')})
    for role in unique_roles:
        role_count_map_df[role] = cumulative_counts[role]

    role_count_map_df = role_count_map_df.groupby('Month').sum()
    role_count_map_df = role_count_map_df.T
    role_count_map_df = role_count_map_df.reset_index()
    role_count_map_df = role_count_map_df.rename(columns={'index': 'Role'})
    
    return role_count_map_df
# role_count_map_df


# Get and Clean Data
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

#mobile loans
drawdown_data = '''
select * from drawdown_daily
where 1=1
---and drawdown_dt >= date_trunc('years',now() - interval '1 year')
and drawdown_dt >= date_trunc('years',now())
                         
'''
drawdown_data = pd.read_sql_query(drawdown_data , conn)

conn.close()

drawdown_data.columns = drawdown_data.columns.str.upper()
# Rename columns
drawdown_data.rename(columns={
    'ACCOUNT_NUMBER' : 'ACCOUNT_NUMBER',
    'CUST_ID' : 'CUST_ID',
    'CUSTOMER_NAME' : 'CUSTOMER_NAME',
    'DRAWDOWN_DT' : 'DRAWDOWN_DT',
    'SALESPERSON' : 'SALES_STAFF',
    'ID_PRODUCT' : 'ID_PRODUCT',
    'PRODUCT_DESC' : 'PRODUCT_NAME',
    'LOAN_OFFICER_ID' : 'LOAN_OFFICER_ID',
    'LOAN_OFFICER_NAME' : 'LOAN_OFFICER_NAME',
    'FINAL_INTEREST' : 'FINAL_INTEREST',
    'LOAN_TERM_DAYS' : 'TOTAL_DAYS',
    'LOAN_TERM_MONTHS' : 'TOTAL_MONTHS',
    'UNIT_CODE' : 'UNIT_CODE',
    'DRAWDOWN_DT_1' : 'EOM_DATE',
    'NET_DRAWDOWN' : 'NET_DRAWDOWN',
    'GROSS_DRAWDOWN' : 'GROSS_DRAWDOWN',
    'CUSTOMER_SEGMENT' : 'SEGMENT',
    'FINANCIAL_SECTOR' : 'FINANCIAL_SECTOR',
    'ACTIVITY_SECTOR' : 'ACTIVITY_SECTOR',
    'DIASPORA_CHECK' : 'DIASPORA_CHECK',
    'FKGD_CATEGORY' : 'FKGD_CATEGORY',
    'DESCRIPTION' : 'DESCRIPTION'
}, inplace=True)

# Remove spaces
drawdown_data['SALES_STAFF'] = drawdown_data['SALES_STAFF'].astype(str).apply(lambda x: x.strip())
drawdown_data['LOAN_OFFICER_ID'] = drawdown_data['LOAN_OFFICER_ID'].astype(str).apply(lambda x: x.strip())

# fill blanks
drawdown_data['SEGMENT'] = drawdown_data['SEGMENT'].fillna('MASS')
drawdown_data['NET_DRAWDOWN'] = drawdown_data['NET_DRAWDOWN'].fillna(0)
drawdown_data['GROSS_DRAWDOWN'] = drawdown_data['GROSS_DRAWDOWN'].fillna(0)
drawdown_data['FKGD_CATEGORY'] = drawdown_data['FKGD_CATEGORY'].fillna(1)
drawdown_data['DESCRIPTION'] = drawdown_data['DESCRIPTION'].fillna('OVERDRAFT')
drawdown_data['FKGD_CATEGORY'] = drawdown_data['FKGD_CATEGORY'].replace(0, 1)
drawdown_data['DESCRIPTION'] = drawdown_data['DESCRIPTION'].replace('null', 'OVERDRAFT')

# Remove staff rows
drawdown_data = drawdown_data[~drawdown_data['SEGMENT'].str.contains('STAFF', case=False, na=False)]
drawdown_data = drawdown_data[~drawdown_data['PRODUCT_NAME'].str.contains('STAFF', case=False, na=False)]
drawdown_data = drawdown_data[~drawdown_data['SALES_STAFF'].str.contains('GLK1744', case=False, na=False)]

# Correct sales codes
drawdown_data.loc[drawdown_data['SALES_STAFF'] == 'AL3116', 'SALES_STAFF'] = 'AKL3116'
drawdown_data.loc[drawdown_data['SALES_STAFF'] == 'SK3539', 'SALES_STAFF'] = 'SKK3539'
drawdown_data.loc[drawdown_data['SALES_STAFF'] == 'DI3498', 'SALES_STAFF'] = 'DKI3498'
drawdown_data.loc[drawdown_data['SALES_STAFF'] == 'PK3453', 'SALES_STAFF'] = 'PMK3453'
drawdown_data.loc[drawdown_data['SALES_STAFF'] == 'SC3568', 'SALES_STAFF'] = 'SJC3568'
drawdown_data.loc[drawdown_data['SALES_STAFF'] == 'DWN3998', 'SALES_STAFF'] = 'DN3998'

print(drawdown_data.shape)

# Merge the Data with the various data maps
# With segment_map
loan_drawdown = pd.merge(drawdown_data, segment_map, left_on = 'SEGMENT', right_on = 'SEGMENT', how = 'left')
print(loan_drawdown.shape)

# With branch_map
loan_drawdown = pd.merge(loan_drawdown, branch_map, left_on = 'UNIT_CODE', right_on = 'CODE', how = 'left')
loan_drawdown.drop(columns = ['CODE'], inplace = True)
print(loan_drawdown.shape)

# With sector_map
loan_drawdown = pd.merge(loan_drawdown, sector_map, left_on = 'FINANCIAL_SECTOR', right_on = 'FINANCIAL_SECTOR', how = 'left')
print(loan_drawdown.shape)

# With product_map
loan_drawdown = pd.merge(loan_drawdown, product_map[['code', 'loan_category', 'loan_security']], left_on = 'ID_PRODUCT', right_on = 'code', how = 'left')
loan_drawdown.rename(columns = {'loan_category':'PRODUCT_CATEGORY', 'loan_security':'SECURITY'}, inplace =True)
loan_drawdown['PRODUCT_CATEGORY'] = loan_drawdown['PRODUCT_CATEGORY'].fillna('TERM LOAN')
loan_drawdown['SECURITY'] = loan_drawdown['SECURITY'].fillna('UNSECURED')
loan_drawdown.drop(columns = ['code'], inplace = True)
print(loan_drawdown.shape)

# Get mortgage class
def categorize_mortgage(row):
    conditions = {
        (row['PRODUCT_CATEGORY'] == "MORTGAGE") & (row['FINAL_INTEREST'] >= 10): "MARKET RATE",
        (row['PRODUCT_CATEGORY'] == "MORTGAGE") & (row['FINAL_INTEREST'] < 10): "NON_MARKET RATE"
    }
    return next((value for condition, value in conditions.items() if condition), "OTHERS")

loan_drawdown['MORTGAGE'] = loan_drawdown.apply(categorize_mortgage, axis=1)
print(loan_drawdown['MORTGAGE'].unique())
print(loan_drawdown.shape)

# With role_map
# Define a function to find matching values from column 'NAME' or 'ROLE'in role_map DataFrame in either column 'SALES_STAFF', 'LOAN_OFFICER_ID' in loan_drawdown DataFrame
def find_matching_value(row, role_map, column_1, lookup_column, return_column):
    if row[column_1] in role_map[lookup_column].values:
        return role_map.loc[role_map[lookup_column] == row[column_1], return_column].values[0]
    return 'Others'

loan_drawdown['ROLE'] = loan_drawdown.apply(lambda row: find_matching_value(row, role_map,'SALES_STAFF', 'sales_code','staff_role'), axis=1)
loan_drawdown['NAME'] = loan_drawdown.apply(lambda row: find_matching_value(row, role_map,'SALES_STAFF', 'sales_code','staff_name'), axis=1)
print(loan_drawdown.shape)

# Function to get TERM
def determine_duration(row):
    if row['TOTAL_MONTHS'] < 48 or row['ID_PRODUCT'] == 1:
        return 'SHORT'
    else:
        return 'LONG'
    
loan_drawdown['TERM'] = loan_drawdown.apply(determine_duration, axis=1)
print(loan_drawdown.shape)

# Function to get month
def get_month_abbreviation(date):
    return date.strftime('%b')

loan_drawdown['MONTH'] = loan_drawdown['DRAWDOWN_DT'].apply(get_month_abbreviation)
print(loan_drawdown.shape)

# Function to get month and year
def get_month_year_abbrev(date):
    return date.strftime('%b-%y')

loan_drawdown['MONTH_YR'] = loan_drawdown['DRAWDOWN_DT'].apply(get_month_year_abbrev)
print(loan_drawdown.shape)

# Function to get Sales code
def get_sales_staff(row):
        return row['SALES_STAFF']

loan_drawdown['SALES_CODE'] = loan_drawdown.apply(get_sales_staff, axis=1)
print(loan_drawdown.shape)

# Function to check for funded accounts
def check_interest(row):
    return 'Y' if row['FINAL_INTEREST'] < 9.5 else 'N'

loan_drawdown['FUNDED_CHECK'] = loan_drawdown.apply(check_interest, axis = 1)
print(loan_drawdown.shape)

# Function to check for diaspora customers
def check_diaspora(row):
    return 'Y' if row['DIASPORA_CHECK'] == 'Diaspora' else 'N'
 
loan_drawdown['IS_DIASPORA'] = loan_drawdown.apply(check_diaspora, axis = 1)
print(loan_drawdown.shape)

# Week column
loan_drawdown['WEEK'] = loan_drawdown['DRAWDOWN_DT'].apply(lambda x: x.isocalendar()[1])
print(loan_drawdown.shape)

# Week_Month column
loan_drawdown['WEEK_MONTH'] = loan_drawdown['WEEK'].astype(str) + ' - ' + loan_drawdown['MONTH']
print(loan_drawdown.shape)

# Reorder the columns to desired output
new_column_order = ['ACCOUNT_NUMBER', 'CUST_ID', 'CUSTOMER_NAME', 'DRAWDOWN_DT',
                    'SALES_STAFF', 'ID_PRODUCT', 'PRODUCT_NAME', 'LOAN_OFFICER_ID',
                    'LOAN_OFFICER_NAME', 'FINAL_INTEREST', 'TOTAL_DAYS', 'TOTAL_MONTHS',
                    'UNIT_CODE', 'EOM_DATE', 'NET_DRAWDOWN', 'GROSS_DRAWDOWN', 'SEGMENT',
                    'FINANCIAL_SECTOR', 'ACTIVITY_SECTOR', 'DIASPORA_CHECK',
                    'FKGD_CATEGORY', 'DESCRIPTION', 'BANKING_SEGMENT', 'PRODUCT_CATEGORY', 'MORTGAGE',
                    'ECONOMIC_SECTOR', 'SECURITY', 'TERM', 'MONTH', 'BRANCH', 'ZONE',
                    'ROLE', 'SALES_CODE', 'NAME', 'FUNDED_CHECK', 'IS_DIASPORA', 
                    'MONTH_YR', 'WEEK', 'WEEK_MONTH']

def reorder_columns(loan_drawdown, new_column_order):
    return loan_drawdown[new_column_order]
loan_drawdown = reorder_columns(loan_drawdown, new_column_order)
print(loan_drawdown.shape)
print(drawdown_data.shape)


# Date variables
# Get the max date(reporting month)
max_date = loan_drawdown['DRAWDOWN_DT'].max()
max_month_name = max_date.strftime('%b-%y')
month_number = max_date.month
# week_number = max_date.isocalendar()[1]
# week_number = max_date.week
week_number = loan_drawdown['WEEK'].max()
year = max_date.year
print(f"Max Date: {max_date}")
print(f"Max Month Date: {max_month_name}")
print(f"Month: {month_number}")
print(f"Week: {week_number}")
print(f"Year: {year}")

# Get days elapsed and remaining to get YTD and MTD
days_in_month = monthrange(year, month_number)[1]
elapsed_days = max_date.day
remaining_days = days_in_month - elapsed_days
print(f'Elapsed days: {elapsed_days}')
print(f'Remaining days: {remaining_days}')

# Get dates in the reporting month
dates_in_month = [(dt.date(dt.date.today().year, month_number, i).strftime('%d-%b-%y')).upper() for i in range(1, days_in_month+1)]
# dates_in_month

# Check the first date in the reporting month
first_date = dates_in_month[0]
print(first_date)

# Check the month name of the first date of the reporting month
first_month_name = dt.datetime.strptime(first_date, '%d-%b-%y').strftime('%B').upper()
print(first_month_name)

# Format date for reporting 
day = max_date.strftime('%d').lstrip('0')
suffix = 'th' if 11 <= int(day) <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(int(day) % 10, 'th')
formatted_date = max_date.strftime(f'{day}{suffix} %b %Y')
print('Report Date:', formatted_date)

#Get months of the reporting year
months = [dt.date(year - 1, 12, 1).strftime('%b-%y')] + [dt.date(year, i, 1).strftime('%b-%y') for i in range(1, 13)]
# months

# Get the month order of the reporting year
month_column_order = months[1:month_number+1]
# month_column_order

# Check the reporting month
# month_column_order[-1]


# Define pivot functions
# Count with no columns
def count(dataframe, index, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, values = value_column_name, aggfunc = 'count')
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt 

# Sum with no columns
def sum(dataframe, index, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, values = value_column_name, aggfunc = 'sum')
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt 

# Count with specified column order
def count_monthly(dataframe, index, months_column_name, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, columns = months_column_name, values = value_column_name, aggfunc = 'count')
    amt = amt.reindex(columns = month_column_order)
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt

# Sum with specified column order
def sum_monthly(dataframe, index, months_column_name, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, columns = months_column_name, values = value_column_name, aggfunc = 'sum')
    amt = amt.reindex(columns = month_column_order)
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt

# sum MOM for segment analysis
def segment_value(dataframe, index, months_column_name, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, columns = months_column_name, values = value_column_name, aggfunc = 'sum')
    amt = amt.reindex(columns = month_column_order)
    amt['YTD_Actual'] = amt.sum(axis = 1)
    amt = amt.fillna(0)
    return amt

# column name undefined
def sum_undefined(dataframe, index, column_name, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, columns = column_name, values = value_column_name, aggfunc = 'sum')
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt 

# Count with no index
def count_no_index(dataframe, months_column_name, value_column_name):
    amt = pd.pivot_table(dataframe, columns = months_column_name, values = value_column_name, aggfunc = 'count')
    amt = amt.reindex(columns = month_column_order)
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt

# Sum with no index
def sum_no_index(dataframe, months_column_name, value_column_name):
    amt = pd.pivot_table(dataframe, columns = months_column_name, values = value_column_name, aggfunc = 'sum')
    amt = amt.reindex(columns = month_column_order)
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt


# Define Acheivement Calculation
def calculate_percentage_achieved(row, numerator_col, denominator_col):
    numerator = row[numerator_col]
    denominator = row[denominator_col]
    if denominator == 0:
        return 0
    return numerator / denominator

delta = relativedelta.relativedelta(max_date, max_date.replace(month=1, day=1))
# delta

year_fraction = delta.years + delta.months / 12 + delta.days / 365
# year_fraction


# Define worksheet names and format styles
file_name = f'Drawdown Report - {formatted_date}.xlsx'

daily_drawdown_report_writer = pd.ExcelWriter(file_name, engine='xlsxwriter')
workbook = daily_drawdown_report_writer.book
workbook.set_tab_ratio(90)
sheet_tab_color = '#2AAFB8'  # Blue color
menu_sheet_tab_color = '#2AAFB8'

menu_sheet_name = 'MENU'
dashboard_sheet_name = 'Dashboard'
branches_sheet_name = 'Branches'
branches_retail_and_commercial_sheet_name = 'Branches - Retail & Commercial'
segments_sheet_name = 'Segment_Disbursements'
segments_per_role_sheet_name = 'Role_per_Segment_View'
product_disbursements_sheet_name = 'Product_Disbursements'
segments_per_product_category_sheet_name = 'Product_per_Segment_View'
mortgage_sheet_name = 'Mortgage_Business'
msu_sheet_name = 'Mortgage_Sales_Unit'
mortgage_mrkt_rate_sales_sheet_name = 'Mortgage_Mrkt_Rate_Sales'
mortgage_non_mrkt_rate_sales_sheet_name = 'Mortgage_Non_Mrkt_Rate_Sales'
segment_per_mortgage_sheet_name = 'Mortgage_per_Segment_view'
diaspora_disbursements_sheet_name = 'Diaspora_Disbursements'
tenor_disbursements_sheet_name = 'Tenor_Disbursements'
sector_disbursements_sheet_name = 'Sector_Disbursements'
loan_productivity_sheet_name = 'Loan_Productivity'
weekly_productivity_sheet_name = 'Weekly_Productivity'
products_view_sheet_name = 'Products_View'
scheme_loans_sheet_name = 'Scheme_Loans'
performance_sheet_name = 'Sales_Team_Performance'
loan_drawdowns_sheet_name = 'Loan_Drawdowns'
analysis_sheet_name = 'Analysis'

# Define Formats
date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
comma_format = workbook.add_format({'num_format': '_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-'})
border_format = workbook.add_format({'border': 1, 'border_color': 'black'})
bold_border_format = workbook.add_format({'bold': True, 'border': 2, 'border_color': 'black'})
number_format = workbook.add_format({'num_format' : '#,###.00,,'})
million_format = workbook.add_format({'num_format': '#,##0.0,," M"'})
percent_format = workbook.add_format({'num_format': '0%'})
center_format = workbook.add_format({"align": "center"})
bold_format = workbook.add_format({'bold': True})
hidden_format = workbook.add_format({'hidden': True})

green_format = workbook.add_format({'bold': True,'bg_color': '#70AD47', 'font_color': '#000000'})
ytd_grey_format = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'font_color': '#000000', 'num_format': '0%'})
amber_format = workbook.add_format({'bold': True,'bg_color': '#C69500', 'font_color': '#000000'})
red_format = workbook.add_format({'bold': True,'bg_color': '#C0504D', 'font_color': '#000000'})

conditional_format = [
    {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format},
    {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format},
    {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format}
]    

color_scale = {'type': '2_color_scale', 'min_color': "#FFD966",  'max_color': "#00FF00"}

deepskyblue_fill_format = workbook.add_format({
    "bold": True, 
    "bg_color": "#1B4872", 
    "border": 1
})

deepskyblue2_fill_format = workbook.add_format({'bg_color': '#1B4872'})

lightcyan_fill_format = workbook.add_format({'bg_color': '#D9D9D9'})

blue_fill_format = workbook.add_format({
    'bg_color': '#1B4872',
    'bold': True,
    'border': 1,
    'border_color': 'black'
})

gold_fill_format = workbook.add_format({
    'bg_color': '#C69500',
    'bold': True,
    'border': 1,
    'border_color': 'black'
})

white_fill_format = workbook.add_format({
    'bg_color': '#ffffff',
    'bold': True,
    'border': 1,
    'border_color': 'black'
})

paleturquoise_fill_format = workbook.add_format({
    'bg_color': '#1B4872',
    'bold': True,
    'border': 1,
    'border_color': 'black'
})

delft_blue_fill_format = workbook.add_format({
    'bold': True,
    'bg_color': '#1B4872',
    'border': 2, 
    'border_color': 'black', 
    'align': 'center'
})

lemonchiffon_format = workbook.add_format({
    'bg_color': '#fff2cc',
    'border': 1,  # Border style
    'border_color': 'black'  # Border color
})


lavender_fill_format = workbook.add_format({
    'bg_color': '#D9D9D9',
    'bold': True,
    'border': 1,
    'border_color': 'black'
})

lightsteelblue_fill_format = workbook.add_format({
    'bg_color': '#D9D9D9',
    'border': 1,
    'border_color': 'black'
})

delft_blue_fill_format.set_font_color('#C69500')
deepskyblue_fill_format.set_font_color('#F2F2F2')


# Generate tables and write to their respective sheets
# Menu Worksheet
menu_button_format = workbook.add_format({
    "bold": True,
    "font_color": "white",
    "align": "center",
    "valign": "vcenter",
    "bg_color": "#2AAFB8",
    "border": 2,
})

orange_button_format = workbook.add_format({
    "bold": True,
    "font_color": "black",
    "align": "center",
    "valign": "vcenter",
    "bg_color": "#1B4872",
    "border": 2,
})

blue_button_format = workbook.add_format({
    "bold": True,
    "font_color": "white",
    "align": "center",
    "valign": "vcenter",
    "bg_color": "#2AAFB8",
    "border": 2,
})

menu_heading_props = {
    'width':650, 'height':60, 'object_position':3,
    'x_offset': 30,
    'font':{'color':'blue','name':'cambria','size':32,'bold':True},
    'align':{'vertical':'middle','horizontal':'left'},
    'fill':{'color':'#FFFFFF'},
    'line':{'none':True}
}

menu_sub_heading_tabs = {
    'width':302, 'height':37, 'object_position':3,
    'x_offset': 5, 'y_offset':10,
    'font':{'color':'black','name':'cambria','size':12,'bold':True},
    'align':{'vertical':'middle','horizontal':'left'},
    'fill':{'color':'#1B4872'},
    'line':{'none':True}
}

menu_worksheet = workbook.add_worksheet(menu_sheet_name)
# menu_worksheet = daily_drawdown_report_writer.sheets[menu_sheet_name]
menu_worksheet.set_zoom(80)
menu_worksheet.hide_gridlines(2)
menu_worksheet.set_tab_color(menu_sheet_tab_color)

menu_worksheet.insert_textbox('E2', 'DAILY DRAWDOWN REPORT',menu_heading_props)
menu_worksheet.insert_textbox('B6', 'Bank Summaries:',menu_sub_heading_tabs)
menu_worksheet.insert_textbox('B13', 'Performance:',menu_sub_heading_tabs)
menu_worksheet.insert_textbox('B20', 'Segment Summaries:',menu_sub_heading_tabs)
menu_worksheet.insert_textbox('B27', 'Products:',menu_sub_heading_tabs)
menu_worksheet.insert_textbox('B34', 'Data Dump:',menu_sub_heading_tabs)



# Bank Summaries
menu_worksheet.merge_range("B8:D10", "", blue_button_format)
menu_worksheet.write_url('B8','internal:Dashboard!A1', blue_button_format, string = 'DASHBOARD')
menu_worksheet.merge_range("F8:H10", "", blue_button_format)
menu_worksheet.write_url('F8','internal:Branches!A1', blue_button_format, string = 'BRANCHES')
menu_worksheet.merge_range("J8:L10", "", blue_button_format)
menu_worksheet.write_url('J8','internal:Segment_Disbursements!A1', blue_button_format, string = 'SEGMENTS')
menu_worksheet.merge_range("N8:P10", "", blue_button_format)
menu_worksheet.write_url('N8','internal:Diaspora_Disbursements!A1', blue_button_format, string = 'DIASPORA')
menu_worksheet.merge_range("R8:T10", "", blue_button_format)
menu_worksheet.write_url('R8','internal:Mortgage_Business!A1', blue_button_format, string = 'MORTGAGE')
menu_worksheet.merge_range("V8:X10", "", blue_button_format)
menu_worksheet.write_url('V8','internal:Tenor_Disbursements!A1', blue_button_format, string = 'LOAN_TENOR')
menu_worksheet.merge_range("Z8:AC10", "", blue_button_format)
menu_worksheet.write_url('Z8','internal:Sector_Disbursements!A1', blue_button_format, string = 'SECTORS')

# Performance
menu_worksheet.merge_range("B15:D17", "", blue_button_format)
menu_worksheet.write_url('B15','internal:Sales_Team_Performance!B1', blue_button_format, string = 'SALES_TEAM')
menu_worksheet.merge_range("F15:H17", "", blue_button_format)
menu_worksheet.write_url('F15','internal:Loan_Productivity!B1', blue_button_format, string = 'LOAN_PRODUCTIVITY')
menu_worksheet.merge_range("J15:L17", "", blue_button_format)
menu_worksheet.write_url('J15','internal:Weekly_Productivity!B1', blue_button_format, string = 'WEEKLY_PRODUCTIVITY')
menu_worksheet.merge_range("N15:P17", "", blue_button_format)
menu_worksheet.write_url('N15','internal:Mortgage_Sales_Unit!A1', blue_button_format, string = 'MORTGAGE_SALES_UNIT')



# Segment summaries
menu_worksheet.merge_range("B22:D24", "", blue_button_format)
menu_worksheet.write_url('B22','internal:Role_per_Segment_View!A1', blue_button_format, string = 'ROLE_PER_SEGMENT')
menu_worksheet.merge_range("F22:H24", "", blue_button_format)
menu_worksheet.write_url('F22','internal:Product_per_Segment_View!A1', blue_button_format, string = 'PRODUCT_PER_SEGMENT')
menu_worksheet.merge_range("J22:L24", "", blue_button_format)
menu_worksheet.write_url('J22','internal:Mortgage_per_Segment_view!A1', blue_button_format, string = 'MORTGAGE_PER_SEGMENT')

# Product Summaries
menu_worksheet.merge_range("B29:D31", "", blue_button_format)
menu_worksheet.write_url('B29','internal:Product_Disbursements!A1', blue_button_format, string = 'PRODUCTS')
menu_worksheet.merge_range("F29:H31", "", blue_button_format)
menu_worksheet.write_url('F29','internal:Products_View!A1', blue_button_format, string = 'PRODUCTS_VIEW')
menu_worksheet.merge_range("J29:L31", "", blue_button_format)
menu_worksheet.write_url('J29','internal:Scheme_Loans!A1', blue_button_format, string = 'SCHEME_LOANS')

# Data
menu_worksheet.merge_range("B36:D38", "", blue_button_format)
menu_worksheet.write_url('B36','internal:Loan_Drawdowns!A1', blue_button_format, string = 'DATA_DUMP')

# menu_worksheet.hide()
print(f"Sheet '{menu_sheet_name}' is successfully saved.")


# Dashboard Worksheet
dashboard_worksheet = workbook.add_worksheet(dashboard_sheet_name)
dashboard_worksheet.set_zoom(70)
dashboard_worksheet.hide_gridlines(2)
dashboard_worksheet.set_tab_color(sheet_tab_color)


# Branches worksheet
# Zone table
zone  = [
    {'BRANCH':'Zone A', 'ZONE':'Zone A'},
    {'BRANCH':'Zone B', 'ZONE':'Zone B'},
    {'BRANCH':'Zone C', 'ZONE': 'Zone C'},
    {'BRANCH':'', 'ZONE':'TOTAL'}
]
zone_map = pd.DataFrame(zone)
# zone_map

# Branch and zone targets from Metabase
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

branch_targets = '''
select * from branch_final_employee_dmc_data
                         
'''
branch_targets = pd.read_sql_query(branch_targets , conn)

conn.close()
# Get targets for respective zones
zone_target_loan_disbursement_table = sum(branch_targets, index = 'staff_zone', value_column_name = ['target_loan_disbursement', 'target_retail_loan_disbursement', 'target_commercial_loan_disbursement'])
zone_target_loan_disbursement_table = zone_target_loan_disbursement_table[~zone_target_loan_disbursement_table['staff_zone'].str.contains('HEAD OFFICE', case=False, na=False)]
zone_target_loan_disbursement_table.rename(columns = {'target_loan_disbursement': 'Total_FY_Target','target_retail_loan_disbursement':'Retail_FY_Target','target_commercial_loan_disbursement':'Commercial_FY_Target'}, inplace = True)
sum_row = zone_target_loan_disbursement_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'staff_zone', 'TOTAL')   
zone_target_loan_disbursement_table = pd.concat([zone_target_loan_disbursement_table, sum_row], ignore_index = True)
# zone_target_loan_disbursement_table


# Monthly zone drawdown
zone_net_monthly_table = sum_monthly(loan_drawdown, months_column_name = 'MONTH_YR', index = 'ZONE', value_column_name = 'NET_DRAWDOWN')
zone_net_monthly_table = zone_net_monthly_table[~zone_net_monthly_table['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
sum_row = zone_net_monthly_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
zone_net_monthly_table = pd.concat([zone_net_monthly_table, sum_row], ignore_index = True)
zone_net_monthly_table['YTD_Actual'] = zone_net_monthly_table[month_column_order].sum(axis=1)
# zone_net_monthly_table


# Net Drawdown
zone_net_amt_table = sum(loan_drawdown, index = 'ZONE', value_column_name = 'NET_DRAWDOWN')
zone_net_amt_table = zone_net_amt_table[~zone_net_amt_table['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
sum_row = zone_net_amt_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
zone_net_amt_table = pd.concat([zone_net_amt_table, sum_row], ignore_index = True)
# zone_net_amt_table


# Gross Drawdown
zone_gross_amt_table = sum(loan_drawdown, index = 'ZONE', value_column_name = 'GROSS_DRAWDOWN')
zone_gross_amt_table = zone_gross_amt_table[~zone_gross_amt_table['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
sum_row = zone_gross_amt_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
zone_gross_amt_table = pd.concat([zone_gross_amt_table, sum_row], ignore_index = True)
# zone_gross_amt_table

# Weekly Drawdown
weekly_zone_drawdown = loan_drawdown.loc[loan_drawdown['WEEK'] == week_number]
weekly_zone_view = sum(weekly_zone_drawdown, index = 'ZONE', value_column_name = 'NET_DRAWDOWN')
weekly_zone_view = weekly_zone_view[~weekly_zone_view['ZONE'].str.contains('HEAD OFFICE', case = False, na = False)]
weekly_zone_view.rename(columns = {'NET_DRAWDOWN':'Weekly'}, inplace = True)
sum_row = weekly_zone_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
weekly_zone_view = pd.concat([weekly_zone_view, sum_row], ignore_index = True)
# weekly_zone_view


# Daily Drawdown
daily_zone_drawdown = loan_drawdown.loc[loan_drawdown['DRAWDOWN_DT'] == max_date]
daily_zone_view = sum(daily_zone_drawdown, index='ZONE', value_column_name='NET_DRAWDOWN')
daily_zone_view = daily_zone_view[~daily_zone_view['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
daily_zone_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = daily_zone_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
daily_zone_view = pd.concat([daily_zone_view, sum_row], ignore_index = True)
# daily_zone_view

# Merge zone tables
zone_table = pd.merge(zone_map,zone_net_monthly_table, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_table = pd.merge(zone_table,zone_gross_amt_table,left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_table = pd.merge(zone_table,zone_net_amt_table,left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_table = pd.merge(zone_table, zone_target_loan_disbursement_table, left_on = 'ZONE', right_on = 'staff_zone', how = 'left')
zone_table.rename(columns={'GROSS_DRAWDOWN' : 'GROSS', 'NET_DRAWDOWN': 'NET'}, inplace = True)
zone_table.drop(columns = ['staff_zone', 'Commercial_FY_Target', 'Retail_FY_Target'], inplace = True)

specified_order = ['GROSS', 'NET', 'Total_FY_Target', 'YTD_Actual']
remaining_columns = [col for col in zone_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
zone_table = zone_table.reindex(columns = new_order)
# zone_table

# get the latest month
# zone_table[[(max_month_name)]]

# zone achievements
zone_table['YTD_Target'] = zone_table['Total_FY_Target'] * year_fraction
zone_table['YTD_%_Achieved'] = zone_table.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
# zone_table
zone_table['Monthly_Target'] = zone_table['Total_FY_Target'] / 12
zone_table['Month_Actual'] = zone_table[[(max_month_name)]]
zone_table['Month_Deficit'] = zone_table['Month_Actual'] - zone_table['Monthly_Target']
zone_table['Month_%_Achieved'] = zone_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)

specified_order = month_column_order + ['GROSS', 'NET', 'Total_FY_Target', 'YTD_Target', 'YTD_Actual','YTD_%_Achieved',
                   'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved']
remaining_columns = [col for col in zone_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
zone_table = zone_table.reindex(columns = new_order)
# zone_table


# Merge weekly and daily tables
zone_table = pd.merge(zone_table,weekly_zone_view, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_table = pd.merge(zone_table,daily_zone_view, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_table = zone_table.fillna(0)
# zone_table

# Create Rank
# # Create a new column 'Rank' initialized with None
zone_table['Rank'] = None
# Exclude the last row and apply the rank function
zone_table.iloc[:-1, zone_table.columns.get_loc('Rank')] = zone_table.iloc[:-1]['Month_%_Achieved'].rank(method = 'dense', ascending = False)

cols_to_front = ['Rank']
remaining_cols = [col for col in zone_table.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols

zone_table = zone_table[new_order]
zone_table = zone_table.sort_values(by = 'Rank')
# zone_table
zone_table.shape


# Branch View Map from Metabase
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

#mobile loans
branch_view_map = '''
select * from branch_final_employee_dmc_data
                         
'''
branch_view_map = pd.read_sql_query(branch_view_map , conn)

conn.close()

# In[ ]:

branch_view_map = branch_view_map[['staff_branch', 'staff_zone','brn_code']]
branch_view_map.rename(columns = {'staff_branch':'BRANCH', 'staff_zone':'ZONE', 'brn_code':'CODE'}, inplace =True)
row = pd.DataFrame({
    'BRANCH': ['TOTAL'],
    'ZONE': [''],
    'CODE': ['TOTAL']
})
branch_view_map = pd.concat([branch_view_map, row], ignore_index=True)
# branch_view_map.tail()

# Branch Targets
branch_target_loan_disbursement_table = sum(branch_targets, index = 'brn_code', value_column_name = ['target_loan_disbursement', 'target_retail_loan_disbursement', 'target_commercial_loan_disbursement'])
branch_target_loan_disbursement_table = branch_target_loan_disbursement_table[branch_target_loan_disbursement_table['brn_code'] != 100]
branch_target_loan_disbursement_table.rename(columns = {'target_loan_disbursement': 'Total_FY_Target','target_retail_loan_disbursement':'Retail_FY_Target','target_commercial_loan_disbursement':'Commercial_FY_Target'}, inplace = True)
sum_row = branch_target_loan_disbursement_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'brn_code', 'TOTAL')   
branch_target_loan_disbursement_table = pd.concat([branch_target_loan_disbursement_table, sum_row], ignore_index = True)
# branch_target_loan_disbursement_table.tail(2)


# Branch Monthly drawdowns
branch_net_monthly_table = sum_monthly(loan_drawdown, months_column_name = 'MONTH_YR', index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
branch_net_monthly_table = branch_net_monthly_table[branch_net_monthly_table['UNIT_CODE'] != 100]
sum_row = branch_net_monthly_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
branch_net_monthly_table = pd.concat([branch_net_monthly_table, sum_row], ignore_index = True)
branch_net_monthly_table['YTD_Actual'] = branch_net_monthly_table[month_column_order].sum(axis=1)
# branch_net_monthly_table.tail(2)


# Gross Drawdown
branch_gross_amt_table = sum(loan_drawdown, index = 'UNIT_CODE', value_column_name = 'GROSS_DRAWDOWN')
branch_gross_amt_table = branch_gross_amt_table[branch_gross_amt_table['UNIT_CODE'] != 100]
sum_row = branch_gross_amt_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
branch_gross_amt_table = pd.concat([branch_gross_amt_table, sum_row], ignore_index = True)
# branch_gross_amt_table.tail(2)


# Net Drawdown
branch_net_amt_table = sum(loan_drawdown, index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
branch_net_amt_table = branch_net_amt_table[branch_net_amt_table['UNIT_CODE'] != 100]
sum_row = branch_net_amt_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
branch_net_amt_table = pd.concat([branch_net_amt_table, sum_row], ignore_index = True)
# branch_net_amt_table.tail(2)


# Weekly Drawdown
weekly_branch_drawdown = loan_drawdown.loc[loan_drawdown['WEEK'] == week_number]
weekly_branch_view = sum(weekly_branch_drawdown, index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
weekly_branch_view = weekly_branch_view[weekly_branch_view['UNIT_CODE'] != 100]
weekly_branch_view.rename(columns =  {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = weekly_branch_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
weekly_branch_view = pd.concat([weekly_branch_view, sum_row], ignore_index = True)
# weekly_branch_view.tail(2)

# Daily Drawdown
daily_branch_drawdown = loan_drawdown.loc[loan_drawdown['DRAWDOWN_DT'] == max_date]
daily_branch_view = sum(daily_branch_drawdown, index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
daily_branch_view = daily_branch_view[daily_branch_view['UNIT_CODE'] != 100]
daily_branch_view.rename(columns =  {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = daily_branch_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
daily_branch_view = pd.concat([daily_branch_view, sum_row], ignore_index = True)
# daily_branch_view.tail(2)

# Merge branch tables
branch_table = pd.merge(branch_view_map,branch_net_monthly_table, left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_table.drop(columns = ['UNIT_CODE'], inplace = True)

branch_table = pd.merge(branch_table,branch_gross_amt_table,left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_table.drop(columns = ['UNIT_CODE'], inplace = True)

branch_table = pd.merge(branch_table,branch_net_amt_table,left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_table.drop(columns = ['UNIT_CODE'], inplace = True)

branch_table = pd.merge(branch_table,weekly_branch_view,left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_table.drop(columns = ['UNIT_CODE'], inplace = True)

branch_table = pd.merge(branch_table,daily_branch_view,left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_table.drop(columns = ['UNIT_CODE'], inplace = True)

branch_table = pd.merge(branch_table, branch_target_loan_disbursement_table, left_on = 'CODE', right_on = 'brn_code', how = 'left')

branch_table.drop(columns = ['CODE', 'brn_code', 'Commercial_FY_Target', 'Retail_FY_Target'], inplace = True)
branch_table.rename(columns={'GROSS_DRAWDOWN' : 'GROSS', 'NET_DRAWDOWN': 'NET'}, inplace = True)

specified_order = ['GROSS', 'NET', 'Weekly','Daily','Total_FY_Target', 'YTD_Actual']
remaining_columns = [col for col in branch_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
branch_table = branch_table.reindex(columns = new_order)
branch_table = branch_table.fillna(0)
# branch_table.tail()

# Branch achievements
branch_table['YTD_Target'] = branch_table['Total_FY_Target'] * year_fraction
branch_table['YTD_%_Achieved'] = branch_table.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
branch_table['Monthly_Target'] = branch_table['Total_FY_Target'] / 12
branch_table['Month_Actual'] = branch_table[[(max_month_name)]]
branch_table['Month_Deficit'] = branch_table['Month_Actual'] - branch_table['Monthly_Target']
branch_table['Month_%_Achieved'] = branch_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)

specified_order = month_column_order + ['GROSS', 'NET', 'Total_FY_Target', 'YTD_Target', 'YTD_Actual','YTD_%_Achieved',
                   'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved','Weekly','Daily']
remaining_columns = [col for col in branch_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
branch_table = branch_table.reindex(columns = new_order)
# branch_table.tail()


# Create Rank
branch_table['Rank'] = None

branch_table.iloc[:-1, branch_table.columns.get_loc('Rank')] = branch_table.iloc[:-1]['Month_%_Achieved'].rank(method = 'dense', ascending = False)

cols_to_front = ['Rank']
remaining_cols = [col for col in branch_table.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols

branch_table = branch_table[new_order]
branch_table = branch_table.sort_values(by = 'Rank')
# branch_table.head()
branch_table.shape


# Write tables to excel
all_dfs = [zone_table, branch_table]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = branches_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

branches_worksheet = daily_drawdown_report_writer.sheets[branches_sheet_name]
branches_worksheet.set_zoom(80)
branches_worksheet.set_tab_color(sheet_tab_color)

ytd_perc_col = all_dfs[0].columns.get_loc('YTD_%_Achieved')
month_perc_col = all_dfs[0].columns.get_loc('Month_%_Achieved')

branches_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,2, 'ZONES', delft_blue_fill_format)
branches_worksheet.merge_range(fin_rows[0]-1,3,fin_rows[0]-1,zone_table.shape[1]-11, 'MOM LOAN DISBURSEMENTS', delft_blue_fill_format)
branches_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,2, 'BRANCHES', delft_blue_fill_format)
branches_worksheet.merge_range(fin_rows[1]-1,3,fin_rows[1]-1,zone_table.shape[1]-11, 'MOM LOAN DISBURSEMENTS', delft_blue_fill_format)

branches_worksheet.merge_range("A1:B1", "", menu_button_format)
branches_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

branches_worksheet.set_column(0,0,10.00, center_format)
branches_worksheet.set_column(1,1,32.00)
branches_worksheet.set_column(2,2,10.00)
branches_worksheet.set_column(3,zone_table.shape[1]-8,13.00, million_format)
branches_worksheet.set_column(ytd_perc_col,ytd_perc_col,13.55, percent_format)
branches_worksheet.set_column(zone_table.shape[1]-6,zone_table.shape[1]-4,13.20, million_format)
branches_worksheet.set_column(month_perc_col,month_perc_col,15.82, percent_format)
branches_worksheet.set_column(zone_table.shape[1]-2,zone_table.shape[1]-1,13.00, million_format)
           
branches_worksheet.set_column(0,0,10.00, center_format)
branches_worksheet.set_column(1,1,32.00)
branches_worksheet.set_column(2,2,10.00)
branches_worksheet.set_column(3,branch_table.shape[1]-8,13.00, million_format)
branches_worksheet.set_column(ytd_perc_col,ytd_perc_col,13.55, percent_format)
branches_worksheet.set_column(branch_table.shape[1]-6,branch_table.shape[1]-4,13.20, million_format)
branches_worksheet.set_column(month_perc_col,month_perc_col,15.82, percent_format)
branches_worksheet.set_column(branch_table.shape[1]-2,branch_table.shape[1]-1,13.00, million_format)

      
for row, df in zip(fin_rows, all_dfs):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1
    
    branches_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
    branches_worksheet.conditional_format(row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    branches_worksheet.conditional_format(row+1, start_col, end_row, 2, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    branches_worksheet.conditional_format(row+1, end_col-5, end_row, end_col-3, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    branches_worksheet.conditional_format(row+1, end_col-9, end_row, end_col-7, {'type': 'no_errors', 'format': gold_fill_format})
    branches_worksheet.conditional_format(row+1, end_col-1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})
    branches_worksheet.conditional_format(end_row, 3, end_row, end_col-10, {'type': 'no_errors', 'format': bold_format})
    
    branches_worksheet.conditional_format(row+1, ytd_perc_col, end_row, ytd_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    branches_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 1,'format': green_format})
    branches_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 0.8,'format': amber_format})
    branches_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '<=','value': 0.8,'format': red_format})

branches_worksheet.freeze_panes(5,3)
# branches_worksheet.hide()
print(f"Sheet '{branches_sheet_name}' is successfully saved.")


# Branches - Retail & Commercial Worksheet
# Zone Table (Retail & Commercial)

# Create a mapping for retail and commercial
def is_retail(x):
    if x in ('BUSINESS', 'DIASPORA', 'IB', 'PERSONAL', 'PF', 'ULTIMATE', 'VIRTUAL'):
        return 'RETAIL'
    elif x in ('COMMERCIAL'):
        return 'COMMERCIAL'

loan_drawdown['RETAIL_CHECK'] = loan_drawdown['BANKING_SEGMENT'].apply(is_retail)
# loan_drawdown.head(2)


# Zone Total Disbursement View
zone_total_table  = zone_table.copy()
zone_total_table.drop(columns = 'Rank', inplace = True)
# zone_total_table

# Create rank on YTD Values
zone_total_table['Rank'] = None

zone_total_table.iloc[:-1, zone_total_table.columns.get_loc('Rank')] = zone_total_table.iloc[:-1]['YTD_%_Achieved'].rank(method='dense', ascending = False)

cols_to_front = ['Rank']
remaining_cols = [col for col in zone_total_table.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols

zone_total_table = zone_total_table[new_order]
zone_total_table = zone_total_table.sort_values(by = 'Rank')
# zone_total_table


# Zone Commercial Disbursement View
# Commercial zone monthly drawdown
commercial_zone_drawdown = loan_drawdown.loc[loan_drawdown['RETAIL_CHECK'] == 'COMMERCIAL']

amount_column = ['NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['RETAIL_CHECK']
detail_column = ['NAME', 'ROLE']
if commercial_zone_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'COMMERCIAL'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        commercial_zone_drawdown = pd.concat([commercial_zone_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')

zone_commercial_table = sum_monthly(commercial_zone_drawdown, index = 'ZONE', months_column_name = ['MONTH_YR'], value_column_name = 'NET_DRAWDOWN')
zone_commercial_table = zone_commercial_table[~zone_commercial_table['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
sum_row = zone_commercial_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
zone_commercial_table = pd.concat([zone_commercial_table, sum_row], ignore_index = True)
zone_commercial_table['YTD_Actual'] = zone_commercial_table[month_column_order].sum(axis=1)
# zone_commercial_table


# Commercial zone weekly drawdown
weekly_zone_commercial_drawdown = commercial_zone_drawdown.loc[commercial_zone_drawdown['WEEK'] == week_number]
weekly_zone_commercail_view = sum(weekly_zone_commercial_drawdown, index = 'ZONE', value_column_name = 'NET_DRAWDOWN')
weekly_zone_commercail_view = weekly_zone_commercail_view[~weekly_zone_commercail_view['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
weekly_zone_commercail_view.rename(columns = {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = weekly_zone_commercail_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
weekly_zone_commercail_view = pd.concat([weekly_zone_commercail_view, sum_row], ignore_index = True)
# Check if df is empty
if weekly_zone_commercail_view.shape[0] == 1:
    data = {
        'ZONE':['Zone A', 'Zone B', 'Zone C', 'TOTAL'],
        'Weekly':[0,0,0,0]
    }
    weekly_zone_commercail_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# weekly_zone_commercail_view


# Commercial zone daily drawdown
daily_zone_commercial_drawdown = commercial_zone_drawdown.loc[commercial_zone_drawdown['DRAWDOWN_DT'] == max_date]
daily_zone_commercial_view = sum(daily_zone_commercial_drawdown, index = 'ZONE', value_column_name = 'NET_DRAWDOWN')
daily_zone_commercial_view = daily_zone_commercial_view[~daily_zone_commercial_view['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
daily_zone_commercial_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = daily_zone_commercial_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
daily_zone_commercial_view = pd.concat([daily_zone_commercial_view, sum_row], ignore_index = True)
# Check if df is empty
if daily_zone_commercial_view.shape[0] == 1:
    data = {
        'ZONE':['Zone A', 'Zone B', 'Zone C', 'TOTAL'],
        'Daily':[0,0,0,0]
    }
    daily_zone_commercial_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# daily_zone_commercial_view

# merge commercial zone tables
zone_commercial_table = pd.merge(zone_map, zone_commercial_table, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_commercial_table = zone_commercial_table.fillna(0)
zone_commercial_table = pd.merge(zone_commercial_table, zone_target_loan_disbursement_table, left_on = 'ZONE', right_on = 'staff_zone', how = 'left')
zone_commercial_table.drop(columns = ['staff_zone', 'Total_FY_Target', 'Retail_FY_Target'], inplace = True)
# zone_commercial_table


# zone commercial achievement
zone_commercial_table['YTD_Target'] = zone_commercial_table['Commercial_FY_Target'] * year_fraction
zone_commercial_table['YTD_%_Achieved'] = zone_commercial_table.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
zone_commercial_table['Monthly_Target'] = zone_commercial_table['Commercial_FY_Target'] / 12
zone_commercial_table['Month_Actual'] =  zone_commercial_table[[(max_month_name)]]
zone_commercial_table['Month_Deficit'] = zone_commercial_table['Month_Actual'] - zone_commercial_table['Monthly_Target']
zone_commercial_table['Month_%_Achieved'] = zone_commercial_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
# zone_commercial_table


# add weekly and daily tables
zone_commercial_table = pd.merge(zone_commercial_table,weekly_zone_commercail_view, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_commercial_table = pd.merge(zone_commercial_table,daily_zone_commercial_view, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_commercial_table = zone_commercial_table.fillna(0)
# zone_commercial_table

# merge the zone_commercial with the zone_total to get the order in terms of rank
zone_commercial_table = pd.merge(zone_commercial_table, zone_total_table[['Rank','BRANCH']], left_on = 'BRANCH', right_on = 'BRANCH', how = 'left')
zone_commercial_table = zone_commercial_table.sort_values(by = 'Rank')
# zone_commercial_table.head()                                   


# Zone Retail Disbursement View
# retail zone monthly drawdown
retail_zone_drawdown = loan_drawdown.loc[loan_drawdown['RETAIL_CHECK'] == 'RETAIL']

amount_column = ['NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['RETAIL_CHECK']
detail_column = ['NAME', 'ROLE']
if retail_zone_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'RETAIL'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        retail_zone_drawdown = pd.concat([retail_zone_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')

zone_retail_table = sum_monthly(retail_zone_drawdown, index = 'ZONE', months_column_name = ['MONTH_YR'], value_column_name = 'NET_DRAWDOWN')
zone_retail_table = zone_retail_table[~zone_retail_table['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
sum_row = zone_retail_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
zone_retail_table = pd.concat([zone_retail_table, sum_row], ignore_index = True)
zone_retail_table['YTD_Actual'] = zone_retail_table[month_column_order].sum(axis=1)
# zone_retail_table


# retail zone weekly drawdown
weekly_zone_retail_drawdown = retail_zone_drawdown.loc[retail_zone_drawdown['WEEK'] == week_number]
weekly_zone_retail_view = sum(weekly_zone_retail_drawdown, index='ZONE', value_column_name='NET_DRAWDOWN')
weekly_zone_retail_view = weekly_zone_retail_view[~weekly_zone_retail_view['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
weekly_zone_retail_view.rename(columns = {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = weekly_zone_retail_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
weekly_zone_retail_view = pd.concat([weekly_zone_retail_view, sum_row], ignore_index = True)
# Check if df is empty
if weekly_zone_retail_view.shape[0] == 1:
    data = {
        'ZONE':['Zone A', 'Zone B', 'Zone C', 'TOTAL'],
        'Weekly':[0,0,0,0]
    }
    weekly_zone_retail_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# weekly_zone_retail_view

# retail zone daily drawdown
daily_zone_retail_drawdown = retail_zone_drawdown.loc[retail_zone_drawdown['DRAWDOWN_DT'] == max_date]
daily_zone_retail_view = sum(daily_zone_retail_drawdown, index='ZONE', value_column_name='NET_DRAWDOWN')
daily_zone_retail_view = daily_zone_retail_view[~daily_zone_retail_view['ZONE'].str.contains('HEAD OFFICE', case=False, na=False)]
daily_zone_retail_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = daily_zone_retail_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ZONE', 'TOTAL')   
daily_zone_retail_view = pd.concat([daily_zone_retail_view, sum_row], ignore_index = True)
# Check if df is empty
if daily_zone_retail_view.shape[0] == 1:
    data = {
        'ZONE':['Zone A', 'Zone B', 'Zone C', 'TOTAL'],
        'Daily':[0,0,0,0]
    }
    daily_zone_retail_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# daily_zone_retail_view

# merge zone retail tables
zone_retail_table = pd.merge(zone_map, zone_retail_table, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_retail_table = zone_retail_table.fillna(0)
zone_retail_table = pd.merge(zone_retail_table, zone_target_loan_disbursement_table, left_on = 'ZONE', right_on = 'staff_zone', how = 'left')
zone_retail_table.drop(columns = ['staff_zone', 'Total_FY_Target', 'Commercial_FY_Target'], inplace = True)
# zone_retail_table


# zone retail achievements
zone_retail_table['YTD_Target'] = zone_retail_table['Retail_FY_Target'] * year_fraction
zone_retail_table['YTD_%_Achieved'] = zone_retail_table.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
zone_retail_table['Monthly_Target'] = zone_retail_table['Retail_FY_Target'] / 12
zone_retail_table['Month_Actual'] =  zone_retail_table[[(max_month_name)]]
zone_retail_table['Month_Deficit'] = zone_retail_table['Month_Actual'] - zone_retail_table['Monthly_Target']
zone_retail_table['Month_%_Achieved'] = zone_retail_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
# zone_retail_table


# add weekly and daily tables
zone_retail_table = pd.merge(zone_retail_table,weekly_zone_retail_view, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_retail_table = pd.merge(zone_retail_table,daily_zone_retail_view, left_on = 'ZONE', right_on = 'ZONE', how = 'left')
zone_retail_table = zone_retail_table.fillna(0)
# zone_retail_table

# merge the zone_retail with the zone_total to get the order in terms of rank
zone_retail_table = pd.merge(zone_retail_table, zone_total_table[['Rank','BRANCH']], left_on = 'BRANCH', right_on = 'BRANCH', how = 'left')
zone_retail_table = zone_retail_table.sort_values(by = 'Rank')
# zone_retail_table.head()                                   


# Drop column that are not needed for display
zone_total_final_table = zone_total_table.copy()
columns_to_drop = month_column_order + ['GROSS', 'NET']
zone_total_final_table = zone_total_final_table.drop(columns = columns_to_drop)
# zone_total_final_table


zone_commercial_final_table = zone_commercial_table.copy()
# Drop columns not needed
columns_to_drop = ['BRANCH', 'ZONE', 'Rank'] + month_column_order 
zone_commercial_final_table = zone_commercial_final_table.drop(columns = columns_to_drop)
# Order remaining columns
specified_order = ['Commercial_FY_Target', 'YTD_Target', 'YTD_Actual','YTD_%_Achieved',
                   'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved','Weekly','Daily']
remaining_columns = [col for col in zone_commercial_final_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
zone_commercial_final_table = zone_commercial_final_table.reindex(columns = new_order)
# zone_commercial_final_table


zone_retail_final_table = zone_retail_table.copy()
# Drop columns not needed
columns_to_drop = ['BRANCH', 'ZONE', 'Rank'] + month_column_order 
zone_retail_final_table = zone_retail_table.drop(columns = columns_to_drop)
# Order remaining columns
specified_order = ['Retail_FY_Target', 'YTD_Target', 'YTD_Actual','YTD_%_Achieved',
                   'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved','Weekly','Daily']
remaining_columns = [col for col in zone_retail_final_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
zone_retail_final_table = zone_retail_final_table.reindex(columns = new_order)
# zone_retail_final_table


# Branch Table (Retail & Commercial)
# Branch Total Disbursment View
branch_total_table = branch_table.copy()
branch_total_table.drop(columns = 'Rank', inplace = True)
# branch_total_table.head(2)


# Create rank wiht the YTD values
branch_total_table['Rank'] = None

branch_total_table.iloc[:-1, branch_total_table.columns.get_loc('Rank')] = branch_total_table.iloc[:-1]['YTD_%_Achieved'].rank(method='dense', ascending = False)

cols_to_front = ['Rank']
remaining_cols = [col for col in branch_total_table.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols

branch_total_table = branch_total_table[new_order]
branch_total_table = branch_total_table.sort_values(by = 'Rank')
# branch_total_table.head(2)


# Branch code list for error handling
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

branch_code_list = '''
select * from branch_final_employee_dmc_data

'''
branch_code_list = pd.read_sql_query(branch_code_list , conn)

conn.close()

branch_code_list = branch_code_list[['brn_code']]
branch_code_list = branch_code_list[branch_code_list['brn_code'] != 100]
branch_code_list.rename(columns = {'brn_code':'UNIT_CODE'}, inplace =True)
sum_row = branch_code_list.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
branch_code_list = pd.concat([branch_code_list, sum_row], ignore_index = True)
print(branch_code_list['UNIT_CODE'].nunique())
print(branch_code_list['UNIT_CODE'].unique())


# Branch Commercial Disbursement View
# commercial branch monthly
commercial_branch_drawdown = loan_drawdown.loc[loan_drawdown['RETAIL_CHECK'] == 'COMMERCIAL']

amount_column = ['NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['RETAIL_CHECK']
detail_column = ['NAME', 'ROLE']
if commercial_branch_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'COMMERCIAL'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        commercial_branch_drawdown = pd.concat([commercial_branch_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')

branch_commercial_table = sum_monthly(commercial_branch_drawdown, index = 'UNIT_CODE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
branch_commercial_table = branch_commercial_table[branch_commercial_table['UNIT_CODE'] != 100]
sum_row = branch_commercial_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
branch_commercial_table = pd.concat([branch_commercial_table, sum_row], ignore_index = True)
# Check if df is empty
if branch_commercial_table.shape[0] == 1:
    data = branch_code_list.copy()
    data[month_column_order] = 0
    branch_commercial_table = data.copy()
else:
    print('DataFrame is not empty')
branch_commercial_table['YTD_Actual'] = branch_commercial_table[month_column_order].sum(axis=1)
# branch_commercial_table.tail(2)


# commercial branch weekly
weekly_branch_commercial_drawdown = commercial_branch_drawdown.loc[commercial_branch_drawdown['WEEK'] == week_number]
weekly_branch_commercail_view = sum(weekly_branch_commercial_drawdown, index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
weekly_branch_commercail_view = weekly_branch_commercail_view[weekly_branch_commercail_view['UNIT_CODE'] != 100]
weekly_branch_commercail_view.rename(columns =  {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = weekly_branch_commercail_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
weekly_branch_commercail_view = pd.concat([weekly_branch_commercail_view, sum_row], ignore_index = True)
# Check if df is empty
if weekly_branch_commercail_view.shape[0] == 1:
    data = branch_code_list.copy()
    data['Weekly'] = 0
    weekly_branch_commercail_view = data.copy()
else:
    print('DataFrame is not empty')
# weekly_branch_commercail_view.tail(2)


# Commercial branch daily
daily_branch_commercial_drawdown = commercial_branch_drawdown.loc[commercial_branch_drawdown['DRAWDOWN_DT'] == max_date]
daily_branch_commercial_view = sum(daily_branch_commercial_drawdown, index='UNIT_CODE', value_column_name='NET_DRAWDOWN')
daily_branch_commercial_view = daily_branch_commercial_view[daily_branch_commercial_view['UNIT_CODE'] != 100]
daily_branch_commercial_view.rename(columns =  {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = daily_branch_commercial_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
daily_branch_commercial_view = pd.concat([daily_branch_commercial_view, sum_row], ignore_index = True)
# Check if df is empty
if daily_branch_commercial_view.shape[0] == 1:
    data = branch_code_list.copy()
    data['Daily'] = 0
    daily_branch_commercial_view = data.copy()
else:
    print('DataFrame is not empty')
# daily_branch_commercial_view.tail(2)

# Merge commercial branch tables
branch_commercial_table = pd.merge(branch_view_map, branch_commercial_table, left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_commercial_table = pd.merge(branch_commercial_table, weekly_branch_commercail_view, left_on = 'UNIT_CODE', right_on = 'UNIT_CODE', how = 'left')
branch_commercial_table = pd.merge(branch_commercial_table, daily_branch_commercial_view, left_on = 'UNIT_CODE', right_on = 'UNIT_CODE', how = 'left')
branch_commercial_table = pd.merge(branch_commercial_table, branch_target_loan_disbursement_table, left_on = 'UNIT_CODE', right_on = 'brn_code', how = 'left')
branch_commercial_table.drop(columns = ['CODE', 'UNIT_CODE','brn_code', 'Total_FY_Target', 'Retail_FY_Target'], inplace = True)
branch_commercial_table = branch_commercial_table.fillna(0)
# branch_commercial_table.head(2)

# Commercial branch achievements
branch_commercial_table['YTD_Target'] = branch_commercial_table['Commercial_FY_Target'] * year_fraction
branch_commercial_table['YTD_%_Achieved'] = branch_commercial_table.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
branch_commercial_table['Monthly_Target'] = branch_commercial_table['Commercial_FY_Target'] / 12
branch_commercial_table['Month_Actual'] =  branch_commercial_table[[(max_month_name)]]
branch_commercial_table['Month_Deficit'] = branch_commercial_table['Month_Actual'] - branch_commercial_table['Monthly_Target']
branch_commercial_table['Month_%_Achieved'] = branch_commercial_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
# branch_commercial_table.head(2)

cols_to_back = ['Weekly', 'Daily']
remaining_cols = [col for col in branch_commercial_table.columns if col not in cols_to_back]
new_order_2 = remaining_cols + cols_to_back
branch_commercial_table = branch_commercial_table[new_order_2]
# branch_commercial_table.head(2)

# merge the branch_commercial with the branch_total to get the order in terms of rank
branch_commercial_table = pd.merge(branch_commercial_table, branch_total_table[['Rank','BRANCH']], left_on = 'BRANCH', right_on = 'BRANCH', how = 'left')
branch_commercial_table = branch_commercial_table.sort_values(by = 'Rank')
# branch_commercial_table.head(2)                                   



# Branch Retail Disbursement View
# Retail branch monthly
retail_branch_drawdown = loan_drawdown.loc[loan_drawdown['RETAIL_CHECK'] == 'RETAIL']

amount_column = ['NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['RETAIL_CHECK']
detail_column = ['NAME', 'ROLE']
if retail_branch_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'RETAIL'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        retail_branch_drawdown = pd.concat([retail_branch_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')
    
branch_retail_table = sum_monthly(retail_branch_drawdown, index = 'UNIT_CODE', months_column_name = ['MONTH_YR'], value_column_name = 'NET_DRAWDOWN')
branch_retail_table = branch_retail_table[branch_retail_table['UNIT_CODE'] != 100]
sum_row = branch_retail_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
branch_retail_table = pd.concat([branch_retail_table, sum_row], ignore_index = True)
# Check if df is empty
if branch_retail_table.shape[0] == 1:
    data = branch_code_list.copy()
    data[month_column_order] = 0
    branch_retail_table = data.copy()
else:
    print('DataFrame is not empty')
branch_retail_table['YTD_Actual'] = branch_retail_table[month_column_order].sum(axis=1)
# branch_retail_table.tail(2)

# Retail branch weekly
weekly_branch_retail_drawdown = retail_branch_drawdown.loc[retail_branch_drawdown['WEEK'] == week_number]
weekly_branch_retail_view = sum(weekly_branch_retail_drawdown, index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
weekly_branch_retail_view = weekly_branch_retail_view[weekly_branch_retail_view['UNIT_CODE'] != 100]
weekly_branch_retail_view.rename(columns =  {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = weekly_branch_retail_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
weekly_branch_retail_view = pd.concat([weekly_branch_retail_view, sum_row], ignore_index = True)
# Check if df is empty
if weekly_branch_retail_view.shape[0] == 1:
    data = branch_code_list.copy()
    data['Weekly'] = 0
    weekly_branch_retail_view = data.copy()
else:
    print('DataFrame is not empty')
weekly_branch_retail_view.tail(2)
# weekly_branch_retail_view.tail(2)

# Retail branch daily
daily_branch_retail_drawdown = retail_branch_drawdown.loc[retail_branch_drawdown['DRAWDOWN_DT'] == max_date]
daily_branch_retail_view = sum(daily_branch_retail_drawdown, index = 'UNIT_CODE', value_column_name = 'NET_DRAWDOWN')
daily_branch_retail_view = daily_branch_retail_view[daily_branch_retail_view['UNIT_CODE'] != 100]
daily_branch_retail_view.rename(columns =  {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = daily_branch_retail_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'UNIT_CODE', 'TOTAL')   
daily_branch_retail_view = pd.concat([daily_branch_retail_view, sum_row], ignore_index = True)
# Check if df is empty
if daily_branch_retail_view.shape[0] == 1:
    data = branch_code_list.copy()
    data['Daily'] = 0
    daily_branch_retail_view = data.copy()
else:
    print('DataFrame is not empty')
daily_branch_retail_view.tail(2)
# daily_branch_retail_view.tail(2)

# Merge retail branch tables
branch_retail_table = pd.merge(branch_view_map, branch_retail_table, left_on = 'CODE', right_on = 'UNIT_CODE', how = 'left')
branch_retail_table = pd.merge(branch_retail_table, weekly_branch_retail_view, left_on = 'UNIT_CODE', right_on = 'UNIT_CODE', how = 'left')
branch_retail_table = pd.merge(branch_retail_table, daily_branch_retail_view, left_on = 'UNIT_CODE', right_on = 'UNIT_CODE', how = 'left')
branch_retail_table = pd.merge(branch_retail_table, branch_target_loan_disbursement_table, left_on = 'UNIT_CODE', right_on = 'brn_code', how = 'left')
branch_retail_table.drop(columns = ['CODE','UNIT_CODE','brn_code', 'Total_FY_Target', 'Commercial_FY_Target'], inplace = True)
branch_retail_table = branch_retail_table.fillna(0)
# branch_retail_table.head(2)

# retail branch achievements
branch_retail_table['YTD_Target'] = branch_retail_table['Retail_FY_Target'] * year_fraction
branch_retail_table['YTD_%_Achieved'] = branch_retail_table.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
branch_retail_table['Monthly_Target'] = branch_retail_table['Retail_FY_Target'] / 12
branch_retail_table['Month_Actual'] =  branch_retail_table[[(max_month_name)]]
branch_retail_table['Month_Deficit'] = branch_retail_table['Month_Actual'] - branch_retail_table['Monthly_Target']
branch_retail_table['Month_%_Achieved'] = branch_retail_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
# branch_retail_table.head(2)

cols_to_back = ['Weekly', 'Daily']
remaining_cols = [col for col in branch_retail_table.columns if col not in cols_to_back]
new_order_2 = remaining_cols + cols_to_back
branch_retail_table = branch_retail_table[new_order_2]
# branch_retail_table.head(2)

# merge the branch_retail with the branch_total to get the order in terms of rank
branch_retail_table = pd.merge(branch_retail_table, branch_total_table[['Rank','BRANCH']], left_on = 'BRANCH', right_on = 'BRANCH', how = 'left')
branch_retail_table = branch_retail_table.sort_values(by = 'Rank')
# branch_retail_table.head(2)                                   


# Drop column that are not needed for display
branch_total_final_table = branch_total_table.copy()
columns_to_drop = month_column_order + ['GROSS', 'NET']
branch_total_final_table = branch_total_final_table.drop(columns = columns_to_drop)
# branch_total_final_table.head(2)


branch_commercial_final_table = branch_commercial_table.copy()
# Drop columns not needed
columns_to_drop = ['BRANCH', 'ZONE', 'Rank'] + month_column_order 
branch_commercial_final_table = branch_commercial_table.drop(columns = columns_to_drop)
# Order remaining columns
specified_order = ['Commercial_FY_Target', 'YTD_Target', 'YTD_Actual','YTD_%_Achieved',
                   'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved','Weekly','Daily']
remaining_columns = [col for col in branch_commercial_final_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
branch_commercial_final_table = branch_commercial_final_table.reindex(columns = new_order)
# branch_commercial_final_table.head(2)


branch_retail_final_table = branch_retail_table.copy()
# Drop columns not needed
columns_to_drop = ['BRANCH', 'ZONE', 'Rank'] + month_column_order 
branch_retail_final_table = branch_retail_table.drop(columns = columns_to_drop)
# Order remaining columns
specified_order = ['Retail_FY_Target', 'YTD_Target', 'YTD_Actual','YTD_%_Achieved',
                   'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved','Weekly','Daily']
remaining_columns = [col for col in branch_retail_final_table.columns if col not in specified_order]
new_order = remaining_columns + specified_order
branch_retail_final_table = branch_retail_final_table.reindex(columns = new_order)
# branch_retail_final_table.head(2)


# Write tables to excel
# Function to calculate starting rows
def calculate_start_rows(dfs):
    rows = np.cumsum([df.shape[0] + 4 for df in dfs])
    return [4] + [data + 4 for data in rows[:-1]]

# Writing Total DataFrames to Excel
total_dfs = [zone_total_final_table, branch_total_final_table]
total_start_rows = calculate_start_rows(total_dfs)
startcol = 0

for i, df in enumerate(total_dfs):
    df.to_excel(daily_drawdown_report_writer, sheet_name = branches_retail_and_commercial_sheet_name, index = False, startrow = total_start_rows[i], startcol = startcol)

ytd_total_perc_col = total_dfs[0].columns.get_loc('YTD_%_Achieved')
month_total_perc_col = total_dfs[0].columns.get_loc('Month_%_Achieved')

# Writing Retail DataFrames to Excel
retail_dfs = [zone_retail_final_table, branch_retail_final_table]
retail_start_rows = calculate_start_rows(retail_dfs)
retail_start_cols = [total_dfs[i].shape[1] + 2 for i in range(len(retail_dfs))]

for i, (df, col) in enumerate(zip(retail_dfs, retail_start_cols)):
    df.to_excel(daily_drawdown_report_writer, sheet_name = branches_retail_and_commercial_sheet_name, index = False, startrow = retail_start_rows[i], startcol = retail_start_cols[i])

ytd_retail_perc_col = retail_dfs[0].columns.get_loc('YTD_%_Achieved')
month_retail_perc_col = retail_dfs[0].columns.get_loc('Month_%_Achieved')

# Writing Commercial DataFrames to Excel
commercial_dfs = [zone_commercial_final_table, branch_commercial_final_table]
commercial_start_rows = calculate_start_rows(commercial_dfs)
commercial_start_cols = [total_dfs[i].shape[1] + retail_dfs[i].shape[1] + 4 for i in range(len(commercial_dfs))]

for i, (df, col) in enumerate(zip(commercial_dfs, commercial_start_cols)):
    df.to_excel(daily_drawdown_report_writer, sheet_name = branches_retail_and_commercial_sheet_name, index = False, startrow = commercial_start_rows[i], startcol = commercial_start_cols[i])

ytd_commercial_perc_col = commercial_dfs[0].columns.get_loc('YTD_%_Achieved')
month_commercial_perc_col = commercial_dfs[0].columns.get_loc('Month_%_Achieved')

# Applying formatting
branches_retail_and_commercial_worksheet = daily_drawdown_report_writer.sheets[branches_retail_and_commercial_sheet_name]
branches_retail_and_commercial_worksheet.set_zoom(80)
branches_retail_and_commercial_worksheet.set_tab_color(sheet_tab_color)

## Total tables formatting
branches_retail_and_commercial_worksheet.merge_range(3, 0, 3, 2, 'ZONES', delft_blue_fill_format)
branches_retail_and_commercial_worksheet.merge_range(3, 3, 3, total_dfs[0].shape[1]-1, 'TOTAL DISBURSEMENTS', delft_blue_fill_format)
branches_retail_and_commercial_worksheet.merge_range(total_start_rows[1]-1, 0, total_start_rows[1]-1, 2, 'BRANCHES', delft_blue_fill_format)
branches_retail_and_commercial_worksheet.merge_range(total_start_rows[1]-1, 3, total_start_rows[1]-1, total_dfs[1].shape[1]-1, 'TOTAL DISBURSEMENTS', delft_blue_fill_format)

# Set column widths and formats for total tables
total_start_cols = [0]
for start_col, df in zip(total_start_cols, total_dfs):
    end_col = start_col + df.shape[1] - 1
    branches_retail_and_commercial_worksheet.set_column(start_col, start_col, 10.00, center_format)
    branches_retail_and_commercial_worksheet.set_column(start_col+1, start_col+1, 32.00)
    branches_retail_and_commercial_worksheet.set_column(start_col+2, end_col, 10.00)    
    branches_retail_and_commercial_worksheet.set_column(start_col + 3, start_col + 5, 13.20, million_format)
    branches_retail_and_commercial_worksheet.set_column(start_col + 6, start_col + 6, 14.20, percent_format)
    branches_retail_and_commercial_worksheet.set_column(start_col + 7, start_col + 9, 13.90, million_format)
    branches_retail_and_commercial_worksheet.set_column(end_col - 2, end_col - 2, 16.73, percent_format)
    branches_retail_and_commercial_worksheet.set_column(end_col - 1, end_col, 13.00, million_format)
    
        
for start_row, df in zip(total_start_rows, total_dfs):
    end_row = df.shape[0] + start_row
    end_col = df.shape[1] - 1    
    branches_retail_and_commercial_worksheet.conditional_format(start_row, startcol, start_row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row, startcol, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, startcol, end_row, 2, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, end_col-5, end_row, end_col-3, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, end_col-9, end_row, end_col-7, {'type': 'no_errors', 'format': white_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, end_col-1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})
    # branches_retail_and_commercial_worksheet.conditional_format(end_row, 2, end_row, end_col-8, {'type': 'no_errors', 'format': bold_format})
    
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, ytd_total_perc_col, end_row, ytd_total_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, month_total_perc_col, end_row, month_total_perc_col, {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, month_total_perc_col, end_row, month_total_perc_col, {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, month_total_perc_col, end_row, month_total_perc_col, {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format})

## Retail tables formatting
branches_retail_and_commercial_worksheet.merge_range(3, retail_start_cols[0], 3, retail_start_cols[0] + retail_dfs[0].shape[1]-1, 'RETAIL DISBURSEMENTS', delft_blue_fill_format)
branches_retail_and_commercial_worksheet.merge_range(retail_start_rows[1]-1, retail_start_cols[1], retail_start_rows[1]-1, retail_start_cols[1] + retail_dfs[1].shape[1]-1, 'RETAIL DISBURSEMENTS', delft_blue_fill_format)

# Set column widths and formats for retail tables
for start_col, df in zip(retail_start_cols, retail_dfs):
    end_col = start_col + df.shape[1] - 1

    branches_retail_and_commercial_worksheet.set_column(start_col, start_col + 2, 13.55, million_format)
    branches_retail_and_commercial_worksheet.set_column(start_col + 3, start_col + 3, 14.20, percent_format)
    branches_retail_and_commercial_worksheet.set_column(start_col + 4, start_col + 6, 13.90, million_format)
    branches_retail_and_commercial_worksheet.set_column(end_col - 2, end_col - 2, 16.73, percent_format)
    branches_retail_and_commercial_worksheet.set_column(end_col - 1, end_col, 13.00, million_format)
    
# Iterate over retail_dfs and retail_start_cols directly
for start_row, df, start_col in zip(retail_start_rows, retail_dfs, retail_start_cols):
    end_row = df.shape[0] + start_row
    end_col = start_col + df.shape[1] - 1

    branches_retail_and_commercial_worksheet.conditional_format(start_row, startcol, start_row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row + 1, start_col, end_row, start_col + 2, {'type': 'no_errors', 'format': white_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row + 1, start_col + 4, end_row, start_col + 6, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row + 1, end_col - 1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})
    
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + ytd_retail_perc_col, end_row, start_col + ytd_retail_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + month_retail_perc_col, end_row, start_col + month_retail_perc_col, {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + month_retail_perc_col, end_row, start_col + month_retail_perc_col, {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + month_retail_perc_col, end_row, start_col + month_retail_perc_col, {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format})

## Commercial tables formatting
branches_retail_and_commercial_worksheet.merge_range(3, commercial_start_cols[0], 3, commercial_start_cols[0] + commercial_dfs[0].shape[1]-1, 'COMMERCIAL DISBURSEMENTS', delft_blue_fill_format)
branches_retail_and_commercial_worksheet.merge_range(commercial_start_rows[1]-1, commercial_start_cols[1], commercial_start_rows[1]-1, commercial_start_cols[1] + commercial_dfs[1].shape[1]-1, 'COMMERCIAL DISBURSEMENTS', delft_blue_fill_format)

# Set column widths and formats for commercial tables
for start_col, df in zip(commercial_start_cols, commercial_dfs):
    end_col = start_col + df.shape[1] - 1
    
    branches_retail_and_commercial_worksheet.set_column(start_col, start_col + 2, 19.18, million_format)
    branches_retail_and_commercial_worksheet.set_column(start_col + 3, start_col + 3, 14.20, percent_format)
    branches_retail_and_commercial_worksheet.set_column(start_col + 4, start_col + 6, 13.90, million_format)
    branches_retail_and_commercial_worksheet.set_column(end_col - 2, end_col - 2, 16.73, percent_format)
    branches_retail_and_commercial_worksheet.set_column(end_col - 1, end_col, 13.00, million_format)
    
# Iterate over commercial_dfs and commercial_start_cols directly
for start_row, df, start_col in zip(commercial_start_rows, commercial_dfs, commercial_start_cols):
    end_row = df.shape[0] + start_row
    end_col = start_col + df.shape[1] - 1

    branches_retail_and_commercial_worksheet.conditional_format(start_row, startcol, start_row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row + 1, start_col, end_row, start_col + 2, {'type': 'no_errors', 'format': white_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row + 1, start_col + 4, end_row, start_col + 6, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row + 1, end_col - 1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})
    
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + ytd_commercial_perc_col, end_row, start_col + ytd_commercial_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + month_commercial_perc_col, end_row, start_col + month_commercial_perc_col, {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + month_commercial_perc_col, end_row, start_col + month_commercial_perc_col, {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format})
    branches_retail_and_commercial_worksheet.conditional_format(start_row+1, start_col + month_commercial_perc_col, end_row, start_col + month_commercial_perc_col, {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format})

        
branches_retail_and_commercial_worksheet.set_column(13, 14, 0)
branches_retail_and_commercial_worksheet.set_column(25, 26, 0)

branches_retail_and_commercial_worksheet.freeze_panes(5,3)
branches_retail_and_commercial_worksheet.hide()
print(f"Sheet '{branches_retail_and_commercial_sheet_name}' is successfully saved.")



# Segments worksheet
banking_segment_order = ['BUSINESS', 'COMMERCIAL', 'DIASPORA', 'PERSONAL', 'ULTIMATE']

# Gross Values
segment_gross_value_table = sum_monthly(loan_drawdown, months_column_name = 'MONTH_YR', index = 'BANKING_SEGMENT', value_column_name = 'GROSS_DRAWDOWN')
segment_gross_value_table = segment_gross_value_table[(segment_gross_value_table['BANKING_SEGMENT'].isin(banking_segment_order))]
# Calculate the sum of the columns and create a new row
sum_row = segment_gross_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'BANKING_SEGMENT', 'BANK')   
# Append the total row to the DataFrame
segment_gross_value_table = pd.concat([segment_gross_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
segment_gross_value_table['YTD_Actual'] = segment_gross_value_table[month_column_order].sum(axis=1)
# segment_gross_value_table
print(segment_gross_value_table.shape)


# Net Values
segment_net_value_table = sum_monthly(loan_drawdown, months_column_name = 'MONTH_YR', index = 'BANKING_SEGMENT', value_column_name = 'NET_DRAWDOWN')
segment_net_value_table = segment_net_value_table[(segment_net_value_table['BANKING_SEGMENT'].isin(banking_segment_order))]
# Calculate the sum of the columns and create a new row
sum_row = segment_net_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'BANKING_SEGMENT', 'BANK')   
# Append the total row to the DataFrame
segment_net_value_table = pd.concat([segment_net_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
segment_net_value_table['YTD_Actual'] = segment_net_value_table[month_column_order].sum(axis=1)
# segment_net_value_table
print(segment_gross_value_table.shape)


# Weekly Segment  Values
weekly_segment_drawdown = loan_drawdown.loc[loan_drawdown['WEEK'] == week_number]
segment_weekly_view = sum(weekly_segment_drawdown, index = 'BANKING_SEGMENT', value_column_name = 'NET_DRAWDOWN')
segment_weekly_view = segment_weekly_view[(segment_weekly_view['BANKING_SEGMENT'].isin(banking_segment_order))]
segment_weekly_view.rename(columns = {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = segment_weekly_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'BANKING_SEGMENT', 'BANK')   
segment_weekly_view = pd.concat([segment_weekly_view, sum_row], ignore_index = True)
# Check if df is empty
if segment_weekly_view.shape == (1,1):
    data = {
        'BANKING_SEGMENT':['BUSINESS', 'COMMERCIAL', 'DIASPORA', 'PERSONAL', 'ULTIMATE', 'BANK'],
        'Weekly':[0,0,0,0,0,0]
    }
    segment_weekly_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
print(segment_weekly_view.shape)


# Daily Segment Values
daily_segment_drawdown = loan_drawdown.loc[loan_drawdown['DRAWDOWN_DT'] == max_date]
segment_daily_view = sum(daily_segment_drawdown, index ='BANKING_SEGMENT', value_column_name ='NET_DRAWDOWN')
segment_daily_view = segment_daily_view[(segment_daily_view['BANKING_SEGMENT'].isin(banking_segment_order))]
segment_daily_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = segment_daily_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'BANKING_SEGMENT', 'BANK')   
segment_daily_view = pd.concat([segment_daily_view, sum_row], ignore_index = True)
# Check if df is empty
if segment_daily_view.shape == (1,1):
    data = {
        'BANKING_SEGMENT':['BUSINESS', 'COMMERCIAL', 'DIASPORA', 'PERSONAL', 'ULTIMATE', 'BANK'],
        'Daily':[0,0,0,0,0,0]
    }
    segment_daily_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
print(segment_daily_view.shape)

# Merge net, weekly and daily tables
segment_net_value_table = pd.merge(segment_net_value_table,segment_weekly_view, left_on = 'BANKING_SEGMENT', right_on = 'BANKING_SEGMENT', how = 'left')
segment_net_value_table = pd.merge(segment_net_value_table,segment_daily_view, left_on = 'BANKING_SEGMENT', right_on = 'BANKING_SEGMENT', how = 'left')
segment_net_value_table = segment_net_value_table.fillna(0)
print(segment_net_value_table.shape)



# Segment Targets
# segments_targets_data = [
#     {'banking_segment':'BUSINESS', 'fy_target': 5160000000}, 
#     {'banking_segment':'COMMERCIAL', 'fy_target': 5880000000},   
#     {'banking_segment':'DIASPORA', 'fy_target': 1080000000},
#     {'banking_segment':'MORTGAGE', 'fy_target': 2400000000},   
#     {'banking_segment':'PERSONAL', 'fy_target': 4800000000},   
#     {'banking_segment':'ULTIMATE', 'fy_target': 1920000000}
# ]
# segment_targets_table = pd.DataFrame(segments_targets_data)

conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

segment_targets_table = '''
select banking_segment, fy_target
from segment_drawdown_targets

'''
segment_targets_table = pd.read_sql_query(segment_targets_table , conn)

conn.close()

# Remove mortgage targets
segment_targets_table = segment_targets_table[~segment_targets_table['banking_segment'].str.contains('MORTGAGE', case=False, na=False)]
print(segment_targets_table)
# Calculate the sum of the columns and create a new row
sum_row = segment_targets_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'banking_segment', 'BANK')   
# Append the total row to the DataFrame
segment_targets_table = pd.concat([segment_targets_table, sum_row], ignore_index = True)
segment_targets_table['Monthly_Target'] = segment_targets_table['fy_target'] / 12
segment_targets_table

# Calcuations
segment_net_value_table_refined = segment_net_value_table.copy()
segment_net_value_table_refined = segment_net_value_table_refined[['BANKING_SEGMENT', (max_month_name), 'YTD_Actual']]
segment_net_value_table_refined.rename(columns = {(max_month_name): 'Month_Actual'}, inplace=True)
# segment_net_value_table_refined

# Merge the tables
segment_targets_view = segment_targets_table.copy()
segment_targets_view = pd.merge(segment_targets_view, segment_net_value_table_refined, left_on = 'banking_segment', right_on = 'BANKING_SEGMENT', how = 'left')
segment_targets_view.drop(columns = ['BANKING_SEGMENT'], inplace = True)
segment_targets_view = segment_targets_view.fillna(0)
# segment_targets_view

# Segment Achievements
segment_targets_view['YTD_Target'] = segment_targets_view['fy_target'] * year_fraction
segment_targets_view['YTD_%_Achieved'] = segment_targets_view.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
segment_targets_view['Month_Deficit'] = segment_targets_view['Month_Actual'] - segment_targets_view['Monthly_Target']
segment_targets_view['Month_%_Achieved'] = segment_targets_view.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)

# Order columns
column_order = ['banking_segment', 'fy_target', 'YTD_Actual', 'YTD_Target','YTD_%_Achieved', 'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved']
segment_targets_view = segment_targets_view.reindex(columns = column_order)
# segment_targets_view

# Write tables to excel
all_dfs = [segment_gross_value_table,segment_net_value_table, segment_targets_view]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = segments_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

ytd_perc_col = all_dfs[2].columns.get_loc('YTD_%_Achieved')
month_perc_col = all_dfs[2].columns.get_loc('Month_%_Achieved')

segments_worksheet = daily_drawdown_report_writer.sheets[segments_sheet_name]
segments_worksheet.set_zoom(80)
segments_worksheet.set_tab_color(sheet_tab_color)

segments_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'GROSS PER SEGMENT', delft_blue_fill_format)
segments_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'NET PER SEGMENT', delft_blue_fill_format)
segments_worksheet.merge_range(fin_rows[2]-1,0,fin_rows[2]-1,1, 'SEGMENT PERFORMANCE', delft_blue_fill_format)

segments_worksheet.merge_range("A1:B1", "", menu_button_format)
segments_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

segments_worksheet.set_column(0,0,19.00)
segments_worksheet.set_column(1,segment_targets_view.shape[1]-1,17.00)

for row, df in zip(fin_rows[:1], [segment_gross_value_table]):  
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    segments_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    segments_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': bold_format})
    segments_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    segments_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})

for row, df in zip(fin_rows[1:2], [segment_net_value_table]):  # Apply only to the second DataFrame
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    segments_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    segments_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    segments_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    segments_worksheet.conditional_format(row + 1, end_col - 2, end_row, end_col -2, {'type': 'no_errors', 'format': bold_format})
    segments_worksheet.conditional_format(row + 1, end_col - 1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})

for row, df in zip(fin_rows[2:3], [segment_targets_view]):  
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    segments_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    segments_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    segments_worksheet.conditional_format(row + 1, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': million_format})
    segments_worksheet.conditional_format(row + 1, col + 1, end_row - 1, col + 3, {'type': 'no_errors', 'format': white_fill_format})
    segments_worksheet.conditional_format(end_row, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row + 1, col + 4, end_row, col +4, {'type': 'no_errors', 'format': percent_format})
    segments_worksheet.conditional_format(row + 1, end_col - 3, end_row, end_col - 1, {'type': 'no_errors', 'format': million_format})
    segments_worksheet.conditional_format(row + 1, end_col - 3, end_row - 1, end_col - 1, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    segments_worksheet.conditional_format(end_row, end_col - 3, end_row, end_col - 1, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    segments_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': percent_format})
    

    segments_worksheet.conditional_format(row+1, ytd_perc_col, end_row, ytd_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    segments_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format})
    segments_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format})
    segments_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format})

segments_worksheet.freeze_panes(5,1)
print(f"Sheet '{segments_sheet_name}' is successfully saved.")



# Role per Segment View
role_segment_value_table = segment_value(loan_drawdown, index=['BANKING_SEGMENT', 'ROLE'], months_column_name = 'MONTH_YR',  value_column_name = 'NET_DRAWDOWN')
# role_segment_value_table.head(2)

role_segment_value_table = role_segment_value_table.reset_index()
bb_seg = role_segment_value_table[role_segment_value_table['BANKING_SEGMENT'] == 'BUSINESS']
commercial_seg = role_segment_value_table[role_segment_value_table['BANKING_SEGMENT'] == 'COMMERCIAL']
diaspora_seg = role_segment_value_table[role_segment_value_table['BANKING_SEGMENT'] == 'DIASPORA']
personal_seg = role_segment_value_table[role_segment_value_table['BANKING_SEGMENT'] == 'PERSONAL']
ultimate_seg = role_segment_value_table[role_segment_value_table['BANKING_SEGMENT'] == 'ULTIMATE']


def order_and_sort_dataframes(bb_seg, commercial_seg, diaspora_seg, personal_seg, ultimate_seg, role_order):
    """
    Processes 5 dataframes with role ordering and sorting (Python 3.6 compatible)
    
    Args:
        df1, df2, df3, df4, df5: Input dataframes with 'ROLE' column
        role_order: List defining the desired role order
        
    Returns:
        Tuple of 5 processed dataframes
    """
    def process_df(df):
        # Filter and convert to categorical
        df_processed = df[df['ROLE'].isin(role_order)].copy()
        df_processed['ROLE'] = pd.Categorical(df_processed['ROLE'], categories=role_order, ordered=True)
        # Sort and return
        return df_processed.sort_values('ROLE')
    
    # Process each dataframe
    return (
        process_df(bb_seg),
        process_df(commercial_seg),
        process_df(diaspora_seg),
        process_df(personal_seg),
        process_df(ultimate_seg)
    )

role_order = ['COMMERCIAL RM', 'DIASPORA ARM', 'DIASPORA RM', 'MORTGAGE ARM', 'Others', 'PB ARM', 'PB BBC', 'PB DSR', 'PB RM', 'SME ARM', 'SME BBC', 'SME DSR', 'SME RM', 'ULTIMATE RM']
# Apply function
bb_seg, commercial_seg, diaspora_seg, personal_seg, ultimate_seg = order_and_sort_dataframes(bb_seg, commercial_seg, diaspora_seg, personal_seg, ultimate_seg, role_order)


def process_role_seg(df, main_category, month_column_order):
    """Processes a role segmentation DataFrame to include totals and percentage calculations."""
    
    # Ensure the DataFrame is not empty
    if df.empty:
        data = {
            'BANKING_SEGMENT': [main_category],  # Dynamically set BANKING_SEGMENT category
            'ROLE': [''],
            'YTD_Actual': [0]
        }
        for column in month_column_order:
            data[column] = [0]
        df = pd.DataFrame(data)
    else:
        df = df.copy()
        df = df.assign(BANKING_SEGMENT = main_category)

    # Compute total category sum
    df_total = df.copy()
    df_total['ROLE'] = 'TOTAL'
    df_total = df_total.groupby(['BANKING_SEGMENT', 'ROLE'], as_index=False).sum()
    
    # Combine original and total DataFrames
    df_combined = pd.concat([df, df_total], ignore_index=True)

    # Compute percentage values
    if 'YTD_Actual' not in df_combined.columns:
        raise ValueError("DataFrame does not contain 'YTD_Actual' column.")
    
    max_value = df_combined['YTD_Actual'].max()
    if max_value == 0:
        df_combined['% Per Role'] = None
    else:
        df_combined['% Per Role'] = df_combined['YTD_Actual'] / max_value

    # Ensure rows with max value have NaN percentage
    df_combined.loc[df_combined['YTD_Actual'] == max_value, '% Per Role'] = None

    # create rank on % values
    df_combined['Rank'] = None
    df_combined.iloc[:-1, df_combined.columns.get_loc('Rank')] = df_combined.iloc[:-1]['% Per Role'].rank(method = 'dense', ascending = False)
    df_combined = df_combined.sort_values(by = 'Rank')
    df_combined = df_combined.drop(columns = 'Rank')

    # Order columns properly
    ordered_columns = ['BANKING_SEGMENT', 'ROLE'] + month_column_order + ['YTD_Actual', '% Per Role']
    
    return df_combined[ordered_columns]

# Define DataFrames and their respective BANKING_SEGMENT categories
role_dataframes = {
    "BUSINESS": bb_seg,
    "COMMERCIAL": commercial_seg,
    "DIASPORA": diaspora_seg,
    "PERSONAL": personal_seg,
    "ULTIMATE": ultimate_seg
}
# Concatenate all dataframes
processed_dfs = [process_role_seg(df, BANKING_SEGMENT, month_column_order) for BANKING_SEGMENT, df in role_dataframes.items()]
total_role_seg_summ = pd.concat(processed_dfs, ignore_index = True, verify_integrity = True)

# Get grand total row
# Get the total rows (assuming they're the last row of each df)
role_total_rows = [df.iloc[[-1], 1:-1] for df in processed_dfs]
# Concatenate those total rows into a new dataframe
role_totals_df = pd.concat(role_total_rows, ignore_index = True)
# Sum the total rows to get grand total
role_grand_total = role_totals_df.select_dtypes(include = 'number').sum(numeric_only = True)
# Create a new row with "Grand Total" as the index or a label in one column
role_grand_total_row = role_totals_df.iloc[0].copy()
role_grand_total_row.loc[role_grand_total.index] = role_grand_total
# Label the row appropriately (assuming first column is 'Label' or similar)
if 'ROLE' in total_role_seg_summ.columns:
    role_grand_total_row['ROLE'] = 'GRAND TOTAL'

# Append grand total row to the combined dataframe
total_role_seg_summ_final = pd.concat([total_role_seg_summ, pd.DataFrame([role_grand_total_row])], ignore_index=True)
# total_role_seg_summ_final.tail(2)

total_role_seg_summ_2 = total_role_seg_summ_final.copy()
total_role_seg_summ_2 = total_role_seg_summ_2.set_index(['BANKING_SEGMENT', 'ROLE'])
# total_role_seg_summ_2.head()


# Writing the table in excel(Segments_per_Role)
value_to_find = 'TOTAL'
total_row_numbers = total_role_seg_summ_final.index[total_role_seg_summ_final['ROLE'] == value_to_find].tolist()

start_row = 4
end_row = total_role_seg_summ_2.shape[0] + start_row
start_col = 0
end_col = total_role_seg_summ_2.shape[1]+1
title_cols = 1
role_perc_col = total_role_seg_summ_2.shape[1]+1

total_role_seg_summ_2.to_excel(daily_drawdown_report_writer, sheet_name = segments_per_role_sheet_name, index = True, startrow = start_row, startcol = start_col)

segments_per_role_worksheet = daily_drawdown_report_writer.sheets[segments_per_role_sheet_name]
segments_per_role_worksheet.set_zoom(80)
segments_per_role_worksheet.set_tab_color(sheet_tab_color)

segments_per_role_worksheet.merge_range(start_row-1,0,start_row-1,1, 'ROLE PER SEGMENT', delft_blue_fill_format)

segments_per_role_worksheet.merge_range("A1:B1", "", menu_button_format)
segments_per_role_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

segments_per_role_worksheet.set_column(0,0,20.00)
segments_per_role_worksheet.set_column(1,1,25.00)
segments_per_role_worksheet.set_column(2,total_role_seg_summ_2.shape[1],20.00,comma_format)
segments_per_role_worksheet.set_column(total_role_seg_summ_2.shape[1]+1,total_role_seg_summ_2.shape[1]+1,20.00, percent_format)

segments_per_role_worksheet.conditional_format(start_row, start_col, start_row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
segments_per_role_worksheet.conditional_format(start_row+1, start_col, end_row, start_col, {'type': 'no_errors','format': deepskyblue_fill_format})
segments_per_role_worksheet.conditional_format(start_row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
segments_per_role_worksheet.conditional_format(start_row+1, end_col-1, end_row, end_col-1, {'type': 'no_errors','format': bold_format})
segments_per_role_worksheet.conditional_format(end_row, start_col, end_row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

for row_num in total_row_numbers:
    row = row_num + title_cols + 4
    segments_per_role_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

perc_col = role_perc_col
segments_per_role_worksheet.conditional_format(start_row+1, perc_col, end_row, perc_col, color_scale)

segments_per_role_worksheet.freeze_panes(5,2)
print(f"Sheet '{segments_per_role_sheet_name}' is successfully saved.")

# Product Disbursements
# Gross Values
product_gross_value_table = sum_monthly(loan_drawdown, index = 'PRODUCT_CATEGORY', months_column_name = 'MONTH_YR', value_column_name = 'GROSS_DRAWDOWN')
sum_row = product_gross_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'PRODUCT_CATEGORY', 'TOTAL')   
product_gross_value_table = pd.concat([product_gross_value_table, sum_row], ignore_index = True)
product_gross_value_table['YTD_Actual'] = product_gross_value_table[month_column_order].sum(axis=1)
# product_gross_value_table

# Net Values
product_net_value_table = sum_monthly(loan_drawdown, index = 'PRODUCT_CATEGORY', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
sum_row = product_net_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'PRODUCT_CATEGORY', 'TOTAL')   
product_net_value_table = pd.concat([product_net_value_table, sum_row], ignore_index = True)
product_net_value_table['YTD_Actual'] = product_net_value_table[month_column_order].sum(axis=1)
# product_net_value_table


# Write tables to excel
all_dfs = [product_gross_value_table,product_net_value_table]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = product_disbursements_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

product_disbursement_worksheet = daily_drawdown_report_writer.sheets[product_disbursements_sheet_name]
product_disbursement_worksheet.set_zoom(80)
product_disbursement_worksheet.set_tab_color(sheet_tab_color)

product_disbursement_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'GROSS PER PRODUCT', delft_blue_fill_format)
product_disbursement_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'NET PER PRODUCT', delft_blue_fill_format)

product_disbursement_worksheet.merge_range("A1:B1", "", menu_button_format)
product_disbursement_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

product_disbursement_worksheet.set_column(0,0,19.27)
product_disbursement_worksheet.set_column(1,product_gross_value_table.shape[1]-1,15.00)

for row, df in zip(fin_rows, all_dfs):  
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    product_disbursement_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    product_disbursement_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': bold_format})
    product_disbursement_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    product_disbursement_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    product_disbursement_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    product_disbursement_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})

product_disbursement_worksheet.freeze_panes(5,1)
print(f"Sheet '{product_disbursements_sheet_name}' is successfully saved.")  

# Product per Segment View
product_segment_value_table = segment_value(loan_drawdown, index = ['BANKING_SEGMENT', 'PRODUCT_CATEGORY'], months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# product_segment_value_table.head(2)

product_segment_value_table = product_segment_value_table.reset_index()
bb_product_seg = product_segment_value_table[product_segment_value_table['BANKING_SEGMENT'] == 'BUSINESS']
commercial_product_seg = product_segment_value_table[product_segment_value_table['BANKING_SEGMENT'] == 'COMMERCIAL']
diaspora_product_seg = product_segment_value_table[product_segment_value_table['BANKING_SEGMENT'] == 'DIASPORA']
personal_product_seg = product_segment_value_table[product_segment_value_table['BANKING_SEGMENT'] == 'PERSONAL']
ultimate_product_seg = product_segment_value_table[product_segment_value_table['BANKING_SEGMENT'] == 'ULTIMATE']

print("printing commercial product segmennt table")
print(commercial_product_seg.shape)
print(commercial_product_seg)


def process_product_seg(df, main_category, month_column_order):
    """Processes a product segmentation DataFrame to include totals and percentage calculations."""
    
    # Ensure the DataFrame is not empty
    if df.empty:
        data = {
            'BANKING_SEGMENT': [main_category],  # Dynamically set BANKING_SEGMENT category
            'PRODUCT_CATEGORY': [''],
            'YTD_Actual': [0]
        }
        for column in month_column_order:
            data[column] = [0]
        df = pd.DataFrame(data)
    else:
        df = df.copy()
        df = df.assign(BANKING_SEGMENT = main_category)

    # Compute total category sum
    df_total = df.copy()
    df_total['PRODUCT_CATEGORY'] = 'TOTAL'
    df_total = df_total.groupby(['BANKING_SEGMENT', 'PRODUCT_CATEGORY'], as_index = False).sum()
    
    # Combine original and total DataFrames
    df_combined = pd.concat([df, df_total], ignore_index = True)

    # Compute percentage values
    if 'YTD_Actual' not in df_combined.columns:
        raise ValueError("DataFrame does not contain 'YTD_Actual' column.")
    
    max_value = df_combined['YTD_Actual'].max()
    if max_value == 0:
        df_combined['% Per Product'] = None
    else:
        df_combined['% Per Product'] = df_combined['YTD_Actual'] / max_value

    # Ensure rows with max value have NaN percentage
    df_combined.loc[df_combined['YTD_Actual'] == max_value, '% Per Product'] = None

    # create rank on % values
    df_combined['Rank'] = None
    df_combined.iloc[:-1, df_combined.columns.get_loc('Rank')] = df_combined.iloc[:-1]['% Per Product'].rank(method = 'dense', ascending = False)
    df_combined = df_combined.sort_values(by = 'Rank')
    df_combined = df_combined.drop(columns = 'Rank')

    # Order columns properly
    ordered_columns = ['BANKING_SEGMENT', 'PRODUCT_CATEGORY'] + month_column_order + ['YTD_Actual', '% Per Product']
    return df_combined[ordered_columns]

# Define DataFrames and their respective BANKING_SEGMENT categories
product_dataframes = {
    "BUSINESS": bb_product_seg,
    "COMMERCIAL": commercial_product_seg,
    "DIASPORA": diaspora_product_seg,
    "PERSONAL": personal_product_seg,
    "ULTIMATE": ultimate_product_seg
}
# Concatenate all dataframes
processed_dfs_2 = [process_product_seg(df, BANKING_SEGMENT, month_column_order) for BANKING_SEGMENT, df in product_dataframes.items()]
total_product_seg_summ = pd.concat(processed_dfs_2, ignore_index=True, verify_integrity=True)

# Get grand total row
# Get the total rows (assuming they're the last row of each df)
product_total_rows = [df.iloc[[-1], 1:-1] for df in processed_dfs_2]
# Concatenate those total rows into a new dataframe
product_totals_df = pd.concat(product_total_rows, ignore_index = True)
# Sum the total rows to get grand total
product_grand_total = product_totals_df.select_dtypes(include = 'number').sum(numeric_only = True)
# Create a new row with "Grand Total" as the index or a label in one column
product_grand_total_row = product_totals_df.iloc[0].copy()
product_grand_total_row.loc[product_grand_total.index] = product_grand_total
# Label the row appropriately (assuming first column is 'Label' or similar)
if 'PRODUCT_CATEGORY' in total_product_seg_summ.columns:
    product_grand_total_row['PRODUCT_CATEGORY'] = 'GRAND TOTAL'

# Append grand total row to the combined dataframe
total_product_seg_summ_final = pd.concat([total_product_seg_summ, pd.DataFrame([product_grand_total_row])], ignore_index=True)
# total_product_seg_summ_final.tail(2)

print("printing product segmennt table")
print(total_product_seg_summ_final.shape)
print(total_product_seg_summ_final)

total_product_seg_summ_2 = total_product_seg_summ_final.copy()
total_product_seg_summ_2 = total_product_seg_summ_2.set_index(['BANKING_SEGMENT', 'PRODUCT_CATEGORY'])
# total_product_seg_summ_2.head()



# Write table to excel
value_to_find = 'TOTAL'
total_row_numbers = total_product_seg_summ_final.index[total_product_seg_summ_final['PRODUCT_CATEGORY'] == value_to_find].tolist()

start_row = 4
end_row = total_product_seg_summ_2.shape[0] + start_row
start_col = 0
end_col = total_product_seg_summ_2.shape[1]+1
title_cols = 1
product_perc_col = total_product_seg_summ_2.shape[1]+1

total_product_seg_summ_2.to_excel(daily_drawdown_report_writer, sheet_name = segments_per_product_category_sheet_name, index = True, startrow = start_row, startcol = start_col)

segments_per_product_category_worksheet = daily_drawdown_report_writer.sheets[segments_per_product_category_sheet_name]
segments_per_product_category_worksheet.set_zoom(80)
segments_per_product_category_worksheet.set_tab_color(sheet_tab_color)

segments_per_product_category_worksheet.merge_range(start_row-1,0,start_row-1,2, 'PRODUCT_CATEGORY PER SEGMENT', delft_blue_fill_format)

segments_per_product_category_worksheet.merge_range("A1:B1", "", menu_button_format)
segments_per_product_category_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

segments_per_product_category_worksheet.set_column(0,1,22.00)
segments_per_product_category_worksheet.set_column(2,total_product_seg_summ_2.shape[1],20.00,comma_format)
segments_per_product_category_worksheet.set_column(total_product_seg_summ_2.shape[1]+1,total_product_seg_summ_2.shape[1]+1,20.00, percent_format)

segments_per_product_category_worksheet.conditional_format(start_row, start_col, start_row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
segments_per_product_category_worksheet.conditional_format(start_row+1, start_col, end_row, start_col, {'type': 'no_errors','format': deepskyblue_fill_format})
segments_per_product_category_worksheet.conditional_format(start_row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
segments_per_product_category_worksheet.conditional_format(start_row+1, end_col-1, end_row, end_col-1, {'type': 'no_errors','format': bold_format})
segments_per_product_category_worksheet.conditional_format(end_row, start_col, end_row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

for row_num in total_row_numbers:
    row = row_num + title_cols + 4
    segments_per_product_category_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

perc_col = product_perc_col
segments_per_product_category_worksheet.conditional_format(start_row+1, perc_col, end_row, perc_col, color_scale)   

segments_per_product_category_worksheet.freeze_panes(5,2)
print(f"Sheet '{segments_per_product_category_sheet_name}' is successfully saved.")

# Mortgage Worksheet
mortgage_order = ['MARKET RATE', 'NON_MARKET RATE']

# Gross Values
mortgage_gross_value_table = sum_monthly(loan_drawdown, index = 'MORTGAGE', months_column_name = 'MONTH_YR', value_column_name = 'GROSS_DRAWDOWN')
mortgage_gross_value_table = mortgage_gross_value_table[~mortgage_gross_value_table['MORTGAGE'].str.contains('OTHERS', case=False, na=False)]
mortgage_gross_value_table = mortgage_gross_value_table[(mortgage_gross_value_table['MORTGAGE'].isin(mortgage_order))]
# Calculate the sum of the columns
sum_row = mortgage_gross_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')
mortgage_gross_value_table = pd.concat([mortgage_gross_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
mortgage_gross_value_table['YTD_Actual'] = mortgage_gross_value_table[month_column_order].sum(axis=1)
# mortgage_gross_value_table

# Net Values
mortgage_net_value_table = sum_monthly(loan_drawdown, index = 'MORTGAGE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
mortgage_net_value_table = mortgage_net_value_table[~mortgage_net_value_table['MORTGAGE'].str.contains('OTHERS', case=False, na=False)]
mortgage_net_value_table = mortgage_net_value_table[(mortgage_net_value_table['MORTGAGE'].isin(mortgage_order))]
# Calculate the sum of the columns
sum_row = mortgage_net_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')
mortgage_net_value_table = pd.concat([mortgage_net_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
mortgage_net_value_table['YTD_Actual'] = mortgage_net_value_table[month_column_order].sum(axis=1)
# mortgage_net_value_table

# Weekly Mortgage values
mortgage_drawdown = loan_drawdown.loc[loan_drawdown['MORTGAGE'] != 'Others']

amount_column = ['FINAL_INTEREST', 'NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['MORTGAGE']
detail_column = ['NAME', 'ROLE']
if mortgage_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'NON_MARKET RATE'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        mortgage_drawdown = pd.concat([mortgage_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')
    
weekly_mortgage_drawdown = mortgage_drawdown.loc[mortgage_drawdown['WEEK'] == week_number]
mortgage_weekly_view = sum(weekly_mortgage_drawdown, index = 'MORTGAGE', value_column_name = 'NET_DRAWDOWN')
mortgage_weekly_view = mortgage_weekly_view[(mortgage_weekly_view['MORTGAGE'].isin(mortgage_order))]
mortgage_weekly_view.rename(columns = {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = mortgage_weekly_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')   
mortgage_weekly_view = pd.concat([mortgage_weekly_view, sum_row], ignore_index = True)
# Check if df is empty
if mortgage_weekly_view.shape == (1,1):
    data = {
        'MORTGAGE':['MARKET RATE', 'NON_MARKET RATE	', 'TOTAL'],
        'Weekly':[0,0,0]
    }
    mortgage_weekly_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# mortgage_weekly_view

# Daily Mortgage values
daily_mortgage_drawdown = mortgage_drawdown.loc[mortgage_drawdown['DRAWDOWN_DT'] == max_date]
mortgage_daily_view = sum(daily_mortgage_drawdown, index = 'MORTGAGE', value_column_name = 'NET_DRAWDOWN')
mortgage_daily_view = mortgage_daily_view[(mortgage_daily_view['MORTGAGE'].isin(mortgage_order))]
mortgage_daily_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = mortgage_daily_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')   
mortgage_daily_view = pd.concat([mortgage_daily_view, sum_row], ignore_index = True)
# Check if df is empty
if mortgage_daily_view.shape == (1,1):
    data = {
        'MORTGAGE':['MARKET RATE', 'NON_MARKET RATE	', 'TOTAL'],
        'Daily':[0,0,0]
    }
    mortgage_daily_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# mortgage_daily_view

# Merge net, weekly and daily tables
mortgage_net_value_table = pd.merge(mortgage_net_value_table,mortgage_weekly_view, left_on = 'MORTGAGE', right_on = 'MORTGAGE', how = 'left')
mortgage_net_value_table = pd.merge(mortgage_net_value_table,mortgage_daily_view, left_on = 'MORTGAGE', right_on = 'MORTGAGE', how = 'left')
mortgage_net_value_table = mortgage_net_value_table.fillna(0)
# mortgage_net_value_table

# Mortgage Targets
# mortgage_targets_data = [
#     {'banking_segment':'MORTGAGE', 'fy_target': 7536000000}
# ]
# mortgage_targets_table = pd.DataFrame(mortgage_targets_data)

conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

mortgage_targets_table = '''
select banking_segment, fy_target
from segment_drawdown_targets

'''
mortgage_targets_table = pd.read_sql_query(mortgage_targets_table , conn)

conn.close()

mortgage_targets_table = mortgage_targets_table.loc[mortgage_targets_table['banking_segment'] == 'MORTGAGE']
mortgage_targets_table = mortgage_targets_table.reset_index(drop=True)
mortgage_targets_table.rename(columns = {'banking_segment': 'MORTGAGE'}, inplace=True)
mortgage_targets_table['Monthly_Target'] = mortgage_targets_table['fy_target'] / 12
# mortgage_targets_table

# Calculations
mortgage_net_value_table_refined = mortgage_net_value_table.copy()
mortgage_net_value_table_refined = mortgage_net_value_table_refined[['MORTGAGE', (max_month_name), 'YTD_Actual']]
mortgage_net_value_table_refined.rename(columns = {(max_month_name): 'Month_Actual'}, inplace=True)
mortgage_net_value_table_refined = mortgage_net_value_table_refined.tail(1)
mortgage_net_value_table_refined = mortgage_net_value_table_refined.reset_index(drop = True)
mortgage_net_value_table_refined.loc[0, 'MORTGAGE'] = mortgage_net_value_table_refined.loc[0, 'MORTGAGE'].replace('TOTAL', 'MORTGAGE')
# mortgage_net_value_table_refined

# Merge tables
mortgage_targets_view = mortgage_targets_table.copy()
mortgage_targets_view = pd.merge(mortgage_targets_view, mortgage_net_value_table_refined, left_on = 'MORTGAGE', right_on = 'MORTGAGE', how = 'left')
mortgage_targets_view = mortgage_targets_view.fillna(0)
# mortgage_targets_view

# mortgage achievements
mortgage_targets_view['YTD_Target'] = mortgage_targets_view['fy_target'] * year_fraction
mortgage_targets_view['YTD_%_Achieved'] = mortgage_targets_view.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
mortgage_targets_view['Month_Deficit'] = mortgage_targets_view['Month_Actual'] - mortgage_targets_view['Monthly_Target']
mortgage_targets_view['Month_%_Achieved'] = mortgage_targets_view.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
# mortgage_targets_view

# Order columns
column_order = ['MORTGAGE', 'fy_target', 'YTD_Target', 'YTD_Actual', 'YTD_%_Achieved', 'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved']
mortgage_targets_view = mortgage_targets_view.reindex(columns = column_order)
# mortgage_targets_view

# Write tables to excel
all_dfs = [mortgage_gross_value_table,mortgage_net_value_table,mortgage_targets_view]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = mortgage_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

mortgage_worksheet = daily_drawdown_report_writer.sheets[mortgage_sheet_name]
mortgage_worksheet.set_zoom(80)
mortgage_worksheet.set_tab_color(sheet_tab_color)

mortgage_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'GROSS MORTGAGE VALUES', delft_blue_fill_format)
mortgage_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'NET MORTGAGE VALUES', delft_blue_fill_format)
mortgage_worksheet.merge_range(fin_rows[2]-1,0,fin_rows[2]-1,1, 'MORTGAGE PERFORMANCE', delft_blue_fill_format)

mortgage_worksheet.merge_range("A1:B1", "", menu_button_format)
mortgage_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

mortgage_worksheet.set_column(0,0,19.00)
mortgage_worksheet.set_column(1,mortgage_targets_view.shape[1]-1,17.00)


for row, df in zip(fin_rows[:1], [mortgage_gross_value_table]):     
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    mortgage_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    mortgage_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': bold_format})
    mortgage_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    mortgage_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})

for row, df in zip(fin_rows[1:2], [mortgage_net_value_table]):  # Apply only to the second DataFrame
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    mortgage_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    mortgage_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    mortgage_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    mortgage_worksheet.conditional_format(row + 1, end_col - 2, end_row, end_col -2, {'type': 'no_errors', 'format': bold_format})
    mortgage_worksheet.conditional_format(row + 1, end_col - 1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})

for row, df in zip(fin_rows[2:3], [mortgage_targets_view]):  
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    mortgage_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    mortgage_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    mortgage_worksheet.conditional_format(row + 1, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': million_format})    
    mortgage_worksheet.conditional_format(row + 1, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': white_fill_format})
    # mortgage_worksheet.conditional_format(end_row, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row + 1, col + 4, end_row, col +4, {'type': 'no_errors', 'format': percent_format})
    mortgage_worksheet.conditional_format(row + 1, end_col - 3, end_row, end_col - 1, {'type': 'no_errors', 'format': million_format})
    mortgage_worksheet.conditional_format(row + 1, end_col - 3, end_row - 1, end_col - 1, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    # mortgage_worksheet.conditional_format(end_row, end_col - 3, end_row, end_col - 1, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    mortgage_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': percent_format})
    

    mortgage_worksheet.conditional_format(row+1, ytd_perc_col, end_row, ytd_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    mortgage_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format})
    mortgage_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format})
    mortgage_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format})

mortgage_worksheet.freeze_panes(5,1)
print(f"Sheet '{mortgage_sheet_name}' is successfully saved.")


# Mortgage per segment view
mortgage_segment_value_table = segment_value(loan_drawdown, months_column_name = 'MONTH_YR', index = ['BANKING_SEGMENT', 'MORTGAGE'], value_column_name = 'NET_DRAWDOWN')
mortgage_segment_value_table = mortgage_segment_value_table.reset_index()
mortgage_segment_value_table = mortgage_segment_value_table[~mortgage_segment_value_table['MORTGAGE'].str.contains('OTHERS', case=False, na=False)]
# mortgage_segment_value_table.head(2)

bb_mortgage_seg = mortgage_segment_value_table[mortgage_segment_value_table['BANKING_SEGMENT'] == 'BUSINESS']
commercial_mortgage_seg = mortgage_segment_value_table[mortgage_segment_value_table['BANKING_SEGMENT'] == 'COMMERCIAL']
diaspora_mortgage_seg = mortgage_segment_value_table[mortgage_segment_value_table['BANKING_SEGMENT'] == 'DIASPORA']
personal_mortgage_seg = mortgage_segment_value_table[mortgage_segment_value_table['BANKING_SEGMENT'] == 'PERSONAL']
ultimate_mortgage_seg = mortgage_segment_value_table[mortgage_segment_value_table['BANKING_SEGMENT'] == 'ULTIMATE']

def process_mortgage_seg(df, main_category, month_column_order):
    """Processes a mortgage segmentation DataFrame to include totals and percentage calculations."""
    
    # Ensure the DataFrame is not empty
    if df.empty:
        data = {
            'BANKING_SEGMENT': [main_category],  # Dynamically set BANKING_SEGMENT category
            'MORTGAGE': [''],
            'YTD_Actual': [0]
        }
        for column in month_column_order:
            data[column] = [0]
        df = pd.DataFrame(data)
    else:
        df = df.copy()
        df = df.assign(BANKING_SEGMENT = main_category)

    # Compute total category sum
    df_total = df.copy()
    df_total['MORTGAGE'] = 'TOTAL'
    df_total = df_total.groupby(['BANKING_SEGMENT', 'MORTGAGE'], as_index=False).sum()
    
    # Combine original and total DataFrames
    df_combined = pd.concat([df, df_total], ignore_index=True)

    # Compute percentage values
    if 'YTD_Actual' not in df_combined.columns:
        raise ValueError("DataFrame does not contain 'YTD_Actual' column.")
    
    max_value = df_combined['YTD_Actual'].max()
    if max_value == 0:
        df_combined['% Per Mortgage'] = None
    else:
        df_combined['% Per Mortgage'] = df_combined['YTD_Actual'] / max_value

    # Ensure rows with max value have NaN percentage
    df_combined.loc[df_combined['YTD_Actual'] == max_value, '% Per Mortgage'] = None

    # create rank on % values
    df_combined['Rank'] = None
    df_combined.iloc[:-1, df_combined.columns.get_loc('Rank')] = df_combined.iloc[:-1]['% Per Mortgage'].rank(method = 'dense', ascending = False)
    df_combined = df_combined.sort_values(by = 'Rank')
    df_combined = df_combined.drop(columns = 'Rank')

    # Order columns properly
    ordered_columns = ['BANKING_SEGMENT', 'MORTGAGE'] + month_column_order + ['YTD_Actual', '% Per Mortgage']
    return df_combined[ordered_columns]

# Define DataFrames and their respective BANKING_SEGMENT categories
mortgage_dataframes = {
    "BUSINESS": bb_mortgage_seg,
    "COMMERCIAL": commercial_mortgage_seg,
    "DIASPORA": diaspora_mortgage_seg,
    "PERSONAL": personal_mortgage_seg,
    "ULTIMATE": ultimate_mortgage_seg
}
# Concatenate all dataframes
processed_dfs_3 = [process_mortgage_seg(df, BANKING_SEGMENT, month_column_order) for BANKING_SEGMENT, df in mortgage_dataframes.items()]
total_mortgage_seg_summ = pd.concat(processed_dfs_3, ignore_index=True, verify_integrity=True)
# Get grand total row
# Get the total rows (assuming they're the last row of each df)
mortgage_total_rows = [df.iloc[[-1], 1:-1] for df in processed_dfs_3]
# Concatenate those total rows into a new dataframe
mortgage_totals_df = pd.concat(mortgage_total_rows, ignore_index = True)
# Sum the total rows to get grand total
mortgage_grand_total = mortgage_totals_df.select_dtypes(include = 'number').sum(numeric_only = True)
# Create a new row with "Grand Total" as the index or a label in one column
mortgage_grand_total_row = mortgage_totals_df.iloc[0].copy()
mortgage_grand_total_row.loc[mortgage_grand_total.index] = mortgage_grand_total
# Label the row appropriately (assuming first column is 'Label' or similar)
if 'MORTGAGE' in total_mortgage_seg_summ.columns:
    mortgage_grand_total_row['MORTGAGE'] = 'GRAND TOTAL'

# Append grand total row to the combined dataframe
total_mortgage_seg_summ_final = pd.concat([total_mortgage_seg_summ, pd.DataFrame([mortgage_grand_total_row])], ignore_index=True)
# total_mortgage_seg_summ_final.tail(2)

total_mortgage_seg_summ_2 = total_mortgage_seg_summ_final.copy()
total_mortgage_seg_summ_2 = total_mortgage_seg_summ_2.set_index(['BANKING_SEGMENT', 'MORTGAGE'])
# total_mortgage_seg_summ_2.head(2)

# Write table to excel
value_to_find = 'TOTAL'
total_row_numbers = total_mortgage_seg_summ_final.index[total_mortgage_seg_summ_final['MORTGAGE'] == value_to_find].tolist()

start_row = 4
end_row = total_mortgage_seg_summ_2.shape[0] + start_row
start_col = 0
end_col = total_mortgage_seg_summ_2.shape[1]+1
title_cols = 1
mortgage_perc_col = total_mortgage_seg_summ_2.shape[1]+1

total_mortgage_seg_summ_2.to_excel(daily_drawdown_report_writer, sheet_name = segment_per_mortgage_sheet_name, index = True, startrow = start_row, startcol = start_col)

segments_per_mortgage_worksheet = daily_drawdown_report_writer.sheets[segment_per_mortgage_sheet_name]
segments_per_mortgage_worksheet.set_zoom(80)
segments_per_mortgage_worksheet.set_tab_color(sheet_tab_color)

segments_per_mortgage_worksheet.merge_range(start_row-1,0,start_row-1,2, 'MORTGAGE PER SEGMENT', delft_blue_fill_format)

segments_per_mortgage_worksheet.merge_range("A1:B1", "", menu_button_format)
segments_per_mortgage_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

segments_per_mortgage_worksheet.set_column(0,0,20.00)
segments_per_mortgage_worksheet.set_column(1,1,23.00)
segments_per_mortgage_worksheet.set_column(2,total_mortgage_seg_summ_2.shape[1],20.00,comma_format)
segments_per_mortgage_worksheet.set_column(total_mortgage_seg_summ_2.shape[1]+1,total_mortgage_seg_summ_2.shape[1]+1,20.00, percent_format)

segments_per_mortgage_worksheet.conditional_format(start_row, start_col, start_row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
segments_per_mortgage_worksheet.conditional_format(start_row+1, start_col, end_row, start_col, {'type': 'no_errors','format': deepskyblue_fill_format})
segments_per_mortgage_worksheet.conditional_format(start_row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
segments_per_mortgage_worksheet.conditional_format(start_row+1, end_col-1, end_row, end_col-1, {'type': 'no_errors','format': bold_format})
segments_per_mortgage_worksheet.conditional_format(end_row, start_col, end_row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

for row_num in total_row_numbers:
    row = row_num + title_cols + 4
    segments_per_mortgage_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

perc_col = mortgage_perc_col
segments_per_mortgage_worksheet.conditional_format(start_row+1, perc_col, end_row, perc_col, color_scale)  

segments_per_mortgage_worksheet.freeze_panes(5,2)
print(f"Sheet '{segment_per_mortgage_sheet_name}' is successfully saved.")


# Mortgage Sales Unit View
msu_drawdown = loan_drawdown[loan_drawdown['PRODUCT_CATEGORY'] == 'MORTGAGE'].copy()
roles = ['MORTGAGE ARM']
msu_drawdown = msu_drawdown[msu_drawdown['ROLE'].isin(roles)].copy()
print(msu_drawdown['SALES_CODE'].unique())

# Gross MSU values
msu_gross_value_table = sum_monthly(msu_drawdown, index = 'MORTGAGE', months_column_name = 'MONTH_YR', value_column_name = 'GROSS_DRAWDOWN')
msu_gross_value_table = msu_gross_value_table[~msu_gross_value_table['MORTGAGE'].str.contains('OTHERS', case=False, na=False)]
msu_gross_value_table = msu_gross_value_table[(msu_gross_value_table['MORTGAGE'].isin(mortgage_order))]
# Calculate the sum of the columns
sum_row = msu_gross_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')
msu_gross_value_table = pd.concat([msu_gross_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
msu_gross_value_table['YTD_Actual'] = msu_gross_value_table[month_column_order].sum(axis=1)
# msu_gross_value_table

# Net MSU values
msu_net_value_table = sum_monthly(msu_drawdown, index = 'MORTGAGE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
msu_net_value_table = msu_net_value_table[~msu_net_value_table['MORTGAGE'].str.contains('OTHERS', case=False, na=False)]
msu_net_value_table = msu_net_value_table[(msu_net_value_table['MORTGAGE'].isin(mortgage_order))]
# Calculate the sum of the columns
sum_row = msu_net_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')
msu_net_value_table = pd.concat([msu_net_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
msu_net_value_table['YTD_Actual'] = msu_net_value_table[month_column_order].sum(axis=1)
# msu_net_value_table

# Weekly MSU values
amount_column = ['FINAL_INTEREST', 'NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['MORTGAGE']
detail_column = ['NAME', 'ROLE']
if msu_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'NON_MARKET RATE'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        msu_drawdown = pd.concat([msu_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')
    
weekly_msu_drawdown = msu_drawdown.loc[msu_drawdown['WEEK'] == week_number]
msu_weekly_view = sum(weekly_msu_drawdown, index = 'MORTGAGE', value_column_name = 'NET_DRAWDOWN')
msu_weekly_view = msu_weekly_view[(msu_weekly_view['MORTGAGE'].isin(mortgage_order))]
msu_weekly_view.rename(columns = {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = msu_weekly_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')   
msu_weekly_view = pd.concat([msu_weekly_view, sum_row], ignore_index = True)
# Check if df is empty
if msu_weekly_view.shape == (1,1):
    data = {
        'MORTGAGE':['MARKET RATE', 'NON_MARKET RATE	', 'TOTAL'],
        'Weekly':[0,0,0]
    }
    msu_weekly_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# msu_weekly_view

# Daily MSU values
daily_msu_drawdown = msu_drawdown.loc[msu_drawdown['DRAWDOWN_DT'] == max_date]
msu_daily_view = sum(daily_msu_drawdown, index = 'MORTGAGE', value_column_name = 'NET_DRAWDOWN')
msu_daily_view = msu_daily_view[(msu_daily_view['MORTGAGE'].isin(mortgage_order))]
msu_daily_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = msu_daily_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'MORTGAGE', 'TOTAL')   
msu_daily_view = pd.concat([msu_daily_view, sum_row], ignore_index = True)
# Check if df is empty
if msu_daily_view.shape == (1,1):
    data = {
        'MORTGAGE':['MARKET RATE', 'NON_MARKET RATE	', 'TOTAL'],
        'Daily':[0,0,0]
    }
    msu_daily_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# msu_daily_view

# Merge net, weekly and daily tables
msu_net_value_table = pd.merge(msu_net_value_table,msu_weekly_view, left_on = 'MORTGAGE', right_on = 'MORTGAGE', how = 'left')
msu_net_value_table = pd.merge(msu_net_value_table,msu_daily_view, left_on = 'MORTGAGE', right_on = 'MORTGAGE', how = 'left')
msu_net_value_table = msu_net_value_table.fillna(0)
msu_net_value_table

# MSU Targets
msu_targets_data = [
    {'banking_segment':'MORTGAGE', 'fy_target': 2400000000}
]
msu_targets_table = pd.DataFrame(msu_targets_data)

msu_targets_table.rename(columns = {'banking_segment': 'MORTGAGE'}, inplace=True)
msu_targets_table['Monthly_Target'] = msu_targets_table['fy_target'] / 12
# msu_targets_table

# Calculations
msu_net_value_table_refined = msu_net_value_table.copy()
msu_net_value_table_refined = msu_net_value_table_refined[['MORTGAGE', (max_month_name), 'YTD_Actual']]
msu_net_value_table_refined.rename(columns = {(max_month_name): 'Month_Actual'}, inplace=True)
msu_net_value_table_refined = msu_net_value_table_refined.tail(1)
msu_net_value_table_refined = msu_net_value_table_refined.reset_index(drop = True)
msu_net_value_table_refined.loc[0, 'MORTGAGE'] = msu_net_value_table_refined.loc[0, 'MORTGAGE'].replace('TOTAL', 'MORTGAGE')
# msu_net_value_table_refined

# Merge tables
msu_targets_view = msu_targets_table.copy()
msu_targets_view = pd.merge(msu_targets_view, msu_net_value_table_refined, left_on = 'MORTGAGE', right_on = 'MORTGAGE', how = 'left')
msu_targets_view = msu_targets_view.fillna(0)
# msu_targets_view

# mortgage achievements
msu_targets_view['YTD_Target'] = msu_targets_view['fy_target'] * year_fraction
msu_targets_view['YTD_%_Achieved'] = msu_targets_view.apply(lambda row: calculate_percentage_achieved(row, 'YTD_Actual', 'YTD_Target'), axis=1)
msu_targets_view['Month_Deficit'] = msu_targets_view['Month_Actual'] - msu_targets_view['Monthly_Target']
msu_targets_view['Month_%_Achieved'] = msu_targets_view.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
# msu_targets_view

# Order columns
column_order = ['MORTGAGE', 'fy_target', 'YTD_Target', 'YTD_Actual', 'YTD_%_Achieved', 'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved']
msu_targets_view = msu_targets_view.reindex(columns = column_order)
# msu_targets_view

# Write tables to excel
all_dfs = [msu_gross_value_table,msu_net_value_table,msu_targets_view]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = msu_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

msu_worksheet = daily_drawdown_report_writer.sheets[msu_sheet_name]
msu_worksheet.set_zoom(80)
msu_worksheet.set_tab_color(sheet_tab_color)

msu_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'GROSS MSI VALUES', delft_blue_fill_format)
msu_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'NET MSU VALUES', delft_blue_fill_format)
msu_worksheet.merge_range(fin_rows[2]-1,0,fin_rows[2]-1,1, 'MSU PERFORMANCE', delft_blue_fill_format)

msu_worksheet.merge_range("A1:B1", "", menu_button_format)
msu_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

msu_worksheet.set_column(0,0,19.00)
msu_worksheet.set_column(1,msu_targets_view.shape[1]-1,17.00)


for row, df in zip(fin_rows[:1], [msu_gross_value_table]):     
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    msu_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    msu_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': bold_format})
    msu_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    msu_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})

for row, df in zip(fin_rows[1:2], [msu_net_value_table]):  # Apply only to the second DataFrame
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    msu_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    msu_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    msu_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    msu_worksheet.conditional_format(row + 1, end_col - 2, end_row, end_col -2, {'type': 'no_errors', 'format': bold_format})
    msu_worksheet.conditional_format(row + 1, end_col - 1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})

for row, df in zip(fin_rows[2:3], [msu_targets_view]):  
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    msu_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    msu_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    msu_worksheet.conditional_format(row + 1, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': million_format})    
    msu_worksheet.conditional_format(row + 1, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': white_fill_format})
    # msu_worksheet.conditional_format(end_row, col + 1, end_row, col + 3, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row + 1, col + 4, end_row, col +4, {'type': 'no_errors', 'format': percent_format})
    msu_worksheet.conditional_format(row + 1, end_col - 3, end_row, end_col - 1, {'type': 'no_errors', 'format': million_format})
    msu_worksheet.conditional_format(row + 1, end_col - 3, end_row - 1, end_col - 1, {'type': 'no_errors', 'format': paleturquoise_fill_format})
    # msu_worksheet.conditional_format(end_row, end_col - 3, end_row, end_col - 1, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    msu_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': percent_format})
    

    msu_worksheet.conditional_format(row+1, ytd_perc_col, end_row, ytd_perc_col, {'type': 'no_errors', 'format': ytd_grey_format})
    msu_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '>', 'value': 1, 'format': green_format})
    msu_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '>', 'value': 0.8, 'format': amber_format})
    msu_worksheet.conditional_format(row+1, month_perc_col, end_row, month_perc_col, {'type': 'cell', 'criteria': '<=', 'value': 0.8, 'format': red_format})

msu_worksheet.freeze_panes(5,1)
print(f"Sheet '{msu_sheet_name}' is successfully saved.")



# Mortgage Sales Unit View (Roles)
# MSU role map
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

msu_role_target_map = '''
select * from branch_employee_dmc_data where active = 1
                         
'''
msu_role_target_map = pd.read_sql_query(msu_role_target_map , conn)

conn.close()
# get mortgage rms
msu_role_target_map = msu_role_target_map[msu_role_target_map['staff_role'].isin(['MORTGAGE ARM'])]
msu_role_target_map = msu_role_target_map[['active', 'sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone', 'target_mortgage_mrkt_rate', 'target_mortgage_non_mrkt_rate']]
msu_role_target_map = msu_role_target_map.reset_index(drop=True)
print(msu_role_target_map['active'].unique())
print(msu_role_target_map['staff_role'].unique())
print(msu_role_target_map.head(1))

# MSU mrkt rate summaries
# filter markrt rate data
mortgage_mrkt_rate_drawdown = mortgage_drawdown.loc[loan_drawdown['MORTGAGE'] == 'MARKET RATE']

amount_column = ['FINAL_INTEREST', 'NET_DRAWDOWN', 'GROSS_DRAWDOWN']  # Add all your amount columns here
staff_column = ['SALES_STAFF', 'SALES_CODE']
check_column = ['MORTGAGE']
detail_column = ['NAME', 'ROLE']
if mortgage_mrkt_rate_drawdown.shape[0] == 0:  # Check if the DataFrame has 0 rows
        # Copy the first row from the `data` DataFrame
        new_row = loan_drawdown.iloc[0:1].copy()  # Get the first row as a DataFrame
        # Replace values in "amount" columns with 0
        new_row[amount_column] = 0
        new_row[staff_column] = 'IAPPLY'
        new_row[check_column] = 'MARKET RATE'
        new_row[detail_column] = 'Others'
        # Append the new row to the empty DataFrame
        mortgage_mrkt_rate_drawdown = pd.concat([mortgage_mrkt_rate_drawdown, new_row], ignore_index=True)
else:
    print('DataFrame is not empty')
    
print(mortgage_mrkt_rate_drawdown['MORTGAGE'].unique())

# get market rate drawdowns
msu_mrkt_rate_drawdown = sum_monthly(mortgage_mrkt_rate_drawdown, index = 'SALES_CODE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
msu_mrkt_rate_drawdown.head(1)

# Get Month_Actual values
mrkt_rate_month_actual = msu_mrkt_rate_drawdown[[('SALES_CODE'), (max_month_name)]]
mrkt_rate_month_actual = mrkt_rate_month_actual.rename(columns = {(max_month_name) : 'Month_Actual'})
mrkt_rate_month_actual.head(1)

# Mrkt rate tables for all roles
msu_mrkt_rate = []

roles = ['MORTGAGE ARM']

for role in roles:
    # get role targets
    msu_mrkt_rate_map = msu_role_target_map.loc[msu_role_target_map['staff_role'] == role, 
                                               ['sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone', 'target_mortgage_mrkt_rate']]
    msu_mrkt_rate_map = msu_mrkt_rate_map.rename(columns = {'target_mortgage_mrkt_rate': 'Monthly_Target'})
    
    # Merge to get month actual values
    msu_mrkt_rate_table = pd.merge(msu_mrkt_rate_map,mrkt_rate_month_actual, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    msu_mrkt_rate_table.drop(columns = ['SALES_CODE'], inplace = True)
    msu_mrkt_rate_table = msu_mrkt_rate_table.fillna(0)
    
    # Calculate month achievements
    msu_mrkt_rate_table['Month_Deficit'] = msu_mrkt_rate_table['Month_Actual'] - msu_mrkt_rate_table['Monthly_Target']
    msu_mrkt_rate_table = msu_mrkt_rate_table.fillna(0)
    msu_mrkt_rate_table['Month_%_Achieved'] = msu_mrkt_rate_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
    
    # Get monthly drawdowns
    msu_mrkt_rate_table = pd.merge(msu_mrkt_rate_table, msu_mrkt_rate_drawdown, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    msu_mrkt_rate_table.drop(columns = 'SALES_CODE', inplace = True)
    
    # Create role rank
    msu_mrkt_rate_table['Rank'] = msu_mrkt_rate_table['Month_%_Achieved'].rank(method = 'dense', ascending = False)
    msu_mrkt_rate_table = msu_mrkt_rate_table.sort_values(by = 'Rank')
    
    # Define column order
    cols_to_front = ['Rank','sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone',
                    'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved']
    remaining_cols = [col for col in msu_mrkt_rate_table.columns if col not in cols_to_front]
    column_order = cols_to_front + remaining_cols
    
    msu_mrkt_rate_table = msu_mrkt_rate_table.reindex(columns = column_order)
    msu_mrkt_rate_table = msu_mrkt_rate_table.fillna(0)
    
     # Append all role dfs
    msu_mrkt_rate.append(msu_mrkt_rate_table)


# MSU non-mrkt rate summaries
# filter markrt rate data
mortgage_non_mrkt_rate_drawdown = mortgage_drawdown.loc[loan_drawdown['MORTGAGE'] == 'NON_MARKET RATE']
print(mortgage_non_mrkt_rate_drawdown['MORTGAGE'].unique())

# get non_market rate drawdowns
msu_non_mrkt_rate_drawdown = sum_monthly(mortgage_non_mrkt_rate_drawdown, index = 'SALES_CODE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
msu_non_mrkt_rate_drawdown.head(1)

# Get Month_Actual values
non_mrkt_rate_month_actual = msu_non_mrkt_rate_drawdown[[('SALES_CODE'), (max_month_name)]]
non_mrkt_rate_month_actual = non_mrkt_rate_month_actual.rename(columns = {(max_month_name) : 'Month_Actual'})
non_mrkt_rate_month_actual.head(1)

# Non-mrkt rate tables for all roles
msu_non_mrkt_rate = []

roles = ['MORTGAGE ARM']

for role in roles:
    # get role targets
    msu_non_mrkt_rate_map = msu_role_target_map.loc[msu_role_target_map['staff_role'] == role, 
                                                   ['sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone', 'target_mortgage_non_mrkt_rate']]
    msu_non_mrkt_rate_map = msu_non_mrkt_rate_map.rename(columns = {'target_mortgage_non_mrkt_rate': 'Monthly_Target'})
    
    # Merge to get month actual values
    msu_non_mrkt_rate_table = pd.merge(msu_non_mrkt_rate_map,non_mrkt_rate_month_actual, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    msu_non_mrkt_rate_table.drop(columns = ['SALES_CODE'], inplace = True)
    msu_non_mrkt_rate_table = msu_non_mrkt_rate_table.fillna(0)
    
    # Calculate month achievements
    msu_non_mrkt_rate_table['Month_Deficit'] = msu_non_mrkt_rate_table['Month_Actual'] - msu_non_mrkt_rate_table['Monthly_Target']
    msu_non_mrkt_rate_table = msu_non_mrkt_rate_table.fillna(0)
    msu_non_mrkt_rate_table['Month_%_Achieved'] = msu_non_mrkt_rate_table.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
    
    # Get monthly drawdowns
    msu_non_mrkt_rate_table = pd.merge(msu_non_mrkt_rate_table, msu_non_mrkt_rate_drawdown, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    msu_non_mrkt_rate_table.drop(columns = 'SALES_CODE', inplace = True)
    
    # Create role rank
    msu_non_mrkt_rate_table['Rank'] = msu_non_mrkt_rate_table['Month_%_Achieved'].rank(method = 'dense', ascending = False)
    msu_non_mrkt_rate_table = msu_non_mrkt_rate_table.sort_values(by = 'Rank')
    
    # Define column order
    cols_to_front = ['Rank','sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone',
                    'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved']
    remaining_cols = [col for col in msu_non_mrkt_rate_table.columns if col not in cols_to_front]
    column_order = cols_to_front + remaining_cols
    
    msu_non_mrkt_rate_table = msu_non_mrkt_rate_table.reindex(columns = column_order)
    msu_non_mrkt_rate_table = msu_non_mrkt_rate_table.fillna(0)
    
    # Append all role dfs
    msu_non_mrkt_rate.append(msu_non_mrkt_rate_table)

# Write tables to excel
# msu_mrkt_rate worksheet
rows = np.cumsum([df.shape[0] + 4 for df in msu_mrkt_rate])
fin_rows = [4] + [data + 4 for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), msu_mrkt_rate):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = mortgage_mrkt_rate_sales_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

mortgage_mrkt_sales_worksheet = daily_drawdown_report_writer.sheets[mortgage_mrkt_rate_sales_sheet_name]
mortgage_mrkt_sales_worksheet.set_zoom(80)
mortgage_mrkt_sales_worksheet.set_tab_color(sheet_tab_color)

month_perc_col = msu_mrkt_rate[0].columns.get_loc('Month_%_Achieved')

month_col = [col for col in msu_mrkt_rate[0].columns if col in month_column_order]
month_column_indices = [msu_mrkt_rate[0].columns.get_loc(col) for col in month_col]

mortgage_mrkt_sales_worksheet.merge_range("A1:B1", "", menu_button_format)
mortgage_mrkt_sales_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

mortgage_mrkt_sales_worksheet.set_column(0,1,11.00)
mortgage_mrkt_sales_worksheet.set_column(2,2,20.00)
mortgage_mrkt_sales_worksheet.set_column(3,3,13.00)
mortgage_mrkt_sales_worksheet.set_column(4,4,18.00)
mortgage_mrkt_sales_worksheet.set_column(5,5,13.00)
mortgage_mrkt_sales_worksheet.set_column(6,8,14.00,million_format)
mortgage_mrkt_sales_worksheet.set_column(10,msu_mrkt_rate[0].shape[1],14.00)
mortgage_mrkt_sales_worksheet.set_column(month_perc_col,month_perc_col,17.00, percent_format)

for (row, title) in zip(fin_rows,roles):
    mortgage_mrkt_sales_worksheet.merge_range(row-1,0,row-1,2, title, delft_blue_fill_format)
    
for i , (row, df) in enumerate(zip(fin_rows, msu_mrkt_rate)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1
    col = 0
    mortgage_mrkt_sales_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
    mortgage_mrkt_sales_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    mortgage_mrkt_sales_worksheet.conditional_format(row + 1, 0, end_row, 5, {'type': 'no_errors','format': lemonchiffon_format})
    mortgage_mrkt_sales_worksheet.conditional_format(row + 1, 6, end_row, 8, {'type': 'no_errors','format': deepskyblue_fill_format})
    mortgage_mrkt_sales_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 1,'format': green_format})
    mortgage_mrkt_sales_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 0.8,'format': amber_format})
    mortgage_mrkt_sales_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '<=','value': 0.8,'format': red_format})
    
    for month_col in month_column_indices:
        mortgage_mrkt_sales_worksheet.conditional_format(row + 1, month_col, end_row, month_col, {'type': 'no_errors','format': million_format})    

mortgage_mrkt_sales_worksheet.freeze_panes(5,6)
print(f"Sheet '{mortgage_mrkt_rate_sales_sheet_name}' is successfully saved.")

# msu_non_mrkt_rate worksheet
rows = np.cumsum([df.shape[0] + 4 for df in msu_non_mrkt_rate])
fin_rows = [4] + [data + 4 for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), msu_non_mrkt_rate):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = mortgage_non_mrkt_rate_sales_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

mortgage_non_mrkt_sales_worksheet = daily_drawdown_report_writer.sheets[mortgage_non_mrkt_rate_sales_sheet_name]
mortgage_non_mrkt_sales_worksheet.set_zoom(80)
mortgage_non_mrkt_sales_worksheet.set_tab_color(sheet_tab_color)

month_perc_col = msu_mrkt_rate[0].columns.get_loc('Month_%_Achieved')

month_col = [col for col in msu_mrkt_rate[0].columns if col in month_column_order]
month_column_indices = [msu_mrkt_rate[0].columns.get_loc(col) for col in month_col]

mortgage_non_mrkt_sales_worksheet.merge_range("A1:B1", "", menu_button_format)
mortgage_non_mrkt_sales_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

mortgage_non_mrkt_sales_worksheet.set_column(0,1,11.00)
mortgage_non_mrkt_sales_worksheet.set_column(2,2,20.00)
mortgage_non_mrkt_sales_worksheet.set_column(3,3,13.00)
mortgage_non_mrkt_sales_worksheet.set_column(4,4,25.00)
mortgage_non_mrkt_sales_worksheet.set_column(5,5,13.00)
mortgage_non_mrkt_sales_worksheet.set_column(6,8,14.00,million_format)
mortgage_non_mrkt_sales_worksheet.set_column(10,msu_non_mrkt_rate[0].shape[1],14.00)
mortgage_non_mrkt_sales_worksheet.set_column(month_perc_col,month_perc_col,17.00, percent_format)

for (row, title) in zip(fin_rows,roles):
    mortgage_non_mrkt_sales_worksheet.merge_range(row-1,0,row-1,2, title, delft_blue_fill_format)
    
for i , (row, df) in enumerate(zip(fin_rows, msu_non_mrkt_rate)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1
    col = 0
    mortgage_non_mrkt_sales_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
    mortgage_non_mrkt_sales_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    mortgage_non_mrkt_sales_worksheet.conditional_format(row + 1, 0, end_row, 5, {'type': 'no_errors','format': lemonchiffon_format})
    mortgage_non_mrkt_sales_worksheet.conditional_format(row + 1, 6, end_row, 8, {'type': 'no_errors','format': deepskyblue_fill_format})
    mortgage_non_mrkt_sales_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 1,'format': green_format})
    mortgage_non_mrkt_sales_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 0.8,'format': amber_format})
    mortgage_non_mrkt_sales_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '<=','value': 0.8,'format': red_format})

    for month_col in month_column_indices:
        mortgage_non_mrkt_sales_worksheet.conditional_format(row + 1, month_col, end_row, month_col, {'type': 'no_errors','format': million_format})    

mortgage_non_mrkt_sales_worksheet.freeze_panes(5,6)
print(f"Sheet '{mortgage_non_mrkt_rate_sales_sheet_name}' is successfully saved.")


# Diaspora Disbursements
diaspora_order = ['DIASPORA', 'NON RESIDENT KENYANS', 'DIASPORA BUSINESS BANKING', 'DIASPORA PERSONAL BANKING', 'DIASPORA ULTIMATE BANKING']

# Gross_values
diaspora_gross_value_table = sum_monthly(loan_drawdown, index = 'SEGMENT', months_column_name = 'MONTH_YR', value_column_name = 'GROSS_DRAWDOWN')
diaspora_gross_value_table = diaspora_gross_value_table[(diaspora_gross_value_table['SEGMENT'].isin(diaspora_order))]
sum_row = diaspora_gross_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'SEGMENT', 'TOTAL')
diaspora_gross_value_table = pd.concat([diaspora_gross_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
diaspora_gross_value_table['YTD_Actual'] = diaspora_gross_value_table[month_column_order].sum(axis=1)
# diaspora_gross_value_table

# Net_Values
diaspora_net_value_table = sum_monthly(loan_drawdown, index = 'SEGMENT', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
diaspora_net_value_table = diaspora_net_value_table[(diaspora_net_value_table['SEGMENT'].isin(diaspora_order))]
sum_row = diaspora_net_value_table.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'SEGMENT', 'TOTAL')
diaspora_net_value_table = pd.concat([diaspora_net_value_table, sum_row], ignore_index = True)
# Get the sum of the month values
diaspora_net_value_table['YTD_Actual'] = diaspora_net_value_table[month_column_order].sum(axis=1)
# diaspora_net_value_table

# Weekly Diaspora values
weekly_diaspora_drawdown = loan_drawdown.loc[loan_drawdown['WEEK'] == week_number]
diaspora_weekly_view = sum(weekly_diaspora_drawdown, index = 'SEGMENT', value_column_name = 'NET_DRAWDOWN')
diaspora_weekly_view = diaspora_weekly_view[(diaspora_weekly_view['SEGMENT'].isin(diaspora_order))]
diaspora_weekly_view.rename(columns = {'NET_DRAWDOWN': 'Weekly'}, inplace=True)
sum_row = diaspora_weekly_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'SEGMENT', 'TOTAL')   
diaspora_weekly_view = pd.concat([diaspora_weekly_view, sum_row], ignore_index = True)
# Check if df is empty
if diaspora_weekly_view.shape == (1,1):
    data = {
        'SEGMENT':['DIASPORA', 'DIASPORA BUSINESS BANKING', 'DIASPORA PERSONAL BANKING', 'DIASPORA ULTIMATE BANKING'],
        'Weekly':[0,0,0,0]
    }
    diaspora_weekly_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# diaspora_weekly_view

# Daily Diaspora values
daily_diaspora_drawdown = loan_drawdown.loc[loan_drawdown['DRAWDOWN_DT'] == max_date]
diaspora_daily_view = sum(daily_diaspora_drawdown, index = 'SEGMENT', value_column_name = 'NET_DRAWDOWN')
diaspora_daily_view = diaspora_daily_view[(diaspora_daily_view['SEGMENT'].isin(diaspora_order))]
diaspora_daily_view.rename(columns = {'NET_DRAWDOWN': 'Daily'}, inplace=True)
sum_row = diaspora_daily_view.iloc[:, 1:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'SEGMENT', 'TOTAL')   
diaspora_daily_view = pd.concat([diaspora_daily_view, sum_row], ignore_index = True)
# Check if df is empty
if diaspora_daily_view.shape == (1,1):
    data = {
        'SEGMENT':['DIASPORA', 'DIASPORA BUSINESS BANKING', 'DIASPORA PERSONAL BANKING', 'DIASPORA ULTIMATE BANKING', 'TOTAL'],
        'Weekly':[0,0,0,0,0]
    }
    diaspora_daily_view = pd.DataFrame(data)
else:
    print('DataFrame is not empty')
# diaspora_daily_view

# Merge net, weekly and daily tables
diaspora_net_value_table = pd.merge(diaspora_net_value_table,diaspora_weekly_view, left_on = 'SEGMENT', right_on = 'SEGMENT', how = 'left')
diaspora_net_value_table = pd.merge(diaspora_net_value_table,diaspora_daily_view, left_on = 'SEGMENT', right_on = 'SEGMENT', how = 'left')
diaspora_net_value_table = diaspora_net_value_table.fillna(0)
# diaspora_net_value_table



# Write tables to excel
all_dfs = [diaspora_gross_value_table,diaspora_net_value_table]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = diaspora_disbursements_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

diaspora_disbursement_worksheet = daily_drawdown_report_writer.sheets[diaspora_disbursements_sheet_name]
diaspora_disbursement_worksheet.set_zoom(80)
diaspora_disbursement_worksheet.set_tab_color(sheet_tab_color)

diaspora_disbursement_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'GROSS PER SEGMENT', delft_blue_fill_format)
diaspora_disbursement_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'NET PER SEGMENT', delft_blue_fill_format)

diaspora_disbursement_worksheet.merge_range("A1:B1", "", menu_button_format)
diaspora_disbursement_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

diaspora_disbursement_worksheet.set_column(0,0,30.00)
diaspora_disbursement_worksheet.set_column(1,diaspora_net_value_table.shape[1]-1,15.00)

for row, df in zip(fin_rows[:1], [diaspora_gross_value_table]):     
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    diaspora_disbursement_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    diaspora_disbursement_worksheet.conditional_format(row + 1, end_col, end_row, end_col, {'type': 'no_errors', 'format': bold_format})
    diaspora_disbursement_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    diaspora_disbursement_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    diaspora_disbursement_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    diaspora_disbursement_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})

for row, df in zip(fin_rows[-1:], [diaspora_net_value_table]):  
    end_row = df.shape[0] + row
    end_col = df.shape[1] - 1
    col = 0
    diaspora_disbursement_worksheet.conditional_format(row + 1, col + 1, end_row, end_col, {'type': 'no_errors', 'format': million_format})
    diaspora_disbursement_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
    diaspora_disbursement_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    diaspora_disbursement_worksheet.conditional_format(row + 1, col, end_row, col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
    diaspora_disbursement_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    diaspora_disbursement_worksheet.conditional_format(row + 1, end_col - 2, end_row, end_col -2, {'type': 'no_errors', 'format': bold_format})
    diaspora_disbursement_worksheet.conditional_format(row + 1, end_col - 1, end_row, end_col, {'type': 'no_errors', 'format': lavender_fill_format})

diaspora_disbursement_worksheet.freeze_panes(5,1)
print(f"Sheet '{diaspora_disbursements_sheet_name}' is successfully saved.")

# Tenor Disbursements
# Segment Tenor Disbursements
tenor_segment_value_table = segment_value(loan_drawdown, index = ['BANKING_SEGMENT', 'TERM'], months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# tenor_segment_value_table.head(2)

tenor_segment_value_table = tenor_segment_value_table.reset_index()
bb_product_tenor = tenor_segment_value_table[tenor_segment_value_table['BANKING_SEGMENT'] == 'BUSINESS']
commercial_product_tenor = tenor_segment_value_table[tenor_segment_value_table['BANKING_SEGMENT'] == 'COMMERCIAL']
diaspora_product_tenor = tenor_segment_value_table[tenor_segment_value_table['BANKING_SEGMENT'] == 'DIASPORA']
personal_product_tenor = tenor_segment_value_table[tenor_segment_value_table['BANKING_SEGMENT'] == 'PERSONAL']
ultimate_product_tenor = tenor_segment_value_table[tenor_segment_value_table['BANKING_SEGMENT'] == 'ULTIMATE']

def process_tenor_seg(df, main_category, month_column_order):
    """Processes a product segmentation DataFrame to include totals and percentage calculations."""
    
    # Ensure the DataFrame is not empty
    if df.empty:
        data = {
            'BANKING_SEGMENT': [main_category],  # Dynamically set BANKING_SEGMENT category
            'TERM': [''],
            'YTD_Actual': [0]
        }
        for column in month_column_order:
            data[column] = [0]
        df = pd.DataFrame(data)
    else:
        df = df.copy()
        df = df.assign(BANKING_SEGMENT = main_category)

    # Compute total category sum
    df_total = df.copy()
    df_total['TERM'] = 'TOTAL'
    df_total = df_total.groupby(['BANKING_SEGMENT', 'TERM'], as_index = False).sum()
    
    # Combine original and total DataFrames
    df_combined = pd.concat([df, df_total], ignore_index = True)

    # Compute percentage values
    if 'YTD_Actual' not in df_combined.columns:
        raise ValueError("DataFrame does not contain 'YTD_Actual' column.")
    
    max_value = df_combined['YTD_Actual'].max()
    if max_value == 0:
        df_combined['% Per Criteria'] = None
    else:
        df_combined['% Per Criteria'] = df_combined['YTD_Actual'] / max_value

    # Ensure rows with max value have NaN percentage
    df_combined.loc[df_combined['YTD_Actual'] == max_value, '% Per Criteria'] = None

    # create rank on % values
    df_combined['Rank'] = None
    df_combined.iloc[:-1, df_combined.columns.get_loc('Rank')] = df_combined.iloc[:-1]['% Per Criteria'].rank(method = 'dense', ascending = False)
    df_combined = df_combined.sort_values(by = 'Rank')
    df_combined = df_combined.drop(columns = 'Rank')

    # Order columns properly
    ordered_columns = ['BANKING_SEGMENT', 'TERM'] + month_column_order + ['YTD_Actual', '% Per Criteria']
    return df_combined[ordered_columns]

# Define DataFrames and their respective BANKING_SEGMENT categories
tenor_dataframes = {
    "BUSINESS": bb_product_tenor,
    "COMMERCIAL": commercial_product_tenor,
    "DIASPORA": diaspora_product_tenor,
    "PERSONAL": personal_product_tenor,
    "ULTIMATE": ultimate_product_tenor
}
# Concatenate all dataframes
processed_dfs_4 = [process_tenor_seg(df, BANKING_SEGMENT, month_column_order) for BANKING_SEGMENT, df in tenor_dataframes.items()]
total_tenor_seg_summ = pd.concat(processed_dfs_4, ignore_index=True, verify_integrity=True)

# Get grand total row
# Get the total rows (assuming they're the last row of each df)
tenor_total_rows = [df.iloc[[-1], 1:-1] for df in processed_dfs_4]
# Concatenate those total rows into a new dataframe
tenor_totals_df = pd.concat(tenor_total_rows, ignore_index = True)
# Sum the total rows to get grand total
tenor_grand_total = tenor_totals_df.select_dtypes(include = 'number').sum(numeric_only = True)
# Create a new row with "Grand Total" as the index or a label in one column
tenor_grand_total_row = tenor_totals_df.iloc[0].copy()
tenor_grand_total_row.loc[tenor_grand_total.index] = tenor_grand_total
# Label the row appropriately (assuming first column is 'Label' or similar)
if 'TERM' in total_tenor_seg_summ.columns:
    tenor_grand_total_row['TERM'] = 'GRAND TOTAL'

# Append grand total row to the combined dataframe
total_tenor_seg_summ_final = pd.concat([total_tenor_seg_summ, pd.DataFrame([tenor_grand_total_row])], ignore_index=True)
# total_tenor_seg_summ_final.tail(4)

total_tenor_seg_summ_2 = total_tenor_seg_summ_final.copy()
total_tenor_seg_summ_2 = total_tenor_seg_summ_2.set_index(['BANKING_SEGMENT', 'TERM'])
# total_tenor_seg_summ_2.head()

value_to_find = 'TOTAL'
total_row_numbers = total_tenor_seg_summ_final.index[total_tenor_seg_summ_final['TERM'] == value_to_find].tolist()

start_row = 4
end_row = total_tenor_seg_summ_2.shape[0] + start_row
start_col = 0
end_col = total_tenor_seg_summ_2.shape[1]+1
title_cols = 1
tenor_perc_col = total_tenor_seg_summ_2.shape[1]+1

total_tenor_seg_summ_2.to_excel(daily_drawdown_report_writer, sheet_name = tenor_disbursements_sheet_name, index = True, startrow = start_row, startcol = start_col)

segments_per_tenor_category_worksheet = daily_drawdown_report_writer.sheets[tenor_disbursements_sheet_name]
segments_per_tenor_category_worksheet.set_zoom(80)
segments_per_tenor_category_worksheet.set_tab_color(sheet_tab_color)

segments_per_tenor_category_worksheet.merge_range(start_row-1,0,start_row-1,2, 'TERM PER SEGMENT', delft_blue_fill_format)

segments_per_tenor_category_worksheet.merge_range("A1:B1", "", menu_button_format)
segments_per_tenor_category_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

segments_per_tenor_category_worksheet.set_column(0,1,20.00)
segments_per_tenor_category_worksheet.set_column(2,total_tenor_seg_summ_2.shape[1],20.00,comma_format)
segments_per_tenor_category_worksheet.set_column(total_tenor_seg_summ_2.shape[1]+1,total_tenor_seg_summ_2.shape[1]+1,20.00, percent_format)

segments_per_tenor_category_worksheet.conditional_format(start_row, start_col, start_row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
segments_per_tenor_category_worksheet.conditional_format(start_row+1, start_col, end_row, start_col, {'type': 'no_errors','format': deepskyblue_fill_format})
segments_per_tenor_category_worksheet.conditional_format(start_row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
segments_per_tenor_category_worksheet.conditional_format(start_row+1, end_col-1, end_row, end_col-1, {'type': 'no_errors','format': bold_format})
segments_per_tenor_category_worksheet.conditional_format(end_row, start_col, end_row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

for row_num in total_row_numbers:
    row = row_num + title_cols + 4
    segments_per_tenor_category_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

perc_col = tenor_perc_col
segments_per_tenor_category_worksheet.conditional_format(start_row+1, perc_col, end_row, perc_col, color_scale)

segments_per_tenor_category_worksheet.freeze_panes(5,2)
print(f"Sheet '{tenor_disbursements_sheet_name}' is successfully saved.")


# Sector Disbursements
# Financial_sector per economic_sector
sector_order = ['PRIMARY SECTOR', 'SECONDARY SECTOR', 'TERTIARY SECTOR', 'QUATERMARY SECTOR', 'OTHERS']

economic_sector_value_table = segment_value(loan_drawdown, index = ['ECONOMIC_SECTOR', 'FINANCIAL_SECTOR'], months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
economic_sector_value_table = economic_sector_value_table.reset_index()
economic_sector_value_table = economic_sector_value_table[economic_sector_value_table['ECONOMIC_SECTOR'].isin(sector_order)]
economic_sector_value_table['ECONOMIC_SECTOR'] = pd.Categorical(economic_sector_value_table['ECONOMIC_SECTOR'], categories = sector_order, ordered = True)
economic_sector_value_table = economic_sector_value_table.sort_values(by = 'ECONOMIC_SECTOR')
# economic_sector_value_table.head(2)

primary_sec = economic_sector_value_table[economic_sector_value_table['ECONOMIC_SECTOR'] == 'PRIMARY SECTOR']
secondary_sec = economic_sector_value_table[economic_sector_value_table['ECONOMIC_SECTOR'] == 'SECONDARY SECTOR']
tertiary_sec = economic_sector_value_table[economic_sector_value_table['ECONOMIC_SECTOR'] == 'TERTIARY SECTOR']
quatermary_sec = economic_sector_value_table[economic_sector_value_table['ECONOMIC_SECTOR'] == 'QUATERMARY SECTOR']
others_sec = economic_sector_value_table[economic_sector_value_table['ECONOMIC_SECTOR'] == 'OTHERS']

def process_economic_sector(df, main_category, month_column_order):
    """Processes an economic sector DataFrame to include totals."""
    
    # Ensure the DataFrame is not empty
    if df.empty:
        data = {
            'ECONOMIC_SECTOR': [main_category],  # Dynamically set BANKING_SEGMENT category
            'FINANCIAL_SECTOR': [''],
            'YTD_Actual': [0]
        }
        for column in month_column_order:
            data[column] = [0]
        df = pd.DataFrame(data)
    else:
        df = df.copy()
        df = df.assign(ECONOMIC_SECTOR = main_category)

    # Compute total category sum
    df_total = df.copy()
    df_total['FINANCIAL_SECTOR'] = 'TOTAL'
    df_total = df_total.groupby(['ECONOMIC_SECTOR', 'FINANCIAL_SECTOR'], as_index=False).sum()
    
    # Combine original and total DataFrames
    df_combined = pd.concat([df, df_total], ignore_index=True)

    # # Compute percentage values
    # if 'YTD_Actual' not in df_combined.columns:
    #     raise ValueError("DataFrame does not contain 'YTD_Actual' column.")
    
    # max_value = df_combined['YTD_Actual'].max()
    # if max_value == 0:
    #     df_combined['% Per Sector'] = None
    # else:
    #     df_combined['% Per Sector'] = df_combined['YTD_Actual'] / max_value

    # # Ensure rows with max value have NaN percentage
    # df_combined.loc[df_combined['YTD_Actual'] == max_value, '% Per Sector'] = None

    # # create rank on % values
    # df_combined['Rank'] = None
    # df_combined.iloc[:-1, df_combined.columns.get_loc('Rank')] = df_combined.iloc[:-1]['% Per Sector'].rank(method = 'dense', ascending = False)
    # df_combined = df_combined.sort_values(by = 'Rank')
    # df_combined = df_combined.drop(columns = 'Rank')

    # Order columns properly
    ordered_columns = ['ECONOMIC_SECTOR', 'FINANCIAL_SECTOR'] + month_column_order + ['YTD_Actual'] #, '% Per Sector' ]
    return df_combined[ordered_columns]

# Define DataFrames and their respective BANKING_SEGMENT categories
economic_sector_dataframes = {
    "PRIMARY SECTOR": primary_sec,
    "SECONDARY SECTOR": secondary_sec,
    "TERTIARY SECTOR": tertiary_sec,
    "QUATERMARY SECTOR": quatermary_sec,
    "OTHERS": others_sec
}
# Concatenate all dataframes
processed_dfs_5 = [process_economic_sector(df, BANKING_SEGMENT, month_column_order) for BANKING_SEGMENT, df in economic_sector_dataframes.items()]
total_economic_sec_summ = pd.concat(processed_dfs_5, ignore_index=True, verify_integrity=True)

# Get grand total row
# Get the total rows (assuming they're the last row of each df)
economic_total_rows = [df.iloc[[-1], 1:] for df in processed_dfs_5]
# Concatenate those total rows into a new dataframe
economic_totals_df = pd.concat(economic_total_rows, ignore_index = True)
# Sum the total rows to get grand total
economic_grand_total = economic_totals_df.select_dtypes(include = 'number').sum(numeric_only = True)
# Create a new row with "Grand Total" as the index or a label in one column
economic_grand_total_row = economic_totals_df.iloc[0].copy()
economic_grand_total_row.loc[economic_grand_total.index] = economic_grand_total
# Label the row appropriately (assuming first column is 'Label' or similar)
if 'FINANCIAL_SECTOR' in total_economic_sec_summ.columns:
    economic_grand_total_row['FINANCIAL_SECTOR'] = 'GRAND TOTAL'

# Append grand total row to the combined dataframe
total_economic_sec_summ_final = pd.concat([total_economic_sec_summ, pd.DataFrame([economic_grand_total_row])], ignore_index=True)
# total_economic_sec_summ_final.tail(2)

total_economic_sec_summ_2 = total_economic_sec_summ_final.copy()
total_economic_sec_summ_2 = total_economic_sec_summ_2.set_index(['ECONOMIC_SECTOR', 'FINANCIAL_SECTOR'])
# total_economic_sec_summ_2.head(2)


# Financial_sector per segment
segment_sector_value_table = segment_value(loan_drawdown, index = ['BANKING_SEGMENT', 'FINANCIAL_SECTOR'], months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
segment_sector_value_table = segment_sector_value_table.reset_index()
# segment_sector_value_table.head(2)

business_sec = segment_sector_value_table[segment_sector_value_table['BANKING_SEGMENT'] == 'BUSINESS']
commercial_sec = segment_sector_value_table[segment_sector_value_table['BANKING_SEGMENT'] == 'COMMERCIAL']
diaspora_sec = segment_sector_value_table[segment_sector_value_table['BANKING_SEGMENT'] == 'DIASPORA']
personal_sec = segment_sector_value_table[segment_sector_value_table['BANKING_SEGMENT'] == 'PERSONAL']
ultimate_sec = segment_sector_value_table[segment_sector_value_table['BANKING_SEGMENT'] == 'ULTIMATE']

def process_segment_sector(df, main_category, month_column_order):
    """Processes an segment financial sector DataFrame to include totals."""
    
    # Ensure the DataFrame is not empty
    if df.empty:
        data = {
            'BANKING_SEGMENT': [main_category],  # Dynamically set BANKING_SEGMENT category
            'FINANCIAL_SECTOR': [''],
            'YTD_Actual': [0]
        }
        for column in month_column_order:
            data[column] = [0]
        df = pd.DataFrame(data)
    else:
        df = df.copy()
        df = df.assign(BANKING_SEGMENT = main_category)

    # Compute total category sum
    df_total = df.copy()
    df_total['FINANCIAL_SECTOR'] = 'TOTAL'
    df_total = df_total.groupby(['BANKING_SEGMENT', 'FINANCIAL_SECTOR'], as_index=False).sum()
    
    # Combine original and total DataFrames
    df_combined = pd.concat([df, df_total], ignore_index=True)

    # # Compute percentage values
    # if 'YTD_Actual' not in df_combined.columns:
    #     raise ValueError("DataFrame does not contain 'YTD_Actual' column.")
    
    # max_value = df_combined['YTD_Actual'].max()
    # if max_value == 0:
    #     df_combined['% Per Segment'] = None
    # else:
    #     df_combined['% Per Segment'] = df_combined['YTD_Actual'] / max_value

    # # Ensure rows with max value have NaN percentage
    # df_combined.loc[df_combined['YTD_Actual'] == max_value, '% Per Segment'] = None

    # # create rank on % values
    # df_combined['Rank'] = None
    # df_combined.iloc[:-1, df_combined.columns.get_loc('Rank')] = df_combined.iloc[:-1]['% Per Segment'].rank(method = 'dense', ascending = False)
    # df_combined = df_combined.sort_values(by = 'Rank')
    # df_combined = df_combined.drop(columns = 'Rank')

    # Order columns properly
    ordered_columns = ['BANKING_SEGMENT', 'FINANCIAL_SECTOR'] + month_column_order + ['YTD_Actual'] #, '% Per Segment' ]
    return df_combined[ordered_columns]

# Define DataFrames and their respective BANKING_SEGMENT categories
segment_sector_dataframes = {
    "BUSINESS": business_sec,
    "COMMERCIAL": commercial_sec,
    "DIASPORA": diaspora_sec,
    "PERSONAL": personal_sec,
    "ULTIMATE": ultimate_sec
}
# Concatenate all dataframes
processed_dfs_6 = [process_segment_sector(df, BANKING_SEGMENT, month_column_order) for BANKING_SEGMENT, df in segment_sector_dataframes.items()]
total_segment_sec_summ = pd.concat(processed_dfs_6, ignore_index=True, verify_integrity=True)

# Get grand total row
# Get the total rows (assuming they're the last row of each df)
segment_total_rows = [df.iloc[[-1], 1:] for df in processed_dfs_6]
# Concatenate those total rows into a new dataframe
segment_totals_df = pd.concat(segment_total_rows, ignore_index = True)
# Sum the total rows to get grand total
segment_grand_total = segment_totals_df.select_dtypes(include = 'number').sum(numeric_only = True)
# Create a new row with "Grand Total" as the index or a label in one column
segment_grand_total_row = segment_totals_df.iloc[0].copy()
segment_grand_total_row.loc[segment_grand_total.index] = segment_grand_total
# Label the row appropriately (assuming first column is 'Label' or similar)
if 'FINANCIAL_SECTOR' in total_segment_sec_summ.columns:
    segment_grand_total_row['FINANCIAL_SECTOR'] = 'GRAND TOTAL'

# Append grand total row to the combined dataframe
total_segment_sec_summ_final = pd.concat([total_segment_sec_summ, pd.DataFrame([segment_grand_total_row])], ignore_index=True)
# total_segment_sec_summ_final.tail(2)

total_segment_sec_summ_2 = total_segment_sec_summ_final.copy()
total_segment_sec_summ_2 = total_segment_sec_summ_2.set_index(['BANKING_SEGMENT', 'FINANCIAL_SECTOR'])
# total_segment_sec_summ_2.head(2)


# Write tables to excel
value_to_find = 'TOTAL'
df1_row_numbers = total_economic_sec_summ_final.index[total_economic_sec_summ_final['FINANCIAL_SECTOR'] == value_to_find].tolist()
df2_row_numbers = total_segment_sec_summ_final.index[total_segment_sec_summ_final['FINANCIAL_SECTOR'] == value_to_find].tolist()
total_row_numbers = [df1_row_numbers, df2_row_numbers]


all_dfs = [total_economic_sec_summ_2, total_segment_sec_summ_2]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = sector_disbursements_sheet_name, index = True, startrow = fin_rows[row], startcol = start_col)

sector_disbursements_worksheet = daily_drawdown_report_writer.sheets[sector_disbursements_sheet_name]
sector_disbursements_worksheet.set_zoom(80)
sector_disbursements_worksheet.set_tab_color(sheet_tab_color)

sector_disbursements_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'NET VALUES', delft_blue_fill_format)
sector_disbursements_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'NET VALUES' , delft_blue_fill_format)

sector_disbursements_worksheet.merge_range("A1:B1", "", menu_button_format)
sector_disbursements_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

sector_disbursements_worksheet.set_column(0,0,20.20)
sector_disbursements_worksheet.set_column(1,1,42.00)
sector_disbursements_worksheet.set_column(2,total_mortgage_seg_summ_2.shape[1],20.00,comma_format)

for idx, (row, df) in enumerate(zip(fin_rows, all_dfs)):
    end_row = df.shape[0] + row
    end_col = df.shape[1] + 1
    col = 0

    if idx == 0:  # Conditional formatting for the first dataframe
        sector_disbursements_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
        sector_disbursements_worksheet.conditional_format(row+1, col, end_row, col, {'type': 'no_errors','format': deepskyblue_fill_format})
        sector_disbursements_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
        sector_disbursements_worksheet.conditional_format(row+1, end_col, end_row, end_col, {'type': 'no_errors','format': bold_format})
        sector_disbursements_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})

    elif idx == 1:  # Conditional formatting for the second dataframe
        sector_disbursements_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
        sector_disbursements_worksheet.conditional_format(row+1, col, end_row, col, {'type': 'no_errors','format': deepskyblue_fill_format})
        sector_disbursements_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
        sector_disbursements_worksheet.conditional_format(row+1, end_col, end_row, end_col, {'type': 'no_errors','format': bold_format})
        sector_disbursements_worksheet.conditional_format(end_row, col, end_row, end_col, {'type': 'no_errors','format': deepskyblue_fill_format})


    # Format "TOTAL" rows differently for each dataframe
    rows_to_format = []
    if idx == 0:
        rows_to_format = [r + row + 1 for r in df1_row_numbers]
        total_row_format = {'type': 'no_errors', 'format': deepskyblue_fill_format}
    elif idx == 1:
        rows_to_format = [r + row + 1 for r in df2_row_numbers]
        total_row_format = {'type': 'no_errors', 'format': deepskyblue_fill_format}

    for total_row in rows_to_format:
        sector_disbursements_worksheet.conditional_format(total_row, col, total_row, end_col, total_row_format)

sector_disbursements_worksheet.freeze_panes(5,2)
print(f"Sheet '{sector_disbursements_sheet_name}' is successfully saved.")


# Loan_Productivity worksheet
# Role Count Tables
role_count_map_df = process_role_count_df(role_count_map, year)
focus_role_count_map = role_count_map_df.copy()
focus_role_count_map = focus_role_count_map.groupby('Role').sum()
focus_role_count_map = focus_role_count_map.reset_index()
# focus_role_count_map.head(3)

role_order = ['COMMERCIAL RM', 'DIASPORA ARM', 'DIASPORA RM', 'MORTGAGE ARM', 'Others', 'PB ARM', 'PB BBC', 'PB DSR', 'PB RM', 'SME ARM', 'SME BBC', 'SME DSR', 'SME RM', 'ULTIMATE RM']

curr_role_count = focus_role_count_map.copy()
curr_role_count['Curr_Head_Count'] = curr_role_count[month_column_order[-1]]
curr_role_count = curr_role_count.reindex(['Curr_Head_Count','Role'] + month_column_order,axis=1)
curr_role_count = curr_role_count[curr_role_count['Role'].isin(role_order)]
curr_role_count['Role'] = pd.Categorical(curr_role_count['Role'], categories = role_order, ordered = True)
curr_role_count = curr_role_count.sort_values(by='Role')
curr_role_count = curr_role_count.set_index(['Curr_Head_Count'])
curr_role_count = curr_role_count.reset_index()
# curr_role_count

# Volume Tables
loan_productivity_vol_table = count_monthly(loan_drawdown, index = 'ROLE', months_column_name = 'MONTH_YR', value_column_name = 'GROSS_DRAWDOWN')
loan_productivity_vol_table = loan_productivity_vol_table[(loan_productivity_vol_table['ROLE'].isin(role_order))]
# loan_productivity_vol_table

# Head count on Volume
head_count_volume = loan_productivity_vol_table.copy()
head_count_volume.fillna(0, inplace = True)

head_count_volume = pd.merge(head_count_volume, curr_role_count[['Role', 'Curr_Head_Count']], left_on = 'ROLE', right_on = 'Role', how = 'left')
head_count_volume.drop(columns = ['Role'], inplace = True)
head_count_volume.fillna(0, inplace = True)
cols_to_front = ['Curr_Head_Count']
remaining_cols = [col for col in head_count_volume.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols
head_count_volume = head_count_volume[new_order]
# head_count_volume    

# head_count_productivity on Volume
head_count_volume_productivity = head_count_volume.copy()
# Dividing the value of sales by the count of people in the given role
for month in month_column_order:
    head_count_volume_productivity[month] = head_count_volume[month] / head_count_volume['Curr_Head_Count']
    
head_count_volume_productivity = head_count_volume_productivity.replace([np.inf, -np.inf], np.nan)
head_count_volume_productivity.fillna(0, inplace = True)
# head_count_volume_productivity

# Value Tables
loan_productivity_val_table = sum_monthly(loan_drawdown, index = 'ROLE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
loan_productivity_val_table = loan_productivity_val_table[(loan_productivity_val_table['ROLE'].isin(role_order))]
# loan_productivity_val_table

# Head Count on Value
head_count_value = loan_productivity_val_table
head_count_value.fillna(0, inplace = True)

head_count_value = pd.merge(head_count_value, curr_role_count[['Role', 'Curr_Head_Count']], left_on = 'ROLE', right_on = 'Role', how = 'left')
head_count_value.drop(columns = ['Role'], inplace = True)
head_count_value.fillna(0, inplace = True)
cols_to_front = ['Curr_Head_Count']
remaining_cols = [col for col in head_count_value.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols
head_count_value = head_count_value[new_order]
# head_count_value

# head_count_productivity on Value
head_count_value_productivity = head_count_value.copy()
# Dividing the value of sales by the count of people in the given role
for month in month_column_order:
    head_count_value_productivity[month] = head_count_value[month] / head_count_value['Curr_Head_Count']
    
head_count_value_productivity = head_count_value_productivity.replace([np.inf, -np.inf], np.nan)
head_count_value_productivity.fillna(0, inplace = True)
# head_count_value_productivity

# Write the tables to excel
all_dfs = [head_count_volume,head_count_volume_productivity,head_count_value,head_count_value_productivity]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]


for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = loan_productivity_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

loan_productivity_worksheet = daily_drawdown_report_writer.sheets[loan_productivity_sheet_name]
loan_productivity_worksheet.set_zoom(80)
loan_productivity_worksheet.set_tab_color(sheet_tab_color)

loan_productivity_worksheet.merge_range(fin_rows[0]-1,0,fin_rows[0]-1,1, 'VOLUME', delft_blue_fill_format)
loan_productivity_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'VOLUME PRODUCTIVITY', delft_blue_fill_format)
loan_productivity_worksheet.merge_range(fin_rows[2]-1,0,fin_rows[2]-1,1, 'VALUE', delft_blue_fill_format)
loan_productivity_worksheet.merge_range(fin_rows[3]-1,0,fin_rows[3]-1,1, 'VALUE PRODUCTIVITY', delft_blue_fill_format)

loan_productivity_worksheet.merge_range("A1:B1", "", menu_button_format)
loan_productivity_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

loan_productivity_worksheet.set_column(0,0,17.00)
loan_productivity_worksheet.set_column(1,1,20.00)
loan_productivity_worksheet.set_column(2,head_count_volume.shape[1],20.00,comma_format)


for row, df in zip(fin_rows, all_dfs):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1
    start_col = 0
    
    loan_productivity_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
    loan_productivity_worksheet.conditional_format(row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    
loan_productivity_worksheet.freeze_panes(5,2)
print(f"Sheet '{loan_productivity_sheet_name}' is successfully saved.")


# Weekly_Productivity worksheet
# Weekly view per segment
weekly_drawdown = loan_drawdown[loan_drawdown['MONTH_YR'] == max_month_name].copy()
weekly_segment_view = sum_undefined(weekly_drawdown, index = 'BANKING_SEGMENT', column_name = 'WEEK_MONTH', value_column_name = 'GROSS_DRAWDOWN')
weekly_segment_view = weekly_segment_view[(weekly_segment_view['BANKING_SEGMENT'].isin(banking_segment_order))]
weekly_segment_view.rename(columns={'BANKING_SEGMENT' : 'SEGMENT'}, inplace = True)
# weekly_segment_view


# Weekly view per role value
weekly_role_value_view = sum_undefined(weekly_drawdown, index ='ROLE', column_name ='WEEK_MONTH', value_column_name = 'NET_DRAWDOWN')
weekly_role_value_view = weekly_role_value_view[(weekly_role_value_view['ROLE'].isin(role_order))]
# weekly_role_value_view.head(2)

# Merge to get the current head count
weekly_role_value_view = pd.merge(weekly_role_value_view, curr_role_count[['Role', 'Curr_Head_Count']], left_on = 'ROLE', right_on = 'Role', how = 'left')
weekly_role_value_view.drop(columns = ['Role'], inplace = True)
weekly_role_value_view.fillna(0, inplace = True)
cols_to_front = ['Curr_Head_Count']
remaining_cols = [col for col in weekly_role_value_view.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols
weekly_role_value_view = weekly_role_value_view[new_order]
# weekly_role_value_view.head(2)

week_list = weekly_drawdown['WEEK_MONTH'].drop_duplicates().tolist()
week_list


# Weekly productivity
weekly_role_productivity = weekly_role_value_view.copy()
# Dividing the value of sales by the count of people in the given role
for week in week_list:
    weekly_role_productivity[week] = weekly_role_value_view[week] / weekly_role_value_view['Curr_Head_Count']

weekly_role_productivity = weekly_role_productivity.replace([np.inf, -np.inf], np.nan)
weekly_role_productivity.fillna(0, inplace = True)
# weekly_role_productivity.head(2)


# Write tables to excel
all_dfs = [weekly_segment_view, weekly_role_value_view, weekly_role_productivity]
rows = np.cumsum([df.shape[0] + 4 for df in all_dfs])
fin_rows = [4] + [data + 4 for data in rows[:len(rows) - 1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), all_dfs):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = weekly_productivity_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

weekly_productivity_worksheet = daily_drawdown_report_writer.sheets[weekly_productivity_sheet_name]
weekly_productivity_worksheet.set_zoom(80)
weekly_productivity_worksheet.set_tab_color(sheet_tab_color)

weekly_productivity_worksheet.merge_range(fin_rows[1]-1,0,fin_rows[1]-1,1, 'VALUE', delft_blue_fill_format)
weekly_productivity_worksheet.merge_range(fin_rows[2]-1,0,fin_rows[2]-1,1, 'VALUE PRODUCTIVITY', delft_blue_fill_format)

weekly_productivity_worksheet.merge_range("A1:B1", "", menu_button_format)
weekly_productivity_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')


weekly_productivity_worksheet.set_column(0,0,17.00)
weekly_productivity_worksheet.set_column(1,1,20.00)
weekly_productivity_worksheet.set_column(1,weekly_segment_view.shape[1],20.00,comma_format)
weekly_productivity_worksheet.set_column(2,head_count_volume.shape[1],20.00,comma_format)


for row, df in zip(fin_rows, all_dfs):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1
    start_col = 0
    
    weekly_productivity_worksheet.conditional_format(row, start_col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
    weekly_productivity_worksheet.conditional_format(row, start_col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    
print(f"Sheet '{weekly_productivity_sheet_name}' is successfully saved.")


# Product_View worksheet
product_view_map = loan_drawdown[['ID_PRODUCT','PRODUCT_NAME', 'SECURITY']]
product_view_map = product_view_map.drop_duplicates(subset = ['ID_PRODUCT'])
print(product_view_map.shape)


# Monthly product drawdowns
product_view_data_table = sum_monthly(loan_drawdown, index = 'ID_PRODUCT', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# product_view_data_table.tail(2)
product_view_data_table.shape

# Merge with map
product_view_table = pd.merge(product_view_map, product_view_data_table, left_on = 'ID_PRODUCT', right_on = 'ID_PRODUCT', how = 'left')
# product_view_table.drop(columns = ['ID_PRODUCT'], inplace = True)
product_view_table.fillna(0, inplace = True)

# Calculate the sum of the month columns and create a new row
sum_row = product_view_table.iloc[:, 3:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'ID_PRODUCT', '')  
sum_row.insert(1, 'PRODUCT_NAME', '')  
sum_row.insert(2, 'SECURITY', 'TOTAL')
# Append the total row to the DataFrame
product_view_table = pd.concat([product_view_table, sum_row], ignore_index = True)
# Adding a 'Total' column that sums across the rows
product_view_table['YTD_Actual'] = product_view_table.iloc[:, 3:].sum(axis=1)
# product_view_table.tail(3)

# Create rank column
product_view_table['Rank'] = None
# Calculate the rank separately and then assign it to the 'Rank' column, excluding the last row
ranks = product_view_table.iloc[:-1]['YTD_Actual'].rank(method='dense', ascending=False)
product_view_table.iloc[:-1, product_view_table.columns.get_loc('Rank')] = ranks
# Sort the DataFrame by 'Rank', excluding the Total row from the sorting
product_view_table = product_view_table.sort_values(by='Rank', na_position='last')

cols_to_front = ['Rank']
remaining_cols = [col for col in product_view_table.columns if col not in cols_to_front]
new_order = cols_to_front + remaining_cols

product_view_table = product_view_table[new_order]
# product_view_table.head()
print(product_view_table.shape)


# Writing the table to excel (Product_view)
start_row = 4
start_col = 0

product_view_table.to_excel(daily_drawdown_report_writer, sheet_name = products_view_sheet_name, startrow = start_row, startcol = start_col, index = False, header = True),

product_view_worksheet = daily_drawdown_report_writer.sheets[products_view_sheet_name]
product_view_worksheet.set_zoom(80)
product_view_worksheet.set_tab_color(sheet_tab_color)

max_col = product_view_table.shape[1] - 1
max_row = product_view_table.shape[0] + start_row

product_view_worksheet.merge_range("A1:B1", "", menu_button_format)
product_view_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

product_view_worksheet.merge_range(start_row-1,4,start_row-1,max_col-1, 'MOM DISBURSEMENT', delft_blue_fill_format)

product_view_worksheet.autofilter(start_row, start_col, start_row, max_col)
 
product_view_worksheet.set_column(0,0,10.00)
product_view_worksheet.set_column(1,1,11.00)
product_view_worksheet.set_column(2,2,44.00)
product_view_worksheet.set_column(3,3,13.00)
product_view_worksheet.set_column(4,max_col,15.30)

product_view_worksheet.conditional_format(start_row,0,start_row,max_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
product_view_worksheet.conditional_format(start_row+1,0,max_row,3, {'type': 'no_errors', 'format': deepskyblue_fill_format})
product_view_worksheet.conditional_format(start_row+1,4,max_row,max_col, {'type': 'no_errors', 'format': million_format})
product_view_worksheet.conditional_format(start_row,0,max_row,max_col, {'type': 'no_errors', 'format': border_format})
product_view_worksheet.conditional_format(max_row,4,max_row,max_col, {'type': 'no_errors', 'format': bold_format})

product_view_worksheet.freeze_panes(5, 4)
print(f"Sheet '{products_view_sheet_name}' is successfully saved.")



# Schemes_Loans worksheet
schemes_loans_map = loan_drawdown[['FKGD_CATEGORY','DESCRIPTION']]
schemes_loans_map = schemes_loans_map.dropna(subset = ['FKGD_CATEGORY'])
schemes_loans_map = schemes_loans_map.drop_duplicates(subset = ['FKGD_CATEGORY'])
# print("printing table schemes_loans_map")
# print(schemes_loans_map.shape)
# print(schemes_loans_map.head(3))

# Monthly scheme drawdowns
scheme_loans_data_table = sum_monthly(loan_drawdown, months_column_name='MONTH_YR', index='FKGD_CATEGORY', value_column_name='NET_DRAWDOWN')
#print(scheme_loans_data_table.head(5))
#print("shape of scheme_loans_data_table")
#print(scheme_loans_data_table.shape)

# Merge with map
scheme_loans_table = pd.merge(schemes_loans_map, scheme_loans_data_table, left_on = 'FKGD_CATEGORY', right_on = 'FKGD_CATEGORY', how = 'left')
# scheme_loans_table.drop(columns = ['FKGD_CATEGORY'], inplace = True)
scheme_loans_table.fillna(0, inplace = True)
# scheme_loans_table.head(2)


# Calculate funded vs undunded schemes
def calculate_funded(row, funded_check):
    code = row['FKGD_CATEGORY']
    filtered_df = loan_drawdown[(loan_drawdown['FUNDED_CHECK'] == funded_check) & (loan_drawdown['FKGD_CATEGORY'] == code)]
    return filtered_df['NET_DRAWDOWN'].sum()

# Ensure scheme_loans_table is a copy of the DataFrame, not a view
scheme_loans_table = scheme_loans_table.copy()
# Apply function and use .loc to set values
scheme_loans_table.loc[:, 'Funded'] = scheme_loans_table.apply(lambda row: calculate_funded(row, 'Y'), axis=1)
scheme_loans_table.loc[:, 'Non-Funded'] = scheme_loans_table.apply(lambda row: calculate_funded(row, 'N'), axis=1)
# scheme_loans_table.head()

# Calculate the sum of the month columns and create a new row
sum_row = scheme_loans_table.iloc[:, 2:].sum()
sum_row = pd.DataFrame(sum_row).T  
sum_row.insert(0, 'FKGD_CATEGORY', '')  
sum_row.insert(1, 'DESCRIPTION', 'TOTAL')  
# Append the total row to the DataFrame
scheme_loans_table = pd.concat([scheme_loans_table, sum_row], ignore_index = True)
# scheme_loans_table.tail(2)

# Get the sum of the month values
scheme_loans_table['YTD_Actual'] = scheme_loans_table[month_column_order].sum(axis=1)
# scheme_loans_table.tail(2)


# Create rank
scheme_loans_table['Rank'] = None

# Calculate the rank separately and then assign it to the 'Rank' column, excluding the last row
ranks = scheme_loans_table.iloc[:-1]['YTD_Actual'].rank(method='dense', ascending=False)
scheme_loans_table.iloc[:-1, scheme_loans_table.columns.get_loc('Rank')] = ranks
scheme_loans_table = scheme_loans_table.sort_values(by = 'Rank')

ordered_columns = ['Rank', 'FKGD_CATEGORY', 'DESCRIPTION'] + month_column_order + ['YTD_Actual', 'Funded', 'Non-Funded']
scheme_loans_table = scheme_loans_table[ordered_columns]
# scheme_loans_table.head(2)


# Writing the table to excel (Schemes_view)
start_row = 4
start_col = 0

scheme_loans_table.to_excel(daily_drawdown_report_writer, sheet_name = scheme_loans_sheet_name, startrow = start_row, startcol = start_col, index = False, header = True),

scheme_loans_worksheet = daily_drawdown_report_writer.sheets[scheme_loans_sheet_name]
scheme_loans_worksheet.set_zoom(80)
scheme_loans_worksheet.set_tab_color(sheet_tab_color)

max_col = scheme_loans_table.shape[1] - 1
max_row = scheme_loans_table.shape[0] + start_row

scheme_loans_worksheet.merge_range("A1:B1", "", menu_button_format)
scheme_loans_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

scheme_loans_worksheet.merge_range(start_row-1,3,start_row-1,max_col-3, 'MOM DISBURSEMENT', delft_blue_fill_format)

scheme_loans_worksheet.autofilter(start_row, start_col, start_row, max_col)

scheme_loans_worksheet.set_column(0,0,10.00)
scheme_loans_worksheet.set_column(1,1,11.00)
scheme_loans_worksheet.set_column(2,2,44.00)
scheme_loans_worksheet.set_column(3,max_col,15.30)

scheme_loans_worksheet.conditional_format(start_row,0,start_row,max_col, {'type': 'no_errors', 'format': delft_blue_fill_format})
scheme_loans_worksheet.conditional_format(start_row+1,0,max_row, 2, {'type': 'no_errors', 'format': deepskyblue_fill_format})
scheme_loans_worksheet.conditional_format(start_row+1,3,max_row, max_col, {'type': 'no_errors', 'format': million_format})
scheme_loans_worksheet.conditional_format(start_row,3,max_row, max_col, {'type': 'no_errors', 'format': border_format})
scheme_loans_worksheet.conditional_format(max_row,3,max_row, max_col, {'type': 'no_errors', 'format': bold_format})

scheme_loans_worksheet.freeze_panes(5,3)
print(f"Sheet '{scheme_loans_sheet_name}' is successfully saved.")


# Salesperson_View
# Current Month Daily sales
# create copy of the data
current_month_data = loan_drawdown[loan_drawdown['MONTH_YR'] == max_month_name].copy()
# format date column
current_month_data['DRAWDOWN_DT'] = pd.to_datetime(current_month_data['DRAWDOWN_DT'], errors = 'coerce')
current_month_data['DRAWDOWN_DT'] = current_month_data['DRAWDOWN_DT'].dt.strftime('%Y-%m-%d')
# get daily sales
current_month_sales_table = sum_undefined(current_month_data, index = 'SALES_CODE', column_name = 'DRAWDOWN_DT', value_column_name = 'NET_DRAWDOWN')
# current_month_sales_table.head(2)

# Monthly sales value
# Count
sales_person_vol_table = count_monthly(loan_drawdown, index = 'SALES_CODE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# sales_person_vol_table.head(2)

# Sum
sales_person_val_table = sum_monthly(loan_drawdown, index = 'SALES_CODE', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# sales_person_val_table.head(2)

# Get the Month_Actual values
sales_month_actual = sales_person_val_table[[('SALES_CODE'), (max_month_name)]]
sales_month_actual = sales_month_actual.rename(columns = {(max_month_name) : 'Month_Actual'})
# sales_month_actual.head(2)


# Merge volume and value tables
sales_person_table = pd.merge(sales_person_vol_table, sales_person_val_table, left_on = 'SALES_CODE', right_on = 'SALES_CODE', how = 'left',sort = True, suffixes = ('_vol','_val'))
# sales_person_table.head(2)
sales_person_table.shape

# Get Staff Role
conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

role_target_map = '''
select * from branch_employee_dmc_data where active = 1
                         
'''
role_target_map = pd.read_sql_query(role_target_map , conn)

conn.close()


# Tables for all roles
combined_seller_person = []

roles = ['COMMERCIAL RM', 'DIASPORA ARM', 'DIASPORA RM', 'MORTGAGE ARM', 'PB ARM', 'PB BBC', 'PB DSR', 'PB RM', 'SME ARM', 'SME BBC', 'SME DSR', 'SME RM', 'ULTIMATE RM']

for role in roles:
    # get role targets
    seller_role_map = role_target_map.loc[role_target_map['staff_role'] == role, 
                                         ['sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone', 'target_loan_disbursement']]
    seller_role_map = seller_role_map.rename(columns = {'target_loan_disbursement': 'Monthly_Target'})

    # merge to get Month_Actual values
    seller_role_map = pd.merge(seller_role_map, sales_month_actual, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    seller_role_map.drop(columns = 'SALES_CODE', inplace = True)
    seller_role_map = seller_role_map.fillna(0)

    # Calculate month achievements
    seller_role_map['Month_Deficit'] = seller_role_map['Month_Actual'] - seller_role_map['Monthly_Target']
    seller_role_map = seller_role_map.fillna(0)
    seller_role_map['Month_%_Achieved'] = seller_role_map.apply(lambda row: calculate_percentage_achieved(row, 'Month_Actual', 'Monthly_Target'), axis=1)
    
    # Calculate percentage achieved - more efficient vectorized approach
    # seller_role_map['Month_%_Achieved'] = 0
    # mask = seller_role_map['Monthly_Target'] != 0
    # seller_role_map.loc[mask, 'Month_%_Achieved'] = (seller_role_map.loc[mask, 'Month_Actual'] / seller_role_map.loc[mask, 'Monthly_Target'])
    # seller_role_map = seller_role_map.fillna(0)

    # Get monthly drawdowns
    seller_role_map = pd.merge(seller_role_map, sales_person_table, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    seller_role_map.drop(columns = 'SALES_CODE', inplace = True)
    seller_role_map = seller_role_map.fillna(0)

    # Get daily drawdowns
    seller_role_map = pd.merge(seller_role_map, current_month_sales_table, left_on = 'sales_code', right_on = 'SALES_CODE', how = 'left')
    seller_role_map.drop(columns = 'SALES_CODE', inplace = True)
    seller_role_map = seller_role_map.fillna(0)

    # Create role rank
    seller_role_map['Rank'] = seller_role_map['Month_%_Achieved'].rank(method = 'dense', ascending = False)
    seller_role_map = seller_role_map.sort_values(by = 'Rank')

    # Define column order
    new_column_order = []
    for col in month_column_order:
        col_vol = col+'_vol'
        col_val = col+'_val'
        new_column_order.append(col_vol)
        new_column_order.append(col_val)
        
    final_column_order = ['Rank','sales_code', 'staff_name', 'staff_branch', 'staff_role', 'staff_zone',
                          'Monthly_Target', 'Month_Actual', 'Month_Deficit', 'Month_%_Achieved'] + new_column_order
    cols_to_front = final_column_order
    remaining_cols = [col for col in seller_role_map.columns if col not in cols_to_front]
    new_final_column_order = cols_to_front + remaining_cols
    
    seller_role_map = seller_role_map.reindex(columns = new_final_column_order)
    seller_role_map = seller_role_map.fillna(0)

    # Append all role dfs
    combined_seller_person.append(seller_role_map)        


# Write table to Salesperson_view sheet
rows = np.cumsum([df.shape[0] + 4 for df in combined_seller_person])
fin_rows = [4] + [data + 4 for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for row, df in zip(range(0,len(fin_rows)), combined_seller_person):
    start_col = 0
    df.to_excel(daily_drawdown_report_writer, sheet_name = performance_sheet_name, index = False, startrow = fin_rows[row], startcol = start_col)

performance_worksheet = daily_drawdown_report_writer.sheets[performance_sheet_name]
performance_worksheet.set_zoom(80)
performance_worksheet.set_tab_color(sheet_tab_color)

month_perc_col = combined_seller_person[0].columns.get_loc('Month_%_Achieved')

vol_columns = [col for col in combined_seller_person[0].columns if '_vol' in col]
vol_column_indices = [combined_seller_person[0].columns.get_loc(col) for col in vol_columns]

val_columns = [col for col in combined_seller_person[0].columns if '_val' in col]
val_column_indices = [combined_seller_person[0].columns.get_loc(col) for col in val_columns]

day_columns = remaining_cols
day_column_indices = [combined_seller_person[0].columns.get_loc(col) for col in day_columns]

performance_worksheet.merge_range("A1:B1", "", menu_button_format)
performance_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

performance_worksheet.set_column(0,1,11.00)
performance_worksheet.set_column(2,3,30.00)
performance_worksheet.set_column(4,5,16.00)
performance_worksheet.set_column(6,8,14.00,million_format)
performance_worksheet.set_column(10,combined_seller_person[0].shape[1],14.00)
performance_worksheet.set_column(month_perc_col,month_perc_col,17.00, percent_format)

for (row, title) in zip(fin_rows,roles):
    performance_worksheet.merge_range(row-1,0,row-1,2, title, delft_blue_fill_format)
    
for i , (row, df) in enumerate(zip(fin_rows, combined_seller_person)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1
    col = 0
    performance_worksheet.conditional_format(row, col, row, end_col, {'type': 'no_errors','format': delft_blue_fill_format})
    performance_worksheet.conditional_format(row, col, end_row, end_col, {'type': 'no_errors', 'format': border_format})
    performance_worksheet.conditional_format(row + 1, 0, end_row, 5, {'type': 'no_errors','format': lemonchiffon_format})
    performance_worksheet.conditional_format(row + 1, 6, end_row, 8, {'type': 'no_errors','format': deepskyblue_fill_format})
    performance_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 1,'format': green_format})
    performance_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '>','value': 0.8,'format': amber_format})
    performance_worksheet.conditional_format(row + 1, month_perc_col, end_row, month_perc_col, {'type': 'cell','criteria': '<=','value': 0.8,'format': red_format})

    for vol_col in vol_column_indices:
        performance_worksheet.conditional_format(row + 1, vol_col, end_row, vol_col, {'type': 'no_errors','format': comma_format})

    for val_col in val_column_indices:
        performance_worksheet.conditional_format(row + 1, val_col, end_row, val_col, {'type': 'no_errors','format': million_format})
    
    for day_col in day_column_indices:
        performance_worksheet.conditional_format(row + 1, day_col, end_row, day_col, {'type': 'no_errors','format': million_format})
        performance_worksheet.conditional_format(row + 1, day_col, end_row, day_col, {'type': 'no_errors','format': lightsteelblue_fill_format})
                
    
performance_worksheet.freeze_panes(5,6)
print(f"Sheet '{performance_sheet_name}' is successfully saved.")


# Loan_Drawdown worksheet
# Get excel data
loan_drawdown_excel = loan_drawdown.copy()
print(loan_drawdown_excel.shape)
loan_drawdown_excel = loan_drawdown_excel[~loan_drawdown_excel['SALES_STAFF'].str.contains('SBP0001', case=False, na=False)]
loan_drawdown_excel.drop(columns = ['IS_DIASPORA', 'MONTH_YR', 'WEEK', 'WEEK_MONTH', 'RETAIL_CHECK'], inplace = True)
print(loan_drawdown_excel.shape)

# Sort in ascending_order
loan_drawdown_excel = loan_drawdown_excel.sort_values(by = 'DRAWDOWN_DT')

# Write to excel
start_row = 4
start_col = 0

loan_drawdown_excel.to_excel(daily_drawdown_report_writer, sheet_name = loan_drawdowns_sheet_name, index = False, startrow = start_row, startcol = start_col, header = True)

loan_drawdown_worksheet = daily_drawdown_report_writer.sheets[loan_drawdowns_sheet_name]
loan_drawdown_worksheet.set_zoom(80)
loan_drawdown_worksheet.set_tab_color(sheet_tab_color)

max_col = loan_drawdown_excel.shape[1]-1
max_row = loan_drawdown_excel.shape[0]+start_row

loan_drawdown_worksheet.merge_range("A1:B1", "", menu_button_format)
loan_drawdown_worksheet.write_url('A1','internal:MENU!A1', menu_button_format, string = 'MENU')

loan_drawdown_worksheet.autofilter(start_row, 0, start_row, max_col)

loan_drawdown_worksheet.set_column(0, max_col, 15.20)

loan_drawdown_worksheet.conditional_format(start_row, 0, start_row, max_col, {'type': 'no_errors', 'format': deepskyblue_fill_format})
loan_drawdown_worksheet.conditional_format(start_row+1,22,max_row,max_col, {'type': 'no_errors', 'format': lightcyan_fill_format})
loan_drawdown_worksheet.conditional_format(start_row+1,14,max_row,15, {'type': 'no_errors', 'format': comma_format})
loan_drawdown_worksheet.conditional_format(start_row+1, 3, max_row, 3, {'type': 'no_errors', 'format': date_format})
loan_drawdown_worksheet.conditional_format(start_row+1, 13, max_row, 13, {'type': 'no_errors', 'format': date_format})

loan_drawdown_worksheet.freeze_panes(5,0)
print(f"Sheet '{loan_drawdowns_sheet_name}' is successfully saved.")


# Analysis Worksheet
# Writing Info
top_branch_info = branch_table.loc[branch_table['Rank'] == 1, ['Rank', 'BRANCH', 'Monthly_Target', 'Month_Actual', 'Month_%_Achieved']]
# top_branch_info
top_branch_info.shape

year_info = branch_table.iloc[-1][['YTD_Target', 'YTD_Actual', 'YTD_%_Achieved']]
year_info_df = pd.DataFrame(year_info).transpose()
# year_info_df
year_info_df.shape


month_info = branch_table.iloc[-1][['Monthly_Target', 'Month_Actual', 'Month_%_Achieved']]
month_info_df = pd.DataFrame(month_info).transpose()
# month_info_df
month_info_df.shape


# Graphs
# Segments column graph(column stacked graph)
segment_graph_values = sum_monthly(loan_drawdown, index = 'BANKING_SEGMENT', months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
segment_graph_values = segment_graph_values[(segment_graph_values['BANKING_SEGMENT'].isin(banking_segment_order))]
# segment_graph_values


# Disbursment Distribution (pie chart)
distribution_graph_values = sum(loan_drawdown, index = 'SECURITY', value_column_name = 'NET_DRAWDOWN')
# distribution_graph_values


# Monthly vol(line graph)
vol_graph_values = count_no_index(loan_drawdown, months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# vol_graph_values


# Monthly val(column graph)
val_graph_values = sum_no_index(loan_drawdown, months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# val_graph_values


# Monthly Tenor Distribution (column stacked)
tenor_graph_values = sum_monthly(loan_drawdown, months_column_name = 'MONTH_YR', index = 'TERM', value_column_name = 'NET_DRAWDOWN')
# tenor_graph_values


# Pie chart
tenor_dist_graph_values = sum(loan_drawdown, index = 'TERM', value_column_name = 'NET_DRAWDOWN')
# tenor_dist_graph_values


# Date 
report_date = formatted_date
# report_date
report_date_df = pd.DataFrame([report_date], columns=['Report Date'])


# Writing to excel

report_date_df.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 0, startcol = 0,)

top_branch_info.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 3, startcol = 0, header = True)

year_info_df.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 3, startcol = 6, header = True)

month_info_df.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 6, startcol = 6, header = True)

segment_graph_values.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 0, startcol = 10, header = True)

distribution_graph_values.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 0, startcol = 24, header = True)

vol_graph_values.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 9, startcol = 10, header = True)

val_graph_values.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 12, startcol = 10, header = True)

tenor_graph_values.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 15, startcol = 10, header = True)

tenor_dist_graph_values.to_excel(daily_drawdown_report_writer, sheet_name = analysis_sheet_name, index = False, startrow = 5, startcol = 24, header = True)

analysis_worksheet = daily_drawdown_report_writer.sheets[analysis_sheet_name]
analysis_worksheet.set_zoom(80)
analysis_worksheet.set_tab_color(sheet_tab_color)

analysis_worksheet.set_column(0,0,15.00)
analysis_worksheet.set_column(1,1,11.00)
analysis_worksheet.set_column(2,3,20.00, million_format)
analysis_worksheet.set_column(4,4,20.00, percent_format)
analysis_worksheet.set_column(6,7,20.00, comma_format)
analysis_worksheet.set_column(8,8,20.00, percent_format)

analysis_worksheet.hide()
print(f"Sheet '{analysis_sheet_name}' is successfully saved.")


# Dashboard Writing
# Styling Charts
chart_1 = workbook.add_chart({'type': 'column', 'subtype': 'stacked'})
chart_2 = workbook.add_chart({'type': 'pie'})
chart_3 = workbook.add_chart({'type': 'column'})
chart_4 = workbook.add_chart({'type': 'line'})
chart_5 = workbook.add_chart({'type': 'column'})
chart_6 = workbook.add_chart({'type': 'pie'})


chart_1.add_series({
    'name':'=Analysis!$K$2',
    'categories': '=Analysis!$L$1:$W$1',
    'values' : '=Analysis!$L$2:$W$2',
    'fill': {'color':'#2AAFB8'}
})

chart_1.add_series({
    'name':'=Analysis!$K$3',
    'categories': '=Analysis!$L$1:$W$1',
    'values' : '=Analysis!$L$3:$W$3',
    'fill': {'color':'#C69500'}
})

chart_1.add_series({
    'name':'=Analysis!$K$4',
    'categories': '=Analysis!$L$1:$W$1',
    'values' : '=Analysis!$L$4:$W$4',
    'fill': {'color':'#70AD47'}
})

chart_1.add_series({
    'name':'=Analysis!$K$5',
    'categories': '=Analysis!$L$1:$W$1',
    'values' : '=Analysis!$L$5:$W$5',
    'fill': {'color':'#70AD47'}
})

chart_1.add_series({
    'name':'=Analysis!$K$6',
    'categories': '=Analysis!$L$1:$W$1',
    'values' : '=Analysis!$L$6:$W$6',
    'fill': {'color':'#D9D9D9'}
})


chart_1.set_title({
    'name': 'Segments',
    'name_font': {'name':'cambria', 'size': 16, 'bold':True, 'color':'white'},
})
chart_1.show_blanks_as('zero')
chart_1.set_size({'width': 910, 'height': 420})
chart_1.set_y_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'},
                   'num_format': '#,##0.0,,'})
chart_1.set_x_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'}})
chart_1.set_legend({'font': {'name':'cambria', 'size': 11, 'bold':True, 'color':'white'}})
chart_1.set_chartarea({
    'border':{'color':'white'},
    'fill': {'color':'#2AAFB8'}
})
chart_1.set_plotarea({'fill':{'color': '#2AAFB8'}})



chart_2.add_series({
    'categories': '=Analysis!$Y$2:$Y$3',
    'values': '=Analysis!$Z$2:$Z$3',
    'points': [
        {'fill': {'color': '#2AAFB8'}},
        {'fill': {'color': '#C69500'}}
    ],
    'data_labels': {'category': True, 'value':True, 'num_format':'#,##0.0,, "M"',
                    'position':'center', 'fill':{'color':'black'},'border':{'none':True},
                    'font':{'name':'cambria', 'size': 11, 'bold':True, 'color':'white'}
                    },
})


chart_2.set_title({
    'name': 'Disbursements Distribution',
    'name_font': {'name':'cambria', 'size': 16, 'bold':True, 'color':'white'},
    })
chart_2.set_size({'width': 448, 'height': 420})
chart_2.set_legend({'none':True})
chart_2.set_chartarea({
    'border':{'color':'white'},
    'fill': {'color':'#2AAFB8'}
})


chart_3.add_series({
     'name':'Val',
     'categories': '=Analysis!$L$13:$W$13',
     'values' : '=Analysis!$L$14:$W$14',
     'fill': {'color':'#70AD47'}
})



chart_4.add_series({
     'name':'Vol',
     'categories': '=Analysis!$L$10:$W$10',
     'values' : '=Analysis!$L$11:$W$11',
     'y2_axis': True,
     'fill': {'color':'#D9D9D9'}
})
chart_4.set_y2_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'},
                    'name':'Volume',
                    'name_font': {'name':'cambria', 'size': 10, 'bold':True, 'color':'white'}
                    })

chart_3.combine(chart_4)
chart_3.set_title({
    'name': 'Monthly Disbursements',
    'name_font': {'name':'cambria', 'size': 16, 'bold':True, 'color':'white'},
    })
chart_3.show_blanks_as('zero')
chart_3.set_size({'width': 1351, 'height': 420})
chart_3.set_y_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'},
                    'num_format': '#,##0.0,,',
                    'name':'Value',
                    'name_font': {'name':'cambria', 'size': 10, 'bold':True, 'color':'white'}
                    })
chart_3.set_x_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'}})
chart_3.set_legend({'font': {'name':'cambria', 'size': 11, 'bold':True, 'color':'white'}})
chart_3.set_chartarea({
    'border':{'color':'white'},
    'fill': {'color':'#2AAFB8'}
})
chart_3.set_plotarea({'fill':{'color': '#2AAFB8'}})


chart_5.add_series({
    'name':'=Analysis!$K$17',
    'categories': '=Analysis!$L$16:$W$16',
    'values' : '=Analysis!$L$17:$W$17',
    'fill': {'color':'#70AD47'}
})

chart_5.add_series({
    'name':'=Analysis!$K$18',
    'categories': '=Analysis!$L$16:$W$16',
    'values' : '=Analysis!$L$18:$W$18',
    'fill': {'color':'#D9D9D9'}
})


chart_5.set_title({
    'name': 'Monthly Disbursements',
    'name_font': {'name':'cambria', 'size': 16, 'bold':True, 'color':'white'},
})
chart_5.show_blanks_as('zero')
chart_5.set_size({'width': 910, 'height': 420})
chart_5.set_y_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'},
                   'num_format': '#,##0.0,,'})
chart_5.set_x_axis({'num_font': {'name':'cambria', 'size': 9, 'bold':True, 'color':'white'}})
chart_5.set_legend({'font': {'name':'cambria', 'size': 11, 'bold':True, 'color':'white'}})
chart_5.set_chartarea({
    'border':{'color':'white'},
    'fill': {'color':'#2AAFB8'}
})
chart_5.set_plotarea({'fill':{'color': '#2AAFB8'}})


chart_6.add_series({
    'categories': '=Analysis!$Y$7:$Y$8',
    'values': '=Analysis!$Z$7:$Z$8',
    'points': [
        {'fill': {'color': '#2AAFB8'}},
        {'fill': {'color': '#C69500'}}
    ],
    'data_labels': {'category': True, 'value':True, 'num_format':'#,##0.0,, "M"',
                    'position':'center', 'fill':{'color':'black'},'border':{'none':True},
                    'font':{'name':'cambria', 'size': 12, 'bold':True, 'color':'white'}
                    },
})


chart_6.set_title({
    'name': 'Tenor Distribution',
    'name_font': {'name':'cambria', 'size': 16, 'bold':True, 'color':'white'},
    })
chart_6.set_size({'width': 448, 'height': 420})
chart_6.set_legend({'none':True})
chart_6.set_chartarea({
    'border':{'color':'white'},
    'fill': {'color':'#2AAFB8'}
})


# Styling text boxes
background_box = {
    'width':1350, 'height':280,
    'fill':{'color':'#2AAFB8'}
}
branch_box = {
    'width':419, 'height':250,
    'x_offset':8,'y_offset':15,
    'fill':{'none':True},
    'line': {'color': 'white',
    'width': 2.5,
    'dash_type': 'square_dot'}
}

heading_props = {
    'width':600, 'height':60, 'object_position':3,
    'x_offset': 30,
    'font':{'color':'white','name':'cambria','size':32,'bold':True},
    'align':{'vertical':'middle','horizontal':'left'},
    'fill':{'none':True},
    'line':{'none':True},
}
date_props = { 
    'textlink':'=Analysis!$A$2',    
    'x_offset':35,
    'width':247, 'height':60, 'object_position':3,
    'font':{'color':'white','name':'cambria','size':20,'bold':True},
    'align':{'vertical':'middle','horizontal':'right','text':'right'},
    'line':{'none':True},
    'fill':{'none':True}
}

mid_tabs = {
    'width':250, 'height':35, 'object_position':3,
    'x_offset':30,
    'font':{'color':'white','name':'cambria','size':14,'bold':True},
    'align':{'vertical':'middle','horizontal':'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
}
# Year
ytd_target_tab = {
    'textlink': '=Analysis!G5',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text': 'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
 }
ytd_actual_tab = {
    'textlink': '=Analysis!H5',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text': 'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
 }
ytd_perf_tab = {
    'textlink': '=Analysis!I5',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
}
# Month
mtd_target_tab = {
    'textlink': '=Analysis!G8',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
 }
mtd_actual_tab = {
    'textlink': '=Analysis!H8',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
 }
mtd_perf_tab = {
    'textlink': '=Analysis!I8',
    'width':370, 'height':50, 'object_position':3,
     'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
}
# Branch
top_br_tab = {
    'textlink': '=Analysis!B5',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'center'},
    'line':{'none':True},
     'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':18, 'bold':True}
}
tar_br_tab = {
    'textlink': '=Analysis!C5',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':20, 'bold':True}
}
act_br_tab = {
    'textlink': '=Analysis!D5',
    'width':370, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal':'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':20, 'bold':True}
}
perf_br_tab = {
    'textlink': '=Analysis!E5',
    'width':120, 'height':50, 'object_position':3,
    'x_offset':5,'y_offset':10,
    'align': {'vertical': 'middle','horizontal': 'left','text':'left'},
    'line':{'none':True},
    'fill':{'none':True},
    'font': {'color': '#C69500', 'name':'cambria', 'size':23, 'bold':True}
}


# Writing Textboxes
dashboard_worksheet.insert_textbox('A1', '',background_box)
dashboard_worksheet.insert_textbox('O1', '',branch_box)

dashboard_worksheet.insert_textbox('A1', 'DRAWDOWN DASHBOARD',heading_props)
dashboard_worksheet.insert_textbox('J1', '', date_props)

dashboard_worksheet.insert_textbox('A5', 'YTD_Target', mid_tabs)
dashboard_worksheet.insert_textbox('A7', '', ytd_target_tab)

dashboard_worksheet.insert_textbox('E5', 'YTD_Actual', mid_tabs)
dashboard_worksheet.insert_textbox('E7', '', ytd_actual_tab)

dashboard_worksheet.insert_textbox('I5', 'Performance %', mid_tabs)
dashboard_worksheet.insert_textbox('I7', '', ytd_perf_tab)

dashboard_worksheet.insert_textbox('A10', 'Monthly_Target', mid_tabs)
dashboard_worksheet.insert_textbox('A12', '', mtd_target_tab)

dashboard_worksheet.insert_textbox('E10', 'Month_Actual', mid_tabs)
dashboard_worksheet.insert_textbox('E12', '', mtd_actual_tab)

dashboard_worksheet.insert_textbox('I10', 'Performance %', mid_tabs)
dashboard_worksheet.insert_textbox('I12', '', mtd_perf_tab)


dashboard_worksheet.insert_textbox('P2', 'Top Branch', mid_tabs)
dashboard_worksheet.insert_textbox('P3', '', top_br_tab)

dashboard_worksheet.insert_textbox('O6', 'MTD Target:', mid_tabs)
dashboard_worksheet.insert_textbox('R5', '', tar_br_tab)

dashboard_worksheet.insert_textbox('O9', 'MTD Actual:', mid_tabs)
dashboard_worksheet.insert_textbox('R8', '', act_br_tab)

dashboard_worksheet.insert_textbox('Q11', '', perf_br_tab)                         

# Writing Charts
dashboard_worksheet.insert_chart('A15', chart_1, {'object_position':3})
dashboard_worksheet.insert_chart('O15', chart_2, {'object_position':3,'x_offset':8})
dashboard_worksheet.insert_chart('A36', chart_3, {'object_position':3})
dashboard_worksheet.insert_chart('A57', chart_5, {'object_position':3})
dashboard_worksheet.insert_chart('O57', chart_6, {'object_position':3,'x_offset':8})

# Internal Link
dashboard_worksheet.merge_range("W1:X2", "", menu_button_format)
dashboard_worksheet.write_url('W1','internal:MENU!A1', menu_button_format, string = 'MENU')

dashboard_worksheet.protect()

# Save and close the workbook
daily_drawdown_report_writer.close()


# Email Styling and Writing
# Create dataframe for email
# Total bank disbursment
total_bank_monthly_table = sum_no_index(loan_drawdown, months_column_name = 'MONTH_YR', value_column_name = 'NET_DRAWDOWN')
# total_bank_monthly_table

# Per Segment Disbursment
segment_disbursment_table = sum_monthly(loan_drawdown, months_column_name = 'MONTH_YR', index = 'BANKING_SEGMENT', value_column_name = 'NET_DRAWDOWN')
segment_disbursment_table = segment_disbursment_table[(segment_disbursment_table['BANKING_SEGMENT'].isin(banking_segment_order))]
# segment_disbursment_table

business_monthly_table = segment_disbursment_table[segment_disbursment_table['BANKING_SEGMENT'] == 'BUSINESS']
if business_monthly_table.empty:
    data = {'BANKING_SEGMENT': ['BUSINESS']}
    for column in month_column_order:
        data[column] = [0]
    business_monthly_table = pd.DataFrame(data)    
# business_monthly_table

commercial_monthly_table = segment_disbursment_table[segment_disbursment_table['BANKING_SEGMENT'] == 'COMMERCIAL']
if commercial_monthly_table.empty:
    data = {'BANKING_SEGMENT': ['COMMERCIAL']}
    for column in month_column_order:
        data[column] = [0]
    commercial_monthly_table = pd.DataFrame(data)    
# commercial_monthly_table

diaspora_monthly_table = segment_disbursment_table[segment_disbursment_table['BANKING_SEGMENT'] == 'DIASPORA']
if diaspora_monthly_table.empty:
    data = {'BANKING_SEGMENT': ['DIASPORA']}
    for column in month_column_order:
        data[column] = [0]
    diaspora_monthly_table = pd.DataFrame(data)    
# diaspora_monthly_table

personal_monthly_table = segment_disbursment_table[segment_disbursment_table['BANKING_SEGMENT'] == 'PERSONAL']
if personal_monthly_table.empty:
    data = {'BANKING_SEGMENT': ['PERSONAL']}
    for column in month_column_order:
        data[column] = [0]
    personal_monthly_table = pd.DataFrame(data)
# personal_monthly_table

ultimate_monthly_table = segment_disbursment_table[segment_disbursment_table['BANKING_SEGMENT'] == 'ULTIMATE']
if ultimate_monthly_table.empty:
    data = {'BANKING_SEGMENT': ['ULTIMATE']}
    for column in month_column_order:
        data[column] = [0]
    ultimate_monthly_table = pd.DataFrame(data)
# ultimate_monthly_table


# Segment targets
segment_targets = segment_targets_table.copy()
# segment_targets

# Business
business_target = segment_targets['Monthly_Target'][0]
# Create a DataFrame for the first row: Monthly Targets
target_row = pd.DataFrame({
    'BANKING_SEGMENT': ['Disburment Targets'],
    **{month: [business_target] for month in month_column_order}
})
# Create a DataFrame for the second row: Actual Values
actual_row = business_monthly_table.copy()
actual_row['BANKING_SEGMENT'] = 'Actual Disbursment'
# Create a DataFrame for the third row: Results Ratio (Actual / Target)
rr_row = business_monthly_table.copy()
for month in month_column_order:
    rr_row[month] = business_monthly_table[month] / business_target
rr_row['BANKING_SEGMENT'] = '% Against Target'

business_final_df = pd.concat([target_row, actual_row, rr_row], ignore_index=True)
business_final_df.insert(0, 'Segment', '')
business_final_df.at[0, 'Segment'] = 'BUSINESS'
business_final_df.rename(columns={'BANKING_SEGMENT' : 'Measure'}, inplace = True)
# business_final_df


# Commercial
commercial_target = segment_targets['Monthly_Target'][1]
# Create a DataFrame for the first row: Monthly Targets
target_row = pd.DataFrame({
    'BANKING_SEGMENT': ['Disburment Targets'],
    **{month: [commercial_target] for month in month_column_order}
})
# Create a DataFrame for the second row: Actual Values
actual_row = commercial_monthly_table.copy()
actual_row['BANKING_SEGMENT'] = 'Actual Disbursment'
# Create a DataFrame for the third row: Results Ratio (Actual / Target)
rr_row = commercial_monthly_table.copy()
for month in month_column_order:
    rr_row[month] = commercial_monthly_table[month] / commercial_target
rr_row['BANKING_SEGMENT'] = '% Against Target'

# Concatenate the rows together
commercial_final_df = pd.concat([target_row, actual_row, rr_row], ignore_index=True)
commercial_final_df.insert(0, 'Segment', '')
commercial_final_df.at[0, 'Segment'] = 'COMMERCAIL'
commercial_final_df.rename(columns={'BANKING_SEGMENT' : 'Measure'}, inplace = True)
# commercial_final_df


# Diaspora
diaspora_target = segment_targets['Monthly_Target'][2]
# Create a DataFrame for the first row: Monthly Targets
target_row = pd.DataFrame({
    'BANKING_SEGMENT': ['Disburment Targets'],
    **{month: [diaspora_target] for month in month_column_order}
})
# Create a DataFrame for the second row: Actual Values
actual_row = diaspora_monthly_table.copy()
actual_row['BANKING_SEGMENT'] = 'Actual Disbursment'
# Create a DataFrame for the third row: Results Ratio (Actual / Target)
rr_row = diaspora_monthly_table.copy()
for month in month_column_order:
    rr_row[month] = diaspora_monthly_table[month] / diaspora_target
rr_row['BANKING_SEGMENT'] = '% Against Target'

# Concatenate the rows together
diaspora_final_df = pd.concat([target_row, actual_row, rr_row], ignore_index=True)
diaspora_final_df.insert(0, 'Segment', '')
diaspora_final_df.at[0, 'Segment'] = 'DIASPORA'
diaspora_final_df.rename(columns={'BANKING_SEGMENT' : 'Measure'}, inplace = True)
# diaspora_final_df


# Personal
personal_target = segment_targets['Monthly_Target'][3]
# Create a DataFrame for the first row: Monthly Targets
target_row = pd.DataFrame({
    'BANKING_SEGMENT': ['Disburment Targets'],
    **{month: [personal_target] for month in month_column_order}
})
# Create a DataFrame for the second row: Actual Values
actual_row = personal_monthly_table.copy()
actual_row['BANKING_SEGMENT'] = 'Actual Disbursment'
# Create a DataFrame for the third row: Results Ratio (Actual / Target)
rr_row = personal_monthly_table.copy()
for month in month_column_order:
    rr_row[month] = personal_monthly_table[month] / personal_target
rr_row['BANKING_SEGMENT'] = '% Against Target'

# Concatenate the rows together
personal_final_df = pd.concat([target_row, actual_row, rr_row], ignore_index=True)
personal_final_df.insert(0, 'Segment', '')
personal_final_df.at[0, 'Segment'] = 'PERSONAL'
personal_final_df.rename(columns={'BANKING_SEGMENT' : 'Measure'}, inplace = True)
# personal_final_df


# Ultimate
ultimate_target = segment_targets['Monthly_Target'][4]

# Create a DataFrame for the first row: Monthly Targets
target_row = pd.DataFrame({
    'BANKING_SEGMENT': ['Disburment Targets'],
    **{month: [ultimate_target] for month in month_column_order}
})

# Create a DataFrame for the second row: Actual Values
actual_row = ultimate_monthly_table.copy()
actual_row['BANKING_SEGMENT'] = 'Actual Disbursment'

# Create a DataFrame for the third row: Results Ratio (Actual / Target)
rr_row = ultimate_monthly_table.copy()
for month in month_column_order:
    rr_row[month] = ultimate_monthly_table[month] / ultimate_target
rr_row['BANKING_SEGMENT'] = '% Against Target'

# Concatenate the rows together
ultimate_final_df = pd.concat([target_row, actual_row, rr_row], ignore_index=True)
ultimate_final_df.insert(0, 'Segment', '')
ultimate_final_df.at[0, 'Segment'] = 'ULTIMATE'
ultimate_final_df.rename(columns={'BANKING_SEGMENT' : 'Measure'}, inplace = True)
ultimate_final_df


# Total Bank
bank_target = segment_targets['Monthly_Target'][5]

# Create a DataFrame for the first row: Monthly Targets
target_row = pd.DataFrame({
    'index': ['Disburment Targets'],
    **{month: [bank_target] for month in month_column_order}
})

# Create a DataFrame for the second row: Actual Values
actual_row = total_bank_monthly_table.copy()
actual_row['index'] = 'Actual Disbursment'

# Create a DataFrame for the third row: Results Ratio (Actual / Target)
rr_row = total_bank_monthly_table.copy()
for month in month_column_order:
    rr_row[month] = total_bank_monthly_table[month] / bank_target
rr_row['index'] = '% Against Target'

# Concatenate the rows together
bank_final_df = pd.concat([target_row, actual_row, rr_row], ignore_index=True)
bank_final_df.insert(0, 'Segment', '')
bank_final_df.at[0, 'Segment'] = 'TOTAL BANK'
bank_final_df.rename(columns={'index' : 'Measure'}, inplace = True)
bank_final_df


# Combine the segment tables
target_dfs = [bank_final_df, business_final_df, commercial_final_df, diaspora_final_df, personal_final_df, ultimate_final_df] 
targets_summ = pd.concat(target_dfs, ignore_index=True, verify_integrity=True)
targets_summ.head(2)




# Styling dfs for email
# Segment targets table
def style_segment_targets_table(df):
    # Define a function to format the values based on the 'Measure' column
    def format_row(row):
        return [
            f"{x:.0%}" if row['Measure'] == '% Against Target' and isinstance(x, (int, float)) else
            f"{x / 1_000_000:,.0f}M" if isinstance(x, (int, float)) else x
            for x in row
        ]

    # Apply formatting function to each row
    formatted_data = df.apply(format_row, axis=1)

    # Convert the formatted data back into a DataFrame
    formatted_df = pd.DataFrame(formatted_data.tolist(), columns=df.columns)

    # Define a custom color scale function for '% Against Target' row
    def color_ytd_percentage(val):
        if isinstance(val, str) and '%' in val:  # Handle percentage values formatted as strings
            val = float(val.strip('%')) / 100
        if val < 0.80:
            return 'background-color: red'
        elif 0.80 <= val < 1.00:
            return 'background-color: yellow'
        elif val >= 1.00:
            return 'background-color: green'
        return ''

    # Style the DataFrame
    styled_df = formatted_df.style \
        .set_table_styles([
            {'selector': 'td', 'props': [("border", "2px solid black"),
                                         ("border-collapse", "collapse"),
                                         ("padding", "8px"),
                                         ("text-align", "center")]},
            {'selector': 'th', 'props': [("font-size", "11pt"),
                                          ("background-color", "#1B4872"),
                                          ("color", "white"),
                                          ("border", "2px solid black"),
                                          ("font-weight", "bold"),
                                          ("text-transform", "uppercase"),
                                          ("padding", "8px"),
                                          ("text-align", "center")]},
            # Adding styles for the first three columns
            {'selector': 'td:nth-child(1)', 'props': [("background-color", "#1B4872"), ("color", "white")]},
            {'selector': 'td:nth-child(2)', 'props': [("background-color", "#1B4872"), ("color", "white")]},
            {'selector': 'td:nth-child(3)', 'props': [("background-color", "#1B4872"), ("color", "white")]}  
        ])

    # Apply the custom color scale to the '% Against Target' row
    percent_rows = df['Measure'] == '% Against Target'

    # Apply the color function using applymap only on numerical columns after the first three
    styled_df = styled_df.map(
        color_ytd_percentage,
        subset=pd.IndexSlice[percent_rows, df.columns[2:]]  # Use column names starting from the 4th column
    )

    return styled_df

# Applying the formatting function to your DataFrame
targets_summ_formatted_df = style_segment_targets_table(targets_summ)
# targets_summ_formatted_df


## Segment per product table
# def style_segment_product_pivot(dataframe):
#     format_dict = {col: lambda x: f"{x / 1_000_000:,.0f}M" if pd.notna(x) else "0M" for col in dataframe.columns if col not in ['% Per Product', 'BANKING_SEGMENT', 'PRODUCT_CATEGORY']}
#     # Fixed percentage formatting with proper error handling
#     def format_percentage(x):
#         if pd.isna(x) or x is None:
#             return ""
#         try:
#             return f"{x:.0%}"
#         except (ValueError, TypeError):
#             return ""
    
#     format_dict['% Per Product'] = format_percentage

#     return dataframe.style \
#         .format(format_dict) \
#         .set_properties(**{'border': '2px solid black', 
#                            'border-collapse': 'collapse', 
#                            'border-spacing': '0'}) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'},subset=(("BUSINESS", "TOTAL"),)) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'},subset=(("COMMERCIAL", "TOTAL"),)) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'},subset=(("DIASPORA", "TOTAL"),)) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'},subset=(("PERSONAL", "TOTAL"),)) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'},subset=(("ULTIMATE", "TOTAL"),)) \
#         .set_table_styles([{'selector': 'th', 'props': [('border', '2px solid black'), 
#                                                         ('color', 'white'), 
#                                                         ('background-color', '#1B4872')]
#                            }, 
#                           {'selector': 'th.col_heading', 'props': [('border', '2px solid black'), 
#                                                                    ('color', 'white'), 
#                                                                    ('background-color', '#1B4872')]
#                           }
#                           ]) \
#         .background_gradient(cmap="YlGn", subset=['% Per Product'], axis=None) # Two-color scale
#   # Apply formatting
# total_product_seg_summ_2_formatted_df = style_segment_product_pivot(total_product_seg_summ_2)


# def style_segment_product_pivot(dataframe):
#     format_dict = {col: lambda x: f"{x / 1_000_000:,.0f}M" if pd.notna(x) else "0M" for col in dataframe.columns if col not in ['% Per Product', 'BANKING_SEGMENT', 'PRODUCT_CATEGORY']}
    
#     # Fixed percentage formatting with proper error handling
#     def format_percentage(x):
#         if pd.isna(x) or x is None:
#             return ""
#         try:
#             return f"{x:.0%}"
#         except (ValueError, TypeError):
#             return ""
    
#     format_dict['% Per Product'] = format_percentage

#     return dataframe.style \
#         .format(format_dict) \
#         .set_properties(**{'border': '2px solid black', 
#                            'border-collapse': 'collapse', 
#                            'border-spacing': '0'}) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'}, subset=([4], slice(None))) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'}, subset=([6], slice(None))) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'}, subset=([8], slice(None))) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'}, subset=([13], slice(None))) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'black'}, subset=([15], slice(None))) \
#         .set_properties(**{'font-weight': 'bold', 'background-color': '#1B4872', 'color': 'white'}, subset=([16], slice(None))) \
#         .set_table_styles([{'selector': 'th', 'props': [('border', '2px solid black'), 
#                                                         ('color', 'white'), 
#                                                         ('background-color', '#1B4872')]
#                            }, 
#                           {'selector': 'th.col_heading', 'props': [('border', '2px solid black'), 
#                                                                    ('color', 'white'), 
#                                                                    ('background-color', '#1B4872')]
#                           }
#                           ]) \
#         .background_gradient(cmap="YlGn", subset=['% Per Product'], axis=None)

# # Apply formatting
# total_product_seg_summ_2_formatted_df = style_segment_product_pivot(total_product_seg_summ_2)



## sending emails
import smtplib
import os
import psutil
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Build a full audit trace of the process ancestry
def get_trigger_audit():
    scheduled_triggers = {'cron', 'crond', 'anacron', 'atd'}
    chain = []
    try:
        proc = psutil.Process(os.getpid())
        while proc is not None:
            try:
                chain.append({
                    'pid':     proc.pid,
                    'ppid':    proc.ppid(),
                    'name':    proc.name(),
                    'cmdline': ' '.join(proc.cmdline()) or proc.name(),
                    'user':    proc.username(),
                    'started': datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S'),
                })
            except (psutil.AccessDenied, psutil.ZombieProcess):
                chain.append({'pid': proc.pid, 'ppid': proc.ppid(), 'name': proc.name(),
                              'cmdline': '<access denied>', 'user': '<access denied>', 'started': 'N/A'})
            proc = proc.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    trigger_names = [e['name'] for e in chain if e['name'] in scheduled_triggers]
    trigger_type  = ', '.join(trigger_names) if trigger_names else 'interactive'
    return trigger_type, chain

def send_trigger_audit_email(trigger_type, chain, sender, smtp_host, smtp_port, smtp_user, smtp_password):
    trigger_list_of_recipients = [
        'clinton.ontweka@hfgroup.co.ke',
        'reports.analytics@hfgroup.co.ke',
        'allan.aswani@hfgroup.co.ke',
    ]

    rows = ''.join(
        f"""<tr>
              <td style="padding:4px 8px;border:1px solid #ccc;">{e['pid']}</td>
              <td style="padding:4px 8px;border:1px solid #ccc;">{e['ppid']}</td>
              <td style="padding:4px 8px;border:1px solid #ccc;">{e['name']}</td>
              <td style="padding:4px 8px;border:1px solid #ccc;">{e['user']}</td>
              <td style="padding:4px 8px;border:1px solid #ccc;">{e['started']}</td>
              <td style="padding:4px 8px;border:1px solid #ccc;">{e['cmdline']}</td>
            </tr>"""
        for e in chain
    )

    body = f"""<!DOCTYPE html>
        <html><body>
        <p>Dear Team,</p>
        <p>The <strong>Drawdown Report</strong> was triggered at <strong>{formatted_date}</strong>.<br/>
        Trigger source: <strong>{trigger_type}</strong></p>

        <table style="border-collapse:collapse;font-family:monospace;font-size:12px;">
        <thead>
            <tr style="background:#1B4872;color:#fff;">
            <th style="padding:4px 8px;border:1px solid #ccc;">PID</th>
            <th style="padding:4px 8px;border:1px solid #ccc;">PPID</th>
            <th style="padding:4px 8px;border:1px solid #ccc;">Process</th>
            <th style="padding:4px 8px;border:1px solid #ccc;">User</th>
            <th style="padding:4px 8px;border:1px solid #ccc;">Started</th>
            <th style="padding:4px 8px;border:1px solid #ccc;">Command</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
        </table>

        <br/><p>Analytics and Business Performance.</p>
        </body></html>"""

    msg = MIMEMultipart()
    msg['From']    = sender
    msg['To']      = ','.join(trigger_list_of_recipients)
    msg['Subject'] = f"[AUDIT] Drawdown Report Trigger — {trigger_type} — {formatted_date}"
    msg.attach(MIMEText(body, 'html'))

    s = smtplib.SMTP(smtp_host, smtp_port)
    s.starttls()
    s.login(smtp_user, smtp_password)
    s.sendmail(sender, trigger_list_of_recipients, msg.as_string())
    s.quit()


trigger_source, trigger_chain = get_trigger_audit()
send_trigger_audit_email(
    trigger_source, trigger_chain,
    sender       = app.hf_email['user'],
    smtp_host    = app.hf_email['host'],
    smtp_port    = app.hf_email['port'],
    smtp_user    = app.hf_email['user'],
    smtp_password= app.hf_email['password'],
)

# define sender
from1 = app.hf_email['user']

# define recipients
# global recipients
list_of_recipients = [
    'branch.managers@hfgroup.co.ke',
    'HFExCo@hfgroup.co.ke',
    'RetailManagementCommittee@hfgroup.co.ke',
    'Robert.Kibaara@hfgroup.co.ke',
]
cc_list_of_recipients = [
    'Branch_Business_Consultants@hfgroup.co.ke',
    'BusinessDevOfficer@hfgroup.co.ke',
    'CommercialBanking@hfgroup.co.ke',
    'SMEBanking@hfgroup.co.ke',
    'Personal_Banking_Team@hfgroup.co.ke',
    'Ultimate.banking@hfgroup.co.ke',
    'Treasury@hfgroup.co.ke',
    'SCHEMETEAM@hfgroup.co.ke',
    'SalesAdministration@hfgroup.co.ke',
    'Strategy&BusinessPerformance@hfgroup.co.ke',
    'Belinda.Nganga@hfgroup.co.ke',
    'Patrick.Wainaina@hfgroup.co.ke',
    'Jillvian.Njimo@hfgroup.co.ke',
    'TransactionalBanking@hfgroup.co.ke',
    'Ariel.Jumba@hfgroup.co.ke',
    'John.Njoroge@hfgroup.co.ke',
    'Stella.Mutai@hfgroup.co.ke',
    'diasporabanking@housingfinancekenya.onmicrosoft.com',
    'Business.Banking@hfgroup.co.ke',
    'Credit.Analyst@hfgroup.co.ke',
    'Homes@hfgroup.co.ke',
    'CreditPortfolioManagement@hfgroup.co.ke',
    'Peris.Muchiri@hfgroup.co.ke',
    'Arnold.Njoka@hfgroup.co.ke',
    'phoebe.mwai@hfgroup.co.ke',
    'creditevaluation@housingfinancekenya.onmicrosoft.com',
    'Caroline.Mburu@hfgroup.co.ke',
]

# Internal recipients
# list_of_recipients = ['shekinah.mwangi@hfgroup.co.ke']
# cc_list_of_recipients = ['reports.analytics@hfgroup.co.ke']


# instance of MIMEMultipart
data = MIMEMultipart()

# storing the senders email address
data['From'] = from1

# storing the receivers email address — cron/anacron: only list_of_recipients; interactive: include CC
data['To'] = ','.join(list_of_recipients)
data['CC'] = ','.join(cc_list_of_recipients)

# storing the subject
data['Subject'] = f"DRAWDOWN REPORT - {formatted_date}"

# string to store the body of the mail
# string to store the body of the mail
body = """
<!DOCTYPE html>
<html>
<head>
<title>Drawdown Dashboard</title>
</head>
<body>

<p> 
Dear All, <br/><br/>
    
    Please find the attached Drawdown Report.<br/>
    <br/><br/>
    Data summary for Segments is as shown:<br/><br/>
    {0}
    <br/><br/>
    <!-- 
    Data summary for Segments per product is as shown:<br/><br/>
    
    <br/><br/>
    -->


<br/></p>
<p> Please contact the Analytics Team directly if you have any questions. <br/>
    Thank you! <br/><br/>
    Best Regards, <br/>
    Analytics and Business Performance. </p>
<br/><br/>

<br/></p>
<p> This report is autogenerated. <br/>

</body>
</html>
""".format(targets_summ_formatted_df.to_html())

# attach the body with the msg instance
data.attach(MIMEText(body, 'html'))
# attach file to message
os.chdir(path)
FILES = os.listdir()
name = FILES
for i in range(len(FILES)):    
# open the file to be sent  
    filename = name[i]
    attachment = open(FILES[i], "rb")
# instance of MIMEBase and named as p
    p = MIMEBase('application', 'octet-stream')
# To change the payload into encoded form
    p.set_payload((attachment).read())
# encode into base64
    encoders.encode_base64(p)
    p.add_header('Content-Disposition', "attachment; filename= %s" % filename)
# attach the instance 'p' to instance 'msg'
    data.attach(p)

# creates SMTP session
s = smtplib.SMTP(app.hf_email['host'], app.hf_email['port'])

# start TLS for security
s.starttls()

# Authentication
s.login(from1,app.hf_email['password'])

# Converts the Multipart msg into a string
text = data.as_string()

# sending the mail
all_recipients = list_of_recipients + cc_list_of_recipients
s.sendmail(from1, all_recipients, text)

# terminating the session
s.quit()
  
print(f"'{file_name}' is successfully generated.")

