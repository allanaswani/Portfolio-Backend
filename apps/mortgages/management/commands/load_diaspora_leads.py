"""
Load the diaspora leads master CSV into the Mortgages Leads pipeline, assigning
each lead to its RM so the RM sees only their own leads (Lead.assigned_to is the
login the leads list is scoped to — see apps.mortgages.views._scoped_leads).

The RMs ALREADY have logins. This command does NOT create accounts — it looks up
each RM's existing User, grants them the `mortgage_officer` group (so the Mortgages
Officer module/nav shows for them), and assigns their leads. It refuses to run if
any RM can't be resolved to exactly one account, so nothing is mis-assigned.

What it does (idempotent — safe to re-run):
  1. Resolves each RM in ROSTER to their existing User (unique match required).
  2. Adds the `mortgage_officer` group + sets Profile.sales_code for each.
  3. Ensures a LeadSource row for the campaign.
  4. Reads the CSV, maps the free-text `RM` column to a roster RM, and creates
     (or updates) one Lead per row assigned to that RM.

RM mapping applied to the CSV `RM` column:
    NA                        -> Beldine   (unallocated bucket, per business)
    Previously allocated-X    -> X         (keep current owner)
    <name>                    -> that RM

FIRST: discover the real usernames on the server, then put them in ROSTER["match"]:
    docker cp "diaspora_leads_master_clean 1.csv" hf-backend:/tmp/leads.csv
    docker exec hf-backend python manage.py load_diaspora_leads --csv /tmp/leads.csv --probe
  -> lists candidate accounts per RM. Edit ROSTER so each "match" is the EXACT
     username (or email) of that RM. Then:
    docker exec hf-backend python manage.py load_diaspora_leads --csv /tmp/leads.csv --dry-run
    docker exec hf-backend python manage.py load_diaspora_leads --csv /tmp/leads.csv
"""

import csv

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.mortgages.models import Lead, LeadSource

User = get_user_model()

OFFICER_GROUP = "mortgage_officer"
SOURCE_NAME = "Diaspora Roadshow 2025"

# ── RM roster ────────────────────────────────────────────────────────────────
# Canonical RM key -> how to find their EXISTING account.
#   "match"      : a search term used to locate the account. Run --probe first;
#                  once you know the exact username/email, put it here so the
#                  lookup is unambiguous (exact username or email wins).
#   "sales_code" : optional; written to the RM's Profile.sales_code. Leave "" to skip.
ROSTER = {
    "Beldine": {"match": "beldine", "sales_code": ""},
    "Doris":   {"match": "doris",   "sales_code": ""},
    "Mark":    {"match": "mark",    "sales_code": ""},
    "Opitso":  {"match": "opitso",  "sales_code": ""},
    "Edward":  {"match": "edward",  "sales_code": ""},
    "Antony":  {"match": "antony",  "sales_code": ""},
}

# CSV `RM` value (case-insensitive, trimmed) -> canonical RM key.
ALIASES = {
    "na": "Beldine",
    "": "Beldine",
    "beldine": "Beldine",
    "doris": "Doris",
    "mark": "Mark",
    "opitso": "Opitso",
    "edward": "Edward",
    "antony": "Antony",
    "previously allocated-doris": "Doris",
    "previously allocated-mark": "Mark",
    "previously allocated-opitso": "Opitso",
}


def _clean_phone(raw):
    # CSV stores phones as text with a leading apostrophe to preserve digits.
    return (raw or "").replace("'", "").strip()


def _rm_key(raw):
    key = (raw or "").strip().lower()
    return ALIASES.get(key)


def _candidates(term):
    """Users whose username/email/name matches `term` (exact username/email first)."""
    exact = User.objects.filter(Q(username__iexact=term) | Q(email__iexact=term))
    if exact.exists():
        return list(exact)
    return list(User.objects.filter(
        Q(username__icontains=term) | Q(email__icontains=term)
        | Q(first_name__icontains=term) | Q(last_name__icontains=term)))


