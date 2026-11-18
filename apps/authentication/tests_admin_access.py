"""Administration: who may look and who may change (Nov 2026).

After the QA walkthrough: the Administration APIs took a create, an edit, a
delete or an upload from any signed-in account, because the menu - not the API -
was the only thing keeping people out. And ``is_staff``, widely held, was enough
to create users and put oneself in any group.

Now a change needs a superuser or ``staff_mgt``; ``admin_viewer`` sees the
Administration screens and every save it tries is refused.
"""
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.permissions import ADMIN_ONLY_MESSAGE, READ_ONLY_MESSAGE
from apps.staff_management.models import ScorecardRole

ROLES = "/staff_management/roles/"
USERS = "/auth/users/"
MATRIX = "/auth/access-matrix/"
PRORATION = "/staff_management/scorecard-automation/manual-figures/proration/"
DATA_HEALTH = "/observability/data-health/"


def account(username, *groups, **flags):
    user = User.objects.create_user(username, password="x", **flags)
    for name in groups:
        user.groups.add(Group.objects.get_or_create(name=name)[0])
    return user


class AdminAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.role = ScorecardRole.objects.create(name="Teller")

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    # -- an ordinary login -------------------------------------------------
    def test_an_ordinary_login_reads_but_cannot_change(self):
        rm = self.as_(account("some.rm", "portfolio_mgt"))
        self.assertEqual(rm.get(ROLES).status_code, 200)
        r = rm.post(ROLES, {"role_name": "Made up"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(str(r.data["detail"]), ADMIN_ONLY_MESSAGE)
        self.assertEqual(rm.delete(f"{ROLES}{self.role.pk}/").status_code, 403)
        self.assertTrue(ScorecardRole.objects.filter(pk=self.role.pk).exists())
        self.assertFalse(ScorecardRole.objects.filter(name="Made up").exists())

    def test_is_staff_alone_is_not_administration(self):
        legacy = account("legacy.flag", is_staff=True)
        client = self.as_(legacy)
        self.assertEqual(client.post(ROLES, {"role_name": "X"}, format="json").status_code, 403)
        # Could create users and give itself any group before.
        r = client.post(USERS, {"username": "new.one", "email": "n@example.com"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = client.patch(f"{USERS}{legacy.pk}/", {"groups": ["ceo"]}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(legacy.groups.filter(name="ceo").exists())
        # Looking at the Users screen is unchanged.
        self.assertEqual(client.get(USERS).status_code, 200)

    # -- the read-only administrator ---------------------------------------
    def test_the_read_only_administrator_sees_every_screen(self):
        viewer = self.as_(account("tester.one", "admin_viewer"))
        for url in (ROLES, USERS, MATRIX, PRORATION, DATA_HEALTH):
            self.assertEqual(viewer.get(url).status_code, 200, url)

    def test_the_read_only_administrator_cannot_change_anything(self):
        user = account("tester.two", "admin_viewer")
        viewer = self.as_(user)
        r = viewer.post(ROLES, {"role_name": "X"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(str(r.data["detail"]), READ_ONLY_MESSAGE)
        self.assertEqual(viewer.patch(f"{ROLES}{self.role.pk}/", {"is_active": False},
                                      format="json").status_code, 403)
        self.assertEqual(viewer.post(USERS, {"username": "x"}, format="json").status_code, 403)
        r = viewer.patch(f"{USERS}{user.pk}/", {"groups": ["staff_mgt"]}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(user.groups.filter(name="staff_mgt").exists())
        self.assertEqual(viewer.post(PRORATION, {"sales_code": "X", "reason": "joined",
                                                 "from": "2026-03"},
                                     format="json").status_code, 403)
        self.assertTrue(ScorecardRole.objects.get(pk=self.role.pk).is_active)

    def test_the_read_only_administrator_cannot_download_the_staff_list(self):
        viewer = self.as_(account("tester.three", "admin_viewer"))
        self.assertEqual(viewer.get(MATRIX + "?download=1").status_code, 403)

    def test_without_the_role_the_screens_stay_shut(self):
        rm = self.as_(account("some.rm2", "portfolio_mgt"))
        for url in (USERS, MATRIX, PRORATION, DATA_HEALTH):
            self.assertEqual(rm.get(url).status_code, 403, url)

    # -- Administration ----------------------------------------------------
    def test_administration_still_changes_things(self):
        for user in (account("admin.group", "staff_mgt"),
                     User.objects.create_superuser("root.admin", password="x")):
            client = self.as_(user)
            r = client.post(ROLES, {"role_name": f"Made by {user.username}"}, format="json")
            self.assertEqual(r.status_code, 201, r.data)
