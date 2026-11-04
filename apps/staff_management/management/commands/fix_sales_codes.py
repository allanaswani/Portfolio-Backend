"""Correct profiles that carry another person's sales code.

    manage.py fix_sales_codes                      # lists every change, saves nothing
    manage.py fix_sales_codes --apply --csv /app/etl_requests/sales_codes_before.csv
    manage.py fix_sales_codes --restore /app/etl_requests/sales_codes_before.csv

The right code is looked up from the account's own address and login on the Branch
Managers page, the Sales Staff page, the HR roster and the reporting lines, and from
its name on a scorecard workbook. It is never taken from the code being replaced.

Each account comes out as one of:

    CHANGE     exactly one code belongs to this person: --apply writes it
    SEVERAL    the records disagree: left alone, for a person to decide
    NO CODE    nothing says this person has a code of their own: left alone

An account in the Strategy group is never listed, since they carry codes on purpose.
Profile has no change history, so --apply needs --csv: that file is the way back.
Keep it under /app/etl_requests, the folder mounted from the host, or it is lost
when the container is recreated.
"""

import csv
import re

from django.core.management.base import BaseCommand, CommandError


def _local(account):
    username = str(account.username or "").strip().lower()
    return username.split("@")[0]


def codes_for(user):
    """Every code this account's own identity leads to → {code: where it was found}."""
    from apps.staff_management.live_scorecard import (
        _name_is_on_account, _workbook_code_for, resolve_person)
    from apps.staff_management.models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData, ScReportingLine,
        StaffEmployeeData)

    email = str(user.email or "").strip()
    local = _local(user)
    found = {}

    def offer(code, where):
        code = str(code or "").strip().upper()
        # A bare number is a PF typed into the code field, which is the fault being
        # corrected, not a code.
        if not code or code.isdigit() or code in found:
            return
        person = resolve_person(code)
        if person is None or _name_is_on_account(user, person.name):
            found[code] = where

    rosters = (
        (BranchFinalEmployeeDmcData.objects.filter(active=1).exclude(exit=1),
         "Branch Managers page"),
        (BranchEmployeeDmcData.objects.exclude(active=0).exclude(staff_exit=1),
         "Sales Staff page"),
        (StaffEmployeeData.objects.all(), "HR roster"),
    )
    for rows, where in rosters:
        matches = rows.none()
        if email:
            matches = matches | rows.filter(staff_email__iexact=email)
        if local:
            matches = matches | rows.filter(staff_email__istartswith=f"{local}@")
        for code in matches.values_list("sales_code", flat=True).distinct():
            offer(code, where)

    lines = ScReportingLine.objects.filter(active=True)
    matches = lines.none()
    if email:
        matches = matches | lines.filter(person_email__iexact=email)
    if local:
        matches = matches | lines.filter(person_email__istartswith=f"{local}@")
    for code in matches.values_list("person_code", flat=True).distinct():
        offer(code, "a workbook List")

    offer(_workbook_code_for(user, None), "their name on a scorecard workbook")
    return found


def spelling_with_a_card(code, stored=None):
    """A roster's code, or the one with a card that it is plainly a misspelling of.

    The Branch Managers page has CKG1784 where the workbook and the actuals template
    have CGK1784. Same first letter and same digits, and only one of them has a card:
    that is the same person. The first letter must match, because PF numbers can
    collide: LMN1452 and NJK1452 are two people.
    """
    from apps.staff_management.models import BoScorecard, SchemeScorecard

    if stored is None:
        stored = {str(c).strip().upper() for c in
                  BoScorecard.objects.values_list("sales_code", flat=True).distinct()}
        stored |= {str(c).strip().upper() for c in
                   SchemeScorecard.objects.values_list("sales_code", flat=True).distinct()}
    if code in stored:
        return code
    digits = re.sub(r"\D", "", code)
    near = {c for c in stored if digits and re.sub(r"\D", "", c) == digits and c[:1] == code[:1]}
    return near.pop() if len(near) == 1 else code


def settled_codes(user):
    """codes_for, with misspellings folded into the code that holds the card."""
    found = {}
    for code, where in codes_for(user).items():
        right = spelling_with_a_card(code)
        note = where if right == code else f"{where}, which misspells it as {code}"
        found.setdefault(right, note)
    return found


def plan():
    """[(profile, current code, whose it is, verdict, new code, where found)]."""
    from apps.staff_management.management.commands.scorecard_reach import (
        mismatched_profiles)

    rows = []
    for profile, person in mismatched_profiles():
        found = settled_codes(profile.user)
        if len(found) == 1:
            code, where = next(iter(found.items()))
            rows.append((profile, person, "CHANGE", code, where))
        elif found:
            rows.append((profile, person, "SEVERAL", "", ", ".join(
                f"{code} ({where})" for code, where in sorted(found.items()))))
        else:
            rows.append((profile, person, "NO CODE", "", ""))
    return rows


class Command(BaseCommand):
    help = "Correct profiles that carry another person's sales code."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Save the CHANGE rows.")
        parser.add_argument("--csv", default="", help="File to keep the old codes in.")
        parser.add_argument("--restore", default="", help="Put back the codes in this file.")

    def handle(self, *args, **options):
        if options["restore"]:
            return self._restore(options["restore"])
        if options["apply"] and not options["csv"]:
            raise CommandError("--apply needs --csv, which is the only way back.")

        rows = plan()
        write = self.stdout.write
        for verdict in ("CHANGE", "SEVERAL", "NO CODE"):
            group = [r for r in rows if r[2] == verdict]
            write(f"\n{verdict}: {len(group)}")
            for profile, person, _verdict, code, where in group:
                was = (profile.sales_code or "").strip()
                arrow = f"-> {code:10} from {where}" if verdict == "CHANGE" else where
                write(f"  {profile.user.username:32} {was:10} ({person.name}) {arrow}")

        changes = [r for r in rows if r[2] == "CHANGE"]
        if not options["apply"]:
            write(f"\nNothing saved. {len(changes)} would change. Add --apply --csv FILE.")
            return

        with open(options["csv"], "w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            writer.writerow(["username", "old_code", "new_code"])
            for profile, _person, _verdict, code, _where in changes:
                writer.writerow([profile.user.username, profile.sales_code or "", code])
        for profile, _person, _verdict, code, _where in changes:
            profile.sales_code = code
            profile.save(update_fields=["sales_code"])
        write(f"\nSaved {len(changes)}. Old codes are in {options['csv']}.")

    def _restore(self, path):
        from apps.portfolio.models import Profile

        with open(path, newline="", encoding="utf-8") as held:
            rows = list(csv.DictReader(held))
        restored = 0
        for row in rows:
            profile = Profile.objects.filter(user__username=row["username"]).first()
            if profile is not None and (profile.sales_code or "") == row["new_code"]:
                profile.sales_code = row["old_code"]
                profile.save(update_fields=["sales_code"])
                restored += 1
        self.stdout.write(f"Restored {restored} of {len(rows)}. A code changed since "
                          f"the correction is left as it is.")
