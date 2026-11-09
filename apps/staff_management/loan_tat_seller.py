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
           "StatusFrom", "ActionUser", "ActionUserName", "SellerCode", "Seller"]

_DATE = ("CASE WHEN {c}::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
         "THEN {c}::text::timestamp END")


def _rows(year, month, timeout_ms):
    from django.db import connection, transaction

    first = datetime.date(year, month, 1)
    after = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    action, created = _DATE.format(c='"ActionDate"'), _DATE.format(c='"createdAt"')
    select = ", ".join(f'ilt."{c}"' for c in COLUMNS)
    sql = f"""
        SELECT {select}
        FROM {TABLE} ilt
        LEFT JOIN customers c ON ilt."Customerid"::decimal = c.cust_id::decimal
        WHERE ilt."ApplicationId" IN (
            SELECT "ApplicationId" FROM {TABLE}
            WHERE ({action} >= %s AND {action} < %s)
               OR ({created} >= %s AND {created} < %s))
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        cur.execute(sql, [first, after, first, after])
        return cur.fetchall()


def seller_tat(rows, year, month):
    """The report's seller view for one month → {SELLER CODE: days}."""
    import numpy as np
    import pandas as pd

    from .loan_tat_stages import map_stage

    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        return {}
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
    df = pd.concat([df, current], ignore_index=True)

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

    month_rows = df[df["ActionDate"].dt.strftime("%Y-%m") == f"{year}-{month:02d}"]
    out = {}
    for (code, _seller), group in month_rows.groupby(["SellerCode", "Seller"], sort=True):
        values = group["TAT"][group["TAT"] != 0]
        key = str(code).replace(" ", "").upper()
        # The report has a row per code AND name; the desk's lookup by code takes
        # the first, and the sheet is sorted.
        out.setdefault(key, float(values.mean()) if len(values) else 0.0)
    return out


def seller_month_tat(year, month, timeout_ms=180_000):
    """{SELLER CODE: days} for the month, or None while it is read in the
    background (see feed_cache)."""
    from .feed_cache import cached

    return cached(f"loan_tat_seller:{year}-{month:02d}",
                  lambda: seller_tat(_rows(year, month, timeout_ms), year, month))
