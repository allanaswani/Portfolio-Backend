from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.pagination import StandardPagination
from .models import (
    Profile, HfCustomer, RetailAllocatedPortfolio, Prospects, Feedback,
    PortfolioRmDepositTrends, PortfolioRmRevenue, Accounts, AccountsHistory,
    Loans, LoansMomIFRSMovement,
)
from .serializers import (
    ProfileSerializer, UserSerializer, HfCustomerSerializer,
    RetailAllocatedPortfolioSerializer, ProspectsSerializer, FeedbackSerializer,
    PortfolioRmDepositTrendsSerializer, PortfolioRmRevenueSerializer,
    AccountsSerializer, AccountsHistorySerializer, LoansSerializer,
    LoansMomIFRSMovementSerializer, ChangePasswordSerializer, LogoutSerializer,
)
from services import portfolio_service as svc

import django_filters.rest_framework


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


# ---------------------------------------------------------------------------
# Customer views
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Customers"])
class CustomerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = svc.customers(profile.sales_code)
        serializer = HfCustomerSerializer(qs, many=True)
        return Response(serializer.data)


@extend_schema(tags=["Portfolio — Customers"])
class DynamicFilterCustomerListPaginatedDetailView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    # Params that steer the query/pagination rather than filter customer columns.
    _CONTROL_PARAMS = {"sales_code", "page", "page_size", "format", "ordering"}
    # Numeric columns that support min_<field> / max_<field> range filtering.
    _NUMERIC_FIELDS = ("total_revenue", "total_depost_balance", "total_loans")

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        sales_code = self.request.query_params.get("sales_code", profile.sales_code)
        raw_qs = svc.customers(sales_code)
        # RawQuerySet -> list so we can filter/paginate in Python.
        customers = list(raw_qs)

        params = self.request.query_params
        if not params:
            return customers

        # Dynamic per-column search: any param matching a customer attribute is a
        # case-insensitive partial match (mirrors the old backend's UI search by
        # any visible column). Numeric range filters use min_/max_ prefixes.
        filtered = []
        for customer in customers:
            match = True

            for param, value in params.items():
                if param in self._CONTROL_PARAMS or param.startswith(("min_", "max_")):
                    continue
                if hasattr(customer, param) and value != "":
                    attr = getattr(customer, param, "")
                    if str(attr if attr is not None else "").lower().find(value.lower()) == -1:
                        match = False
                        break

            if match:
                for field in self._NUMERIC_FIELDS:
                    field_value = getattr(customer, field, 0) or 0
                    min_value = params.get(f"min_{field}")
                    max_value = params.get(f"max_{field}")
                    try:
                        if min_value not in (None, "") and float(field_value) < float(min_value):
                            match = False
                            break
                        if max_value not in (None, "") and float(field_value) > float(max_value):
                            match = False
                            break
                    except (TypeError, ValueError):
                        # Non-numeric query value — ignore that range filter.
                        continue

            if match:
                filtered.append(customer)

        return filtered


@extend_schema(tags=["Portfolio — Customers"])
class RmCustomerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, rm_code):
        qs = svc.customers(rm_code)
        serializer = HfCustomerSerializer(qs, many=True)
        return Response(serializer.data)


@extend_schema(tags=["Portfolio — Customers"])
class CustomerDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    queryset = HfCustomer.objects.all()


@extend_schema(tags=["Portfolio — Customers"])
class CustomerDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        accounts = AccountsSerializer(svc.customer_accounts(pk), many=True).data
        loans = LoansSerializer(svc.customer_loans(pk), many=True).data
        return Response({"accounts": accounts, "loans": loans})


@extend_schema(tags=["Portfolio — Customers"])
class CustomerDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        accounts = svc.customer_accounts(pk).filter(product_type__in=["SA", "CA", "FD"])
        return Response(AccountsSerializer(accounts, many=True).data)


@extend_schema(tags=["Portfolio — Customers"])
class CustomerLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        loans = svc.customer_loans(pk)
        return Response(LoansSerializer(loans, many=True).data)


@extend_schema(tags=["Portfolio — Customers"])
class CustomerPpcView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # PPC = Product Per Customer — return product breakdown
        accounts = svc.customer_accounts(pk)
        product_summary = {}
        for acc in accounts:
            pt = acc.product_type
            product_summary[pt] = product_summary.get(pt, 0) + 1
        return Response({"cust_id": pk, "ppc": product_summary})


