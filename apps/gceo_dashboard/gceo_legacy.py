"""Verbatim ports of the OLD gceo_dashboard customer-KPI raw queries.

The rewritten views returned per-channel/segment LISTS, but the frontend (built for
the old backend) expects SCALAR objects: {total,...}, {number_of_digital,...},
{number_of_active,...}. These reproduce the old queries 1:1 against the same tables.
"""
from django.core.cache import cache
from django.db import connection
from apps.gceo_dashboard.models import Customers, TransactionDiary
from core.date_utils import current_year, previous_year


def _first(rows, default=None):
    for r in rows:
        return r
    return default


# These four customer KPIs run live COUNT(DISTINCT) aggregations over the very
# large customers/accounts and transaction_diary tables. They are daily-grade
# figures, so we serve them from the shared (DB) cache and only recompute every
# 30 min — this keeps a single heavy query from blocking gunicorn workers on
# every dashboard load. See ActiveCustomersView (was timing out at 120s).
_KPI_TTL = 60 * 30  # seconds


def _cached(key, compute, ttl=_KPI_TTL):
    value = cache.get(key)
    if value is None:
        value = compute()
        cache.set(key, value, ttl)
    return value


def customer_total():
    """customer_total/ → {total, percentage_change} (old customer_total_list)."""
    def _compute():
        q = Customers.objects.raw('''
            SELECT 1 id,
                Count(DISTINCT c.cust_id) filter ( WHERE account_no IS NOT NULL ) AS total,
                round(CASE
                    WHEN (count(DISTINCT c.cust_id) filter ( WHERE c.open_date::DATE >= date_trunc('year', now())::timestamp::DATE)::DOUBLE PRECISION / nullif(count(DISTINCT c.cust_id),0))::DOUBLE PRECISION * 1 IS NULL THEN 0
                    ELSE (count(DISTINCT c.cust_id) filter ( WHERE c.open_date::DATE >= date_trunc('year', now())::timestamp::DATE)::DOUBLE PRECISION / nullif(count(DISTINCT c.cust_id),0))::DOUBLE PRECISION * 1
                END::numeric, 2) AS percentage_change
            FROM customers c
            JOIN accounts a ON c.cust_id = a.cust_id
        ''')
        r = _first(q)
        return {"total": r.total, "percentage_change": r.percentage_change} if r else {}
    return _cached("gceo:customer_total", _compute)


def digital_customers():
    """digital_customers/ → {number_of_digital, percentage_change} (VIRTUAL ACCOUNT MOBILE)."""
    def _compute():
        q = Customers.objects.raw('''
            SELECT 1 id,
                Count(DISTINCT c.cust_id) filter ( WHERE account_no IS NOT NULL ) AS number_of_digital,
                round(CASE
                    WHEN (count(DISTINCT c.cust_id) filter ( WHERE c.open_date::DATE >= date_trunc('year', now())::timestamp::DATE)::DOUBLE PRECISION / nullif(count(DISTINCT c.cust_id),0))::DOUBLE PRECISION * 1 IS NULL THEN 0
                    ELSE (count(DISTINCT c.cust_id) filter ( WHERE c.open_date::DATE >= date_trunc('year', now())::timestamp::DATE)::DOUBLE PRECISION / nullif(count(DISTINCT c.cust_id),0))::DOUBLE PRECISION * 1
                END::numeric, 2) AS percentage_change
            FROM customers c
            LEFT JOIN accounts a ON c.cust_id = a.cust_id
            WHERE a.product_type = 'VIRTUAL ACCOUNT MOBILE' AND 1=1
        ''')
        r = _first(q)
        return {"number_of_digital": r.number_of_digital, "percentage_change": r.percentage_change} if r else {}
    return _cached("gceo:digital_customers", _compute)


