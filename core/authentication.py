"""The server's side of the second factor at sign-in.

``auth/api/token/`` answers a correct password with tokens, and the OTP page used to
be enforced only by the browser: a cookie named ``isVerified``. Anybody holding the
password could call the API directly, and Customer 360 accepts the same token, so it
stepped round that system's own second factor too.

So the token now says which it is. ``mfa: false`` comes from the password alone and
opens only the views marked ``allow_unverified_token``. ``verify-otp/`` issues the
pair with ``mfa: true``. A token issued before this change has no claim and is let
through until it expires.

**Whose token.** Customer 360 signs with the same key and keeps its own user table in
its own database, so its user number 5 and this system's user number 5 can be two
different people. The token's username has to match the account the number finds.
"""

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication


class SecondFactorJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return result
        user, token = result
        named = token.get("username")
        if named is not None and named != user.get_username():
            raise AuthenticationFailed(
                "This token was issued to a different account.", code="wrong_account")
        if not getattr(settings, "LOGIN_MFA_ENFORCED", False):
            return result
        if token.get("mfa") is False:
            context = getattr(request, "parser_context", None) or {}
            view = context.get("view")
            if not getattr(view, "allow_unverified_token", False):
                raise AuthenticationFailed(
                    "Enter the code sent to your e-mail first.", code="mfa_required")
        return result


class LoginAccountThrottle(SimpleRateThrottle):
    """Sign-in attempts per account named, so that guessing one person's password
    from many addresses is limited as well."""

    scope = "login_account"

    def get_cache_key(self, request, view):
        data = request.data if hasattr(request.data, "get") else {}
        username = str(data.get("username") or "").strip().lower()
        if not username:
            return None
        return self.cache_format % {"scope": self.scope, "ident": username}
