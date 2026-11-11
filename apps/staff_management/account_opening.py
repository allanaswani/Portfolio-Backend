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


def turnarounds(sales_code, year, branch_code=None, bank_wide=False):
    """Account-opening turnaround for one person, every segment at once.

    ``branch_code`` / ``bank_wide`` widen the read from the person's own
    ``SellerCode`` to every application of their branch, or of the bank.
    That is for back-office cards: a branch operations manager or the RBO
    team never appears as a seller, so keyed on their own code the line
    could never find a single application. ``live_scorecard.bo_scope``
    decides which, and only after their own code has found nothing.

    → ``{segment: (average_days, applications, latest)}``.

    ONE pass. ``iapply_accounts_tat`` is 611,218 rows and nothing indexes
    ``SellerCode``, so a query per segment meant four scans of it for every
    card built. The segments are separated with FILTER instead, which costs
    one scan however many of them a card carries.

    The average is over APPLICATIONS, not over status changes - the table is
    a row per status change, and an application that went round the houses
    would otherwise count six times and drag the branch's figure with it.
    """
    from django.db import connection, transaction

    # ``CreationDate`` is a varchar and ``ActionDate`` is a timestamp, so one
    # of these guards is load-bearing and the other is insurance against a
    # host where the types differ. Both go through ::text::timestamp:
    # casting a timestamp to text gives the ISO form, which parses back
    # exactly, and ::timestamp rather than ::timestamptz keeps the session's
    # time zone out of a figure measured in days.
    started = ('MIN(CASE WHEN "CreationDate"::text '
               "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
               'THEN "CreationDate"::text::timestamp END)')
    finished = ('MAX(CASE WHEN "ActionDate"::text '
                "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
                'THEN "ActionDate"::text::timestamp END)')

    if bank_wide:
        who, params = "TRUE", [year]
    elif branch_code not in (None, ""):
        # "Branch" is the numeric branch code (accounts_tat.py maps it with
        # its _BRANCH_MAP), stored as text on some loads - hence the guard.
        who = ("NULLIF(regexp_replace(\"Branch\"::text, '\\D', '', 'g'), '')"
               "::int = %s")
        params = [int(branch_code), year]
    else:
        who = "UPPER(TRIM(COALESCE(\"SellerCode\", ''))) = UPPER(TRIM(%s))"
        params = [sales_code.strip(), year]
    pieces = []
    order = []
    for segment in ("pb", "bb", "ub", "sme"):
        if segment == "pb":
            # The ETL's ELSE: personal banking is everything not claimed by
            # another segment, so a segment nobody has mapped still lands
            # somewhere rather than vanishing from every card.
            where = "(s.segment = ANY(%s) OR s.segment <> ALL(%s))"
            params_for = [list(SEGMENTS[segment]), list(NAMED_ELSEWHERE)]
        else:
            where = "s.segment = ANY(%s)"
            params_for = [list(SEGMENTS[segment])]

        pieces.append(
            f"AVG(EXTRACT(EPOCH FROM (s.finished - s.started)) / 86400.0) "
            f"FILTER (WHERE {where}) AS days_{segment}")
        pieces.append(
            f"COUNT(*) FILTER (WHERE {where}) AS seen_{segment}")
        pieces.append(
            f"MAX(s.finished) FILTER (WHERE {where}) AS latest_{segment}")
        # Each FILTER repeats the predicate, so the parameters go in three
        # times - in the order the placeholders appear.
        params.extend(params_for * 3)
        order.append(segment)

    sql = f"""
        WITH trail AS (
            SELECT "ApplicationId" AS application,
                   MIN(NULLIF(regexp_replace("Customerid"::text,
                                             '\\D', '', 'g'), ''))::bigint
                       AS cust_id,
                   {started} AS started,
                   {finished} AS finished
            FROM iapply_accounts_tat
            WHERE {who}
            GROUP BY "ApplicationId"
        ), scoped AS (
            SELECT t.started, t.finished,
                   UPPER(TRIM(COALESCE(c.segment, ''))) AS segment
            FROM trail t
            LEFT JOIN customers c ON c.cust_id = t.cust_id
            WHERE t.started IS NOT NULL
              AND t.finished IS NOT NULL
              -- A trail that runs backwards is a correction, not a
              -- turnaround.
              AND t.finished >= t.started
              AND EXTRACT(YEAR FROM t.started) = %s
        )
        SELECT {', '.join(pieces)}
        FROM scoped s
    """

    try:
        with transaction.atomic(), connection.cursor() as cur:
            # SET LOCAL only takes effect inside a transaction - outside one
            # PostgreSQL ignores it with a warning, leaving the cap silently
            # absent. Same pattern as observability.health.
            cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            cur.execute(sql, params)
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - the caller turns this into a
        # reason on the line. Nothing is reported as nought on the strength
        # of a read that did not finish.
        raise AccountOpeningUnavailable(_why(exc)) from exc

    out = {}
    for index, segment in enumerate(order):
        average, applications, latest = row[index * 3:index * 3 + 3]
        if not applications:
            out[segment] = (None, 0, None)
            continue
        out[segment] = (
            float(average), int(applications),
            latest.date() if hasattr(latest, "date") else latest)
    return out


def turnaround(sales_code, year, segment):
    """One segment → ``(average_days, applications, latest)``.

    A thin wrapper over :func:`turnarounds`, which reads them all in one
    pass. Kept because asking about one segment is the readable thing to do
    from a test.
    """
    if segment not in SEGMENTS:
        return None, 0, None
    return turnarounds(sales_code, year)[segment]


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


#: The desk's back-office account-opening TAT, ported from accounts_tat.py
#: (its "tat_vol_rts_user_view"): per iApply ActionUser and banking segment,
#: the month of each action, the mean of the non-zero step TATs. The ETL
#: saves those steps to this table. Checked on 11 Nov 2026 against the BO
#: template for Joseph Kinuthia (JKKINUTHIA): BB 0.8241 / 5.5519 / 0.6036 and
#: personal 0.1367 / 0.5369 / 0.2255 for Jul / Aug / Sep, the template's
#: own figures; Embu branch's figures (0.87 / 0.72 / 0.47 ...) do not match.
DESK_SEGMENTS = {"accountopeningpb": "PERSONAL BANKING",
                 "accountopeningbb": "BB"}


def desk_turnaround(action_user, sheet_key, month_start):
    """(days, steps) for one iApply user, segment and month, as the desk's
    report gives it; (None, 0) when the user actioned nothing that month.
    Raises AccountOpeningUnavailable when the table cannot be read."""
    import datetime

    from django.core.cache import cache
    from django.db import connection, transaction

    segment = DESK_SEGMENTS[sheet_key]
    user = str(action_user or "").strip().upper()
    if not user:
        return None, 0
    key = f"ao_desk_tat:{user}:{segment}:{month_start:%Y-%m}"
    kept = cache.get(key)
    if kept is not None:
        return tuple(kept)
    end = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            cur.execute("""
                SELECT AVG(tat_days) FILTER (WHERE tat_days <> 0), COUNT(*)
                FROM account_tat_individuals_application_data_dump
                WHERE UPPER(TRIM(action_user)) = %s AND banking_segment = %s
                  AND action_date >= %s AND action_date < %s""",
                        [user, segment, month_start, end])
            average, steps = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - the card says why
        raise AccountOpeningUnavailable(_why(exc)) from exc
    # mean_non_zero gives 0 when every step was nought.
    found = ((float(average) if average is not None else 0.0), int(steps)) \
        if steps else (None, 0)
    cache.set(key, list(found), 3600)
    return found