def bank_customers_active():
    """bank_customers_active → {number_of_active, percentage_change} — distinct customers
    transacting in the last 30 days (old customers_active)."""
    def _compute():
        q = TransactionDiary.objects.raw('''
        SELECT 1 id,
            Count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp >= now() - interval '30days') AS number_of_active,
            ((count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp <= now() - interval '30days' AND tmstamp >= now() - interval '60days')
              - count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp >= now() - interval '30days'))::DOUBLE PRECISION
             / nullif(count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp <= now() - interval '30days' AND tmstamp >= now() - interval '60days'),0))::DOUBLE PRECISION * 1 AS percentage_change
        FROM transaction_diary t
        WHERE
            -- Every FILTER above only looks back 60 days, so rows older than that
            -- contribute 0 to all counts. Bounding the scan here is equivalent but
            -- reads a 60-day slice instead of the entire transaction history
            -- (this is what was blowing the 120s worker timeout).
            t.tmstamp >= now() - interval '60days' AND
            t.justific_name IN (
            'CHEQUE DEPOSIT OF OTHER BANK (ELEC.CLER)','IN HOUSE CHEQUES','DEPOSIT CASH','CASH DEPOSIT FROM ATM',
            'CASH WITHDRAWAL','CHEQUE PAYMENT FROM CARNET','ORDINARY CLEARING CHEQUE','CLOSURE ZERO BALANCE',
            'ATM WITHDRAWAL (HF TERMINAL)','Confirmation To Embassies','Audit Confirmation','Bank Reference/Opinion',
            'Interim Statement- e-mail','CHEQUE DEPOSIT OF OTHER BANK FC','OTC CASH WITHDRAWAL','ACCOUNT CLOSING AFTER 6 MONTHS',
            'WITHDRAW FROM UNCLEAR BALANCE','INTERIM STATEMENT PER PG','COUNTER CHEQUE WITHDRAWAL','DUPLICATE STATEMENT PER PG',
            'DEBIT FROM MOBILE BANKING','CREDIT FROM MOBILE BANKING','CHEQUE STOP PAYMENT','BANK DRAFT ISSUED',
            'CR FROM MOBILE BANKING-MPESA TO ACC','CONTRACT FINANCING','SECURED OVERDRAFTS (SOD)','NORMAL INSPECTION FEES-PROJECTS',
            'BANK DRAFT ISSUED /NON ACC.HOLDER','BANK DRAFT ISSUED /ACC. HOLDER','BANK DRAFT ISSUED /STAFF','BILL COMMISSION',
            'REACTIVATION ACCOUNT CHARGES (DORMANT)','STANDING ORDER DEACTIVATION FEE','CASH WITHDRAWAL LENGO FOR CLOSING',
            'A/C CLOSURE-JOURNAL TRANSFER WITH COMM','ATM WITHDRAWAL ONUS KENSWITCH','ATM WITHDR OFFUS KENSWITCH',
            'ATM WITHDR OFFUS MASTERCARD','INCOMING RTGS CR','INCOMING RTGS DB','BUY GOOD( MOBILE APP)',
            'PAY BILL(ACCOUNT TO MPESA PAYBILL)','AIRTIME PURCHASE( MOBILE APP)','ACCOUNT TO MPESA(B2C)','UTILITY BILL PAYMENT(APP)',
            'CR UTILITY BILLPAYMENT(APP)','CR AIRTIME PURCHASE(APP)','CR PAYBILL(ACCOUNT TO MPESA PAYBILL)','CR BUY GOODS (APP)',
            'MOBILE APP DEPOSIT','MPESA CR WHIZZPAY','MPESA DR WHIZZPAY','DEPOSIT THROUGH TILL','DR THROUGH TILL',
            'retrieval of documents -vouchers','Duplicate Statement (before Bankplus)','BATCH STATEMENT CHARGE/PAGE-EMAIL',
            'ACCOUNT CLOSING BEFORE 6 MONTHS','DOMESTIC FCY CHEQUES VALUE 7days','Effects not cleared (withdr from unclear',
            'Retrieval of documents Archives','STAGE INSPECTION FEES-RETAIL','ATM CASH DEPOSIT','CLOSED AC BELOW 5Y PER PG')
        AND t.chanel_description IS NOT NULL
        AND t.value_date IS NOT NULL
        AND account_number IS NOT NULL
        AND product_description IS NOT NULL
        AND lower(reversed_trx_flag) != lower('Reversed')
        AND reverse_flag != 'Reversal'
    ''')
        r = _first(q)
        return {"number_of_active": r.number_of_active, "percentage_change": r.percentage_change} if r else {}
    return _cached("gceo:bank_customers_active", _compute)


