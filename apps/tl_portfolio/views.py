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
    HfCustomer, Prospects, Feedback,
    Accounts, Profile,
)
from apps.portfolio.serializers import (
    HfCustomerSerializer, ProspectsSerializer, FeedbackSerializer,
    AccountsSerializer, ProfileSerializer,
    SegmentCustomerSerializer,
)
from . import legacy_queries as lq
from apps.gceo_dashboard.models import LoansHistory
from core.pagination import StandardPagination
from core.date_utils import current_year

import django_filters.rest_framework


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


def _segment(profile):
    return profile.segment or ""


class _DynamicCustomerFilterMixin:
    """Applies the old frontend's per-column search + min_/max_ numeric range
    filters to a customer queryset before pagination — mirrors the RM app's
    ``DynamicFilterCustomerListPaginatedDetailView``. Unknown params are ignored,
    and numeric range filters only apply to attributes the row actually carries
    (so a filter on a computed column absent from the ORM row is a no-op rather
    than excluding every row)."""

    _CONTROL_PARAMS = {"sales_code", "page", "page_size", "format", "ordering"}
    _NUMERIC_FIELDS = ("total_revenue", "total_depost_balance", "total_loans")

    def _apply_filters(self, customers):
        params = self.request.query_params
        if not params:
            return customers

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
                    if not hasattr(customer, field):
                        continue
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
                        continue

            if match:
                filtered.append(customer)

        return filtered


# ── Customers ──────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Customers"])
class TlCustomerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old segment_customers query — supplies the computed allocation columns
        # (rm_name, total_depost_balance, ...) the frontend tables render.
        profile = _get_profile(request.user)
        qs = lq.segment_customers(_segment(profile))
        return Response(SegmentCustomerSerializer(qs, many=True).data)


