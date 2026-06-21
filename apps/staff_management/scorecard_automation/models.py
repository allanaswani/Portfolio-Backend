"""
Scorecard Automation — parallel port of the legacy KPI engine.

This subsystem is a faithful port of the legacy backend's scorecard automation
(KPI / Role / RoleKPIMapping / EmployeePerformanceActual / EmployeeMonthlyPerformance
+ per-KPI calculation strategies). It is ADDITIVE: its tables are namespaced with
the ``sc_`` prefix so they do NOT collide with the new backend's redesigned
scorecard models (which keep ``scorecard_*`` / ``employee_monthly_performance``).

The engine reuses the new backend's existing staff models as inputs:
StaffEmployeeData, EmployeeRoleHistory, LeaveRecord, RmKPIBaseSummary and
MissingEmployeeActual (imported in services), and writes its computed results to
``sc_employee_monthly_performance``.

Two legacy definitions are corrected for Django 6:
  * CheckConstraint uses ``condition=`` (not ``check=``).
"""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F, Sum
from simple_history.models import HistoricalRecords
from simple_history.utils import update_change_reason


class ScKpi(models.Model):
    """Central repository of KPIs used in performance management (legacy KPI)."""
    CALCULATION_CHOICES = [
        ("actual_over_target", "Actual Over Target"),
        ("growth_on_growth", "Growth on Growth"),
        ("percentage_of_target", "Percentage of Target"),
        ("tiered_range", "Tiered Range"),
    ]
    RATING_TYPE_CHOICES = [
        ("nps", "NPS"),
        ("prorate", "Prorate"),
    ]
    kpi_code = models.CharField(max_length=100, unique=True)
    kpi_name = models.CharField(max_length=100)
    kpi_description = models.TextField(blank=True)
    kpi_calculation_mode = models.CharField(
        max_length=100, default="actual_over_target", choices=CALCULATION_CHOICES
    )
    kpi_rating_type = models.CharField(
        max_length=100, default="prorate", choices=RATING_TYPE_CHOICES
    )
    score_cap = models.DecimalField(
        max_digits=3, decimal_places=2,
        validators=[MinValueValidator(0.00), MaxValueValidator(2.00)],
    )
    has_base_value = models.BooleanField(default=False)
    is_increasing = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "staff_management"
        db_table = "sc_kpi_definitions"
        verbose_name = "Scorecard KPI Definition"
        verbose_name_plural = "Scorecard KPI Definitions"
        ordering = ["kpi_code"]

    def __str__(self):
        return f"{self.kpi_code} - {self.kpi_name}"


class ScRole(models.Model):
    """Organization roles for the scorecard engine (legacy Role)."""
    ROLE_TYPE_CHOICES = [
        ("IC", "Individual Contributor"),
        ("MGR", "Manager"),
        ("EXEC", "Executive"),
    ]
    role_code = models.CharField(max_length=100, unique=True)
    role_name = models.CharField(max_length=100, unique=True)
    role_type = models.CharField(max_length=4, choices=ROLE_TYPE_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.save()

    class Meta:
        app_label = "staff_management"
        db_table = "sc_organization_roles"
        verbose_name = "Scorecard Organization Role"
        verbose_name_plural = "Scorecard Organization Roles"
        indexes = [models.Index(fields=["role_type", "role_code", "role_name"])]
        ordering = ["role_name"]

    def __str__(self):
        return f"{self.role_name} ({self.is_active})"


class ScRoleKpiMapping(models.Model):
    """Mapping between roles and KPIs with role-specific targets (legacy RoleKPIMapping)."""
    PLAN_CATEGORY_CHOICES = [
        ("p1", "First Plan"),
        ("p2", "Second Plan"),
        ("p3", "Third Plan"),
        ("p4", "Fourth Plan"),
    ]
    TARGET_CATEGORY_CHOICES = [
        ("full_year", "Full Year Target"),
        ("monthly", "Monthly Target"),
    ]
    role_code = models.CharField(max_length=100)
    kpi_order = models.IntegerField()
    kpi_code = models.CharField(max_length=100)
    mapping_category = models.CharField(max_length=50)
    kpi_target = models.FloatField(null=True, blank=True)
    effective_from = models.DateField()
    effective_to = models.DateField()
    bonus_effective_from = models.DateField()
    bonus_effective_to = models.DateField()
    kpi_weight = models.DecimalField(
        max_digits=6, decimal_places=5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    plan_category = models.CharField(max_length=20, choices=PLAN_CATEGORY_CHOICES)
    target_category = models.CharField(max_length=20, choices=TARGET_CATEGORY_CHOICES)
    prorate = models.BooleanField(default=True)
    is_bonus = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        app_label = "staff_management"
        db_table = "sc_role_kpi_mappings"
        verbose_name = "Scorecard Role-KPI Assignment"
        verbose_name_plural = "Scorecard Role-KPI Assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["role_code", "kpi_code", "effective_from", "effective_to", "plan_category", "is_bonus"],
                name="sc_unique_role_kpi_effective_dates",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__gt=F("effective_from")),
                name="sc_effective_to_after_from",
            ),
        ]
        indexes = [models.Index(fields=["effective_from", "effective_to"])]

    def __str__(self):
        return f"{self.role_code} - {self.kpi_code} ({self.plan_category})"

    def save(self, *args, **kwargs):
        from decimal import Decimal

        total_weight = ScRoleKpiMapping.objects.filter(
            role_code=self.role_code,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            plan_category=self.plan_category,
            is_bonus=False,
        ).exclude(pk=self.pk).aggregate(total=Sum("kpi_weight"))["total"] or Decimal("0")

        # kpi_weight may still be a str/float/Decimal depending on how it was set.
        total_weight = Decimal(str(total_weight)) + Decimal(str(self.kpi_weight))
        if total_weight > 1:
            raise ValidationError(
                f"The total weight for role '{self.role_code}' in plan category "
                f"{self.plan_category} exceeds 1. Current total: {total_weight}"
            )
        super().save(*args, **kwargs)


