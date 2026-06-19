"""TL Portfolio views — all endpoints for the Team Leader dashboard."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Q
from django.db import connection
from django.shortcuts import get_object_or_404

from apps.portfolio.models import (
    HfCustomer, RetailAllocatedPortfolio, Prospects, Feedback,
    Accounts, Loans, Profile,
)
from apps.portfolio.serializers import (
    HfCustomerSerializer, ProspectsSerializer, FeedbackSerializer,
    AccountsSerializer, LoansSerializer, ProfileSerializer,
)
from apps.gceo_dashboard.models import (
    DailyBalanceMovement, LoanDailyBalanceMovement, LoansHistory,
)
from core.pagination import StandardPagination
from core.date_utils import cy, py, current_year, _yester_case, _prev_month_case


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


def _segment(profile):
    return profile.segment or ""


# ── Customers ──────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Customers"])
class TlCustomerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(banking_segment=_segment(profile))
        return Response(HfCustomerSerializer(qs, many=True).data)


@extend_schema(tags=["TL Portfolio — Customers"])
class TlCustomerListPaginatedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return HfCustomer.objects.filter(banking_segment=_segment(profile))


@extend_schema(tags=["TL Portfolio — Customers"])
class TlCustomerDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    queryset = HfCustomer.objects.all()


@extend_schema(tags=["TL Portfolio — Summary"])
class TlTotalCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(banking_segment=_segment(profile))
        return Response({
            "total_customers": qs.count(),
            "active_customers": qs.filter(active=True).count(),
            "segment": profile.segment,
        })


@extend_schema(tags=["TL Portfolio — Customers"])
class TlNewCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        count = HfCustomer.objects.filter(
            banking_segment=_segment(profile),
            date_time_created__year=current_year,
        ).count()
        return Response({"new_customers": count})


@extend_schema(tags=["TL Portfolio — Customers"])
class TlNewCustomerListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return HfCustomer.objects.filter(
            banking_segment=_segment(profile),
            date_time_created__year=current_year,
        )


@extend_schema(tags=["TL Portfolio — Customers"])
class TlAllocatedCustomersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        allocated_ids = RetailAllocatedPortfolio.objects.values_list("cust_id", flat=True)
        return HfCustomer.objects.filter(
            banking_segment=_segment(profile),
            cust_id__in=allocated_ids,
        )


@extend_schema(tags=["TL Portfolio — Customers"])
class TlUnallocatedCustomersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        allocated_ids = RetailAllocatedPortfolio.objects.values_list("cust_id", flat=True)
        return HfCustomer.objects.filter(banking_segment=_segment(profile)).exclude(cust_id__in=allocated_ids)


# ── RM list ────────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — RM"])
class TlRMListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        rms = (
            Profile.objects.filter(segment=_segment(profile))
            .select_related("user")
            .values("sales_code", "user__first_name", "user__last_name", "branch")
        )
        data = [
            {
                "sales_code": r["sales_code"],
                "rm_name": f"{r['user__first_name']} {r['user__last_name']}".strip(),
                "branch": r["branch"],
            }
            for r in rms
        ]
        return Response(data)


# ── Summary ────────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Summary"])
class TlTotalSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(banking_segment=_segment(profile))
        agg = qs.aggregate(
            total_customers=Count("cust_id"),
            active_customers=Count("cust_id", filter=Q(active=True)),
            total_deposits=Sum("total_depost_balance"),
            total_loans=Sum("total_loans"),
            total_revenue=Sum("total_revenue"),
        )
        return Response(agg)


@extend_schema(tags=["TL Portfolio — Summary"])
class TlPPCView(APIView):
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
                WHERE banking_segment = %s
            """, [_segment(profile)])
            row = cur.fetchone()
        return Response({"avg_products_per_customer": row[0], "total_customers": row[1]})


# ── Revenue ────────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Revenue"])
class TlSegmentRevenueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        qs = HfCustomer.objects.filter(banking_segment=_segment(profile))
        agg = qs.aggregate(
            total_revenue=Sum("total_revenue"),
            total_deposits=Sum("total_depost_balance"),
            total_loans=Sum("total_loans"),
        )
        return Response(agg)


