"""
Customer–RM reallocation workflow (ported from the legacy backend).

Lifecycle of a transfer (CustomerTransferHistory.approval_status):
    under_review → rm_approved → approved        (RM requests, counter-RM approves,
                                                  team leader finalises + moves the
                                                  customer in CustomerAllocationBase)
    under_review/rm_approved → rejected          (rejected at any step)
    tl_reallocation                              (team leader moves directly)

Permission mapping (legacy used rights-issue group names by copy-paste; the
reallocation personas are portfolio_mgt / tl_portfolio / exco, so we gate on
those):
    legacy RMPermissions / RightsIssuePermissions   → PortfolioMgtPermissions ("portfolio_mgt")
    legacy TLPermissions / TLRightsIssuePermissions → TlPortfolioPermissions  ("tl_portfolio")
    legacy excoPermissions                          → ExcoPermissions         ("exco")
"""
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import TotalPagesPagination
from core.permissions import (
    ExcoPermissions, PortfolioMgtPermissions, TlPortfolioPermissions,
)
from core.search import DynamicColumnSearchListView
from apps.portfolio.models import Profile
from .models import (
    CustomerAllocationBase, RmAllocationList, TeamLeaderMovementApprovers,
    CustomerTransferHistory,
)
from .serializers import (
    CustomerAllocationBaseSerializer, RmAllocationListSerializer,
    CustomerTransferHistorySerializer,
)

_TAG = "Reallocation — Workflow"


def _profile(request):
    return get_object_or_404(Profile, user_id=request.user.id)


# ── Transfer actions ───────────────────────────────────────────────────────────

@extend_schema(tags=[_TAG])
class InitiateTransfer(APIView):
    """An RM requests that one of their customers be moved to another RM."""
    permission_classes = [IsAuthenticated, PortfolioMgtPermissions]

    def post(self, request, cust_id):
        profile = _profile(request)
        customer = get_object_or_404(CustomerAllocationBase, cust_id=cust_id)
        from_rm = get_object_or_404(RmAllocationList, rm_code=profile.sales_code)
        to_rm = get_object_or_404(RmAllocationList, rm_code=request.data.get("to_rm_code"))

        auto_approved = (to_rm.rm_code == "SBP001") or (customer.rm_code == "Unassigned")
        transfer = CustomerTransferHistory.objects.create(
            group_id=customer.group_id, cust_id=customer.cust_id,
            customer_name=customer.customer_name, main_segment=customer.main_segment,
            customer_branch_name=customer.customer_branch_name, cust_branch=customer.cust_branch,
            from_rm_code=from_rm.rm_code, from_rm_name=from_rm.rm_name,
            from_rm_role=from_rm.rm_role, from_rm_branch_name=from_rm.rm_branch_name,
            to_rm_code=to_rm.rm_code, to_rm_name=to_rm.rm_name,
            to_rm_role=to_rm.rm_role, to_rm_branch_name=to_rm.rm_branch_name,
            approval_status="rm_approved" if auto_approved else "under_review",
            approved_by_team_leader="Pending",
            requesting_comments=request.data.get("requesting_comments") or "",
            approval_comments="",
        )
        return Response(CustomerTransferHistorySerializer(transfer).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=[_TAG])
class ApproveTransfer(APIView):
    """The counter-RM approves a pending transfer (under_review → rm_approved)."""
    permission_classes = [IsAuthenticated, PortfolioMgtPermissions]

    def post(self, request, cust_id, transfer_id):
        profile = _profile(request)
        transfer = get_object_or_404(CustomerTransferHistory, id=transfer_id, cust_id=cust_id)

        if transfer.from_rm_code == profile.sales_code:
            return Response({"status": "You do not have permission to approve this transfer."},
                            status=status.HTTP_403_FORBIDDEN)
        if transfer.approval_status == "under_review":
            transfer.approval_status = "rm_approved"
            transfer.approval_comments = request.data.get("approval_comments") or ""
            transfer.requesting_comments = ""
            transfer.save()
            return Response(CustomerTransferHistorySerializer(transfer).data, status=status.HTTP_200_OK)
        return Response({"status": "Approval not valid."}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=[_TAG])
