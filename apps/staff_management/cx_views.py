"""The CX team's own screen: where contactability and CSAT are kept.

The ask behind this module, in the business's words: "can we have a place where
the CX team could be updating it instead of waiting for them to share the excel
sheet". So the editing comes first here and the upload second — the upload is
for the first load and for a quarter CX would rather paste in bulk, and after
that the figures are maintained in place.

Four endpoints:

``cx/``            the period's figures, and what is not matched to a roster
``cx/upload/``     CX's own workbook; reads and reports, writes on ``apply``
``cx/entry/``      one RM's figures, typed or corrected
``cx/segments/``   the per-segment NPS and CES, which no card reads yet

Who may change a figure: superuser, or ``staff_mgt`` / ``Management`` / ``hr``
/ ``cx``. The CX group is the point of the screen — until now the only way a
survey figure reached a card was an administrator retyping it off an e-mail.
Reading is open to any signed-in user, because an RM should be able to see the
figure they are scored on.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import cx_metrics

_TAG = "Scorecard Automation"

#: Groups that may change a figure. ``cx`` is the whole reason this exists;
#: ``is_staff`` is deliberately absent, as it is on every other screen that
#: sets what people are paid on - it is legacy noise in this estate.
EDIT_GROUPS = ("staff_mgt", "Management", "hr", "cx")


def may_edit(user):
    return bool(
        user and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(name__in=EDIT_GROUPS).exists()))


def _rows(period):
    from .models import CxRmMetric

    out = []
    for row in CxRmMetric.objects.filter(period=period):
        out.append({
            "id": row.id,
            "period": row.period,
            "rm_name": row.rm_name,
            "sales_code": row.sales_code,
            "contactability": row.contactability,
            "csat": row.csat,
            "full_marks": row.full_marks,
            "note": row.note,
            "source": row.source,
            "updated_at": row.updated_at,
            "updated_by": row.updated_by,
            # The one thing worth flagging on the screen: a name CX spell
            # differently from the roster is an RM with no score, and it looks
            # exactly like an RM CX did not survey.
            "matched": bool(row.sales_code),
        })
    return out


@extend_schema(tags=[_TAG])
class CxMetricsView(APIView):
    """One period's figures, with the two scorecard lines they feed."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        period = str(request.query_params.get("period") or "").strip()
        period = period or cx_metrics.latest_period() or ""
        return Response({
            "period": period,
            "may_edit": may_edit(request.user),
            "coverage": cx_metrics.coverage(period) if period else None,
            "rows": _rows(period) if period else [],
            # What these figures do, said on the screen rather than left in a
            # docstring - the people typing here are not the people who read
            # the scorecard code.
            "feeds": [
                {"line": "Portfolio Coverage (engagement)",
                 "field": "contactability", "target": 0.8,
                 "detail": "The Contactability sheet. Target 80%."},
                {"line": "Portfolio NPS",
                 "field": "csat", "target": 0.6,
                 "detail": "The Satisfaction sheet - the RM's own CSAT, which "
                           "is the figure the business scores this line on. "
                           "The per-segment NPS below is a different measure "
                           "and is not per RM, so no card reads it."},
            ],
        })


