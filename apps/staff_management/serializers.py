from rest_framework import serializers

from core.serializers import WarehouseModelSerializer
from .models import (
    BranchEmployeeData, ScorecardRole, ScorecardKPI, RoleKPIMapping,
    PerformanceActual, EmployeeMonthlyPerformance,
    # Ported legacy models
    BranchEmployeeDmcData, BranchFinalEmployeeDmcData, Drawdown, DrawdownDaily,
    InsurancePolicy, TradeFinanceData, CustMonthlyFtp, DailySalesAccountsWithCto,
    PremiumTypeMapping,
    DailyDormancyConvertedAccount, MerchantBankTillManualData, IapplyLoanApproval,
    Product, StaffEmployeeData, LeaveRecord, EmployeeRoleHistory, RmKPIBaseSummary,
    MissingEmployeeActual, TelesalesStaff, TelesalesDormantTillsAllocation,
    # Managed mirror tables for manual uploads of warehouse datasets
    DailySalesAccountsWithCtoUpload, DailyDormancyConvertedAccountUpload,
    MerchantBankTillManualUpload, BranchDepartmentCost,
)
from apps.portfolio.models import RetailAllocatedPortfolioUpload


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
    # Frontend Role KPI Mappings screen contract: role_code / role_name /
    # role_type / is_active. role_name maps to the model's canonical ``name``.
    role_name = serializers.CharField(source="name")

    class Meta:
        model = ScorecardRole
        fields = ["id", "role_code", "role_name", "role_type", "is_active"]


class ScorecardKPISerializer(serializers.ModelSerializer):
    # Frontend contract: kpi_code / kpi_name / kpi_description /
    # kpi_calculation_mode / kpi_rating_type / score_cap / is_active.
    kpi_name = serializers.CharField(source="name")

    class Meta:
        model = ScorecardKPI
        fields = [
            "id", "kpi_code", "kpi_name", "kpi_description",
            "kpi_calculation_mode", "kpi_rating_type", "score_cap", "is_active",
        ]


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


class DrawdownDailySerializer(WarehouseModelSerializer):
    class Meta:
        model = DrawdownDaily
        fields = "__all__"


class InsurancePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = InsurancePolicy
        fields = "__all__"


class PremiumTypeMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PremiumTypeMapping
        fields = "__all__"
        # `product` is the primary key, so ModelSerializer attaches its own
        # UniqueValidator - which fires on an UPDATE too, making every edit of
        # an existing mapping fail against itself. validate_product does the
        # job properly: case-insensitively, excluding the row being edited, and
        # naming the spelling already stored.
        extra_kwargs = {"product": {"validators": []}}

    def validate_product(self, value):
        """One mapping per product, compared case-insensitively.

        The unique index enforces this too, but reaching it raises
        IntegrityError and the client gets a 500. Checked here so the answer is
        a 400 naming the product that is already mapped."""
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Product is required.")
        clash = PremiumTypeMapping.objects.filter(product__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                f'"{clash.first().product}" is already mapped. Edit that row instead.'
            )
        return value

    def update(self, instance, validated_data):
        """Renaming a product is a delete and an add, not an UPDATE.

        ``product`` is the primary key — the real table has no surrogate one.
        Changing the pk on a loaded instance and calling save() does NOT rename
        the row: Django issues an UPDATE against the NEW key, matches nothing,
        and falls back to an INSERT, leaving both the old and the new mapping
        behind. Silently duplicating a row people classify policies against is
        the worst outcome available here.

        So a rename is done explicitly. The old row goes and the new one
        arrives, which is also what actually happened, and simple_history
        records both halves instead of one confusing edit."""
        from django.db import transaction

        new_product = validated_data.get("product", instance.pk)
        if new_product == instance.pk:
            return super().update(instance, validated_data)

        values = {f: validated_data.get(f, getattr(instance, f))
                  for f in ("product", "vic_check", "life_policy_check",
                            "premium_type", "policy_category")}
        with transaction.atomic():
            instance.delete()
            return PremiumTypeMapping.objects.create(**values)


class TradeFinanceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeFinanceData
        fields = "__all__"


class CustMonthlyFtpSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustMonthlyFtp
        fields = "__all__"


class DailySalesAccountsWithCtoSerializer(WarehouseModelSerializer):
    class Meta:
        model = DailySalesAccountsWithCto
        fields = "__all__"


class DailyDormancyConvertedAccountSerializer(WarehouseModelSerializer):
    class Meta:
        model = DailyDormancyConvertedAccount
        fields = "__all__"


class MerchantBankTillManualDataSerializer(WarehouseModelSerializer):
    class Meta:
        model = MerchantBankTillManualData
        fields = "__all__"


class IapplyLoanApprovalSerializer(WarehouseModelSerializer):
    class Meta:
        model = IapplyLoanApproval
        fields = "__all__"


class ProductSerializer(WarehouseModelSerializer):
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


# ── Managed mirror serializers (manual uploads of warehouse datasets) ───────────

class DailySalesAccountsWithCtoUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySalesAccountsWithCtoUpload
        fields = "__all__"


class DailyDormancyConvertedAccountUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyDormancyConvertedAccountUpload
        fields = "__all__"


class MerchantBankTillManualUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantBankTillManualUpload
        fields = "__all__"


class RetailAllocatedPortfolioUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetailAllocatedPortfolioUpload
        fields = "__all__"


# ── Branch department cost (manually captured — no warehouse source) ───────────

class BranchDepartmentCostSerializer(serializers.ModelSerializer):
    """Cost for one department at one branch for one month.

    ``period`` is a convenience read-only "YYYY-MM" so the frontend can key rows
    without reassembling year/month itself.
    """

    period = serializers.SerializerMethodField()

    class Meta:
        model = BranchDepartmentCost
        fields = "__all__"
        read_only_fields = ("updated_at",)
        # DRF 3.15 auto-derives a UniqueTogetherValidator from the model's
        # UniqueConstraint, which would 400 a re-submitted month before the view
        # got the chance to UPDATE it. Correcting a month must be allowed; the
        # database constraint still guarantees one row per branch/dept/period.
        validators = []

    def get_period(self, obj) -> str:
        return f"{obj.year}-{obj.month:02d}"

    def validate_month(self, value):
        if not 1 <= int(value) <= 12:
            raise serializers.ValidationError("month must be between 1 and 12")
        return value

    def validate_branch(self, value):
        cleaned = " ".join(str(value or "").split()).upper()
        if not cleaned:
            raise serializers.ValidationError("branch is required")
        return cleaned

    def validate_department(self, value):
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            raise serializers.ValidationError("department is required")
        return cleaned
