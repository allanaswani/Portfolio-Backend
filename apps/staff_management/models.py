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
    ROLE_TYPE_CHOICES = [("IC", "IC"), ("MGR", "MGR"), ("EXEC", "EXEC")]

    # ``name`` stays the canonical unique key (used by the seed + RoleKPIMapping);
    # the frontend Role KPI Mappings screen reads/writes it as ``role_name``.
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    # Contract fields the scorecard config screen expects.
    role_code = models.CharField(max_length=50, blank=True, null=True)
    role_type = models.CharField(max_length=10, choices=ROLE_TYPE_CHOICES, blank=True, null=True)

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
    # ``name`` stays the canonical unique key; the frontend reads/writes it as
    # ``kpi_name``. ``category``/``weight`` remain the internal computation inputs.
    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="deposits")
    weight = models.FloatField(default=1.0)
    is_active = models.BooleanField(default=True)
    # Contract fields the scorecard config screen expects.
    kpi_code = models.CharField(max_length=50, blank=True, null=True)
    kpi_description = models.TextField(blank=True, null=True)
    kpi_calculation_mode = models.CharField(max_length=50, blank=True, null=True)
    kpi_rating_type = models.CharField(max_length=50, blank=True, null=True)
    score_cap = models.FloatField(default=0)

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
    # The banca split the business now plans against. Migration 0043 put these
    # on the TABLE; without them on the model the serializer never saw them, so
    # they were missing from the sales-staff template and there was no way to
    # upload one - "the sales staff template haina the new insurance targets".
    #
    # Nullable with NO default, deliberately. A column full of noughts reads as
    # "the plan is nought", which is a target; NULL reads as "no plan set",
    # which is what an unfilled column means, and the card tells those apart.
    # That is why they are not BigIntegerField(default=0) like the two above.
    target_life_excl_ni = models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True)
    target_life_ni = models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True)
    target_life_elimu_gi = models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True)
    target_non_life_gi = models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True)
    target_non_life_medical = models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True)
    target_life_volume = models.IntegerField(blank=True, null=True)
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
    # HFCB-Properties units planned for the year. The catalogue in targets.py
    # has carried a ("properties", "target_properties", ...) entry all along;
    # the column existed only on branch_employee_dmc_data, so at branch, zone
    # and bank scope the metric was silently skipped — rollup() intersects the
    # catalogue with the columns a table actually has.
    #
    # DECIMAL, where the staff table's copy is a BigInteger, and that is
    # deliberate. The plan apportions the bank's 340 units across 22 branches
    # by weight, so the branch figures are fractional (Rehani 35.664...). Round
    # them on the way in and the 22 rows sum to 341 — the bank would be reading
    # a plan one unit larger than the one it set. Stored exact; prorate()
    # already rounds "number" units for display, and it rounds AFTER summing,
    # so the bank scope still reports a whole 340.
    target_properties = models.DecimalField(
        max_digits=14, decimal_places=8, blank=True, null=True,
        help_text="Property units planned for the year. Fractional by design.",
    )
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


class PremiumTypeMapping(models.Model):
    """How one insurance product is classified.

    `insurance_policies.product` is free text typed by whoever loaded the
    policy, so the classification cannot live on the policy row: it would have
    to be re-decided every upload, by hand, per row. This table decides it once
    per product.

    **The table already exists in production and this model matches it exactly**
    — five text columns and no surrogate key:

        product | vic_check | life_policy_check | premium_type | policy_category

    So ``product`` IS the primary key. Django otherwise invents an implicit
    ``id``, and every query then selects a column that is not there; the first
    version of this model did exactly that and the migration stopped on the
    host. ``updated_at`` / ``updated_by`` are gone for the same reason — this
    is somebody else's table and growing it to suit our audit habits is not a
    change to make in passing. Who changed what is recorded by
    ``HistoricalRecords`` in a table Django does own.

    A CharField primary key means the API addresses a mapping BY PRODUCT NAME,
    so the detail route uses ``<path:pk>`` — product names contain spaces, and
    can contain slashes ("MOTOR/PRIVATE"), which ``<str:pk>`` would reject.

    The four classification columns are free text on purpose. The values seen so
    far are vic_check "vic", life_policy_check "life", premium_type
    "non-motor" and policy_category "Life", but this is an insurance product
    list that Bancassurance extends, and a choices= list would reject the next
    product rather than record it. Validation belongs with the people who own
    the vocabulary, not in a column definition written from three rows.
    """

    product = models.CharField(
        max_length=255, primary_key=True, verbose_name="Product",
        help_text="Product name as it appears on the policy, e.g. WHOLE LIFE.",
    )
    vic_check = models.CharField(
        max_length=100, blank=True, default="",
        help_text='Observed value: "vic".',
    )
    life_policy_check = models.CharField(
        max_length=100, blank=True, default="",
        help_text='Observed value: "life".',
    )
    premium_type = models.CharField(
        max_length=100, blank=True, default="",
        help_text='Observed value: "non-motor".',
    )
    policy_category = models.CharField(
        max_length=100, blank=True, default="",
        help_text='Observed value: "Life".',
    )

    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "premium_types_mapping"
        ordering = ["product"]
        verbose_name = "Premium type mapping"
        verbose_name_plural = "Premium type mappings"

    def __str__(self):
        return f"{self.product} -> {self.premium_type or '-'} / {self.policy_category or '-'}"


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
        # Renamed upstream: the warehouse dropped the "_manual" suffix. The old
        # table is still present but no longer filled, which is why data health
        # reported it empty rather than missing — the model was reading a table
        # nothing writes to any more. The API route keeps its own name
        # (merchant-bank-tills-manual/), so nothing on the frontend moves.
        db_table = "weighted_sales_seller_bank_till_data_dump"

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
    sme_pb = models.CharField(max_length=20)
    # Loan classification columns (already present in the product_mapping table).
    loan_category = models.CharField(max_length=50, blank=True, null=True)
    loan_security = models.CharField(max_length=50, blank=True, null=True)
    loan_collateral = models.CharField(max_length=50, blank=True, null=True)
    # Default so "Add New Product" no longer requires it; existing rows keep theirs.
    date_created = models.DateTimeField(default=timezone.now, blank=True)

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
            models.CheckConstraint(check=Q(exit_date__gt=F("employment_date")), name="exit_after_hire"),
            models.CheckConstraint(check=Q(is_active=True) | Q(exit_date__isnull=False), name="inactive_requires_exit_date"),
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
            models.CheckConstraint(check=Q(end_date__gt=F("start_date")), name="leave_end_after_start"),
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
            models.CheckConstraint(check=Q(end_date__gt=F("start_date")), name="end_after_start"),
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


