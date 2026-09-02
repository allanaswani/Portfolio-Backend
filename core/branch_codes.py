"""Branch name ⇄ branch/unit code resolution.

Several warehouse tables carry only a numeric branch code and no branch name at
all — ``drawdown_daily`` has ``unit_code`` and nothing else — while a user's
posting (``apps.portfolio.models.Profile.branch``) and every branch endpoint's
scope are a NAME such as ``"BURUBURU BRANCH"``. Scoping those tables to one
branch therefore needs a name → code map, and there is no branch dimension
table in the warehouse to read one from.

The branches DO carry codes; they are just spread across several tables. Three
sources are combined, in this order of weight:

1. ``drawdown`` — the ETL-built sibling of ``drawdown_daily``, which carries
   ``unit_code`` and ``branch`` **side by side**. This is the warehouse's own
   pairing for exactly the data being scoped, so it is the primary source.
2. the DMC staff rosters (``branch_final_employee_dmc_data``,
   ``branch_employee_dmc_data``), which pair ``brn_code`` with ``staff_branch``.
3. a static fallback transcribed from the branch CASE the CEO dashboard already
   uses (``apps.gceo_dashboard.views.BRANCH_CODE_CASE``), used ONLY for codes
   no live source knows.

``hf_customer.branch_code`` is deliberately NOT a source. It is not 1:1 with
``hf_customer.branch`` — measured on production, one branch's codes matched 32
branches and 99.6% of the book. See ``tests_branch_scoping.py``.

**Each code is assigned to exactly one branch**, by majority vote across the
live rows. Letting a code belong to two branches because a handful of rows are
mislabelled would quietly pull another branch's customers into this branch's
figures, which is the whole thing the scope exists to prevent.

Names are compared NORMALISED — upper-cased, whitespace-collapsed, a trailing
"BRANCH" dropped — because the same branch is spelled ``HEAD OFFICE`` in the
warehouse CASE and ``HEAD OFFICE BRANCH`` in ``Profile.BRANCH_CHOICES``.

Security note: ``branch_codes_for`` returns an EMPTY list for a branch it cannot
resolve. Callers must treat that as "match nothing", never as "no filter" — an
unresolvable branch must not fall back to the whole bank. See
``apps/branch_portfolio/tests_branch_ops.py``.
"""

import threading
import time

from django.core.cache import cache
from django.db import connection

# Transcribed 1:1 from apps/gceo_dashboard/views.py BRANCH_CODE_CASE. A gap
# filler only — a code any live table knows about is taken from the live table.
STATIC_CODE_TO_NAME = {
    230: "BURUBURU BRANCH",
    410: "ELDORET BRANCH",
    25:  "EMBU BRANCH",
    220: "HARAMBEE AVE BRANCH",
    100: "HEAD OFFICE",
    109: "HF WHIZZ",
    19:  "HURLINGHAM BRANCH",
    600: "KISUMU BRANCH",
    16:  "KITENGELA BRANCH",
    23:  "KOMAROCK BRANCH",
    24:  "MACHAKOS BRANCH",
    520: "MERU BRANCH",
    300: "MOMBASA BRANCH",
    17:  "NAIVASHA BRANCH",
    400: "NAKURU BRANCH",
    22:  "NANYUKI BRANCH",
    510: "NYERI BRANCH",
    200: "REHANI BRANCH",
    20:  "RIVERROAD BRANCH",
    250: "RONGAI BRANCH",
    270: "SAMEER BRANCH",
    500: "THIKA BRANCH",
    260: "TRM BRANCH",
    280: "WESTLANDS BRANCH",
}

# (table, code column, name column). Order is documentation only — the vote is
# by row count, not by position.
_LIVE_SOURCES = (
    ("drawdown", "unit_code", "branch"),
    ("branch_final_employee_dmc_data", "brn_code", "staff_branch"),
    ("branch_employee_dmc_data", "brn_code", "staff_branch"),
)

# The map is shared across gunicorn workers so a rebuild is not paid per worker,
# and memoised in-process so the common path touches neither cache nor database.
_SHARED_CACHE_KEY = "hf:branch_code_map:v2"
_SHARED_TTL_SECONDS = 3600
_LOCAL_TTL_SECONDS = 300

_lock = threading.Lock()
_local = {"built_at": 0.0, "name_to_codes": None, "code_to_name": None}


def normalize_branch(name) -> str:
    """Comparison key for a branch name: upper, whitespace-collapsed, no suffix.

    ``"  head office branch "`` and ``"HEAD OFFICE"`` both become
    ``"HEAD OFFICE"``.
    """
    if name is None:
        return ""
    collapsed = " ".join(str(name).split()).upper().strip()
    if collapsed.endswith(" BRANCH"):
        collapsed = collapsed[: -len(" BRANCH")].strip()
    return collapsed