class ScEmployeePerformanceActual(models.Model):
    """Comprehensive actual performance recording (legacy EmployeePerformanceActual)."""
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    kpi_code = models.CharField(max_length=100)
    eom_date = models.DateField()
    kpi_value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        app_label = "staff_management"
        db_table = "sc_employee_performance_actual_values"
        verbose_name = "Scorecard Performance Actual"
        verbose_name_plural = "Scorecard Performance Actuals"
        constraints = [
            models.UniqueConstraint(
                fields=["sales_code", "kpi_code", "eom_date"],
                name="sc_unique_actual_per_employee_kpi_period",
            )
        ]
        indexes = [
            models.Index(fields=["eom_date", "kpi_code"]),
            models.Index(fields=["sales_code", "eom_date"]),
        ]

    def __str__(self):
        return f"{self.sales_code} - {self.kpi_code} - {self.eom_date}"

    def save(self, *args, **kwargs):
        if self.pk:
            if not getattr(self, "_change_reason", None):
                raise ValidationError("A change reason must be provided when updating this record.")
            update_change_reason(self, self._change_reason)
        super().save(*args, **kwargs)


class ScEmployeeMonthlyPerformance(models.Model):
    """Computed monthly scorecard rows (legacy EmployeeMonthlyPerformance)."""
    sales_code = models.CharField(max_length=255, blank=True, null=True)
    eom_date = models.DateField()
    role_code = models.CharField(max_length=100)
    kpi_order = models.IntegerField()
    kpi_code = models.CharField(max_length=100)
    mapping_category = models.CharField(max_length=50)
    kpi_name = models.CharField(max_length=100)
    kpi_description = models.TextField(blank=True)
    kpi_weight = models.FloatField()
    prev_year_value = models.FloatField(null=True, blank=True)
    kpi_target = models.FloatField(null=True, blank=True)
    curr_year_value = models.FloatField(null=True, blank=True)
    ytd_target = models.FloatField()
    ytd_actual = models.FloatField()
    ytd_score = models.FloatField()
    ytd_weighted_score = models.FloatField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "staff_management"
        db_table = "sc_employee_monthly_performance"
        verbose_name = "Scorecard Employee Monthly Performance"
        verbose_name_plural = "Scorecard Employee Monthly Performances"
        ordering = ["-eom_date", "sales_code", "kpi_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["sales_code", "kpi_code", "eom_date", "kpi_order"],
                name="sc_unique_employee_performance_per_scorecard_period",
            )
        ]
        indexes = [
            models.Index(fields=["eom_date", "kpi_code"]),
            models.Index(fields=["sales_code", "eom_date"]),
            models.Index(fields=["role_code", "eom_date"]),
        ]

    def __str__(self):
        return f"{self.sales_code} - {self.eom_date}"
