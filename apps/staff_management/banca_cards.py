"""The Banca DSR scorecards, computed exactly as the desk's workbook computes them.

Source: ``Banca_DSRs_ScoreCard 2026 Template.xlsm`` (the card, its List,
targets and constants) and ``2026_Insurance_Data_Actuals_Template.xlsx`` (the
figures). One card sheet, ``Bancassurance_DSR``, for every BANCA DSR on the
List.

**Faithful, quirks included.** The number on the platform must be the number
on the desk's card, so this reproduces what the template does - and checks,
on every load, that the template still does it: each line's formula is read
and compared with the one below, and a template whose formulas changed is
refused rather than scored the old way. Quirks reproduced on purpose:

* "Number of Funded Accounts" reads the ``disbursements`` sheet and "Number of
  disbursed loans" reads ``accounts`` - the template's own wiring (rows 16, 17);
* the interdepartment-survey line reads the ``nps`` sheet, like the NPS line;
* "Collection of Property Sales Value" reads a ``properties_value`` sheet the
  actuals workbook does not have - weight 0, so it never moves the score;
* the staff-engagement line reads another workbook (MANCO) - weight 0 too.

How a figure is looked up, as the template does::

    =VLOOKUP(name, '<sheet>'!$C:$R, month + 4, 0)

by the person's NAME, exact and case-insensitive, in the month's column
(Jan = G). A missing name or an empty cell scores nought: every score is
``IFERROR(MIN(H/G, 1.2), 0)``.

YTD targets (``m`` = the month, ``M`` = the List's prorate for the person):

* "joiner"  G = F * (m - M) / (12 - M)
* "growth"  G = F * (r-1)/(r^n-1) * SUM_{i=1..m} r^(m-i)   r, n = constants G1, G2
            (the three life-premium lines: a target that grows 1.5x a month)
* "fixed"   G = F

The total is ``SUM(J7:J26) / SUM(E7:E25)``.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

CARD_SHEET = "Bancassurance_DSR"
ROLE_CODE = "banca_dsr"
SHEET_KEY = "BANCASSURANCE_DSR"
#: The rows of the card sheet that are lines, and how each forms its YTD target.
YTD_RULE = {7: "joiner", 8: "growth", 9: "growth", 10: "growth", 11: "fixed",
            12: "joiner", 13: "joiner", 14: "fixed", 16: "joiner", 17: "joiner",
            18: "joiner", 19: "fixed", 21: "fixed", 22: "fixed", 24: "joiner",
            25: "fixed"}
#: The template's formulas these rules were read from - checked on every load.
EXPECTED = {
    "joiner": re.compile(r"^=\$F(\d+)\*\(constants!\$B\$2-\$M\1\)/\(12-\$?M\1\)$"),
    "growth": re.compile(
        r"^=\(\$F(\d+)\*\(constants!\$G\$1-1\)/\(constants!\$G\$1\^constants!\$G\$2-1\)\)"
        r" \* SUM\(constants!\$G\$1\^\(constants!\$B\$2-ROW\(INDIRECT\(\"1:\"&constants!\$B\$2\)\)\)\)$"),
}
LOOKUP = re.compile(r'^=\+VLOOKUP\(\$C\$2,INDIRECT\("\[[^\]]+\]"&\$L(\d+)&"!" &"\$[BC]:\$[PR]"\),\$L\$1,0\)$')
SCORE = re.compile(r"^=IFERROR\(MIN\(H(\d+)/G\1,1\.2\),0\)$")


class BancaCardError(Exception):
    """The workbooks cannot be scored as the desk scores them - with why."""


@dataclass
class Line:
    row: int
    perspective: str
    category: str
    description: str
    weight: float
    target: object        # F as the template holds it (F18/F19 are per person)
    rule: str
    sheet: str            # L: the actuals sheet the line reads


@dataclass
class Person:
    pf: object
    sales_code: str
    name: str
    role: str
    joined: float         # the List's prorate: months of the year before joining
    email: str = ""
    reports_to: str = ""


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fold(text):
    """VLOOKUP's match: exact, case-insensitive."""
    return str(text if text is not None else "").strip().lower() \
        if isinstance(text, str) else text