class DSRSalesCode(models.Model):
    """A DSR (Direct Sales Rep) seller-code allocation — one per person.

    Mirrors the "DSRs Seller Code Allocation" listing. ``pf_number`` is the unique
    person key (used to detect an existing allocation) and ``sales_code`` is a
    unique ``DSR###`` code. New codes are the next sequential number after the
    current maximum, so a code is never reused (see ``dsr.next_sales_code``).
    """

    pf_number = models.CharField(max_length=30, unique=True, verbose_name="PF Number")
    sales_code = models.CharField(max_length=20, unique=True, verbose_name="Sales Code")
    salesperson = models.CharField(max_length=200, blank=True)
    branch = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=60, blank=True)
    team_leader = models.CharField(max_length=200, blank=True)
    date_of_employment = models.DateField(null=True, blank=True)
    allocation_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # A seller code decides whose name a sale is credited to, and codes are now
    # editable and deletable from Administration — so every correction is kept.
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "dsr_sales_codes"
        ordering = ["sales_code"]

    def __str__(self):
        return f"{self.sales_code} — {self.salesperson} (PF {self.pf_number})"


class DSRRoleTeamLeader(models.Model):
    """Team leader(s) that own a DSR **role** (as opposed to a branch).

    Some DSR roles are led by a team leader independent of branch — e.g.
    "BANCA DSR" → David Wambugu, "SME DSR" (a.k.a. DPA) → Eva Kabiwa / Luke Njagi.
    A role may have more than one leader, so the Seller-Codes allocator offers the
    matching options for the chosen role and the admin picks the right one.
    """

    role = models.CharField(max_length=60, db_index=True)
    team_leader = models.CharField(max_length=200)
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "dsr_role_team_leaders"
        ordering = ["role", "sort_order", "team_leader"]
        constraints = [
            models.UniqueConstraint(fields=["role", "team_leader"], name="uniq_role_team_leader"),
        ]

    def __str__(self):
        return f"{self.role} → {self.team_leader}"


class TeamLeaderBranch(models.Model):
    """Which team leader owns a branch (for PB DSRs etc.).

    One row per branch (canonical, normalised name). A team leader owns many
    branches; when a TL exits, their branches are reassigned to another TL. Used to
    auto-fill a DSR's team leader from its branch on allocation.
    """

    branch = models.CharField(max_length=120, unique=True, verbose_name="Branch")
    team_leader = models.CharField(max_length=200, verbose_name="Team Leader")
    role = models.CharField(max_length=60, blank=True, default="PB DSR")
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Who owns which branch drives target attribution, so reassignments are kept.
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "team_leader_branches"
        ordering = ["team_leader", "branch"]

    def __str__(self):
        return f"{self.branch} → {self.team_leader}"


