"""The two things that have to be right before a card can be signed.

1. the TARGET is the person's own, off the per-person DMC table
2. the target is sliced to the same date as the ACTUAL it is compared with

Both have been wrong, and both were wrong in the direction that flatters or
punishes somebody by an order of magnitude, so each has its own test.
"""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from .live_scorecard import (
    STAFF_TABLE, BRANCH_TABLE, build_card, last_closed_month_end, prorate_to,
    roster_target_row, score_for,
)
from .models import BranchEmployeeDmcData, BranchFinalEmployeeDmcData
from .scorecard_signoff import build_card_workbook, period_for


class TargetsComeFromThePersonsOwnRowTests(TestCase):
    """``branch_employee_dmc_data`` is one row per SALES PERSON.
    ``branch_final_employee_dmc_data`` is one row per BRANCH. Reading the
    branch one for an RM scored an SME RM against a 14 million disbursement
    target where their card says 270 million."""

    CODE = "CMM4236"

    def staff_row(self, **kwargs):
        defaults = dict(
            staff_pf_number=4236, staff_name="Charles Muchiri",
            sales_code=self.CODE, staff_role="SME RM", staff_branch="Rehani",
            active=1, target_loan_disbursement=270_000_000,
            target_new_customers=24, target_deposits_value=120_000_000)
        defaults.update(kwargs)
        return BranchEmployeeDmcData.objects.create(**defaults)

    def branch_row(self, **kwargs):
        defaults = dict(
            staff_pf_number=4236, staff_name="Charles Muchiri",
            sales_code=self.CODE, staff_role="SME RM", staff_branch="Rehani",
            active=1, target_loan_disbursement=14_400_000,
            target_new_customers=4, target_deposits_value=38_400_000,
            target_pbt_revenue=900_000_000)
        defaults.update(kwargs)
        return BranchFinalEmployeeDmcData.objects.create(**defaults)

    def test_the_per_person_row_wins_over_the_branch_row(self):
        self.staff_row()
        self.branch_row()
        targets, table, _ = roster_target_row(self.CODE)
        self.assertEqual(table, STAFF_TABLE)
        self.assertEqual(targets["target_loan_disbursement"], 270_000_000)
        self.assertEqual(targets["target_new_customers"], 24)

    def test_somebody_with_no_personal_row_falls_back_to_the_branch_row(self):
        """A BBM's personal row IS the branch row, so without this they would
        have no targets at all."""
        self.branch_row()
        targets, table, _ = roster_target_row(self.CODE)
        self.assertEqual(table, BRANCH_TABLE)
        self.assertEqual(targets["target_loan_disbursement"], 14_400_000)

    def test_a_branch_only_target_is_not_lent_to_an_rm(self):
        """``target_pbt_revenue`` is on the branch table and not the staff one.

        Handing an RM the BRANCH's revenue target would read as a couple of
        percent and paint a fully performing RM red, so the line reports that
        the column is missing instead of borrowing a figure from a different
        grain."""
        self.staff_row()
        self.branch_row()
        targets, table, columns = roster_target_row(self.CODE)
        self.assertEqual(table, STAFF_TABLE)
        self.assertNotIn("target_pbt_revenue", columns)
        self.assertIsNone(targets.get("target_pbt_revenue"))

        card = build_card(self.CODE)
        lines = [ln for g in card["perspectives"] for ln in g["lines"]]
        profit = [ln for ln in lines if ln["kpi_code"] == "operating_profit"]
        self.assertTrue(profit, "the SME RM card has an Operating Profit line")
        self.assertEqual(profit[0]["pending_label"], "No target set")
        self.assertIsNone(profit[0]["score"])
        self.assertIsNone(profit[0]["ytd_target"])

    def test_the_card_says_which_table_its_targets_came_from(self):
        """A figure nobody can trace is a figure nobody will sign."""
        self.staff_row()
        card = build_card(self.CODE)
        self.assertEqual(card["target_source"], STAFF_TABLE)
        lines = [ln for g in card["perspectives"] for ln in g["lines"]]
        disbursements = [ln for ln in lines
                         if ln["kpi_code"] == "net_asset_disbursements"][0]
        self.assertEqual(disbursements["target_field"],
                         "target_loan_disbursement")
        self.assertEqual(disbursements["annual_target"], 270_000_000)


