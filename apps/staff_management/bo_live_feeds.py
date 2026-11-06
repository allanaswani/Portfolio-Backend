"""Back-office figures read live from the warehouse - only once proven.

The back-office actuals template has a sheet per measure and a row per
person. Nothing in the ETL repo builds those sheets: the desk assembles them.
What the warehouse does have is every transaction with the user who posted it
(``transaction_diary.trx_usr``, which is the sales code), its code and its date.

Three things can prove a sheet, and each is compared with the desk's figures:

* a count of one transaction code, or a ratio such as transactions per day
  worked or reversals per transaction, for everybody or for one role, since
  the same sheet can mean different things on a teller's and a BOM's card;
* the branch figures the branch managers' cards already read, because on twelve
  sheets everybody in a branch carries one figure (PL_Charge, TAT and others);
* the live engine's own reading of the line, stored separately
  (:data:`ENGINE_STORE_KIND`, by ``sales_live_feeds.probe``). It leaves loaded
  figures out, so it cannot pass by matching the desk's own upload.

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
ENGINE_STORE_KIND = "bo_engine_feeds"
#: How close a ratio must be: a hundredth, or half a percent of a larger figure.
RELATIVE = 0.005
MIN_PEOPLE = 5
MIN_DISTINCT = 3

#: Each counted per person per month. Column names are the ones the ETLs use.
_ORIGINAL = "coalesce(reverse_flag, 'Original') = 'Original'"
_CHARGES = ("'EXCISE DUTY', 'COMMISSION ON TRANSACTION AMOUNT', "
            "'CHARGES ON TRANSACTION AMOUNT'")
MEASURES = {
    "rows": "count(*)",
    "original": f"count(*) FILTER (WHERE {_ORIGINAL})",
    "posted": ("count(*) FILTER (WHERE lower(reversed_trx_flag) = 'posted' "
               f"AND {_ORIGINAL})"),
    "refs": "count(DISTINCT transaction_ref)",
    "original_refs": f"count(DISTINCT transaction_ref) FILTER (WHERE {_ORIGINAL})",
    "no_charges": (f"count(*) FILTER (WHERE {_ORIGINAL} AND coalesce(justific_name, '') "
                   f"NOT IN ({_CHARGES}))"),
    "reversed": f"count(*) FILTER (WHERE NOT ({_ORIGINAL}))",
    "days": "count(DISTINCT trx_date::date)",
}
#: (numerator, denominator, what it is called). "weekdays" is the calendar's.
RATIOS = [(n, d, f"{n} per {'day worked' if d == 'days' else 'weekday'}")
          for n in ("rows", "original", "posted", "refs", "original_refs", "no_charges")
          for d in ("days", "weekdays")] + [
    ("reversed", "rows", "reversed share of all transactions"),
    ("reversed", "original", "reversals per original transaction"),
]


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


def _weekdays(first, end):
    """Monday to Friday from ``first`` up to, not including, ``end``."""
    return sum(1 for n in range((end - first).days)
               if (first + datetime.timedelta(days=n)).weekday() < 5)


def _ratio(values, num, den, weekdays):
    """One person's ratio from their measures → a number or None."""
    bottom = weekdays if den == "weekdays" else values.get(den)
    return values.get(num, 0) / bottom if bottom else None


def _close(desk, got):
    """The same figure? Half a percent of it, or a hundredth where that is more -
    except on a small rate, where a flat hundredth would pass nearly anything."""
    if got is None:
        return False
    size = abs(desk)
    return abs(desk - got) <= max(RELATIVE * size, min(TOLERANCE, 0.02 * size))


def _varied(values):
    """Enough different figures to prove anything: a count that happens to be 1
    for everybody also "matches" a sheet where everybody has 1."""
    return len({round(v, 4) for v in values}) >= MIN_DISTINCT


def _measures(first, end, timeout_ms, user=None):
    """{user: {measure: value}} for a span of the diary."""
    names = list(MEASURES)
    select = ", ".join(f"{MEASURES[n]} AS {n}" for n in names)
    who = "AND upper(trim(trx_usr)) = %s" if user else ""
    rows = _rows(f"""SELECT upper(trim(trx_usr)), {select} FROM transaction_diary
                     WHERE trx_date >= %s AND trx_date < %s {who} GROUP BY 1""",
                 [first, end] + ([user] if user else []), timeout_ms)
    return {r[0]: dict(zip(names, r[1:])) for r in rows}


