"""Guard: branch queries must scope on the customer set, never on branch_code.

``hf_customer.branch_code`` is NOT 1:1 with ``branch``. The codes carried by one
branch's customers are also carried by every other branch's, so::

    brn_code::text IN (SELECT DISTINCT branch_code FROM hf_customer
                       WHERE branch ILIKE %s)

silently resolves to the entire bank. Measured on production, 25 Aug 2026, for
MOMBASA BRANCH: that subquery matched **32 branches** and returned
**KSh 60.26B of the bank's KSh 60.52B** in deposits — 99.6% of the book.

The visible symptom was a branch dashboard reporting a YTD deposit *movement*
(KSh 4.72B) twenty times larger than its own deposit *book* (KSh 232.12M), and
a loan movement (KSh 3.06B) larger than its loan book (KSh 1.68B). Both figures
were in fact the whole bank's movement. The Top Inflow/Outflow tables have the
same scoping and list customer names, so the same bug also showed one branch's
manager customers belonging to other branches — which is exactly what
``_branch_filter``'s authorisation checks exist to prevent.

Every table involved carries a customer key (``cust_cif``, or ``cust_id`` on
``revenue``), so the fix is to scope on the customer set — the same population
``BranchDashboardSummaryView`` and ``BranchNPLSummaryView`` already use. That is
why those two tiles were right while the rest were not.

These models are all ``managed=False`` warehouse mirrors, so there are no test
tables to populate and no way to assert on real rows here. This guard is
therefore static: it reads the view source and fails if the old pattern comes
back — the same approach used for the segment-predicate drift test.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

VIEWS = Path(__file__).resolve().parent / "views.py"

# The exact shape that caused the bug.
BRANCH_CODE_SUBQUERY = re.compile(
    r"branch_code\s+FROM\s+hf_customer\s+WHERE\s+branch\s+ILIKE", re.IGNORECASE)

# What every branch-scoped raw query should look like now.
CUSTOMER_SUBQUERY = re.compile(
    r"cust_(?:cif|id)\s+IN\s*\(\s*\n\s*SELECT\s+cust_id\s+FROM\s+hf_customer\s+"
    r"WHERE\s+branch\s+ILIKE\s+%s", re.IGNORECASE)


class BranchScopingTests(SimpleTestCase):
    def setUp(self):
        self.source = VIEWS.read_text(encoding="utf-8")

    def test_no_query_scopes_on_branch_code(self):
        """branch_code resolves to the whole bank — see the module docstring."""
        hits = BRANCH_CODE_SUBQUERY.findall(self.source)
        self.assertEqual(
            hits, [],
            "apps/branch_portfolio/views.py scopes on hf_customer.branch_code "
            "again. That column is not 1:1 with branch, so the query returns "
            "the whole bank. Scope on the customer set instead:\n"
            "    cust_cif IN (SELECT cust_id FROM hf_customer WHERE branch ILIKE %s)",
        )

    def test_every_branch_scoped_query_uses_the_customer_set(self):
        """All ten raw queries carry the corrected predicate."""
        self.assertEqual(
            len(CUSTOMER_SUBQUERY.findall(self.source)), 10,
            "expected all 10 branch-scoped raw queries to filter on the customer "
            "set; a query was added, removed, or reverted",
        )

    def test_the_customer_key_matches_each_table(self):
        """``revenue`` keys on cust_id; the movement tables key on cust_cif.
        Using the wrong one silently returns nothing rather than erroring."""
        revenue_block = re.search(
            r"FROM revenue\s*\n\s*WHERE\s+(cust_\w+)", self.source, re.IGNORECASE)
        self.assertIsNotNone(revenue_block, "revenue query not found")
        self.assertEqual(revenue_block.group(1), "cust_id")

        for table in ("daily_balance_movement", "loan_daily_balance_movement"):
            self.assertNotIn(
                f"FROM {table}\n            WHERE cust_id IN", self.source,
                f"{table} keys on cust_cif, not cust_id",
            )
