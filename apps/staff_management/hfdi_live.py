"""HFDI (properties) cards for the month still open, from the properties
desk's own report sources.

The desk's figures come from datawarehouse-etls ``hfcb_properties_reports``
(group_synergies_report.py and its siblings). People are matched to their
sales code through ``hfdi_employee_data`` (sales_code, staff_name, active) -
the table those reports join every source on - by their name's words, only
where exactly one employee row carries them.

A sheet goes live the way IB deposit growth does: the person's figure is the
desk's own figure for its closed month plus the change in the report's source
since. For each sheet the candidate rules below (each read off the report) are
run for the month before the desk's and the desk's month; the first whose
change gives the desk's own change for every person the desk scored, within
TOLERANCE, is the one used. A sheet no rule reproduces keeps the desk's figure.

Sources (group_synergies_report.py):
* bancassurance_sale - insurance_policies, de-duplicated on r_number +
  starting_date, its two code fixes (Mary Mungai -> MM4251, Lucy Ngima Maina's
  policy -> AMM3550), paid premiums by starting month;
* bank_accounts / accounts_deposits - daily_sales_accounts_with_cto opened
  this year by sale_code, "Funded" when bal > 0 or account_cto > 0;
* mortgage_sale - iapply_loan_approvals_data_dump by seller_code: approved
  when the approved amount is above 0 with an approval date (offer letter,
  else drawdown initiation) and not cancelled.
"""
from __future__ import annotations

import datetime

TOLERANCE = 0.005
_DATE = "CASE WHEN {c}::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN {c}::text::date END"


def _rows(sql, params):
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = 120000")
        cur.execute(sql, params)
        return cur.fetchall()


def _merge(a, b):
    """Two {key: [12 months]} added."""
    out = {k: list(v) for k, v in a.items()}
    for k, v in b.items():
        out[k] = [x + y for x, y in zip(out.get(k, [0.0] * 12), v)]
    return out


def _monthly(rows):
    """[(code, date, value)] → {CODE: [ytd Jan..Dec]}."""
    out = {}
    for code, when, value in rows:
        if not code or not isinstance(when, datetime.date):
            continue
        months = out.setdefault(str(code).strip().upper(), [0.0] * 12)
        for m in range(when.month, 13):
            months[m - 1] += float(value or 0)
    return out


# ── the report's sources, as candidate rules ───────────────────────────────

def employee_codes():
    """The active hfdi_employee_data sales codes, upper case - the report's
    employee map (load_employee_map keeps active rows only)."""
    return {str(c).strip().upper() for c, active in _rows(
        "SELECT sales_code, active FROM hfdi_employee_data", [])
        if c and str(active).strip().lower() in ("1", "true", "yes", "y")}


def resolve_partial_codes(codes, employees, digits=4):
    """group_synergies_report.resolve_partial_codes: a code that is not an
    employee's (e.g. "3561") becomes the one employee sales code ending in the
    same four digits (EWK3561); digits shared by several codes are left alone.
    → {raw code: resolved code} for the codes it changes."""
    import re

    ends = {}
    for e in employees:
        m = re.search(r"(\d{%d})$" % digits, e)
        if m:
            ends.setdefault(m.group(1), []).append(e)
    partial = {k: v[0] for k, v in ends.items() if len(v) == 1}
    out = {}
    for raw in codes:
        code = re.sub(r"\.0+$", "", str(raw or "").strip().upper())
        if code and code not in employees and code in partial:
            out[raw] = partial[code]
    return out


def insurance_paid(year):
    code = ("CASE WHEN LOWER(c.sales_person) LIKE '%%mary mungai%%' THEN 'MM4251' "
            "WHEN LOWER(c.insured) LIKE '%%lucy ngima maina%%' THEN 'AMM3550' ELSE c.code END")
    sql = f"""
        WITH cte AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY CONCAT(r_number, starting_date)
                                         ORDER BY r_number, starting_date DESC) AS rn
            FROM insurance_policies)
        SELECT UPPER(TRIM(({code}))), {_DATE.format(c='c.starting_date')},
               COALESCE(NULLIF(TRIM(c.paid::text), ''), '0')::numeric
        FROM cte c WHERE c.rn = 1 AND c.year::text = %s"""
    rows = _rows(sql, [str(year)])
    fixed = resolve_partial_codes({r[0] for r in rows}, employee_codes())
    return _monthly([(fixed.get(c, c), when, v) for c, when, v in rows])


