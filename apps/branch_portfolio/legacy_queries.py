"""Verbatim ports of the OLD backend's branch customer raw-SQL queries.

The redesigned frontend targets the OLD backend's exact response shapes, so these
reproduce the old `core.core` query functions 1:1 (same SQL, same output columns).
They run against the same physical tables (hf_customer, retail_allocated_portfolio,
revenue), so the SQL is copied unchanged. See apps/branch_portfolio/views.py for the
views that consume them and serialize with SegmentCustomerSerializer.
"""
from django.db import connection

from apps.portfolio.models import HfCustomer, RetailAllocatedPortfolio
from apps.gceo_dashboard.models import Revenue


def branch_new_customers_ytd(branch):
    """Count of a branch's customers who OPENED an account this year →
    {branch, new_customers}. Verbatim port of old core.branch_new_customers_ytd
    (accounts + customers.open_date; NOT hf_customer.date_time_created, which the
    view previously used and got wrong counts / zeros)."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT current_branch AS branch,
                   COUNT(DISTINCT hc.cust_id) AS new_customers
            FROM accounts a
            LEFT JOIN hf_customer hc ON a.cust_id = hc.cust_id
            LEFT JOIN customers c ON a.cust_id = c.cust_id
            WHERE current_branch = %s
              AND date_trunc('year', c.open_date) = date_trunc('year', now())
            GROUP BY current_branch
            """,
            [branch],
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows[0] if rows else {"branch": branch, "new_customers": 0}


def branch_customers(branch):
    """All customers whose hf_customer.branch matches EXACTLY (old: customer_list)."""
    return HfCustomer.objects.raw('''
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name, total_revenue,
                   total_depost_balance, total_loans, active,
                   Row_number() OVER (partition BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM   hf_customer AS pn
                   LEFT OUTER JOIN (
                       SELECT DISTINCT ON (cust_id) *
                       FROM retail_allocated_portfolio
                       WHERE cust_id IS NOT NULL
                       ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
                   ) rap ON pn.cust_id = rap.cust_id
            WHERE  pn.branch = %s)
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    ''', [branch])


def branch_customers_allocated(branch):
    """Customers allocated to an RM in the branch (old: branch_customers_allocated)."""
    branch_pattern = f"%{branch.strip()}%"
    return HfCustomer.objects.raw('''
        WITH retail_allocation AS (
            SELECT pn.cust_id, customer_name, sales_code, rm_name, total_revenue,
                   total_depost_balance, total_loans, active,
                   Row_number() OVER (partition BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM   retail_allocated_portfolio AS rap
                   LEFT OUTER JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE  1=1 AND lower(trim(pn.branch)) LIKE lower(trim(%s)))
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    ''', [branch_pattern])


def branch_customers_not_allocated(branch):
    """Branch customers NOT allocated to any RM (old: branch_customers_not_allocated)."""
    branch_pattern = f"%{branch.strip()}%"
    return HfCustomer.objects.raw('''
        WITH retail_allocation AS (
            SELECT pn.cust_id, latin_surname as customer_name, sales_code, rm_name,
                   total_revenue, total_depost_balance, total_loans, active,
                   Row_number() OVER (partition BY pn.cust_id ORDER BY pn.cust_id ASC) AS rn
            FROM   retail_allocated_portfolio AS rap
                   RIGHT JOIN hf_customer AS pn ON pn.cust_id = rap.cust_id
            WHERE  1=1 AND rap.cust_id is null AND lower(trim(pn.branch)) LIKE lower(trim(%s)))
        SELECT cust_id AS id, * FROM retail_allocation WHERE rn = 1
        ORDER BY total_depost_balance DESC, total_loans DESC
    ''', [branch_pattern])


