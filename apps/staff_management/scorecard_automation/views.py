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


def _month_asked_for(request):
    """``?month=YYYY-MM`` -> that month's LAST day, or ``(None, None)``.

    Returns ``(None, Response)`` when the month cannot be used, so the caller
    reports it rather than quietly serving the wrong period.

    A month that has not finished is refused. A card for the month you are
    standing in shows a handful of days of actuals against a target
    pro-rated to the same handful - arithmetically consistent and completely
    misleading, because the warehouse feeds land in arrears.
    """
    import calendar
    import datetime

    raw = str(request.query_params.get("month") or "").strip()
    if not raw:
        return None, None

    try:
        year, month = raw.split("-")
        first = datetime.date(int(year), int(month), 1)
    except (ValueError, TypeError):
        return None, Response(
            {"month": f"{raw!r} is not a month. Use YYYY-MM, e.g. 2026-09."},
            status=status.HTTP_400_BAD_REQUEST)

    last = first.replace(
        day=calendar.monthrange(first.year, first.month)[1])
    if last >= datetime.date.today():
        return None, Response(
            {"month": f"{first:%B %Y} has not closed yet. A card can only be "
                      f"built for a month that has finished, because the "
                      f"figures arrive in arrears."},
            status=status.HTTP_400_BAD_REQUEST)
    return last, None


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
            # The rosters, so a row whose SALES CODE CELL IS BLANK still
            # reaches its owner by name. Nine people in the sales template -
            # Anna Amasinde, Simon Waruingi, John Gichuki, Jane Imana and
            # five more, every one of them a head - have figures and no code,
            # and without this every figure of theirs is read and discarded.
            from apps.staff_management.cx_metrics import roster_names

            result = read_actuals(upload, month, definitions,
                                  names=roster_names())
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
            # People with figures and no sales code whose name no roster
            # matched either. Reported rather than dropped: these are real
            # figures and the only thing missing is one cell, which somebody
            # can fill in a minute once they know whose it is.
            "no_sales_code": [
                {"sheet": sheet, "row": row_number, "name": person,
                 "role": role, "figures": many}
                for sheet, row_number, person, role, many in result.unkeyed],
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

        # The KPI's real name, so the screen stops inventing one from the
        # code. Title-casing `reduce_p_l_provisions_nill_provisions_loan_loss`
        # gives "Reduce P L Provisions Nill Provisions Loan Loss", and
        # `commercial_trade_group_synergies_23_0` gives "Commercial Trade
        # Group Synergies 23 0" - which is the group heading migration 0053
        # renamed away from, reappearing on a different screen because this
        # one never asked for the name.
        named = {k.kpi_code: (k.kpi_name or "").strip()
                 for k in ScKpi.objects.filter(kpi_code__in=by_kpi)}

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
            "by_kpi": [{"kpi_code": k, "kpi_name": named.get(k) or k,
                        "people": n}
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

        # The roster is loaded alongside, and must not be able to lose the
        # targets. It could: an unwritable roster row raised out of this view
        # as a bare 500, and the 2,822 targets that had just read perfectly
        # went with it - the page said "Server Error (500)" and nobody could
        # tell that half the work had succeeded.
        #
        # The targets are already committed by the line above, so a roster
        # failure is reported beside them rather than thrown.
        try:
            body["roster_saved"] = apply_roster(roster, year, changed_by=who)
        except Exception as exc:  # noqa: BLE001
            body["roster_saved"] = {"error": str(exc)}
            body["warnings"] = body.get("warnings", []) + [
                f"The targets were saved. The roster was not: {exc}"]

        body["applied"] = True
        return Response(body, status=201)


@extend_schema(tags=[_TAG])
class ScorecardCardView(APIView):
    """The signed-in person's scorecard, shaped like the card they are sent.

    One call rather than three, because the page is one document: a header, the
    KPI lines grouped by perspective, and a total. Splitting it would mean the
    browser deciding how a scorecard is laid out, and the layout is not the
    browser's to decide.

    Scoped to the caller, and to the caller only: there is no ``sales_code``
    parameter to forget to check. A manager looking at somebody else is a
    different screen with a different gate.

    **Who the caller is** is resolved by
    ``live_scorecard.resolve_sales_code_for_user`` rather than by
    ``Profile.sales_code`` alone. That field is set for people who carry a
    sales book and for nobody else, so the 101 back-office people seeded onto
    cards by migration 0032 - the BOMs, the CSOs, the tellers, the RBO team
    leaders - all had a configured card and no way to open it.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date

        from apps.portfolio.models import Profile
        from apps.staff_management.models import (
            EmployeeRoleHistory, StaffEmployeeData)

        from apps.staff_management.live_scorecard import (
            no_card_for_user, resolve_sales_code_for_user)

        profile = Profile.objects.filter(user_id=request.user.id).first()
        sales_code, how = resolve_sales_code_for_user(request.user, profile)
        if not sales_code:
            # Everything that was tried is named. "Your profile has no sales
            # code" sent every back-office card holder to the wrong place -
            # their card was fine, and so was their profile; what was missing
            # was any link at all between the account and a roster row.
            return Response(no_card_for_user(request.user, profile))

        # ``?month=YYYY-MM`` builds the card FOR that month: the warehouse
        # asked for that closing, the targets pro-rated to that date, the
        # loaded figures read for that month.
        #
        # This view ignored the parameter entirely and always built the live
        # card, while download/ and card-for/ honoured it. So the month picker
        # on the page moved the downloaded workbook and left the card on
        # screen untouched - "I go to other months and nothing changes", which
        # is exactly what it did.
        month, bad = _month_asked_for(request)
        if bad is not None:
            return bad

        # Built from what the system already holds - the DMC roster for the
        # role and the targets, the warehouse for the actuals - so the card
        # exists without anybody uploading or running anything, and moves when
        # the warehouse moves. A stored run, if there is one, is a snapshot of
        # a closed month and is offered alongside rather than instead.
        from apps.staff_management.live_scorecard import build_card

        try:
            live = build_card(sales_code, profile, as_at=month)
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

            # The signature belongs to the month being LOOKED AT, not to the
            # month that happens to have closed today. Reading the current
            # period against a card built for July would show July's figures
            # under September's signature.
            period = (f"{month.year:04d}-{month.month:02d}" if month
                      else period_for())
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
                signed["matched_by"] = how
                signed["month"] = month.isoformat() if month else None
                return Response(signed)
            live["matched_by"] = how
            live["month"] = month.isoformat() if month else None
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


@extend_schema(tags=[_TAG])
class ScorecardHolderView(APIView):
    """Does the signed-in person hold a card at all? -> ``{holds_card, ...}``.

    The home screen asks this to decide whether to show a "My Scorecard"
    tile. "My Scorecard" was only ever a link on the RM, TL and Branch
    menus, and a teller, CSO or BOM is in none of those groups - so the 41
    tellers had a configured card, were recognised by my-card/, and had no
    link anywhere that reached it. They signed in to Customer 360 and nothing
    else.

    Only who the person is and which card they hold: no figures, so it is
    cheap enough to ask on every visit to home, unlike my-card/ itself.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.portfolio.models import Profile
        from apps.staff_management.live_scorecard import (
            resolve_person, resolve_sales_code_for_user)

        profile = Profile.objects.filter(user_id=request.user.id).first()
        code, _how = resolve_sales_code_for_user(request.user, profile)
        person = resolve_person(code) if code else None
        if person is None:
            return Response({"holds_card": False})
        return Response({
            "holds_card": True,
            "sales_code": person.sales_code,
            "role_code": person.role_code,
            "role_name": (ScRole.objects.filter(role_code=person.role_code)
                          .values_list("role_name", flat=True).first()
                          or person.role_code),
        })


def _own_sales_code(request):
    """The caller's own sales code, or "". Never taken from the request body:
    a card belongs to one person and there is no parameter to forget to check.

    ``Profile.sales_code`` first, then the identifiers the estate holds for
    somebody who carries no sales book - see
    ``live_scorecard.resolve_sales_code_for_user``. Every Team Leader, BOM,
    CSO and teller seeded onto a card by migration 0032 had a card and no way
    to reach it, because the profile field nobody fills in for them was the
    only thing that was ever consulted.
    """
    code, _how = _own_sales_code_and_how(request)
    return code


def _own_sales_code_and_how(request):
    """``(sales_code, how)`` - the code and the identifier that found it.

    The card says which one answered, because "we matched you on your work
    e-mail" is the difference between somebody trusting the card in front of
    them and wondering whose it is.
    """
    from apps.portfolio.models import Profile
    from apps.staff_management.live_scorecard import resolve_sales_code_for_user

    profile = Profile.objects.filter(user_id=request.user.id).first()
    return resolve_sales_code_for_user(request.user, profile)


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
        # So the page can say "you withdrew this on the 9th" rather than
        # showing an unsigned card with no explanation of why the signature
        # somebody remembers making has gone.
        "withdrawn": bool(signoff.withdrawn_at),
        "withdrawn_at": (signoff.withdrawn_at.isoformat()
                         if signoff.withdrawn_at else None),
        "withdrawn_by": signoff.withdrawn_by_name,
        "withdrawn_reason": signoff.withdrawn_reason,
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
            # Either of the roster's two manager columns - see
            # live_scorecard.team_leader_of. Reading one and stopping is how
            # nobody can counter-sign anything.
            from apps.staff_management.live_scorecard import team_leader_of

            named = team_leader_of(row).strip().lower()
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
class ScorecardUnsignView(APIView):
    """Withdraw your own signature, while it is still only yours.

    Signing is one button next to a long page, and people press it before
    they meant to - which is exactly what happened the first week this was
    live. Without a way back, the only remedy was somebody editing the
    database, and a figure that can only be corrected in the database is a
    figure nobody can trust.

    The rules are narrow on purpose:

    * **you may only withdraw your own.** The sales code comes from the
      signed-in profile, as it does for signing, so there is no parameter to
      forget to check.
    * **not once the line manager has counter-signed.** At that point the two
      of you have agreed a document, and one side cannot quietly take it
      back; a superuser can, because somebody has to be able to fix a
      genuine mistake, and it is recorded against their name.
    * **the frozen copy is kept, not deleted.** The card goes back to live
      figures, and the copy that was signed stays on the row with
      ``withdrawn_at`` set, because "this was signed and then withdrawn" is
      part of the record and deleting it would hide it.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone

        from apps.staff_management.scorecard_signoff import period_for
        from .models import ScorecardSignoff

        sales_code = _own_sales_code(request)
        if not sales_code:
            return Response(
                {"detail": "Your profile has no sales code, so there is no "
                           "signature to withdraw."},
                status=status.HTTP_400_BAD_REQUEST)

        period = str(request.data.get("period") or period_for()).strip()
        signoff = ScorecardSignoff.objects.filter(
            sales_code=sales_code, period=period).first()
        if signoff is None or not signoff.signed_at:
            return Response(
                {"detail": f"You have not signed your card for {period}, so "
                           f"there is nothing to withdraw."},
                status=status.HTTP_409_CONFLICT)

        if signoff.manager_signed_at and not request.user.is_superuser:
            manager = signoff.manager_signed_by_name or "your line manager"
            return Response(
                {"detail": f"{manager} has already counter-signed this card, "
                           f"so it is an agreed document and you cannot "
                           f"withdraw it on your own. Ask them to reopen it."},
                status=status.HTTP_409_CONFLICT)

        who = (request.user.get_full_name() or request.user.username).strip()
        signoff.withdrawn_at = timezone.now()
        signoff.withdrawn_by_name = who
        signoff.withdrawn_reason = str(
            request.data.get("reason") or "").strip()[:255]
        # The signature comes off; the copy that was signed stays put.
        signoff.signed_at = None
        signoff.signed_by = None
        signoff.manager_signed_at = None
        signoff.manager_signed_by = None
        signoff.save()

        return Response({
            "withdrawn": True,
            "signoff": _signoff_payload(signoff),
            "detail": (f"Your signature for {period} has been withdrawn. The "
                       f"card is back to live figures and you can sign it "
                       f"again when it reads right."),
        }, status=status.HTTP_200_OK)


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

        # ``month=YYYY-MM`` downloads THAT month's card.
        #
        # Not a stored snapshot - the same computation anchored on that
        # month, so the warehouse is asked for that closing and the targets
        # are pro-rated to it. A month that has not closed is refused rather
        # than served half-done: a card for the month you are standing in
        # shows a few days of actuals against a few days of target, which
        # reads as a collapse in performance.
        month, bad = _month_asked_for(request)
        if bad is not None:
            return bad

        if signoff and signoff.signed_at and signoff.card and month is None:
            card = signoff.card
        else:
            card = build_card(sales_code, as_at=month)
            if not card.get("has_card"):
                return Response(card, status=status.HTTP_400_BAD_REQUEST)

        buffer = build_card_workbook(card, signoff)
        name = ((card.get("staff") or {}).get("name")
                or sales_code).replace(" ", "_")
        response = HttpResponse(
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")
        # The month the card is FOR goes in the filename, so downloading
        # September and October does not produce two files with the same
        # name, one of which silently replaces the other in Downloads.
        stamp = f"{month:%Y-%m}" if month else period
        response["Content-Disposition"] = (
            f'attachment; filename="Scorecard_{name}_{stamp}.xlsx"')
        return response


class ScorecardSendView(APIView):
    """E-mail a scorecard - the button the desk asked for.

    GET  reports who it would go to, and why an address is missing, without
         sending anything. The button can then say "to Mary, cc Floyd" before
         anybody presses it.
    POST sends it, with the read-only workbook attached.

    Which card: your OWN by default, resolved from your profile, so there is
    no parameter to forget to check. An administrator may pass ``sales_code``
    to send somebody else's - a manager chasing a card that was never sent -
    and only an administrator, because a scorecard is a performance record and
    mailing one around is not a read.

    Which COPY: the signed one when there is one, so the file and the
    signature agree; the live figures otherwise, marked unsigned on the sheet.
    Exactly as the download does, and deliberately the same code path - a
    card that was e-mailed and a card that was downloaded must not be two
    different documents.
    """

    permission_classes = [IsAuthenticated]

    def _resolve(self, request):
        """→ ``(sales_code, card, signoff, period, error_response)``."""
        from apps.staff_management.live_scorecard import build_card
        from apps.staff_management.scorecard_signoff import period_for
        from .models import ScorecardSignoff

        asked = str(request.query_params.get("sales_code")
                    or request.data.get("sales_code") or "").strip()
        own = _own_sales_code(request)

        if asked and asked.upper() != (own or "").upper():
            if not _may_set_figures(request.user):
                return None, None, None, None, Response(
                    {"detail": "You can only send your own scorecard. "
                               "Administration can send anybody's."},
                    status=status.HTTP_403_FORBIDDEN)
            sales_code = asked
        else:
            sales_code = own

        if not sales_code:
            return None, None, None, None, Response(
                {"detail": "Your profile has no sales code, so there is no "
                           "card to send."},
                status=status.HTTP_400_BAD_REQUEST)

        period = str(request.query_params.get("period")
                     or request.data.get("period") or period_for()).strip()
        signoff = ScorecardSignoff.objects.filter(
            sales_code=sales_code, period=period).first()

        if signoff and signoff.signed_at and signoff.card:
            card = signoff.card
        else:
            card = build_card(sales_code)
            if not card.get("has_card"):
                return None, None, None, None, Response(
                    card, status=status.HTTP_400_BAD_REQUEST)
        return sales_code, card, signoff, period, None

    def get(self, request):
        from apps.staff_management import scorecard_email

        sales_code, card, signoff, period, error = self._resolve(request)
        if error is not None:
            return error

        to, cc, problems = scorecard_email.recipients_for(card)
        subject, body = scorecard_email.compose(card, signoff)
        return Response({
            "sales_code": sales_code, "period": period,
            "to": to, "cc": cc, "problems": problems,
            "can_send": bool(to),
            "is_signed": bool(getattr(signoff, "signed_at", None)),
            "subject": subject, "preview": body,
            "last_sent": self._history(sales_code, period),
        })

    def post(self, request):
        from apps.staff_management import scorecard_email

        sales_code, card, signoff, period, error = self._resolve(request)
        if error is not None:
            return error

        extra = request.data.get("to") or []
        if isinstance(extra, str):
            extra = [part for part in extra.replace(";", ",").split(",")]

        try:
            sent = scorecard_email.send_card(
                card, signoff, extra_to=extra,
                who=(getattr(request.user, "get_full_name", lambda: "")()
                     or getattr(request.user, "username", "")),
                request_user=request.user)
        except ValueError as exc:
            # No address. Not an error in the usual sense - it is a thing
            # somebody has to go and fix on the roster - so it comes back as
            # the reason rather than a stack trace.
            return Response({"detail": str(exc), "can_send": False},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            return Response(
                {"detail": f"The mail server would not take it: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY)

        recipients = [a for a in (sent.sent_to or "").split(", ") if a]
        copied = [a for a in (sent.sent_cc or "").split(", ") if a]
        return Response({
            "sent": True, "sales_code": sales_code, "period": period,
            "to": recipients, "cc": copied,
            "sent_at": sent.sent_at,
            "detail": (
                f"Sent to {', '.join(recipients)}"
                + (f", copying {', '.join(copied)}" if copied else "")
                + ("." if getattr(signoff, "signed_at", None)
                   else ", marked unsigned on the sheet.")),
            "last_sent": self._history(sales_code, period),
        })

    @staticmethod
    def _history(sales_code, period):
        from .models import ScScorecardDispatch

        return [
            {"sent_at": row.sent_at, "to": row.sent_to, "cc": row.sent_cc,
             "by": row.sent_by_name, "was_signed": row.was_signed}
            for row in ScScorecardDispatch.objects.filter(
                sales_code=sales_code, period=period)[:10]
        ]


@extend_schema(tags=[_TAG])
class ScorecardSendManyView(APIView):
    """Send a whole card's worth of people their own scorecard.

    This is the screen the desk asked for: one action, from
    Scorecards -> Cards -> Who holds them, that gets every individual their
    own card rather than somebody opening 91 pages.

    Two steps, and the second one has to say so
    ------------------------------------------
    A GET - or a POST without ``confirm`` - reports who WOULD receive it and
    who could not be addressed, and sends nothing. Only a POST carrying
    ``confirm: true`` sends. This is mail to real people about their own
    performance: it cannot be undone, and a mis-aimed bulk send is not a
    thing an apology fixes.

    Each person gets their OWN card, addressed to them and copying their own
    line manager, exactly as the single send does - the same code path, so a
    card sent in bulk is the same document as one sent on its own.

    Administration only. ``_may_set_figures`` rather than ``_may_load``,
    because ``is_staff`` is legacy noise in this estate and this mails
    everybody.
    """

    permission_classes = [IsAuthenticated]

    #: A ceiling, so a mistyped filter cannot mail the whole bank. The desk's
    #: largest card holds 41 people; 150 leaves room and still stops a runaway.
    MAX_AT_ONCE = 150

    def _people(self, request):
        """Who this request is about → ``[(sales_code, name), ...]``."""
        from apps.staff_management.live_scorecard import resolve_person
        from .models import ScRoleKpiMapping

        codes = request.data.get("sales_codes") or request.query_params.get(
            "sales_codes") or []
        if isinstance(codes, str):
            codes = [c.strip() for c in codes.split(",") if c.strip()]

        role = str(request.data.get("role_code")
                   or request.query_params.get("role_code") or "").strip()

        if not codes and role:
            # Everybody the rosters put on that card. Read through
            # resolve_person rather than off one roster, because three
            # different rosters answer for different people and the card
            # screen shows all three.
            from apps.staff_management.models import (
                BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
                EmployeeRoleHistory)

            seen = set()
            for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData):
                for row in model.objects.exclude(sales_code="").only(
                        "sales_code"):
                    seen.add((row.sales_code or "").strip())
            for row in EmployeeRoleHistory.objects.filter(
                    role_code=role).only("sales_code"):
                seen.add((row.sales_code or "").strip())
            codes = sorted(c for c in seen if c)

        out, unknown = [], []
        for code in dict.fromkeys(c.strip() for c in codes if c and c.strip()):
            person = resolve_person(code)
            if person is None or not person.role_code:
                unknown.append({"sales_code": code,
                                "why": "that sales code holds no card here"})
                continue
            if role and person.role_code != role:
                continue
            out.append((code, person.name))
        if role and not ScRoleKpiMapping.objects.filter(
                role_code=role).exists():
            return [], [{"sales_code": "", "why": f"no card called {role}"}]
        return out, unknown

    def _preview(self, request, people, unknown):
        from apps.staff_management import scorecard_email
        from apps.staff_management.live_scorecard import build_card

        ready, blocked = [], []
        for code, name in people:
            card = build_card(code)
            if not card.get("has_card"):
                blocked.append({"sales_code": code, "staff_name": name,
                                "why": card.get("reason")
                                or "no card could be built"})
                continue
            to, cc, problems = scorecard_email.recipients_for(card)
            if to:
                ready.append({"sales_code": code, "staff_name": name,
                              "to": to, "cc": cc})
            else:
                blocked.append({"sales_code": code, "staff_name": name,
                                "why": " ".join(problems)
                                or "no address on file"})
        return ready, blocked + list(unknown)

    def get(self, request):
        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only Administration can send scorecards out."},
                status=status.HTTP_403_FORBIDDEN)
        people, unknown = self._people(request)
        if len(people) > self.MAX_AT_ONCE:
            return Response(
                {"detail": f"That is {len(people)} people. The most this will "
                           f"send at once is {self.MAX_AT_ONCE} - narrow it to "
                           f"one card."},
                status=status.HTTP_400_BAD_REQUEST)
        ready, blocked = self._preview(request, people, unknown)
        return Response({
            "sent": False, "would_send": len(ready), "ready": ready,
            "blocked": blocked,
            "detail": (
                f"{len(ready)} person/people would be e-mailed their own "
                f"card"
                + (f"; {len(blocked)} cannot be addressed yet."
                   if blocked else ".")
                + " Nothing has been sent - send it again with confirm."),
        })

    def post(self, request):
        from apps.staff_management import scorecard_email
        from apps.staff_management.live_scorecard import build_card
        from .models import ScorecardSignoff
        from apps.staff_management.scorecard_signoff import period_for

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only Administration can send scorecards out."},
                status=status.HTTP_403_FORBIDDEN)

        if str(request.data.get("confirm", "")).lower() not in ("1", "true",
                                                                 "yes"):
            return self.get(request)

        people, unknown = self._people(request)
        if not people:
            return Response(
                {"detail": "Nobody was named, and no card was chosen."},
                status=status.HTTP_400_BAD_REQUEST)
        if len(people) > self.MAX_AT_ONCE:
            return Response(
                {"detail": f"That is {len(people)} people. The most this will "
                           f"send at once is {self.MAX_AT_ONCE}."},
                status=status.HTTP_400_BAD_REQUEST)

        who = (getattr(request.user, "get_full_name", lambda: "")()
               or getattr(request.user, "username", ""))
        period = period_for()
        sent, failed = [], list(unknown)

        for code, name in people:
            try:
                signoff = ScorecardSignoff.objects.filter(
                    sales_code=code, period=period).first()
                card = (signoff.card
                        if signoff and signoff.signed_at and signoff.card
                        else build_card(code))
                if not card.get("has_card"):
                    failed.append({"sales_code": code, "staff_name": name,
                                   "why": card.get("reason")
                                   or "no card could be built"})
                    continue
                record = scorecard_email.send_card(
                    card, signoff, who=who, request_user=request.user)
                sent.append({"sales_code": code, "staff_name": name,
                             "to": record.sent_to, "cc": record.sent_cc})
            except Exception as exc:  # noqa: BLE001 - one failure must not
                # stop the other ninety. Each is a separate message to a
                # separate person, and the ones that went are recorded.
                failed.append({"sales_code": code, "staff_name": name,
                               "why": str(exc)})

        return Response({
            "sent": True, "count": len(sent), "sent_to": sent,
            "failed": failed,
            "detail": (f"Sent {len(sent)} scorecard(s)."
                       + (f" {len(failed)} could not be sent."
                          if failed else "")),
        })


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
        from apps.staff_management.live_scorecard import resolve_person
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

        # All three rosters, not just the sales one. A teller is on none of
        # the sales tables, so resolving against them alone refused every
        # back-office figure.
        person = resolve_person(code)
        role = person.role_code if person else ""
        if not role:
            return Response(
                {"detail": f"{code} is on none of the rosters with a role "
                           f"that has a card."}, status=400)
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


# ── Administration: the cards, who holds them, and anyone's card ─────────────


@extend_schema(tags=[_TAG])
class ScorecardCatalogueView(APIView):
    """Every configured card, or one of them in full.

    ``?role_code=`` returns that card's lines - weight, target, feed, this
    role's own wording, and whether the line is measured, loadable or
    stranded. Without it, a row per card.

    The cards were seeded and then existed only in the database, with nowhere
    to look at them. This is that place.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.scorecard_catalogue import (
            cards, cards_without_holders)

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can see everybody's cards."},
                status=403)

        role = str(request.query_params.get("role_code") or "").strip()
        found = cards(role)
        if role and not found:
            return Response(
                {"detail": f"There is no card configured for {role}."},
                status=404)
        if role:
            return Response(found[0])

        by_family = {"sales": [], "back office": []}
        for card in found:
            by_family[card["family"]].append(card)
        return Response({
            "cards": found,
            "totals": {
                "cards": len(found),
                "sales": len(by_family["sales"]),
                "back_office": len(by_family["back office"]),
                "lines": sum(c["lines"] for c in found),
                "holders": sum(c["holders"] for c in found),
            },
            # Cards nobody holds. A question rather than a fault: seeding them
            # onto somebody would have been a guess.
            "without_holders": cards_without_holders(),
        })


