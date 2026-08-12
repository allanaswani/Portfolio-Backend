"""Enriched JWT — carries identity + RBAC so other HF systems can trust it.

The portfolio platform is the estate's authoritative identity provider: it owns the
user accounts, the role Groups and the Profile (branch / segment / sales_code). By
embedding those into the access token, a *resource server* such as Customer 360 can
authenticate a caller and resolve their book scope **from the token alone** — no
shared user database, no second login. Both backends sign with the same
``SIMPLE_JWT['SIGNING_KEY']`` (the shared ``SECRET_KEY``), so a token minted here
validates there.

The extra claims are additive and backward-compatible: the portfolio's own SPA
ignores them. Keep the claim shape in sync with Customer 360's
``c360/auth/claims.py::apply_claims`` — the two must agree field-for-field.
"""
from __future__ import annotations

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


def embed_identity_claims(token, user):
    """Write the shared identity + RBAC claims onto ``token`` (a RefreshToken).

    SimpleJWT copies these onto the derived access token, so the Bearer token the
    SPA sends carries them too.
    """
    profile = getattr(user, "profile", None)
    token["username"] = user.username
    token["email"] = user.email or ""
    token["name"] = user.get_full_name() or user.username
    token["is_staff"] = bool(user.is_staff)
    token["is_superuser"] = bool(user.is_superuser)
    token["is_active"] = bool(user.is_active)
    # Role Groups drive tiering (management vs RM) in every downstream system.
    token["groups"] = list(user.groups.values_list("name", flat=True))
    # Profile carries the RM's book identity + branch/segment scoping.
    token["sales_code"] = getattr(profile, "sales_code", None)
    token["branch"] = getattr(profile, "branch", None)
    token["segment"] = getattr(profile, "segment", None)
    return token


class EnrichedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Standard username/password → JWT pair, plus the shared identity claims."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        return embed_identity_claims(token, user)
