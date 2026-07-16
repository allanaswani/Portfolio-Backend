"""
Verbatim ports of the OLD backend's TL (segment) queries from core/core.py.

The frontend TL dashboard is built against these exact response shapes — the
per-account month-balance rows (mon_YY_bal columns), the `movement`/`dec_bal`
field names on the top-mover lists, and the `active_cusomers` typo on
customer_per_segment. Do not "fix" shapes here without changing the frontend.

TL scoping note: `profile.segment` holds a BANKING segment name (e.g.
'BUSINESS BANKING'), while daily/loan_balance_movement.customer_segment holds
raw core-banking segments ('MEDIUM ENTERPRISES', ...). Every query therefore
maps customer_segment through the CASE below before filtering — a raw
`customer_segment = %s` filter matches nothing.
"""
from django.db import connection

from core.date_utils import current_year, previous_year, year_before_last
from apps.portfolio.models import HfCustomer

cy = str(current_year)[-2:]
py = str(previous_year)[-2:]
ybl = str(year_before_last)[-2:]

# customer_segment -> banking_segment mapping used by the trend/movement queries
# (old core.py inlines this CASE; ULTIMATE maps from 'ULTIMATE' only here).
SEG_CASE = """
    case when customer_segment in ('FINANCIAL INSTITUTIONS', 'GLOBAL MARKETS') then 'FINANCIAL INSTITUTIONS'
         when customer_segment in ('INSTITUTIONAL BANKING', 'IB NON PUBLIC SECTOR') then 'INSTITUTIONAL BANKING'
         when customer_segment in ('INTERNAL ACCOUNTS') then 'INTERNAL ACCOUNTS'
         when customer_segment in ('PROJECT FINANCE') then 'PROJECT FINANCE'
         when customer_segment in ('SCHEME') then 'SCHEME'
         when customer_segment in ('VIRTUAL') then 'VIRTUAL'
         when customer_segment in ('STAFF') then 'STAFF'
         when customer_segment in ('DIASPORA', 'NON RESIDENT KENYANS') then 'DIASPORA'
         when customer_segment in ('MEDIUM ENTERPRISES', 'SMALL ENTERPRISES') then 'BUSINESS BANKING'
         when customer_segment in ('LARGE ENTERPRISES') then 'COMMERCIAL'
         when customer_segment in ('MASS', 'STANDARD') then 'PB'
         when customer_segment in ('ULTIMATE') then 'ULTIMATE'
         else 'New-Unsegmented' end
"""

# The monthly aggregate queries use a slightly different mapping ('PRIVATE'
# also maps to ULTIMATE) — kept verbatim from old core.py.
SEG_CASE_MONTHLY = SEG_CASE.replace("in ('ULTIMATE')", "in ('PRIVATE', 'ULTIMATE')")

# All month-end balance columns selected on the per-account trend rows.
_BAL_COLS = ", ".join(
    f"{c}::text"
    for c in (
        [f"dec_{ybl}_bal", f"mar_{py}_bal", f"jun_{py}_bal", f"sep_{py}_bal", f"dec_{py}_bal"]
        + [f"{m}_{cy}_bal" for m in ("jan", "feb", "mar", "apr", "may", "jun",
                                     "jul", "aug", "sep", "oct", "nov", "dec")]
    )
)

# Old top-mover yester fallback: when yesterday's balance is 0, substitute the
# last complete month's balance (verbatim CASE, incl. month=1 -> dec_CY).
def _yester_fallback(col: str) -> str:
    branches = "\n".join(
        f"when (sum({col}) = 0 and EXTRACT(month FROM current_date) = {month}) then sum({bal}_{cy}_bal)"
        for month, bal in ((2, "jan"), (3, "feb"), (4, "mar"), (5, "apr"), (6, "may"), (7, "jun"),
                           (8, "jul"), (9, "aug"), (10, "sep"), (11, "oct"), (12, "nov"), (1, "dec"))
    )
    return f"case\n{branches}\nelse sum({col}) end"


def _monthly_yester_fallback(col: str) -> str:
    branches = "\n".join(
        f"when (sum({col}) = 0 and EXTRACT(month FROM current_date) = {month}) "
        f"then sum({bal}_{cy}_bal) filter(WHERE {bal}_{cy}_bal > 0)"
        for month, bal in ((2, "jan"), (3, "feb"), (4, "mar"), (5, "apr"), (6, "may"), (7, "jun"),
                           (8, "jul"), (9, "aug"), (10, "sep"), (11, "oct"), (12, "nov"), (1, "dec"))
    )
    return f"case\n{branches}\nelse sum({col}) filter(WHERE {col} > 0) end"


_MONTHLY_SUMS = ",\n".join(
    f"sum(dbm.{c}) filter(WHERE dbm.{c} > 0) AS {c}"
    for c in (
        [f"dec_{ybl}_bal", f"mar_{py}_bal", f"jun_{py}_bal", f"sep_{py}_bal", f"dec_{py}_bal"]
        + [f"{m}_{cy}_bal" for m in ("jan", "feb", "mar", "apr", "may", "jun",
                                     "jul", "aug", "sep", "oct", "nov", "dec")]
    )
)


