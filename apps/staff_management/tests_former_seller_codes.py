"""A DSR moved to a card under a new code still files on iApply under the old
one (Claudine Odhiambo: card CO4115, iApply DSR421). Her TAT (Loan), Loan
Approvals and Errors read both codes, linked by her PF - never by a name."""
import datetime as dt
from unittest import mock

from django.test import TestCase

from . import loan_applications as la
from . import loan_tat_seller as lts
from .models import DSRSalesCode, StaffEmployeeData
from . import tests_workbook_cards as twc


def staff(code, pf, name):
    StaffEmployeeData.objects.create(
        staff_pf_number=pf, staff_name=name, staff_email="x@x", sales_code=code,
        department="Retail", staff_unit="Mortgage", staff_org_unit="X", job_title="ARM",
        employment_date=dt.date(2020, 1, 1), employee_category="front_office")


class FormerSellerCodeTests(TestCase):
    def setUp(self):
        staff("CO4115", 4115, "Claudine Odhiambo")
        DSRSalesCode.objects.create(pf_number="04115", sales_code="DSR421",
                                    salesperson="Claudine Odhiambo")
        # Same name, different PF: never linked.
        DSRSalesCode.objects.create(pf_number="7777", sales_code="DSR999",
                                    salesperson="Claudine Odhiambo")
        staff("ZZ1", 1, "Nobody Else")

    def test_codes_follow_the_pf_not_the_name(self):
        self.assertEqual(la.seller_codes("co 4115"), ["CO4115", "DSR421"])
        self.assertEqual(la.seller_codes("ZZ1"), ["ZZ1"])
        self.assertEqual(la.seller_codes("NOPF1"), ["NOPF1"])

    def test_pf_from_the_workbook_list_when_hr_has_none(self):
        # Sarah Nzeli: no staff_employee_data row; the retail back office
        # List carries her PF; DSR224 carries the same PF.
        import datetime

        from .models import BoScorecard

        BoScorecard.objects.create(book="retail_back_office", sales_code="SN3521",
                                   staff_pf="3521", staff_name="Sarah Nzeli",
                                   sheet="RO_COMMERCIAL", month=datetime.date(2026, 9, 1))
        DSRSalesCode.objects.create(pf_number="3521", sales_code="DSR224",
                                    salesperson="Sarah Nzeli")
        self.assertEqual(la.seller_codes("SN3521"), ["SN3521", "DSR224"])

    def test_vic_lines_add_the_former_codes_policies(self):
        import datetime

        from . import bb_live_feeds
        from .live_scorecard import live_actuals
        from .models import BoScorecard

        BoScorecard.objects.create(book="retail_back_office", sales_code="SN3521",
                                   staff_pf="3521", staff_name="Sarah Nzeli",
                                   sheet="RO_COMMERCIAL", month=datetime.date(2026, 9, 1))
        DSRSalesCode.objects.create(pf_number="3521", sales_code="DSR224",
                                    salesperson="Sarah Nzeli")
        sellers = {"SN3521": {"vic_life": 2642088.0, "vic_non_life": 0.0, "non_vic": 0.0,
                              "all": 2642088.0, "vic_life_n": 1, "vic_non_life_n": 0},
                   "DSR224": {"vic_life": 0.0, "vic_non_life": 225603.0, "non_vic": 0.0,
                              "all": 225603.0, "vic_life_n": 0, "vic_non_life_n": 4}}
        with mock.patch.object(bb_live_feeds, "banca_by_seller", return_value=sellers):
            got = live_actuals("SN3521", wanted={"vic_life_count", "vic_non_life_count"},
                               as_at=datetime.date(2026, 10, 31))
        self.assertEqual(got["vic_life_count"]["value"], 1)
        self.assertEqual(got["vic_non_life_count"]["value"], 4)

    def test_loan_approvals_count_the_former_code(self):
        twc.LoanApprovalsTests._trail(self, [
            ("B1", "DSR421", "2026-10-03", "RM Processing Accepted Letter Of Offer", "12000000"),
            ("B2", "CO4115", "2026-10-20", "RM Processing Accepted Letter Of Offer", "3000000"),
            ("B3", "DSR999", "2026-10-21", "RM Processing Accepted Letter Of Offer", "9000000"),
        ])
        got = la.accepted_offers("CO4115", 2026, dt.date(2026, 10, 31))
        self.assertEqual((got["applications"], got["amount"]), (2, 15_000_000))

    def test_tat_reads_the_former_code(self):
        with mock.patch.object(lts, "seller_month_tat", return_value={"DSR421": 4.5}):
            self.assertEqual(lts.tat_for_codes(la.seller_codes("CO4115"), 2026, 10),
                             (4.5, ["DSR421"]))
        with mock.patch.object(lts, "seller_month_tat", return_value={"XX": 1.0}):
            self.assertEqual(lts.tat_for_codes(["CO4115", "DSR421"], 2026, 10), (None, []))

    def test_two_codes_average_over_their_steps(self):
        with mock.patch.object(lts, "seller_month_tat",
                               return_value={"CO4115": 2.0, "DSR421": 8.0}), \
                mock.patch("apps.staff_management.feed_cache.cached",
                           side_effect=lambda key, fn: fn()), \
                mock.patch.object(lts, "_rows", return_value=[]), \
                mock.patch.object(lts, "seller_parts",
                                  return_value={"CO4115": (2.0, 1), "DSR421": (24.0, 3)}):
            # (2 + 24) / (1 + 3) steps, not (2 + 8) / 2.
            self.assertEqual(lts.tat_for_codes(["CO4115", "DSR421"], 2026, 10),
                             (6.5, ["CO4115", "DSR421"]))
