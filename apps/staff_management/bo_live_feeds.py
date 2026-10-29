"""Back-office figures read live from the warehouse - only once proven.

The back-office actuals template has a sheet per measure and a row per
teller. Nothing in the ETL repo builds those sheets: the desk assembles them,
and how it counts a teller's KYC updates or funded accounts is written down
nowhere. What the warehouse does have is every transaction with the user who
posted it (``transaction_diary.trx_usr``), its code and its date.

So nothing here assumes a definition. :func:`probe` takes a month the desk
has already closed, counts each teller's transactions every way that is
plausible - per transaction code, per day worked - and compares each count
with the figure the desk put on the template for the same teller and month.
A definition that reproduces the desk's figures for at least
:data:`PASS_SHARE` of the tellers is stored as that sheet's live feed; one
that does not is reported and left off. The live card reads only stored
feeds, so a figure on a live card is one the warehouse has been shown to
give the same way the desk does.

Run on the host (the warehouse is there):

    manage.py bo_feed_probe --month 2026-09
"""

from __future__ import annotations

import datetime

#: The share of tellers whose figure a definition must reproduce exactly.
PASS_SHARE = 0.9
#: How far apart two figures may be and still be the same number - the
#: template carries some as floats (102.55) written from a division.
TOLERANCE = 0.01
#: The probe reads a month of the whole bank's transactions.
PROBE_TIMEOUT_MS = 600_000
LIVE_TIMEOUT_MS = 20_000
STORE_KIND = "bo_live_feeds"


def _month_bounds(year, month):
    first = datetime.date(year, month, 1)
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return first, nxt


def _rows(sql, params, timeout_ms):
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
            cur.execute(sql, params)
            return cur.fetchall()


def _template_values(actuals, sheet, month):
    """{name lower: (this month, previous month)} off a template sheet."""
    out = {}
    for row in (actuals.get(sheet) or [])[1:]:
        if len(row) < 3 or not isinstance(row[2], str):
            continue
        col = 6 + month - 1

        def num(i):
            v = row[i] if i < len(row) else None
            return float(v) if isinstance(v, (int, float)) and not \
                isinstance(v, bool) else None

        out[row[2].strip().lower()] = (num(col), num(col - 1) if month > 1
                                       else 0.0)
    return out


def _cumulative(actuals, sheet):
    from .bo_actuals import is_cumulative

    series = []
    for row in (actuals.get(sheet) or [])[1:]:
        vals = [row[i] for i in range(6, min(18, len(row)))
                if isinstance(row[i], (int, float))
                and not isinstance(row[i], bool)]
        if vals:
            series.append(vals)
    return is_cumulative(series)


def _identifiers(book):
    """{name lower: sales code} for everybody on the back-office List."""
    from .workbook_cards import holders

    return {h.name.strip().lower(): h.sales_code for h in holders(book)
            if h.sales_code}


