"""
Load the diaspora leads master CSV and assign each lead to its existing RM login.

Thin CLI wrapper around apps.mortgages.diaspora (the same logic backs the admin
browser-upload endpoint). Does NOT create accounts — it resolves each RM to their
existing User, grants `mortgage_officer`, and assigns leads. RM mapping:
    NA -> Hilda (Chemutai)  |  "Previously allocated-X" -> X  |  <name> -> that RM

Discover usernames first (no CSV needed):
    docker exec hf-backend python manage.py load_diaspora_leads --probe
Then dry-run and load (pin ambiguous RMs with --map RM=username):
    docker cp /tmp/leads.csv hf-backend:/tmp/leads.csv
    docker exec hf-backend python manage.py load_diaspora_leads --csv /tmp/leads.csv --dry-run
    docker exec hf-backend python manage.py load_diaspora_leads --csv /tmp/leads.csv
"""

import csv

from django.core.management.base import BaseCommand, CommandError

from apps.mortgages import diaspora


class Command(BaseCommand):
    help = "Load the diaspora leads CSV and assign each lead to its existing RM login."

    def add_arguments(self, parser):
        parser.add_argument("--csv", help="Path to the diaspora leads CSV (not needed for --probe).")
        parser.add_argument("--probe", action="store_true",
                            help="List candidate accounts for each RM and exit (no writes).")
        parser.add_argument("--map", action="append", default=[], metavar="RM=IDENTIFIER",
                            help="Override an RM's account lookup, e.g. --map Beldine=beldine.otieno "
                                 "(repeatable).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and report, but write nothing.")

    def _overrides(self, mappings):
        out = {}
        for item in mappings:
            if "=" not in item:
                raise CommandError(f"--map expects RM=IDENTIFIER, got {item!r}")
            key, ident = item.split("=", 1)
            out[key.strip()] = ident.strip()
        return out

    def handle(self, *args, **opts):
        overrides = self._overrides(opts["map"])

        if opts["probe"]:
            try:
                roster = diaspora.build_roster(overrides)
            except diaspora.DiasporaLoadError as e:
                raise CommandError(str(e))
            self.stdout.write("Candidate accounts per RM (id · username · email · name):")
            for key, cands in diaspora.probe(roster).items():
                self.stdout.write(f"\n  {key}  (match={roster[key]['match']!r}):")
                if not cands:
                    self.stdout.write(self.style.WARNING("    (no matches)"))
                for u in cands:
                    name = f"{u.first_name} {u.last_name}".strip()
                    self.stdout.write(f"    {u.id} · {u.username} · {u.email or '-'} · {name or '-'}")
            return

        path = opts.get("csv")
        if not path:
            raise CommandError("--csv is required (or use --probe to discover usernames).")
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except FileNotFoundError:
            raise CommandError(f"CSV not found: {path}")

        try:
            summary = diaspora.run_load(rows, overrides=overrides, dry_run=opts["dry_run"])
        except diaspora.DiasporaLoadError as e:
            raise CommandError(str(e))

        for key, username in summary["resolved"].items():
            self.stdout.write(self.style.SUCCESS(f"  = {key} -> '{username}'  (+mortgage_officer)"))
        self.stdout.write("\nPer-RM lead counts:")
        for key, n in summary["per_rm"].items():
            self.stdout.write(f"    {key:10} {n:4}")
        msg = (f"{summary['created']} leads created, {summary['updated']} updated, "
               f"{summary['rows']} rows read.")
        if summary["dry_run"]:
            self.stdout.write(self.style.WARNING(f"DRY RUN — nothing written. {msg}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. {msg}"))
