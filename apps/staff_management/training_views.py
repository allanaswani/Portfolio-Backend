"""The training-returns screen.

HR circulate ``2026 Training Returns Template - <Mon>_<yy>.xlsx`` monthly, and
until it landed here a training line on all 22 cards said "recorded in the
learning system, not here".

Two endpoints, because the figures are a system extract rather than something
anybody types: a summary with one row per person, and an upload that reads and
reports before it writes. Nobody types hours in here — 289 people times twelve
months is not a form, and the return is the record.

``training/`` the year's figures and how far they reach
``training/upload/`` HR's workbook; reads and reports, writes on ``apply``

Who may load one: superuser, or ``staff_mgt`` / ``Management`` / ``hr``. HR
owns this return, which is why ``hr`` is on the list. Reading is open to any
signed-in user, because the hours are what somebody is scored on.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import training

_TAG = "Scorecard Automation"

#: ``cx`` is deliberately NOT here: the CX team maintain the survey, not the
#: training return. ``is_staff`` is deliberately not here either, as on every
#: screen that sets what people are measured on.
LOAD_GROUPS = ("staff_mgt", "Management", "hr")


def may_load(user):
    return bool(
        user and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(name__in=LOAD_GROUPS).exists()))


@extend_schema(tags=[_TAG])
class TrainingReturnsView(APIView):
    """The year's training hours, one row per person."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        year = str(request.query_params.get("year") or "").strip()
        year = int(year) if year.isdigit() else None
        search = str(request.query_params.get("search") or "")

        found = training.coverage(year)
        return Response({
            "year": found["year"],
            "may_load": may_load(request.user),
            "coverage": found,
            "rows": training.people(year, search),
            "detail": (
                "A training line sits on every one of the 22 scorecards. "
                "These are the hours behind it, from HR's monthly return."),
            # The one thing a reader has to understand to trust the numbers.
            "how_it_is_read": (
                "Year to date is the months added up, and it is sliced to the "
                "month the RETURN reaches - not to today, and not to the last "
                "month a person has a figure in. A blank month inside the "
                "return is no training that month; a blank month beyond it is "
                "simply not reported yet."),
        })


@extend_schema(tags=[_TAG])
class TrainingUploadView(APIView):
    """HR's return. Reads and reports; writes only when asked."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 20 * 1024 * 1024

    def post(self, request):
        if not may_load(request.user):
            return Response(
                {"detail": "Only HR or an administrator can load the training "
                           "return."}, status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the return first."}, status=400)
        if not upload.name.lower().endswith((".xlsx", ".xlsm")):
            return Response(
                {"file": f"{upload.name} is not an Excel workbook. Save it as "
                         f".xlsx and try again."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=400)

        try:
            rows, report = training.read_workbook(upload, upload.name)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response(
                {"file": f"That return could not be read: {exc}"}, status=400)

        if not rows:
            return Response({
                "applied": False, "report": report,
                "detail": "Nothing was read from that return. It needs a "
                          "sheet with a StaffPF or staff-code column and a "
                          "column per month.",
            }, status=400)

        if str(request.data.get("apply", "")).lower() not in ("1", "true", "yes"):
            return Response({
                "applied": False,
                "report": report,
                "figures": len(rows),
                "detail": (
                    f"Read {report['people']} people and {len(rows):,} "
                    f"figure(s) across {len(report['months'])} month(s). "
                    f"Nothing has been saved yet - send it again with apply "
                    f"to save."),
            })

        written = training.save(
            rows, who=getattr(request.user, "username", ""))
        found = training.coverage()
        return Response({
            "applied": True,
            "report": report,
            "written": written,
            "coverage": found,
            "detail": (f"Saved {written:,} figure(s) for {report['people']} "
                       f"people."),
        })
