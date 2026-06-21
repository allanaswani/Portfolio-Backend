from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.exco_innitiatives.models import (
    StrategicExcoOwner, StrategicThrust, StrategicInitiative, StrategicMilestone,
)

BASE = "/exco_innitiatives/"


def _seed():
    owner = StrategicExcoOwner.objects.create(
        owner_name="Alice", owner_division="Retail", owner_designation="GM",
        email="alice@hf.co.ke",
    )
    thrust = StrategicThrust.objects.create(
        thrust_name="Growth", thrust_description="Grow the book",
        thrust_start_date=date(2026, 1, 1), thrust_end_date=date(2026, 12, 31),
    )
    initiative = StrategicInitiative.objects.create(
        thrust=thrust, initiative_name="Deposits Drive", initiative_status="open",
        primary_owner="Alice", initiative_start_date=date(2026, 1, 1),
        initiative_end_date=date(2026, 6, 30),
    )
    StrategicMilestone.objects.create(
        thrust=thrust, initiative=initiative, milestone_name="Q1 target",
        milestone_description="hit Q1", milestone_status="open", review_status="Approved",
        proportion_contribution=0.5, proportion_complete=0.4, approved_proportion_complete=0.4,
    )
    return owner, thrust, initiative


class ExcoHierarchyApiTests(TestCase):
    def setUp(self):
        _seed()
        self.user = get_user_model().objects.create_user(username="exco", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_initiatives_path_is_strategic_hierarchy(self):
        resp = self.client.get(BASE + "initiatives/")
        self.assertEqual(resp.status_code, 200, resp.content)
        # Strategic initiative has initiative_name; the flat model does not.
        results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertTrue(any("initiative_name" in r for r in results))

    def test_initiative_milestones_subpath(self):
        init = StrategicInitiative.objects.first()
        resp = self.client.get(BASE + f"initiatives/{init.initiative_id}/milestones")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_all_summary_endpoints_run(self):
        for path in [
            "summary_of_thrust_by_initiatives/",
            "SummaryOfInitiativesByQuarters/",
            "SummaryInitiativesByPrimaryOwnership/",
            "SummaryInitiativesByPrimaryOwnershipPerThrust/",
            "SummaryInitiativesByPrimaryOwnershipPerThrustOverdue/",
            "SummaryInitiativesByPrimaryOwnershipPerThrustReview/",
            "SummaryAvgApprovedProportion/",
        ]:
            resp = self.client.get(BASE + path)
            self.assertEqual(resp.status_code, 200, f"{path} -> {resp.status_code}: {resp.content}")
            self.assertIsInstance(resp.data, list)

    def test_thrust_initiative_summary_counts(self):
        resp = self.client.get(BASE + "summary_of_thrust_by_initiatives/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data[0]["thrust_name"], "Growth")
        self.assertEqual(resp.data[0]["number_of_initiatives"], 1)

    def test_ownership_summary_shape(self):
        resp = self.client.get(BASE + "SummaryInitiativesByPrimaryOwnership/")
        self.assertEqual(resp.status_code, 200, resp.content)
        alice = next((r for r in resp.data if r["owner_name"] == "Alice"), None)
        self.assertIsNotNone(alice)
        self.assertEqual(alice["primary_owner_count"], 1)
