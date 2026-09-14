"""The service desk: the clock, the workflow, and who may do what.

Most of these are about time, because "how long did this take" is the question
the module exists to answer and it is the one that is easy to answer wrongly in
a way nobody notices until somebody disputes a report.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from . import rbac, workflow
from .models import DeskSettings, Holiday, Ticket, TicketCategory, TicketEvent
from .worktime import WorkWeek, add_business_seconds, business_seconds, describe

NBO = ZoneInfo("Africa/Nairobi")


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NBO)


def user(username, group=None, email=None):
    u = get_user_model().objects.create_user(
        username=username, password="x", email=email or f"{username}@hf.test")
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


class WorkingClockTests(TestCase):
    """8am-5pm, Monday to Friday. 2026-09-14 is a Monday."""

    WEEK = WorkWeek()

    def test_an_hour_inside_the_day_is_an_hour(self):
        self.assertEqual(
            business_seconds(at(2026, 9, 14, 9), at(2026, 9, 14, 10), self.WEEK), 3600)

    def test_the_night_does_not_count(self):
        """16:30 Monday to 08:30 Tuesday is one working hour, not sixteen."""
        self.assertEqual(
            business_seconds(at(2026, 9, 14, 16, 30), at(2026, 9, 15, 8, 30), self.WEEK),
            3600)

    def test_the_weekend_does_not_count(self):
        """Friday 16:55 to Monday 08:10 is fifteen working minutes.

        This single case is why the clock is not wall-clock: measured on a wall
        it is 63 hours, and every Monday morning would read as a breach.
        """
        self.assertEqual(
            business_seconds(at(2026, 9, 11, 16, 55), at(2026, 9, 14, 8, 10), self.WEEK),
            15 * 60)

    def test_a_full_working_day_is_nine_hours(self):
        self.assertEqual(
            business_seconds(at(2026, 9, 14, 0), at(2026, 9, 15, 0), self.WEEK),
            9 * 3600)

    def test_time_before_opening_is_not_credited(self):
        """A ticket raised at 6am has not been waiting since 6am."""
        self.assertEqual(
            business_seconds(at(2026, 9, 14, 6), at(2026, 9, 14, 9), self.WEEK), 3600)

    def test_a_holiday_is_not_a_working_day(self):
        week = WorkWeek(holidays=frozenset({date(2026, 12, 25)}))
        # Christmas 2026 is a Friday; Thursday 16:00 to the following Monday
        # 09:00 is one hour Thursday plus one hour Monday.
        self.assertEqual(
            business_seconds(at(2026, 12, 24, 16), at(2026, 12, 28, 9), week), 2 * 3600)

    def test_an_end_before_the_start_is_zero_not_negative(self):
        self.assertEqual(
            business_seconds(at(2026, 9, 14, 10), at(2026, 9, 14, 9), self.WEEK), 0)

    def test_a_deadline_skips_the_weekend(self):
        """Four working hours from 3pm Friday is 10am Monday."""
        due = add_business_seconds(at(2026, 9, 11, 15), 4 * 3600, self.WEEK)
        self.assertEqual(due.astimezone(NBO), at(2026, 9, 14, 10))

    def test_a_deadline_from_outside_hours_starts_at_opening(self):
        due = add_business_seconds(at(2026, 9, 14, 5), 2 * 3600, self.WEEK)
        self.assertEqual(due.astimezone(NBO), at(2026, 9, 14, 10))

    def test_a_deadline_longer_than_a_day_rolls_over(self):
        due = add_business_seconds(at(2026, 9, 14, 16), 2 * 3600, self.WEEK)
        self.assertEqual(due.astimezone(NBO), at(2026, 9, 15, 9))

    def test_a_desk_that_is_never_open_does_not_hang(self):
        """A misconfigured calendar must fail fast, not loop for ten years."""
        shut = WorkWeek(workdays=frozenset())
        self.assertEqual(business_seconds(at(2026, 9, 14), at(2027, 9, 14), shut), 0)
        self.assertIsNotNone(add_business_seconds(at(2026, 9, 14), 3600, shut))

    def test_durations_read_in_working_days(self):
        self.assertEqual(describe(0), "0s")
        self.assertEqual(describe(45 * 60), "45m")
        self.assertEqual(describe(2 * 3600), "2h")
        # Nine working hours is one day of this desk's time, not 24.
        self.assertEqual(describe(9 * 3600), "1d")
        self.assertIsInstance(describe(None), str)


class SlaTests(TestCase):
    def setUp(self):
        self.category = TicketCategory.objects.create(
            name="Data", slug="data", response_minutes=240, resolution_minutes=1080)

    def test_the_promise_is_frozen_onto_the_ticket(self):
        """Repricing a category must not breach yesterday's tickets."""
        ticket = workflow.create(subject="q", category=self.category)
        first = ticket.resolution_due_at
        self.category.resolution_minutes = 60
        self.category.save()
        ticket.refresh_from_db()
        self.assertEqual(ticket.resolution_due_at, first)

    def test_urgent_is_the_same_promise_sooner(self):
        normal = workflow.create(subject="a", category=self.category)
        urgent = workflow.create(subject="b", category=self.category,
                                 priority=Ticket.PRIORITY_URGENT)
        self.assertLess(urgent.resolution_minutes, normal.resolution_minutes)

    def test_a_ticket_still_in_time_is_not_yet_breached_or_met(self):
        """Unknown is not the same as met, and must not render as green."""
        ticket = workflow.create(subject="q", category=self.category)
        self.assertIsNone(ticket.response_breached)

    def test_waiting_on_the_requester_does_not_count_against_the_desk(self):
        agent = user("agent1", rbac.AGENT_GROUP)
        ticket = workflow.create(subject="q", category=self.category)
        workflow.set_status(ticket, Ticket.STATUS_ON_HOLD, actor=agent)
        ticket.refresh_from_db()
        ticket.on_hold_since = timezone.now() - timedelta(days=1)
        ticket.save()
        held = ticket.working_seconds_open()
        workflow.set_status(ticket, Ticket.STATUS_IN_PROGRESS, actor=agent)
        ticket.refresh_from_db()
        self.assertGreater(ticket.on_hold_seconds, 0)
        # The open time did not grow by the day spent waiting.
        self.assertLessEqual(ticket.working_seconds_open(), held + 60)


