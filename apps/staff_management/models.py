from django.db import models
from django.db.models import Q, F
from django.core.validators import MinValueValidator
from django.utils import timezone
from simple_history.models import HistoricalRecords


class BranchEmployeeData(models.Model):
    """Read-only view of branch managers from the employee data table."""
    staff_id = models.DecimalField(max_digits=990, decimal_places=5, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
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

# ── Scorecard (redesigned) ─────────────────────────────────────────────────────
# These four models (ScorecardRole/ScorecardKPI/RoleKPIMapping/PerformanceActual)
# plus EmployeeMonthlyPerformance below are a SIMPLIFIED REDESIGN of the legacy
# "Scorecard Automation" engine. The legacy engine instead used Role
# (orgnization_roles), KPI (kpi_definitions), RoleKPIMapping (role_kpi_mappings),
# EmployeePerformanceActual (employee_performance_actual_values) and a richer
# EmployeeMonthlyPerformance — driven by per-KPI calculation strategies
# (actual_over_target / growth_on_growth / inverse_growth / tiered_range), a
# score_cap, proration for leave, and weighting.
#
# NOTE (reconciled 2026-07-02 for the full-replace deploy): the legacy prod
# "employee_monthly_performance" table has an INCOMPATIBLE column set to the
# redesigned model below. To avoid a schema collision on the shared prod DB (which
# would 500 the moment a scorecard view queried it), the redesigned model now owns
# its own greenfield table "employee_monthly_performance_v2". The legacy prod
# table is left untouched (its historical rows are preserved, just not read by this
# ORM); the v2 table is created empty and repopulated by the scorecard recompute.
# See [[model-gap-audit]] and docs/DEPLOY.md §"Full-replace".
class ScorecardRole(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "scorecard_roles"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ScorecardKPI(models.Model):
    CATEGORY_CHOICES = [
        ("deposits", "Deposits"),
        ("loans", "Loans"),
        ("revenue", "Revenue"),
        ("customers", "New Customers"),
        ("quality", "Quality"),
    ]
    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="deposits")
    weight = models.FloatField(default=1.0)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "scorecard_kpis"
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoleKPIMapping(models.Model):
    role = models.ForeignKey(ScorecardRole, on_delete=models.CASCADE, related_name="kpi_mappings")
    kpi = models.ForeignKey(ScorecardKPI, on_delete=models.CASCADE, related_name="role_mappings")
    weight = models.FloatField(default=1.0)

    class Meta:
        managed = True
        db_table = "scorecard_role_kpi_mappings"
        unique_together = (("role", "kpi"),)


class PerformanceActual(models.Model):
    sales_code = models.CharField(max_length=50)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    staff_role = models.CharField(max_length=255, blank=True, null=True)
    department = models.CharField(max_length=255, blank=True, null=True)
    kpi_name = models.CharField(max_length=255)
    month = models.DateField()
    actual_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    target_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    class Meta:
        managed = True
        db_table = "scorecard_performance_actuals"
        ordering = ["-month", "sales_code"]


class EmployeeMonthlyPerformance(models.Model):
    # The generated monthly scorecard for one employee (one row per sales_code +
    # month). For each pillar — deposits, loans, revenue, new customers — it
    # stores the actual vs target, the per-pillar score, then the weighted
    # total_score, the letter grade (A–E) and how many KPIs were met. It is the
    # OUTPUT of the scorecard computation (actuals + targets in → scored row out),
    # consumed by the scorecard dashboards and the AI agent's staff-performance tool.
    GRADE_CHOICES = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E")]

    sales_code = models.CharField(max_length=50)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    staff_role = models.CharField(max_length=255, blank=True, null=True)
    department = models.CharField(max_length=255, blank=True, null=True)
    org_unit = models.CharField(max_length=255, blank=True, null=True)
    month = models.DateField()

    deposit_actual = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    deposit_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    loan_actual = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    loan_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    revenue_actual = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    revenue_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    new_customers_actual = models.IntegerField(default=0)
    new_customers_target = models.IntegerField(default=0)

    deposit_score = models.FloatField(default=0)
    loan_score = models.FloatField(default=0)
    revenue_score = models.FloatField(default=0)
    new_customers_score = models.FloatField(default=0)
    total_score = models.FloatField(default=0)

    grade = models.CharField(max_length=5, choices=GRADE_CHOICES, blank=True, null=True)
    kpis_met = models.CharField(max_length=50, blank=True, null=True)

    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "employee_monthly_performance_v2"
        unique_together = (("sales_code", "month"),)
        ordering = ["-month", "-total_score"]

    def __str__(self):
        return f"{self.sales_code} — {self.month}"


# ══════════════════════════════════════════════════════════════════════════════
# Legacy staff_management tables ported from hf_group_project-master.
# db_table and managed flags are copied EXACTLY so the new backend reads/writes
# the same production tables. managed=False tables live in the datawarehouse and
# are read-only from the app's perspective (the router blocks writes to them).
# ══════════════════════════════════════════════════════════════════════════════


class BranchEmployeeDmcData(models.Model):
    staff_pf_number = models.IntegerField(blank=True, null=True)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    staff_unit = models.CharField(max_length=255, blank=True, null=True)
    staff_role = models.CharField(max_length=255, blank=True, null=True)
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    staff_branch = models.CharField(max_length=255, blank=True, null=True)
    staff_zone = models.CharField(max_length=255, blank=True, null=True)
    staff_email = models.CharField(max_length=255, blank=True, null=True)
    team_leader = models.CharField(max_length=255, blank=True, null=True)
    team_leader_name = models.CharField(max_length=255, blank=True, null=True)
    employment_date = models.DateField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    exit_date = models.DateField(blank=True, null=True)
    staff_exit = models.IntegerField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)
    target_loan_disbursement = models.IntegerField(blank=True, null=True)
    target_focus_accounts = models.IntegerField(blank=True, null=True)
    target_new_customers = models.IntegerField(blank=True, null=True)
    target_deposits_value = models.BigIntegerField(blank=True, null=True)
    target_banca_value = models.BigIntegerField(blank=True, null=True)
    target_tills_volume = models.BigIntegerField(blank=True, null=True)
    target_tills_value = models.BigIntegerField(blank=True, null=True)
    target_dormancy_activations = models.IntegerField(blank=True, null=True)
    target_savings_value = models.BigIntegerField(blank=True, null=True)
    target_trade_finance_income = models.BigIntegerField(blank=True, null=True)
    target_training_hours = models.IntegerField(blank=True, null=True)
    date_time_etl = models.DateField(default=timezone.now)
    updated_at = models.DateField(default=timezone.now)
    target_loan_approvals = models.BigIntegerField(blank=True, null=True)
    target_tills_transactions = models.BigIntegerField(blank=True, null=True)
    target_active_tills = models.BigIntegerField(blank=True, null=True)
    target_trade_finance_value = models.BigIntegerField(blank=True, null=True)
    target_banca_motor = models.BigIntegerField(blank=True, null=True)
    target_banca_non_motor = models.BigIntegerField(blank=True, null=True)
    target_banca_life = models.BigIntegerField(default=0, blank=True, null=True)
    target_banca_non_life = models.BigIntegerField(default=0, blank=True, null=True)
    target_mortgage_mrkt_rate = models.BigIntegerField(default=0, blank=True, null=True)
    target_mortgage_non_mrkt_rate = models.BigIntegerField(default=0, blank=True, null=True)
    target_bank_tills_volume = models.BigIntegerField(blank=True, null=True)
    target_saf_tills_volume = models.BigIntegerField(blank=True, null=True)
    target_properties = models.BigIntegerField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "branch_employee_dmc_data"