def best_ratio(people, measures, weekdays):
    """The ratio matching most of ``people`` [(code, desk)] → (share, ratio) or None."""
    best = None
    for num, den, label in RATIOS:
        hits = sum(1 for code, desk in people if code in measures
                   and _close(desk, _ratio(measures[code], num, den, weekdays)))
        share = hits / len(people) if people else 0
        if hits and (best is None or share > best[0]):
            best = (share, {"kind": "ratio", "num": num, "den": den, "label": label})
    return best


#: Per person per month off iapply_accounts_tat, which is what accounts_tat.py
#: reads for its "ActionUser" and "Returns by user" sheets. The person who actioned
#: a step is ActionUser, not SellerCode. Step time and its zeroing on a closing
#: status are the ETL's calculate_tat; the segments are its CASE.
IAPPLY_TERMINAL = ("stored", "cancel", "reject", "decline", "archive", "complete",
                   "stored archived - cancelled", "stored archived - approved",
                   "stored archived - declined", "stored archived cancelled",
                   "stored archived approved")
IAPPLY_FIELDS = ("apps", "actions", "days", "returned", "pb_time", "pb_steps",
                 "bb_time", "bb_steps")
IAPPLY_MEASURES = {
    "tat_pb": "average days per step, personal banking",
    "tat_bb": "average days per step, business banking",
    "apps_per_day": "applications actioned per day worked",
    "actions_per_day": "steps actioned per day worked",
    "apps_per_weekday": "applications actioned per weekday",
    "returned_of_apps": "applications returned, share of those actioned",
    "returned_of_actions": "applications returned, share of steps actioned",
}
IAPPLY_SPANS = {"month": "the month", "running": "since the sheet's first month",
                "ytd": "the year to date"}
#: The one read has to scan the trail; its result is kept for everybody.
IAPPLY_LIVE_TIMEOUT_MS = 60_000


def _iapply_rows(year, end, timeout_ms):
    """[(user, month, *IAPPLY_FIELDS)] for the year up to ``end``."""
    good = "'^[0-9]{4}-[0-9]{2}-[0-9]{2}'"
    closing = ", ".join(f"'{s}'" for s in IAPPLY_TERMINAL)
    counted = f"s.tat > 0 AND NOT (s.status IN ({closing}) OR split_part(s.who, ' ', 1) IN ({closing}))"
    return _rows(f"""
        WITH trail AS (
            SELECT upper(trim(i."ActionUser"::text)) AS usr, i."ApplicationId" AS app,
                   lower(trim(coalesce(i."ActionUserName"::text, ''))) AS who,
                   lower(trim(coalesce(i."StatusTo"::text, ''))) AS status,
                   NULLIF(regexp_replace(i."Customerid"::text, '\\D', '', 'g'), '')::bigint AS cust,
                   CASE WHEN i."ActionDate"::text ~ {good}
                        THEN i."ActionDate"::text::timestamp END AS acted,
                   CASE WHEN i."CreationDate"::text ~ {good}
                        THEN i."CreationDate"::text::timestamp END AS created
            FROM iapply_accounts_tat i
        ), steps AS (
            SELECT t.*, EXTRACT(EPOCH FROM t.acted - COALESCE(
                       LAG(t.acted) OVER (PARTITION BY t.app ORDER BY t.acted), t.created)
                   ) / 86400.0 AS tat
            FROM trail t WHERE t.acted IS NOT NULL
        ), named AS (
            SELECT s.*, CASE
                     WHEN c.segment IN ('MEDIUM ENTERPRISES', 'SMALL ENTERPRISES') THEN 'bb'
                     WHEN c.segment IN ('MASS', 'STANDARD', 'PRIVATE', 'VIRTUAL') THEN 'pb'
                     WHEN c.segment IN ('ULTIMATE', 'LARGE ENTERPRISES', 'PROJECT FINANCE',
                                        'INTERNAL ACCOUNTS', 'INSTITUTIONAL BANKING',
                                        'DIASPORA PERSONAL BANKING', 'DIASPORA ULTIMATE BANKING',
                                        'DIASPORA BUSINESS BANKING', 'DIASPORA',
                                        'NON RESIDENT KENYANS') THEN 'other'
                     ELSE 'pb' END AS seg
            FROM steps s LEFT JOIN customers c ON c.cust_id = s.cust
        )
        SELECT s.usr, EXTRACT(MONTH FROM s.acted)::int,
               count(DISTINCT s.app), count(*), count(DISTINCT s.acted::date),
               count(DISTINCT s.app) FILTER (WHERE s.who LIKE '%%return%%'),
               coalesce(sum(s.tat) FILTER (WHERE s.seg = 'pb' AND {counted}), 0),
               count(*) FILTER (WHERE s.seg = 'pb' AND {counted}),
               coalesce(sum(s.tat) FILTER (WHERE s.seg = 'bb' AND {counted}), 0),
               count(*) FILTER (WHERE s.seg = 'bb' AND {counted})
        FROM named s
        WHERE s.acted >= %s AND s.acted < %s AND coalesce(s.usr, '') <> ''
        GROUP BY 1, 2""", [datetime.date(year, 1, 1), end], timeout_ms)