class WorkflowTests(TestCase):
    def setUp(self):
        self.category = TicketCategory.objects.create(
            name="Data", slug="data", response_minutes=240, resolution_minutes=1080)
        self.requester = user("asker")
        self.agent = user("agent2", rbac.AGENT_GROUP)
        self.manager = user("boss", rbac.MANAGER_GROUP)

    def raise_one(self, **kw):
        return workflow.create(subject="Why is this number wrong?",
                               category=self.category, raised_by=self.requester, **kw)

    def test_raising_starts_the_timeline(self):
        ticket = self.raise_one()
        self.assertTrue(ticket.reference.startswith("SD-"))
        self.assertEqual(ticket.status, Ticket.STATUS_NEW)
        self.assertEqual(ticket.events.count(), 1)
        self.assertEqual(ticket.events.first().kind, TicketEvent.KIND_CREATED)

    def test_every_step_records_how_long_it_took_to_get_there(self):
        ticket = self.raise_one()
        workflow.assign(ticket, self.agent, actor=self.manager)
        workflow.set_status(ticket, Ticket.STATUS_IN_PROGRESS, actor=self.agent)
        workflow.resolve(ticket, actor=self.agent, note="Fixed the mapping")
        kinds = list(ticket.events.values_list("kind", flat=True))
        self.assertEqual(kinds, ["created", "assigned", "status", "resolved"])
        for event in ticket.events.all():
            self.assertIsNotNone(event.seconds_since_previous)
            self.assertIsNotNone(event.working_seconds_since_previous)

    def test_assignment_is_not_a_response(self):
        """Being put in a queue is not an answer, and must not stop the clock."""
        ticket = self.raise_one()
        workflow.assign(ticket, self.agent, actor=self.manager)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.first_response_at)

    def test_an_internal_note_is_not_a_response_either(self):
        """Otherwise the desk meets its SLA by talking to itself."""
        ticket = self.raise_one()
        workflow.comment(ticket, self.agent, "checking with the ETL team",
                         is_internal=True)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.first_response_at)

    def test_a_visible_reply_from_the_desk_is(self):
        ticket = self.raise_one()
        workflow.comment(ticket, self.agent, "Looking at it now")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_response_at)

    def test_the_requester_talking_is_not_a_response(self):
        ticket = self.raise_one()
        workflow.comment(ticket, self.requester, "any update?")
        ticket.refresh_from_db()
        self.assertIsNone(ticket.first_response_at)

    def test_resolving_does_not_close(self):
        """The desk's word is not the last word. This is the whole module."""
        ticket = self.raise_one()
        workflow.resolve(ticket, actor=self.agent, note="done")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_RESOLVED)
        self.assertIsNone(ticket.closed_at)
        self.assertIsNone(ticket.confirmed_by_requester)

    def test_the_requester_confirming_closes_it(self):
        ticket = self.raise_one()
        workflow.resolve(ticket, actor=self.agent)
        workflow.confirm(ticket, actor=self.requester, satisfaction=5)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_CLOSED)
        self.assertTrue(ticket.confirmed_by_requester)
        self.assertEqual(ticket.satisfaction, 5)

    def test_an_auto_close_is_recorded_as_unconfirmed(self):
        """Silence must never be filed as satisfaction."""
        ticket = self.raise_one()
        workflow.resolve(ticket, actor=self.agent)
        workflow.auto_close(ticket)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_CLOSED)
        self.assertIs(ticket.confirmed_by_requester, False)

    def test_reopening_keeps_the_history_and_counts(self):
        ticket = self.raise_one()
        workflow.resolve(ticket, actor=self.agent)
        workflow.reopen(ticket, actor=self.requester, note="still wrong")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.STATUS_IN_PROGRESS)
        self.assertEqual(ticket.reopened_count, 1)
        self.assertIsNone(ticket.resolved_at)
        self.assertEqual(ticket.events.filter(kind="reopened").count(), 1)

    def test_repeating_a_transition_does_nothing(self):
        """A double-clicked button must not send a second email."""
        ticket = self.raise_one()
        workflow.resolve(ticket, actor=self.agent)
        before = ticket.events.count()
        workflow.resolve(ticket, actor=self.agent)
        self.assertEqual(ticket.events.count(), before)

    def test_assigning_the_same_person_twice_does_nothing(self):
        ticket = self.raise_one()
        workflow.assign(ticket, self.agent, actor=self.manager)
        before = ticket.events.count()
        workflow.assign(ticket, self.agent, actor=self.manager)
        self.assertEqual(ticket.events.count(), before)

    def test_a_step_taken_by_a_job_says_so(self):
        ticket = self.raise_one()
        workflow.resolve(ticket, actor=self.agent)
        workflow.auto_close(ticket)
        self.assertEqual(ticket.events.last().actor_label, "system / job")

    def test_a_ticket_can_be_logged_for_somebody_who_phoned(self):
        ticket = workflow.create(
            subject="called about a report", category=self.category,
            on_behalf_of="Jane from Thika", requester_email="jane@hf.test",
            actor=self.agent)
        self.assertEqual(ticket.on_behalf_of, "Jane from Thika")
        self.assertIn("Jane from Thika", ticket.events.first().note)


