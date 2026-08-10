"""Team-leader ↔ branch mapping API (Administration).

* ``GET  team-leaders/``            — list branch→TL mappings.
* ``POST team-leaders/``            — upsert one branch's team leader (admin).
* ``DELETE team-leaders/<pk>/``     — remove a mapping (admin).
* ``POST team-leaders/reassign/``   — move all of one TL's branches to another
                                      TL (when a team leader exits) (admin).
* ``POST team-leaders/upload-csv/`` — import the pivot listing (TL name rows
                                      followed by their branch rows).

Branch names are normalised (see :mod:`apps.staff_management.branches`) so the
mapping is consistent with the rest of the platform.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from .branches import normalize_branch
from .dsr_views import _is_admin, _read_upload_rows
from .models import TeamLeaderBranch


class TeamLeaderBranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamLeaderBranch
        fields = "__all__"
        read_only_fields = ["updated_at"]


class TeamLeaderBranchListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeamLeaderBranchSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["team_leader", "role", "active"]
    search_fields = ["branch", "team_leader", "role"]
    ordering_fields = ["team_leader", "branch"]
    queryset = TeamLeaderBranch.objects.all()


class TeamLeaderBranchUpsertView(APIView):
    """Set (or change) the team leader for a branch."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_admin(request.user):
            return Response({"detail": "Administrators only."}, status=status.HTTP_403_FORBIDDEN)

        branch = normalize_branch(request.data.get("branch"))
        team_leader = str(request.data.get("team_leader") or "").strip()
        if not branch or not team_leader:
            return Response({"detail": "branch and team_leader are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        obj, _ = TeamLeaderBranch.objects.update_or_create(
            branch=branch,
            defaults={
                "team_leader": team_leader,
                "role": str(request.data.get("role") or "PB DSR").strip(),
                "active": bool(request.data.get("active", True)),
            },
        )
        return Response(TeamLeaderBranchSerializer(obj).data, status=status.HTTP_200_OK)


class TeamLeaderBranchDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    queryset = TeamLeaderBranch.objects.all()
    serializer_class = TeamLeaderBranchSerializer

    def delete(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response({"detail": "Administrators only."}, status=status.HTTP_403_FORBIDDEN)
        return super().delete(request, *args, **kwargs)


class TeamLeaderReassignView(APIView):
    """Move every branch owned by one team leader to another — used when a TL exits."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_admin(request.user):
            return Response({"detail": "Administrators only."}, status=status.HTTP_403_FORBIDDEN)

        src = str(request.data.get("from_team_leader") or "").strip()
        dst = str(request.data.get("to_team_leader") or "").strip()
        if not src or not dst:
            return Response({"detail": "from_team_leader and to_team_leader are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        moved = TeamLeaderBranch.objects.filter(team_leader__iexact=src).update(team_leader=dst)
        return Response({"reassigned": moved, "from": src, "to": dst}, status=status.HTTP_200_OK)


class TeamLeaderBranchUploadView(APIView):
    """Import the team-leader pivot listing (CSV or XLSX).

    Layout: a row holding a team-leader name, followed by rows holding the branches
    under them (until the next name). Header/label rows (Staff Role, Active, Row
    Labels, Grand Total) and blanks are ignored.
    """

    permission_classes = [IsAuthenticated]
    _SKIP = {"row labels", "grand total", "staff role", "active", "team leader", ""}

    def post(self, request):
        if not _is_admin(request.user):
            return Response({"detail": "Administrators only."}, status=status.HTTP_403_FORBIDDEN)

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rows = _read_upload_rows(upload)
        except Exception as exc:
            return Response({"detail": f"Could not read the file: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        mappings = {}          # canonical branch -> team leader
        current_tl = None
        for row in rows:
            cells = [c.strip() for c in row if c and str(c).strip()]
            if not cells:
                continue
            val = cells[0].strip()
            low = val.lower()
            if low in self._SKIP:
                continue
            if "branch" in low:                       # a branch under the current TL
                if current_tl:
                    mappings[normalize_branch(val)] = current_tl
            else:                                      # a team-leader name
                current_tl = val

        if not mappings:
            return Response(
                {"detail": "No branch→team-leader rows found. Expected TL names followed by their branches."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = updated = 0
        for branch, tl in mappings.items():
            _, was_created = TeamLeaderBranch.objects.update_or_create(
                branch=branch, defaults={"team_leader": tl},
            )
            created += int(was_created)
            updated += int(not was_created)

        return Response({"created": created, "updated": updated, "team_leaders": sorted(set(mappings.values()))},
                        status=status.HTTP_200_OK)
