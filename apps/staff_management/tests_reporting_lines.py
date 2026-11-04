"""Reporting lines: reading each workbook's List, and who may open whose card."""

import io

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.staff_management import reporting_lines as lines
from apps.staff_management.models import DSRSalesCode, ScReportingLine

SC = "/staff_management/scorecard-automation/"


def sales(code, name, role, branch, zone, bbm, one, two):
    return {"sales_code": code, "name": name, "role": role, "branch": branch,
            "zone": zone, "bbm": bbm, "e-mail1": one, "e-mail2": two}


class ReadingTheWorkbooksTests(SimpleTestCase):
    def test_a_branch_rm_has_a_branch_line_and_a_segment_line(self):
        source, found = lines.lines_from_rows([sales(
            "AMN3416", "Anne Muthanje", "SME BBC", "Nanyuki", "Zone A",
            "Calvin Muchiri", "Calvin.Muchiri@hfcb.co.ke", "Anna.Amasinde@hfcb.co.ke")])
        self.assertEqual(source, "sales")
        by_kind = {f["line_kind"]: f for f in found}
        self.assertEqual(by_kind["branch"]["manager_name"], "Calvin Muchiri")
        self.assertEqual(by_kind["branch"]["manager_email"], "calvin.muchiri@hfcb.co.ke")
        self.assertEqual(by_kind["segment"]["manager_name"], "Anna Amasinde")
        self.assertEqual(by_kind["segment"]["unit_name"], "SME")

    def test_head_office_first_address_is_their_own_not_the_managers(self):
        """Sylvia Kimani and Evah Kimani share a surname, and that must not confuse."""
        _source, found = lines.lines_from_rows([sales(
            "SWK3881", "Sylvia Kimani", "Ultimate RM", "Ultimate RM", "H/O",
            "Evah Kimani", "Sylvia.Kimani@hfcb.co.ke", "Evah.Kimani@hfcb.co.ke")])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line_kind"], "segment")
        self.assertEqual(found[0]["manager_email"], "evah.kimani@hfcb.co.ke")

    def test_a_placeholder_manager_keeps_the_address_beside_it(self):
        _source, found = lines.lines_from_rows([sales(
            "X1", "Some Person", "PB RM", "Nyeri", "Zone A", "BM Nyeri",
            "samuel.kibiti@hfcb.co.ke", "Imelda.Muganda@hfcb.co.ke")])
        by_kind = {f["line_kind"]: f for f in found}
        self.assertEqual(by_kind["branch"]["manager_email"], "samuel.kibiti@hfcb.co.ke")
        self.assertEqual(by_kind["segment"]["manager_name"], "Imelda Muganda")

    def test_a_real_name_is_not_replaced_by_an_address_that_is_not_theirs(self):
        """Naivasha on the Q3 List: BBM Nelly Kibet, e-mail1 Christopher.Opiyo."""
        _source, found = lines.lines_from_rows([sales(
            "X2", "Some Person", "PB ARM", "Naivasha", "Zone A", "Nelly Kibet",
            "Christopher.Opiyo@hfcb.co.ke", "Imelda.Muganda@hfcb.co.ke")])
        by_kind = {f["line_kind"]: f for f in found}
        self.assertEqual(by_kind["branch"]["manager_name"], "Nelly Kibet")
        self.assertEqual(by_kind["branch"]["manager_email"], "")
        self.assertEqual(by_kind["segment"]["manager_name"], "Imelda Muganda")

    def test_branch_managers_report_to_their_zone(self):
        source, found = lines.lines_from_rows([
            {"sales_code": "SOA3923", "name": "Silas Abudho", "zone": "Zone A",
             "e-mail": "Silas.Abudho@hfcb.co.ke", "cc": "Jerusha.Igombo@hfcb.co.ke",
             "reports-to": "Jerusha Igombo"},
            {"sales_code": None, "name": "Christopher Opiyo", "zone": "Zone B",
             "reports-to": None, "e-mail": None, "cc": None}])
        self.assertEqual(source, "bb")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line_kind"], "zone")
        self.assertEqual(found[0]["person_email"], "silas.abudho@hfcb.co.ke")

    def test_back_office_skips_leavers_and_people_listed_under_themselves(self):
        rows = [{"staffsalescode": c, "staff - name": n, "role": "BOM", "branch": b,
                 "zone": z, "bm": m, "e-mail_to": ""} for c, n, b, z, m in (
            ("EKN1329", "Eric Nguithi", "Meru", "Zone A", "Annrita Mwirigi  "),
            ("JMW516", "Joyce Wambugu", "Mombasa", "Zone B", "Joyce Wambugu"),
            ("SNM1905", "Samuel Nduati Muigai", "Retail Banking", "Retail Back Office",
             "Samuel Muigai"),
            ("RWW3529", "Rahab Wambui", "left", "Head Office", "Reports Analytics"),
            ("BN4018", "Brian Njenga", "Retail Banking", "Retail Back Office",
             "Samuel Muigai"))]
        source, found = lines.lines_from_rows(rows)
        self.assertEqual(source, "bo")
        self.assertEqual({f["person_code"]: f["line_kind"] for f in found},
                         {"EKN1329": "branch", "BN4018": "department"})

    def test_a_sector_sheet_needs_no_new_code(self):
        source, found = lines.lines_from_rows([{
            "sales_code": "ab1", "name": "A B", "role": "Sector RM",
            "line_kind": "Sector", "unit_code": "S01", "unit_name": "Energy",
            "manager_name": "C D", "manager_email": "c.d@hfcb.co.ke"}])
        self.assertEqual(source, "upload")
        self.assertEqual(found[0]["line_kind"], "sector")
        self.assertEqual(found[0]["unit_code"], "S01")
        self.assertEqual(found[0]["person_code"], "AB1")

    def test_a_sheet_with_no_lines_is_refused(self):
        with self.assertRaises(lines.ReportingLineError):
            lines.lines_from_rows([{"sales_code": "A1", "name": "A"}])


