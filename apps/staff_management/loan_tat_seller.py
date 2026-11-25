"""TAT (Loan) per seller, as loan_tat_iapply_automation.py computes it.

The desk's TAT (Loan) figure is that report's ``tat_vol_rts_seller_view`` sheet:
for each month, the mean of the non-zero step times of the actions dated in that
month, by ``SellerCode``. The card used to average the year's total bank TAT off
the summarised dump, which read 80-93 days where the desk had 12-23 (September
2026 proof). This follows the report step by step:

1. ``load_raw_data``: ``iapply_loan_tat`` LEFT JOIN ``customers`` (kept, as it can
   repeat rows and the report's averages count those repeats);
2. ``add_current_status_rows``: one more row per application from its latest
   action - StatusFrom = StatusTo, ActionUser = StatusTo's first word, ActionDate
   = createdAt - unless it is STORED, or the user's name starts Cancel / Reject /
   Decline;
3. text columns cast to str and stripped; the stage from StatusFrom
   (:mod:`loan_tat_stages`, the report's map copied verbatim);
4. ``calculate_tat``: sorted by application and date, a step's time is the gap
   from the previous action (creation for the first), nought on a closing status;
5. days, then a running total per application, stage and ActionUser;
6. the month's actions, grouped by SellerCode and Seller, mean of the non-zero
   values (``mean_non_zero``).

Steps 2's "latest action" is the latest at the time of reading, as in the report,
so a month read long after it closed can differ slightly from the report run then.

**By branch (20 Nov 2026).** The back office's ``Branch_Loan_TAT`` sheet carries
one figure per branch and month, the same on the BOM's and the CSOs' rows. The
same report has a ``tat_vol_rts_branch_view`` sheet: the same step times,
grouped by the application's ``Branch`` code (named through the report's own
``_BRANCH_MAP``, copied below) and ``banking_segment``. :func:`branch_tat`
returns both readings - the branch over every segment, and each branch and
segment - so :func:`apps.staff_management.bo_live_feeds.prove_branch_loan_tat`
can find which one the desk's figures are, rather than assuming it.
"""
from __future__ import annotations

import datetime

TABLE = "iapply_loan_tat"
TERMINAL = {"stored", "cancel", "reject", "decline", "archive",
            "stored archived - cancelled", "stored archived - declined",
            "stored archived - disbursed", "stored archived cancelled",
            "stored archived disbursed", "stored cancelled & archive",
            "stored declined & archived", "stored disbursed"}
COLUMNS = ["ApplicationId", "ActionDate", "CreationDate", "createdAt", "StatusTo",
           "StatusFrom", "ActionUser", "ActionUserName", "SellerCode", "Seller",
           "Branch"]
#: The report's load_raw_data segment, verbatim (its CASE, in its order).
SEGMENT_SQL = """CASE
    WHEN c.segment IN ('MASS','STANDARD','PRIVATE','VIRTUAL') THEN 'PERSONAL BANKING'
    WHEN c.segment IN ('PRIVATE','ULTIMATE') THEN 'ULTIMATE'
    WHEN c.segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES') THEN 'SME'
    WHEN c.segment IN ('LARGE ENTERPRISES') THEN 'COMMERCIAL'
    WHEN c.segment IN ('PROJECT FINANCE') THEN 'PROJECT FINANCE'
    WHEN c.segment IN ('INTERNAL ACCOUNTS') THEN 'INTERNAL ACCOUNTS'
    WHEN c.segment IN ('INSTITUTIONAL BANKING') THEN 'INSTITUTIONAL BANKING'
    WHEN c.segment IN ('DIASPORA PERSONAL BANKING','DIASPORA ULTIMATE BANKING',
    'DIASPORA BUSINESS BANKING','DIASPORA','NON RESIDENT KENYANS') THEN 'DIASPORA'
    ELSE 'PERSONAL BANKING' END"""
