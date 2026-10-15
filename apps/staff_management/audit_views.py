"""The Audit returns screen.

Internal Audit's return is eight rows. Making somebody save a workbook to load
eight numbers is how a screen goes unused, so this takes a **paste** as readily
as a file — the table as it comes out of a mail or a spreadsheet, tabs, commas
or runs of spaces.

``audit/``         the period's figures, and what they do and do not reach
``audit/upload/``  a file or a pasted table; reads and reports, writes on apply
``audit/entry/``   one branch, typed or corrected

Who may load one: superuser, or ``staff_mgt`` / ``Management`` / ``audit``.
``audit`` is a new group, for the same reason ``cx`` exists: the team that owns
the figures should not have to go through an administrator to file them.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import audit_returns

_TAG = "Scorecard Automation"

#: ``is_staff`` is deliberately absent, as on every screen that sets what
#: people are measured on.
EDIT_GROUPS = ("staff_mgt", "Management", "audit")


def may_edit(user):
    return bool(
        user and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(name__in=EDIT_GROUPS).exists()))


def _rows(period):
    from .models import ScAuditReturn

    rows = [{
        "id": row.id, "period": row.period, "branch": row.branch,
        "branch_key": row.branch_key, "audit_score": row.audit_score,
        "implementation": row.implementation, "note": row.note,
        "updated_at": row.updated_at, "updated_by": row.updated_by,
        "source": row.source,
    } for row in ScAuditReturn.objects.filter(period=period)]
    return audit_returns.annotate(rows)


@extend_schema(tags=[_TAG])
class AuditReturnsView(APIView):
    """One period's audit figures, and the nine card lines they feed."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        period = str(request.query_params.get("period") or "").strip()
        period = period or audit_returns.latest_period() or ""
        return Response({
            "period": period,
            "may_edit": may_edit(request.user),
            "coverage": audit_returns.coverage(period) if period else None,
            "rows": _rows(period) if period else [],
            # What these figures do, on the screen rather than in a docstring:
            # the people filing them are not the people who read the scorecard
            # code, and "why does this matter" is the first question.
            "feeds": [
                {"column": "Audit Score", "target": 1.65,
                 "direction": "lower is better",
                 "lines": "Audit (Diaspora RM and ARM), Branch Audit (six "
                          "back-office roles), Audit (Diaspora CSM)",
                 "detail": "A grade, not a quantity: 1.65 or better, and "
                           "better means smaller."},
                {"column": "Implementation", "target": 0.85,
                 "direction": "higher is better",
                 "lines": "Branch Audit - implementation (branch operations "
                          "manager, cash teller, customer service officer)",
                 "detail": "How much of what the audit asked for has been "
                           "done. 85% or better."},
            ],
            "not_covered": (
                "Two audit lines are not in this return and still come off "
                "Figures to load: the branch compliance score (90% and above) "
                "and cash management accuracy."),
        })


