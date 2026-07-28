#!/usr/bin/env python
# coding: utf-8

# In[1]:


#!/usr/bin/env python
# coding: utf-8


# In[ ]:







# In[2]:


import numpy as np
import pandas as pd
import xlsxwriter
import calendar
import os

from datetime import ( datetime as dt, date,timedelta)
from calendar import monthrange
from pandas import DataFrame as df

import openpyxl
from openpyxl import Workbook


# In[3]:


# Step 1: Create the directory if it does not exist
path = os.path.join(os.getcwd(), "attachments", "bancassurance")
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


# 
# 
# ## Read & manipulate data


# In[4]:


# Get the current year
# Check if today's date is before 20th January of the current year to account for a grace period in time taken to migrate the tables in produciton to the new year 
current_year = (dt.now().year - 1) if (dt.now().month == 1 and dt.now().day < 20) else dt.now().year

import app_settings as app  # type: ignore

import psycopg2 as psql

# SQL query to fetch sales report data for the current year
p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

# SELECT 
#     r_number, sales_type, insured, phone_no, email, financier, underwriter, 
#     policy_no, product, reg_no, starting_date, ending_date, sum_insured, 
#     premiums AS total_premiums, paid AS paid_premiums, balance, commission, 
#     branch, sales_person, code, rm, month, year
# FROM insurance_policies 
# WHERE year IN ('{current_year}');
sales_report_query = f'''
    WITH CTE AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY CONCAT(r_number, starting_date) ORDER BY r_number, starting_date DESC) AS rn
        -----ROW_NUMBER() OVER (PARTITION BY r_number, starting_date ORDER BY updated_at DESC) AS rn
    FROM insurance_policies
    )
    SELECT
        id, r_number, sales_type, insured, phone_no, email, financier, underwriter, policy_no, product, reg_no, starting_date, ending_date, sum_insured, premiums AS total_premiums, paid AS paid_premiums, balance, commission, branch, sales_person, code, rm, month, year, updated_at
    FROM CTE
    WHERE rn = 1
    and year IN ('{current_year}');
'''
sales_report = pd.read_sql_query(sales_report_query , p_conn)

p_conn.close()


# In[ ]:









# In[5]:


# sales_report= pd.read_excel("banca_report.xlsx")
# sales_report.head(3)


# In[6]:


sales_report.dtypes


# In[7]:


# they are not required in the output
sales_report.drop(columns={'phone_no','financier'}, inplace = True)
sales_report.head(1)


# In[8]:


##convert to date format
# sales_report['starting_date']= pd.to_datetime(sales_report['starting_date'], dayfirst = True).dt.strftime('%d-%m-%Y')
# sales_report['ending_date']= pd.to_datetime(sales_report['ending_date'], dayfirst = True).dt.strftime('%d-%m-%Y')

# sales_report['starting_date']= pd.to_datetime(sales_report['starting_date'], dayfirst = True).dt.strftime('%d/%m/%Y')
# sales_report['ending_date']= pd.to_datetime(sales_report['ending_date'], dayfirst = True).dt.strftime('%Y/%m/%d')
# sales_report.head()


# In[9]:


# drop row if raw data has total values or totals in any of the columns

if 'TOTAL' in sales_report.iloc[-1].values:
    sales_report=sales_report.drop(sales_report.index[-1])
    
sales_report.tail(1)


# In[10]:


sales_report.shape


# In[11]:


# check to confirm if the sales code is present 
# is_present = 3408 in sales_report['code'].values
# is_present


# In[12]:


#remove spaces from sales codes
sales_report['code'] = sales_report['code'].apply(lambda x: str(x).replace(" ","") if isinstance(x,str) else x )


# In[13]:


sales_report['code'] = pd.to_numeric(sales_report['code'], errors = 'ignore')


# In[ ]:









# In[14]:


# change dtype
sales_report['total_premiums']= sales_report['total_premiums'].fillna(0).astype(int)
sales_report['paid_premiums']= sales_report['paid_premiums'].fillna(0).astype(int)
sales_report['balance']= sales_report['balance'].fillna(0).astype(int)
sales_report['commission']= sales_report['commission'].fillna(0).astype(int)
sales_report['rm']= sales_report['rm'].fillna(0).astype(str)


# In[15]:


sales_report['sum_insured']= sales_report['sum_insured'].fillna(0).astype(int)


# In[16]:


# trim column to remove spaces after the words
sales_report['branch'] = sales_report['branch'].str.strip()


# In[17]:


sales_report.dtypes


# In[18]:


#remove space from the word Operations in rm column
sales_report.loc[sales_report['rm'] == 'Operations ','rm']='Operations'


# In[19]:


#remove 'operations' for anything that's not HFIA Head office( Only HFIA Head office should be operations)
rm_condition = (sales_report['branch'] !='HFIA Head office') & (sales_report['rm'] == 'Operations')


# In[20]:


# Update RM column based on the above condition
sales_report.loc[rm_condition, 'rm'] = ' '


# In[21]:


# add missing code LOREEN  for Loreen Amoding
# rm_code1 = (sales_report['sales_person'] == 'Loreen  Orori  Amoding') & (sales_report['code'].isna() |( sales_report['code'] == ''))

# sales_report.loc[rm_code1, 'code'] = 'LOREEN'


# In[22]:


month_map ={
    1 :'Jan',
    2 :'Feb',
    3 :'Mar',
    4 :'Apr',
    5 :'May',
    6 :'Jun',
    7 :'Jul',
    8 :'Aug',
    9 :'Sep',
    10 :'Oct',
    11 :'Nov',
    12 :'Dec'
}


# In[23]:


#abbreviated months
# sales_report['month_name'] = sales_report['month'].map(month_map)


# In[24]:


# sales_report['month_name'] = pd.to_datetime(sales_report['starting_date'],format='%d/%m/%Y').dt.strftime('%b-%Y')
# convert to datetime
sales_report['starting_date'] = pd.to_datetime(sales_report['starting_date'])
sales_report['month_name'] = sales_report['starting_date'].dt.strftime('%b-%Y')
sales_report['month_name'] 


# In[25]:


sales_report['branch']=sales_report['branch'].fillna(0)


# In[ ]:









# In[26]:


# get mapping for branch targets 
p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

branch_mapping_query = '''
select * from branch_final_employee_dmc_data
                         
'''
branch_mapping = pd.read_sql_query(branch_mapping_query , p_conn)

p_conn.close()


# In[27]:


# branch_mapping =pd.read_excel("branch_final_employee_dmc_data.xlsx")
branch_mapping.head(1)


# In[28]:


branch_mapping.columns


# In[29]:


# only bancassurance targets are needed
columns_to_keep= ['staff_branch','start_date','exit_date','brn_code','staff_zone','target_banca_value','target_banca_life','target_banca_non_life']
filtered_branch_mapping =branch_mapping[columns_to_keep]


# In[30]:


# contains mapping that isn't in the main branch targets mapping (for ease of mapping)

# branch =pd.read_excel("branch.xlsx")
# branch_map = branch.to_dict(orient='records')
# branch_map
mapping_for_branch = [{'branch': 'HFIA Head office', 'branch_2': 'HFCB-BI'},
 {'branch': 'Kisumu Branch', 'branch_2': 'KISUMU BRANCH'},
 {'branch': 'Harambee Avenue Branch', 'branch_2': 'HARAMBEE AVE BRANCH'},
 {'branch': 'Machakos', 'branch_2': 'MACHAKOS BRANCH'},
 {'branch': 'Eldoret Branch', 'branch_2': 'ELDORET BRANCH'},
 {'branch': 'Rehani House', 'branch_2': 'REHANI BRANCH'},
 {'branch': 'Hurlingham Branch', 'branch_2': 'HURLINGHAM BRANCH'},
 {'branch': 'Buruburu Branch', 'branch_2': 'BURUBURU BRANCH'},
 {'branch': 'Rongai Branch', 'branch_2': 'RONGAI BRANCH'},
 {'branch': 'SameerPark', 'branch_2': 'SAMEER BUSINESS PARK BRANCH'},
 {'branch': 'Nyeri Branch', 'branch_2': 'NYERI BRANCH'},
 {'branch': 'Westlands Branch', 'branch_2': 'WESTLANDS BRANCH'},
 {'branch': 'DEFENCE SACCO', 'branch_2': 'HFCB-BI'},
 {'branch': 'Komarock Branch', 'branch_2': 'KOMAROCK BRANCH'},
 {'branch': 'TRM Branch', 'branch_2': 'THIKA ROAD MALL-TRM BRANCH'},
 {'branch': 'Nanyuki', 'branch_2': 'NANYUKI BRANCH'},
 {'branch': 'Meru Branch', 'branch_2': 'MERU BRANCH'},
 {'branch': 'Nakuru Branch', 'branch_2': 'NAKURU BRANCH'},
 {'branch': 'Thika', 'branch_2': 'THIKA BRANCH'},
 {'branch': 'River Road', 'branch_2': 'RIVERROAD BRANCH'},
 {'branch': 'Embu', 'branch_2': 'EMBU BRANCH'},
 {'branch': 'Kitengela Branch', 'branch_2': 'KITENGELA BRANCH'},
 {'branch': 'Mombasa Branch', 'branch_2': 'MOMBASA BRANCH'},
 {'branch': 'Naivasha Branch', 'branch_2': 'NAIVASHA BRANCH'},
 {'branch': 'TELESALES - GRACE GACHOHI', 'branch_2': 'HFCB-BI'},
 {'branch': 'HR', 'branch_2': 'HFCB-BI'},
 {'branch': 'Treasury', 'branch_2': 'HFCB-BI'},
 {'branch': 'Projects', 'branch_2': 'HFCB-BI'},
 {'branch': 'SME', 'branch_2': 'HFCB-BI'},
 {'branch': 'Risk', 'branch_2': 'HFCB-BI'},
 {'branch': 'HFC LTD', 'branch_2': 'HFCB-BI'},
 {'branch': 'HFBI', 'branch_2': 'HFCB-BI'},
 {'branch': 'Marketing', 'branch_2': 'HFCB-BI'},
 {'branch': 0, 'branch_2': 'HFCB-BI'},
 {'branch': 'HeadOffice', 'branch_2': 'HFCB-BI'},
 {'branch': 'HFBI SELF SERVICE - CLIENT PORTAL', 'branch_2': 'HFCB-BI'},
 {'branch': 'Mortgage Sales', 'branch_2': 'MORTGAGE BUSINESS'},
 {'branch': 'Commercial Banking', 'branch_2': 'COMMERCIAL BANKING'}, 
 {'branch': 'Diaspora Banking', 'branch_2': 'DIASPORA BANKING'},  
 {'branch': 'HFDI', 'branch_2': 'PROPERTY'}              
         ]
branch = pd.DataFrame(mapping_for_branch)


# In[31]:


branch_map= pd.merge(branch,filtered_branch_mapping, left_on='branch_2', right_on='staff_branch', how= 'left')
branch_map.drop(columns ='staff_branch', inplace =True)
branch_map.head(2)


# In[32]:


branch_map= branch_map.fillna(0)
branch_map['brn_code'] = branch_map['brn_code'].astype(int)
branch_map['target_banca_value'] = branch_map['target_banca_value'].astype(int)
branch_map['target_banca_life'] = branch_map['target_banca_life'].astype(int)
branch_map['target_banca_non_life'] = branch_map['target_banca_non_life'].astype(int)


# In[33]:


sales_report = pd.merge(sales_report,branch_map, on='branch', how='left')
sales_report.drop(columns={'target_banca_value','brn_code'},inplace = True )


# In[34]:


sales_report.dtypes


# In[35]:


sales_report.rename(columns={'branch_2':'branch_name','staff_zone':'zone'},inplace =True)


# In[36]:


sales_report['zone'] = sales_report['zone'].fillna('Other_business')
sales_report = sales_report.sort_values(by='month')


# In[37]:


# # table for premium types mapping
# premium_type = pd.read_excel("premium_types.xlsx")
# premium_type= premium_type.to_dict(orient='records')
# premium_type


# In[38]:


# mapping for the premiums
premium_type = [
  {'product': 'ipp',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
  {'product': 'WHOLE LIFE',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
  {'product': 'IDD',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
  {'product': 'Imarika Investment',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
  {'product': 'Life With Retrenchment',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'LIFE',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},                
 {'product': 'Life Without Retrenchment',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Life Plus',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Credit Life',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Life With Retrenchment - Top up',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Credit Life Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Credit Life'},
 {'product': 'HF Elimu Plan- API',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'HF Elimu Plan- API'},
 {'product': 'Akiba Savings Plan',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Akiba Savings Plan API'},
 {'product': 'Fariji Funeral Plan',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Fariji Funeral Plan'},
 {'product': 'Somasure and Unit Linked Products',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'},
 {'product': 'Credit Life - Reschedule',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Credit Life'},
 {'product': 'Life Without Retrenchment - Capitalization',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Life Without Retrenchment - Top up',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Life Without Retrenchment - Reschedule',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Life With Retrenchment - Capital Reduction',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Keyman',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'HF Elimu',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'HF Elimu Plan- API'},
 {'product': 'Pension',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'},
 {'product': 'Unit Linked Products',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'},
 {'product': 'Private Comprehensive',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Terrorism and Political Risk',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Fire Material Damage',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'Professional Indemnity',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Domestic Package',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Private TPO',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Golfers Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Commercial TPO',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Personal Accident',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Personal Accident'},
 {'product': 'Fire and Special Peril',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'Fire Residential Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'Fire Commercial Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'PSV Comprehensive',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Commercial Comprehensive',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Travel Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Fire Consequential Loss',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'Burglary Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Machinery Breakdown',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Machinery Breakdown Conloss',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Fidelity Guarantee Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'MONEY',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Money',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'WIBA',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Employers Liability',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Medical Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Life Tables - Capital Reduction',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Contractors All Risk',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Contractors all risk'},
 {'product': 'Performance Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'Advanced Payment Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'Motorcycle Private COMP',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'AUCTIONEERS COMBINED POLICY',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'New HFDI Business',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'HF Afyamed',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Medical/HF Afyamed'},
 {'product': 'SME Combo',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'SME Combo'},
 {'product': 'SME Combo 2',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'SME Combo'},
 {'product': 'Home Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Home Insurance'},
 {'product': 'Trade Finance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'Custom Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'Business Guard Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'SME Combo'},
 {'product': 'Security Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'All Risks Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Contractors all risk'},
 {'product': 'Life Tables',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Public Liability Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'TukTuk Private COMP',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Marine Cargo',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Contractor Plant & Machinery',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Livestock Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Plate Glass Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'WIBA PLUS',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Personal Accident'},
 {'product': 'TSV Comprehensive',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Pet Insurance',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Electronic equipment',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Electronic Equipment',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Bid Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'PSV TPO',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Advance Payment Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'All Risks',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Contractors all risk'},
 {'product': 'Business Guard',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'SME Combo'},
 {'product': 'Burglary',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': "CPM (Contractor's Plant & Machinery)",
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Customs Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Trade Finance'},
 {'product': 'Fidelity Guarantee',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Fire',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'Funeral Expense',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Golfers',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'PA (Personal Accident)',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Personal Accident'},
 {'product': 'D & O',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
{'product': 'Pet',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Plate Glass',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Public Liability',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'PVT (Private Vehicle Third Party)',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'WIBA/GPA (Work Injury Benefits Act / Group Personal Accident)',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Motor',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Livestock',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Machinery Breakdown Con Loss',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Marine',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Medical',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Medical/HF Afyamed'},
 {'product': 'Comesa',
  'vic_check': 'non-vic',
  'life_policy_check': 'non-life',
  'premium_type': 'motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'CPM',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'PA',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Personal Accident'},
{'product': 'GPA',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Personal Accident'},
 {'product': 'PVT',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Medical/HF Afyamed'},
 {'product': 'WIBA/GPA',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Personal Accident'},
 {'product': 'Erection All Risks',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Contractors all risk'},
 {'product': 'GIT',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Home Insurance/DP',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Home Insurance'},
 {'product': 'Somasure',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'},
 {'product': 'Plant All Risk',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Carriers Liability',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'Industrial All Risk',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'FIRE',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},                
 {'product': 'FIRE INSURANCE - RESIDENTIAL PROPERTIES',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'FIRE INSURANCE - COMMERCIAL PROPERTIES',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'FIRE INSURANCE - NSSF',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Fire'},
 {'product': 'LIFE INSURANCE',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'NSSF LIFE INSURANCE',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'},
 {'product': 'LIFE INSURANCE WITHOUT RETRENCHMENT',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'LIFE INSURANCE WITH RETRENCHMENT',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'LIFE INSURANCE WITH RETRENCHMENT/WITHOUT',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'LIFE INSURANCE WITH RETRENCHMENT 2025-6',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'LIFE INSURANCE NO RETRENCHMENT 2025-4.5',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'LIFEPLUS INSURANCE',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'POLISURE',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
 {'product': 'STAFF PERSONAL LOANS INSURANCE',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other GI Premiums'},
 {'product': 'Individual Pension Plan',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'},
 {'product': 'HF ELIMU',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'HF Elimu Plan- API'},
 {'product': 'BONDPLUS',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'NAWIRI',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Life'},
 {'product': 'Akiba',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Akiba Savings Plan API'},
 {'product': 'IMARIKA',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'LIFE'},
  {'product': 'Bankers Blanket Bond',
  'vic_check': 'vic',
  'life_policy_check': 'non-life',
  'premium_type': 'non-motor',
  'policy_category': 'Other Premiums'},
  {'product':'PENSION',
  'vic_check': 'vic',
  'life_policy_check': 'life',
  'premium_type': 'non-motor',
  'policy_category': 'Somasure, pension,Unit Linked and other life Products API'}
    
]
 

banca_type = pd.DataFrame(premium_type)
banca_type


# In[39]:


# banca_type.to_excel('premium_types_mapping.xlsx',index = False)


# In[40]:


sales_report = pd.merge(sales_report,banca_type, on ='product',how ='left')
sales_report.columns


# In[41]:


# this is a list of products that are manually mapped to britam

product_names = ['FIRE INSURANCE - COMMERCIAL PROPERTIES','FIRE INSURANCE - RESIDENTIAL PROPERTIES','LIFE','LIFE INSURANCE',
 'LIFE INSURANCE NO RETRENCHMENT 2025-4.5','LIFE INSURANCE WITH RETRENCHMENT','LIFE INSURANCE WITH RETRENCHMENT 2025-6',
 'LIFE INSURANCE WITH RETRENCHMENT/WITHOUT','LIFE INSURANCE WITHOUT RETRENCHMENT','Life With Retrenchment',
 'Life Without Retrenchment','LIFEPLUS INSURANCE']


# In[42]:


sales_report.loc[sales_report['underwriter']=='BRITAM','underwriter']='Britam'


# In[43]:


sales_report['underwiter_mapping_to_britam'] = sales_report['underwriter'].apply(lambda x:'Britam' if x in product_names else x)


# In[44]:


sales_report.loc[sales_report['product']=='FIRE INSURANCE - COMMERCIAL PROPERTIES','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='FIRE INSURANCE - RESIDENTIAL PROPERTIES','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE INSURANCE','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE INSURANCE NO RETRENCHMENT 2025-4.5','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE INSURANCE WITH RETRENCHMENT','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE INSURANCE WITH RETRENCHMENT 2025-6','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE INSURANCE WITH RETRENCHMENT/WITHOUT','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFE INSURANCE WITHOUT RETRENCHMENT','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='Life With Retrenchment','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='Life Without Retrenchment','underwiter_mapping_to_britam']='Britam'
sales_report.loc[sales_report['product']=='LIFEPLUS INSURANCE','underwiter_mapping_to_britam']='Britam'


# In[45]:


# Vic premiums should only be for Britam
sales_report.loc[sales_report['underwriter']=='Britam','vic_check']='vic'
sales_report.loc[sales_report['underwriter']=='Britam Life','vic_check']='vic'
# vic_premium_condition = (sales_report['underwiter_mapping_to_britam'] !='Britam') & (sales_report['vic_check'] == 'vic')
vic_premium_condition = (sales_report['underwriter'] !='Britam')& (sales_report['underwriter'] !='Britam Life')  & (sales_report['vic_check'] == 'vic')
sales_report.loc[vic_premium_condition, 'vic_check'] = 'non-vic'


# In[46]:


sales_report = sales_report.sort_values(by ='starting_date')


# In[47]:


# add week column
sales_report['week'] = sales_report['starting_date'].apply(lambda x: x.isocalendar()[1])
sales_report.shape


# In[48]:


sales_report['just_month_name'] = sales_report['starting_date'].dt.strftime('%b')
sales_report['week_month'] = 'Week' + '-' +sales_report['week'].astype(str) + ' - ' + sales_report['just_month_name']
sales_report['week_month']


# In[49]:


# sales_report['week_month'] = sales_report.apply( lambda row: f"Week-{row['week']} - {row['just_month_name']}", axis=1 )
# sales_report['week_month']


# In[50]:


# sales_report.loc[sales_report['vic_check']=='vic'].count()


# In[51]:


# ## RMs & BBCs


# In[52]:


p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])
 
role_count_map_query = '''
select * from branch_employee_dmc_data
                         
'''
# role_mapping = pd.read_sql_query(role_count_map_query , p_conn)
 
sales_persons_targets_mapping_trial = pd.read_sql_query(role_count_map_query , p_conn)
 
p_conn.close()


# In[53]:


# months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
#           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# month_names_to_number= {m: i for i, m in enumerate(months, 1)}


# def calculate_targets(df, monthly_target_columns, start_month_col='start_date'):
#     results = []

#     for _, row in df.iterrows():
#         start_month_num = month_names_to_number[row[start_month_col]]
#         out = row.to_dict()

#         for col in target_cols:
#             base = row[col]
#             multiplier = 1
#             annual_total = 0

#             for i, month in enumerate(months, 1):
#                 if i < start_month_num:
#                     value = 0
#                 else:
#                     value = base * multiplier
#                     multiplier += 1
#                     annual_total += value

#                 out[f"{col}_{month}"] = value

#             out[f"{col}_annual_total"] = annual_total

#         results.append(out)

#     return pd.DataFrame(results)


# In[54]:


####test change 

# get targets and other details for all sales persons
# sales_persons_targets_mapping_trial= pd.read_excel("branch_employee_dmc_data.xlsx")

# to include all active and exits
role_mapping = sales_persons_targets_mapping_trial.sort_values(by=['sales_code','active'], ascending=[True,False])
# sales_persons_targets_mapping_trial[['sales_code','active']].head(10)
# sales_persons_targets_mapping_trial_filtered = sales_persons_targets_mapping_trial[sales_persons_targets_mapping_trial['active']==1]
role_mapping =role_mapping.drop_duplicates(subset='sales_code', keep='first')
role_mapping[['sales_code','active']].head(20)


# In[55]:


sales_report = pd.merge(sales_report,role_mapping, left_on = 'code', right_on ='sales_code', how='left')
sales_report['staff_role'] = sales_report['staff_role'].fillna('Others')

sales_report.columns


# In[56]:


segment_map = [{'staff_role':'PB BBC','segment':'PERSONAL BANKING','segment_2':'PERSONAL BANKING'},
               {'staff_role':'SME BBC','segment':'BUSINESS BANKING','segment_2':'BUSINESS BANKING'},
               {'staff_role':'BANCA DSR','segment':'HFCB-BI','segment_2':'HFCB-BI'},
               {'staff_role':'BANCA BDO','segment':'HFCB-BI','segment_2':'HFCB-BI'},
               {'staff_role':'ULTIMATE RM','segment':'ULTIMATE','segment_2':'ULTIMATE'},
               {'staff_role':'SME RM','segment':'BUSINESS BANKING','segment_2':'BUSINESS BANKING'},
               {'staff_role':'SME ARM','segment':'BUSINESS BANKING','segment_2':'BUSINESS BANKING'},
               {'staff_role':'PB RM','segment':'PERSONAL BANKING','segment_2':'PERSONAL BANKING'},
               {'staff_role':'PB ARM','segment':'PERSONAL BANKING','segment_2':'PERSONAL BANKING'},
               {'staff_role':'PB DSR','segment':'PERSONAL BANKING','segment_2':'PERSONAL BANKING'},
               {'staff_role':'SME DSR','segment':'BUSINESS BANKING','segment_2':'BUSINESS BANKING'},
               {'staff_role':'COMMERCIAL RM','segment':'COMMERCIAL','segment_2':'COMMERCIAL'},
               {'staff_role':'DIASPORA RM','segment':'DIASPORA','segment_2':'DIASPORA'},
               {'staff_role':'DIASPORA ARM','segment':'DIASPORA','segment_2':'DIASPORA'},
               {'staff_role':'Business Development Manager','segment':'MORTGAGE','segment_2':'MORTGAGE'},
               {'staff_role':'MORTGAGE RM','segment':'MORTGAGE','segment_2':'MORTGAGE'},
               {'staff_role':'MORTGAGE ARM','segment':'MORTGAGE','segment_2':'MORTGAGE'},
               {'staff_role':'Property Advisor','segment':'PROPERTY','segment_2':'PROPERTY - SALES'},
               {'staff_role':'HFDI PA','segment':'PROPERTY','segment_2':'PROPERTY - SALES'},
               {'staff_role':'HFDI RO','segment':'PROPERTY','segment_2':'PROPERTY - SALES'},
               {'staff_role':'HFDI PM','segment':'PROPERTY','segment_2':'PROPERTY - PROJECT MANAGEMENT'},
               {'staff_role':'HFDI BDM','segment':'PROPERTY','segment_2':'PROPERTY - BUSINESS DEVELOPMENT'},
               {'staff_role':'HFDI DPB','segment':'PROPERTY','segment_2':'PROPERTY - DIGITAL PROPERTY'},
               {'staff_role':'IB RM','segment':'INSTITUTIONAL BANKING','segment_2':'INSTITUTIONAL BANKING'},
               {'staff_role':'SCHEME RM','segment':'INSTITUTIONAL BANKING','segment_2':'INSTITUTIONAL BANKING'}
              ]
                   
segment_mapping = pd.DataFrame(segment_map)
segment_mapping


# In[57]:


sales_report = pd.merge(sales_report,segment_mapping,on ='staff_role', how='left')
sales_report['segment'] = sales_report['segment'].fillna('OTHER SALES')

# if the client is britam holdings, segemnt is hfbi
sales_report.loc[sales_report['insured']=='BRITAM HOLDINGS PLC','segment']='HFCB-BI'


sales_report.loc[(sales_report['branch_name'] == 'HFCB-BI') & (sales_report['segment'] == 'OTHER SALES'),'segment'] = 'HFCB-BI'
sales_report.loc[(sales_report['branch_name'] == 'PROPERTY') & (sales_report['segment'] == 'OTHER SALES'),'segment'] = 'PROPERTY'


# In[58]:


# Segment Esther Mulweye under Business Banking
sales_report.loc[sales_report['sales_person']=='Esther Mulweye','staff_role']='TRADE FINANCE RM'
sales_report.loc[sales_report['sales_person']=='Esther Mulweye','segment']='BUSINESS BANKING'


# In[59]:


sales_report.loc[sales_report['staff_role']=='TRADE FINANCE RM','segment_2']='BUSINESS BANKING'


# In[60]:


sales_report.loc[sales_report['code']== 4035,'segment']='PROPERTY'
sales_report.loc[sales_report['code']== 4035,'segment_2']='PROPERTY - SALES'
sales_report.loc[sales_report['code']== 4035,'branch_name']='PROPERTY'
sales_report.loc[sales_report['code']== 'JD3708','segment_2']='PROPERTY - DIGITAL PROPERTY'


sales_report.loc[sales_report['sales_person']== 'STELLA GACHERI MUTAI','segment']='MORTGAGE'
sales_report.loc[sales_report['sales_person']== 'STELLA GACHERI MUTAI','segment_2']='MORTGAGE'


# In[61]:


sales_report.loc[(sales_report['sales_type'] =='From Profits')&(sales_report['segment'] == 'OTHER SALES'),'segment']='HFCB-BI'
sales_report.loc[(sales_report['sales_type'] =='From Profits')&(sales_report['segment'] == 'HFCB-BI'),'segment_2']='BI INSTALLED'

sales_report.loc[(sales_report['sales_type'] !='From Profits')&(sales_report['segment'] == 'HFCB-BI'),'segment_2']='BI SALES'


# In[62]:


# useful when mapping the premiums in the summaries below( to both installed and sales as advised by director)
sales_report.loc[(sales_report['insured']=='BRITAM HOLDINGS PLC')&(sales_report['product']=='Medical'),'segment_2']='BI(ALL)'
# sales_report.loc[sales_report['code']==3568,['staff_role','segment']]='TRADE FINANCE'
sales_report['segment_2'] = sales_report['segment_2'].fillna('OTHER SALES')

# for hfdi,default to hfdi sales if unmapped
sales_report.loc[(sales_report['segment'] =='PROPERTY')&(sales_report['segment_2'] == 'OTHER SALES'),'segment_2']='PROPERTY - SALES'


# In[63]:


sales_report.columns


# In[64]:


# segment_vic_table = pd.read_excel('segment_vic_targets.xlsx')
# segment_vic_table= segment_vic_table.to_dict(orient='records')
# segment_vic_table


# In[65]:


# segemnt vic life and non- life targets
segment_vic_table= [{'SEGMENT': 'PERSONAL BANKING',
  'target_banca_value': 2449592.21372315,
  'target_banca_life': 240246.380389814,
  'target_banca_non_life': 2209345.83333333},
 {'SEGMENT': 'BUSINESS BANKING',
  'target_banca_value': 3140369.4439572,
  'target_banca_life': 139834.72173498,
  'target_banca_non_life': 3000534.72222222},
 {'SEGMENT': 'ULTIMATE',
  'target_banca_value': 1002468.13632442,
  'target_banca_life': 98318.1363244176,
  'target_banca_non_life': 904150.0},
 {'SEGMENT': 'DIASPORA',
  'target_banca_value': 554370.478529236,
  'target_banca_life': 54370.4785292361,
  'target_banca_non_life': 500000},
 {'SEGMENT': 'COMMERCIAL',
  'target_banca_value': 5136888.733682672,
  'target_banca_life': 228735.9559048946,
  'target_banca_non_life': 4908152.777777777},
 {'SEGMENT': 'MORTGAGE',
  'target_banca_value': 706498.977345634,
  'target_banca_life': 69290.6440123006,
  'target_banca_non_life': 637208.3333333334},
 {'SEGMENT': 'BI SALES',
  'target_banca_value': 6074519.138238094,
  'target_banca_life': 595764.9715714253,
  'target_banca_non_life': 5478754.166666669},                    
 {'SEGMENT': 'BI INSTALLED',
  'target_banca_value': 23718180.5833333,
  'target_banca_life': 10910363.0683333,
  'target_banca_non_life': 12807817.515},
 {'SEGMENT': 'PROPERTY - SALES',
  'target_banca_value': 1962381.1262077,
  'target_banca_life': 87381.1262077008,
  'target_banca_non_life':1875000},
 {'SEGMENT': 'PROPERTY - DIGITAL PROPERTY',
  'target_banca_value':218042.347356411 ,
  'target_banca_life':9709.01402307787 ,
  'target_banca_non_life': 208333.333333333},
 {'SEGMENT': 'PROPERTY - BUSINESS DEVELOPMENT',
  'target_banca_value': 872169.389425645,
  'target_banca_life': 38836.0560923115 ,
  'target_banca_non_life': 833333.333333333 },
  {'SEGMENT': 'PROPERTY - PROJECT MANAGEMENT',
  'target_banca_value': 1308254.08413847 ,
  'target_banca_life': 58254.0841384672,
  'target_banca_non_life': 1250000},
  {'SEGMENT': 'INSTITUTIONAL BANKING',
  'target_banca_value': 1308254.08413847 ,
  'target_banca_life': 58254.0841384672,
  'target_banca_non_life': 1250000}
  ]

segment_vic_targets = pd.DataFrame(segment_vic_table).reset_index(drop=True)

segment_vic_targets


# In[66]:


# segment_vic_targets.to_excel('vic_segment_targets.xlsx',index = False)


# In[67]:


# revised segment targets on Feb

segment_table = [{'SEGMENT': 'PERSONAL BANKING',
  'target_banca_value': 2449592.2137231478,
  'target_banca_life': 240246.3803898143,
  'target_banca_non_life': 2209345.8333333335},
 {'SEGMENT': 'BUSINESS BANKING',
  'target_banca_value': 3140369.443957201,
  'target_banca_life': 139834.7217349805,
  'target_banca_non_life': 3000534.7222222206},
 {'SEGMENT': 'ULTIMATE',
  'target_banca_value': 1002468.1363244175,
  'target_banca_life': 98318.1363244176,
  'target_banca_non_life': 904150.0},
 {'SEGMENT': 'DIASPORA',
  'target_banca_value': 554370.478529236,
  'target_banca_life': 54370.4785292361,
  'target_banca_non_life': 500000},
 {'SEGMENT': 'COMMERCIAL',
  'target_banca_value': 5136888.733682672,
  'target_banca_life': 228735.9559048946,
  'target_banca_non_life': 4908152.777777777},
 {'SEGMENT': 'MORTGAGE',
  'target_banca_value': 706498.977345634,
  'target_banca_life': 69290.6440123006,
  'target_banca_non_life': 637208.3333333334},
 {'SEGMENT': 'BI SALES',
  'target_banca_value': 6074519.13823809,
  'target_banca_life': 595764.971571425,
  'target_banca_non_life': 5478754.16666667},                
 {'SEGMENT': 'BI INSTALLED',
  'target_banca_value': 31944131.9444445,
  'target_banca_life': 14694300.6944445,
  'target_banca_non_life': 17249831.25},
 {'SEGMENT': 'PROPERTY - SALES',
  'target_banca_value': 1962381.1262077,
  'target_banca_life': 87381.1262077008,
  'target_banca_non_life':1875000},
 {'SEGMENT': 'PROPERTY - DIGITAL PROPERTY',
  'target_banca_value':218042.347356411 ,
  'target_banca_life':9709.01402307787 ,
  'target_banca_non_life': 208333.333333333},
 {'SEGMENT': 'PROPERTY - BUSINESS DEVELOPMENT',
  'target_banca_value': 872169.389425645,
  'target_banca_life': 38836.0560923115 ,
  'target_banca_non_life': 833333.333333333 },
  {'SEGMENT': 'PROPERTY - PROJECT MANAGEMENT',
  'target_banca_value': 1308254.08413847 ,
  'target_banca_life': 58254.0841384672,
  'target_banca_non_life': 1250000},
  {'SEGMENT': 'INSTITUTIONAL BANKING',
  'target_banca_value': 1308254.08413847 ,
  'target_banca_life': 58254.0841384672,
  'target_banca_non_life': 1250000}
                ]


segment_targets = pd.DataFrame(segment_table).reset_index(drop=True)
# segment_targets['annual_target_banca']= segment_targets['annual_target_banca_non_life']+segment_targets['annual_target_banca_life']
segment_targets


# In[68]:


segment_targets['SEGMENT']


# In[69]:


# def calculate_segment_targets_full_year(group, monthly_target_columns, mtd_date, mtd_fraction):
#     """
#     Calculates for segment-level targets (no sales_code, no date columns):
#     - monthly target (ramped) for the reporting month
#     - annual total (sum of ramped months for full year)
#     - YTD target = sum of past months + current month * mtd_fraction

#     Assumes segment is active the whole year.
#     Old columns are suffixed '_base', new calculated columns '_calc'.
#     """

#     result = {}
#     report_year = mtd_date.year
#     mtd_month_num = mtd_date.month

#     # Step 1: preserve base values
#     for col in monthly_target_columns:
#         base_value = group[col].dropna().iloc[0] if col in group.columns and not group[col].dropna().empty else 0
#         result[f'{col}_base'] = base_value
#         result[f'{col}_calc'] = 0
#         result[f'annual_{col}_calc'] = 0
#         result[f'ytd_{col}_calc'] = 0

#     # Since segments run full year, we just calculate once per group
#     past_months_sum = {col: 0 for col in monthly_target_columns}
#     current_month_value = {col: 0 for col in monthly_target_columns}

#     for month_num in range(1, 13):
#         month_index = month_num  # ramp: Jan=1, Feb=2, ...

#         for col in monthly_target_columns:
#             base = result[f'{col}_base'] or 0
#             monthly_value = base * month_index

#             # Reporting month target
#             if month_num == mtd_month_num:
#                 result[f'{col}_calc'] += monthly_value
#                 current_month_value[col] = monthly_value

#             # Annual total
#             result[f'annual_{col}_calc'] += monthly_value

#             # Past months for YTD
#             if month_num < mtd_month_num:
#                 past_months_sum[col] += monthly_value

#     # YTD = past months + current month * MTD fraction
#     for col in monthly_target_columns:
#         result[f'ytd_{col}_calc'] = past_months_sum[col] + current_month_value[col] * mtd_fraction

#     return pd.Series(result)


# In[70]:


# def calculate_segment_targets_full_year(group, monthly_target_columns, mtd_date, mtd_fraction):

#     result = {}
#     mtd_month_num = mtd_date.month
#     growth_rate = 1.5  # geometric growth as at 04/03/2026

#     life_columns = [col for col in monthly_target_columns if 'target_banca_life' in col.lower()]

#     for col in monthly_target_columns:
#         base_value = (
#             group[col].dropna().iloc[0]
#             if col in group.columns and not group[col].dropna().empty
#             else 0
#         )

#         result[f'{col}_base'] = base_value
#         result[f'{col}_calc'] = 0
#         result[f'annual_{col}_calc'] = 0
#         result[f'ytd_{col}_calc'] = 0

#     past_months_sum = {col: 0 for col in monthly_target_columns}
#     current_month_value = {col: 0 for col in monthly_target_columns}

#     for month_num in range(1, 13):

#         for col in monthly_target_columns:
#             base = result[f'{col}_base'] or 0

#             if col in life_columns:
#                 monthly_value = base * (growth_rate ** (month_num - 1))
#             else:
#                 monthly_value = base
           
#             # Reporting month
#             if month_num == mtd_month_num:
#                 result[f'{col}_calc'] = monthly_value
#                 current_month_value[col] = monthly_value

#             # Annual total
#             result[f'annual_{col}_calc'] += monthly_value

#             # Past months for YTD
#             if month_num < mtd_month_num:
#                 past_months_sum[col] += monthly_value

#     # YTD calculation
#     for col in monthly_target_columns:
#         result[f'ytd_{col}_calc'] = (
#             past_months_sum[col]
#             + current_month_value[col] * mtd_fraction
#         )


    
#     return pd.Series(result)


# In[71]:


def calculate_segment_targets_full_year(group, monthly_target_columns, mtd_date, mtd_fraction):

    result = {}
    mtd_month_num = mtd_date.month
    growth_rate = 1.5  # geometric growth

    # Detect segment
    segment_value = group['SEGMENT'].iloc[0] if 'SEGMENT' in group.columns else None

    life_columns = [
        col for col in monthly_target_columns
        if 'target_banca_life' in col.lower()
    ]

    # keep the base values
    for col in monthly_target_columns:
        base_value = (
            group[col].dropna().iloc[0]
            if col in group.columns and not group[col].dropna().empty
            else 0
        )

        result[f'{col}_base'] = base_value
        result[f'{col}_calc'] = 0
        result[f'annual_{col}_calc'] = 0
        result[f'ytd_{col}_calc'] = 0

    past_months_sum = {col: 0 for col in monthly_target_columns}
    current_month_value = {col: 0 for col in monthly_target_columns}

    for month_num in range(1, 13):

        for col in monthly_target_columns:
            base = result[f'{col}_base'] or 0

            if col in life_columns:
                if segment_value == 'BI INSTALLED':
                    monthly_value = base  # no ramp for BI INSTALLED as directed by HFBI
                else:
                    monthly_value = base * (growth_rate ** (month_num - 1))
            else:
                monthly_value = base

            # Reporting month
            if month_num == mtd_month_num:
                result[f'{col}_calc'] = monthly_value
                current_month_value[col] = monthly_value

            # Annual
            result[f'annual_{col}_calc'] += monthly_value

            # Past months
            if month_num < mtd_month_num:
                past_months_sum[col] += monthly_value

    # YTD
    for col in monthly_target_columns:
        result[f'ytd_{col}_calc'] = (
            past_months_sum[col]
            + current_month_value[col] * mtd_fraction
        )

    # Total banca aggregation
    if "target_banca_value" in monthly_target_columns:
        result["target_banca_value_calc"] = (
            result.get("target_banca_life_calc", 0)
            + result.get("target_banca_non_life_calc", 0)
        )
        result["annual_target_banca_value_calc"] = (
            result.get("annual_target_banca_life_calc", 0)
            + result.get("annual_target_banca_non_life_calc", 0)
        )
        result["ytd_target_banca_value_calc"] = (
            result.get("ytd_target_banca_life_calc", 0)
            + result.get("ytd_target_banca_non_life_calc", 0)
        )

    return pd.Series(result)



# In[72]:


# policy_targets_table = pd.read_excel('policy_category_targets.xlsx')
# policy_targets_table = policy_targets_table.to_dict(orient='records')
# policy_targets_table


# In[73]:


policy_targets= [{'policy_category': 'Life', 'annual_targets': 154563161.408364},
 {'policy_category': 'Credit Life', 'annual_targets': 34654507.6106113},
 {'policy_category': 'Fire', 'annual_targets': 58044327.65955832},
 {'policy_category': 'Trade Finance', 'annual_targets': 50000000.0},
 {'policy_category': 'Other GI Premiums', 'annual_targets': 89418921.58399999},
 {'policy_category': 'HF Elimu Plan- API', 'annual_targets': 48773571.42857143},
 {'policy_category': 'Akiba Savings Plan API', 'annual_targets': 9032142.857142858},
 {'policy_category': 'Fariji Funeral Plan', 'annual_targets': 4516071.428571429},
 {'policy_category': 'Contractors all risk', 'annual_targets': 4253148.003915409},
 {'policy_category': 'Personal Accident', 'annual_targets': 500000.0},
 {'policy_category': 'SME Combo', 'annual_targets': 17747494.42},
 {'policy_category': 'Somasure, pension,Unit Linked and other life Products API',
  'annual_targets': 18678214.285714284},
 {'policy_category': 'Home Insurance', 'annual_targets': 7956196.800000001},
 {'policy_category': 'Medical/HF Afyamed', 'annual_targets': 23393227.200000003},
 {'policy_category': 'Other Premiums', 'annual_targets': 442074015.646884}]

policy_targets_table = pd.DataFrame(policy_targets)
policy_targets_table


# ## get calculations


# In[74]:


year= dt.now().year
year


# In[75]:


today = dt.today()

def get_reporting_date():
    # if today.weekday() == 0: # Monday is 0
    #     reporting_date = today - timedelta(days = 2) #Should return Saturday's date
    # else:
    #     reporting_date = today - timedelta(days = 1) # returns previous day
    max_date = sales_report['starting_date'].max()
    report_date = max_date.strftime('%d-%b-%Y')
    max_month_name = max_date.strftime('%b-%Y')
    report_month = max_date.strftime('%b')
    report_year = max_date.year

    return report_date,max_month_name,report_month,report_year


report_date,max_month_name,report_month,report_year =get_reporting_date()
report_date


# In[76]:


# month to date fraction
def month_to_date_fraction(mtd_date):
    
  total_days = monthrange(mtd_date.year,mtd_date.month)[1]
  current_day = mtd_date.day
    
  fraction = current_day/ total_days

  return fraction
    
mtd_date = dt.strptime(report_date, "%d-%b-%Y").date()

mtd_fraction= month_to_date_fraction(mtd_date)
mtd_fraction


# In[77]:


# year_to_date_fraction
def year_to_date_fraction(ytd_date):
  start_year = date(ytd_date.year,1,1)
  end_year = date(ytd_date.year+1,1,1)

  total_days = (end_year - start_year).days
  elapsed_days = (ytd_date - start_year).days

  fraction = elapsed_days/ total_days

  return fraction

# ytd_date = string_to_date(formatted_date)
ytd_date = dt.strptime(report_date, "%d-%b-%Y").date()
fraction = year_to_date_fraction(ytd_date)
fraction


# In[78]:


def sales_persons_year_to_date_fraction(df, report_year, report_date):
    df['start_date'] = pd.to_datetime(df['start_date'])
    report_date = pd.to_datetime(report_date, dayfirst=True)
    start_of_year = pd.Timestamp(f"{report_year}-01-01")
    end_of_year   = pd.Timestamp(f"{report_year}-12-31")

    # Get earliest start_date per sales code especially for promoted persons in the same line (only within the report year)
    effective_start = (
        df.groupby('sales_code')['start_date']
          .transform(lambda x: max(min(x), start_of_year))
    )

    def get_ytd_fraction(start_date):
        total_days = (end_of_year - start_date).days
        if total_days <= 0:
            return 1.0 if report_date >= end_of_year else 0.0
        elapsed_days = (report_date - start_date).days
        return max(0.0, min(elapsed_days / total_days, 1.0))

    df['ytd_fraction'] = effective_start.apply(get_ytd_fraction)
    return df
    


# In[79]:


# def calculation_branch_formulas(df):
#     column_name = f'{report_month}-{report_year}'
#     if column_name in df.columns:
#         df['current_month_actuals'] = df[column_name]

#     else:
#         df['current_month_actuals'] = 0
   
   
#     if 'annual_targets' in df.columns and 'monthly_targets' in df.columns:
      
#         df['mtd_target'] = df['monthly_targets'] * mtd_fraction
#         df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target']).clip(upper=1.2)
#         df['ytd_target'] = df['annual_targets'] * fraction
#         if 'ytd_cumulative' in df.columns:
#             df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(upper=1.2)
#         else:
#             df['ytd_score'] =0

#     else:
#         df['monthly_targets'] = df['annual_targets'] / 12
#         df['mtd_target'] = df['monthly_targets'] * mtd_fraction
#         df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target']).clip(upper=1.2)
#         df['ytd_target'] = df['annual_targets'] * fraction
#         if 'ytd_cumulative' in df.columns:
#             df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(upper=1.2)
#         else:
#             df['ytd_score'] =0
    
#     return df


# In[80]:


def calculation_branch_formulas(df):
    column_name = f'{report_month}-{report_year}'

    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]
    else:
        df['current_month_actuals'] = 0

    # if 'monthly_targets' not in df.columns:
    #     df['monthly_targets'] = df['annual_targets'] / 12


    df['mtd_target'] = df['monthly_targets'] * mtd_fraction
    # df['ytd_target'] = df['annual_targets'] * fraction


    df['current_month_score'] = 0.0
    df['ytd_score'] = 0.0

    non_zero_annual_targets = df['annual_targets'] > 0

    
    df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_score'] = (
        df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_actuals']
        / df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'mtd_target']
    ).clip(upper=1.2)

    
    if 'ytd_cumulative' in df.columns:
        df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_score'] = (
            df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_cumulative']
            / df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_target']
        ).clip(upper=1.2)

    return df


# In[81]:


def calculation_branch_formulas_no_capping(df):
    column_name = f'{report_month}-{report_year}'

    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]
    else:
        df['current_month_actuals'] = 0

    # if 'monthly_targets' not in df.columns:
    #     df['monthly_targets'] = df['annual_targets'] / 12


    df['mtd_target'] = df['monthly_targets'] * mtd_fraction
    # df['ytd_target'] = df['annual_targets'] * fraction


    df['current_month_score'] = 0.0
    df['ytd_score'] = 0.0

    non_zero_annual_targets = df['annual_targets'] > 0

    
    df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_score'] = (
        df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_actuals']
        / df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'mtd_target']
    )

    
    if 'ytd_cumulative' in df.columns:
        df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_score'] = (
            df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_cumulative']
            / df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_target']
        )

    return df


# In[82]:


def calculation_segment_formulas(df):
    column_name = f'{report_month}-{report_year}'

    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]
    else:
        df['current_month_actuals'] = 0

    # if 'monthly_targets' not in df.columns:
    #     df['monthly_targets'] = df['annual_targets'] / 12


    df['mtd_target'] = df['monthly_targets'] * mtd_fraction
    # df['ytd_target'] = df['annual_targets'] * fraction


    df['current_month_score'] = 0.0
    df['ytd_score'] = 0.0

    non_zero_annual_targets = df['annual_targets'] > 0

    
    df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_score'] = (
        df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_actuals']
        / df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'mtd_target']
    ).clip(upper=1.2)

    
    if 'ytd_cumulative' in df.columns:
        df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_score'] = (
            df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_cumulative']
            / df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_target']
        ).clip(upper=1.2)

    return df


# In[83]:


def calculation_segment_formulas_without_capping(df):
    column_name = f'{report_month}-{report_year}'

    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]
    else:
        df['current_month_actuals'] = 0

    # if 'monthly_targets' not in df.columns:
    #     df['monthly_targets'] = df['annual_targets'] / 12


    df['mtd_target'] = df['monthly_targets'] * mtd_fraction
    # df['ytd_target'] = df['annual_targets'] * fraction


    df['current_month_score'] = 0.0
    df['ytd_score'] = 0.0

    non_zero_annual_targets = df['annual_targets'] > 0

    
    df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_score'] = (
        df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_actuals']
        / df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'mtd_target']
    )

    
    if 'ytd_cumulative' in df.columns:
        df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_score'] = (
            df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_cumulative']
            / df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_target']
        )

    return df


# In[84]:


#updated
def calculation_formulas(df):
    column_name = f'{report_month}-{report_year}'
    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]

    else:
        df['current_month_actuals'] = 0

    if 'annual_targets' in df.columns and 'monthly_targets' in df.columns:
        df['mtd_target'] = df['monthly_targets'] * mtd_fraction
        df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target']).clip(upper=1.2)
        df['ytd_target'] = df['annual_targets'] * df['ytd_fraction']
        if 'ytd_cumulative' in df.columns:
            df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(upper=1.2)
        else:
            df['ytd_score'] =0

    else:
        df['monthly_targets'] = df['annual_targets'] / 12
        df['mtd_target'] = df['monthly_targets'] * mtd_fraction
        df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target']).clip(upper=1.2)
        df['ytd_target'] = df['annual_targets'] * df['ytd_fraction']
        if 'ytd_cumulative' in df.columns:
            df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(upper=1.2)
        else:
            df['ytd_score'] =0
    
    return df


# In[85]:


def calculation_formulas_without_ytd(df):
    column_name = f'{report_month}-{report_year}'
    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]

    else:
        df['current_month_actuals'] = 0

    if 'annual_targets' in df.columns and 'monthly_targets' in df.columns:
        df['mtd_target'] = df['monthly_targets'] * mtd_fraction
        df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target']).clip(upper=1.2)
        # df['ytd_target'] = df['annual_targets'] * df['ytd_fraction']
        if 'ytd_cumulative' in df.columns:
            df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(upper=1.2)
        else:
            df['ytd_score'] =0

    else:
        df['monthly_targets'] = df['annual_targets'] / 12
        df['mtd_target'] = df['monthly_targets'] * mtd_fraction
        df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target']).clip(upper=1.2)
        # df['ytd_target'] = df['annual_targets'] * df['ytd_fraction']
        if 'ytd_cumulative' in df.columns:
            df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target']).clip(upper=1.2)
        else:
            df['ytd_score'] =0
    
    return df


# In[86]:


def calculation_formulas_without_ytd_and_uncapped(df):
    column_name = f'{report_month}-{report_year}'
    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]

    else:
        df['current_month_actuals'] = 0

    if 'annual_targets' in df.columns and 'monthly_targets' in df.columns:
        df['mtd_target'] = df['monthly_targets'] * mtd_fraction
        df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target'])
        # df['ytd_target'] = df['annual_targets'] * df['ytd_fraction']
        if 'ytd_cumulative' in df.columns:
            df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target'])
        else:
            df['ytd_score'] =0

    else:
        df['monthly_targets'] = df['annual_targets'] / 12
        df['mtd_target'] = df['monthly_targets'] * mtd_fraction
        df["current_month_score"] = (df['current_month_actuals'] / df['mtd_target'])
        # df['ytd_target'] = df['annual_targets'] * df['ytd_fraction']
        if 'ytd_cumulative' in df.columns:
            df['ytd_score'] = (df['ytd_cumulative'] / df['ytd_target'])
        else:
            df['ytd_score'] =0
    
    return df


# In[87]:


def total_row(df):
    total_row = df.sum(numeric_only =True)
    if 'current_month_actuals' != 0:
        month_ratio = (df['current_month_actuals'].sum() / df['mtd_target'].sum())
    else:
        month_ratio = 0
    total_row["current_month_score"] = min((month_ratio),1.2)
    
    if 'ytd_cumulative' != 0:
        year_ratio = (df['ytd_cumulative'].sum() / df['ytd_target'].sum())
    else:
        year_ratio = 0
        
    total_row['ytd_score'] = min((year_ratio),1.2)
    total_row = pd.DataFrame(total_row).T
    total_row.index = ['Total']
    df = pd.concat([df, total_row],axis = 0)
    
    return df

def total_row_less_ib(df):
    df_for_total = df[df['SEGMENT'] != 'INSTITUTIONAL BANKING']
    total_row = df_for_total.sum(numeric_only =True)
    if 'current_month_actuals' != 0:
        month_ratio = (df_for_total['current_month_actuals'].sum() / df_for_total['mtd_target'].sum())
    else:
        month_ratio = 0
    total_row["current_month_score"] = min((month_ratio),1.2)
    
    if 'ytd_cumulative' != 0:
        year_ratio = (df_for_total['ytd_cumulative'].sum() / df_for_total['ytd_target'].sum())
    else:
        year_ratio = 0
        
    total_row['ytd_score'] = min((year_ratio),1.2)
    total_row = pd.DataFrame(total_row).T
    total_row.index = ['Total']
    df = pd.concat([df, total_row],axis = 0)
    
    return df
# In[88]:


def uncapped_total_row(df):
    total_row = df.sum(numeric_only =True)
    if 'current_month_actuals' != 0:
        month_ratio = (df['current_month_actuals'].sum() / df['mtd_target'].sum())
    else:
        month_ratio = 0
    total_row["current_month_score"] = min((month_ratio),1.2)
    
    if 'ytd_cumulative' != 0:
        year_ratio = (df['ytd_cumulative'].sum() / df['ytd_target'].sum())
    else:
        year_ratio = 0
        
    total_row['ytd_score'] = year_ratio
    uncapped_total_row = pd.DataFrame(total_row).T
    uncapped_total_row.index = ['Total']
    df = pd.concat([df, uncapped_total_row],axis = 0)
    
    return df


def uncapped_total_row_less_ib(df):
    df_for_total = df[df['SEGMENT'] != 'INSTITUTIONAL BANKING']
    total_row = df_for_total.sum(numeric_only =True)
    if 'current_month_actuals' != 0:
        month_ratio = (df_for_total['current_month_actuals'].sum() / df_for_total['mtd_target'].sum())
    else:
        month_ratio = 0
    total_row["current_month_score"] = min((month_ratio),1.2)
    
    if 'ytd_cumulative' != 0:
        year_ratio = (df_for_total['ytd_cumulative'].sum() / df_for_total['ytd_target'].sum())
    else:
        year_ratio = 0
        
    total_row['ytd_score'] = year_ratio
    uncapped_total_row = pd.DataFrame(total_row).T
    uncapped_total_row.index = ['Total']
    df = pd.concat([df, uncapped_total_row],axis = 0)
    
    return df






# In[89]:


def rank_performance(dataframe,sort_column):
    # Exclude the Total row
    df_without_last_row = dataframe.iloc[:-1].copy()
    df_without_last_row['rank'] = df_without_last_row[sort_column].rank(ascending=False, method='first')

    # Sort the new DataFrame by 'rank'
    sorted_df = df_without_last_row.sort_values(by='rank')

    # Get the Total row
    last_row = dataframe.iloc[-1:]

    # Reattach the Total row to the sorted DataFrame
    result_df = pd.concat([sorted_df, last_row])
    result_df = result_df.reindex(['rank']+[column for column in result_df.columns if column not in ['rank']], axis=1)
    
    return result_df


# In[90]:


# #updated
def calculate_deficits(df, report_month):
    current_month = dt.strptime(f'{report_month}','%b').month
    required_columns = {'annual_targets','monthly_targets','ytd_target','ytd_cumulative' }
    
    if required_columns.issubset(df.columns):
        remaining_months = 12-current_month+1
        
        df['ytd_deficit'] = (df['ytd_target'] - df['ytd_cumulative'])
        
        # df['adjusted_annual_targets'] = ((df['ytd_target']+ (df['ytd_deficit'].abs()))) + (df['monthly_targets'].apply(lambda x: x / remaining_months if x > 0 else 0))- df['ytd_cumulative']
        # df['adjusted_annual_targets'] = ((df['ytd_target']+ df['ytd_deficit'].abs()) + df['monthly_targets']*remaining_months - df['ytd_cumulative'])
        
        df['adjusted_annual_targets'] = (df['annual_targets'] - df['ytd_cumulative'])

        # df['adjusted_monthly_targets'] = df['adjusted_annual_targets'] / remaining_months
                  
    return df






# In[91]:


def calculate_targets_with_ytd_fraction(group, monthly_target_columns, mtd_date, mtd_fraction):
    result = {}
    report_year = mtd_date.year
    year_start = pd.Timestamp(report_year, 1, 1)
    year_end = pd.Timestamp(report_year, 12, 31)

    mtd_month = mtd_date.month

    # initialize result fields
    for col in monthly_target_columns:
        result[f'{col}_base'] = 0
        result[f'{col}_calc'] = 0
        result[f'annual_{col}_calc'] = 0
        result[f'ytd_{col}_calc'] = 0

    # iterate through each promotion row
    for _, row in group.iterrows():

        start_date = pd.to_datetime(row['start_date'], errors='coerce')
        exit_date = pd.to_datetime(row['exit_date'], errors='coerce')

        if pd.isna(start_date):
            continue

        if pd.isna(exit_date):
            exit_date = year_end

        # restrict to reporting year
        role_start = max(start_date, year_start)
        role_end = min(exit_date, year_end)
# role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))

        
        if role_start > role_end:
            continue

        start_month = role_start.month
        end_month = role_end.month

        for col in monthly_target_columns:

            base = row.get(col, 0)
            if pd.isna(base):
                base = 0

            # store latest base for reference
            result[f'{col}_base'] = base

            # LIFE (ramped)
            if col == "target_banca_life":
                # monthly_ramps = [base * (i+1) for i in range(12)]
                # monthly_ramps = [base*(1.5^((i+1)-1)) for i in range(12)] # geometric growth rate of 1.5
                monthly_ramps = [base * (1.5 ** i) for i in range(12)] 

                active_ramps = monthly_ramps[start_month-1:end_month]

                annual_value = sum(active_ramps)

                # YTD calculation
                ytd_value = 0
                for m in range(start_month, end_month+1):
                    month_value = monthly_ramps[m-1]

                    if m < mtd_month:
                        ytd_value += month_value
                    elif m == mtd_month:
                        ytd_value += month_value * mtd_fraction

                current_month_value = (
                    monthly_ramps[mtd_month-1]
                    if start_month <= mtd_month <= end_month
                    else 0
                )

            # NON-LIFE (straight)
            elif col == "target_banca_non_life":
                months_active = end_month - start_month + 1
                annual_value = base * months_active

                current_month_value = (
                    base if start_month <= mtd_month <= end_month else 0
                )

                ytd_months = max(
                    0,
                    min(end_month, mtd_month) - start_month
                )

                ytd_value = base * ytd_months

                if start_month <= mtd_month <= end_month:
                    ytd_value += base * mtd_fraction

            else:
                continue

            result[f'{col}_calc'] += current_month_value
            result[f'annual_{col}_calc'] += annual_value
            result[f'ytd_{col}_calc'] += ytd_value

    # total banca
    if "target_banca_value" in monthly_target_columns:
        result["target_banca_value_calc"] = (
            result.get("target_banca_life_calc", 0) +
            result.get("target_banca_non_life_calc", 0)
        )
        result["annual_target_banca_value_calc"] = (
            result.get("annual_target_banca_life_calc", 0) +
            result.get("annual_target_banca_non_life_calc", 0)
        )
        result["ytd_target_banca_value_calc"] = (
            result.get("ytd_target_banca_life_calc", 0) +
            result.get("ytd_target_banca_non_life_calc", 0)
        )

    return pd.Series(result)


# In[92]:


monthly_target_column =['target_banca_value','target_banca_life','target_banca_non_life']

annual_targets_df =(
    segment_targets
    .groupby('SEGMENT')
    .apply(calculate_segment_targets_full_year,monthly_target_columns=monthly_target_column, mtd_date=mtd_date,mtd_fraction= mtd_fraction)
    .reset_index()
                   )

segment_targets = pd.merge(
    segment_targets,
    annual_targets_df,
    on='SEGMENT',
    how='left')

segment_targets_columns_to_keep=['SEGMENT','target_banca_value_calc', 'annual_target_banca_value_calc','ytd_target_banca_value_calc','target_banca_life_calc', 
                                 'annual_target_banca_life_calc','ytd_target_banca_life_calc','target_banca_non_life_calc', 'annual_target_banca_non_life_calc',
                                 'ytd_target_banca_non_life_calc']
segment_targets = segment_targets[segment_targets_columns_to_keep]
segment_targets = segment_targets.rename(columns={'annual_target_banca_value_calc':'annual_target_banca_value','annual_target_banca_non_life_calc':'annual_target_banca_non_life',
                                                  'annual_target_banca_life_calc':'annual_target_banca_life','target_banca_value_calc':'target_banca_value','target_banca_life_calc':'target_banca_life',
                                                  'target_banca_non_life_calc':'target_banca_non_life'})

segment_targets


# In[93]:


monthly_target_column =['target_banca_value','target_banca_life','target_banca_non_life']

annual_targets_df =(
    segment_vic_targets
    .groupby('SEGMENT')
    .apply(calculate_segment_targets_full_year,monthly_target_columns=monthly_target_column, mtd_date=mtd_date,mtd_fraction= mtd_fraction)
    .reset_index()
                   )

segment_vic_targets = pd.merge(
    segment_vic_targets,
    annual_targets_df,
    on='SEGMENT',
    how='left')

segment_vic_targets_columns_to_keep=['SEGMENT','target_banca_value_calc', 'annual_target_banca_value_calc','ytd_target_banca_value_calc','target_banca_life_calc', 
                                 'annual_target_banca_life_calc','ytd_target_banca_life_calc','target_banca_non_life_calc', 'annual_target_banca_non_life_calc',
                                 'ytd_target_banca_non_life_calc']
segment_vic_targets = segment_vic_targets[segment_vic_targets_columns_to_keep]
segment_vic_targets = segment_vic_targets.rename(columns={'annual_target_banca_value_calc':'annual_target_banca_value','annual_target_banca_non_life_calc':'annual_target_banca_non_life',
                                                  'annual_target_banca_life_calc':'annual_target_banca_life','target_banca_value_calc':'target_banca_value','target_banca_life_calc':'target_banca_life',
                                                  'target_banca_non_life_calc':'target_banca_non_life'})

segment_vic_targets


# In[94]:


# def calculate_deficits(df, report_month):
#     current_month = dt.strptime(report_month, '%b').month

#     required_columns = {'annual_targets','monthly_targets','ytd_target','ytd_cumulative' }

#     if required_cols.issubset(df.columns):

#         # Dynamic remaining months (inclusive of report month)
#         remaining_months = 12 - current_month + 1

#         df['ytd_deficit'] = df['ytd_target'] - df['ytd_cumulative']

#         # Remaining target for the year
#         df['adjusted_annual_targets'] = (
#             df['annual_targets'] - df['ytd_cumulative']
#         )

#         df['adjusted_monthly_targets'] = (
#             df['adjusted_annual_targets'] / remaining_months
#         )

#     return df


# ## sheet formats


# In[ ]:













# In[95]:


file_name = f'Bancassurance report - {report_date}.xlsx'


weekly_banca_report_writer = pd.ExcelWriter(file_name, engine = 'xlsxwriter')
workbook = weekly_banca_report_writer.book


menu_sheet_name ='MENU'
dashboard_sheet_name = 'Dashboard'
subsidiaries_sheet_name ='Subsidiaries_View'
roles_summary_sheet_name = 'Roles_summary'
vic_summary_sheet_name = 'VIC_products_summary'
products_view_sheet_name = 'Products_View'
branches_sheet_name = 'Branch_Performance'
branches_life_sheet_name = 'Branch_Life_Premiums'
branches_non_life_sheet_name = 'Branch_non_Life_Premiums'
branch_vic_sheet_name = 'Branch_VIC_Premiums'
branch_total_vic_premium_table = 'Branch_total_vic_premiums'
rm_sheet_name = 'RMs_and_BBCs_Life'
rm_vic_sheet_name = 'RMs_and_BBCs_VIC'
dsr_sheet_name = 'PB_and_Banca_Dsrs_Life'
dsr_vic_sheet_name = 'PB_and_Banca_Dsrs_VIC'
# segments_sheet_name ='Segments_summary'
banca_data_sheet_name = 'Bancassurance_data'
analysis_sheet_name ='Analysis'
weekly_productivity_sheet_name ='Weekly_Productivity'
vic_weekly_productivity_sheet_name ='VIC_Weekly_Productivity'
segment_life_sheet_name='Segments_summary'
segment_vic_sheet_name ='VIC_Segment_summary'
rm_paid_premiums_sheet_name = 'RMs_and_BBCs_paid_premiums'
dsr_all_premiums_sheet_name ='PB_and_Banca_Dsrs_all_premiums'


# In[96]:


directors_file_name = f'VIC Summary report - {report_date}.xlsx'

directors_weekly_banca_report_writer = pd.ExcelWriter(directors_file_name, engine = 'xlsxwriter')
directors_workbook = directors_weekly_banca_report_writer.book


directors_banca_data_sheet_name = 'Bancassurance_data'
directors_segment_vic_sheet_name ='VIC_Segment_summary'


# In[97]:


#1996A9 - teal


roles_sheet_tab_color = '#084B65' # royal blue
data_points_sheet_tab_color = '#084B65' #chocolate web

sheet_tab_colour = '#084B65' #royal blue colour
font_size_format = workbook.add_format({'font_size':12})
column_header_format= workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})        #FFFFFF is white
sub_header_format= workbook.add_format({'font_size':12,'bold': True,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})  #C69500 is yellow, #1B4872 is blue
number_format = workbook.add_format({'font_size':12,'num_format':'_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-', 'align': 'right','valign': 'vcenter' }) #align number to the right & center it
percent_format = workbook.add_format({'bold':True,'num_format':'0.0%','align': 'right','valign': 'vcenter'})
million_format = workbook.add_format({'bold':True,'num_format':'#,##0.00,,"M"','align': 'right','valign': 'vcenter'})
bold_format = workbook.add_format({'bold': True})
background_format = workbook.add_format({'bold': True,'bg_color':'#084B65', 'font_color': '#000000'})
grey_format = workbook.add_format({'bold':True,'bg_color':'#F2F2F2'})
border_format = workbook.add_format({'border': 1})
blue_format = workbook.add_format({'text_wrap':True,'bold': True,'font_size':20,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})
total_format = workbook.add_format({'bold':True,'font_color':'#FFFFFF','bg_color':'#084B65'})
fill_format = workbook.add_format({'bg_color':'#1996A9','align': 'right','num_format':'_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-'})
maya_blue_format= workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})
column_name_format=workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})
lavender_format = workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#000000','bg_color':'#1996A9'})
antique_white= workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#000000','bg_color':'#F2F2F2'})
date_format= workbook.add_format({'num_format':'dd/mm/yyyy'})

deficit_header_format= workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#1996A9'})        #FFFFFF is white

red_format = workbook.add_format({'bold': True,'bg_color':'#C0504D', 'font_color': '#000000','num_format':'0%'})
amber_format = workbook.add_format({'bold': True,'bg_color':'#C69500', 'font_color': '#000000','num_format':'0%'})
green_format = workbook.add_format({'bold': True,'bg_color':'#70AD47', 'font_color': '#000000','num_format':'0%'})
ytd_grey_format = workbook.add_format({'bold': True, 'bg_color': '#1996A9', 'font_color': '#000000', 'num_format': '0%'})


# In[98]:


font_size_format2 = directors_workbook.add_format({'font_size':12})
column_header_format2= directors_workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})        #FFFFFF is white
sub_header_format2= directors_workbook.add_format({'font_size':12,'bold': True,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})  #C69500 is yellow, #1B4872 is blue
number_format2 = directors_workbook.add_format({'font_size':12,'num_format':'_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-', 'align': 'right','valign': 'vcenter' }) #align number to the right & center it
percent_format2 = directors_workbook.add_format({'bold':True,'num_format':'0.0%','align': 'right','valign': 'vcenter'})
million_format2 = directors_workbook.add_format({'bold':True,'num_format':'#,##0.00,,"M"','align': 'right','valign': 'vcenter'})
bold_format2 = directors_workbook.add_format({'bold': True})
background_format2 = directors_workbook.add_format({'bold': True,'bg_color':'#084B65', 'font_color': '#000000'})
grey_format2 = directors_workbook.add_format({'bold':True,'bg_color':'#F2F2F2'})
border_format2 = directors_workbook.add_format({'border': 1})
blue_format2 = directors_workbook.add_format({'text_wrap':True,'bold': True,'font_size':20,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})
total_format2 = directors_workbook.add_format({'bold':True,'font_color':'#FFFFFF','bg_color':'#084B65'})
fill_format2 = directors_workbook.add_format({'bg_color':'#1996A9','align': 'right','num_format':'_-* #,##0_-;-* #,##0_-;_-* "-"??_-;_-@_-'})
maya_blue_format2= directors_workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})
column_name_format2=directors_workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#084B65'})
lavender_format2 = directors_workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#000000','bg_color':'#1996A9'})
antique_white2= directors_workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#000000','bg_color':'#F2F2F2'})
date_format2= directors_workbook.add_format({'num_format':'dd/mm/yyyy'})

deficit_header_format2= directors_workbook.add_format({'bold': True,'font_size':12,'align': 'center','valign':'bottom','font_color':'#FFFFFF','bg_color':'#1996A9'})        #FFFFFF is white

red_format2 = directors_workbook.add_format({'bold': True,'bg_color':'#C0504D', 'font_color': '#000000','num_format':'0%'})
amber_format2= directors_workbook.add_format({'bold': True,'bg_color':'#C69500', 'font_color': '#000000','num_format':'0%'})
green_format2 = directors_workbook.add_format({'bold': True,'bg_color':'#70AD47', 'font_color': '#000000','num_format':'0%'})
ytd_grey_format2 = directors_workbook.add_format({'bold': True, 'bg_color': '#1996A9', 'font_color': '#000000', 'num_format': '0%'})


# ## Branch & Zone tables


# In[99]:


sales_report = sales_report.rename(columns={'paid_premiums':'paid_premiums_prev'})


# In[100]:


sales_report["starting_date"] = pd.to_datetime(sales_report["starting_date"])
accrue_names = ['BRITAM HOLDINGS PLC']
def accrue_value(row):
    if row["insured"] not in accrue_names:
        return row["paid_premiums_prev"]  

    start_month = row["starting_date"].month
    current_month = mtd_date.month

    if current_month < start_month:
        return 0  # not started yet
        
    total_months = 12 - start_month + 1
    monthly_value = row["paid_premiums_prev"] / total_months

    # full months accrued
    months_elapsed = current_month - start_month

    # total accrued including MTD for current month
    accrued = months_elapsed * monthly_value
    accrued += monthly_value * mtd_fraction

    return accrued

sales_report["paid_premiums_accrued"] = sales_report.apply(accrue_value, axis=1)
sales_report = sales_report.rename(columns={'paid_premiums_accrued':'paid_premiums'})
print(sales_report)


# In[101]:
premiums_for_entities_excluded= ['Britam Holdings Plc','Hf Bancassurance Intermediary Ltd','Hf Bancassurance Intermediary Limited']
filtered_sales_report = sales_report[~sales_report['insured'].isin(premiums_for_entities_excluded)]

motor_premiums_data = filtered_sales_report[(filtered_sales_report['premium_type']=='motor')]
motor_premiums_data.shape


# In[102]:


non_motor_premiums_data = filtered_sales_report[(filtered_sales_report['premium_type']=='non-motor')]
non_motor_premiums_data.shape


# In[103]:


life_premiums_data = filtered_sales_report[(filtered_sales_report['life_policy_check']=='life')]
life_premiums_data.shape


# In[104]:


non_life_premiums_data = filtered_sales_report[(filtered_sales_report['life_policy_check']=='non-life')]
non_life_premiums_data.shape


# In[105]:


vic_premiums_data = filtered_sales_report[(filtered_sales_report['vic_check']=='vic')]
vic_premiums_data.shape


# In[106]:


non_vic_premiums_data = filtered_sales_report[(filtered_sales_report['vic_check']=='non-vic')]
non_vic_premiums_data.shape


# In[107]:


vic_life_premiums_data = filtered_sales_report[(filtered_sales_report['vic_check']=='vic')& (filtered_sales_report['life_policy_check']=='life')]
vic_life_premiums_data.shape


# In[108]:


vic_non_life_premiums_data = filtered_sales_report[(filtered_sales_report['vic_check']=='vic')& (filtered_sales_report['life_policy_check']=='non-life')]
vic_non_life_premiums_data.shape


# ### branch tables


# In[109]:


def branch_vic_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

branch_vic_premium_table = branch_vic_premium(vic_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_vic_premium_table.tail(2)


# In[110]:


def branch_vic_life_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

branch_vic_life_premium_table = branch_vic_life_premium(vic_life_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_vic_life_premium_table.tail(2)


# In[111]:


# Apply the function to each row
monthly_target_column =['target_banca_value','target_banca_life','target_banca_non_life']

annual_targets_df =(
    filtered_branch_mapping
    .groupby('staff_branch')
    .apply(calculate_targets_with_ytd_fraction,monthly_target_columns=monthly_target_column, mtd_date=mtd_date,mtd_fraction= mtd_fraction)
    .reset_index()
                   )

filtered_branch_mapping = pd.merge(
    filtered_branch_mapping,
    annual_targets_df,
    on='staff_branch',
    how='left'
)

filtered_branch_mapping


# In[112]:


filtered_branch_mapping_columns_to_keep=['staff_branch', 'brn_code',
       'staff_zone','target_banca_life_calc','target_banca_non_life_calc','annual_target_banca_life_calc',
                                       'annual_target_banca_non_life_calc','ytd_target_banca_life_calc',
                                       'ytd_target_banca_non_life_calc','target_banca_value_calc','annual_target_banca_value_calc','ytd_target_banca_value_calc']

filtered_branch_mapping = filtered_branch_mapping[filtered_branch_mapping_columns_to_keep]
filtered_branch_mapping = filtered_branch_mapping.rename(columns={'target_banca_life_calc':'target_banca_life','annual_target_banca_life_calc':'annual_target_banca_life',
                                                              'target_banca_non_life_calc':'target_banca_non_life','annual_target_banca_non_life_calc':'annual_target_banca_non_life',
                                                              'annual_target_banca_value_calc':'annual_target_banca_value','target_banca_value_calc':'target_banca_value'})
filtered_branch_mapping.head(2)


# In[113]:


branch_vic_premium_table = pd.merge(filtered_branch_mapping,branch_vic_premium_table,left_on='staff_branch', right_on='branch_name', how='left').reset_index(drop=True).fillna(0)
month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_vic_premium_table.columns]

# branch_vic_premium_table.drop(columns={'brn_code','branch_name','target_banca_value','target_banca_life','target_banca_non_life'}, inplace=True)
# branch_vic_premium_table =branch_vic_premium_table.rename(columns={'staff_branch':'branch_name','Total':'ytd_cumulative'}).fillna(0)
branch_vic_premium_table.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_value':'annual_targets','Total':'ytd_cumulative',
                                          'ytd_target_banca_value_calc':'ytd_target','target_banca_value':'monthly_targets'}, inplace= True)

branch_vic_premium_table.tail(2)


# In[114]:


branch_vic_life_premium_table = pd.merge(filtered_branch_mapping,branch_vic_life_premium_table,left_on='staff_branch', right_on='branch_name', how='left').reset_index(drop=True).fillna(0)
month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_vic_life_premium_table.columns]
branch_vic_life_premium_table.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_life':'annual_targets','Total':'ytd_cumulative',
                                          'ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'}, inplace= True)

branch_vic_life_premium_table.tail(2)


# In[115]:


segment_targets['SEGMENT']


# In[116]:


value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES',
                   'BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY','PROPERTY - BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']

branch_vic_premium_table = branch_vic_premium_table[~branch_vic_premium_table['branch_name'].isin(value_to_remove)]
branch_vic_life_premium_table = branch_vic_life_premium_table[~branch_vic_life_premium_table['branch_name'].isin(value_to_remove)]


# In[117]:


branch_vic_premium_table=calculation_branch_formulas_no_capping(branch_vic_premium_table)
branch_vic_premium_table=uncapped_total_row(branch_vic_premium_table)
branch_vic_premium_table= rank_performance(branch_vic_premium_table,sort_column ='ytd_score')

month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_vic_premium_table.columns]

column_order = ['rank','branch','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_vic_premium_table= branch_vic_premium_table[column_order]
branch_vic_premium_table.columns



# get deficit from targets
branch_table_vic_premiums=branch_vic_premium_table.copy()
branch_vic_deficit_table = calculate_deficits(branch_table_vic_premiums,report_month)
branch_vic_deficit_table = pd.merge(branch_vic_deficit_table, branch_vic_premium_table[['rank','branch']],on = 'branch', how = 'left')
branch_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
branch_vic_deficit_table = branch_vic_deficit_table[branch_columns_to_keep]
branch_vic_deficit_table


# In[118]:


branch_vic_life_premium_table=calculation_branch_formulas_no_capping(branch_vic_life_premium_table)
branch_vic_life_premium_table=uncapped_total_row(branch_vic_life_premium_table)
branch_vic_life_premium_table= rank_performance(branch_vic_life_premium_table,sort_column ='ytd_score')

month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_vic_life_premium_table.columns]

column_order = ['rank','branch','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_vic_life_premium_table= branch_vic_life_premium_table[column_order]
branch_vic_life_premium_table.columns



# get deficit from targets
branch_table_vic_life_premiums=branch_vic_life_premium_table.copy()
branch_vic_life_deficit_table = calculate_deficits(branch_table_vic_life_premiums,report_month)
branch_vic_life_deficit_table = pd.merge(branch_vic_life_deficit_table, branch_vic_life_premium_table[['rank','branch']],on = 'branch', how = 'left')
branch_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
branch_vic_life_deficit_table = branch_vic_life_deficit_table[branch_columns_to_keep]
branch_vic_life_deficit_table.head(2)


# In[119]:


def branch_non_vic_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

branch_non_vic_premium_table_with_branch_names = branch_non_vic_premium(non_vic_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_non_vic_premium_table_with_branch_names.tail(2)


# In[120]:


def branch_vic_non_life_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

branch_vic_non_life_premium_table_with_branch_names = branch_vic_non_life_premium(vic_non_life_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_vic_non_life_premium_table_with_branch_names.tail(2)


# In[121]:


value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']

branch_non_vic_premium_table_with_branch_names = branch_non_vic_premium_table_with_branch_names[~branch_non_vic_premium_table_with_branch_names['branch_name'].isin(value_to_remove)]


# In[122]:


branch_vic_non_life_premium_table_with_branch_names = branch_vic_non_life_premium_table_with_branch_names[~branch_vic_non_life_premium_table_with_branch_names['branch_name'].isin(value_to_remove)]


# In[123]:


branch_non_vic_premium_table_with_branch_names = pd.merge(filtered_branch_mapping,branch_non_vic_premium_table_with_branch_names,left_on='staff_branch', right_on='branch_name', how='left').reset_index(drop=True).fillna(0)
month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_non_vic_premium_table_with_branch_names.columns]

branch_non_vic_premium_table_with_branch_names.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_non_life':'annual_targets',
                                                                'Total':'ytd_cumulative','ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'}, inplace= True)

branch_non_vic_premium_table_with_branch_names.tail(2)


# In[124]:


branch_vic_non_life_premium_table_with_branch_names = pd.merge(filtered_branch_mapping,branch_vic_non_life_premium_table_with_branch_names,left_on='staff_branch', right_on='branch_name', how='left').reset_index(drop=True).fillna(0)
month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_vic_non_life_premium_table_with_branch_names.columns]

branch_vic_non_life_premium_table_with_branch_names.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_non_life':'annual_targets',
                                                                'Total':'ytd_cumulative','ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'}, inplace= True)

branch_vic_non_life_premium_table_with_branch_names.tail(2)


# In[125]:


branch_non_vic_premium_table_with_branch_names=calculation_branch_formulas(branch_non_vic_premium_table_with_branch_names)
branch_non_vic_premium_table_with_branch_names=total_row(branch_non_vic_premium_table_with_branch_names)
# branch_non_vic_premium_table= rank_performance(branch_non_vic_premium_table,sort_column ='ytd_score')

month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_non_vic_premium_table_with_branch_names.columns]

column_order = ['branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_non_vic_premium_table= branch_non_vic_premium_table_with_branch_names[column_order]
branch_non_vic_premium_table.columns


# In[126]:


branch_vic_non_life_premium_table_with_branch_names=calculation_branch_formulas_no_capping(branch_vic_non_life_premium_table_with_branch_names)
branch_vic_non_life_premium_table_with_branch_names=uncapped_total_row(branch_vic_non_life_premium_table_with_branch_names)
# branch_non_vic_premium_table= rank_performance(branch_non_vic_premium_table,sort_column ='ytd_score')

month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_vic_non_life_premium_table_with_branch_names.columns]

column_order = ['branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_vic_non_life_premium_table= branch_vic_non_life_premium_table_with_branch_names[column_order]
branch_vic_non_life_premium_table.columns


# In[127]:


branch_non_vic_premium_table = pd.merge(branch_non_vic_premium_table, branch_vic_premium_table[['branch']], on = 'branch', how = 'right')
branch_non_vic_premium_table = branch_non_vic_premium_table.drop(columns={'branch'})
branch_non_vic_premium_table = branch_non_vic_premium_table.rename(columns={'Total':'ytd_cumulative'}).fillna(0)


# In[128]:


branch_vic_non_life_premium_table = pd.merge(branch_vic_non_life_premium_table, branch_vic_life_premium_table[['rank','branch']], on = 'branch', how = 'right')
branch_vic_non_life_premium_table = branch_vic_non_life_premium_table.sort_values(by ='rank')
branch_vic_non_life_premium_table = branch_vic_non_life_premium_table.drop(columns={'rank','branch'})
branch_vic_non_life_premium_table = branch_vic_non_life_premium_table.rename(columns={'Total':'ytd_cumulative'}).fillna(0)

branch_vic_non_life_premium_table.head(2)


# In[129]:


# get deficit from targets
# branch_table_vic_premiums=branch_vic_premium_table.copy()
# branch_vic_deficit_table = calculate_deficits(branch_table_vic_premiums,report_month)
# branch_vic_deficit_table = pd.merge(branch_vic_deficit_table, branch_vic_premium_table[['rank','branch']],on = 'branch', how = 'left')
# branch_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
# branch_vic_deficit_table = branch_vic_deficit_table[branch_columns_to_keep]
# branch_vic_deficit_table


# In[130]:


# branch_vic_total_row = branch_vic_premium_table.sum(numeric_only =True)
# branch_vic_total_row = pd.DataFrame(branch_vic_total_row).T
# branch_vic_premium_table = pd.concat([branch_vic_premium_table,branch_vic_total_row], ignore_index=True)
# branch_vic_premium_table.tail()


# In[131]:


branch_vic_premium_table['branch']= branch_vic_premium_table['branch'].fillna(0).str.replace(' BRANCH','')  
branch_vic_life_premium_table['branch']= branch_vic_life_premium_table['branch'].fillna(0).str.replace(' BRANCH','')  


# In[132]:


def branch_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0).reset_index()
  
  premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
                                    
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

branch_monthly_premium_table = branch_premium(filtered_sales_report, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_monthly_premium_table.head(1)


# In[133]:


branch_premium_table = pd.merge(filtered_branch_mapping,branch_monthly_premium_table,left_on='staff_branch', right_on='branch_name', how='left')
branch_premium_table.drop(columns={'brn_code','branch_name'}, inplace=True)
branch_premium_table.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_value':'annual_targets','Total':'ytd_cumulative',
                                     'ytd_target_banca_value_calc':'ytd_target','target_banca_value':'monthly_targets'}, inplace= True)
branch_premium_table= branch_premium_table.fillna(0)
branch_premium_table.tail(2)


# In[134]:


branch_premium_table=calculation_branch_formulas(branch_premium_table)
branch_premium_table=total_row(branch_premium_table)
branch_premium_table= rank_performance(branch_premium_table,sort_column ='ytd_score')

month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_premium_table.columns]

column_order = ['rank','branch','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_premium_table= branch_premium_table[column_order]
branch_premium_table.columns


# In[135]:


# get deficit from targets
branch_table_premiums=branch_premium_table.copy()
branch_deficit_table = calculate_deficits(branch_table_premiums,report_month)
branch_deficit_table = pd.merge(branch_deficit_table, branch_premium_table[['rank','branch']],on = 'branch', how = 'left')
branch_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
branch_deficit_table = branch_deficit_table[branch_columns_to_keep]


# In[136]:


def branch_commission(dataframe, index, month_column_name, value_column_name):
  comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  comm_amt = comm_amt.fillna(0).reset_index()

  comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
  comm_present_columns = [col for col in comm_month_order if col in comm_amt.columns]

  for month in comm_month_order:
      if  month not in comm_amt.columns:
          comm_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
                                            
  comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']] 
  comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)
    
  return comm_amt

branch_commission_table = branch_commission(filtered_sales_report, month_column_name='month_name', index = 'branch_name',value_column_name = 'commission')

branch_commission_table.rename(columns ={'Total':'ytd_cumulative'}, inplace= True)

branch_commission_table.head(1)


# In[137]:


branch_commission_table['branch_name']


# In[138]:


# remove HFBI since it isn't a branch
value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']

branch_commission_table = branch_commission_table[~branch_commission_table['branch_name'].isin(value_to_remove)]
branch_commission_table


# In[139]:


branch_commission_table = pd.merge(filtered_branch_mapping,branch_commission_table,left_on='staff_branch', right_on='branch_name', how='left')
branch_commission_table.drop(columns={'brn_code','branch_name','target_banca_life','target_banca_value',
                                      'target_banca_non_life','staff_zone','annual_target_banca_life', 'annual_target_banca_non_life',
       'ytd_target_banca_life_calc', 'ytd_target_banca_non_life_calc',
       'annual_target_banca_value', 'ytd_target_banca_value_calc'}, inplace=True)
branch_commission_table.rename(columns ={'staff_branch':'branch'}, inplace= True)
branch_commission_table= branch_commission_table.fillna(0)
branch_commission_table.tail(2)


# In[140]:


branch_commission_table = pd.merge(branch_commission_table, branch_premium_table[['rank','branch']], on = 'branch', how = 'left')
branch_commission_table = branch_commission_table.sort_values(by = 'rank')
branch_commission_table = branch_commission_table.fillna(0)
branch_commission_table.head(2)


# In[141]:


# it has zero values
# branch_commission_table = branch_commission_table.drop(branch_commission_table.index[-1])
branch_commission_table.drop(columns={'branch','rank'}, inplace =True)

# add totals
sum_row= branch_commission_table.iloc[:,:].sum()
sum_row= pd.DataFrame(sum_row).T

branch_commission_table=pd.concat([branch_commission_table,sum_row], ignore_index=True)
# branch_commission_table

#removing the word branch to make it cleaner
branch_premium_table['branch']= branch_premium_table['branch'].fillna(0).str.replace(' BRANCH','')        
branch_premium_table['rank'] = branch_premium_table['rank'].fillna(0).astype(int)
branch_premium_table['branch'] = branch_premium_table['branch'].fillna('')
branch_premium_table.head(2)


# ## all life & non-life tables


# In[142]:


def branch_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

branch_life_premium_table = branch_life_premium(life_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_life_premium_table.head(1)


# In[143]:


branch_life_premium_table = pd.merge(filtered_branch_mapping,branch_life_premium_table,left_on='staff_branch', right_on='branch_name', how='left')
branch_life_premium_table.drop(columns={'brn_code','branch_name','target_banca_non_life','target_banca_value'}, inplace=True)
branch_life_premium_table.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_life':'annual_targets','Total':'ytd_cumulative',
                                          'ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'}, inplace= True)
branch_life_premium_table= branch_life_premium_table.fillna(0)
branch_life_premium_table.tail(2)


# In[144]:


branch_life_premium_table


# In[145]:


value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']
branch_life_premium_table = branch_life_premium_table[~branch_life_premium_table['branch'].isin(value_to_remove)]


# In[146]:


# branch_life_premium_table = pd.merge(filtered_branch_mapping,branch_life_premium_table,left_on='staff_branch', right_on='branch_name', how='left')
# month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
# present_columns = [col for col in month_order if col in branch_life_premium_table.columns]

# branch_life_premium_table.drop(columns={'brn_code','branch_name','target_banca_value','target_banca_non_life'}, inplace=True)
# branch_life_premium_table =branch_life_premium_table.rename(columns={'staff_branch':'branch_name','Total':'ytd_cumulative'}).fillna(0)

# branch_life_premium_table


# In[147]:


branch_life_premium_table=calculation_branch_formulas(branch_life_premium_table)
branch_life_premium_table=total_row(branch_life_premium_table)
branch_life_premium_table= rank_performance(branch_life_premium_table,sort_column ='ytd_score')


# In[148]:


month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_life_premium_table.columns]

column_order = ['rank','branch','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_life_premium_table= branch_life_premium_table[column_order]
branch_life_premium_table.columns


# In[149]:


value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']
branch_life_premium_table = branch_life_premium_table[~branch_life_premium_table['branch'].isin(value_to_remove)].reset_index(drop=True)
branch_life_premium_table


# In[150]:


# get deficit from targets
branch_table_life_premiums=branch_life_premium_table.copy()
branch_deficit_life_table = calculate_deficits(branch_table_life_premiums,report_month)
branch_deficit_life_table = pd.merge(branch_deficit_life_table, branch_life_premium_table[['rank','branch']],on = 'branch', how = 'left')
branch_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
branch_deficit_life_table = branch_deficit_life_table[branch_columns_to_keep]
branch_deficit_life_table.head(2)


# In[151]:


def branch_life_commission(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order


    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]

 
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    comm_amt = comm_amt.fillna(0).reset_index()
          
  
    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return comm_amt

branch_life_commission_table = branch_life_commission(life_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'commission')

branch_life_commission_table.head()


# In[152]:


# remove HFBI since it isn't a branch
value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']
branch_life_commission_table = branch_life_commission_table[~branch_life_commission_table['branch_name'].isin(value_to_remove)].reset_index(drop=True)
branch_life_commission_table


# In[153]:


# branch_life_commission_table = pd.merge(filtered_branch_mapping,branch_life_commission_table,left_on='staff_branch', right_on='branch_name', how='outer')
# branch_life_commission_table = branch_life_commission_table.drop(columns={'brn_code','branch_name','target_banca_life','target_banca_value','target_banca_non_life','staff_zone'}, inplace=True)
# branch_life_commission_table = branch_life_commission_table.rename(columns ={'staff_branch':'branch'}, inplace= True)
# branch_life_commission_table= branch_life_commission_table.fillna(0)
# branch_life_commission_table


# In[154]:


branch_life_commission_table = pd.merge(branch_life_commission_table, branch_life_premium_table[['rank','branch']], left_on = 'branch_name', right_on = 'branch', how = 'right')
branch_life_commission_table = branch_life_commission_table.sort_values(by = 'rank')
branch_life_commission_table = branch_life_commission_table.fillna(0)
branch_life_commission_table


# In[155]:


value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']
branch_life_commission_table = branch_life_commission_table[~branch_life_commission_table['branch_name'].isin(value_to_remove)]


# In[156]:


# it has zero values
# branch_life_commission_table = branch_life_commission_table.drop(branch_life_commission_table.index[-1])
branch_life_commission_table.drop(columns={'branch_name','branch','rank'}, inplace =True)

# add totals
sum_row= branch_life_commission_table.iloc[:,:].sum()
sum_row= pd.DataFrame(sum_row).T

branch_life_commission_table=pd.concat([branch_life_commission_table,sum_row], ignore_index=True)
# branch_life_commission_table

#removing the word branch to make it cleaner
branch_life_premium_table['branch']= branch_life_premium_table['branch'].fillna(0).str.replace(' BRANCH','')        
branch_life_premium_table['rank'] = branch_life_premium_table['rank'].fillna(0).astype(int)
branch_life_premium_table['branch'] = branch_life_premium_table['branch'].fillna('')
branch_life_premium_table.head(2)


# In[157]:


def branch_non_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]


    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

branch_non_life_premium_table = branch_non_life_premium(non_life_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'paid_premiums')

branch_non_life_premium_table.head(2)


# In[158]:


branch_non_life_premium_table = pd.merge(filtered_branch_mapping,branch_non_life_premium_table,left_on='staff_branch', right_on='branch_name', how='left')
branch_non_life_premium_table.drop(columns={'brn_code','branch_name','target_banca_value'}, inplace=True)
branch_non_life_premium_table.rename(columns ={'staff_branch':'branch','staff_zone':'zone','annual_target_banca_non_life':'annual_targets','Total':'ytd_cumulative',
                                              'ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'}, inplace= True)
branch_non_life_premium_table= branch_non_life_premium_table.fillna(0)
branch_non_life_premium_table.tail(2)


# In[159]:


branch_non_life_premium_table=calculation_branch_formulas(branch_non_life_premium_table)
branch_non_life_premium_table=total_row(branch_non_life_premium_table)
branch_non_life_premium_table= rank_performance(branch_non_life_premium_table,sort_column ='ytd_score')


# In[160]:


month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_columns = [col for col in month_order if col in branch_non_life_premium_table.columns]

column_order = ['rank','branch','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

branch_non_life_premium_table= branch_non_life_premium_table[column_order]
branch_non_life_premium_table.columns


# In[161]:


# get deficit from targets
branch_table_non_life_premiums=branch_non_life_premium_table.copy()
branch_deficit_non_life_table = calculate_deficits(branch_table_non_life_premiums,report_month)
branch_deficit_non_life_table = pd.merge(branch_deficit_non_life_table, branch_non_life_premium_table[['rank','branch']],on = 'branch', how = 'left')
branch_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
branch_deficit_non_life_table = branch_deficit_non_life_table[branch_columns_to_keep]
# branch_deficit_non_life_table


# In[162]:


def branch_non_life_commission(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order


    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]


    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    comm_amt = comm_amt.fillna(0).reset_index()
          
  
    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return comm_amt

branch_non_life_commission_table = branch_non_life_commission(non_life_premiums_data, month_column_name='month_name', index = 'branch_name',value_column_name = 'commission')

branch_non_life_commission_table.head(2)


# In[163]:


# remove HFBI since it isn't a branch
value_to_remove = [0,'MORTGAGE BUSINESS','HFCB-BI','COMMERCIAL BANKING','DIASPORA BANKING','PROPERTY','Total','BI SALES','BI INSTALLED','PROPERTY - SALES','PROPERTY - DIGITAL PROPERTY',' HFDI BUSINESS DEVELOPMENT','PROPERTY - PROJECT MANAGEMENT']

branch_non_life_commission_table = branch_non_life_commission_table[~branch_non_life_commission_table['branch_name'].isin(value_to_remove)]
branch_non_life_commission_table = pd.merge(branch_non_life_commission_table, branch_non_life_premium_table[['rank','branch']], left_on = 'branch_name', right_on = 'branch', how = 'left')
branch_non_life_commission_table = branch_non_life_commission_table.sort_values(by = 'rank')
branch_non_life_commission_table = branch_non_life_commission_table.fillna(0)
branch_non_life_commission_table.head(2)


# In[164]:


# it has zero values
# branch_non_life_commission_table = branch_non_life_commission_table.drop(branch_non_life_commission_table.index[-1])
branch_non_life_commission_table.drop(columns={'branch_name','branch','rank'}, inplace =True)

# add totals
sum_row= branch_non_life_commission_table.iloc[:,:].sum()
sum_row= pd.DataFrame(sum_row).T

branch_non_life_commission_table=pd.concat([branch_non_life_commission_table,sum_row], ignore_index=True)

#removing the word branch to make it cleaner
branch_non_life_premium_table['branch']= branch_non_life_premium_table['branch'].fillna(0).str.replace(' BRANCH','')        
branch_non_life_premium_table['rank'] = branch_non_life_premium_table['rank'].fillna(0).astype(int)
branch_non_life_premium_table['branch'] = branch_non_life_premium_table['branch'].fillna('')
branch_non_life_commission_table.tail(2)


# 
# 
# ## Zone performance tables
# 
# #### all premiums(paid)


# In[165]:


def zone_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns= month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0).reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]  
    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)

  return premium_amt

zone_premium_table = zone_premium(filtered_sales_report, month_column_name='month_name', index = 'zone',value_column_name = 'paid_premiums')

zone_premium_table


# In[166]:


# interested in zones only
value_to_drop = [0,'Total','Other_business']

zone_premium_table = zone_premium_table[~zone_premium_table['zone'].isin(value_to_drop)]
zone_premium_targets = filtered_branch_mapping.groupby('staff_zone')[['target_banca_life',
       'target_banca_non_life', 'annual_target_banca_life',
       'annual_target_banca_non_life', 'ytd_target_banca_life_calc',
       'ytd_target_banca_non_life_calc', 'target_banca_value',
       'annual_target_banca_value', 'ytd_target_banca_value_calc']].sum().reset_index()
zone_premium_targets


# In[167]:


zone_premium_table= pd.merge(zone_premium_targets,zone_premium_table, left_on ='staff_zone', right_on='zone', how='left')
zone_premium_table.drop(columns= {'zone'}, inplace=True)
zone_premium_table.rename(columns={'staff_zone':'zone','annual_target_banca_value':'annual_targets','Total':'ytd_cumulative',
                                  'target_banca_value':'monthly_targets','ytd_target_banca_value_calc':'ytd_target'}, inplace =True)
zone_premium_table=calculation_branch_formulas(zone_premium_table)
zone_premium_table=total_row(zone_premium_table)
zone_premium_table= rank_performance(zone_premium_table,'ytd_score')
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
present_columns = [col for col in month_order if col in zone_premium_table.columns]

column_order = ['rank','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

zone_premium_table= zone_premium_table[column_order]


# In[168]:


# get deficit targets and actuals
zone_table_premiums=zone_premium_table.copy()
zone_deficit_table = calculate_deficits(zone_table_premiums,report_month)
# zone_deficit_table.columns
zone_deficit_table = pd.merge(zone_deficit_table, zone_premium_table[['rank','zone']], on = 'zone', how = 'left')
zone_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
zone_deficit_table = zone_deficit_table[zone_columns_to_keep]
zone_deficit_table


# In[169]:


def zone_comm(dataframe, index, month_column_name, value_column_name):
  comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  comm_amt = comm_amt.fillna(0).reset_index()

  comm_month_order =[f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
  comm_present_columns = [col for col in comm_month_order if col in comm_amt.columns]

  for month in comm_month_order:
      if  month not in comm_amt.columns:
          comm_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
                                         
  comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']] 
  comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)
    
  return comm_amt

zone_comm_table = zone_comm(filtered_sales_report, month_column_name='month_name', index = 'zone',value_column_name = 'commission')
zone_comm_table


# In[170]:


value_to_drop = [0,'Total','Other_business']
zone_comm_table = zone_comm_table[~zone_comm_table['zone'].isin(value_to_drop)]
zone_comm_table = zone_comm_table.rename(columns={'Total':'ytd_cumulative'})
zone_comm_table


# In[171]:


zone_comm_table = pd.merge(zone_comm_table, zone_premium_table[['rank','zone']], left_on = 'zone', right_on = 'zone', how = 'left')
zone_comm_table = zone_comm_table.sort_values(by='rank')
zone_comm_table.drop(columns={'rank','zone'}, inplace =True)
sum_row= zone_comm_table.iloc[:,:].sum()
sum_row= pd.DataFrame(sum_row).T

zone_comm_table=pd.concat([zone_comm_table,sum_row], ignore_index=True)
zone_comm_table


# #### life and non-life tables


# In[172]:


def zone_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]


    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

zone_life_premium_table = zone_life_premium(life_premiums_data, month_column_name='month_name', index = 'zone',value_column_name = 'paid_premiums')

zone_life_premium_table.head(1)


# In[173]:


zone_life_premium_targets = filtered_branch_mapping.groupby('staff_zone')[['target_banca_life','annual_target_banca_life', 'ytd_target_banca_life_calc']].sum().reset_index()
zone_life_premium_targets

# interested in zones only
value_to_drop = [0,'Total']

zone_life_premium_table = (zone_life_premium_table[~zone_life_premium_table['zone'].isin(value_to_drop)] if 'zone' in zone_life_premium_table.columns else pd.DataFrame(columns=zone_life_premium_table.columns))
zone_life_premium_table


# In[174]:


zone_life_premium_table= pd.merge(zone_life_premium_targets,zone_life_premium_table, left_on ='staff_zone', right_on='zone', how='left').fillna(0)
zone_life_premium_table.drop(columns= {'zone'}, inplace=True)
zone_life_premium_table.rename(columns={'staff_zone':'zone','annual_target_banca_life':'annual_targets','Total':'ytd_cumulative','ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'}, inplace =True)
zone_life_premium_table


# In[175]:


zone_life_premium_table=calculation_branch_formulas(zone_life_premium_table)
zone_life_premium_table=total_row(zone_life_premium_table)
zone_life_premium_table= rank_performance(zone_life_premium_table,'ytd_score')
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
present_columns = [col for col in month_order if col in zone_life_premium_table.columns]

column_order = ['rank','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

zone_life_premium_table= zone_life_premium_table[column_order]
zone_life_premium_table


# In[176]:


# get deficit targets and actuals
zone_table_life_premiums=zone_life_premium_table.copy()
zone_deficit_life_table = calculate_deficits(zone_table_life_premiums,report_month)
# zone_deficit_table.columns
zone_deficit_life_table = pd.merge(zone_deficit_life_table, zone_life_premium_table[['rank','zone']], on = 'zone', how = 'left')
zone_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
zone_deficit_life_table = zone_deficit_life_table[zone_columns_to_keep]
zone_deficit_life_table


# In[177]:


def zone_life_comm(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in comm_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]


    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    comm_amt = comm_amt.fillna(0).reset_index()
          
  
    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return comm_amt

zone_comm_life_table = zone_life_comm(life_premiums_data, month_column_name='month_name', index = 'zone',value_column_name = 'commission')
zone_comm_life_table



# In[178]:


value_to_drop = [0,'Total']
zone_comm_life_table = (zone_comm_life_table[~zone_comm_life_table['zone'].isin(value_to_drop)] if 'zone' in zone_comm_life_table.columns else pd.DataFrame(columns = zone_comm_life_table.columns))
zone_comm_life_table = zone_comm_life_table.rename(columns={'Total':'ytd_cumulative'})
zone_comm_life_table


# In[179]:


zone_comm_life_table = pd.merge(zone_comm_life_table, zone_life_premium_table[['rank','zone']], left_on = 'zone', right_on = 'zone', how = 'left')
zone_comm_life_table = zone_comm_life_table.sort_values(by='rank')
zone_comm_life_table.drop(columns={'rank','zone'}, inplace =True)
sum_row= zone_comm_life_table.iloc[:,:].sum()
sum_row= pd.DataFrame(sum_row).T

zone_comm_life_table=pd.concat([zone_comm_life_table,sum_row], ignore_index=True)
zone_comm_life_table


# In[180]:


def zone_non_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]


    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

zone_non_life_premium_table = zone_non_life_premium(non_life_premiums_data, month_column_name='month_name', index = 'zone',value_column_name = 'paid_premiums')

zone_non_life_premium_table.head(1)


# In[181]:


zone_non_life_premium_targets = filtered_branch_mapping.groupby('staff_zone')[['target_banca_non_life','annual_target_banca_non_life', 'ytd_target_banca_non_life_calc']].sum().reset_index()
zone_non_life_premium_targets


# In[182]:


# interested in zones only
value_to_drop = [0,'Total','Other_business']

zone_non_life_premium_table = (zone_non_life_premium_table[~zone_non_life_premium_table['zone'].isin(value_to_drop)] if 'zone' in zone_non_life_premium_table.columns else pd.DataFrame(columns=zone_non_life_premium_table.columns))
zone_non_life_premium_table


# In[183]:


zone_non_life_premium_table= pd.merge(zone_non_life_premium_targets,zone_non_life_premium_table, left_on ='staff_zone', right_on='zone', how='left').fillna(0)
zone_non_life_premium_table.drop(columns= {'zone'}, inplace=True)
zone_non_life_premium_table.rename(columns={'staff_zone':'zone','annual_target_banca_non_life':'annual_targets','Total':'ytd_cumulative',
                                           'ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'}, inplace =True)
zone_non_life_premium_table


# In[184]:


zone_non_life_premium_table=calculation_branch_formulas(zone_non_life_premium_table)
zone_non_life_premium_table=total_row(zone_non_life_premium_table)
zone_non_life_premium_table= rank_performance(zone_non_life_premium_table,'ytd_score')
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
present_columns = [col for col in month_order if col in zone_non_life_premium_table.columns]

column_order = ['rank','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

zone_non_life_premium_table= zone_non_life_premium_table[column_order]
zone_non_life_premium_table


# In[185]:


# get deficit targets and actuals
zone_table_non_life_premiums=zone_non_life_premium_table.copy()
zone_deficit_non_life_table = calculate_deficits(zone_table_non_life_premiums,report_month)
# zone_deficit_table.columns
zone_deficit_non_life_table = pd.merge(zone_deficit_non_life_table, zone_table_non_life_premiums[['rank','zone']], on = 'zone', how = 'left')
zone_columns_to_keep=['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
zone_deficit_non_life_table = zone_deficit_non_life_table[zone_columns_to_keep]
zone_deficit_non_life_table


# In[186]:


def zone_non_life_comm(dataframe, index, month_column_name, value_column_name):
    comm_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in comm_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]


    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    comm_amt = comm_amt.fillna(0).reset_index()
          
  
    for month in comm_month_order:
        if  month not in comm_amt.columns:
            comm_amt[month]=0
          
    comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)                          
    comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return comm_amt

zone_comm_non_life_table = zone_non_life_comm(non_life_premiums_data, month_column_name='month_name', index = 'zone',value_column_name = 'commission')
zone_comm_non_life_table



# In[187]:


value_to_drop = [0,'Total','Other_business']
zone_comm_non_life_table = (zone_comm_non_life_table[~zone_comm_non_life_table['zone'].isin(value_to_drop)] if 'zone' in zone_comm_non_life_table.columns else pd.DataFrame(columns = zone_comm_non_life_table.columns))
zone_comm_non_life_table = zone_comm_non_life_table.rename(columns={'Total':'ytd_cumulative'})
zone_comm_non_life_table


# In[188]:


zone_comm_non_life_table = pd.merge(zone_comm_non_life_table, zone_non_life_premium_table[['rank','zone']], left_on = 'zone', right_on = 'zone', how = 'left')
zone_comm_non_life_table = zone_comm_non_life_table.sort_values(by='rank')
zone_comm_non_life_table.drop(columns={'rank','zone'}, inplace =True)
sum_row= zone_comm_non_life_table.iloc[:,:].sum()
sum_row= pd.DataFrame(sum_row).T

zone_comm_non_life_table=pd.concat([zone_comm_non_life_table,sum_row], ignore_index=True)
zone_comm_non_life_table


# ## RMs & BBCs


# In[189]:


# p_conn = psql.connect(host=app.postgres['host'],database = app.postgres['db'], user=app.postgres['user'], password=app.postgres['password'])

# role_count_map_query = '''
# select * from branch_employee_dmc_data
                         
# '''
# # role_mapping = pd.read_sql_query(role_count_map_query , p_conn)

# sales_persons_targets_mapping_trial = pd.read_sql_query(role_count_map_query , p_conn)

# p_conn.close()


# ###  Role mapping


# In[190]:


columns_to_keep= ['active','sales_code','staff_name', 'staff_branch', 'staff_role','staff_zone','target_banca_value','target_banca_life','target_banca_non_life','target_banca_motor','target_banca_non_motor','start_date','exit_date']
filtered_role_mapping=sales_persons_targets_mapping_trial[columns_to_keep]
filtered_role_mapping = filtered_role_mapping.sort_values(by=['sales_code','active','start_date'], ascending=[True,False,False])

# # filtered_role_mapping.drop(columns={'active'},inplace=True)
filtered_role_mapping.fillna(0)
filtered_role_mapping.columns


# In[191]:


filtered_role_mapping[filtered_role_mapping['staff_name']=='Anne Mwaura']


# In[192]:


filtered_role_mapping['start_date'] = pd.to_datetime(filtered_role_mapping['start_date'])


# In[193]:


# # function without the increasing logic
# def calculate_annual_target(group, monthly_target_columns, mtd_date):
#     """
#     Calculates annual targets for staff, including those promoted within the year and if in the same segment.
#     Sums monthly targets for each role segment active in the reporting year.
    
#     """
#     annual_targets = {}
#     report_year = mtd_date.year
    
#     # Initialize all target columns to 0
#     for target_column in monthly_target_columns:
#         annual_targets[f'annual_{target_column}'] = 0
    
#     # Loop through each role entry for that staff (this handles multiple promotions in the report year)
#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = (
#             pd.to_datetime(row['exit_date'])
#             if pd.notnull(row['exit_date'])
#             else pd.Timestamp(year=report_year, month=12, day=31)
#         )
        
#         # Restrict interval to current reporting year
#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))
        
#         if role_start > role_end:
#             continue  # not active this year
        
#         # Count active months inclusive
#         months_active = (role_end.year - role_start.year) * 12 + (role_end.month - role_start.month) + 1
        
#         # Accumulate targets for each column across all roles
#         for target_column in monthly_target_columns:
#             monthly_target = row.get(target_column, 0) if pd.notnull(row.get(target_column)) else 0
#             annual_targets[f'annual_{target_column}'] += monthly_target * months_active
    
#     return pd.Series(annual_targets)


# In[194]:


# #### with increasing targets less ytd fraction

# MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
#           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# def calculate_annual_target(group, monthly_target_columns, mtd_date):
#     """
#     Calculates monthly ramped targets and sums them into annual targets
#     for staff (handles multiple roles/promotions within the year).
#     """

#     annual_targets = {}
#     report_year = mtd_date.year

#     # Initialize totals
#     for target_column in monthly_target_columns:
#         annual_targets[f'annual_{target_column}'] = 0

#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = (
#             pd.to_datetime(row['exit_date'])
#             if pd.notnull(row['exit_date'])
#             else pd.Timestamp(year=report_year, month=12, day=31)
#         )

#         # Clip role period to report year
#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))

#         if role_start > role_end:
#             continue

#         # Loop month by month instead of multiplying by months_active
#         current_month_index = 1  # ramp resets per role

#         current = role_start.to_period("M").to_timestamp()

#         while current <= role_end:
#             for target_column in monthly_target_columns:
#                 base_target = row.get(target_column, 0) or 0
#                 monthly_value = base_target * current_month_index
#                 annual_targets[f'annual_{target_column}'] += monthly_value

#             current_month_index += 1
#             current += pd.DateOffset(months=1)

#     return pd.Series(annual_targets)


# In[195]:


# ### with increasing targets as well as calculating ytd fraction

# def calculate_annual_target(group, monthly_target_columns, mtd_date):
#     """
#     Calculate ramped annual and YTD targets for staff.
    
#     Returns one row per staff with:
#     - annual_ and ytd columns
#     """
#     result = {}
#     report_year = mtd_date.year
#     mtd_month_num = mtd_date.month 

#     # totals
#     for col in monthly_target_columns:
#         result[f'annual_{col}'] = 0
#         result[f'ytd_{col}'] = 0

#     # Loop through each role/promotion for this staff
#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = pd.to_datetime(row['exit_date']) if pd.notnull(row.get('exit_date')) else pd.Timestamp(year=report_year, month=12, day=31)

#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))

#         if role_start > role_end:
#             continue  # not active this year

#         # Number of months in this role
#         months_active = (role_end.year - role_start.year) * 12 + (role_end.month - role_start.month) + 1

#         for col in monthly_target_columns:
#             base = row.get(col, 0) or 0

#             # Ramped monthly total= months_active * (months_active + 1)/2
#             ramped_total = base * months_active * (months_active + 1) / 2
#             result[f'annual_{col}'] += ramped_total

#             # YTD: only count months up to reporting month
#             months_ytd = min(months_active, mtd_month_num - role_start.month + 1)
#             if months_ytd > 0:
#                 ramped_ytd = base * months_ytd * (months_ytd + 1) / 2
#                 result[f'ytd_{col}'] += ramped_ytd

#     return pd.Series(result)


# In[196]:


# months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
#           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# months_to_number = {m: i for i, m in enumerate(months, 1)}


# def calculate_annual_target(group, monthly_target_columns, mtd_date):
#     """
#     Calculate ramped monthly targets, annual totals, and YTD totals for staff,
#     including those starting mid-year or leaving mid-year, and multiple metrics.

#     Parameters:
#     - group: DataFrame for one staff member (can be multiple rows if multiple roles)
#     - monthly_target_columns: list of base monthly target columns
#     - mtd_date: reporting date (used to calculate YTD totals)

#     Returns:
#     - pd.Series with monthly columns, annual totals, and YTD totals
#     """
#     result = {}

#     report_year = mtd_date.year
#     mtd_month_num = mtd_date.month  # for YTD calculation

#     # Initialize totals
#     for col in monthly_target_columns:
#         result[f'annual_{col}'] = 0
#         result[f'ytd_{col}'] = 0

#     # Loop through each role/promotion for this staff
#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = pd.to_datetime(row['exit_date']) if pd.notnull(row.get('exit_date')) else pd.Timestamp(year=report_year, month=12, day=31)

#         # Clip to reporting year
#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))

#         if role_start > role_end:
#             continue  # not active this year

#         # Calculate ramped monthly targets
#         month_index = 1
#         current = role_start.to_period("M").to_timestamp()

#         while current <= role_end:
#             month_num = current.month
#             month_name = months[month_num - 1]

#             for col in monthly_target_columns:
#                 base = row.get(col, 0) or 0
#                 monthly_value = base * month_index

#                 # Add monthly column
#                 col_name = f"{col}_{month_name}"
#                 result[col_name] = result.get(col_name, 0) + monthly_value

#                 # Add to annual total
#                 result[f'annual_{col}'] += monthly_value

#                 # Add to YTD if month <= reporting month
#                 if month_num <= mtd_month_num:
#                     result[f'ytd_{col}'] += monthly_value

#             month_index += 1
#             current += pd.DateOffset(months=1)

#     return pd.Series(result)


# In[197]:


# def calculate_annual_target(row,monthly_target_columns):
#     start_date = row['start_date']
    
#     annual_targets ={}
#     for target_column in monthly_target_columns:
#         monthly_targets = row[target_column]
#         months_remaining = 12 - (start_date.month) +1
#         annual_targets['annual' + '_' + target_column] = monthly_targets * months_remaining  # each persons targets depend on how many months they have in the year
#     return pd.Series(annual_targets)


# In[198]:


filtered_role_mapping = sales_persons_year_to_date_fraction(filtered_role_mapping,report_year,report_date)
filtered_role_mapping= filtered_role_mapping[filtered_role_mapping['active']==1]
# filtered_role_mapping = filtered_role_mapping.drop(columns={'start_date', 'exit_date','active'})
filtered_role_mapping


# In[199]:


# def calculate_targets_with_ytd_fraction(group, monthly_target_columns, mtd_date, ytd_fraction_col='ytd_fraction'):
#     """
#     Calculate ramped monthly targets stored in a single column per metric,
#     annual total, and YTD target using ytd_fraction.
    
#     - monthly_target_columns: list of base monthly targets (e.g., ["revenue_target"])
#     - ytd_fraction_col: column that contains fraction of year achieved (0-1)
    
#     Returns:
#     - monthly target for reporting month in <metric>
#     - annual total in annual_<metric>
#     - ytd target in ytd_<metric> = annual_total * ytd_fraction
#     """
#     result = {}
#     report_year = mtd_date.year

#     for col in monthly_target_columns:

#         # Rename base columns
#         result[f'{col}_base_target'] = group.iloc[0].get(col, 0)
        
#         result[col] = 0 # monthly target for each reporting  month
#         result[f'annual_{col}'] = 0
#         result[f'ytd_{col}'] = 0

#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = pd.to_datetime(row['exit_date']) if pd.notnull(row.get('exit_date')) else pd.Timestamp(year=report_year, month=12, day=31)

#         # Clip role period to reporting year
#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))

#         if role_start > role_end:
#             continue

#         # Ramp calculation
#         month_index = 1
#         current = role_start.to_period("M").to_timestamp()
#         mtd_month_num = mtd_date.month

#         while current <= role_end:
#             month_num = current.month

#             for col in monthly_target_columns:
#                 base = row.get(col, 0) or 0
#                 monthly_value = base * month_index

#                 # Monthly target for the reporting month
#                 if month_num == mtd_month_num:
#                     result[col] += monthly_value

#                 # Add to annual total
#                 result[f'annual_{col}'] += monthly_value

#             month_index += 1
#             current += pd.DateOffset(months=1)

#         # Compute YTD using fraction column
#         for col in monthly_target_columns:
#             fraction = row.get(ytd_fraction_col, 0) or 0
#             result[f'ytd_{col}'] = result[f'annual_{col}'] * fraction

#     return pd.Series(result)


# In[200]:


# def calculate_targets_with_ytd_fraction(group, monthly_target_columns, mtd_date, ytd_fraction_col="ytd_fraction"):
#     """
#     Preserves old columns with '_base' suffix.
#     All new calculated columns (monthly target, annual, YTD) are suffixed '_calc'.
#     """
#     result = {}
#     report_year = mtd_date.year
#     mtd_month_num = mtd_date.month

#     # Step 1: Preserve old columns with '_base'
#     for col in monthly_target_columns:
#         # Take the first non-null value in the group for the base column
#         base_value = group[col].dropna().iloc[0] if col in group.columns and not group[col].dropna().empty else 0
#         result[f'{col}_base'] = base_value

#         # Initialize calculated columns with '_calc'
#         result[f'{col}_calc'] = 0
#         result[f'annual_{col}_calc'] = 0
#         result[f'ytd_{col}_calc'] = 0

#     # Step 2: Loop through each row to calculate ramped targets
#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = pd.to_datetime(row['exit_date']) if pd.notnull(row.get('exit_date')) else pd.Timestamp(year=report_year, month=12, day=31)

#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))
#         if role_start > role_end:
#             continue

#         month_index = 1
#         current = role_start.to_period("M").to_timestamp()

#         while current <= role_end:
#             month_num = current.month

#             for col in monthly_target_columns:
#                 base = row.get(col, 0) or 0
#                 monthly_value = base * month_index

#                 # Current month target
#                 if month_num == mtd_month_num:
#                     result[f'{col}_calc'] += monthly_value

#                 # Annual total
#                 result[f'annual_{col}_calc'] += monthly_value

#             month_index += 1
#             current += pd.DateOffset(months=1)

#         # YTD using fraction
#         for col in monthly_target_columns:
#             fraction = row.get(ytd_fraction_col, 0) or 0
#             result[f'ytd_{col}_calc'] = result[f'annual_{col}_calc'] * fraction

#     return pd.Series(result)


# In[201]:


# ## with correct ytd total calculations

# def calculate_targets_with_ytd_fraction(group, monthly_target_columns, mtd_date, ytd_fraction_col="ytd_fraction"):
#     """
#     Preserves old columns with '_base' suffix.
#     Calculates monthly ramped target for the reporting month,
#     annual total for the full year,
#     and YTD total = sum of ramped months up to reporting month * ytd_fraction.
#     """
#     result = {}
#     report_year = mtd_date.year
#     mtd_month_num = mtd_date.month

#     # Preserve old columns
#     for col in monthly_target_columns:
#         base_value = group[col].dropna().iloc[0] if col in group.columns and not group[col].dropna().empty else 0
#         result[f'{col}_base'] = base_value

#         # Initialize calculated columns
#         result[f'{col}_calc'] = 0
#         result[f'annual_{col}_calc'] = 0
#         result[f'ytd_{col}_calc'] = 0

#     for _, row in group.iterrows():
#         start_date = pd.to_datetime(row['start_date'])
#         end_date = pd.to_datetime(row['exit_date']) if pd.notnull(row.get('exit_date')) else pd.Timestamp(year=report_year, month=12, day=31)

#         role_start = max(start_date, pd.Timestamp(year=report_year, month=1, day=1))
#         role_end = min(end_date, pd.Timestamp(year=report_year, month=12, day=31))
#         if role_start > role_end:
#             continue

#         # Ramp month index
#         month_index = 1
#         current = role_start.to_period("M").to_timestamp()

#         # For calculating annual total (full year)
#         annual_total = 0
#         ytd_total = 0

#         while current <= role_end:
#             month_num = current.month

#             for col in monthly_target_columns:
#                 base = row.get(col, 0) or 0
#                 monthly_value = base * month_index

#                 # Monthly target for the reporting month
#                 if month_num == mtd_month_num:
#                     result[f'{col}_calc'] += monthly_value

#                 # Annual total accumulates all months
#                 result[f'annual_{col}_calc'] += monthly_value

#                 # YTD only up to reporting month
#                 if month_num <= mtd_month_num:
#                     ytd_total = result[f'ytd_{col}_calc'] + monthly_value

#             month_index += 1
#             current += pd.DateOffset(months=1)

#         # Apply fraction to YTD
#         for col in monthly_target_columns:
#             fraction = row.get(ytd_fraction_col, 0) or 0
#             result[f'ytd_{col}_calc'] = ytd_total * fraction

#     return pd.Series(result)


# In[202]:


# Apply the function to each row
monthly_target_column =['target_banca_value','target_banca_life','target_banca_non_life']

annual_targets_df =(
    filtered_role_mapping
    .sort_values(['sales_code','start_date'])
    .groupby('sales_code')
    .apply(calculate_targets_with_ytd_fraction,monthly_target_columns=monthly_target_column, mtd_date=mtd_date,mtd_fraction= mtd_fraction)
    .reset_index()
                   )

filtered_role_mapping = pd.merge(
    filtered_role_mapping,
    annual_targets_df,
    on='sales_code',
    how='left'
)
# filtered_role_mapping = pd.concat([filtered_role_mapping,annual_targets_df], axis=1)
# filtered_role_mapping = filtered_role_mapping.drop(columns={'start_date'})
filtered_role_mapping.columns


# In[203]:


filtered_role_mapping_columns_to_keep=['sales_code', 'staff_name', 'staff_branch', 'staff_role',
       'staff_zone','target_banca_life_calc','target_banca_non_life_calc','annual_target_banca_life_calc',
                                       'annual_target_banca_non_life_calc','ytd_target_banca_life_calc',
                                       'ytd_target_banca_non_life_calc','target_banca_value_calc','annual_target_banca_value_calc','ytd_target_banca_value_calc','ytd_fraction']


# In[204]:


filtered_role_mapping[['sales_code','target_banca_life','target_banca_life_base','target_banca_life_calc','annual_target_banca_life_calc','ytd_target_banca_life_calc','ytd_fraction']]


# In[205]:


filtered_role_mapping = filtered_role_mapping[filtered_role_mapping_columns_to_keep]
filtered_role_mapping = filtered_role_mapping.rename(columns={'target_banca_life_calc':'target_banca_life','annual_target_banca_life_calc':'annual_target_banca_life',
                                                              'target_banca_non_life_calc':'target_banca_non_life','annual_target_banca_non_life_calc':'annual_target_banca_non_life',
                                                              'annual_target_banca_value_calc':'annual_target_banca_value','target_banca_value_calc':'target_banca_value'})


# In[206]:


# a check 
filtered_role_mapping[filtered_role_mapping['staff_name']=='Anne Mwaura']


# In[207]:


def roles_all_premiums(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in[ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    
  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_premium_table = roles_all_premiums(filtered_sales_report, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_premium_table.head(2)


# In[208]:


def roles_motor_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in[ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    
  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_motor_premium_table = roles_motor_premium(motor_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_motor_premium_table.head(2)


# In[209]:


def roles_non_motor_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_non_motor_premium_table = roles_non_motor_premium(non_motor_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_non_motor_premium_table.head(2)


# In[210]:


def roles_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

roles_life_premium_table = roles_life_premium(life_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_life_premium_table.head(1)


# In[211]:


def roles_non_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

roles_non_life_premium_table = roles_non_life_premium(non_life_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_non_life_premium_table.head(1)


# In[212]:


def roles_vic_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_vic_premium_table = roles_vic_premium(vic_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_vic_premium_table.head(2)


# In[213]:


def roles_vic_life_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_vic_life_premium_table = roles_vic_life_premium(vic_life_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_vic_life_premium_table.head(2)


# In[214]:


def roles_vic_non_life_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_vic_non_life_premium_table = roles_vic_non_life_premium(vic_non_life_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_vic_non_life_premium_table.head(2)


# In[215]:


def roles_non_vic_premium(dataframe, index, month_column_name, value_column_name):
  premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  premium_amt = premium_amt.fillna(0)
  premium_amt = premium_amt.reset_index()

  premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

  for month in premium_month_order:
      if  month not in premium_amt.columns:
          premium_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

                                            
  premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]

    
  premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
  return premium_amt

roles_non_vic_premium_table = roles_non_vic_premium(non_vic_premiums_data, month_column_name='month_name', index = 'code',value_column_name = 'paid_premiums')

roles_non_vic_premium_table.head(2)


# In[216]:


def roles_comm(dataframe, index, month_column_name, value_column_name):
  comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  comm_amt = comm_amt.fillna(0)
  comm_amt = comm_amt.reset_index()

  comm_month_order = [f'{month}-{report_year}' for month in[ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
  comm_present_columns = [col for col in comm_month_order if col in comm_amt.columns]

  for month in comm_month_order:
      if  month not in comm_amt.columns:
          comm_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
                                
  comm_amt =comm_amt[[index] + past_and_reporting_months +['Total']]   
    
  comm_amt['Total'] = comm_amt[past_and_reporting_months].sum(axis=1)
    
  return comm_amt

roles_comm_table = roles_comm(filtered_sales_report, month_column_name='month_name', index = 'code',value_column_name = 'commission')
roles_comm_table


# In[217]:


# def calculate_deficits(df, report_month):
#     months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
#               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
#     month_to_num = {m: i+1 for i, m in enumerate(months)}
#     report_month_num = month_to_num[report_month]

#     for idx, row in df.iterrows():
#         join_month = row['join_date'].month
#         target = row['monthly_target']
#         total_deficit = 0

#         for m in months[:report_month_num]:
#             month_num = month_to_num[m]

#             if month_num < join_month:
#                 df.at[idx, f'{m}_monthly_deficit'] = None
#                 continue

#             sales = row.get(m, 0) or 0
#             monthly_deficit = max(0, target - sales)
#             total_deficit += monthly_deficit

#             df.at[idx, f'{m}_monthly_deficit'] = monthly_deficit

#         # Store total and YTD deficit (same value)
#         df.at[idx, 'total_monthly_deficit'] = total_deficit
#         df.at[idx, 'adjusted_annual_targets'] = total_deficit

#         # Spread over remaining months
#         remaining_months = (12 - report_month_num) + 1
#         df.at[idx, 'adjusted_monthly_targets'] = 0 if total_deficit <= 0 else total_deficit / remaining_months

#     return df


# In[218]:


# ### motor premiums for roles


# In[219]:


# roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

# all_premiums_modified_tables=[]

# for role in roles:    
#     roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
#     roles_table= roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

#     all_premium_merged_roles_table = pd.merge(roles_table,roles_life_premium_table, left_on='sales_code', right_on='code', how='left')

#     all_premium_merged_roles_table=all_premium_merged_roles_table.fillna(0)
#     all_premium_merged_roles_table= all_premium_merged_roles_table.drop(columns=['code'])
#     all_premium_merged_roles_table= all_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
#                                                            'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_value':'annual_targets'},inplace = False)

#     month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
#     present_columns = [col for col in month_order if col in all_premium_merged_roles_table.columns]
#     # existing_columns = present_columns

    
#     #calculations

#     all_premium_merged_roles_table = calculation_formulas(all_premium_merged_roles_table)
#     all_premium_merged_roles_table= total_row(all_premium_merged_roles_table)
#     all_premium_merged_roles_table= rank_performance(all_premium_merged_roles_table,'ytd_score')
 
    
#     # life_premium_merged_roles_table['rm_code']= life_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
#     # replace branch with ''
#     all_premium_merged_roles_table['branch']= all_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


#     column_order = ['rank','rm_code','rm_name','branch','role','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
#     # life_premium_merged_roles_table = life_premium_merged_roles_table.fillna(0)
#     all_premium_merged_roles_table=all_premium_merged_roles_table[column_order].reset_index(drop=True)


#     all_premiums_modified_tables.append(all_premium_merged_roles_table)
    
# all_premium_merged_roles_table


# In[ ]:













# In[220]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

life_premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

    life_premium_merged_roles_table = pd.merge(roles_table,roles_life_premium_table, left_on='sales_code', right_on='code', how='left')

    life_premium_merged_roles_table=life_premium_merged_roles_table.fillna(0)
    life_premium_merged_roles_table= life_premium_merged_roles_table.drop(columns=['code'])
    life_premium_merged_roles_table= life_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_life':'annual_targets',
                                                                                     'ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in life_premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    life_premium_merged_roles_table = calculation_formulas_without_ytd(life_premium_merged_roles_table)
    life_premium_merged_roles_table= total_row(life_premium_merged_roles_table)
    life_premium_merged_roles_table= rank_performance(life_premium_merged_roles_table,'ytd_score')
 
    
    # life_premium_merged_roles_table['rm_code']= life_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    life_premium_merged_roles_table['branch']= life_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    column_order = ['rank','rm_code','rm_name','branch','role','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
    # life_premium_merged_roles_table = life_premium_merged_roles_table.fillna(0)
    life_premium_merged_roles_table=life_premium_merged_roles_table[column_order].reset_index(drop=True)


    life_premimum_modified_tables.append(life_premium_merged_roles_table)
    


# In[221]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

non_life_premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_non_life':'monthly_targets'},inplace = False)

    non_life_premium_merged_roles_table = pd.merge(roles_table,roles_non_life_premium_table, left_on='sales_code', right_on='code', how='left')

    non_life_premium_merged_roles_table=non_life_premium_merged_roles_table.fillna(0)
    non_life_premium_merged_roles_table= non_life_premium_merged_roles_table.drop(columns=['code'])
    non_life_premium_merged_roles_table= non_life_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_non_life':'annual_targets',
                                                                                            'ytd_target_banca_non_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]  
    present_columns = [col for col in month_order if col in non_life_premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    non_life_premium_merged_roles_table = calculation_formulas_without_ytd(non_life_premium_merged_roles_table)
    # non_life_premium_merged_roles_table = non_life_premium_merged_roles_table.fillna(0)
    non_life_premium_merged_roles_table= total_row(non_life_premium_merged_roles_table)
    # non_life_premium_merged_roles_table= rank_performance(non_motor_premium_merged_roles_t/able,'ytd_score')
    
    # non_life_premium_merged_roles_table['rm_code']= non_life_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    non_life_premium_merged_roles_table['branch']= non_life_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    column_order = ['rm_code','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
    
    non_life_premium_merged_roles_table=non_life_premium_merged_roles_table[column_order].reset_index(drop=True)


    non_life_premimum_modified_tables.append(non_life_premium_merged_roles_table)


# In[222]:


# ### non-vic premiums for roles


# In[223]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

non_vic_premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_non_life':'monthly_targets'},inplace = False)

    non_vic_premium_merged_roles_table = pd.merge(roles_table,roles_non_vic_premium_table, left_on='sales_code', right_on='code', how='left')

    non_vic_premium_merged_roles_table= non_vic_premium_merged_roles_table.fillna(0)
    non_vic_premium_merged_roles_table= non_vic_premium_merged_roles_table.drop(columns=['code'])
    non_vic_premium_merged_roles_table= non_vic_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_non_life':'annual_targets',
                                                                                            'ytd_target_banca_non_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]  
    present_columns = [col for col in month_order if col in non_vic_premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    non_vic_premium_merged_roles_table = calculation_formulas_without_ytd(non_vic_premium_merged_roles_table)
    # non_vic_premium_merged_roles_table = non_vic_premium_merged_roles_table.fillna(0)
    non_vic_premium_merged_roles_table= total_row(non_vic_premium_merged_roles_table)
    # non_vic_premium_merged_roles_table= rank_performance(non_motor_premium_merged_roles_t/able,'ytd_score')
    
    # non_vic_premium_merged_roles_table['rm_code']= non_vic_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    non_vic_premium_merged_roles_table['branch']= non_vic_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    # column_order = ['rm_code','rm_name']+ present_columns+[ 'ytd_cumulative']
    column_order = ['rm_code','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
    
    non_vic_premium_merged_roles_table=non_vic_premium_merged_roles_table[column_order].reset_index(drop=True)


    non_vic_premimum_modified_tables.append(non_vic_premium_merged_roles_table)


# In[224]:


non_vic_premium_merged_roles_table.head()


# In[225]:


# ### vic premiums for roles


# In[226]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

vic_premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

    vic_premium_merged_roles_table = pd.merge(roles_table,roles_vic_premium_table, left_on='sales_code', right_on='code', how='left')

    vic_premium_merged_roles_table= vic_premium_merged_roles_table.fillna(0)
    vic_premium_merged_roles_table= vic_premium_merged_roles_table.drop(columns=['code'])
    vic_premium_merged_roles_table= vic_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_life':'annual_targets',
                                                                                            'ytd_target_banca_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]  
    present_columns = [col for col in month_order if col in vic_premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    vic_premium_merged_roles_table = calculation_formulas_without_ytd_and_uncapped(vic_premium_merged_roles_table)
    vic_premium_merged_roles_table = calculate_deficits(vic_premium_merged_roles_table,report_month)
    vic_premium_merged_roles_table= uncapped_total_row(vic_premium_merged_roles_table)
    # vic_premium_merged_roles_table= rank_performance(non_motor_premium_merged_roles_t/able,'ytd_score')
    
    # vic_premium_merged_roles_table['rm_code']= vic_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    vic_premium_merged_roles_table['branch']= vic_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    # column_order = ['rm_code','rm_name']+ present_columns+['ytd_cumulative']
    column_order = ['rm_code','rm_name','branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score','ytd_deficit','adjusted_annual_targets']
 
    vic_premium_merged_roles_table=vic_premium_merged_roles_table[column_order].reset_index(drop=True)


    vic_premimum_modified_tables.append(vic_premium_merged_roles_table)


# In[227]:


merged_non_vic_tables=[]

for df1,df2 in zip(vic_premimum_modified_tables,non_vic_premimum_modified_tables):
    non_vic_combined_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # non_vic_combined_df = non_vic_combined_df.sort_values(by ='rank')
    non_vic_combined_df= non_vic_combined_df.drop(columns={'rm_code'})
    # non_vic_combined_df_column_order = present_columns + ['ytd_cumulative']
    # non_vic_combined_df = non_vic_combined_df[non_vic_combined_df_column_order]
    merged_non_vic_tables.append(non_vic_combined_df)


# In[228]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

vic_life_premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

    vic_life_premium_merged_roles_table = pd.merge(roles_table,roles_vic_life_premium_table, left_on='sales_code', right_on='code', how='left')

    vic_life_premium_merged_roles_table= vic_life_premium_merged_roles_table.fillna(0)
    vic_life_premium_merged_roles_table= vic_life_premium_merged_roles_table.drop(columns=['code'])
    vic_life_premium_merged_roles_table= vic_life_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_life':'annual_targets',
                                                                                            'ytd_target_banca_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]  
    present_columns = [col for col in month_order if col in vic_life_premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    vic_life_premium_merged_roles_table = calculation_formulas_without_ytd_and_uncapped(vic_life_premium_merged_roles_table)
    # vic_life_premium_merged_roles_table = vic_life_premium_merged_roles_table.fillna(0)
    vic_life_premium_merged_roles_table= uncapped_total_row(vic_life_premium_merged_roles_table)
    # vic_life_premium_merged_roles_table= rank_performance(non_motor_premium_merged_roles_t/able,'ytd_score')
    
    # vic_life_premium_merged_roles_table['rm_code']= vic_life_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    vic_life_premium_merged_roles_table['branch']= vic_life_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    # column_order = ['rm_code','rm_name']+ present_columns+['ytd_cumulative']
    column_order = ['rm_code','rm_name','branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
 
    vic_life_premium_merged_roles_table=vic_life_premium_merged_roles_table[column_order].reset_index(drop=True)


    vic_life_premimum_modified_tables.append(vic_life_premium_merged_roles_table)


# In[229]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

vic_non_life_premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_non_life':'monthly_targets'},inplace = False)

    vic_non_life_premium_merged_roles_table = pd.merge(roles_table,roles_vic_non_life_premium_table, left_on='sales_code', right_on='code', how='left')

    vic_non_life_premium_merged_roles_table= vic_non_life_premium_merged_roles_table.fillna(0)
    vic_non_life_premium_merged_roles_table= vic_non_life_premium_merged_roles_table.drop(columns=['code'])
    vic_non_life_premium_merged_roles_table= vic_non_life_premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_non_life':'annual_targets',
                                                                                            'ytd_target_banca_non_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]  
    present_columns = [col for col in month_order if col in vic_non_life_premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    vic_non_life_premium_merged_roles_table = calculation_formulas_without_ytd_and_uncapped(vic_non_life_premium_merged_roles_table)
    # vic_non_life_premium_merged_roles_table = vic_non_life_premium_merged_roles_table.fillna(0)
    vic_non_life_premium_merged_roles_table= uncapped_total_row(vic_non_life_premium_merged_roles_table)
    # vic_non_life_premium_merged_roles_table= rank_performance(non_motor_premium_merged_roles_t/able,'ytd_score')
    
    # vic_non_life_premium_merged_roles_table['rm_code']= vic_non_life_premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    vic_non_life_premium_merged_roles_table['branch']= vic_non_life_premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    # column_order = ['rm_code','rm_name']+ present_columns+[ 'ytd_cumulative']
    column_order = ['rm_code','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
    
    vic_non_life_premium_merged_roles_table=vic_non_life_premium_merged_roles_table[column_order].reset_index(drop=True)


    vic_non_life_premimum_modified_tables.append(vic_non_life_premium_merged_roles_table)


# In[230]:


merged_vic_nonlife_tables=[]

for df1,df2 in zip(vic_life_premimum_modified_tables,vic_non_life_premimum_modified_tables):
    vic_non_life_combined_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # non_vic_combined_df = non_vic_combined_df.sort_values(by ='rank')
    vic_non_life_combined_df= vic_non_life_combined_df.drop(columns={'rm_code'})
    # non_vic_combined_df_column_order = present_columns + ['ytd_cumulative']
    # non_vic_combined_df = non_vic_combined_df[non_vic_combined_df_column_order]
    merged_vic_nonlife_tables.append(vic_non_life_combined_df)


# ### all premiums for roles


# In[231]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

premimum_modified_tables=[]

for role in roles:    
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    roles_table= roles_table.rename(columns={'target_banca_value':'monthly_targets'},inplace = False)

    premium_merged_roles_table = pd.merge(roles_table,roles_premium_table, left_on='sales_code', right_on='code', how='left')

    premium_merged_roles_table=premium_merged_roles_table.fillna(0)
    premium_merged_roles_table= premium_merged_roles_table.drop(columns=['code'])
    premium_merged_roles_table= premium_merged_roles_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_value':'annual_targets',
                                                                          'ytd_target_banca_value_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]  
    present_columns = [col for col in month_order if col in premium_merged_roles_table.columns]
    # existing_columns = present_columns

    
    #calculations

    premium_merged_roles_table = calculation_formulas_without_ytd(premium_merged_roles_table)
    premium_merged_roles_table = calculate_deficits(premium_merged_roles_table,report_month)
    premium_merged_roles_table= total_row(premium_merged_roles_table)
    # premium_merged_roles_table= rank_performance(non_motor_premium_merged_roles_t/able,'ytd_score')
    
    # premium_merged_roles_table['rm_code']= premium_merged_roles_table['rm_code'].fillna('Total')
    
    
    # replace branch with ''
    premium_merged_roles_table['branch']= premium_merged_roles_table['branch'].str.replace(' BRANCH','',regex = False)


    # column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets','adjusted_monthly_targets']
    
    
    premium_merged_roles_table =premium_merged_roles_table.drop(columns={'target_banca_life', 'target_banca_non_life', 'annual_target_banca_life','annual_target_banca_non_life','ytd_fraction'})

    column_order = ['rm_code','rm_name','branch','role','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score','ytd_deficit','adjusted_annual_targets']
    premium_merged_roles_table=premium_merged_roles_table[column_order].reset_index(drop=True)
    premimum_modified_tables.append(premium_merged_roles_table)
    


# In[232]:


roles_vic_premium_table


# ### roles commissions


# In[233]:


roles = ['COMMERCIAL RM','SME RM', 'SME ARM','SME BBC','ULTIMATE RM','PB RM', 'PB ARM','PB BBC', 'DIASPORA RM', 'DIASPORA ARM','MORTGAGE RM', 'MORTGAGE ARM', 'HFDI PA','HFDI RO','HFDI PM','HFDI BDM','HFDI DPB']

commission_tables=[]

for role in roles:
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    roles_commission = pd.merge(roles_table,roles_comm_table, left_on ='sales_code', right_on='code', how= 'left')
    # roles_commission= roles_commission.drop(columns={'staff_name','staff_branch','staff_role','staff_zone','target_banca_value','annual_target_banca_value','code','target_banca_life',
    #                                                  'annual_target_banca_life','target_banca_non_life','annual_target_banca_non_life','ytd_target_banca_life_calc',
    #                                                  'ytd_target_banca_non_life_calc','ytd_target_banca_value_calc'})
    roles_commission=roles_commission.fillna(0)

    total_rows=[]
    total_n={}
    total_n.update(roles_commission.sum(numeric_only = True))
    total_rows.append(total_n)
    total_row_df = pd.DataFrame(total_rows, index=[0])
    roles_commission = pd.concat([roles_commission,total_row_df], ignore_index= True)
    roles_commission = roles_commission.reset_index(drop =True)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in roles_commission.columns]
    roles_commission_column_order = ['sales_code'] + present_columns +['Total']
    roles_commission = roles_commission[roles_commission_column_order]
    
    commission_tables.append(roles_commission)


# In[234]:


merged_non_life_tables=[]

for df1,df2 in zip(life_premimum_modified_tables,non_life_premimum_modified_tables):
    non_life_combined_df = pd.merge(df2,df1[['rank','rm_code']], on='rm_code', how='left')
    non_life_combined_df = non_life_combined_df.sort_values(by ='rank')
    non_life_combined_df= non_life_combined_df.drop(columns={'rank','rm_code'})
    merged_non_life_tables.append(non_life_combined_df)


# In[235]:


# premium_merged_roles_table.columns


# In[236]:


merged_premium_tables=[]

for df1,df2 in zip(life_premimum_modified_tables,premimum_modified_tables):
    premiums_combined_df = pd.merge(df2,df1[['rank','rm_code']], on='rm_code', how='left')
    premiums_combined_df = premiums_combined_df.sort_values(by ='rank')
    premiums_combined_df= premiums_combined_df.drop(columns={'rank'})
    column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
    
    premiums_combined_df=premiums_combined_df[column_order].reset_index(drop=True)
    merged_premium_tables.append(premiums_combined_df)


# In[237]:


merged_vic_deficit_tables=[]

for df1,df2 in zip(vic_premimum_modified_tables,premimum_modified_tables):
    vic_deficit_combined_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # premiums_combined_df = premiums_combined_df.sort_values(by ='rank')
    # premiums_combined_df= premiums_combined_df.drop(columns={'rank'})
    column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
    
    vic_deficit_combined_df=vic_deficit_combined_df[column_order].reset_index(drop=True)
    merged_vic_deficit_tables.append(vic_deficit_combined_df)


# In[238]:


vic_premimum_modified_tables[0].columns


# In[239]:


merged_vic_life_nonlife_deficit_tables=[]

for df1,df2 in zip(vic_life_premimum_modified_tables,vic_premimum_modified_tables):
    vic_life_non_life_deficit_combined_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # premiums_combined_df = premiums_combined_df.sort_values(by ='rank')
    # premiums_combined_df= premiums_combined_df.drop(columns={'rank'})
    column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
    
    vic_life_non_life_deficit_combined_df=vic_life_non_life_deficit_combined_df[column_order].reset_index(drop=True)
    merged_vic_life_nonlife_deficit_tables.append(vic_life_non_life_deficit_combined_df)


# In[240]:


# merge premium dfs with commission dfs to get values for a sales person in one row
merged_commission_tables =[]

for i,(df1,df2) in enumerate(zip(life_premimum_modified_tables,commission_tables)):
    comm_combined_df = pd.merge(df2,df1[['rank','rm_code']], left_on='sales_code', right_on='rm_code', how='left')
    comm_combined_df = comm_combined_df.sort_values(by ='rank')
    comm_combined_df= comm_combined_df.drop(columns={'sales_code','rank','rm_code'})
    # comm_combined_df= comm_combined_df.rename(columns={'Total':'ytd_cumulative'})

    merged_commission_tables.append(comm_combined_df)
# merged_commission_tables


# In[241]:


def get_avg_ytd_score(life_premiums,non_life_premiums):

    life_weight = 0.3
    non_life_weight = 0.7
    
   
    avg_ytd_score = (life_premiums['ytd_score']* life_weight) + (non_life_premiums['ytd_score'] * non_life_weight)                     
    return avg_ytd_score


# In[242]:


pb_dsr_average_ytd_score = get_avg_ytd_score(life_premiums=life_premium_merged_roles_table ,non_life_premiums = non_life_premium_merged_roles_table)


# In[243]:


pb_dsr_average_ytd_score.name = 'avg_ytd_score'


# ## pb & banca dsrs


# In[ ]:













# In[244]:


#motor premiums for roles

dsr_roles =['PB DSR','SME DSR','BANCA DSR']

life_premimum_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

    dsr_life_premium_merged_table = pd.merge(dsr_roles_table,roles_life_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_life_premium_merged_table=dsr_life_premium_merged_table.fillna(0)
    dsr_life_premium_merged_table= dsr_life_premium_merged_table.drop(columns=['code'])
    dsr_life_premium_merged_table= dsr_life_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_life':'annual_targets',
                                                                                'ytd_target_banca_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] 
    present_columns = [col for col in month_order if col in dsr_life_premium_merged_table.columns]

    # calculations
    dsr_life_premium_merged_table = calculation_formulas_without_ytd(dsr_life_premium_merged_table)
    dsr_life_premium_merged_table= total_row(dsr_life_premium_merged_table)
    dsr_life_premium_merged_table= rank_performance(dsr_life_premium_merged_table,'ytd_score')
    
    dsr_life_premium_merged_table['zone']= dsr_life_premium_merged_table['zone'].fillna('Total')
        
    # replace branch with ''
    dsr_life_premium_merged_table['branch']= dsr_life_premium_merged_table['branch'].str.replace(' BRANCH','',regex = False)


    column_order = ['rank','rm_code','rm_name','branch','role','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
    # dsr_life_premium_merged_table = dsr_life_premium_merged_table.fillna(0)
    dsr_life_premium_merged_table=dsr_life_premium_merged_table[column_order].reset_index(drop=True)


    life_premimum_dsr_tables.append(dsr_life_premium_merged_table)
    


# In[245]:


#remove duplicate rows for the same sales person
# dsrs_table= dsrs.drop_duplicates(subset='sales_code', keep='first')
# dsrs_table.head()


# In[246]:


dsr_roles =['PB DSR','SME DSR','BANCA DSR']

non_life_premium_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_non_life':'monthly_targets'},inplace = False)

    dsr_non_life_premium_merged_table = pd.merge(dsr_roles_table,roles_non_life_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_non_life_premium_merged_table=dsr_non_life_premium_merged_table.fillna(0)
    dsr_non_life_premium_merged_table= dsr_non_life_premium_merged_table.drop(columns=['code','staff_branch','staff_role','staff_zone','staff_name'])
    dsr_non_life_premium_merged_table= dsr_non_life_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code',
                                                                                           'annual_target_banca_non_life':'annual_targets',
                                                                                        'ytd_target_banca_non_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in dsr_non_life_premium_merged_table.columns]

    # calculations
    dsr_non_life_premium_merged_table = calculation_formulas_without_ytd(dsr_non_life_premium_merged_table)
    dsr_non_life_premium_merged_table= total_row(dsr_non_life_premium_merged_table)

    column_order = ['rm_code','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
    # dsr_non_life_premium_merged_table = dsr_non_life_premium_merged_table.fillna(0)
    dsr_non_life_premium_merged_table=dsr_non_life_premium_merged_table[column_order].reset_index(drop=True)


    non_life_premium_dsr_tables.append(dsr_non_life_premium_merged_table)


# In[247]:


dsr_roles =['PB DSR','SME DSR','BANCA DSR']

non_vic_premimum_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_non_life':'monthly_targets'},inplace = False)

    dsr_non_vic_premium_merged_table = pd.merge(dsr_roles_table,roles_non_vic_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_non_vic_premium_merged_table=dsr_non_vic_premium_merged_table.fillna(0)
    dsr_non_vic_premium_merged_table= dsr_non_vic_premium_merged_table.drop(columns=['code','staff_branch','staff_role','staff_zone','staff_name'])
    dsr_non_vic_premium_merged_table= dsr_non_vic_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code',
                                                                                           'annual_target_banca_non_life':'annual_targets',
                                                                                        'ytd_target_banca_non_life_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in dsr_non_vic_premium_merged_table.columns]

    # calculations
    dsr_non_vic_premium_merged_table = calculation_formulas_without_ytd_and_uncapped(dsr_non_vic_premium_merged_table)
    dsr_non_vic_premium_merged_table= total_row(dsr_non_vic_premium_merged_table)

    # column_order = ['rm_code']+ present_columns+['ytd_cumulative']
    column_order = ['rm_code','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

    
    # dsr_non_vic_premium_merged_table = dsr_non_vic_premium_merged_table.fillna(0)
    dsr_non_vic_premium_merged_table=dsr_non_vic_premium_merged_table[column_order].reset_index(drop=True)


    non_vic_premimum_dsr_tables.append(dsr_non_vic_premium_merged_table)

dsr_non_vic_premium_merged_table


# In[248]:


dsr_roles =['PB DSR','SME DSR','BANCA DSR']

vic_premimum_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

    dsr_vic_premium_merged_table = pd.merge(dsr_roles_table,roles_vic_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_vic_premium_merged_table=dsr_vic_premium_merged_table.fillna(0)
    dsr_vic_premium_merged_table= dsr_vic_premium_merged_table.drop(columns=['code','staff_role','staff_zone'])
    dsr_vic_premium_merged_table= dsr_vic_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code',
                                                                               'annual_target_banca_life':'annual_targets',
                                                                               'ytd_target_banca_life_calc':'ytd_target','staff_name':'rm_name','staff_branch':'branch'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in dsr_vic_premium_merged_table.columns]

    # calculations
    dsr_vic_premium_merged_table = calculation_formulas_without_ytd_and_uncapped(dsr_vic_premium_merged_table)
    dsr_vic_premium_merged_table = calculate_deficits(dsr_vic_premium_merged_table, report_month)
    dsr_vic_premium_merged_table= uncapped_total_row(dsr_vic_premium_merged_table)

    # column_order = ['rm_code','rm_name']+ present_columns+['ytd_cumulative']
    column_order = ['rm_code','rm_name','branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score','ytd_deficit','adjusted_annual_targets']

    dsr_vic_premium_merged_table['branch']= dsr_vic_premium_merged_table['branch'].str.replace(' BRANCH','',regex = False)
    # dsr_vic_premium_merged_table = dsr_vic_premium_merged_table.fillna(0)
    dsr_vic_premium_merged_table=dsr_vic_premium_merged_table[column_order].reset_index(drop=True)


    vic_premimum_dsr_tables.append(dsr_vic_premium_merged_table)

dsr_vic_premium_merged_table


# In[249]:


dsr_roles =['PB DSR','SME DSR','BANCA DSR']

vic_life_premimum_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_life':'monthly_targets'},inplace = False)

    dsr_vic_life_premium_merged_table = pd.merge(dsr_roles_table,roles_vic_life_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_vic_life_premium_merged_table=dsr_vic_life_premium_merged_table.fillna(0)
    dsr_vic_life_premium_merged_table= dsr_vic_life_premium_merged_table.drop(columns=['code','staff_role','staff_zone'])
    dsr_vic_life_premium_merged_table= dsr_vic_life_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code',
                                                                               'annual_target_banca_life':'annual_targets',
                                                                               'ytd_target_banca_life_calc':'ytd_target','staff_name':'rm_name','staff_branch':'branch'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in dsr_vic_life_premium_merged_table.columns]

    # calculations
    dsr_vic_life_premium_merged_table = calculation_formulas_without_ytd_and_uncapped(dsr_vic_life_premium_merged_table)
    dsr_vic_life_premium_merged_table= uncapped_total_row(dsr_vic_life_premium_merged_table)

    # column_order = ['rm_code','rm_name']+ present_columns+['ytd_cumulative']
    column_order = ['rm_code','rm_name','branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

    dsr_vic_life_premium_merged_table['branch']= dsr_vic_life_premium_merged_table['branch'].str.replace(' BRANCH','',regex = False)
    # dsr_vic_life_premium_merged_table = dsr_vic_life_premium_merged_table.fillna(0)
    dsr_vic_life_premium_merged_table=dsr_vic_life_premium_merged_table[column_order].reset_index(drop=True)


    vic_life_premimum_dsr_tables.append(dsr_vic_life_premium_merged_table)

dsr_vic_life_premium_merged_table


# In[250]:


dsr_roles =['PB DSR','SME DSR','BANCA DSR']

vic_non_life_premimum_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_non_life':'monthly_targets'},inplace = False)

    dsr_vic_non_life_premium_merged_table = pd.merge(dsr_roles_table,roles_vic_non_life_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_vic_non_life_premium_merged_table=dsr_vic_non_life_premium_merged_table.fillna(0)
    dsr_vic_non_life_premium_merged_table= dsr_vic_non_life_premium_merged_table.drop(columns=['code','staff_role','staff_zone'])
    dsr_vic_non_life_premium_merged_table= dsr_vic_non_life_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code',
                                                                               'annual_target_banca_non_life':'annual_targets',
                                                                               'ytd_target_banca_non_life_calc':'ytd_target','staff_name':'rm_name','staff_branch':'branch'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in dsr_vic_non_life_premium_merged_table.columns]

    # calculations
    dsr_vic_non_life_premium_merged_table = calculation_formulas_without_ytd_and_uncapped(dsr_vic_non_life_premium_merged_table)
    dsr_vic_non_life_premium_merged_table= uncapped_total_row(dsr_vic_non_life_premium_merged_table)

    # column_order = ['rm_code','rm_name']+ present_columns+['ytd_cumulative']
    column_order = ['rm_code','rm_name','branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']

    dsr_vic_non_life_premium_merged_table['branch']= dsr_vic_non_life_premium_merged_table['branch'].str.replace(' BRANCH','',regex = False)
    # dsr_vic_non_life_premium_merged_table = dsr_vic_non_life_premium_merged_table.fillna(0)
    dsr_vic_non_life_premium_merged_table=dsr_vic_non_life_premium_merged_table[column_order].reset_index(drop=True)


    vic_non_life_premimum_dsr_tables.append(dsr_vic_non_life_premium_merged_table)

# dsr_vic_non_life_premium_merged_table


# In[ ]:













# In[251]:


# all premiums

dsr_roles =['PB DSR','SME DSR','BANCA DSR']

premimum_dsr_tables=[]

for role in dsr_roles:    
    dsr_roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    
    dsr_roles_table= dsr_roles_table.rename(columns={'target_banca_value':'monthly_targets'},inplace = False)

    dsr_premium_merged_table = pd.merge(dsr_roles_table,roles_premium_table, left_on='sales_code', right_on='code', how='left')

    dsr_premium_merged_table=dsr_premium_merged_table.fillna(0)
    dsr_premium_merged_table= dsr_premium_merged_table.drop(columns=['code'])
    dsr_premium_merged_table= dsr_premium_merged_table.rename(columns={'Total':'ytd_cumulative','sales_code':'rm_code','staff_name':'rm_name',
                                                           'staff_branch':'branch','staff_role':'role','staff_zone':'zone','annual_target_banca_value':'annual_targets',
                                                                          'ytd_target_banca_value_calc':'ytd_target'},inplace = False)

    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] 
    present_columns = [col for col in month_order if col in dsr_premium_merged_table.columns]

    # calculations
    dsr_premium_merged_table = calculation_formulas_without_ytd(dsr_premium_merged_table)
    dsr_premium_merged_table = calculate_deficits(dsr_premium_merged_table,report_month)
    dsr_premium_merged_table= total_row(dsr_premium_merged_table)
 
    
    # dsr_premium_merged_table['zone']= dsr_premium_merged_table['zone'].fillna('Total')
        
    # # replace branch with ''
    # dsr_premium_merged_table['branch']= dsr_premium_merged_table['branch'].str.replace(' BRANCH','',regex = False)


    # column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets','adjusted_monthly_targets']
   
    # dsr_premium_merged_table=dsr_premium_merged_table[column_order].reset_index(drop=True)
    
    

    column_order = ['rm_code','rm_name','branch','role','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score','ytd_deficit','adjusted_annual_targets']
    dsr_premium_merged_table= dsr_premium_merged_table[column_order]


    premimum_dsr_tables.append(dsr_premium_merged_table)
    
premimum_dsr_tables


# In[252]:


dsrs_non_life_tables=[]

for df1,df2 in zip(life_premimum_dsr_tables,non_life_premium_dsr_tables):
    combined_df = pd.merge(df2,df1[['rank','rm_code']], on='rm_code', how='left')
    combined_df = combined_df.sort_values(by ='rank')
    combined_df= combined_df.drop(columns={'rank','rm_code'})
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_non_life_tables.append(combined_df)


# In[253]:


dsrs_non_vic_tables=[]

for df1,df2 in zip(vic_premimum_dsr_tables,non_vic_premimum_dsr_tables):
    non_vic_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # non_vic_df = non_vic_df.sort_values(by ='rank')
    non_vic_df= non_vic_df.drop(columns={'rm_code'})
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_non_vic_tables.append(non_vic_df)


# In[254]:


dsrs_vic_non_life_tables=[]

for df1,df2 in zip(vic_life_premimum_dsr_tables,vic_non_life_premimum_dsr_tables):
    vic_non_life_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # non_vic_df = non_vic_df.sort_values(by ='rank')
    vic_non_life_df= vic_non_life_df.drop(columns={'rm_code'})
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_vic_non_life_tables.append(vic_non_life_df)


# In[255]:


dsrs_all_premiums_tables=[]

for df1,df2 in zip(life_premimum_dsr_tables,premimum_dsr_tables):
    combined_df = pd.merge(df2,df1[['rank','rm_code']], on='rm_code', how='left')
    combined_df = combined_df.sort_values(by ='rank')
    combined_df= combined_df.drop(columns={'rank'})
    column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
    
    combined_df=combined_df[column_order].reset_index(drop=True)
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_all_premiums_tables.append(combined_df)


# In[256]:


dsrs_vic_deficit_tables=[]

for df1,df2 in zip(vic_premimum_dsr_tables,premimum_dsr_tables):
    combined_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # combined_df = combined_df.sort_values(by ='rank')
    # combined_df= combined_df.drop(columns={'rank'})
    column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
    
    combined_df=combined_df[column_order].reset_index(drop=True)
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_vic_deficit_tables.append(combined_df)


# In[257]:


dsrs_vic_life_nonlife_deficit_tables=[]

for df1,df2 in zip(vic_life_premimum_dsr_tables,vic_premimum_dsr_tables):
    combined_df = pd.merge(df2,df1[['rm_code']], on='rm_code', how='left')
    # combined_df = combined_df.sort_values(by ='rank')
    # combined_df= combined_df.drop(columns={'rank'})
    column_order = ['ytd_cumulative','ytd_deficit','adjusted_annual_targets']
    
    combined_df=combined_df[column_order].reset_index(drop=True)
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_vic_life_nonlife_deficit_tables.append(combined_df)


# In[258]:


dsr_commission_tables=[]

for role in dsr_roles:
    roles_table = filtered_role_mapping[filtered_role_mapping['staff_role']== role]
    roles_commission = pd.merge(roles_table,roles_comm_table, left_on ='sales_code', right_on='code', how= 'left')
    roles_commission= roles_commission.drop(columns={'staff_name','staff_branch','staff_role','staff_zone','target_banca_non_life','target_banca_life',
                                                     'target_banca_value','annual_target_banca_value','annual_target_banca_non_life','annual_target_banca_life','code'})
    roles_commission=roles_commission.fillna(0)

    total_rows=[]
    total_n={}
    total_n.update(roles_commission.sum(numeric_only = True))
    total_rows.append(total_n)
    total_row_df = pd.DataFrame(total_rows, index=[0])
    roles_commission = pd.concat([roles_commission,total_row_df], ignore_index= True)
    roles_commission = roles_commission.reset_index(drop =True)
    month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]
    present_columns = [col for col in month_order if col in roles_commission.columns]
    roles_commission_column_order = ['sales_code'] + present_columns +['Total']

    roles_commission = roles_commission[roles_commission_column_order]
    
    dsr_commission_tables.append(roles_commission)


# In[259]:


dsrs_commission_tables=[]

for df1,df2 in zip(life_premimum_dsr_tables,dsr_commission_tables):
    combined_df = pd.merge(df2,df1[['rank','rm_code']], left_on ='sales_code', right_on='rm_code', how='left')
    combined_df = combined_df.sort_values(by ='rank')
    combined_df= combined_df.drop(columns={'rank','rm_code','sales_code'})
    # combined_df= combined_df.rename(columns={'Total':'ytd_cumulative'})

    dsrs_commission_tables.append(combined_df)


# In[260]:


# dsrs_commission_tables


# In[261]:


#Total premiums
def total_premiums(dataframe, index, month_column_name, value_column_name):
  prem_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
  prem_amt = prem_amt.fillna(0).reset_index()

  prem_month_order = [f'{month}-{report_year}' for month in[ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ] #define the month order
  prem_present_columns = [col for col in prem_month_order if col in prem_amt.columns]
  for month in prem_month_order:
      if  month not in prem_amt.columns:
          prem_amt[month]=0

  current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
  past_and_reporting_months = [month for month in prem_month_order if dt.strptime (month,'%b-%Y') <= current_month]
                                            
  prem_amt =prem_amt[[index] + past_and_reporting_months +['Total']]     
  prem_amt['Total'] = prem_amt[past_and_reporting_months].sum(axis=1)
    
  return prem_amt

total_premiums_table = total_premiums(filtered_sales_report, month_column_name='month_name', index = 'code',value_column_name = 'total_premiums')

total_premiums_table.head(2)


# In[262]:


banca_dsrs_table = filtered_role_mapping[filtered_role_mapping['staff_role']== 'BANCA DSR']
banca_dsrs_table.columns


# In[263]:


# banca_dsrs_table['annual_targets'] = banca_dsrs_table[['annual_target_banca_motor','annual_target_banca_non_motor']].sum(axis=1)


# In[264]:


# banca_dsrs_table['monthly_targets'] = banca_dsrs_table[['target_banca_motor','target_banca_non_motor']].sum(axis=1)


# In[265]:


#total premiums
banca_dsr_total_premiums = pd.merge(banca_dsrs_table,total_premiums_table, left_on='sales_code', right_on='code', how='left')
banca_dsr_total_premiums.drop(columns ={'code','annual_target_banca_life','annual_target_banca_non_life','target_banca_life','target_banca_non_life'}, inplace =True)
banca_dsr_total_premiums = banca_dsr_total_premiums.rename(columns={'sales_code':'rm_code','staff_name':'rm_name','staff_branch':'branch','staff_role':'role','staff_zone':'zone',
                                                                   'Total':'ytd_cumulative','target_banca_value':'monthly_targets','annual_target_banca_value':'annual_targets'})
banca_dsr_total_premiums = banca_dsr_total_premiums.fillna(0)
banca_dsr_total_premiums


# In[266]:


banca_dsr_total_premiums = calculation_formulas(banca_dsr_total_premiums)


# In[267]:


banca_dsr_total_premiums= total_row(banca_dsr_total_premiums)


# In[268]:


banca_dsr_total_premiums = rank_performance(banca_dsr_total_premiums,'ytd_score')


# In[269]:


banca_dsr_total_premiums.columns


# In[270]:


dsr_column_order = ['rank','rm_code','rm_name','branch','role','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score"]+ present_columns+['ytd_target', 'ytd_cumulative','ytd_score']
banca_dsr_total_premiums= banca_dsr_total_premiums[dsr_column_order]


# In[271]:


banca_dsr_total_premiums.head(1)


# ## Subsidiaries


# In[ ]:













# In[272]:


# define subsidiaries and their targets which are adjusted every year(March); data from finance/hfbi
subs_vic_targets = [{'SUBSIDIARY':'HFCB','target_banca_life':841002.561890224,'target_banca_non_life':7734000 ,'target_banca_value':8575002.56189022 ,},
        {'SUBSIDIARY':'HFCB-BI','target_banca_life':1496928.01486693,'target_banca_non_life':13766000,'target_banca_value':15262928.0148669 },
        {'SUBSIDIARY':'PROPERTY','target_banca_life':271852.39264618,'target_banca_non_life':2500000,'target_banca_value':2771852.39264618}
               ]
subs_vic_targets = pd.DataFrame(subs_vic_targets)
subs_vic_targets


# In[273]:


# define subsidiaries and their targets which are adjusted every year(March); data from finance/hfbi
subs = [{'SUBSIDIARY':'HFCB','target_banca_life':841002.561890224,'target_banca_non_life':7734000 ,'target_banca_value':8575002.56189022 ,},
        {'SUBSIDIARY':'HFCB-BI','target_banca_life':1768780.40751311,'target_banca_non_life':16266000,'target_banca_value':18034780.4075131},
        {'SUBSIDIARY':'PROPERTY','target_banca_life':271852.39264618,'target_banca_non_life':2500000,'target_banca_value':2771852.39264618}]
subsidiaries = pd.DataFrame(subs)
subsidiaries


# ### hfc calculations


# In[274]:


# Apply the function to each row
monthly_target_column =['target_banca_value','target_banca_life','target_banca_non_life']

annual_targets_df =(
    subsidiaries
    .groupby('SUBSIDIARY')
    .apply(calculate_segment_targets_full_year,monthly_target_columns=monthly_target_column, mtd_date=mtd_date,mtd_fraction= mtd_fraction)
    .reset_index()
                   )

subsidiaries = pd.merge(
    subsidiaries,
    annual_targets_df,
    on='SUBSIDIARY',
    how='left'
)


subsidiaries_columns_to_keep=['SUBSIDIARY','target_banca_life_calc','target_banca_non_life_calc','annual_target_banca_life_calc',
                                       'annual_target_banca_non_life_calc','ytd_target_banca_life_calc',
                                       'ytd_target_banca_non_life_calc','target_banca_value_calc','annual_target_banca_value_calc','ytd_target_banca_value_calc']

subsidiaries_targets = subsidiaries[subsidiaries_columns_to_keep]
subsidiaries_targets = subsidiaries_targets.rename(columns={'target_banca_life_calc':'target_banca_life','annual_target_banca_life_calc':'annual_target_banca_life',
                                                              'target_banca_non_life_calc':'target_banca_non_life','annual_target_banca_non_life_calc':'annual_target_banca_non_life',
                                                              'annual_target_banca_value_calc':'annual_target_banca_value','target_banca_value_calc':'target_banca_value'})
subsidiaries_targets


# In[275]:


# Apply the function to each row
monthly_target_column =['target_banca_value','target_banca_life','target_banca_non_life']

annual_targets_df =(
    subs_vic_targets
    .groupby('SUBSIDIARY')
    .apply(calculate_segment_targets_full_year,monthly_target_columns=monthly_target_column, mtd_date=mtd_date,mtd_fraction= mtd_fraction)
    .reset_index()
                   )

subs_vic_targets = pd.merge(
    subs_vic_targets,
    annual_targets_df,
    on='SUBSIDIARY',
    how='left'
)


subsidiaries_columns_to_keep=['SUBSIDIARY','target_banca_life_calc','target_banca_non_life_calc','annual_target_banca_life_calc',
                                       'annual_target_banca_non_life_calc','ytd_target_banca_life_calc',
                                       'ytd_target_banca_non_life_calc','target_banca_value_calc','annual_target_banca_value_calc','ytd_target_banca_value_calc']

subsidiaries_vic_targets_table = subs_vic_targets[subsidiaries_columns_to_keep]
subsidiaries_vic_targets_table = subsidiaries_vic_targets_table.rename(columns={'target_banca_life_calc':'target_banca_life','annual_target_banca_life_calc':'annual_target_banca_life',
                                                              'target_banca_non_life_calc':'target_banca_non_life','annual_target_banca_non_life_calc':'annual_target_banca_non_life',
                                                              'annual_target_banca_value_calc':'annual_target_banca_value','target_banca_value_calc':'target_banca_value'})
subsidiaries_vic_targets_table


# In[ ]:

















# In[276]:


subsidiaries_life_targets_columns_to_keep= ['SUBSIDIARY','target_banca_life', 'annual_target_banca_life','ytd_target_banca_life_calc']
subsidiaries_life_targets =subsidiaries_targets[subsidiaries_life_targets_columns_to_keep]


# In[277]:


subsidiaries_non_life_targets_columns_to_keep= ['SUBSIDIARY','target_banca_non_life', 'annual_target_banca_non_life','ytd_target_banca_non_life_calc']
subsidiaries_non_life_targets =subsidiaries_targets[subsidiaries_non_life_targets_columns_to_keep]


# In[278]:


subsidiaries_vic_targets_columns_to_keep= ['SUBSIDIARY','target_banca_life', 'annual_target_banca_life','ytd_target_banca_life_calc']
subsidiaries_vic_life_targets =subsidiaries_vic_targets_table[subsidiaries_vic_targets_columns_to_keep]


# In[279]:


subsidiaries_non_vic_targets_columns_to_keep=['SUBSIDIARY','target_banca_non_life', 'annual_target_banca_non_life','ytd_target_banca_non_life_calc']
subsidiaries_vic_non_life_targets =subsidiaries_vic_targets_table[subsidiaries_non_vic_targets_columns_to_keep]


# In[280]:


subsidiaries_all_targets_columns_to_keep= ['SUBSIDIARY','target_banca_value', 'annual_target_banca_value','ytd_target_banca_value_calc']
subsidiaries_all_targets =subsidiaries_targets[subsidiaries_all_targets_columns_to_keep]


# In[281]:


# for hfc, we'll need branch values and rm (where =operations) values
#get data for operations only
report= filtered_sales_report[filtered_sales_report['rm'] == 'Operations']
report.head(2)


# In[282]:


# # get total premiums where RM is Operations only

# def hfc_premium(dataframe, index, month_column_name, value_column_name):
#   premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
#   premium_amt = premium_amt.fillna(0)
#   premium_amt = premium_amt.reset_index()

  
#   premium_month_order = [f'{month}-{report_year}' for month in[ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
#   premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]
    
#   for month in premium_month_order:
#       if  month not in premium_amt.columns:
#           premium_amt[month]=0

#   current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
#   past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
                                            

                                            
#   premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown
    
#   premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    
#   return premium_amt

# operations_premium_table = hfc_premium(report, month_column_name='month_name', index = 'rm',value_column_name = 'total_premiums')


# operations_premium_table


# In[283]:


def hfc_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

operations_premium_table = hfc_premium(report, month_column_name='month_name', index = 'rm',value_column_name = 'total_premiums')


operations_premium_table
# report


# In[284]:


# drop total row
hfc_premium_table=(operations_premium_table.drop(operations_premium_table.index[-1]) if not operations_premium_table.empty else operations_premium_table.copy())
hfc_premium_table

# get totals paid premiums from branches table
hfc_branch_premium_table= pd.DataFrame(branch_premium_table.iloc[-1]).T
hfc_branch_premium_table.drop(columns={'branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score",'ytd_target','ytd_cumulative','ytd_score'}, inplace =True)
hfc_branch_premium_table


# In[285]:


# value_to_remove =['HFCB-BI'] # remove hfbi row

# branch_monthly_premium_table =branch_monthly_premium_table[~branch_monthly_premium_table['branch_name'].isin(value_to_remove)]
# branch_monthly_premium_table


# In[286]:


# concat operations and branch values
hfc =pd.concat([hfc_branch_premium_table, hfc_premium_table], axis =0)
hfc.drop(columns={'rank','Total','rm'},inplace=True)
hfc

sum_row =hfc.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfc = pd.concat([hfc, sum_row], ignore_index = True)


hfc_premiums = hfc.iloc[-1:]
hfc_premiums = hfc_premiums.astype(int)
hfc_premiums


# #### hfbi calculations


# In[ ]:













# In[287]:


# for getting values when rm is not Operations and branch name is HFBI
hfbi_report = filtered_sales_report[(filtered_sales_report['rm'] != 'Operations') & (filtered_sales_report['branch_name']=='HFCB-BI')]
              


# In[288]:


hfdi_report = filtered_sales_report[filtered_sales_report['segment']=='PROPERTY']


# In[289]:


def hfbi_paid_premiums (dataframe, index, month_column_name, value_column_name):
    premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    premium_amt = premium_amt.fillna(0)
    premium_amt = premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in premium_amt.columns]

    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    premium_amt = premium_amt[[index] + past_and_reporting_months +['Total']]

    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    return premium_amt



hfbi_premiums_table = hfbi_paid_premiums(hfbi_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfbi_premiums_table


# In[290]:


def hfdi_paid_premiums (dataframe, index, month_column_name, value_column_name):
    premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    premium_amt = premium_amt.fillna(0)
    premium_amt = premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in premium_amt.columns]

    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    premium_amt = premium_amt[[index] + past_and_reporting_months +['Total']]

    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)
    return premium_amt



hfdi_premiums_table = hfdi_paid_premiums(hfdi_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfdi_premiums_table


# In[291]:


hfbi_premiums_table=hfbi_premiums_table.drop(hfbi_premiums_table.index[-1])
hfbi_premiums_table


# In[292]:


hfdi_premiums_table=hfdi_premiums_table.drop(hfdi_premiums_table.index[-1])
hfdi_premiums_table = hfdi_premiums_table.drop(columns={'branch_name','Total'})


# In[293]:


operations_premium_table= (pd.DataFrame(operations_premium_table.iloc[-1]).T if not operations_premium_table.empty else pd.DataFrame(columns=operations_premium_table.columns))
operations_premium_table

# print("hfbi_premiums_table")


# print("operations_premium_table")


# In[294]:


hfbi =pd.concat([hfbi_premiums_table, operations_premium_table], axis =0, ignore_index=True)
hfbi.drop(columns={'branch_name','Total','rm'},inplace=True)
hfbi


# In[295]:


hfbi= hfbi.T
hfbi


# In[296]:


#the year's allocated monthly amount 
# this values change every year( get values from hfbi/finance)
# this is for mortgage renewals(fire,20%),BBB & Cyber crime, company assets

## for months were values are unequal
# month_values_jan_and_feb =5173323.5
# march_month_value =  5173323.5
# month_values_april_to_dec = 5173323.5

equal_monthly_values = 15855003.0183333

current_month = dt.strptime(f'{report_month}','%b').month


mtd_values = {}
month_names = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]

def calculate_fire_month_values(mtd_fraction):

    # for month in range(1,13):( for unequal months)
    #     if month < current_month:
    #         if month == 1 or month == 2: #Jan & Feb have the same values 
    #             additional_value = month_values_jan_and_feb
    #         elif  month == 3: # for March
    #             additional_value = march_month_value
    #         else: # months greather than March
    #             additional_value = month_values_april_to_dec
                
    #     elif month == current_month:
    #         if month == 1 or month == 2: #Jan & Feb
    #             additional_value = month_values_jan_and_feb * mtd_fraction
    #         elif month == 3:
    #             additional_value = march_month_value* mtd_fraction
    #         elif month > 3:
    #             additional_value = month_values_april_to_dec* mtd_fraction     
    #     else:
    #         additional_value = 0


    for month in range(1,13):
        if month < current_month:
            additional_value = equal_monthly_values
                
        elif month == current_month:
            additional_value = equal_monthly_values* mtd_fraction     
        else:
            additional_value = 0
            
        mtd_values[month_names[month-1]] = additional_value
        
    return mtd_values

mtd_values=  calculate_fire_month_values(mtd_fraction)

hfbi_fire_bbb_companyassets_additional_values = pd.DataFrame(list(mtd_values.items()), columns=['month_name','values'])
hfbi_fire_bbb_companyassets_additional_values.set_index('month_name', inplace =True)

hfbi_fire_bbb_companyassets_additional_values


# In[297]:


#the year's allocated monthly amount 
# this values change manually every year on  March / April
# this values are for mortgage renewals(life only)(80%)

# month_values_jan_and_feb =18180090
# march_month_value =  18180090
# month_values_april_to_dec = 18180090

equal_monthly_values = 11145367.8

current_month = dt.strptime(f'{report_month}','%b').month


mtd_values = {}
month_names = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]

def calculate_life_month_values(mtd_fraction):

    for month in range(1,13):
        # if month < current_month:
        #     if month == 1 or month == 2: #Jan & Feb have the same values 
        #         additional_value = month_values_jan_and_feb
        #     elif  month == 3: # for March
        #         additional_value = march_month_value
        #     else: # months greather than March
        #         additional_value = month_values_april_to_dec
                
        # elif month == current_month:
        #     if month == 1 or month == 2: #Jan & Feb
        #         additional_value = month_values_jan_and_feb * mtd_fraction
        #     elif month == 3:
        #         additional_value = march_month_value* mtd_fraction
        #     elif month > 3:
        #         additional_value = month_values_april_to_dec* mtd_fraction     
        # else:
        #     additional_value = 0
                  
        # mtd_values[month_names[month-1]] = additional_value

        if month < current_month:
            additional_value = equal_monthly_values
                
        elif month == current_month:
            additional_value = equal_monthly_values* mtd_fraction     
        else:
            additional_value = 0
                  
        mtd_values[month_names[month-1]] = additional_value

        
    return mtd_values

mtd_values=  calculate_life_month_values(mtd_fraction)

hfbi_life_additional_values = pd.DataFrame(list(mtd_values.items()), columns=['month_name','values'])
hfbi_life_additional_values.set_index('month_name', inplace =True)

hfbi_life_additional_values


# In[298]:


#the year's allocated monthly amount 
# this a summation of the life and non lfe additional values 

# month_values_jan_and_feb =23353413.5
# march_month_value =  23353413.5
# month_values_april_to_dec = 23353413.5
equal_monthly_values = 27000370.8183333

current_month = dt.strptime(f'{report_month}','%b').month


mtd_values = {}
month_names = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]

def calculate_month_values(mtd_fraction):

    for month in range(1,13):
        # if month < current_month:
        #     if month == 1 or month == 2: #Jan & Feb have the same values 
        #         additional_value = month_values_jan_and_feb
        #     elif  month == 3: # for March
        #         additional_value = march_month_value
        #     else: # months greather than March
        #         additional_value = month_values_april_to_dec
                
        # elif month == current_month:
        #     if month == 1 or month == 2: #Jan & Feb
        #         additional_value = month_values_jan_and_feb * mtd_fraction
        #     elif month == 3:
        #         additional_value = march_month_value* mtd_fraction
        #     elif month > 3:
        #         additional_value = month_values_april_to_dec* mtd_fraction     
        # else:
        #     additional_value = 0
                  
        # mtd_values[month_names[month-1]] = additional_value


        if month < current_month:
            additional_value = equal_monthly_values
        elif month == current_month:
            additional_value = equal_monthly_values* mtd_fraction     
        else:
            additional_value = 0
                  
        mtd_values[month_names[month-1]] = additional_value
    
    return mtd_values

mtd_values=  calculate_month_values(mtd_fraction)

hfbi_additional_values = pd.DataFrame(list(mtd_values.items()), columns=['month_name','values'])
hfbi_additional_values.set_index('month_name', inplace =True)

hfbi_additional_values


# In[299]:


# month_values_jan_and_feb =23353413.5
# march_month_value =  23353413.5
# month_values_april_to_dec = 23353413.5
equal_monthly_values = 3348614.37163917

current_month = dt.strptime(f'{report_month}','%b').month


mtd_values = {}
month_names = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]

def calculate_month_values(mtd_fraction):

    for month in range(1,13):
        if month < current_month:
            additional_value = equal_monthly_values
        elif month == current_month:
            additional_value = equal_monthly_values* mtd_fraction     
        else:
            additional_value = 0
                  
        mtd_values[month_names[month-1]] = additional_value
    
    return mtd_values

mtd_values=  calculate_month_values(mtd_fraction)

hfbi_installed_britam_medical_values = pd.DataFrame(list(mtd_values.items()), columns=['month_name','values'])
hfbi_installed_britam_medical_values.set_index('month_name', inplace =True)

hfbi_installed_britam_medical_values


# In[300]:


# month_values_jan_and_feb =23353413.5
# march_month_value =  23353413.5
# month_values_april_to_dec = 23353413.5
equal_monthly_values = 2186285.41619417

current_month = dt.strptime(f'{report_month}','%b').month


mtd_values = {}
month_names = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]

def calculate_month_values(mtd_fraction):

    for month in range(1,13):
        if month < current_month:
            additional_value = equal_monthly_values
        elif month == current_month:
            additional_value = equal_monthly_values* mtd_fraction     
        else:
            additional_value = 0
                  
        mtd_values[month_names[month-1]] = additional_value
    
    return mtd_values

mtd_values=  calculate_month_values(mtd_fraction)

hfbi_sales_britam_medical_values = pd.DataFrame(list(mtd_values.items()), columns=['month_name','values'])
hfbi_sales_britam_medical_values.set_index('month_name', inplace =True)

hfbi_sales_britam_medical_values


# In[301]:


equal_monthly_values = 5534899.78783333  # totals for both intalled and sales
# equal_monthly_values = 2186285.41619417 # only for installed business( total of 26 million)
current_month = dt.strptime(f'{report_month}','%b').month


mtd_values = {}
month_names = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec'] ]

def calculate_month_values(mtd_fraction):

    for month in range(1,13):
        if month < current_month:
            additional_value = equal_monthly_values
        elif month == current_month:
            additional_value = equal_monthly_values* mtd_fraction     
        else:
            additional_value = 0
                  
        mtd_values[month_names[month-1]] = additional_value
    
    return mtd_values

mtd_values=  calculate_month_values(mtd_fraction)

hfbi_total_britam_medical_values = pd.DataFrame(list(mtd_values.items()), columns=['month_name','values'])
hfbi_total_britam_medical_values.set_index('month_name', inplace =True)

hfbi_total_britam_medical_values


# In[302]:


hfbi= pd.concat([hfbi,hfbi_additional_values], axis =1)
hfbi= hfbi.dropna()
hfbi= hfbi.T
hfbi

#hfbi premiums calculation total
sum_row =hfbi.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfbi = pd.concat([hfbi, sum_row], ignore_index = True)


# In[303]:


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
hfbi_present_months = [col for col in month_order if col in hfbi.columns]

for month in month_order:
    if  month not in hfbi.columns:
        hfbi[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

hfbi = hfbi[past_and_reporting_months]


hfbi_premiums= hfbi.iloc[-1:]
hfbi_premiums=hfbi_premiums.reset_index(drop=True)
hfbi_premiums=hfbi_premiums.astype(int)
hfbi_premiums = hfbi_premiums[past_and_reporting_months]
hfbi_premiums


# In[304]:


# subsidiaries_premiums




# In[305]:


# merged subsidiaries calculations

subsidiaries_premiums= pd.concat([hfc_premiums,hfbi_premiums],axis =0)
subsidiaries_premiums= pd.concat([subsidiaries_premiums,hfdi_premiums_table], axis =0)
subsidiaries_premiums=subsidiaries_premiums.reset_index(drop=True)
subsidiaries_premiums['ytd_cumulative'] = subsidiaries_premiums.sum(axis=1)
subsidiaries_premiums


# In[306]:


subsidiaries_premiums_table= pd.concat([subsidiaries_all_targets,subsidiaries_premiums], axis =1)
subsidiaries_premiums_table = subsidiaries_premiums_table.fillna(0)


# In[307]:


subsidiaries_premiums_table


# In[308]:


subsidiaries_premiums_table = subsidiaries_premiums_table.rename(columns ={'target_banca_value':'monthly_targets','annual_target_banca_value':'annual_targets',
'ytd_target_banca_value_calc':'ytd_target'})


# In[ ]:

















# In[309]:


subsidiaries_premiums_table = calculation_branch_formulas(subsidiaries_premiums_table)
subsidiaries_premiums_table = calculate_deficits(subsidiaries_premiums_table,report_month)


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in subsidiaries_premiums_table.columns]
# existing_months=present_months
column_order = ['SUBSIDIARY', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit','adjusted_annual_targets']


subsidiaries_premiums_table= subsidiaries_premiums_table[column_order]
subsidiaries_premiums_table
subsidiaries_premiums_table_total_row= total_row(subsidiaries_premiums_table)


# In[310]:


subsidiaries_premiums_table_total_row = subsidiaries_premiums_table_total_row.iloc[-1:]
subsidiaries_premiums_table_total_row= subsidiaries_premiums_table_total_row.fillna(0).astype(int)


# In[311]:


subsidiaries_premiums_table_total_row


# In[312]:


# determine operation values to less from the total
operations_premium_total_row = operations_premium_table.rename(columns={'Total':'ytd_cumulative'})
operations_premium_total_row.drop(columns={'rm'}, inplace =True)
operations_premium_total_row


# In[313]:


def calculation_operations_formulas(df):
    column_name = f'{report_month}-{report_year}'

    if column_name in df.columns:
        df['current_month_actuals'] = df[column_name]
    else:
        df['current_month_actuals'] = 0

    if 'monthly_targets' not in df.columns:
        df['monthly_targets'] = df['annual_targets'] / 12


    df['mtd_target'] = df['monthly_targets'] * mtd_fraction
    df['ytd_target'] = df['annual_targets'] * fraction


    df['current_month_score'] = 0.0
    df['ytd_score'] = 0.0

    non_zero_annual_targets = df['annual_targets'] > 0

    
    df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_score'] = (
        df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'current_month_actuals']
        / df.loc[non_zero_annual_targets & (df['mtd_target'] > 0), 'mtd_target']
    ).clip(upper=1.2)

    
    if 'ytd_cumulative' in df.columns:
        df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_score'] = (
            df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_cumulative']
            / df.loc[non_zero_annual_targets & (df['ytd_target'] > 0), 'ytd_target']
        ).clip(upper=1.2)

    return df


# In[314]:


operations_premium_total_row['annual_targets'] =122500000
operations_premium_total_row = calculation_operations_formulas(operations_premium_total_row)
operations_premium_total_row


# In[315]:


operations_premium_total_row.columns


# In[316]:


# operations_premium_total_row


# In[317]:


#operations values to be deducted from subsidiaries total to get actual values

column_order = ['annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score']
operations_premium_total_row= operations_premium_total_row[column_order]
operations_premium_total_row = operations_premium_total_row.fillna(0).astype(int)
operations_premium_total_row = operations_premium_total_row.reset_index(drop=True)
operations_premium_total_row


# In[318]:


if not operations_premium_total_row.empty and 0 in operations_premium_total_row.index:
    operations_premium_total_row.loc[0] = -operations_premium_total_row.loc[0]


# In[319]:


# operations_premium_total_row.loc[0]=-operations_premium_total_row.loc[0]
operations_premium_total_row


# In[ ]:























# In[320]:


#concatenate the two dfs
merged_subsidiaries_premiums = pd.concat([subsidiaries_premiums_table_total_row,operations_premium_total_row], axis = 0)
merged_subsidiaries_premiums=merged_subsidiaries_premiums.reset_index(drop=True)
merged_subsidiaries_premiums = merged_subsidiaries_premiums.fillna(0)
merged_subsidiaries_premiums


# In[321]:


# function to get actual subsidiaries total values
def premiums_total_row(df):
    premiums_total_row = df.select_dtypes(include ='number').sum()
    premiums_total_row["current_month_score"] = premiums_total_row['current_month_actuals']/ premiums_total_row['mtd_target']
    premiums_total_row['ytd_score'] = premiums_total_row['ytd_cumulative'] / premiums_total_row['ytd_target']
    premiums_total_row = pd.DataFrame(premiums_total_row).T
    premiums_total_row.index = ['Total']
    df = pd.concat([df, premiums_total_row],axis = 0)
    
    return df


# In[322]:


merged_subsidiaries_premiums =premiums_total_row(merged_subsidiaries_premiums)
merged_subsidiaries_premiums


# In[323]:


merged_subsidiaries_premiums_actual_total = merged_subsidiaries_premiums.iloc[-1:]
merged_subsidiaries_premiums_actual_total


# In[324]:


#merge actual subsidiaries total row to subsidiaries table
subsidiaries_premiums_table = pd.concat([subsidiaries_premiums_table, merged_subsidiaries_premiums_actual_total],axis = 0)
subsidiaries_premiums_table


# In[ ]:























# In[325]:


subsidiaries_premiums_table.iloc[3:4,:1] ='Total'
subsidiaries_premiums_table


# ## subsidiaries- life & non- life tables


# In[326]:


life_premiums_report= life_premiums_data[life_premiums_data['rm'] == 'Operations']
non_life_premiums_report= non_life_premiums_data[non_life_premiums_data['rm'] == 'Operations']


# In[327]:


def hfc_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

operations_life_premium_table = hfc_life_premium(life_premiums_report, month_column_name='month_name', index = 'rm',value_column_name = 'total_premiums')


operations_life_premium_table


# In[328]:


# drop total row
hfc_life_premium_table=(operations_life_premium_table.drop(operations_life_premium_table.index[-1]) if not operations_life_premium_table.empty else operations_life_premium_table.copy())
hfc_life_premium_table

# get totals paid premiums from branches table
hfc_branch_life_premium_table= pd.DataFrame(branch_life_premium_table.iloc[-1]).T
hfc_branch_life_premium_table.drop(columns={'rank','zone','branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score",'ytd_target','ytd_cumulative','ytd_score'}, inplace =True)
hfc_branch_life_premium_table


# In[329]:


# concat operations and branch values
hfc_life =pd.concat([hfc_branch_life_premium_table, hfc_life_premium_table], axis =0)
hfc_life.drop(columns={'Total','rm'},inplace=True)
hfc_life

sum_row =hfc_life.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfc_life = pd.concat([hfc_life, sum_row], ignore_index = True)


hfc_life_premiums = hfc_life.iloc[-1:]
hfc_life_premiums = hfc_life_premiums.astype(int)
hfc_life_premiums


# In[ ]:





















# In[330]:


def hfc_non_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

operations_non_life_premium_table = hfc_non_life_premium(non_life_premiums_report, month_column_name='month_name', index = 'rm',value_column_name = 'total_premiums')


operations_non_life_premium_table


# In[331]:


# drop total row
hfc_non_life_premium_table=(operations_non_life_premium_table.drop(operations_non_life_premium_table.index[-1]) if not operations_non_life_premium_table.empty else operations_non_life_premium_table.copy())


# get totals paid premiums from branches table
hfc_non_life_branch_premium_table= pd.DataFrame(branch_non_life_premium_table.iloc[-1]).T
hfc_non_life_branch_premium_table.drop(columns={'rank','branch','zone','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score",'ytd_target','ytd_cumulative','ytd_score'}, inplace =True)
hfc_non_life_branch_premium_table


# In[332]:


# concat operations and branch values
hfc_non_life =pd.concat([hfc_non_life_branch_premium_table, hfc_non_life_premium_table], axis =0)
hfc_non_life.drop(columns={'Total','rm'},inplace=True)
hfc_non_life

sum_row =hfc_non_life.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfc_non_life = pd.concat([hfc_non_life, sum_row], ignore_index = True)


hfc_non_life_premiums = hfc_non_life.iloc[-1:]
hfc_non_life_premiums = hfc_non_life_premiums.astype(int)
hfc_non_life_premiums


# #### hfbi - life


# In[333]:


# for getting values when rm is not Operations and branch name is HFBI

hfbi_life_report = life_premiums_data[(life_premiums_data['rm'] != 'Operations') & (life_premiums_data['branch_name']=='HFCB-BI')]
hfbi_life_report.head() 


# In[334]:


def hfbi_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfbi_life_premiums_table = hfbi_life_premiums(hfbi_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfbi_life_premiums_table


# In[335]:


# hfbi_life_premiums_table=hfbi_life_premiums_table.drop(hfbi_life_premiums_table.index[-1])
# hfbi_life_premiums_table


# In[ ]:





















# In[336]:


hfbi_life_premiums_table= (pd.DataFrame(hfbi_life_premiums_table.iloc[-1]).T if not hfbi_life_premiums_table.empty else pd.DataFrame(columns=hfbi_life_premiums_table.columns))
hfbi_life_premiums_table

# print("hfbi_premiums_table")
# hfbi_life_premiums_table

# print("operations_premium_table")
# hfbi_life_premiums_table


# In[337]:


# hfbi_life_additional_values= hfbi_life_additional_values.T


# In[338]:


hfbi_life_table =pd.concat([hfbi_life_premiums_table, operations_life_premium_table], axis =0, ignore_index=True)
hfbi_life_table.drop(columns={'branch_name','Total','rm'},inplace=True)
hfbi_life_table


# In[339]:


hfbi_life_table =hfbi_life_table.T


# In[340]:


hfbi_life_table= pd.concat([hfbi_life_table,hfbi_life_additional_values], axis =1)
hfbi_life_table= hfbi_life_table.dropna()
hfbi_life_table= hfbi_life_table.T
hfbi_life_table

#hfbi premiums calculation total
sum_row =hfbi_life_table.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfbi_life_table = pd.concat([hfbi_life_table, sum_row], ignore_index = True)
hfbi_life_table= (pd.DataFrame(hfbi_life_table.iloc[-1]).T if not hfbi_life_table.empty else pd.DataFrame(columns=hfbi_life_table.columns))


# In[341]:


hfbi_life_table


# In[342]:


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
hfbi_present_months = [col for col in month_order if col in hfbi_life_table.columns]

for month in month_order:
    if  month not in hfbi_life_table.columns:
        hfbi_life_table[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

hfbi_life_table = hfbi_life_table[past_and_reporting_months]

hfbi_life_table


# #### hfbi - non_life


# In[ ]:















# In[ ]:















# In[343]:


hfbi_non_life_report = non_life_premiums_data[(non_life_premiums_data['rm'] != 'Operations') & (non_life_premiums_data['branch_name']=='HFCB-BI')]
hfbi_non_life_report.head() 


# In[344]:


def hfbi_non_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfbi_non_life_premiums_table = hfbi_non_life_premiums(hfbi_non_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfbi_non_life_premiums_table


# In[345]:


hfbi_non_life_premiums_table= (pd.DataFrame(hfbi_non_life_premiums_table.iloc[-1]).T if not hfbi_non_life_premiums_table.empty else pd.DataFrame(columns=hfbi_non_life_premiums_table.columns))
hfbi_non_life_premiums_table


# In[346]:


hfbi_non_life_table =pd.concat([hfbi_non_life_premiums_table, operations_non_life_premium_table], axis =0, ignore_index=True)
hfbi_non_life_table.drop(columns={'branch_name','Total','rm'},inplace=True)
hfbi_non_life_table


# In[347]:


hfbi_non_life_table =hfbi_non_life_table.T


# In[348]:


hfbi_non_life_table= pd.concat([hfbi_non_life_table,hfbi_fire_bbb_companyassets_additional_values], axis =1)
hfbi_non_life_table= hfbi_non_life_table.dropna()
hfbi_non_life_table= hfbi_non_life_table.T
hfbi_non_life_table

#hfbi premiums calculation total
sum_row =hfbi_non_life_table.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfbi_non_life_table = pd.concat([hfbi_non_life_table, sum_row], ignore_index = True)
hfbi_non_life_table= (pd.DataFrame(hfbi_non_life_table.iloc[-1]).T if not hfbi_non_life_table.empty else pd.DataFrame(columns=hfbi_non_life_table.columns))


# In[349]:


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
hfbi_present_months = [col for col in month_order if col in hfbi_non_life_table.columns]

for month in month_order:
    if  month not in hfbi_non_life_table.columns:
        hfbi_non_life_table[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

hfbi_non_life_table = hfbi_non_life_table[past_and_reporting_months]

hfbi_non_life_table


# #### hfdi_life


# In[350]:


hfdi_life_report = life_premiums_data[life_premiums_data['segment']=='PROPERTY']
hfdi_life_report.head() 

hfdi_non_life_report = non_life_premiums_data[non_life_premiums_data['segment']=='PROPERTY']
hfdi_non_life_report.head() 


# In[351]:


def hfdi_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfdi_life_premiums_table = hfdi_life_premiums(hfdi_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfdi_life_premiums_table


# In[ ]:





















# In[352]:


def hfdi_non_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfdi_non_life_premiums_table = hfdi_non_life_premiums(hfdi_non_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfdi_non_life_premiums_table


# #### merge the life and non-life subsidiaries table


# In[353]:


hfdi_non_life_premiums_table= (pd.DataFrame(hfdi_non_life_premiums_table.iloc[-1]).T if not hfdi_non_life_premiums_table.empty else pd.DataFrame(columns=hfdi_non_life_premiums_table.columns))
hfdi_non_life_premiums_table


# In[354]:


hfdi_life_premiums_table= (pd.DataFrame(hfdi_life_premiums_table.iloc[-1]).T if not hfdi_life_premiums_table.empty else pd.DataFrame(columns=hfdi_life_premiums_table.columns))
hfdi_life_premiums_table


# In[355]:


hfdi_non_life_premiums_table = hfdi_non_life_premiums_table.drop(columns={'branch_name','Total'})
hfdi_life_premiums_table = hfdi_life_premiums_table.drop(columns={'branch_name','Total'})


# In[356]:


hfdi_life_premiums_table


# In[357]:


subsidiaries_life_premiums_table= pd.concat([hfc_life_premiums,hfbi_life_table], axis =0)
subsidiaries_life_premiums_table= pd.concat([subsidiaries_life_premiums_table,hfdi_life_premiums_table], axis =0)
subsidiaries_life_premiums_table=subsidiaries_life_premiums_table.reset_index(drop=True)
subsidiaries_life_premiums_table['ytd_cumulative'] = subsidiaries_life_premiums_table.sum(axis=1)
subsidiaries_life_premiums_table


# In[358]:


subsidiaries_life_premiums_table_with_targets = pd.concat([subsidiaries_life_targets,subsidiaries_life_premiums_table],axis=1).fillna(0)
subsidiaries_life_premiums_table_with_targets = subsidiaries_life_premiums_table_with_targets.rename(columns={'annual_target_banca_life':'annual_targets',
'ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'})
subsidiaries_life_premiums_table_with_targets


# In[359]:


subsidiaries_life_premiums_table_with_targets = calculation_branch_formulas(subsidiaries_life_premiums_table_with_targets)
subsidiaries_life_premiums_table_with_targets = calculate_deficits(subsidiaries_life_premiums_table_with_targets,report_month)
subsidiaries_life_premiums_table_with_targets
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in subsidiaries_life_premiums_table_with_targets.columns]
# existing_months=present_months
column_order = ['SUBSIDIARY', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit','adjusted_annual_targets']

subsidiaries_life_premiums_table_with_targets= subsidiaries_life_premiums_table_with_targets[column_order]
# subsidiaries_life_premiums_table_with_targets
subsidiaries_life_premiums_table_with_targets_total_row= total_row(subsidiaries_life_premiums_table_with_targets)
subsidiaries_life_premiums_table_with_targets_total_row


# In[360]:


subsidiaries_non_life_premiums_table= pd.concat([hfc_non_life_premiums,hfbi_non_life_table], axis =0)
subsidiaries_non_life_premiums_table


# In[361]:


subsidiaries_non_life_premiums_table= pd.concat([subsidiaries_non_life_premiums_table,hfdi_non_life_premiums_table], axis =0)
subsidiaries_non_life_premiums_table=subsidiaries_non_life_premiums_table.reset_index(drop=True)
subsidiaries_non_life_premiums_table


# In[362]:


subsidiaries_non_life_premiums_table['ytd_cumulative'] = subsidiaries_non_life_premiums_table.sum(axis=1)
subsidiaries_non_life_premiums_table


# In[363]:


subsidiaries_non_life_premiums_table_with_targets = pd.concat([subsidiaries_non_life_targets,subsidiaries_non_life_premiums_table],axis=1).fillna(0)
subsidiaries_non_life_premiums_table_with_targets = subsidiaries_non_life_premiums_table_with_targets.rename(columns={'annual_target_banca_non_life':'annual_targets',
'ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'})
subsidiaries_non_life_premiums_table_with_targets


# In[364]:


subsidiaries_non_life_premiums_table_with_targets = calculation_branch_formulas(subsidiaries_non_life_premiums_table_with_targets)
subsidiaries_non_life_premiums_table_with_targets = calculate_deficits(subsidiaries_non_life_premiums_table_with_targets,report_month)
subsidiaries_non_life_premiums_table_with_targets
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in subsidiaries_non_life_premiums_table_with_targets.columns]
# existing_months=present_months
column_order = ['SUBSIDIARY', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit','adjusted_annual_targets']

subsidiaries_non_life_premiums_table_with_targets= subsidiaries_non_life_premiums_table_with_targets[column_order]
# subsidiaries_non_life_premiums_table_with_targets
subsidiaries_non_life_premiums_table_with_targets_total_row= total_row(subsidiaries_non_life_premiums_table_with_targets)
subsidiaries_non_life_premiums_table_with_targets_total_row


# In[ ]:





















# In[365]:


# #### subsidiaries- vic and non vic

# ##### hfc- vic and non-vic


# In[366]:


vic_life_premiums_report= vic_life_premiums_data[vic_life_premiums_data['rm'] == 'Operations']
vic_non_life_premiums_report= vic_non_life_premiums_data[vic_non_life_premiums_data['rm'] == 'Operations']


# In[367]:


def hfc_vic_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

operations_vic_life_premium_table = hfc_vic_life_premium(vic_life_premiums_report, month_column_name='month_name', index = 'rm',value_column_name = 'total_premiums')


operations_vic_life_premium_table


# In[368]:


# drop total row
hfc_vic_life_premium_table=(operations_vic_life_premium_table.drop(operations_vic_life_premium_table.index[-1]) if not operations_vic_life_premium_table.empty else operations_vic_life_premium_table.copy())
hfc_vic_life_premium_table

# get totals paid premiums from branches table
hfc_branch_vic_life_premium_table= pd.DataFrame(branch_vic_life_premium_table.iloc[-1]).T
hfc_branch_vic_life_premium_table.drop(columns={'branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score",'ytd_target','ytd_cumulative','ytd_score'}, inplace =True)
hfc_branch_vic_life_premium_table


# In[369]:


# concat operations and branch values
hfc_life_vic =pd.concat([hfc_branch_vic_life_premium_table, hfc_vic_life_premium_table], axis =0)
hfc_life_vic.drop(columns={'rank','Total','rm'},inplace=True)
hfc_life_vic

sum_row =hfc_life_vic.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfc_life_vic = pd.concat([hfc_life_vic, sum_row], ignore_index = True)


hfc_vic_life_premiums = hfc_life_vic.iloc[-1:]
hfc_vic_life_premiums = hfc_vic_life_premiums.astype(int)
hfc_vic_life_premiums


# In[370]:


def hfc_vic_non_life_premium(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt

operations_vic_non_life_premium_table = hfc_vic_non_life_premium(vic_non_life_premiums_report, month_column_name='month_name', index = 'rm',value_column_name = 'total_premiums')


operations_vic_non_life_premium_table


# In[371]:


# drop total row
hfc_vic_non_life_premium_table=(operations_vic_non_life_premium_table.drop(operations_vic_non_life_premium_table.index[-1]) if not operations_vic_non_life_premium_table.empty else operations_vic_non_life_premium_table.copy())
hfc_vic_non_life_premium_table

# get totals paid premiums from branches table
hfc_branch_vic_non_life_premium_table= pd.DataFrame(branch_vic_non_life_premium_table_with_branch_names.iloc[-1]).T
hfc_branch_vic_non_life_premium_table.drop(columns={'branch','annual_targets','monthly_targets','mtd_target','current_month_actuals',"current_month_score",
                                               'ytd_target','ytd_cumulative','ytd_score','target_banca_life', 'annual_target_banca_life','ytd_target_banca_life_calc', 'target_banca_value',
       'annual_target_banca_value', 'ytd_target_banca_value_calc','branch_name'}, inplace =True)
# hfc_branch_non_vic_premium_table_columns_to_keep =[ 


# In[372]:


hfc_branch_vic_non_life_premium_table.columns


# In[373]:


# hfc_vic_non_life


# In[374]:


# concat operations and branch values
hfc_vic_non_life =pd.concat([hfc_branch_vic_non_life_premium_table, hfc_vic_non_life_premium_table], axis =0)
hfc_vic_non_life.drop(columns={'Total','rm'},inplace=True)
hfc_vic_non_life

sum_row =hfc_vic_non_life.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfc_vic_non_life = pd.concat([hfc_vic_non_life, sum_row], ignore_index = True)


hfc_vic_non_life_premiums = hfc_vic_non_life.iloc[-1:]
hfc_vic_non_life_premiums = hfc_vic_non_life_premiums.astype(int)
hfc_vic_non_life_premiums


# In[375]:


# ##### hfbi - vic and non-vic


# In[376]:


# for getting values when rm is not Operations and branch name is HFBI
hfbi_vic_report = vic_premiums_data[(vic_premiums_data['rm'] != 'Operations') & (vic_premiums_data['branch_name']=='HFCB-BI')]
hfbi_vic_life_report = vic_life_premiums_data[(vic_life_premiums_data['rm'] != 'Operations') & (vic_life_premiums_data['branch_name']=='HFCB-BI')]
hfbi_vic_non_life_report = vic_non_life_premiums_data[(vic_non_life_premiums_data['rm'] != 'Operations') & (vic_non_life_premiums_data['branch_name']=='HFCB-BI')]
# hfbi_vic_report.head() 


# In[377]:


def hfbi_vic_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfbi_vic_premiums_table = hfbi_vic_premiums(hfbi_vic_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfbi_vic_premiums_table


# In[378]:


def hfbi_vic_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfbi_vic_life_premiums_table = hfbi_vic_life_premiums(hfbi_vic_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfbi_vic_life_premiums_table


# In[379]:


def hfbi_vic_non_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfbi_vic_non_life_premiums_table = hfbi_vic_non_life_premiums(hfbi_vic_non_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')
hfbi_vic_non_life_premiums_table


# In[380]:


hfbi_vic_premiums_table= (pd.DataFrame(hfbi_vic_premiums_table.iloc[-1]).T if not hfbi_vic_premiums_table.empty else pd.DataFrame(columns=hfbi_vic_premiums_table.columns))
hfbi_vic_premiums_table


# In[381]:


hfbi_vic_life_premiums_table= (pd.DataFrame(hfbi_vic_life_premiums_table.iloc[-1]).T if not hfbi_vic_life_premiums_table.empty else pd.DataFrame(columns=hfbi_vic_life_premiums_table.columns))
hfbi_vic_life_premiums_table


# In[382]:


hfbi_vic_non_life_premiums_table= (pd.DataFrame(hfbi_vic_non_life_premiums_table.iloc[-1]).T if not hfbi_vic_non_life_premiums_table.empty else pd.DataFrame(columns=hfbi_vic_non_life_premiums_table.columns))
hfbi_vic_non_life_premiums_table


# In[383]:


hfbi_vic_life_table =pd.concat([hfbi_vic_life_premiums_table, operations_vic_life_premium_table], axis =0, ignore_index=True)
hfbi_vic_life_table.drop(columns={'branch_name','Total','rm'},inplace=True)
hfbi_vic_life_table = hfbi_vic_life_table.T


# In[384]:


hfbi_vic_life_table= pd.concat([hfbi_vic_life_table,hfbi_life_additional_values], axis =1)
hfbi_vic_life_table= hfbi_vic_life_table.dropna()
hfbi_vic_life_table= hfbi_vic_life_table.T
hfbi_vic_life_table

#hfbi premiums calculation total
sum_row =hfbi_vic_life_table.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfbi_vic_life_table = pd.concat([hfbi_vic_life_table, sum_row], ignore_index = True)
hfbi_vic_life_table= (pd.DataFrame(hfbi_vic_life_table.iloc[-1]).T if not hfbi_vic_life_table.empty else pd.DataFrame(columns=hfbi_vic_life_table.columns))


# In[385]:


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
hfbi_present_months = [col for col in month_order if col in hfbi_vic_life_table.columns]

for month in month_order:
    if  month not in hfbi_vic_life_table.columns:
        hfbi_vic_life_table[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

hfbi_vic_life_table = hfbi_vic_life_table[past_and_reporting_months]

hfbi_vic_life_table


# In[ ]:





















# In[386]:


hfbi_non_vic_report = non_vic_premiums_data[(non_vic_premiums_data['rm'] != 'Operations') & (non_vic_premiums_data['branch_name']=='HFCB-BI')]


# In[387]:


# def hfbi_vic_premiums(dataframe, index, month_column_name, value_column_name):
#     premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
#     # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

#     current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
#     past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
#     if dataframe.empty:
#         return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
#     premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
#     premium_amt = premium_amt.fillna(0).reset_index()
          
  
#     for month in premium_month_order:
#         if  month not in premium_amt.columns:
#             premium_amt[month]=0
          
#     premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
#     premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
#     return premium_amt


# hfbi_non_vic_premiums_table = hfbi_non_vic_premiums(hfbi_vic_non_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

# hfbi_non_vic_premiums_table


# In[388]:


hfbi_vic_non_life_premiums_table= (pd.DataFrame(hfbi_vic_non_life_premiums_table.iloc[-1]).T if not hfbi_vic_non_life_premiums_table.empty else pd.DataFrame(columns=hfbi_vic_non_life_premiums_table.columns))
hfbi_vic_non_life_premiums_table


# In[389]:


hfbi_vic_non_life_table =pd.concat([hfbi_vic_non_life_premiums_table, operations_vic_non_life_premium_table], axis =0, ignore_index=True)
hfbi_vic_non_life_table.drop(columns={'branch_name','Total','rm'},inplace=True)
hfbi_vic_non_life_table = hfbi_vic_non_life_table.T


# In[390]:


hfbi_vic_non_life_table= pd.concat([hfbi_vic_non_life_table,hfbi_life_additional_values], axis =1)
hfbi_vic_non_life_table= hfbi_vic_non_life_table.dropna()
hfbi_vic_non_life_table= hfbi_vic_non_life_table.T
hfbi_vic_non_life_table

#hfbi premiums calculation total
sum_row =hfbi_vic_non_life_table.iloc[:,:].sum()
sum_row = pd.DataFrame(sum_row).T

hfbi_vic_non_life_table = pd.concat([hfbi_vic_non_life_table, sum_row], ignore_index = True)
hfbi_vic_non_life_table= (pd.DataFrame(hfbi_vic_non_life_table.iloc[-1]).T if not hfbi_vic_non_life_table.empty else pd.DataFrame(columns=hfbi_vic_non_life_table.columns))


# In[391]:


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
hfbi_present_months = [col for col in month_order if col in hfbi_vic_non_life_table.columns]

for month in month_order:
    if  month not in hfbi_vic_non_life_table.columns:
        hfbi_vic_non_life_table[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

hfbi_vic_non_life_table = hfbi_vic_non_life_table[past_and_reporting_months]

hfbi_vic_non_life_table


# ##### hfdi - vic and non-vic


# In[392]:


hfdi_vic_life_report = vic_life_premiums_data[vic_life_premiums_data['segment']=='PROPERTY']
hfdi_vic_life_report.head() 


# In[393]:


hfdi_vic_non_life_report = vic_non_life_premiums_data[vic_non_life_premiums_data['segment']=='PROPERTY']
hfdi_vic_non_life_report.head() 


# In[394]:


def hfdi_vic_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfdi_vic_life_premiums_table = hfdi_vic_life_premiums(hfdi_vic_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfdi_vic_life_premiums_table


# In[395]:


hfdi_vic_life_premiums_table= (pd.DataFrame(hfdi_vic_life_premiums_table.iloc[-1]).T if not hfdi_vic_life_premiums_table.empty else pd.DataFrame(columns=hfdi_vic_life_premiums_table.columns))
hfdi_vic_life_premiums_table


# In[396]:


hfdi_vic_life_premiums_table = hfdi_vic_life_premiums_table.drop(columns={'branch_name','Total'})


# In[397]:


def hfdi_vic_non_life_premiums(dataframe, index, month_column_name, value_column_name):
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in premium_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    premium_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    premium_amt = premium_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in premium_amt.columns:
            premium_amt[month]=0
          
    premium_amt['Total'] = premium_amt[past_and_reporting_months].sum(axis=1)                          
    premium_amt =premium_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return premium_amt


hfdi_vic_non_life_premiums_table = hfdi_vic_non_life_premiums(hfdi_vic_non_life_report, month_column_name='month_name', index='branch_name',  value_column_name='paid_premiums')

hfdi_vic_non_life_premiums_table


# #### merge the subsidiaries vic and non vic tables


# In[398]:


hfdi_vic_non_life_premiums_table = hfdi_vic_non_life_premiums_table.drop(columns={'branch_name','Total'})


# In[399]:


hfdi_vic_non_life_premiums_table= (pd.DataFrame(hfdi_vic_non_life_premiums_table.iloc[-1]).T if not hfdi_vic_non_life_premiums_table.empty else pd.DataFrame(columns=hfdi_vic_non_life_premiums_table.columns))
hfdi_vic_non_life_premiums_table


# In[400]:


subsidiaries_vic_life_premiums_table= pd.concat([hfc_vic_life_premiums,hfbi_vic_life_table], axis =0)
subsidiaries_vic_life_premiums_table= pd.concat([subsidiaries_vic_life_premiums_table,hfdi_vic_life_premiums_table], axis =0)
subsidiaries_vic_life_premiums_table=subsidiaries_vic_life_premiums_table.reset_index(drop=True)
subsidiaries_vic_life_premiums_table['ytd_cumulative'] = subsidiaries_vic_life_premiums_table.sum(axis=1)
subsidiaries_vic_life_premiums_table


# In[401]:


# using same targets as life and non life targets(70:30 ratio)

subsidiaries_vic_life_premiums_table_with_targets = pd.concat([subsidiaries_vic_life_targets,subsidiaries_vic_life_premiums_table],axis=1).fillna(0)
subsidiaries_vic_life_premiums_table_with_targets = subsidiaries_vic_life_premiums_table_with_targets.rename(columns={'annual_target_banca_life':'annual_targets','ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'})
subsidiaries_vic_life_premiums_table_with_targets


# In[402]:


subsidiaries_vic_life_premiums_table_with_targets = calculation_branch_formulas_no_capping(subsidiaries_vic_life_premiums_table_with_targets)
subsidiaries_vic_life_premiums_table_with_targets = calculate_deficits(subsidiaries_vic_life_premiums_table_with_targets,report_month)
subsidiaries_vic_life_premiums_table_with_targets
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in subsidiaries_vic_life_premiums_table_with_targets.columns]
# existing_months=present_months
column_order = ['SUBSIDIARY', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit','adjusted_annual_targets']

subsidiaries_vic_life_premiums_table_with_targets= subsidiaries_vic_life_premiums_table_with_targets[column_order]
# subsidiaries_vic_life_premiums_table_with_targets
subsidiaries_vic_life_premiums_table_with_targets_total_row= uncapped_total_row(subsidiaries_vic_life_premiums_table_with_targets)
subsidiaries_vic_life_premiums_table_with_targets_total_row


# In[ ]:





















# In[403]:


subsidiaries_vic_non_life_premiums_table= pd.concat([hfc_vic_non_life_premiums,hfbi_vic_non_life_table], axis =0)
subsidiaries_vic_non_life_premiums_table


# In[404]:


subsidiaries_vic_non_life_premiums_table= pd.concat([subsidiaries_vic_non_life_premiums_table,hfdi_vic_non_life_premiums_table], axis =0)
subsidiaries_vic_non_life_premiums_table=subsidiaries_vic_non_life_premiums_table.reset_index(drop=True)
subsidiaries_vic_non_life_premiums_table['ytd_cumulative'] = subsidiaries_vic_non_life_premiums_table.sum(axis=1)
subsidiaries_vic_non_life_premiums_table


# In[405]:


subsidiaries_vic_non_life_premiums_table_with_targets = pd.concat([subsidiaries_vic_non_life_targets,subsidiaries_vic_non_life_premiums_table],axis=1).fillna(0)
subsidiaries_vic_non_life_premiums_table_with_targets = subsidiaries_vic_non_life_premiums_table_with_targets.rename(columns={'annual_target_banca_non_life':'annual_targets','ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'})
subsidiaries_vic_non_life_premiums_table_with_targets


# In[406]:


# subsidiaries_vic_non_life_premiums_table_with_targets.columns


# In[407]:


subsidiaries_vic_non_life_premiums_table_with_targets = calculation_branch_formulas_no_capping(subsidiaries_vic_non_life_premiums_table_with_targets)
subsidiaries_vic_non_life_premiums_table_with_targets = calculate_deficits(subsidiaries_vic_non_life_premiums_table_with_targets,report_month)
subsidiaries_vic_non_life_premiums_table_with_targets
month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in subsidiaries_vic_non_life_premiums_table_with_targets.columns]
# existing_months=present_months
column_order = ['SUBSIDIARY', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit','adjusted_annual_targets']

subsidiaries_vic_non_life_premiums_table_with_targets= subsidiaries_vic_non_life_premiums_table_with_targets[column_order]
# subsidiaries_vic_non_life_premiums_table_with_targets
subsidiaries_vic_non_life_premiums_table_with_targets_total_row= uncapped_total_row(subsidiaries_vic_non_life_premiums_table_with_targets)
subsidiaries_vic_non_life_premiums_table_with_targets_total_row


# In[408]:


analysis_columns_to_keep = ['branch','ytd_target','ytd_cumulative']
branch_chart_ytd_values = branch_premium_table[analysis_columns_to_keep]


# ## Segment tables


# In[409]:


def paid_premiums_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_premium_amt = segment_premium_amt.fillna(0)
    segment_premium_amt = segment_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in segment_premium_amt.columns]

    for month in premium_month_order:
        if  month not in segment_premium_amt.columns:
            segment_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_premium_amt = segment_premium_amt[[index] + past_and_reporting_months +['Total']]

    segment_premium_amt['Total'] = segment_premium_amt[past_and_reporting_months].sum(axis=1)
    return segment_premium_amt



segments_paid_premiums_table = paid_premiums_by_segment(filtered_sales_report, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')

segments_paid_premiums_table


# In[410]:


value_to_remove = ['BI(ALL)']

segments_paid_premiums_table = segments_paid_premiums_table[~segments_paid_premiums_table['segment_2'].isin(value_to_remove)]


# In[411]:


hfbi_additional_values = hfbi_additional_values.T
hfbi_installed_britam_medical_values = hfbi_installed_britam_medical_values.T
hfbi_sales_britam_medical_values = hfbi_sales_britam_medical_values.T
hfbi_total_britam_medical_values = hfbi_total_britam_medical_values.T
hfbi_fire_bbb_companyassets_additional_values = hfbi_fire_bbb_companyassets_additional_values.T
hfbi_fire_bbb_companyassets_additional_values


# In[412]:


month_columns = hfbi_additional_values.columns

for col in month_columns:
    if col not in segments_paid_premiums_table.columns:
        segments_paid_premiums_table[col] = 0


values_to_add = hfbi_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()


# Add only to BI INSTALLED segment
segments_paid_premiums_table.loc[
    segments_paid_premiums_table["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values
# segments_paid_premiums_table.loc[
#     segments_paid_premiums_table["segment_2"] == "BI INSTALLED",
#     month_columns
# ] += installed_britam_values_to_add.values
segments_paid_premiums_table.loc[
    segments_paid_premiums_table["segment_2"] == "BI SALES",
    month_columns
] += sales_britam_values_to_add.values

# Recalculate total
segments_paid_premiums_table["Total"] = (
    segments_paid_premiums_table[month_columns].sum(axis=1)
)
segments_paid_premiums_table


# In[413]:


segments_paid_premiums_table_with_targets = pd.merge(segment_targets,segments_paid_premiums_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segments_paid_premiums_table_with_targets = segments_paid_premiums_table_with_targets.drop(columns={'annual_target_banca_life','segment_2'})
segments_paid_premiums_table_with_targets = segments_paid_premiums_table_with_targets.rename(columns={'annual_target_banca_value':'annual_targets',
                                                                                                      'Total':'ytd_cumulative','ytd_target_banca_value_calc':'ytd_target',
                                                                                                      'target_banca_value':'monthly_targets'})

segments_paid_premiums_table_with_targets = calculation_segment_formulas(segments_paid_premiums_table_with_targets)
segments_paid_premiums_table_with_targets = calculate_deficits(segments_paid_premiums_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_paid_premiums_table_with_targets.columns]

for month in month_order:
    if  month not in segments_paid_premiums_table_with_targets.columns:
        segments_paid_premiums_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]


# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_paid_premiums_table_with_targets= segments_paid_premiums_table_with_targets[column_order]
# segment_life_table_with_targets
segments_paid_premiums_table_with_targets= total_row_less_ib(segments_paid_premiums_table_with_targets)
segments_paid_premiums_table_with_targets


# In[414]:


vic_data_sales_report =filtered_sales_report[filtered_sales_report['vic_check']=='vic']


# In[ ]:















# In[415]:


def total_vic_premiums_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_premium_amt = segment_premium_amt.fillna(0)
    segment_premium_amt = segment_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in segment_premium_amt.columns]

    for month in premium_month_order:
        if  month not in segment_premium_amt.columns:
            segment_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_premium_amt = segment_premium_amt[[index] + past_and_reporting_months +['Total']]

    segment_premium_amt['Total'] = segment_premium_amt[past_and_reporting_months].sum(axis=1)
    return segment_premium_amt

segments_total_vic_premiums_table = total_vic_premiums_by_segment(vic_data_sales_report, month_column_name='month_name', index='segment_2',  value_column_name='total_premiums')

segments_total_vic_premiums_table


# In[416]:


segments_total_vic_premiums_table_with_split_britam_medical_values = segments_total_vic_premiums_table.copy()


# In[417]:


def paid_vic_premiums_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_premium_amt = segment_premium_amt.fillna(0)
    segment_premium_amt = segment_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in segment_premium_amt.columns]

    for month in premium_month_order:
        if  month not in segment_premium_amt.columns:
            segment_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_premium_amt = segment_premium_amt[[index] + past_and_reporting_months +['Total']]

    segment_premium_amt['Total'] = segment_premium_amt[past_and_reporting_months].sum(axis=1)
    return segment_premium_amt

segments_paid_vic_premiums_table = paid_vic_premiums_by_segment(vic_data_sales_report, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')

segments_paid_vic_premiums_table


# In[418]:


segments_paid_vic_premiums_table_with_split_britam_values = segments_paid_vic_premiums_table.copy()


# In[419]:


def total_premiums_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_premium_amt = segment_premium_amt.fillna(0)
    segment_premium_amt = segment_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in segment_premium_amt.columns]

    for month in premium_month_order:
        if  month not in segment_premium_amt.columns:
            segment_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_premium_amt = segment_premium_amt[[index] + past_and_reporting_months +['Total']]

    segment_premium_amt['Total'] = segment_premium_amt[past_and_reporting_months].sum(axis=1)
    return segment_premium_amt

segments_total_premiums_table = total_premiums_by_segment(filtered_sales_report, month_column_name='month_name', index='segment_2',  value_column_name='total_premiums')

segments_total_premiums_table


# In[420]:


segments_total_premiums_table_with_split_britam_values = segments_total_premiums_table.copy()


# In[421]:


month_columns = hfbi_additional_values.columns


for col in month_columns:
    if col not in segments_total_premiums_table.columns:
        segments_total_premiums_table[col] = 0


values_to_add = hfbi_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_total_premiums_table.loc[
    segments_total_premiums_table["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values
# segments_total_premiums_table.loc[
#     segments_total_premiums_table["segment_2"] == "BI INSTALLED",
#     month_columns
# ] += installed_britam_values_to_add.values
segments_total_premiums_table.loc[
    segments_total_premiums_table["segment_2"] == "BI SALES",
    month_columns
] += sales_britam_values_to_add.values

# Recalculate total
segments_total_premiums_table["Total"] = (
    segments_total_premiums_table[month_columns].sum(axis=1)
)
# segments_total_premiums_table


# In[ ]:











# In[422]:


month_columns = hfbi_additional_values.columns


for col in month_columns:
    if col not in segments_total_vic_premiums_table_with_split_britam_medical_values.columns:
        segments_total_vic_premiums_table_with_split_britam_medical_values[col] = 0


values_to_add = hfbi_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()

# Add only to HFBI segmentS
segments_total_vic_premiums_table_with_split_britam_medical_values.loc[
    segments_total_vic_premiums_table_with_split_britam_medical_values["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values
# segments_total_vic_premiums_table_with_split_britam_medical_values.loc[
#     segments_total_vic_premiums_table_with_split_britam_medical_values["segment_2"] == "BI INSTALLED",
#     month_columns
# ] += installed_britam_values_to_add.values
segments_total_vic_premiums_table_with_split_britam_medical_values.loc[
    segments_total_vic_premiums_table_with_split_britam_medical_values["segment_2"] == "BI SALES",
    month_columns
] += sales_britam_values_to_add.values


# Recalculate total
segments_total_vic_premiums_table_with_split_britam_medical_values["Total"] = (
    segments_total_vic_premiums_table_with_split_britam_medical_values[month_columns].sum(axis=1)
)
# segments_total_premiums_table




# In[423]:


month_columns = hfbi_additional_values.columns


for col in month_columns:
    if col not in segments_total_vic_premiums_table.columns:
        segments_total_vic_premiums_table[col] = 0


values_to_add = hfbi_additional_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()

total_britam_values_to_add = hfbi_total_britam_medical_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_total_vic_premiums_table.loc[
    segments_total_vic_premiums_table["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values
segments_total_vic_premiums_table.loc[
    segments_total_vic_premiums_table["segment_2"] == "BI INSTALLED",
    month_columns
] += total_britam_values_to_add.values

# Recalculate total
segments_total_vic_premiums_table["Total"] = (
    segments_total_vic_premiums_table[month_columns].sum(axis=1)
)
# segments_total_premiums_table


# In[424]:


month_columns = hfbi_additional_values.columns


for col in month_columns:
    if col not in segments_paid_vic_premiums_table_with_split_britam_values.columns:
        segments_paid_vic_premiums_table_with_split_britam_values[col] = 0


values_to_add = hfbi_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_paid_vic_premiums_table_with_split_britam_values.loc[
    segments_paid_vic_premiums_table_with_split_britam_values["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values
# segments_paid_vic_premiums_table_with_split_britam_values.loc[
#     segments_paid_vic_premiums_table_with_split_britam_values["segment_2"] == "BI INSTALLED",
#     month_columns
# ] += installed_britam_values_to_add.values
segments_paid_vic_premiums_table_with_split_britam_values.loc[
    segments_paid_vic_premiums_table_with_split_britam_values["segment_2"] == "BI SALES",
    month_columns
] += sales_britam_values_to_add.values

# Recalculate total
segments_paid_vic_premiums_table_with_split_britam_values["Total"] = (
    segments_paid_vic_premiums_table_with_split_britam_values[month_columns].sum(axis=1)
)





# In[425]:


month_columns = hfbi_additional_values.columns


for col in month_columns:
    if col not in segments_paid_vic_premiums_table.columns:
        segments_paid_vic_premiums_table[col] = 0


values_to_add = hfbi_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
total_britam_values_to_add = hfbi_total_britam_medical_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_paid_vic_premiums_table.loc[
    segments_paid_vic_premiums_table["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values
segments_paid_vic_premiums_table.loc[
    segments_paid_vic_premiums_table["segment_2"] == "BI INSTALLED",
    month_columns
] += total_britam_values_to_add.values

# Recalculate total
segments_paid_vic_premiums_table["Total"] = (
    segments_paid_vic_premiums_table[month_columns].sum(axis=1)
)





# In[ ]:











# In[426]:


segments_total_premiums_table_with_targets = pd.merge(segment_targets,segments_total_premiums_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segments_total_premiums_table_with_targets = segments_total_premiums_table_with_targets.drop(columns={'annual_target_banca_life','segment_2'})
segments_total_premiums_table_with_targets = segments_total_premiums_table_with_targets.rename(columns={'annual_target_banca_value':'annual_targets',
                                                                                                      'Total':'ytd_cumulative','ytd_target_banca_value_calc':'ytd_target',
                                                                                                      'target_banca_value':'monthly_targets'})

segments_total_premiums_table_with_targets = calculation_segment_formulas(segments_total_premiums_table_with_targets)
segments_total_premiums_table_with_targets = calculate_deficits(segments_total_premiums_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_total_premiums_table_with_targets.columns]


for month in month_order:
    if  month not in segments_total_premiums_table_with_targets.columns:
        segments_total_premiums_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]




# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_total_premiums_table_with_targets= segments_total_premiums_table_with_targets[column_order]
# segment_life_table_with_targets
segments_total_premiums_table_with_targets= total_row_less_ib(segments_total_premiums_table_with_targets)
segments_total_premiums_table_with_targets


# In[427]:


segments_total_vic_premiums_table_with_split_britam_medical_values


# In[428]:


segments_vic_total_premiums_table_with_targets = pd.merge(segment_vic_targets,segments_total_vic_premiums_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segments_vic_total_premiums_table_with_targets = segments_vic_total_premiums_table_with_targets.drop(columns={'annual_target_banca_life','segment_2'})
segments_vic_total_premiums_table_with_targets = segments_vic_total_premiums_table_with_targets.rename(columns={'annual_target_banca_value':'annual_targets',
                                                                                                      'Total':'ytd_cumulative','ytd_target_banca_value_calc':'ytd_target',
                                                                                                      'target_banca_value':'monthly_targets'})

segments_vic_total_premiums_table_with_targets = calculation_segment_formulas_without_capping(segments_vic_total_premiums_table_with_targets)
segments_vic_total_premiums_table_with_targets = calculate_deficits(segments_vic_total_premiums_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_total_premiums_table_with_targets.columns]


for month in month_order:
    if  month not in segments_vic_total_premiums_table_with_targets.columns:
        segments_vic_total_premiums_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]




# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_total_premiums_table_with_targets= segments_vic_total_premiums_table_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_total_premiums_table_with_targets= uncapped_total_row_less_ib(segments_vic_total_premiums_table_with_targets)
segments_vic_total_premiums_table_with_targets


# In[429]:


segments_vic_total_premiums_table_with_added_britam_medical_with_targets = pd.merge(segment_vic_targets,segments_total_vic_premiums_table_with_split_britam_medical_values,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segments_vic_total_premiums_table_with_added_britam_medical_with_targets = segments_vic_total_premiums_table_with_added_britam_medical_with_targets.drop(columns={'annual_target_banca_life','segment_2'})
segments_vic_total_premiums_table_with_added_britam_medical_with_targets = segments_vic_total_premiums_table_with_added_britam_medical_with_targets.rename(columns={'annual_target_banca_value':'annual_targets',
                                                                                                      'Total':'ytd_cumulative','ytd_target_banca_value_calc':'ytd_target',
                                                                                                      'target_banca_value':'monthly_targets'})

segments_vic_total_premiums_table_with_added_britam_medical_with_targets = calculation_segment_formulas_without_capping(segments_vic_total_premiums_table_with_added_britam_medical_with_targets)
segments_vic_total_premiums_table_with_added_britam_medical_with_targets = calculate_deficits(segments_vic_total_premiums_table_with_added_britam_medical_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_total_premiums_table_with_added_britam_medical_with_targets.columns]


for month in month_order:
    if  month not in segments_vic_total_premiums_table_with_added_britam_medical_with_targets.columns:
        segments_vic_total_premiums_table_with_added_britam_medical_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]




# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_total_premiums_table_with_added_britam_medical_with_targets= segments_vic_total_premiums_table_with_added_britam_medical_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_total_premiums_table_with_added_britam_medical_with_targets= uncapped_total_row_less_ib(segments_vic_total_premiums_table_with_added_britam_medical_with_targets)
segments_vic_total_premiums_table_with_added_britam_medical_with_targets


# In[430]:


segments_vic_paid_premiums_table_with_added_britam_with_targets = pd.merge(segment_vic_targets,segments_paid_vic_premiums_table_with_split_britam_values,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segments_vic_paid_premiums_table_with_added_britam_with_targets = segments_vic_paid_premiums_table_with_added_britam_with_targets.drop(columns={'annual_target_banca_life','segment_2'})
segments_vic_paid_premiums_table_with_added_britam_with_targets = segments_vic_paid_premiums_table_with_added_britam_with_targets.rename(columns={'annual_target_banca_value':'annual_targets',
                                                                                                      'Total':'ytd_cumulative','ytd_target_banca_value_calc':'ytd_target',
                                                                                                      'target_banca_value':'monthly_targets'})

segments_vic_paid_premiums_table_with_added_britam_with_targets = calculation_segment_formulas_without_capping(segments_vic_paid_premiums_table_with_added_britam_with_targets)
segments_vic_paid_premiums_table_with_added_britam_with_targets = calculate_deficits(segments_vic_paid_premiums_table_with_added_britam_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_paid_premiums_table_with_added_britam_with_targets.columns]


for month in month_order:
    if  month not in segments_vic_paid_premiums_table_with_added_britam_with_targets.columns:
        segments_vic_paid_premiums_table_with_added_britam_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]




# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_paid_premiums_table_with_added_britam_with_targets= segments_vic_paid_premiums_table_with_added_britam_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_paid_premiums_table_with_added_britam_with_targets= uncapped_total_row_less_ib(segments_vic_paid_premiums_table_with_added_britam_with_targets)
segments_vic_paid_premiums_table_with_added_britam_with_targets


# In[431]:


segments_vic_paid_premiums_table_with_targets = pd.merge(segment_vic_targets,segments_paid_vic_premiums_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segments_vic_paid_premiums_table_with_targets = segments_vic_paid_premiums_table_with_targets.drop(columns={'annual_target_banca_life','segment_2'})
segments_vic_paid_premiums_table_with_targets = segments_vic_paid_premiums_table_with_targets.rename(columns={'annual_target_banca_value':'annual_targets',
                                                                                                      'Total':'ytd_cumulative','ytd_target_banca_value_calc':'ytd_target',
                                                                                                      'target_banca_value':'monthly_targets'})

segments_vic_paid_premiums_table_with_targets = calculation_segment_formulas_without_capping(segments_vic_paid_premiums_table_with_targets)
segments_vic_paid_premiums_table_with_targets = calculate_deficits(segments_vic_paid_premiums_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_paid_premiums_table_with_targets.columns]


for month in month_order:
    if  month not in segments_vic_paid_premiums_table_with_targets.columns:
        segments_vic_paid_premiums_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]




# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_paid_premiums_table_with_targets= segments_vic_paid_premiums_table_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_paid_premiums_table_with_targets= uncapped_total_row_less_ib(segments_vic_paid_premiums_table_with_targets)
segments_vic_paid_premiums_table_with_targets


# In[432]:


def sum_undefined(dataframe, index, column_name, value_column_name):
    amt = pd.pivot_table(dataframe, index = index, columns = column_name, values = value_column_name, aggfunc = 'sum')
    amt = amt.fillna(0)
    amt = amt.reset_index()
    return amt 


# In[433]:


weekly_paid_premiums = filtered_sales_report[filtered_sales_report['month_name'] == max_month_name].copy()


# In[434]:


weekly_paid_premiums.head(1)


# In[435]:


weekly_vic_paid_premiums = filtered_sales_report[(filtered_sales_report['month_name'] == max_month_name)& (filtered_sales_report['vic_check']=='vic')].copy()


# In[436]:


segemnt_2_columns_to_keep= ['SEGMENT']
segment_2_names= segment_vic_targets[segemnt_2_columns_to_keep]
segment_2_names


# In[437]:


weekly_segment_paid_premiums_table = sum_undefined(weekly_paid_premiums, index = 'segment_2', column_name = 'week_month', value_column_name = 'paid_premiums')
weekly_segment_paid_premiums_table = pd.merge(segment_2_names,weekly_segment_paid_premiums_table, left_on ='SEGMENT',right_on ='segment_2', how = 'left')
weekly_segment_paid_premiums_table = weekly_segment_paid_premiums_table.fillna(0)
weekly_segment_paid_premiums_table = weekly_segment_paid_premiums_table.drop(columns ='segment_2')
weekly_segment_paid_premiums_total_row = weekly_segment_paid_premiums_table.sum(numeric_only =True)
weekly_segment_paid_premiums_total_row = pd.DataFrame(weekly_segment_paid_premiums_total_row).T
weekly_segment_paid_premiums_table = pd.concat([weekly_segment_paid_premiums_table,weekly_segment_paid_premiums_total_row], ignore_index=True)

weekly_segment_paid_premiums_table


# In[438]:


weekly_segment_vic_paid_premiums_table = sum_undefined(weekly_vic_paid_premiums, index = 'segment_2', column_name = 'week_month', value_column_name = 'paid_premiums')
weekly_segment_vic_paid_premiums_table = pd.merge(segment_2_names,weekly_segment_vic_paid_premiums_table, left_on ='SEGMENT',right_on ='segment_2', how = 'left')
weekly_segment_vic_paid_premiums_table = weekly_segment_vic_paid_premiums_table.fillna(0)
weekly_segment_vic_paid_premiums_table = weekly_segment_vic_paid_premiums_table.drop(columns ='segment_2')
weekly_segment_vic_paid_premiums_total_row = weekly_segment_vic_paid_premiums_table.sum(numeric_only =True)
weekly_segment_vic_paid_premiums_total_row = pd.DataFrame(weekly_segment_vic_paid_premiums_total_row).T
weekly_segment_vic_paid_premiums_table = pd.concat([weekly_segment_vic_paid_premiums_table,weekly_segment_vic_paid_premiums_total_row], ignore_index=True)
weekly_segment_vic_paid_premiums_table


# In[439]:


weekly_segment_revenue_table = sum_undefined(weekly_paid_premiums, index = 'segment_2', column_name = 'week_month', value_column_name = 'commission')
weekly_segment_revenue_table = pd.merge(segment_2_names,weekly_segment_revenue_table, left_on ='SEGMENT',right_on ='segment_2', how = 'left')
weekly_segment_revenue_table = weekly_segment_revenue_table.fillna(0)
weekly_segment_revenue_table = weekly_segment_revenue_table.drop(columns ='segment_2')
weekly_segment_revenue_table


# In[ ]:









# In[440]:


weekly_segment_revenue_table_total_row = weekly_segment_revenue_table.sum(numeric_only =True)
weekly_segment_revenue_table_total_row = pd.DataFrame(weekly_segment_revenue_table_total_row).T
weekly_segment_revenue_table = pd.concat([weekly_segment_revenue_table,weekly_segment_revenue_table_total_row], ignore_index=True)
weekly_segment_revenue_table


# In[441]:


weekly_vic_segment_revenue_table = sum_undefined(weekly_vic_paid_premiums, index = 'segment_2', column_name = 'week_month', value_column_name = 'commission')
weekly_vic_segment_revenue_table = pd.merge(segment_2_names,weekly_vic_segment_revenue_table, left_on ='SEGMENT',right_on ='segment_2', how = 'left')
weekly_vic_segment_revenue_table = weekly_vic_segment_revenue_table.fillna(0)
weekly_vic_segment_revenue_table = weekly_vic_segment_revenue_table.drop(columns ='segment_2')
weekly_vic_segment_revenue_table


# In[442]:


weekly_vic_segment_revenue_table_total_row = weekly_vic_segment_revenue_table.sum(numeric_only =True)
weekly_vic_segment_revenue_table_total_row = pd.DataFrame(weekly_vic_segment_revenue_table_total_row).T
weekly_vic_segment_revenue_table = pd.concat([weekly_vic_segment_revenue_table,weekly_vic_segment_revenue_table_total_row], ignore_index=True)
weekly_vic_segment_revenue_table


# In[443]:


weekly_roles_paid_premiums_table = sum_undefined(weekly_paid_premiums, index = 'staff_role', column_name = 'week_month', value_column_name = 'paid_premiums')
weekly_roles_paid_premiums_table_total_row = weekly_roles_paid_premiums_table.sum(numeric_only =True)
weekly_roles_paid_premiums_table_total_row = pd.DataFrame(weekly_roles_paid_premiums_table_total_row).T
weekly_roles_paid_premiums_table = pd.concat([weekly_roles_paid_premiums_table,weekly_roles_paid_premiums_table_total_row], ignore_index=True)
weekly_roles_paid_premiums_table


# In[444]:


weekly_roles_vic_paid_premiums_table = sum_undefined(weekly_vic_paid_premiums, index = 'staff_role', column_name = 'week_month', value_column_name = 'paid_premiums')
weekly_roles_vic_paid_premiums_table_total_row = weekly_roles_vic_paid_premiums_table.sum(numeric_only =True)
weekly_roles_vic_paid_premiums_table_total_row = pd.DataFrame(weekly_roles_vic_paid_premiums_table_total_row).T
weekly_roles_vic_paid_premiums_table = pd.concat([weekly_roles_vic_paid_premiums_table,weekly_roles_vic_paid_premiums_table_total_row], ignore_index=True)
weekly_roles_vic_paid_premiums_table


# In[445]:


weekly_roles_revenue_table = sum_undefined(weekly_paid_premiums, index = 'staff_role', column_name = 'week_month', value_column_name = 'commission')
weekly_roles_revenue_table_total_row = weekly_roles_revenue_table.sum(numeric_only =True)
weekly_roles_revenue_table_total_row = pd.DataFrame(weekly_roles_revenue_table_total_row).T
weekly_roles_revenue_table = pd.concat([weekly_roles_revenue_table,weekly_roles_revenue_table_total_row], ignore_index=True)
weekly_roles_revenue_table


# In[446]:


weekly_roles_vic_revenue_table = sum_undefined(weekly_vic_paid_premiums, index = 'staff_role', column_name = 'week_month', value_column_name = 'commission')
weekly_roles_vic_revenue_table_total_row = weekly_roles_vic_revenue_table.sum(numeric_only =True)
weekly_roles_vic_revenue_table_total_row = pd.DataFrame(weekly_roles_vic_revenue_table_total_row).T
weekly_roles_vic_revenue_table = pd.concat([weekly_roles_vic_revenue_table,weekly_roles_vic_revenue_table_total_row], ignore_index=True)
weekly_roles_vic_revenue_table


# In[447]:


def revenue_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_comm_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_comm_amt = segment_comm_amt.fillna(0)
    segment_comm_amt = segment_comm_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in segment_comm_amt.columns]

    for month in comm_month_order:
        if  month not in segment_comm_amt.columns:
            segment_comm_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_comm_amt = segment_comm_amt[[index] + past_and_reporting_months +['Total']]

    segment_comm_amt['Total'] = segment_comm_amt[past_and_reporting_months].sum(axis=1)
    return segment_comm_amt



segments_revenue_table = revenue_by_segment(filtered_sales_report, month_column_name='month_name', index='segment_2',  value_column_name='commission')

segments_revenue_table


# In[448]:


def non_vic_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_non_vic_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_non_vic_amt = segment_non_vic_amt.fillna(0)
    segment_non_vic_amt = segment_non_vic_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in segment_non_vic_amt.columns]

    for month in comm_month_order:
        if  month not in segment_non_vic_amt.columns:
            segment_non_vic_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_non_vic_amt = segment_non_vic_amt[[index] + past_and_reporting_months +['Total']]

    segment_non_vic_amt['Total'] = segment_non_vic_amt[past_and_reporting_months].sum(axis=1)
    return segment_non_vic_amt



segments_non_vic_table = non_vic_by_segment(non_vic_premiums_data, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')

segments_non_vic_table


# In[449]:


def vic_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_vic_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_vic_amt = segment_vic_amt.fillna(0)
    segment_vic_amt = segment_vic_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in segment_vic_amt.columns]

    for month in comm_month_order:
        if  month not in segment_vic_amt.columns:
            segment_vic_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_vic_amt = segment_vic_amt[[index] + past_and_reporting_months +['Total']]

    segment_vic_amt['Total'] = segment_vic_amt[past_and_reporting_months].sum(axis=1)
    return segment_vic_amt



segments_vic_table = vic_by_segment(vic_premiums_data, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')

segments_vic_table


# ## Role summary


# In[450]:


def vic_life_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_vic_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_vic_amt = segment_vic_amt.fillna(0)
    segment_vic_amt = segment_vic_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in segment_vic_amt.columns]

    for month in comm_month_order:
        if  month not in segment_vic_amt.columns:
            segment_vic_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_vic_amt = segment_vic_amt[[index] + past_and_reporting_months +['Total']]

    segment_vic_amt['Total'] = segment_vic_amt[past_and_reporting_months].sum(axis=1)
    return segment_vic_amt



segments_vic_life_table = vic_life_by_segment(vic_life_premiums_data, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')

segments_vic_life_table




# In[451]:


# segments_vic_life_table_with_split_britam = segments_vic_life_table.copy()


# In[452]:


hfbi_life_additional_values = hfbi_life_additional_values.T

month_columns = hfbi_life_additional_values.columns


for col in month_columns:
    if col not in segments_vic_life_table.columns:
        segments_vic_life_table[col] = 0


values_to_add = hfbi_life_additional_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_vic_life_table.loc[
    segments_vic_life_table["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values

# Recalculate total
segments_vic_life_table["Total"] = (
    segments_vic_life_table[month_columns].sum(axis=1)
)
segments_vic_life_table




# In[ ]:











# In[ ]:











# In[ ]:











# In[453]:


def vic_non_life_by_segment (dataframe, index, month_column_name, value_column_name):
    segment_vic_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    segment_vic_amt = segment_vic_amt.fillna(0)
    segment_vic_amt = segment_vic_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in segment_vic_amt.columns]

    for month in comm_month_order:
        if  month not in segment_vic_amt.columns:
            segment_vic_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    segment_vic_amt = segment_vic_amt[[index] + past_and_reporting_months +['Total']]

    segment_vic_amt['Total'] = segment_vic_amt[past_and_reporting_months].sum(axis=1)
    return segment_vic_amt



segments_vic_non_life_table = vic_non_life_by_segment(vic_non_life_premiums_data, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')

segments_vic_non_life_table




# In[454]:


segments_vic_non_life_table_with_added_britam_medical = segments_vic_non_life_table.copy()


# In[ ]:











# In[455]:


month_columns = hfbi_fire_bbb_companyassets_additional_values.columns


for col in month_columns:
    if col not in segments_vic_non_life_table_with_added_britam_medical.columns:
        segments_vic_non_life_table_with_added_britam_medical[col] = 0


fire_values_to_add = hfbi_fire_bbb_companyassets_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_vic_non_life_table_with_added_britam_medical.loc[segments_vic_non_life_table_with_added_britam_medical["segment_2"] == "BI INSTALLED",month_columns] += fire_values_to_add.values
# segments_vic_non_life_table_with_added_britam_medical.loc[segments_vic_non_life_table_with_added_britam_medical["segment_2"] == "BI INSTALLED",month_columns] += installed_britam_values_to_add.values
segments_vic_non_life_table_with_added_britam_medical.loc[segments_vic_non_life_table_with_added_britam_medical["segment_2"] == "BI SALES",month_columns] += sales_britam_values_to_add.values

# Recalculate total
segments_vic_non_life_table_with_added_britam_medical["Total"] = (
    segments_vic_non_life_table_with_added_britam_medical[month_columns].sum(axis=1)
)
segments_vic_non_life_table_with_added_britam_medical


# In[456]:


month_columns = hfbi_fire_bbb_companyassets_additional_values.columns


for col in month_columns:
    if col not in segments_vic_non_life_table.columns:
        segments_vic_non_life_table[col] = 0


fire_values_to_add = hfbi_fire_bbb_companyassets_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
total_britam_values_to_add = hfbi_total_britam_medical_values[month_columns].sum() # all britam medical added to BI SALES


# Add only to BI INSTALLED segment
segments_vic_non_life_table.loc[segments_vic_non_life_table["segment_2"] == "BI INSTALLED",month_columns] += fire_values_to_add.values
# segments_vic_non_life_table.loc[segments_vic_non_life_table["segment_2"] == "BI INSTALLED",month_columns] += installed_britam_values_to_add.values
segments_vic_non_life_table.loc[segments_vic_non_life_table["segment_2"] == "BI INSTALLED",month_columns] += total_britam_values_to_add.values

# Recalculate total
segments_vic_non_life_table["Total"] = (
    segments_vic_non_life_table[month_columns].sum(axis=1)
)
segments_vic_non_life_table


# In[457]:


segments_vic_life_table_with_targets = pd.merge(segment_vic_targets,segments_vic_life_table,left_on='SEGMENT',right_on='segment_2' ,how='left').reset_index().fillna(0)
segments_vic_life_table_with_targets = segments_vic_life_table_with_targets.drop(columns={'segment_2'})
segments_vic_life_table_with_targets = segments_vic_life_table_with_targets.rename(columns={'annual_target_banca_life':'annual_targets','Total':'ytd_cumulative',
                                                                                 'ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'})

segments_vic_life_table_with_targets = calculation_segment_formulas_without_capping(segments_vic_life_table_with_targets)
segments_vic_life_table_with_targets = calculate_deficits(segments_vic_life_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_life_table_with_targets.columns]

for month in month_order:
    if  month not in segments_vic_life_table_with_targets.columns:
        segments_vic_life_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_life_table_with_targets= segments_vic_life_table_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_life_table_with_targets= uncapped_total_row_less_ib(segments_vic_life_table_with_targets)
segments_vic_life_table_with_targets


# In[458]:


# segment_targets


# In[459]:


segments_vic_non_life_table_with_targets = pd.merge(segment_vic_targets,segments_vic_non_life_table,left_on='SEGMENT',right_on='segment_2' ,how='left').reset_index().fillna(0)
segments_vic_non_life_table_with_targets = segments_vic_non_life_table_with_targets.drop(columns={'segment_2'})
segments_vic_non_life_table_with_targets = segments_vic_non_life_table_with_targets.rename(columns={'annual_target_banca_non_life':'annual_targets','Total':'ytd_cumulative',
                                                                                 'ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'})

segments_vic_non_life_table_with_targets = calculation_segment_formulas_without_capping(segments_vic_non_life_table_with_targets)
segments_vic_non_life_table_with_targets = calculate_deficits(segments_vic_non_life_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_non_life_table_with_targets.columns]

for month in month_order:
    if  month not in segments_vic_non_life_table_with_targets.columns:
        segments_vic_non_life_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]
# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_non_life_table_with_targets= segments_vic_non_life_table_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_non_life_table_with_targets= uncapped_total_row_less_ib(segments_vic_non_life_table_with_targets)
segments_vic_non_life_table_with_targets


# In[460]:


segments_vic_non_life_table_with_added_britam_medical_with_targets = pd.merge(segment_vic_targets,segments_vic_non_life_table_with_added_britam_medical,left_on='SEGMENT',right_on='segment_2' ,how='left').reset_index().fillna(0)
segments_vic_non_life_table_with_added_britam_medical_with_targets = segments_vic_non_life_table_with_added_britam_medical_with_targets.drop(columns={'segment_2'})
segments_vic_non_life_table_with_added_britam_medical_with_targets = segments_vic_non_life_table_with_added_britam_medical_with_targets.rename(columns={'annual_target_banca_non_life':'annual_targets','Total':'ytd_cumulative',
                                                                                 'ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'})

segments_vic_non_life_table_with_added_britam_medical_with_targets = calculation_segment_formulas_without_capping(segments_vic_non_life_table_with_added_britam_medical_with_targets)
segments_vic_non_life_table_with_added_britam_medical_with_targets = calculate_deficits(segments_vic_non_life_table_with_added_britam_medical_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segments_vic_non_life_table_with_added_britam_medical_with_targets.columns]

for month in month_order:
    if  month not in segments_vic_non_life_table_with_added_britam_medical_with_targets.columns:
        segments_vic_non_life_table_with_added_britam_medical_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]
# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segments_vic_non_life_table_with_added_britam_medical_with_targets= segments_vic_non_life_table_with_added_britam_medical_with_targets[column_order]
# segment_life_table_with_targets
segments_vic_non_life_table_with_added_britam_medical_with_targets= uncapped_total_row_less_ib(segments_vic_non_life_table_with_added_britam_medical_with_targets)
segments_vic_non_life_table_with_added_britam_medical_with_targets










# In[461]:


def life_premiums_by_segment (dataframe, index, month_column_name, value_column_name):
    # segments_prem_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in segments_prem_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    segments_prem_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    segments_prem_amt = segments_prem_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in segments_prem_amt.columns:
            segments_prem_amt[month]=0
          
    segments_prem_amt['Total'] = segments_prem_amt[past_and_reporting_months].sum(axis=1)                          
    segments_prem_amt =segments_prem_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return segments_prem_amt

segments_life_table = life_premiums_by_segment(life_premiums_data, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')
segments_life_table


# In[462]:


value_to_remove = ['BI(ALL)']

segments_life_table = segments_life_table[~segments_life_table['segment_2'].isin(value_to_remove)]


# In[463]:


# hfbi_life_additional_values = hfbi_life_additional_values.T
# hfbi_life_additional_values


# In[464]:


# values_to_add = hfbi_life_additional_values[month_columns].sum()
# values_to_add


# In[465]:


month_columns = hfbi_life_additional_values.columns


for col in month_columns:
    if col not in segments_life_table.columns:
        segments_life_table[col] = 0


values_to_add = hfbi_life_additional_values[month_columns].sum()

# Add only to BI INSTALLED segment
segments_life_table.loc[
    segments_life_table["segment_2"] == "BI INSTALLED",
    month_columns
] += values_to_add.values

# Recalculate total
segments_life_table["Total"] = (
    segments_life_table[month_columns].sum(axis=1)
)
segments_life_table


# In[466]:


def non_life_premiums_by_segment (dataframe, index, month_column_name, value_column_name):
    # segments_prem_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in segments_prem_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    segments_prem_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    segments_prem_amt = segments_prem_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in segments_prem_amt.columns:
            segments_prem_amt[month]=0
          
    segments_prem_amt['Total'] = segments_prem_amt[past_and_reporting_months].sum(axis=1)                          
    segments_prem_amt =segments_prem_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return segments_prem_amt

segments_non_life_table = non_life_premiums_by_segment(non_life_premiums_data, month_column_name='month_name', index='segment_2',  value_column_name='paid_premiums')
segments_non_life_table


# In[467]:


value_to_remove = ['BI(ALL)']

segments_non_life_table = segments_non_life_table[~segments_non_life_table['segment_2'].isin(value_to_remove)]


# In[468]:


# hfbi_fire_bbb_companyassets_additional_values = hfbi_fire_bbb_companyassets_additional_values.T
# hfbi_fire_bbb_companyassets_additional_values


# In[469]:


month_columns = hfbi_fire_bbb_companyassets_additional_values.columns


for col in month_columns:
    if col not in segments_non_life_table.columns:
        segments_non_life_table[col] = 0


fire_values_to_add = hfbi_fire_bbb_companyassets_additional_values[month_columns].sum()
# installed_britam_values_to_add = hfbi_installed_britam_medical_values[month_columns].sum()
sales_britam_values_to_add = hfbi_sales_britam_medical_values[month_columns].sum()

# Add to the hfbi segmenst
segments_non_life_table.loc[segments_non_life_table["segment_2"] == "BI INSTALLED",month_columns] += fire_values_to_add.values
# segments_non_life_table.loc[segments_non_life_table["segment_2"] == "BI INSTALLED",month_columns] += installed_britam_values_to_add.values
segments_non_life_table.loc[segments_non_life_table["segment_2"] == "BI SALES",month_columns] += sales_britam_values_to_add.values


# Recalculate total
segments_non_life_table["Total"] = (
    segments_non_life_table[month_columns].sum(axis=1)
)
segments_non_life_table


# In[470]:


def total_premium_by_roles (dataframe, index, month_column_name, value_column_name):
    roles_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    roles_premium_amt = roles_premium_amt.fillna(0)
    roles_premium_amt = roles_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in roles_premium_amt.columns]

    for month in premium_month_order:
        if  month not in roles_premium_amt.columns:
            roles_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    roles_premium_amt = roles_premium_amt[[index] + past_and_reporting_months +['Total']]

    roles_premium_amt['Total'] = roles_premium_amt[past_and_reporting_months].sum(axis=1)
    return roles_premium_amt



roles_total_premiums_table = total_premium_by_roles(filtered_sales_report, month_column_name='month_name', index='staff_role',  value_column_name='total_premiums')

roles_total_premiums_table


# In[471]:


def premium_by_roles (dataframe, index, month_column_name, value_column_name):
    roles_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    roles_premium_amt = roles_premium_amt.fillna(0)
    roles_premium_amt = roles_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in roles_premium_amt.columns]

    for month in premium_month_order:
        if  month not in roles_premium_amt.columns:
            roles_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    roles_premium_amt = roles_premium_amt[[index] + past_and_reporting_months +['Total']]

    roles_premium_amt['Total'] = roles_premium_amt[past_and_reporting_months].sum(axis=1)
    return roles_premium_amt



roles_premiums_table = premium_by_roles(filtered_sales_report, month_column_name='month_name', index='staff_role',  value_column_name='paid_premiums')

# roles_premiums_table


# In[472]:


def revenue_by_roles (dataframe, index, month_column_name, value_column_name):
    role_comm_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    role_comm_amt = role_comm_amt.fillna(0)
    role_comm_amt = role_comm_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in role_comm_amt.columns]

    for month in comm_month_order:
        if  month not in role_comm_amt.columns:
            role_comm_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    role_comm_amt = role_comm_amt[[index] + past_and_reporting_months +['Total']]

    role_comm_amt['Total'] = role_comm_amt[past_and_reporting_months].sum(axis=1)
    return role_comm_amt



roles_revenue_table = revenue_by_roles(filtered_sales_report, month_column_name='month_name', index='staff_role',  value_column_name='commission')
# roles_revenue_table


# In[473]:


def vic_by_roles (dataframe, index, month_column_name, value_column_name):
    role_vic_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    role_vic_amt = role_vic_amt.fillna(0)
    role_vic_amt = role_vic_amt.reset_index()
    
    comm_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    comm_present_months = [col for col in comm_month_order if col in role_vic_amt.columns]

    for month in comm_month_order:
        if  month not in role_vic_amt.columns:
            role_vic_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in comm_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    role_vic_amt = role_vic_amt[[index] + past_and_reporting_months +['Total']]

    role_vic_amt['Total'] = role_vic_amt[past_and_reporting_months].sum(axis=1)
    return role_vic_amt



roles_vic_table = vic_by_roles(vic_premiums_data, month_column_name='month_name', index='staff_role', value_column_name='paid_premiums')
roles_vic_table


# In[474]:


def life_premiums_by_roles (dataframe, index, month_column_name, value_column_name):
    # role_comm_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    premium_month_order = [f'{month}-{report_year}' for month in['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]  #define the month order
    # premium_present_columns = [col for col in premium_month_order if col in role_comm_amt.columns]

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]

     
    if dataframe.empty:
        return pd.DataFrame(columns=[index] + past_and_reporting_months + ['Total'])

        
    role_comm_amt = pd.pivot_table(dataframe, columns=month_column_name, index = index, values = value_column_name, aggfunc = 'sum', margins = True, margins_name='Total')
    role_comm_amt = role_comm_amt.fillna(0).reset_index()
          
  
    for month in premium_month_order:
        if  month not in role_comm_amt.columns:
            role_comm_amt[month]=0
          
    role_comm_amt['Total'] = role_comm_amt[past_and_reporting_months].sum(axis=1)                          
    role_comm_amt =role_comm_amt[[index] + past_and_reporting_months +['Total']]   # ensure the branches are shown

    
    return role_comm_amt

roles_life_premiums_table = life_premiums_by_roles(life_premiums_data, month_column_name='month_name', index='staff_role',  value_column_name='paid_premiums')
roles_life_premiums_table


# In[475]:


def vic_total_premium_by_product (dataframe, index, month_column_name, value_column_name):
    vic_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    vic_premium_amt = vic_premium_amt.fillna(0)
    vic_premium_amt = vic_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in vic_premium_amt.columns]

    for month in premium_month_order:
        if  month not in vic_premium_amt.columns:
            vic_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    vic_premium_amt = vic_premium_amt[[index] + past_and_reporting_months +['Total']]

    vic_premium_amt['Total'] = vic_premium_amt[past_and_reporting_months].sum(axis=1)
    return vic_premium_amt
    

vic_products_table = filtered_sales_report[filtered_sales_report['vic_check']=='vic']

vic_total_premiums_table = vic_total_premium_by_product(vic_products_table, month_column_name='month_name', index='policy_category',  value_column_name='total_premiums')

vic_total_premiums_table


# In[476]:


def vic_total_premium_by_policy_category (dataframe, index, month_column_name, value_column_name):
    vic_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum')
    vic_premium_amt = vic_premium_amt.fillna(0)
    vic_premium_amt = vic_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in vic_premium_amt.columns]

    for month in premium_month_order:
        if  month not in vic_premium_amt.columns:
            vic_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    vic_premium_amt = vic_premium_amt[index + past_and_reporting_months]

    vic_premium_amt['ytd_cumulative'] = vic_premium_amt[past_and_reporting_months].sum(axis=1)
    return vic_premium_amt

vic_products_table = filtered_sales_report[filtered_sales_report['vic_check']=='vic']

vic_total_premiums_by_category_table = vic_total_premium_by_policy_category(vic_products_table, month_column_name='month_name', index=['policy_category','product'],  value_column_name='total_premiums')

vic_total_premiums_by_category_table


# In[477]:


vic_total_premiums_by_category_table_indexed = vic_total_premiums_by_category_table.copy()
vic_total_premiums_by_category_table_indexed =vic_total_premiums_by_category_table_indexed.set_index(['policy_category','product'])
vic_total_premiums_by_category_table_indexed
                                                                              


# In[478]:


subtotals = (vic_total_premiums_by_category_table_indexed.groupby(level='policy_category').sum())

subtotals['product'] = 'Subtotal'
subtotals = subtotals.reset_index().set_index(['policy_category', 'product'])

vic_paid_premiums_policy_category_with_subtotals = (pd.concat([vic_total_premiums_by_category_table_indexed, subtotals]).sort_index(level=['policy_category', 'product']))
vic_paid_premiums_policy_category_with_subtotals


# In[479]:


vic_total_premiums_by_category_table_indexed_grand_total = vic_total_premiums_by_category_table_indexed.sum().to_frame().T
vic_total_premiums_by_category_table_indexed_grand_total.index = pd.MultiIndex.from_tuples([('All Policies', 'Grand Total')])

final_vic_total_premiums_by_category_table_indexed = pd.concat([vic_paid_premiums_policy_category_with_subtotals,vic_total_premiums_by_category_table_indexed_grand_total])
final_vic_total_premiums_by_category_table_indexed


# In[480]:


# vic_products_table['policy_category']


# In[481]:


# vic_total_premiums_table.columns


# In[482]:


vic_total_premiums_table = pd.merge(policy_targets_table,vic_total_premiums_table, on ='policy_category', how ='left').fillna(0)
vic_total_premiums_table = vic_total_premiums_table.rename(columns={'Total':'ytd_cumulative'})
vic_total_premiums_table = calculation_operations_formulas(vic_total_premiums_table)
vic_total_premiums_table = calculate_deficits(vic_total_premiums_table, report_month)


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in vic_total_premiums_table.columns]
# existing_months=present_months
column_order = ['policy_category', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

vic_total_premiums_table= vic_total_premiums_table[column_order]
vic_total_premiums_table
vic_total_premiums_table= uncapped_total_row(vic_total_premiums_table)
vic_total_premiums_table


# In[483]:


vic_total_premiums_table.columns


# In[484]:


def vic_paid_premium_by_product (dataframe, index, month_column_name, value_column_name):
    vic_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    vic_premium_amt = vic_premium_amt.fillna(0)
    vic_premium_amt = vic_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in vic_premium_amt.columns]

    for month in premium_month_order:
        if  month not in vic_premium_amt.columns:
            vic_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    vic_premium_amt = vic_premium_amt[[index] + past_and_reporting_months +['Total']]

    vic_premium_amt['Total'] = vic_premium_amt[past_and_reporting_months].sum(axis=1)
    return vic_premium_amt

vic_products_table = filtered_sales_report[filtered_sales_report['vic_check']=='vic']

vic_premiums_table = vic_paid_premium_by_product(vic_products_table, month_column_name='month_name', index='policy_category',  value_column_name='paid_premiums')

vic_premiums_table




# In[485]:


def vic_paid_premium_by_policy_category (dataframe, index, month_column_name, value_column_name):
    vic_premium_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum')
    vic_premium_amt = vic_premium_amt.fillna(0)
    vic_premium_amt = vic_premium_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in vic_premium_amt.columns]

    for month in premium_month_order:
        if  month not in vic_premium_amt.columns:
            vic_premium_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    vic_premium_amt = vic_premium_amt[index + past_and_reporting_months]

    vic_premium_amt['ytd_cumulative'] = vic_premium_amt[past_and_reporting_months].sum(axis=1)
    return vic_premium_amt

vic_products_table = filtered_sales_report[filtered_sales_report['vic_check']=='vic']

vic_paid_premiums_policy_category = vic_paid_premium_by_policy_category(vic_products_table, month_column_name='month_name', index=['policy_category','product'],  value_column_name='paid_premiums')

vic_paid_premiums_policy_category




# In[486]:


vic_products_table.columns


# In[487]:


vic_paid_premiums_policy_category


# In[ ]:





















# In[488]:


vic_paid_premiums_policy_category_table_indexed = vic_paid_premiums_policy_category.copy()
vic_paid_premiums_policy_category_table_indexed =vic_paid_premiums_policy_category_table_indexed.set_index(['policy_category','product'])
vic_paid_premiums_policy_category_table_indexed


# In[489]:


subtotals = (vic_paid_premiums_policy_category_table_indexed.groupby(level='policy_category').sum())

subtotals['product'] = 'Subtotal'
subtotals = subtotals.reset_index().set_index(['policy_category', 'product'])

vic_paid_premiums_policy_category_with_subtotals = (pd.concat([vic_paid_premiums_policy_category_table_indexed, subtotals]).sort_index(level=['policy_category', 'product']))
vic_paid_premiums_policy_category_with_subtotals


# In[490]:


vic_paid_premiums_policy_category_table_indexed_grand_total = vic_paid_premiums_policy_category_table_indexed.sum().to_frame().T
vic_paid_premiums_policy_category_table_indexed_grand_total.index = pd.MultiIndex.from_tuples([('All Policies', 'Grand Total')])

final_vic_paid_premiums_policy_category_table_indexed = pd.concat([vic_paid_premiums_policy_category_with_subtotals,vic_paid_premiums_policy_category_table_indexed_grand_total])
final_vic_paid_premiums_policy_category_table_indexed


# In[ ]:





















# In[ ]:





















# In[ ]:





















# In[491]:


vic_premiums_table = pd.merge(policy_targets_table,vic_premiums_table, on ='policy_category', how ='left').fillna(0)
vic_premiums_table = vic_premiums_table.rename(columns={'Total':'ytd_cumulative'})
vic_premiums_table = calculation_operations_formulas(vic_premiums_table)
vic_premiums_table = calculate_deficits(vic_premiums_table, report_month)


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in vic_premiums_table.columns]
# existing_months=present_months
column_order = ['policy_category', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+present_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

vic_premiums_table= vic_premiums_table[column_order]
vic_premiums_table
vic_premiums_table= uncapped_total_row(vic_premiums_table)
vic_premiums_table


# In[492]:


def vic_revenue_by_product (dataframe, index, month_column_name, value_column_name):
    vic_comm_amt= pd.pivot_table(dataframe, index = index, columns= month_column_name, values= value_column_name, aggfunc='sum', margins= True, margins_name ='Total')
    vic_comm_amt = vic_comm_amt.fillna(0)
    vic_comm_amt = vic_comm_amt.reset_index()
    
    premium_month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
    premium_present_months = [col for col in premium_month_order if col in vic_comm_amt.columns]

    for month in premium_month_order:
        if  month not in vic_comm_amt.columns:
            vic_comm_amt[month]=0

    current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
    past_and_reporting_months = [month for month in premium_month_order if dt.strptime (month,'%b-%Y') <= current_month]
    

    vic_comm_amt = vic_comm_amt[[index] + past_and_reporting_months +['Total']]

    vic_comm_amt['Total'] = vic_comm_amt[past_and_reporting_months].sum(axis=1)
    return vic_comm_amt


vic_comm_table = vic_revenue_by_product(vic_products_table, month_column_name='month_name', index='policy_category',  value_column_name='commission')

vic_comm_table


# ## Analysis worksheet


# In[493]:


vic_comm_table = pd.merge(policy_targets_table,vic_comm_table, on ='policy_category', how ='left').fillna(0)
vic_comm_table = vic_comm_table.rename(columns={'Total':'ytd_cumulative'})
vic_comm_table = vic_comm_table.drop(columns={'annual_targets'})


# In[494]:


# vic_comm_table


# In[495]:


sales_report_copy = filtered_sales_report.copy()


# In[496]:


sales_report_copy.columns


# In[497]:


life_vs_non_life_premiums = sales_report_copy.groupby('life_policy_check')['paid_premiums'].sum().reset_index()
life_vs_non_life_premiums


# In[498]:


vic_vs_non_vic_premiums = sales_report_copy.groupby('vic_check')['paid_premiums'].sum().reset_index()
vic_vs_non_vic_premiums


# In[499]:


sales_report_copy['month_only']= pd.to_datetime(sales_report_copy['month_name'],format = '%b-%Y').dt.strftime('%b')
sales_report_copy['month_only']


# In[500]:


premiums_pvt = pd.pivot_table(sales_report_copy, index= 'month_only', values=['total_premiums','paid_premiums'], aggfunc= 'sum')
premiums_pvt = premiums_pvt.reset_index()
premiums_pvt


# In[501]:


month_order =['Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec','Total']
premiums_pvt['month_only'] = pd.Categorical(premiums_pvt['month_only'], categories = month_order, ordered = True)
ordered_premiums_pvt = premiums_pvt.sort_values(by ='month_only')
ordered_premiums_pvt


# In[502]:


role_names = pd.DataFrame({'role':roles})
role_names


# In[503]:


life_ytd_scores=[df['ytd_score'].iloc[-1] for df in life_premimum_modified_tables]
life_ytd_scores= pd.DataFrame({'life':life_ytd_scores})
life_ytd_scores


# In[504]:


non_life_ytd_scores=[df['ytd_score'].iloc[-1] for df in merged_non_life_tables]
non_life_ytd_scores= pd.DataFrame({'non_life':non_life_ytd_scores})
non_life_ytd_scores


# In[505]:


vic_life_ytd_scores=[df['ytd_score'].iloc[-1] for df in vic_life_premimum_modified_tables]
vic_life_ytd_scores= pd.DataFrame({'vic_life':vic_life_ytd_scores})
vic_life_ytd_scores


# In[506]:


vic_non_life_ytd_scores=[df['ytd_score'].iloc[-1] for df in vic_non_life_premimum_modified_tables]
vic_non_life_ytd_scores= pd.DataFrame({'vic_non_life':vic_non_life_ytd_scores})
vic_non_life_ytd_scores


# In[507]:


role_scores_df = pd.concat([role_names,vic_life_ytd_scores], ignore_index= False, axis =1)
role_scores = pd.concat([role_scores_df,vic_non_life_ytd_scores], ignore_index= False, axis =1)
role_scores


# In[508]:


subsidiaries_premiums_table.columns


# In[509]:


# Subsidiaries values for chart
columns_to_keep = ['SUBSIDIARY','ytd_target', 'ytd_cumulative']
subsidiaries_chart_values = subsidiaries_premiums_table[columns_to_keep]
subsidiaries_chart_values


# In[510]:


# Subsidiaries values for chart
columns_to_keep = ['SUBSIDIARY','ytd_target', 'ytd_cumulative']
subsidiaries_vic_life_chart_values = subsidiaries_vic_life_premiums_table_with_targets_total_row[columns_to_keep]
subsidiaries_vic_life_chart_values


# In[511]:


subsidiaries_vic_non_life_chart_values = subsidiaries_vic_non_life_premiums_table_with_targets_total_row[columns_to_keep]


# In[512]:


# subsidiaries_vic_life_premiums_table_with_targets_total_row


# In[513]:


zone_premium_table.columns


# In[514]:


zone_columns_to_keep =['zone','ytd_score']
zone_chart_values = zone_premium_table[zone_columns_to_keep]
zone_chart_values


# In[515]:


# ## Menu sheet


# In[516]:


segment_life_table_with_targets = pd.merge(segment_targets,segments_life_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segment_life_table_with_targets = segment_life_table_with_targets.drop(columns={'annual_target_banca_value','annual_target_banca_non_life','segment_2'})
segment_life_table_with_targets = segment_life_table_with_targets.rename(columns={'annual_target_banca_life':'annual_targets','Total':'ytd_cumulative',
                                                                                 'ytd_target_banca_life_calc':'ytd_target','target_banca_life':'monthly_targets'})


# In[517]:


segment_life_table_with_targets = calculation_segment_formulas(segment_life_table_with_targets)
segment_life_table_with_targets = calculate_deficits(segment_life_table_with_targets, report_month)


month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segment_life_table_with_targets.columns]

for month in month_order:
    if  month not in segment_life_table_with_targets.columns:
        segment_life_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]


# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segment_life_table_with_targets= segment_life_table_with_targets[column_order]
# segment_life_table_with_targets
segment_life_table_with_targets= total_row_less_ib(segment_life_table_with_targets)
segment_life_table_with_targets.columns


# In[ ]:























# In[518]:


segment_non_life_table_with_targets = pd.merge(segment_targets,segments_non_life_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segment_non_life_table_with_targets = segment_non_life_table_with_targets.drop(columns={'annual_target_banca_value','annual_target_banca_life','segment_2'})
segment_non_life_table_with_targets = segment_non_life_table_with_targets.rename(columns={'annual_target_banca_non_life':'annual_targets','Total':'ytd_cumulative',
                                                                                 'ytd_target_banca_non_life_calc':'ytd_target','target_banca_non_life':'monthly_targets'})

segment_non_life_table_with_targets = calculation_segment_formulas(segment_non_life_table_with_targets)
segment_non_life_table_with_targets = calculate_deficits(segment_non_life_table_with_targets, report_month)

month_order = [f'{month}-{report_year}' for month in [ 'Jan','Feb','Mar', 'Apr','May','Jun', 'Jul', 'Aug','Sep','Oct','Nov','Dec']]
present_months = [col for col in month_order if col in segment_non_life_table_with_targets.columns]


for month in month_order:
    if  month not in segment_non_life_table_with_targets.columns:
        segment_non_life_table_with_targets[month]=0

current_month = dt.strptime(f'{report_month}-{report_year}','%b-%Y')
past_and_reporting_months = [month for month in month_order if dt.strptime (month,'%b-%Y') <= current_month]

# existing_months=present_months
column_order = ['SEGMENT', 'annual_targets','monthly_targets','mtd_target', 'current_month_actuals', 
       "current_month_score"]+past_and_reporting_months+[ 'ytd_cumulative',
         'ytd_target', 'ytd_score','ytd_deficit',
       'adjusted_annual_targets']

segment_non_life_table_with_targets= segment_non_life_table_with_targets[column_order]
# segment_life_table_with_targets
segment_non_life_table_with_targets= total_row_less_ib(segment_non_life_table_with_targets)
segment_non_life_table_with_targets


# In[519]:


segment_comission_table = pd.merge(segment_targets,segments_revenue_table,left_on='SEGMENT',right_on='segment_2' ,how='left').fillna(0)
segment_comission_table = segment_comission_table.drop(columns={'annual_target_banca_non_life','annual_target_banca_life','segment_2'})
segment_comission_table = segment_comission_table.rename(columns={'Total':'ytd_cumulative'})
segment_comission_table


# In[520]:


# [segment_life_table_with_targets,segment_non_life_table_with_targets]


# In[521]:


"""## Menu Sheet"""

menu_worksheet = workbook.add_worksheet(menu_sheet_name)
# menu_worksheet = weighted_sales_report_writer.sheets[menu_sheet_name]

menu_worksheet.set_tab_color(roles_sheet_tab_color)


# textbox hyperlink formart with the page to link

menu_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 0.5,'y_scale':0.3,
              'url':"internal:'MENU'!A1"}

dashboard_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Dashboard'!A1"}


subsidiaries_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Subsidiaries_View'!A1"}

segments_summary_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Segments_summary'!A1"}

roles_summary_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Roles_summary'!A1"}

vic_products_summary_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#1996A9'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'VIC_products_summary'!A1"}

products_view_summary_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Products_View'!A1"}

vic_rms_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#1996A9'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'RMs_and_BBCs_VIC'!A1"}

vic_dsrs_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#1996A9'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'PB_and_Banca_Dsrs_VIC'!A1"}

vic_branch_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#1996A9'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Branch_VIC_Premiums'!A1"}


branch_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Branch_Performance'!A1"}


rms_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'RMs_and_BBCs_Life'!A1"}


dsrs_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'PB_and_Banca_Dsrs_Life'!A1"}

segment_life_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Segments_summary'!A1"}

segment_vic_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#1996A9'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'VIC_Segment_summary'!A1"}


branch_life_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'Branch_Life_Premiums'!A1"}

rms_bbcs_paid_premiums_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'RMs_and_BBCs_paid_premiums'!A1"}


dsrs_paid_premiums_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1.2,'y_scale':0.5,
              'url':"internal:'PB_and_Banca_Dsrs_all_premiums'!A1"}

dashboard_title ='BANCASSURANCE MENU'
menu_worksheet.insert_textbox('G2',dashboard_title,
                              {'fill':{'none': True},
                               'font':{'color':'#084B65','bold':True,'size':40,'align':'center','valign':'middle'},
                               'x_scale': 4,'y_scale':0.5,'border':{'none': True}})


data_point_format = workbook.add_format({'font':{'color':'#084B65','bold':True,'size':12}})

data_format = {'font':{'size':12,'name':'Calibri','bold': False,'color':'#FFFFFF','border':1},
              'fill':{'color':'#084B65'},
              'align':{ 'vertical':'middle','horizontal':'center'},
              'x_scale': 1,'y_scale':0.5,
              'url':"internal:'Bancassurance_data'!A1"}


data_points_title ='DATA POINTS'
menu_worksheet.insert_textbox('B28',data_points_title,
                              {'fill':{'color': '#F04E45'},'font':{'color':'#FFFFFF','bold':True,'size':12,'align':'center','valign':'middle'},
                               'x_scale': 1,'y_scale':0.25,'border':{'none': True}})

summary_title ='CATEGORICAL SUMMARIES'
menu_worksheet.insert_textbox('B6',summary_title,
                              {'fill':{'color':'#F04E45'},'font':{'color':'#FFFFFF','bold':True,'size':12,'align':'center','valign':'middle'},
                               'x_scale': 1,'y_scale':0.25,'border':{'none': True}})


vic_title ='VIC SUMMARIES'
menu_worksheet.insert_textbox('B22',vic_title,
                              {'fill':{'color': '#F04E45'},'font':{'color':'#FFFFFF','bold':True,'size':12,'align':'center','valign':'middle'},
                               'x_scale': 1,'y_scale':0.25,'border':{'none': True}})

premium_type_title ='LIFE PREMIUMS'
menu_worksheet.insert_textbox('B12',premium_type_title,
                              {'fill':{'color': '#F04E45'},'font':{'color':'#FFFFFF','bold':True,'size':12,'align':'center','valign':'middle'},
                               'x_scale': 1,'y_scale':0.25,'border':{'none': True}})

# apply format on sheet

menu_worksheet.insert_textbox('B8','Dashboard',dashboard_format)
menu_worksheet.insert_textbox('F8','Subsidiaries_View',subsidiaries_format)
menu_worksheet.insert_textbox('J8','Segments_summary',segments_summary_format)
menu_worksheet.insert_textbox('N8','Products_View',products_view_summary_format)
menu_worksheet.insert_textbox('B24','VIC_Segment_summary',segment_vic_format)
menu_worksheet.insert_textbox('F24','VIC_products_summary',vic_products_summary_format)
menu_worksheet.insert_textbox('J24','RMs_and_BBCs_VIC',vic_rms_format)
menu_worksheet.insert_textbox('N24','PB_and_Banca_Dsrs_VIC',vic_dsrs_format)
menu_worksheet.insert_textbox('R24','Branch_VIC_Premiums',vic_branch_format)
menu_worksheet.insert_textbox('B14','Branch_Performance',branch_format)
menu_worksheet.insert_textbox('F14','RMs_and_BBCs_all_premiums',rms_bbcs_paid_premiums_format)
menu_worksheet.insert_textbox('J14','PB_and_Banca_Dsrs_all_premiums',dsrs_paid_premiums_format)
menu_worksheet.insert_textbox('N14','Segments_summary',segment_life_format)
menu_worksheet.insert_textbox('B18','Branch_life',branch_life_format)
menu_worksheet.insert_textbox('F18','RMs_and_BBCs_Life',rms_format)
menu_worksheet.insert_textbox('J18','PB_and_Banca_DSRs_Life',dsrs_format)
menu_worksheet.insert_textbox('B31','Bancassurance_data',data_format)


menu_worksheet.set_zoom(80)
menu_worksheet.hide_gridlines(2)
menu_worksheet.protect('password', {'objects': False, 'scenarios': False, 'select_locked_cells': False,
                               'select_unlocked_cells': False,'insert_hyperlinks':True})


# In[ ]:























# In[522]:


dashboard_worksheet = workbook.add_worksheet(dashboard_sheet_name)
# dashboard_worksheet = weekly_banca_report_writer.sheets[dashboard_sheet_name] 


# In[523]:


# analysis_worksheet = workbook.add_worksheet(analysis_sheet_name)


start_col= 0
start_row= 1
end_row = ordered_premiums_pvt.shape[0]+ start_row

ordered_premiums_pvt.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

analysis_worksheet = weekly_banca_report_writer.sheets[analysis_sheet_name] 

analysis_worksheet.set_column(0,2,16.00)

analysis_worksheet.conditional_format(start_row+1,start_col+1,end_row,start_col+2,{'type':'no_errors','format':number_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,start_col+2,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,start_col+2,{'type':'no_errors','format':column_header_format})


# In[524]:


start_row= 1
start_col = 5

role_scores.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

end_row = role_scores.shape[0]+ start_row

analysis_worksheet.conditional_format(start_row+1,start_col,end_row,start_col+2,{'type':'no_errors','format':percent_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,start_col+2,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,start_col+2,{'type':'no_errors','format':column_header_format})

analysis_worksheet.set_zoom(80)


# In[525]:


role_scores


# In[526]:


start_col=14
start_row= 1

branch_chart_ytd_values.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

end_row = branch_chart_ytd_values.shape[0]+ start_row
end_col = branch_chart_ytd_values.shape[1]+ start_col-1

analysis_worksheet.conditional_format(start_row+1,start_col,end_row,end_col,{'type':'no_errors','format':number_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type':'no_errors','format':column_header_format})



# In[527]:


start_col = 9
start_row= 1

subsidiaries_chart_values.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

end_row = subsidiaries_chart_values.shape[0]+ start_row
end_col = subsidiaries_chart_values.shape[1]+ start_col-1

analysis_worksheet.conditional_format(start_row +1,start_col,end_row,end_col,{'type':'no_errors','format':number_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type':'no_errors','format':column_header_format})

analysis_worksheet.set_zoom(80)


# In[528]:


# start_col = 9
# start_row= 7
# subsidiaries_vic_non_life_chart_values.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

# end_row = subsidiaries_vic_non_life_chart_values.shape[0]+ start_row
# end_col = subsidiaries_vic_non_life_chart_values.shape[1]+ start_col-1

# analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':number_format})
# analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':border_format})
# analysis_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type':'no_errors','format':column_header_format})

# analysis_worksheet.set_zoom(80)


# In[529]:


start_col = 9
start_row= 7

zone_chart_values.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

end_row = zone_chart_values.shape[0]+ start_row
end_col = zone_chart_values.shape[1]+ start_col-1

analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':percent_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type':'no_errors','format':column_header_format})



# In[530]:


# life_vs_non_life_premiums


# In[531]:


start_col = 19
start_row= 1

life_vs_non_life_premiums.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

end_row = life_vs_non_life_premiums.shape[0]+ start_row
end_col = life_vs_non_life_premiums.shape[1]+ start_col-1

# analysis_worksheet.conditional_format(1,9,end_row,end_col,{'type':'no_errors','format':percent_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type':'no_errors','format':column_header_format})


# In[532]:


start_col = 23
start_row= 1

vic_vs_non_vic_premiums.to_excel(weekly_banca_report_writer, sheet_name=analysis_sheet_name, index = False, startcol= start_col,startrow=start_row)

end_row = vic_vs_non_vic_premiums.shape[0]+ start_row
end_col = vic_vs_non_vic_premiums.shape[1]+ start_col-1

# analysis_worksheet.conditional_format(1,9,end_row,end_col,{'type':'no_errors','format':percent_format})
analysis_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type':'no_errors','format':border_format})
analysis_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type':'no_errors','format':column_header_format})


# In[533]:


analysis_worksheet.hide()


# ### Charts

# #### Chart formats


# In[534]:


life_premiums_chart = workbook.add_chart({"type":"pie"})
vic_premiums_chart = workbook.add_chart({"type":"pie"})
branch_ytd_chart = workbook.add_chart({"type":"column"})
premiums_chart = workbook.add_chart({"type":"column"})
role_performance_chart = workbook.add_chart({"type":"column"})
zone_chart = workbook.add_chart({"type":"doughnut"})
subsidiaries_chart  = workbook.add_chart({"type":"column"})


# In[535]:


bar_size = {'x_scale':1.2,'y_scale':1.1}
big_pie_size = {'x_scale':1.2,'y_scale':1.1}
pie_size = {'x_scale':0.6,'y_scale':1.1}
legend = {'position':'bottom','font':{'bold': True,'size':8},'fill':{'color':'white'}}
title ={ 'size': 12,'font':'cambria','underline': True}

chart_area = {
    'border':{'color':'#084B65'},
    'fill': {'color': '#1996A9'}
}

#subsidiaries chart format

sub_bar_size = {'x_scale':0.67,'y_scale':1.1}


plot_area = {
    'fill':{'color':'#1996A9'},'positions':[90,100]
                
}

background_box = {'fill':{'color': '#084B65'},'x_scale': 1,'y_scale':0.33,'border':{'none': True}}
text_box = {'fill':{'none': True},'font':{'color':'white','bold':True,'size':18,'align':'center'},'x_scale': 1,'y_scale':0.25,'border':{'none': True}}
vtext_box = {'fill':{'none': True},'font':{'color':'#084B65','bold':True,'size':18,'align':'center'},'x_scale': 1,'y_scale':0.25,'border':{'none': True}}


# In[536]:


#ytd target
branch_ytd_chart.add_series({
    
    'name':'=Analysis!$P$2',
    'categories':'=Analysis!$O$3:$O$12',
    'values':'=Analysis!$P$3:$P$12',
    'fill':{'color':'#084B65'},
    'gap': 80
    })

# ytd cumulative
branch_ytd_chart.add_series({
    
    'name':'=Analysis!$Q$2',
    'categories':'=Analysis!$O$3:$O$12',
    'values':'=Analysis!$Q$3:$Q$12',
    'fill':{'color':'#F04E45'},
    'gap': 80
})


branch_ytd_chart.set_size(bar_size)

branch_ytd_chart.set_x_axis({'num_font':{'size':7, 'bold':True}})
branch_ytd_chart.set_y_axis({'num_font':{'size':10,'bold':False},'num_format':'#,##0.0,, "M"'})
# branch_ytd_chart.set_y_axis(})


branch_ytd_chart.set_title({'name':'Top 10 Branches: YTD Target vs Actual', 'name_font':title})

branch_ytd_chart.set_legend(legend)
branch_ytd_chart.set_style(10)
branch_ytd_chart.set_chartarea(chart_area)
branch_ytd_chart.set_plotarea(plot_area)


# In[537]:


#TOTAL PREMIUMS
premiums_chart.add_series({
    
    'name':'=Analysis!$C$2',
    'categories':'=Analysis!$A3:$A$14',
    'values':'=Analysis!$C$3:$C$14',
    'fill':{'color':'#084B65'},
    'gap': 80
    })

#PAID PREMIUMS
premiums_chart.add_series({
    
    'name':'=Analysis!$B$2',
    'categories':'=Analysis!$A3:$A$14',
    'values':'=Analysis!$B$3:$B$14',
    'fill':{'color':'#F04E45'},
    'gap': 80
})


premiums_chart.set_size(bar_size)

premiums_chart.set_x_axis({'num_font':{'size':8, 'bold':True}})
premiums_chart.set_y_axis({'num_font':{'size':10, 'bold':False}, 'num_format':'#,##0.0,,"M"'})

premiums_chart.set_title({'name':'Monthly premium trend',  'name_font' :title})

premiums_chart.set_legend(legend)
premiums_chart.set_style(10)
premiums_chart.set_chartarea(chart_area)
premiums_chart.set_plotarea(plot_area)


# In[538]:


life_premiums_chart.add_series({
    'categories':'=Analysis!$T$3:$T$4',
    'values':'=Analysis!$U$3:$U$4',
    'points':[{'fill':{'color':'#084B65'}},
              {'fill':{'color':'#F04E45'}},
              {'fill':{'color':'#1996A9'}}],
    'data_labels':{'category':True,'value':True,'num_format':'#,##0.0,,"M"','font':{'color':'#FFFFFF','bold':True,'fill':{'none':True}},'border':{'none':True}}
})
# 'data_labels':{'category':True,'value':True,'bold':True,'num_format':'0%','fill':{'color':'white'},'border':{'none':True}}
life_premiums_chart.set_size(big_pie_size)
life_premiums_chart.set_title(title)
life_premiums_chart.set_legend({'none':True})       
life_premiums_chart.set_chartarea(chart_area)
life_premiums_chart.set_plotarea(plot_area)             
life_premiums_chart.set_title({'name': 'Distribution of Life and Non-life Premiums', 'name_font':title})
# life_premiums_chart.set_hole_size(25)


# In[539]:


vic_premiums_chart.add_series({
    'categories':'=Analysis!$X$3:$X$4',
    'values':'=Analysis!$Y$3:$Y$4',
    'points':[{'fill':{'color':'#084B65'}},
              {'fill':{'color':'#F04E45'}},
              {'fill':{'color':'#1996A9'}}],
    'data_labels':{'category':True,'value':True,'num_format':'#,##0.0,,"M"','font':{'color':'#FFFFFF','bold':True,'fill':{'none':True}},'border':{'none':True}}
})
# 'data_labels':{'category':True,'value':True,'bold':True,'num_format':'0%','fill':{'color':'white'},'border':{'none':True}}
vic_premiums_chart.set_size(big_pie_size)
vic_premiums_chart.set_title(title)
vic_premiums_chart.set_legend({'none':True})       
vic_premiums_chart.set_chartarea(chart_area)
vic_premiums_chart.set_plotarea(plot_area)             
vic_premiums_chart.set_title({'name': 'Distribution of Vic and Non-Vic Premiums', 'name_font':title})


# In[540]:


zone_chart.add_series({
    'categories':'=Analysis!$J$9:$J$11',
    'values':'=Analysis!$K$9:$K$11',
    'points':[{'fill':{'color':'#084B65'}},
              {'fill':{'color':'#F04E45'}},
              {'fill':{'color':'#21C5DE'}}],
    'data_labels':{'category':True,'value':True,'num_format':'0%','font':{'color':'#FFFFFF','bold':True,'fill':{'none':True}},'border':{'none':True}}
})
# 'data_labels':{'category':True,'value':True,'bold':True,'num_format':'0%','fill':{'color':'white'},'border':{'none':True}}
zone_chart.set_size(pie_size)
zone_chart.set_title(title)
zone_chart.set_legend({'none':True})       
zone_chart.set_chartarea(chart_area)
zone_chart.set_plotarea(plot_area)             
zone_chart.set_title({'name': 'Zone Ytd achivement', 'name_font':title})
zone_chart.set_hole_size(25)


# In[541]:


#MOTOR
role_performance_chart.add_series({
    
    'name':'=Analysis!$G$2',
    'categories':'=Analysis!$F3:$F$8',
    'values':'=Analysis!$G$3:$G$8',
    'fill':{'color':'#084B65'},
    'gap': 80
    })

#non_motor
role_performance_chart.add_series({
    
    'name':'=Analysis!$H$2',
    'categories':'=Analysis!$F3:$F$8',
    'values':'=Analysis!$H$3:$H$8',
    'fill':{'color':'#F04E45'},
    'gap': 80
    })


role_performance_chart.set_size(bar_size)

role_performance_chart.set_x_axis({'num_font':{'size':8, 'bold':True}})
role_performance_chart.set_y_axis({'num_font':{'size':10, 'bold':False}, 'num_format':'0%'})

role_performance_chart.set_title({'name':'Ytd role performance',  'name_font' :title})

role_performance_chart.set_legend(legend)
role_performance_chart.set_style(10)
role_performance_chart.set_chartarea(chart_area)
role_performance_chart.set_plotarea(plot_area)


# In[542]:


subsidiaries_chart.add_series({
    
    'name':'=Analysis!$K$2',
    'categories':'=Analysis!$J3:$J$5',
    'values':'=Analysis!$K$3:$K$5',
    'fill':{'color':'#084B65'},
    'gap': 80
    })

subsidiaries_chart.add_series({
    
    'name':'=Analysis!$L$2',
    'categories':'=Analysis!$J3:$J$5',
    'values':'=Analysis!$L$3:$L$5',
    'fill':{'color':'#F04E45'},
    'gap': 80
})
subsidiaries_chart.set_size(sub_bar_size)

subsidiaries_chart.set_x_axis({'num_font':{'size':8, 'bold':True}})
subsidiaries_chart.set_y_axis({'num_font':{'size':10, 'bold':False}, 'num_format':'#,##0.0,, "M"'})

subsidiaries_chart.set_title({'name':'Subsidiaries performance',  'name_font' :title})

subsidiaries_chart.set_legend(legend)
subsidiaries_chart.set_style(10)
subsidiaries_chart.set_chartarea(chart_area)
subsidiaries_chart.set_plotarea(plot_area)


# ## Write charts & sheets

# ### Dashboard sheet


# In[543]:


# dashboard_worksheet = weekly_banca_report_writer.sheets[dashboard_sheet_name] 
dashboard_worksheet.set_tab_color(sheet_tab_colour)



dashboard_worksheet.insert_textbox('A1','',{'fill':{'color': '#1996A9'},'x_scale': 6.0,'y_scale':0.82,'border':{'none': True}})

year_title = "BANCASSURANCE DASHBOARD"

dashboard_worksheet.insert_textbox('E2',year_title,{'fill':{'none': True},'font':{'color':'#084B65','bold':True,'size':40,'align':'center','valign':'middle'},'x_scale': 4.3,'y_scale':0.54,'border':{'none': True}})

# reporting_date = get_reporting_date()
date_value = report_date

dashboard_worksheet.insert_textbox('A1','',{'fill':{'color': '#1996A9'},'x_scale': 1,'y_scale':0.54,'border':{'none': True}})
dashboard_worksheet.insert_textbox('A3',date_value,{'fill':{'none': True},'font':{'color':'#084B65','bold':True,'size':26,'align':'center'},'x_scale': 1.5,'y_scale':0.5,'border':{'none': True}})

dashboard_worksheet.insert_chart('A6',vic_premiums_chart)
dashboard_worksheet.insert_chart('J6',life_premiums_chart)
dashboard_worksheet.insert_chart('A22',branch_ytd_chart)
dashboard_worksheet.insert_chart('J22',premiums_chart)
dashboard_worksheet.insert_chart('A38',role_performance_chart)
dashboard_worksheet.insert_chart('J38',zone_chart)
dashboard_worksheet.insert_chart('N38',subsidiaries_chart)
dashboard_worksheet.insert_textbox('A1','MENU',menu_format)
dashboard_worksheet.set_zoom(100)
dashboard_worksheet.hide_gridlines(2)
dashboard_worksheet.protect() #protect sheet




# ### Subsidiaries sheet


# In[544]:


# vic_total_premiums_table


# In[545]:


# segments_vic_non_life_table_with_added_britam_medical_with_targets

# segment_vic_sheet_name

segment_vic_tables =[segments_vic_total_premiums_table_with_added_britam_medical_with_targets,segments_vic_paid_premiums_table_with_added_britam_with_targets,segments_vic_life_table_with_targets,segments_vic_non_life_table_with_added_britam_medical_with_targets]

start_row = 3
start_col = 0

rows = np.cumsum([df.shape[0]+4 for df in segment_vic_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, segment_vic_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = segment_vic_sheet_name, index = False, startrow = row, startcol=start_col)

    segemnt_vic_worksheet = weekly_banca_report_writer.sheets[segment_vic_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
        subject = 'Total Vic Premiums to be collected'
    elif i == 1:
        subject = 'Paid Vic Premiums'
    elif i==2:
        subject = 'Vic Life Premiums'
    else:
        subject = 'Vic non-life Premiums'


        
    segemnt_vic_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
    # segemnt_vic_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    segemnt_vic_worksheet.set_column(start_col,end_col,20.00,number_format)
    
    segemnt_vic_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    segemnt_vic_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
    segemnt_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    segemnt_vic_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        segemnt_vic_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        segemnt_vic_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        segemnt_vic_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        segemnt_vic_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        segemnt_vic_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        segemnt_vic_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, segment_vic_tables)):
    # start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 6
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'G:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    segemnt_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    segemnt_vic_worksheet.conditional_format(row,8,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})
    segemnt_vic_worksheet.conditional_format(row+1,start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# for i , (row, df) in enumerate(zip(fin_rows, segment_vic_tables)):
#     segemnt_vic_worksheet.set_row(row+13,None,None,{'hidden':True})


segemnt_vic_worksheet.insert_textbox('A1','MENU',menu_format)
segemnt_vic_worksheet.set_tab_color(sheet_tab_colour)  
segemnt_vic_worksheet.set_zoom(90)
segemnt_vic_worksheet.freeze_panes(0,1)



# In[546]:


start_row = 3
start_col= 0

vic_tables =[vic_total_premiums_table, vic_premiums_table,vic_comm_table]

rows = np.cumsum([df.shape[0]+4 for df in vic_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, vic_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = vic_summary_sheet_name, index = False, startrow = row, startcol=start_col)

    vic_summary_worksheet = weekly_banca_report_writer.sheets[vic_summary_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
       subject = 'TOTAL PREMIUMS'
    elif i==1:
        subject = 'COLLECTED PREMIUMS' 
    else:
        subject = ' REVENUE'
    vic_summary_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
    # vic_summary_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    vic_summary_worksheet.set_column(start_col,end_col,20.00,number_format)
    
    vic_summary_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    vic_summary_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
    vic_summary_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    vic_summary_worksheet.conditional_format(row,start_col,end_row,start_col+1,{'type': 'no_errors', 'format': grey_format})


    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        vic_summary_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        vic_summary_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        vic_summary_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        vic_summary_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        vic_summary_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        vic_summary_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})


# for i,( row, df) in enumerate(zip(fin_rows, vic_tables)):
#     # start_col = 0 if i == 1 else 1
#     # start_col =  start_col  + 6 # where months starts
#     group_end_col =  df.shape[1] + start_col - 7
    
#     # Dynamically create the column range
#     # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
#     column_range = f'G:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
#     # column_range = f'H:L'
#     # Group and hide columns
#     vic_summary_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
#     vic_summary_worksheet.conditional_format(row,7,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# for i , (row, df) in enumerate(zip(fin_rows, vic_tables)):
#     vic_summary_worksheet.set_row(row+13,None,None,{'hidden':True})


vic_summary_worksheet.insert_textbox('A1','MENU',menu_format)
vic_summary_worksheet.set_tab_color(sheet_tab_colour)  
vic_summary_worksheet.set_zoom(90)
vic_summary_worksheet.freeze_panes(4,2)




# In[ ]:















# In[547]:


# final_vic_paid_premiums_policy_category_table_indexed


# In[548]:


start_row = 3
start_col = 0


vic_products_tables =[final_vic_total_premiums_by_category_table_indexed,final_vic_paid_premiums_policy_category_table_indexed]

# value_to_find = 'Subtotal'
# total_row_numbers = vic_products_tables.index[vic_products_tables['product'] == value_to_find].tolist()


rows = np.cumsum([df.shape[0]+4 for df in vic_products_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, vic_products_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = products_view_sheet_name, index = True, startrow = row, startcol=start_col)

    products_view_worksheet = weekly_banca_report_writer.sheets[products_view_sheet_name] 

    end_row = df.shape[0]+ row
    end_col = df.shape[1] + start_col -1

    title = ' TOTAL PREMIUMS' if i== 0 else 'PAID PREMIUMS'

    products_view_worksheet.merge_range(row-1,start_col,row-1,start_col+1,title,maya_blue_format) 

    products_view_worksheet.conditional_format(row+1,start_col,end_row,end_col+2,{'type': 'no_errors', 'format': border_format})
    products_view_worksheet.conditional_format(row,start_col,row,end_col+2,{'type': 'no_errors', 'format': maya_blue_format})
    products_view_worksheet.conditional_format(end_row,start_col,end_row,end_col+2,{'type': 'no_errors', 'format': total_format})
    products_view_worksheet.conditional_format(row,start_col,end_row,start_col+1,{'type': 'no_errors', 'format': grey_format})
    products_view_worksheet.set_column(start_col,end_col+2,20.00,number_format)

    # value_to_find = 'Subtotal'
    # # subtotal_rows = df.index[df['product'] == value_to_find].tolist() 
    # subtotal_rows = df.index[df.index == value_to_find].tolist()

    # for row_num in subtotal_rows:
    #     sub_row = row + df.index.get_loc(row_num) + 1  # convert label to position
    #     # sub_row = row + row_num + 1
    #     products_view_worksheet.conditional_format(sub_row, start_col, sub_row, end_col, {'type': 'no_errors','format': maya_blue_format})

# value_to_find = 'Subtotal'

# subtotal_rows = df.index[df.index == value_to_find].tolist()

# for row_num in subtotal_rows:
#     sub_row = row + df.index.get_loc(row_num) + 1  # convert label to position
#     products_view_worksheet.conditional_format(
#         sub_row, start_col, sub_row, end_col,
#         {'type': 'no_errors', 'format': maya_blue_format}




products_view_worksheet.insert_textbox('A1','MENU',menu_format)
products_view_worksheet.set_tab_color(sheet_tab_colour)  
products_view_worksheet.set_zoom(90)
products_view_worksheet.freeze_panes(4,2)


# In[549]:


# n= final_vic_total_premiums_by_category_table_indexed.index[final_vic_total_premiums_by_category_table_indexed['product']]
# n


# In[550]:


# start_col= 0
# start_row= 3

# subsidiaries_premiums_table.to_excel(weekly_banca_report_writer, sheet_name=subsidiaries_sheet_name, index = False, startcol= start_col, startrow = start_row)

# subsidiaries_worksheet = weekly_banca_report_writer.sheets[subsidiaries_sheet_name] 
# subsidiaries = [subsidiaries_premiums_table]

# for df in subsidiaries:
    
#     end_row = subsidiaries_premiums_table.shape[0] + start_row
#     end_col = subsidiaries_premiums_table.shape[1] + start_col-1

#     mtd_percent_col = df.columns.get_loc("current_month_score") 
#     ytd_percent_col = df.columns.get_loc('ytd_score')

#     for percent_col in (mtd_percent_col,ytd_percent_col):
        
#         subsidiaries_worksheet.conditional_format(start_row+1,percent_col,end_row,percent_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
#         subsidiaries_worksheet.conditional_format(start_row+1,percent_col,end_row,percent_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
#         subsidiaries_worksheet.conditional_format(start_row+1,percent_col,end_row,percent_col,{'type': 'cell','criteria':'between', 'minimum': 0.8,'maximum': 1.0,  'format': amber_format})

    
# header_name = 'COLLECTED PREMIUMS' 

# subsidiaries_worksheet.merge_range(start_row-1,start_col,start_row-1,1,"SUMMARY",sub_header_format)  
# subsidiaries_worksheet.merge_range(start_row-1,6,start_row-1,end_col,header_name,sub_header_format)

# subsidiaries_worksheet.set_column(start_col,end_col,20.00,number_format)

# subsidiaries_worksheet.conditional_format(start_row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
# subsidiaries_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type': 'no_errors', 'format': column_header_format})
# subsidiaries_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
# subsidiaries_worksheet.conditional_format(start_row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})

# group_start_col =  start_col  + 6 # where months starts
# group_end_col =  subsidiaries_premiums_table.shape[1]+start_col - 4

# # Dynamically create the column range
# # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
# column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# # column_range = f'H:L'
# # Group and hide columns
# subsidiaries_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
# subsidiaries_worksheet.conditional_format(start_row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# subsidiaries_worksheet.insert_textbox('A1','MENU',menu_format)

# subsidiaries_worksheet.set_tab_color(sheet_tab_colour)  
# # subsidiaries_worksheet.autofit()
# subsidiaries_worksheet.set_zoom(90)
# subsidiaries_worksheet.freeze_panes(4,2)


# In[551]:


# subsidiaries_non_life_premiums_table_with_targets


start_col= 0
start_row= 3

subsidiaries_tables =[subsidiaries_premiums_table,subsidiaries_life_premiums_table_with_targets_total_row,subsidiaries_non_life_premiums_table_with_targets_total_row,
                     subsidiaries_vic_life_premiums_table_with_targets_total_row,subsidiaries_vic_non_life_premiums_table_with_targets_total_row]
# subsidiaries_tables =[segment_life_table_with_targets,segment_non_life_table_with_targets]

rows = np.cumsum([df.shape[0]+4 for df in subsidiaries_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, subsidiaries_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = subsidiaries_sheet_name, index = False, startrow = row, startcol=start_col)

    subsidiaries_worksheet = weekly_banca_report_writer.sheets[subsidiaries_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
       subject = 'All Premiums'    
    elif i==1:
       subject = 'Life Premiums'
    elif i ==2:
        subject = 'Non-life Premiums'
    elif i ==3:
        subject = 'Vic Life Premiums'
    else:
        subject = 'Vic non-life Premiums'
        
    subsidiaries_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,sub_header_format)  
    # subsidiaries_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    subsidiaries_worksheet.set_column(start_col,end_col,20.00,number_format)
    
    subsidiaries_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    subsidiaries_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    subsidiaries_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    subsidiaries_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        subsidiaries_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        subsidiaries_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        subsidiaries_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        subsidiaries_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        subsidiaries_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        subsidiaries_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, subsidiaries_tables)):
    # start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 6
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'G:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    subsidiaries_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    subsidiaries_worksheet.conditional_format(row,6,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})



# group_start_col =  start_col  + 6 # where months starts
# group_end_col =  subsidiaries_premiums_table.shape[1]+start_col - 4

# # Dynamically create the column range
# # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
# column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# # column_range = f'H:L'
# # Group and hide columns
# subsidiaries_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
# subsidiaries_worksheet.conditional_format(start_row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})




subsidiaries_worksheet.insert_textbox('A1','MENU',menu_format)
subsidiaries_worksheet.set_tab_color(sheet_tab_colour)  
subsidiaries_worksheet.set_zoom(90)
subsidiaries_worksheet.freeze_panes(4,2)


# In[552]:


start_row = 3
start_col= 0
segment_tables =[segments_total_premiums_table_with_targets,segments_paid_premiums_table_with_targets,segment_life_table_with_targets,segment_non_life_table_with_targets]
# segment_tables =[segment_life_table_with_targets,segment_non_life_table_with_targets]

rows = np.cumsum([df.shape[0]+4 for df in segment_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, segment_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = segment_life_sheet_name, index = False, startrow = row, startcol=start_col)

    segemnt_life_worksheet = weekly_banca_report_writer.sheets[segment_life_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
       subject = 'Total Premiums to be collected'
    elif i==1:
       subject = 'Paid Premiums'        
    elif i==2:
       subject = 'Life Premiums'
    else:
        subject = 'Non-life Premiums'
        
    segemnt_life_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
    # segemnt_life_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    segemnt_life_worksheet.set_column(start_col,end_col,20.00,number_format)
    
    segemnt_life_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    segemnt_life_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
    segemnt_life_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    segemnt_life_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        segemnt_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        segemnt_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        segemnt_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        segemnt_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        segemnt_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        segemnt_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, segment_tables)):
    # start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 6
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'G:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    segemnt_life_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    segemnt_life_worksheet.conditional_format(row,8,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# for i , (row, df) in enumerate(zip(fin_rows, segment_tables)):
#     segemnt_life_worksheet.set_row(row+13,None,None,{'hidden':True})

segemnt_life_worksheet.insert_textbox('A1','MENU',menu_format)
segemnt_life_worksheet.set_tab_color(sheet_tab_colour)  
segemnt_life_worksheet.set_zoom(90)
segemnt_life_worksheet.freeze_panes(0,2)




# In[553]:


start_row = 3
start_col= 0

weekly_tables =[weekly_segment_paid_premiums_table, weekly_segment_revenue_table,weekly_roles_paid_premiums_table,weekly_roles_revenue_table]

rows = np.cumsum([df.shape[0]+4 for df in weekly_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, weekly_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = weekly_productivity_sheet_name, index = False, startrow = row, startcol=start_col)

    weekly_productivity_worksheet = weekly_banca_report_writer.sheets[weekly_productivity_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
       subject = 'Paid Premiums by Segment'
    elif i==1:
        subject = 'Revenue by Segment'
    elif i==2:
        subject = 'Paid Premiums by Roles'
    else:
        subject = 'Revenue by Roles'
    weekly_productivity_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
    # weekly_productivity_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    weekly_productivity_worksheet.set_column(start_col,end_col,20.00,number_format)
    
    weekly_productivity_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    weekly_productivity_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
    weekly_productivity_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    weekly_productivity_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})


weekly_productivity_worksheet.insert_textbox('A1','MENU',menu_format)
weekly_productivity_worksheet.set_tab_color(sheet_tab_colour)  
weekly_productivity_worksheet.set_zoom(90)




# In[554]:


weekly_segment_vic_paid_premiums_table


# In[555]:


start_row = 3
start_col= 0

vic_weekly_tables  =[weekly_segment_vic_paid_premiums_table, weekly_vic_segment_revenue_table,weekly_roles_vic_paid_premiums_table,weekly_roles_vic_revenue_table]

rows = np.cumsum([df.shape[0]+4 for df in vic_weekly_tables ])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, vic_weekly_tables )):
    df.to_excel(weekly_banca_report_writer, sheet_name = vic_weekly_productivity_sheet_name, index = False, startrow = row, startcol=start_col)

    weekly_vic_productivity_worksheet  = weekly_banca_report_writer.sheets[vic_weekly_productivity_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
       subject = 'VIC paid premiums by segment'
    elif i==1:
        subject = 'VIC revenue by segment'
    elif i==2:
        subject = 'VIC paid premiums by roles'
    else:
        subject = 'VIC revenue by roles'
    weekly_vic_productivity_worksheet .merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
    # weekly_vic_productivity_worksheet .merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    weekly_vic_productivity_worksheet .set_column(start_col,end_col,20.00,number_format)
    
    weekly_vic_productivity_worksheet .conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    weekly_vic_productivity_worksheet .conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
    weekly_vic_productivity_worksheet .conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    weekly_vic_productivity_worksheet .conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})


weekly_vic_productivity_worksheet .insert_textbox('A1','MENU',menu_format)
weekly_vic_productivity_worksheet .set_tab_color(sheet_tab_colour)  
weekly_vic_productivity_worksheet .set_zoom(90)




# In[556]:


weekly_segment_vic_paid_premiums_table


# In[557]:


# start_row = 3
# start_col= 0

# segment_tables =[segments_paid_premiums_table_with_targets,segments_vic_table_with_targets,segments_non_vic_table_with_targets,segment_comission_table]

# rows = np.cumsum([df.shape[0]+4 for df in segment_tables])
# fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
# fin_rows = [int(item) for item in fin_rows]

# for i,( row, df) in enumerate(zip(fin_rows, segment_tables)):
#     df.to_excel(weekly_banca_report_writer, sheet_name = segments_sheet_name, index = False, startrow = row, startcol=start_col)

#     segments_worksheet = weekly_banca_report_writer.sheets[segments_sheet_name] 
    
#     end_row = df.shape[0]+ row
#     end_col = df.shape[1]-1

#     if i ==0:
#         subject = 'COLLECTED PREMIUMS' 
#     elif i == 1:
#         subject = 'VIC PREMIUMS'
#     elif i == 2:
#         subject = 'NON- VIC PREMIUMS'
#     else:
#         subject = 'REVENUE'
#     segments_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
#     # segments_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
#     segments_worksheet.set_column(start_col,end_col,20.00,number_format)
    
#     segments_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
#     segments_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
#     segments_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
#     segments_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})
    
#     # segments_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# segments_worksheet.insert_textbox('A1','MENU',menu_format)

# segments_worksheet.set_tab_color(sheet_tab_colour)  
# # segments_worksheet.autofit()
# segments_worksheet.set_zoom(90)
# # segments_worksheet.freeze_panes(6,2)


# # ### summary roles sheet


# In[ ]:





















# In[558]:


# weekly_roles_paid_premiums_table


# In[559]:


#writing premium dfs
premiums =[zone_premium_table, branch_premium_table]
labels = ['zone','branch']

start_row=3

rows = np.cumsum([df.shape[0]+3 for df in premiums])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]


for i , (row, df) in enumerate(zip(fin_rows, premiums)):
    start_col = 0 if i == 1 else 1
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_sheet_name, index = False, startrow = row, startcol=start_col)

    branch_worksheet = weekly_banca_report_writer.sheets[branches_sheet_name] 

    end_row = df.shape[0] + row
    end_col = df.shape[1]  + start_col -1
    
    header_name = 'ZONES' if i== 0 else 'BRANCHES'
    branch_worksheet.merge_range(row-1,start_col,row-1,start_col + 1,header_name,sub_header_format)
    branch_worksheet.merge_range(row-1,7,row-1,end_col,'PAID PREMIUMS',sub_header_format)
    branch_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    branch_worksheet.set_column(start_col,start_col,5.00)

    
    branch_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    branch_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    branch_worksheet.conditional_format(row,start_col,end_row,6,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        branch_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        branch_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        branch_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        branch_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        branch_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        branch_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, premiums)):
    start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 4
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    branch_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    branch_worksheet.conditional_format(row,8,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


deficit_tables = [zone_deficit_table,branch_deficit_table]

rows = np.cumsum([df.shape[0]+3 for df in deficit_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

deficit_start_col= [premiums[i].shape[1] + 1 if i==0 else premiums[i].shape[1]  for i in range(len(deficit_tables))]

for i,(df, col) in enumerate( zip(deficit_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (deficit_tables):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    

    branch_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    branch_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'DEFICIT TARGETS',deficit_header_format)

    branch_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    # branch_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    branch_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})



# write commission dfs to the right of premium dfs
commissions =[zone_comm_table, branch_commission_table]

rows = np.cumsum([df.shape[0]+3 for df in commissions])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

comm_start_col= [premiums[i].shape[1] + deficit_tables[i].shape[1] + 1 if i==0 else premiums[i].shape[1] + deficit_tables[i].shape[1] for i in range(len(commissions))]

for i,(df, col) in enumerate( zip(commissions, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (commissions):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    

    branch_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    branch_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)

    branch_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    branch_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    branch_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

branch_worksheet.insert_textbox('A1','MENU',menu_format)

# branch_worksheet.autofit()
branch_worksheet.set_tab_color(sheet_tab_colour)      
branch_worksheet.freeze_panes(3,4)
branch_worksheet.set_zoom(90)


# In[560]:


#writing branch and zone life tables


# [branch_life_premium_table,branch_deficit_life_table,branch_life_commission_table,zone_deficit_life_table,zone_comm_life_table,# branch_life_premium_table,
# branch_deficit_life_table,branch_life_commission_table,zone_deficit_life_table,zone_comm_life_table]

premiums =[zone_life_premium_table, branch_life_premium_table]
labels = ['zone','branch']

start_row=3

rows = np.cumsum([df.shape[0]+3 for df in premiums])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]


for i , (row, df) in enumerate(zip(fin_rows, premiums)):
    start_col = 0 if i == 1 else 1
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_life_sheet_name, index = False, startrow = row, startcol=start_col)

    branch_life_worksheet = weekly_banca_report_writer.sheets[branches_life_sheet_name] 

    end_row = df.shape[0] + row
    end_col = df.shape[1]  + start_col -1
    
    header_name = 'ZONES' if i== 0 else 'BRANCHES'
    branch_life_worksheet.merge_range(row-1,start_col,row-1,start_col + 1,header_name,sub_header_format)
    branch_life_worksheet.merge_range(row-1,7,row-1,end_col,'PAID LIFE PREMIUMS',sub_header_format)
    branch_life_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    branch_life_worksheet.set_column(start_col,start_col,5.00)

    
    branch_life_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_life_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    branch_life_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    branch_life_worksheet.conditional_format(row,start_col,end_row,6,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        branch_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        branch_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        branch_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        branch_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        branch_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        branch_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, premiums)):
    start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 4
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    branch_life_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    branch_life_worksheet.conditional_format(row,8,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


deficit_tables = [zone_deficit_life_table,branch_deficit_life_table]

rows = np.cumsum([df.shape[0]+3 for df in deficit_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

deficit_start_col= [premiums[i].shape[1] + 1 if i==0 else premiums[i].shape[1]  for i in range(len(deficit_tables))]

for i,(df, col) in enumerate( zip(deficit_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_life_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (deficit_tables):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    

    branch_life_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    branch_life_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'DEFICIT TARGETS',deficit_header_format)

    branch_life_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_life_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    # branch_life_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    branch_life_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})



# write commission dfs to the right of premium dfs
commissions =[zone_comm_life_table, branch_life_commission_table]

rows = np.cumsum([df.shape[0]+3 for df in commissions])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

comm_start_col= [premiums[i].shape[1] + deficit_tables[i].shape[1] + 1 if i==0 else premiums[i].shape[1] + deficit_tables[i].shape[1] for i in range(len(commissions))]

for i,(df, col) in enumerate( zip(commissions, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_life_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (commissions):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    

    branch_life_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    branch_life_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'LIFE COMMISSIONS',maya_blue_format)

    branch_life_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_life_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    branch_life_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    branch_life_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

branch_life_worksheet.insert_textbox('A1','MENU',menu_format)

# branch_life_worksheet.autofit()
branch_life_worksheet.set_tab_color(sheet_tab_colour)      
branch_life_worksheet.freeze_panes(3,4)
branch_life_worksheet.set_zoom(90)


# In[561]:


#writing branch and zone life tables


# [branch_life_premium_table,branch_deficit_life_table,branch_life_commission_table,zone_deficit_life_table,zone_comm_life_table,# branch_life_premium_table,
# branch_deficit_life_table,branch_life_commission_table,zone_deficit_life_table,zone_comm_life_table]

premiums =[zone_non_life_premium_table, branch_non_life_premium_table]
labels = ['zone','branch']

start_row=3

rows = np.cumsum([df.shape[0]+3 for df in premiums])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]


for i , (row, df) in enumerate(zip(fin_rows, premiums)):
    start_col = 0 if i == 1 else 1
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_non_life_sheet_name, index = False, startrow = row, startcol=start_col)

    branch_non_life_worksheet = weekly_banca_report_writer.sheets[branches_non_life_sheet_name] 

    end_row = df.shape[0] + row
    end_col = df.shape[1]  + start_col -1
    
    header_name = 'ZONES' if i== 0 else 'BRANCHES'
    branch_non_life_worksheet.merge_range(row-1,start_col,row-1,start_col + 1,header_name,sub_header_format)
    branch_non_life_worksheet.merge_range(row-1,7,row-1,end_col,'PAID NON LIFE PREMIUMS',sub_header_format)
    branch_non_life_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    branch_non_life_worksheet.set_column(start_col,start_col,5.00)

    
    branch_non_life_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_non_life_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    branch_non_life_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    branch_non_life_worksheet.conditional_format(row,start_col,end_row,6,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        branch_non_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        branch_non_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        branch_non_life_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        branch_non_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        branch_non_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        branch_non_life_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, premiums)):
    start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 4
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    branch_non_life_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    branch_non_life_worksheet.conditional_format(row,8,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


deficit_tables = [zone_deficit_non_life_table,branch_deficit_non_life_table]

rows = np.cumsum([df.shape[0]+3 for df in deficit_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

deficit_start_col= [premiums[i].shape[1] + 1 if i==0 else premiums[i].shape[1]  for i in range(len(deficit_tables))]

for i,(df, col) in enumerate( zip(deficit_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_non_life_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (deficit_tables):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    

    branch_non_life_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    branch_non_life_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'DEFICIT TARGETS',deficit_header_format)

    branch_non_life_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_non_life_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    # branch_non_life_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    branch_non_life_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})



# write commission dfs to the right of premium dfs
commissions =[zone_comm_non_life_table, branch_non_life_commission_table]

rows = np.cumsum([df.shape[0]+3 for df in commissions])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

comm_start_col= [premiums[i].shape[1] + deficit_tables[i].shape[1] + 1 if i==0 else premiums[i].shape[1] + deficit_tables[i].shape[1] for i in range(len(commissions))]

for i,(df, col) in enumerate( zip(commissions, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = branches_non_life_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,df in enumerate (commissions):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    

    branch_non_life_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    branch_non_life_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'NON LIFE COMMISSIONS',maya_blue_format)

    branch_non_life_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': border_format})
    branch_non_life_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type': 'no_errors', 'format': column_name_format})
    branch_non_life_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    branch_non_life_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

branch_non_life_worksheet.insert_textbox('A1','MENU',menu_format)

# branch_non_life_worksheet.autofit()
branch_non_life_worksheet.set_tab_color(sheet_tab_colour)      
branch_non_life_worksheet.freeze_panes(3,4)
branch_non_life_worksheet.set_zoom(90)


# In[562]:


start_row=3
start_col = 0


branch_vic_life_premium_table.to_excel(weekly_banca_report_writer, sheet_name = branch_vic_sheet_name, index = False, startrow = start_row, startcol=start_col)

branch_vic_worksheet = weekly_banca_report_writer.sheets[branch_vic_sheet_name] 

end_row = branch_vic_life_premium_table.shape[0] + start_row
end_col = branch_vic_life_premium_table.shape[1]  + start_col-1

branch_vic_worksheet.merge_range(start_row-1,2,start_row-1,end_col,'VIC LIFE PREMIUMS',sub_header_format)

branch_vic_worksheet.set_column(start_col,end_col,20.00,None)
# branch_vic_worksheet.set_column(end_col+1,end_col+1,1.00,None)


branch_vic_worksheet.conditional_format(start_row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
branch_vic_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type': 'no_errors', 'format': column_header_format})
branch_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
branch_vic_worksheet.conditional_format(start_row,start_col,end_row,3,{'type': 'no_errors', 'format': grey_format})
branch_vic_worksheet.set_column(start_col+2,end_col,20.00,number_format)

if 'current_month_score' in branch_vic_life_premium_table.columns and 'ytd_score' in branch_vic_life_premium_table.columns:
    mtd_perc_col = branch_vic_life_premium_table.columns.get_loc("current_month_score")
    ytd_perc_col = branch_vic_life_premium_table.columns.get_loc('ytd_score')
    
    branch_vic_worksheet.conditional_format(start_row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
    branch_vic_worksheet.conditional_format(start_row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    branch_vic_worksheet.conditional_format(start_row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
    branch_vic_worksheet.conditional_format(start_row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
    branch_vic_worksheet.conditional_format(start_row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    branch_vic_worksheet.conditional_format(start_row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})


group_end_col =  end_col - 4
# Dynamically create the column range
# column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
branch_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
branch_vic_worksheet.conditional_format(start_row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

    

non_vic_start_col= branch_vic_life_premium_table.shape[1]

branch_vic_non_life_premium_table.to_excel(weekly_banca_report_writer, sheet_name = branch_vic_sheet_name, index = False, startrow = start_row, startcol=non_vic_start_col)


non_vic_end_row = branch_vic_non_life_premium_table.shape[0]+start_row
non_vic_end_col = branch_vic_non_life_premium_table.shape[1]+non_vic_start_col -1



branch_vic_worksheet.set_column(non_vic_start_col,non_vic_end_col,20.00,number_format)
branch_vic_worksheet.merge_range(start_row-1,non_vic_start_col,start_row-1,non_vic_end_col,'VIC NON-LIFE PREMIUMS',column_header_format)

branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col,non_vic_end_row,non_vic_end_col,{'type': 'no_errors', 'format': border_format})
branch_vic_worksheet.conditional_format(start_row,non_vic_start_col,start_row,non_vic_end_col,{'type': 'no_errors', 'format': column_name_format})
branch_vic_worksheet.conditional_format(start_row + 1,non_vic_start_col,non_vic_end_row-1,non_vic_start_col+1,{'type': 'no_errors', 'format': grey_format})
branch_vic_worksheet.conditional_format(non_vic_end_row,non_vic_start_col,non_vic_end_row,non_vic_end_col,{'type': 'no_errors', 'format': total_format})

if 'current_month_score' in branch_vic_non_life_premium_table.columns and 'ytd_score' in branch_vic_non_life_premium_table.columns:
    mtd_perc_col = branch_vic_non_life_premium_table.columns.get_loc("current_month_score")
    ytd_perc_col = branch_vic_non_life_premium_table.columns.get_loc('ytd_score')
    
    branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col+mtd_perc_col,end_row,non_vic_start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
    branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col+mtd_perc_col,end_row,non_vic_start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col+mtd_perc_col,end_row,non_vic_start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
    branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col+ytd_perc_col,end_row,non_vic_start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
    branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col+ytd_perc_col,end_row,non_vic_start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    branch_vic_worksheet.conditional_format(start_row+1,non_vic_start_col+ytd_perc_col,end_row,non_vic_start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
    
non_vic_group_start_col =  non_vic_start_col + 4
non_vic_group_end_col =  non_vic_end_col - 4
# Dynamically create the column range
# column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
branch_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
branch_vic_worksheet.conditional_format(start_row,non_vic_group_start_col,end_row,non_vic_group_end_col,{'type': 'no_errors', 'format': number_format})    
    
# for col_idx, column in enumerate(branch_vic_non_life_premium_table.columns):
#     column_width = max(branch_vic_non_life_premium_table[column].astype(str).apply(len).max(), len(column))
#     branch_vic_worksheet.set_column(col_idx, col_idx, column_width)


branch_vic_worksheet.insert_textbox('A1','MENU',menu_format)

# branch_vic_worksheet.autofit()
branch_vic_worksheet.set_tab_color(sheet_tab_colour)      
branch_vic_worksheet.freeze_panes(4,2)
branch_vic_worksheet.set_zoom(90)


# In[563]:


start_row=3
start_col = 0


branch_vic_premium_table.to_excel(weekly_banca_report_writer, sheet_name = branch_total_vic_premium_table, index = False, startrow = start_row, startcol=start_col)

branch_total_vic_worksheet = weekly_banca_report_writer.sheets[branch_total_vic_premium_table] 

end_row = branch_vic_premium_table.shape[0] + start_row
end_col = branch_vic_premium_table.shape[1]  + start_col-1

branch_total_vic_worksheet.merge_range(start_row-1,2,start_row-1,end_col,'TOTAL VIC PREMIUMS',sub_header_format)

branch_total_vic_worksheet.set_column(start_col,end_col,20.00,None)
# branch_total_vic_worksheet.set_column(end_col+1,end_col+1,1.00,None)


branch_total_vic_worksheet.conditional_format(start_row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
branch_total_vic_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type': 'no_errors', 'format': column_header_format})
branch_total_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
branch_total_vic_worksheet.conditional_format(start_row,start_col,end_row,3,{'type': 'no_errors', 'format': grey_format})
branch_total_vic_worksheet.set_column(start_col+2,end_col,20.00,number_format)

if 'current_month_score' in branch_vic_premium_table.columns and 'ytd_score' in branch_vic_premium_table.columns:
    mtd_perc_col = branch_vic_premium_table.columns.get_loc("current_month_score")
    ytd_perc_col = branch_vic_premium_table.columns.get_loc('ytd_score')
    
    branch_total_vic_worksheet.conditional_format(start_row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
    branch_total_vic_worksheet.conditional_format(start_row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    branch_total_vic_worksheet.conditional_format(start_row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
    branch_total_vic_worksheet.conditional_format(start_row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
    branch_total_vic_worksheet.conditional_format(start_row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    branch_total_vic_worksheet.conditional_format(start_row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})


group_end_col =  end_col - 4
# Dynamically create the column range
# column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
branch_total_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
branch_total_vic_worksheet.conditional_format(start_row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

branch_total_vic_worksheet.insert_textbox('A1','MENU',menu_format)

# branch_vic_worksheet.autofit()
branch_total_vic_worksheet.set_tab_color(sheet_tab_colour)      
branch_total_vic_worksheet.freeze_panes(4,2)
branch_total_vic_worksheet.set_zoom(90)
    


# In[564]:


start_row = 3
start_col= 0

roles_tables =[roles_total_premiums_table,roles_premiums_table,roles_revenue_table,roles_life_premiums_table,roles_vic_table]

rows = np.cumsum([df.shape[0]+4 for df in roles_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, roles_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = roles_summary_sheet_name, index = False, startrow = row, startcol=start_col)

    roles_summary_worksheet = weekly_banca_report_writer.sheets[roles_summary_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    # subject = 'TOTAL PREMIUMS' if i == 0 else ('COLLECTED PREMIUMS' if i == 1 else 'TOTAL REVENUE' if i == 2 else 'VIC PREMIUMS')
    if i == 0: 
        subject = "TOTAL PREMIUMS" 
    elif i == 1: 
        subject = "COLLECTED PREMIUMS" 
    elif i == 2:
        subject = "TOTAL REVENUE" 
    elif i == 3:
        subject = "PAID LIFE PREMIUMS" 
    else: 
        subject = "PAID VIC PREMIUMS"
    roles_summary_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format)  
    # roles_summary_worksheet.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    roles_summary_worksheet.set_column(start_col,end_col,20.00,number_format)
    
    roles_summary_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    roles_summary_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format})
    roles_summary_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    roles_summary_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format})
    
    # roles_summary_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

roles_summary_worksheet.insert_textbox('A1','MENU',menu_format)

roles_summary_worksheet.set_tab_color(sheet_tab_colour)  

roles_summary_worksheet.set_zoom(90)
roles_summary_worksheet.freeze_panes(2,0)

roles_summary_worksheet.hide()


# ### summary products sheet


# In[565]:


# premimum_modified_tables
   
start_row=3
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in premimum_modified_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, premimum_modified_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_paid_premiums_sheet_name, index = False, startrow = row, startcol=start_col)

rm_paid_premiums_worksheet = weekly_banca_report_writer.sheets[rm_paid_premiums_sheet_name] 


for (row, title) in zip(fin_rows,roles):
    rm_paid_premiums_worksheet.merge_range(row-1,0,row-1,1, title, sub_header_format)


for i , (row, df) in enumerate(zip(fin_rows, premimum_modified_tables)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1

    rm_paid_premiums_worksheet.merge_range(row-1,10,row-1,end_col-3,'PAID PREMIUMS',sub_header_format)
    rm_paid_premiums_worksheet.merge_range(row-1,end_col-2,row-1,end_col,'DEFICIT TARGETS',deficit_header_format)
    rm_paid_premiums_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    rm_paid_premiums_worksheet.set_column(start_col,start_col,5.00)
    rm_paid_premiums_worksheet.set_column(end_col+1,end_col+1,2.00)
    
    rm_paid_premiums_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    rm_paid_premiums_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    rm_paid_premiums_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    rm_paid_premiums_worksheet.conditional_format(row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
    
        rm_paid_premiums_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        rm_paid_premiums_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_paid_premiums_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        rm_paid_premiums_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        rm_paid_premiums_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_paid_premiums_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

# for i , (row, df) in enumerate(zip(fin_rows, premimum_modified_tables)):

# start_col =  start_col  + 6 # where months starts
group_end_col =  df.shape[1] + start_col - 6

# Dynamically create the column range
# column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
column_range = f'K:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# column_range = f'H:L'
# Group and hide columns
rm_paid_premiums_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
rm_paid_premiums_worksheet.conditional_format(row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})



comm_start_col= [premimum_modified_tables[i].shape[1]  for i in range(len(merged_commission_tables))]

for i,(df, col) in enumerate( zip(merged_commission_tables, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_paid_premiums_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,merged_commission_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    rm_paid_premiums_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    rm_paid_premiums_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)
    rm_paid_premiums_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    rm_paid_premiums_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    rm_paid_premiums_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    rm_paid_premiums_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})






rm_paid_premiums_worksheet.insert_textbox('A1','MENU',menu_format)
rm_paid_premiums_worksheet.set_tab_color(sheet_tab_colour)    
rm_paid_premiums_worksheet.set_zoom(90)
rm_paid_premiums_worksheet.freeze_panes(3,4)


# In[566]:


# merged_premium_tables ,dsrs_all_premiums_tables

# life_premimum_modified_tables,non_motor_premimum_modified_tables]   
start_row=3
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in life_premimum_modified_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, life_premimum_modified_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_sheet_name, index = False, startrow = row, startcol=start_col)

rm_worksheet = weekly_banca_report_writer.sheets[rm_sheet_name] 


for (row, title) in zip(fin_rows,roles):
    rm_worksheet.merge_range(row-1,0,row-1,1, title, sub_header_format)


for i , (row, df) in enumerate(zip(fin_rows, life_premimum_modified_tables)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1

    rm_worksheet.merge_range(row-1,10,row-1,end_col,'LIFE PREMIUMS',sub_header_format)
    rm_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    rm_worksheet.set_column(start_col,start_col,5.00)
    rm_worksheet.set_column(end_col+1,end_col+1,2.00)
    
    rm_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    rm_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    rm_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    rm_worksheet.conditional_format(row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
    
        rm_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        rm_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        rm_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        rm_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

# for i , (row, df) in enumerate(zip(fin_rows, life_premimum_modified_tables)):

# start_col =  start_col  + 6 # where months starts
group_end_col =  df.shape[1] + start_col - 4

# Dynamically create the column range
# column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
column_range = f'L:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# column_range = f'H:L'
# Group and hide columns
rm_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
rm_worksheet.conditional_format(row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


#### non_motor premiums

non_motor_start_col= [life_premimum_modified_tables[i].shape[1] for i in range(len(merged_non_life_tables))]

rows = np.cumsum([df.shape[0]+3 for df in merged_non_life_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,(df, col) in enumerate( zip(merged_non_life_tables, non_motor_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate(zip (fin_rows, merged_non_life_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = df.shape[1] + non_motor_start_col[i] -1

    rm_worksheet.set_column(non_motor_start_col[i],end_col,20.00,number_format)
    rm_worksheet.merge_range(fin_rows[i]-1,non_motor_start_col[i],fin_rows[i]-1,end_col,'NON-LIFE PREMIUMS',sub_header_format)
    rm_worksheet.conditional_format(fin_rows[i],non_motor_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_header_format}) 
    rm_worksheet.conditional_format(fin_rows[i]+1,non_motor_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    rm_worksheet.conditional_format(end_row,non_motor_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    rm_worksheet.conditional_format(fin_rows[i]+1,non_motor_start_col[i],end_row,non_motor_start_col[i]+2,{'type': 'no_errors', 'format': grey_format})
    rm_worksheet.set_column(end_col+1,end_col+1,2.00)

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        month_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        rm_worksheet.conditional_format(row +1,non_motor_start_col[i]+month_perc_col,end_row,non_motor_start_col[i]+month_perc_col,{'type':'cell','criteria':'<', 'value':0.8, 'format': red_format})
        rm_worksheet.conditional_format(row +1,non_motor_start_col[i]+month_perc_col,end_row,non_motor_start_col[i]+month_perc_col,{'type':'cell','criteria':'>=', 'value':1.0, 'format': green_format})
        rm_worksheet.conditional_format(row +1,non_motor_start_col[i]+month_perc_col,end_row,non_motor_start_col[i]+month_perc_col,{'type':'cell','criteria':'between', 'minimum':0.8, 'maximum':1.0,'format': amber_format})
        rm_worksheet.conditional_format(row +1,non_motor_start_col[i]+ytd_perc_col,end_row,non_motor_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        rm_worksheet.conditional_format(row +1,non_motor_start_col[i]+ytd_perc_col,end_row,non_motor_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_worksheet.conditional_format(row +1,non_motor_start_col[i]+ytd_perc_col,end_row,non_motor_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

group_start_col =  non_motor_start_col[i]  + 5 # where months starts
group_end_col =  df.shape[1] + non_motor_start_col[i] - 4
# Dynamically create the column range
column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
rm_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
rm_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


# deficit tables
deficit_start_col= [merged_non_life_tables[i].shape[1] + life_premimum_modified_tables[i].shape[1] for i in range(len(merged_premium_tables))]
# merged_premium_tables
for i,(df, col) in enumerate( zip(merged_premium_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,merged_premium_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    rm_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    rm_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'DEFICIT TARGETS',deficit_header_format)
    rm_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    # rm_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    rm_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    rm_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    rm_worksheet.set_column(end_col+1,end_col+1,2.00)




# commission tables
comm_start_col= [merged_non_life_tables[i].shape[1] + life_premimum_modified_tables[i].shape[1]+ merged_premium_tables[i].shape[1]  for i in range(len(merged_commission_tables))]

for i,(df, col) in enumerate( zip(merged_commission_tables, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,merged_commission_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    rm_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    rm_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)
    rm_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    rm_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    rm_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    rm_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    
rm_worksheet.insert_textbox('A1','MENU',menu_format)
# rm_worksheet.autofit()
rm_worksheet.set_tab_color(sheet_tab_colour)      
rm_worksheet.freeze_panes(3,4)
rm_worksheet.set_zoom(90)


# In[567]:


# merged_vic_life_nonlife_deficit_tables ,dsrs_all_premiums_tables

# vic_life_premimum_modified_tables,non_vic_premimum_modified_tables]   
start_row=3
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in vic_life_premimum_modified_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, vic_life_premimum_modified_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_vic_sheet_name, index = False, startrow = row, startcol=start_col)

rm_vic_worksheet = weekly_banca_report_writer.sheets[rm_vic_sheet_name] 


for (row, title) in zip(fin_rows,roles):
    rm_vic_worksheet.merge_range(row-1,0,row-1,1, title, sub_header_format)


for i , (row, df) in enumerate(zip(fin_rows, vic_life_premimum_modified_tables)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1

    rm_vic_worksheet.merge_range(row-1,2,row-1,end_col,'VIC LIFE PREMIUMS',deficit_header_format)
    rm_vic_worksheet.set_column(start_col,end_col,20.00,number_format)
    rm_vic_worksheet.set_column(end_col+1,end_col+1,1.00)

    rm_vic_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    rm_vic_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    rm_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    rm_vic_worksheet.conditional_format(row,start_col,end_row,3,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
    
        rm_vic_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        rm_vic_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_vic_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        rm_vic_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        rm_vic_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_vic_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

    
    # rm_vic_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    # rm_vic_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    # rm_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    # rm_vic_worksheet.conditional_format(row,start_col,end_row,start_col+1,{'type': 'no_errors', 'format': grey_format})

# # for i , (row, df) in enumerate(zip(fin_rows, vic_life_premimum_modified_tables)):

# start_col =  start_col  + 6 # where months starts
group_end_col =  df.shape[1] + start_col - 4

# Dynamically create the column range
# column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# column_range = f'H:L'
# Group and hide columns
rm_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
rm_vic_worksheet.conditional_format(row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


#### non_motor premiums

non_vic_start_col= [vic_life_premimum_modified_tables[i].shape[1] for i in range(len(merged_vic_nonlife_tables))]

rows = np.cumsum([df.shape[0]+3 for df in merged_vic_nonlife_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,(df, col) in enumerate( zip(merged_vic_nonlife_tables, non_vic_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_vic_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate(zip (fin_rows, merged_vic_nonlife_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = df.shape[1] + non_vic_start_col[i] -1

    rm_vic_worksheet.set_column(non_vic_start_col[i],end_col,20.00,number_format)
    rm_vic_worksheet.merge_range(fin_rows[i]-1,non_vic_start_col[i],fin_rows[i]-1,end_col,'VIC NON-LIFE PREMIUMS',deficit_header_format)
    # rm_vic_worksheet.conditional_format(fin_rows[i],non_vic_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_header_format}) 
    # rm_vic_worksheet.conditional_format(fin_rows[i]+1,non_vic_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    # rm_vic_worksheet.conditional_format(end_row,non_vic_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    # rm_vic_worksheet.set_column(end_col+1,end_col+1,1.00)
    rm_vic_worksheet.conditional_format(fin_rows[i],non_vic_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_header_format}) 
    rm_vic_worksheet.conditional_format(fin_rows[i]+1,non_vic_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    rm_vic_worksheet.conditional_format(end_row,non_vic_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    rm_vic_worksheet.conditional_format(fin_rows[i]+1,non_vic_start_col[i],end_row,non_vic_start_col[i]+2,{'type': 'no_errors', 'format': grey_format})
    rm_vic_worksheet.set_column(end_col+1,end_col+1,0.00)

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        month_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        rm_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+month_perc_col,end_row,non_vic_start_col[i]+month_perc_col,{'type':'cell','criteria':'<', 'value':0.8, 'format': red_format})
        rm_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+month_perc_col,end_row,non_vic_start_col[i]+month_perc_col,{'type':'cell','criteria':'>=', 'value':1.0, 'format': green_format})
        rm_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+month_perc_col,end_row,non_vic_start_col[i]+month_perc_col,{'type':'cell','criteria':'between', 'minimum':0.8, 'maximum':1.0,'format': amber_format})
        rm_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+ytd_perc_col,end_row,non_vic_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        rm_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+ytd_perc_col,end_row,non_vic_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        rm_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+ytd_perc_col,end_row,non_vic_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

group_start_col =  non_vic_start_col[i]  + 5 # where months starts
group_end_col =  df.shape[1] + non_vic_start_col[i] - 4
# Dynamically create the column range
column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
rm_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
rm_vic_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})
  

# group_start_col =  non_vic_start_col[i] 
# group_end_col =  df.shape[1] + non_vic_start_col[i] - 2
# # Dynamically create the column range
# column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# # Group and hide columns
# rm_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
# rm_vic_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


# deficit tables
deficit_start_col= [merged_vic_nonlife_tables[i].shape[1] + vic_life_premimum_modified_tables[i].shape[1]  for i in range(len(merged_vic_life_nonlife_deficit_tables))]
# merged_vic_life_nonlife_deficit_tables
for i,(df, col) in enumerate( zip(merged_vic_life_nonlife_deficit_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = rm_vic_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,merged_vic_life_nonlife_deficit_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    rm_vic_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    rm_vic_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'VIC DEFICIT TARGETS',deficit_header_format)
    rm_vic_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    # rm_vic_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    rm_vic_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    rm_vic_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})


rm_vic_worksheet.insert_textbox('A1','MENU',menu_format)

# # commission tables
# comm_start_col= [merged_vic_nonlife_tables[i].shape[1] + vic_life_premimum_modified_tables[i].shape[1]+ merged_vic_life_nonlife_deficit_tables[i].shape[1] + 3 for i in range(len(merged_commission_tables))]

# for i,(df, col) in enumerate( zip(merged_commission_tables, comm_start_col)):
#     df.to_excel(weekly_banca_report_writer, sheet_name = rm_vic_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

# for i,(row,df) in enumerate (zip(fin_rows,merged_commission_tables)):
#     end_row = df.shape[0]+fin_rows[i]
#     end_col = comm_start_col[i]+ df.shape[1]-1

#     rm_vic_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
#     rm_vic_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)
#     rm_vic_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
#     rm_vic_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
#     rm_vic_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
#     rm_vic_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

# rm_vic_worksheet.autofit()
rm_vic_worksheet.set_tab_color(sheet_tab_colour)      
rm_vic_worksheet.freeze_panes(3,2)
rm_vic_worksheet.set_zoom(90)


# ### dsr vic sheets


# In[568]:


premimum_dsr_tables


start_row = 3
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in premimum_dsr_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, premimum_dsr_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_all_premiums_sheet_name, index = False, startrow = row, startcol=start_col)

dsr_all_premiums_worksheet = weekly_banca_report_writer.sheets[dsr_all_premiums_sheet_name] 

for (row, title) in zip(fin_rows,dsr_roles):
    dsr_all_premiums_worksheet.merge_range(row-1,0,row-1,1, title, sub_header_format)

for i , (row, df) in enumerate(zip(fin_rows, premimum_dsr_tables)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1

    dsr_all_premiums_worksheet.merge_range(row-1,2,row-1,end_col,'PAID PREMIUMS',sub_header_format)
    dsr_all_premiums_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    dsr_all_premiums_worksheet.set_column(start_col,start_col,9.00)
    dsr_all_premiums_worksheet.set_column(end_col+1,end_col+1,2.00)
    
    dsr_all_premiums_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    dsr_all_premiums_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    dsr_all_premiums_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    dsr_all_premiums_worksheet.conditional_format(row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')

        dsr_all_premiums_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        dsr_all_premiums_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_all_premiums_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        dsr_all_premiums_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        dsr_all_premiums_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_all_premiums_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
   

group_end_col =  df.shape[1] + start_col - 6

# Dynamically create the column range
# column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
column_range = f'K:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# column_range = f'H:L'
# Group and hide columns
dsr_all_premiums_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
dsr_all_premiums_worksheet.conditional_format(row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


# commission tables
comm_start_col= [premimum_dsr_tables[i].shape[1] for i in range(len(dsrs_commission_tables))]

for i,(df, col) in enumerate( zip(dsrs_commission_tables, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_all_premiums_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,dsrs_commission_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    dsr_all_premiums_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    dsr_all_premiums_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)
    dsr_all_premiums_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    dsr_all_premiums_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    dsr_all_premiums_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    dsr_all_premiums_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})            
            
            
            
dsr_all_premiums_worksheet.insert_textbox('A1','MENU',menu_format)
dsr_all_premiums_worksheet.set_tab_color(sheet_tab_colour)    
dsr_all_premiums_worksheet.insert_textbox('A1','MENU',menu_format)
dsr_all_premiums_worksheet.set_zoom(90)
dsr_all_premiums_worksheet.freeze_panes(3,4)


# In[569]:


start_row = 3
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in life_premimum_dsr_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, life_premimum_dsr_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_sheet_name, index = False, startrow = row, startcol=start_col)

dsr_worksheet = weekly_banca_report_writer.sheets[dsr_sheet_name] 

for (row, title) in zip(fin_rows,dsr_roles):
    dsr_worksheet.merge_range(row-1,0,row-1,1, title, sub_header_format)

for i , (row, df) in enumerate(zip(fin_rows, life_premimum_dsr_tables)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1

    dsr_worksheet.merge_range(row-1,10,row-1,end_col,'LIFE PREMIUMS',sub_header_format)
    dsr_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    dsr_worksheet.set_column(start_col,start_col,5.00)
    dsr_worksheet.set_column(end_col+1,end_col+1,2.00)
    
    dsr_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    dsr_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    dsr_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    dsr_worksheet.conditional_format(row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')

        dsr_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        dsr_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        # dsr_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'no_errors', 'format': ytd_grey_format})
        dsr_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        dsr_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})


# banca dsrs total premiums

for i,df in enumerate(life_premimum_dsr_tables):

    total_start_row = fin_rows[-1] + life_premimum_dsr_tables[-1].shape[0] + 3
banca_dsr_total_premiums.to_excel(weekly_banca_report_writer, index=False, sheet_name= dsr_sheet_name, startrow=total_start_row, startcol=start_col)
  

end_row = banca_dsr_total_premiums.shape[0]+total_start_row
end_col = banca_dsr_total_premiums.shape[1]-1


dsr_worksheet.set_column(start_col+1,end_col,20.00,number_format)
dsr_worksheet.set_column(start_col,start_col,5.00)
dsr_worksheet.set_column(end_col+1,end_col+1,2.00)
dsr_worksheet.merge_range(total_start_row-1,10,total_start_row-1,end_col,'TOTAL PREMIUMS',sub_header_format)

dsr_worksheet.conditional_format(total_start_row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
dsr_worksheet.conditional_format(total_start_row,start_col,total_start_row,end_col,{'type': 'no_errors', 'format': column_header_format})
dsr_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
dsr_worksheet.conditional_format(total_start_row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})

if 'current_month_score' in banca_dsr_total_premiums.columns and 'ytd_score' in banca_dsr_total_premiums.columns:
    mtd_perc_col = df.columns.get_loc('current_month_score')
    ytd_perc_col = df.columns.get_loc('ytd_score')

    dsr_worksheet.conditional_format(total_start_row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
    dsr_worksheet.conditional_format(total_start_row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    dsr_worksheet.conditional_format(total_start_row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
    # dsr_worksheet.conditional_format(total_start_row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'no_errors', 'format': ytd_grey_format})
    dsr_worksheet.conditional_format(total_start_row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
    dsr_worksheet.conditional_format(total_start_row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
    dsr_worksheet.conditional_format(total_start_row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})



group_end_col =  df.shape[1] + start_col - 4
# Dynamically create the column range
column_range = f'L:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
dsr_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
dsr_worksheet.conditional_format(row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})


    
#### non_motor premiums

non_motor_start_col= [life_premimum_dsr_tables[i].shape[1]  for i in range(len(dsrs_non_life_tables))]

rows = np.cumsum([df.shape[0]+3 for df in dsrs_non_life_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,(df, col) in enumerate( zip(dsrs_non_life_tables, non_motor_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate(zip (fin_rows, dsrs_non_life_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = df.shape[1] + non_motor_start_col[i] -1

    dsr_worksheet.set_column(non_motor_start_col[i],end_col,20.00,number_format)
    dsr_worksheet.merge_range(fin_rows[i]-1,non_motor_start_col[i],fin_rows[i]-1,end_col,'NON-LIFE PREMIUMS',sub_header_format)
    dsr_worksheet.conditional_format(fin_rows[i],non_motor_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_header_format}) 
    dsr_worksheet.conditional_format(fin_rows[i]+1,non_motor_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    dsr_worksheet.conditional_format(end_row,non_motor_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    dsr_worksheet.conditional_format(fin_rows[i]+1,non_motor_start_col[i],end_row,non_motor_start_col[i]+2,{'type': 'no_errors', 'format': grey_format})
    dsr_worksheet.set_column(end_col+1,end_col+1,2.00)

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        month_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        dsr_worksheet.conditional_format(row +1,non_motor_start_col[i]+month_perc_col,end_row,non_motor_start_col[i]+month_perc_col,{'type':'cell','criteria':'<', 'value':0.8, 'format': red_format})
        dsr_worksheet.conditional_format(row +1,non_motor_start_col[i]+month_perc_col,end_row,non_motor_start_col[i]+month_perc_col,{'type':'cell','criteria':'>=', 'value':1.0, 'format': green_format})
        dsr_worksheet.conditional_format(row +1,non_motor_start_col[i]+month_perc_col,end_row,non_motor_start_col[i]+month_perc_col,{'type':'cell','criteria':'between', 'minimum':0.8, 'maximum':1.0,'format': amber_format})
        dsr_worksheet.conditional_format(row +1,non_motor_start_col[i]+ytd_perc_col,end_row,non_motor_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        dsr_worksheet.conditional_format(row +1,non_motor_start_col[i]+ytd_perc_col,end_row,non_motor_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_worksheet.conditional_format(row +1,non_motor_start_col[i]+ytd_perc_col,end_row,non_motor_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

group_start_col =  non_motor_start_col[i] +5
group_end_col =  df.shape[1] + non_motor_start_col[i] - 4
# Dynamically create the column range
column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
dsr_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
dsr_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

    

# deficit tables
deficit_start_col= [dsrs_non_life_tables[i].shape[1] + life_premimum_dsr_tables[i].shape[1] for i in range(len(dsrs_all_premiums_tables))]

for i,(df, col) in enumerate( zip(dsrs_all_premiums_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,dsrs_all_premiums_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    dsr_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    dsr_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'DEFICIT TARGETS',deficit_header_format)
    dsr_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    # dsr_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    dsr_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    dsr_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    dsr_worksheet.set_column(end_col+1,end_col+1,2.00)





# commission tables
comm_start_col= [dsrs_non_life_tables[i].shape[1] + life_premimum_dsr_tables[i].shape[1] + dsrs_all_premiums_tables[i].shape[1] for i in range(len(dsrs_commission_tables))]

for i,(df, col) in enumerate( zip(dsrs_commission_tables, comm_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,dsrs_commission_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = comm_start_col[i]+ df.shape[1]-1

    dsr_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
    dsr_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)
    dsr_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    dsr_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    dsr_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    dsr_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

dsr_worksheet.insert_textbox('A1','MENU',menu_format)

# dsr_worksheet.autofit()
dsr_worksheet.set_tab_color(sheet_tab_colour)      
dsr_worksheet.freeze_panes(2,4)
dsr_worksheet.set_zoom(90)


# In[ ]:

























# In[ ]:
























# In[570]:


# vic_life_premimum_dsr_tables,dsrs_vic_non_life_tables,dsrs_vic_life_nonlife_deficit_tables

start_row = 3
start_col = 0

rows = np.cumsum([df.shape[0]+3 for df in vic_life_premimum_dsr_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, vic_life_premimum_dsr_tables)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_vic_sheet_name, index = False, startrow = row, startcol=start_col)

dsr_vic_worksheet = weekly_banca_report_writer.sheets[dsr_vic_sheet_name] 


for (row, title) in zip(fin_rows,dsr_roles):
    dsr_vic_worksheet.merge_range(row-1,0,row-1,1, title, sub_header_format)

for i , (row, df) in enumerate(zip(fin_rows, vic_life_premimum_dsr_tables)):
    end_row = df.shape[0]+row
    end_col = df.shape[1]-1

    dsr_vic_worksheet.merge_range(row-1,2,row-1,end_col,'VIC LIFE PREMIUMS',deficit_header_format)
    dsr_vic_worksheet.set_column(start_col+1,end_col,20.00,number_format)
    dsr_vic_worksheet.set_column(end_col+1,end_col+1,2.00)
    
    # dsr_vic_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    # dsr_vic_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    # dsr_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    # dsr_vic_worksheet.conditional_format(row,start_col,end_row,start_col+1,{'type': 'no_errors', 'format': grey_format})


    dsr_vic_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
    dsr_vic_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': column_header_format})
    dsr_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
    dsr_vic_worksheet.conditional_format(row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})
    
    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
    
        dsr_vic_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format})
        dsr_vic_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_vic_worksheet.conditional_format(row+1,mtd_perc_col+ start_col,end_row,mtd_perc_col+ start_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})
        # dsr_vic_worksheet.conditional_format(row+1,ytd_perc_col+ start_col,end_row,ytd_perc_col+ start_col,{'type': 'no_errors', 'format': ytd_grey_format})



group_end_col =  df.shape[1] + start_col - 4
# Dynamically create the column range
column_range = f'I:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
dsr_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
dsr_vic_worksheet.conditional_format(row,11,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

# # banca dsrs total premiums

# for i,df in enumerate(vic_life_premimum_dsr_tables):

#     total_start_row = fin_rows[-1] + vic_life_premimum_dsr_tables[-1].shape[0] + 3
# banca_dsr_total_premiums.to_excel(weekly_banca_report_writer, index=False, sheet_name= dsr_vic_sheet_name, startrow=total_start_row, startcol=start_col)
  

# end_row = banca_dsr_total_premiums.shape[0]+total_start_row
# end_col = banca_dsr_total_premiums.shape[1]-1


# dsr_vic_worksheet.set_column(start_col+1,end_col,20.00,number_format)
# dsr_vic_worksheet.set_column(start_col,start_col,5.00)
# dsr_vic_worksheet.set_column(end_col+1,end_col+1,2.00)
# dsr_vic_worksheet.merge_range(total_start_row-1,10,total_start_row-1,end_col,'TOTAL PREMIUMS',sub_header_format)

# dsr_vic_worksheet.conditional_format(total_start_row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
# dsr_vic_worksheet.conditional_format(total_start_row,start_col,total_start_row,end_col,{'type': 'no_errors', 'format': column_header_format})
# dsr_vic_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format})
# dsr_vic_worksheet.conditional_format(total_start_row,start_col,end_row,5,{'type': 'no_errors', 'format': grey_format})



    
#### non_motor premiums

non_vic_start_col= [vic_life_premimum_dsr_tables[i].shape[1] for i in range(len(dsrs_vic_non_life_tables))]

rows = np.cumsum([df.shape[0]+3 for df in dsrs_vic_non_life_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,(df, col) in enumerate( zip(dsrs_vic_non_life_tables, non_vic_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_vic_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate(zip (fin_rows, dsrs_vic_non_life_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = df.shape[1] + non_vic_start_col[i] -1

    dsr_vic_worksheet.set_column(non_vic_start_col[i],end_col,20.00,number_format)
    dsr_vic_worksheet.merge_range(fin_rows[i]-1,non_vic_start_col[i],fin_rows[i]-1,end_col,'VIC NON-LIFE PREMIUMS',deficit_header_format)
    dsr_vic_worksheet.conditional_format(fin_rows[i],non_vic_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_header_format}) 
    dsr_vic_worksheet.conditional_format(fin_rows[i]+1,non_vic_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    dsr_vic_worksheet.conditional_format(end_row,non_vic_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})
    dsr_vic_worksheet.conditional_format(fin_rows[i]+1,non_vic_start_col[i],end_row -1,non_vic_start_col[i]+2,{'type': 'no_errors', 'format': grey_format})
    dsr_vic_worksheet.set_column(end_col+1,end_col+1,2.00)

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        month_perc_col = df.columns.get_loc('current_month_score')
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        dsr_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+month_perc_col,end_row,non_vic_start_col[i]+month_perc_col,{'type':'cell','criteria':'<', 'value':0.8, 'format': red_format})
        dsr_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+month_perc_col,end_row,non_vic_start_col[i]+month_perc_col,{'type':'cell','criteria':'>=', 'value':1.0, 'format': green_format})
        dsr_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+month_perc_col,end_row,non_vic_start_col[i]+month_perc_col,{'type':'cell','criteria':'between', 'minimum':0.8, 'maximum':1.0,'format': amber_format})
        dsr_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+ytd_perc_col,end_row,non_vic_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        dsr_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+ytd_perc_col,end_row,non_vic_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        dsr_vic_worksheet.conditional_format(row +1,non_vic_start_col[i]+ytd_perc_col,end_row,non_vic_start_col[i]+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

group_start_col =  non_vic_start_col[i] +5
group_end_col =  df.shape[1] + non_vic_start_col[i] - 4
# Dynamically create the column range
column_range = f'{xlsxwriter.utility.xl_col_to_name(group_start_col)}:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
# Group and hide columns
dsr_vic_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
dsr_vic_worksheet.conditional_format(row,group_start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format})

    

# deficit tables
deficit_start_col= [dsrs_vic_non_life_tables[i].shape[1] + vic_life_premimum_dsr_tables[i].shape[1] for i in range(len(dsrs_vic_life_nonlife_deficit_tables))]

for i,(df, col) in enumerate( zip(dsrs_vic_life_nonlife_deficit_tables, deficit_start_col)):
    df.to_excel(weekly_banca_report_writer, sheet_name = dsr_vic_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

for i,(row,df) in enumerate (zip(fin_rows,dsrs_vic_life_nonlife_deficit_tables)):
    end_row = df.shape[0]+fin_rows[i]
    end_col = deficit_start_col[i]+ df.shape[1]-1

    dsr_vic_worksheet.set_column(deficit_start_col[i],end_col,20.00,number_format)
    dsr_vic_worksheet.merge_range(fin_rows[i]-1,deficit_start_col[i],fin_rows[i]-1,end_col,'VIC DEFICIT TARGETS',deficit_header_format)
    dsr_vic_worksheet.conditional_format(fin_rows[i],deficit_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
    # dsr_vic_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
    dsr_vic_worksheet.conditional_format(fin_rows[i]+1,deficit_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
    dsr_vic_worksheet.conditional_format(end_row,deficit_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})



dsr_vic_worksheet.insert_textbox('A1','MENU',menu_format)

# # commission tables
# comm_start_col= [dsrs_vic_non_life_tables[i].shape[1] + vic_life_premimum_dsr_tables[i].shape[1] + dsrs_vic_life_nonlife_deficit_tables[i].shape[1]+ 3 for i in range(len(dsrs_commission_tables))]

# for i,(df, col) in enumerate( zip(dsrs_commission_tables, comm_start_col)):
#     df.to_excel(weekly_banca_report_writer, sheet_name = dsr_vic_sheet_name, index = False, startrow = fin_rows[i], startcol=col)

# for i,(row,df) in enumerate (zip(fin_rows,dsrs_commission_tables)):
#     end_row = df.shape[0]+fin_rows[i]
#     end_col = comm_start_col[i]+ df.shape[1]-1

#     dsr_vic_worksheet.set_column(comm_start_col[i],end_col,20.00,number_format)
#     dsr_vic_worksheet.merge_range(fin_rows[i]-1,comm_start_col[i],fin_rows[i]-1,end_col,'COMMISSIONS',maya_blue_format)
#     dsr_vic_worksheet.conditional_format(fin_rows[i],comm_start_col[i],fin_rows[i],end_col,{'type':'no_errors','format':column_name_format})
#     dsr_vic_worksheet.conditional_format(fin_rows[i],end_col,end_row-1,end_col,{'type': 'no_errors', 'format': lavender_format})
    
#     dsr_vic_worksheet.conditional_format(fin_rows[i]+1,comm_start_col[i],end_row,end_col,{'type':'no_errors','format': border_format})
#     dsr_vic_worksheet.conditional_format(end_row,comm_start_col[i],end_row,end_col,{'type': 'no_errors', 'format': total_format})

# dsr_vic_worksheet.autofit()
dsr_vic_worksheet.set_tab_color(sheet_tab_colour)      
dsr_vic_worksheet.freeze_panes(3,3)
dsr_vic_worksheet.set_zoom(90)


# In[571]:


# comm_start_col= [premiums[i].shape[1] + deficit_tables[i].shape[1] + 4]
# comm_start_col


# ### RMs sheet


# In[572]:


# #### DSRs sheet


# In[ ]:































# In[573]:


##ment_tables


# In[574]:


total_start_row


# #### Banca sales data sheet


# In[575]:


sales_report_columns_to_keep =['r_number', 'sales_type', 'insured', 'email', 'underwriter',
       'policy_no', 'product', 'starting_date', 'ending_date', 'sum_insured',
       'total_premiums', 'paid_premiums', 'balance', 'commission', 'branch',
       'sales_person', 'code', 'rm', 'month', 'month_name',
       'branch_name', 'zone','life_policy_check', 'vic_check','premium_type','staff_role','segment','segment_2','underwiter_mapping_to_britam','paid_premiums_prev']
sales_report =sales_report[sales_report_columns_to_keep]


# In[576]:


#BANCA DATA SHEET

start_col = 0
start_row = 2
end_row = sales_report.shape[0] + start_row
end_col = sales_report.shape[1] + start_col - 1
        
sales_report.to_excel(weekly_banca_report_writer, sheet_name = banca_data_sheet_name, index = False, startrow = start_row, startcol=start_col)

sales_worksheet = weekly_banca_report_writer.sheets[banca_data_sheet_name] 

sales_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format})
sales_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type': 'no_errors', 'format': column_header_format})
sales_worksheet.conditional_format(start_row,19,end_row,end_col,{'type': 'no_errors', 'format': antique_white})
sales_worksheet.conditional_format(start_row,9,end_row,13,{'type': 'no_errors', 'format': number_format})
sales_worksheet.conditional_format(start_row+1,7,end_row,8,{'type': 'no_errors', 'format': date_format})
sales_worksheet.set_column(start_col,end_col,16.00,None)
sales_worksheet.conditional_format(start_row,end_col,end_row,end_col,{'type': 'no_errors', 'format': number_format})

## set column width
# for col_idx, column in enumerate(sales_report.columns):
#     column_width = max(sales_report[column].astype(str).apply(len).max(), len(column))
#     sales_worksheet.set_column(col_idx, col_idx, column_width)

sales_worksheet.insert_textbox('A1','MENU',menu_format)

column_range = f'{xlsxwriter.utility.xl_col_to_name(end_col-1)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
sales_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
sales_worksheet.set_tab_color(sheet_tab_colour)     

sales_worksheet.freeze_panes(3,3)
sales_worksheet.set_zoom(90)


# In[577]:


# directors workbook


# In[578]:


# segment_vic_sheet_name

directors_segment_vic_tables =[segments_vic_total_premiums_table_with_targets,segments_vic_paid_premiums_table_with_targets,segments_vic_life_table_with_targets,segments_vic_non_life_table_with_targets]

start_row = 0
start_col = 0

rows = np.cumsum([df.shape[0]+4 for df in directors_segment_vic_tables])
fin_rows = [start_row] + [data + start_row for data in rows[:len(rows)-1]]
fin_rows = [int(item) for item in fin_rows]

for i,( row, df) in enumerate(zip(fin_rows, directors_segment_vic_tables)):
    df.to_excel(directors_weekly_banca_report_writer, sheet_name = segment_vic_sheet_name, index = False, startrow = row, startcol=start_col)

    directors_segment_worksheet = directors_weekly_banca_report_writer.sheets[segment_vic_sheet_name] 
    
    end_row = df.shape[0]+ row
    end_col = df.shape[1]-1

    if i==0:
        subject = 'Total Vic Premiums to be collected'
    elif i == 1:
        subject = 'Paid Vic Premiums'
    elif i==2:
        subject = 'Vic Life Premiums'
    else:
        subject = 'Vic non-life Premiums'


        
    directors_segment_worksheet.merge_range(row-1,start_col,row-1,start_col+1,subject,maya_blue_format2)  
    # directors_segment_vic_tables.merge_range(1,6,1,end_col,header_name,sub_header_format)
    
    directors_segment_worksheet.set_column(start_col,end_col,20.00,number_format2)
    
    directors_segment_worksheet.conditional_format(row+1,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format2})
    directors_segment_worksheet.conditional_format(row,start_col,row,end_col,{'type': 'no_errors', 'format': maya_blue_format2})
    directors_segment_worksheet.conditional_format(end_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': total_format2})
    directors_segment_worksheet.conditional_format(row,start_col,end_row,start_col,{'type': 'no_errors', 'format': grey_format2})

    if 'current_month_score' in df.columns and 'ytd_score' in df.columns:
        mtd_perc_col = df.columns.get_loc("current_month_score")
        ytd_perc_col = df.columns.get_loc('ytd_score')
        
        directors_segment_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'<', 'value': 0.8, 'format': red_format2})
        directors_segment_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format2})
        directors_segment_worksheet.conditional_format(row+1,start_col+mtd_perc_col,end_row,start_col+mtd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format2})
        directors_segment_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'<',  'value': 0.8, 'format': red_format})
        directors_segment_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 1.0, 'format': green_format})
        directors_segment_worksheet.conditional_format(row+1,start_col+ytd_perc_col,end_row,start_col+ytd_perc_col,{'type': 'cell','criteria':'>=', 'value': 0.8, 'format': amber_format})

for i , (row, df) in enumerate(zip(fin_rows, directors_segment_vic_tables)):
    # start_col = 0 if i == 1 else 1
    # start_col =  start_col  + 6 # where months starts
    group_end_col =  df.shape[1] + start_col - 6
    
    # Dynamically create the column range
    # column_range = f'{xlsxwriter.utility.xl_col_to_name(start_col)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
    column_range = f'G:{xlsxwriter.utility.xl_col_to_name(group_end_col)}'
    # column_range = f'H:L'
    # Group and hide columns
    directors_segment_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
    directors_segment_worksheet.conditional_format(row,8,end_row,group_end_col,{'type': 'no_errors', 'format': number_format2})
    directors_segment_worksheet.conditional_format(row+1,start_col,end_row,group_end_col,{'type': 'no_errors', 'format': number_format2})


# directors_segment_worksheet.insert_textbox('A1','MENU',menu_format)
directors_segment_worksheet.set_tab_color(sheet_tab_colour)  
directors_segment_worksheet.set_zoom(90)



# In[ ]:











# In[579]:


#BANCA DATA SHEET

start_col = 0
start_row = 0
end_row = sales_report.shape[0] + start_row
end_col = sales_report.shape[1] + start_col - 1
        
sales_report.to_excel(directors_weekly_banca_report_writer, sheet_name = banca_data_sheet_name, index = False, startrow = start_row, startcol=start_col)

directors_sales_worksheet = directors_weekly_banca_report_writer.sheets[banca_data_sheet_name] 

directors_sales_worksheet.conditional_format(start_row,start_col,end_row,end_col,{'type': 'no_errors', 'format': border_format2})
directors_sales_worksheet.conditional_format(start_row,start_col,start_row,end_col,{'type': 'no_errors', 'format': column_header_format2})
directors_sales_worksheet.conditional_format(start_row,19,end_row,end_col,{'type': 'no_errors', 'format': antique_white2})
directors_sales_worksheet.conditional_format(start_row,9,end_row,13,{'type': 'no_errors', 'format': number_format2})
directors_sales_worksheet.conditional_format(start_row+1,7,end_row,8,{'type': 'no_errors', 'format': date_format2})
directors_sales_worksheet.set_column(start_col,end_col,16.00,None)
directors_sales_worksheet.conditional_format(start_row,end_col,end_row,end_col,{'type': 'no_errors', 'format': number_format2})

## set column width
# for col_idx, column in enumerate(sales_report.columns):
#     column_width = max(sales_report[column].astype(str).apply(len).max(), len(column))
#     directors_sales_worksheet.set_column(col_idx, col_idx, column_width)
#
# directors_sales_worksheet.insert_textbox('A1','MENU',menu_format)

column_range = f'{xlsxwriter.utility.xl_col_to_name(end_col-1)}:{xlsxwriter.utility.xl_col_to_name(end_col)}'
directors_sales_worksheet.set_column(column_range, None, None, {'level': 1, 'hidden': True})
directors_sales_worksheet.set_tab_color(sheet_tab_colour)     

directors_sales_worksheet.freeze_panes(1,3)
directors_sales_worksheet.set_zoom(90)


# In[580]:


# premium_sheet_name = 'types'
# banca_type.to_excel('premium_sheet.xlsx', sheet_name =premium_sheet_name , index=False)
# premium_type_worksheet = weekly_banca_report_writer.sheets[premium_sheet_name]


# In[581]:


workbook.close()


# In[582]:


directors_workbook.close()


# In[583]:


# ## Styling for email


# In[584]:


def color_mtd_percentage(val):
    if not isinstance(val, (int, float)):
        return ''
    if val < 0.80:
        return 'background-color: #C0504D; color: red'
    elif val < 1.00:
        return 'background-color: #C69500; color: amber'
    return 'background-color: #70AD47; color: green'

def color_ytd_percentage(val):
    if not isinstance(val, (int, float)):
        return ''
    return 'background-color: #D9D9D9; color: white'


# In[585]:


# def style_subsidiaries_performance(dataframe):
#     format_dict = { col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ["current_month_score",'ytd_score'] }
#     format_dict['ytd_score'] = '{:.0%}'
#     format_dict["current_month_score"]='{:.0%}'
    
#     def style_total_row(s):
#         is_total_row = s.name == (len(dataframe) - 1)
#         styles = [f'background-color: #1B4872; color: white; font-weight: bold' if is_total_row else '' for _ in s]
#         return styles
#     return dataframe.set_index(['SUBSIDIARY']).style \
#           .format(format_dict) \
#           .map(color_mtd_percentage, subset=['current_month_score']) \
#   .map(color_ytd_percentage, subset=['ytd_score']) \
#           .apply(style_total_row, axis=1) \
#           .set_properties(**{
#               'border': '1px solid black',
#               'border-collapse': 'collapse',
#               'border-spacing': '0'
#           }) \
#           .set_table_styles([{
#               'selector': 'th',
#               'props': [
#                   ('border', '2px solid black'),
#                   ('color', 'white'),
#                   ('background-color', '#084B65')
#               ]
#           }, {
#               'selector': '',
#               'props': [
#                     ('border', '2px solid black'),
#                     ('padding', '0 2px'),
#                     ('font-size', '12px')
#               ]
#           }, {
#               'selector': 'tbody > tr:last-child',
#               'props': [
#                   ('border', '1px solid black'),
#                   ('color', 'white'),
#                   ('background-color', '#084B65'),
#                   ('font-weight','bold')
#               ]
#           }])

# style_subsidiaries_performance(subsidiaries_premiums_table)


# In[586]:


def style_subsidiaries_vic_life_performance(dataframe):
    format_dict = { col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ["current_month_score",'ytd_score'] }
    format_dict['ytd_score'] = '{:.0%}'
    format_dict["current_month_score"]='{:.0%}'
    
    def style_total_row(s):
        is_total_row = s.name == (len(dataframe) - 1)
        styles = [f'background-color: #1B4872; color: white; font-weight: bold' if is_total_row else '' for _ in s]
        return styles
    return dataframe.set_index(['SUBSIDIARY']).style \
          .format(format_dict) \
          .map(color_mtd_percentage, subset=['current_month_score']) \
          .map(color_ytd_percentage, subset=['ytd_score']) \
          .apply(style_total_row, axis=1) \
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
                  ('background-color', '#084B65')
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
                  ('background-color', '#084B65'),
                  ('font-weight','bold')
              ]
          }])

style_subsidiaries_vic_life_performance(subsidiaries_vic_life_premiums_table_with_targets_total_row)


# In[587]:


def style_subsidiaries_vic_non_life_performance(dataframe):
    format_dict = { col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ["current_month_score",'ytd_score'] }
    format_dict['ytd_score'] = '{:.0%}'
    format_dict["current_month_score"]='{:.0%}'
    
    def style_total_row(s):
        is_total_row = s.name == (len(dataframe) - 1)
        styles = [f'background-color: #1B4872; color: white; font-weight: bold' if is_total_row else '' for _ in s]
        return styles
    return dataframe.set_index(['SUBSIDIARY']).style \
          .format(format_dict) \
          .map(color_mtd_percentage, subset=['current_month_score']) \
          .map(color_ytd_percentage, subset=['ytd_score']) \
          .apply(style_total_row, axis=1) \
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
                  ('background-color', '#084B65')
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
                  ('background-color', '#084B65'),
                  ('font-weight','bold')
              ]
          }])

style_subsidiaries_vic_non_life_performance(subsidiaries_vic_non_life_premiums_table_with_targets_total_row)


# In[588]:


segments_vic_paid_premiums_table_with_added_britam_with_targets.columns


# In[589]:


def style_segment_vic_paid_premiums(dataframe):
    # format_dict = {col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ["current_month_score",'ytd_score'] }
    format_dict = {col: lambda x: f"{x:,.0f}" for col in dataframe.columns if col not in ['rank','branch','zone',"current_month_score",'ytd_score'] }
    format_dict["current_month_score"]= '{:.0%}'
    format_dict['ytd_score']= '{:.0%}'
    # format_dict['rank']= '{:.0f}'

    def style_total_row(s):
        is_total_row = s.name ==(len(dataframe)-1)
        styles = [ f'background-color:#1B4872, color:white, font-weight:bold' if is_total_row else '' for _ in s]
        return styles
    return dataframe.set_index(['SEGMENT']).style \
        .format(format_dict)\
        .map(color_mtd_percentage, subset=['current_month_score']) \
        .map(color_ytd_percentage, subset=['ytd_score']) \
        .apply(style_total_row, axis = 1)\
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
                  ('background-color', '#084B65')
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
                  ('background-color', '#084B65'),
                  ('font-weight','bold')
              ]
          }])

style_segment_vic_paid_premiums(segments_vic_paid_premiums_table_with_added_britam_with_targets)


# In[590]:


styled_subsidiaries_vic_life_premiums = style_subsidiaries_vic_life_performance(subsidiaries_vic_life_premiums_table_with_targets_total_row)
styled_subsidiaries_vic_non_life_premiums = style_subsidiaries_vic_non_life_performance(subsidiaries_vic_non_life_premiums_table_with_targets_total_row)

# styled_subsidiaries_premiums = style_subsidiaries_performance(subsidiaries_premiums_table)
styled_segment_vic_paid_premiums= style_segment_vic_paid_premiums(segments_vic_paid_premiums_table_with_added_britam_with_targets)


# In[591]:


# #  Sending to directors
# import smtplib
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from email.mime.base import MIMEBase
# from email import encoders

# # from1 = 'Reports.Analytics@hfcb.co.ke'
# from1 = app.hf_email['user']
# list_of_recipients = [
#     'branch.managers@hfcb.co.ke',
#     'branch.operations@hfcb.co.ke',
#     'RetailManagementCommittee@hfcb.co.ke',
#     'Robert.Kibaara@hfcb.co.ke',
#     'SMEBanking@hfcb.co.ke',
#     'SalesAdministration@hfcb.co.ke',
#     'DSR@hfcb.co.ke',
#     'Ultimate.banking@hfcb.co.ke',
#     'CommercialBanking@hfcb.co.ke',
#     'Personal_Banking_Team@hfcb.co.ke',
#     'diaspora@hfcb.co.ke',
#     'Homes@hfcb.co.ke',
#     'fpa@hfcb.co.ke',
#     'hfdiprojectmanagement2@hfcb.co.ke',
#     'diasporabanking@housingfinancekenya.onmicrosoft.com',
#     'Business.Banking@hfcb.co.ke',
#     'DIGITALPAYMENTS@housingfinancekenya.onmicrosoft.com'
# ]
    
    
# cc_list_of_recipients = [
#     'Jeffrey.Ongicho@hfcb.co.ke', 
#     'Kennedy.Njunje@hfcb.co.ke',
#     'Joan.Mugure@hfcb.co.ke',
#     'bancassurance@hfcb.co.ke',
#     'Strategy&BusinessPerformance@hfcb.co.ke'
# ]

# directors_list_of_recipients =['Maureen.Stephyne@hfcb.co.ke','David.Wambugu@hfcb.co.ke']

# address_book = [  
#     'stacy.kendi@hfcb.co.ke',
#     'allan.aswani@hfcb.co.ke',
#      'Reports.Analytics@hfcb.co.ke'
#     ]



# # instance of MIMEMultipart
# os.chdir(path)
# data = MIMEMultipart()
# FILES = os.listdir()
# file_substrings =[
#     'Bancassurance dashboard',
#     'Directors report']

# email_recipients_map = {
#     'Bancassurance dashboard': list_of_recipients,
#     'Directors report': directors_list_of_recipients
# }
# email_cc_recipients_map = {
#     'Bancassurance dashboard': cc_list_of_recipients}
# subject_map= {
#     'Bancassurance dashboard':f'BANCASSURANCE DASHBOARD - {report_date}',
#     'Directors report': f'VIC Summary report - {report_date}'
# }
    

# body = { 
# 'Bancassurance dashboard': """
# <span> Hello Team,</span>
# <br/><br/>
# <span>Please find attached Bancassurance Report.</span>
# <br/><br/>
# <ol>
# <li><b><u>Summary view of Subsidiaries:</u></b><br/>{0}</li><br/>
# <li><b><u>Branch premiums:</u></b><br/>{1}</li><br/>
# </ol>
# <br/>
# <span>
# Kind Regards, <br/>
# Analytics & Business Performance
# </span>
# <br/><br/>
# """.format(
#             styled_subsidiaries_premiums.to_html(),
#             styled_branch_premiums.to_html()
#           ), 
# 'Directors report': """
# <span> Hello Leaders,</span>
# <br/><br/>
# <span>Please find attached VIC report summary.</span>
# <br/><br/>
# <span>
# Kind Regards, <br/>
# Analytics & Business Performance
# </span>
# <br/><br/>
# """}



# for substr in file_substrings:
#     matching_files = [filename for filename in FILES if substr in filename]
#     if matching_files:
#         data = MIMEMultipart()
#         data['From'] = from1
#         data['To'] = ','.join(email_recipients_map[substr])
#         data['CC'] = ','.join(email_cc_recipients_map[substr])
#         data['Subject'] = f"{subject_map[substr]}"
#         body = body[substr]
#         data.attach(MIMEText(body, 'html'))
#         for filename in matching_files:
#             with open(filename, "rb") as attachment:
#                 p = MIMEBase('application', 'octet-stream')
#                 p.set_payload(attachment.read())
#                 encoders.encode_base64(p)
#                 p.add_header('Content-Disposition', f"attachment; filename= {filename}")
#                 data.attach(p)
#         s = smtplib.SMTP(app.hf_email['host'], app.hf_email['port'])
#         s.starttls()
#         s.login(from1, app.hf_email['password'])
#         text = data.as_string()
#         all_recipients = email_recipients_map[substr] + email_cc_recipients_map[substr]
#         s.sendmail(from1, all_recipients, text)
#         print(f"{substr} email sent successfully!")
#         s.quit()


# In[ ]:





# In[592]:


# #previous 
# import smtplib
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from email.mime.base import MIMEBase
# from email import encoders

# from1 = 'Reports.Analytics@hfcb.co.ke'
# list_of_recipients = [
#     'branch.managers@hfcb.co.ke',
#     'branch.operations@hfcb.co.ke',
#     'RetailManagementCommittee@hfcb.co.ke',
#     'Robert.Kibaara@hfcb.co.ke',
#     'SMEBanking@hfcb.co.ke',
#     'SalesAdministration@hfcb.co.ke',
#     'DSR@hfcb.co.ke',
#     'Ultimate.banking@hfcb.co.ke',
#     'CommercialBanking@hfcb.co.ke',
#     'Personal_Banking_Team@hfcb.co.ke',
#     'diaspora@hfcb.co.ke',
#     'Homes@hfcb.co.ke',
#     'fpa@hfcb.co.ke',
#     'hfdiprojectmanagement2@hfcb.co.ke',
#     'diasporabanking@housingfinancekenya.onmicrosoft.com',
#     'Business.Banking@hfcb.co.ke',
#     'DIGITALPAYMENTS@housingfinancekenya.onmicrosoft.com'
# ]
    
    
# cc_list_of_recipients = [
#     'Jeffrey.Ongicho@hfcb.co.ke', 
#     'Kennedy.Njunje@hfcb.co.ke',
#     'Joan.Mugure@hfcb.co.ke',
#     'bancassurance@hfcb.co.ke',
#     'Strategy&BusinessPerformance@hfcb.co.ke'
# ]

# directors_list_of_recipients =['Maureen.Stephyne@hfcb.co.ke','David.Wambugu@hfcb.co.ke']

# address_book = [  
#     'stacy.kendi@hfcb.co.ke',
#     'allan.aswani@hfcb.co.ke',
#      'Reports.Analytics@hfcb.co.ke',
#     ]

# subject_map= {
#     'Bancassurance dashboard':f'BANCASSURANCE DASHBOARD - {report_date}'
#     # 'Directors report': f'VIC Summary report - {report_date}'
# }

# ##to = "Strategy&BusinessPerformance@hfcb.co.ke"

# # instance of MIMEMultipart
# data = MIMEMultipart()

# # storing the senders email address
# data['From'] = from1

# # storing the receivers email address
# # data['To'] = ','.join(address_book)
# data['To'] = ','.join(list_of_recipients)
# data['CC'] = ','.join(cc_list_of_recipients)

# # storing the subject
# data['Subject'] = f'BANCASSURANCE DASHBOARD - {report_date}'

# # string to store the body of the mail
# body =     """
# <span> Hello Team,</span>
# <br/><br/>
# <span>Please find attached Bancassurance Report.</span>
# <br/><br/>
# <ol>
# <li><b><u>Summary view of Subsidiaries:</u></b><br/>{0}</li><br/>
# <li><b><u>Branch premiums:</u></b><br/>{1}</li><br/>
# </ol>
# <br/>
# <span>
# Kind Regards, <br/>
# Analytics & Business Performance
# </span>
# <br/><br/>
# """.format(
#             styled_subsidiaries_premiums.to_html(),
#             styled_branch_premiums.to_html()
#           )
            
# # attach the body with the msg instance
# data.attach(MIMEText(body, 'html'))  # 'plain'
# os.chdir(path)
# FILES = os.listdir()
# name = FILES
# for i in range(len(FILES)):
# # open the file to be sent
#     filename = name[i]
#     attachment = open(FILES[i], 'rb')
# # instance of MIMEBase and named as p
#     p = MIMEBase('application', 'octet-stream')
# # To change the payload into encoded form
#     p.set_payload(attachment.read())
# # encode into base64
#     encoders.encode_base64(p)
#     p.add_header('Content-Disposition', 'attachment; filename= %s'
#                  % filename)
# # attach the instance 'p' to instance 'msg'
#     data.attach(p)
# # creates SMTP session
# s = smtplib.SMTP(app.hf_email['host'], app.hf_email['port'])
# # start TLS for security
# s.starttls()
# # Authentication
# s.login(from1, app.hf_email['password'])
# # Converts the Multipart msg into a string
# text = data.as_string()
# # sending the mail
# # combine all email recipients
# all_recipients = list_of_recipients + cc_list_of_recipients
# s.sendmail(from1, all_recipients, text)
# # terminating the session
# s.quit()


# # In[576]:


# p_conn.close()
#trial combat 
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

# -- CONFIG --------------------------------------------------------------------
from1 = app.hf_email['user']

list_of_recipients = [
    'branch.managers@hfcb.co.ke',
    'branch.operations@hfcb.co.ke',
    'RetailManagementCommittee@hfcb.co.ke',
    'Robert.Kibaara@hfcb.co.ke',
    'SMEBanking@hfcb.co.ke',
    'SalesAdministration@hfcb.co.ke',
    'DSR@hfcb.co.ke',
    'Ultimate.banking@hfcb.co.ke',
    'CommercialBanking@hfcb.co.ke',
    'Personal_Banking_Team@hfcb.co.ke',
    'diaspora@hfcb.co.ke',
    'Homes@hfcb.co.ke',
    'fpa@hfcb.co.ke',
    'hfdiprojectmanagement2@hfcb.co.ke',
    'diasporabanking@housingfinancekenya.onmicrosoft.com',
    'Business.Banking@hfcb.co.ke',
    'DIGITALPAYMENTS@housingfinancekenya.onmicrosoft.com'
]

cc_list_of_recipients = [
    'Jeffrey.Ongicho@hfcb.co.ke',
    'Kennedy.Njunje@hfcb.co.ke',
    'Joan.Mugure@hfcb.co.ke',
    'bancassurance@hfcb.co.ke',
    'Strategy&BusinessPerformance@hfcb.co.ke'
]

directors_list_of_recipients = [
    'Maureen.Stephyne@hfcb.co.ke',
    'David.Wambugu@hfcb.co.ke'
]
address_book = ['Allan.Aswani@hfcb.co.ke','stacy.kendi@hfcb.co.ke','reports.analytics@hfcb.co.ke']

# -- HELPER FUNCTIONS ----------------------------------------------------------
def build_email(from_addr, to_list, cc_list, subject, body_html):
    """Construct a MIMEMultipart email.

    Subject is encoded as UTF-8 via RFC 2047 (email.header.Header) so any
    non-ASCII characters (arrows, accented letters, etc.) do not crash
    msg.as_string() which only accepts ASCII by default.
    """
    from email.header import Header
    msg = MIMEMultipart()
    msg['From']    = from_addr
    msg['To']      = ','.join(to_list)
    msg['CC']      = ','.join(cc_list)
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))
    return msg


def attach_files_filtered(msg, folder_path, keyword):
    """Attach only files whose name contains the given keyword (case-insensitive)."""
    matched = [f for f in os.listdir(folder_path)
               if os.path.isfile(os.path.join(folder_path, f))
               and keyword.lower() in f.lower()]

    if not matched:
        print(f"  [WARNING] No files matched keyword '{keyword}' in {folder_path}")

    for filename in matched:
        filepath = os.path.join(folder_path, filename)
        with open(filepath, 'rb') as attachment:
            p = MIMEBase('application', 'octet-stream')
            p.set_payload(attachment.read())
        encoders.encode_base64(p)
        p.add_header('Content-Disposition', f'attachment; filename={filename}')
        msg.attach(p)
        print(f"  [ATTACHED] {filename}")

    return msg


def send_email(msg, from_addr, to_list, cc_list):
    """Open SMTP connection and dispatch the email."""
    all_recipients = to_list + cc_list
    try:
        s = smtplib.SMTP(app.hf_email['host'], app.hf_email['port'])
        s.starttls()
        s.login(from_addr, app.hf_email['password'])
        s.sendmail(from_addr, all_recipients, msg.as_string())
        s.quit()
        print("  [SENT] '{}' to {} recipient(s)".format(msg['Subject'], len(all_recipients)))
    except Exception as e:
        print(f"  [ERROR] Failed to send '{msg['Subject']}': {e}")


# -- EMAIL SUBJECTS ------------------------------------------------------------
banca_subject = f'BANCASSURANCE DASHBOARD - {report_date}'
vic_subject   = f'VIC Summary Report - {report_date}'


# -- EMAIL BODIES --------------------------------------------------------------
banca_body = """
<span>Hello Team,</span>
<br/><br/>
<span>Please find attached the Bancassurance Report.</span>
<br/><br/>
<ol>
  <li><b><u>Subsidiaries VIC life premiums:</u></b><br/>{0}</li><br/>
  <li><b><u>Subsidiaries VIC non-life premiums:</u></b><br/>{1}</li><br/>
  <li><b><u>Segment VIC premiums:</u></b><br/>{2}</li><br/>
</ol>
<br/>
<span>Kind Regards,<br/>Analytics and Business Performance</span>
<br/><br/>
""".format(
    styled_subsidiaries_vic_life_premiums.to_html(),
    styled_subsidiaries_vic_non_life_premiums.to_html(),
    styled_segment_vic_paid_premiums.to_html()
)

vic_body = """
<span>Dear Director,</span>
<br/><br/>
<span>Please find attached the VIC Summary Report.</span>
<br/><br/>
<span>Kind Regards,<br/>Analytics and Business Performance</span>
<br/><br/>
"""


# -- 1. BANCASSURANCE EMAIL -> list_of_recipients + cc -------------------------
print("\n--- Sending Bancassurance Report ---")
banca_msg = build_email(from1, list_of_recipients, cc_list_of_recipients, banca_subject, banca_body)
# banca_msg = build_email(from1, address_book, [],banca_subject, banca_body)
banca_msg = attach_files_filtered(banca_msg, path, keyword='Bancassurance')
send_email(banca_msg, from1, list_of_recipients, cc_list_of_recipients)
# send_email(banca_msg, from1, address_book, [])


# -- 2. VIC SUMMARY EMAIL -> directors only ------------------------------------
print("\n--- Sending VIC Summary Report ---")
vic_msg = build_email(from1, directors_list_of_recipients, [], vic_subject, vic_body)
# vic_msg = build_email(from1, address_book, [], vic_subject, vic_body)
vic_msg = attach_files_filtered(vic_msg, path, keyword='VIC')
send_email(vic_msg, from1, directors_list_of_recipients, [])
# send_email(vic_msg, from1, address_book, [])

