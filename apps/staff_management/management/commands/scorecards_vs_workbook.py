"""Every person's card on this platform against the score the desk's workbook
signed for them - the whole roster, not one pasted card at a time.

    manage.py scorecards_vs_workbook \\
        --sales "Portfolio Management - Q3 2026_scorecards.xlsb" \\
        --bo "2026_BO_Non_Sales_Scorecards - Q2 with_updated_targets.xlsb"
    manage.py scorecards_vs_workbook --sales ... --month 2026-07
    manage.py scorecards_vs_workbook --bo ... --all-months --csv diff.csv

Both workbooks keep a ``Monthly_Summ`` sheet: a row per person, the score the
card produced for every month. That is the number that went out. This reads
it, builds this platform's card for the same person and the same month - the
same ``build_card`` the page uses - and lists every difference, worst first.

The month defaults to each workbook's own review month (``Constants``
Month_count: 8 = August on the sales workbook, 6 = June on the back-office
one). Months after it are not scores: the back-office sheet keeps a copy of
the current score, a changed/unchanged flag and an ``old_jun`` column beside
them. Where ``old_jun`` differs from June, both are shown - June was
recomputed after it went out, and which of the two was signed is a question
for the desk.

Read-only. Nothing is written and no card is signed. Run it on the host:
the cards read the warehouse, which only the host can reach.
"""

import csv
import datetime

from django.core.management.base import BaseCommand, CommandError


def _month_end(first):
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt - datetime.timedelta(days=1)


def _excel_date(value):
    """A header cell that is a month → date(1st), else None."""
    if isinstance(value, datetime.datetime):
        return value.date().replace(day=1)
    if isinstance(value, datetime.date):
        return value.replace(day=1)
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and 40000 < value < 60000:
        return (datetime.date(1899, 12, 30)
                + datetime.timedelta(days=int(value))).replace(day=1)
    return None


def _rows(path, sheet):
    from pyxlsb import open_workbook

    with open_workbook(path) as wb:
        if sheet not in wb.sheets:
            return None
        with wb.get_sheet(sheet) as sh:
            return [[cell.v for cell in row] for row in sh.rows()]


#: The summary sheets that hold a row per person. The back-office workbook
#: scores its Retail Back Office team on a sheet of its own.
SUMMARY_SHEETS = ("Monthly_Summ", "RBO_Monthly_Summ")


def read_summary(path):
    """→ (review month 1..12 or None, [{code, name, role, months{date: score},
    old_jun}]) - every summary sheet the workbook has."""
    constants = _rows(path, "Constants") or []
    review = None
    for row in constants:
        cells = [v for v in row if v not in (None, "")]
        if cells and str(cells[0]).strip().lower() == "month_count" \
                and len(cells) > 1 and isinstance(cells[1], (int, float)):
            review = int(cells[1])
            break

    people, found = [], False
    for sheet in SUMMARY_SHEETS:
        rows = _rows(path, sheet)
        if rows is None:
            continue
        found = True
        people.extend(_people(path, sheet, rows, review))
    if not found:
        raise CommandError(f"{path} has no Monthly_Summ sheet")
    return review, people


def _people(path, sheet, rows, review):
    header_at = next(
        (i for i, row in enumerate(rows)
         if any(str(v or "").strip().lower() in ("salescode", "sales_code")
                for v in row)), None)
    if header_at is None:
        raise CommandError(f"{path}: no sales-code header on {sheet}")
    header = rows[header_at]
    lowered = [str(v or "").strip().lower() for v in header]
    code_col = next(i for i, v in enumerate(lowered)
                    if v in ("salescode", "sales_code"))
    name_col = next((i for i, v in enumerate(lowered)
                     if v in ("name", "staff - name", "staff name")), None)
    role_col = next((i for i, v in enumerate(lowered) if v == "role"), None)
    old_jun_col = next((i for i, v in enumerate(lowered) if v == "old_jun"),
                       None)
    month_cols = {i: _excel_date(v) for i, v in enumerate(header)
                  if _excel_date(v) is not None}

    people = []
    for row in rows[header_at + 1:]:
        row = list(row) + [None] * (len(header) - len(row))
        code = str(row[code_col] or "").strip().upper()
        if not code:
            continue
        months = {}
        for col, month in month_cols.items():
            value = row[col]
            if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and (review is None or month.month <= review):
                months[month] = float(value)
        old_jun = row[old_jun_col] if old_jun_col is not None else None
        people.append({
            "code": code,
            "name": str(row[name_col] or "") if name_col is not None else "",
            "role": str(row[role_col] or "") if role_col is not None else "",
            "months": months,
            "old_jun": (float(old_jun) if isinstance(old_jun, (int, float))
                        and not isinstance(old_jun, bool) else None),
        })
    return people


