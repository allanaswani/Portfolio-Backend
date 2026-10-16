"""Sending a scorecard out, and the grid the sent copy is laid out on.

The two things the desk asked for and the platform did not have: a button that
mails the card, and a file that looks like the card they already know.
"""

import datetime
from io import BytesIO

from django.core import mail
from django.test import TestCase

from . import scorecard_email as E
from .models import StaffEmployeeData
from .scorecard_signoff import HEADERS, build_card_workbook


def a_card(**over):
    card = {
        "staff": {"name": "Juspher Muriithi", "title": "COMMERCIAL RM",
                  "branch": "H/Q", "team_leader": "Floyd Mathias",
                  "sales_code": "JM4191"},
        "period": {"label": "Q3_Aug_26"},
        "performance_score": 0.4952,
        "perspectives": [{
            "perspective": "Financials (20.0%)", "weight": 0.2, "lines": [
                {"kpi_order": 1, "kpi_name": "Trade Income",
                 "measure_of_success": "As per assigned Target",
                 "weight": 0.05, "prior_year": None,
                 "annual_target": 9_600_000.0, "ytd_target": 6_400_000.0,
                 "ytd_actual": 121_042.81, "score": 0.0189129,
                 "weighted_score": 0.000945, "as_at": "as at 31 Aug 2026"},
                {"kpi_order": 2, "kpi_name": "Direct Portfolio Contribution",
                 "measure_of_success": "(GII-IE+NFI)", "weight": 0.1,
                 "prior_year": 231_547_094.69,
                 "annual_target": 277_856_513.628,
                 "ytd_target": 185_237_675.752, "ytd_actual": 183_369_929.77,
                 "score": 0.98991703, "weighted_score": 0.098991703,
                 "as_at": ""},
            ]}],
    }
    card.update(over)
    return card


class TheGridMatchesTheBanksOwnCardTests(TestCase):
    """Cell for cell, against the desk's own workbook.

    The sent file is the document a reviewer signs, so it has to be the one
    they already read. These positions are taken from the Commercial sheet of
    ``Portfolio Management - Q3 2026_scorecards.xlsb``.
    """

    def setUp(self):
        import openpyxl

        self.ws = openpyxl.load_workbook(build_card_workbook(a_card())).active

    def cell(self, ref):
        return self.ws[ref].value

    def test_the_header_block_is_where_the_bank_puts_it(self):
        self.assertIn("COMMERCIAL RM OBJECTIVES", self.cell("A1"))
        self.assertIn("HFCB", self.cell("A1"))
        self.assertEqual(self.cell("A2"), "Staff Name:")
        self.assertEqual(self.cell("C2"), "Juspher Muriithi")
        self.assertEqual(self.cell("D2"), "Title:")
        self.assertEqual(self.cell("E2"), "COMMERCIAL RM")
        self.assertEqual(self.cell("G2"), "Performance Score:")
        self.assertAlmostEqual(self.cell("K2"), 0.4952)
        self.assertEqual(self.cell("A3"), "BM Branch:")
        self.assertEqual(self.cell("E3"), "Floyd Mathias")
        self.assertEqual(self.cell("G3"), "Performance Rating:")
        self.assertEqual(self.cell("A4"), "Review Period")
        self.assertEqual(self.cell("C4"), "Q3_Aug_26")

    def test_the_twelve_columns_are_the_banks_twelve(self):
        self.assertEqual(
            [self.ws.cell(row=5, column=i).value
             for i in range(1, len(HEADERS) + 1)],
            ["COUNT", "KPI", "KPI Description", "Measure of Success",
             "Weight", "2025 FY", "GROWTH", "2026 FY", "YTD Target",
             "ACTUAL", "% SCORE", "Weighted Score"])

    def test_the_perspective_is_named_once_against_its_first_line(self):
        self.assertEqual(self.cell("A6"), 1)
        self.assertEqual(self.cell("B6"), "Financials (20.0%)")
        self.assertEqual(self.cell("C6"), "Trade Income")
        # The second line of the same perspective does not repeat it.
        self.assertIsNone(self.cell("B7"))
        self.assertEqual(self.cell("C7"), "Direct Portfolio Contribution")

    def test_growth_is_the_target_less_the_prior_year(self):
        """F + G = H, which is how the bank's sheet reads. Reproduces the
        Commercial card's own row to the cent."""
        self.assertAlmostEqual(self.cell("F7"), 231_547_094.69, places=2)
        self.assertAlmostEqual(self.cell("G7"), 46_309_418.94, places=2)
        self.assertAlmostEqual(self.cell("H7"), 277_856_513.63, places=2)
        self.assertAlmostEqual(
            self.cell("F7") + self.cell("G7"), self.cell("H7"), places=1)

    def test_with_no_prior_year_the_whole_target_is_the_growth(self):
        self.assertIsNone(self.cell("F6"))
        self.assertEqual(self.cell("G6"), self.cell("H6"))

    def test_a_weighted_score_is_not_rounded_away(self):
        """``_money`` rounds to two decimals, which would turn 0.000945 into
        nought. Weights and scores are fractions and keep their precision."""
        self.assertAlmostEqual(self.cell("L6"), 0.000945, places=6)
        self.assertAlmostEqual(self.cell("E6"), 0.05)

    def test_the_signature_rows_use_the_banks_wording(self):
        text = [self.ws.cell(row=r, column=c).value
                for r in range(1, self.ws.max_row + 1)
                for c in range(1, 13)]
        self.assertIn("Reviewee Name:", text)
        self.assertIn("Reviewee Sign and date", text)
        self.assertIn("Reviewer Name:", text)
        self.assertIn("Reviewer Sign and date", text)

    def test_a_pending_line_prints_its_reason_not_a_nought(self):
        import openpyxl

        card = a_card(perspectives=[{
            "perspective": "Group Synergies (20.0%)", "weight": 0.04,
            "lines": [{"kpi_order": 1, "kpi_name": "Mobile onboarding",
                       "measure_of_success": "1 day", "weight": 0.04,
                       "pending": "No feed records this turnaround."}]}])
        ws = openpyxl.load_workbook(build_card_workbook(card)).active
        self.assertEqual(ws["J6"].value, "No feed records this turnaround.")
        self.assertIsNone(ws["K6"].value)

    def test_the_sheet_cannot_be_edited(self):
        self.assertTrue(self.ws.protection.sheet)


