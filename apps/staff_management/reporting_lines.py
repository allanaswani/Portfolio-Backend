"""Who reports to whom, in one table - branch, segment, zone, department, sector.

A person often has more than one line. An SME RM at Thika reports to Naomi Kagiri
as branch manager and to Anna Amasinde as head of the segment. So a line is a row,
not a column on the person, and ``line_kind`` is open text: a new kind of structure
such as a sector is new rows, not new code.

Each scorecard workbook writes its reporting lines in its own List sheet:

=========  ==========================================================
Workbook   Where the manager is
=========  ==========================================================
sales      ``BBM`` + ``e-mail1``; the segment lead in ``e-mail2``
bb         ``Reports-to`` + ``cc``
bo         ``BM`` + ``E-mail_To``
scheme     ``reports_to`` + ``email_cc``
=========  ==========================================================

The sales List's ``e-mail1`` is the manager's address at a branch, but the person's
OWN address at head office, so each address is matched to a name before it is used.

**Whose team is it** is decided from the account's own e-mail, login and name, and
never from ``Profile.sales_code``. Carrying somebody's code must not hand over the
team that goes with it.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections import defaultdict

#: How far down a chain to walk: person, branch, zone, head, general manager, CEO.
MAX_DEPTH = 6

#: The titles the bank's four workbooks use, kept so a role can be picked before
#: anybody holds it. What people already hold is added by :func:`role_titles`.
KNOWN_TITLES = (
    "BBM", "IB RM", "COMMERCIAL RM", "COMMERCIAL RM- TRADE", "SME RM", "SME ARM",
    "SME BBC", "ULTIMATE RM", "PB RM", "PB ARM", "PB BBC", "PB DSR", "SME DSR",
    "DIASPORA RM", "DIASPORA ARM", "MORTGAGE BUSINESS ARM", "BOM", "CSO", "CSO_UB",
    "CSM_DB", "TELLER", "CASH_CENTER", "RBO", "TL_RBO", "SCHEMES RM", "SCHEMES ADMIN",
    "PROJECT ADMIN", "HEAD OF SCHEMES",
)


class ReportingLineError(ValueError):
    """The sheet is not one this can read; the message says why."""


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _fold(text):
    return " ".join(str(text or "").lower().split())


def _local(email):
    """The part of an address before the @, lower case. The bank has used both
    hfcb.co.ke and hfgroup.co.ke, so the domain says nothing about the person."""
    return str(email or "").strip().lower().split("@")[0]


def _words(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _address_is(email, name):
    """Every word of the address is in the name: Evah.Kimani is Evah Kimani, and
    is not Sylvia Kimani."""
    words = _words(_local(email))
    return bool(words) and words <= _words(name)


def _name_from_address(email):
    return " ".join(w.capitalize() for w in re.split(r"[._]", _local(email)) if w)


def _line(code, name, role, kind, unit, manager, manager_email="", person_email=""):
    return {
        "person_code": _text(code).upper(),
        "person_name": _text(name),
        "person_email": _text(person_email).lower(),
        "role_title": _text(role),
        "line_kind": kind,
        "unit_code": "",
        "unit_name": _text(unit),
        "manager_name": _text(manager),
        "manager_email": _text(manager_email).lower(),
        "manager_code": "",
    }


def _sales_lines(rows):
    out = []
    for row in rows:
        code, name = row.get("sales_code"), row.get("name")
        if not _text(code) or not _text(name):
            continue
        role, boss = _text(row.get("role")), _text(row.get("bbm"))
        zone, branch = _text(row.get("zone")), _text(row.get("branch"))
        at_branch = zone.lower().startswith("zone")
        family = role.split()[0].upper() if role else ""
        addresses = [a for a in (_text(row.get("e-mail1")), _text(row.get("e-mail2")))
                     if a and not _address_is(a, name)]
        boss_mail = next((a for a in addresses if _address_is(a, boss)), "")
        # "BM Nyeri" is a placeholder rather than a name, so the address beside it
        # says who that is. For a real name that does not match its address, the name
        # stands: Naivasha's RMs name Nelly Kibet beside Christopher Opiyo's address.
        if not boss_mail and boss.upper().startswith("BM ") and addresses:
            first = _text(row.get("e-mail1"))
            boss_mail = first if first in addresses else ""
        if boss:
            out.append(_line(code, name, role, "branch" if at_branch else "segment",
                             branch if at_branch else family, boss, boss_mail))
        second = _text(row.get("e-mail2"))
        lead = second if second in addresses and second.lower() != boss_mail.lower() else ""
        if lead and at_branch:
            out.append(_line(code, name, role, "segment", family,
                             _name_from_address(lead), lead))
    return out


def _bb_lines(rows):
    out = []
    for row in rows:
        code, name = row.get("sales_code"), row.get("name")
        boss = _text(row.get("reports-to"))
        if not _text(code) or not _text(name) or not boss:
            continue
        out.append(_line(code, name, "BBM", "zone", row.get("zone"), boss,
                         row.get("cc"), row.get("e-mail")))
    return out


def _bo_lines(rows):
    out = []
    for row in rows:
        code, name = row.get("staffsalescode"), row.get("staff - name")
        branch, boss = _text(row.get("branch")), _text(row.get("bm"))
        if (not _text(code) or not _text(name) or not boss
                or branch.lower() == "left"):
            continue
        # A branch manager acting as their own operations manager, and the RBO team
        # leader, are listed as reporting to themselves.
        if _words(boss) <= _words(name):
            continue
        kind = ("branch" if _text(row.get("zone")).lower().startswith("zone")
                else "department")
        out.append(_line(code, name, row.get("role"), kind, branch, boss,
                         row.get("e-mail_to")))
    return out


def _scheme_lines(rows):
    out = []
    for row in rows:
        code, name = row.get("sales_code"), row.get("staff_name")
        boss = _text(row.get("reports_to"))
        if not _text(code) or not _text(name) or not boss:
            continue
        out.append(_line(code, name, row.get("staff_role"), "department", "Schemes",
                         boss, row.get("email_cc"), row.get("email_to")))
    return out


def _generic_lines(rows):
    """The sheet for anything the workbooks do not hold, such as sectors. Columns:
    sales_code, name, role, line_kind, unit_code, unit_name, manager_name,
    manager_email, and optionally person_email and manager_code."""
    out = []
    for row in rows:
        code, kind = _text(row.get("sales_code")), _fold(row.get("line_kind"))
        boss = _text(row.get("manager_name"))
        boss_mail = _text(row.get("manager_email"))
        if not code and not kind and not boss:
            continue
        if not code or not kind or not (boss or boss_mail):
            raise ReportingLineError(
                f"The row for '{code or row.get('name') or '?'}' needs a sales_code, "
                f"a line_kind and a manager_name or manager_email.")
        line = _line(code, row.get("name"), row.get("role"), kind,
                     row.get("unit_name"),
                     boss or _name_from_address(boss_mail), boss_mail,
                     row.get("person_email"))
        line["unit_code"] = _text(row.get("unit_code"))
        line["manager_code"] = _text(row.get("manager_code")).upper()
        out.append(line)
    return out


#: The headers that say which sheet this is, most specific first.
_BOOKS = (
    ("scheme", {"reports_role", "staff_name"}, _scheme_lines),
    ("bb", {"reports-to", "sales_code"}, _bb_lines),
    ("bo", {"staffsalescode", "bm"}, _bo_lines),
    ("sales", {"bbm", "sales_code"}, _sales_lines),
    ("upload", {"sales_code", "line_kind"}, _generic_lines),
)


def lines_from_rows(rows):
    """``(source, lines)`` from a List sheet's rows, as dicts with folded headers."""
    headers = set()
    for row in rows[:1]:
        headers = {k for k, v in row.items() if k}
    for source, needs, reader in _BOOKS:
        if needs <= headers:
            return source, reader(rows)
    raise ReportingLineError(
        "That sheet is not one of the scorecard Lists and has no sales_code and "
        "line_kind columns, so it says nothing about who reports to whom.")


