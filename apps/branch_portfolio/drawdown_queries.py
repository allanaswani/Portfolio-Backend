"""Branch-scoped reads over ``drawdown_daily``.

``drawdown_daily`` is the warehouse table the Drawdowns screen already renders
(``staff_management/drawdown-daily/``). It has NO branch column — the only
branch dimension on it is ``unit_code``, which the existing screen labels
"Branch". Scoping it to one branch therefore means resolving the branch NAME to
its set of unit codes first (``core.branch_codes``) and filtering on those.

Every function takes ``codes``:

* ``None``  — no branch restriction (EXCO/CEO all-branch roll-up only);
* ``[]``    — the branch could not be resolved to any code, so match NOTHING.
              Never let this degrade into "no filter"; that would hand one
              branch manager the whole bank's drawdowns.
* ``[…]``   — restrict to those unit codes.

The aggregates are computed in the database, not summed in the browser, so the
KPI tiles are right regardless of how many rows the table page happens to hold.
"""

from django.db import connection

TABLE = "drawdown_daily"

# Columns the branch drawdowns table renders. Kept explicit rather than SELECT *
# so a warehouse column added upstream cannot change the response shape.
LIST_COLUMNS = (
    "id",
    "drawdown_dt",
    "account_number",
    "cust_id",
    "customer_name",
    "salesperson",
    "product_desc",
    "loan_officer_id",
    "loan_officer_name",
    "final_interest",
    "loan_term_months",
    "unit_code",
    "net_drawdown",
    "gross_drawdown",
    "customer_segment",
    "description",
    "financial_sector",
    "activity_sector",
    "diaspora_check",
)

_SEARCH_COLUMNS = (
    "customer_name",
    "salesperson",
    "loan_officer_name",
    "product_desc",
    "customer_segment",
    "account_number::text",
    "cust_id::text",
)


def _scope(codes, date_from=None, date_to=None, search=None):
    """WHERE fragment + params for the branch/date/search scope."""
    clauses, params = [], []

    if codes is None:
        clauses.append("TRUE")
    elif not codes:
        # Unresolvable branch — match nothing. See the module docstring.
        clauses.append("FALSE")
    else:
        clauses.append("unit_code = ANY(%s)")
        params.append([int(c) for c in codes])

    if date_from:
        clauses.append("drawdown_dt >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("drawdown_dt <= %s")
        params.append(date_to)

    term = (search or "").strip()
    if term:
        ors = " OR ".join(f"{col} ILIKE %s" for col in _SEARCH_COLUMNS)
        clauses.append(f"({ors})")
        params.extend([f"%{term}%"] * len(_SEARCH_COLUMNS))

    return " AND ".join(clauses), params


def _rows(sql, params):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def summary(codes, date_from=None, date_to=None):
    """KPI tiles for the branch: volume, value, MTD and YTD — all DB-side."""
    where, params = _scope(codes, date_from, date_to)
    sql = f"""
        SELECT
            COUNT(*)                                              AS drawdown_count,
            COUNT(DISTINCT cust_id)                               AS customers,
            COALESCE(SUM(gross_drawdown), 0)                      AS gross_value,
            COALESCE(SUM(net_drawdown), 0)                        AS net_value,
            COALESCE(AVG(gross_drawdown), 0)                      AS average_value,
            COUNT(*) FILTER (
                WHERE date_trunc('month', drawdown_dt) = date_trunc('month', current_date)
            )                                                     AS mtd_count,
            COALESCE(SUM(gross_drawdown) FILTER (
                WHERE date_trunc('month', drawdown_dt) = date_trunc('month', current_date)
            ), 0)                                                 AS mtd_gross_value,
            COUNT(*) FILTER (
                WHERE date_trunc('year', drawdown_dt) = date_trunc('year', current_date)
            )                                                     AS ytd_count,
            COALESCE(SUM(gross_drawdown) FILTER (
                WHERE date_trunc('year', drawdown_dt) = date_trunc('year', current_date)
            ), 0)                                                 AS ytd_gross_value,
            MIN(drawdown_dt)                                      AS first_drawdown,
            MAX(drawdown_dt)                                      AS last_drawdown
        FROM {TABLE}
        WHERE {where}
    """
    rows = _rows(sql, params)
    return rows[0] if rows else {}


def page(codes, date_from=None, date_to=None, search=None, limit=10, offset=0):
    """One page of drawdowns plus the total row count for the same scope.

    Server-side paging: the branch drawdown book is far too big to hand the
    browser in one array, and a client-side cap would silently under-count.
    """
    where, params = _scope(codes, date_from, date_to, search)

    with connection.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}", params)
        total = cur.fetchone()[0] or 0

    cols = ", ".join(LIST_COLUMNS)
    sql = f"""
        SELECT {cols}
        FROM {TABLE}
        WHERE {where}
        ORDER BY drawdown_dt DESC, id DESC
        LIMIT %s OFFSET %s
    """
    rows = _rows(sql, params + [int(limit), int(offset)])
    return rows, total


def by_product(codes, date_from=None, date_to=None, limit=25):
    where, params = _scope(codes, date_from, date_to)
    sql = f"""
        SELECT
            COALESCE(NULLIF(btrim(product_desc), ''), 'Unclassified') AS product_desc,
            COUNT(*)                          AS drawdown_count,
            COALESCE(SUM(gross_drawdown), 0)  AS gross_value,
            COALESCE(SUM(net_drawdown), 0)    AS net_value
        FROM {TABLE}
        WHERE {where}
        GROUP BY 1
        ORDER BY gross_value DESC
        LIMIT %s
    """
    return _rows(sql, params + [int(limit)])


def by_seller(codes, date_from=None, date_to=None, limit=50):
    """Who wrote the business — the branch manager's main use for this screen."""
    where, params = _scope(codes, date_from, date_to)
    sql = f"""
        SELECT
            COALESCE(NULLIF(btrim(salesperson), ''), 'Unassigned') AS salesperson,
            COUNT(*)                          AS drawdown_count,
            COUNT(DISTINCT cust_id)           AS customers,
            COALESCE(SUM(gross_drawdown), 0)  AS gross_value,
            COALESCE(SUM(net_drawdown), 0)    AS net_value
        FROM {TABLE}
        WHERE {where}
        GROUP BY 1
        ORDER BY gross_value DESC
        LIMIT %s
    """
    return _rows(sql, params + [int(limit)])


def monthly(codes, months=24):
    """Drawdown trend for the last ``months`` calendar months."""
    where, params = _scope(codes)
    sql = f"""
        SELECT
            to_char(date_trunc('month', drawdown_dt), 'YYYY-MM') AS period,
            COUNT(*)                          AS drawdown_count,
            COALESCE(SUM(gross_drawdown), 0)  AS gross_value,
            COALESCE(SUM(net_drawdown), 0)    AS net_value
        FROM {TABLE}
        WHERE {where}
          AND drawdown_dt >= date_trunc('month', current_date) - make_interval(months => %s)
        GROUP BY 1
        ORDER BY 1
    """
    return _rows(sql, params + [int(months) - 1])
