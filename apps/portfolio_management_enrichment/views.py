from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination
import django_filters.rest_framework

from .models import CustomerEnrichment, RmTarget
from .serializers import CustomerEnrichmentSerializer, RmTargetSerializer


@extend_schema(tags=["Portfolio Enrichment — Customers"])
class CustomerEnrichmentListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerEnrichmentSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["income_band", "employment_status", "risk_rating", "data_source"]
    queryset = CustomerEnrichment.objects.all()


@extend_schema(tags=["Portfolio Enrichment — Customers"])
class CustomerEnrichmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerEnrichmentSerializer
    queryset = CustomerEnrichment.objects.all()


@extend_schema(tags=["Portfolio Enrichment — RM Targets"])
class RmTargetListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmTargetSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "month"]
    queryset = RmTarget.objects.all()


@extend_schema(tags=["Portfolio Enrichment — RM Targets"])
class RmTargetDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmTargetSerializer
    queryset = RmTarget.objects.all()
