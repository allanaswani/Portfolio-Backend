from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    Profile, RetailAllocatedPortfolio, HfCustomer, Prospects, Feedback,
    PortfolioRmDepositTrends, PortfolioRmRevenue, Accounts, AccountsHistory,
    Loans, OTP, LoansMomIFRSMovement,
)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = "__all__"


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    # `groups` and `is_superuser` are the role contract the frontend relies on
    # (store/authStore.ts -> hasPermission). Without these, migrated users lose
    # all role-based navigation even though their roles exist in the DB.
    groups = serializers.SerializerMethodField()
    # Flatten the RBAC-relevant profile fields to the top level too — the
    # frontend User type reads user.sales_code / user.branch / user.segment.
    sales_code = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    segment = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "first_name", "last_name", "email",
            "is_superuser", "is_staff", "groups",
            "sales_code", "branch", "segment", "profile",
        )

    def get_groups(self, obj):
        return list(obj.groups.values_list("name", flat=True))

    def _profile(self, obj):
        return getattr(obj, "profile", None)

    def get_sales_code(self, obj):
        prof = self._profile(obj)
        return prof.sales_code if prof else None

    def get_branch(self, obj):
        prof = self._profile(obj)
        return prof.branch if prof else None

    def get_segment(self, obj):
        prof = self._profile(obj)
        return prof.segment if prof else None


class RetailAllocatedPortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetailAllocatedPortfolio
        fields = "__all__"


class HfCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfCustomer
        fields = "__all__"


class ProspectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prospects
        fields = "__all__"


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = "__all__"


class PortfolioRmDepositTrendsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioRmDepositTrends
        fields = "__all__"


class PortfolioRmRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioRmRevenue
        fields = "__all__"


class AccountsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Accounts
        fields = "__all__"


class AccountsHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountsHistory
        fields = "__all__"


class LoansSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loans
        fields = "__all__"


class OTPSerializer(serializers.ModelSerializer):
    class Meta:
        model = OTP
        fields = ("id", "created_at", "expires_at")


class LoansMomIFRSMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoansMomIFRSMovement
        fields = "__all__"


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
    otp = serializers.CharField(required=False, allow_blank=True)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
