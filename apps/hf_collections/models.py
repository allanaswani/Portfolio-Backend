from datetime import date

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


class Collection(models.Model):
    cust_id = models.IntegerField(blank=True, null=True)
    loan_account_no = models.BigIntegerField(blank=True, null=True)
    collection_officer_code = models.CharField(max_length=100, blank=True, null=True)
    collection_officer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    contactibility = models.CharField(max_length=100, blank=True, null=True)
    reasons_for_default = models.CharField(max_length=255, blank=True, null=True)
    outcomes = models.CharField(max_length=255, blank=True, null=True)
    foreclosure_outcomes = models.CharField(max_length=255, blank=True, null=True)
    ptp_amount = models.BigIntegerField(blank=True, null=True)
    profiling = models.CharField(max_length=255, blank=True, null=True)
    next_action = models.CharField(max_length=255, blank=True, null=True)
    next_action_date = models.DateField(blank=True, null=True)
    additional_comments = models.TextField(blank=True, null=True)
    additional_contacts_1 = models.CharField(max_length=100, blank=True, null=True)
    additional_contacts_2 = models.CharField(max_length=100, blank=True, null=True)
    additional_contacts_3 = models.CharField(max_length=100, blank=True, null=True)
    recording_date = models.DateField(default=date.today)
    collection_status = models.CharField(max_length=50, default="closed")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hf_collections_feedback"