class ProrationTests(TestCase):
    """The target is sliced to the date the ACTUAL is as at — not to today.

    The eight Q3 cards put the YTD target at 8/12 of the year with actuals to
    31 August. 31 August is day 243 of 365, so the two agree to one part in
    750; comparing an August actual against a target sliced to today would
    hand the RM nine weeks of plan they never had the chance to earn.
    """

    def test_a_month_end_actual_matches_the_cards_own_months_over_twelve(self):
        annual = 270_000_000
        august = datetime.date(2026, 8, 31)
        self.assertAlmostEqual(prorate_to(annual, august),
                               annual * 8 / 12, delta=annual * 0.002)

    def test_the_slice_follows_the_actuals_date_not_today(self):
        annual = 1_200_000
        january = prorate_to(annual, datetime.date(2026, 1, 31))
        december = prorate_to(annual, datetime.date(2026, 12, 31))
        self.assertLess(january, december)
        self.assertAlmostEqual(december, annual, delta=1)

    def test_counts_come_out_whole(self):
        """"589.578 new customers" is not a target anybody can be held to."""
        value = prorate_to(897, datetime.date(2026, 9, 5), counted=True)
        self.assertEqual(value, float(round(value)))

    def test_no_target_stays_no_target(self):
        self.assertIsNone(prorate_to(None, datetime.date(2026, 9, 5)))

    def test_a_monthly_feed_is_dated_to_the_last_closed_month(self):
        """A feed loaded monthly cannot be current to today, and saying it is
        would slice the target past the actual."""
        self.assertEqual(last_closed_month_end(datetime.date(2026, 10, 9)),
                         datetime.date(2026, 9, 30))
        self.assertEqual(last_closed_month_end(datetime.date(2026, 1, 3)),
                         datetime.date(2025, 12, 31))


class LoanLossScoringTests(TestCase):
    """Provisions are a ceiling. Nil provisions is the best outcome, and the
    line on the card is literally titled "Nil provisions"."""

    def test_under_the_ceiling_scores_above_target(self):
        self.assertAlmostEqual(score_for(500_000, 1_000_000, False), 1.2)

    def test_over_the_ceiling_scores_below(self):
        self.assertAlmostEqual(score_for(2_000_000, 1_000_000, False), 0.5)

    def test_nil_provisions_is_the_best_score_not_a_division_by_zero(self):
        self.assertAlmostEqual(score_for(0, 1_000_000, False), 1.2)


