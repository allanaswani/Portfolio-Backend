from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from core.pagination import StandardPagination
from .models import LoanRepayments
from .serializers import LoanRepaymentsSerializer
import django_filters.rest_framework


@extend_schema(tags=["Collections TL — Repayments"])
class LoanRepaymentsListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoanRepaymentsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_number", "channel_id", "product_id"]
    queryset = LoanRepayments.objects.all()


@extend_schema(tags=["Collections TL — Repayments"])
class LoanRepaymentsDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoanRepaymentsSerializer
    queryset = LoanRepayments.objects.all()
