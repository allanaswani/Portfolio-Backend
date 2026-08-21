from django.db import connection
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
    CustomerRevenueListSerializer,
)
from core.permissions import PortfolioMgtPermissions
from .rm_rollup import fetch_rm_rollup
from services import portfolio_service as svc
from services import fixed_deposit_managers as fdm
from services.arrears_managers import (
    LoansArrearsSummaryManager, LoansArrearsDPDBucketSummaryManager,
    LoansProductArrearsSummaryManager, LoansArrearsAccountsListManager,
)

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
class RmTopCustomersView(APIView):
    """customers/top/?limit=N — the RM's top customers by deposit balance (default 10).

    Reuses svc.customers() (the same query the paginated list uses), sorts in Python,
    and returns only the top N. The frontend chart used to pull the RM's whole book to
    rank it client-side; now it fetches just the N rows it renders."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 10)), 100))
        except (TypeError, ValueError):
            limit = 10
        customers = list(svc.customers(profile.sales_code))
        customers.sort(
            key=lambda c: float(getattr(c, "total_depost_balance", 0) or 0),
            reverse=True,
        )
        return Response(HfCustomerSerializer(customers[:limit], many=True).data)


@extend_schema(tags=["Portfolio — Customers"])
class DynamicFilterCustomerListPaginatedDetailView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    # Params that steer the query/pagination rather than filter customer columns.
    _CONTROL_PARAMS = {"sales_code", "page", "page_size", "format", "ordering", "search"}
    # Numeric columns that support min_<field> / max_<field> range filtering.
    _NUMERIC_FIELDS = ("total_revenue", "total_depost_balance", "total_loans")
    # Free-text `search` matches ANY of these (OR). MUST be limited to columns the
    # svc.customers() raw SELECT actually returns — referencing any other model
    # field here triggers a deferred per-row DB fetch (N+1) that under the multi-DB
    # router comes back null, so it is both slow AND silently misses matches.
    _SEARCH_FIELDS = ("customer_name", "latin_surname", "cust_id", "sales_code")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HfCustomer.objects.none()
        profile = _get_profile(self.request.user)
        sales_code = self.request.query_params.get("sales_code", profile.sales_code)
        raw_qs = svc.customers(sales_code)
        # RawQuerySet -> list so we can filter/paginate in Python.
        customers = list(raw_qs)

        params = self.request.query_params
        if not params:
            return customers

        search = (params.get("search") or "").strip().lower()

        # Dynamic per-column search: any param matching a customer attribute is a
        # case-insensitive partial match (mirrors the old backend's UI search by
        # any visible column). Numeric range filters use min_/max_ prefixes.
        filtered = []
        for customer in customers:
            match = True

            # Free-text search: keep the customer if the term appears in ANY of the
            # searchable columns (OR). Empty term is a no-op.
            if search:
                hit = False
                for field in self._SEARCH_FIELDS:
                    attr = getattr(customer, field, None)
                    if attr is not None and search in str(attr).lower():
                        hit = True
                        break
                if not hit:
                    continue

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
        # /customers/<pk>/data → customer income breakdown by category
        # (old customerData -> cust_revenues), not {accounts, loans}.
        return Response(svc.cust_revenues(pk))


@extend_schema(tags=["Portfolio — Customers"])
class CustomerDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # Per-customer deposit balance trend (old core.depost_trends_per_customer).
        # NOT customer_accounts filtered by product_type IN ('SA','CA','FD') —
        # product_type never holds those codes, so that returned nothing.
        return Response(svc.deposit_trends_per_customer(pk))


@extend_schema(tags=["Portfolio — Customers"])
class CustomerLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # /customers/<pk>/loans → per-customer loan balance TREND
        # (old customerLoanTrends -> loan_trends_per_customer), not raw Loans records.
        return Response(svc.loan_trends_per_customer(pk))


@extend_schema(tags=["Portfolio — Customers"])
class CustomerPpcView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # /customers/<pk>/ppc → {ppc: <number>} (old customerPpc -> ppc_per_customer).
        return Response(svc.ppc_per_customer(pk))


@extend_schema(tags=["Portfolio — Customers"])
class CustomerFocusChartView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # /customers/<pk>/focus → [{product_type, dates_eom, current_balance}]
        # (old customerFocusChart -> portfolio_cust_deposit_trends).
        return Response(svc.customer_focus_chart(pk))


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
        # Old deposit_trends_data — per-account rows with month-end balance columns;
        # the frontend aggregates mon_YY_bal keys (PortfolioRmDepositTrends rows
        # lack them and chart empty).
        profile = _get_profile(request.user)
        data = svc.deposit_trends_data(profile.sales_code)
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
        # loan_trends/ — RM's per-account loan balance rows (old rm_loan_trends_data →
        # loan_trends_data). Was returning customer_loans(None) = always empty.
        profile = _get_profile(request.user)
        return Response(svc.loan_trends_data(profile.sales_code))


@extend_schema(tags=["Portfolio — Trends"])
class RmLoanTrendsByCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, rm_code):
        # loan_trends/<rm_code> — old RM_rm_loan_trends_data: the same rows as
        # loan_trends/ but for an explicitly-supplied sales_code (exco/TL viewing a
        # specific RM's book) instead of the caller's own profile. Mirrors the
        # deposit_trends/<rm_code> → RmDepositsView pairing.
        return Response(svc.loan_trends_data(rm_code))


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
    """RM revenue / deposit / loan totals. Ports the old backend's
    core.rM_total_summary() and returns its exact shape:
    ``[{sales_code, total_revenue, total_deposit_balance, total_loans}]``.

    revenue = SUM(portfolio_rm_revenue.value) + YTD FTP + YTD loan-loss. The
    revenue SUM is wrapped in COALESCE so a user with no portfolio_rm_revenue
    row yields total_revenue = 0 (not NULL) — the old backend omitted this,
    which returned null and crashed the legacy frontend's .toFixed()."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        sql = """
            WITH valid_portfolio AS (
                SELECT cust_id FROM retail_allocated_portfolio WHERE sales_code = %s
            ), rm_revenue AS (
                SELECT * FROM portfolio_rm_revenue WHERE sales_code = %s
            ), ftp AS (
                SELECT COALESCE(SUM(ftp.total_ftp), 0) AS ftp_value
                FROM cust_monthly_ftp ftp
                JOIN valid_portfolio vp ON ftp.cust_cif = vp.cust_id
                WHERE ftp.current_year = EXTRACT(YEAR FROM CURRENT_DATE)
            ), loan_loss AS (
                SELECT -SUM(COALESCE(l.pl_charge, 0) - COALESCE(l.int_adj, 0)) AS loan_loss_value
                FROM loans_mom_ifrs_movement l
                JOIN valid_portfolio vp ON l.cust_code_strategy::int = vp.cust_id
                WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                  AND l.cust_code_strategy ~ '^[0-9]+$'
            )
            SELECT
                %s AS sales_code,
                COALESCE((SELECT SUM(value) FROM rm_revenue), 0)
                    + COALESCE((SELECT ftp_value FROM ftp), 0)
                    + COALESCE((SELECT loan_loss_value FROM loan_loss), 0) AS total_revenue,
                SUM(total_depost_balance) AS total_deposit_balance,
                SUM(total_loans) AS total_loans
            FROM hf_customer
            JOIN valid_portfolio vp ON hf_customer.cust_id = vp.cust_id
        """
        sales_code = profile.sales_code
        with connection.cursor() as cur:
            cur.execute(sql, [sales_code, sales_code, sales_code])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Portfolio — Customers"])
class CustomersYtdView(APIView):
    # current_customers/ → {sales_code, current_customers} (old rm_customers_ytd):
    # total distinct customers allocated to the RM. Previously returned a list of
    # customer objects filtered by date_time_created, so the frontend's
    # current_customers count read as zero.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(svc.rm_customers_ytd(profile.sales_code))


@extend_schema(tags=["Portfolio — Customers"])
class NewCustomersYtdView(APIView):
    # new_customers/ → {sales_code, new_customers} (old rm_new_customers_ytd):
    # customers who opened an account this year (accounts.opened_by + customers.open_date).
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(svc.rm_new_customers_ytd(profile.sales_code))


@extend_schema(tags=["Portfolio — Customers"])
class NewCustomersYtdListView(APIView):
    # new_customers_list/ → plain list of {cust_id, account_name, current_balance,
    # open_date, opening_branch} (old rm_new_customers_ytd_list). The old endpoint
    # returned a bare JSON array (not paginated, not HfCustomer objects).
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(svc.rm_new_customers_ytd_list(profile.sales_code))


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
    """Old backend `rmlist`: per-RM revenue / deposit / loan totals from
    hf_customer joined to retail_allocated_portfolio.

    Shares ``rm_rollup`` with the CEO/branch RM lists — one row per sales code,
    each customer counted once even when the ETL leaves duplicate allocation
    rows behind."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(fetch_rm_rollup())


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
        # ppc/ — RM products-per-customer {ppc} (old rm_ppc → core.ppc). Was returning
        # global product_type counts, not RM-scoped PPC.
        profile = _get_profile(request.user)
        return Response(svc.ppc(profile.sales_code))


