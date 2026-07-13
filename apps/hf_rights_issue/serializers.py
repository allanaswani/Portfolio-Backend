from rest_framework import serializers
from .models import RightsIssueApplication, SecurityDetail


class RightsIssueApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RightsIssueApplication
        fields = "__all__"


class SecurityDetailSerializer(serializers.ModelSerializer):
    """Full SecurityDetail row plus aliases matching the field names the rights
    issue uptake page reads (shareholder_name, cds_account, total_shares, uptake,
    registrar), so the table/KPIs populate without frontend changes."""

    shareholder_name = serializers.CharField(source="account_name", read_only=True)
    cds_account = serializers.CharField(source="account_number", read_only=True)
    total_shares = serializers.DecimalField(source="current_shares", max_digits=20, decimal_places=2, read_only=True)
    uptake = serializers.CharField(source="rights_taken", read_only=True)
    registrar = serializers.CharField(source="stock_broker_agent_name", read_only=True)

    class Meta:
        model = SecurityDetail
        fields = "__all__"
