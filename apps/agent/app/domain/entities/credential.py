"""Credential domain entity and metadata DTO."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Credential:
    """Encrypted credential entity."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID | None
    name: str
    credential_type: str
    encrypted_data: str
    nonce: str
    key_version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class CredentialMetadata:
    """Non-sensitive credential metadata for safe API responses."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID | None
    name: str
    credential_type: str
    key_version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None
