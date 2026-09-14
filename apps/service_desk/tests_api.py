"""The endpoints, the emails, and the jobs.

Written against the behaviour a user would notice, not the implementation: what
a requester can see, what the desk can do, who is told, and what the cron does
when it runs twice.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from . import rbac, workflow
from .models import DeskSettings, Holiday, Ticket, TicketCategory, TicketEvent

BASE = "/service_desk/"


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


class DeskTestCase(APITestCase):
    def setUp(self):
        self.category = TicketCategory.objects.get(slug="report-request")
        self.requester = user("req", email="req@hf.test")
        self.agent = user("agt", rbac.AGENT_GROUP, email="agt@hf.test")
        self.manager = user("mgr", rbac.MANAGER_GROUP, email="mgr@hf.test")
        self.stranger = user("nosy", email="nosy@hf.test")
        mail.outbox.clear()

    def as_(self, who):
        client = APIClient()
        client.force_authenticate(who)
        return client

    def act(self, who, path, payload=None, method="post"):
        """Make a request AND run the after-commit work.

        Mail is sent from transaction.on_commit so a rolled-back resolution
        never announces itself. TestCase wraps each test in a transaction that
        is rolled back, so those callbacks would otherwise never fire and every
        email assertion here would pass vacuously against an empty outbox.
        """
        with self.captureOnCommitCallbacks(execute=True):
            return getattr(self.as_(who), method)(
                BASE + path, payload or {}, format="json")

    def run_commits(self, fn, *args, **kwargs):
        """Same, for workflow functions called directly."""
        with self.captureOnCommitCallbacks(execute=True):
            return fn(*args, **kwargs)

    def raise_ticket(self, who=None, **extra):
        payload = {"subject": "The deposit figure looks wrong",
                   "body": "Branch total does not match the report.",
                   "category": self.category.id}
        payload.update(extra)
        res = self.act(who or self.requester, "tickets/", payload)
        self.assertEqual(res.status_code, 201, res.data)
        return Ticket.objects.get(reference=res.data["reference"])


class RaisingTests(DeskTestCase):
    def test_anyone_signed_in_can_raise_one(self):
        ticket = self.raise_ticket()
        self.assertEqual(ticket.status, Ticket.STATUS_NEW)
        self.assertEqual(ticket.raised_by, self.requester)
        self.assertEqual(ticket.requester_email, "req@hf.test")

    def test_the_promise_comes_back_with_it(self):
        ticket = self.raise_ticket()
        self.assertIsNotNone(ticket.response_due_at)
        self.assertIsNotNone(ticket.resolution_due_at)
        self.assertGreater(ticket.resolution_due_at, ticket.response_due_at)

    def test_a_subject_nobody_could_recognise_is_refused(self):
        res = self.as_(self.requester).post(
            BASE + "tickets/", {"subject": "help", "category": self.category.id},
            format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("subject", res.data)

    def test_raising_tells_the_requester_and_the_desk(self):
        self.raise_ticket()
        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn("req@hf.test", recipients)
        self.assertIn("agt@hf.test", recipients)

    def test_an_ordinary_user_cannot_raise_one_in_somebody_elses_name(self):
        """Otherwise anyone could log a query as a colleague and get their mail."""
        res = self.as_(self.requester).post(BASE + "tickets/", {
            "subject": "logging this for someone",
            "category": self.category.id,
            "on_behalf_of": "Someone Else",
            "requester_email": "victim@hf.test",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("on_behalf_of", res.data)

    def test_the_desk_can_log_a_phone_call(self):
        ticket = self.raise_ticket(
            who=self.agent, on_behalf_of="Jane from Thika",
            requester_email="jane@hf.test")
        self.assertEqual(ticket.on_behalf_of, "Jane from Thika")
        self.assertIsNone(ticket.raised_by)
        self.assertIn("jane@hf.test", [a for m in mail.outbox for a in m.to])

    def test_logging_for_somebody_needs_a_way_to_reach_them(self):
        res = self.as_(self.agent).post(BASE + "tickets/", {
            "subject": "called about the report",
            "category": self.category.id,
            "on_behalf_of": "Jane",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("requester_email", res.data)


class VisibilityTests(DeskTestCase):
    def test_a_requester_sees_only_their_own(self):
        self.raise_ticket()
        self.raise_ticket(who=self.stranger)
        res = self.as_(self.requester).get(BASE + "tickets/")
        self.assertEqual(res.data["count"], 1)

    def test_the_desk_sees_everything(self):
        self.raise_ticket()
        self.raise_ticket(who=self.stranger)
        res = self.as_(self.agent).get(BASE + "tickets/")
        self.assertEqual(res.data["count"], 2)

    def test_somebody_elses_ticket_is_not_found_rather_than_forbidden(self):
        """403 confirms the reference exists, which is enough to go fishing."""
        ticket = self.raise_ticket()
        res = self.as_(self.stranger).get(BASE + f"tickets/{ticket.reference}/")
        self.assertEqual(res.status_code, 404)

    def test_an_internal_note_never_reaches_the_requester(self):
        ticket = self.raise_ticket()
        workflow.comment(ticket, self.agent, "the ETL is broken again",
                         is_internal=True)
        res = self.as_(self.requester).get(BASE + f"tickets/{ticket.reference}/")
        bodies = [c["body"] for c in res.data["comments"]]
        self.assertEqual(bodies, [])

    def test_the_desk_sees_internal_notes(self):
        ticket = self.raise_ticket()
        workflow.comment(ticket, self.agent, "the ETL is broken again",
                         is_internal=True)
        res = self.as_(self.agent).get(BASE + f"tickets/{ticket.reference}/")
        self.assertEqual(len(res.data["comments"]), 1)

    def test_signing_out_closes_the_door(self):
        ticket = self.raise_ticket()
        res = APIClient().get(BASE + f"tickets/{ticket.reference}/")
        self.assertIn(res.status_code, (401, 403))


class WorkingTests(DeskTestCase):
    def test_a_handler_replying_claims_the_ticket(self):
        """No allocation step: whoever picks it up owns it."""
        ticket = self.raise_ticket()
        self.as_(self.agent).post(
            BASE + f"tickets/{ticket.reference}/comment/",
            {"body": "Looking at this now"}, format="json")
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.agent)
        self.assertEqual(ticket.status, Ticket.STATUS_IN_PROGRESS)
        self.assertIsNotNone(ticket.first_response_at)

    def test_picking_up_does_not_steal_a_colleagues_ticket(self):
        ticket = self.raise_ticket()
        workflow.assign(ticket, self.agent, actor=self.manager)
        self.as_(self.manager).post(
            BASE + f"tickets/{ticket.reference}/comment/",
            {"body": "any progress?"}, format="json")
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.agent)

    def test_a_requester_commenting_does_not_claim_anything(self):
        ticket = self.raise_ticket()
        self.as_(self.requester).post(
            BASE + f"tickets/{ticket.reference}/comment/",
            {"body": "any update?"}, format="json")
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assigned_to)
        self.assertIsNone(ticket.first_response_at)

    def test_a_reply_from_the_desk_emails_the_requester(self):
        ticket = self.raise_ticket()
        mail.outbox.clear()
        self.act(self.agent, f"tickets/{ticket.reference}/comment/",
                 {"body": "Checking the source now"})
        self.assertTrue(any("req@hf.test" in m.to for m in mail.outbox))

    def test_an_internal_note_emails_nobody_outside_the_desk(self):
        ticket = self.raise_ticket()
        mail.outbox.clear()
        self.act(self.agent, f"tickets/{ticket.reference}/comment/",
                 {"body": "ETL broken", "is_internal": True})
        self.assertFalse(any("req@hf.test" in m.to for m in mail.outbox))

    def test_a_requester_cannot_smuggle_an_internal_note(self):
        ticket = self.raise_ticket()
        self.as_(self.requester).post(
            BASE + f"tickets/{ticket.reference}/comment/",
            {"body": "sneaky", "is_internal": True}, format="json")
        self.assertFalse(ticket.comments.first().is_internal)

    def test_a_requester_cannot_move_the_status(self):
        ticket = self.raise_ticket()
        res = self.as_(self.requester).post(
            BASE + f"tickets/{ticket.reference}/status/",
            {"status": Ticket.STATUS_IN_PROGRESS}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_status_cannot_be_used_to_resolve_behind_the_desks_back(self):
        """Resolving tells somebody. It must not be reachable as a status patch."""
        ticket = self.raise_ticket()
        res = self.as_(self.agent).post(
            BASE + f"tickets/{ticket.reference}/status/",
            {"status": Ticket.STATUS_RESOLVED}, format="json")
        self.assertEqual(res.status_code, 400)
        ticket.refresh_from_db()
        self.assertNotEqual(ticket.status, Ticket.STATUS_RESOLVED)


class ResolutionTests(DeskTestCase):
    def test_resolving_needs_a_note(self):
        """The requester is about to be asked to agree with it."""
        ticket = self.raise_ticket()
        res = self.as_(self.agent).post(
            BASE + f"tickets/{ticket.reference}/resolve/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("note", res.data)

    def test_resolving_emails_the_requester(self):
        ticket = self.raise_ticket()
        mail.outbox.clear()
        self.act(self.agent, f"tickets/{ticket.reference}/resolve/",
                 {"note": "The report was filtered to one branch."})
        sent = [m for m in mail.outbox if "req@hf.test" in m.to]
        self.assertTrue(sent)
        self.assertIn("resolved", sent[0].subject.lower())

    def test_the_desk_cannot_confirm_its_own_resolution(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="done")
        res = self.as_(self.agent).post(
            BASE + f"tickets/{ticket.reference}/confirm/", {}, format="json")
        self.assertEqual(res.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_RESOLVED)

    def test_the_requester_confirms_and_it_closes(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="done")
        res = self.as_(self.requester).post(
            BASE + f"tickets/{ticket.reference}/confirm/",
            {"satisfaction": 4}, format="json")
        self.assertEqual(res.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_CLOSED)
        self.assertTrue(ticket.confirmed_by_requester)
        self.assertEqual(ticket.satisfaction, 4)

    def test_reopening_brings_it_back_with_its_history(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="done")
        before = ticket.events.count()
        res = self.as_(self.requester).post(
            BASE + f"tickets/{ticket.reference}/reopen/",
            {"note": "still wrong"}, format="json")
        self.assertEqual(res.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_IN_PROGRESS)
        self.assertGreater(ticket.events.count(), before)

    def test_a_requester_may_withdraw_their_own(self):
        ticket = self.raise_ticket()
        res = self.as_(self.requester).post(
            BASE + f"tickets/{ticket.reference}/cancel/",
            {"note": "sorted itself out"}, format="json")
        self.assertEqual(res.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_CANCELLED)

    def test_a_stranger_cannot_cancel_somebody_elses(self):
        ticket = self.raise_ticket()
        res = self.as_(self.stranger).post(
            BASE + f"tickets/{ticket.reference}/cancel/", {}, format="json")
        self.assertEqual(res.status_code, 404)


class AssignmentTests(DeskTestCase):
    def test_a_handler_can_take_a_ticket(self):
        ticket = self.raise_ticket()
        res = self.as_(self.agent).post(
            BASE + f"tickets/{ticket.reference}/assign/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.agent)

    def test_a_handler_cannot_hand_one_to_somebody_else(self):
        ticket = self.raise_ticket()
        res = self.as_(self.agent).post(
            BASE + f"tickets/{ticket.reference}/assign/",
            {"username": "mgr"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_a_manager_can(self):
        ticket = self.raise_ticket()
        res = self.as_(self.manager).post(
            BASE + f"tickets/{ticket.reference}/assign/",
            {"username": "agt"}, format="json")
        self.assertEqual(res.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.agent)

    def test_assigning_to_somebody_outside_the_desk_is_refused(self):
        """They would never see it, so it would simply disappear."""
        ticket = self.raise_ticket()
        res = self.as_(self.manager).post(
            BASE + f"tickets/{ticket.reference}/assign/",
            {"username": "nosy"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_superuser_can_still_work_any_ticket(self):
        """Being able to administer the system means being able to fix a ticket."""
        boss = user("super", superuser=True, email="super@hf.test")
        ticket = self.raise_ticket()
        res = self.as_(boss).get(BASE + f"tickets/{ticket.reference}/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["permissions"]["resolve"])

    def test_a_superuser_is_not_on_the_desk_team(self):
        """Superusers exist across the bank who have nothing to do with
        Strategy. Mailing them the queue puts it in the inbox of people who
        did not ask for it, and offering them in the assign list offers to
        hand a query to somebody who will never look at it."""
        from apps.service_desk import notifications

        user("super2", superuser=True, email="super2@hf.test")
        self.assertNotIn("super2@hf.test", notifications.handler_addresses())

        res = self.as_(self.manager).get(BASE + "handlers/")
        usernames = [h["username"] for h in res.data["handlers"]]
        self.assertNotIn("super2", usernames)
        self.assertIn("agt", usernames)

    def test_the_queue_email_goes_to_the_team_only(self):
        user("super3", superuser=True, email="super3@hf.test")
        mail.outbox.clear()
        self.raise_ticket()
        went_to = {a for m in mail.outbox for a in m.to}
        self.assertIn("agt@hf.test", went_to)
        self.assertNotIn("super3@hf.test", went_to)


class PermissionPayloadTests(DeskTestCase):
    """The UI draws its buttons from this, so it has to be right."""

    def test_a_requester_is_not_offered_resolve(self):
        ticket = self.raise_ticket()
        res = self.as_(self.requester).get(BASE + f"tickets/{ticket.reference}/")
        perms = res.data["permissions"]
        self.assertFalse(perms["resolve"])
        self.assertFalse(perms["internal_note"])
        self.assertTrue(perms["comment"])
        self.assertTrue(perms["cancel"])

    def test_confirm_is_offered_only_once_it_is_resolved(self):
        ticket = self.raise_ticket()
        res = self.as_(self.requester).get(BASE + f"tickets/{ticket.reference}/")
        self.assertFalse(res.data["permissions"]["confirm"])
        workflow.resolve(ticket, actor=self.agent, note="done")
        res = self.as_(self.requester).get(BASE + f"tickets/{ticket.reference}/")
        self.assertTrue(res.data["permissions"]["confirm"])


class TimelineTests(DeskTestCase):
    def test_the_detail_shows_where_the_time_went(self):
        ticket = self.raise_ticket()
        workflow.comment(ticket, self.agent, "on it")
        workflow.resolve(ticket, actor=self.agent, note="fixed")
        res = self.as_(self.requester).get(BASE + f"tickets/{ticket.reference}/")
        breakdown = res.data["time_breakdown"]
        self.assertIn("to_first_response", breakdown)
        self.assertTrue(breakdown["steps"])
        for step in breakdown["steps"]:
            self.assertIn("gap", step)
            self.assertIn("at", step)

    def test_every_event_carries_both_clocks(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="fixed")
        res = self.as_(self.agent).get(BASE + f"tickets/{ticket.reference}/")
        for event in res.data["events"]:
            self.assertIn("seconds_since_previous", event)
            self.assertIn("working_seconds_since_previous", event)


class FilterTests(DeskTestCase):
    def test_scope_mine_is_what_i_am_handling(self):
        a = self.raise_ticket()
        self.raise_ticket()
        workflow.assign(a, self.agent, actor=self.manager)
        res = self.as_(self.agent).get(BASE + "tickets/?scope=mine")
        self.assertEqual(res.data["count"], 1)

    def test_unassigned_is_what_nobody_has_picked_up(self):
        a = self.raise_ticket()
        self.raise_ticket()
        workflow.assign(a, self.agent, actor=self.manager)
        res = self.as_(self.agent).get(BASE + "tickets/?scope=unassigned")
        self.assertEqual(res.data["count"], 1)

    def test_open_excludes_the_finished(self):
        a = self.raise_ticket()
        self.raise_ticket()
        workflow.cancel(a, actor=self.requester)
        res = self.as_(self.agent).get(BASE + "tickets/?status=open")
        self.assertEqual(res.data["count"], 1)

    def test_search_finds_by_reference(self):
        ticket = self.raise_ticket()
        res = self.as_(self.agent).get(BASE + f"tickets/?search={ticket.reference}")
        self.assertEqual(res.data["count"], 1)

    def test_a_nonsense_ordering_does_not_500(self):
        self.raise_ticket()
        res = self.as_(self.agent).get(BASE + "tickets/?ordering=;drop table")
        self.assertEqual(res.status_code, 200)


class ConfigTests(DeskTestCase):
    def test_anyone_can_read_the_categories_to_raise_a_ticket(self):
        res = self.as_(self.requester).get(BASE + "categories/")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 6)

    def test_only_a_manager_changes_them(self):
        res = self.as_(self.agent).post(
            BASE + "categories/", {"name": "New", "slug": "new"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_a_response_target_after_the_resolution_target_is_refused(self):
        res = self.as_(self.manager).post(BASE + "categories/", {
            "name": "Backwards", "slug": "backwards",
            "response_minutes": 600, "resolution_minutes": 60,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_category_with_tickets_cannot_be_deleted(self):
        self.raise_ticket()
        res = self.as_(self.manager).delete(BASE + f"categories/{self.category.id}/")
        self.assertEqual(res.status_code, 400)

    def test_a_desk_that_closes_before_it_opens_is_refused(self):
        res = self.as_(self.manager).patch(
            BASE + "settings/", {"opens_minute": 1020, "closes_minute": 480},
            format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_manager_can_add_a_gazetted_holiday(self):
        res = self.as_(self.manager).post(
            BASE + "holidays/", {"day": "2026-03-20", "name": "Eid al-Fitr"},
            format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Holiday.objects.filter(day="2026-03-20").exists())


class MyDeskTests(DeskTestCase):
    def test_an_ordinary_user_gets_their_own_counts(self):
        self.raise_ticket()
        res = self.as_(self.requester).get(BASE + "my-desk/")
        self.assertEqual(res.data["raised_open"], 1)
        self.assertFalse(res.data["is_handler"])
        self.assertNotIn("queue_open", res.data)

    def test_a_handler_gets_the_queue_counts(self):
        self.raise_ticket()
        res = self.as_(self.agent).get(BASE + "my-desk/")
        self.assertTrue(res.data["is_handler"])
        self.assertEqual(res.data["unassigned"], 1)


class ReportTests(DeskTestCase):
    def test_the_reports_are_for_the_desk(self):
        res = self.as_(self.requester).get(BASE + "reports/")
        self.assertEqual(res.status_code, 403)

    def test_the_desk_gets_them(self):
        self.raise_ticket()
        res = self.as_(self.agent).get(BASE + "reports/")
        self.assertEqual(res.status_code, 200)
        for key in ("overview", "by_category", "by_handler", "trend", "ageing"):
            self.assertIn(key, res.data)

    def test_attainment_is_unmeasured_rather_than_zero_when_nothing_is_judged(self):
        """0% would read as total failure on a desk that has done nothing yet."""
        res = self.as_(self.agent).get(BASE + "reports/")
        self.assertIsNone(res.data["overview"]["sla_resolution_percent"])

    def test_the_emailed_report_runs_and_has_the_numbers(self):
        self.raise_ticket()
        from apps.service_desk import reports as r
        body = r.digest_text(days=7)
        self.assertIn("Service Desk", body)
        self.assertIn("Raised", body)
        # ASCII only, so --dry-run cannot die on a console codepage.
        body.encode("ascii")

    def test_the_report_command_says_so_when_nobody_can_receive_it(self):
        get_user_model().objects.update(email="")
        call_command("send_service_desk_report", "--days", "7")


class MaintenanceTests(DeskTestCase):
    def test_a_resolved_ticket_nobody_confirmed_closes_itself(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="done")
        Ticket.objects.filter(pk=ticket.pk).update(
            resolved_at=timezone.now() - timedelta(days=30))
        call_command("service_desk_maintenance")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_CLOSED)
        self.assertIs(ticket.confirmed_by_requester, False)

    def test_a_freshly_resolved_ticket_is_left_alone(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="done")
        call_command("service_desk_maintenance")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_RESOLVED)

    def test_a_breach_escalates_once_however_often_the_cron_runs(self):
        """Fifteen-minute reminders are how a breach alert gets filtered."""
        ticket = self.raise_ticket()
        Ticket.objects.filter(pk=ticket.pk).update(
            response_due_at=timezone.now() - timedelta(hours=5),
            resolution_due_at=timezone.now() - timedelta(hours=1))
        mail.outbox.clear()
        self.run_commits(call_command, "service_desk_maintenance")
        first = len(mail.outbox)
        self.assertGreater(first, 0)
        self.run_commits(call_command, "service_desk_maintenance")
        self.run_commits(call_command, "service_desk_maintenance")
        self.assertEqual(len(mail.outbox), first)

    def test_a_dry_run_changes_nothing_and_sends_nothing(self):
        ticket = self.raise_ticket()
        workflow.resolve(ticket, actor=self.agent, note="done")
        Ticket.objects.filter(pk=ticket.pk).update(
            resolved_at=timezone.now() - timedelta(days=30))
        mail.outbox.clear()
        call_command("service_desk_maintenance", "--dry-run")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_RESOLVED)
        self.assertEqual(len(mail.outbox), 0)

    def test_the_escalation_goes_to_managers_not_to_the_handler(self):
        ticket = self.raise_ticket()
        workflow.assign(ticket, self.agent, actor=self.manager)
        Ticket.objects.filter(pk=ticket.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=1))
        mail.outbox.clear()
        self.run_commits(call_command, "service_desk_maintenance")
        breaches = [m for m in mail.outbox if "breached" in m.subject.lower()]
        self.assertTrue(breaches)
        for message in breaches:
            self.assertIn("mgr@hf.test", message.to)


class MailFailureTests(DeskTestCase):
    def test_a_dead_mail_server_does_not_lose_the_ticket(self):
        """A resolution that rolled back because Office365 was slow would be
        done twice by a handler who was told nothing."""
        from unittest.mock import patch

        ticket = self.raise_ticket()
        with patch("apps.service_desk.notifications.get_connection",
                   side_effect=OSError("smtp down")):
            res = self.as_(self.agent).post(
                BASE + f"tickets/{ticket.reference}/resolve/",
                {"note": "fixed it"}, format="json")
        self.assertEqual(res.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_RESOLVED)


class EmailShapeTests(DeskTestCase):
    """What lands in somebody's inbox.

    The first version was plain text with column-aligned labels, which arrives
    as ragged monospace in Outlook and reads like a machine fault report rather
    than a bank's desk writing to a colleague.
    """

    def test_a_message_carries_an_html_alternative(self):
        self.raise_ticket()
        message = mail.outbox[0]
        self.assertTrue(message.alternatives, "no HTML part was attached")
        html, mime = message.alternatives[0]
        self.assertEqual(mime, "text/html")
        self.assertIn("<table", html)

    def test_it_is_branded_hfcb_not_hf_group(self):
        """The bank rebranded. An email still signed HF Group is wrong on the
        one line every recipient reads."""
        self.raise_ticket()
        for message in mail.outbox:
            blob = message.subject + message.body + message.alternatives[0][0]
            self.assertNotIn("HF Group", blob)
            self.assertIn("HFCB", blob)

    def test_the_plain_text_alternative_still_says_everything(self):
        """Some people read mail as text by choice, and some clients strip HTML."""
        ticket = self.raise_ticket()
        body = mail.outbox[0].body
        self.assertIn(ticket.reference, body)
        self.assertIn(ticket.subject, body)
        self.assertIn("Status", body)

    def test_the_resolution_note_is_escaped_not_injected(self):
        """A note is typed by a person and lands inside an HTML document."""
        ticket = self.raise_ticket()
        mail.outbox.clear()
        self.act(self.agent, f"tickets/{ticket.reference}/resolve/",
                 {"note": "<script>alert(1)</script> fixed & checked"})
        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_the_report_email_is_html_too(self):
        from apps.service_desk import notifications, reports

        sent = notifications.report(
            ["boss@hf.test"], "Weekly service desk report",
            reports.digest_text(days=7))
        self.assertEqual(sent, 1)
        self.assertTrue(mail.outbox[-1].alternatives)


class AccountFreeRecipientTests(DeskTestCase):
    """People on the desk who have no login on the tool.

    The first design tied being notified to holding an account. Several of the
    people who actually run this desk do not have one and do not need one — and
    creating logins purely so that mail has somewhere to go is a worse answer
    than writing the address down.
    """

    def test_the_named_addresses_are_seeded(self):
        from apps.service_desk.models import DeskRecipient

        emails = set(DeskRecipient.objects.values_list("email", flat=True))
        for address in ("trevor.william@hfcb.co.ke", "arthur.nyota@hfcb.co.ke",
                        "jewell.karani@hfcb.co.ke"):
            self.assertIn(address, emails)

    def test_a_new_query_reaches_them_without_an_account(self):
        mail.outbox.clear()
        self.raise_ticket()
        went_to = {a for m in mail.outbox for a in m.to}
        self.assertIn("trevor.william@hfcb.co.ke", went_to)

    def test_they_are_added_to_the_team_not_instead_of_it(self):
        """Removing the last account must not silently stop the queue."""
        mail.outbox.clear()
        self.raise_ticket()
        went_to = {a for m in mail.outbox for a in m.to}
        self.assertIn("agt@hf.test", went_to)             # the account
        self.assertIn("arthur.nyota@hfcb.co.ke", went_to)  # the address

    def test_an_inactive_address_is_not_written_to(self):
        from apps.service_desk.models import DeskRecipient

        DeskRecipient.objects.filter(email="trevor.william@hfcb.co.ke").update(
            is_active=False)
        mail.outbox.clear()
        self.raise_ticket()
        went_to = {a for m in mail.outbox for a in m.to}
        self.assertNotIn("trevor.william@hfcb.co.ke", went_to)

    def test_queue_and_escalations_are_separate(self):
        from apps.service_desk import notifications
        from apps.service_desk.models import DeskRecipient

        DeskRecipient.objects.create(
            email="watcher@hfcb.co.ke", queue=False, escalations=True)
        self.assertNotIn("watcher@hfcb.co.ke", notifications.handler_addresses())
        self.assertIn("watcher@hfcb.co.ke", notifications.manager_addresses())

    def test_a_manager_can_add_one_through_the_api(self):
        res = self.as_(self.manager).post(
            BASE + "recipients/",
            {"email": "new.person@hfcb.co.ke", "name": "New Person"},
            format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_an_ordinary_user_cannot(self):
        res = self.as_(self.requester).post(
            BASE + "recipients/", {"email": "sneaky@hfcb.co.ke"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_an_address_subscribed_to_nothing_is_refused(self):
        res = self.as_(self.manager).post(
            BASE + "recipients/",
            {"email": "nobody@hfcb.co.ke", "queue": False, "escalations": False},
            format="json")
        self.assertEqual(res.status_code, 400)

    def test_the_command_adds_an_address_without_an_account(self):
        from io import StringIO

        from apps.service_desk.models import DeskRecipient

        out = StringIO()
        call_command("service_desk_team", "--add-email", "extra@hfcb.co.ke",
                     stdout=out, stderr=out)
        self.assertTrue(
            DeskRecipient.objects.filter(email="extra@hfcb.co.ke").exists())

    def test_the_command_rejects_something_that_is_not_an_address(self):
        from io import StringIO

        out = StringIO()
        call_command("service_desk_team", "--add-email", "trevor",
                     stdout=out, stderr=out)
        self.assertIn("not an email address", out.getvalue())

    def test_adding_the_same_address_twice_is_not_a_second_row(self):
        from io import StringIO

        from apps.service_desk.models import DeskRecipient

        for _ in range(2):
            call_command("service_desk_team", "--add-email", "dup@hfcb.co.ke",
                         stdout=StringIO(), stderr=StringIO())
        self.assertEqual(
            DeskRecipient.objects.filter(email="dup@hfcb.co.ke").count(), 1)
