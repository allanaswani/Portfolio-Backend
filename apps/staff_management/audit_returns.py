"""Internal Audit's branch return: the score, and the implementation rate.

Nine scorecard lines across eight roles read this, and none of them could be
scored before it existed. The figures arrive as a short table from Internal
Audit — a branch, a score, an implementation rate::

    Branch     Score   Implimentation
    Eldoret    1.65    93%
    Rehani     1.72    82%
    Embu       1.65    80%
    ...

Eight rows. Which is why this takes a **paste** as readily as a file: making
somebody save a workbook to load eight numbers is how a screen goes unused.

What makes this different from the rest of the module
────────────────────────────────────────────────────
It is a **branch** measure feeding **personal** cards. One row serves every
person in that branch, so a branch spelt differently here from the roster takes
the score away from all of them at once — not one card, a whole branch.

So the matching is deliberately **exact after folding**, never a prefix match.
``Thika`` and ``Thika Road Mall-TRM`` are two different branches, and a prefix
match would quietly give one of them the other's audit score. A branch that
matches nothing is reported instead, in both directions: names on the return
that match no branch, and branches with staff that the return does not mention.

The score is lower-is-better
────────────────────────────
1.65 is a grade, not a quantity. "Annual audit score of 1.65" means achieve
1.65 **or better**, and better means smaller. The Diaspora card confirms it: an
actual of 1.6337 against a target of 1.65 scores full marks. Read the other way
round, the branches with the worst audits would come top.

``implementation`` is the opposite — 85% or better, and better means larger.
"""

from __future__ import annotations

import csv
import io
import re

#: Header spellings for each column. Internal Audit's own sheet says
#: "Implimentation", which is a typo and is matched as written: a reader that
#: only accepts the correct spelling rejects the real file.
BRANCH_HEADERS = ("branch", "branch name", "branchname", "unit")
SCORE_HEADERS = ("score", "audit score", "auditscore", "audit")
IMPLEMENTATION_HEADERS = (
    "implimentation", "implementation", "impl", "implementation score",
    "implimentation score", "resolution", "audit implementation",
)

#: Dropped from a branch name before matching. The roster writes "ELDORET
#: BRANCH" and Internal Audit write "Eldoret"; neither is wrong.
BRANCH_NOISE = re.compile(r"\b(branch|br|bran)\b", re.I)

#: Labels that are a total row rather than a branch.
NOT_A_BRANCH = ("", "total", "grand total", "average", "overall", "bank",
                "group")


def fold_branch(name):
    """A branch name reduced to something comparable.

    Upper case, no punctuation, no spaces, and the word "branch" removed —
    so ``Eldoret``, ``ELDORET BRANCH`` and ``Eldoret  Br.`` are one branch.

    Deliberately NOT a prefix or fuzzy match. ``THIKA`` and
    ``THIKAROADMALLTRM`` stay different, because they are different branches
    and handing one the other's audit score would be worse than reporting
    neither.
    """
    text = BRANCH_NOISE.sub(" ", str(name or ""))
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _score(value):
    """An audit grade, or None. Something like 1.65."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _rate(value):
    """An implementation rate as 0–1, or None.

    Internal Audit write ``93%``; a spreadsheet may hold ``0.93`` or ``93``.
    All three mean the same thing, and 93 scored against a target of 0.85
    would read as 9,300%.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    else:
        text = str(value).strip().replace("%", "").replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number / 100 if number > 1.5 else number


def period_of(text="", today=None):
    """``2026`` from whatever is given, else this year.

    The audit score is annual — its own target says "Annual audit score" — so
    a bare year is the default. A month is accepted so the cadence can change
    without a migration.
    """
    import datetime

    raw = str(text or "").strip()
    found = re.search(r"(20\d{2})[-/](0[1-9]|1[0-2])", raw)
    if found:
        return f"{found.group(1)}-{found.group(2)}"
    found = re.search(r"(20\d{2})", raw)
    if found:
        return found.group(1)
    return str((today or datetime.date.today()).year)


