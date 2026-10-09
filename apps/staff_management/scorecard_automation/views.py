from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
import django_filters.rest_framework

from core.pagination import StandardPagination
from .models import (
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)
from .serializers import (
    ScKpiSerializer, ScRoleSerializer, ScRoleKpiMappingSerializer,
    ScEmployeePerformanceActualSerializer, ScEmployeeMonthlyPerformanceSerializer,
    RunScorecardSerializer,
)
from .services import EmployeeMonthlyPerformanceService, MissingEmployeeActualService

_TAG = "Scorecard Automation"


@extend_schema(tags=[_TAG])
class ScKpiListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScKpiSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["kpi_code", "kpi_calculation_mode", "is_active"]
    queryset = ScKpi.objects.all()


@extend_schema(tags=[_TAG])
class ScKpiDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScKpiSerializer
    queryset = ScKpi.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["role_code", "role_type", "is_active"]
    queryset = ScRole.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleSerializer
    queryset = ScRole.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleKpiMappingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleKpiMappingSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["role_code", "kpi_code", "plan_category", "is_bonus"]
    queryset = ScRoleKpiMapping.objects.all()


@extend_schema(tags=[_TAG])
class ScRoleKpiMappingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScRoleKpiMappingSerializer
    queryset = ScRoleKpiMapping.objects.all()


@extend_schema(tags=[_TAG])
class ScEmployeePerformanceActualListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScEmployeePerformanceActualSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "kpi_code", "eom_date"]
    queryset = ScEmployeePerformanceActual.objects.all()


@extend_schema(tags=[_TAG])
class ScEmployeePerformanceActualDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScEmployeePerformanceActualSerializer
    queryset = ScEmployeePerformanceActual.objects.all()


@extend_schema(tags=[_TAG])
class ScEmployeeMonthlyPerformanceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScEmployeeMonthlyPerformanceSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "role_code", "kpi_code", "eom_date"]
    queryset = ScEmployeeMonthlyPerformance.objects.all()


@extend_schema(tags=[_TAG])
class RefreshMissingActualsView(APIView):
    """Recompute which (employee, KPI) actuals are missing for a month."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        eom_date = request.data.get("eom_date")
        if not eom_date:
            return Response({"detail": "eom_date is required."}, status=status.HTTP_400_BAD_REQUEST)
        records = MissingEmployeeActualService.update_missing_actuals_for_month(eom_date)
        return Response({"eom_date": eom_date, "missing_count": len(records)})


@extend_schema(tags=[_TAG], request=RunScorecardSerializer)
class RunMonthlyScorecardView(APIView):
    """
    Generate the monthly scorecard (scored EmployeeMonthlyPerformance rows) for a
    scope of employees: all / a single employee / a department / a current role.
    Fails if there are unresolved missing actuals for the targeted employees.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = RunScorecardSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        eom_date = data["eom_date"].replace(day=1).isoformat()
        scope = data["scope"]

        svc = EmployeeMonthlyPerformanceService
        try:
            if scope == "employee":
                if not data.get("sales_code"):
                    return Response({"detail": "sales_code is required for scope=employee."}, status=400)
                result = svc.run_monthly_kpi_scorecard_for_employee(data["sales_code"], eom_date)
            elif scope == "department":
                if not data.get("department"):
                    return Response({"detail": "department is required for scope=department."}, status=400)
                result = svc.run_monthly_kpi_scorecard_by_department(data["department"], eom_date)
            elif scope == "role":
                if not data.get("role_code"):
                    return Response({"detail": "role_code is required for scope=role."}, status=400)
                result = svc.run_monthly_kpi_scorecard_by_current_role(data["role_code"], eom_date)
            else:
                result = svc.run_monthly_kpi_scorecard(eom_date)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# Loading the workbooks
# ─────────────────────────────────────────────────────────────────────────────


def _may_load(user):
    """Loading everybody's figures is an administrator's action.

    An RM reads their own card and changes nothing on it, so this is the only
    gate the scorecard needs: it is not per-module RBAC, it is "may this person
    rewrite what 91 people are measured on".
    """
    return bool(user and user.is_authenticated
                and (user.is_superuser or user.is_staff
                     or user.groups.filter(name__in=("staff_mgt", "Management")).exists()))


