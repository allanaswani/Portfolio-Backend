"""Weighted Sales, from the score the weighted sales report already computes.

``weighted_sales_daily_report.py`` in the ETL scores every seller on the
Weighted Sales Dashboard - eleven sales lines, each weighted per role, half
this month and half year to date - and then wrote those scores ONLY into the
workbook it emails. Nothing could read them, so the card said "not yet read
into this card" about a number the bank already sends round every day.

The ETL now also saves one row per seller per run into
``weighted_sales_seller_scores`` (``save_seller_scores`` in
``weighted_sales_seller_scores.py`` beside the report). This reads it.

The score is a FRACTION, the way the workbook's cards carry it: 0.263 on the
Business_Banking card is 26.3% of the dashboard, scored against an 80%
target (0.8) as 0.263 / 0.8. ``weighted_score`` is the dashboard's own
headline column - the one it ranks on - so that is the figure, not the month
or the YTD half on its own.
"""

from __future__ import annotations

import datetime

#: Written by the ETL. The name is the contract between the two repos.
TABLE = "weighted_sales_seller_scores"


def seller_score(sales_code, upto=None):
    """This seller's dashboard score → ``(score, as_at, label, problem)``.

    ``upto`` is the month end a card for a NAMED month is for: the latest run
    on or before it answers, so a September card reads September's last run
    and not one from October.

    A seller can sit in more than one of the report's groups (an RM moved
    from SME to PB keeps a row in each until the roster catches up). The
    latest run wins, and within it the higher score - the report ranks each
    group on its own, so neither row is more "theirs" than the other, and
    the higher one is what that seller would be shown on the dashboard.
    """
    from django.db import connection, transaction

    code = (sales_code or "").strip()
    if not code:
        return None, None, None, "no sales code"

    if TABLE not in connection.introspection.table_names():
        return None, None, None, (
            "the weighted sales report has not saved its scores yet - it "
            "needs the ETL change that writes weighted_sales_seller_scores, "
            "and one run after it")

    sql = f"""
        SELECT weighted_score, report_date, role_group
        FROM {TABLE}
        WHERE UPPER(TRIM(sales_code)) = UPPER(TRIM(%s))
          AND weighted_score IS NOT NULL
          AND (%s::date IS NULL OR report_date <= %s::date)
        ORDER BY report_date DESC, weighted_score DESC
        LIMIT 1
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(sql, [code, upto, upto])
        row = cur.fetchone()
    if row is None:
        return None, None, None, (
            f"the weighted sales dashboard has no score for {code.upper()}"
            + (f" on or before {upto:%d %b %Y}" if upto else ""))

    score, as_at, group = row
    if isinstance(as_at, datetime.datetime):
        as_at = as_at.date()
    label = f"weighted sales dashboard ({group}), as at {as_at:%d %b %Y}"
    return float(score), as_at, label, None
