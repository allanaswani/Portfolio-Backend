"""Whose use of the tools the usage figures leave out.

The usage reports exist to show how the branches and the business use the
tools. The Strategy team builds and supports them, so its own clicks say nothing
about adoption - and put the people who built it at the top of every ranking.

Membership is a group, so an administrator changes it on the Users screen and
needs no deploy. The events themselves are still recorded: leaving someone out
of the report is reversible, and the audit trail stays complete.
"""

from django.contrib.auth import get_user_model

EXCLUDED_GROUP = "usage_report_excluded"


def excluded_usernames():
    """Lower-cased usernames left out of every usage figure."""
    return {name.lower() for name in get_user_model().objects
            .filter(groups__name=EXCLUDED_GROUP)
            .values_list("username", flat=True)}


def excluded_user_ids():
    return set(get_user_model().objects.filter(groups__name=EXCLUDED_GROUP)
               .values_list("id", flat=True))