def _rows(sql, params):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── Customers (RawQuerySets for SegmentCustomerSerializer) ──────────────────

def segment_customers(banking_segment):
    """Old core.segment_customers — whole segment book with allocation columns."""
    return HfCustomer.objects.raw("""
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name,
                   total_revenue, total_depost_balance, total_loans, active,
                   ROW_NUMBER() OVER (PARTITION BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM hf_customer AS pn
                 LEFT OUTER JOIN retail_allocated_portfolio AS rap ON pn.cust_id = rap.cust_id
            WHERE trim(pn.banking_segment) = %s
        )
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    """, [banking_segment])


def segment_customers_allocated(banking_segment):
    """Old core.segment_customers_allocated."""
    return HfCustomer.objects.raw("""
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name,
                   total_revenue, total_depost_balance, total_loans, active,
                   ROW_NUMBER() OVER (PARTITION BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM retail_allocated_portfolio AS rap
                 LEFT OUTER JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE 1=1 and trim(pn.banking_segment) = %s
        )
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    """, [banking_segment])


def segment_customers_not_allocated(banking_segment):
    """Old core.segment_customers_not_allocated (customer_name from latin_surname)."""
    return HfCustomer.objects.raw("""
        WITH retail_allocation AS (
            SELECT pn.cust_id, latin_surname as customer_name, sales_code, rm_name,
                   total_revenue, total_depost_balance, total_loans, active,
                   ROW_NUMBER() OVER (PARTITION BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM retail_allocated_portfolio AS rap
                 RIGHT JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE 1=1 and rap.cust_id is null and trim(pn.banking_segment) = %s
        )
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    """, [banking_segment])


def segment_customer_per_segment(segment):
    """Old core.segment_customer_per_segment — NOTE the `active_cusomers` key
    (typo) is what the old API returned and what the frontend reads."""
    main_seg_case = """
        CASE
            WHEN hf_customer.segment IN ('FINANCIAL INSTITUTIONS','INSTITUTIONAL BANKING',
                                         'INTERNAL ACCOUNTS','PROJECT FINANCE','SCHEME') THEN 'banking'
            WHEN hf_customer.segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES') THEN 'BUSINESS BANKING'
            WHEN hf_customer.segment IN ('PRIVATE','ULTIMATE') THEN 'ULTIMATE'
            WHEN hf_customer.segment IN ('MASS','STANDARD') THEN 'PB'
            WHEN hf_customer.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL'
            ELSE 'others'
        END
    """
    seg_case = "CASE WHEN hf_customer.segment IS NULL THEN 'unsegmented' ELSE hf_customer.segment END"
    rows = _rows(f"""
        SELECT banking_segment,
               {main_seg_case} AS main_segment,
               {seg_case} AS segment,
               COUNT(DISTINCT a.cust_id) AS total_customers,
               COUNT(DISTINCT hf_customer.cust_id) FILTER (WHERE hf_customer.active = TRUE) AS active_customers
        FROM hf_customer
        LEFT JOIN retail_allocated_portfolio rap ON hf_customer.cust_id = rap.cust_id
        INNER JOIN accounts a ON hf_customer.cust_id = a.cust_id
        WHERE 1 = 1 and banking_segment = %s
        GROUP BY banking_segment, {main_seg_case}, {seg_case}
    """, [segment])
    return [{
        "banking_segment": r["banking_segment"],
        "main_segment": r["main_segment"],
        "segment": r["segment"],
        "total_customers": r["total_customers"],
        "active_cusomers": r["active_customers"],   # old API typo — load-bearing
    } for r in rows]


# ── Trends (per-account month-balance rows) ─────────────────────────────────

def segment_deposit_trends(segment):
    """Old core.segment_deposit_trends_data — per-account deposit rows with
    every month-end balance column, filtered on the mapped banking segment."""
    return _rows(f"""
        with data as (
            SELECT daily_balance_movement.id::text, cust_cif::text, acc_num::text, brn_code::text,
                   prod_id::text, customer_segment::text, financial_sector::text,
                   activity_sector::text, segment_code::text,
                   {_BAL_COLS},
                   yester_2_bal::text, yester_1_bal::text, rm_code::text, diaspora_check::text,
                   open_date::text, sale_code::text, full_name::text,
                   {SEG_CASE} as banking_segment,
                   rap.rm_name
            FROM daily_balance_movement
            left join retail_allocated_portfolio rap ON rap.cust_id = daily_balance_movement.cust_cif
        )
        select * from data WHERE 1=1 and banking_segment = %s
    """, [segment])


