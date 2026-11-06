"""Sylvia Kimani, Oct 2026: the Engagement report said 20 of her clients were not
contacted, this list said nil. It counted a contact from any year; the report counts
this year. They now agree, and the list shows when the last contact was."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.portfolio.models import Feedback

from . import views

CODE = "SWK3881"


class FakeSerializer:
    def __init__(self, rows, many=True):
        self.data = [{"cust_id": r.cust_id} for r in rows]


class NotContactedMeansThisYearTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(
            user=get_user_model().objects.create_user(username="rm", password="x"))

    def _list(self, book):
        allocated = MagicMock()
        allocated.objects.filter.return_value.values_list.return_value.first.return_value = "RM"
        with patch.object(views, "_get_profile", return_value=SimpleNamespace(sales_code=CODE)), \
                patch.object(views.svc, "customers",
                             return_value=[SimpleNamespace(cust_id=c) for c in book]), \
                patch.object(views, "HfCustomerSerializer", FakeSerializer), \
                patch.object(views, "RetailAllocatedPortfolio", allocated):
            return self.client.get("/portfolio/feedback_customers_not_contacted/")

    def _contact(self, cust_id, day, code=CODE):
        Feedback.objects.create(cust_id=cust_id, sales_code=code, date=day)

    def test_the_list_counts_this_year_and_shows_the_last_contact(self):
        today = timezone.localdate()
        last_year = today.replace(year=today.year - 1, month=6, day=15)
        self._contact(1, today)
        self._contact(2, last_year)
        self._contact(4, last_year)
        self._contact(4, today)
        found = {r["cust_id"]: r for r in self._list([1, 2, 3, 4]).data}

        self.assertEqual(sorted(found), [2, 3])
        self.assertEqual(found[2]["last_contact_date"], last_year.isoformat())
        self.assertFalse(found[2]["never_contacted"])
        self.assertIsNone(found[3]["last_contact_date"])
        self.assertTrue(found[3]["never_contacted"])

    def test_another_rms_contact_does_not_count(self):
        self._contact(1, timezone.localdate(), code="OTHER")
        self.assertEqual([r["cust_id"] for r in self._list([1]).data], [1])

    def test_the_first_of_january_is_this_year(self):
        self._contact(1, timezone.localdate().replace(month=1, day=1))
        self.assertEqual(self._list([1]).data, [])
