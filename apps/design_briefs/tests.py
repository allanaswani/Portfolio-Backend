"""The design board: the workflow, who may do what, and what archiving means.

Written against the behaviour somebody would notice rather than the
implementation. The rules worth protecting with a test are the ones the
department asked for in words: only the admin allocates work, a designer never
signs off their own work, rework is counted and needs a reason, and a closed
brief is archived rather than deleted.
"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.utils import timezone
from rest_framework.test import APITestCase

from . import images, notifications, rbac, workflow
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

    def test_a_designer_cannot_send_back_somebody_elses_brief(self):
        brief = self.submitted()
        self.client.force_authenticate(self.other_designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/rework/",
                             {"reason": "I would do it differently"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_raising_department_can_send_it_back_not_just_the_raiser(self):
        """The requirement says "the person who raised it OR the department".

        A brief raised by somebody on leave must not sit in review until they
        are back, so a colleague in the same department can judge it.
        """
        colleague = user("mary_colleague", email="colleague@hf.test")
        brief = self.submitted()
        with mock.patch.object(rbac, "department_of", return_value="Marketing"):
            self.client.force_authenticate(colleague)
            r = self.client.post(f"{BASE}briefs/{brief.reference}/rework/",
                                 {"reason": "Wrong brand mark"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], DesignBrief.STATUS_REWORK)
        self.assertEqual(r.data["rework_count"], 1)

    def test_a_different_departments_colleague_still_cannot(self):
        outsider = user("finance_person", email="finance@hf.test")
        brief = self.submitted()
        with mock.patch.object(rbac, "department_of", return_value="Finance"):
            self.client.force_authenticate(outsider)
            r = self.client.post(f"{BASE}briefs/{brief.reference}/rework/",
                                 {"reason": "no"}, format="json")
        # Not even visible to them, so 404 rather than 403 - see VisibilityTests.
        self.assertEqual(r.status_code, 404)

    def test_the_department_spelling_does_not_have_to_match_exactly(self):
        """employee_table.department holds 57 spellings for far fewer real
        departments, so 'MARKETING DEPT' must match 'Marketing'."""
        colleague = user("spelling_colleague", email="spell@hf.test")
        brief = self.submitted()
        with mock.patch.object(rbac, "department_of", return_value="MARKETING DEPARTMENT"):
            self.client.force_authenticate(colleague)
            r = self.client.post(f"{BASE}briefs/{brief.reference}/rework/",
                                 {"reason": "colour is off"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)


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


def png_bytes(w=2400, h=1600, mode="RGB"):
    """A realistic image: big, and smooth rather than flat or noisy.

    Built small and upscaled, which is fast and gives low-frequency content -
    what a real layout looks like to a compressor. Both a flat colour and a
    high-frequency pattern are traps here: PNG stores either far better than
    JPEG does, so a synthetic "original" can be smaller than its own
    downscaled preview.
    """
    import io as _io

    from PIL import Image

    small = Image.new(mode, (24, 16))
    px = small.load()
    for y in range(16):
        for x in range(24):
            v = int(255 * (x / 23))
            colour = (v, 150, 255 - v)
            px[x, y] = colour if mode == "RGB" else colour + (255,)
    img = small.resize((w, h), Image.BICUBIC)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload(name="proof.png", **kw):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, png_bytes(**kw), content_type="image/png")


class ProofTests(BoardTestCase):
    """The artwork. A design board whose cards show no design is a to-do list."""

    def assigned(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        return brief

    def test_the_original_bytes_are_never_stored(self):
        """The container has no volume and /data is 90% full. Only the
        downscaled preview and thumbnail are kept."""
        brief = self.assigned()
        raw = png_bytes()
        prepared = images.prepare(raw, "flyer.png")
        proof = workflow.add_proof(brief, prepared=prepared, uploaded_by=self.designer)

        # What was uploaded is recorded, so the row is honest about it.
        self.assertEqual(proof.original_bytes, len(raw))

        # The actual guarantees. Deliberately NOT "the preview is smaller than
        # the upload": that depends on the image, not on this code - PNG beats
        # JPEG on flat colour and on noise alike, so a synthetic original can
        # be smaller than its own downscale. The invariants are the dimension
        # cap and a stored size the database can carry.
        self.assertLessEqual(max(proof.width, proof.height), images.PREVIEW_EDGE)
        self.assertLess(len(bytes(proof.thumbnail)), len(bytes(proof.preview)))
        self.assertLess(len(bytes(proof.preview)), 2_000_000,
                        "a stored preview must stay small enough for the database")

        # And the model has nowhere to put the original at all, which is the
        # point: /data is 90% full and the container has no volume.
        fields = {f.name for f in proof._meta.get_fields()}
        self.assertNotIn("original", fields)
        self.assertNotIn("file", fields)

    def test_versions_increment_and_are_never_overwritten(self):
        brief = self.assigned()
        for _ in range(3):
            workflow.add_proof(brief, prepared=images.prepare(png_bytes()),
                               uploaded_by=self.designer)
        self.assertEqual(
            list(brief.proofs.order_by("version").values_list("version", flat=True)),
            [1, 2, 3])

    def test_a_designer_uploads_and_hands_over_in_one_step(self):
        brief = self.assigned()
        self.client.force_authenticate(self.designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/proofs/",
                             {"file": upload(), "submit": "true",
                              "note": "First pass"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], DesignBrief.STATUS_SUBMITTED)
        self.assertEqual(r.data["proof_version"], 1)
        self.assertEqual(len(r.data["proofs"]), 1)

    def test_only_the_assigned_designer_can_upload(self):
        brief = self.assigned()
        self.client.force_authenticate(self.other_designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/proofs/",
                             {"file": upload()}, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_a_non_image_is_refused_with_a_usable_message(self):
        brief = self.assigned()
        with self.assertRaises(images.ProofImageError) as ctx:
            images.prepare(b"this is not an image at all", "notes.txt")
        self.assertIn("not an image", str(ctx.exception))

    def test_an_oversized_file_is_refused_before_pillow_opens_it(self):
        with self.assertRaises(images.ProofImageError) as ctx:
            images.prepare(b"x" * (images.MAX_UPLOAD_BYTES + 1), "huge.png")
        self.assertIn("MB", str(ctx.exception))

    def test_transparency_is_kept_as_png_not_flattened(self):
        """Flattening a logo's alpha onto white changes the artwork under review."""
        prepared = images.prepare(png_bytes(mode="RGBA"), "logo.png")
        self.assertEqual(prepared["preview_content_type"], "image/png")

    def test_a_link_only_proof_is_allowed_for_print_and_video(self):
        """A 400 MB print PDF belongs behind a link, not in the database."""
        brief = self.assigned()
        self.client.force_authenticate(self.designer)
        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/proofs/",
            {"source_url": "https://hfgroup.sharepoint.com/flyer-print.pdf"},
            format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["proofs"][0]["source_url"],
                         "https://hfgroup.sharepoint.com/flyer-print.pdf")

    def test_an_empty_upload_with_no_link_is_refused(self):
        brief = self.assigned()
        self.client.force_authenticate(self.designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/proofs/", {},
                             format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_the_image_endpoint_serves_bytes_and_refuses_outsiders(self):
        brief = self.assigned()
        proof = workflow.add_proof(brief, prepared=images.prepare(png_bytes()),
                                   uploaded_by=self.designer)

        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}proofs/{proof.pk}/thumb/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("image/"))
        self.assertIn("private", r["Cache-Control"])

        self.client.force_authenticate(self.outsider)
        self.assertEqual(
            self.client.get(f"{BASE}proofs/{proof.pk}/thumb/").status_code, 404)

    def test_the_card_carries_the_newest_version_only(self):
        brief = self.assigned()
        workflow.add_proof(brief, prepared=images.prepare(png_bytes()),
                           uploaded_by=self.designer)
        newest = workflow.add_proof(brief, prepared=images.prepare(png_bytes()),
                                    uploaded_by=self.designer)
        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}briefs/")
        row = r.data["results"][0]
        self.assertEqual(row["proof_version"], 2)
        self.assertIn(str(newest.pk), row["thumbnail_url"])

    def test_a_board_row_without_artwork_says_so_rather_than_erroring(self):
        self.raise_brief()
        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}briefs/")
        row = r.data["results"][0]
        self.assertIsNone(row["thumbnail_url"])
        self.assertIsNone(row["proof_version"])


