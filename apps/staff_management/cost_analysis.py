"""Operating costs by department, by branch and by expense line.

What this replaces
──────────────────
The CEO deck's cost section was two hard-coded constants in
``app/(dashboard)/gceo/page.tsx``: eighteen departments by nine months, and ten
expense lines. Stale, with no branch split, and April read 10,670 for ICT —
which is a part-month of postings presented as a month.

The cost data was never missing. ``delta.gold_db.sap_cost_data`` holds SAP
document postings with a cost centre and a GL account on every line. What was
missing were the two mappings that turn a posting into a department figure, and
both now exist: :class:`SapCostCentre` (migration 0034) and
``operating_expense_mapping`` (migration 0023, 249 GL accounts, which nothing
was reading for this).

The rules are the Finance team's, not mine
──────────────────────────────────────────
Every rule below is lifted from ``cost_analysis_sap_report.ipynb`` and is
quoted where it is applied, because each one changes the answer:

1. **A credit is negative.** ``amount`` is ``lcy_amount`` negated when the
   debit/credit indicator is ``H``. Without it, credits ADD to a cost instead
   of reducing it, and every total is out by twice the credits.
2. **The date is not on the posting.** It comes from ``assignment_number`` as
   YYYYMMDD, falling back to ``reference_document_number``. Neither is
   reliably populated alone.
3. **An operating expense is a 7-series GL, minus three.** Loan loss charges,
   lease liability interest and interest adjustments sit on 7-series accounts
   and are not operating expenses — see :class:`SapCostExclusion`.
4. **It must also have a GL mapping row** whose ``operating_expense`` is set.
   The notebook's ``operating_expenses()`` overwrites that to
   ``non_operating expense`` for anything off the 7-series and then filters it
   out.
5. **An unmapped cost centre is dropped, not bucketed.** So is BRANCH GROWTH,
   which is a holding cost centre rather than a place. A cost with nowhere to
   go must not quietly land in a department that did not spend it.

Why these are SQL aggregates
────────────────────────────
The posting table is at document-ITEM grain — the whole point, so a department
total can be broken down to the postings behind it. That is hundreds of
thousands of rows for two fiscal years, so the summaries group in the database
rather than pulling rows into Python the way the notebook does.
"""

from __future__ import annotations

import datetime

#: The notebook's own first-digit GL classification. Kept whole rather than
#: trimmed to the 7-series, because the data-quality view wants to show what
#: the other digits are carrying.
GL_TYPES = {
    "1": "assets",
    "2": "liabilities",
    "3": "capital reserves",
    "4": "interest income",
    "5": "nfi",
    "6": "interest expense",
    "7": "other expenses",
    "8": "off balance sheet items",
}

#: Cost centre names the report drops. "unmapped" is the absence of a mapping;
#: BRANCH GROWTH is a holding cost centre. Both are also flagged on the cost
#: centre row itself (``is_reportable``); this is the name-level belt and
#: braces for a posting whose cost centre is not in the mapping at all.
DROPPED_CENTRES = ("BRANCH GROWTH", "unmapped")


def gl_type(gl_account_number):
    """The notebook's first-digit classification of a GL account."""
    digits = "".join(ch for ch in str(gl_account_number or "") if ch.isdigit())
    return GL_TYPES.get(digits[:1], "unmapped") if digits else "unmapped"


def reporting_years(today=None):
    """The two fiscal years the report covers: this one and the one before.

    The notebook keeps both so every month has something to be compared with.
    """
    today = today or datetime.date.today()
    return today.year - 1, today.year


def latest_snapshot():
    """The newest SAP extract loaded, or None.

    Each extract is a FULL replacement for its date rather than an increment,
    which is why the Trino query ends with ``WHERE d.dt = m.max_dt`` — and why
    reading across snapshots would count the same posting twice.
    """
    from .models import SapCostPosting

    return (SapCostPosting.objects.order_by("-snapshot_date")
            .values_list("snapshot_date", flat=True).first())


