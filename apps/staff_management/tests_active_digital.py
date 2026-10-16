"""Active Customers and Digital Adoption.

Both lines showed a dash with the note that no feed held them. The signed Q3
cards say otherwise and name their own arithmetic:

    Alice Kamau  (SME ARM)  Active Customers   2025 FY 42   +20%  ->  50.4
    Lydia Apanja (PB ARM)   Digital Adoption   2025 FY 197  +50%  -> 287.29

The feed is the lake's own: ``delta.gold_db.active_channels``, mirrored into
Postgres. The first attempt reconstructed the measure from raw transactions
instead, which is how it ended up slow enough to time out - the work had
already been done upstream.

"Active" is TWO consecutive months, which is what the measure of success
says, and what these tests hold the reader to.
"""

import datetime

from django.test import TestCase

from . import active_channels
from .live_scorecard import SOURCES, _two_month_active
from .models import CustomerMonthlyActivity

CODE = "AK4001"
YEAR = 2026


def make_the_book():
    """``retail_allocated_portfolio`` is a warehouse table, so Django does
    not create it and the join would go untested."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id bigint,
                sales_code varchar(100),
                updated_at timestamptz
            )
        """)


def allocate(*cust_ids, code=CODE):
    from django.db import connection

    with connection.cursor() as cur:
        for cust_id in cust_ids:
            cur.execute(
                "INSERT INTO retail_allocated_portfolio "
                "(cust_id, sales_code, updated_at) VALUES (%s, %s, NOW())",
                [cust_id, code])


def active(cust_id, year, month, digital=False):
    CustomerMonthlyActivity.objects.update_or_create(
        cust_id=cust_id, month=datetime.date(year, month, 1),
        defaults={"active": True, "digital_active": digital})


class ReadingTheLakesMonthLabelTests(TestCase):
    """The lake holds the month as text, so it has to be parsed."""

    def test_the_labels_the_feed_actually_uses(self):
        for text, expected in (("Apr-26", datetime.date(2026, 4, 1)),
                               ("Jan-26", datetime.date(2026, 1, 1)),
                               ("Dec-25", datetime.date(2025, 12, 1)),
                               ("mar-26", datetime.date(2026, 3, 1)),
                               ("Sep-2026", datetime.date(2026, 9, 1))):
            with self.subTest(text):
                self.assertEqual(active_channels.parse_month(text), expected)

    def test_a_label_it_cannot_read_is_none_rather_than_a_guess(self):
        for text in ("", None, "April", "13-26", "Xxx-26"):
            with self.subTest(text):
                self.assertIsNone(active_channels.parse_month(text))

    def test_an_unreadable_month_is_reported_not_dropped_quietly(self):
        """A change to the lake's month format would otherwise silently empty
        both lines."""
        _entries, report = active_channels.plan([
            {"trx_month": "Apr-26", "cust_id": 1, "active": 1,
             "digital_active": 1},
            {"trx_month": "QUARTER 2", "cust_id": 2, "active": 1,
             "digital_active": 0},
        ])
        self.assertEqual(report["to_write"], 1)
        self.assertEqual(report["unreadable_month"], ["QUARTER 2"])

    def test_the_lake_rows_become_one_row_per_customer_month(self):
        entries, report = active_channels.plan([
            {"trx_month": "Apr-26", "cust_id": 7, "active": 1,
             "digital_active": 0},
        ])
        self.assertEqual(entries, [{
            "cust_id": 7, "month": datetime.date(2026, 4, 1),
            "active": True, "digital_active": False}])
        self.assertEqual(report["customers"], 1)

    def test_saving_is_idempotent(self):
        entries, _report = active_channels.plan([
            {"trx_month": "Apr-26", "cust_id": 7, "active": 1,
             "digital_active": 0},
        ])
        active_channels.save(entries)
        active_channels.save(entries)
        self.assertEqual(CustomerMonthlyActivity.objects.count(), 1)


