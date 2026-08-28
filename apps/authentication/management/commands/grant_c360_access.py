"""Bulk-provision Customer 360 accounts from a DMC staff export.

Reads the ``branch_employee_dmc_data`` CSV (one row per sales staff member) and,
for each person, makes sure a portfolio account exists and carries the Customer
360 role — nothing else.

Why a command and not the Users screen: the export is ~800 rows, and the screen
creates one user per request. This does the same work through the same code
path (``_apply_profile`` + ``muted_profile_signals``), just in bulk and
idempotently.

Idempotent by design — the whole point of "if already created don't create":

* A person is matched on ``email`` first, then ``username`` (both case
  insensitive). A match is NEVER re-created and NEVER has their password,
  names, flags or existing roles touched. They only gain the Customer 360
  group if they do not already have it.
* ``sales_code`` is filled in only when the profile has none. An existing sales
  code is left alone — it is what Customer 360 scopes an officer's book by, and
  the DMC export is not authoritative over a code an operator set by hand.
* Re-running after a partial run reconciles; it does not duplicate.

Two guards that are deliberately conservative, because both failure modes are
security incidents rather than inconveniences:

* **Exited staff are skipped.** The export carries leavers (``staff_exit=1`` /
  ``active=0``) — over a third of the file. Creating live accounts for people
  who have left the bank is not something to do by accident, so it takes an
  explicit ``--include-exited``.
* **People with no sales code are skipped.** ``c360_rm`` is an OFFICER-tier
  role, and Customer 360 resolves an officer's book *from their sales code*
  (see ``core/roles.py``). What that app does with an officer whose sales code
  is blank is decided in that repo, not this one — and "might be the whole
  book" is not a risk worth taking silently. ``--allow-blank-sales-code``
  overrides.

The roster is ``branch_employee_dmc_data``, which is already in this database —
so on the server ``--from-db`` needs no file copied in and can never be run
against a stale download. ``--csv`` stays for provisioning from a file the
table does not carry yet.

Handing over a new account, matching the two flows the app already has:

* ``--email-credentials`` mails a temporary password, exactly as the Users
  screen does (``AdminUserListCreateView``).
* ``--email-welcome`` mails only the username and points at "Forgot password?".
* Neither: the account is created with no usable password and nobody is told.

All three touch NEW accounts only. Anyone who already had an account keeps
their password and is never mailed -- sending them a fresh one would lock them
out of an account they are already using.

Usage::

    python manage.py grant_c360_access --from-db --dry-run
    python manage.py grant_c360_access --from-db --report /tmp/c360.csv
    python manage.py grant_c360_access --from-db --email-credentials
"""

import csv
import os
import re

from django.contrib.auth.models import Group, User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.authentication.serializers import _generate_password
from apps.authentication.views import _email_temp_password
from core.roles import ALL_ROLES
from core.signals import muted_profile_signals

# Customer 360 -- officer tier, own book by sales code. See core/roles.py.
DEFAULT_ROLE = "c360_rm"

# Values the warehouse export uses for "this cell is empty".
NULLS = {"", "null", "none", "nan", "\\n"}