class CommentTests(BoardTestCase):
    def test_anyone_who_can_see_the_brief_can_comment(self):
        brief = self.raise_brief()
        self.client.force_authenticate(self.designer)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/comments/",
                             {"body": "Which logo lockup?"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["body"], "Which logo lockup?")

    def test_an_outsider_cannot(self):
        brief = self.raise_brief()
        self.client.force_authenticate(self.outsider)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/comments/",
                             {"body": "hello"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_a_comment_can_be_pinned_to_one_version(self):
        """Feedback on v1 must still read correctly once v2 lands."""
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        proof = workflow.add_proof(brief, prepared=images.prepare(png_bytes()),
                                   uploaded_by=self.designer)
        self.client.force_authenticate(self.requester)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/comments/",
                             {"body": "Logo too small", "proof": proof.pk},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["proof_version"], 1)

    def test_an_empty_comment_is_refused(self):
        brief = self.raise_brief()
        self.client.force_authenticate(self.requester)
        r = self.client.post(f"{BASE}briefs/{brief.reference}/comments/",
                             {"body": "   "}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_comments_are_separate_from_the_event_timeline(self):
        brief = self.raise_brief()
        workflow.add_comment(brief, author=self.requester, body="Note this")
        self.assertEqual(brief.comments.count(), 1)
        # An event is still written, so the history shows a conversation happened.
        self.assertEqual(
            brief.events.filter(kind=BriefEvent.KIND_COMMENT).count(), 1)


class DeliverableTests(BoardTestCase):
    def test_the_requester_sets_the_checklist_and_the_designer_ticks_it(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)

        self.client.force_authenticate(self.requester)
        r = self.client.put(f"{BASE}briefs/{brief.reference}/deliverables/",
                            {"labels": ["Instagram square", "Story 9:16", "A4 print"]},
                            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([d["label"] for d in r.data],
                         ["Instagram square", "Story 9:16", "A4 print"])

        item = brief.deliverables.first()
        self.client.force_authenticate(self.designer)
        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/deliverables/{item.pk}/tick/",
            {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["done"])

    def test_adding_a_line_does_not_untick_finished_work(self):
        brief = self.raise_brief()
        workflow.set_deliverables(brief, ["Instagram square", "A4 print"])
        first = brief.deliverables.get(label="Instagram square")
        workflow.tick_deliverable(first, actor=self.designer)

        workflow.set_deliverables(
            brief, ["Instagram square", "A4 print", "Email header"])
        again = brief.deliverables.get(label="Instagram square")
        self.assertTrue(again.done, "a tick was lost when a line was added")
        self.assertEqual(brief.deliverables.count(), 3)

    def test_the_designer_cannot_rewrite_the_list(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        self.client.force_authenticate(self.designer)
        r = self.client.put(f"{BASE}briefs/{brief.reference}/deliverables/",
                            {"labels": ["Just the one I feel like"]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_progress_is_on_the_board_row(self):
        brief = self.raise_brief()
        workflow.set_deliverables(brief, ["a", "b", "c", "d"])
        workflow.tick_deliverable(brief.deliverables.first(), actor=self.designer)
        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}briefs/")
        row = r.data["results"][0]
        self.assertEqual(row["deliverables_total"], 4)
        self.assertEqual(row["deliverables_done"], 1)

    def test_too_many_deliverables_is_refused(self):
        brief = self.raise_brief()
        with self.assertRaises(workflow.TransitionError):
            workflow.set_deliverables(brief, [f"item {i}" for i in range(40)])


class CalendarTests(BoardTestCase):
    def test_briefs_land_on_their_release_date(self):
        today = timezone.localdate()
        self.raise_brief(design_item="On a date", release_date=today)
        self.raise_brief(design_item="No date at all", release_date=None)

        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}calendar/?month={today:%Y-%m}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["total"], 1)
        self.assertEqual(len(r.data["days"]), 1)
        self.assertEqual(r.data["days"][0]["briefs"][0]["design_item"], "On a date")

    def test_undated_briefs_are_reported_separately_not_hidden(self):
        self.raise_brief(design_item="No date at all", release_date=None)
        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}calendar/")
        self.assertEqual(r.data["total"], 0)
        self.assertEqual(len(r.data["undated"]), 1)

    def test_a_nonsense_month_falls_back_to_this_one_rather_than_erroring(self):
        self.client.force_authenticate(self.designer)
        for bad in ("", "banana", "2026-13", "1066-01", "2026"):
            r = self.client.get(f"{BASE}calendar/?month={bad}")
            self.assertEqual(r.status_code, 200, bad)
            self.assertEqual(r.data["month"], f"{timezone.localdate():%Y-%m}")

    def test_the_calendar_is_scoped_like_everything_else(self):
        self.raise_brief(release_date=timezone.localdate())
        self.client.force_authenticate(self.outsider)
        r = self.client.get(f"{BASE}calendar/")
        self.assertEqual(r.data["total"], 0)


class MailTests(BoardTestCase):
    """Who hears about a transition, and that mail can never break one.

    Every send is queued on ``transaction.on_commit``, so these use
    ``captureOnCommitCallbacks`` - without it the callbacks never fire inside a
    test's transaction and every one of these would pass vacuously.
    """

    def setUp(self):
        super().setUp()
        mail.outbox = []

    def submitted_brief(self):
        brief = self.raise_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.assign(brief, self.designer, actor=self.admin)
            workflow.start(brief, actor=self.designer)
            workflow.submit(brief, actor=self.designer)
        mail.outbox = []
        return brief

    def test_assigning_mails_the_designer_and_not_the_admin_who_did_it(self):
        brief = self.raise_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.assign(brief, self.designer, actor=self.admin)

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, [self.designer.email])
        self.assertNotIn(self.admin.email, msg.to)
        self.assertIn(brief.design_item, msg.subject)
        self.assertIn(brief.reference, msg.body)

    def test_submitting_mails_the_requester_not_the_designer(self):
        brief = self.raise_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.assign(brief, self.designer, actor=self.admin)
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            workflow.submit(brief, actor=self.designer)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.requester.email])

    def test_rework_mail_carries_the_reason_or_it_is_useless(self):
        brief = self.submitted_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.request_rework(brief, actor=self.requester,
                                    reason="Logo is the old brand mark")

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, [self.designer.email])
        self.assertIn("Logo is the old brand mark", msg.body)
        self.assertIn("Logo is the old brand mark", msg.alternatives[0][0])

    def test_approval_mails_the_designer_whose_work_it_was(self):
        brief = self.submitted_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.approve(brief, actor=self.requester, satisfaction=5)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.designer.email])

    def test_nobody_is_copied_on_their_own_action(self):
        """An email telling you what you just did teaches people to filter."""
        brief = self.submitted_brief()
        # The admin stands in for the requester AND happens to be the designer's
        # colleague; the designer must still not be mailed about their own
        # submission, and an actor is never their own recipient.
        with self.captureOnCommitCallbacks(execute=True):
            workflow.request_rework(brief, actor=self.designer,
                                    reason="spotted it myself")
        self.assertEqual(mail.outbox, [])

    def test_cancelling_tells_the_designer_to_stop(self):
        brief = self.raise_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.assign(brief, self.designer, actor=self.admin)
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            workflow.cancel(brief, actor=self.requester, reason="Campaign dropped")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Stop work", mail.outbox[0].body)
        self.assertIn("Campaign dropped", mail.outbox[0].body)

    def test_an_unassigned_brief_mails_nobody_on_cancel(self):
        brief = self.raise_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.cancel(brief, actor=self.requester, reason="dropped")
        self.assertEqual(mail.outbox, [])

    def test_a_mail_failure_cannot_break_the_transition(self):
        """Office365 being slow must not roll back a submission."""
        brief = self.raise_brief()
        with self.captureOnCommitCallbacks(execute=True):
            workflow.assign(brief, self.designer, actor=self.admin)

        with mock.patch(
            "apps.design_briefs.notifications.EmailMultiAlternatives.send",
            side_effect=RuntimeError("SMTP timeout"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                workflow.submit(brief, actor=self.designer)

        brief.refresh_from_db()
        self.assertEqual(brief.status, DesignBrief.STATUS_SUBMITTED)

    def test_the_admins_hear_when_there_is_no_requester_to_reach(self):
        """A brief raised by somebody since removed must not go silent."""
        brief = self.raise_brief()
        brief.raised_by = None
        brief.save(update_fields=["raised_by"])
        with self.captureOnCommitCallbacks(execute=True):
            workflow.assign(brief, self.designer, actor=self.admin)
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            workflow.submit(brief, actor=self.designer)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.admin.email])

    def test_superusers_are_not_mailed_as_admins(self):
        """A superuser can act on anything; that does not put them on the team."""
        user("root_user", superuser=True, email="root@hf.test")
        self.assertNotIn("root@hf.test", notifications.admin_addresses())
        self.assertIn(self.admin.email, notifications.admin_addresses())


