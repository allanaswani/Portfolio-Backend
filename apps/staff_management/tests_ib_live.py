"""IB live deposit growth: the template's SUMIFS by RM and legacy tag, this
month's balance from daily_balance_movement less the desk's December balance;
nothing goes live unless the method gives the desk's own closed month."""
from unittest import mock

from django.test import TestCase

from . import ib_live

HEAD = ["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch", "staff_zone"]


def growth_sheet(oct_values, sep_values=None):
    """Deposit_Growth laid out as the template: Legacy block, Non-Legacy
    block, the head's sum row. September is column O, October P."""
    sep_values = sep_values or {k: 0.0 for k in oct_values}

    def row(code, name, role, key):
        return [1, code, name, role, "HO", "HO"] + [None] * 8 + [sep_values[key],
                                                                  oct_values[key]]
    return [["Legacy"], HEAD + ["m"] * 12,
            row("AA1", "Amy", "IB RM", ("AA1", "Legacy")),
            ["Unmanaged"],
            ["Non-Legacy"], HEAD + ["m"] * 12,
            row("AA1", "Amy", "IB RM", ("AA1", "Non-Legacy")),
            ["Unmanaged"] + [None] * 13 + [sep_values[("UNMANAGED", "Non-Legacy")],
                                           oct_values[("UNMANAGED", "Non-Legacy")]],
            row("HH4", "Hana", "HEAD OF INSTITUTIONAL BANKING", "head")]


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

    def _proof(self, desk_oct, desk_sep):
        actuals = {"Deposit_Growth": growth_sheet(desk_oct, desk_sep)}
        sep = {"1": 120.0, "2": 10.0, "3": 45.0, "4": 99.0}
        by_month = {10: (OCT, "oct_26_bal"), 9: (sep, "sep_26_bal")}
        with mock.patch.object(ib_live, "_accounts", return_value=ACCOUNTS), \
                mock.patch.object(ib_live, "_balances",
                                  side_effect=lambda a, y, m: by_month[m]):
            return ib_live.proof(self.book, actuals, 2026)

    # The warehouse's Sep -> Oct change: AA1 Legacy +30, AA1 Non-Legacy +20,
    # Unmanaged Non-Legacy -5; the head +45. The desk's LEVELS differ from
    # the warehouse's (as Mary Murage's did) - only the change has to agree.
    SEP = {("AA1", "Legacy"): 900.0, ("AA1", "Non-Legacy"): 500.0,
           ("UNMANAGED", "Non-Legacy"): 0.0, "head": 1400.0}

    def test_proof_passes_when_the_change_agrees(self):
        ok, detail, month = self._proof(
            {("AA1", "Legacy"): 930.0, ("AA1", "Non-Legacy"): 520.0,
             ("UNMANAGED", "Non-Legacy"): -5.0, "head": 1445.0}, self.SEP)
        self.assertTrue(ok, detail)
        self.assertEqual(month, 10)
        self.assertIn("all 4 rows", detail)

    def test_proof_fails_when_one_rows_change_differs(self):
        ok, detail, _ = self._proof(
            {("AA1", "Legacy"): 930.0, ("AA1", "Non-Legacy"): 900.0,
             ("UNMANAGED", "Non-Legacy"): -5.0, "head": 1445.0}, self.SEP)
        self.assertFalse(ok)
        self.assertIn("Non-Legacy AA1", detail)

    def test_movement(self):
        self.assertEqual(ib_live.movement_by_person(ACCOUNTS, OCT, {"1": 100.0, "2": 30.0}),
                         {("AA1", "Legacy"): 50.0, ("AA1", "Non-Legacy"): 0.0})

    def test_no_card_when_the_proof_fails(self):
        import datetime

        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)    # the mocked verdict must not outlive the test
        holder = mock.Mock(sales_code="AA1")
        with mock.patch.object(ib_live, "proof",
                               return_value=(False, "Non-Legacy AA1: the warehouse gives 1", 10)):
            card = ib_live.live_ib_card(self.book, {}, holder, datetime.date(2026, 11, 30))
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "ib_live_not_proven")
        self.assertIn("Non-Legacy AA1: the warehouse gives 1", card["detail"])
