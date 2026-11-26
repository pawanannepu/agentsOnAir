"""Shared Clerk RS256 keypair and JWT helpers for FastAPI integration tests."""

from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_rsa_keypair() -> tuple[bytes, str]:
    """Generate an ephemeral RS256 keypair for testing Clerk JWT verification."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def make_clerk_jwt(
    private_pem: bytes,
    *,
    user_id: str = "user_clerk_test_1",
    clerk_org_id: str | None = None,
    org_role: str | None = "org:member",
    expired: bool = False,
) -> str:
    """Create a signed RS256 Clerk session JWT for tests."""
    now = datetime.now(UTC)
    exp = now - timedelta(minutes=5) if expired else now + timedelta(minutes=15)
    payload: dict = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if clerk_org_id:
        payload["org_id"] = clerk_org_id
    if org_role:
        payload["org_role"] = org_role
    return jwt.encode(payload, private_pem, algorithm="RS256")