@extend_schema(tags=["Portfolio — Customers"])
class CustomerFocusChartView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        accounts = svc.customer_accounts(pk)
        loans = svc.customer_loans(pk)
        return Response({
            "accounts_count": accounts.count(),
            "loans_count": loans.count(),
            "total_deposits": sum(a.current_balance or 0 for a in accounts),
            "total_loans": sum(l.euro_book_balance or 0 for l in loans),
        })


@extend_schema(tags=["Portfolio — Customers"])
class CustomerFeedbackListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackSerializer

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Feedback.objects.filter(cust_id=pk)

    def perform_create(self, serializer):
        profile = _get_profile(self.request.user)
        pk = self.kwargs.get("pk")
        serializer.save(cust_id=pk, sales_code=profile.sales_code)


@extend_schema(tags=["Portfolio — Customers"])
class CustomerAccountDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        accounts = svc.customer_accounts(pk)
        return Response(AccountsSerializer(accounts, many=True).data)


@extend_schema(tags=["Portfolio — Customers"])
class LoanAccountDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        loans = svc.customer_loans(pk)
        return Response(LoansSerializer(loans, many=True).data)


# ---------------------------------------------------------------------------
# RM / Portfolio views
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — RM"])
class RmListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profiles = Profile.objects.select_related("user").all()
        data = [
            {"sales_code": p.sales_code, "branch": p.branch, "segment": p.segment,
             "username": p.user.username, "email": p.user.email}
            for p in profiles
        ]
        return Response(data)


@extend_schema(tags=["Portfolio — RM"])
class ProspectsListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProspectsSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return Prospects.objects.filter(sales_code=profile.sales_code)


@extend_schema(tags=["Portfolio — Feedback"])
class FeedbackListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return Feedback.objects.filter(sales_code=profile.sales_code)

    def perform_create(self, serializer):
        profile = _get_profile(self.request.user)
        serializer.save(sales_code=profile.sales_code)


@extend_schema(tags=["Portfolio — Feedback"])
class FeedbackSummByLeadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        profile = _get_profile(request.user)
        data = (
            Feedback.objects.filter(sales_code=profile.sales_code)
            .values("lead")
            .annotate(count=Count("id"))
        )
        return Response(list(data))


@extend_schema(tags=["Portfolio — Feedback"])
class FeedbackSummContactabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        profile = _get_profile(request.user)
        data = (
            Feedback.objects.filter(sales_code=profile.sales_code)
            .values("category")
            .annotate(count=Count("id"))
        )
        return Response(list(data))


@extend_schema(tags=["Portfolio — Feedback"])
class FeedbackCustomersNotContactedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Subquery, OuterRef
        profile = _get_profile(request.user)
        contacted = Feedback.objects.filter(
            sales_code=profile.sales_code
        ).values_list("cust_id", flat=True).distinct()
        qs = svc.customers(profile.sales_code)
        not_contacted = [c for c in qs if c.cust_id not in contacted]
        return Response(HfCustomerSerializer(not_contacted, many=True).data)


@extend_schema(tags=["Portfolio — Feedback"])
class FeedbackDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackSerializer
    queryset = Feedback.objects.all()


@extend_schema(tags=["Portfolio — Feedback"])
class CustomerFeedbackHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        feedback = get_object_or_404(Feedback, pk=pk)
        history = feedback.history.all().values()
        return Response(list(history))


@extend_schema(tags=["Portfolio — Summary"])
class TotalCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        data = svc.rM_total_customers(profile.sales_code)
        return Response(data)


@extend_schema(tags=["Portfolio — Summary"])
class RmTotalCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, rm_code):
        data = svc.rM_total_customers(rm_code)
        return Response(data)


@extend_schema(tags=["Portfolio — Trends"])
class RmDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        data = svc.rm_deposit_trends(profile.sales_code)
        return Response(data)


@extend_schema(tags=["Portfolio — Trends"])
class RmDepositsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, rm_code):
        data = svc.rm_deposit_trends(rm_code)
        return Response(data)


@extend_schema(tags=["Portfolio — Trends"])
class RmLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        loans = svc.customer_loans(None)
        return Response(LoansSerializer(loans, many=True).data)


@extend_schema(tags=["Portfolio — Revenue"])
class RmRevenueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        data = svc.rm_revenue(profile.sales_code)
        return Response(data)


@extend_schema(tags=["Portfolio — Revenue"])
class RmRevenueByCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, rm_code):
        data = svc.rm_revenue(rm_code)
        return Response(data)