def _rows_from_table(table):
    """``[[cell, ...], ...]`` → ``(rows, report)``, by header name."""
    report = {"columns": {}, "skipped_rows": [], "ignored_values": []}
    if not table:
        return [], report

    header_at = None
    columns = {}
    for index, line in enumerate(table[:10]):
        labels = {n: str(c or "").strip().lower()
                  for n, c in enumerate(line)}
        found = {}
        for n, label in labels.items():
            if label in BRANCH_HEADERS and "branch" not in found:
                found["branch"] = n
            elif label in SCORE_HEADERS and "score" not in found:
                found["score"] = n
            elif label in IMPLEMENTATION_HEADERS and "impl" not in found:
                found["impl"] = n
        if "branch" in found and ("score" in found or "impl" in found):
            header_at, columns = index, found
            break

    if header_at is None:
        # No header line. Internal Audit's table is three columns in a fixed
        # order, and somebody pasting the body without the header is the
        # likeliest reason to get here, so it is read positionally - and the
        # report says so, because a positional read is a guess.
        columns = {"branch": 0, "score": 1, "impl": 2}
        header_at = -1
        report["columns"]["read_positionally"] = True

    report["columns"].update(
        {name: index for name, index in columns.items()})

    out = []
    for line in table[header_at + 1:]:
        if not line:
            continue

        def cell(name):
            index = columns.get(name)
            if index is None or index >= len(line):
                return None
            return line[index]

        name = str(cell("branch") or "").strip()
        if fold_branch(name) == "" or name.strip().lower() in NOT_A_BRANCH:
            if any(str(c or "").strip() for c in line):
                report["skipped_rows"].append(
                    [str(c or "")[:30] for c in line[:4]])
            continue

        score, rate = _score(cell("score")), _rate(cell("impl"))
        for label, raw, parsed in (("score", cell("score"), score),
                                   ("implementation", cell("impl"), rate)):
            if parsed is None and raw not in (None, ""):
                report["ignored_values"].append(
                    {"branch": name, "column": label,
                     "value": str(raw)[:40]})
        if score is None and rate is None:
            continue

        out.append({"branch": name[:120], "branch_key": fold_branch(name),
                    "audit_score": score, "implementation": rate})
    return out, report


def read_pasted(text):
    """A pasted table → ``(rows, report)``.

    Tabs, commas or runs of two or more spaces, because what arrives is
    whatever the person's clipboard produced.
    """
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return [], {"columns": {}, "skipped_rows": [], "ignored_values": []}

    if "\t" in "\n".join(lines):
        table = [line.split("\t") for line in lines]
    elif sum(line.count(",") for line in lines) >= len(lines):
        table = list(csv.reader(io.StringIO("\n".join(lines))))
    else:
        table = [re.split(r"\s{2,}", line.strip()) for line in lines]
    return _rows_from_table(table)


