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
from . import gceo_legacy as gl
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


# Branch CASE keyed on hf_customer.branch_code (old backend's branch_list /
# rmlist read hf_customer, whose column is `branch_code` — NOT the
# daily_balance_movement `brn_code` that BRN_CASE targets).
BRANCH_CODE_CASE = """
    CASE
        WHEN branch_code::text = '230' THEN 'BURUBURU BRANCH'
        WHEN branch_code::text = '410' THEN 'ELDORET BRANCH'
        WHEN branch_code::text = '25'  THEN 'EMBU BRANCH'
        WHEN branch_code::text = '220' THEN 'HARAMBEE AVE BRANCH'
        WHEN branch_code::text = '100' THEN 'HEAD OFFICE'
        WHEN branch_code::text = '109' THEN 'HF WHIZZ'
        WHEN branch_code::text = '19'  THEN 'HURLINGHAM BRANCH'
        WHEN branch_code::text = '600' THEN 'KISUMU BRANCH'
        WHEN branch_code::text = '16'  THEN 'KITENGELA BRANCH'
        WHEN branch_code::text = '23'  THEN 'KOMAROCK BRANCH'
        WHEN branch_code::text = '24'  THEN 'MACHAKOS BRANCH'
        WHEN branch_code::text = '520' THEN 'MERU BRANCH'
        WHEN branch_code::text = '300' THEN 'MOMBASA BRANCH'
        WHEN branch_code::text = '17'  THEN 'NAIVASHA BRANCH'
        WHEN branch_code::text = '400' THEN 'NAKURU BRANCH'
        WHEN branch_code::text = '22'  THEN 'NANYUKI BRANCH'
        WHEN branch_code::text = '510' THEN 'NYERI BRANCH'
        WHEN branch_code::text = '200' THEN 'REHANI BRANCH'
        WHEN branch_code::text = '20'  THEN 'RIVERROAD BRANCH'
        WHEN branch_code::text = '250' THEN 'RONGAI BRANCH'
        WHEN branch_code::text = '270' THEN 'SAMEER BRANCH'
        WHEN branch_code::text = '500' THEN 'THIKA BRANCH'
        WHEN branch_code::text = '260' THEN 'TRM BRANCH'
        WHEN branch_code::text = '280' THEN 'WESTLANDS BRANCH'
        ELSE 'HEAD OFFICE'
    END
"""

# Segment re-mapping used by top_customer_inflow / top_customer_outflow.
_BANKING_SEGMENT_CASE = """
    CASE
        WHEN customer_segment IN ('FINANCIAL INSTITUTIONS') THEN 'FINANCIAL INSTITUTIONS'
        WHEN customer_segment IN ('INSTITUTIONAL BANKING') THEN 'INSTITUTIONAL BANKING'
        WHEN customer_segment IN ('INTERNAL ACCOUNTS') THEN 'INTERNAL ACCOUNTS'
        WHEN customer_segment IN ('PROJECT FINANCE') THEN 'PROJECT FINANCE'
        WHEN customer_segment IN ('SCHEME') THEN 'SCHEME'
        WHEN customer_segment IN ('VIRTUAL') THEN 'VIRTUAL'
        WHEN customer_segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL BANKING'
        WHEN customer_segment IN ('MEDIUM ENTERPRISES', 'SMALL ENTERPRISES') THEN 'SME'
        WHEN customer_segment IN ('ULTIMATE') THEN 'ULTIMATE BANKING'
        WHEN customer_segment IN ('MASS', 'STANDARD') THEN 'PB'
        ELSE 'New-Unsegmented'
    END
"""


