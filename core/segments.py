"""Canonical banking-segment matching.

The platform carries the SAME segment under two different vocabularies, and a
Team Leader's dashboard reads both:

* ``daily_balance_movement.customer_segment`` / ``loan_daily_balance_movement``
  hold RAW core-banking segments ('SMALL ENTERPRISES', 'MEDIUM ENTERPRISES').
  The trend and movement queries map these through the CASE in
  ``apps/tl_portfolio/legacy_queries.py`` before filtering, so a TL whose
  ``profile.segment`` is 'BUSINESS BANKING' matches.
* ``hf_customer.banking_segment`` holds a THIRD spelling — measured on prod
  2026-08-24, the 33,336 customers whose ``hf_customer.segment`` is
  SMALL/MEDIUM ENTERPRISES are stored as **'SME'**, never 'BUSINESS BANKING'.

So every tile reading the movement tables rendered real figures while every
tile reading ``hf_customer.banking_segment = 'BUSINESS BANKING'`` returned zero.
Case-folding does not help: on prod both the exact and the LOWER(TRIM(...))
match counted 0. It is a vocabulary difference, not a formatting one.

``portfolio_profile.segment`` is itself mixed — prod has 54 users on
'BUSINESS BANKING' AND 54 on 'SME', plus 'PRIVATE', 'LARGE ENTERPRISES',
'STANDARD' and 'SMALL ENTERPRISES' — so the same query must satisfy a TL who
is filed under either spelling.

Matching therefore goes through a synonym set rather than an equality test.
Every value is compared UPPER/BTRIM-folded, and a segment with no known
synonyms falls back to matching itself, so a vocabulary this table does not
know about behaves exactly as it does today.
"""

# canonical label -> every spelling that means the same segment. Sources: the
# CASE mappings already blessed in tl_portfolio/legacy_queries.py (SEG_CASE and
# SEG_CASE_MONTHLY) plus the hf_customer.banking_segment values measured on
# prod. Keep every entry UPPER-CASE — lookups fold before comparing.
SEGMENT_SYNONYMS = {
    "BUSINESS BANKING": ("SME", "SMALL ENTERPRISES", "MEDIUM ENTERPRISES"),
    "COMMERCIAL": ("LARGE ENTERPRISES",),
    "PB": ("MASS", "STANDARD"),
    "ULTIMATE": ("PRIVATE",),
    "DIASPORA": ("NON RESIDENT KENYANS",),
    "FINANCIAL INSTITUTIONS": ("GLOBAL MARKETS",),
    "INSTITUTIONAL BANKING": ("IB NON PUBLIC SECTOR",),
}

# reverse index: any spelling -> canonical label
_TO_CANONICAL = {}
for _canonical, _aliases in SEGMENT_SYNONYMS.items():
    _TO_CANONICAL[_canonical] = _canonical
    for _alias in _aliases:
        _TO_CANONICAL[_alias] = _canonical


def _fold(value) -> str:
    return str(value or "").strip().upper()


def canonical_segment(value) -> str:
    """Fold any spelling of a segment to its canonical label.

    Unknown values are returned folded but otherwise untouched, so segments this
    module has never heard of keep matching themselves.
    """
    folded = _fold(value)
    return _TO_CANONICAL.get(folded, folded)


def segment_synonyms(value):
    """Every spelling that means the same segment as ``value``, UPPER-folded.

    Always includes the caller's own value, so an unmapped segment still
    matches itself exactly.
    """
    folded = _fold(value)
    if not folded:
        return []
    canonical = _TO_CANONICAL.get(folded, folded)
    spellings = {folded, canonical}
    spellings.update(SEGMENT_SYNONYMS.get(canonical, ()))
    return sorted(spellings)


def segment_where_sql(alias="hf_customer",
                      banking_segment_col="banking_segment",
                      segment_col="segment") -> str:
    """SQL predicate matching a customer row to a TL's segment.

    Checks BOTH segment columns on hf_customer, because prod populates them
    from different vocabularies and either one may carry the usable value.
    Takes TWO params, both the list from :func:`segment_synonyms` — pass
    ``segment_params(profile_segment)``.
    """
    prefix = f"{alias}." if alias else ""
    return (
        f"(UPPER(BTRIM({prefix}{banking_segment_col})) = ANY(%s)"
        f" OR UPPER(BTRIM({prefix}{segment_col})) = ANY(%s))"
    )


def segment_params(value):
    """The two params :func:`segment_where_sql` expects, in order."""
    synonyms = segment_synonyms(value)
    return [synonyms, synonyms]


def segment_q(value):
    """ORM equivalent of :func:`segment_where_sql` for HfCustomer querysets."""
    from django.db.models import Q

    synonyms = segment_synonyms(value)
    if not synonyms:
        return Q(pk__in=[])
    return Q(banking_segment__in=synonyms) | Q(segment__in=synonyms)
