"""The per-customer current book must follow the user, like its siblings do.

``CustomerCollectionDataCurrentBookView`` was the one view in this module that
ignored ``request.user`` and returned every customer in the book to anyone with
a login, while the five dashboard views beside it all scoped on
``_is_team_level``. The scoped query already existed in ``collections_core`` as
``customer_collection_data_current_book_data_not_rm`` and was called from
nowhere.

Both queries read warehouse mirror tables that no test database has, so these
patch them out and assert on *which* one the view chose, with what argument.
That is the whole behaviour under test - the SQL itself is unchanged by this
work.
"""
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.portfolio.models import Profile

URL = "/hf_collections/customer_collection_data_current_book_data_api/"

ROW = {
    "cust_id": "C1",
    "account_no": "A1",
    "firstname": "Jane",
    "lastname": "Doe",
    "delay_officer": "DSR001",
    "sales_code": "DSR001",
    "rm_name": "Jane Doe",
    "branch_name": "KISII BRANCH",
    "latin_surname": "DOE",
    "number_of_customers": 1,
    "number_of_loans": 1,
    "loan_outstanding_value": 100,
    "days_past_due": 3,
    "total_in_arrears": 10,
    "overdue_days": 3,
}


def make_user(username, group=None, sales_code="DSR001"):
    user = User.objects.create_user(username=username, password="x")
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    Profile.objects.filter(user=user).update(sales_code=sales_code)
    return user


class CustomerBookScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # The view caches per scope; a leaked key would make these tests lie.
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_an_agent_gets_only_their_own_book(self):
        self.client.force_authenticate(make_user("agent", group="collection_mgt"))
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data_not_rm",
            return_value=[ROW],
        ) as scoped, mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW, ROW],
        ) as whole:
            res = self.client.get(URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        whole.assert_not_called()
        scoped.assert_called_once_with("DSR001")
        self.assertEqual(res.json(), [ROW])

    def test_a_plain_login_with_no_role_also_gets_only_its_own_book(self):
        """The hole was that this case received the entire book."""
        self.client.force_authenticate(make_user("nobody", sales_code="DSR999"))
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data_not_rm",
            return_value=[],
        ) as scoped, mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW],
        ) as whole:
            res = self.client.get(URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        whole.assert_not_called()
        scoped.assert_called_once_with("DSR999")

    def test_a_team_leader_still_gets_the_whole_book(self):
        self.client.force_authenticate(make_user("tl", group="tl_collection"))
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW, ROW],
        ) as whole, mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data_not_rm",
            return_value=[ROW],
        ) as scoped:
            res = self.client.get(URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        scoped.assert_not_called()
        whole.assert_called_once_with()
        self.assertEqual(len(res.json()), 2)

    def test_exco_still_gets_the_whole_book(self):
        self.client.force_authenticate(make_user("exco_user", group="exco"))
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW],
        ) as whole:
            res = self.client.get(URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        whole.assert_called_once_with()

    def test_an_agent_with_no_sales_code_gets_an_empty_scope_not_everything(self):
        """A blank code must not fall through to the whole book."""
        self.client.force_authenticate(make_user("blank", sales_code=""))
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data_not_rm",
            return_value=[],
        ) as scoped, mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW],
        ) as whole:
            res = self.client.get(URL)

        whole.assert_not_called()
        scoped.assert_called_once_with("")
        self.assertEqual(res.json(), [])

    def test_anonymous_is_rejected(self):
        self.assertIn(
            self.client.get(URL).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class CustomerBookResponseShapeTests(TestCase):
    """The default response must stay the bare list the frontend already parses.

    Wrapping it in a pagination envelope unconditionally would break every
    existing caller, and a silent page cap would make any client-side total
    under-count - the trap this codebase has hit before.
    """

    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.client.force_authenticate(make_user("tl", group="tl_collection"))

    def tearDown(self):
        cache.clear()

    def test_without_a_page_param_the_response_is_a_plain_list(self):
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW] * 5,
        ):
            body = self.client.get(URL).json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 5)

    def test_with_a_page_param_the_response_is_paginated(self):
        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW] * 5,
        ):
            body = self.client.get(URL, {"page": 1, "page_size": 2}).json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body["count"], 5)
        self.assertEqual(len(body["results"]), 2)


class CustomerBookCacheTests(TestCase):
    """Caching must not leak one officer's book to another."""

    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_two_officers_do_not_share_a_cached_book(self):
        a = make_user("a", sales_code="DSR001")
        b = make_user("b", sales_code="DSR002")

        def per_code(code):
            return [{**ROW, "sales_code": code}]

        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data_not_rm",
            side_effect=per_code,
        ):
            self.client.force_authenticate(a)
            first = self.client.get(URL).json()
            self.client.force_authenticate(b)
            second = self.client.get(URL).json()

        self.assertEqual(first[0]["sales_code"], "DSR001")
        self.assertEqual(second[0]["sales_code"], "DSR002")

    def test_an_agent_does_not_read_the_team_level_cache(self):
        tl = make_user("tl2", group="tl_collection")
        agent = make_user("agent2", sales_code="DSR003")

        with mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data",
            return_value=[ROW] * 9,
        ), mock.patch(
            "apps.hf_collections.collections_core"
            ".customer_collection_data_current_book_data_not_rm",
            return_value=[ROW],
        ):
            self.client.force_authenticate(tl)
            self.assertEqual(len(self.client.get(URL).json()), 9)
            self.client.force_authenticate(agent)
            self.assertEqual(len(self.client.get(URL).json()), 1)
