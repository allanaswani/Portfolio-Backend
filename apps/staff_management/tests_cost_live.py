"""The cost figures are read from the lake, not from whatever was loaded once.

The CEO deck reported "SAP extract of 2026-10-08" for eighteen days. Nothing
was broken: the figures were real, the endpoint was live, and the frontend was
reading it. What was missing was anything at all that moved the mirror on.
``load_sap_costs`` existed, was documented as "the one that should run on a
schedule", and was never put on cron — so the newest extract the deck could
ever show was the last one a person remembered to load by hand.

So the tests here are not about arithmetic. They are about the thing that
actually failed:

* the deck's own read checks the lake, and pulls when the lake is ahead;
* checking is CHEAP — one scalar — and backed off, or being live would cost a
  44,769-row pull on every page view;
* the probe and the load agree on what "the newest extract" means, or the deck
  would chase a date the load cannot produce;
* and every way this can go wrong leaves the figures that are there alone,
  because a wrong total on the CEO's screen is worse than an old one.
"""

import datetime
import re
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import cost_analysis, cost_ingest
from .models import OperatingExpenseMapping, SapCostCentre, SapCostPosting

BASE = "/staff_management/costs/"
THIS_YEAR = datetime.date.today().year
LOADED = datetime.date(THIS_YEAR, 10, 8)      # what the mirror holds
IN_THE_LAKE = datetime.date(THIS_YEAR, 10, 26)  # what the lake has moved on to


def lake_row(**kwargs):
    """One row shaped like the Finance query's output."""
    row = {
        "company_code": 1000, "document_number": "DOC9", "item_number": "1",
        "fiscal_year": str(THIS_YEAR), "debit_credit_indicator": "S",
        "cost_center": 110001, "gl_account_number": 705070001,
        "lcy_amount": 2500, "assignment_number": f"{THIS_YEAR}1015",
        "reference_document_number": "", "source_file": "BSEG_26-10-26",
        "dt": IN_THE_LAKE,
    }
    row.update(kwargs)
    return row


def mirrored(snapshot=LOADED, amount=1000):
    return SapCostPosting.objects.create(
        company_code=1000, document_number="DOC1", item_number="1",
        fiscal_year=THIS_YEAR, debit_credit_indicator="S",
        cost_centre=110001, gl_account_number="705070001",
        lcy_amount=amount, amount=amount,
        entry_date=datetime.date(THIS_YEAR, 3, 15),
        entry_month=f"{THIS_YEAR}-03", snapshot_date=snapshot)


class TheProbeAndTheLoadAgreeTests(TestCase):
    """If these two ever disagree the deck chases a date it cannot load."""

    def test_the_probe_dates_an_extract_exactly_as_the_load_does(self):
        """Both read the date off the SOURCE FILE NAME, in the same two
        shapes. A probe that dated a file differently would announce an
        extract the load then could not find, and the deck would flip between
        two dates for ever."""
        patterns = lambda sql: re.findall(r"'\((.*?)\)'", sql)  # noqa: E731
        self.assertEqual(patterns(cost_ingest.TRINO_QUERY),
                         patterns(cost_ingest.LATEST_SNAPSHOT_QUERY))
        self.assertEqual(patterns(cost_ingest.LATEST_SNAPSHOT_QUERY),
                         [r"\d{2}-\d{2}-\d{4}", r"\d{2}-\d{2}-\d{2}"])

    def test_the_probe_asks_the_same_table(self):
        for sql in (cost_ingest.TRINO_QUERY, cost_ingest.LATEST_SNAPSHOT_QUERY):
            self.assertIn("delta.gold_db.sap_cost_data", sql)

    def test_the_probe_returns_one_row(self):
        """The whole point: finding out the lake has not moved must not cost a
        44,769-row pull."""
        self.assertIn("MAX(", cost_ingest.LATEST_SNAPSHOT_QUERY)
        self.assertNotIn("CROSS JOIN", cost_ingest.LATEST_SNAPSHOT_QUERY)


