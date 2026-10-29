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

        # The template feeds two things: the cards computed from the
        # scorecards workbook's own formulas (every month, below), and the
        # per-line figures the live engine reads for anyone the workbook's
        # List does not hold (further down, as before).
        from . import bo_workbook

        try:
            actuals_book = bo_workbook.read_actuals(upload)
        except Exception as exc:  # noqa: BLE001
            return Response({"file": f"That template could not be read: "
                                     f"{exc}"}, status=400)
        upload.seek(0)
        cards = self._cards_report(bo_workbook.saved("scorecards"),
                                   actuals_book)

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
        bo_workbook.save_file("actuals", actuals_book, upload.name, who)
        book = bo_workbook.saved("scorecards")
        if book is not None:
            cards["stored"] = bo_workbook.rebuild(book, actuals_book, who)
        return Response({
            "applied": True, "report": report, "written": written,
            "cards": cards,
            "detail": (f"Saved {written:,} figure(s)."
                       + (f" {cards['stored']:,} back-office card-month(s) "
                          f"computed from the scorecards workbook."
                          if cards.get("stored") else
                          " Load the back-office scorecards workbook (.xlsb) "
                          "here too, and every card is computed from its own "
                          "formulas.")),
        })

    @staticmethod
    def _cards_report(book, actuals_book):
        from . import bo_workbook

        if book is None or actuals_book is None:
            return {"ready": False,
                    "missing": "scorecards" if book is None else "actuals"}
        report = bo_workbook.check(book, actuals_book)
        report["ready"] = True
        return report

    def _scorecards(self, upload, apply, who):
        """The scorecards .xlsb: the cards' own formulas, the List, Constants.
        """
        from . import bo_workbook

        try:
            book = bo_workbook.read_scorecards(upload)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response({"file": f"That workbook could not be read: "
                                     f"{exc}"}, status=400)
        actuals_book = bo_workbook.saved("actuals")
        cards = self._cards_report(book, actuals_book)
        if not apply:
            return Response({
                "applied": False, "cards": cards,
                "detail": ("Read the back-office scorecards workbook. "
                           "Nothing has been saved yet."
                           + ("" if actuals_book is not None else
                              " No actuals template is loaded yet - load "
                              "2026_BO_Actual_Template.xlsx here as well."))})
        bo_workbook.save_file("scorecards", book, upload.name, who)
        if actuals_book is not None:
            cards["stored"] = bo_workbook.rebuild(book, actuals_book, who)
        return Response({
            "applied": True, "cards": cards,
            "detail": ("Saved the scorecards workbook."
                       + (f" {cards['stored']:,} card-month(s) computed."
                          if cards.get("stored") else
                          " Load the actuals template next, and the cards "
                          "are computed."))})


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

        label = ("Leave balance list" if kind == hr.LEAVE
                 else "Employee listing")
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
