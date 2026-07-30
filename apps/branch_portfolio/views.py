"""Branch Portfolio views — all endpoints for the Branch Manager dashboard."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Q
from django.db import connection
from django.shortcuts import get_object_or_404

from apps.portfolio.models import (
    HfCustomer, Accounts, Loans, Feedback, Profile, Prospects, RetailAllocatedPortfolio,
)
from apps.portfolio.serializers import (
    HfCustomerSerializer, AccountsSerializer, LoansSerializer, FeedbackSerializer,
    BranchFeedbackSerializer, ProspectsSerializer, ProfileSerializer, SegmentCustomerSerializer,
)
from . import legacy_queries as lq
from services.arrears_managers import (
    LoansArrearsSummaryManager, LoansArrearsDPDBucketSummaryManager,
    LoansProductArrearsSummaryManager, LoansArrearsAccountsListManager,
)
from services import fixed_deposit_managers as fdm
from apps.gceo_dashboard.models import (
    DailyBalanceMovement, LoanDailyBalanceMovement, Revenue, LoansHistory,
)
from core.pagination import StandardPagination
from core.date_utils import cy, py, _yester_case, _prev_month_case

import django_filters.rest_framework


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


def _branch_filter(profile, branch=None):
    """Effective branch name to filter on. An explicit `branch` — supplied by the
    /<branch> drill-down routes used by EXCO/CEO to inspect ANY branch — overrides
    the caller's own profile branch. Read-only, mirrors the legacy BranchDash."""
    return (branch or (profile.branch if profile else None) or "").strip()


# ── Customers ──────────────────────────────────────────────────────────────

def _apply_customer_filters(customer_list, query_params):
    """Port of the old DynamicFilterCustomerList*PaginatedDetailView filtering:
    partial (case-insensitive substring) match for any attribute that matches a
    query param name, plus numeric range filters on the three money fields. Unknown
    params (page, min_/max_ keys) are skipped by the hasattr guard, exactly as old."""
    if not query_params:
        return customer_list
    numeric_fields = ['total_revenue', 'total_depost_balance', 'total_loans']
    filtered = []
    for customer in customer_list:
        match = True
        for param, value in query_params.items():
            if hasattr(customer, param):
                if str(getattr(customer, param, "") or "").lower().find(value.lower()) == -1:
                    match = False
                    break
        if not match:
            continue
        for field in numeric_fields:
            min_value = query_params.get(f'min_{field}')
            max_value = query_params.get(f'max_{field}')
            if hasattr(customer, field):
                try:
                    field_value = float(getattr(customer, field, 0) or 0)
                    if min_value is not None and field_value < float(min_value):
                        match = False; break
                    if max_value is not None and field_value > float(max_value):
                        match = False; break
                except (TypeError, ValueError):
                    pass
        if match:
            filtered.append(customer)
    return filtered


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListView(APIView):
    """customers/ — full branch base with computed deposits/loans/revenue/segment
    (old: customer_list → branch_customers + SegmentCustomerSerializer)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        rows = lq.branch_customers(_branch_filter(profile))
        return Response(SegmentCustomerSerializer(rows, many=True).data)


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListAllocatedView(APIView):
    """customers_allocated/ — full allocated list (old: customer_list_allocated)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        rows = lq.branch_customers_allocated(_branch_filter(profile, branch))
        return Response(SegmentCustomerSerializer(list(rows), many=True).data)


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListNotAllocatedView(APIView):
    """customers_not_allocated/ — full unallocated list."""
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        rows = lq.branch_customers_not_allocated(_branch_filter(profile, branch))
        return Response(SegmentCustomerSerializer(list(rows), many=True).data)


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListAllocatedSearchView(generics.ListAPIView):
    """customers_allocated/search/ — server-paginated + filterable (10/page).
    Old: DynamicFilterCustomerListAllocatedPaginatedDetailView."""
    permission_classes = [IsAuthenticated]
    serializer_class = SegmentCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HfCustomer.objects.none()
        profile = _get_profile(self.request.user)
        branch = _branch_filter(profile, self.kwargs.get("branch"))
        rows = list(lq.branch_customers_allocated(branch))
        return _apply_customer_filters(rows, self.request.query_params)


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListNotAllocatedSearchView(generics.ListAPIView):
    """customers_not_allocated/search/ — server-paginated + filterable (10/page)."""
    permission_classes = [IsAuthenticated]
    serializer_class = SegmentCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HfCustomer.objects.none()
        profile = _get_profile(self.request.user)
        branch = _branch_filter(profile, self.kwargs.get("branch"))
        rows = list(lq.branch_customers_not_allocated(branch))
        return _apply_customer_filters(rows, self.request.query_params)