def _iapply_by_user(rows):
    """→ {user: {month: {field: value}}}"""
    out = {}
    for user, month, *values in rows:
        out.setdefault(user, {})[int(month)] = {
            k: float(v or 0) for k, v in zip(IAPPLY_FIELDS, values)}
    return out


def iapply_value(months, measure, span, month, start_month, year, end=None):
    """One person's figure → a number, or None where nothing was actioned."""
    first = {"month": month, "running": start_month or month, "ytd": 1}[span]
    t = dict.fromkeys(IAPPLY_FIELDS, 0.0)
    for m in range(first, month + 1):
        for k, v in months.get(m, {}).items():
            t[k] += v
    if measure == "apps_per_weekday":
        stop = end or (datetime.date(year, month, 28)
                       + datetime.timedelta(days=4)).replace(day=1)
        days = _weekdays(datetime.date(year, first, 1), stop)
        return t["apps"] / days if days else None
    top, bottom = {
        "tat_pb": ("pb_time", "pb_steps"), "tat_bb": ("bb_time", "bb_steps"),
        "apps_per_day": ("apps", "days"), "actions_per_day": ("actions", "days"),
        "returned_of_apps": ("returned", "apps"),
        "returned_of_actions": ("returned", "actions"),
    }[measure]
    return t[top] / t[bottom] if t[bottom] else None


def _iapply_key(holder_code, name, identity):
    if identity == "code":
        return str(holder_code or "").strip().upper()
    return ".".join(str(name or "").strip().upper().split()[:2])


def _first_filled(actuals, sheet):
    """The sheet's first month with any figure."""
    for month in range(1, 13):
        for row in (actuals.get(sheet) or [])[1:]:
            v = row[5 + month] if len(row) > 5 + month else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
                return month
    return None


def prove_iapply(desk, prior, people, by_user, year, month, start_month):
    """The definition matching most of ``people`` [(name, code)] → (share, feed, n) or None.

    ``desk`` and ``prior`` are {name: figure} for the month and the one before it.
    Where the person has a prior-month figure the definition must match that too.
    """
    best = None
    group = [(n, c, desk[n]) for n, c in people if desk.get(n)]
    if len(group) < MIN_PEOPLE or not _varied(v for _, _, v in group):
        return None
    for identity in ("code", "username"):
        for measure in IAPPLY_MEASURES:
            for span in IAPPLY_SPANS:
                hits = 0
                for name, code, value in group:
                    months = by_user.get(_iapply_key(code, name, identity))
                    if not months or not _close(value, iapply_value(
                            months, measure, span, month, start_month, year)):
                        continue
                    before = prior.get(name)
                    if before and month > 1 and not _close(before, iapply_value(
                            months, measure, span, month - 1, start_month, year)):
                        continue
                    hits += 1
                share = hits / len(group)
                if hits and (best is None or share > best[0]):
                    best = (share, {"kind": "iapply", "measure": measure, "span": span,
                                    "identity": identity, "start_month": start_month},
                            len(group))
    return best


def _branch_candidates():
    """(label, feed) for every branch reading the branch managers' cards use."""
    from .bb_live_feeds import DEFINITIONS

    for key, definitions in DEFINITIONS.items():
        for label, kind, options in definitions:
            yield key.split("#")[0], label, dict(options, kind=kind, label=label)