class SignoffTests(TestCase):
    """Signing freezes the figures. A signature against numbers that move
    means nothing."""

    CODE = "FJ4145"

    def setUp(self):
        self.user = User.objects.create_user(
            "fjabani", password="x", first_name="Fridah", last_name="Jabani")
        Profile.objects.update_or_create(
            user=self.user,
            defaults={"sales_code": self.CODE, "branch": "Nyeri"})
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4145, staff_name="Fridah Jabani",
            sales_code=self.CODE, staff_role="SME BBC", staff_branch="Nyeri",
            team_leader="Jane Manager", active=1,
            target_deposits_value=38_400_000, target_new_customers=12,
            target_loan_disbursement=108_000_000)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_signing_stores_the_card_as_it_stood(self):
        response = self.client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "owner", "comment": "Agreed"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        signoff = response.data["signoff"]
        self.assertTrue(signoff["signed"])
        self.assertEqual(signoff["signed_by"], "Fridah Jabani")
        self.assertEqual(signoff["owner_comment"], "Agreed")

        from .scorecard_automation.models import ScorecardSignoff
        stored = ScorecardSignoff.objects.get(sales_code=self.CODE)
        self.assertEqual(stored.period, period_for())
        self.assertTrue(stored.card.get("has_card"))
        self.assertEqual(stored.performance_score,
                         stored.card["performance_score"])

    def test_a_signed_card_is_served_as_signed_not_recomputed(self):
        self.client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "owner"}, format="json")
        response = self.client.get(
            "/staff_management/scorecard-automation/my-card/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["live"],
                         "a signed card must not show live figures under the "
                         "signature")
        self.assertTrue(response.data["signoff"]["signed"])

    def test_a_colleague_cannot_counter_sign(self):
        self.client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "owner"}, format="json")
        other = User.objects.create_user("nosy", password="x",
                                         first_name="Not", last_name="Manager")
        client = APIClient()
        client.force_authenticate(other)
        response = client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "manager", "sales_code": self.CODE}, format="json")
        self.assertEqual(response.status_code, 403, response.content)

    def test_the_named_manager_can_counter_sign(self):
        self.client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "owner"}, format="json")
        manager = User.objects.create_user(
            "jmanager", password="x", first_name="Jane", last_name="Manager")
        client = APIClient()
        client.force_authenticate(manager)
        response = client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "manager", "sales_code": self.CODE,
             "comment": "Discussed"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["signoff"]["fully_signed"])

    def test_a_manager_cannot_counter_sign_an_unsigned_card(self):
        manager = User.objects.create_user(
            "jmanager2", password="x", first_name="Jane", last_name="Manager")
        client = APIClient()
        client.force_authenticate(manager)
        response = client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "manager", "sales_code": self.CODE}, format="json")
        self.assertEqual(response.status_code, 409, response.content)

    def test_download_returns_a_workbook(self):
        response = self.client.get(
            "/staff_management/scorecard-automation/my-card/download/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("spreadsheetml", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"PK"), "not a .xlsx")

    def test_the_signed_download_carries_the_signature_and_drops_the_warning(self):
        """The file and the signature have to agree: a signed card downloaded
        without the signature on it is a document somebody can present as
        unsigned."""
        from io import BytesIO

        from openpyxl import load_workbook

        self.client.post(
            "/staff_management/scorecard-automation/my-card/sign/",
            {"role": "owner", "comment": "Agreed with my manager"},
            format="json")
        response = self.client.get(
            "/staff_management/scorecard-automation/my-card/download/")
        self.assertEqual(response.status_code, 200, response.content)

        sheet = load_workbook(BytesIO(response.content)).active
        text = "\n".join(
            " ".join("" if c.value is None else str(c.value) for c in row)
            for row in sheet.iter_rows())
        self.assertIn("Fridah Jabani", text)
        self.assertIn("Agreed with my manager", text)
        self.assertNotIn("unsigned", text)

    def test_the_workbook_carries_the_lines_and_a_signature_block(self):
        from openpyxl import load_workbook
        from io import BytesIO

        card = build_card(self.CODE)
        book = load_workbook(BytesIO(build_card_workbook(card).read()))
        sheet = book.active
        text = "\n".join(
            " ".join("" if c.value is None else str(c.value) for c in row)
            for row in sheet.iter_rows())
        # The bank is HFCB; HFC is the old name and must not go out on a
        # document somebody signs.
        self.assertIn("HFCB", text)
        self.assertIn("OBJECTIVES", text)
        self.assertIn("Fridah Jabani", text)
        self.assertIn("Staff Name:", text)
        # The bank's own signature wording, not ours. A reviewer signs where
        # they expect to sign.
        self.assertIn("Reviewee Name:", text)
        self.assertIn("Reviewer Sign and date", text)
        self.assertIn("TOTAL PERFORMANCE SCORE", text)
        self.assertIn("unsigned", text,
                      "an unsigned download must say so on the sheet")

    def test_a_pending_line_prints_its_reason_where_the_figure_would_go(self):
        """A pending line has no number, and a zero in the ACTUAL column reads
        as "achieved nothing" - which is a different statement from "nobody
        has this figure". A line that genuinely stands at nil, like drawdowns
        for an RM who has disbursed nothing, is a real zero and stays one."""
        from io import BytesIO

        from openpyxl import load_workbook

        card = build_card(self.CODE)
        lines = {ln["kpi_name"]: ln
                 for g in card["perspectives"] for ln in g["lines"]}
        pending_names = {name for name, ln in lines.items() if ln["pending"]}
        self.assertTrue(pending_names, "nothing is pending, which cannot be "
                                       "right on an empty warehouse")

        book = load_workbook(BytesIO(build_card_workbook(card).read()))
        sheet = book.active
        # The bank's grid: C is the KPI, E its weight, J the ACTUAL. A data
        # row is one with a KPI and a numeric weight - column A numbers the
        # PERSPECTIVE and is blank on every line but its first, so it cannot
        # be what identifies a line.
        printed = {}
        for row in sheet.iter_rows(min_row=6):
            kpi, weight, actual = row[2].value, row[4].value, row[9].value
            if kpi and isinstance(weight, (int, float)):
                printed[kpi] = actual

        for name in pending_names:
            with self.subTest(name):
                self.assertIsInstance(
                    printed.get(name), str,
                    f"{name} is pending but printed {printed.get(name)!r}")


class EveryLineIsAccountedForTests(TestCase):
    """No KPI may reach the card without somebody having decided what it is.

    Without this, adding a role card seeds KPIs that fall through to the
    default and quietly tell the person "measured outside the warehouse" -
    which may be a lie, and is the kind of lie nobody notices because it looks
    like a considered answer.
    """

    def test_every_seeded_kpi_has_an_explicit_source(self):
        from .live_scorecard import SOURCES
        from .scorecard_automation.models import ScKpi

        codes = set(ScKpi.objects.values_list("kpi_code", flat=True))
        self.assertTrue(codes, "the scorecard config was not seeded")
        self.assertEqual(
            sorted(codes - set(SOURCES)), [],
            "these KPIs would fall through to 'measured outside the "
            "warehouse' without anybody deciding that")

    def test_no_source_points_at_a_kpi_that_no_longer_exists(self):
        """A stale entry is a mapping somebody will trust and that never runs."""
        from .live_scorecard import SOURCES
        from .scorecard_automation.models import ScKpi

        codes = set(ScKpi.objects.values_list("kpi_code", flat=True))
        self.assertEqual(sorted(set(SOURCES) - codes), [])

    def test_a_scored_line_has_an_actual_and_a_route_to_a_target(self):
        """Half a mapping scores nothing, and reports the wrong reason for it.

        A route to a target is a DMC column OR a target on the role's card -
        the second is how PAR, NPS, TAT, training and the property lines get
        one, because there is no DMC column for any of them.
        """
        from .live_scorecard import SOURCES
        from .scorecard_automation.models import ScRoleKpiMapping

        with_role_target = set(
            ScRoleKpiMapping.objects.exclude(kpi_target=None)
            .values_list("kpi_code", flat=True))

        for code, source in sorted(SOURCES.items()):
            if source.pending:
                continue
            with self.subTest(code):
                self.assertTrue(source.actual_key,
                                f"{code} is scored but names no actual")
                # A line may deliberately carry a figure with no target, so
                # long as it SAYS so and the target is loadable. Dormancy is
                # the case: the reactivations are counted from the warehouse
                # but the rate they are scored as needs a dormant base that
                # does not exist, so the figure is shown, the reason is on the
                # card, and Administration enters the score. Without
                # no_target_reason this guard still fires, which is the point
                # of it - half a mapping scores nothing and reports the wrong
                # reason for it.
                from .scorecard_manual import MANUAL_TARGETS

                explained = bool(source.no_target_reason) and (
                    code in MANUAL_TARGETS)
                self.assertTrue(
                    source.target_field or code in with_role_target
                    or explained,
                    f"{code} is scored but nothing can give it a target: no "
                    f"DMC column, no target on any role's card, and no "
                    f"no_target_reason naming a route to one")


class TargetLadderTests(TestCase):
    """Where a line's target comes from when the DMC row has no column for it.

    Three rungs, most specific first, and the order is the point: an explicit
    figure for this person must always beat a derived one.
    """

    CODE = "JM4191"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4191, staff_name="Juspher Muriithi",
            sales_code=self.CODE, staff_role="COMMERCIAL RM",
            staff_branch="Rehani", active=1,
            target_deposits_value=417_600_000)

    def lines(self):
        card = build_card(self.CODE)
        self.assertTrue(card["has_card"], card)
        return {ln["kpi_code"]: ln
                for g in card["perspectives"] for ln in g["lines"]}

    def test_a_role_wide_threshold_supplies_a_target_with_no_dmc_column(self):
        """PAR, NPS, TAT, training and the property lines have no DMC column
        and never will - their target is one number for everybody on the
        card."""
        par = self.lines()["par"]
        self.assertEqual(par["annual_target"], 0.025)
        self.assertEqual(par["target_source"], "the target on your role's card")

    def test_a_threshold_is_not_prorated(self):
        """NPS of 60% does not become 45% because it is September, and PAR's
        2.5% ceiling does not loosen as the year runs on."""
        par = self.lines()["par"]
        self.assertTrue(par["full_year_target"])
        self.assertEqual(par["ytd_target"], par["annual_target"])

    def test_a_rate_target_is_taken_on_the_persons_own_base(self):
        """Asset Growth has no column on the per-person DMC table, and every
        card states it as a rate: "Grow by 21% of the Dec book Balance"."""
        from .scorecard_automation.models import ScRoleKpiMapping

        mapping = ScRoleKpiMapping.objects.get(
            role_code="commercial_rm", kpi_code="asset_growth")
        self.assertEqual(mapping.target_basis, "rate_on_base")
        self.assertEqual(mapping.target_base, "december_loan_book")
        self.assertAlmostEqual(mapping.kpi_target, 0.21)

    def test_no_role_target_holds_a_single_rms_own_balance(self):
        """Migration 0027 filled kpi_target from the eight calibration cards,
        so for the financial lines it held one named RM's closing balance.
        Read as a role target, every SME RM would be scored against Charles
        Muchiri's book."""
        from .scorecard_automation.models import ScRoleKpiMapping

        suspect = ScRoleKpiMapping.objects.filter(
            kpi_code__in=["asset_growth", "deposit_growth", "operating_profit",
                          "income_contribution", "grow_deposits",
                          "direct_portfolio_contribution", "loan_loss",
                          "active_customers", "digital_adoption",
                          "portfolio_management_aum_dec_previous_year"],
            target_basis="").exclude(kpi_target=None)
        self.assertFalse(
            [(m.role_code, m.kpi_code, m.kpi_target) for m in suspect],
            "a financial role target survived, which means somebody is being "
            "scored against another RM's balance")

    def test_the_dmc_column_still_wins(self):
        """The ladder is an order, not a replacement."""
        deposits = self.lines()["grow_deposits"]
        self.assertEqual(deposits["annual_target"], 417_600_000)
        self.assertIn("branch_employee_dmc_data", deposits["target_source"])

    def test_a_target_of_nought_is_treated_as_no_target(self):
        """It is how the cards say a line does not apply to a role - Mortgage
        Business carries a property target of 0 - and dividing by it would
        either crash or read as infinite achievement."""
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=9001, staff_name="Roy Gitonga",
            sales_code="RG9001", staff_role="Mortgage Business ARM",
            staff_branch="Rehani", active=1)
        card = build_card("RG9001")
        lines = {ln["kpi_code"]: ln
                 for g in card["perspectives"] for ln in g["lines"]}
        units = lines["number_of_property"]
        self.assertIsNone(units["annual_target"])
        self.assertIsNone(units["score"])
        self.assertEqual(units["pending_label"], "No target set")


