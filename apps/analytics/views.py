from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Avg
from core.pagination import StandardPagination
import django_filters.rest_framework

from apps.portfolio.models import HfCustomer, Loans, Accounts
from apps.gceo_dashboard.models import EmployeeTable
from .models import AnalyticsSnapshot
from .serializers import AnalyticsSnapshotSerializer


@extend_schema(tags=["Analytics — Snapshots"])
class AnalyticsSnapshotListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AnalyticsSnapshotSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["category", "segment", "branch"]
    queryset = AnalyticsSnapshot.objects.all()


@extend_schema(tags=["Analytics — Summary"])
class PortfolioSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total_customers = HfCustomer.objects.count()
        active_customers = HfCustomer.objects.filter(active=True).count()
        total_deposits = Accounts.objects.aggregate(total=Sum("current_balance"))["total"] or 0
        total_loans = Loans.objects.aggregate(total=Sum("euro_book_balance"))["total"] or 0
        total_arrears = Loans.objects.filter(
            days_in_arrears__gt=0
        ).aggregate(total=Sum("total_arrears"))["total"] or 0
        return Response({
            "total_customers": total_customers,
            "active_customers": active_customers,
            "total_deposits": total_deposits,
            "total_loans": total_loans,
            "total_arrears": total_arrears,
        })


@extend_schema(tags=["Analytics — Deposits"])
class DepositsBySegmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            HfCustomer.objects.values("banking_segment")
            .annotate(
                count=Count("cust_id"),
                total_deposits=Sum("total_depost_balance"),
            )
        )
        return Response(list(data))


@extend_schema(tags=["Analytics — Loans"])
class LoansByProductView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            Loans.objects.values("loan_product")
            .annotate(
                count=Count("id"),
                total_balance=Sum("euro_book_balance"),
                total_arrears=Sum("total_arrears"),
            )
        )
        return Response(list(data))


@extend_schema(tags=["Analytics — Staff"])
class StaffSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = EmployeeTable.objects.count()
        exited = EmployeeTable.objects.filter(exit=1).count()
        new = EmployeeTable.objects.filter(new=1).count()
        by_division = list(
            EmployeeTable.objects.values("division").annotate(count=Count("id"))
        )
        return Response({
            "total_staff": total,
            "active_staff": total - exited,
            "exited_staff": exited,
            "new_staff": new,
            "by_division": by_division,
        })
