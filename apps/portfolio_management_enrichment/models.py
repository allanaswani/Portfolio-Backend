from django.db import models
from simple_history.models import HistoricalRecords


class CustomerEnrichment(models.Model):
    cust_id = models.BigIntegerField(unique=True)
    income_band = models.CharField(max_length=50, blank=True, null=True)
    employment_status = models.CharField(max_length=100, blank=True, null=True)
    employer = models.CharField(max_length=255, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    monthly_income_estimate = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    property_owner = models.BooleanField(null=True, blank=True)
    credit_score = models.IntegerField(blank=True, null=True)
    risk_rating = models.CharField(max_length=20, blank=True, null=True)
    lifetime_value_estimate = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    preferred_channel = models.CharField(max_length=50, blank=True, null=True)
    data_source = models.CharField(max_length=100, blank=True, null=True)
    enrichment_date = models.DateField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "portfolio_customer_enrichment"
        ordering = ["-updated_at"]


class RmTarget(models.Model):
    sales_code = models.CharField(max_length=50)
    month = models.DateField()
    deposit_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    loan_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    revenue_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    new_customers_target = models.IntegerField(default=0)
    recording_date = models.DateField(auto_now_add=True)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "portfolio_rm_targets"
        unique_together = (("sales_code", "month"),)