class PropertySalesTests(TestCase):
    """The HFDI sales return is keyed on a NAME, which is the whole problem."""

    CODE = "FM4200"

    def setUp(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4200, staff_name="Faith Muthinja",
            sales_code=self.CODE, staff_role="Ultimate RM",
            staff_branch="Rehani", active=1)

    def sale(self, staff_name, value, when=None):
        from apps.hfdi.models import WeightedDashboardManualSales

        return WeightedDashboardManualSales.objects.create(
            staff_name=staff_name, unit_name=f"Unit {value}",
            unit_value=value,
            sale_month=when or datetime.date.today().replace(day=1))

    def line(self, code):
        card = build_card(self.CODE)
        return {ln["kpi_code"]: ln
                for g in card["perspectives"] for ln in g["lines"]}[code]

    def test_units_and_value_come_off_the_return(self):
        self.sale("Faith Muthinja", 8_200_000)
        self.sale("Faith Muthinja", 4_000_000)
        self.assertEqual(self.line("number_of_property")["ytd_actual"], 2)
        self.assertEqual(self.line("value_of_property_sales")["ytd_actual"],
                         12_200_000)

    def test_somebody_elses_sales_are_not_counted(self):
        self.sale("Somebody Else", 50_000_000)
        self.sale("Faith Muthinja", 1_000_000)
        self.assertEqual(self.line("number_of_property")["ytd_actual"], 1)

    def test_absent_from_a_POPULATED_feed_is_a_nil(self):
        """Somebody the feeds do not mention sold nothing, and the card now
        says so.

        This used to report "no figure", because a name spelt differently
        reads the same as somebody who sold nothing. Two things changed and
        the caution is no longer worth its cost: names are matched on their
        WORDS in any order, so the middle-name and surname-first spellings
        that caused the misses no longer miss; and the feeds can be asked
        whether they hold anything at all.

        A feed carrying other people's units that does not carry yours means
        you sold none. Reporting that as "no figure" leaves the line unscored
        for ever and quietly drags the card - a nil somebody can challenge is
        better than a blank they cannot."""
        self.sale("Somebody Else", 1_000_000)
        units = self.line("number_of_property")
        self.assertEqual(units["ytd_actual"], 0.0)
        self.assertFalse(units["pending"])
        self.assertIn("nil", units["as_at"])
        self.assertIn("none of the three property feeds", units["as_at"])

    def test_absent_from_an_EMPTY_feed_is_still_no_figure(self):
        """The honest exception. If no property feed holds anything, absence
        proves nothing about this person and a nil would be an invention."""
        units = self.line("number_of_property")
        self.assertIsNone(units["ytd_actual"])
        self.assertIn("no property feed holds any data", units["pending"])

    def test_affordable_housing_units_count_towards_the_property_line(self):
        """The HFDI return names the advisor who SOLD a unit; affordable
        housing names whoever ASSISTED the buyer, and a branch RM earns the
        synergy credit the second way."""
        from apps.hfdi.models import (
            AffordableHousingApplication, AFHSellerMapping)

        AFHSellerMapping.objects.create(
            staff_id=self.CODE, afh_name="faith m",
            name="Faith Muthinja", staff_unit="Nyeri")
        AffordableHousingApplication.objects.create(
            application_id="AFH-1", name="A Buyer", assisted_by="Faith M",
            preferred_typology="2 bed", typology="2 bed",
            house_type="Apartment", mode_of_payment="Mortgage",
            need_deposit_assitance="No", unit_price=5_000_000,
            status="Approved",
            timestamp=timezone.now())

        units = self.line("number_of_property")
        self.assertEqual(units["ytd_actual"], 1)
        self.assertIn("affordable housing", units["as_at"])
        self.assertEqual(
            self.line("value_of_property_sales")["ytd_actual"], 5_000_000)

    def test_the_two_returns_add_together(self):
        from apps.hfdi.models import (
            AffordableHousingApplication, AFHSellerMapping)

        self.sale("Faith Muthinja", 8_200_000)
        AFHSellerMapping.objects.create(
            staff_id="OTHER", afh_name="faith muthinja",
            name="Faith Muthinja")
        AffordableHousingApplication.objects.create(
            application_id="AFH-2", name="B Buyer",
            assisted_by="Faith Muthinja", preferred_typology="1 bed",
            typology="1 bed", house_type="Apartment",
            mode_of_payment="Cash", need_deposit_assitance="No",
            unit_price=3_000_000, status="Approved",
            timestamp=timezone.now())

        self.assertEqual(self.line("number_of_property")["ytd_actual"], 2)
        self.assertEqual(
            self.line("value_of_property_sales")["ytd_actual"], 11_200_000)

    def test_a_name_on_the_return_with_no_sales_this_year_is_a_real_nil(self):
        """Once the name is known to be on the return, nil means nil - and an
        RM who sold nothing scores nothing, which is what the cards do."""
        self.sale("Faith Muthinja", 9_000_000,
                  when=datetime.date(datetime.date.today().year - 2, 6, 1))
        units = self.line("number_of_property")
        self.assertEqual(units["ytd_actual"], 0)
        self.assertEqual(units["score"], 0.0)


