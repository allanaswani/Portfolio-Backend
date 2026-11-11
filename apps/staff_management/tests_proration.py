"""Targets prorated by an administrator (11 Nov 2026, Joseph Kinuthia JKK3227:
acting BOM May-Aug 2026, scored as a CSO after it). The entry fills the
workbook List's own proration column, month by month, and the card's
formulas do the rest."""
import datetime

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from . import workbook_cards as bo
from .tests_workbook_cards import ACTUALS, book


def prorated_book(recorded=None, column="prorate_new"):
    """The teller fixture, its List's column O (the cell its target formulas
    look up) named ``column``. ``recorded``: {month: score} on Monthly_Summ."""
    b = book()
    b["tables"]["List"][0][14] = column
    for month, score in (recorded or {}).items():
        b["tables"]["Monthly_Summ"][1][6 + month - 1] = score
    return b


def save_entries(entries):
    bo.save_file(bo.PRORATION, entries)
    cache.delete(bo.PRORATION)


class ExcludedMonthsTests(SimpleTestCase):
    def test_acting_takes_out_the_months_away_and_no_earlier_month(self):
        acting = {"reason": "acting", "from": "2026-05", "to": "2026-08"}
        self.assertEqual([bo.excluded_months(acting, 2026, m) for m in (4, 5, 8, 9, 11)],
                         [0, 1, 4, 4, 4])

    def test_a_joiner_counts_from_the_month_after(self):
        joined = {"reason": "joined", "from": "2026-07"}
        # Joined in July: January to July are out, the target runs from August.
        self.assertEqual(bo.excluded_months(joined, 2026, 9), 7)
        self.assertEqual(bo.excluded_months(joined, 2026, 3), 3)

    def test_last_year_does_not_reach_this_year(self):
        self.assertEqual(bo.excluded_months(
            {"reason": "role_change", "from": "2025-11"}, 2026, 9), 0)
        self.assertEqual(bo.excluded_months(
            {"reason": "maternity_leave", "from": "2025-10", "to": "2026-02"},
            2026, 9), 2)

    def test_an_unknown_reason_takes_nothing(self):
        self.assertEqual(bo.excluded_months({"reason": "x", "from": "2026-01"},
                                            2026, 9), 0)


class ProratedCardTests(TestCase):
    def setUp(self):
        cache.clear()

    def holder(self, b, code="BCK3783"):
        return next(h for h in bo.holders(b) if h.sales_code == code)

    def test_the_cards_own_formula_takes_the_months_out(self):
        b = prorated_book()
        save_entries({"BCK3783": [{"id": "a", "reason": "joined", "from": "2026-03"}]})
        opening, training, nps = bo.compute(b, ACTUALS, self.holder(b), 9)["lines"]
        # 4 a month x (9 - 3); 48 a year x (9 - 3)/12; a level is untouched.
        self.assertEqual(opening["ytd_target"], 24.0)
        self.assertEqual(training["ytd_target"], 24.0)
        self.assertEqual(nps["ytd_target"], 0.6)

    def test_nobody_else_is_touched(self):
        b = prorated_book()
        save_entries({"BCK3783": [{"id": "a", "reason": "joined", "from": "2026-03"}]})
        # New Joiner's own List value (6) stands: 4 x (9 - 6).
        self.assertEqual(bo.compute(b, ACTUALS, self.holder(b, "NEW9999"), 9)
                         ["lines"][0]["ytd_target"], 12.0)

    def test_a_column_the_list_does_not_have_changes_nothing(self):
        b = book()      # column O unnamed
        save_entries({"BCK3783": [{"id": "a", "reason": "joined", "from": "2026-03"}]})
        self.assertEqual(bo.compute(b, ACTUALS, self.holder(b), 9)["lines"][0]["ytd_target"],
                         36.0)

    def test_after_the_absence_the_prorated_score_replaces_the_desks(self):
        bo.save_file("scorecards", prorated_book({9: 0.9}, "prorate_acting_other"))
        bo.save_file("actuals", ACTUALS)
        save_entries({"BCK3783": [{"id": "a", "reason": "acting",
                                   "from": "2026-05", "to": "2026-08"}]})
        self.assertGreater(bo.rescore("BCK3783"), 0)
        card = bo.card_payload(bo.stored_month(
            "BCK3783", datetime.date(2026, 9, 1), bo.BACK_OFFICE))
        self.assertIn("Targets prorated: acting in another role (2026-05 to 2026-08): "
                      "4 month(s)", card["coverage_note"])
        self.assertIn("recorded 90.0%", card["coverage_note"])
        self.assertNotEqual(card["performance_score"], 0.9)
        # 4 a month x (9 - 4).
        self.assertEqual(card["perspectives"][0]["lines"][0]["ytd_target"], 20.0)

    def test_inside_the_absence_the_desks_record_stands(self):
        bo.save_file("scorecards", prorated_book({6: 0.7}, "prorate_acting_other"))
        bo.save_file("actuals", ACTUALS)
        save_entries({"BCK3783": [{"id": "a", "reason": "acting",
                                   "from": "2026-05", "to": "2026-08"}]})
        bo.rescore("BCK3783")
        card = bo.card_payload(bo.stored_month(
            "BCK3783", datetime.date(2026, 6, 1), bo.BACK_OFFICE))
        self.assertEqual(card["performance_score"], 0.7)
        self.assertNotIn("Targets prorated", card["coverage_note"])


class ProrationScreenTests(TestCase):
    URL = "/staff_management/scorecard-automation/manual-figures/proration/"

    def setUp(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient

        cache.clear()
        bo.save_file("scorecards", prorated_book())
        bo.save_file("actuals", ACTUALS)
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_superuser("root.admin", password="x"))

    def test_only_an_administrator(self):
        from django.contrib.auth.models import User

        self.client.force_authenticate(User.objects.create_user("some.one"))
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.assertEqual(self.client.post(self.URL, {}, format="json").status_code, 403)

    def test_add_list_and_remove(self):
        r = self.client.post(self.URL, {"sales_code": "bck 3783", "reason": "joined",
                                        "from": "2026-03"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertGreater(r.data["months_recomputed"], 0)
        self.assertEqual(r.data["warnings"], [])
        self.assertEqual(r.data["cards"][0]["columns_the_card_reads"], ["prorate_new"])
        listed = self.client.get(self.URL).data["people"]
        self.assertEqual(listed[0]["sales_code"], "BCK3783")
        ident = r.data["entry"]["id"]
        gone = self.client.delete(f"{self.URL}?sales_code=BCK3783&id={ident}")
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(self.client.get(self.URL).data["people"], [])

    def test_a_column_the_card_does_not_read_is_warned(self):
        r = self.client.post(self.URL, {"sales_code": "BCK3783", "reason": "sick_leave",
                                        "from": "2026-05", "to": "2026-06"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("does not read prorate_acting_other", r.data["warnings"][0])

    def test_bad_input_is_refused(self):
        for body, field in (
                ({"sales_code": "BCK3783", "reason": "nap", "from": "2026-05"}, "reason"),
                ({"sales_code": "BCK3783", "reason": "acting", "from": "2026-05"}, "to"),
                ({"sales_code": "BCK3783", "reason": "acting", "from": "2026-08",
                  "to": "2026-05"}, "to"),
                ({"sales_code": "BCK3783", "reason": "joined", "from": "July"}, "from"),
                ({"sales_code": "NOPE1", "reason": "joined", "from": "2026-07"},
                 "sales_code")):
            r = self.client.post(self.URL, body, format="json")
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(field, r.data)