class Command(BaseCommand):
    help = "Load the diaspora leads CSV and assign each lead to its existing RM login."

    def add_arguments(self, parser):
        parser.add_argument("--csv", help="Path to the diaspora leads CSV (not needed for --probe).")
        parser.add_argument("--probe", action="store_true",
                            help="List candidate accounts for each RM and exit (no writes).")
        parser.add_argument("--map", action="append", default=[], metavar="RM=IDENTIFIER",
                            help="Override an RM's account lookup at runtime, e.g. "
                                 "--map Beldine=beldine.otieno (repeatable). Wins over ROSTER.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and report, but write nothing.")

    def _apply_overrides(self, mappings):
        for item in mappings:
            if "=" not in item:
                raise CommandError(f"--map expects RM=IDENTIFIER, got {item!r}")
            key, ident = item.split("=", 1)
            key, ident = key.strip(), ident.strip()
            if key not in ROSTER:
                raise CommandError(f"--map key {key!r} is not a known RM {list(ROSTER)}")
            ROSTER[key]["match"] = ident

    # ── account resolution ───────────────────────────────────────────────────
    def _probe(self):
        self.stdout.write("Candidate accounts per RM (id · username · email · name):")
        for key, meta in ROSTER.items():
            cands = _candidates(meta["match"])
            self.stdout.write(f"\n  {key}  (match={meta['match']!r}):")
            if not cands:
                self.stdout.write(self.style.WARNING("    (no matches)"))
            for u in cands:
                name = f"{u.first_name} {u.last_name}".strip()
                self.stdout.write(f"    {u.id} · {u.username} · {u.email or '-'} · {name or '-'}")

    def _resolve_users(self):
        users, problems = {}, []
        for key, meta in ROSTER.items():
            cands = _candidates(meta["match"])
            if len(cands) == 1:
                users[key] = cands[0]
            elif not cands:
                problems.append(f"  {key}: no account matches {meta['match']!r}")
            else:
                listed = ", ".join(f"{u.username}({u.id})" for u in cands)
                problems.append(f"  {key}: {len(cands)} accounts match {meta['match']!r} -> {listed}")
        if problems:
            raise CommandError(
                "Could not resolve every RM to exactly one account. Fix ROSTER['match'] "
                "to the exact username/email (use --probe), then retry:\n" + "\n".join(problems))
        return users

    def handle(self, *args, **opts):
        self._apply_overrides(opts["map"])
        if opts["probe"]:
            self._probe()
            return

        path = opts.get("csv")
        if not path:
            raise CommandError("--csv is required (or use --probe to discover usernames).")
        dry = opts["dry_run"]

        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except FileNotFoundError:
            raise CommandError(f"CSV not found: {path}")
        if not rows:
            raise CommandError("CSV has no data rows.")

        required = {"name", "country", "email", "phone_number", "engagement_location", "RM"}
        missing_cols = required - set(rows[0].keys())
        if missing_cols:
            raise CommandError(f"CSV missing columns: {sorted(missing_cols)}")

        # Report unmapped RM values up front (fail loudly rather than mis-assign).
        unmapped = sorted({(r.get("RM") or "").strip()
                           for r in rows if _rm_key(r.get("RM")) is None})
        if unmapped:
            raise CommandError(
                "Unmapped RM values in CSV (add them to ALIASES): "
                + ", ".join(repr(u) for u in unmapped))

        with transaction.atomic():
            group, _ = Group.objects.get_or_create(name=OFFICER_GROUP)

            # 1) Resolve existing RM logins and grant the officer view.
            users = self._resolve_users()
            for key, user in users.items():
                user.groups.add(group)
                self.stdout.write(self.style.SUCCESS(
                    f"  = {key} -> '{user.username}' (id {user.id}); +{OFFICER_GROUP}"))
                sc = ROSTER[key].get("sales_code")
                prof = getattr(user, "profile", None)
                if prof is not None and sc and prof.sales_code != sc:
                    prof.sales_code = sc
                    prof.save(update_fields=["sales_code"])

            # 2) Ensure the campaign source.
            source, _ = LeadSource.objects.get_or_create(
                name=SOURCE_NAME, defaults={"description": "Diaspora roadshow RSVP leads."})

            # 3) Load leads.
            created_n = updated_n = 0
            per_rm = {k: 0 for k in ROSTER}
            for r in rows:
                key = _rm_key(r.get("RM"))
                owner = users[key]
                per_rm[key] += 1

                full_name = (r.get("name") or "").strip()
                email = (r.get("email") or "").strip()
                phone = _clean_phone(r.get("phone_number"))
                country = (r.get("country") or "").strip()
                where = (r.get("engagement_location") or "").strip()
                location = " — ".join(x for x in (country, where) if x)[:200]

                # Natural key = (full_name, phone) within this campaign source. Email is
                # NOT usable in this data: many rows carry the placeholder "invalid" and a
                # couple of real emails are shared by different people on different RMs, so
                # keying on email would collapse distinct leads and mis-assign them.
                # Scoping to `source` prevents attaching to unrelated pre-existing leads.
                existing = Lead.objects.filter(
                    full_name__iexact=full_name, phone=phone, source=source).first()

                if existing:
                    changed = []
                    if existing.assigned_to_id != owner.id:
                        existing.assigned_to = owner; changed.append("assigned_to")
                    if email and existing.email != email:
                        existing.email = email; changed.append("email")
                    if location and existing.location != location:
                        existing.location = location; changed.append("location")
                    if changed and not dry:
                        existing.save(update_fields=changed)
                    if changed:
                        updated_n += 1
                    continue

                if not dry:
                    Lead.objects.create(
                        full_name=full_name or "(no name)",
                        phone=phone,
                        email=email,
                        location=location,
                        source=source,
                        assigned_to=owner,
                        status="new",
                    )
                created_n += 1

            self.stdout.write("")
            self.stdout.write("Per-RM lead counts:")
            for key in ROSTER:
                self.stdout.write(f"    {key:10} {per_rm[key]:4}")
            summary = f"{created_n} leads created, {updated_n} updated, {len(rows)} rows read."
            if dry:
                self.stdout.write(self.style.WARNING(f"DRY RUN — nothing written. {summary}"))
                transaction.set_rollback(True)
            else:
                self.stdout.write(self.style.SUCCESS(f"Done. {summary}"))