def _formula(cell):
    value = cell.value
    return getattr(value, "text", value)


def read_template(formulas, values):
    """The card's lines, constants, List and property targets → dict.

    ``formulas`` and ``values`` are the same template opened without and with
    ``data_only``. Refuses a template whose line formulas are not the ones
    this module reproduces."""
    if CARD_SHEET not in formulas.sheetnames:
        raise BancaCardError(f"this is not the Banca DSR template - it has no "
                             f"{CARD_SHEET} sheet")
    fcard, vcard = formulas[CARD_SHEET], values[CARD_SHEET]
    problems, lines = [], []
    perspective = category = ""
    for row in range(7, 26):
        b, c = vcard.cell(row, 2).value, vcard.cell(row, 3).value
        if b:
            perspective = str(b).split("\n")[0].strip()
        if c:
            category = re.sub(r"\s*\(\s*[\d.]+%\)\s*$", "", str(c)).strip()
        if row not in YTD_RULE:
            if _num(vcard.cell(row, 5).value):
                problems.append(f"row {row} has a weight but is not a line this "
                                f"module scores")
            continue
        rule = YTD_RULE[row]
        g = _formula(fcard.cell(row, 7))
        if rule in EXPECTED:
            m = EXPECTED[rule].match(str(g or ""))
            if not m or int(m.group(1)) != row:
                problems.append(f"G{row} is {g!r}, not the {rule} target formula")
        elif rule == "fixed" and not (g == f"=F{row}" or _num(g)
                                      or (row == 19 and g == "=F19")):
            problems.append(f"G{row} is {g!r}, not =F{row}")
        h = str(_formula(fcard.cell(row, 8)) or "")
        m = LOOKUP.match(h)
        if not m or int(m.group(1)) != row:
            problems.append(f"H{row} is {h!r}, not the actuals lookup")
        i = str(_formula(fcard.cell(row, 9)) or "")
        m = SCORE.match(i)
        if not m or int(m.group(1)) != row:
            problems.append(f"I{row} is {i!r}, not IFERROR(MIN(H/G,1.2),0)")
        if str(_formula(fcard.cell(row, 10)) or "") != f"=I{row}*E{row}":
            problems.append(f"J{row} is not =I{row}*E{row}")
        f = _formula(fcard.cell(row, 6))
        if row == 18 and f != "=VLOOKUP($C$2,target!$B:$D,3,0)":
            problems.append(f"F18 is {f!r}, not the property target lookup")
        if row == 19 and f != "=F18*8200000":
            problems.append(f"F19 is {f!r}, not =F18*8200000")
        weight = vcard.cell(row, 5).value
        lines.append(Line(
            row=row, perspective=perspective, category=category,
            description=str(vcard.cell(row, 4).value or "").strip(),
            weight=float(weight) if _num(weight) else 0.0,
            target=vcard.cell(row, 6).value if row not in (18, 19) else None,
            rule=rule, sheet=str(vcard.cell(row, 12).value or "").strip()))
    if str(_formula(fcard["J27"])) != "=SUM(J7:J26)/E27" or \
            str(_formula(fcard["E27"])) != "=SUM(E7:E25)":
        problems.append("the total is no longer SUM(J7:J26)/SUM(E7:E25)")
    if str(_formula(formulas["constants"]["B1"])) != "=$B$2+4":
        problems.append("constants!B1 (the month column) is no longer B2+4")
    if problems:
        raise BancaCardError("The Banca DSR template's formulas are not the ones "
                             "the platform reproduces, so it was not scored: "
                             + "; ".join(problems))

    const = values["constants"]
    growth_rate, growth_months = const["G1"].value, const["G2"].value
    if not (_num(growth_rate) and _num(growth_months)):
        raise BancaCardError("constants!G1 / G2 (the life-premium growth rate "
                             "and months) are not numbers")
    people = []
    for row in list(values["list"].iter_rows(min_row=2, values_only=True)):
        if not row or not row[1] or not row[2]:
            continue
        people.append(Person(pf=row[0], sales_code=str(row[1]).strip().upper(),
                             name=str(row[2]), role=str(row[3] or ""),
                             joined=row[8] if len(row) > 8 else None,
                             email=str(row[5] or "") if len(row) > 5 else "",
                             reports_to=str(row[10] or "") if len(row) > 10 else ""))
    targets = {}
    for row in values["target"].iter_rows(min_row=2, values_only=True):
        if row and row[1] is not None and _fold(row[1]) not in targets:
            targets[_fold(row[1])] = row[3] if len(row) > 3 else None
    month_count = const["B2"].value
    return {"lines": lines, "people": people, "targets": targets,
            "growth_rate": float(growth_rate), "growth_months": float(growth_months),
            "month_count": month_count, "year": _year(const)}


