from django.db import models


class Insight(models.Model):
    CATEGORY_CHOICES = [
        ("deposits", "Deposits"),
        ("loans", "Loans"),
        ("customers", "Customers"),
        ("revenue", "Revenue"),
        ("collections", "Collections"),
        ("risk", "Risk"),
        ("performance", "Performance"),
    ]
    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
        ("positive", "Positive"),
    ]

    title = models.CharField(max_length=500)
    body = models.TextField()
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=20)
    severity = models.CharField(choices=SEVERITY_CHOICES, max_length=10, default="info")
    segment = models.CharField(max_length=100, blank=True, null=True)
    branch = models.CharField(max_length=100, blank=True, null=True)
    metric_value = models.DecimalField(max_digits=30, decimal_places=5, blank=True, null=True)
    metric_delta = models.DecimalField(max_digits=30, decimal_places=5, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = "portfolio_insights"
        ordering = ["-generated_at"]
        indexes = [
            models.Index(fields=["category", "generated_at"]),
            models.Index(fields=["is_active", "generated_at"]),
        ]
