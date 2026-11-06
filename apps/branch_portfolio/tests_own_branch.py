"""A branch manager with a blank profile branch is placed by their own address."""

import datetime

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from apps.portfolio.models import Profile
from apps.staff_management.models import StaffEmployeeData

from .own_branch import BRANCH_ROLE, roster_branch
from .views import _branch_filter, _get_profile


def on_hr(email, unit, pf=1):
    StaffEmployeeData.objects.create(
        staff_pf_number=pf, staff_name="x", staff_email=email, department="x",
        staff_unit=unit, staff_org_unit="x", job_title="x",
        employment_date=datetime.date(2020, 1, 1), employee_category="back_office")


class OwnBranchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("amy.k", email="Amy.K@hfcb.co.ke")
        Group.objects.get_or_create(name=BRANCH_ROLE)[0].user_set.add(self.user)
        Profile.objects.update_or_create(user=self.user, defaults={"branch": ""})

    def test_a_blank_profile_is_placed_by_the_roster(self):
        on_hr("amy.k@hfgroup.co.ke", "Nyali Branch")
        self.assertEqual(_branch_filter(_get_profile(self.user)), "NYALI BRANCH")

    def test_nothing_is_saved(self):
        on_hr("amy.k@hfcb.co.ke", "Nyali Branch")
        _get_profile(self.user)
        self.assertFalse(Profile.objects.get(user=self.user).branch)

    def test_the_profile_wins_when_it_has_a_branch(self):
        on_hr("amy.k@hfcb.co.ke", "Nyali Branch")
        Profile.objects.filter(user=self.user).update(branch="KISII BRANCH")
        self.assertEqual(_branch_filter(_get_profile(self.user)), "KISII BRANCH")

    def test_somebody_who_is_not_a_branch_manager_gains_nothing(self):
        on_hr("amy.k@hfcb.co.ke", "Nyali Branch")
        self.user.groups.clear()
        with self.assertRaises(PermissionDenied):
            _branch_filter(_get_profile(self.user))

    def test_a_unit_that_is_not_a_branch_is_not_guessed_at(self):
        on_hr("amy.k@hfcb.co.ke", "Nyali Sub Office")
        self.assertEqual(roster_branch(self.user), "")

    def test_two_answers_place_nobody(self):
        on_hr("amy.k@hfcb.co.ke", "Nyali Branch", pf=1)
        on_hr("amy.k@hfgroup.co.ke", "Kisii Branch", pf=2)
        self.assertEqual(roster_branch(self.user), "")

    def test_a_near_address_is_not_a_match(self):
        on_hr("amy.kariuki@hfcb.co.ke", "Nyali Branch")
        self.assertEqual(roster_branch(self.user), "")