class TwoMonthsMeansTwoMonthsTests(TestCase):
    def setUp(self):
        make_the_book()
        allocate(1, 2, 3, 4)

    def test_a_customer_active_in_two_consecutive_months_counts(self):
        active(1, YEAR, 7)
        active(1, YEAR, 8)
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 1)
        # As at the END of the month the pair closes on.
        self.assertEqual(as_at, datetime.date(YEAR, 8, 31))

    def test_a_customer_active_in_only_one_month_does_not(self):
        """This is the whole measure. "Active" on these cards is not
        "transacted at some point"."""
        active(2, YEAR, 8)
        self.assertNotIn(YEAR, _two_month_active(CODE, YEAR))

    def test_two_months_that_are_not_consecutive_do_not_count(self):
        active(3, YEAR, 5)
        active(3, YEAR, 8)
        self.assertNotIn(YEAR, _two_month_active(CODE, YEAR))

    def test_a_pair_that_straddles_a_year_end_closes_in_the_later_year(self):
        active(1, YEAR - 1, 12)
        active(1, YEAR, 1)
        found = _two_month_active(CODE, YEAR)
        self.assertEqual(found[YEAR][0], 1)
        self.assertEqual(found[YEAR][1], datetime.date(YEAR, 1, 31))

    def test_somebody_elses_customer_is_not_counted(self):
        allocate(99, code="OTHER1")
        active(99, YEAR, 7)
        active(99, YEAR, 8)
        self.assertNotIn(YEAR, _two_month_active(CODE, YEAR))

    def test_the_latest_pair_with_activity_is_the_one_reported(self):
        """A figure read in the first days of a month must not collapse to
        nought because the new month has barely started."""
        active(1, YEAR, 6)
        active(1, YEAR, 7)
        active(2, YEAR, 7)
        active(2, YEAR, 8)
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 1)
        self.assertEqual(as_at, datetime.date(YEAR, 8, 31))

    def test_both_years_come_back_from_one_read(self):
        """The figure is this year's and the rate target's base is last
        year's. One read answers both."""
        active(1, YEAR, 7)
        active(1, YEAR, 8)
        active(1, YEAR - 1, 4)
        active(1, YEAR - 1, 5)
        found = _two_month_active(CODE, YEAR)
        self.assertEqual(found[YEAR][0], 1)
        self.assertEqual(found[YEAR - 1][0], 1)
        self.assertEqual(found[YEAR - 1][1], datetime.date(YEAR - 1, 5, 31))

    def test_an_absent_mirror_says_so_rather_than_reporting_nought(self):
        """A read that failed and a customer who did nothing are different
        statements, and the card says which."""
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("DROP TABLE sc_customer_monthly_activity CASCADE")
        found = _two_month_active(CODE, YEAR)
        self.assertIn("error", found)
        self.assertIn("load_active_channels", found["error"])


class DigitalAdoptionTests(TestCase):
    def setUp(self):
        make_the_book()
        allocate(1, 2)

    def test_only_digital_activity_counts_for_digital_adoption(self):
        active(1, YEAR, 7, digital=True)
        active(1, YEAR, 8, digital=True)
        active(2, YEAR, 7)
        active(2, YEAR, 8)
        self.assertEqual(
            _two_month_active(CODE, YEAR, digital=True)[YEAR][0], 1)
        # Both are active; only one of them is digital.
        self.assertEqual(_two_month_active(CODE, YEAR)[YEAR][0], 2)

    def test_digital_in_one_month_only_is_not_two_months_digital(self):
        active(1, YEAR, 7, digital=True)
        active(1, YEAR, 8, digital=False)
        self.assertNotIn(YEAR, _two_month_active(CODE, YEAR, digital=True))
        # They are still ACTIVE in both, which is a different line.
        self.assertEqual(_two_month_active(CODE, YEAR)[YEAR][0], 1)


class WhatTheMirrorCoversTests(TestCase):
    """So a blank line can be told from a stale load without guessing."""

    def test_it_reports_the_span_and_the_pairs_it_can_answer(self):
        for month in (1, 2, 3):
            active(1, YEAR, month)
        active(1, YEAR, 8)          # an island, with no month before it
        span = active_channels.coverage()
        self.assertEqual(span["first_month"], datetime.date(YEAR, 1, 1))
        self.assertEqual(span["last_month"], datetime.date(YEAR, 8, 1))
        self.assertEqual(
            span["complete_pairs"],
            [datetime.date(YEAR, 2, 1), datetime.date(YEAR, 3, 1)])
        self.assertEqual(span["latest_pair"], datetime.date(YEAR, 3, 1))

    def test_a_single_month_can_answer_no_pair_at_all(self):
        active(1, YEAR, 4)
        span = active_channels.coverage()
        self.assertEqual(span["complete_pairs"], [])
        self.assertIsNone(span["latest_pair"])


