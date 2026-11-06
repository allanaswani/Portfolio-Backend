"""The Daily Usage Report: a short note, the figures in an Excel workbook."""

import datetime
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook

from apps.analytics.exclusions import EXCLUDED_GROUP
from apps.analytics.models import UserActivityEvent
from apps.observability.management.commands import send_usage_report as report
from apps.observability.models import AlertRecipient, ExternalUsageDay
from apps.observability.report_xlsx import build as build_workbook
from apps.portfolio.models import Profile

DAY = datetime.date(2026, 10, 28)


def at(hour, back=0):
    return timezone.make_aware(datetime.datetime.combine(
        DAY - datetime.timedelta(days=back), datetime.time(hour)))


def event(user, path="/rm-portfolio", back=0):
    row = UserActivityEvent.objects.create(user=user, path=path)
    UserActivityEvent.objects.filter(pk=row.pk).update(created_at=at(10, back))


class UsageReportTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.amy = User.objects.create_user(
            "amy.k", first_name="Amy", last_name="Kariuki")
        self.ben = User.objects.create_user(
            "ben.o", first_name="Ben", last_name="Otieno")
        self.strategy = User.objects.create_user(
            "wash.a", first_name="Wash", last_name="Amolo")
        Group.objects.get_or_create(name=EXCLUDED_GROUP)[0].user_set.add(self.strategy)
        event(self.amy)
        event(self.amy, "/rm-portfolio/customers")
        event(self.ben)
        # Whoever opens most - and is on the team that builds it.
        for _ in range(50):
            event(self.strategy)
        event(self.ben, "/home", back=1)  # the day before

    def sheet(self, title):
        wb = load_workbook(io.BytesIO(build_workbook(report.build_sheets(DAY))))
        return [list(r) for r in wb[title].iter_rows(values_only=True)]

    def test_the_day_counts_people_and_pages_but_not_strategy(self):
        p = report.portfolio_day(DAY)
        self.assertEqual(p["users"], 2)
        self.assertEqual(p["views"], 3)
        self.assertEqual(p["accounts"], 2)
        self.assertEqual(p["top_areas"][0], ("/rm-portfolio", 2, 2))

    def test_strategy_is_nowhere_in_the_workbook(self):
        for title in ("People", "Not Using", "Portfolio Areas", "Branch Ranking"):
            self.assertNotIn("Wash Amolo", str(self.sheet(title)))

    def test_strategy_on_customer_360_is_left_out_too(self):
        ExternalUsageDay.objects.create(source="customer-360", day=DAY,
                                        username="WASH.A", customer_views=99)
        self.assertNotIn("Wash Amolo", str(self.sheet("Customer 360 People")))

    def test_every_branch_is_ranked_even_with_nobody_using_it(self):
        Profile.objects.filter(user=self.amy).update(branch="NYALI BRANCH")
        ranking = report.branch_ranking(DAY)
        self.assertEqual(ranking[0]["branch"], "NYALI BRANCH")
        self.assertEqual(ranking[0]["rank"], 1)
        self.assertEqual(ranking[0]["active"], 1)
        self.assertEqual(ranking[0]["share"], 1.0)
        self.assertEqual(ranking[0]["pages"], 2)
        names = [r["branch"] for r in ranking]
        self.assertIn("KENYATTA BRANCH", names)
        self.assertNotIn("HEAD OFFICE BRANCH", names)
        self.assertNotIn("HFDI", names)

    def test_gill_house_is_harambee_and_kisii_is_gone(self):
        from apps.portfolio.models import Profile

        Profile.objects.filter(user=self.amy).update(branch="GILL HOUSE BRANCH")
        names = [r["branch"] for r in report.branch_ranking(DAY)]
        self.assertIn("HARAMBEE AVE BRANCH", names)
        self.assertNotIn("GILL HOUSE BRANCH", names)
        self.assertNotIn("KISII BRANCH", names)
        self.assertEqual(report._branches()["amy.k"], "HARAMBEE AVE BRANCH")

    def test_the_rank_is_on_the_share_of_accounts_not_the_headcount(self):
        User = get_user_model()
        Profile.objects.filter(user=self.amy).update(branch="NYALI BRANCH")
        Profile.objects.filter(user=self.ben).update(branch="KENYATTA BRANCH")
        # Kisii has three people on it, one of whom used it. Nyali's one did.
        for name in ("c.c", "d.d"):
            Profile.objects.filter(user=User.objects.create_user(name)).update(
                branch="KENYATTA BRANCH")
        ranking = report.branch_ranking(DAY)
        self.assertEqual([r["branch"] for r in ranking[:2]],
                         ["NYALI BRANCH", "KENYATTA BRANCH"])

    def test_customer_360_counts_towards_a_branch(self):
        Profile.objects.filter(user=self.amy).update(branch="NYALI BRANCH")
        ExternalUsageDay.objects.create(source="customer-360", day=DAY,
                                        username="amy.k", customer_views=12)
        row = report.branch_ranking(DAY)[0]
        self.assertEqual((row["c360_people"], row["profiles"]), (1, 12))

    def test_the_hr_roster_places_someone_with_no_branch_on_their_profile(self):
        from apps.staff_management.models import StaffEmployeeData

        StaffEmployeeData.objects.create(
            staff_pf_number=1, staff_name="Amy Kariuki",
            staff_email="AMY.K@hfcb.co.ke", department="x",
            staff_unit="Nyali Branch", staff_org_unit="x", job_title="x",
            employment_date=datetime.date(2020, 1, 1),
            employee_category="back_office")
        self.assertEqual(report._branches()["amy.k"], "NYALI BRANCH")

    def test_a_unit_that_is_not_exactly_a_branch_is_not_guessed_at(self):
        from apps.staff_management.models import StaffEmployeeData

        StaffEmployeeData.objects.create(
            staff_pf_number=1, staff_name="Amy Kariuki",
            staff_email="amy.k@hfcb.co.ke", department="x",
            staff_unit="Nyali Sub Office", staff_org_unit="x", job_title="x",
            employment_date=datetime.date(2020, 1, 1),
            employee_category="back_office")
        self.assertEqual(report._branches()["amy.k"], report.NO_BRANCH)

    def test_the_people_who_used_neither_tool_are_listed(self):
        get_user_model().objects.create_user("idle.i", first_name="Idle",
                                             last_name="Ian")
        self.assertIn("Idle Ian", str(self.sheet("Not Using")))
        self.assertNotIn("Amy Kariuki", str(self.sheet("Not Using")))

    def test_a_silent_customer_360_says_when_it_last_reported(self):
        """A stopped push and a quiet day must not both read as zero."""
        ExternalUsageDay.objects.create(
            source="customer-360", day=DAY - datetime.timedelta(days=5),
            username="amy.k", customer_views=3)
        summary = str(self.sheet("Summary"))
        self.assertIn("Nothing reported for 28 Oct 2026", summary)
        self.assertIn("Last report received", summary)

    def test_the_mail_is_the_full_report_and_says_what_is_attached(self):
        body = report.build(DAY)
        self.assertIn("PORTFOLIO TOOL", body)
        self.assertIn("LAST 7 DAYS", body)
        self.assertIn("Most active people", body)
        self.assertIn("attached Excel workbook", body)
        page = report.build_html(DAY)
        self.assertIn("Most active people", page)
        self.assertIn("Amy Kariuki", page)
        self.assertIn("attached Excel workbook", page)

    def test_strategy_stays_out_of_the_full_mail(self):
        ExternalUsageDay.objects.create(
            source="customer-360", day=DAY, username="wash.a", customer_views=99)
        ExternalUsageDay.objects.create(
            source="customer-360", day=DAY, username="amy.k", customer_views=3,
            searches=1)
        for text in (report.build(DAY), report.build_html(DAY)):
            self.assertNotIn("Wash Amolo", text)
            self.assertIn("Amy Kariuki", text)

    def test_the_workbook_has_the_expected_sheets(self):
        ExternalUsageDay.objects.create(
            source="customer-360", day=DAY, username="amy.k",
            customer_views=12, distinct_customers=9, searches=4,
            active_minutes=35, sessions=2, features={"linked_parties": 7})
        wb = load_workbook(io.BytesIO(build_workbook(report.build_sheets(DAY))))
        self.assertEqual(wb.sheetnames, [
            "Summary", "Branch Ranking", "People", "Not Using",
            "Portfolio Areas", "Last 7 Days", "Customer 360 People",
            "Customer 360 Features"])
        self.assertIn("Linked parties", str(self.sheet("Customer 360 Features")))
        self.assertTrue(wb["Branch Ranking"].tables)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_it_goes_only_to_usage_report_recipients_with_the_workbook(self):
        AlertRecipient.objects.create(email="boss@hfgroup.co.ke",
                                      usage_report=True, downtime=False,
                                      data_health=False)
        AlertRecipient.objects.create(email="ops@hfgroup.co.ke",
                                      usage_report=False)
        call_command("send_usage_report", "--day", DAY.isoformat())
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["boss@hfgroup.co.ke"])
        self.assertIn("Daily usage - 28 Oct 2026", message.subject)
        self.assertTrue(message.subject.startswith("[HFCB Portfolio]"))
        self.assertEqual(message.alternatives[0][1], "text/html")
        name, content, kind = message.attachments[0]
        self.assertEqual(name, "Daily Usage Report - 2026-10-28.xlsx")
        self.assertIn("spreadsheetml", kind)
        self.assertIn("Branch Ranking", load_workbook(io.BytesIO(content)).sheetnames)


class TheMigrationsListTests(TestCase):
    """A deliberate list of people deserves one check that it stays exact."""

    def test_the_seed_matches_on_the_whole_name_before_the_at(self):
        import importlib

        from django.apps import apps as django_apps

        module = importlib.import_module(
            "apps.observability.migrations.0006_exclude_strategy_from_usage")
        User = get_user_model()
        by_name = User.objects.create_user("washingtone.amolo")
        by_email = User.objects.create_user("andrewy", email="Andrew.Young@hfcb.co.ke")
        other = User.objects.create_user("washingtone.amolo2")
        module.seed(django_apps, None)
        members = set(Group.objects.get(name=module.GROUP).user_set.all())
        self.assertIn(by_name, members)
        self.assertIn(by_email, members)
        self.assertNotIn(other, members)