class RefreshFromTheLakeTests(TestCase):
    def setUp(self):
        cache.clear()
        SapCostCentre.objects.update_or_create(
            cost_centre=110001,
            defaults={"cost_centre_name": "ICT", "cost_department": "ICT",
                      "cost_department_2": "", "is_branch": False})
        OperatingExpenseMapping.objects.update_or_create(
            gl="705070001",
            defaults={"expense_type": "Legal", "operating_expense": "Legal",
                      "actual_gl_name": "Legal and professional fees"})
        mirrored()

    def test_nothing_is_pulled_when_the_lake_is_not_ahead(self):
        """The common case, every day but one. It has to be cheap: the probe
        answers, and the 44,769-row query is never sent."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=LOADED), \
             mock.patch.object(cost_ingest, "fetch_from_trino") as pull:
            result = cost_ingest.refresh_from_lake()
        pull.assert_not_called()
        self.assertFalse(result["refreshed"])
        self.assertEqual(result["lake_snapshot"], LOADED.isoformat())
        self.assertIn("Already on the newest", result["detail"])

    def test_a_newer_extract_in_the_lake_is_pulled(self):
        """This is the bug. The lake had moved on and the deck could not
        know it."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=IN_THE_LAKE), \
             mock.patch.object(cost_ingest, "fetch_from_trino",
                               return_value=[lake_row(), lake_row()]):
            result = cost_ingest.refresh_from_lake()

        self.assertTrue(result["refreshed"], result)
        self.assertEqual(result["written"], 2)
        self.assertEqual(result["mirror_snapshot"], IN_THE_LAKE.isoformat())
        self.assertEqual(cost_analysis.latest_snapshot(), IN_THE_LAKE)
        # The older extract is still there to be asked for by date.
        self.assertTrue(
            SapCostPosting.objects.filter(snapshot_date=LOADED).exists())

    def test_the_pulled_rows_still_obey_the_finance_rules(self):
        """Going live must not quietly bypass the credit sign or the date off
        the assignment number - the rules are what make the figure right."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=IN_THE_LAKE), \
             mock.patch.object(
                 cost_ingest, "fetch_from_trino",
                 return_value=[lake_row(debit_credit_indicator="H")]):
            cost_ingest.refresh_from_lake()

        row = SapCostPosting.objects.get(snapshot_date=IN_THE_LAKE)
        self.assertEqual(float(row.amount), -2500.0)
        self.assertEqual(row.entry_month, f"{THIS_YEAR}-10")

    def test_an_unreachable_lake_leaves_the_figures_alone(self):
        """A stale figure that says it is stale beats a 500 on the CEO's
        screen."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               side_effect=OSError("connection refused")):
            result = cost_ingest.refresh_from_lake()

        self.assertFalse(result["refreshed"])
        self.assertIn("connection refused", result["error"])
        self.assertIn("could not be reached", result["detail"])
        self.assertEqual(cost_analysis.latest_snapshot(), LOADED)

    def test_an_unconfigured_lake_says_so_rather_than_looking_broken(self):
        with mock.patch.object(
                cost_ingest, "latest_lake_snapshot",
                side_effect=RuntimeError("TRINO_HOST is not set")):
            result = cost_ingest.refresh_from_lake()
        self.assertIn("TRINO_HOST", result["error"])
        self.assertIn("not configured", result["detail"])

    def test_a_pull_that_fails_halfway_leaves_the_old_extract_intact(self):
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=IN_THE_LAKE), \
             mock.patch.object(cost_ingest, "fetch_from_trino",
                               side_effect=OSError("reset by peer")):
            result = cost_ingest.refresh_from_lake()

        self.assertFalse(result["refreshed"])
        self.assertEqual(cost_analysis.latest_snapshot(), LOADED)
        self.assertIn("still the one before it", result["detail"])

    def test_an_empty_pull_does_not_wipe_what_is_there(self):
        """An empty answer from the lake is a failure, not a month with no
        costs in it."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=IN_THE_LAKE), \
             mock.patch.object(cost_ingest, "fetch_from_trino",
                               return_value=[]):
            result = cost_ingest.refresh_from_lake()

        self.assertFalse(result["refreshed"])
        self.assertEqual(SapCostPosting.objects.count(), 1)
        self.assertIn("must not replace a snapshot", result["detail"])


class PruningTests(TestCase):
    """Once this refreshes daily, extracts arrive at ~45,000 rows a day."""

    def setUp(self):
        cache.clear()
        for day in range(1, 16):
            mirrored(snapshot=datetime.date(THIS_YEAR, 9, day))

    def test_only_the_newest_extracts_are_kept(self):
        removed, rows = cost_ingest.prune_old_snapshots(keep=12)
        self.assertEqual(len(removed), 3)
        self.assertEqual(rows, 3)
        self.assertEqual(
            SapCostPosting.objects.values("snapshot_date").distinct().count(),
            12)
        # The OLDEST go, never the newest.
        self.assertEqual(cost_analysis.latest_snapshot(),
                         datetime.date(THIS_YEAR, 9, 15))
        self.assertFalse(SapCostPosting.objects.filter(
            snapshot_date=datetime.date(THIS_YEAR, 9, 1)).exists())

    def test_keeping_everything_is_possible(self):
        """Deleting an extract is irreversible - the Finance query returns
        only the newest, so an old one cannot be pulled back."""
        removed, rows = cost_ingest.prune_old_snapshots(keep=0)
        self.assertEqual((removed, rows), ([], 0))
        self.assertEqual(
            SapCostPosting.objects.values("snapshot_date").distinct().count(),
            15)

    def test_a_hand_load_is_not_pruned(self):
        """Somebody loading an extract by hand usually wants to compare it
        with the one before."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=IN_THE_LAKE), \
             mock.patch.object(cost_ingest, "fetch_from_trino",
                               return_value=[lake_row()]), \
             mock.patch.object(cost_ingest, "prune_old_snapshots") as prune:
            cost_ingest.refresh_from_lake(prune=False)
        prune.assert_not_called()