class BranchFinalEmployeeDmcData(models.Model):
    staff_pf_number = models.IntegerField(blank=True, null=True)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    staff_unit = models.CharField(max_length=255, blank=True, null=True)
    staff_role = models.CharField(max_length=255, blank=True, null=True)
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    staff_branch = models.CharField(max_length=255, blank=True, null=True)
    staff_zone = models.CharField(max_length=255, blank=True, null=True)
    staff_email = models.CharField(max_length=255, blank=True, null=True)
    team_leader = models.CharField(max_length=255, blank=True, null=True)
    employment_date = models.DateField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    exit_date = models.DateField(blank=True, null=True)
    exit = models.IntegerField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)
    target_pbt_revenue = models.BigIntegerField(blank=True, null=True)
    target_loan_disbursement = models.BigIntegerField(blank=True, null=True)
    target_focus_accounts = models.IntegerField(blank=True, null=True)
    target_new_customers = models.IntegerField(blank=True, null=True)
    target_active_new_customers = models.IntegerField(blank=True, null=True)
    target_deposits_value = models.BigIntegerField(blank=True, null=True)
    target_asset_growth_value = models.BigIntegerField(blank=True, null=True)
    target_banca_value = models.BigIntegerField(blank=True, null=True)
    target_tills_volume = models.BigIntegerField(blank=True, null=True)
    target_tills_value = models.BigIntegerField(blank=True, null=True)
    target_dormancy_activations = models.IntegerField(blank=True, null=True)
    target_savings_value = models.BigIntegerField(blank=True, null=True)
    target_trade_finance_income = models.BigIntegerField(blank=True, null=True)
    target_forex = models.BigIntegerField(blank=True, null=True)
    target_training_hours = models.IntegerField(blank=True, null=True)
    target_loan_provisions = models.BigIntegerField(blank=True, null=True)
    target_npl = models.BigIntegerField(blank=True, null=True)
    date_update_etl = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateField(default=timezone.now)
    target_retail_loan_disbursement = models.BigIntegerField(blank=True, null=True)
    target_commercial_loan_disbursement = models.BigIntegerField(blank=True, null=True)
    target_trade_finance_value = models.BigIntegerField(blank=True, null=True)
    target_banca_life = models.BigIntegerField(default=0, blank=True, null=True)
    target_banca_non_life = models.BigIntegerField(default=0, blank=True, null=True)
    target_mortgage_mrkt_rate = models.BigIntegerField(default=0, blank=True, null=True)
    target_mortgage_non_mrkt_rate = models.BigIntegerField(default=0, blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "branch_final_employee_dmc_data"


class Drawdown(models.Model):
    account_number = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    cust_id = models.IntegerField(blank=True, null=True)
    customer_name = models.TextField(blank=True, null=True)
    drawdown_dt = models.TextField(blank=True, null=True)
    sales_staff = models.TextField(blank=True, null=True)
    id_product = models.TextField(blank=True, null=True)
    product_name = models.TextField(blank=True, null=True)
    loan_officer_id = models.TextField(blank=True, null=True)
    loan_officer_name = models.TextField(blank=True, null=True)
    final_interest = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    total_days = models.IntegerField(blank=True, null=True)
    total_months = models.IntegerField(blank=True, null=True)
    unit_code = models.IntegerField(blank=True, null=True)
    eom_date = models.TextField(blank=True, null=True)
    dec_31_total_disbursment = models.TextField(blank=True, null=True)
    current_total_disbursment = models.TextField(blank=True, null=True)
    net_drawdown = models.TextField(blank=True, null=True)
    gross_drawdown = models.TextField(blank=True, null=True)
    segment = models.TextField(blank=True, null=True)
    fkgd_category = models.IntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    main_segment = models.TextField(blank=True, null=True)
    security_type = models.TextField(blank=True, null=True)
    term = models.TextField(blank=True, null=True)
    year_month = models.TextField(blank=True, null=True)
    branch = models.TextField(blank=True, null=True)
    brn_zone = models.TextField(blank=True, null=True)
    specs = models.TextField(blank=True, null=True)
    salesperson = models.TextField(blank=True, null=True)
    updated_at = models.DateField(default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "drawdown"


class DrawdownDaily(models.Model):
    id = models.BigAutoField(primary_key=True)
    drawdown_dt = models.DateField()
    drawdown_dt_1 = models.DateField()
    account_number = models.BigIntegerField()
    cust_id = models.BigIntegerField()
    customer_name = models.CharField(max_length=255)
    salesperson = models.CharField(max_length=255)
    id_product = models.BigIntegerField()
    product_desc = models.CharField(max_length=255)
    loan_officer_id = models.CharField(max_length=50)
    loan_officer_name = models.CharField(max_length=255)
    final_interest = models.FloatField()
    loan_term_days = models.BigIntegerField()
    loan_term_months = models.BigIntegerField()
    unit_code = models.BigIntegerField()
    net_drawdown = models.FloatField()
    gross_drawdown = models.FloatField()
    customer_segment = models.TextField()
    fkgd_category = models.BigIntegerField()
    description = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    financial_sector = models.CharField(max_length=100, blank=True, null=True)
    activity_sector = models.CharField(max_length=100, blank=True, null=True)
    diaspora_check = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "drawdown_daily"
        verbose_name = "Drawdown Daily"
        verbose_name_plural = "Drawdown Daily"


class InsurancePolicy(models.Model):
    r_number = models.CharField(max_length=255, blank=True, null=True)
    sales_type = models.CharField(max_length=255, blank=True, null=True)
    insured = models.CharField(max_length=255, blank=True, null=True)
    phone_no = models.CharField(max_length=255, blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, null=True)
    financier = models.CharField(max_length=255, blank=True, null=True)
    underwriter = models.CharField(max_length=255, blank=True, null=True)
    policy_no = models.CharField(max_length=255, blank=True, null=True)
    product = models.CharField(max_length=255, blank=True, null=True)
    reg_no = models.CharField(max_length=255, blank=True, null=True)
    starting_date = models.DateField(blank=True, null=True)
    ending_date = models.DateField(blank=True, null=True)
    sum_insured = models.DecimalField(max_digits=25, decimal_places=2, blank=True, null=True)
    premiums = models.DecimalField(max_digits=25, decimal_places=2, blank=True, null=True)
    paid = models.DecimalField(max_digits=25, decimal_places=2, blank=True, null=True)
    balance = models.DecimalField(max_digits=25, decimal_places=2, blank=True, null=True)
    commission = models.DecimalField(max_digits=25, decimal_places=2, blank=True, null=True)
    branch = models.CharField(max_length=255, blank=True, null=True)
    sales_person = models.CharField(max_length=255, blank=True, null=True)
    code = models.CharField(max_length=255, blank=True, null=True)
    rm = models.CharField(max_length=255, blank=True, null=True)
    month = models.CharField(max_length=255)
    year = models.CharField(max_length=255, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.policy_no} - {self.insured}"

    class Meta:
        managed = True
        db_table = "insurance_policies"
        verbose_name = "Insurance Policy"
        verbose_name_plural = "Insurance Policies"
        ordering = ["-starting_date"]


class TradeFinanceData(models.Model):
    originating_branch = models.CharField(max_length=255)
    rm_name = models.CharField(max_length=255)
    rm_code = models.CharField(max_length=255, blank=True, null=True)
    guarantee_ref = models.CharField(max_length=255)
    product_type = models.CharField(max_length=255)
    customer_id = models.BigIntegerField()
    segment = models.CharField(max_length=255)
    our_customer = models.CharField(max_length=255)
    beneficiary = models.CharField(max_length=255)
    currency = models.CharField(max_length=3)
    amount_fcy = models.DecimalField(max_digits=25, decimal_places=2, validators=[MinValueValidator(0)])
    issue_date = models.CharField(max_length=255)
    expiry_date = models.CharField(max_length=255)
    commission_lcy = models.DecimalField(max_digits=20, decimal_places=6, validators=[MinValueValidator(0)])
    month = models.CharField(max_length=255)
    fx_rate = models.DecimalField(max_digits=10, decimal_places=6, validators=[MinValueValidator(0)])
    year = models.CharField(max_length=255, db_index=True)
    security_type = models.CharField(max_length=255, blank=True, null=True)
    cash_cover_amount = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True, validators=[MinValueValidator(0)])
    cash_cover_percentage = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True, validators=[MinValueValidator(0)])
    other_security = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.guarantee_ref} - {self.product_type} - {self.our_customer}"

    class Meta:
        managed = True
        db_table = "trade_finance_data"
        verbose_name = "Trade Finance Data"
        verbose_name_plural = "Trade Finance Data"
        ordering = ["-issue_date"]


