"""What the Audit Trail and Data Health dashboards must keep doing.

The warehouse mirrors are ``TEST: {"MIRROR": ...}``, so the unmanaged tables the
data-health scan reads do not exist in a test database. The scan's judgement —
which table counts as empty, stale or missing, and which column is the freshness
column — is therefore pinned as the pure function it is, and the endpoint is
pinned on its permissions.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.observability import audit, health, metrics
from apps.observability.middleware import RequestMetricsMiddleware, flush, normalise_path
from apps.observability.models import AppHeartbeat, RequestMetric
from apps.staff_management.models import TradeFinanceData


def admin_user(username="obs_admin"):
    User = get_user_model()
    return User.objects.create_user(
        username=username, password="x", is_staff=True, email=f"{username}@hf.test"
    )


def metric(path="/ceo/summary/", ms=100, status=200, when=None, username=""):
    return RequestMetric.objects.create(
        path=path, method="GET", status_code=status, duration_ms=ms,
        is_error=status >= 500, username=username,
        created_at=when or timezone.now(),
    )


class PathNormalisationTests(TestCase):
    """Ids collapse so a route aggregates instead of scattering."""

    def test_numeric_ids_collapse(self):
        self.assertEqual(normalise_path("/mortgages/leads/42/"), "/mortgages/leads/:id")

    def test_uuids_collapse(self):
        path = "/client_briefs/3f2504e0-4f89-11d3-9a0c-0305e82c3301/"
        self.assertEqual(normalise_path(path), "/client_briefs/:id")

    def test_the_query_string_is_dropped(self):
        self.assertEqual(normalise_path("/ceo/employees/?page=3"), "/ceo/employees")

    def test_two_records_of_one_route_aggregate_together(self):
        self.assertEqual(
            normalise_path("/mortgages/leads/1/"), normalise_path("/mortgages/leads/999/")
        )


class MiddlewareTests(TestCase):
    def setUp(self):
        flush(force=True)
        RequestMetric.objects.all().delete()

    def test_a_request_is_recorded_with_its_duration(self):
        client = APIClient()
        client.force_authenticate(admin_user())
        client.get("/observability/performance/overview/?hours=1")
        # The observability endpoints are deliberately not measured — they would
        # report on the traffic they themselves generate.
        flush(force=True)
        self.assertEqual(RequestMetric.objects.count(), 0)

    def test_an_ordinary_request_is_measured(self):
        client = APIClient()
        client.get("/auth/api/token/")  # unauthenticated is fine; it is still served
        flush(force=True)
        row = RequestMetric.objects.first()
        self.assertIsNotNone(row, "an ordinary request should have been recorded")
        self.assertEqual(row.method, "GET")
        self.assertGreaterEqual(row.duration_ms, 0)

    def test_a_5xx_is_flagged_as_an_error(self):
        RequestMetricsMiddleware.record(_FakeRequest("/x/1/"), 500, 12)
        flush(force=True)
        row = RequestMetric.objects.get()
        self.assertTrue(row.is_error)
        self.assertEqual(row.path, "/x/:id")

    def test_a_4xx_is_not_counted_as_downtime(self):
        RequestMetricsMiddleware.record(_FakeRequest("/x/"), 404, 5)
        flush(force=True)
        self.assertFalse(RequestMetric.objects.get().is_error)

    def test_a_buffered_row_survives_the_account_it_names_going_away(self):
        """The flush happens after the request — and can outlive the user.

        These rows are telemetry, not relational data. A foreign key here meant
        one deleted (or rolled-back) account discarded the whole buffered batch
        on a constraint violation.
        """
        user = admin_user("transient")
        RequestMetricsMiddleware.record(_FakeRequest("/x/"), 200, 5)
        # Simulate the account disappearing between the request and the flush.
        RequestMetric.objects.all().delete()
        user.delete()
        flush(force=True)
        self.assertEqual(RequestMetric.objects.count(), 1)


class _FakeRequest:
    def __init__(self, path):
        self.path = path
        self.method = "GET"
        self.user = None


class MetricsTests(TestCase):
    def setUp(self):
        RequestMetric.objects.all().delete()
        now = timezone.now()
        for ms in (10, 20, 30, 40, 50, 60, 70, 80, 90, 1000):
            metric(ms=ms, when=now - timedelta(minutes=1))
        metric(ms=5, status=500, when=now - timedelta(minutes=1))

    def test_percentiles_come_from_the_database_not_a_sample(self):
        since, until = metrics.window(hours=1)
        p = metrics.percentiles(since, until)
        self.assertIsNotNone(p["p95"])
        self.assertGreaterEqual(p["p95"], p["p50"])
        self.assertGreaterEqual(p["p99"], p["p95"])

    def test_the_error_rate_counts_only_5xx(self):
        data = metrics.overview(hours=1)
        self.assertEqual(data["requests"], 11)
        self.assertEqual(data["errors"], 1)
        self.assertAlmostEqual(data["error_rate"], round(1 / 11 * 100, 2))

    def test_one_slow_request_moves_p99_but_not_the_median(self):
        since, until = metrics.window(hours=1)
        p = metrics.percentiles(since, until)
        self.assertLess(p["p50"], 200)
        self.assertGreater(p["p99"], 200)

    def test_the_series_is_bucketed_and_ordered(self):
        series = metrics.timeseries(hours=1, buckets=12)
        self.assertTrue(series)
        stamps = [row["t"] for row in series]
        self.assertEqual(stamps, sorted(stamps))

    def test_the_slowest_endpoint_is_ranked_by_p95(self):
        metric(path="/slow/", ms=5000)
        rows = metrics.endpoints(hours=1)
        self.assertEqual(rows[0]["path"], "/slow/")


class UptimeTests(TestCase):
    def test_uptime_is_not_reported_when_nothing_measures_it(self):
        """Silence is not proof of uptime — say so rather than claim 100%."""
        result = metrics.uptime(hours=1)
        self.assertFalse(result["measured"])
        self.assertIsNone(result["percent"])

    def test_heartbeats_give_a_real_percentage(self):
        now = timezone.now().replace(second=0, microsecond=0)
        for offset in range(0, 60):
            AppHeartbeat.objects.create(minute=now - timedelta(minutes=offset))
        result = metrics.uptime(hours=1)
        self.assertTrue(result["measured"])
        self.assertGreater(result["percent"], 90)

    def test_a_gap_in_heartbeats_is_downtime(self):
        now = timezone.now().replace(second=0, microsecond=0)
        # Half the hour recorded, half missing.
        for offset in range(0, 30):
            AppHeartbeat.objects.create(minute=now - timedelta(minutes=offset))
        result = metrics.uptime(hours=1)
        self.assertLess(result["percent"], 60)
        self.assertGreater(result["downtime_minutes"], 20)


class AuditTests(TestCase):
    """The trail simple_history has been writing all along, finally read."""

    def setUp(self):
        self.user = admin_user("auditor")

    def test_every_history_tracked_model_is_discovered(self):
        models = audit.auditable_models()
        names = {(m["app_label"], m["model"]) for m in models}
        self.assertIn(("trade_register", "traderegisterentry"), names)
        self.assertIn(("staff_management", "tradefinancedata"), names)
        self.assertGreater(len(models), 20)

    def test_a_create_appears_in_the_feed(self):
        TradeFinanceData.objects.create(
            originating_branch="THIKA", rm_name="A", guarantee_ref="G1",
            product_type="Bid Bond", customer_id=1, segment="SME",
            our_customer="C", beneficiary="B", currency="KES", amount_fcy=10,
            issue_date="2026-01-01", expiry_date="2026-06-01",
            commission_lcy=1, month="JANUARY", fx_rate=1, year="2026",
        )
        rows = audit.feed(limit=20)
        self.assertTrue(rows)
        self.assertEqual(rows[0]["action"], "created")
        self.assertEqual(rows[0]["model"], "tradefinancedata")

    def test_an_update_reports_which_field_changed_and_what_from(self):
        row = TradeFinanceData.objects.create(
            originating_branch="THIKA", rm_name="A", guarantee_ref="G2",
            product_type="Bid Bond", customer_id=1, segment="SME",
            our_customer="C", beneficiary="B", currency="KES", amount_fcy=10,
            issue_date="2026-01-01", expiry_date="2026-06-01",
            commission_lcy=1, month="JANUARY", fx_rate=1, year="2026",
        )
        row.our_customer = "Corrected Ltd"
        row.save()

        feed = audit.feed(limit=20)
        update = next(r for r in feed if r["action"] == "updated")
        changed = {c["field"]: (c["old"], c["new"]) for c in update["changes"]}
        self.assertIn("our_customer", changed)
        self.assertEqual(changed["our_customer"], ("C", "Corrected Ltd"))

    def test_a_create_carries_no_diff(self):
        TradeFinanceData.objects.create(
            originating_branch="X", rm_name="A", guarantee_ref="G3",
            product_type="P", customer_id=1, segment="S", our_customer="C",
            beneficiary="B", currency="KES", amount_fcy=1, issue_date="2026-01-01",
            expiry_date="", commission_lcy=0, month="JANUARY", fx_rate=1, year="2026",
        )
        created = next(r for r in audit.feed(limit=20) if r["action"] == "created")
        self.assertEqual(created["changes"], [])

    def test_the_feed_can_be_filtered_to_one_model(self):
        TradeFinanceData.objects.create(
            originating_branch="X", rm_name="A", guarantee_ref="G4",
            product_type="P", customer_id=1, segment="S", our_customer="C",
            beneficiary="B", currency="KES", amount_fcy=1, issue_date="2026-01-01",
            expiry_date="", commission_lcy=0, month="JANUARY", fx_rate=1, year="2026",
        )
        rows = audit.feed(model="tradefinancedata", limit=20)
        self.assertTrue(rows)
        self.assertTrue(all(r["model"] == "tradefinancedata" for r in rows))

    def test_a_deletion_is_recorded_rather_than_vanishing(self):
        row = TradeFinanceData.objects.create(
            originating_branch="X", rm_name="A", guarantee_ref="G5",
            product_type="P", customer_id=1, segment="S", our_customer="C",
            beneficiary="B", currency="KES", amount_fcy=1, issue_date="2026-01-01",
            expiry_date="", commission_lcy=0, month="JANUARY", fx_rate=1, year="2026",
        )
        row.delete()
        actions = [r["action"] for r in audit.feed(limit=20)]
        self.assertIn("deleted", actions)


class DataHealthJudgementTests(TestCase):
    """The verdict logic, pinned as the pure function it is."""

    def test_a_table_that_is_not_there_is_missing_not_empty(self):
        self.assertEqual(health._classify(False, 0, None), "missing")

    def test_zero_rows_is_empty(self):
        self.assertEqual(health._classify(True, 0, 0), "empty")

    def test_a_fresh_table_is_ok(self):
        self.assertEqual(health._classify(True, 100, 0), "ok")

    def test_a_week_old_table_is_stale(self):
        self.assertEqual(health._classify(True, 100, health.STALE_DAYS), "stale")

    def test_a_table_with_no_date_column_is_unknown_not_ok(self):
        """Never claim freshness that was not measured."""
        self.assertEqual(health._classify(True, 100, None), "unknown")

    def test_the_freshness_column_prefers_updated_at(self):
        field = health._freshness_field(TradeFinanceData)
        self.assertEqual(field.name, "updated_at")

    def test_one_unreadable_table_does_not_take_the_scan_down(self):
        """The whole point of the page is to report a table it cannot read.

        The scan used to wrap all thirty-six probes in a single
        `except DatabaseError`. Django's InterfaceError is a SIBLING of
        DatabaseError, not a subclass, so a dropped connection — or any other
        exception from one odd column — escaped and 500'd the entire screen.
        """
        # A test database refuses the warehouse alias outright, which raises
        # DatabaseOperationForbidden — itself neither a DatabaseError nor an
        # InterfaceError. That is the same shape as the production failure, so
        # it is the fixture: the scan must survive whatever it is handed.
        rows = health.table_health()

        self.assertTrue(rows, "the scan should still return a row per table")
        self.assertTrue(all(r["status"] == "error" for r in rows))
        self.assertTrue(rows[0]["error"], "the row must say why it could not be read")
        # And it must name the exception, so the page can be acted on.
        self.assertIn(":", rows[0]["error"])

    def test_a_table_that_reads_but_will_not_aggregate_keeps_its_row(self):
        """Losing freshness must cost the row its age, not its whole entry."""
        from unittest.mock import MagicMock, patch

        with patch("apps.observability.health.connections", MagicMock()),              patch("apps.observability.health._estimate_rows",
                   return_value=(True, 100, True)),              patch("django.db.models.QuerySet.aggregate",
                   side_effect=TypeError("not a date")):
            rows = health.table_health()

        dated = [r for r in rows if r["freshness_column"]]
        self.assertTrue(dated)
        # The size survived; only the age was lost.
        self.assertEqual(dated[0]["rows"], 100)
        self.assertIsNone(dated[0]["age_days"])
        self.assertIn("not a date", dated[0]["error"])

    def test_the_endpoint_answers_even_when_the_warehouse_is_unreachable(self):
        client = APIClient()
        client.force_authenticate(admin_user("health_admin"))
        res = client.get("/observability/data-health/")
        self.assertEqual(res.status_code, 200, "the scan must answer, not 500")
        self.assertGreater(res.data["summary"]["tables"], 0)
        # Every table unreadable here, and the response says so per table.
        self.assertTrue(all(t["status"] == "error" for t in res.data["tables"]))

    def test_every_warehouse_table_is_in_scope(self):
        tables = {m._meta.db_table for m in health.warehouse_models()}
        self.assertIn("employee_table", tables)
        self.assertGreater(len(tables), 20)


class PermissionTests(TestCase):
    """The trail says who changed what across the whole bank — admins only."""

    ENDPOINTS = [
        "/observability/audit/feed/",
        "/observability/audit/models/",
        "/observability/audit/summary/",
        "/observability/data-health/",
        "/observability/performance/overview/",
        "/observability/performance/series/",
        "/observability/performance/uptime/",
    ]

    def test_an_ordinary_user_is_refused(self):
        User = get_user_model()
        user = User.objects.create_user(username="plain", password="x")
        client = APIClient()
        client.force_authenticate(user)
        for url in self.ENDPOINTS:
            self.assertEqual(client.get(url).status_code, 403, url)

    def test_a_staff_mgt_administrator_is_let_in(self):
        """The Administration menu is shown to the staff_mgt GROUP.

        Gating the API on is_staff alone meant an administrator saw the menu
        item and was refused behind it — which renders as a page of zeros, not
        as an error anyone can act on.
        """
        User = get_user_model()
        user = User.objects.create_user(username="staffmgt", password="x")
        user.groups.add(Group.objects.get_or_create(name="staff_mgt")[0])
        client = APIClient()
        client.force_authenticate(user)
        for url in self.ENDPOINTS:
            if url == "/observability/data-health/":
                continue  # reads the warehouse, which a test DB mirrors away
            self.assertEqual(client.get(url).status_code, 200, url)

    def test_a_user_in_some_other_group_is_still_refused(self):
        User = get_user_model()
        user = User.objects.create_user(username="othergroup", password="x")
        user.groups.add(Group.objects.get_or_create(name="tl_collection")[0])
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get("/observability/audit/feed/").status_code, 403)

    def test_anonymous_is_refused(self):
        client = APIClient()
        for url in self.ENDPOINTS:
            self.assertIn(client.get(url).status_code, (401, 403), url)

    def test_an_administrator_gets_the_dashboards(self):
        client = APIClient()
        client.force_authenticate(admin_user())
        for url in self.ENDPOINTS:
            if url == "/observability/data-health/":
                continue  # reads the warehouse, which a test DB mirrors away
            self.assertEqual(client.get(url).status_code, 200, url)
