"""Regression test for duplicate allocation rows inflating deposit movement.

``retail_allocated_portfolio`` has no unique key on ``cust_id``, so joining it
to ``daily_balance_movement`` repeated each customer's balances once per
allocation row. The branch dashboard sums those rows into the "Dep. YTD
Movement" tile, which is how a branch with a KSh 785M book reported KSh 4.86B
of YTD movement.

Both tables are ETL-owned (managed = False) and are created by hand here.
"""
from django.db import connection
from django.test import TestCase

from core.date_utils import py


class RapFanOutTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute(f"""CREATE TABLE IF NOT EXISTS daily_balance_movement (
                cust_cif integer, full_name text, rm_code text, brn_code integer,
                customer_segment text, yester_1_bal numeric, yester_2_bal numeric,
                dec_{py}_bal numeric)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id integer, sales_code text, rm_name text, branch integer,
                updated_at timestamptz)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS hf_customer (
                cust_id integer, branch text, branch_code text)""")

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("TRUNCATE daily_balance_movement, retail_allocated_portfolio, hf_customer")
            # Two customers, each +100 YTD (200 today vs 100 last December).
            cur.execute(f"""INSERT INTO daily_balance_movement
                (cust_cif, full_name, rm_code, brn_code, customer_segment,
                 yester_1_bal, yester_2_bal, dec_{py}_bal) VALUES
                (1,'CUST ONE','3914',250,'PB',200,150,100),
                (2,'CUST TWO','3914',250,'PB',200,150,100)""")
            # Customer 1 carries THREE allocation rows — the multiplier.
            cur.execute("""INSERT INTO retail_allocated_portfolio
                (cust_id, sales_code, rm_name, branch, updated_at) VALUES
                (1,'3914','Tony Cherono',250,'2026-01-01'),
                (1,'3914','Tony Cherono',250,'2026-06-01'),
                (1,'3914','Tony Cherono',250,'2026-08-01'),
                (2,'3914','Tony Cherono',250,'2026-01-01')""")
            cur.execute("""INSERT INTO hf_customer (cust_id, branch, branch_code)
                VALUES (1,'RONGAI BRANCH','250'),(2,'RONGAI BRANCH','250')""")

    def test_ytd_movement_counts_each_customer_once(self):
        # Run the view's query through the same code path, with the branch
        # resolution stubbed out (auth/profile is not what is under test).
        from unittest import mock
        from apps.branch_portfolio import views

        class _Profile:
            branch = "RONGAI BRANCH"

        with mock.patch.object(views, "_get_profile", return_value=_Profile()), \
             mock.patch.object(views, "_branch_filter", return_value="RONGAI BRANCH"):
            request = mock.Mock(user=mock.Mock())
            rows = views.BranchRMDepositMovementYTDView().get(request).data

        self.assertEqual(len(rows), 1, rows)          # one RM, not one row per allocation
        row = rows[0]
        self.assertEqual(int(row["yester_1_bal"]), 400)   # 2 customers × 200
        self.assertEqual(int(row["dec_bal"]), 200)        # 2 customers × 100
        self.assertEqual(int(row["ytd_movement"]), 200)   # not 400 (customer 1 counted 3×)

    def test_top_inflow_lists_each_customer_once(self):
        from unittest import mock
        from apps.branch_portfolio import views

        class _Profile:
            branch = "RONGAI BRANCH"

        with mock.patch.object(views, "_get_profile", return_value=_Profile()), \
             mock.patch.object(views, "_branch_filter", return_value="RONGAI BRANCH"):
            request = mock.Mock(user=mock.Mock())
            rows = views.BranchTopInflowDTDView().get(request).data

        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r["cust_cif"] for r in rows}), 2)
