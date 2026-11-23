"""Looking a person up by PF number on ``employee_table``.

The model declares ``staff_id`` numeric (DecimalField), but production's column
is ``character varying``. ``filter(staff_id=3439)`` there is refused outright -
"operator does not exist: character varying = integer" - and every caller that
wrapped the lookup in try/except silently found nobody (the referral HR check,
the DSR code's department). So the comparison is made as text, which is right
on both column types: "3439", or "3439." followed by the decimals a numeric
column prints.
"""

from django.db.models import CharField, Q
from django.db.models.functions import Cast


def staff_id_matches(number):
    """(filter, annotation) for one PF number, compared as text on ``_sid``."""
    text = str(int(number))
    return (Q(_sid=text) | Q(_sid__startswith=f"{text}.")), Cast("staff_id", CharField())


def with_staff_id(qs, number):
    """``qs`` narrowed to the rows of PF ``number``, whatever the column type."""
    match, cast = staff_id_matches(number)
    return qs.annotate(_sid=cast).filter(match)
