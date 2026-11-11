"""Bancassurance "renewals and other banca products".

The line showed a dash with a target beside it, refused on the grounds that
no column records which products are "other". That was the wrong way round:
what "other" MEANS does not have to be named to be measured. The two lines
beside it count the premiums they can classify, and this one is everything
they do not - so the three partition the book and none of them can double
another, whatever "other" turns out to be.
"""

import datetime

from django.db import connection
from django.test import TestCase

from .live_scorecard import SOURCES, _premiums_ytd


def _insert(rows):
    """Put premiums on the warehouse table this reads.

    ``insurance_policies`` is an unmanaged warehouse table. It exists in the
    test database because the mirror models declare it, so the reader can be
    tested against real rows rather than mocked out - the SQL is the thing
    worth testing here.
    """
    with connection.cursor() as cur:
        for product, premium, code in rows:
            cur.execute(
                "INSERT INTO insurance_policies "
                "(product, premiums, code, year, month, starting_date, "
                " updated_at) VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                [product, premium, code, "2026", "Aug",
                 datetime.date(2026, 8, 1)])


def _map(product, life):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO premium_types_mapping "
            "(product, vic_check, life_policy_check, premium_type, "
            " policy_category) VALUES (%s, %s, %s, %s, %s)",
            [product, "vic", "life" if life else "general", "non-motor",
             "Life" if life else "General"])


class TheResidualTests(TestCase):
    CODE = "JM4191"

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("DELETE FROM premium_types_mapping")

    def test_the_three_lines_add_up_to_the_whole_book(self):
        _map("WHOLE LIFE", life=True)
        _map("MOTOR/PRIVATE", life=False)
        _insert([
            ("WHOLE LIFE", 100_000, self.CODE),       # life
            ("MOTOR/PRIVATE", 60_000, self.CODE),     # non-life
            ("TRAVEL", 25_000, self.CODE),            # unclassified
            ("SOMETHING ELSE", 15_000, self.CODE),    # unclassified
        ])
        total, life, non_life, other, unmapped, _latest = _premiums_ytd(
            self.CODE, 2026)
        self.assertEqual(total, 200_000)
        self.assertEqual(life, 100_000)
        self.assertEqual(non_life, 60_000)
        # The whole point: what neither classified line counts.
        self.assertEqual(other, 40_000)
        self.assertEqual(life + non_life + other, total)
        self.assertEqual(unmapped, 2)

    def test_a_fully_classified_book_leaves_nothing_over(self):
        """And the line then reads nought rather than a dash - which is the
        honest answer, not a missing one."""
        _map("WHOLE LIFE", life=True)
        _insert([("WHOLE LIFE", 100_000, self.CODE)])
        total, life, non_life, other, _unmapped, _latest = _premiums_ytd(
            self.CODE, 2026)
        self.assertEqual((total, life, non_life, other),
                         (100_000, 100_000, 0, 0))

    def test_the_residual_is_never_negative(self):
        """A credit note could in principle push it below nought, and a
        negative "other" would read as the RM having sold something back."""
        _map("WHOLE LIFE", life=True)
        _insert([("WHOLE LIFE", 100_000, self.CODE),
                 ("WHOLE LIFE", -20_000, self.CODE)])
        _total, _life, _non_life, other, _unmapped, _latest = _premiums_ytd(
            self.CODE, 2026)
        self.assertGreaterEqual(other, 0)

    def test_somebody_elses_premiums_are_not_counted(self):
        _insert([("TRAVEL", 50_000, "OTHER1")])
        total, _l, _n, other, _u, _latest = _premiums_ytd(self.CODE, 2026)
        self.assertEqual((total, other), (0, 0))


class TheLineIsNoLongerPendingTests(TestCase):
    def test_both_cards_that_carry_it_now_read_a_figure(self):
        for code, key in (("bancassurance_premiums", "banca_non_vic"),
                          ("other_bancassurance_premiums", "banca_other")):
            with self.subTest(code):
                source = SOURCES[code]
                self.assertEqual(source.actual_key, key)
                self.assertFalse(source.pending)
                # The target still comes off the roster column it always did.
                self.assertEqual(source.target_field, "target_banca_value")

    def test_it_is_no_longer_on_the_list_of_figures_to_type_in(self):
        """It is measured now, so asking an administrator to type it would be
        asking for a number the platform already has."""
        from .scorecard_manual import MANUAL_ACTUALS

        self.assertNotIn("bancassurance_premiums", MANUAL_ACTUALS)
        self.assertNotIn("other_bancassurance_premiums", MANUAL_ACTUALS)


class VicOnlyTests(TestCase):
    """The RM VIC lines count Britam and Britam Life only, as the desk's
    bancassurance report does - not every premium on the book."""

    def _policy(self, r_number, product, underwriter, paid, code,
                insured="A CUSTOMER"):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO insurance_policies "
                "(r_number, product, underwriter, insured, paid, premiums, "
                " code, year, month, starting_date, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                [r_number, product, underwriter, insured, paid, paid, code,
                 "2026", "Aug", datetime.date(2026, 8, 1)])

    def test_only_britam_is_vic_and_life_splits_from_non_life(self):
        from .bb_live_feeds import vic_by_seller

        self._policy("R1", "WHOLE LIFE", "Britam Life", 100_000, "AKL3116")
        self._policy("R2", "Fire Material Damage", "Britam", 40_000,
                     "AKL 3116")                       # the report drops spaces
        self._policy("R3", "Private Comprehensive", "Jubilee", 900_000,
                     "AKL3116")                        # not VIC
        self._policy("R4", "Fire Material Damage", "APA", 70_000,
                     "AKL3116")                        # VIC product, not Britam
        self._policy("R5", "WHOLE LIFE", "Britam Life", 5_000, "AKL3116",
                     insured="Hf Bancassurance Intermediary Ltd")  # excluded
        got = vic_by_seller(2026, 9, 60_000)["AKL3116"]
        self.assertEqual(got, {"vic_life": 100_000.0,
                               "vic_non_life": 40_000.0})

    def test_all_paid_premiums_count_every_product_by_code(self):
        """Bancassurance Premiums = the report's RMs_and_BBCs_paid_premiums:
        paid premiums on every product and underwriter, by the policy's code."""
        from .bb_live_feeds import banca_by_seller

        self._policy("R1", "WHOLE LIFE", "Britam Life", 100_000, "AKL3116")
        self._policy("R3", "Private Comprehensive", "Jubilee", 900_000,
                     "AKL 3116")
        self._policy("R6", "SOMETHING UNMAPPED", "APA", 7_000, "AKL3116")
        self._policy("R5", "WHOLE LIFE", "Britam Life", 5_000, "AKL3116",
                     insured="Hf Bancassurance Intermediary Ltd")  # excluded
        got = banca_by_seller(2026, 9, 60_000)["AKL3116"]
        self.assertEqual(got["all"], 1_007_000.0)
        self.assertEqual(got["vic_life"], 100_000.0)

    def test_the_vic_lines_read_the_vic_figures(self):
        for code, key in (("commercial_vic_premiums", "vic_total"),
                          ("vic_premium", "vic_life"),
                          ("group_synergies_20_0", "vic_non_life")):
            self.assertEqual(SOURCES[code].actual_key, key)