class TheyAreNoLongerPendingTests(TestCase):
    def test_both_lines_read_a_feed_now(self):
        for code, key in (("active_customers", "active_customers"),
                          ("digital_adoption", "digital_adoption")):
            with self.subTest(code):
                source = SOURCES[code]
                self.assertEqual(source.actual_key, key)
                self.assertFalse(source.pending)
                # Counts, so the target is pro-rated as a count.
                self.assertTrue(source.counted)

    def test_the_branch_line_is_left_on_the_template(self):
        """``bo_active_customers`` is the BRANCH's count, and a branch manager
        has no allocated book for this reader to count over."""
        self.assertTrue(SOURCES["bo_active_customers"].pending)

    def test_the_target_is_a_rate_on_the_persons_own_prior_year(self):
        from .scorecard_automation.models import ScRoleKpiMapping

        rows = ScRoleKpiMapping.objects.filter(
            kpi_code__in=("active_customers", "digital_adoption"))
        self.assertTrue(rows.exists())
        for row in rows:
            with self.subTest(f"{row.role_code}/{row.kpi_code}"):
                self.assertEqual(row.target_basis, "rate_on_base")
                expected = 0.20 if row.kpi_code == "active_customers" else 0.50
                self.assertAlmostEqual(float(row.kpi_target), expected)
                self.assertIn("last_year", row.target_base)

    def test_alices_card_reproduces(self):
        """42 active customers in 2025, +20%, is the 50.4 on her card."""
        self.assertAlmostEqual(42 * 1.20, 50.4)

    def test_lydias_digital_card_reproduces(self):
        """197 digital customers in 2025, +50%, is 295.5 - her card says
        287.29, which is 145.8% of her base.

        The stated rule is used rather than the arithmetic of one cell: 50% is
        what the card SAYS, and a cell two per cent off it carries a hand
        adjustment nobody else can be held to. This records the discrepancy
        rather than hiding it."""
        self.assertAlmostEqual(197 * 1.50, 295.5)
        self.assertAlmostEqual(round(287.29 / 197, 3), 1.458)


class ACardOnlyReadsItsOwnFeedsTests(TestCase):
    """Every reader used to run for every card - about twenty warehouse
    queries each time, most for lines the card does not carry."""

    CODE = "CMM4236"

    def setUp(self):
        from .models import BranchEmployeeDmcData

        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4236, staff_name="Charles Muchiri",
            sales_code=self.CODE, staff_role="SME RM", staff_branch="Rehani",
            staff_unit="Rehani", active=1)

    def test_a_card_does_not_read_a_feed_no_line_of_it_uses(self):
        from unittest.mock import patch

        from . import live_scorecard as module

        seen = {}
        real = module.live_actuals

        def spy(*args, **kwargs):
            seen["wanted"] = kwargs.get("wanted")
            return real(*args, **kwargs)

        with patch.object(module, "live_actuals", spy):
            card = module.build_card(self.CODE)

        self.assertTrue(card["has_card"])
        wanted = seen["wanted"]
        self.assertIsNotNone(wanted, "build_card must say what it needs")
        everything = {source.actual_key for source in module.SOURCES.values()
                      if source.actual_key}
        self.assertLess(len(wanted), len(everything))
        self.assertNotIn("tills_volume", wanted)

    def test_every_reader_named_in_the_base_map_is_a_real_reader(self):
        """The one that bit. ``last_year_loan_loss`` was mapped to
        "loan_loss", and the reader that produces it is registered as
        "_last_year_loan_loss" - so the skip removed it from every card and
        the Loan Loss line reported "no base to work from".

        Checking that the base NAME is in the map was not enough: the name
        was right and the reader it pointed at did not exist.
        """
        import pathlib as _pathlib
        import re

        from .live_scorecard import _READERS_BEHIND_A_BASE

        source = _pathlib.Path(
            __file__).with_name("live_scorecard.py").read_text(
                encoding="utf-8")
        registered = set()
        for call in re.finditer(r"attempt\(\s*(\(|\[)?([^)]*?)(\)|\])?\s*,",
                                source):
            registered |= set(
                re.findall(r'"([a-z_][a-z0-9_]*)"', call.group(2)))

        self.assertTrue(registered, "no attempt() calls were found at all")
        for base, readers in _READERS_BEHIND_A_BASE.items():
            for reader in readers:
                with self.subTest(f"{base} -> {reader}"):
                    self.assertIn(
                        reader, registered,
                        f"{base} names {reader}, which no attempt() "
                        f"registers - the skip will remove it")

    def test_every_rate_target_base_in_use_has_a_reader_behind_it(self):
        """Otherwise the skip silently removes the base and the line reports
        that it has no target."""
        from .live_scorecard import _READERS_BEHIND_A_BASE
        from .scorecard_automation.models import ScRoleKpiMapping

        in_use = {
            (row.target_base or "").strip()
            for row in ScRoleKpiMapping.objects.filter(
                target_basis="rate_on_base")
            if (row.target_base or "").strip()
        }
        self.assertTrue(in_use, "no card states a rate on a base")
        for base in in_use:
            with self.subTest(base):
                self.assertIn(base, _READERS_BEHIND_A_BASE)