def _year(const):
    v = const["B6"].value
    return int(v) if _num(v) else datetime.date.today().year


def read_actuals(book):
    """{sheet: {folded name: [12 monthly values]}} - first row per name wins,
    as VLOOKUP's does."""
    out = {}
    for ws in book.worksheets:
        rows = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 3 or row[2] is None:
                continue
            key = _fold(row[2])
            if key not in rows:
                rows[key] = [row[6 + i] if len(row) > 6 + i else None for i in range(12)]
        out[ws.title] = rows
    return out


def _lookup(actuals, sheet, name, month):
    """H: the VLOOKUP, or the error it would give → (value, error text)."""
    if sheet not in actuals:
        return None, "#REF!"
    row = actuals[sheet].get(_fold(name))
    if row is None:
        return None, "#N/A"
    v = row[month - 1]
    if v is None:
        return 0.0, ""             # an empty cell reads 0
    if _num(v):
        return float(v), ""
    return v, "#VALUE!"            # text: H/G fails, IFERROR scores 0


def ytd_target(line, f, month, joined, rate, months):
    if not _num(f):
        return None
    if line.rule == "fixed":
        return float(f)
    if line.rule == "growth":
        return (f * (rate - 1) / (rate ** months - 1)
                * sum(rate ** (month - i) for i in range(1, month + 1)))
    if not _num(joined):
        return None                # VLOOKUP of the prorate failed: #N/A
    if 12 - joined == 0:
        return None
    return f * (month - joined) / (12 - joined)


def score(actual, ytd):
    """IFERROR(MIN(H/G, 1.2), 0)."""
    if not (_num(actual) and _num(ytd)) or ytd == 0:
        return 0.0
    return min(actual / ytd, 1.2)


def compute_card(template, actuals, person, month):
    """One person's card for one month → {"lines": [...], "total": float}."""
    rate, months = template["growth_rate"], template["growth_months"]
    prop = template["targets"].get(_fold(person.name))
    out, total_w, total = [], 0.0, 0.0
    for line in template["lines"]:
        if line.row == 18:
            f = prop if _num(prop) else None
        elif line.row == 19:
            f = prop * 8200000 if _num(prop) else None
        else:
            f = line.target
        ytd = ytd_target(line, f, month, person.joined, rate, months)
        actual, error = _lookup(actuals, line.sheet, person.name, month)
        s = score(actual if not error else None, ytd)
        weighted = s * line.weight
        total_w += line.weight
        total += weighted
        out.append({
            "row": line.row, "kpi": f"banca_{line.sheet or line.row}_{line.row}",
            "perspective": line.perspective, "category": line.category,
            "description": line.description, "weight": line.weight,
            "fy_target": f, "ytd_target": ytd,
            "actual": actual if not error else None, "error": error,
            "empty": not error and actual == 0.0 and _cell_empty(actuals, line.sheet,
                                                                  person.name, month),
            "score": s, "weighted": weighted, "sheet": line.sheet,
        })
    return {"lines": out, "total": total / total_w if total_w else 0.0,
            "month": month}