#: loan_tat_iapply_automation.py's _BRANCH_MAP, verbatim.
BRANCH_MAP = {
    100: 'HEAD OFFICE', 101: 'RETAIL MORTGAGE SALES', 102: 'CORPORAE SALES',
    103: 'ASSET FINANCE & IPF', 104: 'DIASPORA AND CHANNELS', 105: 'CUSTODY',
    108: 'CORPORATE & SME/PROJECT FINANC', 16: 'KITENGELA BRANCH',
    17: 'NAIVASHA BRANCH', 18: 'KISII BRANCH', 19: 'HURLINGHAM BRANCH',
    210: 'HURLINGHAM BRANCH', 200: 'REHANI BRANCH', 20: 'RIVERROAD BRANCH',
    220: 'HARAMBEE AVE BRANCH', 22: 'NANYUKI BRANCH', 230: 'BURUBURU BRANCH',
    23: 'KOMAROCK BRANCH', 24: 'MACHAKOS BRANCH', 250: 'RONGAI BRANCH',
    25: 'EMBU BRANCH', 260: 'TRM BRANCH', 270: 'SAMEER BRANCH', 280: 'WESTLANDS BRANCH',
    300: 'MOMBASA BRANCH', 310: 'MOMBASA BRANCH', 400: 'NAKURU BRANCH',
    410: 'ELDORET BRANCH', 500: 'THIKA BRANCH', 510: 'NYERI BRANCH',
    520: 'MERU BRANCH', 600: 'KISUMU BRANCH',
}
#: The key for "every segment" in branch_tat's result.
ALL_SEGMENTS = "*"

_DATE = ("CASE WHEN {c}::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
         "THEN {c}::text::timestamp END")


def _rows(year, month, timeout_ms, columns=None):
    """The applications with an action or a creation in the month - every
    action of each, as the report reads them. ``columns`` (default
    :data:`COLUMNS`) are the iapply_loan_tat columns returned."""
    from django.db import connection, transaction

    first = datetime.date(year, month, 1)
    after = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    action, created = _DATE.format(c='"ActionDate"'), _DATE.format(c='"createdAt"')
    select = ", ".join(f'ilt."{c}"' for c in (columns or COLUMNS))
    sql = f"""
        SELECT {select}, {SEGMENT_SQL} AS banking_segment
        FROM {TABLE} ilt
        LEFT JOIN customers c ON ilt."Customerid"::decimal = c.cust_id::decimal
        WHERE ilt."ApplicationId" IN (
            SELECT "ApplicationId" FROM {TABLE}
            WHERE ({action} >= %s AND {action} < %s)
               OR ({created} >= %s AND {created} < %s))
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {_limit(timeout_ms)}")
        cur.execute(sql, [first, after, first, after])
        return cur.fetchall()


def _month_steps(rows, year, month, columns=None):
    """The report's steps 2-5 → the month's action rows with their TAT, or None.
    ``columns``: what :func:`_rows` was asked for (default :data:`COLUMNS`)."""
    import numpy as np
    import pandas as pd

    from .loan_tat_stages import map_stage

    df = pd.DataFrame(rows, columns=list(columns or COLUMNS) + ["banking_segment"])
    if df.empty:
        return None
    for col in ("CreationDate", "ActionDate", "createdAt"):
        parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
        df[col] = parsed.dt.tz_localize(None)

    current = (df.sort_values("ActionDate", ascending=False)
                 .drop_duplicates(subset="ApplicationId", keep="first").copy())
    current["StatusFrom"] = current["StatusTo"]
    current["ActionUser"] = current["StatusTo"].str.split().str.get(0)
    current["ActionDate"] = current["createdAt"]
    current = current[current["ActionUser"].str.split().str.get(0) != "STORED"]
    for word in ("Cancel", "Reject", "Decline"):
        current = current[current["ActionUserName"].str.split().str.get(0) != word]
    # The report's merge_column: which rows it generated for the current
    # status, as opposed to actions somebody took.
    current = current.assign(generated=True)
    df = pd.concat([df.assign(generated=False), current], ignore_index=True)

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()
    df["stage"] = df["StatusFrom"].apply(map_stage)

    df = df.sort_values(["ApplicationId", "ActionDate"], kind="mergesort")
    df["TAT"] = (df.groupby("ApplicationId")["ActionDate"].diff()
                   .fillna(df["ActionDate"] - df["CreationDate"]))
    terminal = (df["StatusTo"].str.strip().str.lower().isin(TERMINAL)
                | df["ActionUser"].str.split().str.get(0).str.strip()
                    .str.lower().isin(TERMINAL))
    df.loc[terminal, "TAT"] = pd.Timedelta(0)
    df = df.reset_index(drop=True)
    df["TAT"] = pd.to_numeric(df["TAT"] / np.timedelta64(1, "D"),
                              errors="coerce").fillna(0)
    df["TAT"] = df.groupby(["ApplicationId", "stage", "ActionUser"])["TAT"].cumsum()

    return df[df["ActionDate"].dt.strftime("%Y-%m") == f"{year}-{month:02d}"]


def _mean_non_zero(values):
    values = values[values != 0]
    return float(values.mean()) if len(values) else 0.0


def seller_tat(rows, year, month):
    """The report's seller view for one month → {SELLER CODE: days}."""
    month_rows = _month_steps(rows, year, month)
    if month_rows is None:
        return {}
    out = {}
    for (code, _seller), group in month_rows.groupby(["SellerCode", "Seller"], sort=True):
        values = group["TAT"][group["TAT"] != 0]
        key = str(code).replace(" ", "").upper()
        # The report has a row per code AND name; the desk's lookup by code takes
        # the first, and the sheet is sorted.
        out.setdefault(key, float(values.mean()) if len(values) else 0.0)
    return out


