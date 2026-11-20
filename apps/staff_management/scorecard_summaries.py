"""Each group's monthly summary, laid out as the desk's workbooks lay it out.

The desk's scorecard workbooks each carry a summary sheet that their macro
(``Do_Monthly_Summary``) fills: one row per person, then a score per month,
January to December.

* back office: ``Monthly_Summ`` (BOMs, CSOs, tellers ...) and
  ``RBO_Monthly_Summ`` (RBO and TL_RBO);
* sales: ``Monthly_Summ``;
* branch managers: ``Branch_Monthly_Summary``, with a rank.

:func:`group_summaries` rebuilds each of them for a month: the person's own
columns exactly as the desk's sheet has them (PF, sales code, name, role,
branch, zone where the sheet has it), each month the desk scored straight off
its sheet, and each later month from that month's archived card
(:mod:`scorecard_archive`) - the card the person was sent. A month that is
neither is left blank, never estimated. Then the change on the month before,
and, on the branch managers' sheet, the rank on the latest month, as the
desk's sheet has them.
"""
from __future__ import annotations

import datetime
import json
import os
import re

#: The archive's folder for each workbook (scorecard_reach.BOOK_NAMES).
FOLDERS = {"back_office": "Back office", "sales": "Sales",
           "branch_business": "Branch managers"}
#: Sheets that end with a rank on the latest month (the desk's own column).
RANKED = {"Branch_Monthly_Summary"}


def _month_label(year, month):
    return datetime.date(year, month, 1).strftime("%b %y")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _identity(value):
    """A person's own cell as the desk wrote it (a PF 1329.0 is 1329)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def archived_scores(year, upto, folder):
    """{(SALES CODE, month): score} off the archived cards of ``folder`` for
    January to ``upto``. Of several versions of one card, the newest."""
    from .scorecard_archive import archive_dir

    out, when = {}, {}
    for month in range(1, upto + 1):
        path = os.path.join(archive_dir(), f"{year}-{month:02d}", folder)
        if not os.path.isdir(path):
            continue
        for name in os.listdir(path):
            if not name.endswith(".json"):
                continue
            full = os.path.join(path, name)
            try:
                with open(full, encoding="utf-8") as f:
                    card = json.load(f)
            except (OSError, ValueError):
                continue
            code = str((card.get("staff") or {}).get("sales_code") or "").strip().upper()
            score = _number(card.get("performance_score"))
            if not code or score is None:
                continue
            key, stamp = (code, month), os.path.getmtime(full)
            if key not in when or stamp > when[key]:
                out[key], when[key] = score, stamp
    return out


def _desk_rows(book, spec):
    """{SALES CODE: (identity cells, headers, {month: score})} off the desk's
    summary sheets - the desk's own columns and its scores, for whoever is on
    them. Only used to fill in people who hold a card (see group_summaries)."""
    out = {}
    for sheet, header, code_col, first in spec.summaries:
        grid = (book.get("tables") or {}).get(sheet) or []
        if len(grid) <= header:
            continue
        head = [str(h).strip() if h not in (None, "") else "" for h in grid[header][:first]]
        for row in grid[header + 1:]:
            code = str(row[code_col] if len(row) > code_col else "").strip().upper()
            if not code or code in out:
                continue
            scores = {}
            for month in range(1, 13):
                column = first + month - 1
                value = _number(row[column]) if column < len(row) else None
                if value is not None:
                    scores[month] = value
            out[code] = ([_identity(row[i]) if i < len(row) else None
                          for i in range(first)], head, scores)
    return out


def _list_identity(head, holder, role):
    """Someone the desk's summary sheet does not have: their List columns,
    under the sheet's own headings."""
    from .workbook_cards import _key

    values = []
    for h in head:
        k = _key(h)
        values.append(holder.pf if k.startswith("pf")
                      else holder.sales_code if "code" in k
                      else holder.name if "name" in k
                      else role if k == "role"
                      else holder.branch if k == "branch"
                      else None)
    return values


def _role_of(spec, holder):
    return holder.role or str(getattr(spec, "role_code", "") or "").upper() or "(no role)"


