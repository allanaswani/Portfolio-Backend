from django.db import models


class CeoDepositMovementMonthly(models.Model):
    dates_eom = models.DateField(blank=True, null=True)
    sum = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "ceo_deposit_movement_monthly"


class Accounts(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    account_no = models.CharField(max_length=100)
    account_name = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    current_balance = models.FloatField(blank=True, null=True)
    open_date = models.DateTimeField()
    close_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    opening_branch = models.CharField(max_length=100)
    opened_by = models.CharField(max_length=100, blank=True, null=True)
    current_branch = models.CharField(max_length=100, blank=True, null=True)
    changed_by = models.CharField(max_length=100, blank=True, null=True)
    interest_rate = models.FloatField(blank=True, null=True)
    account_status = models.CharField(max_length=100, blank=True, null=True)
    is_transacting_account = models.BooleanField()
    last_transaction_date = models.DateTimeField(blank=True, null=True)
    product_type = models.CharField(max_length=100)
    interest = models.FloatField(blank=True, null=True)
    interest_start_date = models.DateTimeField(blank=True, null=True)
    interest_end_date = models.DateTimeField(blank=True, null=True)
    eom_date = models.DateTimeField(blank=True, null=True)
    date_created = models.DateTimeField(blank=True, null=True)
    account_type = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "accounts"


class Customers(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    firstname = models.CharField(max_length=100)
    middlename = models.CharField(max_length=50, blank=True, null=True)
    lastname = models.CharField(max_length=100)
    dob = models.DateTimeField()
    email = models.CharField(max_length=100, blank=True, null=True)
    gender = models.CharField(max_length=100)
    national_id = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=100, blank=True, null=True)
    other_phone_numbers = models.CharField(max_length=100, blank=True, null=True)
    open_date = models.DateTimeField()
    last_updated_date = models.DateTimeField(blank=True, null=True)
    branch = models.CharField(max_length=100, blank=True, null=True)
    type = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    segment = models.CharField(max_length=100, blank=True, null=True)
    date_created = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "customers"


class CeoChannelReport(models.Model):
    trx_date = models.DateTimeField(blank=True, null=True)
    trx_channel = models.TextField(blank=True, null=True)
    cust_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "ceo_channel_report"


class TransactionDiary(models.Model):
    tmstamp = models.DateTimeField(blank=True, null=True)
    trx_date = models.DateTimeField(blank=True, null=True)
    trx_unit = models.IntegerField(blank=True, null=True)
    trx_usr = models.CharField(max_length=200, blank=True, null=True)
    trx_usr_sn = models.IntegerField(blank=True, null=True)
    tun_internal_sn = models.IntegerField(blank=True, null=True)
    transaction_ref = models.CharField(max_length=1000, blank=True, null=True)
    product_description = models.CharField(max_length=300, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    id_product = models.IntegerField(blank=True, null=True)
    fk_customercust_id = models.IntegerField(blank=True, null=True)
    national_id = models.CharField(max_length=50, blank=True, null=True)
    mobile_tel = models.CharField(max_length=50, blank=True, null=True)
    account_name = models.CharField(max_length=1000, blank=True, null=True)
    i_id_justific = models.IntegerField(blank=True, null=True)
    justific_name = models.CharField(max_length=1000, blank=True, null=True)
    trx_code = models.IntegerField(blank=True, null=True)
    trx_name = models.CharField(max_length=1000, blank=True, null=True)
    cash_debit = models.FloatField(blank=True, null=True)
    cash_credit = models.FloatField(blank=True, null=True)
    journal_debit = models.FloatField(blank=True, null=True)
    jornal_credit = models.FloatField(blank=True, null=True)
    commission = models.FloatField(blank=True, null=True)
    expense_amount = models.FloatField(blank=True, null=True)
    tax_amount = models.FloatField(blank=True, null=True)
    total_charge = models.FloatField(blank=True, null=True)
    trx_comments = models.CharField(max_length=10000, blank=True, null=True)
    value_date = models.DateTimeField(blank=True, null=True)
    currency_id = models.IntegerField(blank=True, null=True)
    currency = models.CharField(max_length=1000, blank=True, null=True)
    reverse_flag = models.CharField(max_length=1000, blank=True, null=True)
    reversed_trx_flag = models.CharField(max_length=1000, blank=True, null=True)
    channel_id = models.IntegerField(blank=True, null=True)
    chanel_description = models.CharField(max_length=1000, blank=True, null=True)
    datecreated = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "transaction_diary"


class CeoDepositMovement(models.Model):
    banking_segment = models.TextField(blank=True, null=True)
    segment = models.CharField(max_length=100, blank=True, null=True)
    end_previous_year_bal = models.FloatField(blank=True, null=True)
    current_bal = models.FloatField(blank=True, null=True)
    percentage_movement = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "ceo_deposit_movement"


class CeoDepositMovementDaily(models.Model):
    dates_eom = models.DateField(blank=True, null=True)
    sum = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "ceo_deposit_movement_daily"


class Revenue(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField(blank=True, null=True)
    prod_code = models.BigIntegerField(blank=True, null=True)
    brn_code = models.BigIntegerField(blank=True, null=True)
    gl_account = models.TextField(blank=True, null=True)
    trx_unit = models.IntegerField(blank=True, null=True)
    txn_narration = models.TextField(blank=True, null=True)
    trx_date = models.DateTimeField(blank=True, null=True)
    tmstamp = models.DateTimeField(blank=True, null=True)
    trx_ref = models.CharField(max_length=10000, blank=True, null=True)
    justific_desc = models.CharField(max_length=10000, blank=True, null=True)
    sum_dc = models.DecimalField(max_digits=10000, decimal_places=10000, blank=True, null=True)
    income_category = models.CharField(max_length=10000, blank=True, null=True)
    external_gl_account = models.CharField(max_length=10000, blank=True, null=True)
    account_no = models.CharField(max_length=10000, blank=True, null=True)
    id_justific = models.IntegerField(blank=True, null=True)
    justific_descr = models.TextField(blank=True, null=True)
    trx_code = models.IntegerField(blank=True, null=True)
    date_created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "revenue"


class MobileLoanDisbusements(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField(blank=True, null=True)
    loan_account = models.CharField(max_length=40, blank=True, null=True)
    tmstamp = models.DateTimeField(blank=True, null=True)
    loans_program_id = models.IntegerField(blank=True, null=True)
    program_currency = models.IntegerField(blank=True, null=True)
    mobile_tel = models.CharField(max_length=20, blank=True, null=True)
    loan_cd = models.IntegerField(blank=True, null=True)
    agreement_account = models.CharField(max_length=50, blank=True, null=True)
    agreement_cd = models.IntegerField(blank=True, null=True)
    deposit_account = models.CharField(max_length=50, blank=True, null=True)
    deposit_cd = models.IntegerField(blank=True, null=True)
    c_digit = models.IntegerField(blank=True, null=True)
    instant_loan_amount = models.FloatField(blank=True, null=True)
    install_freq = models.IntegerField(blank=True, null=True)
    install_count = models.IntegerField(blank=True, null=True)
    acc_open_dt = models.DateTimeField(blank=True, null=True)
    acc_exp_dt = models.DateTimeField(blank=True, null=True)
    trx_user = models.CharField(max_length=20, blank=True, null=True)
    bankemployee = models.CharField(max_length=50, blank=True, null=True)
    allocation_type = models.CharField(max_length=10, blank=True, null=True)
    collateral_sn = models.CharField(max_length=50, blank=True, null=True)
    application_id = models.CharField(max_length=20, blank=True, null=True)
    loan_capital = models.FloatField(blank=True, null=True)
    loan_interest = models.FloatField(blank=True, null=True)
    loan_expences = models.FloatField(blank=True, null=True)
    loan_commission = models.FloatField(blank=True, null=True)
    deposit_amount = models.FloatField(blank=True, null=True)
    trx_comments = models.CharField(max_length=20, blank=True, null=True)
    sex = models.CharField(max_length=5, blank=True, null=True)
    id_no = models.CharField(max_length=20, blank=True, null=True)
    date_closed = models.DateTimeField(blank=True, null=True)
    cust_name = models.CharField(max_length=300, blank=True, null=True)
    age = models.CharField(max_length=50, blank=True, null=True)
    datetime = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "mobile_loan_disbusements"


class HfCustomer(models.Model):
    cust_id = models.DecimalField(primary_key=True, max_digits=990, decimal_places=5)
    latin_surname = models.TextField(blank=True, null=True)
    mobile_tel = models.TextField(blank=True, null=True)
    id_no = models.TextField(blank=True, null=True)
    e_mail = models.TextField(blank=True, null=True)
    fd = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    ca = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    internal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    mobile = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    mortagage = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    other = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    sa = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    registered_mobile = models.BooleanField(blank=True, null=True)
    total_depost_balance = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    total_loans = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    total_revenue = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    segment = models.TextField(blank=True, null=True)
    active = models.BooleanField(blank=True, null=True)
    date_time_created = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "hf_customer"


class PhoneNumber(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.IntegerField(blank=True, null=True)
    latin_surname = models.TextField(blank=True, null=True)
    first_name = models.TextField(blank=True, null=True)
    mobile_tel = models.TextField(blank=True, null=True)
    mobile_tel2 = models.TextField(blank=True, null=True)
    id_no = models.CharField(max_length=1000, blank=True, null=True)
    e_mail = models.TextField(blank=True, null=True)
    e_mail2 = models.TextField(blank=True, null=True)
    account_number = models.CharField(max_length=1000, blank=True, null=True)
    product_id = models.CharField(max_length=1000, blank=True, null=True)
    date_time_created = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "phone_number"


class AccountsHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    account_no = models.CharField(max_length=100)
    account_name = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    current_balance = models.FloatField(blank=True, null=True)
    open_date = models.DateTimeField()
    close_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    opening_branch = models.CharField(max_length=100)
    opened_by = models.CharField(max_length=100, blank=True, null=True)
    current_branch = models.CharField(max_length=100, blank=True, null=True)
    changed_by = models.CharField(max_length=100, blank=True, null=True)
    interest_rate = models.FloatField(blank=True, null=True)
    account_status = models.CharField(max_length=100, blank=True, null=True)
    is_transacting_account = models.BooleanField()
    last_transaction_date = models.DateTimeField(blank=True, null=True)
    product_type = models.CharField(max_length=100)
    interest = models.FloatField(blank=True, null=True)
    interest_start_date = models.DateTimeField(blank=True, null=True)
    interest_end_date = models.DateTimeField(blank=True, null=True)
    eom_date = models.DateTimeField(blank=True, null=True)
    date_created = models.DateTimeField(blank=True, null=True)
    account_type = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "accounts_history"


class CeoLoanMovementMonthlyBySegment(models.Model):
    segment = models.CharField(max_length=100, blank=True, null=True)
    dates_eom = models.DateTimeField(blank=True, null=True)
    volume = models.BigIntegerField(blank=True, null=True)
    value = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "ceo_loan_movement_monthly_by_segment"
        unique_together = (("segment", "dates_eom", "volume", "value"),)


class CeoDepositMovementMonthlyBySegment(models.Model):
    segment = models.CharField(max_length=100, blank=True, null=True)
    dates_eom = models.DateTimeField(blank=True, null=True)
    volume = models.BigIntegerField(blank=True, null=True)
    value = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "ceo_deposit_movement_monthly_by_segment"
        unique_together = (("segment", "dates_eom", "volume", "value"),)


class DailyBalanceMovement(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_cif = models.BigIntegerField(blank=True, null=True)
    acc_num = models.CharField(max_length=100, blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    prod_id = models.IntegerField(blank=True, null=True)
    customer_segment = models.CharField(max_length=100, blank=True, null=True)
    financial_sector = models.CharField(max_length=100, blank=True, null=True)
    activity_sector = models.CharField(max_length=100, blank=True, null=True)
    segment_code = models.CharField(max_length=100, blank=True, null=True)
    dec_24_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    mar_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jun_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    sep_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    dec_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jan_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    feb_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    mar_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    apr_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    may_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jun_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jul_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    aug_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    sep_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    oct_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    nov_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    dec_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    yester_2_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    yester_1_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    rm_code = models.CharField(max_length=100, blank=True, null=True)
    diaspora_check = models.CharField(max_length=100, blank=True, null=True)
    open_date = models.DateTimeField(blank=True, null=True)
    sale_code = models.CharField(max_length=100, blank=True, null=True)
    full_name = models.CharField(max_length=100, blank=True, null=True)
    etl_date_updated = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "daily_balance_movement"


class LoanDailyBalanceMovement(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_cif = models.BigIntegerField(blank=True, null=True)
    acc_num = models.CharField(max_length=100, blank=True, null=True)
    ccy = models.CharField(max_length=100, blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    prod_id = models.IntegerField(blank=True, null=True)
    customer_segment = models.CharField(max_length=100, blank=True, null=True)
    financial_sector = models.CharField(max_length=100, blank=True, null=True)
    activity_sector = models.CharField(max_length=100, blank=True, null=True)
    segment_code = models.CharField(max_length=100, blank=True, null=True)
    dec_24_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    mar_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jun_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    sep_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    dec_25_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jan_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    feb_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    mar_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    apr_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    may_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jun_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    jul_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    aug_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    sep_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    oct_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    nov_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    dec_26_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    yester_2_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    yester_1_bal = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    rm_code = models.CharField(max_length=100, blank=True, null=True)
    diaspora_check = models.CharField(max_length=100, blank=True, null=True)
    open_date = models.DateTimeField(blank=True, null=True)
    sale_code = models.CharField(max_length=100, blank=True, null=True)
    full_name = models.CharField(max_length=100, blank=True, null=True)
    etl_date_updated = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "loan_daily_balance_movement"


class EmployeeTable(models.Model):
    id = models.BigAutoField(primary_key=True)
    staff_id = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    national_id = models.CharField(max_length=100, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateTimeField(blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)
    gender = models.TextField(blank=True, null=True)
    date_of_employment = models.DateTimeField(blank=True, null=True)
    service_code = models.TextField(blank=True, null=True)
    service_years = models.IntegerField(blank=True, null=True)
    division = models.TextField(blank=True, null=True)
    department = models.TextField(blank=True, null=True)
    unit = models.TextField(blank=True, null=True)
    org_unit = models.TextField(blank=True, null=True)
    grade = models.TextField(blank=True, null=True)
    job_title = models.TextField(blank=True, null=True)
    exit = models.IntegerField(blank=True, null=True)
    promotion = models.IntegerField(blank=True, null=True)
    new = models.IntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "employee_table"


class LoansHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    loan_account_no = models.CharField(max_length=20)
    loan_open_date = models.DateTimeField(blank=True, null=True)
    account_no = models.CharField(max_length=20)
    loan_product = models.CharField(max_length=20)
    currency = models.CharField(max_length=20)
    euro_book_balance = models.FloatField()
    interest = models.FloatField()
    facility_fees = models.FloatField()
    first_drawn_down_amount = models.FloatField(blank=True, null=True)
    first_drawn_down_date = models.DateTimeField(blank=True, null=True)
    capital_balance_amount = models.FloatField(blank=True, null=True)
    previous_installment_date = models.DateTimeField(blank=True, null=True)
    next_installment_date = models.DateTimeField(blank=True, null=True)
    last_transaction_date = models.DateTimeField(blank=True, null=True)
    total_commisions = models.FloatField(blank=True, null=True)
    total_penalties = models.FloatField(blank=True, null=True)
    total_interest_collected = models.FloatField(blank=True, null=True)
    open_date = models.DateTimeField(blank=True, null=True)
    close_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, blank=True, null=True)
    penalty_interest_rate = models.FloatField(blank=True, null=True)
    branch = models.IntegerField(blank=True, null=True)
    sector = models.CharField(max_length=100, blank=True, null=True)
    total_arrears = models.FloatField(blank=True, null=True)
    days_in_arrears = models.IntegerField(blank=True, null=True)
    capital_balance = models.FloatField(blank=True, null=True)
    interest_arrears = models.FloatField(blank=True, null=True)
    account_officer = models.CharField(max_length=20, blank=True, null=True)
    delay_officer = models.CharField(max_length=30, blank=True, null=True)
    last_month_interest_debit_amount = models.FloatField(blank=True, null=True)
    insurance = models.FloatField(blank=True, null=True)
    installment_amount = models.FloatField(blank=True, null=True)
    frequency_in_months = models.IntegerField(blank=True, null=True)
    total_capital_balance = models.FloatField(blank=True, null=True)
    charges = models.FloatField(blank=True, null=True)
    interest_on_capital = models.FloatField(blank=True, null=True)
    interest_on_arrears = models.FloatField(blank=True, null=True)
    total_capital_debited = models.FloatField(blank=True, null=True)
    interest_credit = models.FloatField(blank=True, null=True)
    principle = models.FloatField(blank=True, null=True)
    total_interest_credited = models.FloatField(blank=True, null=True)
    overdue_days = models.IntegerField(blank=True, null=True)
    eom_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "loans_history"