def _topcust_yester_case(col: str) -> str:
    """yester_1/yester_2 fallback used ONLY by top_customer_inflow/outflow.

    Differs from date_utils._yester_case in two ways that the old backend
    intentionally has: the monthly SUMs carry NO ``FILTER (WHERE > 0)``, and the
    January (month = 1) fallback uses ``dec_{cy}`` (current year) rather than
    ``dec_{py}``.
    """
    return f"""
        CASE
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 2)  THEN SUM(dbm.jan_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 3)  THEN SUM(dbm.feb_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 4)  THEN SUM(dbm.mar_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 5)  THEN SUM(dbm.apr_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 6)  THEN SUM(dbm.may_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 7)  THEN SUM(dbm.jun_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 8)  THEN SUM(dbm.jul_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 9)  THEN SUM(dbm.aug_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 10) THEN SUM(dbm.sep_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 11) THEN SUM(dbm.oct_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 12) THEN SUM(dbm.nov_{cy}_bal)
            WHEN (SUM(dbm.{col}) = 0 AND EXTRACT(month FROM current_date) = 1)  THEN SUM(dbm.dec_{cy}_bal)
            ELSE SUM(dbm.{col})
        END
    """


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
        # Old shape: {total, percentage_change}. Frontend reads `total`.
        return Response(gl.customer_total())


@extend_schema(tags=["CEO Dashboard — Customers"])
class ActiveCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # bank_customers_active → {number_of_active, percentage_change} (30-day active).
        return Response(gl.bank_customers_active())


@extend_schema(tags=["CEO Dashboard — Customers"])
class NewCustomerBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: per-segment month-over-month DELTAS keyed by date strings
        # from ceo_customers_base_segment_report.
        return Response(gl.new_customer_base())


@extend_schema(tags=["CEO Dashboard — Customers"])
class YtdCustomerBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: per-segment monthly customer counts (Customer Base table).
        return Response(gl.ytd_customer_base())


@extend_schema(tags=["CEO Dashboard — Customers"])
class NewCustomerTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{yesterday/ytd/mtd + jan_volume..december_volume}] (Target vs Actual table).
        return Response(gl.new_customers_trends())


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
        # Old shape: {number_of_digital, percentage_change}. Frontend reads number_of_digital.
        return Response(gl.digital_customers())