class TeamTests(TestCase):
    def setUp(self):
        for code, name, kind, boss, mail, own in (
            ("RM1", "Anne Muthanje", "branch", "Calvin Muchiri", "calvin.muchiri@hfcb.co.ke", ""),
            ("RM1", "Anne Muthanje", "segment", "Anna Amasinde", "anna.amasinde@hfcb.co.ke", ""),
            ("BM1", "Calvin Muchiri", "zone", "Jerusha Igombo", "jerusha.igombo@hfcb.co.ke",
             "calvin.muchiri@hfcb.co.ke"),
        ):
            ScReportingLine.objects.create(
                person_code=code, person_name=name, line_kind=kind, manager_name=boss,
                manager_email=mail, person_email=own, source="t")
        self.client = APIClient()

    def _codes(self, username, **extra):
        user = User.objects.create_user(username, **extra)
        return user, {p["sales_code"] for p in lines.team_for(user)}

    def test_a_zone_head_sees_their_branch_managers_people_too(self):
        _u, codes = self._codes("jerusha.igombo", email="Jerusha.Igombo@hfcb.co.ke")
        self.assertEqual(codes, {"BM1", "RM1"})

    def test_a_segment_lead_sees_the_segment_only(self):
        _u, codes = self._codes("anna.amasinde", email="Anna.Amasinde@hfcb.co.ke")
        self.assertEqual(codes, {"RM1"})

    def test_a_branch_manager_named_only_by_a_list_is_found_by_address(self):
        ScReportingLine.objects.create(
            person_code="RM2", person_name="Bob X", line_kind="branch",
            manager_name="Calvin Muchiri", manager_email="calvin.muchiri@hfcb.co.ke",
            source="t")
        user, codes = self._codes("jerusha.igombo", email="jerusha.igombo@hfcb.co.ke")
        self.assertIn("RM2", codes)
        self.assertTrue(lines.is_direct_report(user, "BM1"))
        self.assertFalse(lines.is_direct_report(user, "RM2"))

    def test_carrying_a_leads_code_does_not_hand_over_their_team(self):
        from apps.portfolio.models import Profile

        user = User.objects.create_user("juddy.wambita")
        Profile.objects.filter(user=user).update(sales_code="AA3104")
        self.assertEqual(lines.team_for(user), [])

    def test_a_rm_has_no_team(self):
        _u, codes = self._codes("anne.muthanje", email="anne.muthanje@hfcb.co.ke")
        self.assertEqual(codes, set())

    def test_a_dsr_under_an_rm_comes_in_by_name_from_the_roster(self):
        DSRSalesCode.objects.create(pf_number="9", sales_code="DSR9", salesperson="Dee Sr",
                                    team_leader="Anne Muthanje", role="PB DSR", branch="X")
        lines.save(lines.lines_from_rosters(), "rosters", apply=True)
        _u, codes = self._codes("anne.muthanje", first_name="Anne", last_name="Muthanje")
        self.assertEqual(codes, {"DSR9"})

    def test_a_cycle_ends(self):
        ScReportingLine.objects.create(
            person_code="BM2", person_name="Jerusha Igombo", line_kind="x",
            manager_name="Anne Muthanje", source="t")
        _u, codes = self._codes("calvin.muchiri", email="calvin.muchiri@hfcb.co.ke")
        self.assertIn("RM1", codes)

    def test_card_for_opens_only_your_team(self):
        user, _codes = self._codes("anna.amasinde", email="anna.amasinde@hfcb.co.ke")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(SC + "card-for/?sales_code=BM1").status_code, 403)
        self.assertEqual(self.client.get(SC + "card-for/?sales_code=RM1").status_code, 200)

    def test_my_team_lists_them(self):
        user, _codes = self._codes("calvin.muchiri", email="calvin.muchiri@hfcb.co.ke")
        self.client.force_authenticate(user)
        data = self.client.get(SC + "my-team/").json()
        self.assertEqual((data["count"], data["direct"]), (1, 1))
        self.assertEqual(data["people"][0]["sales_code"], "RM1")


