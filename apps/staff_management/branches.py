"""Branch-name normalisation.

Branch names arrive spelled inconsistently across sources — the DSR listing uses
short forms ("SAMEER"), the team-leader sheet uses the full name ("SAMEER BUSINESS
PARK"), HQ appears as "HQ" / "HEAD OFFICE". That's why a raw ``distinct(branch)``
count differs page to page, and why a DSR's branch won't match its team-leader
mapping. :func:`normalize_branch` collapses every spelling to one canonical name so
branches group, count, and match consistently.
"""

import re

_HQ = {"HQ", "HEAD OFFICE", "HEAD OFFICE BRANCH", "HEADOFFICE"}

# Variant spellings that must collapse to one canonical branch. Keys and values are
# the "core" name WITHOUT the trailing " BRANCH" (normalize re-appends it). Add a
# row here whenever the DSR data and the team-leader sheet name the same branch
# differently — every listed variant then matches the same mapping.
_ALIASES = {
    "SAMEER": "SAMEER BUSINESS PARK",
    "SAMEER PARK": "SAMEER BUSINESS PARK",
    "SAMEER BUSINESS": "SAMEER BUSINESS PARK",
    "HARAMBEE": "HARAMBEE AVENUE",
    "HARAMBEE AVE": "HARAMBEE AVENUE",
}


def normalize_branch(raw) -> str:
    """Canonical branch name: UPPERCASE, single-spaced, alias-resolved, always
    ``… BRANCH`` (HQ apart)."""
    if not raw:
        return ""
    # Uppercase, drop punctuation (e.g. "AVE." → "AVE"), collapse whitespace.
    s = re.sub(r"\s+", " ", re.sub(r"[.,]", " ", str(raw).upper())).strip()
    if not s:
        return ""
    if s in _HQ:
        return "HEAD OFFICE"
    # Reduce to the core name, resolve aliases, then re-append " BRANCH".
    core = s[:-6].strip() if s.endswith("BRANCH") else s
    if not core:
        return ""
    core = _ALIASES.get(core, core)
    return f"{core} BRANCH"
