from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination, LargePagination
import django_filters.rest_framework

from .models import (
    Project, Targets, Sales, ObligationSummary, CrmProject, CrmSalesRecord,
    LegacyProject, LegacySalesRecord, HfdiManualFinanceEntry, HfdiTargets,
    HfdiEmployeeData, HfdiEmployeeDataSalesRecord, HfdiScorecardPerformanceRecord,
    WeightedDashboardManualSales, HfdiCustomersHfcMortgages,
    HfdiProjectsDailyCollectionsData, HfdiProjectsInventorySalesData,
    AffordableHousingApplication,
)
from .serializers import (
    ProjectSerializer, TargetsSerializer, SalesSerializer, ObligationSummarySerializer,
    CrmProjectSerializer, CrmSalesRecordSerializer, LegacyProjectSerializer,
    LegacySalesRecordSerializer, HfdiManualFinanceEntrySerializer, HfdiTargetsSerializer,
    HfdiEmployeeDataSerializer, HfdiEmployeeDataSalesRecordSerializer,
    HfdiScorecardPerformanceRecordSerializer, WeightedDashboardManualSalesSerializer,
    HfdiCustomersHfcMortgagesSerializer, HfdiProjectsDailyCollectionsDataSerializer,
    HfdiProjectsInventorySalesDataSerializer, AffordableHousingApplicationSerializer,
)


@extend_schema(tags=["HFDI — Projects"])
class ProjectListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()


@extend_schema(tags=["HFDI — Projects"])
class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()


@extend_schema(tags=["HFDI — Targets"])
class TargetsListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TargetsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "month", "pm"]
    queryset = Targets.objects.all()


@extend_schema(tags=["HFDI — Targets"])
class TargetsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TargetsSerializer
    queryset = Targets.objects.all()


@extend_schema(tags=["HFDI — Sales"])
class SalesListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SalesSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "pm", "month"]
    queryset = Sales.objects.all()


@extend_schema(tags=["HFDI — Sales"])
class SalesDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SalesSerializer
    queryset = Sales.objects.all()


@extend_schema(tags=["HFDI — Obligations"])
class ObligationSummaryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ObligationSummarySerializer
    pagination_class = StandardPagination
    queryset = ObligationSummary.objects.all()


@extend_schema(tags=["HFDI — Obligations"])
class ObligationSummaryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ObligationSummarySerializer
    queryset = ObligationSummary.objects.all()


@extend_schema(tags=["HFDI — CRM Projects"])
class CrmProjectListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmProjectSerializer
    queryset = CrmProject.objects.all()


@extend_schema(tags=["HFDI — CRM Projects"])
class CrmProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmProjectSerializer
    queryset = CrmProject.objects.all()


@extend_schema(tags=["HFDI — CRM Sales"])
class CrmSalesRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmSalesRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "sale_month"]
    queryset = CrmSalesRecord.objects.all()


@extend_schema(tags=["HFDI — CRM Sales"])
class CrmSalesRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmSalesRecordSerializer
    queryset = CrmSalesRecord.objects.all()


@extend_schema(tags=["HFDI — Legacy Projects"])
class LegacyProjectListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacyProjectSerializer
    queryset = LegacyProject.objects.all()


@extend_schema(tags=["HFDI — Legacy Projects"])
class LegacyProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacyProjectSerializer
    queryset = LegacyProject.objects.all()


@extend_schema(tags=["HFDI — Legacy Sales"])
class LegacySalesRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacySalesRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "sale_month"]
    queryset = LegacySalesRecord.objects.all()


@extend_schema(tags=["HFDI — Legacy Sales"])
class LegacySalesRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacySalesRecordSerializer
    queryset = LegacySalesRecord.objects.all()


@extend_schema(tags=["HFDI — Manual Finance"])
class HfdiManualFinanceEntryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiManualFinanceEntrySerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "sale_month"]
    queryset = HfdiManualFinanceEntry.objects.all()


@extend_schema(tags=["HFDI — Manual Finance"])
class HfdiManualFinanceEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiManualFinanceEntrySerializer
    queryset = HfdiManualFinanceEntry.objects.all()


@extend_schema(tags=["HFDI — Performance Targets"])
class HfdiTargetsListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiTargetsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "pm", "rm", "is_active"]
    queryset = HfdiTargets.objects.all()


@extend_schema(tags=["HFDI — Performance Targets"])
class HfdiTargetsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiTargetsSerializer
    queryset = HfdiTargets.objects.all()


@extend_schema(tags=["HFDI — Employees"])
class HfdiEmployeeDataListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_pf_number", "staff_role", "primary_project", "active"]
    queryset = HfdiEmployeeData.objects.all()


@extend_schema(tags=["HFDI — Employees"])
class HfdiEmployeeDataDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSerializer
    queryset = HfdiEmployeeData.objects.all()


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSalesRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_pf_number", "sale_month"]
    queryset = HfdiEmployeeDataSalesRecord.objects.all()


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSalesRecordSerializer
    queryset = HfdiEmployeeDataSalesRecord.objects.all()


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_pf_number", "scorecard_month"]
    queryset = HfdiScorecardPerformanceRecord.objects.all()


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    queryset = HfdiScorecardPerformanceRecord.objects.all()


@extend_schema(tags=["HFDI — Weighted Dashboard"])
class WeightedDashboardManualSalesListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WeightedDashboardManualSalesSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "unit_status", "sale_month"]
    queryset = WeightedDashboardManualSales.objects.all()


@extend_schema(tags=["HFDI — Mortgages"])
class HfdiCustomersHfcMortgagesListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiCustomersHfcMortgagesSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "status", "mortgage_stage", "payment_type"]
    queryset = HfdiCustomersHfcMortgages.objects.all()


@extend_schema(tags=["HFDI — Daily Collections"])
class HfdiProjectsDailyCollectionsDataListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiProjectsDailyCollectionsDataSerializer
    pagination_class = LargePagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "sale_month", "paid_month"]
    queryset = HfdiProjectsDailyCollectionsData.objects.all()


@extend_schema(tags=["HFDI — Inventory Sales"])
class HfdiProjectsInventorySalesDataListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiProjectsInventorySalesDataSerializer
    pagination_class = LargePagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "unit_status", "sale_month"]
    queryset = HfdiProjectsInventorySalesData.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingApplicationSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["status", "typology", "mode_of_payment", "house_type"]
    queryset = AffordableHousingApplication.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingApplicationSerializer
    queryset = AffordableHousingApplication.objects.all()