def _dicts(table):
    """The rows under the first row that has a sales code column."""
    table = [list(r) for r in table if any(c not in (None, "") for c in r)]
    for index, row in enumerate(table[:6]):
        labels = [_fold(c) for c in row]
        if {"sales_code", "staffsalescode"} & set(labels):
            return [dict(zip(labels, r)) for r in table[index + 1:]]
    return []


def read_rows(upload):
    """The List sheet, or the only sheet, of an uploaded .xlsb, .xlsx, .xlsm or .csv."""
    import csv
    import io

    name = str(getattr(upload, "name", "") or "").lower()
    upload.seek(0)
    if name.endswith(".xlsb"):
        from pyxlsb import open_workbook

        handle, path = tempfile.mkstemp(suffix=".xlsb")
        try:
            with os.fdopen(handle, "wb") as held:
                held.write(upload.read())
            with open_workbook(path) as book:
                if "List" not in book.sheets:
                    raise ReportingLineError("That workbook has no List sheet.")
                with book.get_sheet("List") as sheet:
                    return _dicts([[c.v for c in r] for r in sheet.rows()])
        finally:
            os.unlink(path)
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl

        book = openpyxl.load_workbook(upload, read_only=True, data_only=True)
        try:
            sheet = book["List"] if "List" in book.sheetnames else book.worksheets[0]
            return _dicts(list(sheet.iter_rows(values_only=True)))
        finally:
            book.close()
    if name.endswith(".csv"):
        text = upload.read()
        text = text.decode("utf-8-sig", "replace") if isinstance(text, bytes) else text
        return _dicts(list(csv.reader(io.StringIO(text))))
    raise ReportingLineError("Send an .xlsb, .xlsx, .xlsm or .csv file.")