def digital_active_30():
    """digital_active_30_days → {number_of_active, percentage_change} — distinct customers
    active on digital channels in the last 30 days."""
    def _compute():
        q = TransactionDiary.objects.raw('''
        SELECT 1 id,
            Count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp >= now() - interval '30days') AS number_of_active,
            ((count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp <= now() - interval '30days' AND tmstamp >= now() - interval '60days')
              - count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp >= now() - interval '30days'))::DOUBLE PRECISION
             / nullif(count(DISTINCT fk_customercust_id) filter ( WHERE tmstamp <= now() - interval '30days' AND tmstamp >= now() - interval '60days'),0))::DOUBLE PRECISION * 1 AS percentage_change
        FROM transaction_diary t
        WHERE
            -- Bound the scan to the 60-day window the FILTERs use (see bank_customers_active).
            t.tmstamp >= now() - interval '60days' AND
            t.justific_name IN (
            'ESB - ENTERPRISE SERVICE BUS','KOCELA - SUBSCRIBER AND PAYMENT CHANNEL','DEPOSIT CASH')
        AND t.chanel_description IS NOT NULL
    ''')
        r = _first(q)
        return {"number_of_active": r.number_of_active, "percentage_change": r.percentage_change} if r else {}
    return _cached("gceo:digital_active_30", _compute)