class BranchDepartmentCost(models.Model):
    """Operating cost for one department at one branch, for one month.

    **There is no cost column anywhere in the warehouse.** The organisation-wide
    "costs per department" figures on the GCEO deck are hard-coded constants in
    the frontend, and they carry no branch dimension at all — so a branch
    manager's cost line cannot be derived from existing data, only captured.

    This table is that capture point: Finance types a month in or uploads the
    CSV, and the branch Staff & Costs page reads it back scoped to the branch.
    Until a month is loaded the page shows real headcount with the cost columns
    blank — it never apportions the org-wide figure across branches, because
    that number would be invented rather than measured.

    ``branch`` is stored as the branch NAME (matching Profile.BRANCH_CHOICES)
    and matched suffix-insensitively on read, so "HEAD OFFICE" and "HEAD OFFICE
    BRANCH" resolve to the same branch. ``department`` should be a canonical
    name from apps.gceo_dashboard.departments.STANDARD_DEPARTMENT_MAP.
    """

    branch = models.CharField(max_length=120, db_index=True, verbose_name="Branch")
    department = models.CharField(max_length=120, db_index=True, verbose_name="Department")
    year = models.IntegerField(validators=[MinValueValidator(2000)])
    month = models.IntegerField(
        validators=[MinValueValidator(1)], help_text="1-12"
    )
    # Total cost booked to the department at this branch for the month.
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # Optional split — staff cost is the line branch managers ask for by name.
    staff_cost = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
    other_cost = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
    notes = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        managed = True
        db_table = "branch_department_cost"
        # One figure per branch/department/month — re-uploading a month updates
        # rather than stacking a second row on top of the first.
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "department", "year", "month"],
                name="uniq_branch_department_cost_period",
            ),
            models.CheckConstraint(
                check=Q(month__gte=1) & Q(month__lte=12),
                name="branch_department_cost_month_range",
            ),
        ]
        ordering = ["branch", "department", "-year", "-month"]
        verbose_name = "Branch department cost"
        verbose_name_plural = "Branch department costs"

    def __str__(self):
        return f"{self.branch} · {self.department} · {self.year}-{self.month:02d}"


class BranchPropertyTarget(models.Model):
    """How many HFCB-Properties units a branch is expected to sell in a year.

    The Property Holdings page could show what HAS been sold but had nothing to
    judge it against — the plan lived in a spreadsheet. These are those numbers:
    22 branches, carrying a zone and a unit target that sums to 340 for 2026.

    ``target_properties`` is deliberately a decimal, not an integer. The plan
    apportions a whole-bank figure across branches by weight, so the source
    values are fractional (Rehani 35.664…, Embu 7.132…) and they are meant to
    add up to the bank number exactly. Rounding each branch to a whole unit on
    the way in would lose that — 22 roundings do not sum back to 340. The UI
    rounds for display; the stored figure stays the plan.

    ``brn_code`` is the warehouse branch code, the same key
    core.date_utils.BRN_CASE maps to names, so a target can be joined to
    holdings without matching on branch text. ``staff_branch`` is kept as the
    name the plan used, which is not always the name the warehouse uses
    (the plan says "SAMEER BUSINESS PARK BRANCH", BRN_CASE says "SAMEER
    BRANCH"), and keeping both means neither has to be corrected to fit.
    """

    brn_code = models.IntegerField(
        db_index=True, verbose_name="Branch code",
        help_text="Warehouse brn_code, e.g. 200 for REHANI BRANCH.",
    )
    staff_branch = models.CharField(
        max_length=120, verbose_name="Branch",
        help_text="Branch name as the plan spells it.",
    )
    staff_zone = models.CharField(
        max_length=60, blank=True, default="", db_index=True,
        verbose_name="Zone", help_text="e.g. Zone A.",
    )
    year = models.IntegerField(
        db_index=True, validators=[MinValueValidator(2000)],
        help_text="Plan year the target applies to.",
    )
    # 8 decimal places, chosen not guessed: the 22 plan values are thirteenths
    # and elevenths (denominator 143), and 8dp is the shortest scale at which
    # they still sum to exactly 340. At 6dp they sum to 340.000001, at 10dp to
    # 340.0000000001 - a target that does not add up to the bank number is the
    # first thing anyone checking the plan will notice.
    target_properties = models.DecimalField(
        max_digits=14, decimal_places=8, default=0,
        verbose_name="Target properties",
        help_text="Units planned for the year. Fractional by design.",
    )
    notes = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")

    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "branch_property_target"
        constraints = [
            # One target per branch per year: re-uploading a plan updates the
            # row rather than stacking a second one behind it.
            models.UniqueConstraint(
                fields=["brn_code", "year"],
                name="uniq_branch_property_target_year",
            ),
            models.CheckConstraint(
                check=Q(target_properties__gte=0),
                name="branch_property_target_non_negative",
            ),
        ]
        ordering = ["-year", "staff_zone", "staff_branch"]
        verbose_name = "Branch property target"
        verbose_name_plural = "Branch property targets"

    def __str__(self):
        return f"{self.staff_branch} · {self.year} · {self.target_properties}"


# ── Scorecard automation engine (parallel subsystem) ───────────────────────────
# Imported here so Django discovers these models under the staff_management app.
# Their tables are namespaced sc_* and do NOT collide with the redesigned
# scorecard models above. See scorecard_automation/models.py.
from apps.staff_management.scorecard_automation.models import (  # noqa: E402,F401
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)


