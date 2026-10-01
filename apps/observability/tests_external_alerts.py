"""Alerts on what Customer 360 reports about itself.

Customer 360 pushes its own health (warehouse tables, the date each source is
current to, deployment settings such as the LAN proxy hosts) with
``manage.py push_monitoring``. Two things have to be true of the alerts here:

* a failing Customer 360 check is mailed in its own words - the warehouse-table
  wording ("the ETL that fills it has stopped") is false for "LAN access";
* Customer 360 going SILENT is itself an alert. A report older than
  EXTERNAL_STALE_MINUTES reads as "unknown", which on its own mails nobody.
"""

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from . import alerts, health
from .models import ExternalTableHealth, MonitoredService


def _report(table="lan_proxy_hosts", status="error", label="LAN access (proxy hosts) (Deployment)",
            error="missing 172.17.0.1, host.docker.internal"):
    return ExternalTableHealth.objects.create(
        source="customer-360", table=table, label=label, status=status, error=error)


class ExternalCheckAlertTests(APITestCase):
    def setUp(self):
        cache.clear()
        MonitoredService.objects.update_or_create(slug="customer-360", defaults={"name": "Customer 360"})

    def test_a_failing_check_is_mailed_in_its_own_words(self):
        _report()
        sent = [a for a in alerts.check_data_health() if "LAN access" in a[1]]
        self.assertEqual(len(sent), 1)
        kind, subject, body = sent[0]
        self.assertEqual(kind, "data_health")
        self.assertEqual(subject, "Customer 360: LAN access (proxy hosts) (Deployment) is error")
        self.assertIn("missing 172.17.0.1", body)
        self.assertIn("Reported by Customer 360", body)
        self.assertNotIn("ETL", body)

    def test_it_is_mailed_once_while_it_persists(self):
        _report()
        alerts.check_data_health()
        cache.clear()
        self.assertEqual([a for a in alerts.check_data_health() if "LAN access" in a[1]], [])

    def test_a_local_table_of_the_same_name_does_not_share_its_state(self):
        _report(table="build", status="error", label="Backend build (Deployment)", error="x")
        alerts.check_data_health()
        from .models import AlertState
        self.assertTrue(AlertState.objects.filter(key="table:customer-360:build").exists())
        self.assertFalse(AlertState.objects.filter(key="table:build").exists())


class SilentReporterTests(APITestCase):
    def setUp(self):
        MonitoredService.objects.update_or_create(slug="customer-360", defaults={"name": "Customer 360"})

    def _age(self, minutes):
        ExternalTableHealth.objects.update(reported_at=timezone.now() - timedelta(minutes=minutes))

    def test_going_quiet_is_an_alert(self):
        _report(status="ok", error="")
        self._age(health.EXTERNAL_STALE_MINUTES + 30)
        sent = alerts.check_external_reports()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], "Customer 360 has stopped reporting its health")
        self.assertIn("push_monitoring", sent[0][2])

    def test_it_is_not_repeated_while_quiet(self):
        _report(status="ok", error="")
        self._age(health.EXTERNAL_STALE_MINUTES + 30)
        alerts.check_external_reports()
        self.assertEqual(alerts.check_external_reports(), [])

    def test_reporting_again_is_mailed_once(self):
        _report(status="ok", error="")
        self._age(health.EXTERNAL_STALE_MINUTES + 30)
        alerts.check_external_reports()
        self._age(5)
        sent = alerts.check_external_reports()
        self.assertEqual([s[1] for s in sent], ["Customer 360 is reporting its health again"])

    def test_a_fresh_reporter_is_not_news(self):
        _report(status="ok", error="")
        self.assertEqual(alerts.check_external_reports(), [])

    def test_run_all_includes_it(self):
        _report(status="ok", error="")
        self._age(health.EXTERNAL_STALE_MINUTES + 30)
        subjects = [d["subject"] for d in alerts.run_all()]
        self.assertIn("Customer 360 has stopped reporting its health", subjects)