class CustMonthlyFtp(models.Model):
    cust_cif = models.IntegerField(blank=True, null=True)
    jan_avg_bal = models.FloatField(default=0)
    jan_loan_bal = models.FloatField(default=0)
    jan_ftp = models.FloatField(default=0)
    feb_avg_bal = models.FloatField(default=0)
    feb_loan_bal = models.FloatField(default=0)
    feb_ftp = models.FloatField(default=0)
    mar_avg_bal = models.FloatField(default=0)
    mar_loan_bal = models.FloatField(default=0)
    mar_ftp = models.FloatField(default=0)
    apr_avg_bal = models.FloatField(default=0)
    apr_loan_bal = models.FloatField(default=0)
    apr_ftp = models.FloatField(default=0)
    may_avg_bal = models.FloatField(default=0)
    may_loan_bal = models.FloatField(default=0)
    may_ftp = models.FloatField(default=0)
    jun_avg_bal = models.FloatField(default=0)
    jun_loan_bal = models.FloatField(default=0)
    jun_ftp = models.FloatField(default=0)
    jul_avg_bal = models.FloatField(default=0)
    jul_loan_bal = models.FloatField(default=0)
    jul_ftp = models.FloatField(default=0)
    aug_avg_bal = models.FloatField(default=0)
    aug_loan_bal = models.FloatField(default=0)
    aug_ftp = models.FloatField(default=0)
    sep_avg_bal = models.FloatField(default=0)
    sep_loan_bal = models.FloatField(default=0)
    sep_ftp = models.FloatField(default=0)
    oct_avg_bal = models.FloatField(default=0)
    oct_loan_bal = models.FloatField(default=0)
    oct_ftp = models.FloatField(default=0)
    nov_avg_bal = models.FloatField(default=0)
    nov_loan_bal = models.FloatField(default=0)
    nov_ftp = models.FloatField(default=0)
    dec_avg_bal = models.FloatField(default=0)
    dec_loan_bal = models.FloatField(default=0)
    dec_ftp = models.FloatField(default=0)
    total_ftp = models.FloatField(default=0)
    current_year = models.IntegerField(db_index=True)

    class Meta:
        managed = True
        verbose_name = "Customer Monthly FTP"
        verbose_name_plural = "Customer Monthly FTPs"
        db_table = "cust_monthly_ftp"
        unique_together = ("cust_cif", "current_year")
        indexes = [models.Index(fields=["cust_cif", "current_year"])]

    def __str__(self):
        return f"{self.cust_cif} - {self.current_year} - YTD FTP: {self.total_ftp}"