@extend_schema(tags=[_TAG])
class AuditUploadView(APIView):
    """A file or a pasted table. Reads and reports; writes only when asked."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    MAX_BYTES = 10 * 1024 * 1024

    def post(self, request):
        if not may_edit(request.user):
            return Response(
                {"detail": "Only Internal Audit or an administrator can load "
                           "the audit return."}, status=403)

        upload = request.FILES.get("file")
        pasted = str(request.data.get("pasted") or "").strip()
        if upload is None and not pasted:
            return Response(
                {"detail": "Paste the table, or choose a file."}, status=400)

        source = "pasted in"
        try:
            if upload is not None:
                if not upload.name.lower().endswith(
                        (".xlsx", ".xlsm", ".csv")):
                    return Response(
                        {"file": f"{upload.name} is not a spreadsheet or a "
                                 f"CSV."}, status=400)
                if upload.size > self.MAX_BYTES:
                    return Response(
                        {"file": f"That file is "
                                 f"{upload.size / 1024 / 1024:.1f} MB; the "
                                 f"limit is "
                                 f"{self.MAX_BYTES // 1024 // 1024} MB."},
                        status=400)
                rows, report = audit_returns.read_workbook(
                    upload, upload.name)
                source = upload.name
            else:
                rows, report = audit_returns.read_pasted(pasted)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response(
                {"detail": f"That could not be read: {exc}"}, status=400)

        period = audit_returns.period_of(
            str(request.data.get("period") or "") or source)
        rows = audit_returns.annotate(rows)
        report["period"] = period
        report["branches"] = len(rows)
        report["unmatched"] = sorted(
            row["branch"] for row in rows if not row["matched"])
        report["loose_matches"] = sorted(
            f"{row['branch']} → {row['roster_branch']}"
            for row in rows if row.get("match_kind") == "prefix")

        if not rows:
            return Response({
                "applied": False, "report": report,
                "detail": "No branches were read. The table needs a branch "
                          "name and at least one of a score or an "
                          "implementation rate.",
            }, status=400)

        if str(request.data.get("apply", "")).lower() not in ("1", "true",
                                                              "yes"):
            return Response({
                "applied": False, "report": report, "rows": rows,
                "detail": (
                    f"Read {len(rows)} branch(es) for {period}. Nothing has "
                    f"been saved yet - send it again with apply to save."),
            })

        written = audit_returns.save(
            rows, period, who=getattr(request.user, "username", ""),
            source=source)
        return Response({
            "applied": True, "report": report, "written": written,
            "coverage": audit_returns.coverage(period),
            "detail": f"Saved {written} branch(es) for {period}.",
        })


@extend_schema(tags=[_TAG])
class AuditEntryView(APIView):
    """One branch, typed in or corrected.

    Here because a correction to one branch should not need the whole table
    again — and because fixing a branch NAME is the commonest correction of
    all, this being a measure matched on the name.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import ScAuditReturn

        if not may_edit(request.user):
            return Response(
                {"detail": "Only Internal Audit or an administrator can set "
                           "an audit figure."}, status=403)

        data = request.data
        period = audit_returns.period_of(str(data.get("period") or ""))
        branch = str(data.get("branch") or "").strip()
        if not branch:
            return Response({"branch": "Which branch?"}, status=400)

        values = {}
        if "audit_score" in data:
            raw = data.get("audit_score")
            if raw in (None, ""):
                values["audit_score"] = None
            else:
                score = audit_returns._score(raw)
                if score is None:
                    return Response(
                        {"audit_score": f"{raw!r} is not a number. The score "
                                        f"looks like 1.65."}, status=400)
                if not 0 < score <= 5:
                    return Response(
                        {"audit_score": "An audit score is a grade between 0 "
                                        "and 5."}, status=400)
                values["audit_score"] = score
        if "implementation" in data:
            raw = data.get("implementation")
            if raw in (None, ""):
                values["implementation"] = None
            else:
                rate = audit_returns._rate(raw)
                if rate is None:
                    return Response(
                        {"implementation": f"{raw!r} is not a number. 93, 0.93 "
                                           f"and 93% all mean 93%."},
                        status=400)
                if not 0 <= rate <= 1:
                    return Response(
                        {"implementation": "An implementation rate is between "
                                           "0% and 100%."}, status=400)
                values["implementation"] = rate
        if "note" in data:
            values["note"] = str(data.get("note") or "")[:200]

        if not values:
            return Response(
                {"detail": "Send an audit_score, an implementation or a "
                           "note."}, status=400)

        values["branch"] = branch[:120]
        values["updated_by"] = getattr(request.user, "username", "")[:150]
        key = audit_returns.fold_branch(branch)
        row, created = ScAuditReturn.objects.update_or_create(
            period=period, branch_key=key, defaults=values)

        shown = audit_returns.annotate([{
            "branch": row.branch, "branch_key": row.branch_key}])[0]
        return Response({
            "created": created,
            "row": {
                "id": row.id, "period": row.period, "branch": row.branch,
                "audit_score": row.audit_score,
                "implementation": row.implementation, "note": row.note,
                "matched": shown["matched"],
                "roster_branch": shown["roster_branch"],
            },
            "detail": (
                f"Saved {row.branch} for {period}."
                + ("" if shown["matched"] else
                   " No branch on the roster matches that name, so it reaches "
                   "nobody's card - check the spelling against the roster.")),
        }, status=201 if created else 200)
