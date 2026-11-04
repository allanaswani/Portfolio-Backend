"""Can everybody on a scorecard workbook actually open their card?

    manage.py scorecard_reach                # everybody, grouped by workbook
    manage.py scorecard_reach --only-broken
    manage.py scorecard_reach --csv /tmp/reach.csv
    manage.py scorecard_reach --link         # fix the ones that can be proven
    manage.py scorecard_reach --mismatched   # profiles carrying another person's code

A card is for the person a workbook's List names. They reach it from their own
login, through the same ``resolve_sales_code_for_user`` the page uses, whichever
module they were given - so what matters is whether a login leads to that code.

Each person comes out as one of:

    OK               a login opens this card
    NO LOGIN         no account reaches this code: nobody can open it
    OTHER CODE       an account proven to be theirs opens a different card

"Proven" means by an exact identifier: the PF number on the List, then the HR
roster's row for it, then that row's address on an account. A name is never
enough, since two people share one often enough. ``--link`` writes the sales
code onto the profile of a proven account, which the page tries first, and
leaves everybody else for Administration. Without it nothing is written.
"""

import csv

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

BOOK_NAMES = {"back_office": "Back office", "sales": "Sales",
              "branch_business": "Branch managers"}


def workbook_people():
    """Everybody on a stored workbook → [{book, code, name, role, pf}] plus the
    workbooks that are not loaded."""
    from apps.staff_management import workbook_cards as wc
    from apps.staff_management.models import SchemeScorecard

    people, missing = [], []
    for spec in wc.SPECS.values():
        title = BOOK_NAMES.get(spec.book, spec.book)
        book = wc.saved(spec.files[0])
        if book is None:
            missing.append(title)
            continue
        for holder in wc.holders(book):
            if holder.sales_code:
                people.append({"book": title, "code": holder.sales_code,
                               "name": holder.name,
                               "role": holder.role or holder.sheet or "",
                               "pf": holder.pf})
    scheme = {}
    for code, name, sheet in (SchemeScorecard.objects.order_by("month")
                              .values_list("sales_code", "staff_name", "sheet")):
        scheme[code.upper()] = {"book": "Scheme", "code": code.upper(),
                                "name": name, "role": sheet, "pf": ""}
    if scheme:
        people += list(scheme.values())
    else:
        missing.append("Scheme")
    return people, missing


def logins_by_code():
    """Sales code → the active accounts that open it, as the page resolves it."""
    from apps.portfolio.models import Profile
    from apps.staff_management.live_scorecard import resolve_sales_code_for_user

    profiles = {p.user_id: p for p in Profile.objects.all()}
    reached, code_of = {}, {}
    for user in get_user_model().objects.filter(is_active=True):
        code, _how = resolve_sales_code_for_user(user, profiles.get(user.id))
        if code:
            reached.setdefault(code.upper(), []).append(user)
            code_of[user.id] = code.upper()
    return reached, code_of


def proven_account(pf, accounts_by_local):
    """The one account an exact PF number leads to, or None."""
    from apps.staff_management.models import StaffEmployeeData

    if not str(pf or "").isdigit():
        return None
    row = StaffEmployeeData.objects.filter(staff_pf_number=int(pf)).first()
    if row is None or not row.staff_email:
        return None
    found = accounts_by_local.get(row.staff_email.strip().lower().split("@")[0], [])
    return found[0] if len(found) == 1 else None


def _where_listed(person):
    """Which roster holds this person, and the address to make an account with.
    "No login" is about accounts: the person may well be on the Sales Staff page."""
    from apps.staff_management.models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData, StaffEmployeeData)

    manager = BranchFinalEmployeeDmcData.objects.filter(
        sales_code__iexact=person["code"]).first()
    if manager is not None:
        return f"Branch Managers page: {manager.staff_email or 'no address'}"
    row = BranchEmployeeDmcData.objects.filter(
        sales_code__iexact=person["code"]).first()
    if row is None and str(person["pf"] or "").isdigit():
        row = BranchEmployeeDmcData.objects.filter(
            staff_pf_number=int(person["pf"])).first()
    if row is not None:
        return f"Sales Staff page: {row.staff_email or 'no address'}"
    hr = StaffEmployeeData.objects.filter(sales_code__iexact=person["code"]).first()
    if hr is not None:
        return f"HR roster: {hr.staff_email or 'no address'}"
    return "on no roster"


