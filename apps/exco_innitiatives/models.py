from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

# Strategic-execution hierarchy (ported from the legacy backend):
#   Strategic Thrust -> Strategic Initiative -> Strategic Milestone,
# with Strategic ExCo Owners as the people accountable for execution.
# These live alongside the flat ``ExcoInitiative`` table (different db_tables),
# so adding them is additive and does not disturb existing data.


class StrategicExcoOwner(models.Model):
    owner_id = models.BigAutoField(primary_key=True)
    owner_name = models.CharField(max_length=255)
    owner_division = models.CharField(max_length=255)
    owner_designation = models.CharField(max_length=255)
    sales_code = models.CharField(max_length=255, null=True, default="1")
    owner_ranking = models.BigIntegerField(null=True, default=1)
    email = models.EmailField(unique=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.owner_name

    class Meta:
        managed = True
        db_table = "exco_owners"
        ordering = ["owner_name"]


class StrategicThrust(models.Model):
    thrust_id = models.BigAutoField(primary_key=True)
    thrust_name = models.CharField(max_length=255)
    thrust_description = models.CharField(max_length=255)
    thrust_start_date = models.DateField(blank=True, null=True)
    thrust_end_date = models.DateField(blank=True, null=True)
    recording_date = models.DateField(default=timezone.now)
    history = HistoricalRecords()

    def __str__(self):
        return self.thrust_name

    class Meta:
        managed = True
        db_table = "exco_strategic_thrust"
        ordering = ["-recording_date"]


class StrategicInitiative(models.Model):
    initiative_id = models.BigAutoField(primary_key=True)
    thrust = models.ForeignKey(StrategicThrust, on_delete=models.CASCADE)
    initiative_name = models.CharField(max_length=255)
    initiative_description = models.CharField(max_length=255, blank=True, null=True)
    initiative_start_date = models.DateField(blank=True, null=True)
    initiative_end_date = models.DateField(blank=True, null=True)
    recording_date = models.DateField(default=timezone.now)
    primary_owner = models.CharField(max_length=255, blank=True, null=True)
    co_owners = models.CharField(max_length=255, blank=True, null=True)
    co_owner_1 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_2 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_3 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_4 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_5 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_6 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_7 = models.CharField(max_length=255, blank=True, null=True)
    initiative_status = models.CharField(max_length=255)
    user_comments = models.CharField(max_length=1000, blank=True, null=True)
    admin_comments = models.CharField(max_length=1000, blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.initiative_name} (Thrust: {self.thrust.thrust_name})"

    class Meta:
        managed = True
        db_table = "exco_strategic_initiatives"
        ordering = ["-recording_date"]


class StrategicMilestone(models.Model):
    milestone_id = models.BigAutoField(primary_key=True)
    thrust = models.ForeignKey(StrategicThrust, on_delete=models.CASCADE)
    initiative = models.ForeignKey(StrategicInitiative, on_delete=models.CASCADE)
    milestone_name = models.CharField(max_length=255)
    milestone_description = models.CharField(max_length=255)
    milestone_start_date = models.DateField(blank=True, null=True)
    milestone_end_date = models.DateField(blank=True, null=True)
    recording_date = models.DateField(default=timezone.now)
    primary_owner = models.CharField(max_length=255, blank=True, null=True)
    co_owner_1 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_2 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_3 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_4 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_5 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_6 = models.CharField(max_length=255, blank=True, null=True)
    co_owner_7 = models.CharField(max_length=255, blank=True, null=True)
    milestone_status = models.CharField(max_length=255)
    review_status = models.CharField(max_length=255, default="", blank=True, null=True)
    proportion_contribution = models.FloatField()
    proportion_complete = models.FloatField()
    approved_proportion_complete = models.FloatField()
    user_comments = models.CharField(max_length=1000, blank=True, null=True)
    admin_comments = models.CharField(max_length=1000, blank=True, null=True)
    update_type = models.CharField(max_length=255, blank=True, null=True)
    sensitivity = models.FloatField(blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.milestone_name} (Thrust: {self.thrust.thrust_name})"

    class Meta:
        managed = True
        db_table = "exco_strategic_milestones"
        ordering = ["-recording_date"]


class ExcoInitiative(models.Model):
    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("In Progress", "In Progress"),
        ("On Hold", "On Hold"),
        ("Completed", "Completed"),
        ("Cancelled", "Cancelled"),
    ]
    PRIORITY_CHOICES = [
        ("Low", "Low"),
        ("Medium", "Medium"),
        ("High", "High"),
        ("Critical", "Critical"),
    ]

    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)
    strategic_objective = models.TextField(blank=True, null=True)
    owner = models.CharField(max_length=255, blank=True, null=True)
    sponsor = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(choices=STATUS_CHOICES, max_length=20, default="Draft")
    priority = models.CharField(choices=PRIORITY_CHOICES, max_length=10, default="Medium")
    target_completion_date = models.DateField(blank=True, null=True)
    actual_completion_date = models.DateField(blank=True, null=True)
    budget_allocated = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    budget_utilised = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    progress_percentage = models.IntegerField(default=0)
    remarks = models.TextField(blank=True, null=True)
    recording_date = models.DateField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "exco_initiatives"
        ordering = ["-recording_date"]

    def __str__(self):
        return self.title