class OperatingExpenseMapping(models.Model):
    """Which expense line a general-ledger account belongs to.

    Finance has kept this as a spreadsheet (``Operating_expenses_mapping.xlsx``):
    249 GL accounts, each tagged with the expense type it rolls up to, the name
    of the operating-expense line, and whether the spend is **Controllable** or
    **Installed** (a fixed, already-committed outflow). Nothing in the warehouse
    carries that classification — the GL postings have account codes and the
    expense slides have category names, and this sheet is the only thing that
    joins the two.

    Captured here for the same reason as :class:`BranchDepartmentCost`: it is a
    mapping only Finance can supply, and while it lives in one person's Downloads
    folder no report can use it. The sheet's own columns are kept verbatim so a
    re-export can be uploaded without renaming anything.

    ``gl`` is stored as text, not a number. It is an identifier that is never
    arithmetic, and a GL beginning with 0 must survive a round trip through
    Excel and CSV; the uniqueness is on ``gl`` rather than the primary key so a
    mistyped account can be corrected in place rather than deleted and re-added.

    ``outflow_type`` is intentionally NOT a choices field. The observed values
    are "Controllable", "Installed" and blank, but Finance owns that vocabulary
    and a new word in next year's sheet must upload rather than fail validation.
    """

    gl = models.CharField(
        max_length=32, unique=True, db_index=True, verbose_name="GL",
        help_text="General ledger account code, e.g. 170150001.",
    )
    expense_type = models.CharField(
        max_length=120, db_index=True, verbose_name="Expense type",
        help_text='Roll-up line, e.g. "Staff costs", "ICT Expense".',
    )
    operating_expense = models.CharField(
        max_length=160, verbose_name="Operating expense",
        help_text='The expense line as Finance names it, e.g. "Software".',
    )
    outflow_type = models.CharField(
        max_length=40, blank=True, default="", db_index=True,
        verbose_name="Outflow type",
        help_text='Observed values: "Controllable", "Installed", or blank.',
    )
    actual_gl_name = models.CharField(
        max_length=160, blank=True, default="", verbose_name="Actual GL name",
        help_text="The GL's own name, where it differs from the expense line.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    # Re-tagging one GL silently moves money between expense lines in every
    # report that reads this table, so each change keeps its before-image.
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "operating_expense_mapping"
        ordering = ["gl"]
        verbose_name = "Operating expense mapping"
        verbose_name_plural = "Operating expense mappings"

    def __str__(self):
        return f"{self.gl} · {self.expense_type}"


# ── SAP cost analysis ─────────────────────────────────────────────────────────
#
# The CEO deck's costs-per-department and costs-per-expense-line were HARD-CODED
# in the frontend: eighteen departments by nine months, and ten expense lines,
# typed in as constants. They were stale on arrival and April read 10,670 for
# ICT, which is a part-month of postings presented as a month.
#
# The real thing is ``delta.gold_db.sap_cost_data`` in the lake - SAP document
# postings with a cost centre and a GL account on every line. What was missing
# was never the cost data; it was the two things that turn a posting into a
# department figure:
#
#   * which DEPARTMENT a cost centre belongs to  -> SapCostCentre, below
#   * which EXPENSE LINE a GL account rolls up to -> operating_expense_mapping,
#     which has been in this database since migration 0023 with 249 GL accounts
#     and nothing reading it for this
#
# So these models are the mapping and the mirror, and ``cost_analysis.py`` is
# the arithmetic - lifted from the Finance notebook rather than invented, which
# is why its rules are quoted there line by line.


class SapCostCentre(models.Model):
    """Which department and which branch a SAP cost centre is.

    Read out of the Finance team's own cost-analysis notebook, where it was a
    literal list of ~85 dicts. A posting without this mapping is a number with
    nowhere to go, which is what the notebook calls ``unmapped`` and drops.

    ``cost_department`` is the roll-up the CEO deck shows - RETAIL, ICT,
    FINANCE, HR, TREASURY and so on. ``cost_department_2`` is a second level
    that only branches use ("BRANCH BUSINESS"), and it is how a branch is told
    apart from a head-office cost centre inside the same RETAIL department.

    Editable, because cost centres are opened and renamed and a code change
    should not be needed for either.
    """

    cost_centre = models.IntegerField(
        unique=True, verbose_name="Cost centre",
        help_text="SAP KOSTL, as it appears on the posting.")
    cost_centre_name = models.CharField(max_length=120)
    cost_department = models.CharField(
        max_length=80,
        help_text="The roll-up the CEO deck reports: RETAIL, ICT, FINANCE…")
    cost_department_2 = models.CharField(
        max_length=80, blank=True, default="",
        help_text='Second level. "BRANCH BUSINESS" marks a branch cost '
                  'centre, which is how a branch is told apart from a '
                  'head-office one inside the same department.')
    #: Set when ``cost_department_2`` says BRANCH BUSINESS, so the branch
    #: screens do not have to know that string. Kept as a column rather than a
    #: property because the summaries group on it in SQL.
    is_branch = models.BooleanField(default=False)
    #: Excluded from the operating-expense report. The notebook drops
    #: BRANCH GROWTH, which is a holding cost centre and not a place.
    is_reportable = models.BooleanField(
        default=True,
        help_text="Clear this for a holding cost centre that should not "
                  "appear in the report, as BRANCH GROWTH does not.")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "sap_cost_centre"
        ordering = ["cost_department", "cost_centre_name"]
        verbose_name = "SAP cost centre"
        verbose_name_plural = "SAP cost centres"
        indexes = [models.Index(fields=["cost_department"])]

    def save(self, *args, **kwargs):
        # One source of truth for "is this a branch": the second department
        # level the Finance mapping uses.
        self.is_branch = (self.cost_department_2 or "").strip().upper() == \
            "BRANCH BUSINESS"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.cost_centre} · {self.cost_centre_name}"


