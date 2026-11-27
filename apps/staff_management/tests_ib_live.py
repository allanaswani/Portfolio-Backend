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

    def test_labels_say_where_each_figure_is_from(self):
        import datetime

        payload = {"perspectives": [{"lines": [
            {"kpi_code": "deposit_growth", "weight": 0.3, "ytd_actual": 5, "as_at": "x"},
            {"kpi_code": "revenue", "weight": 0.1, "ytd_actual": 7, "as_at": "x"},
            {"kpi_code": "trade_fx_sales", "weight": 0.0, "ytd_actual": None, "as_at": "typed"},
        ]}]}
        ib_live.relabel(payload, ["Deposit_Growth"], "October", datetime.date(2026, 11, 27))
        lines = payload["perspectives"][0]["lines"]
        self.assertEqual(lines[0]["as_at"], "live, as at 27 Nov 2026")   # not the 30th
        self.assertEqual(lines[1]["as_at"], "the desk's October figure")
        self.assertEqual(lines[2]["as_at"], "weight 0 on the desk's card - not scored")
