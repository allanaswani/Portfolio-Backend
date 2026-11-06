"""One branch, several spellings, and which table uses which.

Measured on production, 6 Nov 2026. ``hf_customer.branch`` says HARAMBEE AVENUE BRANCH
while the staff rosters and the arrears mapping say HARAMBEE AVE BRANCH, and the ETLs
say GILL HOUSE. They are one branch. A manager filed under the roster's spelling
matched no customers, so every customer tile on their page read nought.

Two answers are therefore needed, and neither can stand in for the other:

* :func:`customer_branch` - what ``hf_customer.branch`` calls it;
* :func:`roster_branch` - what the rosters and ``services.arrears_managers`` call it.
"""

from .branch_codes import normalize_branch

#: (every spelling, as normalize_branch gives it), hf_customer's name, the rosters' name.
_SPELLED_DIFFERENTLY = (
    ({"HARAMBEE AVE", "HARAMBEE AVENUE", "HARAMBEE", "GILL HOUSE"},
     "HARAMBEE AVENUE BRANCH", "HARAMBEE AVE BRANCH"),
    ({"SAMEER", "SAMEER BUSINESS PARK"},
     "SAMEER BUSINESS PARK BRANCH", "SAMEER BRANCH"),
    ({"TRM", "THIKA ROAD MALL-TRM", "THIKA ROAD MALL"},
     "THIKA ROAD MALL-TRM BRANCH", "TRM BRANCH"),
    ({"HEAD OFFICE"}, "HEAD OFFICE", "HEAD OFFICE BRANCH"),
    ({"HF WHIZZ", "HFCB WHIZZ"}, "HFCB WHIZZ", "HF WHIZZ BRANCH"),
)

#: Branches whose name is the same everywhere: a bare "REHANI" on an account means this.
_SAME_EVERYWHERE = {
    "BURUBURU", "ELDORET", "EMBU", "HURLINGHAM", "KENYATTA", "KISUMU", "KITENGELA",
    "KOMAROCK", "MACHAKOS", "MERU", "MOMBASA", "NAIVASHA", "NAKURU", "NANYUKI", "NYALI",
    "NYERI", "REHANI", "RIVERROAD", "RONGAI", "THIKA", "WESTLANDS",
}


def _key(name):
    """Comparison key, also taking off the doubled word on "EMBU BRANCH BRANCH"."""
    key = normalize_branch(name)
    while key.endswith(" BRANCH"):
        key = key[: -len(" BRANCH")].strip()
    return key


def _resolve(name, position):
    key = _key(name)
    if not key:
        return ""
    for spellings, *names in _SPELLED_DIFFERENTLY:
        if key in spellings:
            return names[position]
    if key in _SAME_EVERYWHERE:
        return f"{key} BRANCH"
    return str(name).strip()


def customer_branch(name):
    """What ``hf_customer.branch`` calls this branch. An unknown name is left as given."""
    return _resolve(name, 0)


def roster_branch(name):
    """What the rosters and the arrears mapping call this branch."""
    return _resolve(name, 1)