def _accounts(year, funded, value):
    sql = f"""
        SELECT UPPER(TRIM(sale_code::text)), {_DATE.format(c='acc_open_date')},
               {'COALESCE(bal, 0)' if value == 'bal' else '1'}
        FROM daily_sales_accounts_with_cto
        WHERE {_DATE.format(c='acc_open_date')} >= %s AND {_DATE.format(c='acc_open_date')} < %s
          {"AND (COALESCE(bal, 0) > 0 OR COALESCE(account_cto, 0) > 0)" if funded else ""}"""
    return _monthly(_rows(sql, [datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1)]))


def _loans(year, value):
    approval = (f"COALESCE({_DATE.format(c='offer_letter_generation')}, "
                f"{_DATE.format(c='drawdown_initiation_credit')})")
    sql = f"""
        SELECT seller, approved_on, {'amount' if value == 'amount' else '1'} FROM (
            SELECT application_id, UPPER(TRIM(MAX(seller_code::text))) AS seller,
                   MIN({approval}) AS approved_on,
                   MAX(CASE WHEN TRIM(amount_approved::text) ~ '^-?[0-9]+([.][0-9]+)?$'
                            THEN TRIM(amount_approved::text)::numeric ELSE 0 END) AS amount,
                   BOOL_OR(LOWER(COALESCE(status_to::text, '')) LIKE '%%cancelled%%') AS cancelled
            FROM iapply_loan_approvals_data_dump
            WHERE {_DATE.format(c='creation_date')} >= %s
            GROUP BY application_id) a
        WHERE amount > 0 AND approved_on IS NOT NULL AND NOT cancelled"""
    return _monthly(_rows(sql, [datetime.date(year, 1, 1)]))


def project_sales(year, own, value=False):
    """seller_summary_report.py, Seller Summary - Sales: units in the year's
    pipeline (a sale month this year; or no sale month, booked this year and
    Booked/Sold), in the month of the sale (else the booking), for Property
    Advisors by staff_name - their PF through employee_table (exit = 0)
    joined to hfdi_employee_data on PF; own project = the unit's project is
    their primary_project, cross = any other. Keyed by PF (the Master's
    staff_id). ``value``: unit_value summed instead of units counted."""
    sql = f"""
        WITH staff AS (
            SELECT FLOOR(e.staff_id::numeric)::bigint AS pf, e.name AS staff_name,
                   h.primary_project, h.staff_role
            FROM employee_table e
            LEFT JOIN hfdi_employee_data h
                   ON FLOOR(h.staff_pf_number::numeric) = FLOOR(e.staff_id::numeric)
            WHERE e.exit = 0),
        units AS (
            SELECT s.project_name, s.staff_name, s.unit_status, s.unit_value,
                   {_DATE.format(c='s.sale_month')} AS sold, {_DATE.format(c='s.booking_date')} AS booked
            FROM hfdi_projects_inventory_sales_data s)
        SELECT st.pf::text, COALESCE(u.sold, u.booked),
               {'COALESCE(u.unit_value, 0)' if value else '1'}
        FROM units u JOIN staff st ON st.staff_name = u.staff_name
        WHERE st.staff_role = 'Property Advisor'
          AND (u.project_name = st.primary_project) = %s
          AND (EXTRACT(YEAR FROM u.sold) = %s
               OR (u.sold IS NULL AND EXTRACT(YEAR FROM u.booked) = %s
                   AND u.unit_status IN ('Booked', 'Sold')))"""
    return _monthly(_rows(sql, [own, year, year]))


project_sales.by_pf = True


def _by_pf(fn):
    fn.by_pf = True
    return fn