class WhoItGoesToTests(TestCase):
    CODE = "JM4191"

    def roster(self, name, email, code="", pf="9999"):
        return StaffEmployeeData.objects.create(
            staff_pf_number=pf, staff_name=name, staff_email=email,
            sales_code=code, job_title="RM",
            employment_date=datetime.date(2020, 1, 1), is_active=True)

    def test_the_person_is_found_by_sales_code_and_the_manager_by_name(self):
        self.roster("Juspher Muriithi", "juspher@hfgroup.co.ke",
                    code=self.CODE, pf="4191")
        self.roster("Floyd Mathias", "floyd@hfgroup.co.ke", pf="1001")
        to, cc, problems = E.recipients_for(a_card())
        self.assertEqual(to, ["juspher@hfgroup.co.ke"])
        self.assertEqual(cc, ["floyd@hfgroup.co.ke"])
        self.assertEqual(problems, [])

    def test_a_missing_address_is_reported_and_names_where_it_lives(self):
        to, _cc, problems = E.recipients_for(a_card())
        self.assertEqual(to, [])
        self.assertTrue(any("staff_employee_data" in p for p in problems))
        # And it says the workbook's column is the MANAGER's, which is the
        # mistake this would otherwise invite.
        self.assertTrue(any("manager" in p for p in problems))

    def test_two_people_of_the_same_name_lend_no_address(self):
        """A scorecard sent to the wrong Joseph is not a near miss."""
        self.roster("Juspher Muriithi", "juspher@hfgroup.co.ke",
                    code=self.CODE, pf="4191")
        self.roster("Floyd Mathias", "floyd.a@hfgroup.co.ke", pf="1001")
        self.roster("Floyd Mathias", "floyd.b@hfgroup.co.ke", pf="1002")
        _to, cc, problems = E.recipients_for(a_card())
        self.assertEqual(cc, [])
        self.assertTrue(any("more than one" in p for p in problems))

    def test_the_manager_is_not_copied_on_their_own_card(self):
        self.roster("Floyd Mathias", "floyd@hfgroup.co.ke",
                    code="FM1001", pf="1001")
        card = a_card()
        card["staff"] = dict(card["staff"], name="Floyd Mathias",
                             sales_code="FM1001",
                             team_leader="Floyd Mathias")
        to, cc, _problems = E.recipients_for(card)
        self.assertEqual(to, ["floyd@hfgroup.co.ke"])
        self.assertEqual(cc, [])


class SendingTests(TestCase):
    def setUp(self):
        StaffEmployeeData.objects.create(
            staff_pf_number="4191", staff_name="Juspher Muriithi",
            staff_email="juspher@hfgroup.co.ke", sales_code="JM4191",
            job_title="RM", employment_date=datetime.date(2020, 1, 1),
            is_active=True)

    def test_it_sends_with_the_read_only_workbook_attached(self):
        import openpyxl

        record = E.send_card(a_card(), who="Washington Amolo")
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["juspher@hfgroup.co.ke"])
        self.assertIn("HFCB scorecard", sent.subject)
        self.assertIn("unsigned", sent.subject)
        self.assertEqual(len(sent.attachments), 1)
        name, content, mimetype = sent.attachments[0]
        self.assertTrue(name.endswith(".xlsx"))
        self.assertIn("spreadsheetml", mimetype)
        self.assertTrue(
            openpyxl.load_workbook(BytesIO(content)).active.protection.sheet)

        # And the send is on the record, with who pressed it.
        self.assertEqual(record.sent_to, "juspher@hfgroup.co.ke")
        self.assertEqual(record.sent_by_name, "Washington Amolo")
        self.assertFalse(record.was_signed)

    def test_an_address_typed_by_hand_is_added(self):
        E.send_card(a_card(), extra_to=["head.office@hfgroup.co.ke"])
        self.assertEqual(sorted(mail.outbox[0].to),
                         ["head.office@hfgroup.co.ke",
                          "juspher@hfgroup.co.ke"])

    def test_nothing_is_sent_when_there_is_nobody_to_send_it_to(self):
        StaffEmployeeData.objects.all().delete()
        with self.assertRaises(ValueError) as caught:
            E.send_card(a_card())
        self.assertIn("staff_employee_data", str(caught.exception))
        self.assertEqual(mail.outbox, [])

    def test_a_signed_card_says_so_rather_than_saying_unsigned(self):
        class Frozen:
            signed_at = datetime.datetime(2026, 9, 5, 9, 30)
            signed_by_name = "Juspher Muriithi"
            manager_signed_at = None
            manager_signed_by_name = ""
            owner_comment = ""
            manager_comment = ""

        subject, body = E.compose(a_card(), Frozen())
        self.assertNotIn("unsigned", subject)
        self.assertIn("05 Sep 2026", body)
        self.assertIn("counter-sign", body)