class DailySalesAccountsWithCto(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_cif = models.BigIntegerField(blank=True, null=True)
    cust_open_date = models.DateField(blank=True, null=True)
    full_name = models.CharField(max_length=200, blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    acc_num = models.CharField(max_length=255, blank=True, null=True)
    sale_code = models.CharField(max_length=255, blank=True, null=True)
    prod_id = models.IntegerField(blank=True, null=True)
    customer_segment = models.CharField(max_length=255, blank=True, null=True)
    acc_open_date = models.DateField(blank=True, null=True)
    bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    cust_cto = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    account_cto = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    dec_23_bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    curr_24_bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    total_account_before_2024 = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    account_status = models.CharField(max_length=255, blank=True, null=True)
    etl_date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "daily_sales_accounts_with_cto"
        verbose_name = "Daily Sales Account With CTO"
        verbose_name_plural = "Daily Sales Accounts With CTO"


class DailyDormancyConvertedAccount(models.Model):
    id = models.BigAutoField(primary_key=True)
    acc_num = models.CharField(max_length=255, blank=True, null=True)
    cust_cif = models.BigIntegerField(blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    prod_id = models.IntegerField(blank=True, null=True)
    full_name = models.CharField(max_length=200, blank=True, null=True)
    customer_segment = models.CharField(max_length=20, blank=True, null=True)
    last_dormant_date = models.DateField(blank=True, null=True)
    current_status = models.CharField(max_length=20, blank=True, null=True)
    current_bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    reactivation_date = models.DateField(blank=True, null=True)
    action_user = models.CharField(max_length=200, blank=True, null=True)
    etl_date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "daily_dormancy_converted_accounts"
        verbose_name = "Daily Dormancy Converted Account"
        verbose_name_plural = "Daily Dormancy Converted Accounts"


class MerchantBankTillManualData(models.Model):
    merchant_id = models.CharField(max_length=200, null=True, blank=True)
    credit_account = models.CharField(max_length=200, null=True, blank=True)
    account_no = models.CharField(max_length=200, null=True, blank=True)
    account_name = models.CharField(max_length=255, null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)
    sellercode = models.CharField(max_length=200, null=True, blank=True)
    kra_pin = models.CharField(max_length=200, null=True, blank=True)
    current_branch = models.CharField(max_length=200, null=True, blank=True)
    brn_zone = models.CharField(max_length=200, null=True, blank=True)
    seller_code = models.CharField(max_length=200, null=True, blank=True)
    staff_role = models.CharField(max_length=200, null=True, blank=True)
    staff_name = models.CharField(max_length=200, null=True, blank=True)
    first_time_trx = models.DateTimeField(null=True, blank=True)
    latest_time_trx = models.DateTimeField(null=True, blank=True)
    number_trx_since_inception = models.IntegerField(null=True, blank=True)
    amount_since_inception = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    current_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "weighted_sales_seller_bank_till_data_dump_manual"

    def __str__(self):
        return f"{self.merchant_id or ''} — {self.account_name or ''}"


class IapplyLoanApproval(models.Model):
    application_id = models.CharField(max_length=200, null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)
    branch = models.IntegerField(null=True, blank=True)
    product_category = models.CharField(max_length=10, null=True, blank=True)
    product = models.IntegerField(null=True, blank=True)
    customer_category = models.CharField(max_length=20, null=True, blank=True)
    customer_id = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    currency = models.IntegerField(null=True, blank=True)
    amount_requested = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    amount_approved = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    amount_disbursed = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    loan_account = models.CharField(max_length=200, null=True, blank=True)
    status_from = models.CharField(max_length=200, null=True, blank=True)
    action_user_name = models.CharField(max_length=200, null=True, blank=True)
    status_to = models.CharField(max_length=200, null=True, blank=True)
    action_date = models.DateTimeField(null=True, blank=True)
    action_user = models.CharField(max_length=200, null=True, blank=True)
    action_user_role = models.CharField(max_length=200, null=True, blank=True)
    account_officer = models.CharField(max_length=20, null=True, blank=True)
    seller = models.CharField(max_length=200, null=True, blank=True)
    seller_code = models.CharField(max_length=20, null=True, blank=True)
    created = models.DateTimeField(null=True, blank=True)
    updated = models.DateTimeField(null=True, blank=True)
    segment = models.CharField(max_length=200, null=True, blank=True)
    post_approval = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    merge_column = models.CharField(max_length=200, null=True, blank=True)
    application_status_classification = models.CharField(max_length=200, null=True, blank=True)
    tat = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    current_tat_days = models.CharField(max_length=200, null=True, blank=True)
    last_action_tat = models.CharField(max_length=200, null=True, blank=True)
    tat_max = models.CharField(max_length=200, null=True, blank=True)
    total_bank_tat = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    branch_application = models.DateTimeField(null=True, blank=True)
    business_analysis = models.DateTimeField(null=True, blank=True)
    credit_approval = models.DateTimeField(null=True, blank=True)
    offer_letter_generation = models.DateTimeField(null=True, blank=True)
    drawdown_initiation_credit = models.DateTimeField(null=True, blank=True)
    open_closed = models.CharField(max_length=200, null=True, blank=True)
    product_name = models.CharField(max_length=200, null=True, blank=True)
    product_class = models.CharField(max_length=200, null=True, blank=True)
    month = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "iapply_loan_approvals_data_dump"

    def __str__(self):
        return self.application_id or f"{self.pk}"


class Product(models.Model):
    code = models.CharField(max_length=20, unique=True)
    product_description = models.CharField(max_length=255)
    product_map = models.CharField(max_length=20)
    focus = models.CharField(max_length=1)
    sme_pb = models.CharField(max_length=1)
    date_created = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "product_mapping"


class StaffEmployeeData(models.Model):
    EMPLOYEE_CATEGORY_CHOICES = [
        ("retail_branch_front_office", "Retail Branch Front Office"),
        ("front_office", "Front Office"),
        ("back_office", "Back Office"),
        ("retail_branch_back_office", "Retail Branch Back Office"),
    ]
    staff_pf_number = models.IntegerField(blank=False, unique=True, null=False)
    staff_name = models.CharField(max_length=255, blank=False, null=False)
    staff_email = models.CharField(max_length=255, blank=False, null=False)
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    department = models.CharField(max_length=255, blank=False, null=False)
    staff_unit = models.CharField(max_length=255, blank=False, null=False)
    staff_org_unit = models.CharField(max_length=255, blank=False, null=False)
    job_title = models.CharField(max_length=255, blank=False, null=False)
    employment_date = models.DateField(blank=False, null=False)
    employee_category = models.CharField(blank=False, null=False, max_length=100, choices=EMPLOYEE_CATEGORY_CHOICES)
    exit_date = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "staff_employee_data"
        verbose_name = "Staff Employee Data"
        constraints = [
            models.CheckConstraint(condition=Q(exit_date__gt=F("employment_date")), name="exit_after_hire"),
            models.CheckConstraint(condition=Q(is_active=True) | Q(exit_date__isnull=False), name="inactive_requires_exit_date"),
        ]
        indexes = [
            models.Index(fields=["employment_date", "is_active"]),
            models.Index(fields=["staff_org_unit", "is_active"]),
        ]
        ordering = ["-employment_date"]

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.save()


class LeaveRecord(models.Model):
    LEAVE_TYPE_CHOICES = [
        ("maternity_leave", "Maternity Leave"),
        ("sick_leave", "Sick Leave"),
    ]
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    leave_type = models.CharField(max_length=100, choices=LEAVE_TYPE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        managed = True
        db_table = "staff_leave_records"
        verbose_name = "Staff Leave Records"
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gt=F("start_date")), name="leave_end_after_start"),
        ]
        indexes = [models.Index(fields=["start_date", "end_date"])]
        ordering = ["start_date"]


class EmployeeRoleHistory(models.Model):
    ROLE_STATUS_CHOICES = [
        ("acting", "Acting"),
        ("probation", "Probation"),
        ("permanent", "Permanent"),
        ("contract", "Contract"),
    ]
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    role_code = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    role_status = models.CharField(max_length=20, choices=ROLE_STATUS_CHOICES, default="permanent")
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "employee_role_history"
        verbose_name = "Role History"
        verbose_name_plural = "Role Histories"
        constraints = [
            models.UniqueConstraint(fields=["sales_code", "role_code", "start_date"], name="unique_role_start_per_employee"),
            models.CheckConstraint(condition=Q(end_date__gt=F("start_date")), name="end_after_start"),
        ]
        ordering = ["-start_date"]
        indexes = [models.Index(fields=["sales_code", "start_date"])]

    def __str__(self):
        return f"{self.sales_code} - {self.role_code} ({self.start_date} to {self.end_date})"


class RmKPIBaseSummary(models.Model):
    sales_code = models.CharField(max_length=100)
    eom_date = models.DateField()
    kpi_code = models.CharField(max_length=50)
    kpi_value = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        managed = True
        db_table = "rm_kpi_base_summary"
        verbose_name = "RM KPI Base Summary"
        verbose_name_plural = "RM KPI Base Summaries"
        indexes = [models.Index(fields=["eom_date", "sales_code", "kpi_code"])]


class MissingEmployeeActual(models.Model):
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    staff_name = models.CharField(max_length=255)
    role_code = models.CharField(max_length=100)
    kpi_code = models.CharField(max_length=100)
    eom_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "missing_employee_actuals"
        verbose_name = "Missing Employee Actual"
        verbose_name_plural = "Missing Employee Actuals"
        indexes = [models.Index(fields=["eom_date", "sales_code", "kpi_code"])]


class TelesalesStaff(models.Model):
    sales_code = models.CharField(max_length=50, unique=True)
    sales_person = models.CharField(max_length=100)
    branch = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    team_leader = models.CharField(max_length=100)

    class Meta:
        managed = True
        db_table = "telesales_staff_list"


class TelesalesDormantTillsAllocation(models.Model):
    pyament_method = models.CharField(max_length=50, blank=True, null=True)
    credit_account = models.CharField(max_length=50, blank=True, null=True)
    sellercode = models.CharField(max_length=50, blank=True, null=True)
    code = models.CharField(max_length=50, blank=True, null=True)
    new_code = models.CharField(max_length=50, blank=True, null=True)
    branch = models.CharField(max_length=100, blank=True, null=True)
    target = models.IntegerField(blank=True, null=True)
    allocated_seller_person = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "telesales_dormant_tills_allocation"


# ── Managed mirror tables for manual CSV uploads of warehouse datasets ──────────
# The warehouse models above (DailySalesAccountsWithCto, DailyDormancyConvertedAccount,
# MerchantBankTillManualData) are managed=False — the DB router routes them to the
# read-only datawarehouse and BLOCKS writes, so CSV upload had no write target. These
# mirror models carry the SAME columns but managed=True on the default DB (distinct
# *_upload db_table) so manual uploads persist. ETL-populated reads keep using the
# warehouse models; manual uploads read/write these.

class DailySalesAccountsWithCtoUpload(models.Model):
    cust_cif = models.BigIntegerField(blank=True, null=True)
    cust_open_date = models.DateField(blank=True, null=True)
    full_name = models.CharField(max_length=200, blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    acc_num = models.CharField(max_length=255, blank=True, null=True)
    sale_code = models.CharField(max_length=255, blank=True, null=True)
    prod_id = models.IntegerField(blank=True, null=True)
    customer_segment = models.CharField(max_length=255, blank=True, null=True)
    acc_open_date = models.DateField(blank=True, null=True)
    bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    cust_cto = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    account_cto = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    dec_23_bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    curr_24_bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    total_account_before_2024 = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    account_status = models.CharField(max_length=255, blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "daily_sales_accounts_with_cto_upload"
        ordering = ["-uploaded_at"]


class DailyDormancyConvertedAccountUpload(models.Model):
    acc_num = models.CharField(max_length=255, blank=True, null=True)
    cust_cif = models.BigIntegerField(blank=True, null=True)
    brn_code = models.IntegerField(blank=True, null=True)
    prod_id = models.IntegerField(blank=True, null=True)
    full_name = models.CharField(max_length=200, blank=True, null=True)
    customer_segment = models.CharField(max_length=20, blank=True, null=True)
    last_dormant_date = models.DateField(blank=True, null=True)
    current_status = models.CharField(max_length=20, blank=True, null=True)
    current_bal = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    reactivation_date = models.DateField(blank=True, null=True)
    action_user = models.CharField(max_length=200, blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "daily_dormancy_converted_accounts_upload"
        ordering = ["-uploaded_at"]


class MerchantBankTillManualUpload(models.Model):
    merchant_id = models.CharField(max_length=200, null=True, blank=True)
    credit_account = models.CharField(max_length=200, null=True, blank=True)
    account_no = models.CharField(max_length=200, null=True, blank=True)
    account_name = models.CharField(max_length=255, null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)
    sellercode = models.CharField(max_length=200, null=True, blank=True)
    kra_pin = models.CharField(max_length=200, null=True, blank=True)
    current_branch = models.CharField(max_length=200, null=True, blank=True)
    brn_zone = models.CharField(max_length=200, null=True, blank=True)
    seller_code = models.CharField(max_length=200, null=True, blank=True)
    staff_role = models.CharField(max_length=200, null=True, blank=True)
    staff_name = models.CharField(max_length=200, null=True, blank=True)
    first_time_trx = models.DateTimeField(null=True, blank=True)
    latest_time_trx = models.DateTimeField(null=True, blank=True)
    number_trx_since_inception = models.IntegerField(null=True, blank=True)
    amount_since_inception = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    current_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "merchant_bank_till_manual_upload"
        ordering = ["-uploaded_at"]


# ── Scorecard automation engine (parallel subsystem) ───────────────────────────
# Imported here so Django discovers these models under the staff_management app.
# Their tables are namespaced sc_* and do NOT collide with the redesigned
# scorecard models above. See scorecard_automation/models.py.
from apps.staff_management.scorecard_automation.models import (  # noqa: E402,F401
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)