def branch_customer_per_segment(branch):
    """Customers grouped by banking/main/segment with total & active counts
    (old: branch_customer_per_segment). Rows carry: banking_segment, main_segment,
    segment, total_customers, active_customers."""
    return RetailAllocatedPortfolio.objects.raw('''
        SELECT 1 AS id, banking_segment,
            CASE
                WHEN hf_customer.segment IN ('FINANCIAL INSTITUTIONS','INSTITUTIONAL BANKING','INTERNAL ACCOUNTS','PROJECT FINANCE','SCHEME') THEN 'banking'
                WHEN hf_customer.segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES') THEN 'BUSINESS BANKING'
                WHEN hf_customer.segment IN ('PRIVATE', 'ULTIMATE') THEN 'ULTIMATE'
                WHEN hf_customer.segment IN ('MASS', 'STANDARD') THEN 'PB'
                WHEN hf_customer.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL'
                ELSE 'others'
            END AS main_segment,
            CASE WHEN hf_customer.segment IS NULL THEN 'unsegmented' ELSE hf_customer.segment END AS segment,
            COUNT(DISTINCT hf_customer.cust_id) AS total_customers,
            COUNT(DISTINCT hf_customer.cust_id) FILTER (WHERE hf_customer.active = TRUE) AS active_customers
        FROM hf_customer
        LEFT JOIN (
            SELECT DISTINCT ON (cust_id) *
            FROM retail_allocated_portfolio
            WHERE cust_id IS NOT NULL
            ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
        ) rap ON hf_customer.cust_id = rap.cust_id
        WHERE 1 = 1 AND hf_customer.branch = %s
        GROUP BY banking_segment,
            CASE
                WHEN hf_customer.segment IN ('FINANCIAL INSTITUTIONS','INSTITUTIONAL BANKING','INTERNAL ACCOUNTS','PROJECT FINANCE','SCHEME') THEN 'banking'
                WHEN hf_customer.segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES') THEN 'BUSINESS BANKING'
                WHEN hf_customer.segment IN ('PRIVATE', 'ULTIMATE') THEN 'ULTIMATE'
                WHEN hf_customer.segment IN ('MASS', 'STANDARD') THEN 'PB'
                WHEN hf_customer.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL'
                ELSE 'others'
            END,
            CASE WHEN hf_customer.segment IS NULL THEN 'unsegmented' ELSE hf_customer.segment END
    ''', [branch])


def branch_revenues_query(branch):
    """YTD revenue by income category for the branch (old: branch_revenues_query).
    Rows carry: income_category, value."""
    return Revenue.objects.raw('''
        SELECT 1 as id, income_category, sum(sum_dc) as value
        FROM revenue r
            LEFT JOIN hf_customer hf ON hf.cust_id = r.cust_id
        WHERE date_trunc('year',tmstamp) = date_trunc('year',now())
            AND branch = %s
        GROUP BY income_category
    ''', [branch])


# ── Customer activity: who has transacted, and who has stopped ───────────────
#
# A branch could see how many customers it has and what they hold, but not
# whether any of them are still using the bank. "Active" on ``hf_customer`` is
# a flag somebody else sets; it is not a transaction date, and it cannot answer
# "who has not come near us since March".
#
# These read ``transaction_diary`` - the bank's own transaction history, the
# same table the CEO dashboard's digital-activity tiles and the scorecard's
# Active Customers line read - and reduce it to ONE number per customer: the
# most recent transaction. Everything on the screen is derived from that:
#
#   active in the last N days   last transaction within N days
#   inactive                    last transaction older than N days, OR none at
#                               all inside the lookback
#
# The windows NEST. A customer active in the last 7 days is also in the 30, 60
# and 90 day counts; they are four answers to "how recently", not four buckets
# that add up to the book. The screen says so, because a column of numbers that
# looks like a breakdown and is not is how a branch ends up double-counting its
# own customers.
#
# **Branch-scoped only, deliberately.** There is no all-branch form of these.
# ``transaction_diary`` is the whole bank's transaction history and an
# unscoped version of this query is a table scan nobody asked for; the views
# refuse a call that does not resolve to one branch rather than quietly
# running it. See ``_require_one_branch`` in views.py.

#: The windows the screen reports. Nested, not exclusive - see above.
ACTIVITY_WINDOWS = (7, 30, 60, 90)

#: How far back to look for a last transaction when deciding dormancy. A
#: customer with nothing in this window is reported as "no transaction in the
#: last N days" rather than as a date nobody has, because the alternative is
#: scanning the whole of transaction_diary to date a customer who left in 2019.
DEFAULT_LOOKBACK_DAYS = 365

