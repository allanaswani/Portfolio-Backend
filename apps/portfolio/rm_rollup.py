"""One-row-per-RM roll-up over hf_customer × retail_allocated_portfolio.

Every RM-list endpoint (CEO, EXCO, Branch Manager) used to build this join
inline, and all of them shared two defects that made the RM tables show
duplicate RMs and inflated money columns:

1. **Join fan-out.** ``retail_allocated_portfolio`` is an ETL-owned table with
   no unique constraint on ``cust_id``. When the ETL leaves more than one
   allocation row for a customer, ``hf_customer LEFT JOIN rap ON cust_id``
   emits that customer once per rap row, so the customer's deposits, loans and
   revenue are summed 2× / 3× / … We now collapse rap to the single latest
   allocation per ``cust_id`` before joining, so every customer is counted
   exactly once.

2. **Over-grouping.** The branch endpoint grouped by
   ``sales_code, rm_name, rap.branch``. An RM whose allocated customers carry
   several different ``rap.branch`` values (or several spellings/whitespace
   variants of the same name) was split into one table row per variant — which
   is why a single RM appeared five times under the same sales code and why
   "Total RMs" double-counted. The RM's identity is the sales code, so we group
   by the trimmed sales code alone and pick the most common name/branch label
   for display.

Customers with no allocation at all still appear (LEFT JOIN preserved) as a
single ``sales_code = NULL`` bucket, so the money columns keep reconciling to
the branch/organisation book instead of silently dropping unallocated balances.
Callers that count RMs must therefore skip rows with no sales_code and no
rm_name.
"""
from django.db import connection

# Branch-code → label map used by the Branch Manager RM list. Kept verbatim from
# the endpoint it was extracted out of so the displayed labels do not change.
_BRANCH_LABEL_CASE = """
    CASE
        WHEN a.cust_id IS NULL THEN NULL  -- unallocated bucket has no branch
        WHEN a.branch::text = '230' THEN 'BURUBURU BRANCH'
        WHEN a.branch::text = '410' THEN 'ELDORET BRANCH'
        WHEN a.branch::text = '25'  THEN 'EMBU BRANCH'
        WHEN a.branch::text = '220' THEN 'GILL HOUSE BRANCH'
        WHEN a.branch::text = '100' THEN 'HEAD OFFICE'
        WHEN a.branch::text = '109' THEN 'HF WHIZZ'
        WHEN a.branch::text = '19'  THEN 'HURLINGHAM BRANCH'
        WHEN a.branch::text = '600' THEN 'KISUMU BRANCH'
        WHEN a.branch::text = '16'  THEN 'KITENGELA BRANCH'
        WHEN a.branch::text = '23'  THEN 'KOMAROCK BRANCH'
        WHEN a.branch::text = '24'  THEN 'MACHAKOS BRANCH'
        WHEN a.branch::text = '520' THEN 'MERU BRANCH'
        WHEN a.branch::text = '300' THEN 'MOMBASA BRANCH'
        WHEN a.branch::text = '17'  THEN 'NAIVASHA BRANCH'
        WHEN a.branch::text = '400' THEN 'NAKURU BRANCH'
        WHEN a.branch::text = '22'  THEN 'NANYUKI BRANCH'
        WHEN a.branch::text = '510' THEN 'NYERI BRANCH'
        WHEN a.branch::text = '200' THEN 'REHANI BRANCH'
        WHEN a.branch::text = '20'  THEN 'RIVERROAD BRANCH'
        WHEN a.branch::text = '250' THEN 'RONGAI BRANCH'
        WHEN a.branch::text = '270' THEN 'SAMEER BUSINESS PARK BRANCH'
        WHEN a.branch::text = '500' THEN 'THIKA BRANCH'
        WHEN a.branch::text = '260' THEN 'THIKA ROAD MALL-TRM BRANCH'
        WHEN a.branch::text = '280' THEN 'WESTLANDS BRANCH'
        ELSE 'HEAD OFFICE'
    END
"""

# One allocation row per customer: the most recently updated one wins, with the
# physical row id as a stable tie-breaker when updated_at is null/equal.
_LATEST_ALLOCATION = """
    SELECT DISTINCT ON (cust_id)
        cust_id,
        NULLIF(BTRIM(sales_code::text), '') AS sales_code,
        NULLIF(BTRIM(rm_name), '')          AS rm_name,
        branch
    FROM retail_allocated_portfolio
    WHERE cust_id IS NOT NULL
    ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
"""

# Group key: the sales code identifies the RM. Rows that carry a name but no
# sales code fall back to the upper-cased name so they stay separate RMs rather
# than collapsing into the unallocated bucket.
_NAME_KEY = "CASE WHEN a.sales_code IS NULL THEN UPPER(a.rm_name) END"


def fetch_rm_rollup(branch=None, with_branch_label=False):
    """Return one row per RM: sales_code, rm_name, customers and the three
    money totals. ``branch`` filters hf_customer to a single branch book;
    ``with_branch_label`` adds the ``rm_branch`` display label."""
    branch_label = (
        f",\n                mode() WITHIN GROUP (ORDER BY {_BRANCH_LABEL_CASE.strip()}) AS rm_branch"
        if with_branch_label
        else ""
    )
    where = "WHERE c.branch = %s" if branch is not None else ""
    sql = f"""
        WITH alloc AS ({_LATEST_ALLOCATION})
        SELECT
            a.sales_code,
            mode() WITHIN GROUP (ORDER BY a.rm_name) AS rm_name,
            COUNT(*)                                 AS customers,
            SUM(c.total_revenue)                     AS total_revenue,
            SUM(c.total_depost_balance)              AS total_deposit_balance,
            SUM(c.total_loans)                       AS total_loans{branch_label}
        FROM hf_customer c
        LEFT JOIN alloc a ON c.cust_id = a.cust_id
        {where}
        GROUP BY a.sales_code, {_NAME_KEY}
        ORDER BY (a.sales_code IS NULL AND {_NAME_KEY} IS NULL),
                 total_deposit_balance DESC NULLS LAST
    """
    params = [branch] if branch is not None else []
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
