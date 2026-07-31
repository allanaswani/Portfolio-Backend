"""
Shared logic for loading the diaspora leads master CSV and assigning each lead to
its RM. Used by both the `load_diaspora_leads` management command and the admin
browser-upload endpoint (apps.mortgages.views.DiasporaLeadUploadView) so the two
paths behave identically.

The RMs ALREADY have logins — this never creates accounts. It resolves each RM to
their existing User, grants `mortgage_officer` (so the Officer module shows for
them), and assigns leads. If any RM can't be resolved to exactly one account it
refuses to load, so nothing is mis-assigned. Lead visibility is scoped by
Lead.assigned_to (see apps.mortgages.views._scoped_leads).
"""

import copy

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q

from .models import Lead, LeadSource

User = get_user_model()

OFFICER_GROUP = "mortgage_officer"
SOURCE_NAME = "Diaspora Roadshow 2025"

# Canonical RM key -> how to find their EXISTING account.
#   match      : the RM's exact username (an exact username/email wins over any
#                icontains fallback), so resolution is unambiguous. Override per-run
#                with --map / the upload form if an account is ever renamed.
#   sales_code : optional; written to Profile.sales_code. "" = leave as-is.
# NOTE on the two "antony.opitso" entries: the CSV author wrote this one RM (full
# name *Antony Opitso*, DIASPORA) as both "Opitso" and "Antony". Both labels
# intentionally point at the same login — confirmed with the business.
DEFAULT_ROSTER = {
    "Hilda":   {"match": "hilda.chemutai", "sales_code": ""},   # the NA / unallocated bucket
    "Beldine": {"match": "beldine.otieno", "sales_code": ""},
    "Doris":   {"match": "doris.njuki",    "sales_code": ""},
    "Mark":    {"match": "mark.waiganjo",  "sales_code": ""},
    "Opitso":  {"match": "antony.opitso",  "sales_code": ""},
    "Antony":  {"match": "antony.opitso",  "sales_code": ""},   # same person as Opitso
    "Edward":  {"match": "edward.kosgei",  "sales_code": ""},
}

# CSV `RM` value (case-insensitive, trimmed) -> canonical RM key.
# NA / blank are the unallocated bucket and go to Hilda (per the business).
ALIASES = {
    "na": "Hilda",
    "": "Hilda",
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

REQUIRED_COLUMNS = {"name", "country", "email", "phone_number", "engagement_location", "RM"}


class DiasporaLoadError(Exception):
    """Raised for a caller-fixable problem (bad columns, unmapped RMs, unresolved
    accounts). Carries a human-readable message; safe to surface to the operator."""


def build_roster(overrides=None):
    """Fresh roster copy with per-run `match` overrides applied. `overrides` is a
    dict {RM key: identifier}; each replaces that RM's search term."""
    roster = copy.deepcopy(DEFAULT_ROSTER)
    for key, ident in (overrides or {}).items():
        if key not in roster:
            raise DiasporaLoadError(f"Unknown RM {key!r}; known: {sorted(roster)}")
        roster[key]["match"] = str(ident).strip()
    return roster


def rm_key(raw):
    return ALIASES.get((raw or "").strip().lower())


def clean_phone(raw):
    # CSV stores phones as text with a leading apostrophe to preserve digits.
    return (raw or "").replace("'", "").strip()


def candidates(term):
    """Users matching `term` — exact username/email first, else name/handle icontains."""
    exact = User.objects.filter(Q(username__iexact=term) | Q(email__iexact=term))
    if exact.exists():
        return list(exact)
    return list(User.objects.filter(
        Q(username__icontains=term) | Q(email__icontains=term)
        | Q(first_name__icontains=term) | Q(last_name__icontains=term)))


def probe(roster=None):
    """Return {RM key: [candidate users]} for operator inspection."""
    roster = roster or DEFAULT_ROSTER
    return {key: candidates(meta["match"]) for key, meta in roster.items()}


def resolve_users(roster):
    """Map each RM key -> unique User, or raise DiasporaLoadError listing problems."""
    users, problems = {}, []
    for key, meta in roster.items():
        cands = candidates(meta["match"])
        if len(cands) == 1:
            users[key] = cands[0]
        elif not cands:
            problems.append(f"{key}: no account matches {meta['match']!r}")
        else:
            listed = ", ".join(f"{u.username}({u.id})" for u in cands)
            problems.append(f"{key}: {len(cands)} accounts match {meta['match']!r} -> {listed}")
    if problems:
        raise DiasporaLoadError(
            "Could not resolve every RM to exactly one account. Pin the exact "
            "username/email per RM and retry. Problems:\n  " + "\n  ".join(problems))
    return users


def validate_rows(rows):
    """Check required columns exist and every RM value is mappable. Raises on error."""
    if not rows:
        raise DiasporaLoadError("CSV has no data rows.")
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise DiasporaLoadError(f"CSV missing columns: {sorted(missing)}")
    unmapped = sorted({(r.get("RM") or "").strip()
                       for r in rows if rm_key(r.get("RM")) is None})
    if unmapped:
        raise DiasporaLoadError(
            "Unmapped RM values in CSV (extend ALIASES): "
            + ", ".join(repr(u) for u in unmapped))


def run_load(rows, overrides=None, dry_run=False):
    """Resolve RMs, grant the officer group, and create/update leads from `rows`.

    Returns a summary dict:
      {created, updated, rows, dry_run, per_rm, resolved{key: username}}
    Raises DiasporaLoadError for any caller-fixable problem. Atomic — a dry run is
    rolled back, so nothing is written.
    """
    validate_rows(rows)
    roster = build_roster(overrides)

    with transaction.atomic():
        group, _ = Group.objects.get_or_create(name=OFFICER_GROUP)
        users = resolve_users(roster)

        for key, user in users.items():
            user.groups.add(group)
            sc = roster[key].get("sales_code")
            prof = getattr(user, "profile", None)
            if prof is not None and sc and prof.sales_code != sc:
                prof.sales_code = sc
                prof.save(update_fields=["sales_code"])

        source, _ = LeadSource.objects.get_or_create(
            name=SOURCE_NAME, defaults={"description": "Diaspora roadshow RSVP leads."})

        created_n = updated_n = 0
        per_rm = {k: 0 for k in roster}
        for r in rows:
            key = rm_key(r.get("RM"))
            owner = users[key]
            per_rm[key] += 1

            full_name = (r.get("name") or "").strip()
            email = (r.get("email") or "").strip()
            phone = clean_phone(r.get("phone_number"))
            country = (r.get("country") or "").strip()
            where = (r.get("engagement_location") or "").strip()
            location = " — ".join(x for x in (country, where) if x)[:200]

            # Natural key = (full_name, phone) within this campaign source. Email is
            # NOT usable here: many rows carry the placeholder "invalid" and a couple
            # of real emails are shared by different people, so email-keying would
            # collapse distinct leads and mis-assign them.
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
                if changed and not dry_run:
                    existing.save(update_fields=changed)
                if changed:
                    updated_n += 1
                continue

            if not dry_run:
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

        summary = {
            "created": created_n,
            "updated": updated_n,
            "rows": len(rows),
            "dry_run": dry_run,
            "per_rm": per_rm,
            "resolved": {k: u.username for k, u in users.items()},
        }
        if dry_run:
            transaction.set_rollback(True)
        return summary
