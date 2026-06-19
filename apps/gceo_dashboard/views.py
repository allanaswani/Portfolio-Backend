from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Q
from django.db import connection

from core.pagination import StandardPagination, LargePagination
from core.date_utils import (
    current_year, previous_year, year_before_last,
    cy, py, ybl, MONTH_DATES, BRN_CASE,
    _yester_case, _prev_month_case,
)
from .models import (
    CeoDepositMovementMonthly, Customers, CeoChannelReport, TransactionDiary,
    CeoDepositMovement, CeoDepositMovementDaily, Revenue, MobileLoanDisbusements,
    HfCustomer, PhoneNumber, AccountsHistory, CeoLoanMovementMonthlyBySegment,
    CeoDepositMovementMonthlyBySegment, DailyBalanceMovement, LoanDailyBalanceMovement,
    EmployeeTable, LoansHistory, Accounts,
)
from .serializers import (
    CeoDepositMovementMonthlySerializer, CustomersSerializer, CeoChannelReportSerializer,
    TransactionDiarySerializer, CeoDepositMovementSerializer, CeoDepositMovementDailySerializer,
    RevenueSerializer, MobileLoanDisbusementsSerializer, HfCustomerSerializer,
    PhoneNumberSerializer, AccountsHistorySerializer, CeoLoanMovementMonthlyBySegmentSerializer,
    CeoDepositMovementMonthlyBySegmentSerializer, DailyBalanceMovementSerializer,
    LoanDailyBalanceMovementSerializer, EmployeeTableSerializer, LoansHistorySerializer,
    AccountsSerializer,
)
import django_filters.rest_framework


# ── Helpers ──────────────────────────────────────────────────────────────────

def _raw_to_list(qs, fields):
    return [{f: getattr(r, f) for f in fields} for r in qs]


def _monthly_movement_sql(table: str) -> str:
    month_sums = "\n".join(
        f"         SUM(dbm.{col}_bal) FILTER (WHERE dbm.{col}_bal > 0) AS {col},"
        for _, col in MONTH_DATES
    )
    yester2 = _yester_case("dbm", "yester_2_bal", cy, py)
    yester1 = _yester_case("dbm", "yester_1_bal", cy, py)
    return f"""
        SELECT 1 AS id,
               COALESCE(dbm.customer_segment, 'New-Unsegmented') AS customer_segment,
               {month_sums}
               {yester2} AS yester_2_bal,
               {yester1} AS yester_1_bal
        FROM {table} dbm
        GROUP BY COALESCE(dbm.customer_segment, 'New-Unsegmented')
    """


# ── Existing views (unchanged) ─────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Deposits"])
class MonthlyMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = DailyBalanceMovement.objects.raw(_monthly_movement_sql("daily_balance_movement"))
        data = [
            {
                "customer_segment": r.customer_segment,
                **{date_key: getattr(r, col, None) for date_key, col in MONTH_DATES},
                "yester_2_bal": r.yester_2_bal,
                "yester_1_bal": r.yester_1_bal,
            }
            for r in qs
        ]
        return Response(data)


@extend_schema(tags=["CEO Dashboard — Loans"])
class LoanMonthlyMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LoanDailyBalanceMovement.objects.raw(
            _monthly_movement_sql("loan_daily_balance_movement")
        )
        data = [
            {
                "customer_segment": r.customer_segment,
                **{date_key: getattr(r, col, None) for date_key, col in MONTH_DATES},
                "yester_2_bal": r.yester_2_bal,
                "yester_1_bal": r.yester_1_bal,
            }
            for r in qs
        ]
        return Response(data)


@extend_schema(tags=["CEO Dashboard — Deposits"])
class LatestMonthlyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rec = CeoDepositMovementMonthly.objects.order_by("-dates_eom").first()
        if not rec:
            return Response({})
        return Response(CeoDepositMovementMonthlySerializer(rec).data)


@extend_schema(tags=["CEO Dashboard — Deposits"])
class LatestDailyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rec = CeoDepositMovementDaily.objects.order_by("-dates_eom").first()
        if not rec:
            return Response({})
        return Response(CeoDepositMovementDailySerializer(rec).data)


@extend_schema(tags=["CEO Dashboard — Customers"])
class CustomerTotalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = Customers.objects.count()
        active = Customers.objects.filter(status="Active").count()
        return Response({"total_customers": total, "active_customers": active})


