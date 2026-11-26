"""Changes need the role whose screen makes them (26 Nov 2026).

The groups come from the frontend: each write call was traced to the pages
that make it and to the sidebar module / home tile that owns those pages.
HFDI admin screens -> hfdi_admin; Exco Initiatives admin -> exco_initiatives_admin;
Trade Register -> registry_officer / registry_supervisor; mortgage Approvals ->
mortgage_manager (and mortgage_admin); interest rates -> mortgage_admin; DSR codes and
team leaders -> Administration. Reads are untouched.

Changes are refused by the permission step, before any view body runs, so
these requests never reach the warehouse alias."""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient, APIRequestFactory

from apps.client_briefs.models import ClientBrief
from apps.exco_innitiatives import views as exco
from apps.hfdi import views as hfdi
from apps.mortgages import views as mortgages
from apps.staff_management import dsr_views, tl_views
from apps.trade_register import views as trade

OWNERS = {
    hfdi.ObligationSummaryListCreateView: "hfdi_admin",
    hfdi.ProjectTitanPlotsAllocationDetailView: "hfdi_admin",
    hfdi.AFHSellerMappingListCreateView: "hfdi_admin",
    exco.StrategicInitiativeListCreateView: "exco_initiatives_admin",
    exco.StrategicMilestoneDetailView: "exco_initiatives_admin",
    trade.TradeRegisterEntryListCreateView: "registry_officer",
    trade.TradeRegisterEntryDetailView: "registry_supervisor",
    mortgages.ApplicationApproveView: "mortgage_manager",
    mortgages.ApplicationDisburseView: "mortgage_manager",
    mortgages.InterestRateDetailView: "mortgage_admin",
    dsr_views.DSRSalesCodeAllocateView: "staff_mgt",
    tl_views.TeamLeaderReassignView: "staff_mgt",
}


def url_of(view_class, patterns=None, prefix=""):
    for p in patterns if patterns is not None else get_resolver().url_patterns:
        if isinstance(p, URLResolver):
            found = url_of(view_class, p.url_patterns, prefix + str(p.pattern))
            if found:
                return found
        elif isinstance(p, URLPattern) and getattr(p.callback, "view_class", None) is view_class:
            route = prefix + str(p.pattern)
            for conv in ("<int:pk>", "<int:id>", "<pk>", "<int:application_id>"):
                route = route.replace(conv, "1")
            return "/" + route
    return None


def member(name, *groups):
    user = User.objects.create_user(name, password="x")
    for g in groups:
        user.groups.add(Group.objects.get_or_create(name=g)[0])
    return user


def passes(user, view_class, method):
    request = getattr(APIRequestFactory(), method)("/x/")
    request.user = user
    return all(p().has_permission(request, None) for p in view_class.permission_classes)


class ChangesNeedTheOwningRoleTests(TestCase):
    def test_an_ordinary_user_cannot_change_any_of_them(self):
        client = APIClient()
        client.force_authenticate(member("teller"))
        for view in OWNERS:
            url = url_of(view)
            self.assertIsNotNone(url, view.__name__)
            method = next(m for m in ("post", "patch", "delete") if hasattr(view, m))
            with self.subTest(view=view.__name__, method=method):
                got = getattr(client, method)(url, {}, format="json")
                self.assertEqual(got.status_code, 403, got.content[:200])

    def test_the_owning_role_passes_and_reads_stay_open(self):
        teller = member("t2")
        for view, group in OWNERS.items():
            owner = member("o_" + view.__name__[:20], group)
            with self.subTest(view.__name__):
                self.assertTrue(passes(owner, view, "post"))
                self.assertFalse(passes(teller, view, "post"))
                if "get" in view.http_method_names and not view.__name__.startswith(("Application", "DSRSalesCodeAllocate", "TeamLeaderReassign")):
                    self.assertTrue(passes(teller, view, "get"))


class ClientBriefOwnerTests(TestCase):
    def setUp(self):
        self.alice, self.bob = member("alice", "portfolio_mgt"), member("bob", "portfolio_mgt")
        self.brief = ClientBrief.objects.create(rm=self.alice, client_name="ACME LTD")

    def change(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client.patch(f"/client_briefs/briefs/{self.brief.pk}/", {"client_name": "X"}, format="json")

    def test_another_rm_cannot_change_or_delete_it(self):
        self.assertEqual(self.change(self.bob).status_code, 403)
        client = APIClient()
        client.force_authenticate(self.bob)
        self.assertEqual(client.delete(f"/client_briefs/briefs/{self.brief.pk}/").status_code, 403)
        self.assertTrue(ClientBrief.objects.filter(pk=self.brief.pk).exists())

    def test_its_own_rm_and_administration_can(self):
        self.assertEqual(self.change(self.alice).status_code, 200)
        self.assertEqual(self.change(member("admin", "staff_mgt")).status_code, 200)
