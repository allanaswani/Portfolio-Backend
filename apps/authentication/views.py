import random
import string
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.portfolio.models import OTP
from apps.portfolio.serializers import ChangePasswordSerializer, LogoutSerializer


class OTPRequestThrottle(UserRateThrottle):
    scope = "otp_request"


@extend_schema(tags=["Authentication"])
class ChangePasswordView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def get_object(self):
        return get_object_or_404(User, pk=self.kwargs["pk"])

    def update(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        otp_code = serializer.validated_data.get("otp")
        if otp_code:
            otp_qs = OTP.objects.filter(user=user).order_by("-created_at")
            if not otp_qs.exists() or otp_qs.first().otp != otp_code or otp_qs.first().is_expired():
                return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(serializer.validated_data["old_password"]):
            return Response({"detail": "Wrong current password."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data["new_password"])
        user.save()
        return Response({"detail": "Password changed successfully."}, status=status.HTTP_200_OK)


@extend_schema(tags=["Authentication"])
class LogoutAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            token.blacklist()
        except Exception:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Authentication"])
class GenerateOTPView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        user = request.user
        otp_code = "".join(random.choices(string.digits, k=6))
        expires_at = timezone.now() + timedelta(minutes=5)
        OTP.objects.filter(user=user).delete()
        OTP.objects.create(user=user, otp=otp_code, expires_at=expires_at)

        try:
            send_mail(
                subject="Your OTP Code",
                message=f"Your OTP is: {otp_code}. It expires in 5 minutes.",
                from_email="reports.analytics@hfgroup.co.ke",
                recipient_list=[user.email],
            )
        except Exception:
            pass

        if settings.DEBUG:
            print(f"[DEBUG] Generated OTP for {user.email}: {otp_code}")

        return Response({"detail": "OTP sent to your email."}, status=status.HTTP_200_OK)


@extend_schema(tags=["Authentication"])
class VerifyOTPView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        otp_code = request.data.get("otp")
        if not otp_code:
            return Response({"detail": "OTP is required."}, status=status.HTTP_400_BAD_REQUEST)

        qs = OTP.objects.filter(user=request.user).order_by("-created_at")
        if not qs.exists():
            return Response({"detail": "No OTP found."}, status=status.HTTP_400_BAD_REQUEST)

        otp_obj = qs.first()
        if otp_obj.otp != otp_code:
            return Response({"detail": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)
        if otp_obj.is_expired():
            return Response({"detail": "OTP has expired."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "OTP verified successfully."}, status=status.HTTP_200_OK)


def password_reset_token_created(sender, instance, reset_password_token, *args, **kwargs):
    """Signal handler for django-rest-passwordreset."""
    send_mail(
        subject="Password Reset Request",
        message=(
            f"Hi {instance.user.first_name},\n\n"
            f"Use this token to reset your password: {reset_password_token.key}\n\n"
            "This token expires in 24 hours."
        ),
        from_email="reports.analytics@hfgroup.co.ke",
        recipient_list=[instance.user.email],
    )


# ===========================================================================
# Admin user management — clean replacement for the Django admin UI.
# Only administrators (staff or superuser) may manage users.
# ===========================================================================

from django.contrib.auth.models import Group  # noqa: E402
from rest_framework.generics import (  # noqa: E402
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import BasePermission  # noqa: E402

from .serializers import (  # noqa: E402
    AdminUserSerializer,
    RoleSerializer,
    SetPasswordSerializer,
)


class IsAdministrator(BasePermission):
    """Staff or superuser may manage users."""

    message = "Administrator privileges are required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and (u.is_staff or u.is_superuser))


@extend_schema(tags=["Admin — Users"])
class AdminUserListCreateView(ListCreateAPIView):
    """GET: list users (with roles + profile). POST: create a user and assign roles."""

    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = AdminUserSerializer

    def get_queryset(self):
        qs = (
            User.objects.all()
            .select_related("profile")
            .prefetch_related("groups")
            .order_by("username")
        )
        search = self.request.query_params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(groups__name=role)
        active = self.request.query_params.get("is_active")
        if active in ("true", "false"):
            qs = qs.filter(is_active=(active == "true"))
        return qs


@extend_schema(tags=["Admin — Users"])
class AdminUserDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH a user. DELETE deactivates (soft) rather than destroying."""

    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = AdminUserSerializer
    queryset = User.objects.all().select_related("profile").prefetch_related("groups")

    def perform_destroy(self, instance):
        # Soft-delete: deactivate so history/relations are preserved.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


@extend_schema(tags=["Admin — Users"])
class AdminSetPasswordView(APIView):
    """POST a new password for a user (or omit to auto-generate one)."""

    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.save(user)
        return Response(
            {"detail": "Password updated.", "password": raw},
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Admin — Users"])
class RoleListView(generics.ListAPIView):
    """List all assignable roles (Django Groups) for the Users screen.

    Unpaginated — the full role set is small and feeds a dropdown.
    """

    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = RoleSerializer
    pagination_class = None

    def get_queryset(self):
        return Group.objects.all().order_by("name")
