"""Institutional Banking cards for the month still open, from the warehouse.

Every IB card line reads the IB actuals template, whose per-person sheets are
SUMIFS over its account sheet (Portfolio): each IB account's RM_CODE, the
desk's LEGACY CAT (typed by the desk - no warehouse source), and month-end
balances DEC_25_BAL .. DEC_26_BAL.

What is live: the two deposit growth lines (Deposit_Growth, Legacy and
Non-Legacy blocks) - the desk's own figure for its closed month plus each
account's balance change since, summed by RM and legacy tag as the
template's SUMIFS do (27 Nov 2026: the warehouse's October level for Mary
Murage's Non-Legacy accounts was 153.7m against the desk's 120.4m, so the
level is the desk's and only the change is the warehouse's). Background:

* this month's balance: daily_balance_movement's month-end column
  (``nov_26_bal``), or ``yester_1_bal`` for the month still running. The
  27 Nov 2026 probe: its oct_26_bal agrees with the template's OCT_26_BAL for
  465 of 476 accounts (and July-September likewise);
* December 2025's balance: the desk's own template (its DEC_25_BAL). The
  warehouse's dec_25_bal agreed for only 397 of 461 accounts, so the baseline
  stays the desk's.

Before any of it is shown, the same method is run for the month the desk
closed (the template's run month) and must give the desk's own Deposit_Growth
figure for every person within PROOF_TOLERANCE - else no line goes live and
the card says so. Every other line keeps the desk's latest figure (the
template's run month), as every book's live card does. Accounts opened after
the template are not on its account list and are not counted.
"""
from __future__ import annotations

import datetime

#: A person's live figure for the closed month may differ from the desk's by
#: this share of the desk's figure (or 1 shilling) and still prove the method.
PROOF_TOLERANCE = 0.005
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
           "oct", "nov", "dec")
GROWTH_SHEET = "Deposit_Growth"


def _accounts(year):
    """[(acc, rm_code, legacy, dec_balance)] off the loaded template's
    Portfolio sheet, or []."""
    from . import workbook_cards as wc

    grid = wc.saved(wc.IB_PORTFOLIO_KIND, year) or []
    if len(grid) < 3:
        return []
    head = [str(v or "").strip().upper() for v in grid[1]]
    need = ("ACC_NUM", "RM_CODE", "LEGACY CAT", f"DEC_{(year - 1) % 100:02d}_BAL")
    if any(n not in head for n in need):
        return []
    i = [head.index(n) for n in need]
    out = []
    for r in grid[2:]:
        r = list(r) + [None] * (len(head) - len(r))
        acc = str(r[i[0]] or "").strip().replace(".0", "")
        if acc:
            dec = r[i[3]] if isinstance(r[i[3]], (int, float)) else 0.0
            out.append((acc, str(r[i[1]] or "").strip().upper(),
                        str(r[i[2]] or "").strip(), float(dec)))
    return out


def _balances(accounts, year, month):
    """{acc: balance} off daily_balance_movement for the month's end (the
    running month: yester_1_bal) → dict, or None when it cannot be read."""
    from django.db import connection, transaction

    today = datetime.date.today()
    col = ("yester_1_bal" if (year, month) == (today.year, today.month)
           else f"{_MONTHS[month - 1]}_{year % 100:02d}_bal")
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 120000")
            cur.execute(f"SELECT trim(acc_num::text), SUM({col}) FROM daily_balance_movement "
                        f"WHERE trim(acc_num::text) = ANY(%s) GROUP BY 1",
                        [sorted({a for a, *_ in accounts})])
            return {a: float(v or 0) for a, v in cur.fetchall()}, col
    except Exception:  # noqa: BLE001 - no live line rather than a wrong one
        return None, col


