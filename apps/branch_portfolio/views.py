"""Branch Portfolio views — all endpoints for the Branch Manager dashboard."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Q
from django.db import connection
from django.shortcuts import get_object_or_404

from apps.portfolio.models import HfCustomer, Accounts, Loans, Feedback, Profile, Prospects
from apps.portfolio.serializers import (
    HfCustomerSerializer, AccountsSerializer, LoansSerializer, FeedbackSerializer,
    ProspectsSerializer, ProfileSerializer,
)
from apps.gceo_dashboard.models import (
    DailyBalanceMovement, LoanDailyBalanceMovement, Revenue, LoansHistory,
)
from core.pagination import StandardPagination
from core.date_utils import cy, py, _yester_case, _prev_month_case


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


def _branch_filter(profile):
    return profile.branch or ""


# ── Customers ──────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(branch__icontains=_branch_filter(profile))
        return Response(HfCustomerSerializer(qs, many=True).data)


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerListAllocatedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return HfCustomer.objects.filter(branch__icontains=_branch_filter(profile))


@extend_schema(tags=["Branch Portfolio — Summary"])
class BranchTotalCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(branch__icontains=_branch_filter(profile))
        return Response({
            "total_customers": qs.count(),
            "active_customers": qs.filter(active=True).count(),
            "branch": profile.branch,
        })


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchCustomerPerSegmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        data = (
            HfCustomer.objects
            .filter(branch__icontains=_branch_filter(profile))
            .values("segment")
            .annotate(count=Count("cust_id"))
            .order_by("-count")
        )
        return Response(list(data))


@extend_schema(tags=["Branch Portfolio — Customers"])
class BranchNewCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        from core.date_utils import current_year
        count = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile),
            date_time_created__year=current_year,
        ).count()
        return Response({"new_customers": count})


@extend_schema(tags=["Branch Portfolio — RM"])
class BranchRMListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT
                    rm_code,
                    sale_code,
                    full_name,
                    SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS total_deposits
                FROM daily_balance_movement
                WHERE UPPER(full_name) ILIKE %s
                   OR rm_code IN (
                        SELECT sales_code FROM portfolio_management_profile WHERE branch = %s
                   )
                GROUP BY rm_code, sale_code, full_name
                ORDER BY full_name
            """, [f"%{_branch_filter(profile)}%", _branch_filter(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        # Fallback: use Profile table if no DailyBalanceMovement match
        if not rows:
            rm_profiles = Profile.objects.filter(branch=profile.branch).values(
                "sales_code", "user__first_name", "user__last_name"
            )
            rows = [
                {
                    "rm_code": p["sales_code"],
                    "sale_code": p["sales_code"],
                    "full_name": f"{p['user__first_name']} {p['user__last_name']}".strip(),
                    "total_deposits": None,
                }
                for p in rm_profiles
            ]
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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(branch__icontains=_branch_filter(profile))
        agg = qs.aggregate(
            total_revenue=Sum("total_revenue"),
            total_deposits=Sum("total_depost_balance"),
            total_loans=Sum("total_loans"),
            customer_count=Count("cust_id"),
        )
        return Response(agg)


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

    def get(self, request):
        profile = _get_profile(request.user)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                rm_code,
                MAX(full_name) AS rm_name,
                SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS yester_1_bal,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal,
                SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
                    - SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_movement
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND brn_code::text IN (
                  SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
              )
              AND rm_code IS NOT NULL
            GROUP BY rm_code
            ORDER BY ytd_movement DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchTopInflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    cust_cif, full_name, rm_code, customer_segment,
                    yester_1_bal, yester_2_bal,
                    yester_1_bal - yester_2_bal AS movement
                FROM daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                  AND yester_1_bal > yester_2_bal
                  AND brn_code::text IN (
                      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                  )
                ORDER BY movement DESC NULLS LAST
                LIMIT 50
            """, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Movement"])
class BranchTopOutflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    cust_cif, full_name, rm_code, customer_segment,
                    yester_1_bal, yester_2_bal,
                    yester_2_bal - yester_1_bal AS outflow
                FROM daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                  AND yester_2_bal > yester_1_bal
                  AND brn_code::text IN (
                      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE %s
                  )
                ORDER BY outflow DESC NULLS LAST
                LIMIT 50
            """, [f"%{_branch_filter(profile)}%"])
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
        qs = LoansHistory.objects.filter(cust_id__in=branch_cust_ids, days_in_arrears__gt=90)
        agg = qs.aggregate(
            npl_count=Count("id"),
            npl_value=Sum("euro_book_balance"),
            total_arrears=Sum("total_arrears"),
        )
        return Response(agg)


# ── Arrears ────────────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        qs = LoansHistory.objects.filter(cust_id__in=branch_cust_ids, days_in_arrears__gt=0)
        return Response({
            "total_accounts": qs.count(),
            "total_arrears": qs.aggregate(total=Sum("total_arrears"))["total"] or 0,
        })


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        from apps.gceo_dashboard.serializers import LoansHistorySerializer
        profile = _get_profile(self.request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        return LoansHistory.objects.filter(cust_id__in=branch_cust_ids, days_in_arrears__gt=0)

    def get_serializer_class(self):
        from apps.gceo_dashboard.serializers import LoansHistorySerializer
        return LoansHistorySerializer


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsDPDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    CASE
                        WHEN lh.days_in_arrears BETWEEN 1 AND 30   THEN '1-30 days'
                        WHEN lh.days_in_arrears BETWEEN 31 AND 60  THEN '31-60 days'
                        WHEN lh.days_in_arrears BETWEEN 61 AND 90  THEN '61-90 days'
                        WHEN lh.days_in_arrears BETWEEN 91 AND 180 THEN '91-180 days'
                        WHEN lh.days_in_arrears > 180              THEN '180+ days'
                        ELSE 'Unknown'
                    END AS dpd_bucket,
                    COUNT(*) AS count,
                    SUM(lh.total_arrears) AS total_arrears
                FROM loans_history lh
                JOIN hf_customer hfc ON hfc.cust_id::bigint = lh.cust_id
                WHERE lh.days_in_arrears > 0
                  AND hfc.branch ILIKE %s
                GROUP BY dpd_bucket
                ORDER BY dpd_bucket
            """, [f"%{_branch_filter(profile)}%"])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Branch Portfolio — Arrears"])
class BranchLoansArrearsProductsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        data = (
            LoansHistory.objects.filter(cust_id__in=branch_cust_ids, days_in_arrears__gt=0)
            .values("loan_product")
            .annotate(count=Count("id"), total_arrears=Sum("total_arrears"))
            .order_by("-total_arrears")
        )
        return Response(list(data))


# ── Fixed Deposits ─────────────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Fixed Deposits"])
class BranchFixedDepositListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountsSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return Accounts.objects.filter(
            product_type__icontains="FD",
            opening_branch__icontains=_branch_filter(profile),
        )


# ── Feedback / Prospects ───────────────────────────────────────────────────

@extend_schema(tags=["Branch Portfolio — Feedback"])
class BranchFeedbackView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        branch_cust_ids = HfCustomer.objects.filter(
            branch__icontains=_branch_filter(profile)
        ).values_list("cust_id", flat=True)
        return Feedback.objects.filter(cust_id__in=branch_cust_ids)


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