class TheDeckReadsTheLakeTests(TestCase):
    """The endpoint the CEO deck calls."""

    def setUp(self):
        cache.clear()
        SapCostCentre.objects.update_or_create(
            cost_centre=110001,
            defaults={"cost_centre_name": "ICT", "cost_department": "ICT",
                      "cost_department_2": "", "is_branch": False})
        OperatingExpenseMapping.objects.update_or_create(
            gl="705070001",
            defaults={"expense_type": "Legal", "operating_expense": "Legal",
                      "actual_gl_name": "Legal and professional fees"})
        mirrored()
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("ceo", password="x"))

    def test_reading_the_summary_pulls_a_newer_extract(self):
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=IN_THE_LAKE), \
             mock.patch.object(cost_ingest, "fetch_from_trino",
                               return_value=[lake_row()]):
            response = self.client.get(BASE + "summary/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["snapshot_date"], IN_THE_LAKE.isoformat())
        self.assertTrue(response.data["lake"]["refreshed"])

    def test_the_payload_says_how_fresh_it_is(self):
        """The slide said only 'SAP extract of <date>', which reads as live.
        It now has what it needs to say whether that IS the newest."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=LOADED), \
             mock.patch.object(cost_ingest, "fetch_from_trino"):
            response = self.client.get(BASE + "summary/")

        lake = response.data["lake"]
        self.assertEqual(lake["lake_snapshot"], LOADED.isoformat())
        self.assertEqual(lake["mirror_snapshot"], LOADED.isoformat())
        self.assertFalse(lake["refreshed"])

    def test_the_lake_is_asked_once_however_many_people_open_the_deck(self):
        """Twenty people at 09:00 must produce one probe, not twenty."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               return_value=LOADED) as probe, \
             mock.patch.object(cost_ingest, "fetch_from_trino"):
            for _ in range(5):
                self.client.get(BASE + "summary/")
        self.assertEqual(probe.call_count, 1)

    def test_asking_for_a_named_extract_does_not_move_the_newest(self):
        """``?snapshot=`` is a request for a particular historical extract.
        Refreshing underneath it would be the opposite of what was asked."""
        with mock.patch.object(cost_ingest, "latest_lake_snapshot") as probe, \
             mock.patch.object(cost_ingest, "fetch_from_trino") as pull:
            response = self.client.get(
                BASE + f"summary/?snapshot={LOADED.isoformat()}")

        self.assertEqual(response.status_code, 200)
        probe.assert_not_called()
        pull.assert_not_called()
        self.assertIsNone(response.data["lake"])

    @override_settings(COST_LAKE_AUTOREFRESH=False)
    def test_a_host_that_cannot_reach_the_lake_can_turn_it_off(self):
        with mock.patch.object(cost_ingest, "latest_lake_snapshot") as probe:
            response = self.client.get(BASE + "summary/")
        probe.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["snapshot_date"], LOADED.isoformat())

    def test_an_unreachable_lake_still_serves_the_figures(self):
        with mock.patch.object(cost_ingest, "latest_lake_snapshot",
                               side_effect=OSError("no route to host")):
            response = self.client.get(BASE + "summary/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["snapshot_date"], LOADED.isoformat())
        self.assertEqual(
            [row["department"] for row in response.data["by_department"]],
            ["ICT"])
        self.assertIn("no route to host", response.data["lake"]["error"])
