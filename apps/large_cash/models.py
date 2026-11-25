"""Large cash transactions: every cash deposit or withdrawal of KES 500,000
or more (the foreign-currency ones at their KES equivalent), one row per
transaction, read off the lake's deposit transaction recording. See lake.py."""
from django.db import models


class LargeCashTransaction(models.Model):
    """One cash transaction at or above the threshold. Keyed the way the
    bank keys a transaction: date, unit, user, user serial, internal serial
    (the diary ETL's TRANSACTION_REF)."""

    DEPOSIT, WITHDRAWAL = "deposit", "withdrawal"

    trx_date = models.DateField(db_index=True)
    unit = models.IntegerField()
    teller = models.CharField(max_length=40)
    user_sn = models.BigIntegerField()
    internal_sn = models.BigIntegerField()

    posted_at = models.DateTimeField(null=True, blank=True)
    branch = models.CharField(max_length=120, blank=True, default="", db_index=True)
    teller_name = models.CharField(max_length=200, blank=True, default="")
    account_number = models.CharField(max_length=40, blank=True, default="", db_index=True)
    customer_id = models.CharField(max_length=40, blank=True, default="", db_index=True)
    account_name = models.CharField(max_length=300, blank=True, default="")
    justific_id = models.IntegerField()
    transaction_type = models.CharField(max_length=120)
    direction = models.CharField(max_length=12)
    currency = models.CharField(max_length=60, blank=True, default="")
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    amount_kes = models.DecimalField(max_digits=20, decimal_places=2)
    channel = models.CharField(max_length=120, blank=True, default="")
    comments = models.CharField(max_length=500, blank=True, default="")
    reversed = models.BooleanField(default=False)
    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "large_cash_transaction"
        ordering = ("-trx_date", "-amount_kes")
        constraints = [models.UniqueConstraint(
            fields=("trx_date", "unit", "teller", "user_sn", "internal_sn"),
            name="large_cash_one_row_per_transaction")]


class LargeCashDay(models.Model):
    """What a day's load found: how many, how much, when it was read. A day
    with no row here was never read - not a day with no large cash."""

    day = models.DateField(unique=True)
    transactions = models.IntegerField(default=0)
    total_kes = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    loaded_at = models.DateTimeField(auto_now=True)
    loaded_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        db_table = "large_cash_day"
        ordering = ("-day",)