class SavingTests(TestCase):
    def _line(self, code, kind="sector", boss="Lead One"):
        return lines._line(code, code, "R", kind, "Energy", boss)

    def test_a_line_gone_from_the_source_is_retired_not_deleted(self):
        lines.save([self._line("A"), self._line("B")], "upload", apply=True)
        counts = lines.save([self._line("A")], "upload", apply=True)
        self.assertEqual(counts["retired"], 1)
        self.assertFalse(ScReportingLine.objects.get(person_code="B").active)

    def test_nothing_is_written_without_apply(self):
        counts = lines.save([self._line("A")], "upload")
        self.assertEqual(counts["new"], 1)
        self.assertEqual(ScReportingLine.objects.count(), 0)

    def test_a_sector_sheet_leaves_other_kinds_alone(self):
        lines.save([self._line("A", kind="department")], "upload", apply=True)
        lines.save([self._line("B")], "upload", apply=True, kinds=["sector"])
        self.assertTrue(ScReportingLine.objects.get(person_code="A").active)

    def test_uploading_a_sheet_reports_then_saves(self):
        admin = User.objects.create_superuser("root", password="x")
        client = APIClient()
        client.force_authenticate(admin)
        text = ("sales_code,name,role,line_kind,unit_code,unit_name,manager_name\n"
                "AB1,A B,Sector RM,sector,S01,Energy,Lead One\n")

        def send(**extra):
            upload = SimpleUploadedFile("sectors.csv", text.encode())
            return client.post(SC + "reporting-lines/", {"file": upload, **extra},
                               format="multipart").json()

        self.assertEqual(send()["new"], 1)
        self.assertEqual(ScReportingLine.objects.count(), 0)
        self.assertTrue(send(apply="1")["applied"])
        self.assertEqual(ScReportingLine.objects.get().unit_code, "S01")
        self.assertEqual(client.get(SC + "reporting-lines/?kind=sector").json()["count"], 1)

    def test_only_an_administrator_may_load(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("someone"))
        upload = SimpleUploadedFile("x.csv", io.BytesIO(b"a").read())
        self.assertEqual(client.post(SC + "reporting-lines/", {"file": upload},
                                     format="multipart").status_code, 403)
        self.assertEqual(client.get(SC + "reporting-lines/").status_code, 403)