class ThresholdScoringTests(TestCase):
    def test_par_is_met_or_not_met(self):
        self.assertAlmostEqual(
            score_for(0.009, 0.025, False, threshold=True), 1.2)
        self.assertAlmostEqual(
            score_for(0.025, 0.025, False, threshold=True), 1.2,
            msg="exactly at the limit is within it")
        self.assertAlmostEqual(
            score_for(0.026, 0.025, False, threshold=True), 0.0,
            msg="just over the limit is over it")

    def test_a_higher_is_better_threshold_works_the_other_way(self):
        self.assertAlmostEqual(score_for(0.65, 0.6, True, threshold=True), 1.2)
        self.assertAlmostEqual(score_for(0.55, 0.6, True, threshold=True), 0.0)


class NoKpiIsNamedAfterItsGroupTests(TestCase):
    """A perspective heading is not a measure, and must never be seeded as one.

    A scorecard row carries its GROUP only on the first line of that group,
    and its KPI name only on the first line of that KPI. A row stating a
    SECOND MEASURE of the same KPI - "life", then "non-life" - leaves the KPI
    column blank, and a parser that reads it alone falls back to the column
    beside it, which holds the group.

    That is how the non-life half of VIC Premiums came to be called "Group
    Synergies (23.0%)" and to print on eleven roles' cards, under its own
    weight, as though a perspective heading were something a person is
    measured on.

    A group heading always states its own weight, which is what makes this
    testable rather than a matter of judgement: no measure on any card is
    written "Something (23.0%)".
    """

    def test_no_kpi_name_carries_a_perspective_weight(self):
        import re

        from .scorecard_automation.models import ScKpi

        looks_like_a_group = re.compile(r"\(\s*\d+(\.\d+)?\s*%\s*\)")
        named_after_a_group = sorted(
            f"{k.kpi_code} -> {k.kpi_name!r}"
            for k in ScKpi.objects.all()
            if looks_like_a_group.search(k.kpi_name or ""))

        self.assertEqual(
            named_after_a_group, [],
            "these KPIs are named after the group heading above them, not "
            "after what they measure, and will print on a card as though a "
            "perspective were a measure")


