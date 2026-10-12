"""Serializers for the SAP cost mappings and postings."""

from rest_framework import serializers

from .models import (
    SapCostCentre, SapCostExclusion, SapCostPosting, SapSubsidiary,
)


class SapCostCentreSerializer(serializers.ModelSerializer):
    class Meta:
        model = SapCostCentre
        fields = "__all__"
        # Set by the model's save() from cost_department_2, so one answer to
        # "is this a branch" rather than two that can disagree.
        read_only_fields = ("is_branch", "updated_at", "updated_by")


class SapSubsidiarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SapSubsidiary
        fields = "__all__"
        read_only_fields = ("updated_at",)


class SapCostExclusionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SapCostExclusion
        fields = "__all__"
        read_only_fields = ("updated_at", "updated_by")


class SapCostPostingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SapCostPosting
        fields = "__all__"
        # The whole row is written by the loader, never through the API: a
        # posting typed in by hand would be a cost with no document behind it.
        read_only_fields = tuple(
            field.name for field in SapCostPosting._meta.fields)
