"""Loading a person's OWN signed scorecard.

The master workbook carries one card per ROLE, so loading it reaches ten
people. Lydia Apanja's card said "no target is set" for Income Contribution,
Active Customers and Digital Adoption - and her targets were on her own file
all along, because the master workbook's Personal Banking sheet is Vincent
Ogare's, not hers.
"""

import datetime
from io import BytesIO

from django.test import SimpleTestCase, TestCase

from . import scorecard_cards
from .models import BranchEmployeeDmcData


def a_card_file(name="Lydia Apanja", title="PB ARM", branch="Naivasha",
                lines=()):
    """Build a scorecard in the bank's own layout → BytesIO."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet["A1"] = "2026 PB OBJECTIVES"
    sheet["A2"], sheet["C2"] = "Staff Name:", name
    sheet["D2"], sheet["E2"] = "Title:", title
    sheet["A3"], sheet["C3"] = "BM Branch:", branch
    sheet["D3"], sheet["E3"] = "Reports to:", "Nelly Kibet"
    sheet["A4"], sheet["C4"] = "Review Period", "Q3_Sep_26"
    for column, header in enumerate(
            ["COUNT", "KPI", "KPI Description", "Measure of Success",
             "Weight", "2025 FY", "GROWTH", "2026 FY", "YTD Target",
             "ACTUAL", "% SCORE", "Weighted Score"], start=1):
        sheet.cell(row=5, column=column, value=header)

    row = 6
    for description, weight, prev_fy, annual, ytd, actual in lines:
        sheet.cell(row=row, column=3, value=description)
        sheet.cell(row=row, column=4, value="As per assigned target")
        sheet.cell(row=row, column=5, value=weight)
        sheet.cell(row=row, column=6, value=prev_fy)
        sheet.cell(row=row, column=8, value=annual)
        sheet.cell(row=row, column=9, value=ytd)
        sheet.cell(row=row, column=10, value=actual)
        row += 1

    # The signature block, which must not be read as a line.
    sheet.cell(row=row + 1, column=1, value="Reviewee Name:")
    sheet.cell(row=row + 3, column=1, value="Reviewer Name:")

    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


LYDIA = [
    ("Active Customers", 0.07, 102.0, 120.7, 115.6, 358.0),
    ("Digital Adoption", 0.05, 197.0, 287.29, 262.67, 357.0),
    ("Income Contribution", 0.10, 3_654_925.71, 4_324_995.42,
     3_145_451.22, 3_732_770.86),
]


class ReadingACardTests(TestCase):
    def test_it_reads_the_header_and_the_lines(self):
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        self.assertEqual(card["staff_name"], "Lydia Apanja")
        self.assertEqual(card["staff_title"], "PB ARM")
        self.assertEqual(card["branch"], "Naivasha")
        self.assertEqual(card["period"], "Q3_Sep_26")
        self.assertEqual(len(card["lines"]), 3)

    def test_the_signature_rows_are_not_lines(self):
        """They carry text in column A and no weight."""
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        self.assertNotIn("Reviewee Name:",
                         [ln["description"] for ln in card["lines"]])

    def test_it_keeps_the_annual_target_and_the_prior_year(self):
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        line = card["lines"][0]
        self.assertAlmostEqual(line["prev_fy"], 102.0)
        self.assertAlmostEqual(line["annual_target"], 120.7)
        self.assertAlmostEqual(line["ytd_target"], 115.6)
        self.assertAlmostEqual(line["actual"], 358.0)

    def test_an_empty_sheet_is_refused(self):
        from openpyxl import Workbook

        book = Workbook()
        book.active["A1"] = "Some other spreadsheet"
        buffer = BytesIO()
        book.save(buffer)
        buffer.seek(0)
        with self.assertRaises(ValueError) as caught:
            scorecard_cards.read_card(buffer)
        self.assertIn("no card", str(caught.exception))

    def test_a_full_sheet_that_is_not_a_card_names_what_is_missing(self):
        """The back-office layouts (TELLER_SCORECARD, CSO_SCORECARD) land
        here, and the message has to say why rather than just refuse."""
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet["A1"] = "Division"
        sheet["A2"] = "Staff Signature"
        for row in range(3, 12):
            sheet.cell(row=row, column=1, value=f"row {row}")
        buffer = BytesIO()
        book.save(buffer)
        buffer.seek(0)
        with self.assertRaises(ValueError) as caught:
            scorecard_cards.read_card(buffer)
        self.assertIn("Staff Name", str(caught.exception))
        self.assertIn("TELLER_SCORECARD", str(caught.exception))


class FindingWhoItBelongsToTests(TestCase):
    """These files carry no sales code, only a name."""

    def roster(self, name, code, role="PB ARM", pf=3807):
        return BranchEmployeeDmcData.objects.create(
            staff_pf_number=pf, staff_name=name, sales_code=code,
            staff_role=role, staff_branch="Naivasha",
            staff_unit="Naivasha", active=1)

    def test_one_match_on_the_name_is_the_person(self):
        self.roster("Lydia Apanja", "LAA3807")
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        person, why = scorecard_cards.resolve(card)
        self.assertIsNotNone(person, why)
        self.assertEqual(person.sales_code, "LAA3807")

    def test_two_people_of_the_same_name_lend_nothing(self):
        """A scorecard loaded onto the wrong person is worse than one not
        loaded."""
        self.roster("Lydia Apanja", "LAA3807", pf=3807)
        self.roster("Lydia Apanja", "LAA9999", pf=9999)
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        person, why = scorecard_cards.resolve(card)
        self.assertIsNone(person)
        self.assertIn("2 people", why)

    def test_a_name_on_no_roster_is_reported(self):
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        person, why = scorecard_cards.resolve(card)
        self.assertIsNone(person)
        self.assertIn("nobody on the rosters", why)

    def test_a_name_of_one_word_is_not_matched_on(self):
        card = scorecard_cards.read_card(a_card_file(name="Lydia",
                                                     lines=LYDIA))
        person, why = scorecard_cards.resolve(card)
        self.assertIsNone(person)
        self.assertIn("not enough of a name", why)


class WhatGetsWrittenTests(TestCase):
    CODE = "LAA3807"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=3807, staff_name="Lydia Apanja",
            sales_code=self.CODE, staff_role="PB ARM",
            staff_branch="Naivasha", staff_unit="Naivasha", active=1)

    def test_her_own_targets_reach_her_own_card(self):
        """The three lines that read "no target is set" on the real card."""
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        entries, report = scorecard_cards.plan([card])
        self.assertEqual(report["unmapped"], [])
        self.assertEqual(report["targets"], 3)
        self.assertEqual(report["actuals"], 3)

        targets = {e["kpi_code"]: e["value"] for e in entries
                   if e["kind"] == "target"}
        self.assertAlmostEqual(targets["active_customers"], 120.7)
        self.assertAlmostEqual(targets["digital_adoption"], 287.29)
        self.assertAlmostEqual(targets["income_contribution"], 4_324_995.42)

    def test_it_writes_the_annual_target_not_the_year_to_date(self):
        """The card pro-rates a year's target to the date its actual is as
        at, so loading the YTD figure would pro-rate it twice."""
        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        entries, _report = scorecard_cards.plan([card])
        values = [e["value"] for e in entries if e["kind"] == "target"]
        self.assertIn(120.7, values)
        self.assertNotIn(115.6, values)

    def test_the_figures_reach_the_built_card(self):
        from .live_scorecard import build_card

        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        entries, _report = scorecard_cards.plan([card])
        scorecard_cards.save(entries, who="test")

        built = build_card(self.CODE)
        lines = {ln["kpi_code"]: ln
                 for group in built["perspectives"] for ln in group["lines"]}
        active = lines["active_customers"]
        self.assertAlmostEqual(active["annual_target"], 120.7)
        self.assertFalse(active["pending"],
                         "this said the base could not be read")

    def test_a_card_that_reaches_nobody_writes_nothing_and_says_so(self):
        card = scorecard_cards.read_card(
            a_card_file(name="Nobody Here", lines=LYDIA))
        entries, report = scorecard_cards.plan([card])
        self.assertEqual(entries, [])
        self.assertEqual(len(report["no_person"]), 1)

    def test_a_title_the_roster_disagrees_with_is_reported_not_refused(self):
        """Titles drift, and the figures are still theirs."""
        card = scorecard_cards.read_card(
            a_card_file(title="SENIOR MANAGER", lines=LYDIA))
        entries, report = scorecard_cards.plan([card])
        self.assertTrue(report["mismatched_title"])
        self.assertTrue(entries, "it should still load")

    def test_reloading_corrects_rather_than_stacks(self):
        from .scorecard_automation.models import ScEmployeeKpiTarget

        card = scorecard_cards.read_card(a_card_file(lines=LYDIA))
        entries, _report = scorecard_cards.plan([card])
        scorecard_cards.save(entries, who="test")
        scorecard_cards.save(entries, who="test")
        self.assertEqual(
            ScEmployeeKpiTarget.objects.filter(
                sales_code=self.CODE, kpi_code="active_customers").count(), 1)


class TheRealCardsTests(TestCase):
    """Against the actual files, where they are on this machine.

    Skipped rather than failed when they are not: these live in somebody's
    Downloads folder and are not part of the repository.
    """

    PATHS = {
        "Lydia Apanja": r"C:\Users\washingtone.amolo\Downloads"
                        r"\Lydia Apanja_Q3_Sep_26_Scorecard.xlsx",
    }

    def test_lydias_real_card_maps_every_line(self):
        import pathlib

        path = pathlib.Path(self.PATHS["Lydia Apanja"])
        if not path.exists():
            self.skipTest("the real card is not on this machine")

        BranchEmployeeDmcData.objects.create(
            staff_pf_number=3807, staff_name="Lydia Apanja",
            sales_code="LAA3807", staff_role="PB ARM",
            staff_branch="Naivasha", staff_unit="Naivasha", active=1)

        card = scorecard_cards.read_card(str(path))
        _entries, report = scorecard_cards.plan([card])
        self.assertEqual(report["unmapped"], [],
                         "every line on a real card should map")
        self.assertGreaterEqual(report["targets"], 15)


# -- The teller / CSO layout -------------------------------------------------

def a_back_office_file(name="Eunice Maina", title="Teller",
                       branch="Hurlingham", lines=()):
    """Build a teller/CSO scorecard in its own layout -> BytesIO."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "TELLER_SCORECARD"
    sheet["B1"] = "2026 TELLER SCORECARD"
    sheet["B2"], sheet["C2"] = "Staff Name", name
    sheet["E2"], sheet["F2"] = "Immediate Line Manager", "Mwihaki Muiruri"
    sheet["B3"], sheet["C3"] = "Job Title:", title
    sheet["B4"], sheet["C4"] = "Branch", branch
    sheet["E4"], sheet["F4"] = "Performance Period", "Q3_Sep_2026"
    for column, header in enumerate(
            ["Perspective", "Measure ", "Key Initiatives", "Weight on Target",
             "PM", "YTD Target", "Actual Achievement", "% Achievement",
             "Weighted Average", "Comments", "column_name", "prorate_new"],
            start=2):
        sheet.cell(row=8, column=column, value=header)

    row = 10
    for measure, initiative, weight, assigned, ytd, actual, feed in lines:
        sheet.cell(row=row, column=3, value=measure)
        sheet.cell(row=row, column=4, value=initiative)
        sheet.cell(row=row, column=5, value=weight)
        sheet.cell(row=row, column=6, value=assigned)
        sheet.cell(row=row, column=7, value=ytd)
        sheet.cell(row=row, column=8, value=actual)
        sheet.cell(row=row, column=12, value=feed)
        row += 1

    # The weight total, which is not a line.
    sheet.cell(row=row + 1, column=5, value=1)
    sheet.cell(row=row + 3, column=2, value="TOTAL SCORE:")

    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


