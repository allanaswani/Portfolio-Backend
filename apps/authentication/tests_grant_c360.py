"""Tests for ``manage.py grant_c360_access``.

The two properties that matter most here are the ones the operator asked for
and the ones that would be security incidents if they broke:

* an existing account is never re-created, never re-passworded, and never
  loses a role it already had;
* leavers and people with no sales code are not provisioned by accident.
"""

import csv
import os
import tempfile
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from apps.portfolio.models import Profile

HEADER = [
    "id", "staff_pf_number", "staff_name", "staff_unit", "staff_role",
    "sales_code", "brn_code", "staff_branch", "staff_zone", "staff_email",
    "team_leader", "employment_date", "start_date", "exit_date", "staff_exit",
    "active", "date_time_etl", "updated_at",
]


def row(**kw):
    base = {
        "id": "1", "staff_pf_number": "1000", "staff_name": "Jane Doe",
        "staff_unit": "Rehani Branch", "staff_role": "PB RM",
        "sales_code": "JD1000", "brn_code": "200",
        "staff_branch": "REHANI BRANCH", "staff_zone": "Zone C",
        "staff_email": "Jane.Doe@hfcb.co.ke", "team_leader": "ANNA",
        "employment_date": "2024-01-01", "start_date": "2026-01-01",
        "exit_date": "2050-01-01", "staff_exit": "0", "active": "1",
        "date_time_etl": "2026-07-29", "updated_at": "2026-08-01",
    }
    base.update(kw)
    return base


