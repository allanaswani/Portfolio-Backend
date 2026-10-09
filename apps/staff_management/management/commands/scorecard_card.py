"""One person's live scorecard, line by line, with the provenance of every
number — so it can be checked against the card the desk emailed them.

    manage.py scorecard_card CMM4236
    manage.py scorecard_card CMM4236 --targets   # just the plan row

For each line it prints the target column, which DMC table that column was read
from, the annual figure, the figure pro-rated to the actual's own date, the
actual with its as-at, and the score. A line that is not scored prints the
reason instead of a number.

This is the answer to "why does the tool say 56% when my card says 49%": every
input is on the screen next to where it came from, so the difference can be
settled with a row rather than an opinion.

It writes nothing.
"""
from django.core.management.base import BaseCommand, CommandError


def _money(value):
    return "-" if value is None else f"{float(value):>16,.0f}"


class Command(BaseCommand):
    help = "Print one person's live scorecard with the source of every figure."

    def add_arguments(self, parser):
        parser.add_argument("sales_code")
        parser.add_argument(
            "--targets", action="store_true",
            help="Only the DMC plan row: every target column and its value.")

    def handle(self, sales_code, **options):
        from apps.staff_management.live_scorecard import (
            STAFF_TABLE, build_card, roster_row, roster_target_row,
        )

        code = sales_code.strip()
        write = self.stdout.write

        row = roster_row(code)
        if row is None:
            raise CommandError(
                f"{code} is on neither DMC table, so there is no role and no "
                f"plan to build a card from.")

        targets, table, columns = roster_target_row(code)
        write("")
        write(f"{row.staff_name or '(no name)'}  ·  {code}")
        write(f"  role    {row.staff_role or '(none)'}")
        write(f"  branch  {row.staff_branch or row.staff_unit or '(none)'}")
        write(f"  plan    {table or '(no row on either table)'}")
        if table and table != STAFF_TABLE:
            write(self.style.WARNING(
                "          ^ the BRANCH table. Correct for a BBM, whose own "
                "row IS the branch row;"))
            write(self.style.WARNING(
                "            for anybody else it means they have no row on "
                f"{STAFF_TABLE}."))

        if options["targets"]:
            write("")
            write(f"  {'column':<40} value")
            for column in sorted(columns):
                write(f"  {column:<40}{_money(targets.get(column))}")
            missing = [c for c in sorted(columns) if targets.get(c) is None]
            if missing:
                write("")
                write(f"  {len(missing)} of {len(columns)} columns are blank "
                      f"on this row.")
            return

        card = build_card(code)
        if not card.get("has_card"):
            raise CommandError(f"{card.get('reason')}: {card.get('detail')}")

        for group in card["perspectives"]:
            write("")
            write(self.style.MIGRATE_HEADING(
                f"{group['perspective']}   ({group['weight'] * 100:.1f}%)"))
            for line in group["lines"]:
                write(f"  {line['kpi_name'][:46]:<48}"
                      f"{line['weight'] * 100:>6.1f}%")
                write(f"      target  {line['target_field'] or '(none)':<34}"
                      f"{_money(line['annual_target'])}  for the year")
                write(f"      ytd     {'pro-rated to ' + (line['as_at_date'] or 'today'):<34}"
                      f"{_money(line['ytd_target'])}")
                if line["pending"]:
                    write(self.style.WARNING(
                        f"      actual  not scored - {line['pending']}"))
                else:
                    write(f"      actual  {line['as_at'] or '':<34}"
                          f"{_money(line['ytd_actual'])}")
                    write(f"      score   {line['score'] * 100:>6.1f}%"
                          f"   weighted {line['weighted_score'] * 100:>6.2f}%")

        write("")
        write(self.style.SUCCESS(
            f"Performance score {card['performance_score'] * 100:.1f}%  "
            f"({card['scored_lines']} of "
            f"{card['scored_lines'] + card['pending_lines']} lines scored)"))
        write("")