# ---------------------------------------------------------------------------
# Fixed Deposits
# ---------------------------------------------------------------------------

# Fixed deposits — old backend FD managers, RM scope. FD is identified by the
# product_mapping.product_map = 'FD' join (NOT product_type ILIKE '%FD%', which
# matched nothing -> zeros), and scoped to the RM.

@extend_schema(tags=["Portfolio — Fixed Deposits"])
class FixedDepositListView(APIView):
    # Old backend gated FD with RMPermissions (portfolio_mgt group); non-RMs got
    # 403, not an empty table. Preserve that so collections/other roles don't see
    # an empty RM page and mistake it for broken data.
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        rows = fdm.FixedDepositListManager().fixed_deposits_list_by_rm_code(profile.sales_code)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


@extend_schema(tags=["Portfolio — Fixed Deposits"])
class SearchFixedDepositListView(FixedDepositListView):
    """Same RM fixed-deposit list; the old backend applied no server-side field
    filter beyond the RM scope, so this mirrors the list endpoint."""
    pass


@extend_schema(tags=["Portfolio — Fixed Deposits"])
class FixedDepositRateBandsByRmView(APIView):
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            fdm.FixedDepositRateBandManager().rate_bands_by_rm_code(profile.sales_code)
        )


@extend_schema(tags=["Portfolio — Fixed Deposits"])
class FixedDepositExpiryTimelineByRmView(APIView):
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(fdm.expiry_timeline_band_by_rm_code(profile.sales_code))


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
        if getattr(self, "swagger_fake_view", False):
            return LoansMomIFRSMovement.objects.none()
        return LoansMomIFRSMovement.objects.filter(
            cust_code_strategy=self.kwargs["cust_code_strategy"]
        )