@extend_schema(tags=["Portfolio — Summary"])
class TotalSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        totals = svc.rM_total_customers(profile.sales_code)
        deposits = svc.rm_deposit_trends(profile.sales_code)
        revenue = svc.rm_revenue(profile.sales_code)
        return Response({"totals": totals, "deposit_count": len(deposits), "revenue_count": len(revenue)})


@extend_schema(tags=["Portfolio — Customers"])
class CustomersYtdView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        year = timezone.now().year
        profile = _get_profile(request.user)
        qs = svc.customers(profile.sales_code)
        ytd = [c for c in qs if c.date_time_created and c.date_time_created.year == year]
        return Response(HfCustomerSerializer(ytd, many=True).data)


@extend_schema(tags=["Portfolio — Customers"])
class NewCustomersYtdView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        year = timezone.now().year
        profile = _get_profile(request.user)
        qs = svc.customers(profile.sales_code)
        new = [c for c in qs if c.date_time_created and c.date_time_created.year == year]
        return Response({"count": len(new)})


@extend_schema(tags=["Portfolio — Customers"])
class NewCustomersYtdListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        from django.utils import timezone
        year = timezone.now().year
        profile = _get_profile(self.request.user)
        qs = svc.customers(profile.sales_code)
        return [c for c in qs if c.date_time_created and c.date_time_created.year == year]


@extend_schema(tags=["Portfolio — Customers"])
class CustomerPerSegmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        profile = _get_profile(request.user)
        qs = RetailAllocatedPortfolio.objects.filter(sales_code=profile.sales_code)
        data = qs.values("main_segment").annotate(count=Count("cust_id"))
        return Response(list(data))


# ---------------------------------------------------------------------------
# Profile views
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Profile"])
class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def get_object(self):
        return _get_profile(self.request.user)


@extend_schema(tags=["Portfolio — Profile"])
class UserProfileView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


@extend_schema(tags=["Portfolio — Profile"])
class SalesCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response({"sales_code": profile.sales_code})


@extend_schema(tags=["Portfolio — Profile"])
class RmFullListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profiles = Profile.objects.select_related("user").exclude(sales_code__isnull=True)
        data = [
            {"sales_code": p.sales_code, "branch": p.branch, "name": p.user.get_full_name()}
            for p in profiles
        ]
        return Response(data)


# ---------------------------------------------------------------------------
# Allocated portfolio views
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Allocated"])
class RetailAllocatedPortfolioView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RetailAllocatedPortfolioSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return RetailAllocatedPortfolio.objects.filter(sales_code=profile.sales_code)


@extend_schema(tags=["Portfolio — Allocated"])
class RetailAllocatedPortfolioDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        obj = get_object_or_404(RetailAllocatedPortfolio, pk=pk)
        return Response(RetailAllocatedPortfolioSerializer(obj).data)


@extend_schema(tags=["Portfolio — PPC"])
class RmPpcView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        accounts = Accounts.objects.filter()  # filtered by sales_code via join in real DB
        from django.db.models import Count
        ppc = accounts.values("product_type").annotate(count=Count("id"))
        return Response(list(ppc))


# ---------------------------------------------------------------------------
# Fixed Deposits
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Fixed Deposits"])
class FixedDepositListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountsSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return Accounts.objects.filter(product_type__icontains="FD")


@extend_schema(tags=["Portfolio — Fixed Deposits"])
class SearchFixedDepositListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "account_no", "currency", "account_status"]

    def get_queryset(self):
        return Accounts.objects.filter(product_type__icontains="FD")


@extend_schema(tags=["Portfolio — Fixed Deposits"])
class FixedDepositRateBandsByRmView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Avg
        bands = (
            Accounts.objects.filter(product_type__icontains="FD")
            .values("interest_rate")
            .annotate(count=Count("id"), avg_balance=Avg("current_balance"))
        )
        return Response(list(bands))


@extend_schema(tags=["Portfolio — Fixed Deposits"])
class FixedDepositExpiryTimelineByRmView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        timeline = (
            Accounts.objects.filter(product_type__icontains="FD", expiry_date__isnull=False)
            .values("expiry_date__year", "expiry_date__month")
            .annotate(count=Count("id"))
        )
        return Response(list(timeline))


# ---------------------------------------------------------------------------
# Loans IFRS Movement
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer
    pagination_class = StandardPagination
    queryset = LoansMomIFRSMovement.objects.all()


@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementFilterView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["branch", "segment", "eom_date", "narration_status"]
    queryset = LoansMomIFRSMovement.objects.all()


