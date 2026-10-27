"""Every line of every card, and whether it actually carries a figure.

    manage.py scorecard_coverage
    manage.py scorecard_coverage --role ultimate_rm
    manage.py scorecard_coverage --month 2026-09
    manage.py scorecard_coverage --per-role 0 --csv coverage.csv

This exists because of how the dashes have been found so far: somebody opens
a card, sees a dash, pastes it, one line gets fixed, and the next dash is
found the same way a week later. That loop cannot say whether the tool is
nearly right or barely right, and it cannot tell a line that is BROKEN from a
line that is legitimately empty because the person has no book.

So this builds real cards - the same ``build_card`` the page and the download
use, with no second implementation to drift - and reports, for every KPI line
of every role, how many of the people who hold it get a figure and how many
get a dash, with the reason the card itself gives. Worst line first.

Read-only. Nothing is written, no card is signed, and it is safe to run on
the host against production.

A dash is one of four things and they go to different people:

    no target     the plan is missing - the allocation sheet, or the DMC
                  column. Administration fills that.
    no actual     the target is there and the feed gave nothing. Either an
                  ETL is behind, or this person has no book.
    neither       the line is not wired at all. That one is mine.
    not measured  the card says so on purpose - PAR before the IFRS close,
                  leave with no feed anywhere in this estate.

The last line of each entry is the one to act on: a line where EVERY holder
dashes is a wiring fault, and a line where some do and some do not is a book
or a code mismatch, which is what ``card_doctor`` is for.

ASCII only in the output - a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the whole run down with it.
"""

import csv
import datetime
from collections import defaultdict

from django.core.management.base import BaseCommand


def month_end(text):
    """``YYYY-MM`` -> the last day of that month."""
    year, month = (int(part) for part in text.split("-"))
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