def probe(year, month, out=print):
    """Find, per template sheet, the warehouse count that gives the desk's
    figures → {sheet: feed} stored, and a report printed through ``out``."""
    from .workbook_cards import BACK_OFFICE, SPECS, save_file, saved

    spec = SPECS[BACK_OFFICE]
    book, actuals = saved(spec.files[0]), saved(spec.files[1])
    if book is None or actuals is None:
        out("Load the back-office scorecards workbook and actuals template "
            "first - the probe compares against them.")
        return {}
    who = _identifiers(book)
    first, nxt = _month_bounds(year, month)

    out(f"Reading transaction_diary for {first:%B %Y} ...")
    by_code = _rows(
        """SELECT upper(trim(trx_usr)), trx_code, max(trx_name),
                  count(*),
                  count(*) FILTER (WHERE coalesce(reverse_flag, 'Original')
                                   = 'Original')
           FROM transaction_diary
           WHERE trx_date >= %s AND trx_date < %s
           GROUP BY 1, 2""", [first, nxt], PROBE_TIMEOUT_MS)
    days = dict((u, (d, n)) for u, d, n in _rows(
        """SELECT upper(trim(trx_usr)), count(DISTINCT trx_date::date),
                  count(*)
           FROM transaction_diary
           WHERE trx_date >= %s AND trx_date < %s
           GROUP BY 1""", [first, nxt], PROBE_TIMEOUT_MS))

    users = {u for u, *_ in by_code}
    on_diary = {n: c for n, c in who.items() if c in users}
    out(f"{len(on_diary)} of {len(who)} people on the back-office List post "
        f"transactions under their sales code in {first:%B}.")
    if not on_diary:
        sample = sorted(users)[:15]
        out(f"None do - trx_usr is not the sales code. A sample of what it "
            f"holds: {', '.join(sample)}")
        return {}

    counts = {}  # code -> {user: (all, original, name)}
    for user, code, name, n_all, n_orig in by_code:
        counts.setdefault(code, {})[user] = (n_all, n_orig, name)

    found = {}
    for sheet in sorted(actuals):
        desk = _template_values(actuals, sheet, month)
        cumulative = _cumulative(actuals, sheet)

        def target(name):
            now, before = desk[name]
            return (now - (before or 0.0)) if cumulative else now

        # Only figures that are not zero count as proof: on a sheet that is
        # nought for nearly everybody (operation losses), any code nobody
        # uses would otherwise "match" all of them.
        people = [(n, c) for n, c in on_diary.items()
                  if n in desk and desk[n][0] is not None
                  and abs(target(n)) > TOLERANCE]
        if len(people) < 5:
            continue

        best = None
        # 1. transactions per day worked - the productivity shape.
        hits = sum(1 for n, c in people
                   if c in days and days[c][0]
                   and abs(days[c][1] / days[c][0] - target(n)) <= TOLERANCE)
        best = ({"kind": "per_day_worked", "match": hits / len(people)}
                if hits else None)
        # 2. a count of one transaction code (with or without reversals).
        for code, per_user in counts.items():
            for which, label in ((0, "all"), (1, "original")):
                hits = sum(1 for n, c in people
                           if abs(per_user.get(c, (0, 0, ""))[which]
                                  - target(n)) <= TOLERANCE)
                share = hits / len(people)
                if best is None or share > best["match"]:
                    any_name = next(iter(per_user.values()))[2]
                    best = {"kind": "code_count", "codes": [code],
                            "rows": label, "name": any_name, "match": share}
        if best is None:
            continue
        best.update({"sheet": sheet, "cumulative": cumulative,
                     "people": len(people), "month": f"{year}-{month:02d}"})
        verdict = "LIVE" if best["match"] >= PASS_SHARE else "not good enough"
        what = ("transactions per day worked" if best["kind"] ==
                "per_day_worked" else
                f"count of code {best['codes'][0]} ({best.get('name')}, "
                f"{best['rows']} rows)")
        out(f"  {sheet:28} {best['match']:6.1%} of {best['people']:3} "
            f"tellers match  - {what}  -> {verdict}")
        if best["match"] >= PASS_SHARE:
            found[sheet] = best

    stored = saved(STORE_KIND) or {}
    stored.update(found)
    save_file(STORE_KIND, stored, f"probe {year}-{month:02d}", "probe")
    out(f"{len(found)} sheet(s) now read live: "
        f"{', '.join(sorted(found)) or 'none'}. Sheets not listed have no "
        f"warehouse count that gives the desk's figures; they stay on the "
        f"template.")
    return found


def live_value(feed, sales_code, as_at):
    """The live figure for one person on one proven feed, or None."""
    from django.core.cache import cache

    code = (sales_code or "").strip().upper()
    key = f"bo_live:{feed['sheet']}:{code}:{as_at.isoformat()}"
    hit = cache.get(key)
    if hit is not None:
        return hit if hit != "none" else None
    first, nxt = _month_bounds(as_at.year, as_at.month)
    end = min(nxt, as_at + datetime.timedelta(days=1))
    try:
        if feed["kind"] == "per_day_worked":
            row = _rows("""SELECT count(*), count(DISTINCT trx_date::date)
                           FROM transaction_diary
                           WHERE upper(trim(trx_usr)) = %s
                             AND trx_date >= %s AND trx_date < %s""",
                        [code, first, end], LIVE_TIMEOUT_MS)[0]
            value = (row[0] / row[1]) if row[1] else None
        else:
            start = (datetime.date(as_at.year, 1, 1) if feed["cumulative"]
                     else first)
            original = feed.get("rows") == "original"
            row = _rows(f"""SELECT count(*) FROM transaction_diary
                            WHERE upper(trim(trx_usr)) = %s
                              AND trx_code = ANY(%s)
                              AND trx_date >= %s AND trx_date < %s
                              {"AND coalesce(reverse_flag, 'Original')"
                               " = 'Original'" if original else ""}""",
                        [code, feed["codes"], start, end], LIVE_TIMEOUT_MS)[0]
            value = float(row[0])
    except Exception:  # noqa: BLE001 - a slow warehouse is a waiting line
        return None
    cache.set(key, value if value is not None else "none", 6 * 3600)
    return value


def proven():
    from .workbook_cards import saved

    return saved(STORE_KIND) or {}
