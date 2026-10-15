"""Why is this card empty? One run, one answer.

    manage.py card_doctor AN4321
    manage.py card_doctor AN4321 --like njoka

A scorecard with every target present and every actual at nought looks like
eight separate faults. It almost never is. It is one of three things, and
until now telling them apart meant asking the database eight questions by
hand and guessing between them:

1. **the person's code differs between the roster and the feeds** - the roster
   says CMM4236 and the warehouse says CM4236, so every lookup keyed on the
   code returns nothing;
2. **the feed is empty or stale for everybody** - an ETL has stopped, and this
   person's card is simply the one somebody happened to open;
3. **the person genuinely has no book** - a new joiner, or a role that does
   not carry one.

Those three go to three different people, so this prints what distinguishes
them: for every feed a card reads, whether the table is there, how many rows
it holds IN TOTAL, how many it holds for this person, and - when it holds none
for them - which codes or names in that table look like theirs.

The last column is the one that matters. A feed with two million rows and none
for this code, whose nearest neighbour is the same digits with one more
letter, is cause 1 and takes a minute to fix. A feed with nought rows in it at
all is cause 2 and is not about this person.

Nothing is written. Read-only, and safe to run on the host against production.
"""

import re

from django.core.management.base import BaseCommand, CommandError

#: (table, the column a card looks this person up by, what it feeds).
#: Every warehouse feed the sales and back-office cards read, in the order the
#: card reads them.
#: Each entry's columns are the ones the card's own query matches on, read off
#: those queries rather than guessed - a doctor that probes the wrong column
#: reports a healthy feed as missing, which is worse than no doctor.
#: Several feeds stamp the seller more than one way and the card accepts any of
#: them, so those carry every column it tries.
CODE_FEEDS = [
    ("retail_allocated_portfolio", ["sales_code"],
     "the RM's book - deposits, income, loan loss and PAR all join through it"),
    ("daily_balance_movement", ["rm_code"], "deposit growth and position"),
    ("loan_daily_balance_movement", ["rm_code"],
     "asset growth, and the base its target is a rate on"),
    ("drawdown_daily", ["salesperson", "sales_code", "seller_code"],
     "net disbursements"),
    ("trade_finance_data", ["rm_code"], "trade finance income and volume"),
    ("insurance_policies", ["code", "rm", "sales_person"],
     "bancassurance premiums"),
    ("daily_sales_accounts_with_cto", ["sale_code"],
     "new customers and the turnover-qualified counts"),
    ("iapply_loan_approvals_data_dump", ["seller_code"], "loan turnaround"),
    ("portfolio_rm_revenue", ["sales_code"], "income categories"),
]

#: Feeds keyed on the person's NAME rather than a code.
NAME_FEEDS = [
    ("weighted_dashboard_manual_sales_table", ["staff_name"],
     "property units and value (HFDI sales return)"),
    ("hfdi_projects_inventory_sales_data", ["staff_name"],
     "property units and value (HFCB Properties CRM)"),
    ("affordable_housing_applications", ["assisted_by"],
     "property through affordable housing"),
    ("cx_rm_metric", ["rm_name"], "NPS and portfolio coverage"),
]

#: Feeds keyed on the PF number.
PF_FEEDS = [("sc_training_return", ["staff_pf", "sales_code"],
             "training hours")]

#: Feeds keyed on the branch.
BRANCH_FEEDS = [
    ("daily_dormancy_converted_accounts", ["brn_code"],
     "dormancy reactivations (branch code)"),
    ("sc_audit_return", ["branch_key"], "audit score and implementation"),
]