@extend_schema(tags=["CEO Dashboard — Customers"])
class ActiveCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            Customers.objects.filter(status="Active")
            .values("segment")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response(list(qs))


@extend_schema(tags=["CEO Dashboard — Customers"])
class NewCustomerBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            Customers.objects.filter(open_date__year=current_year)
            .values("segment")
            .annotate(count=Count("id"))
        )
        return Response(list(qs))


@extend_schema(tags=["CEO Dashboard — Customers"])
class YtdCustomerBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Customers.objects.filter(open_date__year=current_year).count()
        return Response({"ytd_new_customers": count, "year": current_year})


@extend_schema(tags=["CEO Dashboard — Customers"])
class NewCustomerTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    TO_CHAR(open_date, 'YYYY-MM') AS month,
                    COUNT(*) AS count
                FROM customers
                WHERE EXTRACT(year FROM open_date) = {current_year}
                GROUP BY TO_CHAR(open_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Channels"])
class TransactingActivityView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CeoChannelReportSerializer
    queryset = CeoChannelReport.objects.all()
    pagination_class = StandardPagination


@extend_schema(tags=["CEO Dashboard — Channels"])
class DigitalCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            CeoChannelReport.objects.values("trx_channel")
            .annotate(count=Count("cust_id"))
        )
        return Response(list(data))


