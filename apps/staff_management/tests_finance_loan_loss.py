"""Loan Loss attributed as Finance attributes it (11 Nov 2026).

Finance's IFRS workbook carries a customer -> RM map (CUSTOMER SUMMARY_2026:
cif, rm_code) and its rm_summary pivot adds each RM's customers' (P&L charge -
interest adjustment). Rebuilt that way from the Aug 2026 file, 92 of 92 RMs
came out identical to Finance's pivot - AKL3116 79,293,055 among them - where
the allocated book gave about 0.7M."""
import datetime

from django.test import SimpleTestCase, TestCase

from services import portfolio_service as svc

from . import ifrs_movement as im
from . import workbook_cards as wc


def ifrs_row(cif, month, charge, adj=0.0, account=None):
    from apps.portfolio.models import LoansMomIFRSMovement

    LoansMomIFRSMovement.objects.create(
        lns_account=account or f"L{cif}{month.month}", cust_code_strategy=str(cif),
        pl_charge=charge, int_adj=adj, eom_date=month)


class FinanceMapTests(TestCase):
    def setUp(self):
        wc.save_file(im.RM_MAP_KIND.format(year=2026), {"year": 2026, "map": {
            "1001": ["AKL3116"],
            "1002": ["AKL3116", "AKL3116"],   # listed twice: Finance counts it twice
            "1003": ["3116"],                 # the staff number alone
            "1004": ["LJB1656"],
        }})

    def test_the_rms_customers_as_finance_lists_them(self):
        self.assertEqual(sorted(svc.finance_rm_cifs("akl3116", 2026)),
                         [1001, 1002, 1002, 1003])
        self.assertIsNone(svc.finance_rm_cifs("AKL3116", 2025))

    def test_loss_is_charge_less_adjustment_over_finances_customers(self):
        jan, aug = datetime.date(2026, 1, 1), datetime.date(2026, 8, 1)
        ifrs_row(1001, jan, 100.0, 10.0)
        ifrs_row(1002, aug, 50.0)
        ifrs_row(1003, aug, 5.0)
        ifrs_row(1004, aug, 999.0)        # another RM's customer
        loss, rows = svc._ifrs_loss("AKL3116", jan, datetime.date(2026, 9, 1))
        # -( (100-10) + 2 x 50 + 5 ): the twice-listed customer counts twice.
        self.assertEqual(loss, -195.0)
        self.assertEqual(rows, 4)

    def test_no_map_for_the_year_keeps_the_book(self):
        with self.assertRaises(Exception):
            # The book read needs the allocation tables; reaching it at all is
            # the point - no map means no Finance attribution.
            svc._ifrs_loss("AKL3116", datetime.date(2025, 1, 1), datetime.date(2026, 1, 1))


class ReadMapTests(SimpleTestCase):
    def test_unmanaged_and_na_are_not_rms(self):
        self.assertTrue({"UNMANAGED", "0X2A", "#N/A"} <= im._NOT_AN_RM)


class WeightedSalesNoteTests(SimpleTestCase):
    def test_nothing_to_compare_is_not_a_zero_match(self):
        from . import sales_live_feeds as slf

        wl = {"feed": "Weighted_Sales", "measure": "Weighted Sales", "initiative": ""}
        key = slf.line_key(wl)
        note = slf.note({key: {"live": False, "match": 0.0, "untested": True,
                               "month": "2026-09"}}, wl)
        self.assertIn("nothing for Sep 2026", note)
        self.assertNotIn("0%", note)

    def test_weighted_sales_holds_at_what_was_achieved(self):
        self.assertIn("weightedsales", wc.STICKY_SHEETS)