def _by_name(text):
    """Roster rows whose staff name contains this text → [(code, name)].

    All three rosters, because a teller is on none of the sales ones.
    """
    from apps.staff_management.models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData, EmployeeRoleHistory,
        StaffEmployeeData,
    )

    from django.db.models import Q

    words = [w for w in str(text or "").split() if w]
    if not words:
        return []

    # Every word, not the whole string. The roster carries the full legal
    # name - ABED KIPKOECH LELGO - and what somebody types off a screenshot
    # is "Abed Lelgo", so matching the string whole finds nothing. This is
    # the same middle-name problem the property feeds have.
    matches = Q()
    for word in words:
        matches &= Q(staff_name__icontains=word)

    out = {}
    for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
                  StaffEmployeeData):
        try:
            rows = (model.objects
                    .filter(matches)
                    .exclude(sales_code="")
                    .values_list("sales_code", "staff_name")[:40])
        except Exception:  # noqa: BLE001 - a missing table must not stop this
            continue
        for sales_code, staff_name in rows:
            key = (sales_code or "").strip().upper()
            if key and key not in out:
                out[key] = (staff_name or "").strip()
    try:
        notes_match = Q()
        for word in words:
            notes_match &= Q(notes__icontains=word)
        for sales_code, notes in EmployeeRoleHistory.objects.filter(
                notes_match).values_list("sales_code", "notes")[:40]:
            key = (sales_code or "").strip().upper()
            if key and key not in out:
                out[key] = (notes or "").split("|")[0].strip()
    except Exception:  # noqa: BLE001
        pass
    return sorted(out.items())


def _exists(cursor, table):
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = %s)", [table])
    return bool(cursor.fetchone()[0])


def _has_column(cursor, table, column):
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s)", [table, column])
    return bool(cursor.fetchone()[0])


