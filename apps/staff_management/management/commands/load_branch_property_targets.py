"""Load a branch property plan from the spreadsheet Strategy issues it in.

    manage.py load_branch_property_targets branch_properties_targets.xlsx --year 2027

Expects the four columns the 2026 plan used: brn_code, staff_branch,
staff_zone, target_properties. Column order does not matter; the header row
names them.

The 2026 plan is already in the database via migration 0016, so this command is
for the next one. It reports the total it loaded, because a plan that does not
add up to the bank figure is the thing worth catching before anyone reads a
dashboard off it.
"""
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.date_utils import branch_code_for

from apps.staff_management.models import (
    BranchFinalEmployeeDmcData, BranchPropertyTarget,
)

REQUIRED = ["brn_code", "staff_branch", "staff_zone", "target_properties"]


class Command(BaseCommand):
    help = "Load branch property targets from an .xlsx plan."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the .xlsx plan.")
        parser.add_argument(
            "--year", type=int, required=True,
            help="Plan year these targets apply to.",
        )
        parser.add_argument(
            "--sheet", default=None,
            help="Sheet name (default: the first sheet).",
        )
        parser.add_argument(
            "--expect-total", type=str, default=None,
            help="Refuse the load unless the targets sum to this, e.g. 340.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse and report, write nothing.",
        )

    def handle(self, *a, **o):
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover - environment issue
            raise CommandError("openpyxl is required to read .xlsx plans") from exc

        wb = openpyxl.load_workbook(o["path"], read_only=True, data_only=True)
        ws = wb[o["sheet"]] if o["sheet"] else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip().lower() if h is not None else "" for h in next(it)]
        except StopIteration:
            raise CommandError("The sheet is empty.")

        missing = [c for c in REQUIRED if c not in header]
        if missing:
            wb.close()
            raise CommandError(
                f"Missing column(s): {', '.join(missing)}. Found: {', '.join(header)}"
            )
        idx = {c: header.index(c) for c in REQUIRED}

        rows, problems = [], []
        for n, r in enumerate(it, start=2):
            if r[idx["brn_code"]] is None:
                continue
            try:
                brn = int(r[idx["brn_code"]])
                target = Decimal(str(r[idx["target_properties"]] or 0))
            except (TypeError, ValueError, InvalidOperation) as exc:
                problems.append(f"  row {n}: {exc}")
                continue
            if target < 0:
                problems.append(f"  row {n}: negative target {target}")
                continue
            rows.append((
                brn,
                str(r[idx["staff_branch"]] or "").strip(),
                str(r[idx["staff_zone"]] or "").strip(),
                target.quantize(Decimal("0.00000001")),
            ))
        wb.close()

        if problems:
            raise CommandError("Could not read every row:\n" + "\n".join(problems))
        if not rows:
            raise CommandError("No rows found.")

        seen, dupes = set(), set()
        for brn, *_ in rows:
            if brn in seen:
                dupes.add(brn)
            seen.add(brn)
        if dupes:
            raise CommandError(f"brn_code repeated in the sheet: {sorted(dupes)}")

        total = sum(r[3] for r in rows)
        if o["expect_total"] is not None:
            expected = Decimal(o["expect_total"])
            if total != expected:
                raise CommandError(
                    f"Targets sum to {total}, not the expected {expected}. "
                    "Nothing was written."
                )

        self.stdout.write(f"{len(rows)} branches, targets totalling {total}")
        if o["dry_run"]:
            for brn, branch, zone, target in sorted(rows):
                self.stdout.write(f"  {brn:>4}  {branch:<30} {zone:<8} {target}")
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        dmc_by_name = {}
        for row in (BranchFinalEmployeeDmcData.objects
                    .filter(brn_code__isnull=True).exclude(staff_branch="")):
            code = branch_code_for(row.staff_branch)
            if code is not None:
                dmc_by_name.setdefault(code, []).append(row.pk)

        created = updated = 0
        dmc_rows, dmc_missing = 0, []
        with transaction.atomic():
            for brn, branch, zone, target in rows:
                _, made = BranchPropertyTarget.objects.update_or_create(
                    brn_code=brn, year=o["year"],
                    defaults={
                        "staff_branch": branch,
                        "staff_zone": zone,
                        "target_properties": target,
                        "updated_by": "load_branch_property_targets",
                    },
                )
                created += made
                updated += not made

                # Keep the branch DMC row in step. That table is what
                # targets.py reads for the bank / zone / branch scopes, so a
                # plan that lives only in BranchPropertyTarget would load
                # cleanly and change nothing anybody can see.
                #
                # On brn_code, never on the name: the plan calls 270 "SAMEER
                # BUSINESS PARK BRANCH" where the warehouse says "SAMEER
                # BRANCH". A row is updated, never created — those rows carry
                # every other target the bank sets.
                hit = BranchFinalEmployeeDmcData.objects.filter(
                    brn_code=brn).update(target_properties=target)
                # The DMC upload upserts on staff_branch alone, so brn_code can
                # be null. Fall back to the name, resolved through the alias
                # table in core.date_utils — exact matches only, so a branch
                # that cannot be resolved is reported rather than guessed at.
                if not hit and brn in dmc_by_name:
                    hit = BranchFinalEmployeeDmcData.objects.filter(
                        pk__in=dmc_by_name[brn]).update(target_properties=target)
                if hit:
                    dmc_rows += hit
                else:
                    dmc_missing.append((brn, branch))

        self.stdout.write(self.style.SUCCESS(
            f"{o['year']}: {created} created, {updated} updated."
        ))
        self.stdout.write(
            f"branch_final_employee_dmc_data: {dmc_rows} row(s) carry the target."
        )
        if dmc_missing:
            self.stdout.write(self.style.WARNING(
                f"{len(dmc_missing)} planned branch(es) have no DMC row, so the "
                "target will not reach the branch/zone/bank scopes for them:"
            ))
            for brn, branch in sorted(dmc_missing):
                self.stdout.write(f"  {brn:>4}  {branch}")