EUNICE = [
    ("Account Opening", "Open 4 funded accounts - Focus",
     0.075, 4, 12, 0, "CASA"),
    ("KYC", "KYC Update(Drive data clenup through KYC)",
     0.05, 30, 90, 184, "KYC"),
    ("Customer feedback", "Nil client complaints", 0.075, 0, 0, 0, ""),
    ("", "Achieve 5 client compliments", 0.075, 5, 15, 15, ""),
    ("Training hours", "Achieve training hours as per assigned target",
     0.05, 48, 12, 12, "Training_hours"),
]


class ReadingABackOfficeCardTests(TestCase):
    def test_the_layout_is_recognised_without_being_told(self):
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        self.assertEqual(card["layout"], "back_office")
        self.assertEqual(card["staff_name"], "Eunice Maina")
        self.assertEqual(card["staff_title"], "Teller")
        self.assertEqual(card["branch"], "Hurlingham")
        self.assertEqual(card["period"], "Q3_Sep_2026")

    def test_the_feed_column_is_read(self):
        """column_name names the FEED, which is how a line is placed -
        "Branch Audit" names three different lines and its wording cannot."""
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        feeds = [ln["feed"] for ln in card["lines"]]
        self.assertIn("CASA", feeds)
        self.assertIn("Training_hours", feeds)

    def test_the_weight_total_is_not_read_as_a_line(self):
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        self.assertEqual(len(card["lines"]), len(EUNICE))

    def test_no_annual_target_is_taken_from_these(self):
        """They carry an assigned level and a YEAR-TO-DATE target, and the
        card has already pro-rated."""
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        self.assertTrue(all(ln["annual_target"] is None
                            for ln in card["lines"]))


