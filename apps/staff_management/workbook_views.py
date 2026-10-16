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
                    f"Nothing has been saved yet - send it again with apply "
                    f"to save."),
            })

        written = workbook.save(
            entries, who=getattr(request.user, "username", ""))
        return Response({
            "applied": True, "report": report, "written": written,
            "detail": (f"Saved {written['actuals']} actual(s) and "
                       f"{written['targets']} target(s). They show on the "
                       f"cards straight away - a card is computed when it is "
                       f"opened - marked as entered rather than measured."),
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
        if not upload.name.lower().endswith((".xlsx", ".xlsm")):
            return Response(
                {"file": f"{upload.name} is not an Excel workbook. The "
                         f"back-office template is an .xlsx."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)

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

        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                              "yes"):
            return Response({
                "applied": False, "report": report,
                "detail": (
                    f"Read {report['figures']:,} figure(s) for "
                    f"{report['people']} people, to "
                    f"{report['reporting_month']}. {planned['written']:,} "
                    f"would be written for {planned['people']} people. "
                    f"Nothing has been saved yet - send it again with apply "
                    f"to save."),
            })

        written = bo_actuals.save(
            entries, who=getattr(request.user, "username", ""))
        return Response({
            "applied": True, "report": report, "written": written,
            "detail": (f"Saved {written:,} figure(s). They show on the cards "
                       f"straight away - a card is computed when it is "
                       f"opened."),
        })


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
