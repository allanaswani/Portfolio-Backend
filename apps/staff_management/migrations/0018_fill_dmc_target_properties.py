"""Copy the 2026 property plan onto branch_final_employee_dmc_data.

The plan is loaded into BranchPropertyTarget by 0016. This puts the same figure
on the branch DMC row, which is where the whole targets machinery reads from:
targets.py's CATALOGUE already had a ("properties", "target_properties", ...)
entry, so the moment the column exists and is filled, Property Sales appears at
bank, zone and branch scope alongside every other target, with no new plumbing.

Matched on brn_code, never on the branch name. The plan calls 270 "SAMEER
BUSINESS PARK BRANCH" and the warehouse calls it "SAMEER BRANCH"; 260 is "THIKA
ROAD MALL-TRM BRANCH" against "TRM BRANCH". Matching on text would miss those
two and, worse, a loose match puts one branch's plan on another branch's row.

A branch in the plan with no DMC row is REPORTED, not created. These rows carry
every other target the bank sets; inventing one from a single column would
produce a branch whose entire plan is one number.
"""
from django.db import migrations

YEAR = 2026


def fill(apps, schema_editor):
    Target = apps.get_model("staff_management", "BranchPropertyTarget")
    Dmc = apps.get_model("staff_management", "BranchFinalEmployeeDmcData")

    plan = {t.brn_code: t for t in Target.objects.filter(year=YEAR)}
    if not plan:
        return

    # The DMC upload upserts on staff_branch alone, so brn_code is not
    # guaranteed to be populated. Build a name -> code index over the rows that
    # are actually there, using the alias table rather than any fuzzy matching,
    # so a branch whose code is missing can still be reached by its name.
    from core.date_utils import branch_code_for

    by_name = {}
    for row in Dmc.objects.filter(brn_code__isnull=True).exclude(staff_branch=""):
        code = branch_code_for(row.staff_branch)
        if code is not None:
            by_name.setdefault(code, []).append(row.pk)

    matched, missing, by_name_hits = 0, [], 0
    for brn, target in plan.items():
        rows = Dmc.objects.filter(brn_code=brn)
        hit = rows.update(target_properties=target.target_properties)
        if not hit and brn in by_name:
            hit = Dmc.objects.filter(pk__in=by_name[brn]).update(
                target_properties=target.target_properties)
            by_name_hits += hit
        if not hit:
            missing.append((brn, target.staff_branch))
            continue
        matched += hit

    if by_name_hits:
        print(f"\n  target_properties: {by_name_hits} row(s) matched by branch "
              f"name because brn_code was null on them.")

    if missing:
        # Printed, not raised: a DMC table that is missing a branch is a data
        # question for Strategy, and failing the migration would block every
        # other change in this deploy over it.
        print(
            f"\n  target_properties: filled {matched} row(s). "
            f"{len(missing)} planned branch(es) have no branch_final_employee_dmc_data "
            f"row and were skipped: "
            + ", ".join(f"{b} ({n})" for b, n in sorted(missing))
        )


def unfill(apps, schema_editor):
    Dmc = apps.get_model("staff_management", "BranchFinalEmployeeDmcData")
    Dmc.objects.update(target_properties=None)


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0017_branchfinalemployeedmcdata_target_properties_and_more"),
    ]

    operations = [migrations.RunPython(fill, unfill)]