@extend_schema(tags=[_TAG])
class ScorecardRosterView(APIView):
    """Who holds which card, across all three rosters.

    The sales DMC tables answer for RMs; ``employee_role_history`` answers for
    the back office, who are on no sales roster because that table is keyed on
    sales targets a teller does not have. Each row says which roster it came
    off, so a card can be traced to the list behind it.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.scorecard_catalogue import roster

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can see the roster."},
                status=403)

        rows = roster(
            role_code=str(request.query_params.get("role_code") or "").strip(),
            search=str(request.query_params.get("search") or "").strip())
        limit = 500
        return Response({
            "total": len(rows),
            "shown": min(len(rows), limit),
            "rows": rows[:limit],
            "by_family": {
                "sales": sum(1 for r in rows if r["family"] == "sales"),
                "back_office": sum(1 for r in rows
                                   if r["family"] == "back office"),
            },
        })


@extend_schema(tags=[_TAG])
class ScorecardForPersonView(APIView):
    """Anyone's card, by sales code.

    The same card the person sees, computed the same way, for somebody who has
    to check it. ``my-card/`` stays the only route to your OWN card and takes
    no parameter; this one is separate and gated, so the two cannot be confused
    and there is no way to read a colleague's card through the personal route.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.live_scorecard import build_card

        if not _may_set_figures(request.user):
            return Response(
                {"detail": "Only an administrator can open somebody else's "
                           "card."}, status=403)

        code = str(request.query_params.get("sales_code") or "").strip()
        if not code:
            return Response({"detail": "sales_code is required."}, status=400)
        try:
            # Administration can look at a past month too, the same way
            # the person can download it.
            month, bad = _month_asked_for(request)
            if bad is not None:
                return bad
            return Response(build_card(code, as_at=month))
        except Exception as exc:  # noqa: BLE001 - reported, not a 500
            return Response(
                {"has_card": False, "reason": "live_failed",
                 "sales_code": code,
                 "detail": f"That card could not be computed: {exc}"})
