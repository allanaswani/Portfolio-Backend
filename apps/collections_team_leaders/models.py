from django.db import models


class LoanRepayments(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField(blank=True, null=True)
    loan_account_number = models.CharField(max_length=100, blank=True, null=True)
    transaction_code = models.IntegerField(blank=True, null=True)
    transaction_description = models.CharField(max_length=255, blank=True, null=True)
    channel_id = models.IntegerField(blank=True, null=True)
    product_id = models.IntegerField(blank=True, null=True)
    justific_description = models.CharField(max_length=255, blank=True, null=True)
    sex = models.CharField(max_length=1, blank=True, null=True)
    principal_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    interest_paid = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    total_drawndown_amount = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    balance = models.DecimalField(max_digits=20, decimal_places=5, blank=True, null=True)
    transaction_time = models.TimeField(blank=True, null=True)
    transaction_date = models.DateTimeField(blank=True, null=True)
    transaction_timestamp = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "loan_repayments"
