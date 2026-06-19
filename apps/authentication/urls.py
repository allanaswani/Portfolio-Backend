from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    ChangePasswordView, LogoutAPIView, GenerateOTPView, VerifyOTPView,
    AdminUserListCreateView, AdminUserDetailView, AdminSetPasswordView, RoleListView,
)

urlpatterns = [
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("change_password/<int:pk>/", ChangePasswordView.as_view(), name="auth_change_password"),
    path("logout/", LogoutAPIView.as_view(), name="auth_logout"),
    path("generate-otp/", GenerateOTPView.as_view(), name="generate_otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify_otp"),

    # Admin user management (staff/superuser only)
    path("users/", AdminUserListCreateView.as_view(), name="admin_user_list_create"),
    path("users/<int:pk>/", AdminUserDetailView.as_view(), name="admin_user_detail"),
    path("users/<int:pk>/set-password/", AdminSetPasswordView.as_view(), name="admin_user_set_password"),
    path("roles/", RoleListView.as_view(), name="admin_role_list"),
]