class Command(BaseCommand):
    help = "Per-line coverage of the live cards: a figure, or a dash and why."

    def add_arguments(self, parser):
        parser.add_argument("--role", default="",
                            help="One role code only, e.g. ultimate_rm.")
        parser.add_argument("--month", default="",
                            help="YYYY-MM. Default: the live card, which "
                                 "reads the last closed month.")
        parser.add_argument("--per-role", type=int, default=5,
                            help="How many people to sample per role. 0 means "
                                 "everybody, which is slow - every card reads "
                                 "the warehouse.")
        parser.add_argument("--csv", default="",
                            help="Also write one row per line to this file.")

    # -- gathering --------------------------------------------------------
    def who_to_build(self, role_filter, per_role):
        """``(sales_code, name, role_code)`` for the people to sample.

        Both rosters, because the back office is not on the DMC table at all.
        The role comes from ``resolve_person``, not from the roster column, so
        the sample is grouped by the card somebody actually holds.
        """
        from apps.staff_management.live_scorecard import resolve_person
        from apps.staff_management.models import (
            BranchEmployeeDmcData, EmployeeRoleHistory)

        codes = []
        seen = set()

        sales = (BranchEmployeeDmcData.objects
                 .filter(active=1)
                 .exclude(sales_code__isnull=True)
                 .exclude(sales_code="")
                 .values_list("sales_code", flat=True))
        # The WHOLE roster table, not just the ``bo_`` half.
        #
        # This filter is why a September coverage run reported 2,885 lines and
        # left out everybody on the workbook's List sheet who is not also on
        # branch_employee_dmc_data - head office, Commercial, Mortgage,
        # Diaspora, Ultimate. ``scorecard_ingest.apply_roster`` writes all 91
        # of them here with role codes like ``sme_rm``, so a report that asks
        # this table for ``bo_`` only is measuring a sample it quietly chose,
        # and the figure it prints is not the bank's coverage.
        #
        # The ``seen`` set below already de-dupes against the sales pass, so
        # anybody on both tables is still counted once, from the DMC row that
        # carries their targets.
        rostered = (EmployeeRoleHistory.objects
                    .exclude(role_code="")
                    .exclude(sales_code__isnull=True)
                    .exclude(sales_code="")
                    .values_list("sales_code", flat=True))

        for code in list(sales) + list(rostered):
            key = (code or "").strip().upper()
            if not key or key in seen:
                continue
            seen.add(key)
            codes.append((code or "").strip())

        per_role_count = defaultdict(int)
        chosen = []
        skipped = defaultdict(int)

        for code in codes:
            person = resolve_person(code)
            if person is None:
                skipped["not on any roster"] += 1
                continue
            if not person.role_code:
                skipped["role has no card"] += 1
                continue
            if role_filter and person.role_code != role_filter:
                continue
            if per_role and per_role_count[person.role_code] >= per_role:
                continue
            per_role_count[person.role_code] += 1
            chosen.append((code, person.name, person.role_code))

        return chosen, skipped, len(codes)

    @staticmethod
    def verdict(line):
        """What this line is, in one word, plus the card's own reason."""
        has_target = line.get("ytd_target") is not None
        has_actual = line.get("ytd_actual") is not None
        why = (line.get("pending_label") or line.get("pending")
               or line.get("diagnostic") or "").strip()

        if has_target and has_actual:
            return "ok", ""
        if not has_target and not has_actual:
            return "neither", why
        if not has_target:
            return "no target", why
        return "no actual", why

    # -- running ----------------------------------------------------------
    def handle(self, **options):
        from apps.staff_management.live_scorecard import build_card

        write = self.stdout.write
        as_at = month_end(options["month"]) if options["month"] else None
        role_filter = (options["role"] or "").strip()
        per_role = max(0, options["per_role"])

        label = ("the live card (last closed month)" if as_at is None
                 else as_at.strftime("%B %Y"))

        write("")
        write("  Scorecard line coverage")
        write("  " + "=" * 74)
        write(f"  month          {label}")

        people, skipped, roster_total = self.who_to_build(role_filter, per_role)
        how_many = (f", up to {per_role} per role" if per_role
                    else ", everybody")
        write(f"  roster         {roster_total} sales codes")
        write(f"  sampled        {len(people)} people{how_many}")
        for reason, count in sorted(skipped.items()):
            write(f"                 {count} skipped - {reason}")
        write("")

        if not people:
            write("  Nobody to build. Check --role, or that the roster has "
                  "active rows.")
            write("")
            return

        # (role, kpi_code, kpi_name) -> verdict -> how many people
        tally = defaultdict(lambda: defaultdict(int))
        reasons = defaultdict(lambda: defaultdict(int))
        weights = {}
        broke = []
        cards = 0
        scored_weight = 0.0
        whole_weight = 0.0
        for_csv = []

        for code, name, role in people:
            try:
                card = build_card(code, as_at=as_at)
            except Exception as exc:                        # noqa: BLE001
                broke.append(f"{code} ({role}): {type(exc).__name__} {exc}")
                continue
            if not card.get("has_card"):
                skipped[card.get("reason") or "no card"] += 1
                continue

            cards += 1
            mine = float(card.get("scored_weight") or 0)
            scored_weight += mine
            whole_weight += mine + float(card.get("unscored_weight") or 0)

            for perspective in card.get("perspectives", []):
                for line in perspective.get("lines", []):
                    key = (role, line.get("kpi_code"), line.get("kpi_name"))
                    verdict, why = self.verdict(line)
                    tally[key][verdict] += 1
                    weights[key] = line.get("weight")
                    if verdict != "ok" and why:
                        reasons[key][why] += 1
                    for_csv.append({
                        "role": role, "sales_code": code, "name": name,
                        "kpi_code": line.get("kpi_code"),
                        "kpi_name": line.get("kpi_name"),
                        "weight": line.get("weight"),
                        "ytd_target": line.get("ytd_target"),
                        "ytd_actual": line.get("ytd_actual"),
                        "verdict": verdict, "why": why,
                    })

        # -- the headline -------------------------------------------------
        every = sum(sum(counts.values()) for counts in tally.values())
        fine = sum(counts.get("ok", 0) for counts in tally.values())
        write(f"  cards built    {cards}")
        write(f"  lines          {every}")
        if every:
            write(f"  carry a figure {fine}  ({fine / every * 100:.1f}%)")
            write(f"  a dash         {every - fine}  "
                  f"({(every - fine) / every * 100:.1f}%)")
        if cards and whole_weight:
            write(f"  weight scored  {scored_weight / whole_weight * 100:.1f}%"
                  f" of the weight on a card, averaged over the sample")
        write("")

        if broke:
            write("  BUILDS THAT RAISED - faults, not missing data")
            write("  " + "-" * 74)
            for item in broke[:20]:
                write(f"      {item}")
            if len(broke) > 20:
                write(f"      ... and {len(broke) - 20} more")
            write("")

        # -- the lines that dash, worst first -----------------------------
        ranked = sorted(
            tally.items(),
            key=lambda kv: (-(sum(kv[1].values()) - kv[1].get("ok", 0)),
                            -(weights.get(kv[0]) or 0),
                            tuple(str(part) for part in kv[0])))
        dashing = [item for item in ranked
                   if sum(item[1].values()) - item[1].get("ok", 0)]

        write(f"  LINES THAT DASH   {len(dashing)} of {len(tally)} role/KPI "
              f"pairs in the sample")
        write("  " + "-" * 74)
        if not dashing:
            write("      None. Every line in the sample carried a target and "
                  "a figure.")

        for key, counts in dashing:
            role, code, kpi_name = key
            held = sum(counts.values())
            ok = counts.get("ok", 0)
            shape = ", ".join(f"{n} {verdict}"
                              for verdict, n in sorted(counts.items())
                              if verdict != "ok")
            every_one = "   <- EVERY holder" if ok == 0 else ""
            weight = float(weights.get(key) or 0) * 100
            write("")
            write(f"      {role}/{code}")
            write(f"        {kpi_name}   weight {weight:.1f}%")
            write(f"        {ok} of {held} carry a figure; {shape}{every_one}")
            for why, n in sorted(reasons[key].items(),
                                 key=lambda kv: -kv[1])[:2]:
                write(f'        "{why}"  x{n}')
        write("")

        if options["csv"]:
            path = options["csv"]
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "role", "sales_code", "name", "kpi_code", "kpi_name",
                    "weight", "ytd_target", "ytd_actual", "verdict", "why"])
                writer.writeheader()
                writer.writerows(for_csv)
            write(f"  {len(for_csv)} rows written to {path}")
            write("")

        write("  A line where EVERY holder dashes is a wiring fault.")
        write("  A line where some do and some do not is a book or a code "
              "mismatch - run card_doctor on one of them.")
        write("  Nothing was written.")
        write("")
