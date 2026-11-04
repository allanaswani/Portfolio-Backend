"""When the database is down, and the self-fix note for the digest."""

import os
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.db import OperationalError
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.analytics.exclusions import EXCLUDED_GROUP
from apps.analytics.models import UserActivityEvent

from . import alerts, outage
from .models import AlertRecipient, AlertState


class OutageTests(TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp()
        patcher = override_settings(
            ALERT_STATE_FILE=os.path.join(folder, "state.json"))
        patcher.enable()
        self.addCleanup(patcher.disable)
        outage.database_answered(["ops@hf.test"])

    def test_one_refused_run_mails_nobody(self):
        outage.database_refused(OperationalError("connection refused"))
        self.assertEqual(mail.outbox, [])

    def test_the_second_mails_what_to_do_from_the_saved_list(self):
        outage.database_refused(OperationalError("connection refused"))
        outage.database_refused(OperationalError("connection refused"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ops@hf.test"])
        self.assertIn("ACTION NEEDED", message.subject)
        self.assertIn("df -h /data", message.body)
        self.assertIn("Do not delete anything in pg_wal", message.body)

    def test_it_mails_once_however_long_it_lasts(self):
        for _ in range(5):
            outage.database_refused(OperationalError("x"))
        self.assertEqual(len(mail.outbox), 1)

    def test_a_blip_that_clears_mails_nobody(self):
        outage.database_refused(OperationalError("x"))
        outage.database_answered(["ops@hf.test"])
        self.assertEqual(mail.outbox, [])

    def test_a_mailed_outage_is_closed(self):
        outage.database_refused(OperationalError("x"))
        outage.database_refused(OperationalError("x"))
        outage.database_answered(["ops@hf.test"])
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Resolved", mail.outbox[1].subject)

    def test_no_saved_list_falls_back_to_the_setting(self):
        os.remove(outage._path())
        with override_settings(ALERT_FALLBACK_EMAILS=["fallback@hf.test"]):
            outage.database_refused(OperationalError("x"))
            outage.database_refused(OperationalError("x"))
        self.assertEqual(mail.outbox[0].to, ["fallback@hf.test"])

    def test_the_job_survives_a_refused_connection(self):
        with mock.patch("django.db.connection.ensure_connection",
                        side_effect=OperationalError("refused")):
            call_command("run_alert_checks")

    def test_a_retried_mail_after_the_server_refused_it(self):
        """A mail that did not go is not recorded as gone."""
        with mock.patch("apps.observability.outage.send_mail",
                        side_effect=OSError("smtp")):
            outage.database_refused(OperationalError("x"))
            outage.database_refused(OperationalError("x"))
        self.assertEqual(mail.outbox, [])
        outage.database_refused(OperationalError("x"))
        self.assertEqual(len(mail.outbox), 1)


class HostAlertTests(TestCase):
    def test_something_fixed_mails_nobody_and_reaches_the_digest(self):
        AlertRecipient.objects.create(email="boss@hf.test", downtime=True,
                                      daily_digest=True)
        call_command("host_alert", "--fixed", "Emptied the trace file.")
        self.assertEqual(mail.outbox, [])
        self.assertTrue(AlertState.objects.filter(
            key__startswith=alerts.SELF_FIXED_PREFIX,
            detail="Emptied the trace file.").exists())
        call_command("send_daily_digest")
        self.assertIn("Fixed automatically: 1", mail.outbox[0].body)

    def test_a_problem_goes_to_the_downtime_list(self):
        AlertRecipient.objects.create(email="ops@hf.test", downtime=True)
        call_command("host_alert", "--subject", "ACTION NEEDED: disk",
                     "--body", "What happened:\nfull")
        self.assertEqual(mail.outbox[0].to, ["ops@hf.test"])
        self.assertIn("<b>What happened:</b>", mail.outbox[0].alternatives[0][0])


class UsageAnalyticsScreenTests(APITestCase):
    """The Administration screen must agree with the mail."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("root.r", password="x")
        self.strategy = User.objects.create_user("wash.a")
        self.rm = User.objects.create_user("amy.k")
        Group.objects.get_or_create(name=EXCLUDED_GROUP)[0].user_set.add(
            self.strategy, self.admin)
        for user in (self.strategy, self.rm):
            UserActivityEvent.objects.create(user=user, path="/x")
        self.client.force_authenticate(self.admin)

    def _get(self, name):
        return self.client.get(f"/api/v1/analytics/activity/{name}/").data

    def test_strategy_is_left_out_of_the_logins(self):
        names = [r["username"] for r in self._get("last-logins")]
        self.assertIn("amy.k", names)
        self.assertNotIn("wash.a", names)

    def test_strategy_is_left_out_of_the_figures(self):
        self.assertEqual(self._get("summary")["tracked_users"], 1)
        self.assertEqual(self._get("top-pages")[0]["users"], 1)
        self.assertEqual([r["username"] for r in self._get("recent")], ["amy.k"])

    def test_the_events_themselves_are_still_recorded(self):
        self.client.force_authenticate(self.strategy)
        before = UserActivityEvent.objects.count()
        self.client.post("/api/v1/analytics/activity/track/", {"path": "/y"})
        self.assertEqual(UserActivityEvent.objects.count(), before + 1)
