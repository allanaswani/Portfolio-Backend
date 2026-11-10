"""New Customers per seller, as weighted_sales_daily_report.py counts them.

The desk's New Customers figure is that report's new_customers_value_table:
``daily_sales_accounts_with_cto`` (accounts opened this year), processed by its
``process_daily_accounts_dataframe`` and filtered at line 3995. The card used to
count ``accounts.opened_by`` - 104 against the desk's 86 for one RM on the
September 2026 proof. This follows the report:

1. ``select * from daily_sales_accounts_with_cto where acc_open_date >= the year``,
   columns lower-cased and the report's renames (dec_23_bal, curr_24_bal,
   total_account_before_2024);
2. spaces out of ``sale_code`` and its four hand corrections;
3. STAFF and INTERNAL ACCOUNTS segments out; blanks to 0;
4. new = no account before this year; funded = cust_cto > 0 or this year's
   balance > 0;
5. a customer counts once, on its FIRST row in the table's order (``duplicated``),
   so a customer whose first row is a closed or unfunded account is not counted;
6. funded, not CLOSED, new, first row; counted by the month the customer opened,
   January to the card's month;
7. ``zero_out_return_salespersons_in_same_role``: DSR309's January-June are nought.

Funded is today's balance, as in the report, so a closed month read later can
differ slightly from the run the desk copied.
"""
from __future__ import annotations

import datetime

SALE_CODE_FIXES = {"AL3116": "AKL3116", "SC3568": "SJC3568", "PK3453": "PMK3453",
                   "AOL3199": "AL3199"}
RENAMES = {"dec_23_bal": "prev_year_dec_bal", "curr_24_bal": "current_year_bal",
           "total_account_before_2024": "total_accounts_before_current_year"}
#: zero_out_return_salespersons_in_same_role: these codes' months up to June are nought.
ZEROED_TO_JUNE = {"DSR309"}


def _rows(year, timeout_ms):
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {_limit(timeout_ms)}")
        # ctid: the table's own order, which is the order the report's unordered
        # select returns it in, and step 5 keeps a customer's first row.
        cur.execute("SELECT * FROM daily_sales_accounts_with_cto "
                    "WHERE acc_open_date >= %s ORDER BY ctid",
                    [datetime.date(year, 1, 1)])
        names = [d[0] for d in cur.description]
        return names, cur.fetchall()


def count_by_seller(frame, year, month):
    """The report's count over a frame of the table → {SALES CODE: customers}."""
    import numpy as np
    import pandas as pd

    df = frame.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns=RENAMES)
    df["sale_code"] = df["sale_code"].astype(str).str.replace(" ", "", regex=False)
    df["sale_code"] = df["sale_code"].replace(SALE_CODE_FIXES)
    df = df[(df["customer_segment"] != "STAFF")
            & (df["customer_segment"] != "INTERNAL ACCOUNTS")]
    df = df.fillna(0)
    new = np.where(df["total_accounts_before_current_year"] == 0, "Y", "N")
    funded = np.where((pd.to_numeric(df["cust_cto"], errors="coerce").fillna(0) > 0)
                      | (pd.to_numeric(df["current_year_bal"], errors="coerce")
                         .fillna(0) > 0), "F", "N")
    first = ~df["cust_cif"].duplicated()
    opened = pd.to_datetime(df["cust_open_date"], errors="coerce")
    keep = ((funded == "F") & (df["account_status"] != "CLOSED") & (new == "Y")
            & first & (opened.dt.year == year) & (opened.dt.month <= month))
    counted = df.loc[keep, "sale_code"].str.strip()
    months = opened[keep].dt.month
    out = {}
    for code, opened_in in zip(counted, months):
        if code in ZEROED_TO_JUNE and opened_in <= 6:
            continue
        out[code.upper()] = out.get(code.upper(), 0) + 1
    return out


def count_by_branch(frame, year, month):
    """The report's branch_new_customers_table (line 11004): the same customers
    as :func:`count_by_seller`, by brn_code, 210 counted as 19 (Hurlingham), and
    no seller zeroed → {brn_code: customers}."""
    import numpy as np
    import pandas as pd

    df = frame.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns=RENAMES)
    df = df[(df["customer_segment"] != "STAFF")
            & (df["customer_segment"] != "INTERNAL ACCOUNTS")]
    df = df.fillna(0)
    new = np.where(df["total_accounts_before_current_year"] == 0, "Y", "N")
    funded = np.where((pd.to_numeric(df["cust_cto"], errors="coerce").fillna(0) > 0)
                      | (pd.to_numeric(df["current_year_bal"], errors="coerce")
                         .fillna(0) > 0), "F", "N")
    first = ~df["cust_cif"].duplicated()
    opened = pd.to_datetime(df["cust_open_date"], errors="coerce")
    keep = ((funded == "F") & (df["account_status"] != "CLOSED") & (new == "Y")
            & first & (opened.dt.year == year) & (opened.dt.month <= month))
    out = {}
    for code in pd.to_numeric(df.loc[keep, "brn_code"], errors="coerce"):
        if pd.isna(code):
            continue
        code = 19 if int(code) == 210 else int(code)
        out[code] = out.get(code, 0) + 1
    return out


