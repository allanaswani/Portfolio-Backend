"""Show how branch names resolve to branch/unit codes on THIS database.

``drawdown_daily`` carries only a numeric ``unit_code``, so every branch-scoped
drawdown query depends on the name → code map built by ``core.branch_codes``.
When a branch page reports no data, the first question is always whether the
branch resolved to any code at all — this answers it against the live database
instead of guessing.

    docker exec hf-backend python manage.py branch_codes
    docker exec hf-backend python manage.py branch_codes --branch "MOMBASA BRANCH"
    docker exec hf-backend python manage.py branch_codes --conflicts
    docker exec hf-backend python manage.py branch_codes --unmapped
"""

from django.core.management.base import BaseCommand

from core import branch_codes as bc


class Command(BaseCommand):
    help = "Show the branch name → branch/unit code map used to scope branch pages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--branch",
            help="Resolve one branch name (suffix- and case-insensitive).",
        )
        parser.add_argument(
            "--conflicts",
            action="store_true",
            help="List codes that more than one branch name claims, with the vote "
                 "counts and the winner. These are data-quality problems upstream.",
        )
        parser.add_argument(
            "--unmapped",
            action="store_true",
            help="List drawdown_daily unit_codes that resolve to no branch. Their "
                 "rows are invisible to every branch page.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Rebuild from the database, ignoring the cached map.",
        )

    def handle(self, *args, **options):
        if options["refresh"]:
            bc.reset_cache()

        if options["branch"]:
            self._one_branch(options["branch"])
            return
        if options["conflicts"]:
            self._conflicts()
            return
        if options["unmapped"]:
            self._unmapped()
            return
        self._full_map()

    # ── views ────────────────────────────────────────────────────────────────

    def _one_branch(self, name):
        codes = bc.branch_codes_for(name)
        key = bc.normalize_branch(name)
        self.stdout.write(f"branch     : {name}")
        self.stdout.write(f"normalised : {key}")
        if codes:
            self.stdout.write(self.style.SUCCESS(f"codes      : {codes}"))
        else:
            self.stdout.write(self.style.ERROR("codes      : NONE — branch pages will show no data"))
            self.stdout.write("")
            self.stdout.write("Known branches:")
            for known in sorted(bc.resolved_map()):
                self.stdout.write(f"  {known}")

    def _full_map(self):
        mapping = bc.resolved_map()
        width = max((len(n) for n in mapping), default=10)
        self.stdout.write(f"{len(mapping)} branches resolved\n")
        for name, codes in mapping.items():
            self.stdout.write(f"  {name:<{width}}  {codes}")

    def _conflicts(self):
        votes = bc._collect_votes()
        conflicted = {c: t for c, t in votes.items() if len(t) > 1}
        if not conflicted:
            self.stdout.write(self.style.SUCCESS("No code is claimed by more than one branch name."))
            return
        self.stdout.write(self.style.WARNING(
            f"{len(conflicted)} code(s) claimed by more than one branch name. "
            "The majority wins; the rest of those rows are mislabelled upstream."
        ))
        _, code_to_name = bc._maps()
        for code in sorted(conflicted):
            tally = sorted(conflicted[code].items(), key=lambda kv: -kv[1])
            winner = code_to_name.get(code)
            self.stdout.write(f"\n  code {code} → {winner}")
            for name, count in tally:
                marker = "*" if name == winner else " "
                self.stdout.write(f"    {marker} {name:<28} {count:>10,} rows")

    def _unmapped(self):
        from django.db import connection

        if "drawdown_daily" not in set(connection.introspection.table_names()):
            self.stdout.write(self.style.WARNING("drawdown_daily is not present on this database."))
            return

        _, code_to_name = bc._maps()
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT unit_code, COUNT(*) AS rows, COALESCE(SUM(gross_drawdown), 0) AS gross
                FROM   drawdown_daily
                WHERE  unit_code IS NOT NULL
                GROUP  BY 1
                ORDER  BY 2 DESC
                """
            )
            rows = cur.fetchall()

        missing = [r for r in rows if int(r[0]) not in code_to_name]
        if not missing:
            self.stdout.write(self.style.SUCCESS(
                f"Every unit_code in drawdown_daily resolves ({len(rows)} codes)."))
            return

        self.stdout.write(self.style.WARNING(
            f"{len(missing)} of {len(rows)} unit_codes resolve to no branch. "
            "Their drawdowns appear on no branch page."
        ))
        for code, count, gross in missing:
            self.stdout.write(f"  unit_code {int(code):<8} {int(count):>10,} rows   {float(gross):>20,.2f} gross")