class Command(BaseCommand):
    help = "Check every person on a scorecard workbook can open their card."

    def add_arguments(self, parser):
        parser.add_argument("--only-broken", action="store_true")
        parser.add_argument("--csv", default="")
        parser.add_argument("--mismatched", action="store_true",
                            help="List profiles carrying another person's code.")
        parser.add_argument("--link", action="store_true",
                            help="Set the sales code on accounts proven by PF.")

    def _mismatched(self):
        """Accounts whose profile code belongs to somebody with another name.

        The card no longer follows such a code, but the rest of the system still
        does: the RM pages and Customer 360 scope on Profile.sales_code. Whether
        one is deliberate is for Administration to say, so this only lists them.
        """
        from apps.portfolio.models import Profile
        from apps.staff_management.live_scorecard import (
            name_fits_account, resolve_person)

        write = self.stdout.write
        found = 0
        for profile in (Profile.objects.select_related("user")
                        .filter(user__is_active=True)
                        .exclude(sales_code__isnull=True).exclude(sales_code="")):
            person = resolve_person(profile.sales_code.strip())
            if person is not None and not name_fits_account(profile.user, person.name):
                found += 1
                write(f"  {profile.user.username:28} carries "
                      f"{profile.sales_code.strip():10} which is {person.name} "
                      f"({person.roster})")
        write(f"  {found} account(s).")

    def handle(self, *args, **options):
        from apps.portfolio.models import Profile

        if options["mismatched"]:
            return self._mismatched()

        people, missing = workbook_people()
        reached, code_of = logins_by_code()

        by_local = {}
        for user in get_user_model().objects.filter(is_active=True):
            names = {user.username.lower(),
                     (user.email or "").strip().lower().split("@")[0]}
            for name in names - {""}:
                by_local.setdefault(name, []).append(user)

        rows = []
        for person in people:
            accounts = reached.get(person["code"], [])
            proven = None if accounts else proven_account(person["pf"], by_local)
            if accounts:
                verdict, note = "OK", ", ".join(u.username for u in accounts)
            elif proven is not None:
                verdict = "OTHER CODE"
                note = (f"{proven.username} opens "
                        f"{code_of.get(proven.id, 'nothing')}")
                if options["link"]:
                    Profile.objects.update_or_create(
                        user=proven, defaults={"sales_code": person["code"]})
                    note += " - linked"
            else:
                verdict, note = "NO LOGIN", _where_listed(person)
            rows.append({**person, "verdict": verdict, "note": note})

        write = self.stdout.write
        write("")
        if missing:
            write(self.style.WARNING(
                f"  NOT LOADED, so nobody on it can be checked: "
                f"{', '.join(missing)}. Scorecards -> Figures to load."))
            write("")
        for title in sorted({r["book"] for r in rows}):
            group = [r for r in rows if r["book"] == title]
            good = sum(1 for r in group if r["verdict"] == "OK")
            write(f"  {title}: {good} of {len(group)} can open their card")
            for row in group:
                if options["only_broken"] and row["verdict"] == "OK":
                    continue
                write(f"    {row['verdict']:11} {row['code']:10} "
                      f"{str(row['name'])[:30]:30} {str(row['role'])[:24]:24} "
                      f"{row['note']}")
            write("")
        if options["csv"] and rows:
            with open(options["csv"], "w", newline="", encoding="utf-8") as out:
                writer = csv.DictWriter(out, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            write(f"  wrote {options['csv']}")
        write("  NO LOGIN: Administration -> Users, find or create the person's "
              "account and put the code above on their profile.")
        write("")
