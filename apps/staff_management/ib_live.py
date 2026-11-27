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


def new_accounts_movement(accounts, year, run, month):
    """{(rm_code, "Non-Legacy"): change} for accounts under an IB RM's code
    that are not on the desk's account list - opened after its template, so
    new portfolio by definition. Each counts its balance now less its balance
    at the desk's month (0 for one opened since): Mary Murage's 9783958952,
    0 at October and 35m on 27 Nov 2026, was missing from her card."""
    from django.db import connection, transaction

    known = {a for a, *_ in accounts}
    codes = sorted({rm for _a, rm, *_ in accounts if rm and rm != "UNMANAGED"})
    if not codes:
        return {}
    today = datetime.date.today()
    now_col = ("yester_1_bal" if (year, month) == (today.year, today.month)
               else f"{_MONTHS[month - 1]}_{year % 100:02d}_bal")
    run_col = f"{_MONTHS[run - 1]}_{year % 100:02d}_bal"
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 120000")
            cur.execute(f"SELECT trim(acc_num::text), UPPER(TRIM(rm_code::text)), "
                        f"COALESCE({run_col}, 0), COALESCE({now_col}, 0) "
                        f"FROM daily_balance_movement "
                        f"WHERE UPPER(TRIM(rm_code::text)) = ANY(%s)", [codes])
            rows = cur.fetchall()
    except Exception:  # noqa: BLE001 - the listed accounts still count
        return {}
    out = {}
    for acc, rm, then, now in rows:
        if acc in known:
            continue
        key = (rm, "Non-Legacy")
        out[key] = out.get(key, 0.0) + float(now) - float(then)
    return out


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
    # v2: the proof checks the change since the desk's month (27 Nov 2026).
    # The cache is the database's, so it outlives a deploy: a new method
    # needs a new key, or the old method's verdict is served for an hour.
    key = f"ib_live_proof:v2:{year}:{wc.ib_run_month(book)}"
    found = cache.get(key)
    if found is None:
        found = proof(book, actuals, year)
        cache.set(key, found, 3600)
    ok, detail, run = found
    if not run or month <= run:
        return None
    # The card is always shown: deposit growth live where the method is
    # proven, every line otherwise the desk's latest figure, each labelled.
    moved, col = {}, ""
    if ok:
        accounts = _accounts(year)
        balances, col = _balances(accounts, year, month)
        at_run, _col = _balances(accounts, year, run)
        if balances and at_run:
            moved = movement_by_person(accounts, balances, at_run)
            # Accounts opened since the desk's template: new portfolio.
            for k, v in new_accounts_movement(accounts, year, run, month).items():
                moved[k] = moved.get(k, 0.0) + v
        else:
            ok, detail = False, f"daily_balance_movement.{col} could not be read"

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
    if ok:
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
    when = datetime.date(year, run, 1).strftime("%B")
    if ok:
        note = (f"Deposit growth is live: the desk's {when} figure plus the change in your "
                f"accounts' balances since (daily_balance_movement.{col}), by your legacy "
                f"tags - proven: {detail}. Every other line is the desk's {when} figure "
                f"until the desk's next template.")
    else:
        note = (f"Every line is the desk's {when} figure until the desk's next template. "
                f"Live deposit growth is off: checked on the desk's {when} figures, {detail}.")
    payload["coverage_note"] = " ".join(x for x in (payload.get("coverage_note"), note) if x)
    payload["live"] = True
    relabel(payload, [GROWTH_SHEET] if ok else [], when)
    fill_zero_weight(payload, holder.sales_code, as_at)
    return payload


def fill_zero_weight(payload, sales_code, as_at, today=None):
    """The IB card's 0-weight Trade Sales and FX Sales lines, kept as the
    desk's card has them, with the figure the warehouse holds:

    * Trade Sales - the RM's trade finance volume, year to date, off the
      reader the RM cards use (live_actuals trade_volume, by RM code);
    * FX Sales - FX deals are recorded by treasury dealer code
      (fx_trx_current_year.py: DEALER_SPECIAL_RAT / FX_FT_RECORDING
      DEALER_CODE), not by RM, so there is no per-RM figure to show.

    Weight 0 on the desk's card: shown, not scored."""
    today = today or datetime.date.today()
    for group in payload.get("perspectives") or []:
        for ln in group.get("lines") or []:
            if ln.get("weight"):
                continue
            name = str(ln.get("kpi_name") or "").strip().lower()
            if name.startswith("trade"):
                try:
                    from .live_scorecard import live_actuals

                    got = live_actuals(sales_code, wanted={"trade_volume"},
                                       as_at=as_at).get("trade_volume") or {}
                except Exception:  # noqa: BLE001 - the line stays unfilled
                    got = {}
                if got.get("value") is not None:
                    ln["ytd_actual"] = float(got["value"])
                    ln["as_at"] = (f"trade finance volume, year to date, as at "
                                   f"{today.day} {today:%b %Y} - weight 0 on the desk's "
                                   f"card: shown, not scored")
                else:
                    ln["as_at"] = (f"no trade finance volume under this RM code "
                                   f"({got.get('problem') or 'none read'}) - weight 0 on "
                                   f"the desk's card: shown, not scored")
            elif name.startswith("fx"):
                ln["as_at"] = ("FX deals are recorded by treasury dealer code, not by "
                               "RM, so there is no per-RM FX figure - weight 0 on the "
                               "desk's card: shown, not scored")
            else:
                ln["as_at"] = "weight 0 on the desk's card: shown, not scored"


def relabel(payload, live_sheets, desk_month, today=None):
    """Each line says where its figure is from: "live, as at <today>" for a
    sheet read live, "the desk's <month> figure" for one carried - not the
    month's end, which has not come yet. 0-weight lines (IB Trade Sales, FX
    Sales) are kept, as the desk's card has them - see fill_zero_weight."""
    today = today or datetime.date.today()
    live = {s.lower() for s in live_sheets}
    for group in payload.get("perspectives") or []:
        for ln in group.get("lines") or []:
            if not ln.get("weight"):
                continue        # 0-weight lines are labelled by fill_zero_weight
            if str(ln.get("as_at", "")).startswith("typed"):
                continue
            elif ln.get("kpi_code") in live:
                ln["as_at"] = f"live, as at {today.day} {today:%b %Y}"
                ln["as_at_date"] = today.isoformat()
            else:
                ln["as_at"] = f"the desk's {desk_month} figure"
