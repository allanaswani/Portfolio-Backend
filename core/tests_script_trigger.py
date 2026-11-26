"""The report buttons may queue only the reports they send (26 Nov 2026). The
host watcher runs any .py it is named, as root, so before this any signed-in
user could run any ETL in the folder by posting its name."""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

URL = "/staff_management/drawdowns/trigger-script/"


class ScriptTriggerAllowListTests(TestCase):
    def setUp(self):
        self.queue = tempfile.TemporaryDirectory()
        self.addCleanup(self.queue.cleanup)
        override = override_settings(ETL_REQUEST_DIR=self.queue.name)
        override.enable()
        self.addCleanup(override.disable)
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("rm", password="x"))

    def queued(self):
        return sorted(p.name for p in Path(self.queue.name).glob("*.request"))

    def test_a_buttons_report_is_queued(self):
        got = self.client.post(URL, {"script_name": "drawdown_report_correct"})
        self.assertEqual(got.status_code, 202, got.content)
        self.assertEqual(len(self.queued()), 1)
        self.assertTrue(self.queued()[0].startswith("drawdown_report_correct__"))

    def test_a_subfolder_report_on_the_list_is_queued(self):
        got = self.client.post(URL, {"script_name": "hfcb_properties_reports/afh_applications"})
        self.assertEqual(got.status_code, 202, got.content)

    def test_any_other_script_is_refused_and_nothing_is_queued(self):
        for name in ("loans_etl", "products_etl", "hfcb_properties_reports/x"):
            with self.subTest(name):
                got = self.client.post(URL, {"script_name": name})
                self.assertEqual(got.status_code, 403)
        self.assertEqual(self.queued(), [])

    def test_signed_out_is_refused(self):
        got = APIClient().post(URL, {"script_name": "drawdown_report_correct"})
        self.assertEqual(got.status_code, 401)
