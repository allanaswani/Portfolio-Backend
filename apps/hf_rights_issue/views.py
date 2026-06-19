from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count
from core.pagination import StandardPagination
import django_filters.rest_framework

from .models import RightsIssueApplication
from .serializers import RightsIssueApplicationSerializer


@extend_schema(tags=["HF Rights Issue"])
class RightsIssueApplicationListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RightsIssueApplicationSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["status", "payment_status", "application_date"]
    queryset = RightsIssueApplication.objects.all()


@extend_schema(tags=["HF Rights Issue"])
class RightsIssueApplicationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RightsIssueApplicationSerializer
    queryset = RightsIssueApplication.objects.all()


@extend_schema(tags=["HF Rights Issue"])
class RightsIssueSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = RightsIssueApplication.objects.all()
        return Response({
            "total_applications": qs.count(),
            "total_shares_applied": qs.aggregate(t=Sum("rights_applied"))["t"] or 0,
            "total_amount_paid": qs.aggregate(t=Sum("amount_paid"))["t"] or 0,
            "total_shares_allotted": qs.aggregate(t=Sum("shares_allotted"))["t"] or 0,
            "by_status": list(qs.values("status").annotate(count=Count("id"))),
        })
