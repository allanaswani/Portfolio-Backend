"""PTP - Promise To Pay.

The promise is easy. What matters is the settlement: whether the money
actually arrived, read off ``loan_repayments``, with the status derived and
never typed.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from . import ptp
from .models import Collection, PromiseToPay

BASE = "/hf_collections/ptp/"
LOAN = 998877
MADE = datetime.date(2026, 9, 1)
DUE = datetime.date(2026, 9, 28)


def make_the_feed():
    """Create ``loan_repayments`` for the test database.

    It is an unmanaged warehouse table - declared in
    ``collections_team_leaders.models`` with ``managed = False`` - so Django
    does not create it, and the settlement SQL would otherwise go untested.
    Only the columns the settlement reads.
    """
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS loan_repayments (
                id bigserial PRIMARY KEY,
                loan_account_number varchar(100),
                principal_paid numeric(20,5),
                interest_paid numeric(20,5),
                transaction_date timestamptz
            )
        """)


def pay(amount, when, loan=LOAN, interest=0):
    """Put a repayment on the warehouse feed the settlement reads."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO loan_repayments "
            "(loan_account_number, principal_paid, interest_paid, "
            " transaction_date) VALUES (%s, %s, %s, %s)",
            [str(loan), amount, interest, when])


def a_promise(**over):
    values = dict(
        loan_account_no=LOAN, customer_name="Mwangi Holdings",
        collection_officer_code="CO1", collection_officer_name="Jane Collector",
        promised_amount=Decimal("50000"), promised_date=DUE, promised_on=MADE)
    values.update(over)
    return PromiseToPay.objects.create(**values)


class SettlementTests(TestCase):
    """The four outcomes, and they are not interchangeable."""

    def setUp(self):
        make_the_feed()

    def test_the_promised_amount_arriving_in_time_is_kept(self):
        promise = a_promise()
        pay(50_000, DUE - datetime.timedelta(days=2))
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)
        self.assertEqual(promise.amount_paid, Decimal("50000"))
        self.assertEqual(promise.shortfall, 0)

    def test_more_than_promised_is_still_kept(self):
        promise = a_promise()
        pay(75_000, DUE)
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)

    def test_interest_counts_as_payment(self):
        """A promise is a promise to pay money, not to pay down principal. A
        borrower who clears their arrears interest has kept their word."""
        promise = a_promise()
        pay(0, DUE, interest=50_000)
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)

    def test_something_short_of_the_promise_is_partly_kept(self):
        promise = a_promise()
        pay(20_000, DUE)
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_PART)
        self.assertEqual(promise.shortfall, Decimal("30000"))

    def test_nothing_after_the_grace_period_is_broken(self):
        promise = a_promise()
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)
        self.assertEqual(promise.amount_paid, Decimal("0"))

    def test_a_promise_not_yet_due_is_open_and_not_held_against_anybody(self):
        promise = a_promise()
        ptp.settle(promise, today=MADE + datetime.timedelta(days=1))
        self.assertEqual(promise.status, PromiseToPay.STATUS_OPEN)

    def test_a_payment_inside_the_grace_period_still_keeps_it(self):
        """A payment on the 29th against a promise for the 28th was kept, in
        every sense a collections desk cares about."""
        promise = a_promise()
        pay(50_000, DUE + datetime.timedelta(days=ptp.GRACE_DAYS))
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)

    def test_a_payment_after_the_grace_period_does_not(self):
        promise = a_promise()
        pay(50_000, DUE + datetime.timedelta(days=ptp.GRACE_DAYS + 5))
        ptp.settle(promise, today=DUE + datetime.timedelta(days=20))
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)

    def test_a_trivial_payment_is_not_treated_as_partly_keeping_it(self):
        """A 50-bob standing order landing in the window is not a borrower
        acting on a promise to pay 50,000."""
        promise = a_promise()
        pay(50, DUE)
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)

    def test_a_payment_on_another_loan_is_not_counted(self):
        promise = a_promise()
        pay(50_000, DUE, loan=111222)
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)

    def test_a_payment_before_the_promise_was_taken_is_not_counted(self):
        """Otherwise last month's payment would keep this month's promise."""
        promise = a_promise()
        pay(50_000, MADE - datetime.timedelta(days=5))
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)

    def test_an_early_payment_counts(self):
        promise = a_promise()
        pay(50_000, MADE + datetime.timedelta(days=1))
        ptp.settle(promise, today=DUE + datetime.timedelta(days=10))
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)


class ReSettlingTests(TestCase):
    def setUp(self):
        make_the_feed()

    def test_a_payment_landing_late_in_the_feed_un_breaks_a_promise(self):
        """The repayments feed lands a day or two behind the payment. So a
        promise judged broken on Monday has to be re-judged on Tuesday when
        the money it was waiting for turns up, dated Saturday."""
        promise = a_promise()
        later = DUE + datetime.timedelta(days=ptp.GRACE_DAYS + 1)
        ptp.settle(promise, today=later)
        promise.save()
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)

        # Paid inside the window; reaches the feed only now.
        pay(50_000, DUE + datetime.timedelta(days=2))
        moved = ptp.settle_all(today=later + datetime.timedelta(days=1))
        self.assertEqual(moved, 1)
        promise.refresh_from_db()
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)

    def test_a_promise_still_inside_its_grace_period_is_not_broken(self):
        """The day after the due date is not yet a broken promise."""
        promise = a_promise()
        ptp.settle(promise, today=DUE + datetime.timedelta(days=1))
        self.assertEqual(promise.status, PromiseToPay.STATUS_OPEN)

    def test_a_kept_promise_is_never_revisited(self):
        """Money that arrived cannot un-arrive."""
        promise = a_promise()
        pay(50_000, DUE)
        ptp.settle(promise, today=DUE + datetime.timedelta(days=1))
        promise.save()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM loan_repayments")
        ptp.settle_all(today=DUE + datetime.timedelta(days=30))
        promise.refresh_from_db()
        self.assertEqual(promise.status, PromiseToPay.STATUS_KEPT)


class FromTheDiaryTests(TestCase):
    """The desk has been recording promises all along - ptp_amount and
    next_action_date on every feedback row - with nothing reading them."""

    def setUp(self):
        make_the_feed()

    def entry(self, **over):
        values = dict(
            cust_id=1, loan_account_no=LOAN, customer_name="Mwangi Holdings",
            collection_officer_code="CO1",
            collection_officer_name="Jane Collector",
            ptp_amount=50_000, next_action_date=DUE, recording_date=MADE)
        values.update(over)
        return Collection.objects.create(**values)

    def test_a_diary_entry_with_an_amount_and_a_date_becomes_a_promise(self):
        self.entry()
        made, read = ptp.from_feedback(today=DUE + datetime.timedelta(days=10))
        self.assertEqual((made, read), (1, 1))
        promise = PromiseToPay.objects.get()
        self.assertEqual(promise.promised_amount, Decimal("50000"))
        self.assertEqual(promise.promised_date, DUE)
        self.assertEqual(promise.source, PromiseToPay.SOURCE_FEEDBACK)
        # And it is settled on the way in, not left open until a cron runs.
        self.assertEqual(promise.status, PromiseToPay.STATUS_BROKEN)

    def test_an_entry_with_no_promise_is_not_one(self):
        self.entry(ptp_amount=None)
        self.entry(next_action_date=None, loan_account_no=222)
        made, _read = ptp.from_feedback()
        self.assertEqual(made, 0)
        self.assertEqual(PromiseToPay.objects.count(), 0)

    def test_running_it_twice_does_not_stack_duplicates(self):
        """A duplicated promise would halve the kept rate."""
        self.entry()
        ptp.from_feedback()
        ptp.from_feedback()
        self.assertEqual(PromiseToPay.objects.count(), 1)


class TheKeptRateTests(TestCase):
    def test_part_kept_is_not_rolled_into_kept(self):
        """A borrower who promised 50,000 and paid 5,000 did not keep their
        promise. Both numbers are given rather than averaged together."""
        a_promise(status=PromiseToPay.STATUS_KEPT, loan_account_no=1)
        a_promise(status=PromiseToPay.STATUS_KEPT, loan_account_no=2)
        a_promise(status=PromiseToPay.STATUS_PART, loan_account_no=3)
        a_promise(status=PromiseToPay.STATUS_BROKEN, loan_account_no=4)
        summary = ptp.kept_rate()
        self.assertEqual(summary["decided"], 4)
        self.assertAlmostEqual(summary["kept_rate"], 0.5)
        self.assertAlmostEqual(summary["kept_or_part_rate"], 0.75)

    def test_a_promise_not_yet_due_is_outside_the_rate(self):
        a_promise(status=PromiseToPay.STATUS_KEPT, loan_account_no=1)
        a_promise(status=PromiseToPay.STATUS_OPEN, loan_account_no=2)
        summary = ptp.kept_rate()
        self.assertEqual(summary["decided"], 1)
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["total"], 2)
        self.assertAlmostEqual(summary["kept_rate"], 1.0)

    def test_no_decided_promise_reports_no_rate_rather_than_nought(self):
        a_promise(status=PromiseToPay.STATUS_OPEN)
        self.assertIsNone(ptp.kept_rate()["kept_rate"])


class TheApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="collector", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        make_the_feed()

    def body(self, **over):
        values = dict(loan_account_no=LOAN, customer_name="Mwangi Holdings",
                      collection_officer_code="CO1",
                      promised_amount="50000", promised_date=DUE.isoformat(),
                      promised_on=MADE.isoformat())
        values.update(over)
        return values

    def test_a_collector_cannot_mark_their_own_promise_kept(self):
        """The whole design. The kept rate is what the desk is measured on,
        and a self-marked measure is not a measure."""
        res = self.client.post(BASE, self.body(status="kept"), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(PromiseToPay.objects.get().status,
                         PromiseToPay.STATUS_BROKEN)

    def test_a_paid_amount_cannot_be_submitted_either(self):
        res = self.client.post(BASE, self.body(amount_paid="50000"),
                               format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(PromiseToPay.objects.get().amount_paid, Decimal("0"))

    def test_a_promise_with_no_loan_account_is_refused(self):
        res = self.client.post(BASE, self.body(loan_account_no=None),
                               format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("loan_account_no", res.data)

    def test_a_promise_of_nothing_is_refused(self):
        res = self.client.post(BASE, self.body(promised_amount="0"),
                               format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("promised_amount", res.data)

    def test_a_date_before_the_promise_was_taken_is_refused(self):
        res = self.client.post(
            BASE, self.body(promised_date="2026-08-01"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("promised_date", res.data)

    def test_it_is_settled_on_the_way_in(self):
        pay(50_000, DUE)
        res = self.client.post(BASE, self.body(), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(PromiseToPay.objects.get().status,
                         PromiseToPay.STATUS_KEPT)

    def test_the_summary_reports_per_officer(self):
        a_promise(status=PromiseToPay.STATUS_KEPT, loan_account_no=1,
                  collection_officer_code="CO1")
        a_promise(status=PromiseToPay.STATUS_BROKEN, loan_account_no=2,
                  collection_officer_code="CO2")
        res = self.client.get(f"{BASE}summary/")
        self.assertEqual(res.status_code, 200, res.data)
        codes = {row["collection_officer_code"]: row
                 for row in res.data["by_officer"]}
        self.assertAlmostEqual(codes["CO1"]["kept_rate"], 1.0)
        self.assertAlmostEqual(codes["CO2"]["kept_rate"], 0.0)

    def test_refresh_builds_from_the_diary_and_settles(self):
        Collection.objects.create(
            cust_id=1, loan_account_no=LOAN, customer_name="Mwangi Holdings",
            collection_officer_code="CO1", ptp_amount=50_000,
            next_action_date=DUE, recording_date=MADE)
        pay(50_000, DUE)
        res = self.client.post(f"{BASE}refresh/", {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["promises_made_from_diary"], 1)
        self.assertEqual(PromiseToPay.objects.get().status,
                         PromiseToPay.STATUS_KEPT)
