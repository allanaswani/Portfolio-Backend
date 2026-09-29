"""Give the imported pipeline rows a sales code, by matching the RM's name.

The workbook records the owner as "Sales Person Name" — free text, and the only
owner an imported row has. Until that text becomes a sales_code, those rows are
visible to the Team Leader and to no individual RM, because an RM's view
filters on the code.

    python manage.py match_pipeline_rms            # look, change nothing
    python manage.py match_pipeline_rms --apply

Matching is deliberately conservative, in this order:

1. **Exact** on the folded full name ("glady wanjira").
2. **Surname plus first initial**, which catches "Glady Wanjira" against a
   profile filed as "Gladys Wanjira" only when nothing else shares that pair.

Anything matching more than one person is reported and left alone. Two RMs
called Irene are a question for the Team Leader, and a script that picks one
has quietly reassigned somebody's deals.

Nothing is ever overwritten: rows that already carry a sales code are skipped,
so this can be run again after new names appear without disturbing work an RM
has since done.
"""

import re
import unicodedata
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.commercial_pipeline.models import PipelineEntry
from apps.portfolio.models import Profile


def fold(name):
    """Lower-cased, unaccented, single-spaced. 'Glady  Wanjira ' -> 'glady wanjira'."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def initial_key(folded):
    """('wanjira', 'g') from 'glady wanjira' — surname plus first initial."""
    parts = folded.split()
    if len(parts) < 2:
        return None
    return (parts[-1], parts[0][0])


class Command(BaseCommand):
    help = "Match imported pipeline rows to RMs by name and set their sales code."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without it nothing is saved.")
        parser.add_argument("--segment", default="",
                            help="Only consider profiles in this segment.")

    def handle(self, *args, **o):
        profiles = Profile.objects.select_related("user").exclude(sales_code="")
        profiles = profiles.exclude(sales_code__isnull=True)
        if o["segment"]:
            profiles = profiles.filter(segment__iexact=o["segment"])

        by_name = defaultdict(list)
        by_initial = defaultdict(list)
        for p in profiles:
            full = fold(f"{p.user.first_name} {p.user.last_name}")
            if not full:
                continue
            by_name[full].append(p)
            key = initial_key(full)
            if key:
                by_initial[key].append(p)

        rows = (PipelineEntry.objects
                .filter(sales_code="")
                .exclude(rm_name="")
                .order_by("rm_name", "id"))

        matched, ambiguous, unknown = [], defaultdict(list), defaultdict(int)

        for row in rows:
            folded = fold(row.rm_name)
            hits = by_name.get(folded, [])
            how = "exact"

            if not hits:
                key = initial_key(folded)
                hits = by_initial.get(key, []) if key else []
                how = "surname + initial"

            if len(hits) == 1:
                matched.append((row, hits[0], how))
            elif len(hits) > 1:
                ambiguous[row.rm_name].append(
                    ", ".join(f"{p.user.get_full_name()} ({p.sales_code})" for p in hits))
            else:
                unknown[row.rm_name] += 1

        # ── report ──────────────────────────────────────────────────
        per_rm = defaultdict(lambda: [0, "", ""])
        for row, p, how in matched:
            entry = per_rm[row.rm_name]
            entry[0] += 1
            entry[1] = p.sales_code
            entry[2] = how

        self.stdout.write(self.style.MIGRATE_HEADING("\nMatched"))
        for name, (count, code, how) in sorted(per_rm.items()):
            self.stdout.write(f"  {name:<28} -> {code:<10} {count:>3} row(s)  [{how}]")
        if not per_rm:
            self.stdout.write("  nothing")

        if ambiguous:
            self.stdout.write(self.style.WARNING(
                "\nMore than one person matches — left alone:"))
            for name, who in sorted(ambiguous.items()):
                self.stdout.write(f"  {name:<28} {who[0]}")

        if unknown:
            self.stdout.write(self.style.WARNING(
                "\nNo profile with a sales code for these names:"))
            for name, count in sorted(unknown.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"  {name:<28} {count:>3} row(s)")
            self.stdout.write(
                "  These stay visible to the Team Leader. Give the person a sales\n"
                "  code on their profile and run this again, or reassign the rows\n"
                "  from the pipeline page.")

        if not o["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN — nothing written. {len(matched)} row(s) would be "
                f"assigned. Re-run with --apply."))
            return

        with transaction.atomic():
            for row, p, _ in matched:
                row.sales_code = p.sales_code
                # Keep the name as written. It is what the Team Leader reads in
                # the report, and the profile's spelling is not necessarily the
                # one the desk uses.
                row.save(update_fields=["sales_code", "updated_at"])

        self.stdout.write(self.style.SUCCESS(
            f"\nAssigned {len(matched)} row(s) to {len(per_rm)} RM(s)."))
