"""Account-opening turnaround, from iApply.

The cards say what this is in their own measure of success: "PB AO TAT OF 1
Day", "BB AO TAT of 1 day", "SME AO TAT of 5days". It is a number of DAYS and
lower is better - Jane Karathe's signed card reads 0.10 for personal banking
and 0.88 for business banking against a one-day target.

This was refused before, on the grounds that iApply carries LOAN turnaround
and pointing an account-opening line at it would put a loan figure against an
account-opening target. That is true of ``iapply_loan_approvals_data_dump``.
It is not true of ``iapply_accounts_tat``, which is the ACCOUNT application
trail - a row per application per status change - and is what the desk's own
accounts-TAT report reads.

The table's shape, which decides the SQL
────────────────────────────────────────
Three things about it are not obvious and all three bite:

* **it is a row per status change**, not per application. The turnaround of
  an application is the span of its rows, so they are grouped first;
* **the dates are TEXT.** ``"ActionDate"::timestamptz`` fails the whole
  statement on one malformed value, so every cast is guarded by the same
  regular expression the ETL guards it with;
* **``"Customerid"`` is text too**, and not always digits. The join to
  ``customers`` strips non-digits and NULLIFs the empty result, which is
  what ``asset_tracking_pipeline_report_takeover`` does.

The column names are quoted PascalCase, which is how iApply wrote them.
"""

from __future__ import annotations

#: How long this read may take before it is given up on. The card path is
#: rebuilt on every page view, and a card nobody can load is worse than a
#: line nobody can score.
TIMEOUT_MS = 15000

#: The card's segment → the ``customers.segment`` values behind it.
#:
#: Taken from the ETL's own CASE (``accounts_tat.py``), because that is what
#: produced the figures on the signed cards. Two notes:
#:
#: * SME and business banking are the SAME population here. ``core.segments``
#:   is explicit about it - BUSINESS BANKING, SME, SMALL ENTERPRISES and
#:   MEDIUM ENTERPRISES are one segment under different names - so the SME
#:   line differs from the BB line only in its target, five days against one,
#:   which is already on the card.
#: * the ETL lists PRIVATE under BOTH personal banking and ultimate, and in a
#:   CASE the first match wins, so PRIVATE counts as personal banking there.
#:   ``core.segments`` reads PRIVATE as ultimate. The ETL's reading is kept,
#:   because the cards were scored against it and changing it here would move
#:   people's figures without anybody asking for that.
SEGMENTS = {
    "pb": ("MASS", "STANDARD", "PRIVATE", "VIRTUAL"),
    "bb": ("MEDIUM ENTERPRISES", "SMALL ENTERPRISES"),
    "sme": ("MEDIUM ENTERPRISES", "SMALL ENTERPRISES"),
    "ub": ("ULTIMATE",),
}

#: Segments that fall to personal banking through the ETL's ELSE. Anything
#: not named anywhere lands here, which is why the personal-banking read is
#: an "everything else" rather than a list.
NAMED_ELSEWHERE = (
    "MEDIUM ENTERPRISES", "SMALL ENTERPRISES", "ULTIMATE", "LARGE ENTERPRISES",
    "PROJECT FINANCE", "INTERNAL ACCOUNTS", "INSTITUTIONAL BANKING",
    "DIASPORA", "NON RESIDENT KENYANS", "DIASPORA BUSINESS BANKING",
    "DIASPORA PERSONAL BANKING", "DIASPORA ULTIMATE BANKING",
)


def turnaround(sales_code, year, segment):
    """Account-opening turnaround for one person in one segment.

    → ``(average_days, applications, latest)``, or ``(None, 0, None)`` when
    there is nothing to measure. Raises nothing: a feed that cannot be read
    is reported by the caller as a reason, not as a nought.

    The average is over APPLICATIONS, not over status changes - an
    application that went round the houses would otherwise count six times
    and drag the branch's figure with it.
    """
    from django.db import connection, transaction

    buckets = SEGMENTS.get(segment)
    if buckets is None:
        return None, 0, None

    if segment == "pb":
        # The ETL's ELSE: personal banking is everything not claimed by
        # another segment, so a segment nobody has mapped still lands
        # somewhere rather than vanishing from every card.
        where_segment = (
            "(UPPER(TRIM(COALESCE(c.segment, ''))) = ANY(%s) "
            " OR UPPER(TRIM(COALESCE(c.segment, ''))) <> ALL(%s))")
        params_segment = [list(buckets), list(NAMED_ELSEWHERE)]
    else:
        where_segment = "UPPER(TRIM(COALESCE(c.segment, ''))) = ANY(%s)"
        params_segment = [list(buckets)]

    sql = f"""
        WITH trail AS (
            SELECT iat."ApplicationId" AS application,
                   MIN(NULLIF(regexp_replace(iat."Customerid"::text,
                                             '\\D', '', 'g'), ''))::bigint
                       AS cust_id,
                   MIN(CASE WHEN iat."CreationDate"::text
                                 ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                            THEN iat."CreationDate"::text::timestamptz END)
                       AS started,
                   MAX(CASE WHEN iat."ActionDate"::text
                                 ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                            THEN iat."ActionDate"::text::timestamptz END)
                       AS finished
            FROM iapply_accounts_tat iat
            WHERE UPPER(TRIM(COALESCE(iat."SellerCode", '')))
                  = UPPER(TRIM(%s))
            GROUP BY iat."ApplicationId"
        )
        SELECT AVG(EXTRACT(EPOCH FROM (t.finished - t.started)) / 86400.0),
               COUNT(*),
               MAX(t.finished)
        FROM trail t
        LEFT JOIN customers c ON c.cust_id = t.cust_id
        WHERE t.started IS NOT NULL
          AND t.finished IS NOT NULL
          -- A trail that runs backwards is a correction, not a turnaround.
          AND t.finished >= t.started
          AND EXTRACT(YEAR FROM t.started) = %s
          AND {where_segment}
    """

    params = [sales_code.strip(), year] + params_segment

    try:
        with transaction.atomic(), connection.cursor() as cur:
            # SET LOCAL only takes effect inside a transaction - outside one
            # PostgreSQL ignores it with a warning, leaving the cap silently
            # absent. Same pattern as observability.health.
            cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            cur.execute(sql, params)
            average, applications, latest = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - the caller turns this into a
        # reason on the line. Nothing is reported as nought on the strength
        # of a read that did not finish.
        raise AccountOpeningUnavailable(_why(exc)) from exc

    if not applications:
        return None, 0, None
    return (float(average), int(applications),
            latest.date() if hasattr(latest, "date") else latest)


class AccountOpeningUnavailable(Exception):
    """The feed could not be read, with a reason fit to print on a card."""


def _why(exc):
    """A database error → something the card can say.

    "Could not be read" is true of every failure and useful for none of
    them: a missing table is the ETL's problem and a timeout is this
    query's, and they go to different people.
    """
    text = str(exc).lower()
    if "statement timeout" in text or "canceling statement" in text:
        return ("the account-opening trail took too long to read - a slow "
                "query rather than a missing figure")
    if "does not exist" in text or "undefined" in text:
        return ("the account-opening trail (iapply_accounts_tat) is not on "
                "this database")
    return "the account-opening trail could not be read"