def _may_set_figures(user):
    """May this person type in what everybody is measured on?

    Tighter than ``_may_load`` on purpose. That one accepts ``is_staff``, and
    ``is_staff`` is legacy noise in this estate - a great many accounts carry
    it for reasons that have nothing to do with administering scorecards. A
    screen that sets the figures people are paid on needs a real signal, so
    this takes a superuser or membership of an administration group and
    nothing else.

    ``_may_load`` is left alone rather than tightened, because the workbook
    uploads behind it are in use and locking somebody out of a working screen
    to make a point about a flag would be the wrong trade.
    """
    return bool(
        user and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(
                 name__in=("staff_mgt", "Management", "hr")).exists()))


class _WorkbookUploadView(APIView):
    """Shared shape: read and report first, write only when asked.

    Two steps on purpose. The first upload reads the file and says what it
    found, writing nothing; only a second call with ``apply=true`` saves. These
    files set what every RM is measured on, and an import that silently
    replaced them would be worse than no import.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 40 * 1024 * 1024
    SUFFIXES = (".xlsx", ".xlsm", ".xlsb")

    def _file(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return None, Response({"file": "Choose the workbook first."}, status=400)
        if not upload.name.lower().endswith(self.SUFFIXES):
            return None, Response(
                {"file": f"{upload.name} is not an Excel workbook. Save it as "
                         f".xlsx and try again."}, status=400)
        if upload.size > self.MAX_BYTES:
            return None, Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; the "
                         f"limit is {self.MAX_BYTES // 1024 // 1024} MB."}, status=400)
        return upload, None

    @staticmethod
    def _asked_to_apply(request):
        return str(request.data.get("apply", "")).lower() in ("1", "true", "yes")


@extend_schema(tags=[_TAG])
class ScorecardActualsUploadView(_WorkbookUploadView):
    """Load one review month of the RM actuals workbook.

    On apply it also runs the scorecard for that month, so nobody has to
    remember a second step - the point of this screen is that the RM's card is
    up to date, not that a table got written.
    """

    def post(self, request):
        from datetime import datetime

        from apps.staff_management.scorecard_ingest import apply_actuals, read_actuals

        if not _may_load(request.user):
            return Response(
                {"detail": "Only an administrator can load the actuals."}, status=403)

        upload, bad = self._file(request)
        if bad is not None:
            return bad

        raw_month = str(request.data.get("eom_date", "")).strip()
        if not raw_month:
            return Response(
                {"eom_date": "Which month are these actuals for? e.g. 2026-08-01"},
                status=400)
        try:
            month = datetime.strptime(raw_month[:10], "%Y-%m-%d").date().replace(day=1)
        except ValueError:
            return Response(
                {"eom_date": f"{raw_month!r} is not a date. Use YYYY-MM-DD."},
                status=400)

        definitions = list(ScKpi.objects.filter(is_active=True))
        if not definitions:
            return Response(
                {"detail": "No KPIs are configured yet, so there is nothing to "
                           "read the workbook for."}, status=400)

        try:
            result = read_actuals(upload, month, definitions)
        except Exception as exc:  # noqa: BLE001 - the message is for the reader
            return Response(
                {"file": f"That workbook could not be read: {exc}"}, status=400)

        found = {}
        for row in result.rows:
            found[row.kpi_code] = found.get(row.kpi_code, 0) + 1

        body = {
            "applied": False,
            "month": month.isoformat(),
            "figures": result.total,
            "people": result.people,
            "sheets_read": result.sheets_seen,
            "by_kpi": [{"kpi_code": k, "figures": n}
                       for k, n in sorted(found.items())],
            "not_configured": result.skipped,
            "could_not_read": result.unreadable,
            "warnings": result.warnings,
        }

        if not self._asked_to_apply(request):
            return Response(body)

        who = (request.user.get_full_name() or request.user.username).strip()
        body["saved"] = apply_actuals(result, month, changed_by=who)
        body["applied"] = True

        # And score it, so the card is current without a second action.
        try:
            EmployeeMonthlyPerformanceService.run_monthly_kpi_scorecard(
                month.isoformat())
            body["scorecard_run"] = True
        except Exception as exc:  # noqa: BLE001
            body["scorecard_run"] = False
            body["scorecard_error"] = str(exc)
        return Response(body, status=201)


@extend_schema(tags=[_TAG])
class ScorecardAllocationUploadView(_WorkbookUploadView):
    """Load the per-person targets from the scorecard workbook.

    Yearly rather than monthly: these are the numbers each RM is set for the
    year, and they come off the "Summary Allocation" sheet.
    """

    def post(self, request):
        from apps.staff_management.scorecard_ingest import (
            apply_allocation, apply_roster, read_allocation, read_roster)

        if not _may_load(request.user):
            return Response(
                {"detail": "Only an administrator can load the targets."}, status=403)

        upload, bad = self._file(request)
        if bad is not None:
            return bad

        raw_year = str(request.data.get("year", "")).strip()
        if not raw_year.isdigit():
            return Response(
                {"year": "Which performance year are these targets for? e.g. 2026"},
                status=400)
        year = int(raw_year)

        sheet = str(request.data.get("sheet", "")).strip() or "Summary Allocation"
        definitions = list(ScKpi.objects.filter(is_active=True)
                           .exclude(allocation_column=""))
        if not definitions:
            return Response(
                {"detail": "No KPI takes a per-person target yet, so there is "
                           "nothing to read the allocation sheet for."}, status=400)
        try:
            rows, warnings = read_allocation(upload, definitions, sheet)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"file": f"That workbook could not be read: {exc}"}, status=400)

        people = len({r["sales_code"] for r in rows})
        by_kpi = {}
        for row in rows:
            by_kpi[row["kpi_code"]] = by_kpi.get(row["kpi_code"], 0) + 1

        # The same workbook carries the roster, and the engine cannot score
        # anybody whose role it does not know - so both are loaded together
        # rather than leaving a second upload to be remembered.
        try:
            roster, roster_warnings = read_roster(upload)
        except Exception as exc:  # noqa: BLE001
            roster, roster_warnings = [], [f"List: could not be read: {exc}"]

        body = {
            "applied": False,
            "year": year,
            "targets": len(rows),
            "people": people,
            "by_kpi": [{"kpi_code": k, "people": n}
                       for k, n in sorted(by_kpi.items())],
            "roster": len(roster),
            "roles": sorted({r["role"] for r in roster}),
            "warnings": warnings + roster_warnings,
        }
        if not self._asked_to_apply(request):
            return Response(body)

        who = (request.user.get_full_name() or request.user.username).strip()
        body["saved"] = apply_allocation(
            rows, year, source_label=upload.name, changed_by=who)
        body["roster_saved"] = apply_roster(roster, year, changed_by=who)
        body["applied"] = True
        return Response(body, status=201)


@extend_schema(tags=[_TAG])
class ScorecardCardView(APIView):
    """The signed-in person's scorecard, shaped like the card they are sent.

    One call rather than three, because the page is one document: a header, the
    KPI lines grouped by perspective, and a total. Splitting it would mean the
    browser deciding how a scorecard is laid out, and the layout is not the
    browser's to decide.

    Scoped to the caller by ``portfolio_profile.sales_code``. A Team Leader
    looking at somebody else is a different screen with a different gate; this
    one is only ever your own card, so there is no ``sales_code`` parameter to
    forget to check.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date

        from apps.portfolio.models import Profile
        from apps.staff_management.models import (
            EmployeeRoleHistory, StaffEmployeeData)

        profile = Profile.objects.filter(user_id=request.user.id).first()
        sales_code = (profile.sales_code or "").strip() if profile else ""
        if not sales_code:
            return Response({
                "has_card": False,
                "reason": "no_sales_code",
                "detail": "Your profile has no sales code, so there is no book "
                          "to score. Administration can add one on the Users "
                          "screen.",
            })

        # Built from what the system already holds - the DMC roster for the
        # role and the targets, the warehouse for the actuals - so the card
        # exists without anybody uploading or running anything, and moves when
        # the warehouse moves. A stored run, if there is one, is a snapshot of
        # a closed month and is offered alongside rather than instead.
        from apps.staff_management.live_scorecard import build_card

        try:
            live = build_card(sales_code, profile)
        except Exception as exc:  # noqa: BLE001 - a broken read must not blank the page
            live = {"has_card": False, "reason": "live_failed",
                    "sales_code": sales_code,
                    "detail": f"Your card could not be computed: {exc}"}
        if live.get("has_card"):
            # Whether this month's card has been signed, and by whom. The page
            # needs it to know whether to offer the signature or show it, and
            # a signed card must not quietly present different figures from the
            # ones on the signed copy.
            from apps.staff_management.scorecard_signoff import period_for
            from .models import ScorecardSignoff

            period = period_for()
            signoff = ScorecardSignoff.objects.filter(
                sales_code=sales_code, period=period).first()
            live["signoff"] = _signoff_payload(signoff)
            live["signoff_period"] = period
            if signoff and signoff.signed_at and signoff.card:
                # Signed: serve the copy that was signed, and say so. Showing
                # live figures under a signature would mean the screen and the
                # signed document disagree.
                signed = dict(signoff.card)
                signed["live"] = False
                signed["signoff"] = live["signoff"]
                signed["signoff_period"] = period
                return Response(signed)
            return Response(live)

        rows = list(ScEmployeeMonthlyPerformance.objects
                    .filter(sales_code=sales_code)
                    .order_by("-eom_date", "kpi_order"))
        if not rows:
            # Nothing live and nothing stored: say which of the two failed,
            # since they are different problems.
            if live.get("reason"):
                return Response(live)
            role = EmployeeRoleHistory.objects.filter(
                sales_code=sales_code,
                start_date__lte=date.today(), end_date__gte=date.today()).first()
            if role is not None:
                reason, detail = "not_run", (
                    "Your card has not been generated yet. It is produced when "
                    "the month's actuals are loaded.")
            elif not EmployeeRoleHistory.objects.exists():
                # Nobody has a role, so this is not about this person. Saying
                # "you are not on a roster" to all 91 people on a roster they
                # ARE on is an accusation the tool is in no position to make.
                reason, detail = "roster_not_loaded", (
                    "The scorecard roster has not been loaded into the tool "
                    "yet, so no cards exist for anybody. Nothing is wrong with "
                    "your profile.")
            else:
                reason, detail = "no_role", (
                    "The roster is loaded but does not list your sales code, "
                    "so no card applies to you. Administration can check it "
                    "against the scorecard workbook.")
            return Response({"has_card": False, "reason": reason,
                             "detail": detail, "sales_code": sales_code})

        latest = rows[0].eom_date
        lines = [r for r in rows if r.eom_date == latest]

        staff = StaffEmployeeData.objects.filter(sales_code=sales_code).first()
        role = EmployeeRoleHistory.objects.filter(
            sales_code=sales_code, start_date__lte=latest).order_by("-start_date").first()
        role_name = ""
        if role:
            found = ScRole.objects.filter(role_code=role.role_code).first()
            role_name = found.role_name if found else role.role_code

        # Grouped the way the card groups them, in the order they are scored.
        perspectives, seen = [], {}
        for line in lines:
            name = line.mapping_category or "Other"
            if name not in seen:
                seen[name] = {"perspective": name, "weight": 0.0, "lines": []}
                perspectives.append(seen[name])
            bucket = seen[name]
            bucket["weight"] += float(line.kpi_weight or 0)
            bucket["lines"].append({
                "kpi_order": line.kpi_order,
                "kpi_code": line.kpi_code,
                "kpi_name": line.kpi_name,
                "measure_of_success": line.kpi_description,
                "weight": float(line.kpi_weight or 0),
                "prev_year_value": line.prev_year_value,
                "target": line.kpi_target,
                "curr_year_value": line.curr_year_value,
                "ytd_target": line.ytd_target,
                "ytd_actual": line.ytd_actual,
                "score": line.ytd_score,
                "weighted_score": line.ytd_weighted_score,
                "notes": line.notes,
            })

        total = sum(float(line.ytd_weighted_score or 0) for line in lines)

        # What the desk has not been able to configure yet, named rather than
        # left as a silently missing row - an RM who cannot see why a line is
        # absent assumes the tool lost it.
        pending = list(
            ScKpi.objects.filter(is_active=False)
            .exclude(not_configured_reason="")
            .values("kpi_code", "kpi_name", "not_configured_reason")[:40])

        return Response({
            "has_card": True,
            "staff": {
                "sales_code": sales_code,
                "name": (staff.staff_name if staff else "")
                        or (request.user.get_full_name() or request.user.username),
                "title": role_name or (staff.job_title if staff else ""),
                "branch": (staff.staff_unit if staff else "") or (
                    profile.branch if profile else ""),
            },
            "period": {"eom_date": latest, "label": latest.strftime("%B %Y")},
            "performance_score": round(total, 4),
            "perspectives": perspectives,
            "lines": len(lines),
            "not_configured": pending,
        })


