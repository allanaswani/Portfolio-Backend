"""Training hours: reading HR's monthly return, and serving the card.

A training line sits on **every one of the 22 cards** — ``business_banking_
training`` on seven sales roles, ``personal_banking_training`` on five, and
``bo_training_hours`` on all ten back-office roles — and not one of them could
be scored. The card said "Training hours are recorded in the learning system,
not here", which was true and was also the end of the conversation.

They are recorded in ``2026 Training Returns Template - <Mon>_<yy>.xlsx``,
which HR circulate monthly. The shape is one row per person and one column per
month, hours in the cells::

    Branch   | StaffPF | StaffCode | Staff Name      | 2026-01-01 | 2026-02-01 | …
    Buruburu | 1886    | CMM1886   | Christopher K.  | 4          | 7          | …

Eight sheets carry people — ``Staff_Training_Returns`` plus one per desk (RBO,
Diaspora, Commercial, Mortgage, Payments, IB, Schemes) — and two carry pivots
of averages, which are derived and ignored.

Checked against the cards
─────────────────────────
Of the eight calibration cards, four name an RM who appears on the August 2026
return. The Jan–Aug sum reproduces the card's own stated actual **exactly on
all four**:

=====================  ==========  ===============  =============
card                   on return   Jan–Aug sum      card's actual
=====================  ==========  ===============  =============
Business_Banking       CM4236              36.0             36.0
Diaspora               EK4188              38.5             38.5
Commercial             JM4191              29.0             29.0
Commercial_trade       GW3961              69.0             69.0
=====================  ==========  ===============  =============

**The PF number is the key, not the sales code.** The roster has Charles
Muchiri as ``CMM4236``; the return has him as ``CM4236``. Both say 4236.
Matching on the code alone loses him, and losing him looks exactly like an RM
who did no training.

**Not being on the return is not nought hours.** Three cards show an actual of
0.0 for somebody the return does not mention, which is the desk filling a
blank. This reports "you are not on the training return for <month>" instead,
because scoring somebody nought on a return they are absent from is a
different statement from scoring them nought on hours they did not do.
"""

from __future__ import annotations

import datetime
import re

#: Header spellings for the three columns that identify a person. The main
#: sheet says ``StaffPF``/``StaffCode``/``Staff Name``; the desk sheets say
#: ``staff_pf``/``sales_code``/``sales_person``.
PF_HEADERS = ("staffpf", "staff_pf", "pf", "staff pf", "pf number",
              "pf_number")
CODE_HEADERS = ("staffcode", "staff_code", "staff code", "sales_code",
                "salescode", "sales code")
NAME_HEADERS = ("staff name", "staff_name", "sales_person", "salesperson",
                "name")
BRANCH_HEADERS = ("branch", "unit", "branch name")
ROLE_HEADERS = ("role", "staff_role", "job title", "designation")

#: Labels that are a summary row rather than a person. They appear with no
#: code and no PF, so they are dropped anyway — this is belt and braces for a
#: return where somebody has filled the code column in on a total row.
NOT_A_PERSON = ("average", "total", "grand total", "sum", "")


def pf_of(value):
    """A PF number reduced to digits, or ``""``.

    The return writes it as a number, the roster as an integer, and a stray
    space or ``.0`` must not make them different people.

    The decimal point is the trap, and it is worse than it looks: openpyxl
    hands back a numeric cell as a float, ``str(4236.0)`` is ``"4236.0"``, and
    simply dropping the non-digits gives **42360** - not a failed match but a
    confident match against somebody else. So a value that is a whole number
    is taken as one before anything else happens.
    """
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value or "").strip()
    # "4236.0" as text, from a CSV round trip or a pasted cell.
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    digits = re.sub(r"\D", "", text)
    return digits.lstrip("0") or digits


def month_of(filename="", today=None):
    """The month a return is for, from its name.

    ``2026 Training Returns Template - Aug_26.xlsx`` → August 2026. The month
    columns inside the file carry their own dates, so this is only the
    fallback label and the default for a figure typed in.
    """
    raw = str(filename or "")
    found = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[_\- ]*"
        r"(20\d{2}|\d{2})", raw, re.I)
    if found:
        month = ["jan", "feb", "mar", "apr", "may", "jun",
                 "jul", "aug", "sep", "oct", "nov", "dec"].index(
                     found.group(1).lower()) + 1
        year = int(found.group(2))
        year = year + 2000 if year < 100 else year
        return datetime.date(year, month, 1)
    today = today or datetime.date.today()
    return today.replace(day=1)


def _hours(value):
    """Hours, or None. A blank month is NOT nought hours."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _month_columns(sheet):
    """``{column: first of month}`` for the header's date columns."""
    out = {}
    for column in range(1, sheet.max_column + 1):
        value = sheet.cell(row=1, column=column).value
        if isinstance(value, datetime.datetime):
            out[column] = value.date().replace(day=1)
        elif isinstance(value, datetime.date):
            out[column] = value.replace(day=1)
    return out


