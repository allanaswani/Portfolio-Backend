"""Customer 360 usage: the ingest of daily per-user rows, and the adoption report that
matches them to this tool's users - including the ones who never opened it."""

from datetime import date, datetime, timedelta, timezone as tz
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from . import usage
from .models import ExternalUsageDay, MonitoredService

TOKEN = "usage-token-123"


def _row(day, username, **kw):
    return {"day": day, "username": username, "requests": 10, "customer_views": 3,
            "distinct_customers": 2, "searches": 1, "active_minutes": 5,
            "features": {"customer_profile": 3, "insights": 1}, **kw}


class UsageIngestTests(APITestCase):
    URL = "/observability/ingest/"

    def setUp(self):
        MonitoredService.objects.update_or_create(
            slug="customer-360", defaults={"name": "Customer 360", "ingest_token": TOKEN})
        self.client = APIClient()

    def _post(self, rows):
        return self.client.post(self.URL, {"usage_days": rows}, format="json",
                                HTTP_X_OBSERVABILITY_TOKEN=TOKEN)

    def test_rows_are_stored_and_resending_a_day_replaces_it(self):
        res = self._post([_row("2026-09-30", "Jane.Doe")])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["usage_days_stored"], 1)
        self._post([_row("2026-09-30", "jane.doe", customer_views=9)])
        rows = ExternalUsageDay.objects.filter(source="customer-360")
        self.assertEqual(rows.count(), 1)                      # upsert, not a duplicate
        self.assertEqual(rows.get().customer_views, 9)
        self.assertEqual(rows.get().username, "jane.doe")      # case-folded

    def test_bad_rows_are_skipped_not_fatal(self):
        res = self._post([{"day": "not-a-date", "username": "x"}, {"day": "2026-09-30"},
                          _row("2026-09-29", "ok.user", requests="junk")])
        self.assertEqual(res.data["usage_days_stored"], 1)
        self.assertEqual(ExternalUsageDay.objects.get().requests, 0)

    def test_usage_must_be_a_list(self):
        res = self.client.post(self.URL, {"usage_days": {"a": 1}}, format="json",
                               HTTP_X_OBSERVABILITY_TOKEN=TOKEN)
        self.assertEqual(res.status_code, 400)

    def test_old_payloads_without_usage_still_work(self):
        res = self.client.post(self.URL, {"audit_events": []}, format="json",
                               HTTP_X_OBSERVABILITY_TOKEN=TOKEN)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["usage_days_stored"], 0)


class AdoptionTests(APITestCase):
    # 09:00 Nairobi on 30 Sep 2026.
    NOW = datetime(2026, 9, 30, 6, 0, tzinfo=tz.utc)

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user("obs_admin", password="x", is_staff=True)
        for name in ("active.rm", "quiet.rm", "lapsed.rm", "never.rm"):
            User.objects.create_user(name, password="x")
        User.objects.create_user("gone.rm", password="x", is_active=False)
        MonitoredService.objects.update_or_create(slug="customer-360", defaults={"name": "Customer 360"})
        today = date(2026, 9, 30)
        mk = lambda d, u, **kw: ExternalUsageDay.objects.create(  # noqa: E731
            source="customer-360", day=today - timedelta(days=d), username=u,
            customer_views=kw.get("cv", 2), searches=1, features={"insights": 1})
        mk(0, "active.rm", cv=5)
        mk(3, "active.rm", cv=1)
        mk(12, "quiet.rm")
        mk(60, "lapsed.rm")
        mk(1, "c360.local.only")                 # a Customer 360 login with no account here

    def report(self, days=30):
        return usage.adoption("customer-360", days, self.NOW)

    def test_every_user_gets_exactly_one_status(self):
        r = {u["username"]: u for u in self.report()["users"]}
        self.assertEqual(r["active.rm"]["status"], "active")
        self.assertEqual(r["quiet.rm"]["status"], "quiet")
        self.assertEqual(r["lapsed.rm"]["status"], "lapsed")
        self.assertEqual(r["never.rm"]["status"], "never")
        self.assertNotIn("gone.rm", r)                         # disabled accounts are not expected to use it

    def test_summary_counts_only_this_directory(self):
        s = self.report()["summary"]
        # obs_admin + 4 RMs are the directory; the C360-only login is listed but not counted.
        self.assertEqual(s["users"], 5)
        self.assertEqual((s["active"], s["quiet"], s["lapsed"], s["never"]), (1, 1, 1, 2))
        self.assertEqual(s["adoption_pct"], 60.0)

    def test_unknown_username_is_listed_and_marked(self):
        r = {u["username"]: u for u in self.report()["users"]}
        self.assertFalse(r["c360.local.only"]["known_here"])

    def test_window_totals_and_trend(self):
        rep = self.report(days=7)
        r = {u["username"]: u for u in rep["users"]}
        self.assertEqual(r["active.rm"]["customer_views"], 6)
        self.assertEqual(r["active.rm"]["days_active"], 2)
        self.assertEqual(r["quiet.rm"]["customer_views"], 0)   # outside a 7-day window
        self.assertEqual(len(rep["trend"]), 7)
        self.assertEqual(rep["trend"][-1]["day"], date(2026, 9, 30))
        self.assertEqual(rep["features"][0]["feature"], "insights")

    def test_endpoint_is_admin_only(self):
        url = "/observability/usage/customer-360/"
        c = APIClient()
        c.force_authenticate(get_user_model().objects.get(username="never.rm"))
        self.assertEqual(c.get(url).status_code, 403)
        c.force_authenticate(self.admin)
        with mock.patch("django.utils.timezone.now", return_value=self.NOW):
            res = c.get(url + "?days=30")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"]["users"], 5)
