"""Active Customers and Digital Adoption.

Both lines showed a dash with the note that no feed held them. The signed Q3
cards say otherwise and name their own arithmetic, so these tests are written
against those cards:

    Alice Kamau  (SME ARM)  Active Customers   2025 FY 42   +20%  ->  50.4
    Lydia Apanja (PB ARM)   Digital Adoption   2025 FY 197  +50%  -> 287.29

"Active" is TWO consecutive months of activity, which is what the measure of
success says, and what these tests hold the reader to.
"""

import datetime

from django.db import connection
from django.test import TestCase

from .live_scorecard import DIGITAL_CHANNELS, SOURCES, _two_month_active

CODE = "AK4001"
YEAR = 2026


def make_the_feeds():
    """Create the two unmanaged warehouse tables the reader joins.

    ``transaction_diary`` and ``retail_allocated_portfolio`` are warehouse
    tables, so Django does not create them and the SQL would go untested.
    Only the columns the reader touches.
    """
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transaction_diary (
                id bigserial PRIMARY KEY,
                fk_customercust_id bigint,
                tmstamp timestamptz,
                justific_name varchar(255),
                chanel_description varchar(255)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id bigint,
                sales_code varchar(100),
                updated_at timestamptz
            )
        """)


def allocate(*cust_ids, code=CODE):
    with connection.cursor() as cur:
        for cust_id in cust_ids:
            cur.execute(
                "INSERT INTO retail_allocated_portfolio "
                "(cust_id, sales_code, updated_at) VALUES (%s, %s, NOW())",
                [cust_id, code])


def transact(cust_id, year, month, digital=False):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO transaction_diary "
            "(fk_customercust_id, tmstamp, justific_name, chanel_description) "
            "VALUES (%s, %s, %s, %s)",
            [cust_id, datetime.datetime(year, month, 15),
             DIGITAL_CHANNELS[0] if digital else "DEPOSIT CASH",
             "MOBILE" if digital else None])


class TwoMonthsMeansTwoMonthsTests(TestCase):
    def setUp(self):
        make_the_feeds()
        allocate(1, 2, 3, 4)

    def test_a_customer_active_in_two_consecutive_months_counts(self):
        transact(1, YEAR, 7)
        transact(1, YEAR, 8)
        count, as_at = _two_month_active(CODE, YEAR)
        self.assertEqual(count, 1)
        # As at the END of the month the pair closes on.
        self.assertEqual(as_at, datetime.date(YEAR, 8, 31))

    def test_a_customer_active_in_only_one_month_does_not(self):
        """This is the whole measure. "Active" on these cards is not
        "transacted at some point"."""
        transact(2, YEAR, 8)
        count, _as_at = _two_month_active(CODE, YEAR)
        self.assertEqual(count, 0)

    def test_two_months_that_are_not_consecutive_do_not_count(self):
        transact(3, YEAR, 5)
        transact(3, YEAR, 8)
        count, _as_at = _two_month_active(CODE, YEAR)
        self.assertEqual(count, 0)

    def test_it_counts_customers_not_transactions(self):
        for _ in range(6):
            transact(1, YEAR, 7)
            transact(1, YEAR, 8)
        count, _as_at = _two_month_active(CODE, YEAR)
        self.assertEqual(count, 1)

    def test_somebody_elses_customer_is_not_counted(self):
        allocate(99, code="OTHER1")
        transact(99, YEAR, 7)
        transact(99, YEAR, 8)
        count, _as_at = _two_month_active(CODE, YEAR)
        self.assertEqual(count, 0)

    def test_the_latest_pair_with_activity_is_the_one_reported(self):
        """A figure read in the first days of a month must not collapse to
        nought because the new month has barely started."""
        transact(1, YEAR, 6)
        transact(1, YEAR, 7)
        transact(2, YEAR, 7)
        transact(2, YEAR, 8)
        count, as_at = _two_month_active(CODE, YEAR)
        self.assertEqual(count, 1)
        self.assertEqual(as_at, datetime.date(YEAR, 8, 31))

    def test_an_absent_feed_reports_nothing_rather_than_nought(self):
        """A read that failed and a customer who did nothing are different
        statements, and the card says which."""
        with connection.cursor() as cur:
            cur.execute("DROP TABLE transaction_diary")
        count, _as_at = _two_month_active(CODE, YEAR)
        self.assertIsNone(count)


class DigitalAdoptionTests(TestCase):
    def setUp(self):
        make_the_feeds()
        allocate(1, 2)

    def test_only_digital_channel_activity_counts(self):
        transact(1, YEAR, 7, digital=True)
        transact(1, YEAR, 8, digital=True)
        transact(2, YEAR, 7)
        transact(2, YEAR, 8)
        self.assertEqual(_two_month_active(CODE, YEAR, digital=True)[0], 1)
        # Both are active; only one of them is digital.
        self.assertEqual(_two_month_active(CODE, YEAR)[0], 2)

    def test_the_channels_are_the_ones_the_ceo_dashboard_uses(self):
        """So "digital" means one thing on both screens."""
        self.assertIn("ESB - ENTERPRISE SERVICE BUS", DIGITAL_CHANNELS)
        self.assertIn("KOCELA - SUBSCRIBER AND PAYMENT CHANNEL",
                      DIGITAL_CHANNELS)


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
        what the card SAYS, and a cell that is two per cent off it carries a
        hand adjustment that is not a rule anybody else can be held to. This
        test exists to record the discrepancy rather than hide it."""
        self.assertAlmostEqual(197 * 1.50, 295.5)
        self.assertAlmostEqual(round(287.29 / 197, 3), 1.458)


class ACardOnlyReadsItsOwnFeedsTests(TestCase):
    """Every reader used to run for every card.

    About twenty warehouse queries each time, most of them for lines the card
    in front of you does not carry. That was survivable until two reads over
    ``transaction_diary`` - the bank's whole transaction history - joined the
    list, and the slowest cards ran past gunicorn's 120-second limit. A killed
    worker returns no response at all, so the page renders blank: "computing
    it..." and then nothing, which reads as the tool losing the card.
    """

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
        # Strictly fewer than everything the module can read.
        everything = {source.actual_key for source in module.SOURCES.values()
                      if source.actual_key}
        self.assertLess(len(wanted), len(everything))
        # And an SME RM's card does not carry the teller's till feed.
        self.assertNotIn("tills_volume", wanted)

    def test_a_base_keeps_its_reader_even_when_its_figure_is_not_read(self):
        """A base is a by-product: ``deposit_growth`` returns the growth AND
        the December book it grew from. A card whose target is "43% of your
        Dec book" needs that reader to run, so the skip must not remove it."""
        from .live_scorecard import _READERS_BEHIND_A_BASE

        for base, readers in _READERS_BEHIND_A_BASE.items():
            with self.subTest(base):
                self.assertTrue(readers, f"{base} names no reader")

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
