"""accounts_opened_compare prints the right count for each source and each
rule it drops customers for (seeded rows, the real command)."""
import datetime as dt
import io
from unittest import mock

import pandas as pd
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from .models import StaffEmployeeData
from .tests_weighted_new_customers import row


class AccountsOpenedCompareTests(TestCase):
    def setUp(self):
        StaffEmployeeData.objects.create(
            staff_pf_number=1, staff_name="Mary Kamau", staff_email="m@x", sales_code="MK3445",
            department="Retail", staff_unit="Retail", staff_org_unit="X", job_title="RM",
            employment_date=dt.date(2020, 1, 1), employee_category="front_office")
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS customers (cust_id bigint, open_date date)")
            cur.execute("CREATE TABLE IF NOT EXISTS accounts (cust_id bigint, opened_by varchar(40))")
            cur.execute("DELETE FROM customers; DELETE FROM accounts")
            this_year = dt.date.today().replace(month=1, day=5)
            for cif in (1, 9):
                cur.execute("INSERT INTO customers VALUES (%s, %s)", [cif, this_year])
                cur.execute("INSERT INTO accounts VALUES (%s, 'MK3445')", [cif])

    def test_each_source_and_each_dropped_rule(self):
        sep, oct_ = dt.datetime(2026, 9, 3), dt.datetime(2026, 10, 3)
        frame = pd.DataFrame([
            row("MK 3445", 1, sep), row("MK3445", 1, sep),
            row("MK3445", 2, sep, status="CLOSED"), row("MK3445", 2, sep),
            row("MK3445", 3, sep, cto=0, bal=0), row("MK3445", 4, sep, before=1),
            row("MK3445", 5, sep, segment="STAFF"), row("MK3445", 6, oct_),
        ])
        card = {"perspectives": [{"lines": [
            {"kpi_code": "new_customers", "kpi_name": "New Customers", "ytd_actual": 2, "as_at": "x"},
            {"kpi_code": "deposits", "kpi_name": "Deposits", "ytd_actual": 9}]}]}
        out = io.StringIO()
        with mock.patch("apps.staff_management.weighted_sales_new_customers._rows",
                        return_value=(list(frame.columns), frame.values.tolist())), \
                mock.patch("apps.staff_management.live_scorecard.build_card", return_value=card), \
                mock.patch("services.portfolio_service.rm_new_customers_ytd_list",
                           return_value=[{}, {}, {}]):
            call_command("accounts_opened_compare", "Mary Kamau", "--months", "2026-09", "2026-10",
                         stdout=out)
        text = out.getvalue()
        self.assertIn("Mary Kamau  (MK3445)", text)
        self.assertIn("CARD  New Customers [new_customers]: 2", text)
        self.assertNotIn("Deposits", text)
        # September: customer 1 only; October adds customer 6
        self.assertIn("WEIGHTED RULE (funded, new, not closed, first row): 1 YTD; 1 opened", text)
        self.assertIn("WEIGHTED RULE (funded, new, not closed, first row): 2 YTD; 1 opened", text)
        self.assertIn("NEW-ACCOUNT RETURN, no filters: 5 customers, 7 accounts", text)
        self.assertIn("NEW-ACCOUNT RETURN, no filters: 6 customers, 8 accounts", text)
        self.assertIn("6 customers on the return under MK3445, one reason each", text)
        # 1 and 6 counted; 2's first row is closed; 3 unfunded; 4 existing; 5 staff
        for n, label in ((2, "COUNTED"), (1, "staff / internal"), (1, "already a customer"),
                         (1, "not funded"), (1, "first account is CLOSED"), (0, "first row is another")):
            self.assertRegex(text, rf"\s{n}  {label}")
        self.assertIn("2 distinct customers; its tile shows 3 rows", text)
        self.assertIn("on both sources: 1; only opened_by=MK3445: 1; only sale_code=MK3445 on the return: 5", text)