@extend_schema(tags=["TL Portfolio — Customers"])
class TlCustomerListPaginatedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SegmentCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return list(lq.segment_customers(_segment(profile)))


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
    serializer_class = SegmentCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return list(lq.segment_customers_allocated(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Customers"])
class TlUnallocatedCustomersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SegmentCustomerSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        profile = _get_profile(self.request.user)
        return list(lq.segment_customers_not_allocated(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Customers"])
class TlAllocatedCustomersSearchView(_DynamicCustomerFilterMixin, TlAllocatedCustomersView):
    """Server-paginated + dynamically filtered variant of the allocated list."""

    def get_queryset(self):
        return self._apply_filters(list(super().get_queryset()))


@extend_schema(tags=["TL Portfolio — Customers"])
class TlUnallocatedCustomersSearchView(_DynamicCustomerFilterMixin, TlUnallocatedCustomersView):
    """Server-paginated + dynamically filtered variant of the unallocated list."""

    def get_queryset(self):
        return self._apply_filters(list(super().get_queryset()))


@extend_schema(tags=["TL Portfolio — Customers"])
class TlCustomerPerSegmentView(APIView):
    """Old segment_customer_per_segment — per (main_segment, segment) counts.
    The frontend table reads main_segment / segment / total_customers /
    active_cusomers (old API typo)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(lq.segment_customer_per_segment(_segment(profile)))


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
        # Frontend reads `ppc` (old segment_ppc shape), not avg_products_per_customer.
        return Response({"ppc": row[0] if row else 0, "total_customers": row[1] if row else 0})


# ── Revenue ────────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Revenue"])
class TlSegmentRevenueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # segment_revenue/ — YTD income by category for the TL's segment, as
        # [{income_category, value}] (old segment_revenues_query). Frontend charts
        # these rows; a scalar aggregate left the revenue-by-category view empty.
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT income_category, SUM(sum_dc) AS value
                FROM revenue r
                LEFT JOIN hf_customer hf ON hf.cust_id = r.cust_id
                WHERE date_trunc('year', tmstamp) = date_trunc('year', now())
                  AND banking_segment = %s
                GROUP BY income_category
            """, [_segment(profile)])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Deposit trends ─────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Deposits"])
class TlDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old segment_deposit_trends_data — per-account rows with every month-end
        # balance column; the frontend aggregates the mon_YY_bal keys into the
        # portfolio trend chart. (A raw customer_segment = segment filter matches
        # nothing — profile.segment is a banking segment name.)
        profile = _get_profile(request.user)
        return Response(lq.segment_deposit_trends(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Deposits"])
class TlMonthlyDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old segment_monthly_deposit_trends_data — one aggregated row; the
        # frontend reads [0].yester_1_bal as the segment's current deposit book.
        profile = _get_profile(request.user)
        return Response(lq.segment_monthly_deposit_trends(_segment(profile)))


# ── Loan trends ────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Loans"])
class TlLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old segment_loan_trends_data_queryset — per-account loan rows with the
        # month-end balance columns (same aggregation contract as deposits).
        profile = _get_profile(request.user)
        return Response(lq.segment_loan_trends(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Loans"])
class TlMonthlyLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old segment_monthly_loan_trends_data — frontend reads [0].yester_1_bal.
        profile = _get_profile(request.user)
        return Response(lq.segment_monthly_loan_trends(_segment(profile)))


# ── Movement ───────────────────────────────────────────────────────────────

@extend_schema(tags=["TL Portfolio — Movement"])
class TlRMDepositMovementYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old segment_rm_deposit_movement_ytd_data — the frontend reads
        # rm_code / rm_name / dec_bal / yester_1_bal / movement.
        profile = _get_profile(request.user)
        return Response(lq.segment_rm_deposit_movement_ytd(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopInflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(lq.segment_top_inflow_dtd(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopOutflowDTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(lq.segment_top_outflow_dtd(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopInflowYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # YTD movers: frontend reads dec_bal (opening) / yester_1_bal / movement.
        profile = _get_profile(request.user)
        return Response(lq.segment_top_inflow_ytd(_segment(profile)))


@extend_schema(tags=["TL Portfolio — Movement"])
class TlTopOutflowYTDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        return Response(lq.segment_top_outflow_ytd(_segment(profile)))


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
class TlLoansArrearsListSearchView(TlLoansArrearsListView):
    """Server-paginated + filterable arrears list (mirrors the RM app's
    SearchLoansArrearsAccountsListByRmView)."""
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["loan_product", "status", "sector", "currency"]


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
        # `total_leads` mirrors the RM app's field name; `count` kept for back-compat.
        data = (
            Feedback.objects.filter(cust_id__in=segment_customer_ids)
            .values("lead")
            .annotate(count=Count("id"), total_leads=Count("id"))
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
        not_contacted = max(0, total_cust - contacted)
        # `allocation` + `percent_contacted` (a fraction) match the field names the
        # frontend reads; the original keys are kept for back-compat.
        return Response({
            "total_customers": total_cust,
            "allocation": total_cust,
            "contacted": contacted,
            "not_contacted": not_contacted,
            "percent_contacted": round(contacted / total_cust, 4) if total_cust else 0,
            "contactability_pct": round(contacted / total_cust * 100, 2) if total_cust else 0,
        })


@extend_schema(tags=["TL Portfolio — Feedback"])
class TlFeedbackSummaryView(APIView):
    """Per-RM contactability call counts over 1/7/30 days and YTD — powers the
    'RM Summary' table on the TL feedback page."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date, timedelta
        profile = _get_profile(request.user)
        today = date.today()
        rms = (
            Profile.objects.filter(segment=_segment(profile))
            .select_related("user")
            .values("sales_code", "user__first_name", "user__last_name")
        )
        rows = []
        for r in rms:
            code = r["sales_code"]
            fb = Feedback.objects.filter(sales_code=code)
            rows.append({
                "sales_code": code,
                "rm_name": f"{r['user__first_name']} {r['user__last_name']}".strip(),
                "call_day_1":   fb.filter(date__gte=today - timedelta(days=1)).count(),
                "call_day_7":   fb.filter(date__gte=today - timedelta(days=7)).count(),
                "call_day_30":  fb.filter(date__gte=today - timedelta(days=30)).count(),
                "call_day_ytd": fb.filter(date__year=today.year).count(),
            })
        return Response(rows)


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