def new_customers_trends():
    """new_customers_trends → single row from new_customer_numbers with
    yesterday/ytd/mtd + jan_volume..december_volume (old new_customers_trend_api).
    Returned as a list (frontend reads [0].<mon>_volume)."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT yesterday_volume, ytd_volume, mtd_volume,
                   jan_volume, feb_volume, mar_volume, apr_volume, may_volume, june_volume,
                   july_volume, aug_volume, sept_volume, oct_volume, nov_volume, december_volume
            FROM new_customer_numbers
        """)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def ytd_customer_base():
    """ytd_customer_base → per banking_segment monthly customer counts from
    ceo_customers_base_segment_report (old ytd_customer_base_api). Column ORDER is
    load-bearing: the frontend reads Object.values() positionally (segment, then
    prev-Dec + Jan..Dec)."""
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT banking_segment,
                   prev_dec AS value_dec_{previous_year},
                   jan AS value_jan_{current_year},
                   feb AS value_feb_{current_year},
                   mar AS value_mar_{current_year},
                   apr AS value_apr_{current_year},
                   may AS value_may_{current_year},
                   jun AS value_june_{current_year},
                   jul AS value_july_{current_year},
                   aug AS value_aug_{current_year},
                   sep AS value_sept_{current_year},
                   oct AS value_oct_{current_year},
                   nov AS value_nov_{current_year},
                   dec AS value_dec_{current_year}
            FROM ceo_customers_base_segment_report
        """)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def target_tracker():
    """target_tracker_nfi_expense_income → scalar {interest_income_actual, nfi_actual,
    interest_expenses_actual, ...targets, ...gaps} (old target_tracker_nfi_expense_income).
    Frontend reads these exact keys for the Revenue Summary + Target Tracker."""
    with connection.cursor() as cur:
        cur.execute("""
            WITH updating_target AS (
                SELECT
                    3939000000 AS interest_expenses_target,
                    7279000000 AS interest_income_target,
                    703000000  AS nfi_target,
                    sum(sum_dc) FILTER ( WHERE income_category='interest_expenses' ) AS interest_expenses_actual,
                    sum(sum_dc) FILTER ( WHERE income_category='interest_income' )   AS interest_income_actual,
                    sum(sum_dc) FILTER ( WHERE income_category='nfi' )               AS nfi_actual,
                    extract(epoch FROM ( CURRENT_TIMESTAMP - date_trunc('year', now()) )) / 31556926 AS prorate
                FROM revenue
                WHERE date_trunc('year', tmstamp) = date_trunc('year', now())
            )
            SELECT
                interest_expenses_target, interest_income_target, nfi_target,
                interest_expenses_actual, interest_income_actual, nfi_actual,
                prorate * interest_income_target    AS ytd_interest_income_target,
                prorate * nfi_target                AS ytd_nfi_target,
                prorate * interest_expenses_target  AS ytd_interest_expenses_target,
                (-1*interest_expenses_actual) - (prorate * interest_expenses_target) AS interest_expenses_gap,
                interest_income_actual - (prorate * interest_income_target)          AS interest_income_gap,
                nfi_actual - (prorate * nfi_target)                                  AS nfi_actual_gap
            FROM updating_target
        """)
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
    return dict(zip(cols, row)) if row else {}


def _rows(sql):
    with connection.cursor() as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── Revenue movement (monthly + cumulative) ───────────────────────────────────
# income_category holds EXACT values 'interest_income' / 'interest_expenses' /
# 'nfi' — ILIKE '%INTEREST INCOME%' style patterns match NOTHING.

def _movement(category, value_alias, cum_alias, date_alias="date_months"):
    return _rows(f"""
        WITH data AS (
            SELECT date_trunc('months', tmstamp) AS {date_alias},
                   SUM(r.sum_dc) AS rev_sum
            FROM revenue r
            WHERE trx_date::date >= date_trunc('months', current_date - '12 months'::interval)
              AND r.income_category = '{category}'
            GROUP BY date_trunc('months', tmstamp)
            ORDER BY date_trunc('months', tmstamp)::date ASC
        )
        SELECT {date_alias},
               rev_sum AS {value_alias},
               SUM(rev_sum) OVER (ORDER BY {date_alias} ASC ROWS BETWEEN unbounded preceding AND CURRENT ROW) AS {cum_alias}
        FROM data
    """)


def intrest_income_movement():
    """intrest_income_movement → [{date_months, rev_sum, cumulative_revenue}]."""
    return _movement("interest_income", "rev_sum", "cumulative_revenue")


def nfi_income_movement():
    """nfi_income_movement → [{dates_months, rev_sum, cumulative_revenue}]
    (note the old dateS_months key — load-bearing)."""
    return _movement("nfi", "rev_sum", "cumulative_revenue", date_alias="dates_months")


def intrest_expense_income_movement():
    """intrest_expense_income_movement → [{date_months, intrest_expense, cumulative_intrest_expense}]."""
    return _movement("interest_expenses", "intrest_expense", "cumulative_intrest_expense")


def _movement_trend(category, value_alias):
    # Old *_trends variants: monthly sums only, current in-progress month excluded.
    return _rows(f"""
        SELECT date_trunc('months', tmstamp) AS date_months,
               SUM(r.sum_dc) AS {value_alias}
        FROM revenue r
        WHERE trx_date::date >= date_trunc('months', CURRENT_DATE - '12 months'::interval)
          AND date_trunc('months', tmstamp) != date_trunc('months', now())
          AND r.income_category = '{category}'
        GROUP BY date_trunc('months', tmstamp)
        ORDER BY date_trunc('months', tmstamp)::date ASC
    """)


def intrest_income_movement_trends():
    """intrest_income_movement_trends → [{date_months, sum_intrest_income}]."""
    return _movement_trend("interest_income", "sum_intrest_income")


def intrest_expense_income_movement_trends():
    """intrest_expense_income_movement_trends → [{date_months, sum_intrest_expense}]."""
    return _movement_trend("interest_expenses", "sum_intrest_expense")


def nfi_income_movement_trend():
    """nfi_income_movement_trend → [{date_months, sum_rev_nfi}]."""
    return _movement_trend("nfi", "sum_rev_nfi")


# ── Mobile loans + products per customer + new customer base ─────────────────

def mobile_loans():
    """mobile_loans → [{date_months, number_of_loans, total_disbused}] — last
    9 months of mobile_loan_disbusements, newest first (old mobile_loans)."""
    return _rows("""
        SELECT date_trunc('month', tmstamp::TIMESTAMP::date) AS date_months,
               count(distinct loan_account) AS number_of_loans,
               sum(instant_loan_amount) AS total_disbused
        FROM mobile_loan_disbusements
        WHERE tmstamp::TIMESTAMP::date >= (now() - INTERVAL '9' month)
        GROUP BY date_trunc('month', tmstamp::TIMESTAMP::date)
        ORDER BY date_trunc('month', tmstamp::TIMESTAMP::date) DESC
    """)


def product_per_customer_by_segment():
    """product_per_customer_by_segment → [{banking_segment, number_of_customers,
    number_of_products, ppc}] + a ROLLUP 'Total' row (old query verbatim)."""
    seg_case = """
        CASE
            WHEN hf.segment IN ('MASS', 'STANDARD') THEN 'PERSONAL BANKING'
            WHEN hf.segment IN ('PRIVATE', 'ULTIMATE') THEN 'ULTIMATE BANKING'
            WHEN hf.segment IN ('VIRTUAL') THEN 'VIRTUAL'
            WHEN hf.segment IN ('MEDIUM ENTERPRISES', 'SMALL ENTERPRISES') THEN 'SME'
            WHEN hf.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL BANKING'
            WHEN hf.segment IN ('INTERNAL ACCOUNTS') THEN 'INTERNAL ACCOUNTS'
            WHEN hf.segment IN ('INSTITUTIONAL BANKING') THEN 'INSTITUTIONAL BANKING'
            WHEN hf.segment IN ('FINANCIAL INSTITUTIONS') THEN 'FINANCIAL INSTITUTIONS'
            ELSE 'OTHERS'
        END
    """
    return _rows(f"""
        WITH data AS (
            SELECT {seg_case} AS banking_segment,
                   Count(DISTINCT hf.cust_id) AS number_of_customers,
                   Count(DISTINCT pn.account_number) AS number_of_products,
                   Count(DISTINCT pn.account_number) / Count(DISTINCT hf.cust_id) AS ppc
            FROM hf_customer hf
                 LEFT JOIN phone_number pn ON hf.cust_id = pn.cust_id
            GROUP BY {seg_case}
        )
        SELECT CASE WHEN Grouping(banking_segment) = 1 THEN 'Total'
                    ELSE banking_segment::text END AS banking_segment,
               sum(number_of_customers) AS number_of_customers,
               sum(number_of_products) AS number_of_products,
               (sum(number_of_products) / sum(number_of_customers)) AS ppc
        FROM data
        WHERE banking_segment NOT IN ('INTERNAL ACCOUNTS', 'OTHERS', 'PROJECT FINANCE')
        GROUP BY rollup (banking_segment)
    """)


def new_customer_base():
    """new_customer_base → per banking_segment MONTH-OVER-MONTH deltas keyed by
    date strings (old new_customer_base_api + new_customer_base_month_dates)."""
    rows = _rows("""
        SELECT banking_segment,
               jan - prev_dec AS jan,
               feb - jan AS feb,
               mar - feb AS mar,
               apr - mar AS apr,
               may - apr AS may,
               jun - may AS june,
               jul - jun AS july,
               aug - jul AS aug,
               sep - aug AS sept,
               oct - sep AS oct,
               nov - oct AS nov,
               dec - nov AS dec
        FROM ceo_customers_base_segment_report
    """)
    month_dates = {
        f"{current_year}-01-01": "jan",  f"{current_year}-02-01": "feb",
        f"{current_year}-03-01": "mar",  f"{current_year}-04-01": "apr",
        f"{current_year}-05-01": "may",  f"{current_year}-06-01": "june",
        f"{current_year}-07-01": "july", f"{current_year}-08-01": "aug",
        f"{current_year}-09-01": "sept", f"{current_year}-10-01": "oct",
        f"{current_year}-11-01": "nov",  f"{current_year}-12-01": "dec",
    }
    return [
        {"banking_segment": r["banking_segment"],
         **{date_key: r[field] for date_key, field in month_dates.items()}}
        for r in rows
    ]
