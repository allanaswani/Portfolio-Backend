import logging
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _brand():
    return getattr(settings, "APP_BRAND_NAME", "HFCB")


def _access_links_block():
    """Footer listing both ways to reach the tool — off-LAN and on-LAN."""
    pub = (getattr(settings, "FRONTEND_PUBLIC_URL", "") or "").rstrip("/")
    lan = (getattr(settings, "FRONTEND_LAN_URL", "") or "").rstrip("/")
    lines = ["Access the tool here:"]
    if pub:
        lines.append(f"  - Off-network (internet): {pub}")
    if lan:
        lines.append(f"  - On-network (office LAN): {lan}")
    return "\n".join(lines)


def _reset_links_block(token):
    """Both password-reset links (off-LAN + on-LAN) carrying the token."""
    pub = (getattr(settings, "FRONTEND_PUBLIC_URL", "") or "").rstrip("/")
    lan = (getattr(settings, "FRONTEND_LAN_URL", "") or "").rstrip("/")
    lines = []
    if pub:
        lines.append(f"  - Off-network (internet): {pub}/reset_password/confirm/{token}")
    if lan:
        lines.append(f"  - On-network (office LAN): {lan}/reset_password/confirm/{token}")
    return "\n".join(lines)
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


class OTPVerifyThrottle(UserRateThrottle):
    """Caps OTP *verification* attempts so the 6-digit code can't be brute-forced
    (1M combinations). Without this the verify endpoint had no attempt limit."""
    scope = "otp_verify"


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
        # secrets (CSPRNG), not random (Mersenne Twister) — OTP codes must not be
        # predictable from previously observed outputs.
        otp_code = "".join(secrets.choice(string.digits) for _ in range(6))
        expires_at = timezone.now() + timedelta(minutes=5)
        OTP.objects.filter(user=user).delete()
        OTP.objects.create(user=user, otp=otp_code, expires_at=expires_at)

        try:
            send_mail(
                subject=f"Your {_brand()} OTP code",
                message=(
                    f"Your {_brand()} OTP is: {otp_code}. It expires in 5 minutes.\n\n"
                    f"{_access_links_block()}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )
        except Exception:
            logger.exception("OTP email failed for %s", user.email)

        if settings.DEBUG:
            print(f"[DEBUG] Generated OTP for {user.email}: {otp_code}")

        return Response({"detail": "OTP sent to your email."}, status=status.HTTP_200_OK)


@extend_schema(tags=["Authentication"])
class VerifyOTPView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OTPVerifyThrottle]

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
    """Signal handler for django-rest-passwordreset — emails the reset links.

    NOTE: in this library ``instance`` is the *view*, not the token. The user is
    on ``reset_password_token.user`` (using ``instance.user`` raised AttributeError
    and 500'd the endpoint before any mail was sent).
    """
    brand = _brand()
    token = reset_password_token.key
    user = reset_password_token.user
    greeting = user.first_name or user.username
    message = (
        f"Hi {greeting},\n\n"
        f"We received a request to reset your {brand} account password.\n\n"
        "Open one of the links below and follow the prompts to set a new password:\n\n"
        f"{_reset_links_block(token)}\n\n"
        f"If the links don't open, go to the reset page and paste this token:\n  {token}\n\n"
        "This link and token expire in 24 hours. If you didn't request this, "
        "you can safely ignore this email."
    )
    try:
        send_mail(
            subject=f"{brand} password reset",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
    except Exception:
        # Don't 500 the reset endpoint on a mail hiccup — but make the cause
        # visible in the container logs instead of failing silently.
        logger.exception("Password reset email failed for %s", user.email)


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


def _email_temp_password(email, username, password, *, is_reset=False):
    """Send an auto-generated / reset password to a user so they can log in and
    change it. Best-effort — never blocks the admin action if mail fails."""
    if not email:
        return
    brand = _brand()
    action = "reset" if is_reset else "created"
    try:
        send_mail(
            subject=f"Your {brand} account password",
            message=(
                f"Hello {username},\n\n"
                f"Your {brand} account has been {action}.\n\n"
                f"Username: {username}\n"
                f"Temporary password: {password}\n\n"
                "Please sign in with this temporary password and update it "
                "immediately from your profile settings.\n\n"
                f"{_access_links_block()}\n\n"
                "If you did not expect this email, contact your administrator."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
        )
    except Exception:
        logger.exception("Account password email failed for %s", email)


@extend_schema(tags=["Admin — Users"])
class AdminUserListCreateView(ListCreateAPIView):
    """GET: list users (with roles + profile). POST: create a user and assign roles."""

    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = AdminUserSerializer

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        # When no password was supplied the serializer auto-generates one and
        # surfaces it as `generated_password`; email it so the new user can log
        # in and update it. (If the admin set a password, they share it directly.)
        gen = response.data.get("generated_password")
        if gen:
            _email_temp_password(response.data.get("email"), response.data.get("username"), gen)
        return response

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
        # Email the (possibly auto-generated) password so the user can log in and
        # change it. Returned to the admin too, for out-of-band sharing.
        _email_temp_password(user.email, user.username, raw, is_reset=True)
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


@extend_schema(tags=["Admin — Users"])
class UserMetaChoicesView(APIView):
    """Branch & segment option lists for the Users screen dropdowns.

    Sourced from the Profile model's ``BRANCH_CHOICES`` / ``SEGMENT_CHOICES`` so
    the form can never store a branch/segment the profile field would reject —
    one source of truth, no free-text typos that would silently break RBAC
    branch scoping (RBACQueryFilter matches ``profile.branch`` exactly).
    """

    permission_classes = [IsAuthenticated, IsAdministrator]

    def get(self, request):
        from apps.portfolio.models import BRANCH_CHOICES, SEGMENT_CHOICES
        return Response({
            "branches": [value for value, _label in BRANCH_CHOICES],
            "segments": [value for value, _label in SEGMENT_CHOICES],
        })
