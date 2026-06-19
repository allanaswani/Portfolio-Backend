from django.db import models
from simple_history.models import HistoricalRecords


class RightsIssueApplication(models.Model):
    STATUS_CHOICES = [
        ("Submitted", "Submitted"),
        ("Under Review", "Under Review"),
        ("Allotted", "Allotted"),
        ("Partially Allotted", "Partially Allotted"),
        ("Rejected", "Rejected"),
        ("Refunded", "Refunded"),
    ]
    PAYMENT_STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Received", "Received"),
        ("Bounced", "Bounced"),
    ]

    application_number = models.CharField(max_length=100, unique=True, blank=True, null=True)
    applicant_name = models.CharField(max_length=255)
    national_id = models.CharField(max_length=50, blank=True, null=True)
    cds_account = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    existing_shares = models.BigIntegerField(default=0)
    rights_entitlement = models.BigIntegerField(default=0)
    rights_applied = models.BigIntegerField(default=0)
    additional_shares_applied = models.BigIntegerField(default=0)
    share_price = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    amount_payable = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    amount_paid = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    payment_status = models.CharField(choices=PAYMENT_STATUS_CHOICES, max_length=20, default="Pending")
    payment_reference = models.CharField(max_length=255, blank=True, null=True)
    payment_date = models.DateField(blank=True, null=True)
    shares_allotted = models.BigIntegerField(default=0)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status = models.CharField(choices=STATUS_CHOICES, max_length=20, default="Submitted")
    application_date = models.DateField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)
    input_user = models.CharField(max_length=100, default="me")
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hf_rights_issue_applications"
        ordering = ["-application_date"]

    def __str__(self):
        return f"{self.applicant_name} - {self.application_number}"
