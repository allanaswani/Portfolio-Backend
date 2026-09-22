"""One spelling per department, for the Staff & HR slide.

employee_table.department is free text typed by whoever prepared the HR upload,
and production currently holds 57 distinct values for a bank of 913 people. They
are not 57 departments. They are a smaller number of departments spelled several
ways each, plus a pile of branches recorded in the department column.

That matters beyond tidiness. The chart ranks departments by headcount and shows
only the top few, so a department split across three spellings is ranked three
times at a third of its size and can fall off the axis entirely while a
single-spelling department half its size stays on.

What this module will merge on its own, and what it refuses to:

    MERGED    case, spacing and punctuation                  safe
    MERGED    a trailing structural word - DEPARTMENT,       safe: it describes
              DEPT, DIVISION, UNIT, SECTION, TEAM            the shape of an org
                                                             unit, not which one
    MERGED    '&' and 'AND'                                  safe
    MERGED    the entity aliases the frontend already ships  already sanctioned
              (HFDI -> HFCB-Properties, HFC -> HFCB, ...)    in lib/formatters.ts
    MERGED    anything that names a branch -> Branch Network matched against the
                                                             real branch list
    MERGED    blank -> Unassigned                            safe

    NOT MERGED  anything else.

That last line is the important one. Whether 'ICT' and 'Technology, Service &
Operations' are one department is a question for HR, not for a guess made here.
Merging two real departments silently is a worse error than leaving one split,
because a split is visible on the chart and a bad merge is not. Names that look
related are reported by ``manage.py dept_audit`` as candidates for someone to
rule on, and only reach ALIASES once they have.
"""
import re

BRANCH_NETWORK = "Branch Network"
UNASSIGNED = "Unassigned"
OTHER = "Other"


# -- Entity aliases ----------------------------------------------------------
# Kept identical to ENTITY_BRAND_ALIASES in the frontend's lib/formatters.ts.
# That table exists because the group renamed its entities and the warehouse
# still carries the old names. It was already trusted for display, and is now
# also trusted for grouping: the frontend applied it AFTER taking the top 8, so
# HFDI and HFCB-Properties competed for a place as two separate departments and
# were only merged into one label once both were already on the chart.
#
# Change these two tables together or the chart and its labels drift apart.
ALIASES = {
    "HFDI": "HFCB-Properties",
    "HFBI": "HFCB-Bancassurance",
    "HF GROUP": "HFCB",
    "HF-GROUP": "HFCB",
    "HFGROUP": "HFCB",
    "HFC": "HFCB",
    "HFC MD": "HFCB MD",
    "HFF": "HFCB Foundation",
}


# -- Display spelling --------------------------------------------------------
# The exact spellings the CEO cost deck uses, so the staff chart and the cost
# chart name the same department the same way. Anything not listed is
# title-cased with acronyms left in capitals.
PREFERRED = [
    "ICT", "RETAIL", "FINANCE", "HFCB MD", "RISK", "AUDIT", "FPEAL",
    "HFCB Foundation", "HFCB-Bancassurance", "HEAD OFFICE", "CREDIT",
    "STRATEGY", "LEGAL", "TREASURY", "HFCB", "MARKETING", "HR",
    "HFCB-Properties",
]

ACRONYMS = {
    "HR", "ICT", "IT", "MD", "CEO", "COO", "CFO", "HFCB", "HFDI", "HFBI",
    "HFC", "HFF", "SME", "NPL", "AML", "KYC", "PR", "MIS", "BI", "FPEAL",
}

# Words that say what KIND of unit this is rather than which unit it is.
_STRUCTURAL = (
    "DEPARTMENT", "DEPARTMENTS", "DEPT.", "DEPT", "DIVISION", "DIVISIONS",
    "DIV.", "DIV", "UNIT", "UNITS", "SECTION", "SECTIONS", "TEAM", "TEAMS",
    "FUNCTION",
)


