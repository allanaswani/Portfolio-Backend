from django.db import models


class AnalyticsSnapshot(models.Model):
    CATEGORY_CHOICES = [
        ("deposits", "Deposits"),
        ("loans", "Loans"),
        ("customers", "Customers"),
        ("revenue", "Revenue"),
        ("collections", "Collections"),
    ]

    category = models.CharField(choices=CATEGORY_CHOICES, max_length=50)
    metric_name = models.CharField(max_length=255)
    metric_value = models.DecimalField(max_digits=30, decimal_places=5)
    segment = models.CharField(max_length=100, blank=True, null=True)
    branch = models.CharField(max_length=100, blank=True, null=True)
    period_start = models.DateField()
    period_end = models.DateField()
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "analytics_snapshots"
        ordering = ["-computed_at"]
        indexes = [
            models.Index(fields=["category", "period_start"]),
            models.Index(fields=["segment", "period_start"]),
        ]
