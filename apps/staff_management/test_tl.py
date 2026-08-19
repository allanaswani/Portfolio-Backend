"""Tests for the team-leader ↔ branch mapping."""

import io

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .branches import normalize_branch
from .dsr import team_leader_for_branch
from .models import TeamLeaderBranch, DSRRoleTeamLeader

User = get_user_model()


class BranchNormalizeTests(APITestCase):
    def test_variants_collapse(self):
        self.assertEqual(normalize_branch("KOMAROCK"), "KOMAROCK BRANCH")
        self.assertEqual(normalize_branch("komarock branch"), "KOMAROCK BRANCH")
        self.assertEqual(normalize_branch("HQ"), "HEAD OFFICE")
        self.assertEqual(normalize_branch(""), "")


class TeamLeaderMappingTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="a", password="x", is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user(username="p", password="x")

    def test_upsert_normalizes_and_lookup(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/team-leaders/upsert/",
                               {"branch": "komarock", "team_leader": "Emanuel"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["branch"], "KOMAROCK BRANCH")
        # a DSR in "KOMAROCK" (any spelling) resolves to Emanuel
        self.assertEqual(team_leader_for_branch("KOMAROCK BRANCH"), "Emanuel")

    def test_reassign_moves_all_branches(self):
        TeamLeaderBranch.objects.create(branch="EMBU BRANCH", team_leader="Ian")
        TeamLeaderBranch.objects.create(branch="MERU BRANCH", team_leader="Ian")
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/team-leaders/reassign/",
                               {"from_team_leader": "Ian", "to_team_leader": "Brian"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["reassigned"], 2)
        self.assertEqual(TeamLeaderBranch.objects.filter(team_leader="Brian").count(), 2)
        self.assertEqual(TeamLeaderBranch.objects.filter(team_leader="Ian").count(), 0)

    def test_upload_pivot(self):
        pivot = "Staff Role,PB DSR\nActive,1\n,\nRow Labels,\nEmanuel,\nKOMAROCK BRANCH,\nTHIKA BRANCH,\nIan,\nEMBU BRANCH,\nGrand Total,\n"
        self.client.force_authenticate(self.admin)
        res = self.client.post("/staff_management/team-leaders/upload-csv/",
                               {"file": io.BytesIO(pivot.encode())}, format="multipart")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["created"], 3)
        self.assertEqual(set(res.data["team_leaders"]), {"Emanuel", "Ian"})
        self.assertEqual(team_leader_for_branch("THIKA"), "Emanuel")
        self.assertEqual(team_leader_for_branch("EMBU"), "Ian")

    def test_non_admin_cannot_upsert(self):
        self.client.force_authenticate(self.plain)
        res = self.client.post("/staff_management/team-leaders/upsert/",
                               {"branch": "MERU", "team_leader": "Ian"}, format="json")
        self.assertEqual(res.status_code, 403)


class RoleTeamLeaderTests(APITestCase):
    ROWS = "/staff_management/dsr-role-team-leaders/manage/"
    OPTS = "/staff_management/dsr-role-team-leaders/"

    def setUp(self):
        self.admin = User.objects.create_user(username="a", password="x", is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user(username="p", password="x")
        # Migration 0011 seeds the real mappings; start these tests from a clean slate.
        DSRRoleTeamLeader.objects.all().delete()

    def test_create_lists_and_feeds_allocator_options(self):
        self.client.force_authenticate(self.admin)
        r1 = self.client.post(self.ROWS, {"role": "SME DSR", "team_leader": "Eva Kabiwa"}, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.client.post(self.ROWS, {"role": "SME DSR", "team_leader": "Luke Njagi"}, format="json")

        rows = self.client.get(self.ROWS)
        self.assertEqual({(x["role"], x["team_leader"]) for x in rows.data},
                         {("SME DSR", "Eva Kabiwa"), ("SME DSR", "Luke Njagi")})
        # Same data feeds the Seller-Codes allocator dropdown shape.
        opts = self.client.get(self.OPTS)
        self.assertEqual(set(opts.data["roles"]["SME DSR"]), {"Eva Kabiwa", "Luke Njagi"})

    def test_create_is_idempotent_no_duplicate(self):
        self.client.force_authenticate(self.admin)
        self.client.post(self.ROWS, {"role": "BANCA DSR", "team_leader": "David Wambugu"}, format="json")
        again = self.client.post(self.ROWS, {"role": "BANCA DSR", "team_leader": "David Wambugu"}, format="json")
        self.assertEqual(again.status_code, 200)  # updated, not created
        self.assertEqual(DSRRoleTeamLeader.objects.filter(role="BANCA DSR", team_leader="David Wambugu").count(), 1)

    def test_delete_removes_mapping(self):
        self.client.force_authenticate(self.admin)
        created = self.client.post(self.ROWS, {"role": "SME DSR", "team_leader": "Luke Njagi"}, format="json")
        pk = created.data["id"]
        res = self.client.delete(f"/staff_management/dsr-role-team-leaders/{pk}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(DSRRoleTeamLeader.objects.filter(pk=pk).exists())

    def test_missing_fields_400(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.ROWS, {"role": "SME DSR"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_non_admin_cannot_create_or_delete(self):
        DSRRoleTeamLeader.objects.create(role="BANCA DSR", team_leader="David Wambugu")
        pk = DSRRoleTeamLeader.objects.first().pk
        self.client.force_authenticate(self.plain)
        self.assertEqual(self.client.post(self.ROWS, {"role": "X", "team_leader": "Y"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"/staff_management/dsr-role-team-leaders/{pk}/").status_code, 403)
