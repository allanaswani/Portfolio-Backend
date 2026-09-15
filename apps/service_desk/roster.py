"""The Strategy & Business Performance roster, and how to find their logins.

Kept out of the migration that first used it, for one reason: matching a roster
row to a portfolio account is guesswork that needs correcting, and a migration
runs once. This is importable, re-runnable and testable, so when somebody is
missed the fix is to run it again rather than to write another migration.

**Why matching is hard here.** The roster and the login agree on almost
nothing:

* the domain moved — ``@hfgroup.co.ke`` on the roster, ``@hfcb.co.ke`` since
  the rebrand;
* one roster address has a typo in the domain (``hfgoup``);
* and Kenyan names carry three parts, so the roster's surname is often not the
  one the account uses. *Stacy Kendi Mwenda* signs in as **Stacy Kendi**;
  *Bryan Mwaura Kanyigi* as **Bryan Mwaura**. Matching on first-plus-last found
  neither, and both were quietly left off the desk.

So every name part is treated as a candidate surname, and the last resort is
"the login mentions their first name and one other part of it" — accepted only
when exactly one account matches, because putting the wrong colleague on a desk
is worse than leaving somebody off it.
"""

from django.contrib.auth import get_user_model
from django.db.models import Q

MANAGER_GROUP = "service_desk_manager"
AGENT_GROUP = "service_desk_agent"

# (full name, roster email, role)
#
# The Strategy & Business Performance department, minus Benson Mbugua, who is
# on the roster but not on this desk. Managers lead the function and can edit
# the team, the query types and the targets; everybody else works the queue.
TEAM = [
    ("Allan Ademba Aswani",     "Allan.Aswani@hfgroup.co.ke",      "manager"),
    ("Eileen Regina Ndegwa",    "Eileen.Ndegwa@hfgroup.co.ke",     "manager"),
    ("Andrew Sero",             "andrew.young@hfcb.co.ke",         "manager"),
    ("Washingtone Amollo",      "Washingtone.Amolo@hfgroup.co.ke", "manager"),
    ("Stacy Kendi Mwenda",      "Stacy.Mwenda@hfgroup.co.ke",      "agent"),
    ("Shekinah Wangui Mwangi",  "Shekinah.Mwangi@hfgroup.co.ke",   "agent"),
    ("Bryan Mwaura Kanyigi",    "Bryan.Kanyigi@hfgoup.co.ke",      "agent"),
]

#: Roster addresses known to be wrong, so never used to send mail — it would
#: bounce somewhere nobody is looking. The account is still found by name.
UNUSABLE = {"bryan.kanyigi@hfgoup.co.ke"}


def _parts(name):
    return [p for p in (name or "").replace(".", " ").split() if len(p) > 1]


def find_account(email, name):
    """Resolve one roster row to a login, or ``None``.

    Ordered by confidence. Every step requires a UNIQUE match: an ambiguous
    one returns nothing rather than picking, because the cost of adding the
    wrong person to this desk is higher than the cost of adding them by hand.
    """
    User = get_user_model()
    active = User.objects.filter(is_active=True)
    local = (email or "").split("@")[0].strip().lower()
    names = _parts(name)

    def only(qs):
        return qs.first() if qs.count() == 1 else None

    # 1. The address, exactly as the roster has it.
    if email:
        found = only(active.filter(email__iexact=email))
        if found:
            return found

    # 2. The local part as a username, or as the local part of any domain —
    #    this is what carries a person across the rebrand.
    if local:
        for qs in (active.filter(username__iexact=local),
                   active.filter(email__istartswith=f"{local}@")):
            found = only(qs)
            if found:
                return found

    if not names:
        return None

    first, rest = names[0], names[1:]

    # 3. First name with ANY of the other parts as the surname. A three-part
    #    Kenyan name means the roster's surname is often not the one in use.
    for surname in rest:
        found = only(active.filter(first_name__iexact=first,
                                   last_name__iexact=surname))
        if found:
            return found
        for pattern in (f"{first}.{surname}", f"{first}{surname}"):
            for qs in (active.filter(username__iexact=pattern),
                       active.filter(email__istartswith=f"{pattern}@")):
                found = only(qs)
                if found:
                    return found

    # 4. Last resort: the login mentions their first name and one other part of
    #    it. Loose enough to catch a spelling nobody anticipated, and still
    #    refused unless it lands on exactly one person.
    for other in rest:
        found = only(active.filter(
            Q(username__icontains=first) | Q(email__icontains=first)
        ).filter(
            Q(username__icontains=other) | Q(email__icontains=other)
        ))
        if found:
            return found
    return None


def apply(recipient_model=None):
    """Put the roster on the desk. Idempotent, and never removes anybody.

    Returns ``(matched, unmatched)`` so a caller can say who was missed —
    "it added nobody" with no explanation is what made the first attempt at
    this impossible to debug.
    """
    from django.contrib.auth.models import Group

    if recipient_model is None:
        from .models import DeskRecipient as recipient_model  # noqa: N813

    manager = Group.objects.get_or_create(name=MANAGER_GROUP)[0]
    agent = Group.objects.get_or_create(name=AGENT_GROUP)[0]

    matched, unmatched = [], []
    for name, email, role in TEAM:
        person = find_account(email, name)
        if person is not None:
            person.groups.add(manager if role == "manager" else agent)
            matched.append((name, person, role))
            continue

        unmatched.append((name, email, role))
        # No login found. Make sure they are at least emailed, rather than
        # dropped — being unreachable is what makes a desk look as though it
        # is ignoring people.
        if (email or "").strip().lower() in UNUSABLE:
            continue
        recipient_model.objects.update_or_create(
            email=email,
            defaults={"name": name, "queue": True,
                      "escalations": role == "manager", "is_active": True},
        )
    return matched, unmatched
