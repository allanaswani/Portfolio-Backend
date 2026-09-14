"""Who is on the service desk.

    manage.py service_desk_team                          # who is on it now
    manage.py service_desk_team --find trevor            # what accounts exist
    manage.py service_desk_team --add trevor.william@hfcb.co.ke
    manage.py service_desk_team --add someone --as-agent
    manage.py service_desk_team --remove benson.k

The team was first seeded by a data migration with the names written into it.
That was the wrong tool twice over: it matched nothing on the server because
the accounts are not spelled the way the list guessed, and a team is not a
thing that changes only when somebody deploys.

``--find`` exists because "it added nobody" is a useless answer on its own. It
shows what accounts are actually there, so the reason is visible rather than
guessed at.

Membership is also editable from Administration by putting people in the
``service_desk_manager`` / ``service_desk_agent`` groups — this is the same
thing from a terminal, for when that is quicker.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.service_desk.models import DeskRecipient

MANAGER_GROUP = "service_desk_manager"
AGENT_GROUP = "service_desk_agent"


def find_person(needle):
    """Resolve one person from an email, a username, or part of either.

    Deliberately forgiving about how an address is written down, and
    deliberately refuses to guess when more than one person matches — adding
    the wrong colleague to a desk is worse than adding nobody.
    """
    User = get_user_model()
    needle = (needle or "").strip()
    if not needle:
        return None, "No name or address given."

    exact = User.objects.filter(
        Q(email__iexact=needle) | Q(username__iexact=needle)
    ).distinct()
    if exact.count() == 1:
        return exact.first(), None
    if exact.count() > 1:
        return None, f"{needle} matches {exact.count()} accounts exactly."

    local = needle.split("@")[0]
    loose = User.objects.filter(
        Q(email__icontains=needle) | Q(username__icontains=needle)
        | Q(email__istartswith=local) | Q(username__iexact=local)
    ).distinct()
    if loose.count() == 1:
        return loose.first(), None
    if loose.count() > 1:
        names = ", ".join(f"{p.username} <{p.email or 'no email'}>" for p in loose[:8])
        return None, f"{needle} matches several accounts: {names}"
    return None, f"No account matches {needle}."


class Command(BaseCommand):
    help = "List, add to, or remove from the service desk team."

    def add_arguments(self, parser):
        parser.add_argument("--add", nargs="*", default=[],
                            help="Email or username to put on the desk.")
        parser.add_argument("--remove", nargs="*", default=[],
                            help="Email or username to take off the desk.")
        parser.add_argument("--as-agent", action="store_true",
                            help="Add as an agent rather than a manager. "
                                 "Agents work the queue; managers also assign "
                                 "to others and edit the categories and SLAs.")
        parser.add_argument("--find", default="",
                            help="Search the accounts, changing nothing.")
        parser.add_argument("--add-email", nargs="*", default=[], dest="add_email",
                            help="Notify this address. No account needed — for "
                                 "people on the desk who have no login.")
        parser.add_argument("--remove-email", nargs="*", default=[],
                            dest="remove_email",
                            help="Stop notifying this address.")

    def handle(self, *args, **options):
        manager, _ = Group.objects.get_or_create(name=MANAGER_GROUP)
        agent, _ = Group.objects.get_or_create(name=AGENT_GROUP)

        if options["find"]:
            self.find(options["find"])
            return

        target = agent if options["as_agent"] else manager
        changed = False

        # Addresses first: this is the path that needs no account, and it is
        # the one somebody reaches for when the desk is emailing nobody.
        for address in options["add_email"]:
            address = address.strip()
            if "@" not in address:
                self.stdout.write(self.style.ERROR(
                    f"  skip  {address}: that is not an email address."))
                continue
            row, created = DeskRecipient.objects.get_or_create(
                email__iexact=address, defaults={"email": address})
            if not created and not row.is_active:
                row.is_active = True
                row.save(update_fields=["is_active", "updated_at"])
            changed = True
            self.stdout.write(self.style.SUCCESS(
                f"  {'added' if created else 'already on'} {row.email}"))

        for address in options["remove_email"]:
            rows = DeskRecipient.objects.filter(email__iexact=address.strip())
            if not rows:
                self.stdout.write(self.style.ERROR(
                    f"  skip  {address}: not on the notify list."))
                continue
            rows.delete()
            changed = True
            self.stdout.write(self.style.SUCCESS(f"  removed {address}"))

        for needle in options["add"]:
            person, problem = find_person(needle)
            if person is None:
                self.stdout.write(self.style.ERROR(f"  skip  {needle}: {problem}"))
                continue
            if not person.email:
                # They would be on the desk and never hear about a query.
                self.stdout.write(self.style.WARNING(
                    f"  note  {person.username} has no email address, so they "
                    f"will not be notified. Added anyway."))
            person.groups.add(target)
            changed = True
            self.stdout.write(self.style.SUCCESS(
                f"  added {person.username} <{person.email or 'no email'}> "
                f"as {'agent' if options['as_agent'] else 'manager'}"))

        for needle in options["remove"]:
            person, problem = find_person(needle)
            if person is None:
                self.stdout.write(self.style.ERROR(f"  skip  {needle}: {problem}"))
                continue
            person.groups.remove(manager)
            person.groups.remove(agent)
            changed = True
            self.stdout.write(self.style.SUCCESS(
                f"  removed {person.username} from the desk "
                f"(nothing else about the account is changed)"))

        if changed:
            self.stdout.write("")
        self.show()

    def find(self, needle):
        User = get_user_model()
        people = User.objects.filter(
            Q(username__icontains=needle) | Q(email__icontains=needle)
            | Q(first_name__icontains=needle) | Q(last_name__icontains=needle)
        ).distinct().order_by("username")[:25]
        if not people:
            self.stdout.write(self.style.WARNING(f"No account matches '{needle}'."))
            return
        self.stdout.write(f"Accounts matching '{needle}':")
        for person in people:
            flags = []
            if not person.is_active:
                flags.append("INACTIVE")
            if person.is_superuser:
                flags.append("superuser")
            groups = list(person.groups.values_list("name", flat=True))
            if MANAGER_GROUP in groups:
                flags.append("desk manager")
            if AGENT_GROUP in groups:
                flags.append("desk agent")
            tail = f"  [{', '.join(flags)}]" if flags else ""
            self.stdout.write(
                f"  {person.username:<28} {person.email or '(no email)':<38}"
                f"{tail}")

    def show(self):
        self.stdout.write("Service desk team")
        for label, name in (("Managers", MANAGER_GROUP), ("Agents", AGENT_GROUP)):
            people = (get_user_model().objects
                      .filter(groups__name=name, is_active=True)
                      .distinct().order_by("username"))
            self.stdout.write(f"  {label}:")
            if not people:
                self.stdout.write("    (nobody)")
            for person in people:
                mail = person.email or self.style.WARNING("no email - will not be notified")
                self.stdout.write(f"    {person.username:<28} {mail}")

        addresses = DeskRecipient.objects.filter(is_active=True)
        self.stdout.write("  Notified without an account:")
        if not addresses:
            self.stdout.write("    (none)")
        for row in addresses:
            kinds = ", ".join(
                k for k, on in (("queue", row.queue), ("escalations", row.escalations))
                if on) or "nothing"
            self.stdout.write(f"    {row.email:<38} {kinds}")

        has_account = get_user_model().objects.filter(
            groups__name__in=[MANAGER_GROUP, AGENT_GROUP], is_active=True).exists()
        if not has_account and not addresses:
            # Nobody on the desk means every query is raised into silence.
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(
                "Nobody is on the desk, so no query will be emailed to anyone. "
                "Add an account with --add, or an address with --add-email if "
                "the person has no login."))