@extend_schema(tags=["Branch Portfolio — Summary"])
class BranchTotalCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(branch__icontains=_branch_filter(profile))
        # The Customers page KPIs read total_deposits/total_loans from here; the
        # old body only returned counts, so both money cards showed KSh 0. Sum the
        # same hf_customer columns the allocated table draws from (mirrors
        # BranchDashboardSummaryView).
        agg = qs.aggregate(
            total_customers=Count("cust_id"),
            active_customers=Count("cust_id", filter=Q(active=True)),
            total_deposits=Sum("total_depost_balance"),
            total_loans=Sum("total_loans"),
            total_revenue=Sum("total_revenue"),
        )
        return Response({
            "total_customers": agg["total_customers"] or 0,
            "active_customers": agg["active_customers"] or 0,
            "total_deposits": agg["total_deposits"] or 0,
            "total_loans": agg["total_loans"] or 0,
            "total_revenue": agg["total_revenue"] or 0,
            "branch": profile.branch,
        })


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerPerSegmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        rows = lq.branch_customer_per_segment(_branch_filter(profile, branch))
        return Response([{
            "banking_segment":  r.banking_segment,
            "main_segment":     r.main_segment,
            "segment":          r.segment,
            "total_customers":  r.total_customers,
            "active_customers": r.active_customers,
        } for r in rows])


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchNewCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # new_customers/ → {branch, new_customers}: customers who OPENED an account
        # this year (old branch_new_customers_ytd). Previously counted
        # hf_customer.date_time_created, which is the wrong signal.
        profile = _get_profile(request.user)
        return Response(lq.branch_new_customers_ytd(_branch_filter(profile)))