def _prove_branch_sheets(actuals, holders_, year, month, out):
    """Sheets where everybody in a branch has one figure, against the branch
    managers' readers → {sheet: feed}."""
    from . import bb_live_feeds

    found = {}
    wanted = {}
    for sheet, label, feed in _branch_candidates():
        wanted.setdefault(sheet, []).append((label, feed))
    for sheet, options in sorted(wanted.items()):
        desk = _template_values(actuals, sheet, month)
        targets = {}
        for h in holders_:
            value = desk.get(str(h.name).strip().lower())
            if value and value[0]:
                targets.setdefault(str(h.branch), value[0])
        if len(targets) < MIN_PEOPLE or not _varied(targets.values()):
            continue
        best = None
        for label, feed in options:
            feed = dict(feed, sheet=sheet)
            try:
                totals = bb_live_feeds._totals(feed, year, month, PROBE_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001 - the reason is the answer
                out(f"  {sheet:28} {label}: could not be read - {exc}")
                continue
            hits = sum(1 for branch, value in targets.items()
                       if _close(value, bb_live_feeds._branch_total(totals, branch, feed)))
            share = hits / len(targets)
            if best is None or share > best[0]:
                best = (share, feed)
        if best is None:
            continue
        verdict = "LIVE" if best[0] >= PASS_SHARE else "not good enough"
        out(f"  {sheet:28} {best[0]:6.1%} of {len(targets):3} branches match - "
            f"{best[1]['label']} -> {verdict}")
        if best[0] >= PASS_SHARE:
            found[sheet] = {"kind": "bb_branch", "feed": best[1], "sheet": sheet,
                            "match": best[0], "people": len(targets),
                            "month": f"{year}-{month:02d}", "cumulative": False}
    return found


def describe(feed):
    """A proven feed in words, for the screen."""
    roles = f" ({', '.join(feed['roles'])})" if feed.get("roles") else ""
    if feed.get("kind") == "ratio":
        return f"{feed.get('label')}{roles}"
    if feed.get("kind") == "iapply":
        return (f"{IAPPLY_MEASURES[feed['measure']]}, {IAPPLY_SPANS[feed['span']]}, "
                f"from the account-opening trail{roles}")
    if feed.get("kind") == "bb_branch":
        return f"branch figure: {(feed.get('feed') or {}).get('label')}"
    if feed.get("kind") == "per_day_worked":
        return "transactions per day worked"
    return f"count of {feed.get('name')}, {feed.get('rows')} rows{roles}"


def engine_proven():
    """Lines the engine has been compared on. Results from before the engine really
    read the warehouse for these people compared the desk with itself, so a line
    without ``warehouse_read`` is not proof of anything."""
    from .workbook_cards import saved

    return {key: dict(value, live=bool(value.get("live") and value.get("warehouse_read")))
            for key, value in (saved(ENGINE_STORE_KIND) or {}).items()}


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
    if not users:
        out(f"transaction_diary has no rows for {first:%B %Y}, so nothing can be compared. "
            f"Check that the ETL has loaded that month.")
        return {}
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

    from .workbook_cards import holders

    everybody = [h for h in holders(book) if h.sales_code]
    role_of = {str(h.name).strip().lower(): str(h.role or "") for h in everybody}
    weekdays = _weekdays(first, nxt)
    try:
        measures = _measures(first, nxt, PROBE_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 - counts below still run
        out(f"The ratios could not be read: {exc}")
        measures = {}
    out("Reading the account-opening trail (iapply_accounts_tat) ...")
    try:
        by_user = _iapply_by_user(_iapply_rows(year, nxt, PROBE_TIMEOUT_MS))
    except Exception as exc:  # noqa: BLE001 - the other tests still run
        out(f"The account-opening trail could not be read: {exc}")
        by_user = {}
    if by_user:
        known = sum(1 for n, c in who.items() if _iapply_key(c, n, "code") in by_user
                    or _iapply_key(c, n, "username") in by_user)
        out(f"{known} of {len(who)} people on the back-office List action applications "
            f"under their code or sign-in name. A sample of what ActionUser holds: "
            f"{', '.join(sorted(by_user)[:8])}")

    found = {}
    for sheet in sorted(actuals):
        desk = _template_values(actuals, sheet, month)
        cumulative = _cumulative(actuals, sheet)

        # Ratios, for everybody and then one role at a time. A ratio is the
        # month's own figure, so it is compared with the sheet as it stands.
        def desk_people(role=None):
            return [(c, desk[n][0]) for n, c in on_diary.items()
                    if n in desk and desk[n][0]
                    and (role is None or role_of.get(n) == role)]

        ratio_best = None
        for role in [None] + sorted({role_of.get(n) for n in on_diary if role_of.get(n)}):
            group = desk_people(role)
            if len(group) < MIN_PEOPLE or not _varied(v for _, v in group):
                continue
            hit = best_ratio(group, measures, weekdays)
            if hit and (ratio_best is None or hit[0] > ratio_best[0]):
                ratio_best = (hit[0], dict(hit[1], roles=[role] if role else None),
                              len(group))
        if ratio_best and ratio_best[0] >= PASS_SHARE:
            feed = dict(ratio_best[1], sheet=sheet, match=ratio_best[0],
                        people=ratio_best[2], cumulative=False,
                        month=f"{year}-{month:02d}")
            out(f"  {sheet:28} {feed['match']:6.1%} of {feed['people']:3} people match"
                f" - {describe(feed)} -> LIVE")
            found[sheet] = feed
            continue

        # The account-opening trail, for everybody and then one role at a time.
        if by_user:
            before = _template_values(actuals, sheet, month - 1) if month > 1 else {}
            flat = {n: v[0] for n, v in desk.items() if v[0]}
            prior = {n: v[0] for n, v in before.items() if v[0]}
            everyone = list(who.items())
            trail_best = None
            for role in [None] + sorted({r for r in role_of.values() if r}):
                group = [(n, c) for n, c in everyone
                         if role is None or role_of.get(n) == role]
                hit = prove_iapply(flat, prior, group, by_user, year, month,
                                   _first_filled(actuals, sheet))
                if hit and (trail_best is None or hit[0] > trail_best[0]):
                    trail_best = (hit[0], dict(hit[1], roles=[role] if role else None), hit[2])
            if trail_best:
                feed = dict(trail_best[1], sheet=sheet, match=trail_best[0],
                            people=trail_best[2], cumulative=False,
                            month=f"{year}-{month:02d}")
                passed = feed["match"] >= PASS_SHARE
                out(f"  {sheet:28} {feed['match']:6.1%} of {feed['people']:3} people match - "
                    f"{describe(feed)} -> {'LIVE' if passed else 'not good enough'}")
                if passed:
                    found[sheet] = feed
                    continue

        def target(name):
            now, before = desk[name]
            return (now - (before or 0.0)) if cumulative else now

        # Only figures that are not zero count as proof: on a sheet that is
        # nought for nearly everybody (operation losses), any code nobody
        # uses would otherwise "match" all of them.
        people = [(n, c) for n, c in on_diary.items()
                  if n in desk and desk[n][0] is not None
                  and abs(target(n)) > TOLERANCE]
        if len(people) < MIN_PEOPLE or not _varied(target(n) for n, _ in people):
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
        if not best["match"]:
            out(f"  {sheet:28}   0.0% of {len(people):3} tellers match  - no "
                f"warehouse count gives any teller's figure")
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

    found.update({sheet: feed for sheet, feed in _prove_branch_sheets(
        actuals, everybody, year, month, out).items() if sheet not in found})

    # This run replaces the last: a sheet that no longer matches stops being live.
    dropped = sorted(set(saved(STORE_KIND) or {}) - set(found))
    save_file(STORE_KIND, found, f"probe {year}-{month:02d}", "probe")
    if dropped:
        out(f"No longer matching, back to the desk's figure: {', '.join(dropped)}.")
    out(f"{len(found)} sheet(s) now read live: "
        f"{', '.join(sorted(found)) or 'none'}. Sheets not listed have no "
        f"warehouse count that gives the desk's figures; they stay on the "
        f"template.")
    return found


def explain(year, month, who, out=print):
    """One teller side by side: the desk's figure on every sheet, and what
    transaction_diary holds for them that month - to read the definition off
    when no count matches on its own."""
    from .workbook_cards import BACK_OFFICE, SPECS, saved

    spec = SPECS[BACK_OFFICE]
    book, actuals = saved(spec.files[0]), saved(spec.files[1])
    if book is None or actuals is None:
        out("Load the back-office scorecards workbook and actuals template "
            "first.")
        return
    wanted = who.strip().lower()
    people = _identifiers(book)
    match = [(n, c) for n, c in people.items()
             if wanted in n or wanted == c.lower()]
    if len(match) != 1:
        out(f"{len(match)} people on the List match {who!r}: "
            f"{', '.join(sorted(n for n, _ in match)[:10]) or 'none'}")
        return
    name, code = match[0]
    first, nxt = _month_bounds(year, month)
    out(f"{name.title()} ({code}), {first:%B %Y}")
    out("On the template:")
    for sheet in sorted(actuals):
        desk = _template_values(actuals, sheet, month)
        if name not in desk or desk[name][0] is None:
            continue
        now, before = desk[name]
        if _cumulative(actuals, sheet):
            out(f"  {sheet:28} {now:g} (cumulative; this month "
                f"{now - (before or 0.0):g})")
        else:
            out(f"  {sheet:28} {now:g}")

    rows = _rows("""SELECT count(*), count(DISTINCT trx_date::date),
                           string_agg(DISTINCT coalesce(reverse_flag, '(blank)'),
                                      ', ')
                    FROM transaction_diary
                    WHERE upper(trim(trx_usr)) = %s
                      AND trx_date >= %s AND trx_date < %s""",
                 [code, first, nxt], PROBE_TIMEOUT_MS)
    total, worked, flags = rows[0]
    out(f"In transaction_diary: {total} transactions on {worked} days "
        f"(reverse_flag values: {flags or 'none'})")
    for trx_code, name_, n_all, n_orig in _rows(
            """SELECT trx_code, max(trx_name), count(*),
                      count(*) FILTER (WHERE coalesce(reverse_flag, 'Original')
                                       = 'Original')
               FROM transaction_diary
               WHERE upper(trim(trx_usr)) = %s
                 AND trx_date >= %s AND trx_date < %s
               GROUP BY 1 ORDER BY 3 DESC""",
            [code, first, nxt], PROBE_TIMEOUT_MS):
        out(f"  {trx_code!s:>6}  {str(name_)[:40]:40} {n_all:6} "
            f"({n_orig} original)")


def _iapply_live(feed, sales_code, name, as_at):
    from django.core.cache import cache

    key = f"bo_iapply:{as_at.isoformat()}"
    by_user = cache.get(key)
    end = as_at + datetime.timedelta(days=1)
    if by_user is None:
        try:
            by_user = _iapply_by_user(_iapply_rows(as_at.year, end, IAPPLY_LIVE_TIMEOUT_MS))
        except Exception:  # noqa: BLE001 - a slow read leaves the desk's figure
            return None
        cache.set(key, by_user, 6 * 3600)
    months = by_user.get(_iapply_key(sales_code, name, feed["identity"]))
    if not months:
        return None
    return iapply_value(months, feed["measure"], feed["span"], as_at.month,
                        feed.get("start_month"), as_at.year, end)


def live_value(feed, sales_code, as_at, branch=None, name=None):
    """The live figure for one person on one proven feed, or None."""
    from django.core.cache import cache

    if feed.get("kind") == "bb_branch":
        from . import bb_live_feeds

        return bb_live_feeds.live_value(feed["feed"], branch, as_at)
    if feed.get("kind") == "iapply":
        return _iapply_live(feed, sales_code, name, as_at)
    code = (sales_code or "").strip().upper()
    key = f"bo_live:{feed['sheet']}:{code}:{as_at.isoformat()}"
    hit = cache.get(key)
    if hit is not None:
        return hit if hit != "none" else None
    first, nxt = _month_bounds(as_at.year, as_at.month)
    end = min(nxt, as_at + datetime.timedelta(days=1))
    try:
        if feed["kind"] == "ratio":
            values = _measures(first, end, LIVE_TIMEOUT_MS, code).get(code)
            value = (_ratio(values, feed["num"], feed["den"], _weekdays(first, end))
                     if values else None)
        elif feed["kind"] == "per_day_worked":
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