@extend_schema(tags=["CEO Dashboard — Channels"])
class DigitalActive30View(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: {number_of_active, percentage_change}.
        return Response(gl.digital_active_30())


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
class CeoDailyAsOfView(APIView):
    """The reference date of the daily balances — the 'as of' behind the day-over-day
    Top Inflows/Outflows (which compare yester_1_bal vs yester_2_bal)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        latest = DailyBalanceMovement.objects.aggregate(mx=Max("etl_date_updated"))["mx"]
        return Response({"as_of": latest.isoformat() if latest else None})


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
        # Old shape: [{dates_months, rev_sum, cumulative_revenue}]. The ILIKE
        # '%NFI%' filter matched nothing — the category value is exactly 'nfi'.
        return Response(gl.nfi_income_movement())


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestIncomeMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{date_months, rev_sum, cumulative_revenue}]; category is
        # exactly 'interest_income' (the ILIKE patterns matched nothing).
        return Response(gl.intrest_income_movement())


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestExpenseMovementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{date_months, intrest_expense, cumulative_intrest_expense}].
        return Response(gl.intrest_expense_income_movement())


@extend_schema(tags=["CEO Dashboard — Revenue"])
class NFITrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{date_months, sum_rev_nfi}] — 12 months, current month excluded.
        return Response(gl.nfi_income_movement_trend())


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestExpenseTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{date_months, sum_intrest_expense}].
        return Response(gl.intrest_expense_income_movement_trends())


@extend_schema(tags=["CEO Dashboard — Revenue"])
class InterestIncomeTrendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{date_months, sum_intrest_income}].
        return Response(gl.intrest_income_movement_trends())


@extend_schema(tags=["CEO Dashboard — Revenue"])
class TargetTrackerNFIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: scalar {interest_income_actual, nfi_actual, interest_expenses_actual,
        # ytd_*_target, *_gap}. Frontend Revenue Summary + Target Tracker read these keys.
        return Response(gl.target_tracker())


# ── Customer analytics ────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Customers"])
class ProductPerCustomerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Old shape: [{banking_segment, number_of_customers, number_of_products,
        # ppc}] + ROLLUP 'Total' row — the frontend PPC tables read these keys.
        return Response(gl.product_per_customer_by_segment())


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
        # Preferred source: the maintained `customers` master. On prod this table
        # is frequently empty / not present, which left the "Active Customers
        # (MoM)" chart blank. If it yields nothing, fall back to distinct
        # transacting customers per month from `transaction_diary` — the same
        # ledger the digital-channel MoM uses, which IS reliably populated.
        # (No ATOMIC_REQUESTS, so a failed statement doesn't poison the next.)
        rows = []
        try:
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
        except Exception:
            rows = []

        if not rows:
            with connection.cursor() as cur:
                cur.execute("""
                    SELECT
                        TO_CHAR(DATE_TRUNC('month', t.tmstamp), 'YYYY-MM') AS month,
                        COUNT(DISTINCT t.fk_customercust_id)                AS active_count
                    FROM   transaction_diary t
                    WHERE  t.tmstamp IS NOT NULL
                      AND  t.tmstamp >= NOW() - INTERVAL '24 months'
                    GROUP BY DATE_TRUNC('month', t.tmstamp)
                    ORDER BY month
                """)
                cols = [c[0] for c in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Channels"])
class DigitalChannelsMoMView(APIView):
    # Old gceo customers_active_digital_channles_month_on_month: distinct active
    # customers per month over digital channels (ESB / KOCELA / INTERNET) from
    # transaction_diary. The chart reads date_trunc_months + number_active_customers;
    # the previous ceo_channel_report shape ({month, trx_channel, count}) left the
    # "Active Digital Customers — Month on Month" chart (and Latest Month Active) empty.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT   Date_trunc('months', t.tmstamp)       AS date_trunc_months,
                         Count(DISTINCT t.fk_customercust_id)   AS number_active_customers
                FROM     transaction_diary t
                WHERE    1=1
                AND      t.justific_name IN ('CHEQUE DEPOSIT OF OTHER BANK (ELEC.CLER)',
                                             'IN HOUSE CHEQUES',
                                             'DEPOSIT CASH',
                                             'CASH DEPOSIT FROM ATM',
                                             'CASH WITHDRAWAL',
                                             'CHEQUE PAYMENT FROM CARNET',
                                             'ORDINARY CLEARING CHEQUE',
                                             'CLOSURE ZERO BALANCE',
                                             'ATM WITHDRAWAL (HF TERMINAL)',
                                             'Confirmation To Embassies',
                                             'Audit Confirmation',
                                             'Bank Reference/Opinion',
                                             'Interim Statement- e-mail',
                                             'CHEQUE DEPOSIT OF OTHER BANK FC',
                                             'OTC CASH WITHDRAWAL',
                                             'ACCOUNT CLOSING AFTER 6 MONTHS',
                                             'WITHDRAW FROM UNCLEAR BALANCE',
                                             'INTERIM STATEMENT PER PG',
                                             'COUNTER CHEQUE WITHDRAWAL',
                                             'DUPLICATE STATEMENT PER PG',
                                             'DEBIT FROM MOBILE BANKING',
                                             'CREDIT FROM MOBILE BANKING',
                                             'CHEQUE STOP PAYMENT',
                                             'BANK DRAFT ISSUED',
                                             'CR FROM MOBILE BANKING-MPESA TO ACC',
                                             'CONTRACT FINANCING',
                                             'SECURED OVERDRAFTS (SOD)',
                                             'NORMAL INSPECTION FEES-PROJECTS',
                                             'BANK DRAFT ISSUED /NON ACC.HOLDER',
                                             'BANK DRAFT ISSUED /ACC. HOLDER',
                                             'BANK DRAFT ISSUED /STAFF',
                                             'BILL COMMISSION',
                                             'REACTIVATION ACCOUNT CHARGES (DORMANT)',
                                             'STANDING ORDER DEACTIVATION FEE',
                                             'CASH WITHDRAWAL LENGO FOR CLOSING',
                                             'A/C CLOSURE-JOURNAL TRANSFER WITH COMM',
                                             'ATM WITHDRAWAL ONUS KENSWITCH',
                                             'ATM WITHDR OFFUS KENSWITCH',
                                             'ATM WITHDR OFFUS MASTERCARD',
                                             'INCOMING RTGS CR',
                                             'INCOMING RTGS DB',
                                             'BUY GOOD( MOBILE APP)',
                                             'PAY BILL(ACCOUNT TO MPESA PAYBILL)',
                                             'AIRTIME PURCHASE( MOBILE APP)',
                                             'ACCOUNT TO MPESA(B2C)',
                                             'UTILITY BILL PAYMENT(APP)',
                                             'CR UTILITY BILLPAYMENT(APP)',
                                             'CR AIRTIME PURCHASE(APP)',
                                             'CR PAYBILL(ACCOUNT TO MPESA PAYBILL)',
                                             'CR BUY GOODS (APP)',
                                             'MOBILE APP DEPOSIT',
                                             'MPESA CR WHIZZPAY',
                                             'MPESA DR WHIZZPAY',
                                             'DEPOSIT THROUGH TILL',
                                             'DR THROUGH TILL',
                                             'retrieval of documents -vouchers',
                                             'Duplicate Statement (before Bankplus)',
                                             'BATCH STATEMENT CHARGE/PAGE-EMAIL',
                                             'ACCOUNT CLOSING BEFORE 6 MONTHS',
                                             'DOMESTIC FCY CHEQUES VALUE 7days',
                                             'Effects not cleared (withdr from unclear',
                                             'Retrieval of documents Archives',
                                             'STAGE INSPECTION FEES-RETAIL',
                                             'ATM CASH DEPOSIT',
                                             'CLOSED AC BELOW 5Y PER PG')
                AND      t.chanel_description IS NOT NULL
                AND      t.value_date IS NOT NULL
                AND      account_number IS NOT NULL
                AND      product_description IS NOT NULL
                AND      tmstamp >= (Now() - interval '366 days')
                AND      date_trunc('months', tmstamp) != date_trunc('months', now())
                AND      chanel_description IN ('ESB - ENTERPRISE SERVICE BUS','KOCELA - SUBSCRIBER AND PAYMENT CHANNEL','INTERNET')
                GROUP BY date_trunc('months', tmstamp)
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
class MobileLoansView(APIView):
    # Old shape: 9-month aggregate [{date_months, number_of_loans, total_disbused}]
    # — NOT the raw disbursement rows (which the frontend can't chart).
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(gl.mobile_loans())


# ── Staff analytics ───────────────────────────────────────────────────────

@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffInformationView(APIView):
    # Staff Analytics card → [{total_staff, new_hires, new_promotion, total_exit}]
    # (old gceo staff_information). The frontend reads staffInformation[0].total_staff
    # etc.; the previous version returned a paginated EmployeeTable list, so those
    # keys were absent and the card showed 0/0/0/0.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    count(distinct staff_id) FILTER (WHERE exit = 0) AS total_staff,
                    count(distinct staff_id) FILTER (WHERE new = 1 AND date_trunc('year', date_of_employment) = date_trunc('year', now())) AS new_hires,
                    count(distinct staff_id) FILTER (WHERE promotion = 1 AND date_trunc('year', promotion_date) = date_trunc('year', now())) AS new_promotion,
                    count(distinct staff_id) FILTER (WHERE exit = 1 AND date_trunc('year', staff_exit_date) = date_trunc('year', now())) AS total_exit
                FROM employee_table
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


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


class EmployeeRosterPagination(StandardPagination):
    # The full roster is ~1,300 rows; allow a single large page so the admin table
    # can load the whole directory in one request (via the frontend's getList).
    max_page_size = 5000


@extend_schema(tags=["CEO Dashboard — Staff"])
class EmployeeRosterListView(generics.GenericAPIView):
    """Complete HR employee roster from ``employee_table`` (~1,271 staff).

    Unlike the sales/branch DMC tables (``branch_employee_dmc_data`` +
    ``branch_final_employee_dmc_data``, ~808 customer-facing staff), this is the
    full headcount including HQ and back-office. Read-only — ``employee_table`` is
    a managed=False datawarehouse mirror.

    We return an explicit ``.values()`` projection of the columns the directory
    needs rather than the full model serializer: ``employee_table`` carries fields
    the ORM/DRF choke on when serialised in bulk (e.g. a ``DecimalField`` declared
    with ``max_digits=990``), so selecting only the needed plain columns is both
    robust and lighter.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = EmployeeRosterPagination

    # Only the columns the admin directory renders — all safe scalar fields.
    COLUMNS = [
        "name", "staff_id", "national_id", "email",
        "department", "division", "unit", "job_title", "grade", "exit",
    ]
    FILTER_FIELDS = ["department", "division", "unit", "grade", "gender", "exit"]

    def get(self, request):
        qs = EmployeeTable.objects.all()

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(national_id__icontains=search)
                | Q(job_title__icontains=search)
                | Q(department__icontains=search)
                | Q(division__icontains=search)
            )
        for field in self.FILTER_FIELDS:
            value = request.query_params.get(field)
            if value not in (None, ""):
                qs = qs.filter(**{field: value})

        rows = list(qs.order_by("name").values(*self.COLUMNS))

        # staff_id is a Decimal; hand back a plain number so the client renders it cleanly.
        for row in rows:
            sid = row.get("staff_id")
            if sid is not None:
                try:
                    row["staff_id"] = int(sid)
                except (TypeError, ValueError):
                    row["staff_id"] = str(sid)

        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(rows)


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
    # Old gceo staff_years_service: banded service periods, NOT raw service_years.
    # The chart reads service_period ('< 1 yr', '1 - 2 yr', ...) + total_staff;
    # returning {service_years, count} left the chart empty.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    service_period,
                    total_staff,
                    new_hires,
                    new_promotion,
                    total_exit
                FROM (
                    SELECT
                        CASE
                            WHEN service_years < 1 THEN '< 1 yr'
                            WHEN service_years < 2 THEN '1 - 2 yr'
                            WHEN service_years < 5 THEN '2 - 5 yr'
                            WHEN service_years < 8 THEN '5 - 8 yr'
                            WHEN service_years < 10 THEN '8 - 10 yr'
                            WHEN service_years < 15 THEN '10 - 15 yr'
                            WHEN service_years >= 10 THEN '> 15 yr'
                        END::text AS service_period,
                        COUNT(*) FILTER (WHERE exit = 0) AS total_staff,
                        COUNT(*) FILTER (WHERE new = 1) AS new_hires,
                        COUNT(*) FILTER (WHERE promotion = 1) AS new_promotion,
                        COUNT(*) FILTER (WHERE exit = 1) AS total_exit,
                        CASE
                            WHEN service_years < 1 THEN 1
                            WHEN service_years < 2 THEN 2
                            WHEN service_years < 5 THEN 3
                            WHEN service_years < 8 THEN 4
                            WHEN service_years < 10 THEN 5
                            WHEN service_years < 15 THEN 6
                            ELSE 7
                        END AS service_period_order
                    FROM employee_table
                    GROUP BY service_period, service_period_order
                ) AS subquery
                ORDER BY service_period_order
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Staff"])
class StaffProjectionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Monthly staff waterfall (old gceo staff_staff_projections):
        # [{employment_date, total_staff, new_hires, total_exit, new_promotion}].
        with connection.cursor() as cur:
            cur.execute("""
                WITH MonthlyData AS (
                    SELECT
                        CASE WHEN date_of_employment < date_trunc('year', current_date)
                             THEN date_trunc('year', current_date) - INTERVAL '1 months'
                             ELSE date_trunc('month', date_of_employment) END AS employment_date,
                        count(*) AS new_hires, 0 AS total_exit, 0 AS new_promotion
                    FROM employee_table
                    WHERE date_of_employment >= date_trunc('year', CURRENT_DATE) - INTERVAL '1 year'
                    GROUP BY 1
                    UNION ALL
                    SELECT
                        CASE WHEN staff_exit_date < date_trunc('year', current_date)
                             THEN date_trunc('year', current_date) - INTERVAL '1 months'
                             ELSE date_trunc('month', staff_exit_date) END,
                        0, count(*), 0
                    FROM employee_table
                    WHERE staff_exit_date >= date_trunc('year', CURRENT_DATE) - INTERVAL '1 year'
                    GROUP BY 1
                    UNION ALL
                    SELECT
                        CASE WHEN promotion_date < date_trunc('year', current_date)
                             THEN date_trunc('year', current_date) - INTERVAL '1 months'
                             ELSE date_trunc('month', promotion_date) END,
                        0, 0, count(*)
                    FROM employee_table
                    WHERE promotion_date >= date_trunc('year', CURRENT_DATE) - INTERVAL '1 year'
                    GROUP BY 1
                ), MonthlySummary AS (
                    SELECT employment_date,
                           SUM(CASE WHEN new_hires > 0 THEN new_hires ELSE 0 END) AS new_hires,
                           SUM(total_exit) AS total_exit,
                           SUM(CASE WHEN new_promotion > 0 THEN new_promotion ELSE 0 END) AS new_promotion
                    FROM MonthlyData GROUP BY employment_date
                ), YearStart AS (
                    SELECT COUNT(*) AS closing_position
                    FROM employee_table
                    WHERE date_of_employment < date_trunc('year', CURRENT_DATE) - INTERVAL '1 year'
                      AND (staff_exit_date IS NULL OR staff_exit_date > date_trunc('year', CURRENT_DATE) - INTERVAL '1 year')
                ), StaffCount AS (
                    SELECT employment_date,
                           COALESCE(SUM(new_hires) OVER (ORDER BY employment_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0) -
                           COALESCE(SUM(total_exit) OVER (ORDER BY employment_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0) +
                           (SELECT closing_position FROM YearStart) AS total_staff
                    FROM MonthlySummary
                )
                SELECT employment_date, total_staff, new_hires, total_exit, new_promotion
                FROM StaffCount LEFT JOIN MonthlySummary USING (employment_date)
                ORDER BY employment_date
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


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

# Fixed deposits — old backend FD managers (whole-bank/CEO scope). FD is
# identified via product_mapping.product_map = 'FD', not product_type ILIKE '%FD%'
# (which matched nothing -> zeros).
from services import fixed_deposit_managers as fdm


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = fdm.FixedDepositListManager().fixed_deposits_list_overall()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositRateBandsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(fdm.FixedDepositRateBandManager().rate_bands_by_overall())


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositProductSummaryView(APIView):
    """FD balances by product/type + currency (Products table). Mirrors the old
    backend's FixedDepositOverallSummary.product_summary() — FD is identified via
    the product_mapping table (product_map = 'FD'), not a name pattern."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT accs.type, accs.currency, SUM(accs.current_balance) AS amount
                FROM accounts accs
                INNER JOIN product_mapping pm ON accs.type = pm.product_description
                WHERE pm.product_map = 'FD'
                GROUP BY accs.type, accs.currency
                ORDER BY amount DESC
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositSegmentSummaryView(APIView):
    """FD balances by the customer's banking segment (Segment table). Mirrors the
    old backend's FixedDepositOverallSummary.segment_summary()."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT c.banking_segment, SUM(accs.current_balance) AS amount
                FROM accounts accs
                INNER JOIN product_mapping pm ON accs.type = pm.product_description
                INNER JOIN hf_customer c ON c.cust_id = accs.cust_id
                WHERE pm.product_map = 'FD'
                GROUP BY c.banking_segment
                ORDER BY amount DESC
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — Fixed Deposits"])
class CeoFixedDepositExpiryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(fdm.expiry_timeline_band_overall())


# ── Loan arrears ──────────────────────────────────────────────────────────

# Arrears — old backend LoansArrears* managers, whole-bank (CEO) scope, live
# `loans` table (NOT loans_history). Shapes match the old backend.
from services.arrears_managers import (
    LoansArrearsSummaryManager, LoansArrearsDPDBucketSummaryManager,
    LoansProductArrearsSummaryManager, LoansArrearsAccountsListManager,
)


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = LoansArrearsAccountsListManager().accounts_in_arrears()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(LoansArrearsSummaryManager().high_level_summary())


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsDPDView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(LoansArrearsDPDBucketSummaryManager().dpd_bucket_summary())


@extend_schema(tags=["CEO Dashboard — Arrears"])
class CeoLoansArrearsProductsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(LoansProductArrearsSummaryManager().product_arrears_summary())


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
        # Old backend `branch_list`: hf_customer grouped by branch_code CASE,
        # no segment filter and no customer_count (the frontend table reads
        # branch_code / total_revenue / total_deposit_balance / total_loans).
        sql = f"""
            SELECT
                {BRANCH_CODE_CASE} AS branch_code,
                SUM(total_revenue)        AS total_revenue,
                SUM(total_depost_balance) AS total_deposit_balance,
                SUM(total_loans)          AS total_loans
            FROM hf_customer
            GROUP BY {BRANCH_CODE_CASE}
            ORDER BY {BRANCH_CODE_CASE}
        """
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["CEO Dashboard — RM"])
class RMListView(APIView):
    """Old backend `rmlist`: per-RM revenue / deposit / loan totals from
    hf_customer joined to retail_allocated_portfolio (NOT a distinct dropdown
    off daily_balance_movement, which returned no totals)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = """
            SELECT
                sales_code,
                rap.rm_name,
                SUM(total_revenue)        AS total_revenue,
                SUM(total_depost_balance) AS total_deposit_balance,
                SUM(total_loans)          AS total_loans
            FROM hf_customer
            LEFT JOIN retail_allocated_portfolio rap
                ON hf_customer.cust_id = rap.cust_id
            GROUP BY sales_code, rap.rm_name
        """
        with connection.cursor() as cur:
            cur.execute(sql)
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
                brn_name AS brn_code,
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
                brn_name AS brn_code,
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
        # Old backend `top_customer_inflow`: aggregate per customer with the
        # month-fallback yester CASE (plain SUMs, no >0 filter), then take the
        # top 10 by inflow movement.
        yester2 = _topcust_yester_case("yester_2_bal")
        yester1 = _topcust_yester_case("yester_1_bal")
        sql = f"""
            WITH data AS (
                SELECT
                    dbm.cust_cif,
                    dbm.full_name,
                    rap.rm_name,
                    {yester2} AS yester_2_bal,
                    {yester1} AS yester_1_bal,
                    {_BANKING_SEGMENT_CASE} AS banking_segment
                FROM daily_balance_movement dbm
                LEFT JOIN retail_allocated_portfolio rap
                    ON dbm.cust_cif = rap.cust_id
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
                GROUP BY dbm.cust_cif, dbm.full_name, rap.rm_name, customer_segment
            )
            SELECT
                cust_cif,
                full_name,
                rm_name,
                yester_2_bal,
                yester_1_bal,
                yester_1_bal - yester_2_bal AS movement,
                banking_segment
            FROM data
            ORDER BY (yester_1_bal - yester_2_bal)::int DESC
            LIMIT 10
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
        # Old backend `top_customer_outflow`: same aggregate as inflow, ordered
        # ascending (largest outflow first), top 10.
        yester2 = _topcust_yester_case("yester_2_bal")
        yester1 = _topcust_yester_case("yester_1_bal")
        sql = f"""
            WITH data AS (
                SELECT
                    dbm.cust_cif,
                    dbm.full_name,
                    rap.rm_name,
                    {yester2} AS yester_2_bal,
                    {yester1} AS yester_1_bal,
                    {_BANKING_SEGMENT_CASE} AS banking_segment
                FROM daily_balance_movement dbm
                LEFT JOIN retail_allocated_portfolio rap
                    ON dbm.cust_cif = rap.cust_id
                WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
                GROUP BY dbm.cust_cif, dbm.full_name, rap.rm_name, customer_segment
            )
            SELECT
                cust_cif,
                full_name,
                rm_name,
                yester_2_bal,
                yester_1_bal,
                yester_1_bal - yester_2_bal AS movement,
                banking_segment
            FROM data
            ORDER BY (yester_1_bal - yester_2_bal)::int ASC
            LIMIT 10
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
        # Old backend `rm_ytd_movement`: rm_name comes from the rap join,
        # dec_bal is an unfiltered SUM(dec_{py}_bal), yester_1_bal uses the
        # month-fallback CASE, and there is NO customer_segment filter.
        yester1 = _yester_case("dbm", "yester_1_bal", cy, py)
        sql = f"""
            WITH data AS (
                SELECT
                    rm_code,
                    rap.rm_name,
                    SUM(dbm.dec_{py}_bal) AS dec_bal,
                    {yester1} AS yester_1_bal
                FROM daily_balance_movement dbm
                LEFT JOIN retail_allocated_portfolio rap
                    ON dbm.cust_cif = rap.cust_id
                GROUP BY rm_code, rap.rm_name
            )
            SELECT
                rm_code,
                rm_name,
                dec_bal,
                yester_1_bal,
                yester_1_bal - dec_bal AS movement
            FROM data
            ORDER BY (yester_1_bal - dec_bal) DESC
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
