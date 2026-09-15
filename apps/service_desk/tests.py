"""The service desk: the clock, the workflow, and who may do what.

Most of these are about time, because "how long did this take" is the question
the module exists to answer and it is the one that is easy to answer wrongly in
a way nobody notices until somebody disputes a report.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
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
        self.assertGreaterEqual(TicketCategory.objects.count(), 8)
        for category in TicketCategory.objects.all():
            self.assertGreater(category.response_minutes, 0, category.slug)
            self.assertGreater(category.resolution_minutes, 0, category.slug)
            self.assertTrue(category.description.strip(), category.slug)

    def test_the_desk_covers_more_than_this_application(self):
        """Most of what Strategy are asked is about the reports and scorecards
        they publish, not about software. A list that does not describe
        somebody's query sends them back to email, which is the behaviour this
        desk exists to replace."""
        slugs = set(TicketCategory.objects.filter(is_active=True)
                    .values_list("slug", flat=True))
        for expected in ("report-request", "clarification", "scorecard",
                         "targets", "other"):
            self.assertIn(expected, slugs)

    def test_the_renamed_category_kept_its_slug_and_its_tickets(self):
        """data-request became report-request by rename, not by replacement —
        a new category would have orphaned every ticket already raised."""
        self.assertFalse(TicketCategory.objects.filter(slug="data-request").exists())
        self.assertTrue(TicketCategory.objects.filter(slug="report-request").exists())

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


class TeamSeedMigrationTests(TestCase):
    """The 0004 data migration, run against accounts that actually exist.

    It passed every test run and then failed on the server, because the test
    database is migrated before any user exists — so the loop that removes
    people from the desk groups never had a row to act on. These tests call the
    migration's own function with the accounts present, which is the state the
    server was in.
    """

    def _seed(self):
        import importlib

        from django.apps import apps as django_apps

        module = importlib.import_module(
            "apps.service_desk.migrations.0004_desk_team_and_more_categories")
        module.seed(django_apps, None)
        return module

    def test_it_runs_when_the_people_it_names_exist(self):
        """Mixing a historical Group with the live User model raised
        'Cannot query Group object: Must be a Group instance'."""
        get_user_model().objects.create_user(
            username="trevor.william", password="x",
            email="trevor.william@hfcb.co.ke")
        desk = Group.objects.get_or_create(name=rbac.MANAGER_GROUP)[0]
        benson = get_user_model().objects.create_user(
            username="benson.kiptoo", password="x", email="benson.kiptoo@hfcb.co.ke")
        benson.groups.add(desk)

        self._seed()  # must not raise

        self.assertTrue(
            get_user_model().objects.get(username="trevor.william")
            .groups.filter(name=rbac.MANAGER_GROUP).exists())
        self.assertFalse(
            get_user_model().objects.get(username="benson.kiptoo")
            .groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_a_missing_account_does_not_fail_the_deployment(self):
        """Nobody named is guaranteed to exist yet when this runs."""
        get_user_model().objects.filter(email__iendswith="@hfcb.co.ke").delete()
        self._seed()  # must not raise

    def test_running_it_twice_changes_nothing(self):
        get_user_model().objects.create_user(
            username="arthur.nyota", password="x", email="arthur.nyota@hfcb.co.ke")
        self._seed()
        self._seed()
        self.assertEqual(
            get_user_model().objects.get(username="arthur.nyota")
            .groups.filter(name=rbac.MANAGER_GROUP).count(), 1)

    def test_it_leaves_everything_else_about_the_account_alone(self):
        """Removing somebody from this desk is not a change to their access."""
        other = Group.objects.get_or_create(name="staff_mgt")[0]
        person = get_user_model().objects.create_user(
            username="clinton.ontweka", password="x", email="clinton.ontweka@hfcb.co.ke")
        person.groups.add(other)
        person.is_superuser = True
        person.save()

        self._seed()

        person.refresh_from_db()
        self.assertTrue(person.groups.filter(name="staff_mgt").exists())
        self.assertTrue(person.is_superuser)
        self.assertTrue(person.is_active)


class TeamCommandTests(TestCase):
    """Managing the desk from a terminal.

    The seed migration added nobody on the server because the accounts are not
    spelled the way its hard-coded list guessed. This is the tool that fixes
    that without a deploy, so it has to be forgiving about how an address is
    written and honest when it cannot find somebody.
    """

    def run_cmd(self, *args):
        from io import StringIO

        out = StringIO()
        call_command("service_desk_team", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_it_finds_somebody_by_their_email(self):
        person = user("twilliam", email="trevor.william@hfcb.co.ke")
        self.run_cmd("--add", "trevor.william@hfcb.co.ke")
        self.assertTrue(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_it_finds_somebody_by_their_username(self):
        person = user("trevor.william", email="t.w@hfcb.co.ke")
        self.run_cmd("--add", "trevor.william")
        self.assertTrue(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_it_finds_somebody_by_the_local_part_of_an_address(self):
        """The address written down is not always the address on the account."""
        person = user("arthur.nyota", email="arthur.nyota@hfgroup.co.ke")
        self.run_cmd("--add", "arthur.nyota@hfcb.co.ke")
        self.assertTrue(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_it_refuses_to_guess_between_two_people(self):
        """Adding the wrong colleague to a desk is worse than adding nobody."""
        a = user("john.smith", email="john.smith@hfcb.co.ke")
        b = user("john.smithers", email="john.smithers@hfcb.co.ke")
        output = self.run_cmd("--add", "john.smith")
        # john.smith matches itself exactly, so that one IS resolved.
        self.assertTrue(a.groups.filter(name=rbac.MANAGER_GROUP).exists())
        self.assertFalse(b.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_an_ambiguous_name_is_reported_not_acted_on(self):
        user("mary.a", email="mary.a@hfcb.co.ke")
        user("mary.b", email="mary.b@hfcb.co.ke")
        output = self.run_cmd("--add", "mary")
        self.assertIn("matches several", output)
        self.assertEqual(
            get_user_model().objects.filter(
                groups__name=rbac.MANAGER_GROUP).count(), 0)

    def test_a_missing_account_says_so_rather_than_failing_quietly(self):
        output = self.run_cmd("--add", "nobody@hfcb.co.ke")
        self.assertIn("No account matches", output)

    def test_it_warns_only_when_the_desk_is_truly_empty(self):
        """A desk nobody is on emails every query into silence.

        Seeded addresses count: somebody with no login who receives the queue
        is on the desk as far as this warning is concerned, which is the whole
        point of having them.
        """
        from apps.service_desk.models import DeskRecipient

        self.assertNotIn("Nobody is on the desk", self.run_cmd())

        DeskRecipient.objects.all().delete()
        self.assertIn("Nobody is on the desk", self.run_cmd())

    def test_an_address_appears_in_the_listing(self):
        from apps.service_desk.models import DeskRecipient

        DeskRecipient.objects.create(email="nolog.in@hfcb.co.ke")
        output = self.run_cmd()
        self.assertIn("Notified without an account", output)
        self.assertIn("nolog.in@hfcb.co.ke", output)

    def test_removing_somebody_touches_nothing_else(self):
        person = user("benson.k", email="benson.k@hfcb.co.ke")
        person.groups.add(Group.objects.get_or_create(name="staff_mgt")[0])
        self.run_cmd("--add", "benson.k")
        self.run_cmd("--remove", "benson.k")
        person.refresh_from_db()
        self.assertFalse(person.groups.filter(name=rbac.MANAGER_GROUP).exists())
        self.assertTrue(person.groups.filter(name="staff_mgt").exists())
        self.assertTrue(person.is_active)

    def test_find_changes_nothing(self):
        person = user("trevor.william", email="trevor.william@hfcb.co.ke")
        output = self.run_cmd("--find", "trevor")
        self.assertIn("trevor.william", output)
        self.assertFalse(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_an_account_with_no_email_is_flagged(self):
        """They would be on the desk and never hear about a query."""
        # Built directly: the helper above substitutes a default for a blank
        # address, which is exactly the case under test.
        get_user_model().objects.create_user(username="silent", password="x", email="")
        output = self.run_cmd("--add", "silent")
        self.assertIn("no email", output)


class StrategyTeamSeedTests(TestCase):
    """Migration 0008 puts the real Strategy roster on the desk.

    The first attempt (0004) matched nothing because the names it guessed were
    not how the accounts are spelled, and left the desk empty — every query
    raised into silence while the requester still got a confirmation. These
    pin the matching that fixes it.
    """

    def _seed(self):
        import importlib

        from django.apps import apps as django_apps

        module = importlib.import_module(
            "apps.service_desk.migrations.0008_seed_strategy_team")
        module.seed(django_apps, None)
        return module

    def test_an_account_is_matched_on_its_exact_address(self):
        person = get_user_model().objects.create_user(
            username="sk", password="x", email="Stacy.Mwenda@hfgroup.co.ke")
        self._seed()
        self.assertTrue(person.groups.filter(name=rbac.AGENT_GROUP).exists())

    def test_it_bridges_the_rebrand_by_the_local_part(self):
        """The roster says @hfgroup.co.ke; the login may be @hfcb.co.ke."""
        person = get_user_model().objects.create_user(
            username="allan.aswani", password="x", email="allan.aswani@hfcb.co.ke")
        self._seed()
        self.assertTrue(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_the_heads_are_managers_and_the_rest_are_handlers(self):
        eileen = get_user_model().objects.create_user(
            username="eileen.ndegwa", password="x", email="e@hfcb.co.ke")
        shekinah = get_user_model().objects.create_user(
            username="shekinah.mwangi", password="x", email="s@hfcb.co.ke")
        self._seed()
        self.assertTrue(eileen.groups.filter(name=rbac.MANAGER_GROUP).exists())
        self.assertTrue(shekinah.groups.filter(name=rbac.AGENT_GROUP).exists())

    def test_benson_is_on_the_roster_but_not_on_this_desk(self):
        person = get_user_model().objects.create_user(
            username="benson.mbugua", password="x",
            email="Benson.Mbugua@hfgroup.co.ke")
        self._seed()
        self.assertFalse(person.groups.filter(
            name__in=[rbac.MANAGER_GROUP, rbac.AGENT_GROUP]).exists())

    def test_somebody_with_no_login_is_emailed_instead_of_dropped(self):
        """Being unreachable is what makes a desk look like it ignores people."""
        from apps.service_desk.models import DeskRecipient

        self._seed()
        self.assertTrue(DeskRecipient.objects.filter(
            email__iexact="Stacy.Mwenda@hfgroup.co.ke").exists())

    def test_a_misspelt_roster_address_is_never_mailed(self):
        """The roster spells one domain 'hfgoup'. Mail there bounces silently."""
        from apps.service_desk.models import DeskRecipient

        self._seed()
        self.assertFalse(DeskRecipient.objects.filter(
            email__icontains="hfgoup").exists())

    def test_running_it_twice_changes_nothing(self):
        person = get_user_model().objects.create_user(
            username="stacy.mwenda", password="x", email="s2@hfcb.co.ke")
        self._seed()
        self._seed()
        self.assertEqual(person.groups.filter(name=rbac.AGENT_GROUP).count(), 1)

    def test_it_never_removes_anybody(self):
        """A manager may have edited the team; a migration must not overrule."""
        added_by_hand = user("someone.else", rbac.AGENT_GROUP)
        self._seed()
        self.assertTrue(added_by_hand.groups.filter(name=rbac.AGENT_GROUP).exists())


class RosterMatchingTests(TestCase):
    """Matching a roster row to a portfolio login.

    Two of the seven were silently missed the first time: the matcher used the
    roster's LAST name, and Kenyan names carry three parts, so the surname on
    the roster is often not the one the account uses.
    """

    def apply(self):
        from apps.service_desk import roster

        return roster.apply()

    def test_stacy_signs_in_under_her_middle_name(self):
        """Stacy Kendi Mwenda is 'Stacy Kendi' on the system."""
        person = get_user_model().objects.create_user(
            username="stacy.kendi", password="x", email="stacy.kendi@hfcb.co.ke",
            first_name="Stacy", last_name="Kendi")
        self.apply()
        self.assertTrue(person.groups.filter(name=rbac.AGENT_GROUP).exists())

    def test_bryan_does_too(self):
        """Bryan Mwaura Kanyigi is 'Bryan Mwaura'."""
        person = get_user_model().objects.create_user(
            username="bryan.mwaura", password="x", email="bryan.mwaura@hfcb.co.ke",
            first_name="Bryan", last_name="Mwaura")
        self.apply()
        self.assertTrue(person.groups.filter(name=rbac.AGENT_GROUP).exists())

    def test_the_exact_address_still_wins(self):
        person = get_user_model().objects.create_user(
            username="whoever", password="x", email="Eileen.Ndegwa@hfgroup.co.ke")
        self.apply()
        self.assertTrue(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_the_rebrand_is_bridged_by_the_local_part(self):
        person = get_user_model().objects.create_user(
            username="aa", password="x", email="allan.aswani@hfcb.co.ke")
        self.apply()
        self.assertTrue(person.groups.filter(name=rbac.MANAGER_GROUP).exists())

    def test_it_refuses_to_guess_between_two_people(self):
        """Putting the wrong colleague on a desk is worse than leaving
        somebody off it."""
        get_user_model().objects.create_user(
            username="stacy.one", password="x", email="stacy.mwenda.one@hfcb.co.ke",
            first_name="Stacy", last_name="Something")
        get_user_model().objects.create_user(
            username="stacy.two", password="x", email="stacy.mwenda.two@hfcb.co.ke",
            first_name="Stacy", last_name="Otherthing")
        _, unmatched = self.apply()
        self.assertIn("Stacy Kendi Mwenda", [name for name, *_ in unmatched])
        self.assertEqual(
            get_user_model().objects.filter(
                username__startswith="stacy.",
                groups__name=rbac.AGENT_GROUP).count(), 0)

    def test_benson_is_never_matched(self):
        person = get_user_model().objects.create_user(
            username="benson.mbugua", password="x",
            email="Benson.Mbugua@hfgroup.co.ke",
            first_name="Benson", last_name="Mbugua")
        self.apply()
        self.assertFalse(person.groups.filter(
            name__in=[rbac.MANAGER_GROUP, rbac.AGENT_GROUP]).exists())

    def test_it_reports_who_it_could_not_find(self):
        """'It added nobody' with no explanation is what made the first
        attempt impossible to debug."""
        matched, unmatched = self.apply()
        self.assertEqual(len(matched) + len(unmatched), 7)
        self.assertTrue(unmatched)

    def test_somebody_unmatched_is_emailed_rather_than_dropped(self):
        from apps.service_desk.models import DeskRecipient

        self.apply()
        self.assertTrue(DeskRecipient.objects.filter(
            email__iexact="Shekinah.Mwangi@hfgroup.co.ke").exists())

    def test_the_misspelt_domain_is_never_used_for_mail(self):
        from apps.service_desk.models import DeskRecipient

        self.apply()
        self.assertFalse(
            DeskRecipient.objects.filter(email__icontains="hfgoup").exists())

    def test_running_it_again_after_a_person_appears_picks_them_up(self):
        """The whole point of making this re-runnable."""
        self.apply()
        person = get_user_model().objects.create_user(
            username="bryan.mwaura", password="x", email="bryan.mwaura@hfcb.co.ke",
            first_name="Bryan", last_name="Mwaura")
        self.apply()
        self.assertTrue(person.groups.filter(name=rbac.AGENT_GROUP).exists())

    def test_the_command_runs_and_reports(self):
        from io import StringIO

        get_user_model().objects.create_user(
            username="stacy.kendi", password="x", email="sk@hfcb.co.ke",
            first_name="Stacy", last_name="Kendi")
        out = StringIO()
        call_command("service_desk_team", "--sync-roster", stdout=out, stderr=out)
        output = out.getvalue()
        self.assertIn("Roster:", output)
        self.assertIn("stacy.kendi", output)
