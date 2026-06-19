from django.db import models


class Slide(models.Model):
    CONTENT_TYPE_CHOICES = [
        ("deposits_summary", "Deposits Summary"),
        ("loans_summary", "Loans Summary"),
        ("customers_summary", "Customers Summary"),
        ("revenue_summary", "Revenue Summary"),
        ("arrears_summary", "Arrears Summary"),
        ("segment_breakdown", "Segment Breakdown"),
        ("branch_performance", "Branch Performance"),
        ("hfdi_performance", "HFDI Performance"),
        ("collections_summary", "Collections Summary"),
        ("custom", "Custom"),
    ]

    title = models.CharField(max_length=255)
    content_type = models.CharField(choices=CONTENT_TYPE_CHOICES, max_length=50)
    payload = models.JSONField(default=dict)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    generated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = "slideshow_slides"
        ordering = ["order", "-generated_at"]

    def __str__(self):
        return self.title