@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementByLnsAccountView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LoansMomIFRSMovement.objects.none()
        return LoansMomIFRSMovement.objects.filter(lns_account=self.kwargs["lns_account"])


@extend_schema(tags=["Portfolio — IFRS"])
class LoansMomIfrsMovementByBranchView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansMomIFRSMovementSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LoansMomIFRSMovement.objects.none()
        return LoansMomIFRSMovement.objects.filter(branch=self.kwargs["branch"])


# ---------------------------------------------------------------------------
# Loans Arrears
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Arrears"])
class LoansArrearsSummaryByRmView(APIView):
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            LoansArrearsSummaryManager().high_level_summary_by_rm_code(profile.sales_code)
        )


@extend_schema(tags=["Portfolio — Arrears"])
class LoansArrearsAccountsListByRmView(APIView):
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        rows = LoansArrearsAccountsListManager().accounts_in_arrears_by_rm_code(profile.sales_code)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


@extend_schema(tags=["Portfolio — Arrears"])
class SearchLoansArrearsAccountsListByRmView(LoansArrearsAccountsListByRmView):
    """Same RM arrears list; the old backend applied no server-side field filter
    here beyond the RM scope, so this mirrors the list endpoint."""
    pass


@extend_schema(tags=["Portfolio — Arrears"])
class LoansArrearsDpdBucketSummaryByRmView(APIView):
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            LoansArrearsDPDBucketSummaryManager().dpd_bucket_summary_by_rm_code(profile.sales_code)
        )


@extend_schema(tags=["Portfolio — Arrears"])
class LoansProductArrearsSummaryByRmView(APIView):
    permission_classes = [PortfolioMgtPermissions]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            LoansProductArrearsSummaryManager().product_arrears_summary_by_rm_code(profile.sales_code)
        )


# ---------------------------------------------------------------------------
# Revenue — top customers
# ---------------------------------------------------------------------------

@extend_schema(tags=["Portfolio — Revenue"])
class RmTopFtpCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # rm_top_ftp_customers/ → [{cust_cif, customer_name, revenue_value}] (old top_ftp_customers_for_rm).
        profile = _get_profile(request.user)
        return Response(svc.top_ftp_customers_for_rm(profile.sales_code))


@extend_schema(tags=["Portfolio — Revenue"])
class RmTopLoanLossCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # rm_top_loan_loss_customers/ → [{cust_code_strategy, customer_name, revenue_value}].
        profile = _get_profile(request.user)
        return Response(svc.top_loan_loss_customers_for_rm(profile.sales_code))


@extend_schema(tags=["Portfolio — Revenue"])
class RmTop10CustomersPerIncomeCategoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # rm_top_10_customers_per_income_category/ → {category: [{cust_id, customer_name, revenue_value}]}.
        profile = _get_profile(request.user)
        return Response(svc.top_10_customers_per_income_category_for_rm(profile.sales_code))


@extend_schema(tags=["Portfolio — Revenue"])
class CustomersRevenueListView(generics.ListAPIView):
    # Per-customer revenue breakdown (interest_income, interest_expenses, nfi, ftp,
    # loan_loss, total_revenue) — old core.customers_revenue_list_for_rm. This is NOT
    # customers() (deposit/loan balances); wiring it there made the revenue columns
    # render as zeros.
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerRevenueListSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return []
        profile = _get_profile(self.request.user)
        return svc.customers_revenue_list_for_rm(profile.sales_code)


@extend_schema(tags=["Portfolio — Revenue"])
class DynamicFilterCustomersRevenueListPaginatedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerRevenueListSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return []
        profile = _get_profile(self.request.user)
        rows = svc.customers_revenue_list_for_rm(profile.sales_code)

        # Old backend's dynamic filter: case-insensitive partial match for strings,
        # exact match for numbers, over any column present in the row. Pagination's
        # own params (page/page_size) aren't row keys, so they're ignored.
        params = self.request.query_params
        if not params:
            return rows
        filtered = []
        for row in rows:
            match = True
            for key, value in params.items():
                if key not in row:
                    continue
                field_val = row[key]
                if isinstance(field_val, str):
                    if value.lower() not in field_val.lower():
                        match = False
                        break
                elif str(field_val) != str(value):
                    match = False
                    break
            if match:
                filtered.append(row)
        return filtered
