"""Clerk RS256 JWT verification using PyJWT and JWKS or PEM public key."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWKClient

from app.domain.exceptions import AuthenticationError


@dataclass(frozen=True, slots=True)
class ClerkUserContext:
    """Verified caller identity and tenant organization extracted from Clerk JWT."""

    user_id: str
    clerk_org_id: str | None
    org_role: str | None
    claims: dict[str, Any]


@lru_cache(maxsize=8)
def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    """Return a cached PyJWKClient instance for a Clerk JWKS endpoint."""
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def _normalize_org_role(raw_role: Any) -> str | None:
    """Normalize Clerk v2 compact roles (e.g. 'admin') to canonical 'org:*' format."""
    if raw_role is None:
        return None
    role = str(raw_role).strip()
    if not role:
        return None
    if role == "admin":
        return "org:admin"
    if role in ("member", "basic_member"):
        return "org:member"
    return role


def verify_clerk_jwt(
    token: str,
    *,
    jwt_key: str | None = None,
    issuer_url: str | None = None,
) -> ClerkUserContext:
    """Verify a Clerk session JWT and return extracted identity claims."""
    if not token:
        raise AuthenticationError("Missing bearer token")

    try:
        if jwt_key:
            pem_key = jwt_key.replace("\\n", "\n")
            claims = jwt.decode(
                token,
                pem_key,
                algorithms=["RS256"],
                options={"require": ["exp", "sub"]},
            )
        elif issuer_url:
            clean_issuer = issuer_url.rstrip("/")
            jwk_client = _get_jwk_client(f"{clean_issuer}/.well-known/jwks.json")
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=clean_issuer,
                options={"require": ["exp", "sub"]},
            )
        else:
            raise AuthenticationError(
                "Clerk JWT verification key or issuer URL is not configured"
            )
    except AuthenticationError:
        raise
    except InvalidTokenError as exc:
        raise AuthenticationError(f"Invalid or expired Clerk token: {exc}") from exc
    except Exception as exc:
        raise AuthenticationError(f"Token verification failed: {exc}") from exc

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise AuthenticationError("Token missing subject claim")

    org_claim = claims.get("o")
    nested_org_id = org_claim.get("id") if isinstance(org_claim, dict) else None
    nested_org_role = org_claim.get("rol") if isinstance(org_claim, dict) else None

    clerk_org_id = claims.get("org_id") or nested_org_id
    raw_org_role = claims.get("org_role") or nested_org_role

    return ClerkUserContext(
        user_id=user_id,
        clerk_org_id=str(clerk_org_id) if clerk_org_id else None,
        org_role=_normalize_org_role(raw_org_role),
        claims=dict(claims),
    )