def growth_by_person(accounts, balances):
    """{(rm_code, legacy): growth} - the template's SUMIFS, live."""
    out = {}
    for acc, rm, legacy, dec in accounts:
        if acc not in balances:
            continue
        key = (rm, legacy)
        out[key] = out.get(key, 0.0) + balances[acc] - dec
    return out


def _block_rows(grid):
    """{(legacy, code): row index} on the template's Deposit_Growth sheet:
    the Legacy block, then the Non-Legacy block (each headed by its tag)."""
    out, tag = {}, None
    for i, row in enumerate(grid):
        cells = [str(v or "").strip() for v in row[:6]]
        cells += [""] * (6 - len(cells))
        if cells[0] in ("Legacy", "Non-Legacy"):
            tag = cells[0]
            continue
        if not tag or cells[1].upper() == "SALES_CODE":
            continue
        if "HEAD" in cells[3].upper():
            continue        # the head's row is the blocks' sum: head_row()
        if "Unmanaged" in cells:
            out[(tag, "UNMANAGED")] = i
        elif cells[1]:
            out[(tag, cells[1].upper())] = i
    return out


def head_row(grid):
    """The head's row on Deposit_Growth (=SUM of both blocks) → index or None."""
    for i, row in enumerate(grid):
        cells = [str(v or "").strip() for v in row[:6]] + [""] * 6
        if "HEAD" in cells[3].upper() and cells[1]:
            return i
    return None


def head_growth(live):
    """=SUM(P11:P16,P3:P8): the Legacy RMs (its Unmanaged row is blank) and
    every Non-Legacy row, Unmanaged included."""
    return (sum(v for (c, t), v in live.items() if t == "Legacy" and c != "UNMANAGED")
            + sum(v for (c, t), v in live.items() if t == "Non-Legacy"))


def _value(grid, row, month):
    col = 6 + month - 1
    v = grid[row][col] if row < len(grid) and col < len(grid[row]) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def movement_by_person(accounts, now, then):
    """{(rm_code, legacy): sum of (now - then)} over the template's accounts -
    the change since the desk's month, which is added to the desk's figure."""
    out = {}
    for acc, rm, legacy, _dec in accounts:
        if acc in now and acc in then:
            out[(rm, legacy)] = out.get((rm, legacy), 0.0) + now[acc] - then[acc]
    return out


def proof(book, actuals, year):
    """The method on the desk's own months → (ok, detail, month).

    The live figure is the desk's closed-month figure plus the warehouse's
    movement since. So what must hold is the movement: for every row, the
    warehouse's change from the month before the desk's to the desk's month
    has to equal the desk's own change, within PROOF_TOLERANCE of the desk's
    figure. (A balance the two sources disagree on in BOTH months - Mary
    Murage's Non-Legacy accounts, 153.7m against the desk's 120.4m for October
    - does not move the change.)"""
    from . import workbook_cards as wc

    month = wc.ib_run_month(book)
    accounts = _accounts(year)
    if not month or month < 2 or not accounts:
        return False, "no IB template account sheet loaded", month
    now, col = _balances(accounts, year, month)
    then, col0 = _balances(accounts, year, month - 1)
    if now is None or then is None:
        return False, f"daily_balance_movement.{col}/{col0} could not be read", month
    moved = movement_by_person(accounts, now, then)
    grid = actuals.get(GROWTH_SHEET) or []
    checks = [((tag, code), r, moved.get((code, tag), 0.0))
              for (tag, code), r in _block_rows(grid).items()]
    h = head_row(grid)
    if h is not None:
        checks.append((("Total", str(grid[h][1]).upper()), h, head_growth(moved)))
    worst, compared = 0.0, 0
    for (tag, code), r, got in checks:
        desk, before = _value(grid, r, month), _value(grid, r, month - 1)
        if desk is None or before is None:
            continue
        compared += 1
        off = abs(got - (desk - before))
        if off > max(1.0, abs(desk) * PROOF_TOLERANCE):
            return False, (f"{tag} {code}: the warehouse's change from "
                           f"{datetime.date(year, month - 1, 1):%b} to "
                           f"{datetime.date(year, month, 1):%b %Y} is {got:,.0f}, the "
                           f"desk's {desk - before:,.0f}"), month
        worst = max(worst, off / abs(desk) if desk else 0.0)
    if not compared:
        return False, "the template's Deposit_Growth sheet has no figures", month
    return True, (f"its change from {datetime.date(year, month - 1, 1):%b} to "
                  f"{datetime.date(year, month, 1):%b %Y} gives the desk's for all "
                  f"{compared} rows (largest difference {worst:.3%} of the figure)"), month


