"""Merge the duplicate sales-staff rows the old uploader created.

The CSV upload used to key on (staff_pf_number, sales_code, staff_role). A row
carrying a sales code therefore never matched the same person's existing row
with a blank one, so every upload of codes created a second row instead of
filling the blank in. The upload is fixed; this repairs what it already did.

    # look, change nothing - always start here
    python manage.py dedupe_sales_staff

    # then, once the report reads correctly
    python manage.py dedupe_sales_staff --apply

For each (PF number, role) with more than one row it keeps ONE and deletes the
rest. The keeper is chosen in this order:

1. has a sales code - a blank code is the thing we were trying to fill in;
2. most recently updated;
3. highest id.

Before deleting, any field the keeper has left blank is taken from the rows
being removed, so a duplicate holding the only copy of a branch or a team
leader does not take it to the grave.

Rows where the duplicates disagree on a populated field are reported and
SKIPPED, not merged. Two different sales codes for one person is a question for
whoever maintains the list, not something a script should decide.

Two of those disagreements are mechanical rather than real, and each has its
own flag so nothing is resolved silently:

``--prefer-lettered``
    One row's "sales code" is just the PF number - 3528 against GO3528. That is
    the PF in the wrong column, not a competing code, so the lettered one wins.

``--resolve-attributes``
    The rows agree on the sales code and differ only on something else, such as
    an exit date or a zone. The keeper's value is taken and the other reported,
    so a stale row cannot quietly overwrite a corrected one.

Neither flag will ever choose between two real sales codes. BL3524 against
DSR221 stays skipped however the command is run - and is worth checking before
merging at all, since a teller holding a DSR code may be two genuine roles
rather than one duplicated person.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from apps.staff_management.models import BranchEmployeeDmcData

#: Identity. Everything else is an attribute that can be merged.
KEY = ("staff_pf_number", "staff_role")
#: Never copied between rows or compared - housekeeping, not data.
IGNORED = {"id", "updated_at", "date_time_etl"}


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


class Command(BaseCommand):
    help = "Merge duplicate branch sales staff rows created by the old uploader."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually merge. Without it nothing is written.")
        parser.add_argument(
            "--pf", help="Limit to one PF number, for checking a single case.")
        parser.add_argument(
            "--prefer-lettered", action="store_true",
            help="When one sales code is just the PF number, keep the lettered one.")
        parser.add_argument(
            "--resolve-attributes", action="store_true",
            help="Merge rows that agree on the sales code and differ only elsewhere, "
                 "taking the keeper's values.")

    def handle(self, *args, **o):
        apply = o["apply"]
        fields = [f.name for f in BranchEmployeeDmcData._meta.fields
                  if f.name not in IGNORED]

        qs = BranchEmployeeDmcData.objects.all()
        if o.get("pf"):
            qs = qs.filter(staff_pf_number=o["pf"])

        groups = (qs.values(*KEY)
                    .annotate(n=Count("id"))
                    .filter(n__gt=1)
                    .order_by("staff_pf_number"))

        if not groups:
            self.stdout.write(self.style.SUCCESS("No duplicates. Nothing to do."))
            return

        merged = skipped = removed = 0
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{len(groups)} PF/role combination(s) with more than one row\n"))

        for group in groups:
            rows = list(BranchEmployeeDmcData.objects.filter(
                staff_pf_number=group["staff_pf_number"],
                staff_role=group["staff_role"],
            ).order_by("-id"))

            label = f"PF {group['staff_pf_number']} / {group['staff_role'] or '(no role)'}"

            # Disagreement on a populated field is a decision, not a merge.
            conflicts, code_values = [], set()
            for field in fields:
                values = {getattr(r, field) for r in rows if not _blank(getattr(r, field))}
                if field == "sales_code":
                    code_values = {str(v) for v in values}
                if len(values) > 1:
                    conflicts.append(f"{field}={sorted(str(v) for v in values)}")

            reason = ""
            if conflicts:
                pf = str(group["staff_pf_number"] or "").strip()
                # A "code" equal to the PF number is the PF in the wrong column.
                placeholders = {c for c in code_values if c == pf or c.isdigit()}
                real_codes = code_values - placeholders

                if len(code_values) > 1 and len(real_codes) == 1 and o["prefer_lettered"]:
                    rows = [r for r in rows
                            if str(r.sales_code or "").strip() not in placeholders] or rows
                    conflicts = [c for c in conflicts if not c.startswith("sales_code=")]
                    reason = f" [dropped placeholder code {sorted(placeholders)}]"

                if conflicts and len(code_values) <= 1 and o["resolve_attributes"]:
                    reason += f" [kept the keeper's {', '.join(c.split('=')[0] for c in conflicts)}]"
                    conflicts = []

            if conflicts:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  SKIP  {label}: rows disagree on {', '.join(conflicts)}"))
                continue

            keeper = sorted(
                rows,
                key=lambda r: (
                    not _blank(r.sales_code),
                    getattr(r, "updated_at", None) or r.id,
                    r.id,
                ),
                reverse=True,
            )[0]
            # Every row in the group that is not the keeper goes, including any
            # placeholder rows filtered out of the conflict check above.
            all_rows = BranchEmployeeDmcData.objects.filter(
                staff_pf_number=group["staff_pf_number"],
                staff_role=group["staff_role"])
            others = [r for r in all_rows if r.id != keeper.id]

            filled = []
            for field in fields:
                if not _blank(getattr(keeper, field)):
                    continue
                for other in others:
                    value = getattr(other, field)
                    if not _blank(value):
                        setattr(keeper, field, value)
                        filled.append(field)
                        break

            note = f" (filled {', '.join(filled)} from the duplicate)" if filled else ""
            self.stdout.write(
                f"  merge {label}: keeping id {keeper.id} "
                f"[code={keeper.sales_code or 'none'}], removing "
                f"{', '.join(str(r.id) for r in others)}{note}{reason}")

            if apply:
                with transaction.atomic():
                    keeper.save()
                    for other in others:
                        other.delete()
                        removed += 1
            merged += 1

        self.stdout.write("")
        if apply:
            self.stdout.write(self.style.SUCCESS(
                f"Merged {merged} group(s), removed {removed} duplicate row(s). "
                f"Skipped {skipped} needing a human decision."))
        else:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN - nothing was written. {merged} group(s) would be merged, "
                f"{skipped} skipped. Re-run with --apply when the above reads right."))
