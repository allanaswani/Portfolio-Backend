"""Read the back-office scorecard workbook into a CSV we can configure from.

    manage.py extract_bo_scorecards "<path to the .xlsb>" --out docs/bo-scorecard-kpi-map.csv

Why this exists, and why it is shorter than the RM equivalent
────────────────────────────────────────────────────────────
The RM workbook (``Portfolio Management - Q3 2026_scorecards.xlsb``) does not
say which sheet of the actuals template each KPI line reads. Establishing that
took a calibration pass — reproducing the ACTUAL each card states — and for 19
KPIs it could not be established at all, because every calibration card read
zero for them.

**The back-office workbook states it.** Each card's table carries a
``column_name`` column naming the actuals sheet for that line:
``Active_Customers``, ``PL_Charge``, ``RE_activation``, ``NPS``,
``Account_Opening_PB``, ``Branch_Loan_TAT``, ``HFDI_Volume``, ``VIC``,
``Branch_Audit``, ``Operation_Lossess``, ``Sales_Productivity``,
``Training_hours`` and so on, all of which are sheets in
``2026_BO_Actual_Template.xlsx``. So there is nothing to infer: the mapping is
declared, and this command just reads it out.

The card layout, which is the same on all ten
─────────────────────────────────────────────
Row 8 is the header, and the columns are fixed:

    1 Perspective (carrying its own weight, e.g. "Financials 24.0%")
    2 Measure              3 Key Initiatives (the measure of success)
    4 Weight on Target     5 Target
    6 YTD Target           7 Actual Achievement
    8 % Achievement        9 Weighted Average
    10 Comments            11 column_name   12 prorate_new

A perspective label appears once and then applies to the rows under it, and a
Measure does the same where one measure has several initiatives (BB and PB
account-opening TAT share "TAT (AO)"). Both are carried down here, because a
row that loses its perspective loses its weight grouping.

Two things worth reading off the numbers rather than assuming
─────────────────────────────────────────────────────────────
On the Q2_Jun_2026 cards the YTD target is the annual one times **6/12** for
every money and count line, and **unchanged** for every threshold (NPS 0.6,
audit 1.0, resolution 0.85, compliance 0.9, productivity 0.8, operation losses
0.0). That is the same two rules the RM card already follows: pro-rate to the
elapsed year, and never pro-rate a threshold.

It writes nothing to the database. It reads a workbook and writes a CSV.
"""

import csv
import datetime
import re

from django.core.management.base import BaseCommand, CommandError

#: Sheets that are not a role card.
NOT_A_CARD = {
    "List", "Monthly_Summ", "RBO_Monthly_Summ", "BOM_SUMM", "BOMCSO_SUMM",
    "CSO_SUMM", "TELLER_SUMM", "Prod", "Sheet1", "Constants", "diaspora_npl",
    "mapping",
}

HEADER_MARKERS = ("perspective", "measure")
COLUMNS = [
    "sheet", "role_title", "staff_name", "sales_code", "branch", "period",
    "kpi_order", "perspective", "perspective_weight", "measure",
    "key_initiative", "weight", "target", "ytd_target", "actual",
    "pct_achievement", "weighted", "actuals_sheet", "ytd_over_annual",
    "target_basis", "threshold", "target_from_ytd",
]


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _weight_in(label):
    """"Financials 24.0%" -> 0.24. The perspective carries its own weight in
    its label and nowhere else, so it is read from the text."""
    found = re.search(r"([\d.]+)\s*%", label or "")
    return round(float(found.group(1)) / 100, 6) if found else None


def _perspective_name(label):
    return re.sub(r"\s*[\d.]+\s*%\s*$", "", label or "").strip()