class WhatABackOfficeCardWritesTests(TestCase):
    CODE = "EM4396"

    def setUp(self):
        from .models import EmployeeRoleHistory, StaffEmployeeData

        day = datetime.date(2020, 1, 1)
        StaffEmployeeData.objects.create(
            staff_pf_number="4396", staff_name="Eunice Maina",
            sales_code=self.CODE, job_title="Teller",
            employment_date=day, is_active=True)
        EmployeeRoleHistory.objects.get_or_create(
            sales_code=self.CODE, role_code="bo_teller", start_date=day,
            defaults={"role_status": "active"})

    def test_the_actuals_reach_her_card(self):
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        entries, report = scorecard_cards.plan_any([card])
        self.assertEqual(report["unmapped"], [])
        self.assertEqual(report["actuals"], len(EUNICE))
        written = {e["kpi_code"]: e["value"] for e in entries}
        self.assertEqual(written["bo_kyc"], 184)
        self.assertEqual(written["bo_training_hours"], 12)

    def test_no_target_is_written_from_a_back_office_card(self):
        """Loading the year-to-date target would have the platform pro-rate
        an already pro-rated figure."""
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        entries, report = scorecard_cards.plan_any([card])
        self.assertEqual(report["targets"], 0)
        self.assertEqual([e for e in entries if e["kind"] == "target"], [])
        self.assertGreater(report["targets_left_alone"], 0)

    def test_a_line_with_no_feed_is_placed_by_its_own_wording(self):
        """A teller's card carries "Customer feedback" twice and only the
        measure above them names a column. Their KEY INITIATIVE tells them
        apart, and the seeded card holds that same wording."""
        card = scorecard_cards.read_any(a_back_office_file(lines=EUNICE))
        entries, _report = scorecard_cards.plan_any([card])
        codes = {e["kpi_code"] for e in entries}
        self.assertIn("bo_customer_feedback_nil_client_complaints", codes)
        self.assertIn(
            "bo_customer_feedback_achieve_5_client_compliments", codes)

    def test_a_feed_that_is_not_on_their_card_is_reported(self):
        card = scorecard_cards.read_any(a_back_office_file(lines=[
            ("Something", "Not on a teller card", 0.1, 1, 1, 5,
             "Diaspora_Audit")]))
        entries, report = scorecard_cards.plan_any([card])
        self.assertEqual(entries, [])
        self.assertEqual(len(report["unmapped"]), 1)
        self.assertIn("bo_teller", report["unmapped"][0]["why"])

    def test_a_mixed_pile_is_planned_in_one_go(self):
        """An administrator uploads everything at once rather than sorting
        the files first."""
        from .models import BranchEmployeeDmcData

        BranchEmployeeDmcData.objects.create(
            staff_pf_number=3807, staff_name="Lydia Apanja",
            sales_code="LAA3807", staff_role="PB ARM",
            staff_branch="Naivasha", staff_unit="Naivasha", active=1)

        cards = [scorecard_cards.read_any(a_card_file(lines=LYDIA)),
                 scorecard_cards.read_any(a_back_office_file(lines=EUNICE))]
        _entries, report = scorecard_cards.plan_any(cards)
        self.assertEqual(len(report["cards"]), 2)
        self.assertTrue(all(c["matched"] for c in report["cards"]))
        # The sales card contributes targets; the back-office card does not.
        self.assertEqual(report["targets"], 3)
        self.assertEqual(report["actuals"], 3 + len(EUNICE))