def _branch_key(text):
    """River Road, RIVERROAD BRANCH and Riverroad are one branch."""
    return "".join(w for w in re.findall(r"[a-z]+", str(text or "").lower())
                   if w != "branch")


def _is_branch_manager(title):
    words = _fold(title)
    return words.startswith("bbm") or "branch manager" in words \
        or "branch business manager" in words


def use_branch_manager_page(lines):
    """Settle who a branch's manager is from Administration's Branch Managers page.

    A List can write a placeholder ("BM Nyeri") or put an address beside a name that
    is not theirs (Naivasha). The page holds the name, address and code of the manager
    of each branch, so it answers those rows. A row the List is already clear about is
    left alone, and a branch the page has no single active manager for keeps the List's
    own value rather than a guess. The table can hold other staff too, hence the title.
    """
    from .models import BranchFinalEmployeeDmcData

    by_code, by_branch = {}, defaultdict(dict)
    for row in BranchFinalEmployeeDmcData.objects.filter(active=1).exclude(exit=1):
        code = _text(row.sales_code).upper()
        if not code or not _is_branch_manager(row.staff_role):
            continue
        by_code[code] = row
        for unit in (row.staff_unit, row.staff_branch):
            if _branch_key(unit):
                by_branch[_branch_key(unit)][code] = row

    out = []
    for line in lines:
        line = dict(line)
        if line["line_kind"] == "zone":
            # The page can misspell a code the workbook has right (CKG1784, CGK1784).
            # Same first letter and same digits is the same manager.
            code = line["person_code"]
            digits = re.sub(r"\D", "", code)
            near = [c for c in by_code if c[:1] == code[:1] and digits
                    and re.sub(r"\D", "", c) == digits]
            row = by_code.get(code) or (by_code[near[0]] if len(near) == 1 else None)
        else:
            row = None
        if row is not None:
            line["person_name"] = _text(row.staff_name) or line["person_name"]
            line["person_email"] = _text(row.staff_email).lower() or line["person_email"]
        unclear = (line["manager_name"].upper().startswith("BM ")
                   or not line["manager_email"])
        if line["line_kind"] == "branch" and unclear:
            found = by_branch.get(_branch_key(line["unit_name"]), {})
            if len(found) == 1:
                code, row = next(iter(found.items()))
                line["manager_name"] = _text(row.staff_name) or line["manager_name"]
                line["manager_email"] = _text(row.staff_email).lower()
                line["manager_code"] = code
        out.append(line)
    return out


def lines_from_rosters():
    """Lines the rosters hold: DSRs under their team leader, and the DMC roster's
    team leader for anybody a workbook does not cover. These have a name only."""
    from .live_scorecard import team_leader_of
    from .models import BranchEmployeeDmcData, DSRSalesCode

    out = []
    for row in BranchEmployeeDmcData.objects.exclude(sales_code=""):
        boss = _text(team_leader_of(row))
        if (not boss or not _text(row.sales_code)
                or row.staff_exit == 1 or row.active == 0
                or _words(boss) <= _words(row.staff_name)):
            continue
        out.append(_line(row.sales_code, row.staff_name, row.staff_role, "roster",
                         row.staff_branch or row.staff_unit, boss,
                         person_email=row.staff_email))
    for row in DSRSalesCode.objects.exclude(team_leader=""):
        if _words(row.team_leader) <= _words(row.salesperson):
            continue
        out.append(_line(row.sales_code, row.salesperson, row.role, "dsr",
                         row.branch, row.team_leader))
    return out