class Command(BaseCommand):
    help = ("Every person's platform card against the score the workbook "
            "signed for them.")

    def add_arguments(self, parser):
        parser.add_argument("--sales", default="",
                            help="Portfolio Management - Q3 2026_scorecards.xlsb")
        parser.add_argument("--bo", default="",
                            help="2026_BO_Non_Sales_Scorecards ... .xlsb")
        parser.add_argument("--month", default="",
                            help="YYYY-MM; default each workbook's own")
        parser.add_argument("--all-months", action="store_true",
                            help="every month the summary holds (slow)")
        parser.add_argument("--tolerance", type=float, default=0.0005,
                            help="a difference this small is a match "
                                 "(the card shows 4 decimals)")
        parser.add_argument("--worst", type=int, default=40)
        parser.add_argument("--csv", default="")

    def handle(self, *args, **opts):
        from apps.staff_management.live_scorecard import build_card

        books = [("sales", opts["sales"]), ("back office", opts["bo"])]
        books = [(label, path) for label, path in books if path]
        if not books:
            raise CommandError("Give --sales and/or --bo.")

        asked = None
        if opts["month"]:
            try:
                asked = datetime.datetime.strptime(
                    opts["month"][:7], "%Y-%m").date()
            except ValueError:
                raise CommandError(f"{opts['month']!r} is not YYYY-MM")

        results = []
        for label, path in books:
            review, people = read_summary(path)
            self.stdout.write(
                f"{label}: {path.split('/')[-1]} - {len(people)} people, "
                f"review month {review}")
            for person in people:
                months = sorted(person["months"])
                if asked is not None:
                    months = [m for m in months if m == asked]
                elif not opts["all_months"] and months:
                    months = [months[-1]]
                for month in months:
                    signed = person["months"][month]
                    try:
                        card = build_card(person["code"],
                                          as_at=_month_end(month))
                    except Exception as exc:  # noqa: BLE001 - reported
                        card = {"has_card": False,
                                "detail": f"could not be built: {exc}"}
                    ours = (card.get("performance_score")
                            if card.get("has_card") else None)
                    if ours is None:
                        status = "NO CARD"
                    elif abs(ours - signed) <= opts["tolerance"]:
                        status = "OK"
                    else:
                        status = "DIFF"
                    note = "" if card.get("has_card") else (
                        card.get("detail") or card.get("reason") or "")
                    if (month.month == 6 and person["old_jun"] is not None
                            and abs(person["old_jun"] - signed) > 1e-9):
                        note = (f"June recomputed: old_jun "
                                f"{person['old_jun']:.4f}. " + note)
                    results.append({
                        "book": label, "code": person["code"],
                        "name": person["name"], "role": person["role"],
                        "month": month.strftime("%Y-%m"), "signed": signed,
                        "ours": ours,
                        "diff": (ours - signed) if ours is not None else None,
                        "status": status, "note": note.strip(),
                    })

        self._report(results, opts["worst"])
        if opts["csv"]:
            with open(opts["csv"], "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(results[0]))
                writer.writeheader()
                writer.writerows(results)
            self.stdout.write(f"Every row written to {opts['csv']}")

    def _report(self, results, worst):
        from collections import defaultdict

        if not results:
            self.stdout.write("Nothing to compare.")
            return
        counts = defaultdict(int)
        for r in results:
            counts[r["status"]] += 1
        total = len(results)
        self.stdout.write("")
        self.stdout.write(
            f"compared {total}:  OK {counts['OK']}  DIFF {counts['DIFF']}  "
            f"NO CARD {counts['NO CARD']}")

        by_role = defaultdict(list)
        for r in results:
            by_role[(r["book"], r["role"])].append(r)
        self.stdout.write("")
        self.stdout.write("BY ROLE  (book / role: ok of n, mean |difference|)")
        for (book, role), rows in sorted(by_role.items()):
            diffs = [abs(r["diff"]) for r in rows if r["diff"] is not None]
            ok = sum(1 for r in rows if r["status"] == "OK")
            mean = (sum(diffs) / len(diffs)) if diffs else None
            self.stdout.write(
                f"  {book:11} {role:22} {ok:3} of {len(rows):3}   "
                + (f"{mean * 100:6.2f} pts" if mean is not None else "   -"))

        self.stdout.write("")
        self.stdout.write(f"WORST {worst}")
        ranked = sorted(
            (r for r in results if r["status"] != "OK"),
            key=lambda r: -(abs(r["diff"]) if r["diff"] is not None else 9))
        for r in ranked[:worst]:
            ours = f"{r['ours'] * 100:6.2f}%" if r["ours"] is not None else "   --  "
            self.stdout.write(
                f"  {r['code']:9} {r['name'][:22]:22} {r['role'][:12]:12} "
                f"{r['month']}  signed {r['signed'] * 100:6.2f}%  "
                f"ours {ours}  {r['status']}"
                + (f"  - {r['note'][:90]}" if r["note"] else ""))