# ── Deposit trends ─────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Deposits"])
class TlDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT customer_segment,
                   {yester2} AS yester_2_bal,
                   {yester1} AS yester_1_bal
            FROM daily_balance_movement
            WHERE customer_segment = %s
            GROUP BY customer_segment
        """
        with connection.cursor() as cur:
            cur.execute(sql, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        if not rows:
            accounts = Accounts.objects.filter(opening_branch__icontains=_segment(profile) or "")
            data = accounts.values("product_type").annotate(
                count=Count("id"), total_balance=Sum("current_balance")
            )
            return Response(list(data))
        return Response(rows)


@extend_schema(tags=["TL Portfolio — Deposits"])
class TlMonthlyDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT customer_segment,
                   {yester2} AS yester_2_bal,
                   {yester1} AS yester_1_bal,
                   SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal
            FROM daily_balance_movement
            WHERE customer_segment = %s
            GROUP BY customer_segment
        """
        with connection.cursor() as cur:
            cur.execute(sql, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Loan trends ────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Loans"])
class TlLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        segment_cust_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        loans = Loans.objects.filter(cust_id__in=segment_cust_ids)
        data = loans.values("loan_product").annotate(
            count=Count("id"), total_balance=Sum("euro_book_balance")
        )
        return Response(list(data))


@extend_schema(tags=["TL Portfolio — Loans"])
class TlMonthlyLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT customer_segment,
                   {yester2} AS yester_2_bal,
                   {yester1} AS yester_1_bal,
                   SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal
            FROM loan_daily_balance_movement
            WHERE customer_segment = %s
            GROUP BY customer_segment
        """
        with connection.cursor() as cur:
            cur.execute(sql, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Movement ───────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Movement"])
class TlRMDepositMovementYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        sql = f"""
            SELECT
                rm_code,
                MAX(full_name) AS rm_name,
                SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS yester_1_bal,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal,
                SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
                    - SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_movement
            FROM daily_balance_movement
            WHERE customer_segment = %s AND rm_code IS NOT NULL
            GROUP BY rm_code
            ORDER BY ytd_movement DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopInflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT cust_cif, full_name, rm_code,
                       yester_1_bal, yester_2_bal,
                       yester_1_bal - yester_2_bal AS movement
                FROM daily_balance_movement
                WHERE customer_segment = %s AND yester_1_bal > yester_2_bal
                ORDER BY movement DESC NULLS LAST LIMIT 50
            """, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopOutflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT cust_cif, full_name, rm_code,
                       yester_1_bal, yester_2_bal,
                       yester_2_bal - yester_1_bal AS outflow
                FROM daily_balance_movement
                WHERE customer_segment = %s AND yester_2_bal > yester_1_bal
                ORDER BY outflow DESC NULLS LAST LIMIT 50
            """, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopInflowYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT cust_cif, full_name, rm_code,
                       yester_1_bal, dec_{py}_bal AS ytd_start,
                       yester_1_bal - dec_{py}_bal AS ytd_movement
                FROM daily_balance_movement
                WHERE customer_segment = %s AND yester_1_bal > dec_{py}_bal
                ORDER BY ytd_movement DESC NULLS LAST LIMIT 50
            """, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopOutflowYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT cust_cif, full_name, rm_code,
                       yester_1_bal, dec_{py}_bal AS ytd_start,
                       dec_{py}_bal - yester_1_bal AS ytd_outflow
                FROM daily_balance_movement
                WHERE customer_segment = %s AND dec_{py}_bal > yester_1_bal
                ORDER BY ytd_outflow DESC NULLS LAST LIMIT 50
            """, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Arrears ────────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Arrears"])
class TlLoansArrearsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        segment_cust_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        qs = LoansHistory.objects.filter(cust_id__in=segment_cust_ids, days_in_arrears__gt=0)
        return Response({
            "total_accounts": qs.count(),
            "total_arrears": qs.aggregate(total=Sum("total_arrears"))["total"] or 0,
        })


@extend_schema(tags=["TL Portfolio — Arrears"])
class TlLoansArrearsListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        segment_cust_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        return LoansHistory.objects.filter(cust_id__in=segment_cust_ids, days_in_arrears__gt=0)

    def get_serializer_class(self):
        from apps.gceo_dashboard.serializers import LoansHistorySerializer
        return LoansHistorySerializer


@extend_schema(tags=["TL Portfolio — Arrears"])
class TlLoansArrearsDPDView(APIView):
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
                WHERE lh.days_in_arrears > 0 AND hfc.banking_segment = %s
                GROUP BY dpd_bucket ORDER BY dpd_bucket
            """, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["TL Portfolio — Arrears"])
class TlLoansArrearsProductsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        segment_cust_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        data = (
            LoansHistory.objects.filter(cust_id__in=segment_cust_ids, days_in_arrears__gt=0)
            .values("loan_product")
            .annotate(count=Count("id"), total_arrears=Sum("total_arrears"))
            .order_by("-total_arrears")
        )
        return Response(list(data))


# ── Fixed Deposits ─────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Fixed Deposits"])
class TlFixedDepositListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountsSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        segment_cust_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        return Accounts.objects.filter(product_type__icontains="FD", cust_id__in=segment_cust_ids)


# ── Feedback ───────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Feedback"])
class TlFeedbackListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        segment_customer_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        return Feedback.objects.filter(cust_id__in=segment_customer_ids)


@extend_schema(tags=["TL Portfolio — Feedback"])
class TlSegmentFeedbackView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        segment_customer_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        data = (
            Feedback.objects.filter(cust_id__in=segment_customer_ids)
            .values("category", "lead")
            .annotate(count=Count("id"))
            .order_by("category")
        )
        return Response(list(data))


@extend_schema(tags=["TL Portfolio — Feedback"])
class TlFeedbackByLeadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        segment_customer_ids = HfCustomer.objects.filter(
            banking_segment=_segment(profile)
        ).values_list("cust_id", flat=True)
        data = (
            Feedback.objects.filter(cust_id__in=segment_customer_ids)
            .values("lead")
            .annotate(count=Count("id"))
        )
        return Response(list(data))


@extend_schema(tags=["TL Portfolio — Feedback"])
class TlContactabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        total_cust = HfCustomer.objects.filter(banking_segment=_segment(profile)).count()
        rm_codes = Profile.objects.filter(segment=_segment(profile)).values_list("sales_code", flat=True)
        contacted = Feedback.objects.filter(sales_code__in=rm_codes).values("cust_id").distinct().count()
        return Response({
            "total_customers": total_cust,
            "contacted": contacted,
            "not_contacted": max(0, total_cust - contacted),
            "contactability_pct": round(contacted / total_cust * 100, 2) if total_cust else 0,
        })


# ── Prospects ──────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Prospects"])
class TlSegmentProspectsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProspectsSerializer

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        rms_in_segment = Profile.objects.filter(segment=_segment(profile)).values_list("sales_code", flat=True)
        return Prospects.objects.filter(sales_code__in=rms_in_segment)


# ── Profile ────────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Profile"])
class TlProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def get_object(self):
        return _get_profile(self.request.user)