@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementByCustCodeView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer

    def get_queryset(self):
        return LoansMomIFRSMovement.objects.filter(
            cust_code_strategy=self.kwargs["cust_code_strategy"]
        )


@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementByLnsAccountView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer

    def get_queryset(self):
        return LoansMomIFRSMovement.objects.filter(lns_account=self.kwargs["lns_account"])


@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementByBranchView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer

    def get_queryset(self):
        return LoansMomIFRSMovement.objects.filter(branch=self.kwargs["branch"])


# ---------------------------------------------------------------------------
# Loans Arrears
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Arrears"])
class LoansArrearsSummaryByRmView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Sum
        profile = _get_profile(request.user)
        qs = Loans.objects.filter(account_officer=profile.sales_code, days_in_arrears__gt=0)
        return Response({
            "total_accounts": qs.count(),
            "total_arrears": qs.aggregate(total=Sum("total_arrears"))["total"] or 0,
            "total_capital": qs.aggregate(total=Sum("capital_balance"))["total"] or 0,
        })


@extend_schema(tags=["Portfolio — Arrears"])
class LoansArrearsAccountsListByRmView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return Loans.objects.filter(account_officer=profile.sales_code, days_in_arrears__gt=0)


@extend_schema(tags=["Portfolio — Arrears"])
class SearchLoansArrearsAccountsListByRmView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["loan_product", "status", "sector", "currency"]

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return Loans.objects.filter(account_officer=profile.sales_code, days_in_arrears__gt=0)


@extend_schema(tags=["Portfolio — Arrears"])
class LoansArrearsDpdBucketSummaryByRmView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Sum
        profile = _get_profile(request.user)
        qs = Loans.objects.filter(account_officer=profile.sales_code, days_in_arrears__gt=0)

        def bucket(days):
            if days <= 30:
                return "1-30"
            elif days <= 60:
                return "31-60"
            elif days <= 90:
                return "61-90"
            return "90+"

        buckets: dict = {}
        for loan in qs:
            b = bucket(loan.days_in_arrears or 0)
            if b not in buckets:
                buckets[b] = {"count": 0, "total_arrears": 0}
            buckets[b]["count"] += 1
            buckets[b]["total_arrears"] += loan.total_arrears or 0

        return Response(buckets)


@extend_schema(tags=["Portfolio — Arrears"])
class LoansProductArrearsSummaryByRmView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Sum
        profile = _get_profile(request.user)
        data = (
            Loans.objects.filter(account_officer=profile.sales_code, days_in_arrears__gt=0)
            .values("loan_product")
            .annotate(count=Count("id"), total_arrears=Sum("total_arrears"))
        )
        return Response(list(data))


# ---------------------------------------------------------------------------
# Revenue — top customers
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Revenue"])
class RmTopFtpCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.gceo_dashboard.models import Revenue
        profile = _get_profile(request.user)
        # Top 10 customers by FTP
        data = (
            Revenue.objects.filter(sales_code=profile.sales_code)
            .order_by("-ftp")[:10]
        ) if hasattr(Revenue, "sales_code") else []
        from apps.gceo_dashboard.serializers import RevenueSerializer
        return Response(RevenueSerializer(data, many=True).data if data else [])


@extend_schema(tags=["Portfolio — Revenue"])
class RmTopLoanLossCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.gceo_dashboard.models import Revenue
        profile = _get_profile(request.user)
        data = (
            Revenue.objects.filter(sales_code=profile.sales_code)
            .order_by("-loan_loss")[:10]
        ) if hasattr(Revenue, "sales_code") else []
        from apps.gceo_dashboard.serializers import RevenueSerializer
        return Response(RevenueSerializer(data, many=True).data if data else [])


@extend_schema(tags=["Portfolio — Revenue"])
class RmTop10CustomersPerIncomeCategoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.gceo_dashboard.models import Revenue
        profile = _get_profile(request.user)
        data = Revenue.objects.filter(sales_code=profile.sales_code) if hasattr(Revenue, "sales_code") else Revenue.objects.none()
        from apps.gceo_dashboard.serializers import RevenueSerializer
        return Response(RevenueSerializer(data[:50], many=True).data)


@extend_schema(tags=["Portfolio — Revenue"])
class CustomersRevenueListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return list(svc.customers(profile.sales_code))


@extend_schema(tags=["Portfolio — Revenue"])
class DynamicFilterCustomersRevenueListPaginatedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return list(svc.customers(profile.sales_code))
