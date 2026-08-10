"""Branch-name normalisation.

Branch names arrive spelled inconsistently across sources — the DSR listing uses
short forms ("KOMAROCK"), the team-leader sheet uses "KOMAROCK BRANCH", HQ appears
as "HQ" / "HEAD OFFICE". That's why a raw ``distinct(branch)`` count differs page to
page. :func:`normalize_branch` collapses them to one canonical spelling so branches
group and count consistently.
"""

import re

_HQ = {"HQ", "HEAD OFFICE", "HEAD OFFICE BRANCH", "HEADOFFICE"}


def normalize_branch(raw) -> str:
    """Canonical branch name: UPPERCASE, single-spaced, always ``… BRANCH`` (HQ apart)."""
    if not raw:
        return ""
    s = re.sub(r"\s+", " ", str(raw).strip().upper())
    if not s:
        return ""
    if s in _HQ:
        return "HEAD OFFICE"
    if not s.endswith("BRANCH"):
        s = f"{s} BRANCH"
    return s
