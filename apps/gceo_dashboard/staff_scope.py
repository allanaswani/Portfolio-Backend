"""One definition of "a member of staff", for every tile on the Staff & HR slide.

There were three, on the same screen, and they counted different people:

    Total Staff        count(DISTINCT staff_id) FILTER (WHERE exit = 0)
    Department / Grade COUNT(id)  with .exclude(exit=1)
    Years of service   COUNT(*)   FILTER (WHERE exit = 0)

Two differences, both silent.

``exit = 0`` and ``.exclude(exit=1)`` are not the same test. A row whose ``exit``
is NULL fails the first and passes the second, so the department and grade
charts counted people the headline total did not.

And ``exit`` is not the only exit marker. apps/trade_register/views.py already
had to handle this: "Either marker alone can carry the exit, depending on which
sheet the HR upload recorded it on." A leaver whose departure was recorded as a
``staff_exit_date`` with no ``exit`` flag was being counted as current staff by
every one of the three.

On top of that, two of the three counted ROWS and one counted DISTINCT
``staff_id``, so any duplicate in the HR upload landed in the charts but not in
the headline.

So: a person has left if EITHER marker says so, and a person is counted once.
Both halves of that live here, and nothing on the slide gets to have its own
opinion about it.
"""
from django.db.models import Count, Q, TextField
from django.db.models.functions import Cast, Coalesce, Trim

# A row that represents somebody who has left the bank.
LEFT = Q(exit=1) | Q(staff_exit_date__isnull=False)


def current_staff(qs):
    """Restrict an EmployeeTable queryset to people still employed."""
    return qs.exclude(LEFT)


# The same rule in SQL, for the views that are raw. Written as a WHERE fragment
# so the caller keeps control of the rest of the statement.
CURRENT_STAFF_SQL = "COALESCE(exit, 0) <> 1 AND staff_exit_date IS NULL"

# Leavers, for the tiles that count departures rather than headcount.
LEFT_SQL = "(exit = 1 OR staff_exit_date IS NOT NULL)"


# ── Counting people ──────────────────────────────────────────────────────────
# ``staff_id`` is nullable, and COUNT(DISTINCT staff_id) DROPS every row where
# it is NULL. Those are real employees, and they disappeared from the headcount
# without a trace - which is why the board reported fewer staff than the bank
# has. Standardising on COUNT(DISTINCT staff_id) is what introduced it to the
# department and grade charts, which had previously counted rows and so at least
# included these people.
#
# So the key is the staff number where there is one, and the row itself where
# there is not: a person with no staff number is still a person, and two rows
# carrying the same staff number are still one person.
PERSON_KEY_SQL = (
    "COALESCE(NULLIF(BTRIM(staff_id::text), ''), 'row:' || id::text)"
)


def people_count():
    """The ORM equivalent of PERSON_KEY_SQL, as a Count() to annotate with."""
    return Count(
        Coalesce(
            Trim(Cast("staff_id", TextField())),
            Cast("id", TextField()),
        ),
        distinct=True,
    )


# ── How long somebody has worked here ────────────────────────────────────────
# NOT ``employee_table.service_years``. That column is stored, not derived, and
# nobody maintains it. Measured on production: 527 of 913 current staff carry
# service_years = 0, none carry NULL, and every single one of them has a real
# date_of_employment. They are not 527 new joiners - only 198 people were
# actually employed this year. The column was simply never filled in for them,
# and a stored zero is indistinguishable from a genuine one.
#
# So the board reported 527 staff with under a year of service beside a New
# Hires tile reading 198. Both cannot be true, and it was the first thing
# anyone noticed.
#
# date_of_employment is present for every current employee, so the length of
# service is computed from it. Whole years, because that is what the bands need.
SERVICE_YEARS_SQL = (
    "date_part('year', age(current_date, date_of_employment))"
)