class Command(BaseCommand):
    help = "Explain why one person's scorecard has no actuals."

    def add_arguments(self, parser):
        parser.add_argument(
            "who",
            help="A sales code, or a name - \"Abed Lelgo\" works as well as "
                 "AKL3116. A name that matches several people lists them "
                 "rather than picking one.")
        parser.add_argument(
            "--like", default="",
            help="Extra text to look for in the name columns - a surname "
                 "usually. Defaults to the roster's own spelling.")
        parser.add_argument(
            "--rows", type=int, default=6,
            help="How many near matches to print per feed. Default 6.")

    # -- one feed --------------------------------------------------------
    def _probe(self, cursor, table, columns, purpose, needle, limit,
               numeric_tail=""):
        write = self.stdout.write

        if not _exists(cursor, table):
            write(self.style.WARNING(
                f"  {table:44} NOT PRESENT          {purpose}"))
            return

        usable = [c for c in columns if _has_column(cursor, table, c)]
        if not usable:
            write(self.style.WARNING(
                f"  {table:44} no {'/'.join(columns)} column   {purpose}"))
            return

        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        total = cursor.fetchone()[0]
        if not total:
            # Cause 2, and it is not about this person at all.
            write(self.style.ERROR(
                f"  {table:44} EMPTY - 0 rows       {purpose}"))
            return

        # Any of the columns the card itself would accept.
        where = " OR ".join(
            f'UPPER(TRIM("{c}"::text)) = UPPER(TRIM(%s))' for c in usable)
        cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}',
                       [needle] * len(usable))
        mine = cursor.fetchone()[0]

        if mine:
            write(self.style.SUCCESS(
                f"  {table:44} {mine:>8,} of {total:>10,}  {purpose}"))
            return

        write(self.style.WARNING(
            f"  {table:44} {0:>8} of {total:>10,}  {purpose}"))
        column = usable[0]

        # Nothing for this person. Which is cause 1 and which is cause 3? The
        # nearest neighbours say: a code with the same digits and different
        # letters is a spelling, not an absence.
        patterns = []
        if numeric_tail:
            patterns.append(f"%{numeric_tail}%")
        head = re.sub(r"[^A-Za-z]", "", needle)[:3]
        if len(head) >= 2:
            patterns.append(f"{head}%")
        seen = []
        for pattern in patterns:
            cursor.execute(
                f'SELECT DISTINCT "{column}"::text FROM "{table}" '
                f'WHERE "{column}"::text ILIKE %s '
                f'AND "{column}" IS NOT NULL LIMIT %s', [pattern, limit])
            for (value,) in cursor.fetchall():
                value = (value or "").strip()
                if value and value not in seen:
                    seen.append(value)
        if seen:
            write(f"      {'nearest in this table:':<24} "
                  f"{', '.join(seen[:limit])}")

    def handle(self, **options):
        from django.db import connection

        from apps.staff_management.live_scorecard import (
            brn_code_for, pf_for, resolve_person, roster_row)

        write = self.stdout.write
        code = options["who"].strip()
        limit = options["rows"]

        person = resolve_person(code)
        if person is None:
            # Not a code this estate knows. Before giving up, look for it as a
            # NAME - which is what somebody holding a screenshot actually has,
            # and hunting for the code is the step that makes this a chore.
            found = _by_name(code)
            if len(found) == 1:
                code = found[0][0]
                person = resolve_person(code)
                write(f"\n  (matched \"{options['who'].strip()}\" to "
                      f"{code} on the roster)")
            elif found:
                lines = "\n".join(
                    f"      {c:<12} {n}" for c, n in found[:12])
                raise CommandError(
                    f"{code!r} matches {len(found)} people on the roster. "
                    f"Run it again with one of these codes:\n{lines}")
            else:
                raise CommandError(
                    f"{code!r} is on none of the three rosters, as a code or "
                    f"as a name, so there is no card to explain. That is "
                    f"itself the answer: Administration maintains those "
                    f"lists.")

        row = roster_row(code)
        pf = pf_for(code, row)
        brn = brn_code_for(code, row)
        name = person.name or ""
        needle_name = options["like"].strip() or name
        tail = re.sub(r"\D", "", code)

        write("")
        write(f"  {name or '(no name on the roster)'}  |  {code}")
        write(f"  role {person.role_code or '(none)'}  |  branch "
              f"{person.branch or '(none)'}  |  branch code {brn or '(none)'}"
              f"  |  PF {pf or '(none)'}")
        write(f"  found on {person.roster}")
        write("")
        write("  Each line: rows FOR THIS PERSON of rows IN THE TABLE.")
        write("")

        with connection.cursor() as cursor:
            write("  -- keyed on the sales code --------------------------")
            for table, columns, purpose in CODE_FEEDS:
                self._probe(cursor, table, columns, purpose, code, limit, tail)

            write("")
            write("  -- keyed on the name --------------------------------")
            if not name:
                write("  (the roster records no name, so none of these can "
                      "match)")
            for table, columns, purpose in NAME_FEEDS:
                self._probe(cursor, table, columns, purpose, needle_name,
                            limit)

            # The commonest single fault on a property line, and the one a
            # list of row counts cannot show: the feeds hold this person
            # under a different spelling of the same name.
            if name:
                from apps.staff_management.live_scorecard import (
                    PROPERTY_UNIT_TABLES, resolve_feed_name)

                spelling, how, candidates = resolve_feed_name(
                    PROPERTY_UNIT_TABLES, "staff_name", name)
                if how == "first-last":
                    write(f"      {'spelt there as:':<24} {spelling!r} "
                          f"(matched on first and last name, not exactly)")
                elif not spelling and candidates:
                    write(f"      {'ambiguous:':<24} "
                          f"{', '.join(repr(c) for c in candidates[:6])} - "
                          f"too alike to choose between, so none was used")

            write("")
            write("  -- keyed on the PF number ---------------------------")
            if not pf:
                write("  (no PF number found, so the training return cannot "
                      "match)")
            else:
                for table, columns, purpose in PF_FEEDS:
                    self._probe(cursor, table, columns, purpose, pf, limit, pf)

            write("")
            write("  -- keyed on the branch ------------------------------")
            for table, columns, purpose in BRANCH_FEEDS:
                if columns[0] == "branch_key":
                    from apps.staff_management.audit_returns import fold_branch

                    needle = fold_branch(person.branch)
                else:
                    needle = brn
                if not needle:
                    write(f"  {table:44} no branch to match   {purpose}")
                    continue
                self._probe(cursor, table, columns, purpose, needle, limit)

        write("")
        write("  Reading it:")
        write("    EMPTY - 0 rows        the feed has stopped. Not about this "
              "person; check Data Health.")
        write("    0 of a large number   this person is not in a feed that "
              "has data. If a 'nearest' line")
        write("                          shows the same digits under another "
              "spelling, that is the fault.")
        write("    n of a large number   the feed has them, so an empty line "
              "above it is a different problem.")
        write("")
