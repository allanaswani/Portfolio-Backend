"""Branch name ⇄ branch/unit code resolution.

Several warehouse tables carry only a numeric branch code and no branch name at
all — ``drawdown_daily`` has ``unit_code`` and nothing else — while a user's
posting (``apps.portfolio.models.Profile.branch``) and every branch endpoint's
scope are a NAME such as ``"BURUBURU BRANCH"``. Scoping those tables to one
branch therefore needs a name → code map, and there is no branch dimension
table in the warehouse to read one from.

Two sources are unioned:

* the live DMC staff tables (``branch_final_employee_dmc_data`` and
  ``branch_employee_dmc_data``), which carry ``brn_code`` next to
  ``staff_branch``. This is the bank's own current pairing and it self-heals
  when a branch is renamed or a new one opens;
* a static fallback transcribed from the branch CASE the CEO dashboard already
  uses (``apps.gceo_dashboard.views.BRANCH_CODE_CASE``), so a branch that has
  no staff row still resolves.

Names are compared NORMALISED — upper-cased, whitespace-collapsed, a trailing
"BRANCH" dropped — because the same branch is spelled ``HEAD OFFICE`` in the
warehouse CASE and ``HEAD OFFICE BRANCH`` in ``Profile.BRANCH_CHOICES``.

Security note: ``branch_codes_for`` returns an EMPTY list for a branch it cannot
resolve. Callers must treat that as "match nothing", never as "no filter" — an
unresolvable branch must not fall back to the whole bank. See
``apps/branch_portfolio/tests_drawdown_scoping.py``.
"""

import threading
import time

from django.db import connection

# Transcribed 1:1 from apps/gceo_dashboard/views.py BRANCH_CODE_CASE. Kept as a
# fallback only — the DMC tables above are the live source.
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

_DMC_TABLES = ("branch_final_employee_dmc_data", "branch_employee_dmc_data")

_CACHE_TTL_SECONDS = 300
_lock = threading.Lock()
_cache = {"built_at": 0.0, "name_to_codes": None, "code_to_name": None}


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


def _build():
    name_to_codes: dict[str, set[int]] = {}
    code_to_name: dict[int, str] = {}

    for code, name in STATIC_CODE_TO_NAME.items():
        name_to_codes.setdefault(normalize_branch(name), set()).add(int(code))
        code_to_name.setdefault(int(code), name)

    # Only query tables that actually exist — a test database mirrors the
    # warehouse rather than creating it, and production has schema drift. Using
    # introspection (not a try/except around the SELECT) matters on Postgres:
    # a failed statement inside an atomic block poisons the whole transaction.
    try:
        existing = set(connection.introspection.table_names())
    except Exception:
        existing = set()

    for table in _DMC_TABLES:
        if table not in existing:
            continue
        with connection.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT brn_code, staff_branch
                FROM   {table}
                WHERE  brn_code IS NOT NULL
                  AND  staff_branch IS NOT NULL
                  AND  btrim(staff_branch) <> ''
                """
            )
            rows = cur.fetchall()
        for raw_code, raw_name in rows:
            try:
                code = int(raw_code)
            except (TypeError, ValueError):
                continue
            key = normalize_branch(raw_name)
            if not key:
                continue
            name_to_codes.setdefault(key, set()).add(code)
            code_to_name.setdefault(code, " ".join(str(raw_name).split()).upper())

    return name_to_codes, code_to_name


def _maps(refresh: bool = False):
    now = time.time()
    with _lock:
        stale = (
            refresh
            or _cache["name_to_codes"] is None
            or now - _cache["built_at"] > _CACHE_TTL_SECONDS
        )
        if stale:
            name_to_codes, code_to_name = _build()
            _cache.update(
                built_at=now, name_to_codes=name_to_codes, code_to_name=code_to_name
            )
        return _cache["name_to_codes"], _cache["code_to_name"]


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


def reset_cache():
    """Drop the memoised maps — for tests and for the admin after a DMC upload."""
    with _lock:
        _cache.update(built_at=0.0, name_to_codes=None, code_to_name=None)
