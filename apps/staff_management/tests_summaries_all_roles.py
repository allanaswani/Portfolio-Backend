"""Group summaries cover every card the platform scores: the retail back
office workbook (its summary only up to the desk's run month), the Scheme
and Banca DSR cards (stored totals, then the archived card), and Banca DSRs
are archived at all (seeded rows, the real functions)."""
import datetime as dt
from unittest.mock import patch

from django.test import TestCase

from . import scorecard_archive as sa
from .models import BancaScorecard, SchemeScorecard
from .tests_scorecard_archive import ArchiveTests


def stored_card(code, name, score):
    return {"has_card": True, "performance_score": score,
            "staff": {"sales_code": code, "name": name},
            "perspectives": [{"lines": [{"kpi_name": "X", "pending": False}]}]}


class AllRolesSummaryTests(TestCase):
    def setUp(self):
        ArchiveTests.setUp(self)
        hdr = ["PF", "SalesCode", "Name", "Role", "Branch", "Reports"] + [None] * 12
        # Constants B2 (the desk's run) = 6: its October column is a copy of June.
        june = [None, None, 0.61, 0.62, None, 0.66, None, None, None, 0.66, None, None]
        self.rbo_book = {"book": "retail_back_office", "cards": {"RO_COMMERCIAL": {}},
                         "tables": {
            "List": [["PF", "Code", "Name", "Role", "Branch", "x", "Reports"],
                     [5, "RO5", "Rita Officer", "RELATIONSHIP OFFICER - COMMERCIAL", "HO", "", "Boss"]],
            "Constants": [[None, 10], [None, 6], [None, None], [None, None], [None, 2026]],
            "Monthly_Summary": [hdr, [5.0, "RO5", "Rita Officer", "RO", "HO", "Boss"] + june],
        }}
        for m, total, banca in ((9, 0.7, 0.8), (10, 0.75, 0.85)):
            SchemeScorecard.objects.create(sales_code="SC1", staff_name="Sam Scheme",
                                           sheet="SCHEMES_RM", month=dt.date(2026, m, 1),
                                           total=total)
            BancaScorecard.objects.create(sales_code="BD1", staff_name="Bea Banca",
                                          month=dt.date(2026, m, 1), total=banca)
        # November: no stored card; the archived one is what was sent.
        sa.archive_card("2026-11", {"book": "Scheme", "code": "SC1", "name": "Sam Scheme"},
                        stored_card("SC1", "Sam Scheme", 0.8))
        sa.archive_card("2026-11", {"book": "Banca DSR", "code": "BD1", "name": "Bea Banca"},
                        stored_card("BD1", "Bea Banca", 0.9))

    def _groups(self, upto):
        from . import scorecard_summaries as ss

        saved = lambda kind, year=None: {"rbo_scorecards": self.rbo_book}.get(kind)  # noqa: E731
        with patch("apps.staff_management.workbook_cards.saved", side_effect=saved), \
                patch("apps.staff_management.workbook_cards.roster_roles", return_value={}), \
                patch("apps.staff_management.workbook_cards.hr_roles", return_value={}):
            return {g["group"]: g for g in ss.group_summaries(2026, upto)}

    def test_retail_back_office_is_a_group_up_to_the_desks_run(self):
        groups = self._groups(10)
        rbo = [g for g in groups.values() if g["workbook"] == "Retail back office"]
        self.assertEqual(len(rbo), 1)
        scores = rbo[0]["rows"][0]["scores"]
        self.assertEqual(scores[5], 0.66)        # June, the desk's
        self.assertIsNone(scores[9])             # October's copy of June is not a score

    def test_scheme_and_banca_stored_months_then_the_archived_month(self):
        groups = self._groups(11)
        scheme = groups["Scheme - SCHEMES_RM"]["rows"][0]
        self.assertEqual(scheme["identity"], ["SC1", "Sam Scheme", "SCHEMES_RM"])
        self.assertEqual(scheme["scores"][8:], [0.7, 0.75, 0.8])
        self.assertAlmostEqual(scheme["change"], 0.05)
        banca = groups["Banca DSR - Banca DSR"]
        self.assertEqual(banca["rows"][0]["scores"][8:], [0.8, 0.85, 0.9])
        self.assertEqual(banca["from_desk"], [9, 10])
        self.assertEqual(banca["from_archive"], [11])

    def test_banca_dsrs_are_archived(self):
        from .management.commands.scorecard_reach import workbook_people

        with patch("apps.staff_management.workbook_cards.saved", return_value=None):
            people, missing = workbook_people()
        self.assertIn({"book": "Banca DSR", "code": "BD1", "name": "Bea Banca",
                       "role": "BANCA_DSR", "pf": ""}, people)
        self.assertNotIn("Banca DSR", missing)
        self.assertIn({"book": "Banca DSR", "code": "BD1", "name": "Bea Banca"}, sa.people())