def _key(raw):
    """A comparison key: upper case, single spaces, no structural word.

    'Retail  Department', 'RETAIL DEPT' and 'retail' all reduce to 'RETAIL'.
    """
    s = str(raw or "").strip().upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^\w\s.,()'-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .,-")
    # Strip structural words from either end, repeatedly, so that something
    # like 'DEPARTMENT OF RISK UNIT' still reduces to 'RISK'.
    changed = True
    while changed and s:
        changed = False
        for word in _STRUCTURAL:
            for pattern in (r"\s+" + re.escape(word) + r"$",
                            r"^" + re.escape(word) + r"\s+"):
                new = re.sub(pattern, "", s).strip(" .,-")
                if new and new != s:
                    s, changed = new, True
        for pattern in (r"^THE\s+", r"^OFFICE OF\s+", r"^OF\s+"):
            new = re.sub(pattern, "", s).strip(" .,-")
            if new and new != s:
                s, changed = new, True
    return re.sub(r"\s+", " ", s).strip()


def compare_key(raw):
    """The reduced form two names are compared on. Public for dept_audit."""
    return _key(raw)


_BRANCH_KEYS = None


def _branch_keys():
    """Every branch name the bank has, as comparison keys.

    Imported lazily: core.date_utils builds this by parsing a large SQL CASE,
    and nothing here should pay for that at import time.
    """
    global _BRANCH_KEYS
    if _BRANCH_KEYS is None:
        from core.date_utils import BRANCH_ALIASES, BRANCH_BY_CODE
        keys = set()
        for name in list(BRANCH_BY_CODE.values()) + list(BRANCH_ALIASES):
            k = _key(name)
            keys.add(k)
            # 'KITENGELA BRANCH' is also written plain 'KITENGELA'.
            keys.add(re.sub(r"\s+BRANCH$", "", k).strip())
        _BRANCH_KEYS = {k for k in keys if k}
    return _BRANCH_KEYS


def is_branch(raw):
    """True when a department value actually names a branch.

    Two tests, because the branch list is not guaranteed complete: the value
    matches a known branch, or it ends in the word BRANCH. The second catches
    branches opened since core.date_utils was last updated.
    """
    k = _key(raw)
    if not k:
        return False
    return k in _branch_keys() or k.endswith(" BRANCH") or k == "BRANCH"


def _display(key):
    """How a canonical key is spelled on screen."""
    for name in PREFERRED:
        if _key(name) == key:
            return name
    words = []
    for word in key.split():
        bare = word.strip("().,-")
        words.append(word if bare in ACRONYMS else word.capitalize())
    return " ".join(words)


_ALIAS_KEYS = None
_PREFERRED_KEYS = None


def canonical(raw):
    """The one name this department is counted and displayed under."""
    global _ALIAS_KEYS, _PREFERRED_KEYS
    key = _key(raw)
    if not key:
        return UNASSIGNED
    # A name the bank's own cost deck calls a department IS a department, even
    # when a branch shares it. 'HEAD OFFICE' is both branch code 100 and a line
    # in the CEO cost deck, and the branch test used to win - which quietly
    # moved 7 people off the department chart and into Branch Network.
    if _PREFERRED_KEYS is None:
        _PREFERRED_KEYS = {_key(n) for n in PREFERRED}
    if key not in _PREFERRED_KEYS and is_branch(raw):
        return BRANCH_NETWORK
    # Aliases are matched on the reduced key, so 'HFDI Department' resolves too.
    if _ALIAS_KEYS is None:
        _ALIAS_KEYS = {_key(k): v for k, v in ALIASES.items()}
    aliased = _ALIAS_KEYS.get(key)
    if aliased:
        key = _key(aliased)
    return _display(key)


def roll_up(pairs, top=None):
    """[(department, person_key), ...] -> [{'department', 'count'}, ...] desc.

    Counts each person once per department. Pass ``top`` to fold everything
    past that rank into a single 'Other' row, so the bars still add up to the
    headcount instead of the chart quietly showing a subset of the bank.
    """
    buckets = {}
    for dept, person in pairs:
        buckets.setdefault(canonical(dept), set()).add(person)

    rows = sorted(
        ({"department": d, "count": len(p)} for d, p in buckets.items()),
        key=lambda r: (-r["count"], r["department"]),
    )
    if not top or len(rows) <= top:
        return rows

    head, tail = rows[:top], rows[top:]
    tail_names = {r["department"] for r in tail}
    # Somebody recorded under two different tail departments is one person in
    # Other, not two - which is why this counts people rather than summing the
    # rows it just discarded.
    spill = {person for dept, person in pairs if canonical(dept) in tail_names}
    head.append({
        "department": OTHER,
        "count": len(spill),
        "departments": len(tail),
    })
    return head