# Branch names in the export vs the Profile.branch choice list
# (apps/portfolio/models.py::BRANCH_CHOICES). Only unambiguous renames belong
# here. Anything still unmatched after this map is left BLANK rather than
# written through -- an off-list value silently breaks the branch dropdown and
# every branch filter that trusts the choice list.
BRANCH_ALIASES = {
    "SAMEER BUSINESS PARK BRANCH": "SAMEER BRANCH",
    "THIKA ROAD MALL-TRM BRANCH": "TRM BRANCH",
    "HEAD OFFICE": "HEAD OFFICE BRANCH",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# The export is hand-maintained and carries the odd typo'd domain
# ("...@hfcb", "...@hfcb.occo.ke"). Those addresses parse fine but no
# password-reset mail will ever reach them, so the account would be created and
# then be unusable. Flag them instead of pretending they are provisioned.
KNOWN_DOMAINS = {"hfcb.co.ke", "hfgroup.co.ke", "housingfinance.co.ke"}


def clean(value):
    """Trim a warehouse cell and normalise its many spellings of NULL to ''.

    Takes ints and dates as well as strings, because the same records arrive
    either from a CSV export (all text) or straight off the model (typed).
    """
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() in NULLS else value


def split_name(full_name):
    """``"Sheila Atuti"`` -> ``("Sheila", "Atuti")``; extra words join the surname."""
    parts = [p for p in clean(full_name).split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def row_sort_key(row):
    """Newest-first ordering for the rows belonging to one person.

    People appear more than once in the export -- a teller re-issued a sales
    code, a Property Advisor re-titled as an HFDI PA. The most recently updated
    row is the one that carries the current sales code, so it wins.
    """
    return (
        clean(row.get("updated_at")),
        clean(row.get("date_time_etl")),
        clean(row.get("id")).zfill(12),
    )


class Command(BaseCommand):
    help = "Create/refresh portfolio accounts for a staff CSV and give them Customer 360 access."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", default="",
            help="Path to a staff CSV export. Use this only when the table is not "
                 "reachable; --from-db needs no file transfer and is never stale.",
        )
        parser.add_argument(
            "--from-db", action="store_true",
            help="Read the staff roster straight from branch_employee_dmc_data "
                 "instead of a CSV. Preferred on the server.",
        )
        parser.add_argument(
            "--role", default=DEFAULT_ROLE,
            help=f"Role (Django Group) to grant. Default: {DEFAULT_ROLE}.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report the full plan without writing anything.",
        )
        parser.add_argument(
            "--include-exited", action="store_true",
            help="Also provision staff the export marks as exited/inactive.",
        )
        parser.add_argument(
            "--allow-blank-sales-code", action="store_true",
            help="Provision people with no sales code (their Customer 360 book scope "
                 "is then whatever that app does with a blank code -- check first).",
        )
        parser.add_argument(
            "--email-credentials", action="store_true",
            help="Email NEWLY created users a temporary password, the same way the "
                 "Users screen does. Only new accounts -- never anyone who already "
                 "had one.",
        )
        parser.add_argument(
            "--email-welcome", action="store_true",
            help="Email NEWLY created users their username and tell them to use "
                 "'Forgot password?'. No password is ever emailed.",
        )
        parser.add_argument(
            "--report", default="",
            help="Write a per-person CSV of what happened to this path.",
        )

    # ------------------------------------------------------------------ read
    # The roster this reads is ``branch_employee_dmc_data``. It is already in
    # the application database, so on the server there is nothing to copy
    # in -- and reading it live means the run can never be against a stale
    # export somebody downloaded weeks ago. The CSV path stays for the case
    # where you want to provision from a file the table does not have yet.
    DB_FIELDS = (
        "id", "staff_pf_number", "staff_name", "staff_role", "sales_code",
        "staff_branch", "staff_email", "staff_exit", "active",
        "date_time_etl", "updated_at",
    )

    def _rows_from_db(self):
        from apps.staff_management.models import BranchEmployeeDmcData

        rows = list(BranchEmployeeDmcData.objects.values(*self.DB_FIELDS))
        if not rows:
            raise CommandError(
                "branch_employee_dmc_data has no rows. Either the DMC load has "
                "not run, or you are pointed at the wrong database."
            )
        return rows

    def _rows_from_csv(self, path):
        if not os.path.exists(path):
            raise CommandError(f"CSV not found: {path}")

        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise CommandError("CSV has no data rows.")

        required = {"staff_email", "staff_name", "sales_code", "active", "staff_exit"}
        missing = required - set(rows[0].keys())
        if missing:
            raise CommandError(f"CSV is missing required column(s): {', '.join(sorted(missing))}")
        return rows

    def _load(self, rows, include_exited, allow_blank_code):
        """Roster rows -> one record per person, newest row wins, skips explained."""
        people, skipped = {}, []

        for row in rows:
            email = clean(row.get("staff_email"))
            if not email:
                skipped.append(("no email", clean(row.get("staff_name")) or "?", ""))
                continue
            people.setdefault(email.lower(), []).append(row)

        records = []
        for key, group in people.items():
            group.sort(key=row_sort_key, reverse=True)
            newest = group[0]
            name = clean(newest.get("staff_name"))

            exited = (clean(newest.get("staff_exit")) == "1"
                      or clean(newest.get("active")) == "0")
            if exited and not include_exited:
                skipped.append(("exited/inactive", name, key))
                continue

            # A person's sales code may sit on an older row than their newest
            # one (the teller re-issue case), so take the newest row that has
            # one rather than only the newest row.
            sales_code = ""
            for row in group:
                if clean(row.get("sales_code")):
                    sales_code = clean(row.get("sales_code"))
                    break
            if not sales_code and not allow_blank_code:
                skipped.append(("no sales code", name, key))
                continue

            first, last = split_name(name)
            raw_branch = clean(newest.get("staff_branch")).upper()
            branch = BRANCH_ALIASES.get(raw_branch, raw_branch)

            records.append({
                # Their own address as spelled on the newest row -- NOT the
                # loop variable from the grouping pass above, which by now
                # holds whichever row the file happened to end on.
                "email": clean(newest.get("staff_email")),
                "username": key.split("@")[0],
                "first_name": first,
                "last_name": last,
                "sales_code": sales_code,
                "branch": branch,
                "raw_branch": raw_branch,
                "pf": clean(newest.get("staff_pf_number")),
                "role_title": clean(newest.get("staff_role")),
            })

        records.sort(key=lambda r: r["username"])
        return records, skipped

    # --------------------------------------------------------------- helpers
    def _valid_branches(self):
        from apps.portfolio.models import BRANCH_CHOICES
        return {value for value, _ in BRANCH_CHOICES}

    def _free_username(self, base, taken):
        """``base``, or ``base2``/``base3``... if the portal already has it."""
        candidate = base
        suffix = 2
        while candidate.lower() in taken:
            candidate = f"{base}{suffix}"
            suffix += 1
        taken.add(candidate.lower())
        return candidate

    def _welcome(self, user):
        # Reuse the branding and the both-networks link block the rest of the
        # auth emails use, so this does not become a second, drifting template.
        from apps.authentication.views import _access_links_block, _brand

        try:
            send_mail(
                subject=f"Your {_brand()} Customer 360 account",
                message=(
                    f"Hi {user.first_name or user.username},\n\n"
                    f"An account has been created for you to access Customer 360.\n\n"
                    f"\tUsername: {user.username}\n\n"
                    f"For security no password is sent by email. Use the "
                    f'"Forgot password?" link on the login page to set yours, '
                    f"then sign in.\n\n"
                    f"{_access_links_block()}\n"
                ),
                from_email="reports.analytics@hfgroup.co.ke",
                recipient_list=[user.email],
                fail_silently=True,
            )
            return True
        except Exception:                                    # pragma: no cover
            self.stderr.write(f"  ! welcome email failed for {user.email}")
            return False

    # ------------------------------------------------------------------ main
    def handle(self, *args, **opts):
        role_name = opts["role"]
        dry_run = opts["dry_run"]

        if role_name not in ALL_ROLES:
            raise CommandError(
                f"Unknown role '{role_name}'. It must be one of core.roles.ALL_ROLES."
            )
        try:
            role = Group.objects.get(name=role_name)
        except Group.DoesNotExist:
            raise CommandError(
                f"Role '{role_name}' has no Group row yet. Run "
                f"`python manage.py seed_roles` first -- roles are seeded by a "
                f"post_migrate signal, not by a migration file."
            )

        if bool(opts["csv"]) == bool(opts["from_db"]):
            raise CommandError("Pass exactly one of --from-db or --csv <path>.")

        if opts["from_db"]:
            rows = self._rows_from_db()
            source = "branch_employee_dmc_data"
        else:
            rows = self._rows_from_csv(opts["csv"])
            source = opts["csv"]

        records, skipped = self._load(
            rows, opts["include_exited"], opts["allow_blank_sales_code"]
        )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Source: {source} ({len(rows)} rows)."
        ))
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{len(records)} people to provision with '{role_name}'; "
            f"{len(skipped)} row(s) skipped."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN -- nothing will be written."))

        valid_branches = self._valid_branches()
        taken = {u.lower() for u in User.objects.values_list("username", flat=True)}

        results = []
        created = existing = granted = already = mailed = 0

        # One transaction: a half-provisioned run is worse than none, and the
        # command is cheap to re-run.
        with transaction.atomic():
            # The portfolio post_save handler auto-creates a Profile and emails
            # the new user. We create the Profile ourselves and send (or
            # suppress) our own mail, so both must be off.
            with muted_profile_signals():
                for rec in records:
                    note = ""
                    user = User.objects.filter(email__iexact=rec["email"]).first()
                    if user is None:
                        # Fall back to the username, but ONLY for an account
                        # that has no email of its own. A same-username account
                        # with a DIFFERENT address is a different person --
                        # merging them would hand this record's Customer 360
                        # access to a stranger and leave the real person
                        # without an account.
                        candidate = User.objects.filter(
                            username__iexact=rec["username"]).first()
                        if candidate is not None and not (candidate.email or "").strip():
                            user = candidate
                            note = "matched an existing account by username; filled in its email"

                    branch = rec["branch"] if rec["branch"] in valid_branches else ""
                    if rec["raw_branch"] and not branch:
                        note = f"branch '{rec['raw_branch']}' not in BRANCH_CHOICES - left blank"
                    domain = rec["email"].rsplit("@", 1)[-1].lower()
                    if not EMAIL_RE.match(rec["email"]) or domain not in KNOWN_DOMAINS:
                        note = (note + "; " if note else "") + \
                            f"suspect email domain '{domain}' - password reset will not reach them"

                    if user is None:
                        action = "created"
                        created += 1
                        username = self._free_username(rec["username"], taken)
                        if not dry_run:
                            user = User(
                                username=username,
                                email=rec["email"],
                                first_name=rec["first_name"],
                                last_name=rec["last_name"],
                                is_active=True,
                                is_staff=False,
                                is_superuser=False,
                            )
                            # Two ways to hand over an account, matching the two
                            # the app already has:
                            #   --email-credentials -> the Users screen's flow
                            #       (AdminUserListCreateView): generate a
                            #       temporary password and mail it.
                            #   otherwise -> no usable password at all; the
                            #       person sets their own through "Forgot
                            #       password?". This is the default because a
                            #       bulk run can put hundreds of passwords in
                            #       hundreds of inboxes in one keystroke.
                            raw = _generate_password() if opts["email_credentials"] else None
                            if raw:
                                user.set_password(raw)
                            else:
                                user.set_unusable_password()
                            user.save()
                            self._apply(user, rec["sales_code"], branch)
                            user.groups.add(role)
                            if raw:
                                _email_temp_password(user.email, user.username, raw)
                                mailed += 1
                            elif opts["email_welcome"]:
                                self._welcome(user)
                                mailed += 1
                        granted += 1
                    else:
                        action = "existing"
                        existing += 1
                        username = user.username
                        has_role = user.groups.filter(pk=role.pk).exists()
                        if has_role:
                            already += 1
                            action = "existing (already had role)"
                        else:
                            granted += 1
                            action = "existing (role granted)"
                        if not dry_run and not has_role:
                            user.groups.add(role)
                        if not dry_run:
                            # An account with no address can never receive a
                            # password reset, so fill that one gap. Everything
                            # else about an existing user is left alone.
                            if not (user.email or "").strip():
                                user.email = rec["email"]
                                user.save(update_fields=["email"])
                            # Fill gaps only -- never overwrite what is there.
                            self._apply(user, rec["sales_code"], branch, fill_only=True)

                    results.append({
                        "action": action,
                        "username": username,
                        "email": rec["email"],
                        "name": f"{rec['first_name']} {rec['last_name']}".strip(),
                        "pf": rec["pf"],
                        "sales_code": rec["sales_code"],
                        "branch": branch or rec["raw_branch"],
                        "staff_role": rec["role_title"],
                        "note": note,
                    })

            if dry_run:
                transaction.set_rollback(True)

        for reason, name, email in skipped:
            results.append({
                "action": f"skipped: {reason}", "username": "", "email": email,
                "name": name, "pf": "", "sales_code": "", "branch": "",
                "staff_role": "", "note": "",
            })

        self._summarise(results, skipped, created, existing, granted, already,
                        mailed, role_name, dry_run, opts["report"])

    def _apply(self, user, sales_code, branch, fill_only=False):
        from apps.authentication.serializers import _apply_profile
        from apps.portfolio.models import Profile

        if fill_only:
            profile = Profile.objects.filter(user=user).first()
            if profile is not None:
                sales_code = sales_code if not clean(profile.sales_code) else None
                branch = branch if not clean(profile.branch) else None
        _apply_profile(user, sales_code or None, branch or None, None)

    def _summarise(self, results, skipped, created, existing, granted, already,
                   mailed, role_name, dry_run, report_path):
        import collections

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(f"  created                 : {created}")
        self.stdout.write(f"  already existed         : {existing}")
        self.stdout.write(f"  '{role_name}' granted    : {granted}")
        self.stdout.write(f"  already had '{role_name}': {already}")
        self.stdout.write(f"  emails sent             : {mailed}")
        self.stdout.write(f"  skipped                 : {len(skipped)}")
        for reason, count in collections.Counter(r for r, _, _ in skipped).most_common():
            self.stdout.write(f"      {reason}: {count}")

        flagged = [r for r in results if r["note"]]
        if flagged:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"{len(flagged)} record(s) need a look:"))
            for r in flagged[:20]:
                self.stdout.write(f"  {r['username'] or r['email']}: {r['note']}")
            if len(flagged) > 20:
                self.stdout.write(f"  ... and {len(flagged) - 20} more (see --report)")

        if report_path and results:
            with open(report_path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
                writer.writeheader()
                writer.writerows(results)
            self.stdout.write("")
            self.stdout.write(f"Report written to {report_path}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN -- nothing was written."))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Done."))
