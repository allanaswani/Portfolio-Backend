"""Trade Register reference-number generator.

The trade desk keeps a weekly register (Esther's "Weekly Trade Transactions"
workbook). Reference numbers there are typed by hand today; this module encodes
the convention reverse-engineered from every historical row so the tool can
generate them instead.

Three product families, three patterns (confirmed against the 2026 live data —
the desk switched the guarantee/export prefix from ``HFC/`` to ``HFCB/`` in 2026):

* guarantee  → ``HFCB/GTE/YYMMDD/NN``  — YYMMDD is the issue date, NN a per-day
                counter that resets each day (01, 02, …).
* export_lc  → ``HFCB/ELC/YYMMDD/NN``  — same date-based scheme.
* import_lc  → ``HF#####``             — a running sequential number (max + 1);
                these are the bank's LC numbers, so the tool only *suggests* the
                next one and the user can overwrite it with the real core number.

Amendments/extensions/settlements of an existing guarantee or export item reuse
the parent's reference with an action suffix (e.g. ``HFCB/GTE/260630/01 - EXT``)
rather than drawing a fresh number — see :func:`amend_reference`.

Every lookup scans BOTH the register table and the legacy ``trade_finance_data``
table so a generated number never collides with a historical one.
"""

from __future__ import annotations

import re
from datetime import date

FAMILY_GUARANTEE = "guarantee"
FAMILY_IMPORT_LC = "import_lc"
FAMILY_EXPORT_LC = "export_lc"

# Family → dated-reference prefix (2026 convention).
DATED_PREFIX = {
    FAMILY_GUARANTEE: "HFCB/GTE",
    FAMILY_EXPORT_LC: "HFCB/ELC",
}

# Action suffixes an amendment can carry, mirrored from the historical data.
AMENDMENT_SUFFIXES = [
    "EXT", "AMENDMENT", "SETTLEMENT", "CANCELLATION", "CALL UP",
    "PAYMENT", "ADVISING", "RELEASE ON INDEMNITY", "REDUCTION", "RETIREMENT",
]

_HF_SEQ_RE = re.compile(r"^HF(\d+)\b")


def _all_refs(prefix=None):
    """Every existing reference across the register and the legacy TF table.

    Imported lazily so this module stays import-safe (models aren't loaded at
    import time) and usable from migrations/tests.
    """
    from apps.staff_management.models import TradeFinanceData
    from .models import TradeRegisterEntry

    reg = TradeRegisterEntry.objects.all()
    tf = TradeFinanceData.objects.all()
    if prefix:
        reg = reg.filter(guarantee_ref__startswith=prefix)
        tf = tf.filter(guarantee_ref__startswith=prefix)
    refs = list(reg.values_list("guarantee_ref", flat=True))
    refs += list(tf.values_list("guarantee_ref", flat=True))
    return [r.strip() for r in refs if r]


def next_dated_ref(family: str, issue_date: date) -> str:
    """Next ``HFCB/{GTE|ELC}/YYMMDD/NN`` for the family on that issue date."""
    prefix = DATED_PREFIX.get(family)
    if not prefix:
        raise ValueError(f"{family!r} is not a dated-reference family")
    if not issue_date:
        raise ValueError("issue_date is required to generate a dated reference")

    base = f"{prefix}/{issue_date.strftime('%y%m%d')}/"
    max_nn = 0
    # Match the base and pull the NN even when an action suffix follows
    # (e.g. "HFCB/GTE/260630/01 - EXT" still counts as sequence 01 that day).
    pat = re.compile(rf"^{re.escape(base)}(\d+)")
    for ref in _all_refs(prefix=base):
        m = pat.match(ref)
        if m:
            max_nn = max(max_nn, int(m.group(1)))
    return f"{base}{max_nn + 1:02d}"


def next_import_lc_ref() -> str:
    """Next sequential ``HF#####`` (max existing + 1). A suggestion — editable."""
    max_num = 0
    for ref in _all_refs():
        m = _HF_SEQ_RE.match(ref)
        if m:
            try:
                max_num = max(max_num, int(m.group(1)))
            except ValueError:
                continue
    # Fall back to a sensible floor so the very first number looks right.
    return f"HF{max(max_num, 92000) + 1}"


def generate_reference(family: str, issue_date: date | None) -> str:
    """Generate a fresh reference for a *new* (non-amendment) entry."""
    if family == FAMILY_IMPORT_LC:
        return next_import_lc_ref()
    return next_dated_ref(family, issue_date)


def amend_reference(parent_ref: str, suffix: str) -> str:
    """Reference for an amendment/extension of an existing item.

    Reuses the parent's base reference with an action suffix, matching the
    desk's convention ("HFCB/GTE/260630/01 - EXT"). If the parent already
    carries a suffix, it is replaced rather than stacked.
    """
    base = re.split(r"\s+-\s+", parent_ref.strip(), maxsplit=1)[0]
    suffix = (suffix or "").strip().upper()
    return f"{base} - {suffix}" if suffix else base
