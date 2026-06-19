"""
Tests for migration-safety of users and their defined roles.

These guard the exact failure the migration must avoid: legacy group-based
roles (ceo/exco/...) being lost or downgraded when users move to the new
backend, and the Profile welcome-email signal firing during a bulk migration.
"""

from io import StringIO

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from core.permissions import get_user_role
from core.roles import (
    LEGACY_ROLES,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_OFFICER,
    tier_for_groups,
)


class RoleMappingTests(TestCase):
    """Legacy groups must drive the new role tier — never silently downgrade."""

    def test_tier_for_groups_picks_strongest(self):
        self.assertEqual(tier_for_groups({"ceo"}), ROLE_ADMIN)
        self.assertEqual(tier_for_groups({"exco"}), ROLE_ADMIN)
        self.assertEqual(tier_for_groups({"hfdi_admin"}), ROLE_ADMIN)
        self.assertEqual(tier_for_groups({"portfolio_mgt"}), ROLE_MANAGER)
        self.assertEqual(tier_for_groups({"tl_collection"}), ROLE_MANAGER)
        self.assertEqual(tier_for_groups({"branch_portfolio"}), ROLE_OFFICER)
        # Strongest wins when several groups are present.
        self.assertEqual(tier_for_groups({"branch_portfolio", "ceo"}), ROLE_ADMIN)
        self.assertEqual(tier_for_groups({"branch_portfolio", "tl_portfolio"}), ROLE_MANAGER)
        # Unknown / empty -> officer (the old default for every RM).
        self.assertEqual(tier_for_groups(set()), ROLE_OFFICER)
        self.assertEqual(tier_for_groups({"nonexistent"}), ROLE_OFFICER)

    def test_ceo_user_not_downgraded(self):
        """A migrated ceo (no is_staff/is_superuser) must resolve to admin."""
        ceo_group, _ = Group.objects.get_or_create(name="ceo")
        user = User.objects.create_user("ceo_user", password="x")
        user.groups.add(ceo_group)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(get_user_role(user), ROLE_ADMIN)

    def test_plain_rm_is_officer(self):
        user = User.objects.create_user("rm_user", password="x")
        self.assertEqual(get_user_role(user), ROLE_OFFICER)

    def test_superuser_and_staff_precedence(self):
        su = User.objects.create_superuser("root", "root@x.com", "x")
        self.assertEqual(get_user_role(su), ROLE_ADMIN)
        staff = User.objects.create_user("staffer", password="x", is_staff=True)
        self.assertEqual(get_user_role(staff), ROLE_MANAGER)


class SeedRolesCommandTests(TestCase):
    def test_seed_roles_creates_all_legacy_groups(self):
        call_command("seed_roles", stdout=StringIO())
        for name in LEGACY_ROLES:
            self.assertTrue(Group.objects.filter(name=name).exists(), name)

    def test_seed_roles_is_idempotent(self):
        call_command("seed_roles", stdout=StringIO())
        call_command("seed_roles", stdout=StringIO())
        self.assertEqual(Group.objects.filter(name__in=LEGACY_ROLES).count(), len(LEGACY_ROLES))


class UserSerializerRoleContractTests(TestCase):
    """The userprofile payload must expose the role contract the frontend reads."""

    def test_groups_and_is_superuser_in_payload(self):
        from apps.portfolio.serializers import UserSerializer

        group, _ = Group.objects.get_or_create(name="exco")
        user = User.objects.create_user("dora", email="dora@hf.co.ke", password="x")
        user.groups.add(group)
        prof = user.profile
        prof.sales_code = "SC9"
        prof.branch = "KISII BRANCH"
        prof.segment = "PB"
        prof.save()

        data = UserSerializer(user).data
        # Frontend hasPermission() reads exactly these.
        self.assertIn("groups", data)
        self.assertEqual(data["groups"], ["exco"])
        self.assertIn("is_superuser", data)
        self.assertFalse(data["is_superuser"])
        # Flattened RBAC fields the frontend User type expects.
        self.assertEqual(data["sales_code"], "SC9")
        self.assertEqual(data["segment"], "PB")


