"""Net drawdowns per seller, as weighted_sales_daily_report.py sums them.

The desk's Drawdowns / Net (Loan, Asset) Disbursements figure is that report's
net_drawdown_table: ``drawdown_daily`` this year through its
``process_daily_drawdown_dataframe`` and ``net_drawdown_amount``. The card used to
match a seller on ``salesperson`` OR ``loan_officer_id``, which read 173.6m
against the desk's 101.7m for one RM on the September 2026 proof. The report:

1. ``select * from drawdown_daily where drawdown_dt >= the year``, renamed
   (drawdown_dt, drawdown_dt_1, customer_segment, salesperson);
2. segment not STAFF, description not Staff, salesperson not SBP0001;
3. merged with branch_name_map on unit_code (one row per employee on
   branch_final_employee_dmc_data, not de-duplicated - so a branch listed twice
   counts its drawdowns twice, as in the report);
4. four hand-corrected codes; the seller is ``salesperson`` stripped - its
   loan-officer fallback is overwritten on the next line, so a loan with no
   salesperson is nobody's;
5. net_drawdown summed by month, January to the card's month;
6. zero_out_return_salespersons_in_same_role: DSR309's January-June are nought.
"""
from __future__ import annotations

import datetime

from .weighted_sales_new_customers import SALE_CODE_FIXES, ZEROED_TO_JUNE

RENAMES = {"drawdown_dt": "drawdown_date", "drawdown_dt_1": "eom_date",
           "customer_segment": "segment", "salesperson": "sales_person"}


def _rows(year, timeout_ms):
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        cur.execute("SELECT * FROM drawdown_daily WHERE drawdown_dt >= %s",
                    [datetime.date(year, 1, 1)])
        names = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.execute("SELECT brn_code, staff_branch FROM branch_final_employee_dmc_data")
        branches = cur.fetchall()
    return names, rows, branches


def net_by_seller(frame, branches, year, month):
    """The report's net drawdowns over a frame of drawdown_daily → {CODE: amount}."""
    import pandas as pd

    df = frame.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns=RENAMES)
    df = df[(df["segment"] != "STAFF") & (df["description"] != "Staff")
            & (df["sales_person"] != "SBP0001")]
    branch_map = pd.DataFrame(branches, columns=["brn_code", "staff_branch"])
    df = df.merge(branch_map, left_on="unit_code", right_on="brn_code", how="left")
    df["sales_person"] = df["sales_person"].replace(SALE_CODE_FIXES)
    code = df["sales_person"].str.strip()
    when = pd.to_datetime(df["drawdown_date"], errors="coerce")
    keep = code.notna() & (when.dt.year == year) & (when.dt.month <= month)
    out = {}
    for seller, amount, in_month in zip(code[keep], df.loc[keep, "net_drawdown"],
                                        when[keep].dt.month):
        if seller in ZEROED_TO_JUNE and in_month <= 6:
            continue
        value = pd.to_numeric(amount, errors="coerce")
        if pd.isna(value):
            continue
        key = seller.upper()
        out[key] = out.get(key, 0.0) + float(value)
    return out


def net_drawdowns_by_seller(as_at, timeout_ms=120_000):
    """{CODE: net drawdowns} January to ``as_at``'s month, or None while it is
    read in the background (see feed_cache)."""
    from .feed_cache import cached

    def compute():
        import pandas as pd

        names, rows, branches = _rows(as_at.year, timeout_ms)
        return net_by_seller(pd.DataFrame(rows, columns=names), branches,
                             as_at.year, as_at.month)

    return cached(f"weighted_net_drawdowns:{as_at.year}-{as_at.month:02d}", compute)
