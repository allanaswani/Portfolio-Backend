"""Weighted Sales, read from the scores the weighted sales report saves.

The report already scored every seller and wrote it only into the workbook
it emails; the card said "not yet read into this card". These hold the
reader to the workbook's own card:

    Business_Banking   Weighted Sales   target 0.8   ACTUAL 0.2633   0.3291
"""

import datetime

from django.db import connection
from django.test import TestCase

from . import weighted_sales as ws

CODE = "AK4001"


def make_scores_table():
    """The ETL creates this; Django does not, so the test does - with the
    ETL's own columns, so a drift between the two repos fails here."""
    with connection.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {ws.TABLE} (
                report_date date NOT NULL,
                sales_code varchar(100) NOT NULL,
                role_group varchar(100) NOT NULL,
                monthly_weighted_score double precision,
                ytd_weighted_score double precision,
                weighted_score double precision,
                loaded_at timestamp DEFAULT now()
            )
        """)


def score(on, value, code=CODE, group="SME RM"):
    with connection.cursor() as cur:
        cur.execute(
            f"INSERT INTO {ws.TABLE} (report_date, sales_code, role_group, "
            f"weighted_score) VALUES (%s, %s, %s, %s)",
            [on, code, group, value])


class ReaderTests(TestCase):

    def test_without_the_table_it_names_the_etl_change(self):
        with connection.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {ws.TABLE}")
        value, _at, _label, problem = ws.seller_score(CODE)
        self.assertIsNone(value)
        self.assertIn("weighted_sales_seller_scores", problem)

    def test_the_latest_run_is_the_figure(self):
        make_scores_table()
        score(datetime.date(2026, 9, 30), 0.2633)
        score(datetime.date(2026, 10, 27), 0.31)
        value, at, label, problem = ws.seller_score(CODE)
        self.assertIsNone(problem)
        self.assertAlmostEqual(value, 0.31)
        self.assertEqual(at, datetime.date(2026, 10, 27))
        self.assertIn("SME RM", label)

    def test_a_september_card_reads_september_not_october(self):
        make_scores_table()
        score(datetime.date(2026, 9, 30), 0.2633)
        score(datetime.date(2026, 10, 27), 0.31)
        value, at, _label, _problem = ws.seller_score(
            CODE, upto=datetime.date(2026, 9, 30))
        self.assertAlmostEqual(value, 0.2633)
        self.assertEqual(at, datetime.date(2026, 9, 30))

    def test_the_code_is_matched_without_case_or_spaces(self):
        make_scores_table()
        score(datetime.date(2026, 9, 30), 0.5, code=" ak4001 ")
        self.assertAlmostEqual(ws.seller_score(CODE)[0], 0.5)

    def test_a_seller_in_two_groups_gets_the_higher_score(self):
        make_scores_table()
        on = datetime.date(2026, 9, 30)
        score(on, 0.2, group="SME RM")
        score(on, 0.4, group="PB RM")
        self.assertAlmostEqual(ws.seller_score(CODE)[0], 0.4)

    def test_nobody_on_the_dashboard_is_told_so(self):
        make_scores_table()
        value, _at, _label, problem = ws.seller_score("ZZ0000")
        self.assertIsNone(value)
        self.assertIn("ZZ0000", problem)


class CardTests(TestCase):

    def test_the_line_reads_the_score_and_is_no_longer_pending(self):
        from .live_scorecard import SOURCES, live_actuals

        for code in ("weighted_sales", "weighted_sales_dashboard"):
            with self.subTest(code):
                self.assertEqual(SOURCES[code].actual_key,
                                 "weighted_sales_score")
                self.assertFalse(SOURCES[code].pending)

        make_scores_table()
        score(datetime.date(2026, 9, 30), 0.2633)
        out = live_actuals(CODE, wanted={"weighted_sales_score"})
        self.assertAlmostEqual(out["weighted_sales_score"]["value"], 0.2633)

    def test_every_card_with_the_line_is_scored_against_80_percent(self):
        """0059 - the workbook's Business_Banking card: target 0.8. Run on
        rows made here, because another module's TransactionTestCase can
        flush what the migrations seeded before this one runs."""
        import importlib

        from django.apps import apps

        from .scorecard_automation.models import ScRoleKpiMapping

        migration = importlib.import_module(
            "apps.staff_management.migrations."
            "0059_weighted_sales_targets_80_percent")
        ScRoleKpiMapping.objects.filter(kpi_code="weighted_sales").delete()
        start, end = datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)
        for role, target in (("sme_rm", None),
                             ("sme_bbc", 0.9)):   # set by hand: left alone
            ScRoleKpiMapping.objects.create(
                role_code=role, kpi_order=4, kpi_code="weighted_sales",
                kpi_weight=0.05, kpi_target=target,
                effective_from=start, effective_to=end,
                bonus_effective_from=start, bonus_effective_to=end,
                plan_category="annual", target_category="individual")

        migration.seed(apps, None)

        targets = dict(ScRoleKpiMapping.objects.filter(
            kpi_code="weighted_sales").values_list("role_code", "kpi_target"))
        self.assertEqual(float(targets["sme_rm"]), 0.8)
        self.assertEqual(float(targets["sme_bbc"]), 0.9)
