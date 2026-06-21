from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
import django_filters.rest_framework

from core.pagination import StandardPagination
from .models import (
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)
from .serializers import (
    ScKpiSerializer, ScRoleSerializer, ScRoleKpiMappingSerializer,
    ScEmployeePerformanceActualSerializer, ScEmployeeMonthlyPerformanceSerializer,
    RunScorecardSerializer,
)
from .services import EmployeeMonthlyPerformanceService, MissingEmployeeActualService

_TAG = "Scorecard Automation"


@extend_schema(tags=[_TAG])
class ScKpiListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScKpiSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["kpi_code", "kpi_calculation_mode", "is_active"]
    queryset = ScKpi.objects.all()


@extend_schema(tags=[_TAG])
class ScKpiDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScKpiSerializer
    queryset = ScKpi.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["role_code", "role_type", "is_active"]
    queryset = ScRole.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleSerializer
    queryset = ScRole.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleKpiMappingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleKpiMappingSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["role_code", "kpi_code", "plan_category", "is_bonus"]
    queryset = ScRoleKpiMapping.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleKpiMappingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleKpiMappingSerializer
    queryset = ScRoleKpiMapping.objects.all()


@extend_schema(tags=[_TAG])
class ScEmployeePerformanceActualListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScEmployeePerformanceActualSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "kpi_code", "eom_date"]
    queryset = ScEmployeePerformanceActual.objects.all()


@extend_schema(tags=[_TAG])
class ScEmployeePerformanceActualDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScEmployeePerformanceActualSerializer
    queryset = ScEmployeePerformanceActual.objects.all()


@extend_schema(tags=[_TAG])
class ScEmployeeMonthlyPerformanceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScEmployeeMonthlyPerformanceSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "role_code", "kpi_code", "eom_date"]
    queryset = ScEmployeeMonthlyPerformance.objects.all()


@extend_schema(tags=[_TAG])
class RefreshMissingActualsView(APIView):
    """Recompute which (employee, KPI) actuals are missing for a month."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        eom_date = request.data.get("eom_date")
        if not eom_date:
            return Response({"detail": "eom_date is required."}, status=status.HTTP_400_BAD_REQUEST)
        records = MissingEmployeeActualService.update_missing_actuals_for_month(eom_date)
        return Response({"eom_date": eom_date, "missing_count": len(records)})


@extend_schema(tags=[_TAG], request=RunScorecardSerializer)
class RunMonthlyScorecardView(APIView):
    """
    Generate the monthly scorecard (scored EmployeeMonthlyPerformance rows) for a
    scope of employees: all / a single employee / a department / a current role.
    Fails if there are unresolved missing actuals for the targeted employees.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = RunScorecardSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        eom_date = data["eom_date"].replace(day=1).isoformat()
        scope = data["scope"]

        svc = EmployeeMonthlyPerformanceService
        try:
            if scope == "employee":
                if not data.get("sales_code"):
                    return Response({"detail": "sales_code is required for scope=employee."}, status=400)
                result = svc.run_monthly_kpi_scorecard_for_employee(data["sales_code"], eom_date)
            elif scope == "department":
                if not data.get("department"):
                    return Response({"detail": "department is required for scope=department."}, status=400)
                result = svc.run_monthly_kpi_scorecard_by_department(data["department"], eom_date)
            elif scope == "role":
                if not data.get("role_code"):
                    return Response({"detail": "role_code is required for scope=role."}, status=400)
                result = svc.run_monthly_kpi_scorecard_by_current_role(data["role_code"], eom_date)
            else:
                result = svc.run_monthly_kpi_scorecard(eom_date)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)