def _cell_empty(actuals, sheet, name, month):
    row = (actuals.get(sheet) or {}).get(_fold(name))
    return row is not None and row[month - 1] is None


def months_with_figures(actuals, people):
    """Months in which the actuals workbook holds any figure for these people."""
    names = {_fold(p.name) for p in people}
    found = set()
    for rows in actuals.values():
        for key, values in rows.items():
            if key in names:
                found |= {i + 1 for i, v in enumerate(values) if _num(v)}
    return sorted(found)


def desk_scores(values):
    """The template's monthly_summary: the desk's own score per person and
    month → {(sales code, month): score}. The answer key."""
    if "monthly_summary" not in values.sheetnames:
        return {}
    out = {}
    for row in values["monthly_summary"].iter_rows(min_row=2, values_only=True):
        if not row or not row[1]:
            continue
        for m in range(12):
            v = row[5 + m] if len(row) > 5 + m else None
            if _num(v):
                out[(str(row[1]).strip().upper(), m + 1)] = float(v)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Loading, storing, showing
# ─────────────────────────────────────────────────────────────────────────────

#: Two scores this close are the same score (floating point only).
SAME = 1e-9


def is_banca_template(formulas):
    return CARD_SHEET in formulas.sheetnames


def compute_months(template, actuals, desk, only=None):
    """Every month the actuals workbook holds figures for (or ``only``) →
    ({month: [(person, card)]}, [mismatch text]).

    ``desk`` is the template's own monthly_summary. Where it holds a score for
    a person and month, the computed card must give exactly that score; any
    that does not is returned as a mismatch and the load is refused."""
    people = [p for p in template["people"] if p.role.strip().upper() == "BANCA DSR"]
    months = months_with_figures(actuals, people)
    if only is not None:
        if only not in months:
            raise BancaCardError(
                f"The actuals workbook has no figure for any Banca DSR in "
                f"{datetime.date(template['year'], only, 1):%B %Y}.")
        months = [only]
    if not months:
        raise BancaCardError("The actuals workbook has no figures for anyone "
                             "on the Banca DSR List.")
    by_month, mismatches = {}, []
    for month in months:
        cards = []
        for person in people:
            card = compute_card(template, actuals, person, month)
            want = desk.get((person.sales_code, month))
            card["desk_score"] = want
            if want is not None and abs(card["total"] - want) > SAME:
                mismatches.append(
                    f"{person.sales_code} {person.name} "
                    f"{datetime.date(template['year'], month, 1):%b %Y}: the desk's "
                    f"monthly_summary says {want:.6%}, computed {card['total']:.6%}")
            cards.append((person, card))
        by_month[month] = cards
    return by_month, mismatches


def store(cards, month_start, loaded_by=""):
    """One row per person per month, replaced on reload → how many."""
    from .models import BancaScorecard

    for person, card in cards:
        BancaScorecard.objects.update_or_create(
            sales_code=person.sales_code, month=month_start,
            defaults={"staff_name": person.name, "joined": person.joined or 0,
                      "reports_to": person.reports_to, "card": card,
                      "total": card["total"], "loaded_by": loaded_by})
    return len(cards)


def stored_for(sales_code, as_at=None):
    """The newest stored card on or before ``as_at`` → BancaScorecard or None."""
    from .models import BancaScorecard

    rows = BancaScorecard.objects.filter(sales_code__iexact=(sales_code or "").strip())
    if as_at is not None:
        rows = rows.filter(month__lte=as_at)
    return rows.order_by("-month").first()


def months_loaded(sales_code):
    from .models import BancaScorecard

    return [m.strftime("%Y-%m") for m in BancaScorecard.objects.filter(
        sales_code__iexact=(sales_code or "").strip()).order_by("month")
        .values_list("month", flat=True)]


