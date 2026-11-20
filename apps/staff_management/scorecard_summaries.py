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


def group_summaries(year, upto):
    """Every group's summary for ``year``, January to ``upto`` →
    [{"group", "sheet", "workbook", "headers", "months", "rows",
      "from_desk", "from_archive"}]. ``rows`` hold the identity cells, a score
    per month (None when there is none), the change on the month before and,
    on a ranked sheet, the rank."""
    from . import workbook_cards as wc

    out = []
    for book_kind, folder in FOLDERS.items():
        spec = wc.SPECS[book_kind]
        book = wc.saved(spec.files[0], year)
        if book is None:
            continue
        archived = archived_scores(year, upto, folder)
        for sheet, header, code_col, first in spec.summaries:
            grid = (book.get("tables") or {}).get(sheet) or []
            if len(grid) <= header:
                continue
            head = [str(h).strip() if h not in (None, "") else ""
                    for h in grid[header][:first]]
            rows, desk_months, archive_months = [], set(), set()
            for row in grid[header + 1:]:
                code = str(row[code_col] if len(row) > code_col else "").strip().upper()
                if not code:
                    continue
                scores = []
                for month in range(1, upto + 1):
                    column = first + month - 1
                    desk = _number(row[column]) if column < len(row) else None
                    if desk is not None:
                        desk_months.add(month)
                        scores.append(desk)
                        continue
                    kept = archived.get((code, month))
                    if kept is not None:
                        archive_months.add(month)
                    scores.append(kept)
                filled = [s for s in scores if s is not None]
                change = (scores[-1] - scores[-2]
                          if len(scores) >= 2 and scores[-1] is not None
                          and scores[-2] is not None else None)
                rows.append({"identity": [_identity(row[i]) if i < len(row) else None
                                          for i in range(first)],
                             "code": code, "scores": scores, "change": change,
                             "latest": filled[-1] if filled else None})
            ranked = sheet in RANKED
            if ranked:
                order = sorted((r for r in rows if r["scores"][-1] is not None),
                               key=lambda r: -r["scores"][-1])
                for n, r in enumerate(order, 1):
                    r["rank"] = n
            out.append({
                "group": (f"{folder} - RBO" if sheet.startswith("RBO_") else folder),
                "sheet": sheet, "workbook": folder,
                "headers": head,
                "months": [_month_label(year, m) for m in range(1, upto + 1)],
                "ranked": ranked, "rows": rows,
                "from_desk": sorted(desk_months),
                "from_archive": sorted(archive_months),
            })
    return out


def _source_note(group, year):
    def names(months):
        return ", ".join(_month_label(year, m) for m in months) or "none"

    return (f"The desk's {group['sheet']} for the months it scored ({names(group['from_desk'])}); "
            f"the archived cards after that ({names(group['from_archive'])}). "
            f"A blank is a month with neither.")


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
        sheets.append({"title": g["group"][:31], "note": _source_note(g, year),
                       "headers": headers, "rows": rows})
    if not sheets:
        sheets.append({"title": "Summary", "headers": ["Note"], "rows": [],
                       "empty": "No scorecards workbook is loaded for this year."})
    return report_xlsx.build(sheets)