def segment_loan_trends(segment):
    """Old core.segment_loan_trends_data_queryset — per-account loan rows
    (no segment_code column / rap join on the loan table)."""
    return _rows(f"""
        with data as (
            SELECT id::text, cust_cif::text, acc_num::text, brn_code::text, prod_id::text,
                   customer_segment::text, financial_sector::text, activity_sector::text,
                   {_BAL_COLS},
                   yester_2_bal::text, yester_1_bal::text, rm_code::text, diaspora_check::text,
                   open_date::text, sale_code::text, full_name::text,
                   {SEG_CASE} as banking_segment
            FROM loan_daily_balance_movement
        )
        select * from data WHERE banking_segment = %s
    """, [segment])


def segment_monthly_deposit_trends(segment):
    """Old core.segment_monthly_deposit_trends_data — one aggregated row for
    the segment: month sums + yester_1/2 (with month fallback)."""
    return _rows(f"""
        with data as (
            SELECT 1 AS id,
                   {_MONTHLY_SUMS},
                   {_monthly_yester_fallback('yester_2_bal')} as yester_2_bal,
                   {_monthly_yester_fallback('yester_1_bal')} as yester_1_bal,
                   {SEG_CASE_MONTHLY} as banking_segment
            FROM daily_balance_movement dbm
            GROUP BY {SEG_CASE_MONTHLY}
        )
        select * from data where banking_segment = %s
    """, [segment])


def segment_monthly_loan_trends(segment):
    """Old core.segment_monthly_loan_trends_data — same aggregate on the loan table."""
    return _rows(f"""
        with data as (
            SELECT 1 AS id,
                   {_MONTHLY_SUMS},
                   {_monthly_yester_fallback('yester_2_bal')} as yester_2_bal,
                   {_monthly_yester_fallback('yester_1_bal')} as yester_1_bal,
                   {SEG_CASE_MONTHLY} as banking_segment
            FROM loan_daily_balance_movement dbm
            GROUP BY {SEG_CASE_MONTHLY}
        )
        select * from data where banking_segment = %s
    """, [segment])


# ── Movements ────────────────────────────────────────────────────────────────

def segment_rm_deposit_movement_ytd(segment):
    """Old core.segment_rm_deposit_movement_ytd_data — per-RM YTD movement:
    {rm_code, rm_name, dec_bal, yester_1_bal, movement, banking_segment}."""
    return _rows(f"""
        with data as (
            select trim(rm_code) as rm_code,
                   rap.rm_name,
                   sum(dec_{py}_bal) as dec_bal,
                   sum(yester_1_bal) as yester_1_bal,
                   sum(yester_1_bal - dec_{py}_bal) as movement,
                   {SEG_CASE} as banking_segment
            from daily_balance_movement dbm
            left join retail_allocated_portfolio rap on dbm.cust_cif = rap.cust_id
            group by trim(rm_code), rap.rm_name, {SEG_CASE}
            order by sum(yester_1_bal - dec_{py}_bal) desc
        )
        select * from data where banking_segment = %s
    """, [segment])


def _top_dtd(segment, order):
    # ::bigint (not old ::int) — day movements can exceed the int4 range,
    # which 500s the old backend; same hotfix as the branch inflow/outflow.
    return _rows(f"""
        with data as (
            select dbm.cust_cif,
                   dbm.full_name,
                   rap.rm_name,
                   {_yester_fallback('yester_2_bal')} as yester_2_bal,
                   {_yester_fallback('yester_1_bal')} as yester_1_bal,
                   {SEG_CASE} as banking_segment
            from daily_balance_movement dbm
                 left join retail_allocated_portfolio rap on dbm.cust_cif = rap.cust_id
            where 1=1
            group by dbm.cust_cif, dbm.full_name, rap.rm_name, {SEG_CASE}
        )
        select cust_cif, full_name, rm_name, yester_2_bal, yester_1_bal,
               yester_1_bal - yester_2_bal as movement, banking_segment
        from data
        where banking_segment = %s
        order by (yester_1_bal - yester_2_bal)::bigint {order}
        limit 10
    """, [segment])


def segment_top_inflow_dtd(segment):
    return _top_dtd(segment, "desc")


def segment_top_outflow_dtd(segment):
    return _top_dtd(segment, "asc")


def _top_ytd(segment, order):
    return _rows(f"""
        with data as (
            select dbm.cust_cif,
                   dbm.full_name,
                   rap.rm_name,
                   sum(dec_{py}_bal) as dec_bal,
                   sum(yester_1_bal) as yester_1_bal,
                   sum(yester_1_bal - dec_{py}_bal) as movement,
                   {SEG_CASE} as banking_segment
            from daily_balance_movement dbm
            left join retail_allocated_portfolio rap on dbm.cust_cif = rap.cust_id
            where 1=1
            group by dbm.cust_cif, dbm.full_name, rap.rm_name, {SEG_CASE}
            order by sum(yester_1_bal - dec_{py}_bal) {order}
        )
        select * from data where banking_segment = %s
        limit 10
    """, [segment])


def segment_top_inflow_ytd(segment):
    return _top_ytd(segment, "desc")


def segment_top_outflow_ytd(segment):
    return _top_ytd(segment, "asc")