#: The join and the filter, in one place. Every summary below starts here, so
#: the department total, the branch total and the expense-line total can never
#: disagree about what counts as an operating expense.
#:
#: The GL is matched on its DIGITS as a number, because the notebook casts both
#: sides to int. ``operating_expense_mapping.gl`` is a CharField and the
#: posting's is too, so a string compare would miss a row that differs only by
#: a leading zero or stray space.
_REPORTABLE = """
    FROM sap_cost_posting p
    JOIN sap_cost_centre c
      ON c.cost_centre = p.cost_centre
     AND c.is_reportable
     AND UPPER(TRIM(c.cost_centre_name)) <> ALL(%(dropped)s)
    JOIN operating_expense_mapping m
      ON NULLIF(regexp_replace(COALESCE(m.gl, ''), '[^0-9]', '', 'g'), '')::bigint
       = NULLIF(regexp_replace(COALESCE(p.gl_account_number, ''), '[^0-9]', '', 'g'), '')::bigint
     AND COALESCE(TRIM(m.operating_expense), '') <> ''
    WHERE p.snapshot_date = %(snapshot)s
      AND p.fiscal_year = ANY(%(years)s)
      AND LEFT(regexp_replace(COALESCE(p.gl_account_number, ''), '[^0-9]', '', 'g'), 1) = '7'
      AND NOT EXISTS (
            SELECT 1 FROM sap_cost_exclusion x
             WHERE NULLIF(regexp_replace(x.gl, '[^0-9]', '', 'g'), '')::bigint
                 = NULLIF(regexp_replace(COALESCE(p.gl_account_number, ''), '[^0-9]', '', 'g'), '')::bigint)
      AND p.entry_month <> ''
"""


def _params(snapshot, years):
    return {
        "snapshot": snapshot,
        "years": list(years),
        "dropped": [name.upper() for name in DROPPED_CENTRES],
    }


def _rows(sql, params):
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(sql, params)
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def by_department(snapshot=None, years=None):
    """Operating cost per department per month — what the CEO deck shows."""
    snapshot = snapshot or latest_snapshot()
    if snapshot is None:
        return []
    sql = f"""
        SELECT c.cost_department AS department,
               p.entry_month AS month,
               SUM(p.amount) AS amount
        {_REPORTABLE}
        GROUP BY c.cost_department, p.entry_month
        ORDER BY c.cost_department, p.entry_month
    """
    return _rows(sql, _params(snapshot, years or reporting_years()))


def by_branch(snapshot=None, years=None):
    """Operating cost per BRANCH per month.

    Grouped on the cost centre NAME rather than its code, because several
    branches have two cost centres - Kisumu is 18 and 600, Eldoret 21 and 410,
    Hurlingham 19 and 210, Mombasa 300 and 310. Grouping on the code would
    report each of those twice, at half its cost.
    """
    snapshot = snapshot or latest_snapshot()
    if snapshot is None:
        return []
    sql = f"""
        SELECT c.cost_centre_name AS branch,
               p.entry_month AS month,
               SUM(p.amount) AS amount
        {_REPORTABLE}
          AND c.is_branch
        GROUP BY c.cost_centre_name, p.entry_month
        ORDER BY c.cost_centre_name, p.entry_month
    """
    return _rows(sql, _params(snapshot, years or reporting_years()))


def by_expense_line(snapshot=None, years=None):
    """Operating cost per expense line.

    The line is ``operating_expense_mapping.actual_gl_name`` where it is set,
    falling back to ``expense_type``. That is what gives "Staff costs",
    "IT Maintenance", "Deposit protection fund" - the ten names the CEO deck
    had hard-coded, all of which are already in that mapping.
    """
    snapshot = snapshot or latest_snapshot()
    if snapshot is None:
        return []
    sql = f"""
        SELECT COALESCE(NULLIF(TRIM(m.actual_gl_name), ''),
                        NULLIF(TRIM(m.expense_type), ''),
                        'unclassified') AS expense_line,
               p.fiscal_year AS fiscal_year,
               SUM(p.amount) AS amount
        {_REPORTABLE}
        GROUP BY 1, p.fiscal_year
        ORDER BY 3 DESC
    """
    return _rows(sql, _params(snapshot, years or reporting_years()))


def by_subsidiary(snapshot=None, years=None):
    """Operating cost per company in the group.

    Worth separating: a department total that silently mixed HFCB-Properties,
    the insurance arm, the foundation and First Permanent into the bank would
    overstate the bank.
    """
    snapshot = snapshot or latest_snapshot()
    if snapshot is None:
        return []
    # The LEFT JOIN has to sit with the other joins, before the WHERE, so it is
    # spliced into the shared clause rather than appended after it.
    joined = _REPORTABLE.replace(
        "    WHERE p.snapshot_date",
        "    LEFT JOIN sap_subsidiary s ON s.company_code = p.company_code\n"
        "    WHERE p.snapshot_date", 1)
    sql = f"""
        SELECT COALESCE(NULLIF(TRIM(s.subsidiary), ''),
                        'company ' || p.company_code::text) AS subsidiary,
               p.fiscal_year AS fiscal_year,
               SUM(p.amount) AS amount
        {joined}
        GROUP BY 1, p.fiscal_year
        ORDER BY 3 DESC
    """
    return _rows(sql, _params(snapshot, years or reporting_years()))


