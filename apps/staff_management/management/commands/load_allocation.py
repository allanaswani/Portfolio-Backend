"""Load the per-person targets from the scorecard workbook's allocation sheet.

    manage.py load_allocation "Portfolio Management - Q3 2026_scorecards.xlsb" --dry-run
    manage.py load_allocation <file> --year 2026
    manage.py load_allocation --check AKL3116

"Summary Allocation" is the authoritative plan: a row per person carrying
their own target for every measure that takes one - around 99 people, where
the workbook's role sheets are ten worked examples. It is the only place
Direct Portfolio Contribution has a per-person target at all.

``--check`` needs no file. It reports what is currently STORED for one
person, which is how to tell "never loaded" from "loaded and the card is not
reading it" without guessing.

ASCII only in the output: a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

import datetime
import pathlib

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load per-person targets from the workbook's allocation sheet."

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", default="",
                            help="The scorecard workbook (.xlsb).")
        parser.add_argument("--year", type=int, default=None,
                            help="Performance year. Defaults to this year.")
        parser.add_argument("--sheet", default="Summary Allocation")
        parser.add_argument(
            "--roster", action="store_true",
            help="Also load the workbook's List sheet - the 91 people and "
                 "which card each is on. The web upload has always done both "
                 "together; this command did only the targets, so a roster "
                 "loaded from the host was silently skipped and those people "
                 "were told their code is on no roster.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be written, write none.")
        parser.add_argument("--check", default="",
                            help="Report what is STORED for one sales code, "
                                 "and read nothing.")
        parser.add_argument("--show", default="",
                            help="After reading, print this person's rows.")

    def handle(self, **options):
        from apps.staff_management.scorecard_automation.models import (
            ScEmployeeKpiTarget, ScKpi)
        from apps.staff_management.scorecard_ingest import (
            apply_allocation, apply_roster, read_allocation, read_roster)

        write = self.stdout.write
        year = options["year"] or datetime.date.today().year

        # ── what is already stored ────────────────────────────────────────
        if options["check"]:
            code = options["check"].strip()
            rows = (ScEmployeeKpiTarget.objects
                    .filter(sales_code__iexact=code, year=year)
                    .order_by("kpi_code"))
            write("")
            write(f"  {code} for {year}: {rows.count()} stored target(s)")
            for row in rows:
                write(f"      {row.kpi_code[:46]:48} "
                      f"{float(row.kpi_target or 0):>18,.2f}  "
                      f"base={float(row.base_value or 0):>18,.2f}  "
                      f"{row.source[:24]}")
            if not rows:
                write(self.style.WARNING(
                    "  Nothing stored. The card will say \"no target is set\" "
                    "for every line that has no warehouse column - Direct "
                    "Portfolio Contribution among them. Load the workbook."))
            else:
                write("")
                write(f"  The card reads these for year "
                      f"{datetime.date.today().year}; these are for {year}."
                      + ("" if year == datetime.date.today().year else
                         "  <-- MISMATCH, the card will not see them"))
            write("")
            return

        if not options["file"]:
            raise CommandError(
                "Give the workbook to read, or --check <sales code> to see "
                "what is already stored.")

        path = pathlib.Path(options["file"])
        if not path.exists():
            raise CommandError(f"{path} is not there.")

        definitions = list(ScKpi.objects.filter(is_active=True)
                           .exclude(allocation_column=""))
        if not definitions:
            raise CommandError(
                "No KPI names a column on that sheet, so there is nothing to "
                "read it for. Run seed_roles first.")

        write("")
        write(f"  reading           {path.name}")
        write(f"  sheet             {options['sheet']}")
        write(f"  measures wanted   {len(definitions)}")

        try:
            rows, warnings = read_allocation(
                str(path), definitions, options["sheet"])
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(f"That sheet could not be read: {exc}") from exc

        if not rows:
            for warning in warnings[:10]:
                write(self.style.WARNING(f"      {warning}"))
            raise CommandError("That sheet gave no rows.")

        people = {r["sales_code"].upper() for r in rows}
        by_kpi = {}
        for row in rows:
            by_kpi[row["kpi_code"]] = by_kpi.get(row["kpi_code"], 0) + 1

        write(f"  people            {len(people)}")
        write(f"  targets           {len(rows)} across {len(by_kpi)} measure(s)")
        write(f"  year              {year}")
        for warning in warnings[:10]:
            write(self.style.WARNING(f"      {warning}"))

        write("")
        for kpi_code, count in sorted(by_kpi.items(),
                                      key=lambda kv: -kv[1])[:30]:
            write(f"      {kpi_code[:48]:50} {count:4} people")

        if options["show"]:
            code = options["show"].strip().upper()
            write("")
            write(f"  {code}:")
            mine = [r for r in rows if r["sales_code"].upper() == code]
            for row in sorted(mine, key=lambda r: r["kpi_code"]):
                base = row["base_value"]
                write(f"      {row['kpi_code'][:46]:48} "
                      f"{row['kpi_target']:>18,.2f}"
                      + (f"  (base {base:,.2f} + growth)" if base is not None
                         else "  (already the year's figure)"))
            if not mine:
                write(self.style.WARNING(
                    f"      {code} is not on that sheet."))

        roster, roster_warnings = [], []
        if options["roster"]:
            try:
                roster, roster_warnings = read_roster(str(path))
            except Exception as exc:  # noqa: BLE001 - the reason is the answer
                raise CommandError(
                    f"The List sheet could not be read: {exc}") from exc
            write("")
            write(f"  roster            {len(roster)} people on the List sheet")
            by_role = {}
            for row in roster:
                by_role[row["role"]] = by_role.get(row["role"], 0) + 1
            for role, count in sorted(by_role.items()):
                write(f"      {role[:40]:42} {count:4}")
            for warning in roster_warnings:
                write(self.style.WARNING(f"      {warning}"))

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return

        if options["roster"] and roster:
            seated = apply_roster(roster, year, changed_by="load_allocation")
            write("")
            write(self.style.SUCCESS(
                f"  Roster: {seated['roles_added']} role(s) added, "
                f"{seated['roles_updated']} changed, "
                f"{seated['roles_unchanged']} already right; "
                f"{seated['people_added']} staff record(s) created."))
            if seated["no_pf_number"]:
                # Named rather than counted: the scorecard knows these people
                # by sales code and HR does not know them by PF, which is a
                # roster gap for Administration, not a failed load.
                write(self.style.WARNING(
                    f"  {len(seated['no_pf_number'])} person(s) have no PF "
                    f"number anywhere, so no staff record was created for "
                    f"them. Their role was still recorded, which is the half "
                    f"the card reads: "
                    f"{', '.join(seated['no_pf_number'][:20])}"))

        result = apply_allocation(
            rows, year, source_label="Summary Allocation",
            changed_by="load_allocation")
        write("")
        write(self.style.SUCCESS(
            f"  Wrote {result['created']} new and {result['updated']} "
            f"changed target(s); {result['unchanged']} were already right."))

        if year != datetime.date.today().year:
            write(self.style.WARNING(
                f"  These are for {year}, and a card reads "
                f"{datetime.date.today().year}. They will not show until "
                f"that year comes round."))
        write("  They show on the cards straight away - a card is computed "
              "when it is opened.")
        write("")
