"""IB live deposit growth: the template's SUMIFS by RM and legacy tag, this
month's balance from daily_balance_movement less the desk's December balance;
nothing goes live unless the method gives the desk's own closed month."""
from unittest import mock

from django.test import TestCase

from . import ib_live

HEAD = ["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch", "staff_zone"]


def growth_sheet(oct_values):
    """Deposit_Growth laid out as the template: Legacy block, Non-Legacy
    block, the head's sum row. October is column P (index 15)."""
    def row(code, name, role, v):
        return [1, code, name, role, "HO", "HO"] + [None] * 9 + [v]
    return [["Legacy"], HEAD + ["m"] * 12,
            row("AA1", "Amy", "IB RM", oct_values[("AA1", "Legacy")]),
            ["Unmanaged"],
            ["Non-Legacy"], HEAD + ["m"] * 12,
            row("AA1", "Amy", "IB RM", oct_values[("AA1", "Non-Legacy")]),
            ["Unmanaged"] + [None] * 14 + [oct_values[("UNMANAGED", "Non-Legacy")]],
            row("HH4", "Hana", "HEAD OF INSTITUTIONAL BANKING", oct_values["head"])]


ACCOUNTS = [("1", "AA1", "Legacy", 100.0), ("2", "AA1", "Non-Legacy", 0.0),
            ("3", "UNMANAGED", "Non-Legacy", 50.0), ("4", "UNMANAGED", "Legacy", 10.0)]
OCT = {"1": 150.0, "2": 30.0, "3": 40.0, "4": 99.0}


class Book(dict):
    pass


class IbLiveTests(TestCase):
    def setUp(self):
        self.book = {"book": "ib", "tables": {"Constants": [[None, 14], [None, 10]]}}

    def test_the_sumifs_by_rm_and_tag(self):
        live = ib_live.growth_by_person(ACCOUNTS, OCT)
        self.assertEqual(live, {("AA1", "Legacy"): 50.0, ("AA1", "Non-Legacy"): 30.0,
                                ("UNMANAGED", "Non-Legacy"): -10.0,
                                ("UNMANAGED", "Legacy"): 89.0})
        # The head: Legacy RMs (Unmanaged's legacy row is blank) + every
        # Non-Legacy row.
        self.assertEqual(ib_live.head_growth(live), 50.0 + 30.0 - 10.0)

    def _proof(self, desk):
        actuals = {"Deposit_Growth": growth_sheet(desk)}
        with mock.patch.object(ib_live, "_accounts", return_value=ACCOUNTS), \
                mock.patch.object(ib_live, "_balances", return_value=(OCT, "oct_26_bal")):
            return ib_live.proof(self.book, actuals, 2026)

    def test_proof_passes_on_the_desks_figures(self):
        ok, detail, month = self._proof({("AA1", "Legacy"): 50.0, ("AA1", "Non-Legacy"): 30.0,
                                         ("UNMANAGED", "Non-Legacy"): -10.0, "head": 70.0})
        self.assertTrue(ok, detail)
        self.assertEqual(month, 10)
        self.assertIn("all 4 rows", detail)

    def test_proof_fails_when_one_person_differs(self):
        ok, detail, _ = self._proof({("AA1", "Legacy"): 50.0, ("AA1", "Non-Legacy"): 99.0,
                                     ("UNMANAGED", "Non-Legacy"): -10.0, "head": 70.0})
        self.assertFalse(ok)
        self.assertIn("Non-Legacy AA1", detail)

    def test_no_card_when_the_proof_fails(self):
        import datetime

        from django.core.cache import cache

        cache.clear()
        holder = mock.Mock(sales_code="AA1")
        with mock.patch.object(ib_live, "proof",
                               return_value=(False, "Non-Legacy AA1: the warehouse gives 1", 10)):
            card = ib_live.live_ib_card(self.book, {}, holder, datetime.date(2026, 11, 30))
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "ib_live_not_proven")
        self.assertIn("Non-Legacy AA1: the warehouse gives 1", card["detail"])
