"""Every card that disagrees with the desk's own run, and why. Read-only.

    docker exec hf-backend python manage.py scorecard_desk_check
    docker exec hf-backend python manage.py scorecard_desk_check --book sales --month 9

For each person and each month the desk's macro scored (Monthly_Summ), the
card is recomputed from the stored workbook and actuals template exactly as the
portal computes it, and every person whose score differs is listed with what
the template shows about them:

* ROLE - the List (what the portal uses today) against the role the desk's
  template carries for the person; a card on the wrong role reads the wrong
  lines (Christine Adhiambo, Sharon Wanjiru);
* NO ROW - sheets with no row for the person by name, sales code or PF
  (#N/A on the card; Joseph Gatundu);
* NO TARGET - lines whose target is 0 (#DIV/0!; Jackson Nyawa).

One fix should cover everybody a cause touches, so the summary at the end
counts people by cause.
"""

from collections import Counter

from django.core.management.base import BaseCommand


def _template_role(actuals, code, name):
    """The role column the desk's template carries for the person."""
    for grid in (actuals or {}).values():
        if not isinstance(grid, list):
            continue
        for row in grid[1:]:
            if len(row) > 3 and (
                    str(row[1] or "").strip().upper() == code
                    or str(row[2] or "").strip().lower() == name.strip().lower()):
                return str(row[3] or "").strip()
    return ""


class Command(BaseCommand):
    help = "List every card whose score differs from the desk's recorded run, with the cause."

    def add_arguments(self, parser):
        parser.add_argument("--book", default="back_office",
                            choices=["back_office", "sales", "branch_business"])
        parser.add_argument("--month", type=int, default=None,
                            help="one month (1-12); default every month the desk scored")
        parser.add_argument("--year", type=int, default=None)

    def handle(self, *args, **opts):
        from apps.staff_management import workbook_cards as wc

        spec = wc.SPECS[opts["book"]]
        book = wc.saved(spec.files[0], opts["year"])
        actuals = wc.saved(spec.files[1], opts["year"])
        if book is None or actuals is None:
            self.stdout.write("The workbook or its actuals template is not loaded.")
            return
        recorded = wc.recorded_scores(book)
        months = sorted({m for (_c, m) in recorded}
                        if opts["month"] is None else {opts["month"]})
        causes, people, same, total = Counter(), set(), 0, 0
        for holder in wc.holders(book):
            if holder.sheet not in book.get("cards", {}):
                continue
            for month in months:
                desk = recorded.get((holder.sales_code, month))
                if desk is None:
                    continue
                total += 1
                card = wc.compute(book, actuals, holder, month)
                score = card["total"]
                if wc._num(score) and abs(score - desk) < 0.0005:
                    same += 1
                    continue
                why = []
                t_role = _template_role(actuals, holder.sales_code, holder.name)
                if t_role and t_role.upper() != str(holder.role or "").upper():
                    why.append(f"ROLE List {holder.role} / template {t_role}")
                    causes["role"] += 1
                no_row = sorted({ln["feed"] for ln in card["lines"]
                                 if isinstance(ln.get("actual"), dict)
                                 and ln["actual"].get("e") == "#N/A"})
                if no_row:
                    why.append("NO ROW " + ", ".join(no_row))
                    causes["no row"] += 1
                no_target = [ln["measure"] or ln["initiative"] for ln in card["lines"]
                             if isinstance(ln.get("score"), dict)
                             and ln["score"].get("e") == "#DIV/0!"]
                if no_target:
                    why.append(f"NO TARGET on {len(no_target)} line(s)")
                    causes["no target"] += 1
                if not why:
                    why.append("other (targets or figures changed since the desk's run)")
                    causes["other"] += 1
                people.add(holder.sales_code)
                shown = f"{score:.1%}" if wc._num(score) else "error"
                self.stdout.write(
                    f"{month:>2}  {holder.sales_code:<9} {holder.name[:26]:<26} "
                    f"{str(holder.role or '')[:12]:<12} {str(holder.branch or '')[:12]:<12} "
                    f"desk {desk:6.1%}  card {shown:>6}  {'; '.join(why)}")
        self.stdout.write(
            f"\n{spec.book}: {same} of {total} person-months match the desk; "
            f"{len(people)} people differ. By cause: "
            + ", ".join(f"{k} {v}" for k, v in causes.most_common()) + ".")
