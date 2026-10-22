"""This tool's card against a signed one, line by line.

    manage.py scorecard_vs_signed "Lydia Apanja_Q3_Sep_26_Scorecard.csv"
    manage.py scorecard_vs_signed card.csv --sales-code LA1234
    manage.py scorecard_vs_signed card.csv --month 2026-09

The desk exports a signed card as CSV in the workbook's own shape - the
header block, then COUNT / KPI / KPI Description / Measure of Success /
Weight / 2025 FY / GROWTH / 2026 FY / YTD Target / ACTUAL / % SCORE /
Weighted Score, and in column 13 the FEED KEY (``Active_Customers``,
``PL_Charge``), which is what makes a reliable match possible: the printed
names vary between sheets and the feed key does not.

This reads that file, builds this tool's card for the same person and the
same month, and puts the two side by side. It is the only honest way to
answer "is the September card right" - every other method has been reading
one pasted line at a time.

Read-only. Nothing is written and no card is signed.

Reading the comparison
----------------------
The CSV holds DISPLAYED figures - "3.7m", ".67m", "120.0%" - so a money line
is only known to one or two significant figures and is compared on a
tolerance that matches what is printed, not to the cent. A count, a
percentage and a weight are exact. Where the signed card shows a figure this
tool cannot produce at all, that is reported as a gap rather than a
difference, because the two mean different things to whoever has to fix it.
"""

import csv
import datetime
import re

from django.core.management.base import BaseCommand, CommandError

#: Column positions in the desk's export, from the workbook's own grid.
WEIGHT, FY_2025, GROWTH, FY_2026 = 4, 5, 6, 7
YTD_TARGET, ACTUAL, SCORE, WEIGHTED = 8, 9, 10, 11
FEED_KEY, KPI_NAME, MEASURE = 12, 2, 3

#: ``Q3_Sep_26`` -> September 2026.
MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def number(text):
    """A displayed figure -> a float, or None.

    The export's own vocabulary: ``3.7m`` is millions, ``120.0%`` is a
    fraction, ``< 2.5%`` is a threshold, ``-`` and blank are nothing.
    """
    raw = (text or "").strip().replace(",", "").replace(" ", " ").strip()
    if raw in ("", "-", "–", "—"):
        return None
    raw = raw.lstrip("<>").strip()
    percent = raw.endswith("%")
    millions = raw.endswith("m") or raw.endswith("M")
    raw = raw.rstrip("%mM").strip()
    if raw in ("", "-", ".", "-."):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if percent:
        return value / 100.0
    if millions:
        return value * 1_000_000
    return value


def displayed_tolerance(signed):
    """How close is close, for a figure printed to two significant figures.

    ``3.7m`` could be anything from 3.65m to 3.75m, so comparing it to the
    cent reports a difference that is only the rounding. Counts and rates are
    compared tightly; money is compared at 1% or half a printed step.
    """
    if signed is None:
        return 0.0
    size = abs(signed)
    if size <= 1000:              # counts, rates, percentages
        return max(0.01, size * 0.005)
    return max(size * 0.01, 5_000.0)


