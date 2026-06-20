from django.db import models
from simple_history.models import HistoricalRecords

# TODO - Missing Models
# This app is to track the execution of strategic initiatives for the company. The order is from Strategic Thrust -> Strategic Initiative -> Milestone - for execution per initiative
# Get more info from Allan on the execution of initiatives to guide the incrporation of initial models created and their relevance to the architecture of the module
# 
# Add the following models, and their consequent implementations (serializers, views and urls): 
# StrategicExcoOwner
# StrategicThrust
# StrategicMilestone

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
