"""Alerting, external-system monitoring, and the ingest path.

The hard requirement here is restraint. An alert that repeats while a problem
persists is an alert people filter away, and then the one that mattered is in
that folder too. Almost every test below is really about NOT sending.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from . import alerts
from .models import (
    AlertRecipient, AlertState, ExternalAuditEvent, ExternalTableHealth,
    MonitoredService, RequestMetric, ServiceProbe,
)


def admin(username="alert_admin"):
    return get_user_model().objects.create_user(
        username=username, password="x", is_staff=True, email=f"{username}@hf.test")


class TransitionTests(APITestCase):
    """The mechanism everything else depends on."""

    def test_a_new_problem_is_a_change(self):
        self.assertTrue(alerts.transition("k", "down", "d"))

    def test_the_same_problem_again_is_not(self):
        alerts.transition("k", "down")
        self.assertFalse(alerts.transition("k", "down"))
        self.assertFalse(alerts.transition("k", "down"))

    def test_recovery_is_a_change(self):
        alerts.transition("k", "down")
        self.assertTrue(alerts.transition("k", "ok"))

    def test_staying_healthy_is_not_a_change(self):
        alerts.transition("k", "ok")
        self.assertFalse(alerts.transition("k", "ok"))

    def test_a_first_sighting_that_is_healthy_is_not_news(self):
        """Otherwise every key mails an all-clear the first time it is checked."""
        self.assertFalse(alerts.transition("brand-new", "ok"))

    def test_a_first_sighting_that_is_broken_is_news(self):
        self.assertTrue(alerts.transition("brand-new-bad", "empty"))

    def test_the_since_time_moves_only_on_a_change(self):
        alerts.transition("k", "down")
        first = AlertState.objects.get(key="k").since
        alerts.transition("k", "down")
        self.assertEqual(AlertState.objects.get(key="k").since, first)
        alerts.transition("k", "ok")
        self.assertGreater(AlertState.objects.get(key="k").since, first)


class RecipientTests(APITestCase):
    def setUp(self):
        AlertRecipient.objects.create(
            email="ops@hf.test", downtime=True, data_health=True,
            sensitive_change=False, daily_digest=False)
        AlertRecipient.objects.create(
            email="boss@hf.test", downtime=False, data_health=False,
            sensitive_change=True, daily_digest=True)
        AlertRecipient.objects.create(
            email="gone@hf.test", downtime=True, is_active=False)

    def test_each_kind_reaches_only_its_subscribers(self):
        self.assertEqual(AlertRecipient.for_kind("downtime"), ["ops@hf.test"])
        self.assertEqual(AlertRecipient.for_kind("sensitive_change"), ["boss@hf.test"])
        self.assertEqual(AlertRecipient.for_kind("daily_digest"), ["boss@hf.test"])

    def test_an_inactive_recipient_is_not_written_to(self):
        self.assertNotIn("gone@hf.test", AlertRecipient.for_kind("downtime"))

    def test_an_unknown_kind_reaches_nobody(self):
        self.assertEqual(AlertRecipient.for_kind("nonsense"), [])

    def test_sending_with_no_subscribers_is_not_an_error(self):
        AlertRecipient.objects.all().delete()
        self.assertEqual(alerts.send("downtime", "s", "b"), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_sent_alert_reaches_the_subscribers(self):
        sent = alerts.send("downtime", "Something broke", "detail")
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Something broke", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["ops@hf.test"])


class ServiceProbeTests(APITestCase):
    """Watching Customer 360 from outside."""

    def setUp(self):
        self.service = MonitoredService.objects.create(
            slug="c360", name="Customer 360",
            health_url="https://example.invalid/health", slow_ms=1000)
        AlertRecipient.objects.create(email="ops@hf.test", downtime=True)

    def _probe(self, ok, duration=100, error="", when=None):
        return ServiceProbe.objects.create(
            service=self.service, ok=ok, duration_ms=duration, error=error,
            status_code=200 if ok else 502,
            created_at=when or timezone.now())

    def test_one_failure_is_not_an_outage(self):
        """A single timeout is a blip; alerting on it is how alerts get ignored."""
        self._probe(False)
        self.assertEqual(alerts.check_services(), [])

    def test_three_failures_in_a_row_are(self):
        for _ in range(3):
            self._probe(False, error="unreachable")
        sent = alerts.check_services()
        self.assertEqual(len(sent), 1)
        self.assertIn("DOWN", sent[0][1])
        self.assertIn("Customer 360", sent[0][1])

    def test_a_continuing_outage_does_not_keep_mailing(self):
        for _ in range(3):
            self._probe(False)
        alerts.check_services()
        self._probe(False)
        self.assertEqual(alerts.check_services(), [])

    def test_recovery_is_reported_once(self):
        for _ in range(3):
            self._probe(False)
        alerts.check_services()
        self._probe(True)
        sent = alerts.check_services()
        self.assertEqual(len(sent), 1)
        self.assertIn("RECOVERED", sent[0][1])
        self.assertEqual(alerts.check_services(), [])

    def test_up_but_slow_is_reported_as_slow_not_down(self):
        self._probe(True, duration=5000)
        sent = alerts.check_services()
        self.assertEqual(len(sent), 1)
        self.assertIn("slowly", sent[0][1])

    def test_a_service_with_no_url_is_not_probed_or_alerted(self):
        """Seeded without a URL on purpose; it must not report as down."""
        MonitoredService.objects.create(slug="push-only", name="Push Only")
        self.assertEqual(
            [s for s in alerts.check_services() if "Push Only" in s[1]], [])

    def test_a_service_never_probed_yields_nothing(self):
        ServiceProbe.objects.all().delete()
        self.assertEqual(alerts.check_services(), [])


class ErrorRateTests(APITestCase):
    def setUp(self):
        AlertRecipient.objects.create(email="ops@hf.test", downtime=True)

    def _requests(self, total, failures):
        now = timezone.now() - timedelta(minutes=5)
        for i in range(total):
            RequestMetric.objects.create(
                path="/x/", method="GET",
                status_code=500 if i < failures else 200,
                duration_ms=10, is_error=i < failures, created_at=now)

    def test_a_few_failures_on_a_quiet_night_are_not_an_incident(self):
        """Two failures out of three requests is not a 66% outage."""
        self._requests(3, 2)
        self.assertEqual(alerts.check_error_rate(), [])

    def test_a_high_rate_with_real_traffic_is(self):
        self._requests(100, 20)
        sent = alerts.check_error_rate()
        self.assertEqual(len(sent), 1)
        self.assertIn("Error rate", sent[0][1])

    def test_a_healthy_rate_does_not_alert(self):
        self._requests(100, 0)
        self.assertEqual(alerts.check_error_rate(), [])

    def test_it_does_not_repeat_while_it_stays_high(self):
        self._requests(100, 20)
        alerts.check_error_rate()
        self.assertEqual(alerts.check_error_rate(), [])


class SensitiveChangeTests(APITestCase):
    def setUp(self):
        AlertRecipient.objects.create(
            email="boss@hf.test", downtime=False, data_health=False,
            sensitive_change=True)

    def test_a_deletion_anywhere_is_reported(self):
        from apps.staff_management.models import TradeFinanceData

        row = TradeFinanceData.objects.create(
            originating_branch="X", rm_name="A", guarantee_ref="G1",
            product_type="P", customer_id=1, segment="S", our_customer="C",
            beneficiary="B", currency="KES", amount_fcy=1, issue_date="2026-01-01",
            expiry_date="", commission_lcy=0, month="JANUARY", fx_rate=1, year="2026")
        row.delete()

        sent = alerts.check_sensitive_changes(minutes=60)
        self.assertEqual(len(sent), 1)
        self.assertIn("sensitive change", sent[0][1])

    def test_a_change_to_a_sensitive_record_is_reported(self):
        from apps.staff_management.models import DSRSalesCode

        code = DSRSalesCode.objects.create(pf_number="1", sales_code="DSR1")
        code.branch = "THIKA"
        code.save()

        sent = alerts.check_sensitive_changes(minutes=60)
        self.assertTrue(sent)
        self.assertIn("DSR seller code", sent[0][2])

    def test_an_ordinary_edit_is_left_to_the_audit_trail(self):
        """A mail per edit would be unreadable, and so unread."""
        from apps.staff_management.models import TradeFinanceData

        row = TradeFinanceData.objects.create(
            originating_branch="X", rm_name="A", guarantee_ref="G2",
            product_type="P", customer_id=1, segment="S", our_customer="C",
            beneficiary="B", currency="KES", amount_fcy=1, issue_date="2026-01-01",
            expiry_date="", commission_lcy=0, month="JANUARY", fx_rate=1, year="2026")
        row.beneficiary = "KENGEN"
        row.save()

        sent = alerts.check_sensitive_changes(minutes=60)
        body = sent[0][2] if sent else ""
        # The edit itself must not be in the mail. (The recipient created in
        # setUp legitimately is — changing who hears about incidents is
        # sensitive — so this asserts on the content, not on silence.)
        self.assertNotIn("KENGEN", body)
        self.assertNotIn("G2", body)

    def test_changing_who_gets_alerted_is_itself_sensitive(self):
        """Whoever can quietly remove a recipient can silence the alerting."""
        sent = alerts.check_sensitive_changes(minutes=60)
        self.assertTrue(sent)
        self.assertIn("Alert recipient", sent[0][2])


class IngestTests(APITestCase):
    """Customer 360 pushing its own audit events and table health."""

    URL = "/observability/ingest/"

    def setUp(self):
        self.service = MonitoredService.objects.create(
            slug="c360", name="Customer 360", ingest_token="secret-token-123")
        self.client = APIClient()

    def _post(self, payload, token="secret-token-123"):
        headers = {"HTTP_X_OBSERVABILITY_TOKEN": token} if token else {}
        return self.client.post(self.URL, payload, format="json", **headers)

    def test_a_valid_token_is_accepted(self):
        res = self._post({"audit_events": [
            {"id": "c360-1", "action": "updated", "model_label": "Customer",
             "object_label": "ACME LTD", "username": "jdoe"},
        ]})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["audit_events_stored"], 1)

    def test_no_token_is_refused(self):
        self.assertEqual(self._post({"audit_events": []}, token=None).status_code, 401)

    def test_a_wrong_token_is_refused(self):
        self.assertEqual(self._post({"audit_events": []}, token="nope").status_code, 401)

    def test_an_inactive_service_cannot_push(self):
        self.service.is_active = False
        self.service.save()
        self.assertEqual(self._post({"audit_events": []}).status_code, 401)

    def test_a_retry_does_not_double_record(self):
        """A timeout on the sender's side must not duplicate the event."""
        payload = {"audit_events": [{"id": "c360-7", "action": "deleted"}]}
        self._post(payload)
        self._post(payload)
        self.assertEqual(
            ExternalAuditEvent.objects.filter(external_id="c360-7").count(), 1)

    def test_table_health_is_replaced_not_appended(self):
        self._post({"tables": [{"table": "c360_customer", "status": "ok", "rows": 10}]})
        self._post({"tables": [{"table": "c360_customer", "status": "empty", "rows": 0}]})
        rows = ExternalTableHealth.objects.filter(table="c360_customer")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().status, "empty")

    def test_an_oversized_batch_is_refused(self):
        res = self._post({"audit_events": [{"id": str(i)} for i in range(600)]})
        self.assertEqual(res.status_code, 400)

    def test_a_pushed_event_appears_in_the_audit_feed(self):
        from . import audit

        self._post({"audit_events": [
            {"id": "c360-9", "action": "updated", "model_label": "Customer",
             "object_label": "ACME LTD", "username": "jdoe",
             "changes": [{"field": "segment", "old": "SME", "new": "BB"}]},
        ]})
        rows = audit.feed(limit=50)
        external = [r for r in rows if r.get("external")]
        self.assertTrue(external, "the pushed event is missing from the feed")
        self.assertEqual(external[0]["source"], "c360")
        self.assertEqual(external[0]["object_label"], "ACME LTD")
        self.assertEqual(external[0]["changes"][0]["field"], "segment")

    def test_a_local_row_is_marked_as_local(self):
        from apps.staff_management.models import TradeFinanceData

        from . import audit

        TradeFinanceData.objects.create(
            originating_branch="X", rm_name="A", guarantee_ref="G9",
            product_type="P", customer_id=1, segment="S", our_customer="C",
            beneficiary="B", currency="KES", amount_fcy=1, issue_date="2026-01-01",
            expiry_date="", commission_lcy=0, month="JANUARY", fx_rate=1, year="2026")
        local = [r for r in audit.feed(limit=50) if not r.get("external")]
        self.assertTrue(local)
        self.assertEqual(local[0]["source"], "portfolio")