@extend_schema(tags=["Branch Portfolio — RM"])
class BranchRMListView(APIView):
    """Old backend `branch_rm_list`: per-RM revenue / deposit / loan totals for
    the branch's book, from hf_customer joined to retail_allocated_portfolio and
    filtered to the caller's branch. Was reading daily_balance_movement with a
    different shape (rm_code/sale_code/full_name/total_deposits), so the branch
    RM-list table — which reads rm_name/total_revenue/total_deposit_balance/
    total_loans — showed nothing."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        branch = _branch_filter(profile)
        sql = """
            SELECT
                sales_code,
                rap.rm_name,
                CASE
                    WHEN rap.branch::text = '230' THEN 'BURUBURU BRANCH'
                    WHEN rap.branch::text = '410' THEN 'ELDORET BRANCH'
                    WHEN rap.branch::text = '25'  THEN 'EMBU BRANCH'
                    WHEN rap.branch::text = '220' THEN 'GILL HOUSE BRANCH'
                    WHEN rap.branch::text = '100' THEN 'HEAD OFFICE'
                    WHEN rap.branch::text = '109' THEN 'HF WHIZZ'
                    WHEN rap.branch::text = '19'  THEN 'HURLINGHAM BRANCH'
                    WHEN rap.branch::text = '600' THEN 'KISUMU BRANCH'
                    WHEN rap.branch::text = '16'  THEN 'KITENGELA BRANCH'
                    WHEN rap.branch::text = '23'  THEN 'KOMAROCK BRANCH'
                    WHEN rap.branch::text = '24'  THEN 'MACHAKOS BRANCH'
                    WHEN rap.branch::text = '520' THEN 'MERU BRANCH'
                    WHEN rap.branch::text = '300' THEN 'MOMBASA BRANCH'
                    WHEN rap.branch::text = '17'  THEN 'NAIVASHA BRANCH'
                    WHEN rap.branch::text = '400' THEN 'NAKURU BRANCH'
                    WHEN rap.branch::text = '22'  THEN 'NANYUKI BRANCH'
                    WHEN rap.branch::text = '510' THEN 'NYERI BRANCH'
                    WHEN rap.branch::text = '200' THEN 'REHANI BRANCH'
                    WHEN rap.branch::text = '20'  THEN 'RIVERROAD BRANCH'
                    WHEN rap.branch::text = '250' THEN 'RONGAI BRANCH'
                    WHEN rap.branch::text = '270' THEN 'SAMEER BUSINESS PARK BRANCH'
                    WHEN rap.branch::text = '500' THEN 'THIKA BRANCH'
                    WHEN rap.branch::text = '260' THEN 'THIKA ROAD MALL-TRM BRANCH'
                    WHEN rap.branch::text = '280' THEN 'WESTLANDS BRANCH'
                    ELSE 'HEAD OFFICE'
                END AS rm_branch,
                SUM(total_revenue)        AS total_revenue,
                SUM(total_depost_balance) AS total_deposit_balance,
                SUM(total_loans)          AS total_loans
            FROM hf_customer
            LEFT JOIN retail_allocated_portfolio rap
                ON hf_customer.cust_id = rap.cust_id
            WHERE hf_customer.branch = %s
            GROUP BY sales_code, rap.rm_name, rap.branch
        """
        with connection.cursor() as cur:
            cur.execute(sql, [branch])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Deposits ───────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Deposits"])
class BranchDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        accounts = Accounts.objects.filter(opening_branch__icontains=_branch_filter(profile))
        data = accounts.values("product_type").annotate(
            count=Count("id"), total_balance=Sum("current_balance")
        )
        return Response(list(data))


@extend_schema(tags=["Branch Portfolio — Deposits"])
class BranchMonthlyDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                customer_segment,
                {yester2} AS yester_2_bal,
                {yester1} AS yester_1_bal,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND brn_code::text IN (
                  SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
              )
            GROUP BY customer_segment
            ORDER BY yester_1_bal DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Deposits"])
class BranchDepositPortfolioView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                {yester1} AS total_deposits,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_start,
                {yester1} - SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_movement
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND brn_code::text IN (
                  SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
              )
        """
        with connection.cursor() as cur:
            cur.execute(sql, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
        return Response(dict(zip(cols, row)) if row else {})


# ── Loans ──────────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Loans"])
class BranchLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        data = (
            Loans.objects.filter(cust_id__in=branch_cust_ids)
            .values("loan_product")
            .annotate(count=Count("id"), total=Sum("euro_book_balance"))
        )
        return Response(list(data))


@extend_schema(tags=["Branch Portfolio — Loans"])
class BranchMonthlyLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                customer_segment,
                {yester2} AS yester_2_bal,
                {yester1} AS yester_1_bal,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal
            FROM loan_daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
              AND brn_code::text IN (
                  SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
              )
            GROUP BY customer_segment
            ORDER BY yester_1_bal DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Loans"])
class BranchLoanPortfolioView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                {yester1} AS total_loans,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_start,
                {yester1} - SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_movement
            FROM loan_daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
              AND brn_code::text IN (
                  SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
              )
        """
        with connection.cursor() as cur:
            cur.execute(sql, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
        return Response(dict(zip(cols, row)) if row else {})


# ── Revenue ────────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Revenue"])
class BranchRevenueView(APIView):
    """branch_revenue/ — YTD revenue rows by income category (old: branch_Revenue →
    branch_revenues_query). Returns [{income_category, value}], NOT a single total;
    the frontend sums `value` for the KPI and charts them by category."""
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        rows = lq.branch_revenues_query(_branch_filter(profile, branch))
        return Response([{
            "income_category": r.income_category,
            "value":           r.value,
        } for r in rows])


@extend_schema(tags=["Branch Portfolio — Revenue"])
class BranchYTDRevenuePerformanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    income_category,
                    SUM(sum_dc) AS total
                FROM revenue
                WHERE brn_code::text IN (
                    SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                )
                GROUP BY income_category
                ORDER BY total DESC NULLS LAST
            """, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Movements (DTD/YTD) ────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchRMDepositMovementYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        # rm_name must be the RM's name (from retail_allocated_portfolio), NOT the
        # customer's. The earlier port used MAX(full_name) — full_name is the
        # CUSTOMER name in daily_balance_movement — so the RM column showed customer
        # names. Old backend (core.branch_rm_deposit_movement_ytd_data) sources it
        # from rap.rm_name via a cust_cif = cust_id join, grouped by rm_code, rm_name.
        sql = f"""
            SELECT
                dbm.rm_code,
                rap.rm_name,
                SUM(dbm.yester_1_bal) FILTER (WHERE dbm.yester_1_bal > 0) AS yester_1_bal,
                SUM(dbm.dec_{py}_bal) FILTER (WHERE dbm.dec_{py}_bal > 0) AS dec_bal,
                SUM(dbm.yester_1_bal) FILTER (WHERE dbm.yester_1_bal > 0)
                    - SUM(dbm.dec_{py}_bal) FILTER (WHERE dbm.dec_{py}_bal > 0) AS ytd_movement
            FROM daily_balance_movement dbm
            LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = dbm.cust_cif
            WHERE dbm.customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND dbm.brn_code::text IN (
                  SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
              )
              AND dbm.rm_code IS NOT NULL
            GROUP BY dbm.rm_code, rap.rm_name
            ORDER BY ytd_movement DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql, [f"%{_branch_filter(profile, branch)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchTopInflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    dbm.cust_cif, dbm.full_name, dbm.rm_code, rap.rm_name, dbm.customer_segment,
                    dbm.yester_1_bal, dbm.yester_2_bal,
                    dbm.yester_1_bal - dbm.yester_2_bal AS movement
                FROM daily_balance_movement dbm
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = dbm.cust_cif
                WHERE dbm.customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                  AND dbm.yester_1_bal > dbm.yester_2_bal
                  AND dbm.brn_code::text IN (
                      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                  )
                ORDER BY movement DESC NULLS LAST
                LIMIT 50
            """, [f"%{_branch_filter(profile, branch)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchTopOutflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, branch=None):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    dbm.cust_cif, dbm.full_name, dbm.rm_code, rap.rm_name, dbm.customer_segment,
                    dbm.yester_1_bal, dbm.yester_2_bal,
                    dbm.yester_1_bal - dbm.yester_2_bal AS movement
                FROM daily_balance_movement dbm
                LEFT JOIN retail_allocated_portfolio rap ON rap.cust_id = dbm.cust_cif
                WHERE dbm.customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                  AND dbm.yester_2_bal > dbm.yester_1_bal
                  AND dbm.brn_code::text IN (
                      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                  )
                ORDER BY movement ASC NULLS LAST
                LIMIT 50
            """, [f"%{_branch_filter(profile, branch)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchTopInflowYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    cust_cif, full_name, rm_code, customer_segment,
                    yester_1_bal,
                    dec_{py}_bal AS ytd_start,
                    yester_1_bal - dec_{py}_bal AS ytd_movement
                FROM daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                  AND yester_1_bal > dec_{py}_bal
                  AND brn_code::text IN (
                      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                  )
                ORDER BY ytd_movement DESC NULLS LAST
                LIMIT 50
            """, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchTopOutflowYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    cust_cif, full_name, rm_code, customer_segment,
                    yester_1_bal,
                    dec_{py}_bal AS ytd_start,
                    dec_{py}_bal - yester_1_bal AS ytd_outflow
                FROM daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                  AND dec_{py}_bal > yester_1_bal
                  AND brn_code::text IN (
                      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                  )
                ORDER BY ytd_outflow DESC NULLS LAST
                LIMIT 50
            """, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── PPC ────────────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Summary"])
class BranchPPCView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    AVG(
                        (CASE WHEN fd > 0 THEN 1 ELSE 0 END) +
                        (CASE WHEN ca > 0 THEN 1 ELSE 0 END) +
                        (CASE WHEN sa > 0 THEN 1 ELSE 0 END) +
                        (CASE WHEN mobile > 0 THEN 1 ELSE 0 END) +
                        (CASE WHEN mortagage > 0 THEN 1 ELSE 0 END)
                    )::numeric AS avg_products_per_customer,
                    COUNT(*) AS total_customers
                FROM hf_customer
                WHERE branch ILIKE %s
            """, [f"%{_branch_filter(profile)}%"])
            row = cur.fetchone()
        return Response({"avg_products_per_customer": row[0], "total_customers": row[1]})


# ── Dashboard summary ──────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Summary"])
class BranchDashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(branch__icontains=_branch_filter(profile))
        agg = qs.aggregate(
            total_customers=Count("cust_id"),
            active_customers=Count("cust_id", filter=Q(active=True)),
            total_deposits=Sum("total_depost_balance"),
            total_loans=Sum("total_loans"),
            total_revenue=Sum("total_revenue"),
        )
        agg["branch"] = profile.branch
        return Response(agg)


# ── NPL summary ────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchNPLSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        # Live `loans` table (not loans_history, which is multi-month and would
        # count each loan once per snapshot).
        qs = Loans.objects.filter(cust_id__in=branch_cust_ids, days_in_arrears__gt=90)
        agg = qs.aggregate(
            npl_count=Count("id"),
            npl_value=Sum("euro_book_balance"),
            total_arrears=Sum("total_arrears"),
        )
        return Response(agg)


# ── Arrears ────────────────────────────────────────────────────────────────

# Arrears — old backend LoansArrears* managers, branch scope, live `loans` table
# (NOT loans_history). Shapes match the old backend that the frontend targets.

@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            LoansArrearsSummaryManager().high_level_summary_by_branch(_branch_filter(profile))
        )


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        rows = LoansArrearsAccountsListManager().accounts_in_arrears_by_branch(_branch_filter(profile))
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsListSearchView(BranchLoansArrearsListView):
    """Same branch arrears list; the old backend applied no server-side field
    filter here beyond the scope, so this mirrors the list endpoint."""
    pass


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsDPDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            LoansArrearsDPDBucketSummaryManager().dpd_bucket_summary_by_branch(_branch_filter(profile))
        )


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsProductsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(
            LoansProductArrearsSummaryManager().product_arrears_summary_by_branch(_branch_filter(profile))
        )