# ── Signing and downloading a card ───────────────────────────────────────────


def _own_sales_code(request):
    """The caller's own sales code, or "". Never taken from the request body:
    a card belongs to one person and there is no parameter to forget to check."""
    from apps.portfolio.models import Profile

    profile = Profile.objects.filter(user_id=request.user.id).first()
    return (profile.sales_code or "").strip() if profile else ""


def _signoff_payload(signoff):
    if signoff is None:
        return None
    return {
        "period": signoff.period,
        "signed": bool(signoff.signed_at),
        "signed_by": signoff.signed_by_name,
        "signed_at": signoff.signed_at.isoformat() if signoff.signed_at else None,
        "owner_comment": signoff.owner_comment,
        "manager_signed": bool(signoff.manager_signed_at),
        "manager_signed_by": signoff.manager_signed_by_name,
        "manager_signed_at": (signoff.manager_signed_at.isoformat()
                              if signoff.manager_signed_at else None),
        "manager_comment": signoff.manager_comment,
        "performance_score": signoff.performance_score,
        "fully_signed": signoff.is_fully_signed,
    }


@extend_schema(tags=[_TAG])
class ScorecardSignView(APIView):
    """Sign your own card, or counter-sign as the line manager.

    Signing FREEZES the card. The live figures move every night, so a
    signature against them would attest to a document that reads differently an
    hour later; what is stored is the card as it was at the moment of signing,
    and that copy is what the download renders from afterwards.

    ``role=owner`` (the default) signs your own card. ``role=manager``
    counter-signs somebody else's, and is accepted only from the person the
    DMC roster names as their team leader — matched on name, because the roster
    records a line manager's NAME and not their user account.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone

        from apps.staff_management.live_scorecard import build_card, roster_row
        from apps.staff_management.scorecard_signoff import period_for
        from .models import ScorecardSignoff

        role = str(request.data.get("role") or "owner").strip().lower()
        comment = str(request.data.get("comment") or "").strip()
        signer = (request.user.get_full_name() or request.user.username).strip()

        if role == "owner":
            sales_code = _own_sales_code(request)
            if not sales_code:
                return Response(
                    {"detail": "Your profile has no sales code, so there is no "
                               "card to sign."},
                    status=status.HTTP_400_BAD_REQUEST)
        else:
            sales_code = str(request.data.get("sales_code") or "").strip()
            if not sales_code:
                return Response(
                    {"detail": "sales_code is required to counter-sign."},
                    status=status.HTTP_400_BAD_REQUEST)
            row = roster_row(sales_code)
            named = (getattr(row, "team_leader", "") or "").strip().lower()
            # A manager signs the people the roster says are theirs. Anyone
            # else counter-signing would make the second signature worthless.
            if not request.user.is_superuser and named != signer.lower():
                return Response(
                    {"detail": f"{sales_code} is not on your team, so you "
                               f"cannot counter-sign their card."},
                    status=status.HTTP_403_FORBIDDEN)

        card = build_card(sales_code)
        if not card.get("has_card"):
            return Response(card, status=status.HTTP_400_BAD_REQUEST)

        period = period_for()
        signoff, _ = ScorecardSignoff.objects.get_or_create(
            sales_code=sales_code, period=period)

        if role == "owner":
            # The owner's signature is what fixes the figures. A manager
            # counter-signing must not quietly re-freeze a different set.
            signoff.card = card
            signoff.performance_score = card.get("performance_score")
            signoff.scored_lines = card.get("scored_lines") or 0
            signoff.pending_lines = card.get("pending_lines") or 0
            signoff.signed_by = request.user
            signoff.signed_by_name = signer
            signoff.signed_at = timezone.now()
            signoff.owner_comment = comment
        else:
            if not signoff.signed_at:
                return Response(
                    {"detail": f"{sales_code} has not signed their own card "
                               f"for {period} yet, so there is nothing to "
                               f"counter-sign."},
                    status=status.HTTP_409_CONFLICT)
            signoff.manager_signed_by = request.user
            signoff.manager_signed_by_name = signer
            signoff.manager_signed_at = timezone.now()
            signoff.manager_comment = comment

        signoff.save()
        return Response({"signoff": _signoff_payload(signoff)},
                        status=status.HTTP_200_OK)


@extend_schema(tags=[_TAG])
class ScorecardDownloadView(APIView):
    """Download your card as the spreadsheet the desk sends.

    The SIGNED copy when there is one, so the file and the signature agree;
    the live figures otherwise, clearly marked unsigned on the sheet itself.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse

        from apps.staff_management.live_scorecard import build_card
        from apps.staff_management.scorecard_signoff import (
            build_card_workbook, period_for)
        from .models import ScorecardSignoff

        sales_code = _own_sales_code(request)
        if not sales_code:
            return Response(
                {"detail": "Your profile has no sales code, so there is no "
                           "card to download."},
                status=status.HTTP_400_BAD_REQUEST)

        period = str(request.query_params.get("period") or period_for()).strip()
        signoff = ScorecardSignoff.objects.filter(
            sales_code=sales_code, period=period).first()

        if signoff and signoff.signed_at and signoff.card:
            card = signoff.card
        else:
            card = build_card(sales_code)
            if not card.get("has_card"):
                return Response(card, status=status.HTTP_400_BAD_REQUEST)

        buffer = build_card_workbook(card, signoff)
        name = ((card.get("staff") or {}).get("name")
                or sales_code).replace(" ", "_")
        response = HttpResponse(
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")
        response["Content-Disposition"] = (
            f'attachment; filename="Scorecard_{name}_{period}.xlsx"')
        return response


# ── Administration: the figures the system cannot compute ────────────────────


@extend_schema(tags=[_TAG])
class ScorecardManualRowsView(APIView):
    """Which lines need a figure typed in, and what is already loaded.

    Administration reads this to see the work: one row per person per line
    that the warehouse cannot answer, with the figure if somebody has already
    loaded one. Pass ``?sales_code=`` for one person.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.scorecard_manual import (
            MANUAL_ACTUALS, MANUAL_TARGETS, _default_month,
            rows_needing_a_figure)
        from .models import ScEmployeeKpiTarget, ScEmployeePerformanceActual

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can see everybody's "
                           "figures."}, status=403)

        month = _default_month()
        rows = rows_needing_a_figure(
            str(request.query_params.get("sales_code") or "").strip())

        targets = {(t.sales_code.strip().upper(), t.kpi_code): t.kpi_target
                   for t in ScEmployeeKpiTarget.objects.filter(
                       year=month.year)}
        actuals = {((a.sales_code or "").strip().upper(), a.kpi_code): a.kpi_value
                   for a in ScEmployeePerformanceActual.objects.filter(
                       eom_date=month)}

        out = []
        for row in rows:
            key = (row["sales_code"], row["kpi_code"])
            out.append({**row,
                        "target": targets.get(key) if row["needs_target"] else None,
                        "actual": actuals.get(key) if row["needs_actual"] else None})
        loaded = sum(1 for r in out
                     if r["target"] is not None or r["actual"] is not None)
        return Response({
            "month": month.isoformat(),
            "rows": out,
            "total": len(out),
            "loaded": loaded,
            "outstanding": len(out) - loaded,
            "manual_actual_kpis": MANUAL_ACTUALS,
            "manual_target_kpis": MANUAL_TARGETS,
        })


@extend_schema(tags=[_TAG])
class ScorecardManualTemplateView(APIView):
    """Download the template, generated from the roster.

    Pre-filled with who and which line, so the only thing to type is the
    number. A blank template that somebody has to match up by hand is how a
    figure ends up against the wrong sales code.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse

        from apps.staff_management.scorecard_manual import build_template

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can load everybody's "
                           "figures."}, status=403)

        code = str(request.query_params.get("sales_code") or "").strip()
        buffer, count = build_template(code)
        name = f"Scorecard_figures_{code or 'all'}.xlsx"
        response = HttpResponse(
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["X-Rows"] = str(count)
        return response


@extend_schema(tags=[_TAG])
class ScorecardManualUploadView(_WorkbookUploadView):
    """Load the filled template.

    Read and report first, write only on a second call with ``apply=true`` -
    these figures are part of what people are paid on, and an import that
    silently replaced them would be worse than no import.
    """

    def post(self, request):
        from apps.staff_management.scorecard_manual import (
            apply_upload, read_upload)

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can load the figures."},
                status=403)

        upload, bad = self._file(request)
        if bad is not None:
            return bad

        try:
            entries, problems = read_upload(upload)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return Response(
                {"detail": f"That file could not be read: {exc}"}, status=400)

        preview = [{
            "row": e["row"], "sales_code": e["sales_code"],
            "kpi_code": e["kpi_code"], "target": e["target"],
            "actual": e["actual"], "month": e["month"].isoformat(),
        } for e in entries[:200]]

        if str(request.data.get("apply", "")).strip().lower() not in (
                "1", "true", "yes", "on"):
            return Response({
                "applied": False,
                "found": len(entries),
                "problems": problems,
                "preview": preview,
                "detail": (f"{len(entries)} figure(s) read and "
                           f"{len(problems)} problem(s) found. Nothing has "
                           f"been saved. Send the same file with apply=true "
                           f"to save."),
            })

        if not entries:
            return Response(
                {"applied": False, "found": 0, "problems": problems,
                 "detail": "There is nothing to save in that file."},
                status=400)

        who = (request.user.get_full_name() or request.user.username).strip()
        written = apply_upload(entries, who=who)
        return Response({
            "applied": True,
            "found": len(entries),
            "problems": problems,
            "written": written,
            "detail": (f"Saved {written['targets']} target(s) and "
                       f"{written['actuals']} actual(s). The cards show them "
                       f"on the next reload."),
        })


