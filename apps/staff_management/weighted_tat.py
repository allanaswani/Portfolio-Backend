"""Weighted TAT, read from the desk's monthly Weighted TAT Dashboard.

No ETL script computes Weighted TAT: every value on the template's Weighted_TAT
sheet is typed. The figures come from the desk's "Weighted TAT Dashboard -
<date>.xlsx", which holds no formulas either - it is the source. Each role sheet
(DIASPORA_RM, MORTGAGE_BUSINESS, BBC and RM) and the Branch sheet scores six
parts, weighted per role (Diaspora RM: TAT Accounts 0.15, TAT Loans 0.30,
Account Error Rate 0.15, Loans Error Rate 0.15, CES 0.15, TAT SLA CRM 0.10),
and gives the month's weighted score in the WEIGHTED SCORES block ("% W. Score"
or "Monthly % W. Score"). That is the figure the desk puts on Weighted_TAT:
Doris Njuki's September 0.775 is the desk's 0.77.

**SLA is the TAT SLA CRM part** - CRM tickets closed inside their SLA.

One dashboard per month is kept (``BoWorkbookFile`` kind ``weighted_tat:YYYY-MM``).
The card reads it for that month: by sales code on a person's card, by branch on
a branch manager's. A cell the dashboard holds as #REF! (the whole BBC and RM
sheet in the 30 Sept 2026 file) is no figure, never a nought.
"""
from __future__ import annotations

import datetime

KIND = "weighted_tat:{:%Y-%m}"
TITLE = "WEIGHTED SCORES"
SLA = "TAT SLA CRM"
SCORE_HEADERS = ("% w. score", "monthly % w. score")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read(stream):
    """The dashboard → {"month", "people": {CODE: score}, "branches": {key: score},
    "sla": {CODE or key: SLA CRM monthly % score}, "sheets", "skipped"}."""
    import openpyxl

    from .bb_live_feeds import _place, branch_key

    book = openpyxl.load_workbook(stream, read_only=True, data_only=True)
    out = {"month": None, "people": {}, "branches": {}, "sla": {},
           "sheets": [], "skipped": {}}
    for ws in book.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for r in rows[:4]:
            for v in r or ():
                if isinstance(v, datetime.datetime) and out["month"] is None:
                    out["month"] = v.date().replace(day=1)
        # A sheet can hold more than one table (Branch: zones, then branches);
        # each starts at a row naming WEIGHTED SCORES, its headers on the next.
        titles_at = [i for i, r in enumerate(rows)
                     if r and TITLE in [str(v).strip() if v else "" for v in r]]
        read_here = skipped = 0
        for n, title in enumerate(titles_at):
            if title + 1 >= len(rows):
                continue
            heads = [str(v).strip().lower() if v is not None else ""
                     for v in rows[title + 1]]
            titles = [str(v).strip() if v is not None else "" for v in rows[title]]
            start_col = titles.index(TITLE)
            score_col = next((j for j in range(start_col, len(heads))
                              if heads[j] in SCORE_HEADERS), None)
            if score_col is None:
                continue
            sla_col = None
            if SLA in titles:
                s_col = titles.index(SLA)
                sla_col = next((j for j in range(s_col, start_col)
                                if heads[j] == "monthly % score"), None)
            # The branch table's first headers read "Branch"; the zone table's
            # read "Zone" - zones are not a card's figure.
            branch_table = heads[:1] == ["branch"] or heads[1:2] == ["branch"]
            zone_table = heads[1:2] == ["zone"]
            if zone_table:
                continue
            stop = titles_at[n + 1] if n + 1 < len(titles_at) else len(rows)
            for r in rows[title + 2:stop]:
                if not r or len(r) <= score_col:
                    continue
                if branch_table:
                    code = r[3] if len(r) > 3 else None
                    key = _place(code) if _number(code) else None
                    if key is None and isinstance(r[1], str):
                        key = branch_key(r[1])
                    if not key:
                        continue
                    target = out["branches"]
                else:
                    code = r[1] if len(r) > 1 else None
                    if not isinstance(code, str) or not code.strip():
                        continue
                    key = code.replace(" ", "").upper()
                    target = out["people"]
                value = r[score_col]
                if _number(value):
                    target[key] = float(value)
                    read_here += 1
                else:
                    skipped += 1
                sla = r[sla_col] if sla_col is not None and len(r) > sla_col else None
                if _number(sla):
                    out["sla"][key] = float(sla)
        out["sheets"].append(f"{ws.title}: {read_here} read")
        if skipped:
            out["skipped"][ws.title] = skipped
    if out["month"] is None:
        raise ValueError("The dashboard's month (the date at the top of each sheet) "
                         "could not be found.")
    return out


def save(found, file_name="", loaded_by=""):
    from .workbook_cards import save_file

    payload = dict(found, month=found["month"].isoformat())
    save_file(KIND.format(found["month"]), payload, file_name, loaded_by)
    from django.core.cache import cache

    cache.delete(KIND.format(found["month"]))


def score(month, code=None, branch=None):
    """The dashboard's weighted score for ``month`` (a date) → float, or None."""
    from django.core.cache import cache

    from .bb_live_feeds import branch_key
    from .workbook_cards import saved

    key = KIND.format(month.replace(day=1))
    data = cache.get(key)
    if data is None:
        data = saved(key) or {}
        cache.set(key, data, 3600)
    if code:
        found = (data.get("people") or {}).get(code.replace(" ", "").upper())
        if found is not None:
            return found
    if branch:
        return (data.get("branches") or {}).get(branch_key(branch))
    return None