CANDIDATES = {
    "own_project_sales": [("own project units in the year's pipeline (seller summary report)",
                           _by_pf(lambda y: project_sales(y, True)))],
    "project_cross_sales": [("other projects' units in the year's pipeline (seller summary report)",
                             _by_pf(lambda y: project_sales(y, False)))],
    "sales_value": [
        ("own project units' value in the year's pipeline (seller summary report)",
         _by_pf(lambda y: project_sales(y, True, value=True))),
        ("every project's units' value in the year's pipeline (seller summary report)",
         _by_pf(lambda y: _merge(project_sales(y, True, value=True),
                                 project_sales(y, False, value=True))))],
    "bancassurance_sale": [("paid premiums (group synergies report)", insurance_paid)],
    "bank_accounts": [
        ("funded accounts opened (group synergies report)", lambda y: _accounts(y, True, "n")),
        ("accounts opened (group synergies report)", lambda y: _accounts(y, False, "n"))],
    "accounts_deposits": [
        ("balances of funded accounts opened (group synergies report)",
         lambda y: _accounts(y, True, "bal")),
        ("balances of accounts opened (group synergies report)",
         lambda y: _accounts(y, False, "bal"))],
    "mortgage_sale": [
        ("approved loans (group synergies report)", lambda y: _loans(y, "count")),
        ("approved amount (group synergies report)", lambda y: _loans(y, "amount"))],
}


# ── people ─────────────────────────────────────────────────────────────────

def code_map():
    """{frozenset(name words): SALES CODE} off hfdi_employee_data, only for
    names exactly one active row carries."""
    from .live_scorecard import name_tokens

    seen = {}
    for code, name, active in _rows(
            "SELECT sales_code, staff_name, active FROM hfdi_employee_data", []):
        if str(active).strip().lower() not in ("1", "true", "yes", "y"):
            continue
        key = frozenset(name_tokens(name))
        if key and code:
            seen.setdefault(key, set()).add(str(code).strip().upper())
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def hfdi_card_code(code):
    """The staff_id an HFDI card is stored under, for the sales code
    hfdi_employee_data gives the person (by their name's words, one stored
    HFDI card only) → str, or None when the code is not an HFDI one."""
    from django.db import transaction

    from .live_scorecard import name_tokens
    from .models import BoScorecard

    code = str(code or "").strip().upper()
    if not code or code.isdigit():
        return None
    try:
        with transaction.atomic():
            rows = _rows("SELECT staff_pf_number, staff_name FROM hfdi_employee_data "
                         "WHERE UPPER(TRIM(sales_code::text)) = %s", [code])
            if not rows:
                return None
            cards = {(c, n) for c, n in BoScorecard.objects.filter(book="hfdi")
                     .values_list("sales_code", "staff_name")}
    except Exception:  # noqa: BLE001 - no HFDI table here: not an HFDI code
        return None
    # The PF first: hfdi_employee_data carries it and the card is kept under
    # the same staff_id. The name only where the PF finds no card.
    pf = str(rows[0][0] or "").strip().replace(".0", "")
    if pf and any(c == pf for c, _n in cards):
        return pf
    want = frozenset(name_tokens(rows[0][1]))
    hits = {c for c, n in cards if frozenset(name_tokens(n)) == want}
    return next(iter(hits)) if len(hits) == 1 else None


def _person_rows(grid, holder, first):
    """The template row for this person: staff_id in A, else the name in B."""
    for i, row in enumerate(grid[1:], start=1):
        sid = str(row[0]).replace(".0", "").strip() if row and row[0] is not None else ""
        if sid and sid == holder.sales_code:
            return i
    for i, row in enumerate(grid[1:], start=1):
        if len(row) > 1 and str(row[1] or "").strip().lower() == holder.name.strip().lower():
            return i
    return None


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ── proof and the live card ────────────────────────────────────────────────