class SapSubsidiary(models.Model):
    """SAP company code -> which company in the group it is.

    Six of them. Worth having because the cost report separates the bank from
    HFCB-Properties, the insurance arm, the foundation and First Permanent, and
    a department total that silently mixed them would overstate the bank.
    """

    company_code = models.IntegerField(unique=True)
    subsidiary = models.CharField(max_length=80)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "sap_subsidiary"
        ordering = ["company_code"]
        verbose_name = "SAP subsidiary"
        verbose_name_plural = "SAP subsidiaries"

    def __str__(self):
        return f"{self.company_code} · {self.subsidiary}"


class SapCostExclusion(models.Model):
    """A GL account that LOOKS like an operating expense and is not.

    Everything on a 7-series GL is an operating expense except these. In the
    Finance notebook they are three numbers in an ``if`` with a comment, which
    means nobody outside that notebook can see them or change them:

        705190002  loan loss charges
        701010014  lease liability interest
        705190006  interest adjustments

    Counting them would inflate every department's operating cost with charges
    that belong in impairment and interest, so they are held here where they
    can be seen and corrected.
    """

    gl = models.CharField(max_length=30, unique=True)
    reason = models.CharField(max_length=200)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "sap_cost_exclusion"
        ordering = ["gl"]
        verbose_name = "SAP cost exclusion"
        verbose_name_plural = "SAP cost exclusions"

    def __str__(self):
        return f"{self.gl} · {self.reason}"


class SapCostPosting(models.Model):
    """One SAP cost posting, as the extract gives it.

    The grain is the document ITEM, which is what the lake holds and what the
    notebook works from. Keeping it at that grain rather than pre-aggregating
    is deliberate: a department total nobody can break down into its postings
    is a figure nobody can defend, and the same rows answer the department
    view, the branch view and the expense-line view without a second load.

    ``amount`` and ``entry_month`` are computed on the way in rather than at
    read time, because the whole screen is group-bys over them:

    * ``amount`` is ``lcy_amount``, NEGATED when the debit/credit indicator is
      ``H`` (credit). Without that, credits add to a cost instead of reducing
      it and every total is wrong by twice the credits.
    * ``entry_date`` comes from ``assignment_number`` as YYYYMMDD, falling back
      to ``reference_document_number``, which is what the notebook does -
      neither is reliably populated on its own.

    ``snapshot_date`` is the extract the row came from. Each SAP extract is a
    FULL replacement for its date, not an increment, so a load replaces the
    snapshot rather than adding to it.
    """

    # Who and what
    company_code = models.IntegerField(null=True, blank=True)
    document_number = models.CharField(max_length=30, blank=True, default="")
    item_number = models.CharField(max_length=10, blank=True, default="")
    fiscal_year = models.IntegerField(null=True, blank=True, db_index=True)
    posting_key = models.CharField(max_length=10, blank=True, default="")
    cost_element_category = models.CharField(max_length=10, blank=True, default="")
    debit_credit_indicator = models.CharField(
        max_length=2, blank=True, default="",
        help_text='SAP SHKZG. "H" is a credit, "S" a debit.')

    # Where it lands
    cost_centre = models.IntegerField(null=True, blank=True, db_index=True)
    gl_account_number = models.CharField(max_length=30, blank=True, default="",
                                         db_index=True)
    vendor_number = models.CharField(max_length=30, blank=True, default="")
    item_description = models.TextField(blank=True, default="")
    origin = models.CharField(max_length=20, blank=True, default="")

    # Money
    lcy_amount = models.DecimalField(max_digits=20, decimal_places=2,
                                     null=True, blank=True)
    fcy_amount = models.DecimalField(max_digits=20, decimal_places=2,
                                     null=True, blank=True)
    payment_currency = models.CharField(max_length=10, blank=True, default="")
    withholding_tax_base_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True)
    tax_code = models.CharField(max_length=10, blank=True, default="")
    withholding_tax_code = models.CharField(max_length=10, blank=True, default="")
    #: lcy_amount with the credit sign applied. See the class docstring.
    amount = models.DecimalField(max_digits=20, decimal_places=2,
                                 null=True, blank=True)

    # Dates
    assignment_number = models.CharField(max_length=30, blank=True, default="")
    reference_document_number = models.CharField(max_length=30, blank=True,
                                                 default="")
    due_date = models.CharField(max_length=30, blank=True, default="")
    terms_of_payment = models.CharField(max_length=20, blank=True, default="")
    #: Derived from assignment_number, else reference_document_number.
    entry_date = models.DateField(null=True, blank=True)
    #: ``YYYY-MM`` of entry_date. A string on purpose: it is a grouping key and
    #: sorts correctly in that shape, where "Sep-2026" does not.
    entry_month = models.CharField(max_length=7, blank=True, default="",
                                   db_index=True)

    # Provenance
    source_file = models.CharField(max_length=255, blank=True, default="")
    snapshot_date = models.DateField(
        null=True, blank=True, db_index=True,
        help_text="The extract this row came from. Each SAP extract is a full "
                  "replacement for its date, not an increment.")
    loaded_at = models.DateTimeField(auto_now_add=True)
    loaded_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        managed = True
        db_table = "sap_cost_posting"
        verbose_name = "SAP cost posting"
        verbose_name_plural = "SAP cost postings"
        indexes = [
            models.Index(fields=["snapshot_date", "fiscal_year"]),
            models.Index(fields=["entry_month", "cost_centre"]),
            models.Index(fields=["fiscal_year", "gl_account_number"]),
        ]

    def __str__(self):
        return (f"{self.document_number}/{self.item_number} · "
                f"{self.gl_account_number} · {self.amount}")


