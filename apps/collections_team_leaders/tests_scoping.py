"""Who can read the whole collections book.

Every endpoint under /collections_tl/ returns the entire book - all delay
officers, every customer. They were open to any authenticated user, which made
the per-user scoping in apps/hf_collections decoration: an agent only had to
call the TL URL instead.

These tests assert on HTTP status rather than payload, because the point is the
door, not what is behind it. The underlying queries read warehouse mirror tables
that a test database does not have, so a 200 here is not expected - what matters
is that an allowed role gets *past* the permission layer (not 403) and a
disallowed one does not.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.portfolio.models import Profile

# Every path in apps/collections_team_leaders/urls.py.
TL_PATHS = [
    "/collections_tl/loan-repayments/",
    "/collections_tl/current_book_rm_summary/",
    "/collections_tl/team_leader_current_book_rm_summary_api/",
    "/collections_tl/total_book_month_by_month_api/",
    "/collections_tl/total_book_by_bucket_collection_summary/",
    "/collections_tl/customer_collection_data_current_book_data_api/",
    # No trailing slash - the frontend calls it that way and the route matches it.
    "/collections_tl/repayment_data_eom_api_per_delay_officer_team_leader",
    "/collections_tl/collections/",
]


def make_user(username, group=None, superuser=False):
    user = User.objects.create_user(username=username, password="x")
    if superuser:
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    # The post_save signal creates the Profile; give it a code where one is read.
    Profile.objects.filter(user=user).update(sales_code="DSR001")
    return user


class TlCollectionsDoorTests(TestCase):
    """403 for everyone who is not team level, on every path."""

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_is_rejected_everywhere(self):
        for path in TL_PATHS:
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertIn(
                    res.status_code,
                    (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
                    msg=f"{path} let an anonymous caller in",
                )

    def test_a_plain_login_can_no_longer_read_the_whole_book(self):
        """The actual hole: any account at all used to reach these."""
        self.client.force_authenticate(make_user("nobody"))
        for path in TL_PATHS:
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get(path).status_code,
                    status.HTTP_403_FORBIDDEN,
                    msg=f"{path} is still readable by any authenticated user",
                )

    def test_an_unrelated_role_is_rejected(self):
        """A telesales agent has a group, but not one of these."""
        self.client.force_authenticate(make_user("agent", group="telesales_agent"))
        for path in TL_PATHS:
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get(path).status_code,
                    status.HTTP_403_FORBIDDEN,
                    msg=f"{path} is readable by telesales_agent",
                )

    def test_a_collections_officer_is_rejected_from_the_TL_urls(self):
        """collection_mgt keeps its own book via /hf_collections/, not whole-book."""
        self.client.force_authenticate(make_user("officer", group="collection_mgt"))
        res = self.client.get("/collections_tl/current_book_rm_summary/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class TlCollectionsAllowedRolesTests(TestCase):
    """The roles that could read this yesterday must still be able to.

    Gating on tl_collection alone would have locked out Exco, who reach the same
    whole-book data through _is_team_level in apps/hf_collections. These assert
    only that the permission layer lets them through.

    ``raise_request_exception=False`` is deliberate. These views read warehouse
    mirror tables that no test database has, so the query raises and the default
    test client re-raises it instead of returning a status - which would fail the
    test for a reason that has nothing to do with access. With it off the failure
    becomes a 500, and a 500 is a pass here: the request reached the view body,
    so the permission layer admitted it. Only 401/403 means the door was shut.
    """

    def setUp(self):
        self.client = APIClient(raise_request_exception=False)

    def assert_not_forbidden(self, user):
        self.client.force_authenticate(user)
        res = self.client.get("/collections_tl/current_book_rm_summary/")
        self.assertNotIn(
            res.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
            msg="permission layer rejected a role that should have access",
        )

    def test_tl_collection_is_allowed(self):
        self.assert_not_forbidden(make_user("tl", group="tl_collection"))

    def test_exco_is_allowed(self):
        self.assert_not_forbidden(make_user("exco_user", group="exco"))

    def test_ceo_is_allowed(self):
        self.assert_not_forbidden(make_user("ceo_user", group="ceo"))

    def test_superuser_is_allowed(self):
        """And why the gap was invisible: InGroup short-circuits for superusers,
        so anyone testing as one saw full data before and after this change."""
        self.assert_not_forbidden(make_user("root", superuser=True))