def proof(book, actuals, year):
    """{sheet: (label, monthly-source) or None, "_detail": {sheet: why}} -
    the rule each sheet runs on, chosen on the desk's own change."""
    from . import workbook_cards as wc
    from .live_scorecard import name_tokens

    spec = wc.SPECS[wc.HFDI]
    run = wc.ib_run_month(book)
    first = spec.template_first_month
    people = [h for h in wc.holders(book) if h.sheet in book["cards"]]
    codes = code_map()
    chosen, detail = {}, {}
    for sheet, candidates in CANDIDATES.items():
        grid = actuals.get(sheet) or []
        pairs = []
        for h in people:
            r = _person_rows(grid, h, first)
            code = codes.get(frozenset(name_tokens(h.name)))
            if r is None or not run or run < 2:
                continue
            row = grid[r]
            now = row[first + run - 1] if len(row) > first + run - 1 else None
            before = row[first + run - 2] if len(row) > first + run - 2 else None
            if _num(now):
                # (sales code, PF = the Master's staff_id, Oct, Sep)
                pairs.append((code, h.sales_code, float(now),
                              float(before) if _num(before) else 0.0))
        if not pairs:
            chosen[sheet], detail[sheet] = None, "nobody on it with a figure"
            continue
        chosen[sheet] = None
        for label, fn in candidates:
            by_pf = getattr(fn, "by_pf", False)
            try:
                src = fn(year)
            except Exception as exc:  # noqa: BLE001 - the next rule
                detail[sheet] = f"{label}: not read ({type(exc).__name__})"
                continue
            moved = [((pf if by_pf else c), now - before,
                      (src.get(pf if by_pf else c) or [0] * 12)[run - 1]
                      - (src.get(pf if by_pf else c) or [0] * 12)[run - 2], now)
                     for c, pf, now, before in pairs if (pf if by_pf else c)]
            if not moved:
                detail[sheet] = f"{label}: nobody on it has a sales code"
                continue
            bad = [m for m in moved if abs(m[1] - m[2]) > max(0.5, abs(m[3]) * TOLERANCE)]
            # Every person compared, for hfdi_live_check --detail: (code, the
            # desk's change, the source's change, the desk's figure).
            detail.setdefault("_rows", {})[f"{sheet} / {label}"] = moved
            moving = sum(1 for m in moved if m[1] != 0)
            if not bad and moving:
                chosen[sheet] = (label, src, by_pf)
                detail[sheet] = (f"{label}: its change to {datetime.date(year, run, 1):%b} gives "
                                 f"the desk's for all {len(moved)} people ({moving} moved)")
                break
            detail[sheet] = (f"{label}: {len(bad)} of {len(moved)} people's change differs"
                             if bad else f"{label}: nobody's figure moved - nothing to prove on")
    chosen["_detail"] = detail
    return chosen


def live_hfdi_card(book, actuals, holder, as_at):
    """The open month's HFDI card: proven sheets live, every other line the
    desk's latest figure → a card payload, or None."""
    from django.core.cache import cache

    from . import workbook_cards as wc
    from .live_scorecard import name_tokens
    from .models import BoScorecard

    year, month = as_at.year, as_at.month
    run = wc.ib_run_month(book)
    if not run or month <= run:
        return None
    key = f"hfdi_live_proof:v3:{year}:{run}"
    found = cache.get(key)
    if found is None:
        found = proof(book, actuals, year)
        cache.set(key, found, 3600)
    first = wc.SPECS[wc.HFDI].template_first_month
    code = code_map().get(frozenset(name_tokens(holder.name)))
    filled = {}
    for sheet, grid in actuals.items():
        rows = []
        for row in grid:
            row = list(row) + [None] * max(0, first + 12 - len(row))
            row[first + month - 1] = row[first + run - 1]
            rows.append(row)
        filled[sheet] = rows
    live = []
    for sheet, rule in found.items():
        if sheet.startswith("_") or not rule:
            continue
        label, src, by_pf = rule
        key = holder.sales_code if by_pf else code      # the PF is the staff_id
        if not key:
            continue
        grid = filled.get(sheet) or []
        r = _person_rows(grid, holder, first)
        if r is None or not _num(grid[r][first + run - 1]):
            continue
        months = src.get(key) or [0.0] * 12
        grid[r][first + month - 1] = grid[r][first + run - 1] + months[month - 1] - months[run - 1]
        live.append(f"{sheet} ({label})")
    if not live:
        # Nothing on this person's card reads a proven source: the month
        # waits, rather than show October's figures as November's.
        return None
    card = wc.compute(book, filled, holder, month)
    record = BoScorecard(book=wc.HFDI, sales_code=holder.sales_code, staff_pf=holder.pf,
                         staff_name=holder.name, sheet=holder.sheet,
                         branch=str(holder.branch or ""), month=datetime.date(year, month, 1),
                         card=card, total=card.get("total") if wc._num(card.get("total")) else None)
    payload = wc.card_payload(record, asked=as_at)
    when = datetime.date(year, run, 1).strftime("%B")
    note = (f"Live: {', '.join(live)} - the desk's {when} figure plus the change in "
            f"the properties report's own source since, each proven on the desk's "
            f"change to {when}. Every other line is the desk's {when} figure until the "
            f"desk's next template.")
    payload["coverage_note"] = " ".join(x for x in (payload.get("coverage_note"), note) if x)
    payload["live"] = True
    return payload