class ExternalHealthTests(APITestCase):
    def test_a_pushed_table_joins_the_data_health_list(self):
        from . import health

        ExternalTableHealth.objects.create(
            source="c360", table="c360_customer", status="ok", rows=1000,
            last_seen=timezone.now())
        rows = health.external_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertTrue(rows[0]["external"])

    def test_a_service_that_stopped_reporting_is_not_reported_as_healthy(self):
        """Silence is not health — a stale report becomes 'unknown' and says why."""
        from . import health

        row = ExternalTableHealth.objects.create(
            source="c360", table="c360_customer", status="ok", rows=1000)
        ExternalTableHealth.objects.filter(pk=row.pk).update(
            reported_at=timezone.now() - timedelta(hours=6))
        result = health.external_rows()[0]
        self.assertEqual(result["status"], "unknown")
        self.assertIn("stopped pushing", result["error"])


class AlertAdminApiTests(APITestCase):
    def setUp(self):
        self.admin = admin()
        self.plain = get_user_model().objects.create_user(
            username="plain_alert", password="x")
        self.client.force_authenticate(self.admin)

    def test_an_admin_can_add_a_recipient(self):
        res = self.client.post("/observability/alerts/recipients/", {
            "email": "new@hf.test", "downtime": True, "data_health": True,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)

    def test_a_recipient_subscribed_to_nothing_is_refused(self):
        """They would sit on the list and never be written to."""
        res = self.client.post("/observability/alerts/recipients/", {
            "email": "silent@hf.test", "downtime": False, "data_health": False,
            "sensitive_change": False, "daily_digest": False,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_an_ordinary_user_cannot_manage_recipients(self):
        self.client.force_authenticate(self.plain)
        self.assertEqual(
            self.client.get("/observability/alerts/recipients/").status_code, 403)

    def test_a_token_is_shown_once_and_never_read_back(self):
        service = MonitoredService.objects.create(slug="s", name="S")
        res = self.client.post(f"/observability/services/{service.id}/token/")
        self.assertEqual(res.status_code, 200)
        token = res.data["ingest_token"]
        self.assertTrue(token)

        listed = self.client.get("/observability/services/").data
        row = next(r for r in listed if r["slug"] == "s")
        self.assertNotIn("ingest_token", row)
        self.assertTrue(row["has_ingest_token"])

    def test_the_test_alert_proves_the_mail_path(self):
        AlertRecipient.objects.create(email="ops@hf.test", downtime=True)
        # apps.portfolio emails every newly created User on post_save, so the
        # admin built in setUp is already in the outbox. Clear it so this
        # measures the alert and nothing else.
        mail.outbox.clear()
        res = self.client.post("/observability/alerts/test/",
                               {"kind": "downtime"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["sent"], 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_the_test_alert_says_so_when_nobody_would_get_it(self):
        res = self.client.post("/observability/alerts/test/",
                               {"kind": "downtime"}, format="json")
        self.assertEqual(res.data["sent"], 0)
        self.assertIn("Nobody is subscribed", res.data["detail"])

    def test_service_status_reports_reachability_not_uptime(self):
        """A probe every few minutes cannot see a 30-second outage."""
        service = MonitoredService.objects.create(
            slug="c360", name="Customer 360", health_url="https://x.invalid/h")
        ServiceProbe.objects.create(service=service, ok=True, duration_ms=50)
        ServiceProbe.objects.create(service=service, ok=False, duration_ms=0)
        res = self.client.get("/observability/services/status/")
        row = next(r for r in res.data["services"] if r["slug"] == "c360")
        self.assertEqual(row["checks"], 2)
        self.assertEqual(row["failed"], 1)
        self.assertEqual(row["reachable_percent"], 50.0)


class DigestTests(APITestCase):
    def test_the_digest_sends_and_says_when_uptime_is_unmeasured(self):
        AlertRecipient.objects.create(
            email="boss@hf.test", downtime=False, data_health=False,
            daily_digest=True)
        call_command("send_daily_digest")
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("APPLICATION", body)
        self.assertIn("not measured", body)

    def test_a_dry_run_sends_nothing(self):
        AlertRecipient.objects.create(email="boss@hf.test", daily_digest=True)
        call_command("send_daily_digest", "--dry-run")
        self.assertEqual(len(mail.outbox), 0)