def _branch_name(code):
    """The report's map_branch: the code as a number, else HEAD OFFICE."""
    try:
        return BRANCH_MAP.get(int(float(str(code).strip())), "HEAD OFFICE")
    except (TypeError, ValueError):
        return "HEAD OFFICE"


def branch_tat(rows, year, month):
    """The report's branch view for one month →
    {BRANCH NAME: {ALL_SEGMENTS: days, segment: days, ...}}.

    The report's rows are a branch CODE and a segment; two codes can share a
    name (Hurlingham 19 and 210, Mombasa 300 and 310), so the name's figure is
    taken over all its codes' rows, which is what a lookup by name on the
    report's ``branch_name`` column gives only when there is one code - and the
    proof says which of the two the desk used if it ever matters.
    """
    month_rows = _month_steps(rows, year, month)
    if month_rows is None:
        return {}
    month_rows = month_rows.assign(branch_name=month_rows["Branch"].map(_branch_name))
    out = {}
    for name, group in month_rows.groupby("branch_name", sort=True):
        out.setdefault(name, {})[ALL_SEGMENTS] = _mean_non_zero(group["TAT"])
    for (name, segment), group in month_rows.groupby(
            ["branch_name", "banking_segment"], sort=True):
        out.setdefault(name, {})[str(segment)] = _mean_non_zero(group["TAT"])
    return out


def branch_month_tat(year, month, timeout_ms=180_000):
    """{BRANCH NAME: {segment or ALL_SEGMENTS: days}} for the month, or None
    while it is read in the background (see feed_cache)."""
    from .feed_cache import cached

    return cached(f"loan_tat_branch:{year}-{month:02d}",
                  lambda: branch_tat(_rows(year, month, timeout_ms), year, month))


def seller_month_tat(year, month, timeout_ms=180_000):
    """{SELLER CODE: days} for the month, or None while it is read in the
    background (see feed_cache)."""
    from .feed_cache import cached

    return cached(f"loan_tat_seller:{year}-{month:02d}",
                  lambda: seller_tat(_rows(year, month, timeout_ms), year, month))


def _limit(ms):
    from .feed_cache import timeout

    return timeout(ms)
