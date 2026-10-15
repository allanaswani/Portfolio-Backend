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
                    f"target(s) would be written; {planned['measured_here']} "
                    f"line(s) are computed here and would be left alone. "
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