#: The branch's own book. ``cust_id`` is cast to bigint because hf_customer
#: holds it as an unconstrained numeric and transaction_diary holds it as an
#: integer - comparing the two without the cast works but will not use the
#: index on fk_customercust_id, which is the difference between this returning
#: and this timing out.
#:
#: retail_allocated_portfolio is deduped with DISTINCT ON before it is joined.
#: That table has no unique cust_id, and joining it raw multiplies a customer
#: by however many rows it holds for them - the fan-out this codebase has
#: already shipped once on the RM list.
_BOOK_SQL = """
    SELECT hc.cust_id::bigint AS cust_id,
           COALESCE(NULLIF(TRIM(rap.customer_name), ''),
                    NULLIF(TRIM(hc.latin_surname), ''), '') AS customer_name,
           hc.segment,
           hc.banking_segment,
           hc.total_depost_balance,
           hc.total_loans,
           hc.total_revenue,
           COALESCE(rap.rm_name, '') AS rm_name,
           COALESCE(rap.sales_code, '') AS sales_code
    FROM hf_customer hc
    LEFT JOIN (
        SELECT DISTINCT ON (cust_id) cust_id, rm_name, sales_code, customer_name
        FROM retail_allocated_portfolio
        WHERE cust_id IS NOT NULL
        ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
    ) rap ON rap.cust_id = hc.cust_id
    WHERE lower(trim(hc.branch)) = lower(trim(%(branch)s))
      AND hc.cust_id IS NOT NULL
"""

#: One row per customer who has transacted inside the lookback, carrying their
#: most recent transaction. Bounded by the lookback on purpose: transaction
#: history is the largest table in the estate and MAX() over all of it, per
#: customer, is not something a page view can ask for.
_LAST_TXN_SQL = """
    SELECT t.fk_customercust_id AS cust_id, MAX(t.tmstamp) AS last_txn
    FROM transaction_diary t
    JOIN book b ON b.cust_id = t.fk_customercust_id
    WHERE t.tmstamp >= now() - (%(lookback)s * INTERVAL '1 day')
      AND t.fk_customercust_id IS NOT NULL
    GROUP BY t.fk_customercust_id
"""