def live_ib_card(book, actuals, holder, as_at):
    """The open month's IB card: deposit growth live (proven), every other
    line the desk's latest figure → a card payload, or None."""
    from django.core.cache import cache

    from . import workbook_cards as wc
    from .models import BoScorecard

    year, month = as_at.year, as_at.month
    key = f"ib_live_proof:{year}:{wc.ib_run_month(book)}"
    found = cache.get(key)
    if found is None:
        found = proof(book, actuals, year)
        cache.set(key, found, 3600)
    ok, detail, run = found
    if not run or month <= run:
        return None
    if not ok:
        # Say why, rather than "not loaded": the method did not give the
        # desk's own closed month, so no line is shown live.
        return {"has_card": False, "reason": "ib_live_not_proven",
                "sales_code": holder.sales_code,
                "detail": (f"Your {as_at:%B %Y} Institutional Banking card fills in when "
                           f"the next IB workbook and template are loaded. Live deposit "
                           f"growth is off: checked on the desk's "
                           f"{datetime.date(year, run, 1):%B} figures, {detail}.")}
    accounts = _accounts(year)
    balances, col = _balances(accounts, year, month)
    at_run, _col = _balances(accounts, year, run)
    if not balances or not at_run:
        return None
    moved = movement_by_person(accounts, balances, at_run)

    # The template with this month's column: the desk's latest figure on
    # every sheet, the live growth on Deposit_Growth.
    filled = {}
    for sheet, grid in actuals.items():
        rows = []
        for row in grid:
            row = list(row) + [None] * max(0, 6 + 12 - len(row))
            last = row[6 + run - 1]
            row[6 + month - 1] = last
            rows.append(row)
        filled[sheet] = rows
    # Deposit growth: the desk's figure for its month plus the warehouse's
    # movement since, row by row (the head's row: the blocks' sum, as its
    # =SUM(P11:P16,P3:P8)).
    grid = filled.get(GROWTH_SHEET) or []
    for (tag, code), r in _block_rows(grid).items():
        desk = _value(grid, r, run)
        if desk is None:
            continue
        grid[r][6 + month - 1] = desk + moved.get((code, tag), 0.0)
    h = head_row(grid)
    if h is not None and _value(grid, h, run) is not None:
        grid[h][6 + month - 1] = _value(grid, h, run) + head_growth(moved)

    card = wc.compute(book, filled, holder, month)
    record = BoScorecard(book=wc.IB, sales_code=holder.sales_code, staff_pf=holder.pf,
                         staff_name=holder.name, sheet=holder.sheet,
                         branch=str(holder.branch or ""),
                         month=datetime.date(year, month, 1), card=card,
                         total=card.get("total") if wc._num(card.get("total")) else None)
    payload = wc.card_payload(record, asked=as_at)
    note = (f"Deposit growth is live: the desk's {datetime.date(year, run, 1):%B} figure "
            f"plus the change in your accounts' balances since (daily_balance_movement."
            f"{col}), by your legacy tags - proven: {detail}. Every other line is the "
            f"desk's {datetime.date(year, run, 1):%B} figure until the desk's next template.")
    payload["coverage_note"] = " ".join(x for x in (payload.get("coverage_note"), note) if x)
    payload["live"] = True
    return payload