class PermissionTests(TestCase):
    def setUp(self):
        self.category = TicketCategory.objects.create(
            name="Data", slug="data", response_minutes=240, resolution_minutes=1080)
        self.requester = user("asker2", email="asker2@hf.test")
        self.other = user("stranger")
        self.agent = user("agent3", rbac.AGENT_GROUP)
        self.manager = user("boss2", rbac.MANAGER_GROUP)
        self.ticket = workflow.create(subject="q", category=self.category,
                                      raised_by=self.requester)

    def test_a_requester_sees_their_own(self):
        self.assertTrue(rbac.can_view(self.requester, self.ticket))

    def test_a_stranger_does_not(self):
        """Queries name customers and figures. They are not a noticeboard."""
        self.assertFalse(rbac.can_view(self.other, self.ticket))

    def test_a_handler_sees_the_queue(self):
        self.assertTrue(rbac.can_view(self.agent, self.ticket))

    def test_the_desk_cannot_confirm_its_own_work(self):
        """A handler confirming their own resolution reproduces the complaint."""
        self.assertFalse(rbac.can_confirm(self.agent, self.ticket))
        self.assertTrue(rbac.can_confirm(self.requester, self.ticket))

    def test_a_phoned_in_ticket_may_be_confirmed_by_the_desk_lead(self):
        """It has no requester account, so somebody has to close it."""
        phoned = workflow.create(subject="q", category=self.category,
                                 on_behalf_of="Jane")
        self.assertTrue(rbac.can_confirm(self.manager, phoned))

    def test_only_the_desk_resolves(self):
        self.assertFalse(rbac.can_resolve(self.requester, self.ticket))
        self.assertTrue(rbac.can_resolve(self.agent, self.ticket))

    def test_a_requester_may_withdraw_their_own_query(self):
        self.assertTrue(rbac.can_cancel(self.requester, self.ticket))
        self.assertFalse(rbac.can_cancel(self.other, self.ticket))

    def test_only_a_manager_assigns_other_people(self):
        self.assertTrue(rbac.can_assign_to_others(self.manager))
        self.assertFalse(rbac.can_assign_to_others(self.agent))

    def test_the_strategy_director_role_already_runs_the_desk(self):
        """It is their department's desk; a second group would be ceremony."""
        director = user("director", "business_performance")
        self.assertTrue(rbac.is_manager(director))

    def test_the_queryset_scopes_to_what_you_may_see(self):
        self.assertEqual(Ticket.objects.for_user(self.other).count(), 0)
        self.assertEqual(Ticket.objects.for_user(self.requester).count(), 1)
        self.assertEqual(Ticket.objects.for_user(self.agent).count(), 1)


