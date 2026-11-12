"""Load the Whizz onboarding counts the Digital Onboarding lines read.

    manage.py load_whizz_onboarding            # this year, from the lake
    manage.py load_whizz_onboarding --check    # and compare with the desk

``--check`` compares, for every person on the BO template's Digital_Customers
sheet, the desk's running total with the report's for each month the desk
filled, and prints how the officer was found - so whether the line can be
trusted is shown, not assumed.
"""
import datetime

from django.core.management.base import BaseCommand


def logins_for(actuals, name):
    """The AD logins the desk keys this person's account-opening rows on."""
    out = set()
    for sheet in ("Account_Opening_PB", "Account_Opening_BB", "Account_Opening_UB"):
        for row in (actuals.get(sheet) or [])[1:]:
            if len(row) > 2 and str(row[2] or "").strip().upper() == name.strip().upper():
                out.add(str(row[1] or "").strip())
    return out


class Command(BaseCommand):
    help = "Load this year's Whizz onboarding counts per officer from the lake."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=datetime.date.today().year)
        parser.add_argument("--check", action="store_true",
                            help="Compare with the desk's Digital_Customers figures.")
        parser.add_argument("--no-load", action="store_true",
                            help="With --check: compare what is already loaded.")

    def handle(self, *args, **opts):
        from apps.staff_management import whizz_onboarding as wo
        from apps.staff_management.workbook_cards import saved

        year = opts["year"]
        if not opts["no_load"]:
            officers = wo.fetch(year)
            wo.save(year, officers)
            self.stdout.write(self.style.SUCCESS(
                f"Loaded {year}: {len(officers)} officers, "
                f"{sum(sum(m.values()) for m in officers.values())} customers."))
        if not opts["check"]:
            return
        officers = (wo._loaded(year).get("officers") or {})
        actuals = saved("actuals") or {}
        rows = (actuals.get("Digital_Customers") or [])[1:]
        agree = differ = unnamed = 0
        for row in rows:
            if len(row) < 7 or not row[1]:
                continue
            code, name = str(row[1]).strip(), str(row[2] or "").strip()
            desk = [(m, row[5 + m]) for m in range(1, 13)
                    if len(row) > 5 + m and isinstance(row[5 + m], (int, float))]
            if not desk:
                continue
            found = wo.mine(officers, (code, *logins_for(actuals, name)), (name,))
            if not found:
                unnamed += 1
                # created_by is a numeric Whizz user id with no name beside
                # it. An id whose running totals equal this person's desk
                # figures in EVERY filled month is evidence, not a guess -
                # printed for a person to confirm, never used by the card.
                same_series = [
                    o for o, months in officers.items()
                    if any(d for _, d in desk)
                    and all(abs(sum(n for mm, n in months.items() if int(mm) <= m) - d) < 1e-9
                            for m, d in desk)]
                hint = (f"  ids matching every desk month: {', '.join(same_series)}"
                        if same_series else "")
                self.stdout.write(f"  NOT IN REPORT  {code:<10} {name}  "
                                  f"desk {[int(d) for _, d in desk]}{hint}")
                continue
            got = [sum(n for o in found for mm, n in officers[o].items() if int(mm) <= m)
                   for m, _ in desk]
            same = sum(1 for (m, d), g in zip(desk, got) if abs(d - g) < 1e-9)
            agree += same
            differ += len(desk) - same
            self.stdout.write(
                f"  {code:<10} {name[:24]:<24} as {', '.join(found)[:30]:<30} "
                f"desk {[int(d) for _, d in desk]}  report {got}")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nmonths agreeing {agree}, differing {differ}; "
            f"people the report does not name {unnamed}"))