def _rows(sql, params):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _clean_window(days):
    """A window the screen offers, or the 30-day default.

    Not free-form: the number goes into an interval, and the four windows are
    what the tables are built around.
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 30
    return days if days in ACTIVITY_WINDOWS else 30


def _clean_lookback(days):
    try:
        days = int(days)
    except (TypeError, ValueError):
        return DEFAULT_LOOKBACK_DAYS
    # Floored at the widest window so "inactive" always means "outside the 90
    # day window", and capped so one query cannot be asked to read five years
    # of transactions for a whole branch.
    return max(max(ACTIVITY_WINDOWS), min(days, 1825))


def branch_customer_activity(branch, lookback=None):
    """The summary table: how many of the branch's customers are still active.

    → one dict carrying the branch's total book, the four nested active counts,
    the inactive count, and the dormancy spread of the inactive.

    The dormancy buckets ARE exclusive and do add up to the inactive count -
    unlike the windows above them, which nest. Both are on the same payload, so
    this says which is which rather than leaving the screen to guess.
    """
    lookback = _clean_lookback(lookback)
    sql = f"""
        WITH book AS ({_BOOK_SQL}),
        last_txn AS ({_LAST_TXN_SQL}),
        scored AS (
            SELECT b.cust_id, l.last_txn,
                   CASE WHEN l.last_txn IS NULL THEN NULL
                        ELSE (now()::date - l.last_txn::date) END AS days_since
            FROM book b
            LEFT JOIN last_txn l ON l.cust_id = b.cust_id
        )
        SELECT COUNT(*) AS customers,
               COUNT(*) FILTER (WHERE days_since <= 7)  AS active_7,
               COUNT(*) FILTER (WHERE days_since <= 30) AS active_30,
               COUNT(*) FILTER (WHERE days_since <= 60) AS active_60,
               COUNT(*) FILTER (WHERE days_since <= 90) AS active_90,
               COUNT(*) FILTER (WHERE days_since IS NULL OR days_since > 90)
                   AS inactive_90,
               COUNT(*) FILTER (WHERE days_since > 90 AND days_since <= 180)
                   AS dormant_91_180,
               COUNT(*) FILTER (WHERE days_since > 180 AND days_since <= 365)
                   AS dormant_181_365,
               COUNT(*) FILTER (WHERE days_since > 365) AS dormant_over_365,
               COUNT(*) FILTER (WHERE days_since IS NULL) AS never_in_lookback,
               MAX(last_txn) AS most_recent_transaction
        FROM scored
    """
    rows = _rows(sql, {"branch": branch, "lookback": lookback})
    row = rows[0] if rows else {}

    customers = row.get("customers") or 0
    windows = [{
        "days": days,
        "label": f"Last {days} days",
        "customers": row.get(f"active_{days}") or 0,
        "share": round((row.get(f"active_{days}") or 0) / customers * 100, 1)
        if customers else 0.0,
    } for days in ACTIVITY_WINDOWS]

    inactive = row.get("inactive_90") or 0
    buckets = [
        ("91-180 days", row.get("dormant_91_180") or 0),
        ("181-365 days", row.get("dormant_181_365") or 0),
        ("Over 365 days", row.get("dormant_over_365") or 0),
        (f"No transaction in {lookback} days", row.get("never_in_lookback") or 0),
    ]
    last_seen = row.get("most_recent_transaction")
    return {
        "branch": branch,
        "lookback_days": lookback,
        "customers": customers,
        # Four answers to "how recently", so they NEST. The screen must not
        # present them as a breakdown.
        "windows": windows,
        "windows_are_cumulative": True,
        "inactive": inactive,
        "inactive_share": round(inactive / customers * 100, 1) if customers else 0.0,
        # These are exclusive and sum to `inactive`.
        "dormancy": [{"label": label, "customers": count,
                      "share": round(count / inactive * 100, 1) if inactive else 0.0}
                     for label, count in buckets],
        "most_recent_transaction": last_seen.isoformat() if last_seen else None,
    }


def branch_customer_activity_page(branch, state="active", days=30, lookback=None,
                                  search="", limit=50, offset=0):
    """A page of the branch's customers with their last transaction.

    ``state="active"``   transacted within ``days``, most recent first.
    ``state="inactive"`` did not, longest silent first - which puts the
                         customers who have never appeared inside the lookback
                         at the top, where the branch wants them.

    → ``(rows, total)``. The total comes back on the rows themselves with a
    window function rather than from a second execution of the same CTEs: the
    heavy part of this query is the transaction scan, and running it twice to
    paginate it would double the cost of every page.
    """
    days = _clean_window(days)
    active = str(state or "active").strip().lower() != "inactive"
    # An active list never needs to look further back than its own window; an
    # inactive one has to look far enough to date the dormancy.
    lookback = days if active else _clean_lookback(lookback)

    predicate = ("s.days_since <= %(days)s" if active else
                 "(s.days_since IS NULL OR s.days_since > %(days)s)")
    order = "s.last_txn DESC" if active else "s.last_txn ASC NULLS FIRST"

    params = {"branch": branch, "lookback": lookback, "days": days,
              "limit": max(1, int(limit)), "offset": max(0, int(offset))}

    term = (search or "").strip()
    search_clause = ""
    if term:
        params["search"] = f"%{term.lower()}%"
        search_clause = """
          AND (lower(s.customer_name) LIKE %(search)s
               OR lower(s.rm_name) LIKE %(search)s
               OR s.cust_id::text LIKE %(search)s)
        """

    sql = f"""
        WITH book AS ({_BOOK_SQL}),
        last_txn AS ({_LAST_TXN_SQL}),
        scored AS (
            SELECT b.*, l.last_txn,
                   CASE WHEN l.last_txn IS NULL THEN NULL
                        ELSE (now()::date - l.last_txn::date) END AS days_since
            FROM book b
            LEFT JOIN last_txn l ON l.cust_id = b.cust_id
        )
        SELECT s.cust_id, s.customer_name, s.segment, s.banking_segment,
               s.rm_name, s.sales_code,
               s.total_depost_balance, s.total_loans, s.total_revenue,
               s.last_txn, s.days_since,
               COUNT(*) OVER () AS total_rows
        FROM scored s
        WHERE {predicate}{search_clause}
        ORDER BY {order}, s.total_depost_balance DESC NULLS LAST
        LIMIT %(limit)s OFFSET %(offset)s
    """
    rows = _rows(sql, params)
    total = rows[0]["total_rows"] if rows else 0
    for row in rows:
        row.pop("total_rows", None)
        last = row.get("last_txn")
        row["last_txn"] = last.isoformat() if last else None
        for money in ("total_depost_balance", "total_loans", "total_revenue"):
            row[money] = float(row[money]) if row[money] is not None else 0.0
    return rows, total