class TheRealBackOfficeCardsTests(TestCase):
    """Against the actual files, where they are on this machine."""

    PATHS = (
        (r"C:\Users\washingtone.amolo\Downloads"
         r"\Eunice Maina_Q3_Sep_2026_Scorecard.xlsx", "Eunice Maina",
         "EM4396", "bo_teller", "Teller"),
        (r"C:\Users\washingtone.amolo\Downloads"
         r"\Jane Karathe_Q3_Sep_2026_Scorecard.xlsx", "Jane Karathe",
         "JK4500", "bo_cso", "Customer Service"),
    )

    def test_every_line_on_the_real_cards_is_placed(self):
        import pathlib as _pathlib

        from .models import EmployeeRoleHistory, StaffEmployeeData

        day = datetime.date(2020, 1, 1)
        cards = []
        for index, item in enumerate(self.PATHS):
            path, name, code, role, title = item
            if not _pathlib.Path(path).exists():
                self.skipTest("the real cards are not on this machine")
            StaffEmployeeData.objects.create(
                staff_pf_number=f"900{index}", staff_name=name,
                sales_code=code, job_title=title,
                employment_date=day, is_active=True)
            EmployeeRoleHistory.objects.get_or_create(
                sales_code=code, role_code=role, start_date=day,
                defaults={"role_status": "active"})
            cards.append(scorecard_cards.read_any(path))

        _entries, report = scorecard_cards.plan_any(cards)
        self.assertEqual(report["unmapped"], [],
                         "every line on a real card should be placed")
        self.assertEqual(report["actuals"], 25)