class Command(BaseCommand):
    help = "Read the back-office scorecard workbook into a CSV."

    def add_arguments(self, parser):
        parser.add_argument("workbook")
        parser.add_argument(
            "--actuals", default="",
            help="The matching actuals template (.xlsx). Given one, every "
                 "sheet name the cards claim is checked against it - which is "
                 "what makes reading that column by position safe.")
        parser.add_argument("--out", default="docs/bo-scorecard-kpi-map.csv")
        parser.add_argument(
            "--roster-out", default="docs/bo-scorecard-roster.csv",
            help="Where to write the List sheet (who holds which card).")

    def _actuals_sheets(self, path):
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True)
        return {name.strip().lower(): name for name in book.sheetnames}

    def handle(self, workbook, **options):
        try:
            from pyxlsb import open_workbook
        except ImportError as exc:  # noqa: BLE001
            raise CommandError(
                "pyxlsb is needed to read a .xlsb. It is in requirements.txt; "
                "install it in this environment first.") from exc

        write = self.stdout.write
        rows, roster, roles = [], [], {}

        with open_workbook(workbook) as book:
            names = list(book.sheets)
            if "List" in names:
                roster = self._roster(book)
                for person in roster:
                    roles.setdefault(person["role"], 0)
                    roles[person["role"]] += 1

            for sheet in names:
                if sheet in NOT_A_CARD:
                    continue
                read = self._card(book, sheet)
                if read:
                    rows.extend(read)
                else:
                    write(self.style.WARNING(
                        f"  {sheet}: no KPI table found, skipped"))

        if not rows:
            raise CommandError("No role cards were read from that workbook.")

        # Check what the cards claim against what the actuals template has.
        known = {}
        if options["actuals"]:
            known = self._actuals_sheets(options["actuals"])
            for row in rows:
                claimed = row["actuals_sheet"]
                if not claimed:
                    continue
                match = known.get(claimed.strip().lower())
                # The cards spell a sheet with different capitals from the
                # template ("Re_activation" against "RE_activation"), so the
                # canonical spelling is written out rather than the card's.
                row["actuals_sheet"] = match or f"{claimed} (NOT A SHEET)"


        with open(options["out"], "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        if roster:
            with open(options["roster_out"], "w", newline="",
                      encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(roster[0].keys()))
                writer.writeheader()
                writer.writerows(roster)

        cards = sorted({r["sheet"] for r in rows})
        sheets = sorted({r["actuals_sheet"] for r in rows if r["actuals_sheet"]})
        unmapped = [r for r in rows if not r["actuals_sheet"]]

        write("")
        write(f"{len(cards)} card(s), {len(rows)} KPI line(s) -> {options['out']}")
        for card in cards:
            lines = [r for r in rows if r["sheet"] == card]
            total = sum(_number(r["weight"]) or 0 for r in lines)
            write(f"   {card:<26}{len(lines):>3} lines   weight {total:.3f}")
        if roster:
            write("")
            write(f"{len(roster)} people on the List sheet -> "
                  f"{options['roster_out']}")
            for role, count in sorted(roles.items()):
                write(f"   {role:<26}{count:>4}")
        write("")
        write(f"{len(sheets)} actuals sheet(s) named by the cards:")
        write("   " + ", ".join(sheets))
        if known:
            missing = sorted({r["actuals_sheet"] for r in rows
                              if "(NOT A SHEET)" in r["actuals_sheet"]})
            unused = sorted(set(known.values())
                            - {r["actuals_sheet"] for r in rows})
            write("")
            write(f"checked against {options['actuals']}: "
                  f"{len(known)} sheet(s) in the template")
            if missing:
                write(self.style.WARNING(
                    "   named by a card but NOT in the template: "
                    + ", ".join(missing)))
            if unused:
                write(f"   in the template but named by no card: "
                      f"{', '.join(unused)}")

        if unmapped:
            write("")
            write(self.style.WARNING(
                f"{len(unmapped)} line(s) name no actuals sheet:"))
            for row in unmapped[:20]:
                write(f"   {row['sheet']:<22}{row['measure'][:30]:<32}"
                      f"{row['key_initiative'][:40]}")

    # ── the List sheet ───────────────────────────────────────────────────
    def _roster(self, book):
        out = []
        with book.get_sheet("List") as sheet:
            header = None
            for row in sheet.rows():
                values = {cell.c: cell.v for cell in row}
                if header is None:
                    labels = {index: _text(v).lower()
                              for index, v in values.items()}
                    if any("salescode" in v.replace(" ", "")
                           for v in labels.values()):
                        header = labels
                    continue
                person = {}
                for index, label in header.items():
                    person[label] = _text(values.get(index))
                code = (person.get("staffsalescode")
                        or person.get("staff sales code") or "")
                if not code:
                    continue
                out.append({
                    "sales_code": code,
                    "pf_number": person.get("staffpf-number", ""),
                    "staff_name": person.get("staff - name", ""),
                    "role": person.get("role", ""),
                    "branch": person.get("branch", ""),
                    "zone": person.get("zone", ""),
                    "line_manager": person.get("bm", ""),
                    "email": person.get("e-mail_to", ""),
                })
        return out

    # ── one role card ────────────────────────────────────────────────────
    def _card(self, book, name):
        with book.get_sheet(name) as sheet:
            grid = {}
            for index, row in enumerate(sheet.rows(), start=1):
                grid[index] = {cell.c: cell.v for cell in row}

        header_row = None
        for index in sorted(grid):
            labels = [_text(v).lower() for v in grid[index].values()]
            if all(any(marker in label for label in labels)
                   for marker in HEADER_MARKERS):
                header_row = index
                break
        if header_row is None:
            return []

        where = {}
        for column, value in grid[header_row].items():
            label = _text(value).lower()
            if "perspective" in label:
                where["perspective"] = column
            elif label.startswith("measure"):
                where["measure"] = column
            elif "initiative" in label:
                where["initiative"] = column
            elif "weight on" in label:
                where["weight"] = column
            elif label in ("target", "pm"):
                # Nine of the ten cards leave "Target" out entirely and put a
                # PM - per month - column there instead. Reading only "target"
                # found nothing on those nine, which is how 120 of the 132
                # lines came back with no target at all.
                where["target"] = column
                where["target_label"] = label
            elif "ytd target" in label:
                where["ytd_target"] = column
            elif "actual" in label:
                where["actual"] = column
            elif "achievement" in label:
                where["pct"] = column
            elif "weighted" in label:
                where["weighted"] = column
            elif "column_name" in label:
                where["actuals_sheet"] = column

        # Three of the ten cards do not LABEL that column - their header row
        # stops at "Comments" - but they still put the sheet name in the
        # column after it. So the position is used when the label is missing,
        # and every value is checked against the actuals template's real sheet
        # names, which is what makes taking it on position safe rather than a
        # guess.
        if "actuals_sheet" not in where and "comments" in {
                _text(v).lower() for v in grid[header_row].values()}:
            for column, value in grid[header_row].items():
                if _text(value).lower() == "comments":
                    where["actuals_sheet"] = column + 1
                    break

        staff = self._header_block(grid, header_row)

        out, order = [], 0
        perspective = measure = ""
        for index in sorted(i for i in grid if i > header_row):
            cells = grid[index]
            weight = _number(cells.get(where.get("weight")))
            initiative = _text(cells.get(where.get("initiative")))
            # A row is a KPI line when it carries a weight. The total row and
            # the signature block carry none.
            if weight is None or not initiative:
                continue
            raw = _text(cells.get(where.get("perspective")))
            if raw:
                perspective = raw
            this_measure = _text(cells.get(where.get("measure")))
            if this_measure:
                measure = this_measure

            target = _number(cells.get(where.get("target")))
            ytd = _number(cells.get(where.get("ytd_target")))
            order += 1
            out.append({
                "sheet": name,
                "role_title": staff.get("job_title", ""),
                "staff_name": staff.get("name", ""),
                "sales_code": staff.get("sales_code", ""),
                "branch": staff.get("branch", ""),
                "period": staff.get("period", ""),
                "kpi_order": order,
                "perspective": _perspective_name(perspective),
                "perspective_weight": _weight_in(perspective),
                "measure": measure,
                "key_initiative": initiative,
                "weight": weight,
                "target": _text(cells.get(where.get("target"))),
                "ytd_target": _text(cells.get(where.get("ytd_target"))),
                "actual": _text(cells.get(where.get("actual"))),
                "pct_achievement": _text(cells.get(where.get("pct"))),
                "weighted": _text(cells.get(where.get("weighted"))),
                "actuals_sheet": _text(cells.get(where.get("actuals_sheet"))),
                # The pro-ration the card itself used, which is how the rule
                # was read off rather than assumed: 6/12 for a money or count
                # line on a Q2 card, 1.0 for a threshold.
                "ytd_over_annual": (round(ytd / target, 6)
                                    if target and ytd is not None else ""),
                # Whether column 5 is the YEAR's target or a PER-MONTH one.
                # The cards do not agree: BOM_SCORECARD heads it "Target" and
                # puts the annual figure there, and the other nine head it
                # "PM" and put a monthly one.
                "target_basis": ("annual" if where.get("target_label")
                                 == "target" else "monthly"),
                # A line where the per-month figure and the YTD figure are the
                # SAME is a threshold, not an accrual: NPS 0.6 against 0.6,
                # branch audit 1 against 1. That is read off the card rather
                # than decided from the KPI's name, and it is the only thing
                # that distinguishes "60% all year" from "0.6 a month".
                "threshold": (
                    "yes" if (
                        # Written as a limit - "< 1 Day", "<20%", "<5%" - in
                        # which case the number is in the YTD column and the
                        # line is a ceiling by construction.
                        (target is None
                         and "<" in _text(cells.get(where.get("target"))))
                        or (target is not None and ytd is not None
                            and abs(target - ytd) < 1e-9))
                    else "no" if ytd is not None else ""),
                # The figure to use when the target cell is prose. "< 2 Days"
                # carries its 2 in the YTD column.
                "target_from_ytd": ("yes" if target is None
                                    and ytd is not None else "no"),
            })
        return out

    def _header_block(self, grid, header_row):
        """Name, job title, branch and period, read off the rows above the
        table. Labels rather than fixed cells, because the block is not in the
        same place on every card."""
        found = {}
        for index in sorted(i for i in grid if i < header_row):
            cells = sorted(grid[index].items())
            for position, (_column, value) in enumerate(cells):
                label = _text(value).lower().rstrip(":")
                following = (_text(cells[position + 1][1])
                             if position + 1 < len(cells) else "")
                if not following:
                    continue
                if label.startswith("emp"):
                    found.setdefault("name", following)
                elif label == "job title":
                    found.setdefault("job_title", following)
                elif label == "branch":
                    found.setdefault("branch", following)
                elif "performance period" in label:
                    found.setdefault("period", following)
                elif "sales code" in label or "staff code" in label:
                    found.setdefault("sales_code", following)
        found.setdefault("read_on", datetime.date.today().isoformat())
        return found