class DeskSettingsTests(TestCase):
    def test_the_public_holidays_are_seeded(self):
        """Christmas comes from the seed migration, not from this test."""
        week = DeskSettings.get().work_week()
        self.assertIn(date(2026, 12, 25), week.holidays)
        self.assertFalse(week.is_working_day(date(2026, 12, 25)))

    def test_a_gazetted_day_added_later_is_picked_up(self):
        """Eid and any gazetted day are keyed in, not shipped — so this is the
        path that actually matters."""
        added = date(2026, 3, 20)
        self.assertTrue(DeskSettings.get().work_week().is_working_day(added))
        Holiday.objects.create(day=added, name="Eid al-Fitr")
        self.assertFalse(DeskSettings.get().work_week().is_working_day(added))

    def test_the_seeded_categories_all_carry_a_promise(self):
        """A category with no SLA is a ticket with no promise attached."""
        self.assertGreaterEqual(TicketCategory.objects.count(), 6)
        for category in TicketCategory.objects.all():
            self.assertGreater(category.response_minutes, 0, category.slug)
            self.assertGreater(category.resolution_minutes, 0, category.slug)

    def test_a_saturday_is_not_a_working_day_by_default(self):
        week = DeskSettings.get().work_week()
        self.assertFalse(week.is_working_day(date(2026, 9, 12)))
        self.assertTrue(week.is_working_day(date(2026, 9, 14)))

    def test_there_can_only_ever_be_one_settings_row(self):
        DeskSettings.get()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DeskSettings.objects.create(opens_minute=9 * 60)
        self.assertEqual(DeskSettings.objects.count(), 1)

    def test_reading_the_settings_twice_gives_the_same_row(self):
        self.assertEqual(DeskSettings.get().pk, DeskSettings.get().pk)
        self.assertEqual(DeskSettings.objects.count(), 1)
