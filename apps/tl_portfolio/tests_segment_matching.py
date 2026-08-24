"""Regression tests for TL segment matching.

The TL dashboard rendered real Deposits/Loans but zero Customers, Revenue,
Allocated, Unallocated and Product/Customer because the same segment is stored
under three vocabularies:

  profile.segment            'BUSINESS BANKING'   (also 'SME' for other TLs)
  daily_balance_movement     'SMALL ENTERPRISES'  -> CASE -> 'BUSINESS BANKING'
  hf_customer.banking_segment'SME'

Only the third was compared with equality, so it never matched. Measured on
prod 2026-08-24: 33,336 customers, exact_match 0, LOWER(TRIM(...)) match 0.
"""
import io

from django.db import connection
from django.test import SimpleTestCase, TestCase

from core.segments import (
    canonical_segment, segment_synonyms, segment_params,
    segment_where_sql, segment_q,
)


class CanonicalSegmentTests(SimpleTestCase):
    def test_sme_and_business_banking_are_the_same_segment(self):
        self.assertEqual(canonical_segment("SME"), "BUSINESS BANKING")
        self.assertEqual(canonical_segment("BUSINESS BANKING"), "BUSINESS BANKING")
        self.assertEqual(canonical_segment("SMALL ENTERPRISES"), "BUSINESS BANKING")
        self.assertEqual(canonical_segment("MEDIUM ENTERPRISES"), "BUSINESS BANKING")

    def test_folds_case_and_whitespace(self):
        self.assertEqual(canonical_segment("  sme  "), "BUSINESS BANKING")

    def test_unknown_segment_matches_only_itself(self):
        # 'MORTGAGE BUSINESS' has 10 profiles on prod and no synonyms; it must
        # keep behaving exactly as it does today rather than collapsing.
        self.assertEqual(canonical_segment("MORTGAGE BUSINESS"), "MORTGAGE BUSINESS")
        self.assertEqual(segment_synonyms("MORTGAGE BUSINESS"), ["MORTGAGE BUSINESS"])

    def test_synonyms_are_symmetric(self):
        self.assertEqual(segment_synonyms("SME"), segment_synonyms("BUSINESS BANKING"))

    def test_blank_segment_yields_no_synonyms(self):
        self.assertEqual(segment_synonyms(""), [])
        self.assertEqual(segment_synonyms(None), [])

    def test_params_bind_one_list_per_column(self):
        params = segment_params("SME")
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0], params[1])
        self.assertIn("SME", params[0])
        self.assertIn("BUSINESS BANKING", params[0])


class PredicateDriftTests(SimpleTestCase):
    """The services embed the predicate literally (their query bodies are plain
    strings that may contain braces). Fail loudly if the two ever diverge."""

    FILES = ("services/arrears_managers.py", "services/fixed_deposit_managers.py")

    def test_embedded_predicate_matches_generator(self):
        expected = segment_where_sql("c")
        for path in self.FILES:
            body = io.open(path, encoding="utf-8").read()
            self.assertIn(expected, body, f"{path} predicate drifted from core.segments")
            self.assertNotIn(
                "LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))", body,
                f"{path} still has an equality segment filter",
            )

    def test_placeholder_count_matches_params(self):
        self.assertEqual(segment_where_sql("c").count("%s"), len(segment_params("SME")))


class SegmentMatchSqlTests(TestCase):
    """Runs the real predicate against a fixture shaped like prod."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hf_customer (
                    cust_id numeric PRIMARY KEY,
                    banking_segment text,
                    segment text,
                    total_depost_balance numeric
                )""")

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("TRUNCATE hf_customer")
            cur.execute("""
                INSERT INTO hf_customer VALUES
                  (1, 'SME',   'SMALL ENTERPRISES',  100),
                  (2, 'SME',   'MEDIUM ENTERPRISES', 100),
                  (3, 'PB',    'MASS',               100),
                  (4, '  sme ','SMALL ENTERPRISES',  100)
            """)

    def _count(self, sql, params):
        with connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM hf_customer c WHERE {sql}", params)
            return cur.fetchone()[0]

    def test_old_equality_filter_found_nothing(self):
        # This is what shipped: the exact defect, reproduced.
        self.assertEqual(
            self._count("LOWER(TRIM(c.banking_segment)) = LOWER(TRIM(%s))",
                        ["BUSINESS BANKING"]),
            0,
        )

    def test_business_banking_profile_now_matches_the_sme_rows(self):
        self.assertEqual(
            self._count(segment_where_sql("c"), segment_params("BUSINESS BANKING")),
            3,
        )

    def test_sme_profile_matches_the_same_rows(self):
        # The mirror case: 54 prod profiles are filed as 'SME' rather than
        # 'BUSINESS BANKING'. Both must resolve to one book.
        self.assertEqual(
            self._count(segment_where_sql("c"), segment_params("SME")),
            3,
        )

    def test_other_segments_are_not_swept_in(self):
        self.assertEqual(
            self._count(segment_where_sql("c"), segment_params("PB")),
            1,
        )

    def test_unknown_segment_matches_nothing_rather_than_everything(self):
        self.assertEqual(
            self._count(segment_where_sql("c"), segment_params("MORTGAGE BUSINESS")),
            0,
        )


class SegmentQTests(SimpleTestCase):
    def test_orm_filter_covers_both_columns(self):
        sql = str(segment_q("BUSINESS BANKING"))
        self.assertIn("banking_segment", sql)
        self.assertIn("segment", sql)
        self.assertIn("SME", sql)
