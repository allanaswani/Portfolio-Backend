"""The daily usage e-mail: the portfolio tool and Customer 360."""

import datetime

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.analytics.models import UserActivityEvent
from apps.observability.management.commands import send_usage_report as report
from apps.observability.models import AlertRecipient, ExternalUsageDay

DAY = datetime.date(2026, 10, 28)


def at(hour):
    return timezone.make_aware(datetime.datetime.combine(
        DAY, datetime.time(hour)))


class UsageReportTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.amy = User.objects.create_user("amy.k", first_name="Amy",
                                            last_name="Kariuki")
        self.ben = User.objects.create_user("ben.o", first_name="Ben",
                                            last_name="Otieno")
        for user, path in ((self.amy, "/rm-portfolio"),
                           (self.amy, "/rm-portfolio/customers"),
                           (self.ben, "/rm-portfolio")):
            event = UserActivityEvent.objects.create(user=user, path=path)
            UserActivityEvent.objects.filter(pk=event.pk).update(
                created_at=at(10))
        # The day before - must not count.
        old = UserActivityEvent.objects.create(user=self.ben, path="/home")
        UserActivityEvent.objects.filter(pk=old.pk).update(
            created_at=at(10) - datetime.timedelta(days=1))

    def test_the_portfolio_day_counts_people_and_pages(self):
        p = report.portfolio_day(DAY)
        self.assertEqual(p["users"], 2)
        self.assertEqual(p["views"], 3)
        self.assertEqual(p["top_users"][0], ("Amy Kariuki", 2))
        self.assertEqual(p["top_areas"][0], ("/rm-portfolio", 2, 2))

    def test_customer_360_is_reported_with_names(self):
        ExternalUsageDay.objects.create(
            source="customer-360", day=DAY, username="amy.k",
            customer_views=12, distinct_customers=9, searches=4,
            active_minutes=35, features={"overview": 7, "statement": 2})
        body = report.build(DAY)
        self.assertIn("CUSTOMER 360", body)
        self.assertIn("People who used it   : 1", body)
        self.assertIn("12 opened, 9 different customers", body)
        self.assertIn("Amy Kariuki", body)
        self.assertIn("overview", body)

    def test_a_silent_customer_360_says_when_it_last_reported(self):
        """A stopped push and a quiet day must not both read as zero."""
        ExternalUsageDay.objects.create(
            source="customer-360", day=DAY - datetime.timedelta(days=5),
            username="amy.k", customer_views=3)
        body = report.build(DAY)
        self.assertIn("Nothing reported for 28 Oct 2026", body)
        self.assertIn("Last report received", body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_it_goes_only_to_usage_report_recipients(self):
        from django.core.management import call_command

        AlertRecipient.objects.create(email="boss@hfgroup.co.ke",
                                      usage_report=True, downtime=False,
                                      data_health=False)
        AlertRecipient.objects.create(email="ops@hfgroup.co.ke",
                                      usage_report=False)
        call_command("send_usage_report", "--day", DAY.isoformat())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["boss@hfgroup.co.ke"])
        self.assertIn("Daily usage - 28 Oct 2026", mail.outbox[0].subject)
