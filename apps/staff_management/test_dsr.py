"""Tests for the DSR seller-code allocation logic."""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .dsr import next_sales_code
from .models import DSRSalesCode

User = get_user_model()


class DSRSalesCodeTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user(username="plain", password="x")

    def test_next_code_from_empty_is_dsr1(self):
        self.assertEqual(next_sales_code(), "DSR1")

    def test_next_code_is_max_plus_one(self):
        DSRSalesCode.objects.create(pf_number="1", sales_code="DSR302")
        DSRSalesCode.objects.create(pf_number="2", sales_code="DSR539")
        DSRSalesCode.objects.create(pf_number="3", sales_code="DSR100")
        self.assertEqual(next_sales_code(), "DSR540")

    def test_allocate_new_pf_creates_sequential_code(self):
        DSRSalesCode.objects.create(pf_number="9", sales_code="DSR539")
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/dsr-sales-codes/allocate/",
                               {"pf_number": "4026", "salesperson": "Test DSR"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(res.data["already_allocated"])
        self.assertEqual(res.data["record"]["sales_code"], "DSR540")
        self.assertEqual(res.data["record"]["pf_number"], "4026")

    def test_allocate_existing_pf_returns_existing_not_new(self):
        DSRSalesCode.objects.create(pf_number="4026", sales_code="DSR303", salesperson="Lucy")
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/dsr-sales-codes/allocate/",
                               {"pf_number": "4026"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["already_allocated"])
        self.assertEqual(res.data["record"]["sales_code"], "DSR303")
        self.assertEqual(DSRSalesCode.objects.filter(pf_number="4026").count(), 1)

    def test_non_admin_cannot_allocate(self):
        self.client.force_authenticate(self.plain)
        res = self.client.post("/staff_management/dsr-sales-codes/allocate/",
                               {"pf_number": "4026"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_lookup_existing_pf(self):
        DSRSalesCode.objects.create(pf_number="4026", sales_code="DSR303", salesperson="Lucy")
        self.client.force_authenticate(self.plain)
        res = self.client.get("/staff_management/dsr-sales-codes/lookup/?pf_number=4026")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["allocated"])
        self.assertEqual(res.data["record"]["sales_code"], "DSR303")

    def test_lookup_new_pf_previews_next_code(self):
        DSRSalesCode.objects.create(pf_number="9", sales_code="DSR539")
        self.client.force_authenticate(self.plain)
        res = self.client.get("/staff_management/dsr-sales-codes/lookup/?pf_number=7777")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["allocated"])
        self.assertEqual(res.data["next_sales_code"], "DSR540")

    def test_sales_code_unique_enforced(self):
        DSRSalesCode.objects.create(pf_number="1", sales_code="DSR303")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DSRSalesCode.objects.create(pf_number="2", sales_code="DSR303")


class DSRSalesCodeEditTests(APITestCase):
    """Correcting and withdrawing an allocation.

    A code allocated against the wrong person used to be permanent — the API was
    list-only. It is now editable and deletable, under the rule that has always
    governed these codes: a number is never shared and never reused.
    """

    URL = "/staff_management/dsr-sales-codes/{}/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="edit_admin", password="x", is_superuser=True, is_staff=True
        )
        self.plain = User.objects.create_user(username="edit_plain", password="x")
        self.record = DSRSalesCode.objects.create(
            pf_number="4026", sales_code="DSR540", salesperson="Lucy Wanjiru",
            branch="THIKA", role="PB DSR",
        )

    def test_an_admin_can_correct_a_wrong_detail(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(self.URL.format(self.record.id),
                                {"salesperson": "Lucy Wanjiku"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.record.refresh_from_db()
        self.assertEqual(self.record.salesperson, "Lucy Wanjiku")

    def test_the_code_itself_can_be_corrected(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(self.URL.format(self.record.id),
                                {"sales_code": "DSR541"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.record.refresh_from_db()
        self.assertEqual(self.record.sales_code, "DSR541")

    def test_a_code_another_dsr_holds_is_refused(self):
        DSRSalesCode.objects.create(pf_number="9999", sales_code="DSR600")
        self.client.force_authenticate(self.admin)
        res = self.client.patch(self.URL.format(self.record.id),
                                {"sales_code": "DSR600"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.record.refresh_from_db()
        self.assertEqual(self.record.sales_code, "DSR540")

    def test_a_malformed_code_is_refused(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(self.URL.format(self.record.id),
                                {"sales_code": "ABC12"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_moving_a_code_onto_a_pf_that_already_has_one_is_refused(self):
        DSRSalesCode.objects.create(pf_number="7777", sales_code="DSR601")
        self.client.force_authenticate(self.admin)
        res = self.client.patch(self.URL.format(self.record.id),
                                {"pf_number": "7777"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_an_admin_can_withdraw_an_allocation(self):
        self.client.force_authenticate(self.admin)
        res = self.client.delete(self.URL.format(self.record.id))
        self.assertEqual(res.status_code, 204)
        self.assertFalse(DSRSalesCode.objects.filter(pk=self.record.pk).exists())

    def test_a_withdrawn_number_is_not_handed_to_somebody_else(self):
        """Deleting frees the person, not the number."""
        DSRSalesCode.objects.create(pf_number="1", sales_code="DSR700")
        self.client.force_authenticate(self.admin)
        self.client.delete(self.URL.format(self.record.id))
        self.assertEqual(next_sales_code(), "DSR701")

    def test_a_non_admin_can_read_but_not_change_or_delete(self):
        self.client.force_authenticate(self.plain)
        self.assertEqual(self.client.get(self.URL.format(self.record.id)).status_code, 200)
        self.assertEqual(
            self.client.patch(self.URL.format(self.record.id),
                              {"salesperson": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(self.URL.format(self.record.id)).status_code, 403)

    def test_an_edit_is_kept_in_the_audit_trail(self):
        self.client.force_authenticate(self.admin)
        self.client.patch(self.URL.format(self.record.id),
                          {"branch": "NAKURU"}, format="json")
        history = list(DSRSalesCode.history.filter(id=self.record.id).order_by("history_date"))
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[-1].branch, "NAKURU")


class DSRTeamLeaderColumnTests(APITestCase):
    """Which team leader the table shows, and where the answer came from.

    The column consulted only the branch map, so every DSR led by ROLE — BANCA
    DSR, SME DSR — read as unmapped even though the mapping was there.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username="tl_admin", password="x", is_superuser=True, is_staff=True
        )
        self.client.force_authenticate(self.admin)

    def _row(self, **kwargs):
        from .dsr_views import DSRSalesCodeSerializer

        defaults = {"pf_number": "1", "sales_code": "DSR1"}
        defaults.update(kwargs)
        return DSRSalesCodeSerializer(DSRSalesCode.objects.create(**defaults)).data

    def test_a_stored_leader_wins(self):
        row = self._row(team_leader="Stored Person", branch="THIKA", role="BANCA DSR")
        self.assertEqual(row["team_leader"], "Stored Person")
        self.assertEqual(row["team_leader_source"], "stored")

    def test_the_branch_map_answers_for_a_branch_dsr(self):
        from .models import TeamLeaderBranch

        # Stored raw; the DSR's branch reads differently. The map is keyed on
        # the canonical name so both still meet.
        TeamLeaderBranch.objects.create(branch="THIKA", team_leader="Emanuel K")
        row = self._row(branch="Thika Branch", role="PB DSR")
        self.assertEqual(row["team_leader"], "Emanuel K")
        self.assertEqual(row["team_leader_source"], "branch")

    def test_a_role_led_dsr_is_no_longer_blank(self):
        from .models import DSRRoleTeamLeader

        DSRRoleTeamLeader.objects.update_or_create(
            role="BANCA DSR", team_leader="David Wambugu", defaults={"active": True}
        )
        row = self._row(role="BANCA DSR", branch="")
        self.assertEqual(row["team_leader"], "David Wambugu")
        self.assertEqual(row["team_leader_source"], "role")

    def test_a_role_with_two_leaders_names_both_rather_than_reading_unmapped(self):
        from .models import DSRRoleTeamLeader

        for name, order in (("Eva Kabiwa", 10), ("Luke Njagi", 20)):
            DSRRoleTeamLeader.objects.update_or_create(
                role="SME DSR", team_leader=name,
                defaults={"active": True, "sort_order": order},
            )
        row = self._row(role="SME DSR", branch="")
        self.assertEqual(row["team_leader"], "Eva Kabiwa / Luke Njagi")
        self.assertEqual(row["team_leader_source"], "role")

    def test_an_unmapped_dsr_is_still_blank(self):
        row = self._row(role="TELESALES", branch="NOWHERE")
        self.assertEqual(row["team_leader"], "")
        self.assertEqual(row["team_leader_source"], "")