def new_customers_by_branch(year, month, timeout_ms=120_000):
    """{brn_code: new customers} January to ``month``, or None while it is read
    in the background (see feed_cache)."""
    from .feed_cache import cached

    def compute():
        import pandas as pd

        names, rows = _rows(year, timeout_ms)
        return count_by_branch(pd.DataFrame(rows, columns=names), year, month)

    return cached(f"weighted_new_customers_branch:{year}-{month:02d}", compute)


def new_customers_by_seller(as_at, timeout_ms=120_000):
    """{SALES CODE: new customers} from 1 January to ``as_at``'s month, or None
    while it is read in the background (see feed_cache)."""
    from .feed_cache import cached

    def compute():
        import pandas as pd

        names, rows = _rows(as_at.year, timeout_ms)
        return count_by_seller(pd.DataFrame(rows, columns=names),
                               as_at.year, as_at.month)

    return cached(f"weighted_new_customers:{as_at.year}-{as_at.month:02d}", compute)


# ── Cross-sell new CASA accounts (focus accounts) ─────────────────────────────
#: process_daily_accounts_dataframe forces these products to focus.
FORCED_FOCUS = {31805, 31806, 31807}


def _lookups(timeout_ms):
    """The two tables the report merges before counting: product_mapping, and
    branch_name_map (brn_code, staff_branch off branch_final_employee_dmc_data,
    one row per employee, so a branch can repeat - and the report does not
    de-duplicate it before merging)."""
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {_limit(timeout_ms)}")
        cur.execute("SELECT code AS prod_id, focus FROM product_mapping")
        products = cur.fetchall()
        cur.execute("SELECT brn_code, staff_branch FROM branch_final_employee_dmc_data")
        branches = cur.fetchall()
    return products, branches


def focus_by_seller(frame, products, branches, year, month):
    """The report's funded focus accounts (line 3877) → {SALES CODE: accounts}:
    funded (balance > 0 or the account's CTO > 0), a focus product, not CLOSED,
    by the month the account opened, January to ``month``. The product and branch
    tables are merged as the report merges them, so a row listed twice in either
    counts its accounts twice, as in the report."""
    import pandas as pd

    df = frame.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns=RENAMES)
    df["sale_code"] = df["sale_code"].astype(str).str.replace(" ", "", regex=False)
    df["sale_code"] = df["sale_code"].replace(SALE_CODE_FIXES)
    df = df[(df["customer_segment"] != "STAFF")
            & (df["customer_segment"] != "INTERNAL ACCOUNTS")]
    df = df.fillna(0)
    funded = ((pd.to_numeric(df["bal"], errors="coerce").fillna(0) > 0)
              | (pd.to_numeric(df["account_cto"], errors="coerce").fillna(0) > 0))
    df = df.assign(_funded=funded.values)
    mapping = pd.DataFrame(products, columns=["prod_id", "focus"])
    df = df.merge(mapping, on="prod_id", how="left")
    df.loc[df["prod_id"].isin(FORCED_FOCUS), "focus"] = "Y"
    branch_map = pd.DataFrame(branches, columns=["brn_code", "staff_branch"])
    df = df.merge(branch_map, on="brn_code", how="left")
    opened = pd.to_datetime(df["acc_open_date"], errors="coerce")
    keep = (df["_funded"] & (df["focus"] == "Y") & (df["account_status"] != "CLOSED")
            & (opened.dt.year == year) & (opened.dt.month <= month))
    out = {}
    for code, opened_in in zip(df.loc[keep, "sale_code"].str.strip(), opened[keep].dt.month):
        if code in ZEROED_TO_JUNE and opened_in <= 6:
            continue
        out[code.upper()] = out.get(code.upper(), 0) + 1
    return out


def focus_accounts_by_seller(as_at, timeout_ms=120_000):
    """{SALES CODE: funded focus accounts} January to ``as_at``'s month, or None
    while it is read in the background (see feed_cache)."""
    from .feed_cache import cached

    def compute():
        import pandas as pd

        names, rows = _rows(as_at.year, timeout_ms)
        products, branches = _lookups(timeout_ms)
        return focus_by_seller(pd.DataFrame(rows, columns=names), products,
                               branches, as_at.year, as_at.month)

    return cached(f"weighted_focus_accounts:{as_at.year}-{as_at.month:02d}", compute)


def _limit(ms):
    from .feed_cache import timeout

    return timeout(ms)
