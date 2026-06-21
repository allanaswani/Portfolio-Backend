from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination
import django_filters.rest_framework

from .models import (
    ExcoInitiative, StrategicExcoOwner, StrategicThrust,
    StrategicInitiative, StrategicMilestone,
)
from .serializers import (
    ExcoInitiativeSerializer, StrategicExcoOwnerSerializer,
    StrategicThrustSerializer, StrategicInitiativeSerializer,
    StrategicMilestoneSerializer,
)


@extend_schema(tags=["ExCo Initiatives"])
class ExcoInitiativeListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ExcoInitiativeSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["status", "priority", "owner", "sponsor"]
    queryset = ExcoInitiative.objects.all()


@extend_schema(tags=["ExCo Initiatives"])
class ExcoInitiativeDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ExcoInitiativeSerializer
    queryset = ExcoInitiative.objects.all()


# ── Strategic execution hierarchy: Owner → Thrust → Initiative → Milestone ─────

@extend_schema(tags=["ExCo — Strategic Owners"])
class StrategicExcoOwnerListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicExcoOwnerSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["owner_division", "owner_designation", "sales_code"]
    queryset = StrategicExcoOwner.objects.all()


@extend_schema(tags=["ExCo — Strategic Owners"])
class StrategicExcoOwnerDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicExcoOwnerSerializer
    queryset = StrategicExcoOwner.objects.all()


@extend_schema(tags=["ExCo — Strategic Thrusts"])
class StrategicThrustListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicThrustSerializer
    pagination_class = StandardPagination
    queryset = StrategicThrust.objects.all()


@extend_schema(tags=["ExCo — Strategic Thrusts"])
class StrategicThrustDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicThrustSerializer
    queryset = StrategicThrust.objects.all()


@extend_schema(tags=["ExCo — Strategic Initiatives"])
class StrategicInitiativeListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicInitiativeSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["thrust", "initiative_status", "primary_owner"]
    queryset = StrategicInitiative.objects.all()


@extend_schema(tags=["ExCo — Strategic Initiatives"])
class StrategicInitiativeDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicInitiativeSerializer
    queryset = StrategicInitiative.objects.all()


@extend_schema(tags=["ExCo — Strategic Initiatives"])
class StrategicInitiativeMilestonesView(generics.ListAPIView):
    """Milestones belonging to a given initiative."""
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicMilestoneSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return StrategicMilestone.objects.filter(
            initiative_id=self.kwargs["initiative_id"]
        )


@extend_schema(tags=["ExCo — Strategic Milestones"])
class StrategicMilestoneListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicMilestoneSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["thrust", "initiative", "milestone_status", "review_status"]
    queryset = StrategicMilestone.objects.all()


@extend_schema(tags=["ExCo — Strategic Milestones"])
class StrategicMilestoneDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StrategicMilestoneSerializer
    queryset = StrategicMilestone.objects.all()


@extend_schema(tags=["ExCo — Strategic Milestones"])
class StrategicMilestoneHistoryView(APIView):
    """Audit trail (simple_history) for a single milestone."""
    permission_classes = [IsAuthenticated]

    def get(self, request, milestone_id):
        history = StrategicMilestone.history.filter(milestone_id=milestone_id).order_by("-history_date")
        data = [
            {
                "milestone_id": h.milestone_id,
                "milestone_name": h.milestone_name,
                "milestone_status": h.milestone_status,
                "review_status": h.review_status,
                "proportion_complete": h.proportion_complete,
                "approved_proportion_complete": h.approved_proportion_complete,
                "user_comments": h.user_comments,
                "admin_comments": h.admin_comments,
                "history_type": h.history_type,
                "history_date": h.history_date,
            }
            for h in history
        ]
        return Response(data)


# ── Dashboard summary aggregations (raw SQL, ported from legacy) ────────────────
# These read the same tables the hierarchy models own (exco_strategic_thrust /
# _initiatives / _milestones / exco_owners). The legacy views fetched a Profile
# that they never used — dropped here.

