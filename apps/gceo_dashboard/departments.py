"""Standard (canonical) department names for the HR roster.

``employee_table.department`` carries 22 distinct raw values, several of which are
spelling variants, double-spaced, or an *entity* repeated in the department slot
rather than a real department. This module folds them to an approved canonical
set so the "All Employees" directory reads consistently.

The mapping was derived ONLY from the actual distinct values in the roster — no
department name here is invented. Decisions signed off by the business:

  * Innovation cluster → merged into "Innovation & Digital Transformation"
    (raw: "Innovation", "Innovation & Digital Transformation",
     "Digital Financial Services").
  * Entity-as-department rows (the subsidiary repeated in the department column)
    → "<Entity> — Unassigned" so they are visibly flagged, raw value preserved
    (raw: "HFDI", "HFBI", "HFC", "HF Group").

An unknown/new raw value is returned cleaned (whitespace-collapsed) rather than
dropped, so a department that appears later still shows until it is mapped here.
Per-employee exceptions are handled by the overlay's ``standard_department``
override — this mapping is only the default.
"""

# Keys are lower-cased, whitespace-collapsed raw values → canonical display name.
STANDARD_DEPARTMENT_MAP = {
    "retail banking": "Retail Banking",
    "technology, service & operations": "Technology, Service & Operations",
    "credit": "Credit",
    "finance": "Finance",
    "risk & compliance": "Risk & Compliance",
    "human resource & administration": "Human Resource & Administration",
    "commercial banking": "Commercial Banking",
    "company secretary and legal": "Company Secretary & Legal",
    "treasury": "Treasury",
    "mortgage business": "Mortgage Business",
    "marketing": "Marketing",
    "internal audit": "Internal Audit",
    "strategy & business performance": "Strategy & Business Performance",
    "diaspora": "Diaspora",
    "group ceo's office": "Group CEO's Office",
    # A — Innovation cluster merged.
    "innovation": "Innovation & Digital Transformation",
    "innovation & digital transformation": "Innovation & Digital Transformation",
    "digital financial services": "Innovation & Digital Transformation",
    # B — entity repeated in the department column; flagged, not pretended a dept.
    "hfdi": "HFDI — Unassigned",
    "hfbi": "HFBI — Unassigned",
    "hfc": "HFC — Unassigned",
    "hf group": "HF Group — Unassigned",
}


def standardize_department(raw) -> str:
    """Return the canonical department name for a raw ``employee_table`` value.

    Whitespace is collapsed (fixes the double-spaced "Company  Secretary And
    Legal"); lookup is case-insensitive. Blank → "Unassigned"; an unmapped value
    is returned cleaned so nothing silently disappears.
    """
    if raw is None:
        return "Unassigned"
    collapsed = " ".join(str(raw).split()).strip()
    if not collapsed:
        return "Unassigned"
    return STANDARD_DEPARTMENT_MAP.get(collapsed.lower(), collapsed)
