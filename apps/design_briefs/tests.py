"""The design board: the workflow, who may do what, and what archiving means.

Written against the behaviour somebody would notice rather than the
implementation. The rules worth protecting with a test are the ones the
department asked for in words: only the admin allocates work, a designer never
signs off their own work, rework is counted and needs a reason, and a closed
brief is archived rather than deleted.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APITestCase

from . import rbac, workflow
from .models import BriefEvent, DesignBrief

BASE = "/design_briefs/"


def user(username, group=None, email=None, superuser=False):
    u = get_user_model().objects.create_user(
        username=username, password="x", email=email or f"{username}@hf.test")
    if superuser:
        u.is_superuser = True
        u.is_staff = True
        u.save()
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


class BoardTestCase(APITestCase):
    def setUp(self):
        self.admin = user("dept_admin", rbac.ADMIN_GROUP)
        self.designer = user("grace_designer", rbac.DESIGNER_GROUP)
        self.other_designer = user("ken_designer", rbac.DESIGNER_GROUP)
        self.requester = user("mary_marketing")
        self.outsider = user("someone_else")

    def raise_brief(self, **kw):
        kw.setdefault("design_item", "Diaspora mortgage flyer")
        kw.setdefault("department", "Marketing")
        kw.setdefault("addressed_to", "Diaspora segment")
        kw.setdefault("raised_by", self.requester)
        return workflow.create(**kw)


class RaisingTests(BoardTestCase):
    def test_a_new_brief_starts_unassigned_and_awaiting_a_designer(self):
        brief = self.raise_brief()
        self.assertEqual(brief.status, DesignBrief.STATUS_NEW)
        self.assertIsNone(brief.assigned_designer_id)
        self.assertTrue(brief.reference.startswith("DB-"))

    def test_raising_writes_the_first_timeline_step(self):
        brief = self.raise_brief()
        events = list(brief.events.all())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, BriefEvent.KIND_RAISED)
        self.assertEqual(events[0].actor_id, self.requester.id)

    def test_the_requester_name_is_snapshotted_so_it_survives_the_account(self):
        self.requester.first_name, self.requester.last_name = "Mary", "Wanjiru"
        self.requester.save()
        brief = self.raise_brief()
        self.assertEqual(brief.raised_by_name, "Mary Wanjiru")
        self.requester.delete()
        brief.refresh_from_db()
        self.assertIsNone(brief.raised_by_id)
        self.assertEqual(brief.raised_by_name, "Mary Wanjiru")

    def test_anyone_signed_in_can_raise_one(self):
        self.client.force_authenticate(self.outsider)
        r = self.client.post(f"{BASE}briefs/", {
            "design_item": "Branch opening banner",
            "department": "Branch Network",
            "addressed_to": "Nakuru branch",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], DesignBrief.STATUS_NEW)

    def test_a_brief_needs_an_item_a_department_and_an_addressee(self):
        self.client.force_authenticate(self.requester)
        r = self.client.post(f"{BASE}briefs/", {"design_item": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        for field in ("design_item", "department", "addressed_to"):
            self.assertIn(field, r.data)


class AssignmentTests(BoardTestCase):
    def test_only_the_department_admin_assigns_a_designer(self):
        brief = self.raise_brief()
        self.client.force_authenticate(self.designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/assign/",
                             {"designer": self.designer.id}, format="json")
        self.assertEqual(r.status_code, 403)

        self.client.force_authenticate(self.admin)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/assign/",
                             {"designer": self.designer.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], DesignBrief.STATUS_ASSIGNED)
        self.assertEqual(r.data["assigned_designer"], self.designer.id)

    def test_reassigning_mid_flight_does_not_reset_progress(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.assign(brief, self.other_designer, actor=self.admin)
        brief.refresh_from_db()
        self.assertEqual(brief.status, DesignBrief.STATUS_IN_PROGRESS)
        self.assertEqual(brief.assigned_designer_id, self.other_designer.id)
        self.assertEqual(
            brief.events.filter(kind=BriefEvent.KIND_REASSIGNED).count(), 1)

    def test_assigning_the_same_designer_twice_writes_no_second_event(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        before = brief.events.count()
        workflow.assign(brief, self.designer, actor=self.admin)
        self.assertEqual(brief.events.count(), before)

    def test_work_cannot_start_before_a_designer_is_assigned(self):
        brief = self.raise_brief()
        with self.assertRaises(workflow.TransitionError):
            workflow.start(brief, actor=self.designer)


class ReworkTests(BoardTestCase):
    def submitted(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.submit(brief, actor=self.designer)
        return brief

    def test_rework_needs_a_reason(self):
        brief = self.submitted()
        with self.assertRaises(workflow.TransitionError):
            workflow.request_rework(brief, actor=self.requester, reason="  ")

    def test_rework_sends_it_back_and_is_counted(self):
        brief = self.submitted()
        workflow.request_rework(brief, actor=self.requester,
                                reason="Logo is the old brand mark.")
        brief.refresh_from_db()
        self.assertEqual(brief.status, DesignBrief.STATUS_REWORK)
        self.assertEqual(brief.rework_count, 1)
        self.assertTrue(brief.was_reworked)
        self.assertIn("old brand mark", brief.last_rework_reason)

    def test_the_count_survives_more_than_one_round(self):
        brief = self.submitted()
        for n in range(1, 4):
            workflow.request_rework(brief, actor=self.requester, reason=f"round {n}")
            workflow.submit(brief, actor=self.designer)
        brief.refresh_from_db()
        self.assertEqual(brief.rework_count, 3)

    def test_rework_cannot_be_requested_before_it_is_submitted(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        with self.assertRaises(workflow.TransitionError):
            workflow.request_rework(brief, actor=self.requester, reason="no")

    def test_only_the_requester_or_the_admin_sends_it_back(self):
        brief = self.submitted()
        self.client.force_authenticate(self.other_designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/rework/",
                             {"reason": "I would do it differently"}, format="json")
        self.assertEqual(r.status_code, 403)


class ApprovalTests(BoardTestCase):
    def submitted(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.submit(brief, actor=self.designer)
        return brief

    def test_the_designer_cannot_approve_their_own_work(self):
        """The rule the board exists for. Refused even for an admin designer."""
        brief = self.submitted()
        with self.assertRaises(workflow.TransitionError):
            workflow.approve(brief, actor=self.designer)

        self.designer.groups.add(
            Group.objects.get_or_create(name=rbac.ADMIN_GROUP)[0])
        with self.assertRaises(workflow.TransitionError):
            workflow.approve(brief, actor=self.designer)

    def test_approval_closes_and_archives_but_never_deletes(self):
        brief = self.submitted()
        workflow.approve(brief, actor=self.requester, satisfaction=5,
                         note="Exactly right.")
        brief.refresh_from_db()
        self.assertEqual(brief.status, DesignBrief.STATUS_APPROVED)
        self.assertTrue(brief.is_closed)
        self.assertTrue(brief.is_archived)
        self.assertIsNotNone(brief.archived_at)
        # Still there, which is the whole point.
        self.assertTrue(DesignBrief.objects.filter(pk=brief.pk).exists())
        self.assertEqual(DesignBrief.objects.closed().count(), 1)
        self.assertEqual(DesignBrief.objects.open().count(), 0)

    def test_satisfaction_must_be_one_to_five(self):
        brief = self.submitted()
        with self.assertRaises(workflow.TransitionError):
            workflow.approve(brief, actor=self.requester, satisfaction=9)

    def test_an_unsubmitted_brief_cannot_be_approved(self):
        brief = self.raise_brief()
        with self.assertRaises(workflow.TransitionError):
            workflow.approve(brief, actor=self.requester)


class ArchiveTests(BoardTestCase):
    def closed_brief(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.submit(brief, actor=self.designer)
        workflow.approve(brief, actor=self.requester)
        return brief

    def test_the_open_and_closed_views_are_separate(self):
        self.closed_brief()
        open_one = self.raise_brief(design_item="Q4 campaign poster")
        self.client.force_authenticate(self.admin)

        r = self.client.get(f"{BASE}briefs/?view=open")
        self.assertEqual([b["reference"] for b in r.data["results"]],
                         [open_one.reference])

        r = self.client.get(f"{BASE}briefs/?view=closed")
        self.assertEqual(len(r.data["results"]), 1)

        r = self.client.get(f"{BASE}briefs/?view=all")
        self.assertEqual(len(r.data["results"]), 2)

    def test_only_the_admin_reopens_an_archived_brief(self):
        brief = self.closed_brief()
        self.client.force_authenticate(self.requester)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/reopen/",
                             {"reason": "Needs a Swahili version"}, format="json")
        self.assertEqual(r.status_code, 403)

        self.client.force_authenticate(self.admin)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/reopen/",
                             {"reason": "Needs a Swahili version"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], DesignBrief.STATUS_REWORK)
        self.assertIsNone(r.data["archived_at"])
        self.assertEqual(r.data["rework_count"], 1)

    def test_reopening_an_open_brief_is_refused(self):
        brief = self.raise_brief()
        with self.assertRaises(workflow.TransitionError):
            workflow.reopen(brief, actor=self.admin, reason="why not")

    def test_a_cancelled_brief_is_archived_not_deleted_and_not_an_approval(self):
        brief = self.raise_brief()
        workflow.cancel(brief, actor=self.requester, reason="Campaign dropped")
        brief.refresh_from_db()
        self.assertEqual(brief.status, DesignBrief.STATUS_CANCELLED)
        self.assertTrue(brief.is_archived)
        self.assertTrue(DesignBrief.objects.filter(pk=brief.pk).exists())
        self.assertEqual(
            DesignBrief.objects.filter(status=DesignBrief.STATUS_APPROVED).count(), 0)


class VisibilityTests(BoardTestCase):
    def test_the_design_team_sees_the_whole_board(self):
        self.raise_brief()
        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}briefs/")
        self.assertEqual(r.data["count"], 1)

    def test_an_unrelated_person_does_not_see_somebody_elses_brief(self):
        self.raise_brief()
        self.client.force_authenticate(self.outsider)
        r = self.client.get(f"{BASE}briefs/")
        self.assertEqual(r.data["count"], 0)

    def test_a_brief_you_may_not_see_is_a_404_not_a_403(self):
        """A 403 would confirm the reference exists, which is enough to probe."""
        brief = self.raise_brief()
        self.client.force_authenticate(self.outsider)
        r = self.client.get(f"{BASE}briefs/{brief.reference}/")
        self.assertEqual(r.status_code, 404)

    def test_the_requester_sees_their_own(self):
        self.raise_brief()
        self.client.force_authenticate(self.requester)
        r = self.client.get(f"{BASE}briefs/")
        self.assertEqual(r.data["count"], 1)


class EditingTests(BoardTestCase):
    def test_the_requester_may_edit_until_work_has_started(self):
        brief = self.raise_brief()
        self.client.force_authenticate(self.requester)
        r = self.client.patch(f"{BASE}briefs/{brief.reference}/",
                              {"design_item": "Diaspora mortgage flyer v2"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)

        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        r = self.client.patch(f"{BASE}briefs/{brief.reference}/",
                              {"design_item": "Something else entirely"},
                              format="json")
        self.assertEqual(r.status_code, 403)

    def test_an_edit_is_recorded_with_what_changed(self):
        brief = self.raise_brief()
        self.client.force_authenticate(self.requester)
        self.client.patch(f"{BASE}briefs/{brief.reference}/",
                          {"priority": DesignBrief.PRIORITY_URGENT}, format="json")
        event = brief.events.filter(kind=BriefEvent.KIND_EDITED).first()
        self.assertIsNotNone(event)
        self.assertIn("priority", event.note)

    def test_status_cannot_be_set_through_a_patch(self):
        """Every transition has to leave a step behind it. A PATCH leaves none."""
        brief = self.raise_brief()
        self.client.force_authenticate(self.admin)
        self.client.patch(f"{BASE}briefs/{brief.reference}/",
                          {"status": DesignBrief.STATUS_APPROVED}, format="json")
        brief.refresh_from_db()
        self.assertEqual(brief.status, DesignBrief.STATUS_NEW)


class ReleaseDateTests(BoardTestCase):
    def test_days_to_release_is_none_without_a_date_not_zero(self):
        brief = self.raise_brief()
        self.assertIsNone(brief.days_to_release)
        self.assertFalse(brief.is_overdue)

    def test_a_passed_release_date_is_overdue_until_it_closes(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        brief = self.raise_brief(release_date=yesterday)
        self.assertEqual(brief.days_to_release, -1)
        self.assertTrue(brief.is_overdue)

        workflow.cancel(brief, actor=self.requester, reason="dropped")
        brief.refresh_from_db()
        self.assertFalse(brief.is_overdue)

    def test_overdue_queryset_excludes_closed_and_undated(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.raise_brief(release_date=yesterday)
        self.raise_brief(design_item="No date", release_date=None)
        closed = self.raise_brief(design_item="Done", release_date=yesterday)
        workflow.cancel(closed, actor=self.requester, reason="dropped")
        self.assertEqual(DesignBrief.objects.overdue().count(), 1)


class BoardScreenTests(BoardTestCase):
    def test_the_board_groups_by_status_and_by_designer(self):
        a = self.raise_brief(design_item="Poster A")
        workflow.assign(a, self.designer, actor=self.admin)
        workflow.start(a, actor=self.designer)
        self.raise_brief(design_item="Poster B")  # left unassigned

        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}board/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["counts"]["open"], 2)
        self.assertEqual(r.data["counts"]["unassigned"], 1)
        self.assertEqual(r.data["counts"]["in_progress"], 1)

        statuses = {c["status"]: c["total"] for c in r.data["columns"]}
        self.assertEqual(statuses[DesignBrief.STATUS_NEW], 1)
        self.assertEqual(statuses[DesignBrief.STATUS_IN_PROGRESS], 1)

        lanes = {p["designer"]: p["total"] for p in r.data["pipelines"]}
        self.assertEqual(lanes["Unassigned"], 1)
        self.assertEqual(lanes[self.designer.username], 1)

    def test_the_unassigned_lane_sorts_last(self):
        a = self.raise_brief(design_item="A")
        workflow.assign(a, self.designer, actor=self.admin)
        self.raise_brief(design_item="B")
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"{BASE}board/")
        self.assertEqual(r.data["pipelines"][-1]["designer"], "Unassigned")

    def test_a_capped_lane_still_reports_the_true_total(self):
        """The display caps rows; it must not understate the pipeline."""
        for n in range(5):
            b = self.raise_brief(design_item=f"Item {n}")
            workflow.assign(b, self.designer, actor=self.admin)
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"{BASE}board/?limit=2")
        lane = next(p for p in r.data["pipelines"]
                    if p["designer_id"] == self.designer.id)
        self.assertEqual(lane["total"], 5)
        self.assertEqual(len(lane["briefs"]), 2)

    def test_my_pipeline_separates_my_work_from_my_requests(self):
        mine = self.raise_brief(design_item="Mine to make")
        workflow.assign(mine, self.designer, actor=self.admin)
        self.raise_brief(design_item="I asked for this")

        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}my-pipeline/")
        self.assertEqual(r.data["counts"]["assigned_to_me"], 1)
        self.assertEqual(r.data["counts"]["raised_by_me"], 0)

        self.client.force_authenticate(self.requester)
        r = self.client.get(f"{BASE}my-pipeline/")
        self.assertEqual(r.data["counts"]["assigned_to_me"], 0)
        self.assertEqual(r.data["counts"]["raised_by_me"], 2)

    def test_my_pipeline_flags_what_is_waiting_on_my_review(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.submit(brief, actor=self.designer)
        self.client.force_authenticate(self.requester)
        r = self.client.get(f"{BASE}my-pipeline/")
        self.assertEqual(r.data["counts"]["waiting_on_my_review"], 1)


class MetaAndSummaryTests(BoardTestCase):
    def test_meta_reports_the_callers_role(self):
        for who, expected in ((self.admin, "admin"),
                              (self.designer, "designer"),
                              (self.outsider, "requester")):
            self.client.force_authenticate(who)
            r = self.client.get(f"{BASE}meta/")
            self.assertEqual(r.data["role"], expected)

    def test_the_designer_dropdown_lists_the_design_team(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"{BASE}designers/")
        self.assertEqual({p["id"] for p in r.data},
                         {self.designer.id, self.other_designer.id})

    def test_summary_is_admin_only(self):
        self.client.force_authenticate(self.designer)
        self.assertEqual(self.client.get(f"{BASE}summary/").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(f"{BASE}summary/").status_code, 200)

    def test_summary_counts_the_archive_too(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.submit(brief, actor=self.designer)
        workflow.request_rework(brief, actor=self.requester, reason="colour")
        workflow.submit(brief, actor=self.designer)
        workflow.approve(brief, actor=self.requester, satisfaction=4)

        self.client.force_authenticate(self.admin)
        r = self.client.get(f"{BASE}summary/?view=all")
        self.assertEqual(r.data["totals"]["briefs"], 1)
        self.assertEqual(r.data["totals"]["approved"], 1)
        self.assertEqual(r.data["totals"]["reworked"], 1)
        self.assertEqual(r.data["totals"]["rework_events"], 1)
        self.assertEqual(r.data["totals"]["avg_satisfaction"], 4.0)
