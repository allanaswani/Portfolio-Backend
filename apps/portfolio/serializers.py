from rest_framework import serializers
from django.contrib.auth.models import User
from django.db import models
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


class SafeDecimalField(serializers.Field):
    """Represents the unmanaged warehouse numeric columns that inspectdb captured
    as ``DecimalField(max_digits=65535, decimal_places=65535)``. DRF's DecimalField
    quantizes every value to those params, which raises ``decimal.InvalidOperation``
    on ordinary values (any nonzero integer part overflows the 65535-digit context)
    and on ``NaN``. We emit a plain string instead (``NaN``/None -> None), the same
    approach SegmentCustomerSerializer already uses for these columns."""

    def to_representation(self, value):
        if value is None:
            return None
        try:
            if value.is_nan():
                return None
        except (AttributeError, TypeError):
            pass
        return str(value)

    def to_internal_value(self, data):
        return data


class HfCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfCustomer
        fields = "__all__"

    def build_standard_field(self, field_name, model_field):
        # HfCustomer's numeric columns are DecimalField(65535, 65535) from inspectdb.
        # DRF's default DecimalField quantizes to that scale and 500s (InvalidOperation),
        # so represent every decimal column via SafeDecimalField (string / NaN->null).
        field_class, field_kwargs = super().build_standard_field(field_name, model_field)
        if isinstance(model_field, models.DecimalField):
            for k in ("max_digits", "decimal_places", "coerce_to_string"):
                field_kwargs.pop(k, None)
            return SafeDecimalField, field_kwargs
        return field_class, field_kwargs


class SegmentCustomerSerializer(serializers.ModelSerializer):
    """Ported verbatim from the OLD backend (tl_portfolio.serializers). Consumes the
    branch/RM customer RawQuerySets (legacy_queries) whose SELECT supplies the
    computed columns (total_depost_balance, total_loans, total_revenue, rm_name,
    sales_code); the remaining fields are HfCustomer model columns. The frontend is
    built against this exact shape — do not change field names/types."""
    cust_id = serializers.SerializerMethodField('get_cust_id')
    fd = serializers.SerializerMethodField('get_fd')
    ca = serializers.SerializerMethodField('get_ca')
    internal = serializers.SerializerMethodField('get_internal')
    mobile = serializers.SerializerMethodField('get_mobile')
    mortagage = serializers.SerializerMethodField('get_mortagage')
    sa = serializers.SerializerMethodField('get_sa')

    product_map = serializers.SerializerMethodField('get_product_map')
    asset_finance = serializers.SerializerMethodField('get_asset_finance')
    cash_cover = serializers.SerializerMethodField('get_cash_cover')
    ipf = serializers.SerializerMethodField('get_ipf')
    overdraft = serializers.SerializerMethodField('get_overdraft')

    project = serializers.SerializerMethodField('get_project')
    staff = serializers.SerializerMethodField('get_staff')
    trade = serializers.SerializerMethodField('get_trade')
    unsecured = serializers.SerializerMethodField('get_unsecured')

    total_depost_balance = serializers.SerializerMethodField('get_total_depost_balance')
    total_loans = serializers.SerializerMethodField('get_total_loans')
    total_revenue = serializers.SerializerMethodField('get_total_revenue')
    branch = serializers.SerializerMethodField('get_branch')
    banking_segment = serializers.SerializerMethodField('get_banking_segment')
    active = serializers.BooleanField()
    sales_code = serializers.SerializerMethodField('get_sales_code')
    rm_name = serializers.SerializerMethodField('get_rm_name')

    class Meta:
        model = HfCustomer
        fields = ['cust_id', 'latin_surname', 'mobile_tel', 'id_no', 'e_mail',
                  'fd', 'ca', 'internal', 'mobile', 'mortagage', 'sa',
                  'product_map', 'asset_finance', 'cash_cover', 'ipf', 'overdraft',
                  'project', 'staff', 'trade', 'unsecured',
                  'registered_mobile', 'total_depost_balance', 'total_loans', 'total_revenue',
                  'active', 'branch', 'banking_segment', 'sales_code', 'rm_name']

    def get_cust_id(self, obj):        return str(obj.cust_id)
    def get_fd(self, obj):             return str(obj.fd)
    def get_ca(self, obj):             return str(obj.ca)
    def get_internal(self, obj):       return str(obj.internal)
    def get_mobile(self, obj):         return str(obj.mobile)
    def get_mortagage(self, obj):      return str(obj.mortagage)
    def get_sa(self, obj):             return str(obj.sa)
    def get_total_depost_balance(self, obj): return str(obj.total_depost_balance)
    def get_total_loans(self, obj):    return str(obj.total_loans)
    def get_total_revenue(self, obj):  return str(obj.total_revenue)
    def get_branch(self, obj):         return str(obj.branch)
    def get_banking_segment(self, obj): return str(obj.banking_segment)
    def get_sales_code(self, obj):     return str(obj.sales_code)
    def get_rm_name(self, obj):        return str(obj.rm_name)
    def get_product_map(self, obj):    return str(obj.product_map)
    def get_asset_finance(self, obj):  return str(obj.asset_finance)
    def get_cash_cover(self, obj):     return str(obj.cash_cover)
    def get_ipf(self, obj):            return str(obj.ipf)
    def get_overdraft(self, obj):      return str(obj.overdraft)
    def get_project(self, obj):        return str(obj.project)
    def get_staff(self, obj):          return str(obj.staff)
    def get_trade(self, obj):          return str(obj.trade)
    def get_unsecured(self, obj):      return str(obj.unsecured)


class CustomerRevenueListSerializer(serializers.Serializer):
    """Ported verbatim from old backend (portfolio.serializers). Shape of
    /portfolio/customers/revenue-list/ — per-customer revenue components. The
    frontend revenue table reads these exact field names; anything else renders
    as zeros."""
    cust_id = serializers.IntegerField()
    customer_name = serializers.CharField()
    interest_income = serializers.FloatField()
    interest_expenses = serializers.FloatField()
    nfi = serializers.FloatField()
    ftp = serializers.FloatField()
    loan_loss = serializers.FloatField()
    total_revenue = serializers.FloatField()


class ProspectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prospects
        fields = "__all__"


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = "__all__"


class BranchFeedbackSerializer(serializers.ModelSerializer):
    """Feedback enriched with the customer name (by cust_id) and RM name (by
    sales_code) for the branch Feedback Log, which renders both columns. The view
    supplies batched ``cust_names`` / ``rm_names`` lookup maps via context."""
    customer_name = serializers.SerializerMethodField()
    rm_name = serializers.SerializerMethodField()

    class Meta:
        model = Feedback
        fields = "__all__"

    def get_customer_name(self, obj):
        if obj.cust_id is None:
            return None
        return (self.context.get("cust_names") or {}).get(int(obj.cust_id))

    def get_rm_name(self, obj):
        return (self.context.get("rm_names") or {}).get(obj.sales_code)


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
