"""Records the app only ever reads can no longer be changed or deleted by any
signed-in user (26 Nov 2026). Before this, a teller could DELETE a customer,
an RM target or a collections record by its id. Reads are untouched; a change
needs Administration (superuser or staff_mgt), as elsewhere.

Only the permission check is exercised: it runs before the view touches the
database, so nothing here reaches the warehouse alias (which the dev settings
point at production)."""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory

from core.permissions import AdministrationWrites

LOCKED = (
    "/portfolio/customers/1/",
    "/portfolio/feedback/1/",
    "/portfolio_management_enrichment/rm_targets/1/",
    "/portfolio_management_enrichment/customer_enrichment/1/",
    "/portfolio_management_enrichment/customer_allocation_base/1/",
    "/portfolio_management_enrichment/rm_allocation_list/1/",
    "/portfolio_management_enrichment/movement_approvers/1/",
    "/portfolio_management_enrichment/customer_transfer_history/1/",
    "/hf_collections/collections/1/",
    "/hf_collections/ptp/1/",
    "/hf_rights_issue/applications/1/",
    "/exco_innitiatives/initiatives/1/",
    "/exco_innitiatives/thrusts/1/",
    "/hfdi/projects/1/",
    "/hfdi/affordable_housing/1/",
)


class LockedWritesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("teller", password="x"))

    def test_a_signed_in_user_cannot_change_or_delete(self):
        for url in LOCKED:
            for method in ("patch", "put", "delete"):
                with self.subTest(url=url, method=method):
                    got = getattr(self.client, method)(url, {}, format="json")
                    self.assertEqual(got.status_code, 403, got.content[:200])


class AdministrationWritesRuleTests(TestCase):
    def allowed(self, user, method):
        request = getattr(APIRequestFactory(), method)("/x/")
        request.user = user
        return AdministrationWrites().has_permission(request, None)

    def test_reads_stay_open_and_changes_need_administration(self):
        teller = User.objects.create_user("t", password="x")
        admin = User.objects.create_user("s", password="x")
        admin.groups.add(Group.objects.create(name="staff_mgt"))
        boss = User.objects.create_superuser("b", "b@b", "x")
        self.assertTrue(self.allowed(teller, "get"))
        self.assertFalse(self.allowed(teller, "delete"))
        self.assertTrue(self.allowed(admin, "delete"))
        self.assertTrue(self.allowed(boss, "patch"))