class WipTests(BoardTestCase):
    """Work in progress against a limit, so the screen can say "too much".

    The limit is ceil(designers x 1.5) - kanban's working rule - derived from
    the designer group rather than configured, so there is no setting to go
    stale.
    """

    def working(self, designer, n=1):
        for i in range(n):
            brief = self.raise_brief(design_item=f"Item {designer.username} {i}")
            workflow.assign(brief, designer, actor=self.admin)
            workflow.start(brief, actor=designer)

    def board(self, who=None):
        self.client.force_authenticate(who or self.admin)
        r = self.client.get(f"{BASE}board/")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data["wip"]

    def test_the_limit_is_one_and_a_half_times_the_designers_rounded_up(self):
        # setUp puts two users in the designer group.
        self.assertEqual(self.board()["designers"], 2)
        self.assertEqual(self.board()["limit"], 3)  # ceil(2 * 1.5)

        user("third_designer", rbac.DESIGNER_GROUP)
        self.assertEqual(self.board()["limit"], 5)  # ceil(3 * 1.5)

    def test_an_idle_designer_still_counts_toward_capacity(self):
        """Counting only people who happen to hold work would tighten the limit
        the moment somebody cleared their plate, which is backwards."""
        self.working(self.designer, 1)
        wip = self.board()
        self.assertEqual(wip["designers"], 2)
        self.assertEqual(wip["in_progress"], 1)
        self.assertFalse(wip["over"])

    def test_over_the_limit_is_reported(self):
        self.working(self.designer, 3)
        self.working(self.other_designer, 2)
        wip = self.board()
        self.assertEqual(wip["in_progress"], 5)
        self.assertEqual(wip["limit"], 3)
        self.assertTrue(wip["over"])

    def test_work_waiting_on_a_requester_is_not_the_designers_load(self):
        """A brief in review is somebody else's turn; counting it would make the
        team look overloaded by another department's silence."""
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        workflow.submit(brief, actor=self.designer)

        wip = self.board()
        self.assertEqual(wip["in_progress"], 0)
        self.assertFalse(wip["over"])

    def test_no_designers_means_no_limit_rather_than_a_limit_of_zero(self):
        """A limit of zero would paint every board as over its limit."""
        for u in (self.designer, self.other_designer):
            u.groups.clear()
        wip = self.board()
        self.assertEqual(wip["designers"], 0)
        self.assertEqual(wip["limit"], 0)
        self.assertFalse(wip["over"])

    def test_the_board_still_answers_for_a_plain_requester(self):
        """The wip block must not be admin-only - the wall display is polled by
        whoever is signed in on that machine."""
        self.working(self.designer, 1)
        wip = self.board(self.requester)
        self.assertEqual(wip["limit"], 3)