# ── Customer experience: contactability, CSAT and segment NPS ─────────────────
#
# Two scorecard lines were unscoreable because the figures lived in an Excel the
# CX team e-mailed round: "NPS" (target 60%) and "Portfolio Coverage
# (engagement)" (target 80%). The card could not be finished until that arrived.
#
# These two tables are where CX keeps them instead, and the card reads them. The
# shape is taken from the file CX already produce - "RM Contactability,
# Satisfaction & Segment NPS & CES Q2 2026.xlsx" - so the first load is their
# own workbook and nothing has to be re-keyed:
#
#   Contactability sheet  RM Name | %Contactability   -> portfolio coverage
#   Satisfaction sheet    RM Name | % CSAT            -> the NPS line
#   NPS & CES Summary     segment | NPS | CES         -> per-segment, no RM
#
# One thing in that file is a RULE and not a number. Four RMs carry the text
# "TSC- Give full marks" instead of a percentage, because they are TSC-scheme
# RMs the measure does not apply to. That is kept as a FLAG rather than
# converted to a percentage - see ``full_marks`` below.


class CxRmMetric(models.Model):
    """One RM's customer-experience figures for one period.

    Keyed on the RM NAME as the CX file spells it, because that is the only key
    the file has: it carries no sales code. ``sales_code`` is resolved against
    the roster on the way in and kept here, so the card does not have to match
    names at read time - and a name that resolves to nobody is reported rather
    than dropped, because a missing RM is a missing score.

    ``csat`` feeds the card's NPS line. That is the business's own choice, and
    it is worth being precise about rather than quiet: the card line is called
    NPS, the figure behind it is the RM's CSAT from the Satisfaction sheet, and
    the per-segment NPS in :class:`CxSegmentMetric` is a different measure that
    is not per RM. Calling CSAT "NPS" in the database would have hidden that.
    """

    #: ``2026-Q2`` or ``2026-06``. The CX file is quarterly; a month is
    #: accepted so the cadence can change without a migration.
    period = models.CharField(
        max_length=10, db_index=True,
        help_text="2026-Q2 for a quarter, or 2026-06 for a month.")
    #: Exactly as the CX file spells it, trailing spaces and all - that string
    #: is how a correction finds its row again.
    rm_name = models.CharField(max_length=160)
    #: Resolved from the name against the roster. Blank when no roster knows
    #: that name, which the screen reports.
    sales_code = models.CharField(max_length=40, blank=True, default="",
                                  db_index=True)

    #: Share of the portfolio contacted - the Contactability sheet. Feeds
    #: "Portfolio Coverage (engagement)", target 80%.
    contactability = models.FloatField(null=True, blank=True)
    #: Customer satisfaction - the Satisfaction sheet. Feeds the NPS line,
    #: target 60%.
    csat = models.FloatField(null=True, blank=True)

    #: The TSC rule, kept as a flag rather than a number.
    #:
    #: Four RMs in the Q2 file have "TSC- Give full marks" where a percentage
    #: would be. Writing 1.0 there would make a business rule indistinguishable
    #: from a measured 100%, and writing 0 would score them nought on a measure
    #: that does not apply to them. So the figures stay NULL, this is set, and
    #: the card scores the line at exactly full marks and says why.
    full_marks = models.BooleanField(
        default=False,
        help_text='Set for an RM the measure does not apply to - the file says '
                  '"TSC- Give full marks". The card scores 100% and says so.')
    #: What the file actually said, when it was not a number.
    note = models.CharField(max_length=160, blank=True, default="")

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    source = models.CharField(max_length=160, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "cx_rm_metric"
        ordering = ["-period", "rm_name"]
        verbose_name = "CX metric (RM)"
        verbose_name_plural = "CX metrics (RM)"
        constraints = [
            # One row per RM per period, so a correction replaces the figure
            # rather than stacking a second one beside it.
            models.UniqueConstraint(fields=["period", "rm_name"],
                                    name="cx_unique_rm_per_period"),
        ]
        indexes = [models.Index(fields=["period", "sales_code"])]

    def __str__(self):
        return f"{self.period} · {self.rm_name}"


class CxSegmentMetric(models.Model):
    """Net Promoter Score and Customer Effort Score for one segment.

    From the file's own summary sheet: SME, Personal Banking, Commercial,
    Ultimate, Mortgage Business, Scheme Admin, HFCB Properties, HFCB
    Bancassurance, and an overall figure.

    Not per RM, so no scorecard line reads it today. It is kept because it is
    the real NPS, it is in the same file, and throwing it away would mean
    asking CX for it again the first time somebody wants it on a dashboard.
    """

    period = models.CharField(max_length=10, db_index=True)
    segment = models.CharField(max_length=80)
    nps = models.FloatField(null=True, blank=True)
    ces = models.FloatField(null=True, blank=True)
    #: True for the "OVERALL NPS" row, which is not a segment.
    is_overall = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "cx_segment_metric"
        ordering = ["-period", "segment"]
        verbose_name = "CX metric (segment)"
        verbose_name_plural = "CX metrics (segment)"
        constraints = [
            models.UniqueConstraint(fields=["period", "segment"],
                                    name="cx_unique_segment_per_period"),
        ]

    def __str__(self):
        return f"{self.period} · {self.segment}"


# ── Training hours, from the monthly training return ─────────────────────────
#
# A training line sits on EVERY ONE of the 22 cards - ``business_banking_
# training`` on 7 sales roles, ``personal_banking_training`` on 5, and
# ``bo_training_hours`` on all 10 back-office roles - and not one of them could
# be scored. The card said "Training hours are recorded in the learning system,
# not here", which was true and was the end of the conversation.
#
# They are recorded in ``2026 Training Returns Template - <Mon>_<yy>.xlsx``,
# which HR circulate monthly: one row per person, one column per month, hours
# in the cells. This table is where that return lands.
#
# Checked against the four calibration cards whose RM appears on the Aug 2026
# return, and the Jan-Aug sum reproduces the card's stated actual EXACTLY on
# all four: Charles Muchiri 36.0, Edward Kosgei 38.5, Juspher Muriithi 29.0,
# Gladys Wambui 69.0.
#
# ``staff_pf`` is kept as well as the sales code, and it is the key that
# matters. The return and the roster do not always spell a code the same way -
# the roster has Charles Muchiri as CMM4236 and the return has CM4236 - but
# the PF number is 4236 on both. Matching on the code alone loses him.


class ScTrainingReturn(models.Model):
    """One person's training hours for one month.

    Stored per month rather than as a year-to-date total, because that is the
    shape of the return and because a card is scored to a date: an RM's YTD at
    the end of August is the sum of January to August, and keeping only a
    total would make that impossible to work out after the next upload.
    """

    #: The first of the month the hours were earned in.
    month = models.DateField(db_index=True)

    #: The PF number, digits only. The key that actually matches - see the
    #: note above. Blank only when the return omits it.
    staff_pf = models.CharField(max_length=20, blank=True, default="",
                                db_index=True)
    #: The sales code as the RETURN spells it, which is not always how the
    #: roster spells it.
    sales_code = models.CharField(max_length=40, blank=True, default="",
                                  db_index=True)
    staff_name = models.CharField(max_length=160, blank=True, default="")
    #: Branch and role as the return gives them - kept for the coverage
    #: screen, not used for scoring.
    branch = models.CharField(max_length=120, blank=True, default="")
    staff_role = models.CharField(max_length=80, blank=True, default="")

    #: Hours. Fractional: the return carries 5.4 and 6.45.
    hours = models.FloatField()

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    source = models.CharField(max_length=160, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "sc_training_return"
        ordering = ["-month", "staff_name"]
        verbose_name = "Training return"
        verbose_name_plural = "Training returns"
        constraints = [
            # One row per person per month. A re-upload of the same month
            # corrects the figure rather than stacking a second one beside it,
            # which would double somebody's year.
            models.UniqueConstraint(
                fields=["month", "staff_pf", "sales_code"],
                name="sc_training_unique_person_month"),
        ]
        indexes = [
            models.Index(fields=["month", "staff_pf"]),
            models.Index(fields=["month", "sales_code"]),
        ]

    def __str__(self):
        return f"{self.month:%b %Y} · {self.staff_name or self.sales_code}"


# ── Internal Audit: the branch score and the implementation rate ─────────────
#
# Nine scorecard lines across eight roles read this one small table:
#
#   audit                           diaspora_rm, diaspora_arm      score 1.65
#   bo_branch_audit_branch_audit    6 back-office roles            score 1.65
#   bo_diaspora_audit               bo_csm_diaspora                score 1.65
#   bo_branch_audit_resolution      bo_bom, bo_cash_teller, bo_cso  impl. 85%
#
# None of them could be scored: the figures arrive as a short table from
# Internal Audit - eight branches, a score and an implementation rate - and
# nothing here held it.
#
# It is a BRANCH measure feeding PERSONAL cards, which is what makes it
# different from everything else in this module. One row serves every person
# in that branch, so a branch whose name is spelt differently here from the
# roster silently takes the score away from all of them at once.
#
# **The audit score is LOWER-IS-BETTER.** 1.65 is a grade, not a quantity:
# "Annual audit score of 1.65" means achieve 1.65 or better, and better means
# smaller. The Diaspora card confirms it - an actual of 1.6337 against a target
# of 1.65 scores full marks. Scored the other way round, the branches with the
# worst audits would come top.


class ScAuditReturn(models.Model):
    """One branch's audit result for one period.

    Two measures, because the card treats them as two lines:

    * ``audit_score`` - the graded audit score, 1.65 or better. Smaller is
      better.
    * ``implementation`` - how much of what the audit asked for has been done,
      85% or better. Larger is better.

    Kept in one row because they arrive in one table and are about the same
    audit; split across two tables, loading half of it would be easy to miss.
    """

    #: ``2026`` for an annual audit, or ``2026-09`` if it ever becomes
    #: monthly. The audit score is annual today - the target says so.
    period = models.CharField(
        max_length=10, db_index=True,
        help_text="2026 for the annual audit, or 2026-09 for a month.")

    #: The branch exactly as Internal Audit spell it.
    branch = models.CharField(max_length=120)
    #: Folded for matching - upper case, no punctuation, no "BRANCH" suffix.
    #: Stored rather than computed at read time so the match is one indexed
    #: lookup instead of a scan over every row.
    branch_key = models.CharField(max_length=120, db_index=True, default="")

    #: The graded score. SMALLER IS BETTER - see the note above.
    audit_score = models.FloatField(null=True, blank=True)
    #: Implementation of audit findings, 0-1. Larger is better.
    implementation = models.FloatField(null=True, blank=True)

    note = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    source = models.CharField(max_length=160, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "sc_audit_return"
        ordering = ["-period", "branch"]
        verbose_name = "Audit return"
        verbose_name_plural = "Audit returns"
        constraints = [
            # One row per branch per period, so a correction replaces the
            # figure rather than stacking a second one beside it - and a
            # second row would be read by whichever came first, silently.
            models.UniqueConstraint(fields=["period", "branch_key"],
                                    name="sc_audit_unique_branch_period"),
        ]
        indexes = [models.Index(fields=["period", "branch_key"])]

    def __str__(self):
        return f"{self.period} · {self.branch}"


class CustomerMonthlyActivity(models.Model):
    """Whether a customer transacted in a month, and whether digitally.

    A mirror of ``delta.gold_db.active_channels``, which lives in the lake
    and not in this database. One row per customer per month, which the lake
    table is NOT: there it is a row per customer per product per transaction
    type, and ``digital_cust_status`` is set on the row rather than on the
    customer - an MPESA credit is digital, the interest posting beside it is
    not. The aggregation happens in Trino, so 350,000 lake rows arrive as
    134,000 and the card reads one row per customer-month.

    Why a mirror at all
    ───────────────────
    The scorecard is built on every page view and has to stay fast. Reading
    the lake on that path is exactly the mistake that produced a blank card
    earlier: a heavy read on the card path runs past the worker timeout and
    the browser is handed a dead connection. So this is loaded on a schedule
    and the card reads Postgres.

    "Active" is presence
    ────────────────────
    A customer appears in this feed for a month when they transacted in it,
    and 349,500 of the lake's 350,323 rows carry "Active Customer". So the
    flag is not really a status - it is attendance - and the card's measure,
    "two months active", is attendance in a month AND the month before it.
    """

    cust_id = models.BigIntegerField(db_index=True)
    #: The first of the month. The lake holds "Apr-26" as text; it is parsed
    #: on the way in so this column can be compared and ordered.
    month = models.DateField(db_index=True)

    active = models.BooleanField(default=True)
    #: Any digital channel at all that month - mobile, Whizz, cards or
    #: internet. Which one is not what the card asks.
    digital_active = models.BooleanField(default=False)

    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "staff_management"
        db_table = "sc_customer_monthly_activity"
        verbose_name = "Customer monthly activity"
        verbose_name_plural = "Customer monthly activity"
        constraints = [
            models.UniqueConstraint(fields=["cust_id", "month"],
                                    name="sc_one_activity_per_cust_month"),
        ]
        indexes = [
            # The card's own query: a month's customers, and the month
            # before it, for the customers on one RM's book.
            models.Index(fields=["month", "cust_id"]),
            models.Index(fields=["month", "digital_active"]),
        ]

    def __str__(self):
        return f"{self.cust_id} {self.month:%b %Y}"


class CustomerLastTransaction(models.Model):
    """One row per customer: when they last transacted. Nothing else.

    Why this exists
    ───────────────
    The branch "active / inactive customers" tables ask one question -
    how long is it since this customer last did anything? - and the only
    source for it is ``transaction_diary``, the largest table in the estate.
    Computing ``MAX(tmstamp) GROUP BY customer`` over a year of it, for a
    branch's whole book, ON A PAGE VIEW, is what the sibling mirror above
    already warns against in its own docstring: a heavy read on a request path
    runs past the worker timeout and the browser is handed a dead connection.
    It did exactly that - 25 seconds, cancelled by the database.

    So the heavy read moves off the request. ``load_activity_from_transactions``
    fills this on a schedule and the page joins one indexed row per customer,
    which is the same trade the scorecard already makes.

    Day grain, not month
    ────────────────────
    ``CustomerMonthlyActivity`` above is attendance per MONTH, which cannot
    answer "in the last 7 days". This carries the timestamp itself, so the
    7 / 30 / 60 / 90 day windows and the dormancy spread all come off the one
    column without another feed.

    A customer with no row has not transacted inside the window the refresh
    covers. That is reported as "no transaction in N days" and never as a
    date, and never as zero days - the most dormant a customer can be is not
    the least.
    """

    cust_id = models.BigIntegerField(unique=True)
    #: The most recent transaction seen, within the window the refresh covers.
    last_txn = models.DateTimeField(null=True, blank=True, db_index=True)
    #: How far back the refresh that wrote this row looked, in days. On the
    #: payload so a screen can say "no transaction in 400 days" with the
    #: number the data actually supports rather than one it assumes.
    lookback_days = models.IntegerField(default=0)
    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "staff_management"
        db_table = "customer_last_transaction"
        verbose_name = "Customer last transaction"
        verbose_name_plural = "Customer last transaction"

    def __str__(self):
        return f"{self.cust_id} {self.last_txn or 'never'}"
