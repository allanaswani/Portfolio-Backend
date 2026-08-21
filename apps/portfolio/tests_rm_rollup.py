"""Regression tests for the RM roll-up.

Guards the two defects that made the RM lists show duplicate RMs and inflated
money columns: join fan-out on duplicate ``retail_allocated_portfolio`` rows,
and grouping that split one RM across several ``rap.branch`` / name variants.

The two source tables are ETL-owned (``managed = False``), so they are created
by hand in the test database rather than by a migration.
"""
from django.db import connection
from django.test import TestCase

from .rm_rollup import fetch_rm_rollup


class RmRollupTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hf_customer (
                    cust_id numeric PRIMARY KEY,
                    total_revenue numeric,
                    total_depost_balance numeric,
                    total_loans numeric,
                    branch text
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                    cust_id integer,
                    sales_code text,
                    rm_name text,
                    branch integer,
                    updated_at timestamptz
                )""")

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("TRUNCATE hf_customer, retail_allocated_portfolio")
            # Five customers in RONGAI (100 deposits each) + one in THIKA.
            cur.execute("""
                INSERT INTO hf_customer VALUES
                  (1, 10, 100, 1000, 'RONGAI BRANCH'),
                  (2, 10, 100, 1000, 'RONGAI BRANCH'),
                  (3, 10, 100, 1000, 'RONGAI BRANCH'),
                  (4, 10, 100, 1000, 'RONGAI BRANCH'),
                  (9, 10, 100, 1000, 'RONGAI BRANCH'),
                  (5, 10, 100, 1000, 'THIKA BRANCH')
            """)
            cur.execute("""
                INSERT INTO retail_allocated_portfolio VALUES
                  -- one RM, but three different rap.branch values and a name
                  -- with trailing whitespace: used to become several rows
                  (1, '3914', 'Tony Cherono',  250, '2026-01-01'),
                  (2, '3914', 'Tony Cherono ', 100, '2026-01-01'),
                  (3, '3914', 'Tony Cherono',  500, '2026-01-01'),
                  -- customer 4 has two allocation rows: used to be counted twice
                  (4, '3914', 'Tony Cherono',  250, '2026-01-01'),
                  (4, '3914', 'Tony Cherono',  250, '2026-06-01'),
                  (5, '3950', 'Faith Minoo',   500, '2026-01-01')
                  -- customer 9 has no allocation row at all
            """)

    @staticmethod
    def _rms(rows):
        return [r for r in rows if r["sales_code"] or r["rm_name"]]

    def test_one_row_per_rm_despite_branch_and_name_variants(self):
        rms = self._rms(fetch_rm_rollup(branch="RONGAI BRANCH"))
        self.assertEqual(len(rms), 1)
        self.assertEqual(rms[0]["sales_code"], "3914")
        self.assertEqual(rms[0]["rm_name"], "Tony Cherono")

    def test_duplicate_allocation_rows_do_not_double_count(self):
        rm = self._rms(fetch_rm_rollup(branch="RONGAI BRANCH"))[0]
        self.assertEqual(int(rm["customers"]), 4)
        self.assertEqual(int(rm["total_deposit_balance"]), 400)
        self.assertEqual(int(rm["total_loans"]), 4000)
        self.assertEqual(int(rm["total_revenue"]), 40)

    def test_unallocated_customers_kept_as_a_single_unnamed_bucket(self):
        rows = fetch_rm_rollup(branch="RONGAI BRANCH")
        bucket = [r for r in rows if not r["sales_code"] and not r["rm_name"]]
        self.assertEqual(len(bucket), 1)
        self.assertEqual(int(bucket[0]["total_deposit_balance"]), 100)
        # ...so the rows still reconcile to the branch's five customers.
        self.assertEqual(sum(int(r["total_deposit_balance"]) for r in rows), 500)

    def test_branch_filter_excludes_other_branches(self):
        codes = {r["sales_code"] for r in fetch_rm_rollup(branch="RONGAI BRANCH")}
        self.assertNotIn("3950", codes)

    def test_branch_label_is_the_rms_dominant_branch(self):
        rows = fetch_rm_rollup(branch="RONGAI BRANCH", with_branch_label=True)
        rm = self._rms(rows)[0]
        self.assertEqual(rm["rm_branch"], "RONGAI BRANCH")
        bucket = [r for r in rows if not r["sales_code"]][0]
        self.assertIsNone(bucket["rm_branch"])

    def test_org_wide_rollup_returns_every_rm_once(self):
        rms = self._rms(fetch_rm_rollup())
        self.assertEqual(len(rms), 2)
        self.assertEqual({r["sales_code"] for r in rms}, {"3914", "3950"})