class BranchManagerPageTests(TestCase):
    """The page answers what a List leaves unclear, and nothing else."""

    def _manager(self, code, name, unit, email, role="BBM", active=1):
        from apps.staff_management.models import BranchFinalEmployeeDmcData

        return BranchFinalEmployeeDmcData.objects.create(
            sales_code=code, staff_name=name, staff_unit=unit, staff_role=role,
            staff_email=email, active=active)

    def _branch_line(self, unit, boss, mail=""):
        return lines._line("RM1", "Some Person", "PB RM", "branch", unit, boss, mail)

    def test_a_placeholder_becomes_the_real_manager(self):
        self._manager("CGK1784", "Real Manager", "Nyeri Branch", "Real.Manager@hfcb.co.ke")
        got = lines.use_branch_manager_page(
            [self._branch_line("Nyeri", "BM Nyeri", "samuel.kibiti@hfcb.co.ke")])[0]
        self.assertEqual(got["manager_name"], "Real Manager")
        self.assertEqual(got["manager_email"], "real.manager@hfcb.co.ke")
        self.assertEqual(got["manager_code"], "CGK1784")

    def test_a_name_with_no_trusted_address_gets_the_pages_address(self):
        self._manager("NJK1452", "Nelly Kibet", "Naivasha Branch", "Nelly.Kibet@hfcb.co.ke")
        got = lines.use_branch_manager_page([self._branch_line("Naivasha", "Nelly Kibet")])[0]
        self.assertEqual(got["manager_email"], "nelly.kibet@hfcb.co.ke")

    def test_a_clear_row_is_left_alone(self):
        self._manager("X1", "Someone Else", "Thika Branch", "someone.else@hfcb.co.ke")
        got = lines.use_branch_manager_page(
            [self._branch_line("Thika", "Naomi Kagiri", "naomi.kagiri@hfcb.co.ke")])[0]
        self.assertEqual(got["manager_name"], "Naomi Kagiri")

    def test_other_staff_on_that_table_are_not_taken_for_the_manager(self):
        self._manager("X2", "A Teller", "Nyeri Branch", "a.teller@hfcb.co.ke", role="TELLER")
        got = lines.use_branch_manager_page(
            [self._branch_line("Nyeri", "BM Nyeri", "samuel.kibiti@hfcb.co.ke")])[0]
        self.assertEqual(got["manager_name"], "BM Nyeri")

    def test_two_active_managers_is_not_guessed_between(self):
        self._manager("A1", "First One", "Nyeri Branch", "first.one@hfcb.co.ke")
        self._manager("A2", "Second One", "Nyeri Branch", "second.one@hfcb.co.ke")
        got = lines.use_branch_manager_page(
            [self._branch_line("Nyeri", "BM Nyeri", "samuel.kibiti@hfcb.co.ke")])[0]
        self.assertEqual(got["manager_name"], "BM Nyeri")

    def test_someone_who_left_is_not_used(self):
        self._manager("A1", "First One", "Nyeri Branch", "first.one@hfcb.co.ke", active=0)
        got = lines.use_branch_manager_page(
            [self._branch_line("Nyeri", "BM Nyeri", "samuel.kibiti@hfcb.co.ke")])[0]
        self.assertEqual(got["manager_name"], "BM Nyeri")

    def test_a_branch_manager_finds_their_own_card_by_their_address(self):
        from apps.staff_management.live_scorecard import resolve_sales_code_for_user

        self._manager("NJK1452", "Nelly Kibet", "Naivasha Branch", "Nelly.Kibet@hfcb.co.ke")
        user = User.objects.create_user("nelly.kibet", email="Nelly.Kibet@hfcb.co.ke")
        self.assertEqual(resolve_sales_code_for_user(user)[0], "NJK1452")


class RoleTitleTests(TestCase):
    def test_every_arm_is_offered(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("someone"))
        titles = client.get(SC + "role-titles/").json()["titles"]
        for title in ("SME ARM", "PB ARM", "MORTGAGE BUSINESS ARM", "DIASPORA ARM",
                      "COMMERCIAL RM- TRADE", "RBO", "CSM_DB"):
            self.assertIn(title, titles)

    def test_every_list_title_reaches_its_card(self):
        from apps.staff_management.live_scorecard import card_role_for

        for title, card in (("SME ARM", "sme_arm"), ("CSO_UB", "bo_cso_ub"),
                            ("CSM_DB", "bo_csm_diaspora"),
                            ("Cash_Center", "bo_cash_centre_teller"),
                            ("TL_RBO", "bo_tl_rbo"), ("RBO", "bo_rbo")):
            self.assertEqual(card_role_for(title), card)

    def test_a_card_added_later_is_reached_by_its_name(self):
        from apps.staff_management.live_scorecard import card_role_for
        from apps.staff_management.scorecard_automation.models import ScRole

        self.assertIsNone(card_role_for("Sector Lead"))
        ScRole.objects.create(role_code="sector_lead", role_name="Sector Lead")
        self.assertEqual(card_role_for("sector  lead"), "sector_lead")