def health(snapshot=None, years=None):
    """What the load is carrying and what it cannot place.

    An unmapped cost centre is the one failure that silently shrinks every
    department total, so it is counted and named rather than left to be
    noticed. Same for a 7-series GL with no mapping row.
    """
    from django.db import connection

    snapshot = snapshot or latest_snapshot()
    if snapshot is None:
        return {"snapshot_date": None, "postings": 0,
                "unmapped_cost_centres": [], "unmapped_gls": [],
                "reportable_postings": 0, "reportable_amount": 0,
                "postings_without_a_date": 0}

    years = list(years or reporting_years())
    params = _params(snapshot, years)
    with connection.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS postings,
                   COUNT(*) FILTER (WHERE entry_month = '') AS no_date,
                   SUM(amount) AS total
            FROM sap_cost_posting
            WHERE snapshot_date = %(snapshot)s AND fiscal_year = ANY(%(years)s)
        """, params)
        postings, no_date, total = cur.fetchone()

        # Cost centres on a 7-series posting that the mapping does not know.
        cur.execute("""
            SELECT p.cost_centre, COUNT(*) AS postings, SUM(p.amount) AS amount
            FROM sap_cost_posting p
            LEFT JOIN sap_cost_centre c ON c.cost_centre = p.cost_centre
            WHERE p.snapshot_date = %(snapshot)s
              AND p.fiscal_year = ANY(%(years)s)
              AND LEFT(regexp_replace(COALESCE(p.gl_account_number, ''),
                                      '[^0-9]', '', 'g'), 1) = '7'
              AND c.id IS NULL
            GROUP BY p.cost_centre
            ORDER BY 3 DESC NULLS LAST
            LIMIT 50
        """, params)
        unmapped_centres = [
            {"cost_centre": row[0], "postings": row[1],
             "amount": float(row[2] or 0)} for row in cur.fetchall()]

        cur.execute("""
            SELECT p.gl_account_number, COUNT(*) AS postings,
                   SUM(p.amount) AS amount
            FROM sap_cost_posting p
            LEFT JOIN operating_expense_mapping m
              ON NULLIF(regexp_replace(COALESCE(m.gl, ''), '[^0-9]', '', 'g'), '')::bigint
               = NULLIF(regexp_replace(COALESCE(p.gl_account_number, ''), '[^0-9]', '', 'g'), '')::bigint
            WHERE p.snapshot_date = %(snapshot)s
              AND p.fiscal_year = ANY(%(years)s)
              AND LEFT(regexp_replace(COALESCE(p.gl_account_number, ''),
                                      '[^0-9]', '', 'g'), 1) = '7'
              AND m.id IS NULL
            GROUP BY p.gl_account_number
            ORDER BY 3 DESC NULLS LAST
            LIMIT 50
        """, params)
        unmapped_gls = [
            {"gl": row[0], "postings": row[1], "amount": float(row[2] or 0)}
            for row in cur.fetchall()]

        cur.execute(f"""
            SELECT COUNT(*), COALESCE(SUM(p.amount), 0)
            {_REPORTABLE}
        """, params)
        reportable, reportable_amount = cur.fetchone()

    return {
        "snapshot_date": snapshot.isoformat(),
        "fiscal_years": years,
        "postings": postings or 0,
        "postings_without_a_date": no_date or 0,
        "total_amount": float(total or 0),
        "reportable_postings": reportable or 0,
        "reportable_amount": float(reportable_amount or 0),
        "unmapped_cost_centres": unmapped_centres,
        "unmapped_gls": unmapped_gls,
    }


def summary(snapshot=None, years=None):
    """Everything the cost screen needs, in one call.

    One call because the screen is one document: the department table, the
    branch table, the expense lines and the health of the load are read
    together or they can disagree about which snapshot they came from.
    """
    snapshot = snapshot or latest_snapshot()
    years = list(years or reporting_years())
    return {
        "snapshot_date": snapshot.isoformat() if snapshot else None,
        "fiscal_years": years,
        "by_department": by_department(snapshot, years),
        "by_branch": by_branch(snapshot, years),
        "by_expense_line": by_expense_line(snapshot, years),
        "by_subsidiary": by_subsidiary(snapshot, years),
        "health": health(snapshot, years),
    }