class AdminUserManagementAPITests(TestCase):
    """The clean replacement for the Django admin user screen."""

    def setUp(self):
        from rest_framework.test import APIClient

        call_command("seed_roles", stdout=StringIO())
        self.admin = User.objects.create_user(
            "boss", email="boss@hf.co.ke", password="x", is_staff=True
        )
        self.plain = User.objects.create_user("nobody", password="x")
        self.client = APIClient()

    def test_non_admin_is_forbidden(self):
        self.client.force_authenticate(self.plain)
        resp = self.client.get("/auth/users/")
        self.assertEqual(resp.status_code, 403)

    def test_admin_creates_user_with_role(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "username": "jdoe",
            "email": "jdoe@hf.co.ke",
            "first_name": "Jane",
            "last_name": "Doe",
            "groups": ["ceo"],
            "branch": "KISII BRANCH",
            "segment": "PB",
            "password": "StrongP@ssw0rd99",
        }
        resp = self.client.post("/auth/users/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        created = User.objects.get(username="jdoe")
        self.assertTrue(created.groups.filter(name="ceo").exists())
        self.assertTrue(created.check_password("StrongP@ssw0rd99"))
        self.assertEqual(created.profile.segment, "PB")
        self.assertEqual(get_user_role(created), ROLE_ADMIN)

    def test_create_without_password_returns_generated_one(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            "/auth/users/",
            {"username": "autopw", "email": "a@hf.co.ke", "groups": ["branch_portfolio"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("generated_password", resp.data)
        self.assertTrue(resp.data["generated_password"])
        user = User.objects.get(username="autopw")
        self.assertTrue(user.check_password(resp.data["generated_password"]))

    def test_creating_user_sends_no_welcome_email(self):
        self.client.force_authenticate(self.admin)
        mail.outbox = []
        self.client.post(
            "/auth/users/",
            {"username": "silent", "email": "s@hf.co.ke", "password": "StrongP@ssw0rd99"},
            format="json",
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_set_password(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            f"/auth/users/{self.plain.pk}/set-password/",
            {"password": "BrandNewP@ss123"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.plain.refresh_from_db()
        self.assertTrue(self.plain.check_password("BrandNewP@ss123"))

    def test_soft_delete_deactivates(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(f"/auth/users/{self.plain.pk}/")
        self.assertIn(resp.status_code, (200, 204))
        self.plain.refresh_from_db()
        self.assertFalse(self.plain.is_active)
        self.assertTrue(User.objects.filter(pk=self.plain.pk).exists())

    def test_role_list_returns_all_roles(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get("/auth/roles/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        names = {r["name"] for r in rows}
        # 14 baseline roles + 4 mortgage-module roles seeded by apps.mortgages.
        self.assertEqual(len(names), 18)
        self.assertIn("ceo", names)
        self.assertIn("staff_mgt", names)
        self.assertIn("mortgage_officer", names)


class MigrateLegacyAuthCommandTests(TestCase):
    """
    Exercises the migration command against a single DB (source == target ==
    default) so the full copy/reconcile path runs without a real legacy server.
    """

    def setUp(self):
        from apps.portfolio.models import Profile

        self.ceo_group, _ = Group.objects.get_or_create(name="ceo")
        self.user = User.objects.create_user(
            "alice", email="alice@hf.co.ke", password="OriginalP@ss1"
        )
        self.user.groups.add(self.ceo_group)
        # Profile is auto-created by signal; set the RBAC-relevant fields.
        prof = Profile.objects.get(user=self.user)
        prof.sales_code = "SC123"
        prof.branch = "KISII BRANCH"
        prof.segment = "PB"
        prof.save()
        self.original_hash = User.objects.get(username="alice").password

    def test_migration_preserves_role_password_and_profile(self):
        from apps.portfolio.models import Profile

        mail.outbox = []
        call_command(
            "migrate_legacy_auth",
            "--source", "default", "--target", "default",
            stdout=StringIO(),
        )

        alice = User.objects.get(username="alice")
        # Role preserved.
        self.assertTrue(alice.groups.filter(name="ceo").exists())
        self.assertEqual(get_user_role(alice), ROLE_ADMIN)
        # Password hash copied verbatim (NOT re-hashed) — login still works.
        self.assertEqual(alice.password, self.original_hash)
        self.assertTrue(alice.check_password("OriginalP@ss1"))
        # Profile fields preserved.
        prof = Profile.objects.get(user=alice)
        self.assertEqual(prof.sales_code, "SC123")
        self.assertEqual(prof.segment, "PB")
        # Signal muted — no welcome emails sent during migration.
        self.assertEqual(len(mail.outbox), 0)

    def test_migration_is_idempotent(self):
        call_command(
            "migrate_legacy_auth", "--source", "default", "--target", "default",
            stdout=StringIO(),
        )
        call_command(
            "migrate_legacy_auth", "--source", "default", "--target", "default",
            stdout=StringIO(),
        )
        self.assertEqual(User.objects.filter(username="alice").count(), 1)
        self.assertEqual(
            User.objects.get(username="alice").groups.filter(name="ceo").count(), 1
        )