@extend_schema(tags=["ExCo — Summaries"])
class SummaryOfThrustByInitiatives(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = StrategicThrust.objects.raw("""
            SELECT est.thrust_id, thrust_name,
                   COUNT(DISTINCT initiative_id) AS number_of_initiatives
            FROM exco_strategic_thrust est
            LEFT JOIN exco_strategic_initiatives esi ON est.thrust_id = esi.thrust_id
            GROUP BY 1, 2
        """)
        return Response([
            {"thrust_name": x.thrust_name, "number_of_initiatives": x.number_of_initiatives}
            for x in rows
        ])


@extend_schema(tags=["ExCo — Summaries"])
class SummaryOfInitiativesByQuarters(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = StrategicInitiative.objects.raw("""
            SELECT initiative_id,
                   DATE_TRUNC('month', initiative_end_date) AS month,
                   COUNT(initiative_id) OVER (PARTITION BY DATE_TRUNC('month', initiative_end_date)) AS number_of_initiatives
            FROM exco_strategic_initiatives
            GROUP BY initiative_id, DATE_TRUNC('month', initiative_end_date)
            ORDER BY month
        """)
        by_month = {}
        for x in rows:
            if x.month is None:
                continue
            key = x.month.strftime("%Y-%m")
            if key not in by_month:
                by_month[key] = {"month": key, "number_of_initiatives": x.number_of_initiatives}
        return Response(list(by_month.values()))


@extend_schema(tags=["ExCo — Summaries"])
class SummaryInitiativesByPrimaryOwnership(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = StrategicExcoOwner.objects.raw("""
            WITH primary_count AS (
                SELECT primary_owner AS owner, COUNT(*) AS primary_count
                FROM exco_strategic_initiatives GROUP BY primary_owner
            ),
            co_owner_count AS (
                SELECT co_owner_1 AS owner FROM exco_strategic_initiatives
                UNION ALL SELECT co_owner_2 FROM exco_strategic_initiatives
                UNION ALL SELECT co_owner_3 FROM exco_strategic_initiatives
                UNION ALL SELECT co_owner_4 FROM exco_strategic_initiatives
                UNION ALL SELECT co_owner_5 FROM exco_strategic_initiatives
                UNION ALL SELECT co_owner_6 FROM exco_strategic_initiatives
                UNION ALL SELECT co_owner_7 FROM exco_strategic_initiatives
            ),
            co_owner_aggregated AS (
                SELECT owner, COUNT(*) AS co_owner_count
                FROM co_owner_count WHERE owner IS NOT NULL GROUP BY owner
            ),
            initiative_details AS (
                SELECT primary_owner,
                    json_agg(json_build_object(
                        'initiative_id', initiative_id,
                        'initiative_name', initiative_name,
                        'initiative_start_date', initiative_start_date,
                        'initiative_end_date', initiative_end_date,
                        'recording_date', recording_date,
                        'co_owners', ARRAY[co_owner_1, co_owner_2, co_owner_3, co_owner_4, co_owner_5, co_owner_6, co_owner_7],
                        'initiative_status', initiative_status,
                        'thrust_id', thrust_id
                    )) AS initiatives
                FROM exco_strategic_initiatives GROUP BY primary_owner
            )
            SELECT DISTINCT ON (eo.owner_name)
                eo.owner_id, eo.owner_name, eo.owner_division,
                COALESCE(p.primary_count, 0) AS primary_owner_count,
                COALESCE(c.co_owner_count, 0) AS co_owner_count,
                id.initiatives
            FROM exco_owners AS eo
            LEFT JOIN primary_count p ON eo.owner_name = p.owner
            LEFT JOIN co_owner_aggregated c ON eo.owner_name = c.owner
            LEFT JOIN initiative_details id ON eo.owner_name = id.primary_owner
        """)
        return Response([
            {
                "owner_id": x.owner_id, "owner_name": x.owner_name,
                "owner_division": x.owner_division,
                "primary_owner_count": x.primary_owner_count,
                "co_owner_count": x.co_owner_count, "initiatives": x.initiatives,
            }
            for x in rows
        ])


# Shared SELECT body for the per-thrust initiative summaries (with milestones).
_PER_THRUST_SQL = """
    WITH ranked_initiatives AS (
        SELECT esi.initiative_id, est.thrust_name, esi.initiative_name, esi.primary_owner,
               esi.co_owner_1, esi.co_owner_2, esi.co_owner_3, esi.co_owner_4,
               esi.co_owner_5, esi.co_owner_6, esi.co_owner_7,
               esi.initiative_start_date, esi.initiative_end_date, esi.initiative_status,
               ROW_NUMBER() OVER (PARTITION BY esi.primary_owner, esi.initiative_name ORDER BY esi.primary_owner) AS rn
        FROM exco_strategic_initiatives esi
        LEFT JOIN exco_strategic_thrust est ON esi.thrust_id = est.thrust_id
    ),
    milestones_agg AS (
        SELECT esm.initiative_id, COUNT(esm.milestone_id) AS no_of_milestones,
               AVG(esm.approved_proportion_complete) AS approve_rating,
               json_agg(json_build_object(
                   'milestone_id', esm.milestone_id, 'milestone_name', esm.milestone_name,
                   'review_status', esm.review_status,
                   'milestone_description', esm.milestone_description,
                   'milestone_start_date', esm.milestone_start_date,
                   'milestone_end_date', esm.milestone_end_date, 'recording_date', esm.recording_date,
                   'primary_owner', esm.primary_owner,
                   'co_owners', ARRAY[esm.co_owner_1, esm.co_owner_2, esm.co_owner_3, esm.co_owner_4, esm.co_owner_5, esm.co_owner_6, esm.co_owner_7],
                   'milestone_status', esm.milestone_status, 'update_type', esm.update_type,
                   'proportion_contribution', esm.proportion_contribution,
                   'proportion_complete', esm.proportion_complete,
                   'approved_proportion_complete', esm.approved_proportion_complete,
                   'initiative_id', esm.initiative_id, 'thrust_id', esm.thrust_id
               )) AS milestones
        FROM exco_strategic_milestones esm
        {milestone_where}
        GROUP BY esm.initiative_id
    )
    SELECT ri.initiative_id, ri.thrust_name, ri.initiative_name, ri.primary_owner,
           ri.co_owner_1, ri.co_owner_2, ri.co_owner_3, ri.co_owner_4,
           ri.co_owner_5, ri.co_owner_6, ri.co_owner_7,
           ri.initiative_start_date, ri.initiative_end_date, ri.initiative_status,
           ma.no_of_milestones, ma.approve_rating, ma.milestones
    FROM ranked_initiatives ri
    LEFT JOIN milestones_agg ma ON ri.initiative_id = ma.initiative_id
    WHERE ri.rn = 1 {extra_where}
    ORDER BY ri.primary_owner
"""


def _serialize_per_thrust(rows):
    return [
        {
            "thrust_name": x.thrust_name, "initiative_id": x.initiative_id,
            "initiative_name": x.initiative_name, "primary_owner": x.primary_owner,
            "co_owner_1": x.co_owner_1, "co_owner_2": x.co_owner_2, "co_owner_3": x.co_owner_3,
            "co_owner_4": x.co_owner_4, "co_owner_5": x.co_owner_5, "co_owner_6": x.co_owner_6,
            "co_owner_7": x.co_owner_7,
            "initiative_start_date": getattr(x, "initiative_start_date", None),
            "initiative_end_date": x.initiative_end_date, "initiative_status": x.initiative_status,
            "no_of_milestones": x.no_of_milestones, "approve_rating": x.approve_rating,
            "milestones": x.milestones,
        }
        for x in rows
    ]


@extend_schema(tags=["ExCo — Summaries"])
class SummaryInitiativesByPrimaryOwnershipPerThrust(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = _PER_THRUST_SQL.format(milestone_where="", extra_where="")
        return Response(_serialize_per_thrust(StrategicInitiative.objects.raw(sql)))


@extend_schema(tags=["ExCo — Summaries"])
class SummaryInitiativesByPrimaryOwnershipPerThrustOverdue(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = _PER_THRUST_SQL.format(
            milestone_where="",
            extra_where="AND lower(ri.initiative_status) != 'closed' AND ri.initiative_end_date <= current_date",
        )
        return Response(_serialize_per_thrust(StrategicInitiative.objects.raw(sql)))


@extend_schema(tags=["ExCo — Summaries"])
class SummaryInitiativesByPrimaryOwnershipPerThrustReview(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sql = _PER_THRUST_SQL.format(
            milestone_where="WHERE esm.review_status IN ('Rejected', 'Under Review', 'Approved')",
            extra_where="AND ma.milestones IS NOT NULL",
        )
        return Response(_serialize_per_thrust(StrategicInitiative.objects.raw(sql)))


@extend_schema(tags=["ExCo — Summaries"])
class SummaryAvgApprovedProportion(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = StrategicThrust.objects.raw("""
            SELECT est.thrust_id, est.thrust_name, esi.initiative_id, esi.initiative_name,
                   esi.primary_owner, AVG(esm.approved_proportion_complete) AS avg_complete
            FROM exco_strategic_thrust est
            LEFT JOIN exco_strategic_initiatives esi ON est.thrust_id = esi.thrust_id
            LEFT JOIN exco_strategic_milestones esm ON est.thrust_id = esm.thrust_id
            GROUP BY est.thrust_id, est.thrust_name, esi.initiative_name, esi.initiative_id, esi.primary_owner
        """)
        return Response([
            {
                "thrust_id": x.thrust_id, "thrust_name": x.thrust_name,
                "initiative_id": x.initiative_id, "initiative_name": x.initiative_name,
                "primary_owner": x.primary_owner, "avg_complete": x.avg_complete,
            }
            for x in rows
        ])