def _collect_votes():
    """``{code: {normalised_name: row_count}}`` across every live source.

    Grouped in the database rather than pulled row by row: ``drawdown`` is a
    transaction table, and this must stay one cheap aggregate.
    """
    # Only query tables that exist — a test database mirrors the warehouse
    # rather than creating it, and production has known schema drift. Using
    # introspection (not a try/except around the SELECT) matters on Postgres:
    # a failed statement inside an atomic block poisons the whole transaction.
    try:
        existing = set(connection.introspection.table_names())
    except Exception:
        return {}

    votes: dict[int, dict[str, int]] = {}
    for table, code_col, name_col in _LIVE_SOURCES:
        if table not in existing:
            continue
        with connection.cursor() as cur:
            cur.execute(
                f"""
                SELECT {code_col}, {name_col}, COUNT(*) AS rows
                FROM   {table}
                WHERE  {code_col} IS NOT NULL
                  AND  {name_col} IS NOT NULL
                  AND  btrim({name_col}::text) <> ''
                GROUP  BY 1, 2
                """
            )
            rows = cur.fetchall()
        for raw_code, raw_name, count in rows:
            try:
                code = int(raw_code)
            except (TypeError, ValueError):
                continue
            key = normalize_branch(raw_name)
            if not key:
                continue
            tally = votes.setdefault(code, {})
            tally[key] = tally.get(key, 0) + int(count)
    return votes


def _build():
    votes = _collect_votes()

    # One winner per code. Ties break on the name so the map is deterministic
    # rather than dependent on dict ordering.
    code_to_name: dict[int, str] = {}
    for code, tally in votes.items():
        code_to_name[code] = max(tally.items(), key=lambda kv: (kv[1], kv[0]))[0]

    # Static entries fill gaps only; a code any live table knows keeps its
    # live answer.
    for code, name in STATIC_CODE_TO_NAME.items():
        code_to_name.setdefault(int(code), normalize_branch(name))

    name_to_codes: dict[str, set[int]] = {}
    for code, name in code_to_name.items():
        name_to_codes.setdefault(name, set()).add(code)

    return name_to_codes, code_to_name


def _maps():
    now = time.time()
    with _lock:
        fresh = (
            _local["name_to_codes"] is not None
            and now - _local["built_at"] <= _LOCAL_TTL_SECONDS
        )
        if fresh:
            return _local["name_to_codes"], _local["code_to_name"]

    cached = None
    try:
        cached = cache.get(_SHARED_CACHE_KEY)
    except Exception:
        # A cache backend outage must never take the branch pages down with it.
        cached = None

    if cached:
        name_to_codes = {k: set(v) for k, v in cached["name_to_codes"].items()}
        code_to_name = {int(k): v for k, v in cached["code_to_name"].items()}
    else:
        name_to_codes, code_to_name = _build()
        try:
            cache.set(
                _SHARED_CACHE_KEY,
                {
                    "name_to_codes": {k: sorted(v) for k, v in name_to_codes.items()},
                    "code_to_name": code_to_name,
                },
                _SHARED_TTL_SECONDS,
            )
        except Exception:
            pass

    with _lock:
        _local.update(
            built_at=time.time(), name_to_codes=name_to_codes, code_to_name=code_to_name
        )
    return name_to_codes, code_to_name


def branch_codes_for(branch_name) -> list[int]:
    """Every branch/unit code that belongs to ``branch_name``.

    Empty list when the name is blank or unknown — the caller MUST treat that as
    "match no rows", not "no branch filter".
    """
    key = normalize_branch(branch_name)
    if not key:
        return []
    name_to_codes, _ = _maps()
    return sorted(name_to_codes.get(key, set()))


def branch_name_for_code(code) -> str:
    """Display name for a branch/unit code, or the code as text if unknown."""
    try:
        key = int(code)
    except (TypeError, ValueError):
        return str(code or "")
    _, code_to_name = _maps()
    return code_to_name.get(key, str(key))


def resolved_map():
    """``{branch_name: [codes]}`` as currently resolved — for diagnostics.

    Used by ``manage.py branch_codes`` so the mapping can be inspected against
    the live database instead of guessed at.
    """
    name_to_codes, _ = _maps()
    return {name: sorted(codes) for name, codes in sorted(name_to_codes.items())}


def reset_cache():
    """Drop the memoised maps — for tests, and after a DMC/drawdown reload."""
    with _lock:
        _local.update(built_at=0.0, name_to_codes=None, code_to_name=None)
    try:
        cache.delete(_SHARED_CACHE_KEY)
    except Exception:
        pass
