from rest_framework import serializers

from core.serializers import WarehouseModelSerializer
from .models import LoanRepayments


class LoanRepaymentsSerializer(WarehouseModelSerializer):
    class Meta:
        model = LoanRepayments
        fields = "__all__"
