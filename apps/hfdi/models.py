from datetime import date
from decimal import Decimal

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords



class Project(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        managed = True
        db_table = "projects"

    def __str__(self):
        return self.name


class Targets(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    pm = models.CharField(max_length=255, blank=True, null=True)
    rm = models.CharField(max_length=255, blank=True, null=True)
    month = models.CharField(max_length=50, blank=True, null=True)
    volume = models.IntegerField(blank=True, null=True)
    value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    income = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    collections_value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    recording_date = models.DateField(default=date.today)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hfdi_target_feedback"


class Sales(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    pm = models.CharField(max_length=255, blank=True, null=True)
    month = models.DateField(default=date.today)
    mtd_volume = models.IntegerField(default=0)
    ytd_volume = models.IntegerField(default=0)
    mtd_value = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    ytd_value = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    ytd_income = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    recording_date = models.DateField(default=date.today)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hfdi_sales_data"


class ObligationSummary(models.Model):
    obligation_summary = models.CharField(max_length=255, blank=True, null=True)
    total_obligation = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    current_year_obligation = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    obligation_honored = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    outstanding_balance = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    recording_date = models.DateField(default=date.today)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "obligation_summary"


class CrmProject(models.Model):
    id = models.BigAutoField(primary_key=True)
    project_id = models.IntegerField(unique=True)
    project_name = models.CharField(max_length=100)
    recording_date = models.DateTimeField(default=date.today)

    class Meta:
        managed = True
        db_table = "hfdi_crm_projects"


class CrmSalesRecord(models.Model):
    project_id = models.IntegerField()
    sale_month = models.DateField()
    mtd_volume = models.IntegerField(default=0)
    ytd_volume = models.IntegerField(default=0)
    mtd_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    ytd_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    recording_date = models.DateTimeField(default=date.today)

    class Meta:
        managed = True
        db_table = "hfdi_crm_sales_data"


class LegacyProject(models.Model):
    id = models.BigAutoField(primary_key=True)
    project_id = models.IntegerField(unique=True, blank=True, null=True)
    project_name = models.CharField(max_length=255)
    recording_date = models.DateTimeField(default=date.today)
    input_user = models.CharField(max_length=100, default="me")

    def save(self, *args, **kwargs):
        if not self.project_id:
            last = LegacyProject.objects.order_by("-project_id").first()
            self.project_id = (last.project_id + 1) if last and last.project_id else 1000
        super().save(*args, **kwargs)

    class Meta:
        managed = True
        db_table = "hfdi_legacy_projects"


class LegacySalesRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    project_id = models.IntegerField()
    mtd_volume = models.IntegerField(default=0)
    ytd_volume = models.IntegerField(default=0)
    sale_month = models.DateField()
    mtd_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    ytd_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    recording_date = models.DateTimeField(default=date.today)
    input_user = models.CharField(max_length=100, default="me")

    class Meta:
        managed = True
        db_table = "hfdi_legacy_sales_data"


class HfdiManualFinanceEntry(models.Model):
    id = models.BigAutoField(primary_key=True)
    project_id = models.IntegerField()
    sale_month = models.DateField()
    mtd_revenue_booked = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    mtd_revenue_collect = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    ytd_revenue_booked = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    ytd_revenue_collect = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    recording_date = models.DateField(default=date.today)
    input_user = models.CharField(max_length=100, default="me")

    class Meta:
        managed = True
        db_table = "hfdi_manual_sales_data"


class HfdiTargets(models.Model):
    id = models.BigAutoField(primary_key=True)
    project_id = models.IntegerField()
    pm = models.CharField(max_length=255, blank=True, null=True)
    rm = models.CharField(max_length=255, blank=True, null=True)
    sales_manager = models.CharField(max_length=255, blank=True, null=True)
    team_leader = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    month = models.CharField(max_length=50, blank=True, null=True)
    target_start_date = models.CharField(max_length=50, default="")
    target_sales_end_date = models.CharField(max_length=50, default="")
    target_collections_end_date = models.CharField(max_length=50, default="")
    volume = models.IntegerField(blank=True, null=True)
    value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    income = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    collections_value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    historical_value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    current_sales_value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    recording_date = models.DateField(default=date.today)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hfdi_performance_target_feedback"


class HfdiEmployeeData(models.Model):
    staff_pf_number = models.IntegerField()
    lead_officer_id = models.IntegerField(default=0, verbose_name="HFDI ERP ID")
    afh_name = models.CharField(max_length=255, blank=True, null=True)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    staff_unit = models.CharField(max_length=255, blank=True, null=True)
    staff_role = models.CharField(max_length=255, blank=True, null=True)
    sales_code = models.CharField(max_length=100, blank=True, null=True)
    primary_project = models.CharField(max_length=255, blank=True, null=True)
    team_leader = models.CharField(max_length=255, blank=True, null=True)
    employment_date = models.DateField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    exit_date = models.DateField(blank=True, null=True)
    active = models.IntegerField(default=1)
    staff_exit = models.IntegerField(default=0)
    target_sales = models.IntegerField(blank=True, null=True)
    target_collections = models.IntegerField(blank=True, null=True)
    input_user = models.CharField(max_length=100, default="me")
    updated_at = models.DateField(auto_now=True)
    created_at = models.DateField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hfdi_employee_data"


class HfdiEmployeeDataSalesRecord(models.Model):
    staff_pf_number = models.IntegerField()
    sale_month = models.DateField()
    mtd_volume = models.IntegerField(blank=True, null=True)
    mtd_collections = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    input_user = models.CharField(max_length=100, default="me")
    recording_date = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hfdi_employee_sales_data"


class HfdiScorecardPerformanceRecord(models.Model):
    staff_pf_number = models.IntegerField()
    scorecard_month = models.DateField()
    performance_score = models.DecimalField(max_digits=5, decimal_places=3)
    input_user = models.CharField(max_length=100, default="me")
    recording_date = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hfdi_employee_scorecard_performance_data"


class WeightedDashboardManualSales(models.Model):
    project_name = models.CharField(max_length=255, blank=True, null=True)
    unit_name = models.CharField(max_length=255, blank=True, null=True)
    unit_status = models.CharField(max_length=100, blank=True, null=True)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    payment_mode = models.CharField(max_length=100, blank=True, null=True)
    lead_id = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    unit_value = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    total_payments = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    prev_year_paid_amounts = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    curr_year_paid_amounts = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    perc_paid = models.FloatField(blank=True, null=True)
    booking_date = models.DateField(blank=True, null=True)
    sale_month = models.DateField(blank=True, null=True)
    etl_date_updated = models.DateField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = "weighted_dashboard_manual_sales_table"


class HfdiCustomersHfcMortgages(models.Model):
    project = models.CharField(max_length=255, blank=True, null=True)
    unit = models.CharField(max_length=255, blank=True, null=True)
    client = models.CharField(max_length=255, blank=True, null=True)
    payment_type = models.CharField(max_length=100, blank=True, null=True)
    mortgage_financier = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    application_number = models.CharField(max_length=100, blank=True, null=True)
    bank_rm = models.CharField(max_length=255, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    first_pay_date = models.DateField(blank=True, null=True)
    total_cost = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    total_paid = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    application_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    perc_paid = models.DecimalField(max_digits=10, decimal_places=5, blank=True, null=True)
    balance = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    mortgage_stage = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "hfdi_customers_hfc_mortgages"


class HfdiProjectsDailyCollectionsData(models.Model):
    project_name = models.CharField(max_length=255, blank=True, null=True)
    unit_name = models.CharField(max_length=255, blank=True, null=True)
    unit_status = models.CharField(max_length=100, blank=True, null=True)
    verified = models.CharField(max_length=100, blank=True, null=True)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    sale_month = models.DateField(blank=True, null=True)
    paid_month = models.DateField(blank=True, null=True)
    entry_month = models.DateField(blank=True, null=True)
    unit_value = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "hfdi_projects_daily_collections_data"


class HfdiProjectsInventorySalesData(models.Model):
    project_name = models.CharField(max_length=255, blank=True, null=True)
    unit_name = models.CharField(max_length=255, blank=True, null=True)
    unit_status = models.CharField(max_length=100, blank=True, null=True)
    staff_name = models.CharField(max_length=255, blank=True, null=True)
    payment_mode = models.CharField(max_length=100, blank=True, null=True)
    unit_value = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    total_payments = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    perc_paid = models.DecimalField(max_digits=10, decimal_places=5, blank=True, null=True)
    perc_paid_prev_month = models.DecimalField(max_digits=10, decimal_places=5, blank=True, null=True)
    prev_year_paid_amounts = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    curr_year_paid_amounts = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    jan_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Jan Paid Amount")
    feb_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Feb Paid Amount")
    mar_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Mar Paid Amount")
    apr_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Apr Paid Amount")
    may_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="May Paid Amount")
    jun_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Jun Paid Amount")
    jul_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Jul Paid Amount")
    aug_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Aug Paid Amount")
    sep_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Sep Paid Amount")
    oct_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Oct Paid Amount")
    nov_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Nov Paid Amount")
    dec_paid_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="Dec Paid Amount")
    jan_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    feb_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    mar_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    apr_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    may_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    jun_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    jul_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    aug_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    sep_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    oct_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    nov_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    dec_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    booking_date = models.DateField(blank=True, null=True)
    sale_month = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "hfdi_projects_inventory_sales_data"


class AffordableHousingApplication(models.Model):
    application_id = models.CharField(max_length=100, blank=True, null=True)
    timestamp = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    assisted_by = models.CharField(max_length=255, blank=True, null=True)
    preferred_typology = models.CharField(max_length=100, blank=True, null=True)
    typology = models.CharField(max_length=100, blank=True, null=True)
    house_type = models.CharField(max_length=100, blank=True, null=True)
    mode_of_payment = models.CharField(max_length=100, blank=True, null=True)
    need_deposit_assitance = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    phone_number = models.BigIntegerField(blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, null=True)
    deposits = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    unit_price = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "affordable_housing_applications"


class AffordableHousingRegistrations(models.Model):
    """Affordable-housing prospect registrations (port of legacy model)."""
    timestamp = models.DateTimeField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.BigIntegerField(unique=True)
    email = models.CharField(max_length=255, blank=True, null=True)
    assisted_by = models.CharField(max_length=255, blank=True, null=True)
    user_deposits = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    typology = models.CharField(max_length=200, blank=True, null=True)
    house_type = models.CharField(max_length=200, default="default")
    project = models.CharField(max_length=200, blank=True, null=True)
    unit_price = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "affordable_housing_registrations"
        verbose_name = "Affordable Housing Registration"
        verbose_name_plural = "Affordable Housing Registrations"

    def __str__(self):
        return f"{self.name} - {self.project} - {self.typology}"


class AffordableHousingProjectsPipeline(models.Model):
    """Pipeline of affordable-housing projects (port of legacy model)."""
    project_name = models.CharField(max_length=255)
    region = models.CharField(max_length=255)
    county = models.CharField(max_length=255)
    mapping = models.CharField(max_length=255, blank=True, null=True)
    units = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    projected_completion_date = models.CharField(max_length=255, blank=True, null=True)
    completion_date = models.DateField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "affordable_housing_projects_pipeline"
        verbose_name = "Affordable Housing Projects Pipeline"
        verbose_name_plural = "Affordable Housing Projects Pipeline"

    def __str__(self):
        return f"{self.project_name} - {self.county}"


class AFHSellerMapping(models.Model):
    """Maps AFH sellers/staff to their org units (port of legacy model)."""
    staff_id = models.CharField(max_length=255, blank=True, null=True)
    afh_name = models.CharField(max_length=255, blank=True, null=True)
    staff_subsidiary = models.CharField(max_length=255, blank=True, null=True)
    staff_unit = models.CharField(max_length=255, blank=True, null=True)
    org_unit = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "afh_seller_mapping"
        verbose_name = "AFH Seller Mapping"
        verbose_name_plural = "AFH Seller Mappings"

    def __str__(self):
        return f"{self.staff_id} - {self.name}"