class GrantC360AccessTests(TestCase):
    def setUp(self):
        # Groups are seeded by a post_migrate signal, which does not survive
        # into the test database -- seed them explicitly.
        call_command("seed_roles", stdout=StringIO())
        self.role = Group.objects.get(name="c360_rm")
        self._paths = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def csv_file(self, rows):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                         newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
        fh.close()
        self._paths.append(fh.name)
        return fh.name

    def run_cmd(self, rows, **opts):
        out = StringIO()
        call_command("grant_c360_access", csv=self.csv_file(rows), stdout=out,
                     stderr=StringIO(), **opts)
        return out.getvalue()

    # ------------------------------------------------------------- creation
    def test_creates_the_account_with_only_the_c360_role(self):
        self.run_cmd([row()])

        user = User.objects.get(username="jane.doe")
        self.assertEqual(user.email, "Jane.Doe@hfcb.co.ke")
        self.assertEqual((user.first_name, user.last_name), ("Jane", "Doe"))
        self.assertTrue(user.is_active)
        # "view of customer 360 only" -- no Django admin rights, one group.
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["c360_rm"])

        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.sales_code, "JD1000")
        self.assertEqual(profile.branch, "REHANI BRANCH")

    def test_new_accounts_have_no_usable_password_and_get_no_mail_by_default(self):
        """No password is set or emailed -- users go through 'Forgot password?'."""
        self.run_cmd([row()])
        self.assertFalse(User.objects.get(username="jane.doe").has_usable_password())
        self.assertEqual(len(mail.outbox), 0)

    def test_email_credentials_matches_the_users_screen_flow(self):
        """The Users screen mails a temporary password on create; --email-credentials
        does the same thing for accounts this command creates."""
        self.run_cmd([row()], email_credentials=True)

        user = User.objects.get(username="jane.doe")
        self.assertTrue(user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("jane.doe", body)
        self.assertIn("Temporary password:", body)
        # The password that was mailed is the one that actually works.
        sent = body.split("Temporary password:")[1].split("\n")[0].strip()
        self.assertTrue(user.check_password(sent))

    def test_nobody_who_already_had_an_account_is_ever_mailed(self):
        """The whole point of the run is that existing people are left alone --
        mailing them a new password would lock them out of their own account."""
        existing = User.objects.create_user(
            username="jane.doe", email="jane.doe@hfcb.co.ke", password="Original#123"
        )
        # create_user fires the portfolio post_save handler, which sends its own
        # account-created mail. That one is not ours -- start counting from here.
        mail.outbox = []

        self.run_cmd([row()], email_credentials=True)

        existing.refresh_from_db()
        self.assertTrue(existing.check_password("Original#123"))
        self.assertEqual(len(mail.outbox), 0)

    def test_email_welcome_sends_a_notice_without_a_password(self):
        self.run_cmd([row()], email_welcome=True)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("jane.doe", body)
        self.assertIn("Forgot password?", body)

    # ---------------------------------------------------------- idempotence
    def test_an_existing_account_is_not_recreated_or_repassworded(self):
        existing = User.objects.create_user(
            username="jane.doe", email="jane.doe@hfcb.co.ke", password="Original#123"
        )
        Profile.objects.update_or_create(user=existing, defaults={"sales_code": "OLD1"})

        self.run_cmd([row()])

        self.assertEqual(User.objects.filter(email__iexact="jane.doe@hfcb.co.ke").count(), 1)
        existing.refresh_from_db()
        self.assertTrue(existing.check_password("Original#123"))
        # ...and they gained Customer 360 access.
        self.assertTrue(existing.groups.filter(name="c360_rm").exists())

    def test_an_existing_users_other_roles_survive(self):
        existing = User.objects.create_user(username="jane.doe", email="jane.doe@hfcb.co.ke")
        existing.groups.add(Group.objects.get(name="portfolio_mgt"))

        self.run_cmd([row()])

        names = set(existing.groups.values_list("name", flat=True))
        self.assertEqual(names, {"portfolio_mgt", "c360_rm"})

    def test_an_existing_sales_code_is_never_overwritten(self):
        """The DMC export is not authoritative over a code an operator set."""
        existing = User.objects.create_user(username="jane.doe", email="jane.doe@hfcb.co.ke")
        Profile.objects.update_or_create(user=existing, defaults={"sales_code": "KEEPME"})

        self.run_cmd([row(sales_code="JD1000")])

        self.assertEqual(Profile.objects.get(user=existing).sales_code, "KEEPME")

    def test_a_blank_existing_sales_code_is_filled_in(self):
        existing = User.objects.create_user(username="jane.doe", email="jane.doe@hfcb.co.ke")
        Profile.objects.update_or_create(user=existing, defaults={"sales_code": ""})

        self.run_cmd([row(sales_code="JD1000")])

        self.assertEqual(Profile.objects.get(user=existing).sales_code, "JD1000")

    def test_running_twice_changes_nothing_the_second_time(self):
        rows = [row()]
        self.run_cmd(rows)
        out = self.run_cmd(rows)

        self.assertEqual(User.objects.filter(username="jane.doe").count(), 1)
        self.assertIn("already had 'c360_rm': 1", out)

    def test_matching_is_on_email_even_when_the_username_differs(self):
        existing = User.objects.create_user(username="jdoe", email="JANE.DOE@hfcb.co.ke")

        self.run_cmd([row()])

        self.assertFalse(User.objects.filter(username="jane.doe").exists())
        self.assertTrue(existing.groups.filter(name="c360_rm").exists())

    # -------------------------------------------------------------- guards
    def test_exited_staff_are_skipped_by_default(self):
        self.run_cmd([row(staff_exit="1", active="0")])
        self.assertFalse(User.objects.filter(username="jane.doe").exists())

    def test_exited_staff_are_provisioned_only_when_asked_for(self):
        self.run_cmd([row(staff_exit="1", active="0")], include_exited=True)
        self.assertTrue(User.objects.filter(username="jane.doe").exists())

    def test_people_with_no_sales_code_are_skipped_by_default(self):
        """c360_rm scopes an officer's book BY sales code -- a blank one is a
        question for the Customer 360 repo, not something to guess at here."""
        self.run_cmd([row(sales_code="")])
        self.assertFalse(User.objects.filter(username="jane.doe").exists())

    def test_blank_sales_codes_can_be_allowed_explicitly(self):
        self.run_cmd([row(sales_code="")], allow_blank_sales_code=True)
        self.assertTrue(User.objects.filter(username="jane.doe").exists())

    def test_dry_run_writes_nothing(self):
        out = self.run_cmd([row()], dry_run=True)
        self.assertEqual(User.objects.filter(username="jane.doe").count(), 0)
        self.assertIn("DRY RUN", out)

    def test_an_unknown_role_is_rejected(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_cmd([row()], role="not_a_real_role")

    # --------------------------------------------------------- data hygiene
    def test_duplicate_rows_make_one_user_and_keep_the_sales_code(self):
        """The export repeats people; the newest row wins, but a sales code on
        an older row is still picked up (the re-issued-teller-code case)."""
        rows = [
            row(id="2", sales_code="", updated_at="2026-08-14", staff_role="TELLER"),
            row(id="1", sales_code="EM4396", updated_at="2026-07-02", staff_role="TELLER"),
        ]
        self.run_cmd(rows)

        self.assertEqual(User.objects.filter(email__iexact="jane.doe@hfcb.co.ke").count(), 1)
        user = User.objects.get(username="jane.doe")
        self.assertEqual(Profile.objects.get(user=user).sales_code, "EM4396")

    def test_a_branch_outside_the_choice_list_is_left_blank(self):
        """Writing an off-list value silently breaks every branch dropdown."""
        self.run_cmd([row(staff_branch="SOMEWHERE THAT CLOSED")])

        user = User.objects.get(username="jane.doe")
        self.assertIn(Profile.objects.get(user=user).branch, ("", None))

    def test_the_units_that_only_exist_in_the_dmc_roster_are_postable(self):
        """HFDI and Harambee Ave carry staff but were missing from
        BRANCH_CHOICES, so 58 people could not be given a posting at all."""
        for unit in ("HFDI", "HARAMBEE AVE BRANCH"):
            with self.subTest(unit=unit):
                User.objects.all().delete()
                self.run_cmd([row(staff_branch=unit)])
                user = User.objects.get(username="jane.doe")
                self.assertEqual(Profile.objects.get(user=user).branch, unit)

    def test_known_branch_aliases_are_mapped_to_the_choice_list(self):
        self.run_cmd([row(staff_branch="SAMEER BUSINESS PARK BRANCH")])

        user = User.objects.get(username="jane.doe")
        self.assertEqual(Profile.objects.get(user=user).branch, "SAMEER BRANCH")

    def test_a_username_collision_gets_a_suffix(self):
        """Someone unrelated already owns the natural username."""
        User.objects.create_user(username="jane.doe", email="other.person@hfcb.co.ke")

        self.run_cmd([row()])

        self.assertTrue(User.objects.filter(username="jane.doe2").exists())
        self.assertEqual(
            User.objects.get(username="jane.doe2").email, "Jane.Doe@hfcb.co.ke"
        )

    def test_a_username_match_is_only_trusted_when_the_account_has_no_email(self):
        """Legacy accounts often carry no address; those are the same person.
        An account with a *different* address is not -- see the collision test."""
        legacy = User.objects.create_user(username="jane.doe", email="")

        self.run_cmd([row()])

        legacy.refresh_from_db()
        self.assertEqual(User.objects.filter(username__startswith="jane.doe").count(), 1)
        self.assertTrue(legacy.groups.filter(name="c360_rm").exists())
        self.assertEqual(legacy.email, "Jane.Doe@hfcb.co.ke")

    # -------------------------------------------------------------- sources
    def test_from_db_reads_the_roster_table_with_no_csv(self):
        """The server has no copy of the export; the table is already here."""
        from apps.staff_management.models import BranchEmployeeDmcData

        BranchEmployeeDmcData.objects.create(
            staff_pf_number=1000, staff_name="Jane Doe", staff_role="PB RM",
            sales_code="JD1000", staff_branch="REHANI BRANCH",
            staff_email="Jane.Doe@hfcb.co.ke", staff_exit=0, active=1,
        )
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=9, staff_name="Gone Away", staff_role="TELLER",
            sales_code="GA9", staff_branch="MERU BRANCH",
            staff_email="gone.away@hfcb.co.ke", staff_exit=1, active=0,
        )

        out = StringIO()
        call_command("grant_c360_access", from_db=True, stdout=out, stderr=StringIO())

        self.assertIn("branch_employee_dmc_data", out.getvalue())
        user = User.objects.get(username="jane.doe")
        self.assertEqual(Profile.objects.get(user=user).sales_code, "JD1000")
        self.assertTrue(user.groups.filter(name="c360_rm").exists())
        # The leaver is still skipped when the rows come from the table.
        self.assertFalse(User.objects.filter(username="gone.away").exists())

    def test_exactly_one_source_is_required(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("grant_c360_access", stdout=StringIO(), stderr=StringIO())
        with self.assertRaises(CommandError):
            self.run_cmd([row()], from_db=True)

    def test_an_empty_roster_table_is_an_error_not_a_silent_no_op(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("grant_c360_access", from_db=True,
                         stdout=StringIO(), stderr=StringIO())

    def test_a_typo_domain_is_flagged(self):
        out = self.run_cmd([row(staff_email="faith.minoo@hfcb.occo.ke")])
        self.assertIn("suspect email domain", out)

    def test_the_report_lists_every_person_and_every_skip(self):
        report = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        report.close()
        self._paths.append(report.name)

        self.run_cmd(
            [row(), row(id="9", staff_pf_number="9", staff_name="Gone Away",
                        staff_email="gone.away@hfcb.co.ke", sales_code="GA9",
                        staff_exit="1", active="0")],
            report=report.name,
        )

        with open(report.name, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        actions = {r["email"]: r["action"] for r in rows}
        self.assertEqual(actions["Jane.Doe@hfcb.co.ke"], "created")
        self.assertEqual(actions["gone.away@hfcb.co.ke"], "skipped: exited/inactive")
