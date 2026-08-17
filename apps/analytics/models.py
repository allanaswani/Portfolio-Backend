from django.conf import settings
from django.db import models


class UserActivityEvent(models.Model):
    """One row per tracked user action in the SPA (page view / feature click).

    Populated by the frontend, which POSTs a lightweight event on each route
    change — with client-side routing the backend never sees navigations
    otherwise. Backs the Administration "Usage Analytics" screen: last activity
    per user, the most-used areas of the app, and a recent-activity feed. Login
    times come from auth_user.last_login (SIMPLE_JWT UPDATE_LAST_LOGIN=True), not
    from here."""

    EVENT_CHOICES = [
        ("pageview", "Page view"),
        ("click", "Click"),
        ("action", "Action"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activity_events",
    )
    path = models.CharField(max_length=300)
    label = models.CharField(max_length=150, blank=True, default="")
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, default="pageview")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "user_activity_events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["path"]),
            models.Index(fields=["created_at"]),
        ]


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
