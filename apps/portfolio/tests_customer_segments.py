"""customer_per_segment/ — the RM's customers grouped by banking segment.

The donut on /rm-portfolio rendered three slices all labelled "Unknown". Three
faults stacked: the endpoint grouped on retail_allocated_portfolio.main_segment
(nearly always empty), returned it under a key no caller reads, and counted
allocation ROWS rather than customers so a reallocated customer counted twice.

Both tables are ETL-owned (managed = False), so they are created by hand — the
same approach as apps/branch_portfolio/tests_rap_fanout.py.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from apps.portfolio.models import Profile

SALES_CODE = "SEGTEST1"


class CustomerPerSegmentTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS hf_customer (
                cust_id integer, banking_segment text, segment text,
                branch text, branch_code text)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id integer, sales_code text, rm_name text, branch integer,
                main_segment text, updated_at timestamptz)""")

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="segrm", password="x", email="segrm@hfcb.co.ke")
        Profile.objects.update_or_create(
            user_id=user.id, defaults={"sales_code": SALES_CODE})
        self.client = APIClient()
        self.client.force_authenticate(user=user)

        with connection.cursor() as cur:
            cur.execute("TRUNCATE hf_customer, retail_allocated_portfolio")
            # Three customers: one with banking_segment, one carrying only
            # `segment`, one with neither (whitespace, which is not a segment).
            cur.execute("""INSERT INTO hf_customer
                (cust_id, banking_segment, segment) VALUES
                (9001, 'STANDARD', 'STANDARD'),
                (9002, NULL,       'SMALL ENTERPRISES'),
                (9003, '   ',      NULL)""")
            # 9001 is allocated THREE times — the fan-out. main_segment is left
            # NULL throughout, which is how prod actually looks and why the old
            # GROUP BY produced nameless slices.
            cur.execute("""INSERT INTO retail_allocated_portfolio
                (cust_id, sales_code, updated_at) VALUES
                (9001, %s, '2026-01-01'),
                (9001, %s, '2026-06-01'),
                (9001, %s, '2026-08-01'),
                (9002, %s, '2026-01-01'),
                (9003, %s, '2026-01-01')""", [SALES_CODE] * 5)

    def _rows(self):
        r = self.client.get("/portfolio/customer_per_segment/")
        self.assertEqual(r.status_code, 200, r.content)
        return {row["segment"]: row["count"] for row in r.json()}

    def test_segments_come_back_named(self):
        rows = self._rows()
        self.assertIn("STANDARD", rows)
        self.assertIn("SMALL ENTERPRISES", rows)

    def test_segment_falls_back_to_the_other_column(self):
        """banking_segment and segment are populated by different loaders, so a
        customer carrying only one of them still has a segment."""
        self.assertEqual(self._rows().get("SMALL ENTERPRISES"), 1)

    def test_a_customer_with_no_segment_is_named_not_blank(self):
        """Whitespace is not a segment. It is what became the nameless slice."""
        rows = self._rows()
        self.assertEqual(rows.get("Unassigned"), 1)
        self.assertNotIn("", rows)
        self.assertNotIn("   ", rows)

    def test_a_reallocated_customer_is_counted_once(self):
        """9001 has three allocation rows. COUNT("cust_id") over the raw table
        called that three customers — the fan-out that inflated the tiles."""
        self.assertEqual(self._rows().get("STANDARD"), 1)

    def test_the_counts_total_the_customers(self):
        self.assertEqual(sum(self._rows().values()), 3)

    def test_another_rms_customers_are_not_counted(self):
        with connection.cursor() as cur:
            cur.execute("""INSERT INTO hf_customer (cust_id, banking_segment)
                           VALUES (9004, 'ULTIMATE')""")
            cur.execute("""INSERT INTO retail_allocated_portfolio
                           (cust_id, sales_code, updated_at)
                           VALUES (9004, 'SOMEBODYELSE', '2026-01-01')""")
        rows = self._rows()
        self.assertNotIn("ULTIMATE", rows)
        self.assertEqual(sum(rows.values()), 3)

    def test_the_keys_the_frontend_reads(self):
        r = self.client.get("/portfolio/customer_per_segment/")
        row = r.json()[0]
        self.assertIn("segment", row)
        self.assertIn("count", row)
        # The old key is retained for anything still reading it, and now
        # carries the real value instead of a blank.
        self.assertEqual(row["main_segment"], row["segment"])

    def test_biggest_segment_first(self):
        with connection.cursor() as cur:
            cur.execute("""INSERT INTO hf_customer (cust_id, banking_segment)
                           VALUES (9005, 'SMALL ENTERPRISES'),
                                  (9006, 'SMALL ENTERPRISES')""")
            cur.execute("""INSERT INTO retail_allocated_portfolio
                           (cust_id, sales_code, updated_at) VALUES
                           (9005, %s, '2026-01-01'), (9006, %s, '2026-01-01')""",
                        [SALES_CODE] * 2)
        r = self.client.get("/portfolio/customer_per_segment/")
        self.assertEqual(r.json()[0]["segment"], "SMALL ENTERPRISES")
        self.assertEqual(r.json()[0]["count"], 3)