class Command(BaseCommand):
    help = "Compare this tool's card with a signed card exported as CSV."

    def add_arguments(self, parser):
        parser.add_argument("path", help="The signed card, as CSV.")
        parser.add_argument("--sales-code", default="",
                            help="Whose card. Default: resolved from the "
                                 "Staff Name on the file.")
        parser.add_argument("--month", default="",
                            help="YYYY-MM. Default: the Review Period on "
                                 "the file.")

    # -- reading the signed card ------------------------------------------
    def read_signed(self, path):
        """-> (header dict, [line dicts])."""
        try:
            with open(path, newline="", encoding="utf-8-sig") as handle:
                grid = list(csv.reader(handle))
        except OSError as exc:
            raise CommandError(f"cannot read {path}: {exc}")

        header, lines, past_the_head = {}, [], False
        for row in grid:
            cells = [(c or "").strip() for c in row]
            if not any(cells):
                continue
            first = cells[0]

            if first.startswith("Staff Name"):
                header["name"] = cells[2] if len(cells) > 2 else ""
                header["title"] = cells[4] if len(cells) > 4 else ""
            elif first.startswith("Review Period"):
                header["period"] = cells[2] if len(cells) > 2 else ""
            elif first.startswith("COUNT"):
                past_the_head = True
                continue
            elif first.startswith(("Reviewee", "Reviewer")):
                break

            if not past_the_head or len(row) <= FEED_KEY:
                continue
            feed = (row[FEED_KEY] or "").strip()
            if not feed:
                continue
            lines.append({
                "feed": feed,
                "kpi": (row[KPI_NAME] or "").strip(),
                "measure": (row[MEASURE] or "").strip(),
                "weight": number(row[WEIGHT]),
                "ytd_target": number(row[YTD_TARGET]),
                "actual": number(row[ACTUAL]),
                "score": number(row[SCORE]),
            })
        return header, lines

    @staticmethod
    def month_from(period):
        """``Q3_Sep_26`` -> date(2026, 9, 30)."""
        found = re.search(r"([A-Z][a-z]{2})[_\- ]?(\d{2,4})", period or "")
        if not found:
            return None
        month = MONTHS.get(found.group(1))
        if not month:
            return None
        year = int(found.group(2))
        year += 2000 if year < 100 else 0
        if month == 12:
            return datetime.date(year, 12, 31)
        return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    # -- running -----------------------------------------------------------
    def handle(self, **options):
        from apps.staff_management.live_scorecard import build_card
        from apps.staff_management.models import StaffEmployeeData
        from apps.staff_management.scorecard_automation.models import ScKpi

        write = self.stdout.write
        header, signed = self.read_signed(options["path"])
        if not signed:
            raise CommandError(
                "no scorecard lines found - this reads the desk's CSV "
                "export, which carries the feed key in column 13.")

        as_at = (self.month_from(options["month"] + "-01")
                 if options["month"] else self.month_from(header.get("period")))
        if options["month"]:
            year, month = (int(p) for p in options["month"].split("-"))
            as_at = (datetime.date(year, 12, 31) if month == 12 else
                     datetime.date(year, month + 1, 1)
                     - datetime.timedelta(days=1))

        code = (options["sales_code"] or "").strip()
        if not code:
            name = header.get("name") or ""
            row = StaffEmployeeData.objects.filter(
                staff_name__iexact=name).first()
            code = (getattr(row, "sales_code", "") or "").strip()
            if not code:
                raise CommandError(
                    f"cannot find a sales code for {name!r} - pass "
                    f"--sales-code.")

        write("")
        write(f"  {header.get('name', '?')}   {header.get('title', '')}   "
              f"{code}")
        write(f"  signed card   {header.get('period', '?')}")
        write(f"  built as at   {as_at}")
        write("  " + "=" * 96)

        card = build_card(code, as_at=as_at)
        if not card.get("has_card"):
            raise CommandError(
                f"this tool has no card for {code}: "
                f"{card.get('detail') or card.get('reason')}")

        # feed key -> this tool's line(s). ``ScKpi.actuals_sheet`` holds the
        # workbook's own feed key - Active_Customers, PL_Charge - which is
        # how the two vocabularies meet. NOT ``actuals_block``: that is a
        # block NUMBER (1, 2, 3) and matching on it collides everything.
        #
        # One feed key legitimately serves several lines - a PB card carries
        # three Banca_Assurance_Income rows, life, non-life and renewals - so
        # each key holds a LIST and they are consumed in order. Both sides are
        # ordered by the sheet, so first meets first.
        feed_of = {k.kpi_code: (k.actuals_sheet or "").strip()
                   for k in ScKpi.objects.all()}
        mine = {}
        for perspective in card.get("perspectives", []):
            for line in sorted(perspective.get("lines", []),
                               key=lambda row: row.get("kpi_order") or 0):
                key = feed_of.get(line["kpi_code"]) or line["kpi_code"]
                mine.setdefault(key.lower(), []).append(line)

        write(f"  {'line':<34}{'signed YTD':>15}{'tool YTD':>15}"
              f"{'signed act':>15}{'tool act':>15}")
        write("  " + "-" * 96)

        agree = differ = gaps = unmatched = 0
        notes = []

        for row in signed:
            found = mine.get(row["feed"].lower())
            label = (row["measure"] or row["kpi"] or row["feed"])[:33]
            if not found:
                unmatched += 1
                write(f"  {label:<34}{'':>15}{'not on this card':>30}")
                continue
            line = found.pop(0) if len(found) > 1 else found[0]

            def show(value):
                if value is None:
                    return "-"
                if abs(value) >= 10_000:
                    return f"{value:,.0f}"
                return f"{value:,.2f}"

            ours_t, ours_a = line.get("ytd_target"), line.get("ytd_actual")
            flag = ""
            for signed_value, ours in ((row["ytd_target"], ours_t),
                                       (row["actual"], ours_a)):
                if signed_value is None:
                    continue
                if ours is None:
                    flag = "   GAP - this tool has no figure"
                    break
                if abs(ours - signed_value) > displayed_tolerance(signed_value):
                    flag = "   DIFFERS"

            if flag.startswith("   GAP"):
                gaps += 1
            elif flag:
                differ += 1
                notes.append((label, row, line))
            else:
                agree += 1

            write(f"  {label:<34}{show(row['ytd_target']):>15}"
                  f"{show(ours_t):>15}{show(row['actual']):>15}"
                  f"{show(ours_a):>15}{flag}")

        write("  " + "-" * 96)
        write(f"  {agree} agree    {differ} differ    {gaps} gap    "
              f"{unmatched} not on this card    of {len(signed)} lines")
        write("")

        if notes:
            write("  WHERE THEY DIFFER")
            write("  " + "-" * 96)
            for label, row, line in notes:
                write(f"      {label}")
                if row["ytd_target"] is not None:
                    write(f"        YTD target  signed {row['ytd_target']:,.2f}"
                          f"   tool {(line.get('ytd_target') or 0):,.2f}")
                if row["actual"] is not None:
                    write(f"        actual      signed {row['actual']:,.2f}"
                          f"   tool {(line.get('ytd_actual') or 0):,.2f}")
            write("")

        write("  A GAP is a line this tool cannot measure; a DIFFERENCE is "
              "one where both have a figure and they disagree.")
        write("  Money on a signed card is printed to two significant "
              "figures, so it is compared on that tolerance, not to the cent.")
        write("  Nothing was written.")
        write("")
