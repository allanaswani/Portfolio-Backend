"""Uploading the desk's scorecard workbook.

The command does the same job, but it needs the file on the host - and the
workbook lives on somebody's laptop, so "copy it to the server first" is the
step that stops this being used. This is the upload.

Reads and reports first; writes only when asked again with ``apply``. The
figures are part of what people are paid on, and the report is worth reading:
it says which cards reached nobody, which lines the platform measures for
itself and will not take from a spreadsheet, and anything it could not map.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import scorecard_workbook as workbook

_TAG = "Scorecard Automation"


from core.permissions import is_admin_viewer  # noqa: E402


def may_load(user):
    """The same gate as the Figures-to-load screen, and for the same reason:
    this sets what people are measured on. ``is_staff`` is legacy noise."""
    return bool(
        user and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(
                 name__in=("staff_mgt", "Management", "hr")).exists()))


def _allocation_year(request):
    """Which performance year the allocation is for.

    The workbook's own ``Constants`` sheet says, and the request may override
    it. Falling back to the current year rather than refusing: a target
    written against the wrong year is correctable, and refusing the whole
    upload over a year nobody typed is not.
    """
    import datetime

    raw = str(request.data.get("year", "")).strip()
    if raw.isdigit():
        return int(raw)
    return datetime.date.today().year


def _read_allocation(request, upload):
    """What "Summary Allocation" would give → ``(summary, year)``.

    Never raises. The role cards are worth loading on their own, so a sheet
    this cannot read costs its own section and says why.
    """
    from apps.staff_management.scorecard_automation.models import ScKpi
    from apps.staff_management.scorecard_ingest import read_allocation

    year = _allocation_year(request)
    blank = {"targets": 0, "people": 0, "by_kpi": {}, "warnings": [],
             "why": ""}

    definitions = list(ScKpi.objects.filter(is_active=True)
                       .exclude(allocation_column=""))
    if not definitions:
        blank["why"] = ("no KPI names a column on that sheet, so there is "
                        "nothing to read it for.")
        return blank, year

    try:
        upload.seek(0)
        rows, warnings = read_allocation(upload, definitions)
    except Exception as exc:  # noqa: BLE001 - the cards still load
        blank["why"] = f"that sheet could not be read: {exc}"
        return blank, year

    by_kpi = {}
    for row in rows:
        by_kpi[row["kpi_code"]] = by_kpi.get(row["kpi_code"], 0) + 1

    return {
        "targets": len(rows),
        "people": len({r["sales_code"] for r in rows}),
        "by_kpi": by_kpi,
        "warnings": warnings[:20],
        "why": "" if rows else "that sheet carried no rows this run.",
    }, year


def _write_allocation(request, upload, year, who=""):
    """Write the per-person targets. Never raises."""
    from apps.staff_management.scorecard_automation.models import ScKpi
    from apps.staff_management.scorecard_ingest import (
        apply_allocation, read_allocation)

    definitions = list(ScKpi.objects.filter(is_active=True)
                       .exclude(allocation_column=""))
    if not definitions:
        return {"created": 0, "updated": 0, "unchanged": 0}
    try:
        upload.seek(0)
        rows, _warnings = read_allocation(upload, definitions)
        return apply_allocation(
            rows, year, source_label="scorecard workbook", changed_by=who)
    except Exception as exc:  # noqa: BLE001 - the cards are already saved
        return {"created": 0, "updated": 0, "unchanged": 0,
                "error": str(exc)}


@extend_schema(tags=[_TAG])
class ScorecardWorkbookUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 40 * 1024 * 1024

    def post(self, request):
        if not may_load(request.user):
            return Response(
                {"detail": "Only an administrator can load the scorecard "
                           "workbook."}, status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the workbook first."}, status=400)
        if not upload.name.lower().endswith((".xlsb", ".xlsm", ".xlsx")):
            return Response(
                {"file": f"{upload.name} is not an Excel workbook. The "
                         f"scorecards file is an .xlsb."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)

        try:
            cards, report = workbook.read_upload(upload)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response(
                {"file": f"That workbook could not be read: {exc}"},
                status=400)

        if not cards:
            return Response({
                "applied": False, "report": report,
                "detail": "No cards were read. The workbook needs its role "
                          "sheets, with a staff name in row 2 and a feed key "
                          "in column M.",
            }, status=400)

        entries, planned = workbook.plan(cards)
        report.update(planned)
        report["to_write"] = len(entries)

        # ── and the rest of the workbook ──────────────────────────────────
        # The role sheets are ten worked examples. "Summary Allocation" is
        # the actual plan: a row per person, with their own target for every
        # measure that takes one - 99 people where the cards cover ten.
        # Reading only the cards is why Direct Portfolio Contribution said
        # "no target is set" for a figure sitting in the same file.
        allocation, allocation_year = _read_allocation(request, upload)
        report["allocation"] = allocation

        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                              "yes"):
            return Response({
                "applied": False, "report": report,
                "detail": (
                    f"Read {len(cards)} card(s) and {report['lines']} line(s). "
                    f"{planned['actuals']} actual(s) and {planned['targets']} "
                    f"target(s) would be written, of which "
                    f"{planned['behind_a_live_source']} sit behind a figure "
                    f"the platform measures itself and will only fill a "
                    f"blank. "
                    + (f"Summary Allocation carries {allocation['targets']} "
                       f"target(s) for {allocation['people']} people, which "
                       f"would be written for {allocation_year}. "
                       if allocation["targets"] else
                       f"Summary Allocation gave nothing: "
                       f"{allocation['why']} ")
                    + f"Nothing has been saved yet - send it again with "
                      f"apply to save."),
            })

        written = workbook.save(
            entries, who=getattr(request.user, "username", ""))

        allocated = _write_allocation(
            request, upload, allocation_year,
            who=getattr(request.user, "username", ""))
        report["allocation_written"] = allocated

        return Response({
            "applied": True, "report": report, "written": written,
            "detail": (
                f"Saved {written['actuals']} actual(s) and "
                f"{written['targets']} target(s) from the role cards"
                + (f", and {allocated['created'] + allocated['updated']} "
                   f"per-person target(s) for {allocation['people']} people "
                   f"from Summary Allocation"
                   if allocated.get("created") or allocated.get("updated")
                   else "")
                + ". They show on the cards straight away - a card is "
                  "computed when it is opened."),
        })


@extend_schema(tags=[_TAG])
class BoActualsUploadView(APIView):
    """The back-office actuals template.

    A different shape from the sales workbook and a far bigger reach: 37
    sheets, a row per person and a column per month, so one upload fills
    every back-office card rather than ten.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 40 * 1024 * 1024

    def post(self, request):
        from . import bo_actuals

        if not may_load(request.user):
            return Response(
                {"detail": "Only an administrator can load the back-office "
                           "actuals."}, status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the template first."},
                            status=400)
        if not upload.name.lower().endswith((".xlsx", ".xlsm", ".xlsb")):
            return Response(
                {"file": f"{upload.name} is not an Excel workbook. The "
                         f"back-office template is an .xlsx, the scorecards "
                         f"workbook an .xlsb."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)
        apply = str(request.data.get("apply", "")).lower() in ("1", "true",
                                                               "yes")
        who = getattr(request.user, "username", "")

        if upload.name.lower().endswith(".xlsb"):
            return self._scorecards(upload, apply, who)

        # The actuals template. Which workbook's it is, its own sheets say.
        from . import workbook_cards

        data = upload.read()
        upload.seek(0)
        if workbook_cards.is_ib_workbook(data):
            return self._ib_scorecards(data, upload.name, apply, who)
        if workbook_cards.is_hfdi_workbook(data):
            return self._ib_scorecards(data, upload.name, apply, who,
                                       kind=workbook_cards.HFDI)
        own_card = workbook_cards.read_rbo_person_card(data)
        if own_card is not None:
            return self._rbo_person_card(own_card, upload.name, apply, who)
        if workbook_cards.is_retail_bo_workbook(data):
            return self._retail_bo(data, upload.name, apply, who)
        from . import rbo_live_feeds

        mapping = rbo_live_feeds.read_tat_mapping(data)
        if mapping is not None:
            # 2026_loan_tat_mapping.xlsx: the desk's product -> analyst
            # category table the credit analysts' TAT lines are split by.
            split = mapping["split"]
            head = (f"Read the loan TAT mapping: {len(mapping['categories'])} product "
                    f"codes into {len(set(mapping['categories'].values()))} analyst "
                    f"categories; {split['category']} split at {split['at']:,.0f}.")
            if not apply:
                return Response({"applied": False, "cards": {"mapping": mapping},
                                 "detail": head + " Nothing has been saved yet."})
            workbook_cards.save_file(rbo_live_feeds.MAPPING_KIND, mapping,
                                     upload.name, who)
            return Response({"applied": True, "cards": {"mapping": mapping},
                             "detail": head + " Saved; the analysts' TAT lines read "
                                              "by it from now on."})
        if workbook_cards.is_probation_workbook(data):
            return self._probation(data, upload.name, apply, who)

        try:
            actuals_book = workbook_cards.read_actuals(upload)
        except Exception as exc:  # noqa: BLE001
            return Response({"file": f"That template could not be read: "
                                     f"{exc}"}, status=400)
        upload.seek(0)
        kind = workbook_cards.actuals_book(actuals_book)
        spec = workbook_cards.SPECS[kind]
        # Which year's template: the template does not say, so the desk does
        # (the page sends it). Without one, the year of the newest scorecards
        # workbook loaded for it, else this year.
        year = self._year(request, spec)
        if isinstance(year, Response):
            return year

        # IB and HFDI report their own proof (_ib_apply); the back-office check
        # below would compute every card a second time (HFDI: 18 s -> 29 s).
        if kind in (workbook_cards.IB, workbook_cards.HFDI):
            if kind == workbook_cards.IB and apply:
                # Its account sheet, for ib_feed_probe (the cards never read it).
                accounts = workbook_cards.ib_portfolio(data)
                if accounts:
                    workbook_cards.save_file(workbook_cards.IB_PORTFOLIO_KIND, accounts,
                                             upload.name, who, year=year)
            return self._ib_apply(workbook_cards.saved(spec.files[0], year),
                                  actuals_book, year, upload.name, apply, who,
                                  save_actuals=True, kind=kind)

        cards = self._cards_report(workbook_cards.saved(spec.files[0], year),
                                   actuals_book, spec)
        cards["year"] = year

        if kind == workbook_cards.SALES:
            # The sales template: the sales workbook's cards, every closed
            # month. (Its per-line figures for the live card still load on
            # the sales actuals section, as before.)
            if not apply:
                return Response({"applied": False, "cards": cards,
                                 "detail": "Read the sales actuals template. "
                                           "Nothing has been saved yet."})
            workbook_cards.save_file(spec.files[1], actuals_book, upload.name,
                                     who, year=year)
            # The branch business workbook reads this same template.
            details = [f"Saved as the {year} template."]
            for other in workbook_cards.SPECS.values():
                if other.files[1] != spec.files[1]:
                    continue
                book = workbook_cards.saved(other.files[0], year)
                if book is None:
                    continue
                stored = workbook_cards.rebuild(book, actuals_book, who)
                details.append(f"{stored:,} {other.label} card-month(s) "
                               f"computed.")
                if other is spec:
                    cards["stored"] = stored
            return Response({"applied": True, "cards": cards,
                             "detail": " ".join(details) or
                             self._stored_detail(cards, spec)})

        # The back-office template feeds two things: the cards computed from
        # the scorecards workbook's own formulas (every month), and the
        # per-line figures the live engine reads for anyone the workbook's
        # List does not hold.
        try:
            rows, report = bo_actuals.read_upload(upload)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response(
                {"file": f"That template could not be read: {exc}"},
                status=400)
        if not rows:
            return Response({
                "applied": False, "report": report,
                "detail": "Nothing was read. The template needs its measure "
                          "sheets, each with StaffSalesCode and a column per "
                          "month.",
            }, status=400)

        entries, planned = bo_actuals.plan(rows)
        report.update(planned)

        if not apply:
            return Response({
                "applied": False, "report": report, "cards": cards,
                "detail": (
                    f"Read {report['figures']:,} figure(s) for "
                    f"{report['people']} people, to "
                    f"{report['reporting_month']}. {planned['written']:,} "
                    f"would be written for {planned['people']} people. "
                    f"Nothing has been saved yet - send it again with apply "
                    f"to save."),
            })

        written = bo_actuals.save(entries, who=who)
        workbook_cards.save_file(spec.files[1], actuals_book, upload.name, who,
                                 year=year)
        book = workbook_cards.saved(spec.files[0], year)
        if book is not None:
            cards["stored"] = workbook_cards.rebuild(book, actuals_book, who)
        return Response({
            "applied": True, "report": report, "written": written,
            "cards": cards,
            "detail": f"Saved {written:,} figure(s) as the {year} template. "
                      + self._stored_detail(cards, spec),
        })

    @staticmethod
    def _year(request, spec):
        """The year a template is for → int, or a 400 Response."""
        import datetime

        from . import workbook_cards

        raw = str(request.data.get("year") or "").strip()
        if raw:
            if not raw.isdigit() or not 2000 < int(raw) < 2100:
                return Response({"year": f"{raw} is not a year."}, status=400)
            return int(raw)
        years = workbook_cards.stored_years(spec.files[0])
        return years[-1] if years else datetime.date.today().year

    @staticmethod
    def _stored_detail(cards, spec):
        if cards.get("stored"):
            return (f"{cards['stored']:,} {spec.label} card-month(s) computed "
                    f"from the workbook's own formulas.")
        return (f"Load the {spec.label} "
                + ("actuals template (.xlsx)" if cards.get("missing") ==
                   "actuals" else "scorecards workbook (.xlsb)")
                + " here too, and every card is computed from its formulas.")

    @staticmethod
    def _cards_report(book, actuals_book, spec):
        from . import workbook_cards

        if book is None or actuals_book is None:
            return {"ready": False, "book": spec.book,
                    "missing": "scorecards" if book is None else "actuals"}
        report = workbook_cards.check(book, actuals_book)
        report["ready"] = True
        return report

    def _scorecards(self, upload, apply, who):
        """A scorecards .xlsb: the cards' own formulas, the List, Constants.
        Back office or sales - the workbook's own sheets say which."""
        from . import workbook_cards

        try:
            book = workbook_cards.read_scorecards(upload)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response({"file": f"That workbook could not be read: "
                                     f"{exc}"}, status=400)
        spec = workbook_cards.spec_of(book)
        # A scorecards workbook says its own year (Constants), and is kept as
        # that year's: loading 2027's leaves every 2026 card as it was.
        year = workbook_cards.book_year(book)
        actuals_book = workbook_cards.saved(spec.files[1], year)
        if actuals_book is not None and year not in workbook_cards.stored_years(
                spec.files[1]):
            actuals_book = None  # another year's template is not this book's
        # Stored as read; the probation joiners' cards ride on it wherever it
        # is computed (saved() adds them on every read).
        raw = book
        book = workbook_cards.with_probation(book, year)
        cards = self._cards_report(book, actuals_book, spec)
        cards["year"] = year
        if not apply:
            return Response({
                "applied": False, "cards": cards,
                "detail": (f"Read the {spec.label} scorecards workbook for "
                           f"{year}. Nothing has been saved yet.")})
        workbook_cards.save_file(spec.files[0], raw, upload.name, who,
                                 year=year)
        if actuals_book is not None:
            cards["stored"] = workbook_cards.rebuild(book, actuals_book, who)
        return Response({
            "applied": True, "cards": cards,
            "detail": (f"Saved the {spec.label} scorecards workbook for "
                       f"{year}. " + self._stored_detail(cards, spec))})

    def _rbo_person_card(self, card, file_name, apply, who):
        """One retail back office person's own card file: its per-line
        figures fill the lines whose return has no row for them."""
        from . import workbook_cards as wc

        book = wc.saved(wc.SPECS[wc.RETAIL_BO].files[0])
        people = [h for h in (wc.holders(book, keep_off=True) if book else [])
                  if h.name.strip().lower() == card["name"].lower()]
        if len(people) != 1:
            return Response({"file": (
                f"{card['name']!r} is on the retail back office List "
                f"{len(people)} times - a card is loaded only onto exactly one "
                f"person. Load the retail back office workbook first if it is "
                f"not loaded.")}, status=400)
        person = people[0]
        lines = "\n".join(f"  {feed}: {value:,.4g}" for feed, value in
                          sorted(card["figures"].items()))
        head = (f"{card['name']} ({person.sales_code}), {card['role']}, "
                f"{card['month']}: {len(card['figures'])} line figure(s) - each "
                f"used only where that line's return has no row for them.\n{lines}")
        if not apply:
            return Response({"applied": False, "cards": {"book": "rbo_card"},
                             "detail": head + "\nNothing has been saved yet."})
        entries = dict(wc.saved(wc.RBO_CARD_FIGURES) or {})
        entries[person.sales_code] = dict(card, file=file_name)
        wc.save_file(wc.RBO_CARD_FIGURES, entries, file_name, who)
        return Response({"applied": True, "cards": {"book": "rbo_card"},
                         "detail": head + "\nSaved."})

    def _ib_scorecards(self, data, file_name, apply, who, kind=None):
        """The Institutional Banking (.xlsm) or HFDI Master (.xlsm)
        scorecards workbook."""
        import io

        from . import workbook_cards as wc

        kind = kind or wc.IB
        reader = wc.read_hfdi if kind == wc.HFDI else wc.read_ib
        try:
            book = reader(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response({"file": f"That workbook could not be read: {exc}"},
                            status=400)
        year = wc.book_year(book)
        spec = wc.SPECS[kind]
        actuals = (wc.saved(spec.files[1], year)
                   if year in wc.stored_years(spec.files[1]) else None)
        return self._ib_apply(book, actuals, year, file_name, apply, who,
                              save_book=True, kind=kind)

    def _ib_apply(self, book, actuals, year, file_name, apply, who,
                  save_book=False, save_actuals=False, kind=None):
        """Report (and with ``apply`` save) the IB workbook and/or template.
        With both, every card holder's card for the month the desk last ran
        is recomputed and set beside the score the desk's macro recorded on
        Monthly_Summary - each difference named. Like the back-office and
        sales templates, a difference does not refuse the load: the stored
        card carries the desk's recorded score beside its own."""
        from . import workbook_cards as wc

        kind = kind or wc.IB
        spec = wc.SPECS[kind]
        short = "IB" if kind == wc.IB else "HFDI"
        report = {"book": kind, "year": year, "ready": bool(book and actuals)}
        lines = []
        if book is not None:
            report["problems"] = book.get("problems", [])
            people = [h for h in wc.holders(book) if h.sheet in book["cards"]]
            report["people"] = len(people)
            report["month"] = wc.ib_run_month(book)
        if book is not None and actuals is not None:
            proof = wc.ib_proof(book, actuals)
            compared = [p for p in proof if p["desk"] is not None]
            same = sum(1 for p in compared if p["same"])
            report.update({"proof": proof, "same": same, "compared": len(compared)})
            lines.append(f"{same} of {len(compared)} cards the desk scored for month "
                         f"{report['month']} recompute to its recorded score.")
            for p in proof:
                if p["desk"] is None:
                    lines.append(f"  {p['sales_code']} {p['name']}: {p['why']} - "
                                 f"computed {p['computed']!s:.6}")
                elif not p["same"]:
                    lines.append(f"  {p['sales_code']} {p['name']}: desk "
                                 f"{p['desk']:.4%}, computed {p['computed']!s:.6} - "
                                 f"the template's figures differ from those the "
                                 f"desk ran this card on")
        elif book is None:
            lines.append(f"Load the {year} {short} scorecards workbook (.xlsm) too, and "
                         f"every card is computed from its formulas.")
        else:
            lines.append(f"Load the {year} {short} actuals template (.xlsx) too, and "
                         f"every card is computed from its formulas.")
        what = (f"{short} scorecards workbook" if save_book else f"{short} actuals template")
        head = f"Read the {what} for {year}."
        if not apply:
            return Response({"applied": False, "cards": report,
                             "detail": "\n".join([head] + lines
                                                 + ["Nothing has been saved yet."])})
        if save_book:
            wc.save_file(spec.files[0], book, file_name, who, year=year)
        if save_actuals:
            wc.save_file(spec.files[1], actuals, file_name, who, year=year)
        if book is not None and actuals is not None:
            report["stored"] = wc.rebuild(book, actuals, who)
            lines.append(f"Saved. {report['stored']:,} card-month(s) computed.")
        else:
            lines.append("Saved.")
        return Response({"applied": True, "cards": report,
                         "detail": "\n".join([head] + lines)})

    def _retail_bo(self, data, file_name, apply, who):
        """The Retail Back Office scorecards workbook (.xlsm): credit
        analysts, product managers, sector RMs and trade. Its cards run on
        its own formulas; the figures its actuals template would give come,
        for the month it was last run, off the cards as the desk ran them."""
        import io

        from . import workbook_cards as wc

        try:
            book, actuals = wc.read_retail_bo(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response({"file": f"That workbook could not be read: {exc}"},
                            status=400)
        year = wc.book_year(book)
        month = wc.rbo_run_month(book)
        proof = wc.rbo_proof(book, actuals)
        same = sum(1 for p in proof if p["same"])
        people = [h for h in wc.holders(book) if h.sheet in book["cards"]]
        lines = "\n".join(
            f"  {p['sheet']}: {p['name']} - desk {p['desk']!s:.6}, recomputed "
            f"{p['computed']!s:.6} {'same' if p['same'] else 'DIFFERENT'}"
            for p in proof)
        report = {"book": wc.RETAIL_BO, "year": year, "month": month,
                  "people": len(people), "proof": proof, "same": same,
                  "problems": book.get("problems", [])}
        head = (f"Read the retail back office scorecards workbook for {year}: "
                f"{len(people)} people on {len({h.sheet for h in people})} cards, "
                f"last run for month {month}. {same} of {len(proof)} cards "
                f"recompute to the score the desk's run gives:\n{lines}")
        if same != len(proof):
            return Response({"applied": False, "cards": report,
                             "detail": head + "\nNot saved: every card must "
                                              "recompute to the desk's score."},
                            status=400)
        if not apply:
            return Response({"applied": False, "cards": report,
                             "detail": head + "\nNothing has been saved yet."})
        spec = wc.SPECS[wc.RETAIL_BO]
        wc.save_file(spec.files[0], book, file_name, who, year=year)
        wc.save_file(spec.files[1], actuals, file_name, who, year=year)
        report["stored"] = wc.rebuild(book, actuals, who)
        return Response({"applied": True, "cards": report,
                         "detail": head + f"\nSaved. {report['stored']:,} card-month(s) "
                                          f"computed."})

    def _probation(self, data, file_name, apply, who):
        """The mortgage business probation workbook (.xlsm): the desk's card
        and targets for the Mortgage Business ARMs on probation whom the
        sales workbook's Summary Allocation does not carry (see
        workbook_cards.with_probation)."""
        import datetime
        import io

        from . import workbook_cards as wc

        try:
            probation = wc.read_probation(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response({"file": f"That workbook could not be read: {exc}"},
                            status=400)
        year = probation["year"]
        sales = wc.SPECS[wc.SALES]
        # The sales workbook as stored - not through saved(), which would add
        # the probation workbook already loaded rather than this one.
        book = self._sales_raw(year)
        if book is None:
            return Response({"file": f"Load the {year} sales scorecards workbook "
                                     f"(.xlsb) first: the probation cards run over "
                                     f"its List and Constants."}, status=400)
        merged = wc.with_probation(book, year, probation=probation)
        people = merged.get("probation") or {}
        on_card = {h.sales_code: h for h in wc.holders(merged)
                   if h.sales_code in people}
        report = {
            "year": year,
            "people": [{"sales_code": c, "name": on_card[c].name, "card": s,
                        # The first month the card scores.
                        "targets_from": wc.probation_start(merged, on_card[c]) + 1}
                       for c, s in sorted(people.items()) if c in on_card],
            "problems": probation.get("problems", []) + [
                p for p in merged.get("problems", []) if "probation" in p.lower()],
        }
        who_list = "\n".join(
            f"  {p['sales_code']}  {p['name']}: {p['card']} card, scored from "
            f"{datetime.date(year, p['targets_from'], 1):%B}"
            if p["targets_from"] <= 12 else f"  {p['sales_code']}  {p['name']}"
            for p in report["people"])
        problems = "".join(f"\n  {p}" for p in report["problems"][:10])
        if not apply:
            return Response({
                "applied": False, "cards": report,
                "detail": (f"Read the mortgage probation workbook for {year}: "
                           f"{len(report['people'])} person(s) the sales Summary "
                           f"Allocation does not carry will be scored on its card. "
                           f"Nothing has been saved yet.\n{who_list}{problems}")})
        wc.save_file(wc.PROBATION_KIND, probation, file_name, who, year=year)
        actuals = wc.saved(sales.files[1], year)
        stored = 0
        if actuals is not None and people:
            results = wc.compute_all(merged, actuals, only=set(people))
            stored = wc.store(results, wc.book_year(merged),
                              wc.recorded_scores(merged), loaded_by=who)
        report["stored"] = stored
        return Response({
            "applied": True, "cards": report,
            "detail": (f"Saved the mortgage probation workbook for {year}. "
                       f"{len(report['people'])} person(s) are scored on its card"
                       + (f"; {stored:,} card-month(s) computed." if stored else
                          "; their months are computed when the sales actuals "
                          "template is loaded." if actuals is None else ".")
                       + f"\n{who_list}{problems}")})

    @staticmethod
    def _sales_raw(year):
        """The sales workbook as stored, without the probation cards in."""
        from .models import BoWorkbookFile
        from . import workbook_cards as wc

        kind = wc.SPECS[wc.SALES].files[0]
        found = wc._year_for(kind, year)
        row = (BoWorkbookFile.objects.filter(kind=wc.year_kind(kind, found)).first()
               if found is not None else None)
        return row.payload if row is not None else None


@extend_schema(tags=[_TAG])
class ScorecardCardsUploadView(APIView):
    """Load people's own signed scorecards - many at a time.

    The master workbook carries one card per ROLE, so loading it reaches ten
    people. Everybody else has their own file in the same layout, with their
    own targets on it, and those targets exist nowhere else: Lydia Apanja's
    Income Contribution target is on Lydia Apanja's card, and the master
    workbook's Personal Banking sheet is Vincent Ogare's.

    Several files in one request, because there is one per person and
    uploading them singly is how a desk gives up half way.

    Two steps, as everywhere else here: the first call reads and reports,
    writing nothing, and only a second call carrying ``apply`` saves.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 10 * 1024 * 1024
    MAX_FILES = 200

    def post(self, request):
        from . import scorecard_cards

        if not may_load(request.user):
            return Response(
                {"detail": "Only an administrator can load scorecards."},
                status=403)

        uploads = request.FILES.getlist("files") or (
            [request.FILES["file"]] if "file" in request.FILES else [])
        if not uploads:
            return Response(
                {"files": "Choose the scorecard files first. Several at once "
                          "is fine - there is one per person."}, status=400)
        if len(uploads) > self.MAX_FILES:
            return Response(
                {"files": f"{len(uploads)} files at once; the limit is "
                          f"{self.MAX_FILES}."}, status=400)

        cards, skipped = [], []
        for upload in uploads:
            if upload.size > self.MAX_BYTES:
                skipped.append({"file": upload.name,
                                "why": "larger than 10 MB"})
                continue
            if not upload.name.lower().endswith((".xlsx", ".xlsm")):
                skipped.append({"file": upload.name,
                                "why": "not an Excel workbook"})
                continue
            try:
                cards.append(scorecard_cards.read_any(upload))
            except Exception as exc:  # noqa: BLE001 - the reason is useful
                skipped.append({"file": upload.name, "why": str(exc)})

        if not cards:
            return Response({
                "applied": False, "skipped": skipped,
                "detail": ("None of those files could be read as a "
                           "scorecard."),
            }, status=400)

        entries, report = scorecard_cards.plan_any(cards)
        report["skipped"] = skipped
        report["read"] = len(cards)

        matched = sum(1 for c in report["cards"] if c["matched"])
        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                               "yes"):
            return Response({
                "applied": False, "report": report,
                "detail": (
                    f"Read {len(cards)} card(s); {matched} matched somebody "
                    f"on the rosters. {report['targets']} target(s) and "
                    f"{report['actuals']} actual(s) would be written. "
                    f"Nothing has been saved yet - send it again with apply "
                    f"to save."),
            })

        written = scorecard_cards.save(
            entries, who=getattr(request.user, "username", ""))
        return Response({
            "applied": True, "written": written, "report": report,
            "detail": (f"Saved {written} figure(s) for {matched} person/"
                       f"people. They show on the cards straight away."),
        })


@extend_schema(tags=[_TAG])
class IfrsMovementUploadView(APIView):
    """Finance's IFRS movement workbook, a month at a time, into
    ``loans_mom_ifrs_movement``.

    The table stopped at 1 July 2025 because its only route in - the old
    system's CSV upload - was never carried over; every PAR and Loan Loss line
    has been reading July 2025 since. See ``staff_management.ifrs_movement``.

    - no ``month``: the months the workbook holds, and the months the table
      already has - so the screen knows what to load;
    - ``month`` (YYYY-MM): that month's rows and totals, written only with
      ``apply`` - which REPLACES the month, as the old upload did, so loading
      it twice never doubles it.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 60 * 1024 * 1024

    def post(self, request):
        import datetime
        import os
        import tempfile

        from apps.staff_management import ifrs_movement as im

        if not may_load(request.user):
            return Response(
                {"detail": "Only an administrator can load the IFRS "
                           "movement."}, status=403)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the workbook first."}, status=400)
        if not upload.name.lower().endswith(".xlsb"):
            return Response(
                {"file": f"{upload.name} is not the IFRS movement workbook - "
                         f"Finance's file is an .xlsb."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)

        # pyxlsb reads a path. A large upload already has one; a small one is
        # written out for the length of the request.
        made = None
        if hasattr(upload, "temporary_file_path"):
            path = upload.temporary_file_path()
        else:
            handle, made = tempfile.mkstemp(suffix=".xlsb")
            with os.fdopen(handle, "wb") as out:
                for chunk in upload.chunks():
                    out.write(chunk)
            path = made
        try:
            return self._handle(request, path, im, datetime)
        except im.IfrsWorkbookError as exc:
            return Response({"detail": str(exc)}, status=400)
        finally:
            if made:
                os.unlink(made)

    def _handle(self, request, path, im, datetime):
        in_book = im.months_in(path)
        held = [m.isoformat() for m in im.months_held()]
        raw = str(request.data.get("month", "")).strip()
        if not raw:
            return Response({
                "months_in_workbook": sorted(m.isoformat() for m in in_book),
                "months_in_table": held,
                "latest_in_table": held[-1] if held else None,
            })
        try:
            month = datetime.datetime.strptime(raw[:7], "%Y-%m").date()
        except ValueError:
            return Response({"month": "Which month? e.g. 2026-08"}, status=400)
        if month not in in_book:
            return Response(
                {"month": f"The workbook has no {month:%b %Y} sheet."},
                status=400)

        rows, totals = im.read_month(path, in_book[month])
        body = {
            "month": month.isoformat(), "sheet": in_book[month],
            "totals": totals, "already_in_table": month.isoformat() in held,
            "applied": False,
        }
        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                              "yes"):
            return Response(body)
        body["written"] = im.replace_month(month, rows)
        # Finance's customer -> RM map, which the Loan Loss line is attributed by.
        year, mapping = im.read_rm_map(path)
        if mapping:
            im.save_rm_map(year, mapping, getattr(request.user, "username", ""))
            body["rm_map_customers"] = len(mapping)
        body["applied"] = True
        return Response(body, status=201)


@extend_schema(tags=[_TAG])
class HrReportUploadView(APIView):
    """Aruti's leave balance list OR its employee listing - whichever the
    file is - stored as a snapshot for the date the report states.

    Reports from different months are kept side by side; loading a date
    again replaces only that date. Reads and reports first; writes only with
    ``apply``. See ``staff_management.hr_reports``.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 30 * 1024 * 1024

    def post(self, request):
        import os
        import tempfile

        from apps.staff_management import hr_reports as hr

        if not may_load(request.user):
            return Response({"detail": "Only an administrator can load HR "
                                       "reports."}, status=403)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the report first."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)

        handle, path = tempfile.mkstemp(suffix=".xls")
        try:
            with os.fdopen(handle, "wb") as out:
                for chunk in upload.chunks():
                    out.write(chunk)
            kind, as_of, rows, report = hr.read(path)
        except hr.HrReportError as exc:
            return Response({"detail": str(exc)}, status=400)
        finally:
            os.unlink(path)

        label = ((report.get("source") or "Leave balance list")
                 if kind == hr.LEAVE else "Employee listing")
        held = [d.isoformat() for d in hr.snapshots(kind)]
        body = {
            "report": kind, "label": label, "as_of": as_of.isoformat(),
            "summary": report, "dates_held": held,
            "replaces": as_of.isoformat() in held, "applied": False,
        }
        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                              "yes"):
            return Response(body)
        body["written"] = hr.replace_snapshot(kind, as_of, rows)
        body["applied"] = True
        body["dates_held"] = [d.isoformat() for d in hr.snapshots(kind)]
        return Response(body, status=201)


@extend_schema(tags=[_TAG])
class CardLayoutUploadView(APIView):
    """Card layouts from the sales or back-office scorecard workbook - which
    lines a card has, their order, perspective, wording and weight, and the
    role-wide targets.

    Reads and reports every difference first; writes only with ``apply``, in
    one transaction. See ``staff_management.card_layouts``.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 60 * 1024 * 1024

    def post(self, request):
        import os
        import tempfile

        from apps.staff_management import card_layouts as cl

        if not may_load(request.user):
            return Response({"detail": "Only an administrator can change the "
                                       "card layouts."}, status=403)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the workbook first."}, status=400)
        if not upload.name.lower().endswith(".xlsb"):
            return Response({"file": f"{upload.name} is not a scorecard "
                                     f"workbook (.xlsb)."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)

        made = None
        if hasattr(upload, "temporary_file_path"):
            path = upload.temporary_file_path()
        else:
            handle, made = tempfile.mkstemp(suffix=".xlsb")
            with os.fdopen(handle, "wb") as out:
                for chunk in upload.chunks():
                    out.write(chunk)
            path = made
        try:
            kind, cards = cl.read(path)
        except cl.LayoutError as exc:
            return Response({"detail": str(exc)}, status=400)
        finally:
            if made:
                os.unlink(made)

        plans = cl.plan(kind, cards)
        body = {"workbook": kind, "summary": cl.summary(plans),
                "cards": plans, "applied": False}
        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                              "yes"):
            return Response(body)
        body["written"] = cl.apply(
            plans, who=getattr(request.user, "username", ""))
        body["applied"] = True
        return Response(body, status=201)


def _card_reads(book, sheet):
    """The List columns a card's formulas look up (VLOOKUP into List)."""
    found = set()
    for tokens in book["cards"][sheet]["f"].values():
        for i, t in enumerate(tokens):
            if (t[:2] == ["a", "List"] and i + 3 < len(tokens)
                    and tokens[i + 1][0] == "n"
                    and tokens[i + 3][:2] == ["f", "VLOOKUP"]):
                found.add(int(t[3]) + int(tokens[i + 1][1]) - 1)
    return found


def _proration_effect(code):
    """Where this person has a card, and which proration columns it reads."""
    from apps.staff_management import workbook_cards as wc

    out = []
    for spec in wc.SPECS.values():
        book = wc.saved(spec.files[0])
        if book is None:
            continue
        holder = next((h for h in wc.holders(book, keep_off=True)
                       if h.sales_code == code and h.sheet in book["cards"]), None)
        if holder is None:
            continue
        columns = wc.proration_columns(book)
        reads = _card_reads(book, holder.sheet)
        out.append({"book": spec.label, "name": holder.name, "card": holder.sheet,
                    "role": holder.role,
                    "columns_on_list": sorted(columns),
                    "columns_the_card_reads": sorted(
                        name for name, i in columns.items() if i in reads)})
    return out


@extend_schema(tags=[_TAG])
class ProrationView(APIView):
    """Targets prorated for one person: joining, a new role, promotion,
    acting, sick or maternity leave. Fills the workbook List's own proration
    column for that person, month by month, so the card's formulas apply it
    as if the desk had typed it. See ``workbook_cards.PRORATION``.

    GET lists the entries. POST adds one: {sales_code, reason, from, to,
    note} - ``from`` alone (YYYY-MM, the start month) for joined /
    role_change / promotion; ``from`` and ``to`` for acting and leave.
    DELETE ?sales_code=&id= removes one. Either change recomputes that
    person's stored months.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management import workbook_cards as wc

        if not (may_load(request.user) or is_admin_viewer(request.user)):
            return Response({"detail": "Only an administrator can see "
                                       "proration."}, status=403)
        entries = wc.saved(wc.PRORATION) or {}
        return Response({
            "reasons": [{"reason": k, "column": v[0], "span": v[1], "label": v[2]}
                        for k, v in wc.PRORATION_REASONS.items()],
            "people": [{"sales_code": code, "entries": rows,
                        "cards": _proration_effect(code)}
                       for code, rows in sorted(entries.items()) if rows],
        })

    def post(self, request):
        import datetime
        import uuid

        from django.core.cache import cache

        from apps.staff_management import workbook_cards as wc

        if not may_load(request.user):
            return Response({"detail": "Only an administrator can prorate "
                                       "targets."}, status=403)
        data = request.data
        code = str(data.get("sales_code") or "").replace(" ", "").upper()
        reason = str(data.get("reason") or "")
        spec = wc.PRORATION_REASONS.get(reason)
        start = str(data.get("from") or "").strip()
        end = str(data.get("to") or "").strip()
        if not code:
            return Response({"sales_code": "Give the sales code."}, status=400)
        if spec is None:
            return Response({"reason": "Choose one of: "
                             + ", ".join(wc.PRORATION_REASONS)}, status=400)
        if wc._ym(start) is None:
            return Response({"from": "The month is YYYY-MM."}, status=400)
        if spec[1]:
            if wc._ym(end) is None:
                return Response({"to": "The last month away is YYYY-MM."},
                                status=400)
            if wc._ym(end) < wc._ym(start):
                return Response({"to": "The last month is before the first."},
                                status=400)
        else:
            end = ""
        cards = _proration_effect(code)
        if not cards:
            return Response({"sales_code": f"{code} is not on any loaded "
                             f"scorecard workbook's List."}, status=400)
        entry = {"id": uuid.uuid4().hex[:8], "reason": reason, "from": start,
                 "to": end, "note": str(data.get("note") or "")[:300],
                 "by": getattr(request.user, "username", ""),
                 "at": datetime.datetime.now().isoformat(timespec="seconds")}
        entries = dict(wc.saved(wc.PRORATION) or {})
        entries[code] = list(entries.get(code) or []) + [entry]
        wc.save_file(wc.PRORATION, entries, "proration",
                     getattr(request.user, "username", ""))
        cache.delete(wc.PRORATION)
        stored = wc.rescore(code)
        warnings = []
        for c in cards:
            used = wc.proration_column(entry, set(c["columns_on_list"]))
            if used is None or used not in c["columns_the_card_reads"]:
                warnings.append(f"{c['name']}'s {c['card']} card does not read "
                                f"{used or spec[0]}, so this entry changes nothing on it.")
        return Response({"entry": entry, "cards": cards,
                         "months_recomputed": stored, "warnings": warnings},
                        status=201)

    def delete(self, request):
        from django.core.cache import cache

        from apps.staff_management import workbook_cards as wc

        if not may_load(request.user):
            return Response({"detail": "Only an administrator can prorate "
                                       "targets."}, status=403)
        code = str(request.query_params.get("sales_code") or "").replace(
            " ", "").upper()
        ident = str(request.query_params.get("id") or "")
        entries = dict(wc.saved(wc.PRORATION) or {})
        rows = [e for e in entries.get(code) or [] if e.get("id") != ident]
        if len(rows) == len(entries.get(code) or []):
            return Response({"detail": "No such entry."}, status=404)
        entries[code] = rows
        wc.save_file(wc.PRORATION, entries, "proration",
                     getattr(request.user, "username", ""))
        cache.delete(wc.PRORATION)
        return Response({"removed": ident, "months_recomputed": wc.rescore(code)})
