from rest_framework import serializers
from .models import LoanRepayments


class LoanRepaymentsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanRepayments
        fields = "__all__"
