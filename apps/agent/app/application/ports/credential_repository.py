"""Credential repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.credential import CredentialMetadata


class CredentialRepository(Protocol):
    """Repository port for encrypted credential management."""

    async def store_secret(
        self,
        org_id: uuid.UUID,
        name: str,
        credential_type: str,
        plaintext: str,
        repo_id: uuid.UUID | None = None,
    ) -> CredentialMetadata:
        """Encrypt and persist a secret token or key."""
        ...

    async def retrieve_secret(
        self,
        org_id: uuid.UUID,
        name: str,
        repo_id: uuid.UUID | None = None,
    ) -> str:
        """Retrieve and decrypt a secret token or key."""
        ...

    async def list_by_org(self, org_id: uuid.UUID) -> list[CredentialMetadata]:
        """List non-sensitive metadata for all organization credentials."""
        ...

    async def revoke_secret(self, org_id: uuid.UUID, credential_id: uuid.UUID) -> None:
        """Hard delete a credential upon revocation."""
        ...