def save(lines, source, apply=False, kinds=None):
    """Bring ``source``'s rows in line with ``lines``.

    A line that has gone from the source is retired rather than deleted, because who
    reported to whom decides who could open whose card. ``kinds`` narrows that to the
    kinds this upload carries: a sector sheet must not retire the department lines.
    """
    from .models import ScReportingLine

    wanted = {}
    for line in lines:
        wanted[(line["person_code"], line["line_kind"], _fold(line["manager_name"]))] = line
    existing = ScReportingLine.objects.filter(source=source)
    if kinds:
        existing = existing.filter(line_kind__in=kinds)
    found = {(r.person_code, r.line_kind, _fold(r.manager_name)): r for r in existing}

    counts = {"new": 0, "changed": 0, "unchanged": 0, "retired": 0}
    for key, line in wanted.items():
        row = found.get(key)
        if row is None:
            counts["new"] += 1
            if apply:
                ScReportingLine.objects.create(source=source, **line)
            continue
        differs = (not row.active
                   or any(getattr(row, f) != v for f, v in line.items()))
        counts["changed" if differs else "unchanged"] += 1
        if apply and differs:
            for field, value in line.items():
                setattr(row, field, value)
            row.active = True
            row.save()
    for key, row in found.items():
        if key not in wanted and row.active:
            counts["retired"] += 1
            if apply:
                row.active = False
                row.save()
    return counts


def _viewer_keys(user):
    """What identifies this account as a manager. Nothing off the profile."""
    locals_ = {_local(getattr(user, "email", "")),
               _local(getattr(user, "username", ""))} - {""}
    name = _fold(user.get_full_name()) if hasattr(user, "get_full_name") else ""
    if not name and len(_words(getattr(user, "username", ""))) >= 2:
        name = " ".join(re.findall(r"[a-z0-9]+", str(user.username).lower()))
    return locals_, name


def team_for(user):
    """Everybody under this account, nearest first, one row per person.

    A row with a manager's address is matched on the address only. A name is the
    fallback for rows that have nothing else: the DSR list and the DMC roster.
    """
    from .models import ScReportingLine

    by_address, by_name = defaultdict(list), defaultdict(list)
    for row in ScReportingLine.objects.filter(active=True):
        if row.manager_email:
            by_address[_local(row.manager_email)].append(row)
        else:
            by_name[_fold(row.manager_name)].append(row)

    locals_, name = _viewer_keys(user)
    own_words = _words(getattr(user, "username", ""))

    def reports_of(addresses, person_name):
        rows = [r for a in addresses for r in by_address.get(a, [])]
        return rows + list(by_name.get(person_name, []) if person_name else [])

    people, frontier = {}, [(locals_, name)]
    for depth in range(1, MAX_DEPTH + 1):
        following = []
        for addresses, person_name in frontier:
            for row in reports_of(addresses, person_name):
                if (row.person_code in people
                        or (len(own_words) >= 2
                            and own_words <= _words(row.person_name))):
                    continue
                people[row.person_code] = {
                    "sales_code": row.person_code,
                    "name": row.person_name,
                    "role": row.role_title,
                    "line_kind": row.line_kind,
                    "unit": row.unit_name,
                    "unit_code": row.unit_code,
                    "manager": row.manager_name,
                    "depth": depth,
                }
                # Down a level. The sales List gives a branch manager's name and
                # address but only names them, so their address is also found by
                # matching it to their name: Silas.Abudho@ is Silas Abudho.
                theirs = {a for a in by_address
                          if len(_words(a)) >= 2 and _address_is(a, row.person_name)}
                if row.person_email:
                    theirs.add(_local(row.person_email))
                following.append((theirs, _fold(row.person_name)))
        if not following:
            break
        frontier = following
    return sorted(people.values(),
                  key=lambda p: (p["depth"], p["line_kind"], p["name"]))


def is_in_team(user, sales_code):
    code = str(sales_code or "").strip().upper()
    return bool(code) and any(p["sales_code"] == code for p in team_for(user))


def is_direct_report(user, sales_code):
    code = str(sales_code or "").strip().upper()
    return any(p["sales_code"] == code and p["depth"] == 1 for p in team_for(user))


def role_titles():
    """Every title a person can be given, without a release when one is added: the
    bank's known titles, then what the rosters and reporting lines hold."""
    from .models import BranchEmployeeDmcData, ScReportingLine

    titles, seen = [], set()

    def add(title):
        text = _text(title)
        key = _fold(text).replace("-", " ")
        key = " ".join(key.split())
        if text and key not in seen:
            seen.add(key)
            titles.append(text)

    for title in KNOWN_TITLES:
        add(title)
    extra = set(BranchEmployeeDmcData.objects.exclude(staff_role="")
                .exclude(staff_role__isnull=True)
                .values_list("staff_role", flat=True).distinct())
    extra |= set(ScReportingLine.objects.filter(active=True).exclude(role_title="")
                 .values_list("role_title", flat=True).distinct())
    for title in sorted(extra, key=str.lower):
        add(title)
    return titles