class MarkupTests(BoardTestCase):
    """Feedback pinned to a place on the artwork.

    Positions are fractions of the preview, never pixels: the preview is itself
    a downscale and the browser renders it at whatever width the layout gives
    it, so a pixel offset would land somewhere else on every other screen.
    """

    def proofed(self):
        brief = self.raise_brief()
        workflow.assign(brief, self.designer, actor=self.admin)
        workflow.start(brief, actor=self.designer)
        proof = workflow.add_proof(
            brief, prepared=images.prepare(png_bytes()),
            uploaded_by=self.designer)
        return brief, proof

    def test_a_pinned_comment_is_markup_and_a_plain_one_is_not(self):
        brief, proof = self.proofed()
        pinned = workflow.add_comment(
            brief, author=self.requester, body="Logo too small",
            proof=proof, x=0.25, y=0.4)
        plain = workflow.add_comment(
            brief, author=self.requester, body="General thought")

        self.assertTrue(pinned.is_markup)
        self.assertFalse(plain.is_markup)
        self.assertEqual((pinned.x, pinned.y), (0.25, 0.4))
        self.assertIsNone(pinned.w)

    def test_a_box_is_allowed(self):
        brief, proof = self.proofed()
        c = workflow.add_comment(
            brief, author=self.requester, body="This whole strip is off-brand",
            proof=proof, x=0.1, y=0.1, w=0.5, h=0.2)
        self.assertTrue(c.is_markup)
        self.assertEqual((c.w, c.h), (0.5, 0.2))

    def test_half_a_position_is_refused_rather_than_pinned_to_the_origin(self):
        """A pin at 0,0 looks like a fault in the artwork, not in the data."""
        brief, proof = self.proofed()
        with self.assertRaises(workflow.TransitionError):
            workflow.add_comment(brief, author=self.requester, body="x only",
                                 proof=proof, x=0.5)
        with self.assertRaises(workflow.TransitionError):
            workflow.add_comment(brief, author=self.requester, body="y only",
                                 proof=proof, y=0.5)

    def test_a_position_outside_the_image_is_refused(self):
        brief, proof = self.proofed()
        for kw in ({"x": 1.4, "y": 0.2}, {"x": -0.1, "y": 0.2},
                   {"x": 0.2, "y": 2.0}):
            with self.assertRaises(workflow.TransitionError, msg=str(kw)):
                workflow.add_comment(brief, author=self.requester,
                                     body="out of bounds", proof=proof, **kw)

    def test_a_box_that_runs_off_the_edge_is_refused(self):
        brief, proof = self.proofed()
        with self.assertRaises(workflow.TransitionError):
            workflow.add_comment(brief, author=self.requester, body="too wide",
                                 proof=proof, x=0.8, y=0.1, w=0.5)

    def test_a_box_with_no_position_is_refused(self):
        brief, proof = self.proofed()
        with self.assertRaises(workflow.TransitionError):
            workflow.add_comment(brief, author=self.requester, body="box only",
                                 proof=proof, w=0.3, h=0.3)

    def test_markup_without_a_version_is_refused_not_silently_unpinned(self):
        """Dropping the coordinate would lose the one thing they pointed at."""
        brief, _ = self.proofed()
        with self.assertRaises(workflow.TransitionError):
            workflow.add_comment(brief, author=self.requester,
                                 body="where though", x=0.3, y=0.3)

    def test_the_api_accepts_markup_and_returns_it(self):
        brief, proof = self.proofed()
        self.client.force_authenticate(self.requester)
        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/comments/",
            {"body": "Old brand mark", "proof": proof.pk,
             "x": 0.32, "y": 0.18, "w": 0.2, "h": 0.1},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["is_markup"])
        self.assertAlmostEqual(r.data["x"], 0.32)
        self.assertEqual(r.data["proof_version"], 1)
        self.assertFalse(r.data["resolved"])

    def test_the_api_rejects_a_position_out_of_range(self):
        brief, proof = self.proofed()
        self.client.force_authenticate(self.requester)
        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/comments/",
            {"body": "nope", "proof": proof.pk, "x": 3.0, "y": 0.2},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("x", r.data)

    def test_markup_rides_on_the_brief_payload(self):
        brief, proof = self.proofed()
        workflow.add_comment(brief, author=self.requester, body="here",
                             proof=proof, x=0.5, y=0.5)
        self.client.force_authenticate(self.designer)
        r = self.client.get(f"{BASE}briefs/{brief.reference}/")
        marks = [c for c in r.data["comments"] if c["is_markup"]]
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0]["y"], 0.5)

    def test_a_comment_can_be_resolved_and_reopened(self):
        brief, proof = self.proofed()
        c = workflow.add_comment(brief, author=self.requester, body="fix this",
                                 proof=proof, x=0.2, y=0.2)
        self.client.force_authenticate(self.designer)

        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/comments/{c.pk}/resolve/",
            {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["resolved"])
        self.assertIsNotNone(r.data["resolved_at"])
        self.assertEqual(r.data["resolved_by"], self.designer.id)

        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/comments/{c.pk}/resolve/",
            {"resolved": False}, format="json")
        self.assertFalse(r.data["resolved"])
        self.assertIsNone(r.data["resolved_at"])
        self.assertIsNone(r.data["resolved_by"])

    def test_resolving_writes_no_timeline_step(self):
        """A history full of ticks buries the steps that matter."""
        brief, proof = self.proofed()
        c = workflow.add_comment(brief, author=self.requester, body="fix",
                                 proof=proof, x=0.2, y=0.2)
        before = brief.events.count()
        workflow.resolve_comment(c, actor=self.designer)
        self.assertEqual(brief.events.count(), before)

    def test_an_outsider_cannot_resolve(self):
        brief, proof = self.proofed()
        c = workflow.add_comment(brief, author=self.requester, body="fix",
                                 proof=proof, x=0.2, y=0.2)
        self.client.force_authenticate(self.outsider)
        r = self.client.post(
            f"{BASE}briefs/{brief.reference}/comments/{c.pk}/resolve/",
            {}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_the_timeline_note_says_it_was_marked_up(self):
        brief, proof = self.proofed()
        workflow.add_comment(brief, author=self.requester, body="here",
                             proof=proof, x=0.5, y=0.5)
        note = brief.events.filter(kind=BriefEvent.KIND_COMMENT).last().note
        self.assertIn("marked up", note)
        self.assertIn("v1", note)