def read_workbook(stream, filename=""):
    """An .xlsx or .csv → ``(rows, report)``."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        raw = stream.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig", errors="replace")
        return read_pasted(raw)

    from openpyxl import load_workbook

    book = load_workbook(stream, data_only=True)
    best, best_report = [], None
    for sheet_name in book.sheetnames:
        sheet = book[sheet_name]
        table = [[cell.value for cell in row] for row in sheet.iter_rows()]
        rows, report = _rows_from_table(table)
        if len(rows) > len(best):
            best, best_report = rows, report
            best_report["sheet"] = sheet_name
    return best, (best_report or {"columns": {}, "skipped_rows": [],
                                  "ignored_values": []})


def match_key(key, candidates):
    """Match a folded branch key against folded candidates.

    Returns ``(matched_key, how)`` where ``how`` is ``"exact"``,
    ``"prefix"`` or ``""``.

    Three rungs, and the order is the whole point:

    1. **exact.** ``ELDORET`` on the return against ``ELDORET BRANCH`` on the
       roster — the same branch written two ways, which folding already
       settles.
    2. **a UNIQUE prefix.** Internal Audit write ``Harambee`` where the roster
       says ``HARAMBEE AVE BRANCH``. Nothing else on the roster begins with
       ``HARAMBEE``, so there is one possible answer and taking it is right.
    3. **nothing.** Reported, never guessed.

    Uniqueness is what makes rung 2 safe. ``THIKA`` is a prefix of both
    ``THIKA`` and ``THIKAROADMALLTRM``, which are two different branches — but
    the exact match is tried first, so it never reaches the prefix rung. A key
    that matches two candidates and neither exactly is reported, because
    handing a branch somebody else's audit score is worse than handing it
    none: one row here serves every person in the branch.
    """
    if not key:
        return "", ""
    if key in candidates:
        return key, "exact"
    starts = [c for c in candidates if c.startswith(key)]
    if len(starts) == 1:
        return starts[0], "prefix"
    # Also the other way round: the return may be the LONGER spelling.
    inside = [c for c in candidates if key.startswith(c)]
    if len(inside) == 1:
        return inside[0], "prefix"
    return "", ""


def roster_branches():
    """Every branch the roster knows → ``{folded: spelling}``.

    Used only to report what did and did not match. Both DMC rosters, because
    a branch can appear on either.
    """
    from .models import BranchEmployeeDmcData, BranchFinalEmployeeDmcData

    out = {}
    for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData):
        for branch, unit in model.objects.values_list(
                "staff_branch", "staff_unit"):
            for name in (branch, unit):
                key = fold_branch(name)
                if key and key not in out:
                    out[key] = str(name).strip()
    return out


def annotate(rows):
    """Say which rows reach a branch the roster knows, and which do not."""
    known = roster_branches()
    for row in rows:
        hit, how = match_key(row["branch_key"], known)
        row["matched"] = bool(hit)
        row["match_kind"] = how
        row["roster_branch"] = known.get(hit, "")
    return rows


def save(rows, period, who="", source=""):
    """Write one period, upserting on (period, branch).

    A branch the new return does not mention is LEFT ALONE rather than
    cleared: Internal Audit send a correction for one branch, and clearing the
    rest would blank the audit line for everybody else in the bank.
    """
    from django.db import transaction

    from .models import ScAuditReturn

    written = 0
    with transaction.atomic():
        for row in rows:
            data = dict(row)
            # Everything annotate() adds for the screen. A key the model does
            # not have raises on update_or_create, and these three are added
            # by a function the upload route always calls - so the write path
            # has to drop them, not hope they are absent.
            for added in ("matched", "match_kind", "roster_branch", "id",
                          "updated_at"):
                data.pop(added, None)
            key = data.pop("branch_key")
            data["updated_by"] = who[:150]
            data["source"] = source[:160]
            ScAuditReturn.objects.update_or_create(
                period=period, branch_key=key, defaults=data)
            written += 1
    return written


# ─────────────────────────────────────────────────────────────────────────────
# What the scorecard reads
# ─────────────────────────────────────────────────────────────────────────────


def latest_period(as_at=None):
    """The newest audit period loaded, or None.

    ``as_at`` restricts it to returns that had CLOSED by that date. Internal
    Audit report quarterly and load late, so without this a September card
    picked up a Q4 return as soon as one arrived - a figure from after the
    period the card reports.
    """
    from .live_scorecard import period_at_or_before
    from .models import ScAuditReturn

    periods = (ScAuditReturn.objects.order_by("-period")
               .values_list("period", flat=True).distinct())
    if as_at is None:
        return periods.first()
    return period_at_or_before(list(periods), as_at)


def for_branch(branch, period=None):
    """This branch's audit figures, or None.

    ``{"period", "branch", "audit_score", "implementation"}``. Matched on the
    folded name, exactly — see the note at the top of this module on why not a
    prefix.
    """
    from .models import ScAuditReturn

    key = fold_branch(branch)
    if not key:
        return None
    period = period or latest_period()
    if not period:
        return None
    rows = {r.branch_key: r
            for r in ScAuditReturn.objects.filter(period=period)}
    # The person's branch against the return's branches - exact, then a
    # unique prefix either way. See match_key.
    hit, _ = match_key(key, set(rows))
    row = rows.get(hit)
    if row is None:
        return None
    return {"period": row.period, "branch": row.branch,
            "audit_score": row.audit_score,
            "implementation": row.implementation}


def coverage(period=None):
    """What the return reaches, and what it misses — both directions.

    The second direction is the one that matters: a branch full of staff that
    the return does not mention is a whole branch with no audit score, and it
    looks exactly like an audit that has not happened.
    """
    from .models import ScAuditReturn

    period = period or latest_period()
    if not period:
        return {"period": None, "periods": [], "branches": 0, "matched": 0,
                "unmatched": [], "roster_without_a_return": [],
                "with_score": 0, "with_implementation": 0}

    rows = list(ScAuditReturn.objects.filter(period=period))
    known = roster_branches()
    on_return = set()
    matched = 0
    unmatched = []
    for row in rows:
        hit, _ = match_key(row.branch_key, known)
        if hit:
            matched += 1
            on_return.add(hit)
        else:
            unmatched.append(row.branch)
    return {
        "period": period,
        "periods": sorted(
            ScAuditReturn.objects.values_list("period", flat=True).distinct(),
            reverse=True),
        "branches": len(rows),
        "matched": matched,
        "unmatched": sorted(unmatched),
        # The direction that matters more. A branch full of staff the return
        # does not mention is a whole branch with no audit score, and on the
        # cards it looks exactly like an audit that never happened.
        "roster_without_a_return": sorted(
            spelling for key, spelling in known.items()
            if key not in on_return),
        "with_score": sum(1 for row in rows if row.audit_score is not None),
        "with_implementation": sum(
            1 for row in rows if row.implementation is not None),
    }