def read_workbook(stream, filename=""):
    """Read HR's return → ``(rows, report)``.

    One entry per person per month that carries a figure. Nothing is written.
    A sheet with no date columns, or no way to identify a person, is named in
    the report rather than skipped in silence — two of the ten sheets are
    pivots of averages and are supposed to be skipped, and saying so is how
    somebody can tell that from a sheet that failed to parse.
    """
    from openpyxl import load_workbook

    book = load_workbook(stream, data_only=True)
    rows, report = [], {
        "sheets_read": [], "sheets_skipped": [], "people": 0, "months": [],
        "no_identity": 0, "ignored_values": [],
        "default_month": month_of(filename).isoformat(),
    }
    seen, months = set(), set()

    for name in book.sheetnames:
        sheet = book[name]
        header = {
            column: str(sheet.cell(row=1, column=column).value or "")
            .strip().lower()
            for column in range(1, sheet.max_column + 1)
        }

        def column_for(options):
            return next((column for column, label in sorted(header.items())
                         if label in options), None)

        pf_at = column_for(PF_HEADERS)
        code_at = column_for(CODE_HEADERS)
        name_at = column_for(NAME_HEADERS)
        branch_at = column_for(BRANCH_HEADERS)
        role_at = column_for(ROLE_HEADERS)
        month_at = _month_columns(sheet)

        if not month_at or (pf_at is None and code_at is None):
            report["sheets_skipped"].append({
                "sheet": name,
                "why": ("no month columns" if not month_at
                        else "no PF or staff-code column"),
            })
            continue
        report["sheets_read"].append(name)

        for row in range(2, sheet.max_row + 1):
            pf = pf_of(sheet.cell(row=row, column=pf_at).value) if pf_at else ""
            code = (str(sheet.cell(row=row, column=code_at).value or "")
                    .strip().upper() if code_at else "")
            who = (str(sheet.cell(row=row, column=name_at).value or "").strip()
                   if name_at else "")
            if not pf and not code:
                # A row with hours and nobody to attach them to. COUNTED
                # rather than dropped in silence: the cumulative-target row at
                # the foot of a desk sheet looks exactly like this (4, 8, 12 …
                # 48), and so does a person whose PF and code columns are both
                # blank - and the second of those is somebody's score.
                #
                # This has to come BEFORE the summary-label check below, or a
                # row with a blank name is skipped as "not a person" and never
                # counted at all.
                if any(_hours(sheet.cell(row=row, column=column).value)
                       is not None for column in month_at):
                    report["no_identity"] += 1
                continue
            if who.strip().lower() in NOT_A_PERSON and who.strip():
                # Belt and braces: a total row with the code column filled in.
                continue

            branch = (str(sheet.cell(row=row, column=branch_at).value or "")
                      .strip() if branch_at else "")
            role = (str(sheet.cell(row=row, column=role_at).value or "")
                    .strip() if role_at else "")
            seen.add((pf, code))

            for column, month in month_at.items():
                raw = sheet.cell(row=row, column=column).value
                hours = _hours(raw)
                if hours is None:
                    if raw not in (None, ""):
                        report["ignored_values"].append(
                            {"sheet": name, "person": who or code or pf,
                             "month": month.isoformat(),
                             "value": str(raw)[:40]})
                    continue
                months.add(month)
                rows.append({
                    "month": month, "staff_pf": pf[:20],
                    "sales_code": code[:40], "staff_name": who[:160],
                    "branch": branch[:120], "staff_role": role[:80],
                    "hours": hours, "source": (filename or "")[:160],
                })

    report["people"] = len(seen)
    report["months"] = sorted(month.isoformat() for month in months)
    return rows, report


def save(rows, who=""):
    """Write the return, one row per person per month.

    Upsert on (month, PF, code), so re-uploading a month corrects it rather
    than doubling somebody's year. A month the new file does not mention is
    left alone: HR send a corrected single month, and clearing the rest would
    wipe the year to date for everybody.
    """
    from django.db import transaction

    from .models import ScTrainingReturn

    written = 0
    with transaction.atomic():
        for row in rows:
            row = dict(row)
            key = {"month": row.pop("month"),
                   "staff_pf": row.pop("staff_pf"),
                   "sales_code": row.pop("sales_code")}
            row["updated_by"] = who[:150]
            ScTrainingReturn.objects.update_or_create(**key, defaults=row)
            written += 1
    return written


# ─────────────────────────────────────────────────────────────────────────────
# What the scorecard reads
# ─────────────────────────────────────────────────────────────────────────────


def latest_month():
    """The newest month any return covers, or None."""
    from .models import ScTrainingReturn

    return (ScTrainingReturn.objects.order_by("-month")
            .values_list("month", flat=True).first())