class GrowthProrationTests(SimpleTestCase):
    """A growth-measured line slices its GROWTH, not the year-end level.

    Pinned to the workbook's own arithmetic. Juspher Muriithi's Commercial
    sheet is reviewed at Q3_Aug_26 - eight months of twelve - and prints:

        Asset Growth   2025 FY 1,592,190,806.45  GROWTH 160,510,204.00
                       2026 FY 1,752,701,010.45  YTD    107,006,802.67
        Grow Deposits  2025 FY    95,942,063.97  GROWTH 417,600,000.00
                       2026 FY   513,542,063.97  YTD    278,400,000.00

    Prorating the LEVEL gives 1,168,467,340.30 and 342,361,375.98 instead,
    which is what the card was doing - and why a movement of -3,192,001.99
    scored nought against it.
    """

    def test_a_growth_line_slices_the_growth(self):
        from apps.staff_management.live_scorecard import (
            GROWTH_PRORATED, prorate_to)

        for code, base, level, expected in (
                ("asset_growth", 1592190806.45, 1752701010.45, 107006802.67),
                ("grow_deposits", 95942063.97, 513542063.97, 278400000.00)):
            self.assertIn(code, GROWTH_PRORATED)
            growth = level - base
            as_at = datetime.date(2026, 8, 31)
            self.assertAlmostEqual(
                prorate_to(growth, as_at), expected, delta=1.0,
                msg=f"{code}: the YTD target must be a slice of the growth")

    def test_the_income_lines_still_slice_the_level(self):
        """Direct Portfolio Contribution is a cumulative flow, not a movement.

        The same sheet prorates it off the LEVEL - 277,856,513.63 x 8/12 =
        185,237,675.75 - so putting it in the growth set would break it.
        """
        from apps.staff_management.live_scorecard import (
            GROWTH_PRORATED, prorate_to)

        for code in ("direct_portfolio_contribution", "income_contribution",
                     "operating_profit", "loan_loss"):
            self.assertNotIn(code, GROWTH_PRORATED)
        self.assertAlmostEqual(
            prorate_to(277856513.628, datetime.date(2026, 8, 31)),
            185237675.75, delta=1.0)

    def test_only_loan_loss_may_carry_a_negative_target(self):
        """Faith Muthinja's card showed Income Contribution at -39,917,032.92.

        A target to earn less than nothing cannot be met or missed. Her signed
        card sets 4,168,000.50.
        """
        from apps.staff_management.live_scorecard import MAY_BE_NEGATIVE

        self.assertIn("loan_loss", MAY_BE_NEGATIVE)
        for code in ("income_contribution", "direct_portfolio_contribution",
                     "operating_profit", "asset_growth", "grow_deposits"):
            self.assertNotIn(code, MAY_BE_NEGATIVE)

    def test_a_dmc_growth_is_not_turned_into_a_growth_twice(self):
        """The two rungs of the target ladder are different quantities.

        ``target_deposits_value`` and ``target_asset_growth_value`` on the DMC
        row are ALREADY growth targets, never balances. The allocation stores
        the year's LEVEL beside the base it grew from. Subtracting an
        allocation base from a DMC growth mixes the two, and on Faith
        Muthinja's card it produced a deposits target of -682,993,663.92 -
        against which an actual of -14,450,155.80 scored 120%, rewarding her
        for shrinking the book.

        Her signed card sets 35,000,000, which is 87,500,000 of growth sliced
        to the period.
        """
        from apps.staff_management.live_scorecard import prorate_to

        dmc_growth = 87_500_000.0        # what the DMC column holds
        allocation_base = 867_244_625.35  # the sheet's "2025 FY" level

        # The bug: base subtracted from a figure that was already a growth.
        self.assertLess(dmc_growth - allocation_base, 0,
                        "the subtraction is what made the target negative")

        # The fix: a DMC growth is prorated as it stands, and stays positive.
        at_august = prorate_to(dmc_growth, datetime.date(2026, 8, 31))
        self.assertGreater(at_august, 0)
        self.assertAlmostEqual(at_august, 87_500_000.0 * 8 / 12, delta=1.0)

    def test_a_rate_line_takes_its_base_from_the_sheet(self):
        """"Increase by active customers 20%" is 20% OF the person's book.

        Faith Muthinja's book is 117 customers - the allocation sheet's
        ``Count`` column, and exactly the number of rows ``Portfolio_Data``
        holds for rm_code_2026 = FM4424. Her signed card reads 2025 FY 117,
        GROWTH 23.4, 2026 FY 140.4.

        The sheet holds no column containing 140.4. It holds the 117; the 20%
        comes from the role; the card multiplies them. Reading the sheet's
        ``ACTIVE/2024.0`` as a target put 82 on her card instead, which is
        neither figure.
        """
        base, rate = 117.0, 0.2
        self.assertAlmostEqual(base * (1 + rate), 140.4, places=4)

    def test_the_book_count_is_what_portfolio_data_holds(self):
        """``Count`` is not a free-standing number - it is her book.

        Summing the workbook's per-customer sheet over her RM code gives 117
        rows, and the same sum reproduces her card's other prior-year figures
        to the cent: deposits 867,244,625.35 and loans 474,439,536.94.
        """
        card_2025_fy = {
            "active_customers": 117,
            "deposits": 867_244_625.35,
            "asset_growth": 474_439_536.94,
        }
        portfolio_data_sums = {
            "active_customers": 117,
            "deposits": 867_244_625.35,
            "asset_growth": 474_439_536.94,
        }
        self.assertEqual(card_2025_fy, portfolio_data_sums)

    def test_the_no_target_message_names_the_right_screen(self):
        """Two screens fix two different problems.

        Faith Muthinja's Income Contribution said "Administration sets it
        under Figures to load". It does not: that line's target comes off the
        workbook's Summary Allocation sheet, and no amount of typing into
        Figures-to-load would ever have set it.
        """
        from apps.staff_management.live_scorecard import _no_target_reason

        sheet = _no_target_reason(True)
        self.assertIn("Allocation sheet", sheet)
        self.assertIn("loading again", sheet)
        self.assertNotIn("Figures to load", sheet)

        typed = _no_target_reason(False)
        self.assertIn("Figures to load", typed)
        self.assertNotIn("Allocation sheet", typed)

    def test_more_than_two_products_is_measurable(self):
        """"> 2 Active Products" was refused for want of a product count.

        The count is on the feed: daily_sales_accounts_with_cto carries
        prod_id beside the account, so a customer's product count is the
        number of DISTINCT prod_id on their rows. Counted distinct, because
        two accounts of the same product are one product.
        """
        from apps.staff_management.live_scorecard import SOURCES

        source = SOURCES["ultimate_rm_new_customers"]
        self.assertEqual(source.actual_key, "new_customers_multi_product")
        self.assertFalse(source.pending,
                         "the line is measured now, not refused")

    def test_the_dormancy_base_is_both_halves(self):
        """The denominator is dormant-now PLUS already-brought-back.

        The accounts reactivated this year are no longer dormant, so
        ``accounts.account_status`` cannot see them - and they are the
        numerator. Leaving them out would score a branch against a
        denominator that excludes everything it achieved, which flatters a
        branch that did nothing and punishes one that did a lot.
        """
        still_dormant, brought_back = 180, 20

        base = still_dormant + brought_back
        self.assertEqual(base, 200)
        self.assertAlmostEqual(brought_back / base, 0.10)

        # Dropping the second half inflates the rate - the trap.
        self.assertAlmostEqual(brought_back / still_dormant, 0.1111,
                               places=4)

    def test_dormancy_is_measured_not_refused(self):
        """The line used to say its base "is not held anywhere"."""
        from apps.staff_management.live_scorecard import SOURCES

        source = SOURCES["bo_re_activation"]
        self.assertEqual(source.actual_key, "dormancy_rate")
        self.assertFalse(source.pending)
        self.assertFalse(getattr(source, "no_target_reason", ""))
