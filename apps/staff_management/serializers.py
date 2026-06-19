from rest_framework import serializers
from .models import (
    BranchEmployeeData, ScorecardRole, ScorecardKPI, RoleKPIMapping,
    PerformanceActual, EmployeeMonthlyPerformance,
    # Ported legacy models
    BranchEmployeeDmcData, BranchFinalEmployeeDmcData, Drawdown, DrawdownDaily,
    InsurancePolicy, TradeFinanceData, CustMonthlyFtp, DailySalesAccountsWithCto,
    DailyDormancyConvertedAccount, MerchantBankTillManualData, IapplyLoanApproval,
    Product, StaffEmployeeData, LeaveRecord, EmployeeRoleHistory, RmKPIBaseSummary,
    MissingEmployeeActual, TelesalesStaff, TelesalesDormantTillsAllocation,
)


class BranchEmployeeDataSerializer(serializers.ModelSerializer):
    branch = serializers.CharField(source="unit", read_only=True)
    role = serializers.CharField(source="job_title", read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = BranchEmployeeData
        fields = [
            "id", "staff_id", "name", "branch", "grade", "role", "status",
            "department", "division", "email", "gender",
            "date_of_employment", "service_years", "updated_at",
        ]

    def get_status(self, obj):
        if obj.exit == 1:
            return "Exited"
        if obj.new == 1:
            return "New"
        if obj.promotion == 1:
            return "Promoted"
        return "Active"


class ScorecardRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScorecardRole
        fields = "__all__"


class ScorecardKPISerializer(serializers.ModelSerializer):
    class Meta:
        model = ScorecardKPI
        fields = "__all__"


class RoleKPIMappingSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)
    kpi_name_display = serializers.CharField(source="kpi.name", read_only=True)

    class Meta:
        model = RoleKPIMapping
        fields = "__all__"


class PerformanceActualSerializer(serializers.ModelSerializer):
    achievement_pct = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceActual
        fields = "__all__"

    def get_achievement_pct(self, obj):
        if obj.target_value and obj.target_value > 0:
            return round(float(obj.actual_value) / float(obj.target_value) * 100, 1)
        return 0.0


class EmployeeMonthlyPerformanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeMonthlyPerformance
        fields = "__all__"


# ── Ported legacy model serializers ───────────────────────────────────────────

class BranchEmployeeDmcDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchEmployeeDmcData
        fields = "__all__"


class BranchFinalEmployeeDmcDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchFinalEmployeeDmcData
        fields = "__all__"


class DrawdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Drawdown
        fields = "__all__"


class DrawdownDailySerializer(serializers.ModelSerializer):
    class Meta:
        model = DrawdownDaily
        fields = "__all__"


class InsurancePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = InsurancePolicy
        fields = "__all__"


class TradeFinanceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeFinanceData
        fields = "__all__"


class CustMonthlyFtpSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustMonthlyFtp
        fields = "__all__"


class DailySalesAccountsWithCtoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySalesAccountsWithCto
        fields = "__all__"


class DailyDormancyConvertedAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyDormancyConvertedAccount
        fields = "__all__"


class MerchantBankTillManualDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantBankTillManualData
        fields = "__all__"


class IapplyLoanApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = IapplyLoanApproval
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"


class StaffEmployeeDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffEmployeeData
        fields = "__all__"


class LeaveRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRecord
        fields = "__all__"


class EmployeeRoleHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeRoleHistory
        fields = "__all__"


class RmKPIBaseSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = RmKPIBaseSummary
        fields = "__all__"


class MissingEmployeeActualSerializer(serializers.ModelSerializer):
    class Meta:
        model = MissingEmployeeActual
        fields = "__all__"


class TelesalesStaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelesalesStaff
        fields = "__all__"


class TelesalesDormantTillsAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelesalesDormantTillsAllocation
        fields = "__all__"