def ytd_hours(sales_code="", staff_pf="", year=None):
    """This person's training hours for the year → ``(hours, as_at, problem)``.

    ``as_at`` is the last month **the return covers**, not the last month this
    person has a figure in, and the difference decides somebody's score.

    A blank month INSIDE the return is nought hours: the return reports the
    whole bank every month, so a person with nothing against July did no
    training in July. A blank month BEYOND it is simply not reported yet.
    Slicing the target to the person's own last figure instead would reward
    exactly the people who stopped training: Juspher Muriithi's 29 hours run
    out in June, and against a June target they score 122% where his card
    says 90.6% — which is 29 against the 32 hours August is worth.

    The target still has to be sliced to this date rather than to today, or
    eight months of hours would be scored against a full year's target.

    **The PF number is tried first.** The return and the roster do not always
    spell a sales code the same way — ``CMM4236`` against ``CM4236`` — and the
    PF number is 4236 on both.

    ``hours`` is None with a reason rather than nought when the person is not
    on the return at all. Absent from a return and nought hours are different
    statements, and only one of them is the person's fault.
    """
    from django.db.models import Max, Sum

    from .models import ScTrainingReturn

    year = year or datetime.date.today().year
    rows = ScTrainingReturn.objects.filter(month__year=year)

    pf = pf_of(staff_pf)
    code = (sales_code or "").strip()
    found = None
    if pf:
        found = rows.filter(staff_pf=pf)
        if not found.exists():
            found = None
    if found is None and code:
        found = rows.filter(sales_code__iexact=code)
        if not found.exists():
            found = None

    if found is None:
        covers = latest_month()
        if covers is None:
            return None, None, ("no training return has been loaded yet. "
                                "Administration → Scorecards → Training "
                                "returns is where that happens")
        return None, None, (
            f"you are not on the training return, which covers up to "
            f"{covers:%B %Y}. HR key it on the PF number; if yours is "
            f"recorded differently there, the hours cannot reach this card")

    hours = float(found.aggregate(hours=Sum("hours"))["hours"] or 0.0)
    # The month the RETURN reaches, over everybody - see the note above.
    covers = rows.aggregate(upto=Max("month"))["upto"]
    return hours, month_end(covers), ""


def month_end(first_of_month):
    """The last day of the month a stored row is keyed on.

    Rows are keyed on the first; the hours are for the whole month, so the
    as-at a target is sliced to is its last day.
    """
    if first_of_month is None:
        return None
    if first_of_month.month == 12:
        return datetime.date(first_of_month.year, 12, 31)
    return (datetime.date(first_of_month.year, first_of_month.month + 1, 1)
            - datetime.timedelta(days=1))


def coverage(year=None):
    """How much of the roster the return reaches, and what it cannot.

    The number worth watching is the same one as everywhere else in this
    estate: a person the return spells differently from the roster has no
    figure, and that is indistinguishable from somebody who did no training.
    """
    from django.db.models import Count, Max, Sum

    from .models import ScTrainingReturn

    year = year or datetime.date.today().year
    rows = ScTrainingReturn.objects.filter(month__year=year)
    if not rows.exists():
        return {"year": year, "people": 0, "months": [], "rows": 0,
                "latest_month": None, "hours": 0.0, "without_a_pf": 0}

    people = rows.values("staff_pf", "sales_code").distinct().count()
    months = sorted({month.isoformat() for month in
                     rows.values_list("month", flat=True).distinct()})
    return {
        "year": year,
        "people": people,
        "months": months,
        "rows": rows.count(),
        "latest_month": (rows.aggregate(m=Max("month"))["m"] or None),
        "hours": float(rows.aggregate(h=Sum("hours"))["h"] or 0.0),
        # A row with no PF can only ever be matched on its sales code, which
        # is the spelling that goes wrong.
        "without_a_pf": rows.filter(staff_pf="").values(
            "sales_code").distinct().count(),
    }


def people(year=None, search=""):
    """One row per person, with their year to date. For the screen."""
    from django.db.models import Max, Sum

    from .models import ScTrainingReturn

    year = year or datetime.date.today().year
    rows = ScTrainingReturn.objects.filter(month__year=year)
    needle = (search or "").strip()
    if needle:
        from django.db.models import Q

        rows = rows.filter(Q(staff_name__icontains=needle)
                           | Q(sales_code__icontains=needle)
                           | Q(staff_pf__icontains=needle)
                           | Q(branch__icontains=needle))
    grouped = (rows.values("staff_pf", "sales_code", "staff_name", "branch",
                           "staff_role")
               .annotate(hours=Sum("hours"), upto=Max("month"))
               .order_by("-hours"))
    return [{
        "staff_pf": row["staff_pf"], "sales_code": row["sales_code"],
        "staff_name": row["staff_name"], "branch": row["branch"],
        "staff_role": row["staff_role"],
        "hours": float(row["hours"] or 0.0),
        "upto": row["upto"].isoformat() if row["upto"] else None,
    } for row in grouped]
