"""Allocating delinquent customers to collections officers.

The problem
───────────
``loans.delay_officer`` is the core banking system's assignment, and plenty of
delinquent loans arrive with it blank. Those customers belong to nobody: they
are on no officer's screen, so nobody calls them, and they age quietly into
the next bucket.

What this does NOT do
─────────────────────
It does not touch ``loans``. That is a warehouse table the ETL rewrites from
core banking every night, so anything written there is gone by morning and
would be fighting the source of truth besides. Allocations are held here, in
``hf_collections_allocation``, and the officer's book is the union of the two:
what core banking assigned, plus what was allocated here for the customers it
left blank.

It also never moves a customer core banking HAS assigned. That is somebody
else's system making a decision, and quietly overriding it is how two desks
end up believing different things about who is calling whom.

The rule
────────
Round robin over the officers, taking the customers in descending order of
arrears, so the biggest exposures are spread across the team rather than
landing on whoever sorts first. Where an officer already has a book, their
existing load is counted first, so a round of allocation levels the team up
instead of giving everyone the same NUMBER regardless of what they were
already carrying.

Branch is respected when asked for - an officer who only works Mombasa should
not be handed Kisumu - but it is off by default, because this desk is
centralised and a branch filter with no officer behind a branch would leave
those customers unallocated, which is the problem being solved.
"""

from __future__ import annotations


def unallocated(limit=None, branch=None):
    """Delinquent customers nobody is calling → list of dicts.

    Blank in core banking AND not allocated here. Ordered by arrears, worst
    first, because that is the order a desk should pick them up in.
    """
    from django.db import connection, transaction

    from .models import CollectionAllocation

    taken = set(
        CollectionAllocation.objects.filter(is_active=True)
        .values_list("cust_id", flat=True))

    sql = """
        SELECT l.cust_id,
               MAX(TRIM(COALESCE(c.firstname,'') || ' '
                        || COALESCE(c.lastname,''))) AS customer_name,
               MAX(l.branch)                         AS branch,
               COUNT(*)                              AS loans,
               COALESCE(SUM(l.total_arrears), 0)     AS arrears,
               COALESCE(SUM(l.euro_book_balance), 0) AS outstanding,
               MAX(l.days_in_arrears)                AS days_past_due
        FROM loans l
        LEFT JOIN customers c ON c.cust_id = l.cust_id
        WHERE COALESCE(l.overdue_days, 0) > 0
          AND COALESCE(TRIM(l.delay_officer), '') = ''
          {branch}
        GROUP BY l.cust_id
        ORDER BY arrears DESC NULLS LAST
    """.format(branch="AND l.branch::text = %s" if branch else "")

    params = [str(branch)] if branch else []
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001 - an absent feed is not a crash
        return []

    rows = [row for row in rows if row["cust_id"] not in taken]
    return rows[:limit] if limit else rows


def current_load(codes):
    """How much each officer is already carrying → ``{code: customers}``.

    Core banking's assignment plus anything allocated here, because a round
    of allocation has to level the team up rather than hand everybody the
    same number on top of whatever they already had.
    """
    from django.db import connection, transaction

    from .models import CollectionAllocation

    load = {code: 0 for code in codes}

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                """
                SELECT LOWER(TRIM(l.delay_officer)) AS code,
                       COUNT(DISTINCT l.cust_id)    AS customers
                FROM loans l
                WHERE COALESCE(l.overdue_days, 0) > 0
                  AND COALESCE(TRIM(l.delay_officer), '') <> ''
                GROUP BY 1
                """, [])
            for code, customers in cur.fetchall():
                for wanted in codes:
                    if wanted.strip().lower() == code:
                        load[wanted] += int(customers or 0)
    except Exception:  # noqa: BLE001
        pass

    for row in (CollectionAllocation.objects
                .filter(is_active=True,
                        collection_officer_code__in=codes)
                .values("collection_officer_code")):
        code = row["collection_officer_code"]
        load[code] = load.get(code, 0) + 1

    return load


def plan(officers, limit=None, branch=None):
    """Who would get whom → ``(assignments, report)``. Writes nothing.

    ``officers`` is a list of ``{"collection_officer_code", "name"}``, or of
    bare codes.
    """
    people = []
    for officer in officers:
        if isinstance(officer, str):
            people.append({"collection_officer_code": officer.strip(),
                           "collection_officer_name": ""})
        else:
            people.append({
                "collection_officer_code": str(
                    officer.get("collection_officer_code") or "").strip(),
                "collection_officer_name": str(
                    officer.get("collection_officer_name") or "").strip()})
    people = [p for p in people if p["collection_officer_code"]]

    report = {"officers": len(people), "unallocated": 0, "assigned": 0,
              "per_officer": {}, "skipped": []}
    if not people:
        report["skipped"].append("No officer was named, so there is nobody "
                                 "to allocate to.")
        return [], report

    waiting = unallocated(limit=limit, branch=branch)
    report["unallocated"] = len(waiting)
    if not waiting:
        return [], report

    load = current_load([p["collection_officer_code"] for p in people])

    assignments = []
    for row in waiting:
        # The officer carrying least, ties broken by code so a dry run and
        # the run that follows it agree.
        chosen = min(people,
                     key=lambda p: (load[p["collection_officer_code"]],
                                    p["collection_officer_code"]))
        code = chosen["collection_officer_code"]
        load[code] += 1
        assignments.append({
            "cust_id": row["cust_id"],
            "customer_name": row.get("customer_name") or "",
            "branch": row.get("branch"),
            "arrears": float(row.get("arrears") or 0),
            "outstanding": float(row.get("outstanding") or 0),
            "days_past_due": row.get("days_past_due"),
            "collection_officer_code": code,
            "collection_officer_name": chosen["collection_officer_name"],
        })
        report["assigned"] += 1

    for person in people:
        code = person["collection_officer_code"]
        report["per_officer"][code] = {
            "name": person["collection_officer_name"],
            "already_carrying": current_load([code])[code],
            "getting": sum(1 for a in assignments
                           if a["collection_officer_code"] == code),
        }
    return assignments, report


def save(assignments, who="", note=""):
    """Write the allocations → how many were written.

    Upserted on the customer, so re-running corrects rather than stacking.
    """
    from django.db import transaction

    from .models import CollectionAllocation

    written = 0
    with transaction.atomic():
        for item in assignments:
            CollectionAllocation.objects.update_or_create(
                cust_id=item["cust_id"],
                defaults={
                    "collection_officer_code": item["collection_officer_code"],
                    "collection_officer_name": item.get(
                        "collection_officer_name") or "",
                    "customer_name": item.get("customer_name") or "",
                    "branch": str(item.get("branch") or ""),
                    "arrears_at_allocation": item.get("arrears") or 0,
                    "allocated_by": who,
                    "note": note,
                    "is_active": True,
                })
            written += 1
    return written