class SignatureTests(TestCase):
    """Strategy may open the card they are checking, and only the holder may sign."""

    def setUp(self):
        from apps.analytics.exclusions import EXCLUDED_GROUP
        from apps.portfolio.models import Profile
        from apps.staff_management.models import BranchEmployeeDmcData

        BranchEmployeeDmcData.objects.create(
            staff_name="Lilian Biwott", sales_code="LJB1656", staff_role="COMMERCIAL RM")
        self.user = User.objects.create_user("washingtone.amolo")
        Group.objects.get_or_create(name=EXCLUDED_GROUP)[0].user_set.add(self.user)
        Profile.objects.filter(user=self.user).update(sales_code="LJB1656")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_they_cannot_sign_withdraw_or_send_it(self):
        for path in ("my-card/sign/", "my-card/unsign/", "my-card/send/"):
            response = self.client.post(SC + path, {}, format="json")
            self.assertEqual(response.status_code, 403, path)

    def test_the_holder_is_not_refused(self):
        from apps.staff_management.live_scorecard import is_someone_elses_card

        self.assertTrue(is_someone_elses_card(self.user, "LJB1656"))
        self.assertFalse(is_someone_elses_card(
            User.objects.create_user("lilian.biwott"), "LJB1656"))


@override_settings(LOGIN_MFA_ENFORCED=True)
class SecondFactorTests(TestCase):
    PASSWORD = "Str0ng!pass9"

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = User.objects.create_user(
            "anne.m", email="anne@hfcb.co.ke", password=self.PASSWORD)
        self.client = APIClient()

    def _login(self):
        data = self.client.post("/auth/api/token/", {
            "username": "anne.m", "password": self.PASSWORD}, format="json").json()
        return data["access"], data["refresh"]

    def _bearer(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def _code(self):
        from apps.portfolio.models import OTP

        self.assertEqual(self.client.post("/auth/generate-otp/").status_code, 200)
        return OTP.objects.get(user=self.user).otp

    def test_the_password_alone_opens_only_the_code_step(self):
        access, _refresh = self._login()
        self._bearer(access)
        self.assertEqual(self.client.get(SC + "my-card/holder/").status_code, 401)
        self.assertEqual(self.client.get("/portfolio/userprofile/").status_code, 200)

    def test_the_code_issues_tokens_that_open_everything(self):
        access, refresh = self._login()
        self._bearer(access)
        data = self.client.post("/auth/verify-otp/", {
            "otp": self._code(), "refresh": refresh}, format="json").json()
        self._bearer(data["access"])
        self.assertEqual(self.client.get(SC + "my-card/holder/").status_code, 200)

    def test_refreshing_does_not_pass_the_second_factor(self):
        access, refresh = self._login()
        data = self.client.post("/auth/api/token/refresh/", {"refresh": refresh},
                                format="json").json()
        self._bearer(data["access"])
        self.assertEqual(self.client.get(SC + "my-card/holder/").status_code, 401)
        del access

    def test_a_code_works_once_and_a_wrong_one_not_at_all(self):
        access, _refresh = self._login()
        self._bearer(access)
        code = self._code()
        wrong = "000000" if code != "000000" else "000001"
        self.assertEqual(self.client.post("/auth/verify-otp/", {"otp": wrong},
                                          format="json").status_code, 400)
        self.assertEqual(self.client.post("/auth/verify-otp/", {"otp": code},
                                          format="json").status_code, 200)
        self.assertEqual(self.client.post("/auth/verify-otp/", {"otp": code},
                                          format="json").status_code, 400)

    @override_settings(LOGIN_MFA_ENFORCED=False)
    def test_off_until_the_frontend_is_live(self):
        access, _refresh = self._login()
        self._bearer(access)
        self.assertEqual(self.client.get(SC + "my-card/holder/").status_code, 200)

    def test_nobody_changes_another_persons_password(self):
        other = User.objects.create_user("other", password=self.PASSWORD)
        self.client.force_authenticate(self.user)
        response = self.client.put(f"/auth/change_password/{other.pk}/", {
            "old_password": self.PASSWORD, "new_password": "An0ther!pass9"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_a_token_naming_another_account_is_refused(self):
        """Customer 360 signs with the same key and numbers its users separately."""
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(self.user)
        token["username"] = "somebody.else"
        self._bearer(str(token))
        self.assertEqual(self.client.get(SC + "my-card/holder/").status_code, 401)
        token["username"] = self.user.username
        token["mfa"] = True
        self._bearer(str(token))
        self.assertEqual(self.client.get(SC + "my-card/holder/").status_code, 200)

    def test_the_api_listing_is_not_public(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/schema/").status_code, (401, 403))