class EveryRoleMatchesItsSheetTests(TestCase):
    """Line COUNT and total WEIGHT per role, checked against the workbook.

    Every sales role sheet was read back and diffed against what is seeded -
    count, order, weight and wording. Eleven of twelve agreed exactly.
    Personal Banking did not: the sheet has 18 lines and the seed had 19, the
    extra being a Loan Loss line at weight ZERO that the sheet does not
    carry at all.

    A zero weight is not harmless. The line prints on the card as a row and
    is counted among the lines a person is measured on, so the card claimed
    a measure the bank's own card does not have.

    The figures below are read off the workbook's role sheets, counting only
    rows that carry a feed key - the TOTAL row at the foot of each sheet has
    none, and a parser that takes it produces a phantom line at 100% weight.
    """

    #: role_code -> (lines on its sheet, total weight)
    FROM_THE_SHEETS = {
        "commercial_rm": (17, 1.025),
        "commercial_rm_trade": (16, 1.025),
        "diaspora_rm": (16, 1.025),
        "diaspora_arm": (16, 1.025),
        "mortgage_business_arm": (13, 1.025),
        # NINETEEN. The Personal_Banking sheet is the only one carrying a
        # zero-weight line - Reduce P&L provisions, at 0.0% - and the count
        # that produced the 18 here dropped it, because it skipped any row
        # whose weight was falsy. Migration 0054 then deleted the line as a
        # phantom; 0056 put it back. Lydia Apanja's signed Q3_Sep_26 PB ARM
        # card prints it, so it is on the document people sign.
        "pb_rm": (19, 1.025),
        "pb_arm": (19, 1.025),
        "pb_bbc": (19, 1.025),
        "sme_rm": (18, 1.025),
        "sme_arm": (18, 1.025),
        "sme_bbc": (18, 1.025),
        "ultimate_rm": (18, 1.025),
    }

    def test_each_role_has_the_lines_its_sheet_has(self):
        from django.db.models import Count, Sum

        from .scorecard_automation.models import ScRoleKpiMapping

        wrong = []
        for role, (lines, weight) in sorted(self.FROM_THE_SHEETS.items()):
            got = (ScRoleKpiMapping.objects.filter(role_code=role)
                   .aggregate(n=Count("id"), w=Sum("kpi_weight")))
            n, w = got["n"], float(got["w"] or 0)
            if n != lines or abs(w - weight) > 1e-6:
                wrong.append(f"{role}: sheet has {lines} lines / {weight:.3f}, "
                             f"seeded has {n} / {w:.3f}")

        self.assertEqual(wrong, [], "\n".join(wrong))

    #: The zero-weight lines the bank's own sheets carry. A weight of nought
    #: is NOT proof of a phantom line - this one is on the Personal_Banking
    #: sheet at row 20 and on Lydia Apanja's signed Q3_Sep_26 card, printed
    #: under "NPL ( 5% )" with a real actual beside it. The person is shown
    #: their provisions position and is not scored on it.
    ZERO_WEIGHT_ON_THE_SHEET = {
        "pb_rm/reduce_p_l_provisions_nill_provisions_loan_loss",
        "pb_arm/reduce_p_l_provisions_nill_provisions_loan_loss",
        "pb_bbc/reduce_p_l_provisions_nill_provisions_loan_loss",
    }

    def test_only_the_sheets_own_zero_weight_lines_carry_nought(self):
        """A line worth nothing still prints and still says you are measured
        on it, so an unexplained one is a fault - but the earlier version of
        this test said NO line may weigh nought, and that is what led to
        0054 deleting a line the sheet does carry. The rule is that every
        zero-weight line must be one the workbook accounts for."""
        from .scorecard_automation.models import ScRoleKpiMapping

        zero = {
            f"{m.role_code}/{m.kpi_code}"
            for m in ScRoleKpiMapping.objects.filter(kpi_weight=0)}

        unexplained = sorted(zero - self.ZERO_WEIGHT_ON_THE_SHEET)
        self.assertEqual(unexplained, [], "\n".join(unexplained))

        missing = sorted(self.ZERO_WEIGHT_ON_THE_SHEET - zero)
        self.assertEqual(
            missing, [],
            "the sheet carries these at nought and they are not seeded:\n"
            + "\n".join(missing))
