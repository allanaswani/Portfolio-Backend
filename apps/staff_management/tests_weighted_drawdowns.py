"""Drawdowns are the weighted sales report's net_drawdown_table.

Checked once against the report's own process_daily_drawdown_dataframe and
net_drawdown_amount on 2,500 random loans: equal for every seller.
"""
import datetime as dt

import pandas as pd
from django.test import SimpleTestCase

from .weighted_sales_drawdowns import net_by_seller


class NetDrawdownTests(SimpleTestCase):
    def test_the_reports_rules(self):
        sep = dt.datetime(2026, 9, 3)
        rows = [
            ("GOO3620 ", "MASS", "Loan", 20, 100.0, sep),    # counted, space stripped
            ("GOO3620", "STAFF", "Loan", 20, 50.0, sep),     # staff segment
            ("GOO3620", "MASS", "Staff", 20, 50.0, sep),     # staff description
            ("SBP0001", "MASS", "Loan", 20, 50.0, sep),      # SBP0001
            ("GOO3620", "MASS", "Loan", 10, 10.0, sep),      # branch listed twice: twice
            (None, "MASS", "Loan", 20, 70.0, sep),           # no salesperson: nobody's
            ("GOO3620", "MASS", "Loan", 20, 900.0, dt.datetime(2026, 10, 1)),  # October
        ]
        frame = pd.DataFrame([{"SALESPERSON": a, "CUSTOMER_SEGMENT": b, "DESCRIPTION": c,
                               "UNIT_CODE": d, "NET_DRAWDOWN": e, "DRAWDOWN_DT": f}
                              for a, b, c, d, e, f in rows])
        got = net_by_seller(frame, [(10, "X"), (10, "X"), (20, "Y")], 2026, 9)
        self.assertEqual(got, {"GOO3620": 120.0})
