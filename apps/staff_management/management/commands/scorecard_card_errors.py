"""Every card's desk errors in one list, so they are fixed once, not one complaint at a time.

    manage.py scorecard_card_errors              (each workbook's latest month)
    manage.py scorecard_card_errors --month 9

Two errors are checked on every person's card, as the workbook computes it:

* a target copied from the line above - the same full-year and year-to-date
  target as the previous line, on a different measure. Felix Saigon's Leave
  Management line carried Training hours' 48 / 24, where every other template
  has 1, and scored 4.2% for a person who meets the policy.
* a line scored from a template sheet nobody has a figure on for the month -
  nothing was measured, yet the card scores it 0 (his CSAT: 0 of 15%).

It writes nothing. Each finding names the card template, the line, and how
many people carry it, which is what the desk needs to correct the workbook.
"""
from django.core.management.base import BaseCommand


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _filled(actuals, feed, month):
    """Has anybody a non-zero figure for ``month`` on this template sheet?"""
    from apps.staff_management.bb_live_feeds import BLOCK_WIDTH

    for row in (actuals.get(feed) or [])[1:]:
        column = 6 + month - 1
        while column < len(row):
            value = row[column]
            if _number(value) and value != 0:
                return True
            column += BLOCK_WIDTH
    return False


def find_errors(book, actuals, month):
    """→ {(template, line, problem): [names]} for one workbook and month.

    Reported only where the evidence proves it, after a first version also
    reported equal targets that were the desk's design:

    * a copied target: equal to the line above AND the same measure carries one
      fixed target on every other template, which this one does not match
      (Leave Management: 1 everywhere else, 48 on the BSA card);
    * an unmeasured line: nobody has a figure on its sheet for the month AND the
      card actually scores it 0 - a blank that scores well is no harm done.
    """
    from apps.staff_management.workbook_cards import compute, holders

    cards = []
    for holder in holders(book):
        if holder.sheet not in book["cards"]:
            continue
        try:
            cards.append((holder, compute(book, actuals, holder, month)))
        except Exception:  # noqa: BLE001 - one card must not stop the sweep
            continue

    # Each measure's targets, by template.
    targets = {}
    for holder, card in cards:
        for line in card["lines"]:
            if line["measure"] and _number(line["pm"]):
                targets.setdefault(line["measure"].lower(), {}).setdefault(
                    holder.sheet, set()).add(line["pm"])

    found, filled = {}, {}
    for holder, card in cards:
        previous = None
        for line in card["lines"]:
            name = line["measure"] or line["initiative"]
            if (previous is not None and line["measure"] and previous["measure"]
                    and line["measure"] != previous["measure"]
                    and _number(line["pm"]) and line["pm"] == previous["pm"]
                    and line["ytd_target"] == previous["ytd_target"]):
                others = [v for sheet, v in targets.get(line["measure"].lower(), {}).items()
                          if sheet != holder.sheet]
                elsewhere = set().union(*others) if others else set()
                # At least two other templates agreeing on one value: a target set
                # per person (banca, mortgages) never gives a single value.
                if len(others) >= 2 and len(elsewhere) == 1 and line["pm"] not in elsewhere:
                    problem = (f"target {line['pm']:g} / {line['ytd_target']:g} is the "
                               f"line above's ({previous['measure']}); every other "
                               f"template has {next(iter(elsewhere)):g}")
                    found.setdefault((holder.sheet, name, problem), []).append(holder.name)
            feed = line["feed"]
            if feed and not line["typed"] and feed in actuals:
                if feed not in filled:
                    filled[feed] = _filled(actuals, feed, month)
                if (not filled[feed] and _number(line["weight"]) and line["weight"] > 0
                        and _number(line["score"]) and line["score"] == 0):
                    problem = (f"scored 0 from {feed}, where nobody has a figure for "
                               f"the month - not measured")
                    found.setdefault((holder.sheet, name, problem), []).append(holder.name)
            previous = line
    return found


class Command(BaseCommand):
    help = "List the desk's errors on every scorecard: copied targets, unmeasured lines."

    def add_arguments(self, parser):
        parser.add_argument("--month", type=int, default=None,
                            help="1-12. Each workbook's latest month when left out.")

    def handle(self, **options):
        from apps.staff_management.workbook_cards import SPECS, saved, template_months

        w = self.stdout.write
        total = 0
        for book_name, spec in SPECS.items():
            book, actuals = saved(spec.files[0]), saved(spec.files[1])
            if not book or not actuals:
                w(f"\n{book_name}: no workbook or template loaded - skipped")
                continue
            months = template_months(actuals)
            month = options["month"] or (months[-1] if months else None)
            if not month:
                w(f"\n{book_name}: the template has no month filled - skipped")
                continue
            found = find_errors(book, actuals, month)
            people = sum(len(v) for v in found.values())
            w(f"\n{book_name}, month {month}: {len(found)} problem(s) on "
              f"{people} card line(s)")
            for (sheet, line, problem), names in sorted(found.items()):
                shown = ", ".join(sorted(set(names))[:4])
                more = len(set(names)) - 4
                w(f"  [{sheet}] {line}: {problem}")
                w(f"      {len(set(names))} people: {shown}"
                  f"{f' and {more} more' if more > 0 else ''}")
            total += len(found)
        w(f"\n{total} problem(s) in all. Correct the target cells in the workbook "
          f"and upload it again; leave unmeasured sheets blank so they are not scored.")
