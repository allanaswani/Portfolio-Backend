"""Regression tests for join fan-out in the loan-arrears queries.

Every arrears query joined three tables on a NON-unique key:

* ``branch_final_employee_dmc_data`` on ``brn_code`` — one row per EMPLOYEE, so
  each loan was repeated once per member of staff in its branch;
* ``retail_allocated_portfolio`` on ``cust_id`` — the ETL can leave several
  allocation rows per customer;
* ``bank_employee`` on ``bank_id``.

The list endpoint therefore showed the same loan many times, and the Loan
Balance / Arrears Balance / grade-bucket / product figures — which SUM over
that join — were multiplied by the number of matches. With the fixture below
(4 staff, 1 duplicated allocation, 1 duplicated bank_employee row) the old code
turned 2 loans into 24 rows and a 2,000 book into 24,000.

The source tables are ETL-owned, so they are created by hand here.
"""
from django.db import connection
from django.test import TestCase

from services.arrears_managers import (
    LoansArrearsSummaryManager, LoansArrearsDPDBucketSummaryManager,
    LoansProductArrearsSummaryManager, LoansArrearsAccountsListManager,
)

# ``loans_mom_ifrs_movement`` and ``branch_final_employee_dmc_data`` are managed
# Django models, so migrations already created them in the test database; the
# rest are ETL-owned (managed = False) and have to be created here. Every INSERT
# names its columns so it does not depend on physical column order.
DDL = [
    """CREATE TABLE IF NOT EXISTS loans (
        cust_id integer, loan_account_no text, euro_book_balance numeric,
        installment_amount numeric, total_arrears numeric, days_in_arrears integer,
        last_transaction_date date, next_installment_date date, delay_officer text,
        loan_product text, branch integer)""",
    "CREATE TABLE IF NOT EXISTS product_mapping (code integer, product_description text)",
    """CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
        cust_id integer, sales_code text, rm_name text, branch integer,
        updated_at timestamptz)""",
    """CREATE TABLE IF NOT EXISTS hf_customer (
        cust_id integer, latin_surname text, banking_segment text)""",
    "CREATE TABLE IF NOT EXISTS bank_employee (bank_id text, full_name text)",
]

TABLES = ("loans", "loans_mom_ifrs_movement", "product_mapping",
          "retail_allocated_portfolio", "hf_customer",
          "branch_final_employee_dmc_data", "bank_employee")


class ArrearsFanOutTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            for stmt in DDL:
                cur.execute(stmt)

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("TRUNCATE " + ", ".join(TABLES))
            # Two loans in RONGAI (branch code 250): 1,000 book / 100 arrears each.
            cur.execute("""INSERT INTO loans
              (cust_id, loan_account_no, euro_book_balance, installment_amount,
               total_arrears, days_in_arrears, last_transaction_date,
               next_installment_date, delay_officer, loan_product, branch)
              VALUES
              (1,'0500000522',1000,50,100,2,'2026-08-19','2026-09-18','E1','1',250),
              (2,'0460002790',1000,50,100,5,'2026-08-19','2026-09-18','E1','1',250)""")
            # Four staff in that branch — the biggest multiplier.
            cur.execute("""INSERT INTO branch_final_employee_dmc_data
              (brn_code, staff_branch, active, date_update_etl, updated_at) VALUES
              (250,'RONGAI BRANCH',1,'2026-08-01',CURRENT_DATE),
              (250,'RONGAI BRANCH',1,'2026-07-01',CURRENT_DATE),
              (250,'RONGAI BRANCH',0,'2026-06-01',CURRENT_DATE),
              (250,'RONGAI BRANCH',1,'2026-05-01',CURRENT_DATE)""")
            # Customer 1 carries two allocation rows.
            cur.execute("""INSERT INTO retail_allocated_portfolio
              (cust_id, sales_code, rm_name, branch, updated_at) VALUES
              (1,'3914','Tony Cherono',250,'2026-01-01'),
              (1,'3914','Tony Cherono',250,'2026-06-01'),
              (2,'3914','Tony Cherono',250,'2026-01-01')""")
            cur.execute("""INSERT INTO bank_employee (bank_id, full_name)
              VALUES ('E1','Jane Doe'),('E1','Jane Doe')""")
            cur.execute("""INSERT INTO hf_customer (cust_id, latin_surname, banking_segment)
              VALUES (1,'POPOTE NI KWAO','PB'),(2,'REFLEX FOOTWEAR','PB')""")
            cur.execute("INSERT INTO product_mapping (code, product_description) VALUES (1,'MORTGAGE')")
            cur.execute("""INSERT INTO loans_mom_ifrs_movement
              (lns_account, pl_charge, int_adj, eom_date, prev_ifrs, current_ifrs,
               movt_in_ifrs, current_grade, cust_code_strategy, branch2, segment,
               created_at, updated_at)
              VALUES
              ('0500000522',10,2,CURRENT_DATE,1,2,1,'WATCH','1','RONGAI','PERSONAL',NOW(),NOW()),
              ('0460002790',10,2,CURRENT_DATE,1,2,1,'NORMAL','2','RONGAI','PERSONAL',NOW(),NOW())""")

    def test_list_returns_each_loan_once(self):
        m = LoansArrearsAccountsListManager()
        for label, rows in (
            ("all",     m.accounts_in_arrears()),
            ("branch",  m.accounts_in_arrears_by_branch("RONGAI BRANCH")),
            ("rm",      m.accounts_in_arrears_by_rm_code("3914")),
            ("segment", m.accounts_in_arrears_by_segment("PB")),
        ):
            with self.subTest(scope=label):
                self.assertEqual(len(rows), 2)
                self.assertEqual(len({r["loan_account_no"] for r in rows}), 2)

    def test_branch_summary_is_not_multiplied_by_headcount(self):
        s = LoansArrearsSummaryManager().high_level_summary_by_branch("RONGAI BRANCH")
        self.assertEqual(int(s["total_outstanding_loan_amount"]), 2000)
        self.assertEqual(int(s["total_arrears_amount"]), 200)
        self.assertEqual(int(s["customers_in_arrears"]), 2)
        self.assertEqual(int(s["loan_loss"]), 16)  # (10-2) × 2 loans, not × 4 staff

    def test_rm_summary_is_not_multiplied_by_duplicate_allocations(self):
        s = LoansArrearsSummaryManager().high_level_summary_by_rm_code("3914")
        self.assertEqual(int(s["total_outstanding_loan_amount"]), 2000)
        self.assertEqual(int(s["total_arrears_amount"]), 200)

    def test_dpd_buckets_sum_to_the_real_book(self):
        m = LoansArrearsDPDBucketSummaryManager()
        for label, rows in (
            ("all",     m.dpd_bucket_summary()),
            ("branch",  m.dpd_bucket_summary_by_branch("RONGAI BRANCH")),
            ("rm",      m.dpd_bucket_summary_by_rm_code("3914")),
            ("segment", m.dpd_bucket_summary_by_segment("PB")),
        ):
            with self.subTest(scope=label):
                self.assertEqual(int(sum(r["total_outstanding"] for r in rows)), 2000)
                self.assertEqual(int(sum(r["total_arrears"] for r in rows)), 200)

    def test_product_summary_sums_to_the_real_book(self):
        m = LoansProductArrearsSummaryManager()
        for label, rows in (
            ("all",     m.product_arrears_summary()),
            ("branch",  m.product_arrears_summary_by_branch("RONGAI BRANCH")),
            ("rm",      m.product_arrears_summary_by_rm_code("3914")),
            ("segment", m.product_arrears_summary_by_segment("PB")),
        ):
            with self.subTest(scope=label):
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["product_description"], "MORTGAGE")
                self.assertEqual(int(rows[0]["total_arrears_amount"]), 200)
