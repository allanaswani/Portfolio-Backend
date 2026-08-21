"""Tests for the Referral module: validation, RBAC scoping, allocation, retention."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Referral
from .rbac import AGENT_GROUP, SUPERVISOR_GROUP

User = get_user_model()


def make_user(username, group=None, **kw):
    user = User.objects.create_user(username=username, password="x", **kw)
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


class ReferralValidationTests(APITestCase):
    def setUp(self):
        self.capturer = make_user("branch_staff")
        self.client.force_authenticate(self.capturer)

    def _payload(self, **over):
        base = {
            "pf_number": "12345",
            "sales_code": "SC001",
            "customer_name": "Jane Wanjiru",
            "national_id": "29384756",
            "phone": "0712345678",
            "email": "jane@example.com",
        }
        base.update(over)
        return base

    def test_create_normalises_phone_and_sets_creator(self):
        res = self.client.post("/referrals/", self._payload(), format="json")
        self.assertEqual(res.status_code, 201, res.content)
        ref = Referral.objects.get(referral_ref=res.data["referral_ref"])
        self.assertEqual(ref.phone, "+254712345678")   # normalised
        self.assertEqual(ref.created_by, self.capturer)  # auto-captured
        self.assertEqual(ref.status, Referral.STATUS_UNALLOCATED)
        self.assertTrue(ref.referral_ref.startswith("RF-"))
        # Empty staff roster locally → cannot verify (None), not a hard fail.
        self.assertIsNone(ref.staff_verified)

    def test_rejects_bad_phone(self):
        res = self.client.post("/referrals/", self._payload(phone="12345"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("phone", res.data)

    def test_rejects_non_numeric_national_id(self):
        res = self.client.post("/referrals/", self._payload(national_id="AB12"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("national_id", res.data)

    def test_duplicate_national_id_is_flagged_not_blocked(self):
        self.client.post("/referrals/", self._payload(), format="json")
        res = self.client.post(
            "/referrals/", self._payload(customer_name="Jane Again", phone="0722000000"),
            format="json",
        )
        self.assertEqual(res.status_code, 201)   # not blocked
        self.assertTrue(res.data["is_possible_duplicate"])  # but flagged

    def test_status_and_assignment_are_read_only_on_create(self):
        other = make_user("someone_else")
        res = self.client.post(
            "/referrals/",
            self._payload(status="converted", assigned_to=other.id),
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        ref = Referral.objects.get(pk=res.data["id"])
        self.assertEqual(ref.status, Referral.STATUS_UNALLOCATED)  # ignored
        self.assertIsNone(ref.assigned_to)                          # ignored


class ReferralScopingTests(APITestCase):
    def setUp(self):
        self.supervisor = make_user("super", group=SUPERVISOR_GROUP)
        self.agent = make_user("agent", group=AGENT_GROUP)
        self.capturer = make_user("capturer")

        self.own = Referral.objects.create(
            pf_number="1", customer_name="A", national_id="111111",
            phone="+254712000001", created_by=self.capturer,
        )
        self.allocated = Referral.objects.create(
            pf_number="2", customer_name="B", national_id="222222",
            phone="+254712000002", created_by=self.supervisor, assigned_to=self.agent,
            status=Referral.STATUS_ALLOCATED,
        )
        self.other = Referral.objects.create(
            pf_number="3", customer_name="C", national_id="333333",
            phone="+254712000003", created_by=self.supervisor,
        )

    def _ids(self, user):
        self.client.force_authenticate(user)
        res = self.client.get("/referrals/")
        self.assertEqual(res.status_code, 200)
        return {r["id"] for r in res.data["results"]}

    def test_supervisor_sees_all(self):
        self.assertEqual(self._ids(self.supervisor),
                         {self.own.id, self.allocated.id, self.other.id})

    def test_agent_sees_only_allocated(self):
        self.assertEqual(self._ids(self.agent), {self.allocated.id})

    def test_capturer_sees_only_own(self):
        self.assertEqual(self._ids(self.capturer), {self.own.id})


class ReferralAllocationTests(APITestCase):
    def setUp(self):
        self.supervisor = make_user("super", group=SUPERVISOR_GROUP)
        self.agent = make_user("agent", group=AGENT_GROUP)
        self.capturer = make_user("capturer")
        self.ref = Referral.objects.create(
            pf_number="1", customer_name="A", national_id="111111",
            phone="+254712000001", created_by=self.capturer,
        )

    def test_supervisor_can_allocate(self):
        self.client.force_authenticate(self.supervisor)
        res = self.client.post(
            f"/referrals/{self.ref.id}/allocate/",
            {"assigned_to": self.agent.id}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.assigned_to, self.agent)
        self.assertEqual(self.ref.allocated_by, self.supervisor)
        self.assertIsNotNone(self.ref.allocated_at)
        self.assertEqual(self.ref.status, Referral.STATUS_ALLOCATED)

    def test_capturer_cannot_allocate(self):
        self.client.force_authenticate(self.capturer)
        res = self.client.post(
            f"/referrals/{self.ref.id}/allocate/",
            {"assigned_to": self.agent.id}, format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_can_allocate_to_an_rm_outside_the_telesales_groups(self):
        """RMs and branch sales staff hold no telesales group but do work
        referrals, so any active account is a valid assignee."""
        from apps.portfolio.models import Profile

        rm = make_user("rm_jane", first_name="Jane")
        Profile.objects.update_or_create(user=rm, defaults={"sales_code": "3914"})
        self.client.force_authenticate(self.supervisor)
        res = self.client.post(
            f"/referrals/{self.ref.id}/allocate/",
            {"assigned_to": rm.id}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.assigned_to, rm)
        # The assignee's sales code is snapshotted onto the referral.
        self.assertEqual(self.ref.assigned_sales_code, "3914")
        self.assertEqual(res.data["assigned_to_sales_code"], "3914")

    def test_cannot_allocate_to_an_inactive_user(self):
        outsider = make_user("outsider", is_active=False)
        self.client.force_authenticate(self.supervisor)
        res = self.client.post(
            f"/referrals/{self.ref.id}/allocate/",
            {"assigned_to": outsider.id}, format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_allocation_roster_includes_non_telesales_staff(self):
        from apps.portfolio.models import Profile

        rm = make_user("rm_peter", first_name="Peter")
        Profile.objects.update_or_create(user=rm, defaults={"sales_code": "3950"})
        self.client.force_authenticate(self.supervisor)
        res = self.client.get("/referrals/telesales-agents/")
        self.assertEqual(res.status_code, 200, res.content)
        by_id = {r["id"]: r for r in res.data}
        self.assertIn(rm.id, by_id)
        self.assertEqual(by_id[rm.id]["sales_code"], "3950")

    def test_assignee_sees_the_referral_allocated_to_them(self):
        rm = make_user("rm_alice")
        self.ref.assigned_to = rm
        self.ref.status = Referral.STATUS_ALLOCATED
        self.ref.save()
        self.client.force_authenticate(rm)
        res = self.client.get("/referrals/")
        self.assertEqual(res.status_code, 200, res.content)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual([r["id"] for r in rows], [self.ref.id])


    def test_agent_updates_status_and_stamps_converted(self):
        self.ref.assigned_to = self.agent
        self.ref.status = Referral.STATUS_ALLOCATED
        self.ref.save()
        self.client.force_authenticate(self.agent)
        res = self.client.post(
            f"/referrals/{self.ref.id}/status/",
            {"status": "converted"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.status, Referral.STATUS_CONVERTED)
        self.assertIsNotNone(self.ref.converted_at)

    def test_agent_cannot_update_someone_elses_referral(self):
        other_agent = make_user("agent2", group=AGENT_GROUP)
        self.ref.assigned_to = other_agent
        self.ref.save()
        self.client.force_authenticate(self.agent)
        res = self.client.post(
            f"/referrals/{self.ref.id}/status/",
            {"status": "contacted"}, format="json",
        )
        self.assertEqual(res.status_code, 403)


class ReferralDeletionTests(APITestCase):
    def setUp(self):
        self.supervisor = make_user("sup2", group=SUPERVISOR_GROUP)
        self.superuser = make_user("root", is_superuser=True, is_staff=True)
        self.agent = make_user("agent2", group=AGENT_GROUP)
        self.ref = Referral.objects.create(
            pf_number="12345", customer_name="Test Row",
            national_id="12345678", phone="+254712345678",
        )

    def test_superuser_can_delete(self):
        self.client.force_authenticate(self.superuser)
        res = self.client.delete(f"/referrals/{self.ref.id}/")
        self.assertEqual(res.status_code, 204, res.content)
        self.assertFalse(Referral.objects.filter(pk=self.ref.pk).exists())

    def test_supervisor_cannot_delete(self):
        self.client.force_authenticate(self.supervisor)
        res = self.client.delete(f"/referrals/{self.ref.id}/")
        self.assertEqual(res.status_code, 403, res.content)
        self.assertTrue(Referral.objects.filter(pk=self.ref.pk).exists())

    def test_rejecting_a_referral_removes_it(self):
        self.ref.assigned_to = self.agent
        self.ref.status = Referral.STATUS_ALLOCATED
        self.ref.save()
        self.client.force_authenticate(self.agent)
        res = self.client.post(
            f"/referrals/{self.ref.id}/status/",
            {"status": "rejected", "notes": "not interested"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.data["deleted"])
        self.assertFalse(Referral.objects.filter(pk=self.ref.pk).exists())
        # The rejection and its notes survive in the history table for audit.
        hist = Referral.history.filter(id=self.ref.pk).order_by("history_date")
        self.assertEqual(hist.last().history_type, "-")
        self.assertIn("rejected", {h.status for h in hist})
        self.assertIn("not interested", {h.notes for h in hist})

class ReferralRetentionTests(APITestCase):
    def _aged(self, days, **over):
        ref = Referral.objects.create(
            pf_number="1", customer_name="A", national_id="111111",
            phone="+254712000001", **over,
        )
        # created_at is auto_now_add — backdate it directly.
        Referral.objects.filter(pk=ref.pk).update(
            created_at=timezone.now() - timedelta(days=days)
        )
        return ref

    def test_purges_stale_unconverted_keeps_fresh(self):
        stale = self._aged(120)                       # >90d, unconverted → purge
        fresh = self._aged(10)                        # recent → keep
        call_command("expire_referrals")
        self.assertFalse(Referral.objects.filter(pk=stale.pk).exists())
        self.assertTrue(Referral.objects.filter(pk=fresh.pk).exists())

    def test_keeps_recently_converted_purges_old_converted(self):
        recent_conv = self._aged(
            120, status=Referral.STATUS_CONVERTED, converted_at=timezone.now() - timedelta(days=30)
        )
        old_conv = self._aged(
            400, status=Referral.STATUS_CONVERTED, converted_at=timezone.now() - timedelta(days=400)
        )
        call_command("expire_referrals")
        self.assertTrue(Referral.objects.filter(pk=recent_conv.pk).exists())
        self.assertFalse(Referral.objects.filter(pk=old_conv.pk).exists())

    def test_dry_run_changes_nothing(self):
        stale = self._aged(120)
        call_command("expire_referrals", "--dry-run")
        self.assertTrue(Referral.objects.filter(pk=stale.pk).exists())