def group_summaries(year, upto):
    """Every group's summary for ``year``, January to ``upto`` →
    [{"group", "workbook", "role", "headers", "months", "rows", "ranked",
      "from_desk", "from_archive", "no_score"}], one group per role.

    **Who is on it:** the people who hold a card now - the workbook's List,
    less the no-card list and anybody whose branch reads "left", and only
    roles the workbook has a card for (the same people as Cards -> Who holds
    them). The desk's summary sheets also carry people who have left or never
    had a card; those are not in a group. **The columns** are the desk's own
    summary row for the person where it has one (PF, zone ...), else the
    List's. **A month's score** is the desk's for the months it scored, else
    the archived card's; a month with neither is blank. Card holders with no
    score in any month are named in ``no_score`` instead of a blank row.
    """
    from . import workbook_cards as wc

    out = []
    for book_kind, folder in FOLDERS.items():
        spec = wc.SPECS[book_kind]
        book = wc.saved(spec.files[0], year)
        if book is None:
            continue
        archived = archived_scores(year, upto, folder)
        desk = _desk_rows(book, spec)
        default_head = (next(iter(desk.values()))[1] if desk
                        else ["PF", "Sales code", "Name", "Role", "Branch"])
        cards = book.get("cards") or {}
        groups = {}
        for holder in wc.holders(book):
            if not holder.sales_code or holder.sheet not in cards:
                continue
            if str(holder.branch or "").strip().lower() == "left":
                continue
            role = _role_of(spec, holder)
            found = desk.get(holder.sales_code)
            if found:
                identity, head, desk_scores = found
            else:
                head, desk_scores = default_head, {}
                identity = _list_identity(head, holder, role)
            g = groups.setdefault(role, {"rows": [], "head": head,
                                         "desk": set(), "archive": set(),
                                         "no_score": []})
            scores = []
            for month in range(1, upto + 1):
                if month in desk_scores:
                    g["desk"].add(month)
                    scores.append(desk_scores[month])
                    continue
                kept = archived.get((holder.sales_code, month))
                if kept is not None:
                    g["archive"].add(month)
                scores.append(kept)
            if all(v is None for v in scores):
                g["no_score"].append(f"{holder.name} ({holder.sales_code})")
                continue
            change = (scores[-1] - scores[-2]
                      if len(scores) >= 2 and scores[-1] is not None
                      and scores[-2] is not None else None)
            g["rows"].append({"identity": identity, "code": holder.sales_code,
                              "scores": scores, "change": change})
        ranked = any(sheet in RANKED for sheet, *_ in spec.summaries)
        for role, g in sorted(groups.items(), key=lambda kv: (-len(kv[1]["rows"]), kv[0])):
            if ranked:
                order = sorted((r for r in g["rows"] if r["scores"][-1] is not None),
                               key=lambda r: -r["scores"][-1])
                for n, r in enumerate(order, 1):
                    r["rank"] = n
            out.append({
                "group": f"{folder} - {role}", "workbook": folder, "role": role,
                "sheet": ", ".join(s[0] for s in spec.summaries),
                "headers": g["head"],
                "months": [_month_label(year, m) for m in range(1, upto + 1)],
                "ranked": ranked, "rows": g["rows"],
                "from_desk": sorted(g["desk"]), "from_archive": sorted(g["archive"]),
                "no_score": g["no_score"],
            })
    return out


def _source_note(group, year):
    def names(months):
        return ", ".join(_month_label(year, m) for m in months) or "none"

    note = (f"{group['role']}: the people who hold this card now. The desk's "
            f"{group['sheet']} for the months it scored ({names(group['from_desk'])}); "
            f"the archived cards after that ({names(group['from_archive'])}). "
            f"A blank is a month with neither.")
    if group["no_score"]:
        note += f" No score in any month yet: {', '.join(group['no_score'])}."
    return note


def summaries_workbook(year, upto):
    """The summaries as one Excel workbook, a sheet per group → bytes."""
    from apps.observability import report_xlsx

    sheets = []
    for g in group_summaries(year, upto):
        headers = [h or f"Column {i + 1}" for i, h in enumerate(g["headers"])]
        headers += [f"{m} %" for m in g["months"]] + ["Change on last month %"]
        if g["ranked"]:
            headers.append("Rank")
        rows = []
        for r in g["rows"]:
            values = list(r["identity"]) + list(r["scores"]) + [r["change"]]
            if g["ranked"]:
                values.append(r.get("rank"))
            rows.append(values)
        short = {"Back office": "BO", "Branch managers": "BM"}.get(g["workbook"], g["workbook"])
        title = re.sub(r"[\\/?*\[\]:]", " ", f"{short} - {g['role']}")[:31]
        sheets.append({"title": title, "note": _source_note(g, year),
                       "headers": headers, "rows": rows})
    if not sheets:
        sheets.append({"title": "Summary", "headers": ["Note"], "rows": [],
                       "empty": "No scorecards workbook is loaded for this year."})
    return report_xlsx.build(sheets)