@extend_schema(tags=["CEO Dashboard — Channels"])
class DigitalActive30View(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT trx_channel, COUNT(DISTINCT cust_id) AS count
                FROM ceo_channel_report
                WHERE trx_date >= current_date - INTERVAL '30 days'
                GROUP BY trx_channel
                ORDER BY count DESC
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Deposits"])
class DepositMovementView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CeoDepositMovementSerializer
    queryset = CeoDepositMovement.objects.all()


@extend_schema(tags=["CEO Dashboard — Deposits"])
class DepositMovementDailyView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CeoDepositMovementDailySerializer
    queryset = CeoDepositMovementDaily.objects.all()


@extend_schema(tags=["CEO Dashboard — Deposits"])
class SegmentDailyMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                COALESCE(customer_segment, 'New-Unsegmented') AS customer_segment,
                {yester2} AS yester_2_bal,
                {yester1} AS yester_1_bal
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
            GROUP BY COALESCE(customer_segment, 'New-Unsegmented')
            ORDER BY yester_1_bal DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Deposits"])
class DailyMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            SELECT
                1 AS id,
                {yester2} AS yester_2_bal,
                {yester1} AS yester_1_bal
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
        """
        qs = DailyBalanceMovement.objects.raw(sql)
        rows = [{"yester_2_bal": r.yester_2_bal, "yester_1_bal": r.yester_1_bal} for r in qs]
        return Response(rows[0] if rows else {})


@extend_schema(tags=["CEO Dashboard — Deposits"])
class DepositGrowthPctView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            WITH totals AS (
                SELECT
                    {yester2} AS y2,
                    {yester1} AS y1
                FROM daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
            )
            SELECT
                y1,
                y2,
                CASE WHEN y2 > 0 THEN ROUND(((y1 - y2) / y2 * 100)::numeric, 2) ELSE 0 END AS pct_growth
            FROM totals
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        if row:
            return Response({"yester_1_bal": row[0], "yester_2_bal": row[1], "pct_growth": row[2]})
        return Response({})


# ── Revenue / Income endpoints ────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Revenue"])
class NFIIncomeMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    income_category,
                    SUM(sum_dc) AS total,
                    TO_CHAR(trx_date, 'YYYY-MM') AS month
                FROM revenue
                WHERE income_category ILIKE '%NFI%'
                  AND EXTRACT(year FROM trx_date) = {current_year}
                GROUP BY income_category, TO_CHAR(trx_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestIncomeMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    income_category,
                    SUM(sum_dc) AS total,
                    TO_CHAR(trx_date, 'YYYY-MM') AS month
                FROM revenue
                WHERE income_category ILIKE '%INTEREST INCOME%'
                   OR income_category ILIKE '%INT INCOME%'
                GROUP BY income_category, TO_CHAR(trx_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestExpenseMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    income_category,
                    SUM(sum_dc) AS total,
                    TO_CHAR(trx_date, 'YYYY-MM') AS month
                FROM revenue
                WHERE income_category ILIKE '%INTEREST EXPENSE%'
                   OR income_category ILIKE '%INT EXPENSE%'
                GROUP BY income_category, TO_CHAR(trx_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Revenue"])
class NFITrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    TO_CHAR(trx_date, 'YYYY-MM') AS month,
                    SUM(sum_dc) AS total
                FROM revenue
                WHERE income_category ILIKE '%NFI%'
                GROUP BY TO_CHAR(trx_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestExpenseTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    TO_CHAR(trx_date, 'YYYY-MM') AS month,
                    SUM(sum_dc) AS total
                FROM revenue
                WHERE income_category ILIKE '%INTEREST EXPENSE%'
                   OR income_category ILIKE '%INT EXPENSE%'
                GROUP BY TO_CHAR(trx_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestIncomeTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    TO_CHAR(trx_date, 'YYYY-MM') AS month,
                    SUM(sum_dc) AS total
                FROM revenue
                WHERE income_category ILIKE '%INTEREST INCOME%'
                   OR income_category ILIKE '%INT INCOME%'
                GROUP BY TO_CHAR(trx_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Revenue"])
class TargetTrackerNFIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT
                    income_category,
                    SUM(sum_dc) AS actual_total
                FROM revenue
                WHERE EXTRACT(year FROM trx_date) = {current_year}
                GROUP BY income_category
                ORDER BY actual_total DESC NULLS LAST
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Customer analytics ────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Customers"])
class ProductPerCustomerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    segment,
                    AVG(CASE WHEN fd > 0    THEN 1 ELSE 0 END +
                        CASE WHEN ca > 0    THEN 1 ELSE 0 END +
                        CASE WHEN sa > 0    THEN 1 ELSE 0 END +
                        CASE WHEN mobile > 0 THEN 1 ELSE 0 END +
                        CASE WHEN mortagage > 0 THEN 1 ELSE 0 END)::numeric AS avg_products
                FROM hf_customer
                WHERE segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                GROUP BY segment
                ORDER BY avg_products DESC NULLS LAST
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Customers"])
class ProductINFFocusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    segment,
                    COUNT(*) FILTER (WHERE fd > 0) AS fd_count,
                    COUNT(*) FILTER (WHERE ca > 0) AS ca_count,
                    COUNT(*) FILTER (WHERE sa > 0) AS sa_count,
                    COUNT(*) FILTER (WHERE mobile > 0) AS mobile_count,
                    COUNT(*) FILTER (WHERE mortagage > 0) AS mortgage_count,
                    COUNT(*) AS total_customers
                FROM hf_customer
                WHERE segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                GROUP BY segment
                ORDER BY total_customers DESC
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Customers"])
class ActiveCustomersMoMView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    TO_CHAR(last_updated_date, 'YYYY-MM') AS month,
                    COUNT(*) AS active_count
                FROM customers
                WHERE status = 'Active'
                  AND last_updated_date IS NOT NULL
                GROUP BY TO_CHAR(last_updated_date, 'YYYY-MM')
                ORDER BY month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Channels"])
class DigitalChannelsMoMView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    TO_CHAR(trx_date, 'YYYY-MM') AS month,
                    trx_channel,
                    COUNT(DISTINCT cust_id) AS count
                FROM ceo_channel_report
                GROUP BY TO_CHAR(trx_date, 'YYYY-MM'), trx_channel
                ORDER BY month, count DESC
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Loan movement ─────────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Loans"])
class LoansBySegmentTrendView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CeoLoanMovementMonthlyBySegmentSerializer
    queryset = CeoLoanMovementMonthlyBySegment.objects.all().order_by("dates_eom")


@extend_schema(tags=["CEO Dashboard — Loans"])
class MobileLoansView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MobileLoanDisbusementsSerializer
    queryset = MobileLoanDisbusements.objects.all()
    pagination_class = StandardPagination


# ── Staff analytics ───────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffInformationView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmployeeTableSerializer
    queryset = EmployeeTable.objects.all()
    pagination_class = StandardPagination


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffGenderView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            EmployeeTable.objects.exclude(exit=1)
            .values("gender")
            .annotate(count=Count("id"))
        )
        return Response(list(data))


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffDepartmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            EmployeeTable.objects.exclude(exit=1)
            .values("department")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response(list(data))


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffGradeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            EmployeeTable.objects.exclude(exit=1)
            .values("grade")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response(list(data))


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffYearsServiceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            EmployeeTable.objects.exclude(exit=1)
            .values("service_years")
            .annotate(count=Count("id"))
            .order_by("service_years")
        )
        return Response(list(data))


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffProjectionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        agg = EmployeeTable.objects.aggregate(
            total=Count("id"),
            exits=Sum("exit"),
            promotions=Sum("promotion"),
            new_hires=Sum("new"),
        )
        return Response(agg)


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffServiceTypeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            EmployeeTable.objects.exclude(exit=1)
            .values("service_code")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response(list(data))


# ── Fixed Deposits ────────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountsSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return Accounts.objects.filter(product_type__icontains="FD")


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositRateBandsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    CASE
                        WHEN interest_rate < 5  THEN '0-5%'
                        WHEN interest_rate < 8  THEN '5-8%'
                        WHEN interest_rate < 10 THEN '8-10%'
                        WHEN interest_rate < 12 THEN '10-12%'
                        ELSE '12%+'
                    END AS rate_band,
                    COUNT(*) AS count,
                    SUM(current_balance) AS total_balance
                FROM accounts
                WHERE product_type ILIKE '%FD%'
                  AND account_status NOT ILIKE '%CLOSE%'
                GROUP BY rate_band
                ORDER BY rate_band
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositExpiryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    TO_CHAR(expiry_date, 'YYYY-MM') AS expiry_month,
                    COUNT(*) AS count,
                    SUM(current_balance) AS total_balance
                FROM accounts
                WHERE product_type ILIKE '%FD%'
                  AND expiry_date >= current_date
                GROUP BY TO_CHAR(expiry_date, 'YYYY-MM')
                ORDER BY expiry_month
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Loan arrears ──────────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoansHistorySerializer
    pagination_class = StandardPagination
    queryset = LoansHistory.objects.filter(days_in_arrears__gt=0)


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LoansHistory.objects.filter(days_in_arrears__gt=0)
        agg = qs.aggregate(
            total_accounts=Count("id"),
            total_arrears=Sum("total_arrears"),
            total_capital=Sum("capital_balance"),
        )
        return Response(agg)


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsDPDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    CASE
                        WHEN days_in_arrears BETWEEN 1 AND 30   THEN '1-30 days'
                        WHEN days_in_arrears BETWEEN 31 AND 60  THEN '31-60 days'
                        WHEN days_in_arrears BETWEEN 61 AND 90  THEN '61-90 days'
                        WHEN days_in_arrears BETWEEN 91 AND 180 THEN '91-180 days'
                        WHEN days_in_arrears > 180              THEN '180+ days'
                        ELSE 'Unknown'
                    END AS dpd_bucket,
                    COUNT(*) AS count,
                    SUM(total_arrears) AS total_arrears
                FROM loans_history
                WHERE days_in_arrears > 0
                GROUP BY dpd_bucket
                ORDER BY dpd_bucket
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsProductsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            LoansHistory.objects.filter(days_in_arrears__gt=0)
            .values("loan_product")
            .annotate(count=Count("id"), total_arrears=Sum("total_arrears"))
            .order_by("-total_arrears")
        )
        return Response(list(data))


# ── Movement by segment ───────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Movement"])
class LoanMovementBySegmentView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CeoLoanMovementMonthlyBySegmentSerializer
    queryset = CeoLoanMovementMonthlyBySegment.objects.all()


@extend_schema(tags=["CEO Dashboard — Movement"])
class DepositMovementBySegmentView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CeoDepositMovementMonthlyBySegmentSerializer
    queryset = CeoDepositMovementMonthlyBySegment.objects.all()


# ── Balance movement ──────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Balance"])
class DailyBalanceMovementView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DailyBalanceMovementSerializer
    pagination_class = LargePagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["rm_code", "customer_segment", "brn_code"]
    queryset = DailyBalanceMovement.objects.all()


@extend_schema(tags=["CEO Dashboard — Balance"])
class LoanDailyBalanceMovementView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoanDailyBalanceMovementSerializer
    pagination_class = LargePagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["rm_code", "customer_segment", "brn_code"]
    queryset = LoanDailyBalanceMovement.objects.all()


# ── Branch & RM analytics ─────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Branches"])
class BranchListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = f"""
            SELECT
                {BRN_CASE} AS branch_name,
                SUM(total_depost_balance) AS total_deposit_balance,
                SUM(total_loans) AS total_loans,
                SUM(total_revenue) AS total_revenue,
                COUNT(*) AS customer_count
            FROM hf_customer
            WHERE segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
            GROUP BY {BRN_CASE}
            ORDER BY total_deposit_balance DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — RM"])
class RMListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT
                    rm_code,
                    sale_code,
                    full_name
                FROM daily_balance_movement
                WHERE rm_code IS NOT NULL
                ORDER BY full_name
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Branches"])
class BranchDepositTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        prev_month = _prev_month_case("", cy, py)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            WITH data AS (
                SELECT
                    {BRN_CASE} AS brn_name,
                    SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal,
                    {prev_month} AS prev_month_bal,
                    {yester2} AS yester_2_bal,
                    {yester1} AS yester_1_bal
                FROM daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
                GROUP BY {BRN_CASE}
            )
            SELECT
                brn_name,
                dec_bal,
                prev_month_bal,
                yester_2_bal,
                yester_1_bal,
                yester_1_bal - yester_2_bal AS dtd_movement,
                yester_1_bal - prev_month_bal AS mtd_movement,
                yester_1_bal - dec_bal AS ytd_movement
            FROM data
            ORDER BY yester_1_bal DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Branches"])
class BranchLoanTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        prev_month = _prev_month_case("", cy, py)
        yester2 = _yester_case("", "yester_2_bal", cy, py)
        yester1 = _yester_case("", "yester_1_bal", cy, py)
        sql = f"""
            WITH data AS (
                SELECT
                    {BRN_CASE} AS brn_name,
                    SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal,
                    {prev_month} AS prev_month_bal,
                    {yester2} AS yester_2_bal,
                    {yester1} AS yester_1_bal
                FROM loan_daily_balance_movement
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
                GROUP BY {BRN_CASE}
            )
            SELECT
                brn_name,
                dec_bal,
                prev_month_bal,
                yester_2_bal,
                yester_1_bal,
                yester_1_bal - yester_2_bal AS dtd_movement,
                yester_1_bal - prev_month_bal AS mtd_movement,
                yester_1_bal - dec_bal AS ytd_movement
            FROM data
            ORDER BY yester_1_bal DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Balance"])
class TopCustomerInflowView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = f"""
            SELECT
                cust_cif,
                full_name,
                customer_segment,
                rm_code,
                yester_1_bal,
                yester_2_bal,
                yester_1_bal - yester_2_bal AS movement
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND yester_1_bal > yester_2_bal
            ORDER BY (yester_1_bal - yester_2_bal) DESC NULLS LAST
            LIMIT 50
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Balance"])
class TopCustomerOutflowView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = f"""
            SELECT
                cust_cif,
                full_name,
                customer_segment,
                rm_code,
                yester_1_bal,
                yester_2_bal,
                yester_2_bal - yester_1_bal AS outflow
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND yester_2_bal > yester_1_bal
            ORDER BY (yester_2_bal - yester_1_bal) DESC NULLS LAST
            LIMIT 50
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — RM"])
class RMYTDMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = f"""
            SELECT
                rm_code,
                MAX(sale_code) AS sale_code,
                MAX(full_name) AS rm_name,
                SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS yester_1_bal,
                SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS dec_bal,
                SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
                    - SUM(dec_{py}_bal) FILTER (WHERE dec_{py}_bal > 0) AS ytd_movement
            FROM daily_balance_movement
            WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
              AND rm_code IS NOT NULL
            GROUP BY rm_code
            ORDER BY ytd_movement DESC NULLS LAST
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


# ── Revenue / customers ───────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Revenue"])
class RevenueView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RevenueSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "income_category", "brn_code"]
    queryset = Revenue.objects.all()


@extend_schema(tags=["CEO Dashboard — Customers"])
class CeoCustomersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomersSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["branch", "segment", "status", "type"]
    queryset = Customers.objects.all()


@extend_schema(tags=["CEO Dashboard — Transactions"])
class TransactionDiaryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionDiarySerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["trx_unit", "channel_id", "trx_code"]
    queryset = TransactionDiary.objects.all()