class TeamLeaderApproveTransfer(APIView):
    """Team leader finalises an rm_approved transfer and moves the customer."""
    permission_classes = [IsAuthenticated, TlPortfolioPermissions]

    def post(self, request, cust_id, transfer_id):
        approval_comments = request.data.get("approval_comments")
        if not approval_comments:
            return Response({"error": "Invalid request. Missing required fields."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            profile = _profile(request)
            transfer = get_object_or_404(CustomerTransferHistory, id=transfer_id, cust_id=cust_id)
            customer = get_object_or_404(CustomerAllocationBase, cust_id=cust_id)
            team_leader = get_object_or_404(TeamLeaderMovementApprovers, sales_code=profile.sales_code)
        except ObjectDoesNotExist as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        if transfer.approval_status != "rm_approved":
            return Response({"error": "You cannot approve transfer before rm approval."},
                            status=status.HTTP_400_BAD_REQUEST)
        if team_leader.segment != transfer.main_segment:
            return Response({"error": "You cannot transfer customers outside your segment."},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            transfer.approved_by_team_leader = team_leader.name
            transfer.approval_status = "approved"
            transfer.approval_comments = approval_comments
            transfer.requesting_comments = ""
            transfer.save()

            customer.rm_code = transfer.from_rm_code
            customer.rm_name = transfer.from_rm_name
            customer.rm_role = transfer.from_rm_role
            customer.rm_branch_name = transfer.from_rm_branch_name
            customer.save()

        return Response(CustomerTransferHistorySerializer(transfer).data, status=status.HTTP_200_OK)


@extend_schema(tags=[_TAG])
class TeamLeaderInitiateCustomerRMTransfer(APIView):
    """Team leader directly reallocates a customer to a new RM (no RM step)."""
    permission_classes = [IsAuthenticated, TlPortfolioPermissions]

    def post(self, request, cust_id):
        to_rm_code = request.data.get("to_rm_code")
        approval_comments = request.data.get("approval_comments")
        if not to_rm_code or not approval_comments:
            return Response({"error": "Invalid request. Missing required fields."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            profile = _profile(request)
            customer = CustomerAllocationBase.objects.get(cust_id=cust_id)
            team_leader = TeamLeaderMovementApprovers.objects.get(sales_code=profile.sales_code)
            to_rm = RmAllocationList.objects.get(rm_code=to_rm_code)
        except ObjectDoesNotExist as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        if team_leader.segment != customer.main_segment:
            return Response({"error": "You cannot transfer customers outside your segment."},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            transfer = CustomerTransferHistory.objects.create(
                group_id=customer.group_id, cust_id=customer.cust_id,
                customer_name=customer.customer_name, main_segment=customer.main_segment,
                customer_branch_name=customer.customer_branch_name, cust_branch=customer.cust_branch,
                from_rm_code=customer.rm_code, from_rm_name=customer.rm_name,
                from_rm_role=customer.rm_role, from_rm_branch_name=customer.rm_branch_name,
                to_rm_code=to_rm.rm_code, to_rm_name=to_rm.rm_name,
                to_rm_role=to_rm.rm_role, to_rm_branch_name=to_rm.rm_branch_name,
                approved_by_team_leader=team_leader.name, approval_status="tl_reallocation",
                approval_comments=approval_comments, requesting_comments="",
            )
            CustomerAllocationBase.objects.filter(cust_id=customer.cust_id).update(
                rm_code=to_rm.rm_code, rm_name=to_rm.rm_name,
                rm_role=to_rm.rm_role, rm_branch_name=to_rm.rm_branch_name,
            )
        return Response(CustomerTransferHistorySerializer(transfer).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=[_TAG])
class RejectTransfer(APIView):
    """RM or TL rejects a transfer."""
    permission_classes = [IsAuthenticated, PortfolioMgtPermissions | TlPortfolioPermissions]

    def post(self, request, cust_id, transfer_id):
        profile = _profile(request)
        transfer = get_object_or_404(CustomerTransferHistory, id=transfer_id, cust_id=cust_id)
        tl_codes = TeamLeaderMovementApprovers.objects.values_list("sales_code", flat=True)

        if (transfer.from_rm_code == profile.sales_code
                or transfer.to_rm_code == profile.sales_code
                or profile.sales_code in tl_codes):
            is_tl = TlPortfolioPermissions().has_permission(request, self)
            transfer.approved_by_team_leader = "TL Rejected" if is_tl else "Rejected"
            transfer.approval_status = "rejected"
            transfer.approval_comments = request.data.get("approval_comments") or ""
            transfer.requesting_comments = ""
            transfer.save()
            return Response(CustomerTransferHistorySerializer(transfer).data, status=status.HTTP_200_OK)
        return Response({"status": "You are not authorized to reject this transfer."},
                        status=status.HTTP_403_FORBIDDEN)


@extend_schema(tags=[_TAG])
class TransferHistory(APIView):
    """Paginated transfer history for one customer."""
    permission_classes = [IsAuthenticated, PortfolioMgtPermissions | TlPortfolioPermissions]
    pagination_class = TotalPagesPagination

    def get(self, request, cust_id):
        get_object_or_404(CustomerAllocationBase, cust_id=cust_id)
        history = CustomerTransferHistory.objects.filter(cust_id=cust_id).order_by("-transfer_date")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(history, request)
        return paginator.get_paginated_response(
            CustomerTransferHistorySerializer(page, many=True).data
        )


# ── Transfer list views (hierarchical exco / TL / RM filtering) ─────────────────

class _HierarchicalTransferListView(generics.ListAPIView):
    """
    Base for the transfer worklists. Subclasses set ``base_filter`` (a Q on
    approval_status) and ``rm_q`` (callable sales_code -> Q for the RM tier).
    Visibility: exco → all; TL → own segment; RM → ``rm_q``; else → none.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerTransferHistorySerializer
    base_filter = Q()
    rm_q = staticmethod(lambda code: Q(from_rm_code=code) | Q(to_rm_code=code))

    def get_queryset(self):
        profile = get_object_or_404(Profile, user_id=self.request.user.id)
        qs = CustomerTransferHistory.objects.filter(self.base_filter, transfer_date__lte=timezone.now())

        if ExcoPermissions().has_permission(self.request, self):
            return qs
        if TlPortfolioPermissions().has_permission(self.request, self):
            return qs.filter(main_segment=profile.segment)
        if PortfolioMgtPermissions().has_permission(self.request, self):
            return qs.filter(self.rm_q(profile.sales_code))
        return qs.none()

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return Response(self.get_serializer(qs, many=True).data)


@extend_schema(tags=[_TAG])
class OpenTransferHistoryView(_HierarchicalTransferListView):
    base_filter = ~Q(approval_status__in=["approved", "rejected", "under_review", "tl_reallocation"])


@extend_schema(tags=[_TAG])
class FromOpenTransferHistoryView(_HierarchicalTransferListView):
    base_filter = ~Q(approval_status__in=["approved", "rejected", "rm_approved", "tl_reallocation"])
    rm_q = staticmethod(lambda code: Q(from_rm_code=code))


@extend_schema(tags=[_TAG])
class ToOpenTransferHistoryView(_HierarchicalTransferListView):
    base_filter = ~Q(approval_status__in=["approved", "rejected", "rm_approved", "tl_reallocation"])
    rm_q = staticmethod(lambda code: Q(to_rm_code=code))


@extend_schema(tags=[_TAG])
class ApprovedTransferHistoryView(_HierarchicalTransferListView):
    base_filter = Q(approval_status="approved")


@extend_schema(tags=[_TAG])
class RejectedTransferHistoryView(_HierarchicalTransferListView):
    base_filter = Q(approval_status="rejected")


@extend_schema(tags=[_TAG])
class TLReallocationTransferHistoryView(_HierarchicalTransferListView):
    base_filter = Q(approval_status="tl_reallocation")
    rm_q = staticmethod(lambda code: Q(to_rm_code=code))


# ── Lookups / lists ────────────────────────────────────────────────────────────

@extend_schema(tags=[_TAG])
class RmAllocationListView(generics.ListAPIView):
    """Active RMs available as transfer targets."""
    permission_classes = [IsAuthenticated]
    serializer_class = RmAllocationListSerializer
    queryset = RmAllocationList.objects.filter(rm_active_status="Active")


@extend_schema(tags=[_TAG])
class FilterCustomerAllocationBaseView(DynamicColumnSearchListView):
    """Dynamic any-column filter over the customer allocation base."""
    serializer_class = CustomerAllocationBaseSerializer
    search_model = CustomerAllocationBase
    pagination_class = TotalPagesPagination

    def get_base_queryset(self):
        return CustomerAllocationBase.objects.all().order_by("-aum_cust_id")


@extend_schema(tags=[_TAG])
class CustomerAllocationByCustIdView(APIView):
    """The allocation record for one customer (by cust_id)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, cust_id):
        customer = get_object_or_404(CustomerAllocationBase, cust_id=cust_id)
        return Response(CustomerAllocationBaseSerializer(customer).data)


# ── Feedback (transfer records) CRUD + history ─────────────────────────────────

@extend_schema(tags=[_TAG])
class TransferFeedbackDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerTransferHistorySerializer
    queryset = CustomerTransferHistory.objects.all()


@extend_schema(tags=[_TAG])
class TransferFeedbackHistoryView(APIView):
    """simple_history audit trail for a transfer record."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        records = CustomerTransferHistory.history.filter(id=pk).order_by("-history_date")
        return Response([
            {
                "id": h.id, "cust_id": h.cust_id, "customer_name": h.customer_name,
                "from_rm_name": h.from_rm_name, "to_rm_name": h.to_rm_name,
                "approval_status": h.approval_status, "approval_comments": h.approval_comments,
                "requesting_comments": h.requesting_comments,
                "approved_by_team_leader": h.approved_by_team_leader,
                "history_type": h.history_type, "history_date": h.history_date,
            }
            for h in records
        ])


# ── Bulk load + EXCO strategy override ─────────────────────────────────────────

@extend_schema(tags=[_TAG])
class CustomerAllocationBaseCSVUploadView(APIView):
    """Upsert CustomerAllocationBase rows from a CSV (keyed on cust_id)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import csv
        import io

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "No file uploaded. Send a CSV in the 'file' field."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response({"detail": "File must be UTF-8 encoded CSV."},
                            status=status.HTTP_400_BAD_REQUEST)

        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return Response({"detail": "CSV has no data rows."}, status=status.HTTP_400_BAD_REQUEST)

        created, updated, errors = 0, 0, []
        for idx, row in enumerate(rows):
            cust_id = (row.get("cust_id") or "").strip()
            if not cust_id:
                errors.append({"row": idx + 2, "errors": "missing cust_id"})
                continue
            existing = CustomerAllocationBase.objects.filter(cust_id=cust_id).first()
            ser = CustomerAllocationBaseSerializer(existing, data=row, partial=bool(existing))
            if ser.is_valid():
                ser.save()
                updated += 1 if existing else 0
                created += 0 if existing else 1
            else:
                errors.append({"row": idx + 2, "errors": ser.errors})

        return Response(
            {"created": created, "updated": updated, "errors": errors[:50], "error_count": len(errors)},
            status=status.HTTP_201_CREATED if (created or updated) else status.HTTP_400_BAD_REQUEST,
        )


@extend_schema(tags=[_TAG])
class PortfolioAllocationUpdateView(APIView):
    """
    EXCO strategy-override: sync retail_allocated_portfolio from
    customer_allocation_base. The legacy implementation runs a single raw-SQL
    statement joining customer_allocation_base (now the APP db) with
    retail_allocated_portfolio + branch_employee_dmc_data (the WAREHOUSE db).
    Under the new two-database split those tables live in different connections,
    so the cross-database join cannot run here. Disabled with a clear message
    rather than silently writing partial/incorrect warehouse data.
    """
    permission_classes = [IsAuthenticated, ExcoPermissions]

    def post(self, request):
        return Response(
            {"detail": "Portfolio allocation sync is unavailable in the split-database "
                       "deployment (customer_allocation_base is in the application DB while "
                       "retail_allocated_portfolio is in the warehouse). Run the sync where "
                       "both tables are co-located, or migrate it to a cross-DB ETL job."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
