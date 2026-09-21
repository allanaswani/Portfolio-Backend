"""What the department column really contains, and what was done about it.

    manage.py dept_audit
    manage.py dept_audit --candidates-only

The Staff & HR chart ranks departments by headcount and shows only the top few.
Production holds 57 distinct department values for 913 people, so departments
spelled more than one way were ranked more than once, each at a fraction of
their real size, and the chart showed roughly 736 of the 913.

This prints three things:

    what merged        every raw spelling, under the name it now counts under
    what was refused   names that look related but were NOT merged, because
                       deciding they are the same department is HR's call
    what it adds up to the headcount before and after, which must match, and
                       how much of the bank the chart now covers

The second section is the one to send to HR. Anything they confirm goes in
core.departments.ALIASES and merges from then on; anything they reject stays
split, which is the safe direction.

It writes nothing.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.gceo_dashboard.models import EmployeeTable
from apps.gceo_dashboard.staff_scope import current_staff
from core.departments import (
    BRANCH_NETWORK, UNASSIGNED, canonical, compare_key, roll_up,
)

# How many bars the CEO slide has room for. Kept here so the coverage figure
# below describes the chart people are actually looking at.
CHART_BARS = 8


class Command(BaseCommand):
    help = "Show how department names collapse, and what still needs HR to rule on."

    def add_arguments(self, parser):
        parser.add_argument(
            "--candidates-only", action="store_true",
            help="Print only the names that were NOT merged - the list for HR.",
        )

    def handle(self, *a, **o):
        w = self.stdout.write

        pairs = [
            (dept, (str(staff_id).strip() or f"row:{pk}") if staff_id else f"row:{pk}")
            for dept, staff_id, pk in current_staff(EmployeeTable.objects.all())
            .values_list("department", "staff_id", "id")
        ]
        people = len({person for _, person in pairs})

        # raw spelling -> people, and canonical -> the raw spellings under it
        raw_people = defaultdict(set)
        groups = defaultdict(set)
        for dept, person in pairs:
            label = (dept or "").strip() or "(blank)"
            raw_people[label].add(person)
            groups[canonical(dept)].add(label)

        rolled = roll_up(pairs)

        if not o["candidates_only"]:
            self._merged(w, groups, raw_people, rolled)
        self._candidates(w, groups)
        if not o["candidates_only"]:
            self._totals(w, raw_people, rolled, people)

    # -- what merged ---------------------------------------------------------

    def _merged(self, w, groups, raw_people, rolled):
        w("")
        w("Department names, under the name they now count as")
        w("=" * 68)
        for row in rolled:
            name = row["department"]
            spellings = sorted(groups.get(name, ()), key=lambda s: -len(raw_people[s]))
            w(f"  {name:<34}{row['count']:>6}")
            if len(spellings) > 1 or name in (BRANCH_NETWORK, UNASSIGNED):
                for s in spellings:
                    w(f"      <- {s[:52]:<52}{len(raw_people[s]):>5}")

    # -- what was refused ----------------------------------------------------

    def _candidates(self, w, groups):
        """Canonical names that look related but were deliberately left apart.

        Two tests, both deliberately loose - this list is meant to be read by a
        person, so a few false suggestions cost nothing and a missed one costs a
        wrong chart. Either one name contains the other ('Retail' inside 'Retail
        Banking'), or they open with the same word.
        """
        names = sorted(n for n in groups if n not in (BRANCH_NETWORK, UNASSIGNED))
        clusters = defaultdict(set)
        for i, a in enumerate(names):
            ka = compare_key(a)
            for b in names[i + 1:]:
                kb = compare_key(b)
                first = ka.split()[0] if ka.split() else ""
                related = (
                    ka in kb or kb in ka
                    or (first and first == (kb.split()[0] if kb.split() else None))
                )
                if related:
                    clusters[min(a, b)].update({a, b})

        w("")
        w("NOT merged - these need HR to say whether they are one department")
        w("=" * 68)
        if not clusters:
            w("  Nothing looks related. Every remaining name is distinct.")
            w("")
            return
        for _, members in sorted(clusters.items()):
            w("  " + "  |  ".join(sorted(members)))
        w("")
        w("  These were left split on purpose. A department split across two")
        w("  bars is visible and wrong; two real departments merged into one")
        w("  bar is invisible and wrong, so nothing merges on a guess.")
        w("")
        w("  To merge a pair once HR confirms it, add it to ALIASES in")
        w("  core/departments.py - the left-hand spelling mapping to the name")
        w("  it should count under - and redeploy. Nothing else needs changing.")
        w("")

    # -- what it adds up to --------------------------------------------------

    def _totals(self, w, raw_people, rolled, people):
        w("")
        w("Does it add up")
        w("=" * 68)
        raw_rows = sorted(raw_people.items(), key=lambda kv: -len(kv[1]))
        raw_top = len({p for _, ps in raw_rows[:CHART_BARS] for p in ps})
        new_top = sum(r["count"] for r in rolled[:CHART_BARS])

        w(f"  people                                      {people:>6}")
        w(f"  distinct spellings in the column            {len(raw_rows):>6}")
        w(f"  departments after merging                   {len(rolled):>6}")
        w("")
        w(f"  on the chart before ({CHART_BARS} raw names)          {raw_top:>6}"
          f"   {raw_top * 100 // max(people, 1):>3}% of the bank")
        w(f"  on the chart now    ({CHART_BARS} departments)        {new_top:>6}"
          f"   {new_top * 100 // max(people, 1):>3}% of the bank")
        w(f"  the rest, in 'Other'                        {people - new_top:>6}")
        w("")

        total = sum(r["count"] for r in rolled)
        if total == people:
            w(f"  Merged rows total {total}, which is the headcount. Nobody was")
            w("  counted twice and nobody was dropped.")
        else:
            # Somebody recorded under two departments is one person but two
            # rows. Worth saying out loud rather than quietly reconciling.
            w(f"  Merged rows total {total} against a headcount of {people}.")
            w(f"  {abs(total - people)} people are recorded under more than one")
            w("  department, so they appear in more than one bar. That is an HR")
            w("  data question, not a charting one.")
        w("")
        branches = next((r["count"] for r in rolled if r["department"] == BRANCH_NETWORK), 0)
        if branches:
            w(f"  {branches} people had a BRANCH recorded in the department column.")
            w(f"  They are grouped as '{BRANCH_NETWORK}' rather than appearing as")
            w("  one bar per branch. Run with --candidates-only if you only want")
            w("  the HR list.")
            w("")
