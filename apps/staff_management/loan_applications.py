"""Loan applications off iApply's raw trail: turnaround, and how many came back.

``loan_tat_iapply_automation.py`` - the iApply TAT report - reads
``iapply_loan_tat``, a row per application per status change, and its
per-seller view groups on ``SellerCode``. Two card lines are that report's
figures and neither was read:

* **Errors** (Mortgage Business ARM, 5%, target 0.05). The report counts an
  application as returned when a status sends it back - "RM Processing
  Application Returned by DCR", "HCS Processing application returned by
  BMD" and some forty more, every one of them saying RETURNED. The error
  rate is the share of this seller's applications sent back at least once.
  Lower is better.
* **TAT (Loan)**, as a fallback. The card reads ``total_bank_tat`` off the
  summarised dump, and where that has no row for a seller - every Mortgage
  ARM on the coverage run - the line said "no loan applications". The trail
  still has them; the turnaround is creation to last action, which is what
  the report's TAT Total adds up to.

The trail's shape is the account-opening one (see ``account_opening``):
dates may be text, so every cast is guarded.
"""

from __future__ import annotations

TIMEOUT_MS = 15000
TABLE = "iapply_loan_tat"


class LoanTrailUnavailable(Exception):
    """The trail could not be read, with a reason fit to print on a card."""


def seller_applications(sales_code, year, up_to=None):
    """This seller's applications started in ``year`` →
    ``{"applications", "returned", "error_rate", "tat_days", "latest"}``,
    with ``applications`` 0 when there are none.
    """
    from django.db import connection, transaction

    started = ('MIN(CASE WHEN "CreationDate"::text '
               "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
               'THEN "CreationDate"::text::timestamp END)')
    finished = ('MAX(CASE WHEN "ActionDate"::text '
                "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
                'THEN "ActionDate"::text::timestamp END)')
    sql = f"""
        WITH trail AS (
            SELECT "ApplicationId" AS application,
                   {started} AS started,
                   {finished} AS finished,
                   BOOL_OR(COALESCE("StatusTo", '') ILIKE '%%returned%%')
                       AS returned
            FROM {TABLE}
            WHERE UPPER(TRIM(COALESCE("SellerCode"::text, '')))
                  = UPPER(TRIM(%s))
            GROUP BY "ApplicationId"
        )
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE returned),
               AVG(EXTRACT(EPOCH FROM (finished - started)) / 86400.0)
                   FILTER (WHERE finished >= started),
               MAX(finished)
        FROM trail
        WHERE started IS NOT NULL
          AND EXTRACT(YEAR FROM started) = %s
          AND (%s::date IS NULL OR started::date <= %s::date)
    """
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            cur.execute(sql, [sales_code.strip(), year, up_to, up_to])
            total, returned, days, latest = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - reported on the line
        raise LoanTrailUnavailable(
            f"the iApply loan trail could not be read: "
            f"{type(exc).__name__}: {exc}".strip()) from exc

    total = int(total or 0)
    return {
        "applications": total,
        "returned": int(returned or 0),
        "error_rate": (int(returned or 0) / total) if total else None,
        "tat_days": float(days) if days is not None else None,
        "latest": latest.date() if hasattr(latest, "date") else latest,
    }