# ── Fixed Deposits ─────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Fixed Deposits"])
class BranchFixedDepositListView(APIView):
    # FD via product_mapping.product_map='FD' (old fixed_deposits_list_by_branch_name),
    # not product_type ILIKE '%FD%' which matched nothing -> zeros.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        rows = fdm.FixedDepositListManager().fixed_deposits_list_by_branch_name(_branch_filter(profile))
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


# ── Feedback / Prospects ───────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Feedback"])
class BranchFeedbackView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchFeedbackSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        return Feedback.objects.filter(cust_id__in=branch_cust_ids)

    def list(self, request, *args, **kwargs):
        # The Feedback Log shows the customer + RM name, but Feedback only stores
        # cust_id + sales_code. Batch-resolve both for the current page (customer
        # name from hf_customer, RM name from retail_allocated_portfolio) and hand
        # them to the serializer via context — avoids an N+1 per row.
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)

        cust_ids = {int(r.cust_id) for r in rows if r.cust_id is not None}
        sales_codes = {r.sales_code for r in rows if r.sales_code}
        cust_names = {
            int(cid): name
            for cid, name in HfCustomer.objects.filter(cust_id__in=cust_ids)
            .values_list("cust_id", "latin_surname")
        }
        rm_names = dict(
            RetailAllocatedPortfolio.objects.filter(sales_code__in=sales_codes)
            .values_list("sales_code", "rm_name")
        )

        ctx = self.get_serializer_context()
        ctx.update({"cust_names": cust_names, "rm_names": rm_names})
        serializer = self.get_serializer(rows, many=True, context=ctx)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


@extend_schema(tags=["Branch Portfolio — Prospects"])
class BranchProspectsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProspectsSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        rm_codes = Profile.objects.filter(branch=profile.branch).values_list("sales_code", flat=True)
        return Prospects.objects.filter(sales_code__in=rm_codes)


# ── Profile ────────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Profile"])
class BranchProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def get_object(self):
        return _get_profile(self.request.user)
