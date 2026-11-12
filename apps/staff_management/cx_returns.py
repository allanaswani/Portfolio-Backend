"""The CX team's two monthly returns behind the back-office CRM and KYC lines.

No report computes either line. Both are typed onto the BO actuals template
from the CX team's own workbooks, which hold the whole year month by month:

* **CRM LOGS - <year>.xlsx** - CRM entries logged each month per person, one
  row per CRM log-in ("CRM LOG IN CREDITIALS"). The template's ``CRM`` sheet
  is that person's running total: Henry Serem (Eldoret) 214, 57, 109 ... gives
  214, 271, 380 ... 798 at August, the template's figures exactly. It follows
  the PERSON, not the branch in the file: Joseph Kinuthia is on Embu's row
  and on the template as JKK3227 at Naivasha.
* **Data Update - <year>.xlsx** - data-update forms received per branch per
  month ("2026 Monthly" sheet). The template's ``KYC`` sheet gives every
  back-office person at a branch the branch's running total: Buru Buru 15,
  28, 25 ... gives 15, 43, 68 ... 170 for the BOM, CSO and tellers alike.
  The desk keeps two rows that are not branches - AMUTHAMA (one CSO's own
  count) and Diaspora - and its template puts those people at that "branch",
  so the person's branch is read off the template's KYC row first.

One return per kind and year is kept (``BoWorkbookFile`` kind
``cx_return:crm:2026`` / ``cx_return:kyc:2026``); loading the next copy of the
file replaces it. A card month reads the running total of the months up to it.
Text in a month cell (``TSC``) is no figure, never a nought.
"""
from __future__ import annotations

import re

KIND = "cx_return:{}:{}"
CRM, KYC = "crm", "kyc"
LABELS = {CRM: "CRM logs", KYC: "Data update (KYC)"}

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
#: How the Data Update file spells branches the template spells otherwise.
BRANCH_ALIAS = {"hurlingam": "hurlingham", "riveroad": "riverroad"}


def _month_of(header):
    text = re.sub(r"[^a-z]", "", str(header or "").lower())[:3]
    return MONTHS.get(text) if len(text) == 3 else None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def branch_of(name):
    """A branch as either file or the template writes it -> one key."""
    from .bb_live_feeds import PLACE_ALIAS, branch_key

    key = branch_key(name)
    key = BRANCH_ALIAS.get(key, key)
    return PLACE_ALIAS.get(key, key)


def read(stream):
    """Either return -> ``{"kind", "year", "rows": [{label, branch, months}],
    "skipped": [...]}``. Which return it is comes from its header row."""
    import openpyxl

    book = openpyxl.load_workbook(stream, read_only=True, data_only=True)
    for sheet in book.worksheets:
        rows = [list(r) for r in sheet.iter_rows(values_only=True)]
        for at, row in enumerate(rows[:10]):
            heads = [str(c or "").strip().upper() for c in row]
            if any("CRM LOG" in h for h in heads):
                kind, label_col = CRM, next(i for i, h in enumerate(heads) if "CRM LOG" in h)
                branch_col = heads.index("BRANCH") if "BRANCH" in heads else None
            elif "BRANCH NAME" in heads and any(_month_of(h) == 1 for h in heads):
                kind, label_col = KYC, heads.index("BRANCH NAME")
                branch_col = label_col
            else:
                continue
            months = {i: _month_of(h) for i, h in enumerate(heads)
                      if _month_of(h) and "CUMULATIVE" not in h and "TARGET" not in h}
            year = _year(sheet.title, heads, getattr(stream, "name", ""))
            return _rows(kind, year, rows[at + 1:], label_col, branch_col, months)
    raise ValueError("neither a CRM LOGS nor a Data Update return: no header "
                     "row with 'CRM LOG IN CREDITIALS' or 'BRANCH NAME' + months")


def _year(title, heads, file_name):
    for text in [title, *heads, file_name]:
        found = re.search(r"\b(20\d\d)\b", str(text or ""))
        if found:
            return int(found.group(1))
    raise ValueError("the return's year is not on the sheet name, header or file name")


def _rows(kind, year, rows, label_col, branch_col, months):
    out, skipped = [], []
    for row in rows:
        label = str(row[label_col] or "").strip() if len(row) > label_col else ""
        if not label or label.upper() == "TOTAL":
            continue
        figures = {}
        for col, month in months.items():
            cell = row[col] if len(row) > col else None
            value = _number(cell)
            if value is None and cell not in (None, ""):
                skipped.append(f"{label} {month:02d}: {cell}")
            if value is not None:
                figures[str(month)] = value
        if not figures:
            continue
        branch = str(row[branch_col] or "").strip() if branch_col is not None else ""
        out.append({"label": label, "branch": branch, "months": figures})
    return {"kind": kind, "year": year, "rows": out, "skipped": skipped}


def save(found, file_name="", loaded_by=""):
    from django.core.cache import cache

    from .workbook_cards import save_file

    key = KIND.format(found["kind"], found["year"])
    save_file(key, found, file_name, loaded_by)
    cache.delete(key)


def _loaded(kind, year):
    from django.core.cache import cache

    from .workbook_cards import saved

    key = KIND.format(kind, year)
    data = cache.get(key)
    if data is None:
        data = saved(key) or {}
        cache.set(key, data, 3600)
    return data


def _running_total(row, month):
    values = [v for m, v in (row.get("months") or {}).items() if int(m) <= month]
    return float(sum(values)) if values else None


def _one_slip(a, b):
    """Equal, or one letter added, dropped or changed (MILKAH/Milka,
    DABASO/Dabasso, PHARECE/Pharace) - words of four letters or more only."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _same_branch_spelling(rows, names, branches):
    """The CRM file names a person as the CX team types it: Peter Ibrae
    Dabasso is PETER DABASO, Sharon Wanjiru is SHARON KIHUNGU. Failing a full
    name match, a row at the person's own branch sharing a name word (one
    letter's slip allowed) is theirs - when it is the only such row there."""
    from .live_scorecard import name_tokens

    wanted = {branch_of(b) for b in branches if b}
    words = set().union(*(name_tokens(n) for n in names if n)) if names else set()
    if not wanted or not words:
        return []
    return [r for r in rows if branch_of(r.get("branch")) in wanted
            and any(_one_slip(w, x) for w in name_tokens(r["label"]) for x in words)]


def running_total(kind, year, month, names=(), branches=()):
    """The return's year-to-date figure at ``month`` -> float, or None.

    CRM: the one row whose name is this person (``names`` - the card's and the
    template's spelling); two rows that could be them reads as none. KYC: the
    row of the first of ``branches`` the return has.
    """
    from .live_scorecard import names_agree

    rows = _loaded(kind, year).get("rows") or []
    if kind == CRM:
        mine = [r for r in rows if any(n and names_agree(r["label"], n) for n in names)]
        if not mine:
            mine = _same_branch_spelling(rows, names, branches)
        return _running_total(mine[0], month) if len(mine) == 1 else None
    by_branch = {branch_of(r["label"]): r for r in rows}
    for branch in branches:
        row = by_branch.get(branch_of(branch)) if branch else None
        if row is not None:
            return _running_total(row, month)
    return None