@extend_schema(tags=[_TAG])
class CxSegmentsView(APIView):
    """The per-segment NPS and CES.

    No scorecard line reads these: they are a segment figure, not a personal
    one. Kept and shown because they are the real NPS, they are in the same
    workbook, and discarding them would mean asking CX for them again the
    first time somebody wants them on a dashboard.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import CxSegmentMetric

        period = str(request.query_params.get("period") or "").strip()
        period = period or cx_metrics.latest_period() or ""
        rows = CxSegmentMetric.objects.filter(period=period)
        return Response({
            "period": period,
            "rows": [{"id": row.id, "segment": row.segment, "nps": row.nps,
                      "ces": row.ces, "is_overall": row.is_overall,
                      "updated_at": row.updated_at,
                      "updated_by": row.updated_by}
                     for row in rows],
            "detail": "Segment figures. No scorecard line is scored on these.",
        })


@extend_schema(tags=[_TAG])
class CxUploadView(APIView):
    """CX's own workbook. Reads and reports; writes only when asked.

    Two steps on purpose, the same as every other upload here: the first call
    says what the file contains and which names matched nobody, and only a
    second call with ``apply=true`` saves. These figures are part of somebody's
    bonus, and a silent import would be worse than no import.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 20 * 1024 * 1024

    def post(self, request):
        if not may_edit(request.user):
            return Response(
                {"detail": "Only the CX team or an administrator can load the "
                           "survey."}, status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the workbook first."}, status=400)
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
            rm_rows, segments, report = cx_metrics.read_workbook(
                upload, upload.name)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response(
                {"file": f"That workbook could not be read: {exc}"}, status=400)

        # The period comes off the file name. CX can override it, because a
        # file saved as "final v3" has no period in its name.
        asked = str(request.data.get("period") or "").strip()
        if asked:
            period = cx_metrics.period_of(asked)
            for row in rm_rows:
                row["period"] = period
            for row in segments:
                row["period"] = period
            report["period"] = period

        if not rm_rows and not segments:
            return Response({
                "applied": False,
                "report": report,
                "detail": "Nothing was read from that workbook. It needs a "
                          "Contactability or Satisfaction sheet with an 'RM "
                          "Name' column.",
            }, status=400)

        if str(request.data.get("apply", "")).lower() not in ("1", "true", "yes"):
            return Response({
                "applied": False,
                "report": report,
                "rows": rm_rows,
                "segments": segments,
                "detail": (
                    f"Read {report['rm_names']} RM(s) and "
                    f"{report['segments']} segment(s) for "
                    f"{report['period']}. Nothing has been saved yet - send "
                    f"it again with apply to save."),
            })

        written = cx_metrics.save(
            rm_rows, segments, who=getattr(request.user, "username", ""))
        return Response({
            "applied": True,
            "report": report,
            "written": written,
            "detail": (f"Saved {written['rm']} RM figure(s) and "
                       f"{written['segments']} segment figure(s) for "
                       f"{report['period']}."),
        })


@extend_schema(tags=[_TAG])
class CxEntryView(APIView):
    """One RM's figures, typed in or corrected.

    This is the screen's real job. A single figure arrives here, so a
    correction does not need a workbook and does not wait for the next
    quarterly file.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import CxRmMetric

        if not may_edit(request.user):
            return Response(
                {"detail": "Only the CX team or an administrator can set a "
                           "survey figure."}, status=403)

        data = request.data
        # No period sent means "the one on the screen", which is the newest
        # one loaded - NOT the quarter we happen to be in. Defaulting to today
        # would open a new period on the first typed figure, and because the
        # card reads the newest period, that one row would shadow the whole
        # loaded quarter for every RM.
        asked = str(data.get("period") or "").strip()
        period = (cx_metrics.period_of(asked) if asked
                  else (cx_metrics.latest_period() or cx_metrics.period_of("")))
        name = str(data.get("rm_name") or "").strip()
        if not name:
            return Response({"rm_name": "Whose figure is this?"}, status=400)

        values = {}
        for field in ("contactability", "csat"):
            if field not in data:
                continue
            raw = data.get(field)
            if raw in (None, ""):
                # Explicitly cleared, which is different from not sent.
                values[field] = None
                continue
            # The SAME parser the workbook goes through, so "73%", 73 and
            # 0.73 mean the same thing whichever route a figure arrives by.
            # A second parser here is a second set of rules to get wrong.
            number = cx_metrics._number(raw)
            if number is None:
                return Response(
                    {field: f"{raw!r} is not a number. 0.73, 73 and 73% all "
                            f"mean 73%."}, status=400)
            if not 0 <= number <= 1:
                return Response(
                    {field: "A survey figure is between 0% and 100%."},
                    status=400)
            values[field] = number

        if "full_marks" in data:
            marked = str(data.get("full_marks")).lower() in ("1", "true", "yes")
            values["full_marks"] = marked
            if marked:
                # The rule and a figure are mutually exclusive: the measure
                # either applies to this person or it does not.
                values["contactability"] = None
                values["csat"] = None
                values.setdefault("note", "")
                if not str(data.get("note") or "").strip():
                    values["note"] = "Give full marks"

        if "note" in data:
            values["note"] = str(data.get("note") or "")[:160]

        if not values:
            return Response(
                {"detail": "Send a contactability, a csat, a full_marks or a "
                           "note."}, status=400)

        # The sales code is resolved here as well as on upload, so a name
        # fixed on this screen gets matched straight away.
        existing = CxRmMetric.objects.filter(
            period=period, rm_name=name).first()
        code = str(data.get("sales_code") or "").strip().upper()
        if not code:
            code = (cx_metrics.roster_names().get(cx_metrics.fold_name(name))
                    or (existing.sales_code if existing else ""))
        values["sales_code"] = code
        values["updated_by"] = getattr(request.user, "username", "")[:150]
        if existing is None:
            values["source"] = "typed in on the CX screen"

        row, created = CxRmMetric.objects.update_or_create(
            period=period, rm_name=name, defaults=values)
        return Response({
            "created": created,
            "row": {
                "id": row.id, "period": row.period, "rm_name": row.rm_name,
                "sales_code": row.sales_code, "matched": bool(row.sales_code),
                "contactability": row.contactability, "csat": row.csat,
                "full_marks": row.full_marks, "note": row.note,
            },
            "detail": (
                f"Saved {name} for {period}."
                + ("" if row.sales_code else
                   " No roster has that name, so it is not yet attached to "
                   "anybody's card - check the spelling against the roster, "
                   "or send the sales code with it.")),
        }, status=201 if created else 200)
