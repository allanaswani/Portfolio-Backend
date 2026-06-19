"""
Migrate users, roles and profiles from the legacy datawarehouse DB into the new
backend's ``default`` database — WITHOUT losing anyone or their defined roles.

What it copies (legacy alias -> default):
    auth_user           -> users (username, email, names, password HASH, flags,
                                   date_joined, last_login)  [password not re-hashed]
    auth_group          -> roles (group names)
    auth_user_groups    -> role memberships (verbatim)
    portfolio_profile   -> profiles (sales_code, branch, segment)

Safety properties:
    * Idempotent — matches on natural keys (username / group name) via
      update_or_create, so re-running reconciles instead of duplicating.
    * Signal-safe — disconnects the Profile post_save signal so migrating users
      does NOT email every production user a welcome/password message.
    * Password hashes are copied verbatim; users keep their existing passwords.
    * --dry-run reports the full plan without writing anything.

Usage:
    python manage.py migrate_legacy_auth --dry-run
    python manage.py migrate_legacy_auth                 # source defaults to 'datawarehouse'
    python manage.py migrate_legacy_auth --source datawarehouse --target default
"""

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.roles import LEGACY_ROLES
from core.signals import muted_profile_signals


USER_FIELDS = (
    "email",
    "first_name",
    "last_name",
    "is_staff",
    "is_superuser",
    "is_active",
    "date_joined",
    "last_login",
    "password",  # copied verbatim — already a hash, never re-hashed
)


class Command(BaseCommand):
    help = "Copy users, roles and profiles from the legacy DB into the default DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", default="datawarehouse",
            help="Database alias to read legacy auth data from (default: datawarehouse).",
        )
        parser.add_argument(
            "--target", default="default",
            help="Database alias to write into (default: default).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **opts):
        source = opts["source"]
        target = opts["target"]
        dry_run = opts["dry_run"]

        from django.conf import settings
        if source not in settings.DATABASES:
            raise CommandError(f"Unknown source database alias '{source}'.")
        if target not in settings.DATABASES:
            raise CommandError(f"Unknown target database alias '{target}'.")

        # --- Pre-flight: confirm the legacy source actually has data -----------
        try:
            legacy_user_count = User.objects.using(source).count()
            legacy_group_count = Group.objects.using(source).count()
        except Exception as exc:  # connection/table errors
            raise CommandError(
                f"Could not read auth tables from source '{source}': {exc}"
            )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Legacy source '{source}': {legacy_user_count} users, "
            f"{legacy_group_count} groups."
        ))
        if legacy_user_count == 0:
            self.stdout.write(self.style.WARNING(
                "Source has 0 users — nothing to migrate. Point --source at the "
                "production datawarehouse (set DW_* in .env) and re-run."
            ))
            return

        stats = {
            "groups_created": 0, "groups_existing": 0,
            "users_created": 0, "users_updated": 0,
            "memberships_set": 0, "profiles_upserted": 0,
        }

        if dry_run:
            self._plan(source, target, stats)
            self.stdout.write(self.style.WARNING("\nDRY RUN — no changes written."))
            return

        with muted_profile_signals():
            with transaction.atomic(using=target):
                self._migrate_groups(source, target, stats)
                self._migrate_users(source, target, stats)
                self._migrate_memberships(source, target, stats)
                self._migrate_profiles(source, target, stats)

        self._report(stats)

    # ------------------------------------------------------------------ groups
    def _migrate_groups(self, source, target, stats):
        names = set(Group.objects.using(source).values_list("name", flat=True))
        names |= set(LEGACY_ROLES)  # ensure canonical roles exist even if unused
        for name in names:
            _, created = Group.objects.using(target).get_or_create(name=name)
            stats["groups_created" if created else "groups_existing"] += 1

    # ------------------------------------------------------------------- users
    def _migrate_users(self, source, target, stats):
        for lu in User.objects.using(source).all().iterator():
            defaults = {f: getattr(lu, f) for f in USER_FIELDS}
            _, created = User.objects.using(target).update_or_create(
                username=lu.username, defaults=defaults,
            )
            stats["users_created" if created else "users_updated"] += 1

    # ------------------------------------------------------------- memberships
    def _migrate_memberships(self, source, target, stats):
        # Cache target groups by name.
        tgt_groups = {g.name: g for g in Group.objects.using(target).all()}
        for lu in User.objects.using(source).all().iterator():
            # Resolve legacy group names for this user, forcing the source DB
            # for the whole join (auth_user_groups -> auth_group).
            legacy_names = list(
                Group.objects.using(source)
                .filter(user__pk=lu.pk)
                .values_list("name", flat=True)
            )
            try:
                tgt_user = User.objects.using(target).get(username=lu.username)
            except User.DoesNotExist:
                continue
            desired = [tgt_groups[n] for n in legacy_names if n in tgt_groups]
            tgt_user.groups.set(desired)  # set() reconciles add/remove
            stats["memberships_set"] += len(desired)

    # ---------------------------------------------------------------- profiles
    def _migrate_profiles(self, source, target, stats):
        from apps.portfolio.models import Profile

        tgt_users = {u.username: u for u in User.objects.using(target).all()}
        # Read legacy profiles joined to their username.
        for prof in (
            Profile.objects.using(source)
            .select_related("user")
            .iterator()
        ):
            username = prof.user.username
            tgt_user = tgt_users.get(username)
            if tgt_user is None:
                continue
            Profile.objects.using(target).update_or_create(
                user=tgt_user,
                defaults={
                    "sales_code": prof.sales_code,
                    "branch": prof.branch,
                    "segment": prof.segment,
                },
            )
            stats["profiles_upserted"] += 1

    # --------------------------------------------------------------- dry plan
    def _plan(self, source, target, stats):
        self.stdout.write("\nPlan (dry run):")
        legacy_groups = set(Group.objects.using(source).values_list("name", flat=True))
        existing_groups = set(Group.objects.using(target).values_list("name", flat=True))
        to_create_groups = (legacy_groups | set(LEGACY_ROLES)) - existing_groups

        existing_usernames = set(
            User.objects.using(target).values_list("username", flat=True)
        )
        legacy_usernames = set(
            User.objects.using(source).values_list("username", flat=True)
        )
        new_users = legacy_usernames - existing_usernames
        upd_users = legacy_usernames & existing_usernames

        self.stdout.write(f"  groups to create : {sorted(to_create_groups)}")
        self.stdout.write(f"  users to create  : {len(new_users)}")
        self.stdout.write(f"  users to update  : {len(upd_users)}")

        try:
            from apps.portfolio.models import Profile
            prof_count = Profile.objects.using(source).count()
        except Exception:
            prof_count = "unknown"
        self.stdout.write(f"  profiles in source: {prof_count}")

    # ----------------------------------------------------------------- report
    def _report(self, stats):
        self.stdout.write(self.style.SUCCESS("\nMigration complete:"))
        for k, v in stats.items():
            self.stdout.write(f"  {k:20s}: {v}")
