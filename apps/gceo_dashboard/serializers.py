from rest_framework import serializers
from .models import (
    CeoDepositMovementMonthly, Accounts, Customers, CeoChannelReport,
    TransactionDiary, CeoDepositMovement, CeoDepositMovementDaily,
    Revenue, MobileLoanDisbusements, HfCustomer, PhoneNumber,
    AccountsHistory, CeoLoanMovementMonthlyBySegment,
    CeoDepositMovementMonthlyBySegment, DailyBalanceMovement,
    LoanDailyBalanceMovement, EmployeeTable, LoansHistory,
)


class CeoDepositMovementMonthlySerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoDepositMovementMonthly
        fields = "__all__"


class AccountsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Accounts
        fields = "__all__"


class CustomersSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customers
        fields = "__all__"


class CeoChannelReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoChannelReport
        fields = "__all__"


class TransactionDiarySerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionDiary
        fields = "__all__"


class CeoDepositMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoDepositMovement
        fields = "__all__"


class CeoDepositMovementDailySerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoDepositMovementDaily
        fields = "__all__"


class RevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Revenue
        fields = "__all__"


class MobileLoanDisbusementsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MobileLoanDisbusements
        fields = "__all__"


class HfCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = HfCustomer
        fields = "__all__"


class PhoneNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhoneNumber
        fields = "__all__"


class AccountsHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountsHistory
        fields = "__all__"


class CeoLoanMovementMonthlyBySegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoLoanMovementMonthlyBySegment
        fields = "__all__"


class CeoDepositMovementMonthlyBySegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeoDepositMovementMonthlyBySegment
        fields = "__all__"


class DailyBalanceMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyBalanceMovement
        fields = "__all__"


class LoanDailyBalanceMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanDailyBalanceMovement
        fields = "__all__"


class EmployeeTableSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeTable
        fields = "__all__"


class LoansHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoansHistory
        fields = "__all__"