@extend_schema(tags=[_TAG])
class ScorecardManualEntryView(APIView):
    """Save one figure, for when a file is more trouble than it is worth.

    Same validation as the upload: a figure against a sales code nobody holds,
    or against a KPI that is not on that person's card, is refused rather than
    saved somewhere nothing reads.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.staff_management.scorecard_manual import (
            MANUAL_ACTUALS, MANUAL_TARGETS, _default_month, _month_of,
            _number, apply_upload)
        from apps.staff_management.live_scorecard import role_code_for, roster_row
        from .models import ScRoleKpiMapping

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can set these figures."},
                status=403)

        code = str(request.data.get("sales_code") or "").strip().upper()
        kpi = str(request.data.get("kpi_code") or "").strip()
        if not code or not kpi:
            return Response(
                {"detail": "sales_code and kpi_code are both required."},
                status=400)

        row = roster_row(code)
        role = role_code_for(getattr(row, "staff_role", "")) if row else None
        if role is None:
            return Response(
                {"detail": f"{code} is not on the DMC roster with a role that "
                           f"has a card."}, status=400)
        if not ScRoleKpiMapping.objects.filter(
                role_code=role, kpi_code=kpi).exists():
            return Response(
                {"detail": f"{kpi} is not on the {role} card, which is the "
                           f"card {code} is measured on."}, status=400)

        target = _number(request.data.get("target"))
        actual = _number(request.data.get("actual"))
        if target is not None and kpi not in MANUAL_TARGETS:
            return Response(
                {"detail": f"{kpi} takes its target from the DMC roster or the "
                           f"role's card, so one set here would be ignored."},
                status=400)
        if actual is not None and kpi not in MANUAL_ACTUALS:
            return Response(
                {"detail": f"{kpi} is computed from the warehouse, so an actual "
                           f"set here would never be used."}, status=400)
        if target is None and actual is None:
            return Response({"detail": "Give a target or an actual."},
                            status=400)

        month = _month_of(request.data.get("month")) or _default_month()
        who = (request.user.get_full_name() or request.user.username).strip()
        written = apply_upload([{
            "sales_code": code, "kpi_code": kpi, "target": target,
            "actual": actual, "month": month, "row": 0,
        }], who=who)
        return Response({"written": written, "month": month.isoformat()})
