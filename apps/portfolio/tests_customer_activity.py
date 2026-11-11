"""A customer's Active status comes from their last transaction, not from
hf_customer's upstream flag (11 Nov 2026: a customer who transacted on 5 Nov
showed Inactive)."""
import datetime

from django.db import connection
from django.test import TestCase

from apps.portfolio import activity


class CustomerActivityTests(TestCase):
    def setUp(self):
        from apps.staff_management.models import CustomerLastTransaction

        now = datetime.datetime.now(datetime.timezone.utc)
        CustomerLastTransaction.objects.create(cust_id=1, last_txn=now - datetime.timedelta(days=6))
        CustomerLastTransaction.objects.create(cust_id=2, last_txn=now - datetime.timedelta(days=45))

    def _active(self, cust_id):
        with connection.cursor() as cur:
            cur.execute(f"SELECT {activity.active_sql('c')} FROM (SELECT %s::bigint AS cust_id) c",
                        [cust_id])
            return cur.fetchone()[0]

    def test_transacted_six_days_ago_is_active(self):
        self.assertTrue(self._active(1))

    def test_outside_the_window_or_never_is_inactive(self):
        self.assertFalse(self._active(2))
        self.assertFalse(self._active(3))
