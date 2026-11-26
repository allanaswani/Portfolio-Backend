"""The bank-wide CEO endpoints are for the groups whose pages call them, not
for everyone signed in (26 Nov 2026).

Who calls what was read off the frontend: /gceo and /cfo belong to ``ceo``,
/exco-view to ``exco``, /business-performance to ``business_performance``; the
branch manager's Customers page also draws branch_deposit_trends; the HR
roster belongs to the Management screens (``staff_mgt``, ``admin_viewer``).

Only the permission step is exercised. It runs before any view body, so
nothing here reaches the warehouse alias (which the dev settings point at
production)."""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory

from apps.gceo_dashboard import urls as ceo_urls


def ceo_routes():
    return [(str(p.pattern), p.callback.view_class) for p in ceo_urls.urlpatterns]


def member(name, *groups):
    user = User.objects.create_user(name, password="x")
    for g in groups:
        user.groups.add(Group.objects.get_or_create(name=g)[0])
    return user


def allowed(user, view_class, method="get"):
    request = getattr(APIRequestFactory(), method)("/ceo/x/")
    request.user = user
    return all(p().has_permission(request, None) for p in view_class.permission_classes)


class CeoEndpointsRefuseEveryoneElseTests(TestCase):
    def test_an_ordinary_signed_in_user_gets_403_on_every_ceo_url(self):
        client = APIClient()
        client.force_authenticate(member("teller"))
        self.assertGreater(len(ceo_routes()), 60)
        for route, _ in ceo_routes():
            with self.subTest(route):
                self.assertEqual(client.get("/ceo/" + route).status_code, 403)

    def test_a_branch_manager_gets_only_the_trend_their_page_draws(self):
        bm = member("bm", "branch_portfolio")
        for route, view in ceo_routes():
            with self.subTest(route):
                self.assertEqual(allowed(bm, view), route == "branch_deposit_trends/")


class OwningGroupsPassTests(TestCase):
    def test_ceo_exco_and_business_performance_read_the_dashboard(self):
        dashboard = [v for r, v in ceo_routes() if not r.startswith("employees")]
        for group in ("ceo", "exco", "business_performance"):
            user = member("u_" + group, group)
            for view in dashboard:
                with self.subTest(group=group, view=view.__name__):
                    self.assertTrue(allowed(user, view))

    def test_the_roster_is_managements_and_only_staff_mgt_changes_it(self):
        roster = [v for r, v in ceo_routes() if r.startswith("employees")]
        self.assertEqual(len(roster), 3)
        staff, viewer, ceo = (member("s", "staff_mgt"), member("v", "admin_viewer"),
                              member("c", "ceo"))
        for view in roster:
            with self.subTest(view.__name__):
                self.assertTrue(allowed(staff, view, "post"))
                self.assertTrue(allowed(viewer, view, "get"))
                self.assertFalse(allowed(viewer, view, "post"))
                self.assertFalse(allowed(ceo, view, "get"))

    def test_a_superuser_passes_everywhere(self):
        boss = User.objects.create_superuser("b", "b@b", "x")
        for _, view in ceo_routes():
            self.assertTrue(allowed(boss, view, "post"))

    def test_the_exco_copies_keep_their_own_gate(self):
        from apps.exco_portfolio.views import ExcoCustomersView
        self.assertTrue(allowed(member("e", "exco"), ExcoCustomersView))
        self.assertFalse(allowed(member("bp", "business_performance"), ExcoCustomersView))
