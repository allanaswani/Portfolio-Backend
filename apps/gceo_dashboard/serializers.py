from rest_framework import serializers

from core.serializers import WarehouseModelSerializer
from .models import (
    CeoDepositMovementMonthly, Accounts, Customers, CeoChannelReport,
    TransactionDiary, CeoDepositMovement, CeoDepositMovementDaily,
    Revenue, MobileLoanDisbusements, HfCustomer, PhoneNumber,
    AccountsHistory, CeoLoanMovementMonthlyBySegment,
    CeoDepositMovementMonthlyBySegment, DailyBalanceMovement,
    LoanDailyBalanceMovement, EmployeeTable, LoansHistory,
)


class CeoDepositMovementMonthlySerializer(WarehouseModelSerializer):
    class Meta:
        model = CeoDepositMovementMonthly
        # Explicit, never "__all__": the table has no id column, so
        # naming everything would put the primary key Django invented
        # into the payload and into the SELECT. See core/warehouse.py.
        fields = ["dates_eom", "sum"]


class AccountsSerializer(WarehouseModelSerializer):
    class Meta:
        model = Accounts
        fields = "__all__"


class CustomersSerializer(WarehouseModelSerializer):
    class Meta:
        model = Customers
        fields = "__all__"


class CeoChannelReportSerializer(WarehouseModelSerializer):
    class Meta:
        model = CeoChannelReport
        # Explicit, never "__all__": the table has no id column, so
        # naming everything would put the primary key Django invented
        # into the payload and into the SELECT. See core/warehouse.py.
        fields = ["trx_date", "trx_channel", "cust_id"]


class TransactionDiarySerializer(WarehouseModelSerializer):
    class Meta:
        model = TransactionDiary
        fields = "__all__"


class CeoDepositMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoDepositMovement
        # Explicit, never "__all__": the table has no id column, so
        # naming everything would put the primary key Django invented
        # into the payload and into the SELECT. See core/warehouse.py.
        fields = ["banking_segment", "segment", "end_previous_year_bal",
                  "current_bal", "percentage_movement"]


class CeoDepositMovementDailySerializer(serializers.Serializer):
    """Deliberately NOT a ModelSerializer.

    ``ceo_deposit_movement_daily`` has no ``id`` column — the ETL builds it with
    two columns and nothing else — but the model declares no primary key, so
    Django adds an implicit one and every query asked for a column that is not
    there. ``fields = "__all__"`` then put that phantom id in the payload too.

    A plain Serializer with the real columns works on the ``.values()`` rows the
    views now pass it, and asserts nothing about the table that is not true.
    """

    dates_eom = serializers.DateField(required=False, allow_null=True)
    sum = serializers.FloatField(required=False, allow_null=True)


class RevenueSerializer(WarehouseModelSerializer):
    class Meta:
        model = Revenue
        fields = "__all__"


class MobileLoanDisbusementsSerializer(WarehouseModelSerializer):
    class Meta:
        model = MobileLoanDisbusements
        fields = "__all__"


class HfCustomerSerializer(WarehouseModelSerializer):
    class Meta:
        model = HfCustomer
        fields = "__all__"


class PhoneNumberSerializer(WarehouseModelSerializer):
    class Meta:
        model = PhoneNumber
        fields = "__all__"


class AccountsHistorySerializer(WarehouseModelSerializer):
    class Meta:
        model = AccountsHistory
        fields = "__all__"


class CeoLoanMovementMonthlyBySegmentSerializer(WarehouseModelSerializer):
    class Meta:
        model = CeoLoanMovementMonthlyBySegment
        # Explicit, never "__all__": the table has no id column, so
        # naming everything would put the primary key Django invented
        # into the payload and into the SELECT. See core/warehouse.py.
        fields = ["segment", "dates_eom", "volume", "value"]


class CeoDepositMovementMonthlyBySegmentSerializer(WarehouseModelSerializer):
    class Meta:
        model = CeoDepositMovementMonthlyBySegment
        # Explicit, never "__all__": the table has no id column, so
        # naming everything would put the primary key Django invented
        # into the payload and into the SELECT. See core/warehouse.py.
        fields = ["segment", "dates_eom", "volume", "value"]


class DailyBalanceMovementSerializer(WarehouseModelSerializer):
    class Meta:
        model = DailyBalanceMovement
        fields = "__all__"


class LoanDailyBalanceMovementSerializer(WarehouseModelSerializer):
    class Meta:
        model = LoanDailyBalanceMovement
        fields = "__all__"


class EmployeeTableSerializer(WarehouseModelSerializer):
    class Meta:
        model = EmployeeTable
        fields = "__all__"


class LoansHistorySerializer(WarehouseModelSerializer):
    class Meta:
        model = LoansHistory
        fields = "__all__"