def _month_end(first):
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt - datetime.timedelta(days=1)


def card_payload(record, asked=None):
    """A stored Banca DSR card in the shape every other card has."""
    data = record.card or {}
    month_end = _month_end(record.month)
    perspectives, seen = [], {}
    for line in data.get("lines", []):
        name = line["perspective"] or "Other"
        if name not in seen:
            seen[name] = {"perspective": name, "weight": 0.0, "lines": []}
            perspectives.append(seen[name])
        seen[name]["weight"] += line["weight"]
        as_at = f"as at {month_end.day} {month_end:%b %Y}"
        pending = ""
        if line.get("error") == "#REF!":
            as_at = (f"the template reads a '{line['sheet']}' sheet the actuals "
                     f"workbook does not have - scores 0, as on the desk's card")
        elif line.get("error") == "#N/A":
            as_at = ("no row for this name on the actuals sheet - scores 0, as on "
                     "the desk's card")
        elif line.get("empty"):
            as_at = (f"no figure entered for {month_end:%B} in the actuals "
                     f"workbook - read as 0, as the workbook reads it")
        fy, ytd, actual = line.get("fy_target"), line.get("ytd_target"), line.get("actual")
        seen[name]["lines"].append({
            "kpi_code": line["kpi"], "kpi_name": line["description"],
            "measure_of_success": line["description"],
            "category": line.get("category", ""),
            "weight": line["weight"],
            "ytd_target": ytd if _num(ytd) else None,
            "annual_target": fy if _num(fy) else None,
            "target_text": "", "prior_year": None, "growth_target": None,
            "target_field": "", "target_source": "the Banca DSR scorecard template",
            "full_year_target": _num(fy) and _num(ytd) and fy == ytd,
            "ytd_actual": actual if _num(actual) else None,
            "warehouse_said": None,
            "score": line["score"], "weighted_score": line["weighted"],
            "counted_in_total": True,
            "as_at": as_at, "as_at_date": month_end.isoformat(),
            "higher_is_better": True, "full_marks_rule": "", "score_cap": 1.2,
            "pending": pending, "pending_label": "", "diagnostic": "",
        })
    total = record.total
    empty = sum(1 for ln in data.get("lines", []) if ln.get("empty") and ln["weight"])
    weighted_lines = sum(1 for ln in data.get("lines", []) if ln["weight"])
    return {
        "has_card": True, "live": False, "banca": True,
        "staff": {"sales_code": record.sales_code, "name": record.staff_name,
                  "title": "BANCA DSR", "role_code": ROLE_CODE,
                  "branch": "Insurance", "team_leader": record.reports_to or "",
                  "roster": "the Banca DSR scorecard workbook", "started": None},
        "book": {"customers": None, "note": ""},
        "period": {"label": record.month.strftime("%B %Y"),
                   "as_at": month_end.isoformat()},
        "target_source": "the Banca DSR scorecard template",
        "performance_score": round(total, 4) if _num(total) else None,
        "scored_lines": sum(len(p["lines"]) for p in perspectives),
        "pending_lines": 0, "scored_weight": 1.0, "unscored_weight": 0.0,
        "perspectives": perspectives,
        "months_loaded": months_loaded(record.sales_code),
        "coverage_note": (
            f"{empty} of {weighted_lines} weighted lines had no figure for "
            f"{record.month:%B %Y} in the actuals workbook, so they read as 0 - "
            f"as the workbook itself reads them." if empty else ""),
        "showing_other_month": (
            "" if asked is None or asked.replace(day=1) == record.month else
            f"Nothing is loaded for {asked:%B %Y}; this is "
            f"{record.month:%B %Y}, the latest month on or before it."),
        "how_scored": ("Computed exactly as the desk's Banca DSR scorecard "
                       "workbook computes it, line by line; on load every card "
                       "is checked against the score the desk's own "
                       "monthly_summary records."),
    }
