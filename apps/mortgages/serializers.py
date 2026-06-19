from rest_framework import serializers

from .models import (
    MortgageProduct, Borrower, Property, MortgageApplication, LoanApproval,
    MortgageLoan, RepaymentScheduleItem, Payment, Fee, MortgageInsurancePolicy,
    MortgageDocument, LeadSource, Campaign, FieldAgent, Lead, FieldVisit,
    FollowUp, CustomerFeedback, InterestRate, CollectionCase, Notification,
)


class MortgageProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = MortgageProduct
        fields = "__all__"


class BorrowerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Borrower
        fields = "__all__"


class PropertySerializer(serializers.ModelSerializer):
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)

    class Meta:
        model = Property
        fields = "__all__"


class MortgageApplicationSerializer(serializers.ModelSerializer):
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = MortgageApplication
        fields = "__all__"
        read_only_fields = ["application_ref"]


class LoanApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApproval
        fields = "__all__"


class RepaymentScheduleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepaymentScheduleItem
        fields = "__all__"


class MortgageLoanSerializer(serializers.ModelSerializer):
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    application_ref = serializers.CharField(source="application.application_ref", read_only=True)

    class Meta:
        model = MortgageLoan
        fields = "__all__"
        read_only_fields = ["loan_ref"]


class PaymentSerializer(serializers.ModelSerializer):
    loan_ref = serializers.CharField(source="loan.loan_ref", read_only=True)

    class Meta:
        model = Payment
        fields = "__all__"


class FeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fee
        fields = "__all__"


class MortgageInsurancePolicySerializer(serializers.ModelSerializer):
    loan_ref = serializers.CharField(source="loan.loan_ref", read_only=True)

    class Meta:
        model = MortgageInsurancePolicy
        fields = "__all__"


class MortgageDocumentSerializer(serializers.ModelSerializer):
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)
    application_ref = serializers.CharField(source="application.application_ref", read_only=True)

    class Meta:
        model = MortgageDocument
        fields = "__all__"


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = "__all__"


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = "__all__"


class FieldAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FieldAgent
        fields = "__all__"


class LeadSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    field_agent_name = serializers.CharField(source="field_agent.name", read_only=True)
    product_name = serializers.CharField(source="interested_product.name", read_only=True)

    class Meta:
        model = Lead
        fields = "__all__"
        read_only_fields = ["lead_ref", "converted_application"]


class FieldVisitSerializer(serializers.ModelSerializer):
    field_agent_name = serializers.CharField(source="field_agent.name", read_only=True)

    class Meta:
        model = FieldVisit
        fields = "__all__"


class FollowUpSerializer(serializers.ModelSerializer):
    class Meta:
        model = FollowUp
        fields = "__all__"


class CustomerFeedbackSerializer(serializers.ModelSerializer):
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)
    lead_ref = serializers.CharField(source="lead.lead_ref", read_only=True)

    class Meta:
        model = CustomerFeedback
        fields = "__all__"


class InterestRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterestRate
        fields = "__all__"
        read_only_fields = ["created_by"]


class CollectionCaseSerializer(serializers.ModelSerializer):
    loan_ref = serializers.CharField(source="loan.loan_ref", read_only=True)
    borrower_name = serializers.CharField(source="loan.borrower.full_name", read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = CollectionCase
        fields = "__all__"

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            return obj.assigned_to.get_full_name().strip() or obj.assigned_to.username
        return None


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"
        read_only_fields = ["user", "created_at"]
