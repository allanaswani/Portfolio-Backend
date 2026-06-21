from rest_framework import serializers
from .models import (
    Project, Targets, Sales, ObligationSummary, CrmProject, CrmSalesRecord,
    LegacyProject, LegacySalesRecord, HfdiManualFinanceEntry, HfdiTargets,
    HfdiEmployeeData, HfdiEmployeeDataSalesRecord, HfdiScorecardPerformanceRecord,
    WeightedDashboardManualSales, HfdiCustomersHfcMortgages,
    HfdiProjectsDailyCollectionsData, HfdiProjectsInventorySalesData,
    AffordableHousingApplication, AffordableHousingRegistrations,
    AffordableHousingProjectsPipeline, AFHSellerMapping,
)


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = "__all__"


class TargetsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Targets
        fields = "__all__"


class SalesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sales
        fields = "__all__"


class ObligationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ObligationSummary
        fields = "__all__"


class CrmProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrmProject
        fields = "__all__"


class CrmSalesRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrmSalesRecord
        fields = "__all__"


class LegacyProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegacyProject
        fields = "__all__"


class LegacySalesRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegacySalesRecord
        fields = "__all__"


class HfdiManualFinanceEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiManualFinanceEntry
        fields = "__all__"


class HfdiTargetsSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiTargets
        fields = "__all__"


class HfdiEmployeeDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiEmployeeData
        fields = "__all__"


class HfdiEmployeeDataSalesRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiEmployeeDataSalesRecord
        fields = "__all__"


class HfdiScorecardPerformanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiScorecardPerformanceRecord
        fields = "__all__"


class WeightedDashboardManualSalesSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeightedDashboardManualSales
        fields = "__all__"


class HfdiCustomersHfcMortgagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiCustomersHfcMortgages
        fields = "__all__"


class HfdiProjectsDailyCollectionsDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiProjectsDailyCollectionsData
        fields = "__all__"


class HfdiProjectsInventorySalesDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfdiProjectsInventorySalesData
        fields = "__all__"


class AffordableHousingApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AffordableHousingApplication
        fields = "__all__"


class AffordableHousingRegistrationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AffordableHousingRegistrations
        fields = "__all__"


class AffordableHousingProjectsPipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = AffordableHousingProjectsPipeline
        fields = "__all__"


class AFHSellerMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AFHSellerMapping
        fields = "__all__"
