"""SQLAlchemy credential repository implementation."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.credential_repository import CredentialRepository
from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret
from app.domain.entities.credential import CredentialMetadata
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.models.credential import CredentialModel


def _to_metadata(model: CredentialModel) -> CredentialMetadata:
    return CredentialMetadata(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        name=model.name,
        credential_type=model.credential_type,
        key_version=model.key_version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyCredentialRepository(CredentialRepository):
    """Async SQLAlchemy adapter for encrypted Credential persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def store_secret(
        self,
        org_id: uuid.UUID,
        name: str,
        credential_type: str,
        plaintext: str,
        repo_id: uuid.UUID | None = None,
    ) -> CredentialMetadata:
        encrypted_data, nonce = encrypt_secret(
            plaintext=plaintext,
            key_base64=settings.CREDENTIALS_ENCRYPTION_KEY,
        )

        stmt = select(CredentialModel).where(
            CredentialModel.org_id == org_id,
            CredentialModel.name == name,
        )
        if repo_id is None:
            stmt = stmt.where(CredentialModel.repo_id.is_(None))
        else:
            stmt = stmt.where(CredentialModel.repo_id == repo_id)

        existing = (await self._session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.encrypted_data = encrypted_data
            existing.nonce = nonce
            existing.credential_type = credential_type
            existing.key_version += 1
            model = existing
        else:
            model = CredentialModel(
                org_id=org_id,
                repo_id=repo_id,
                name=name,
                credential_type=credential_type,
                encrypted_data=encrypted_data,
                nonce=nonce,
                key_version=1,
            )
            self._session.add(model)

        await self._session.flush()
        return _to_metadata(model)

    async def retrieve_secret(
        self,
        org_id: uuid.UUID,
        name: str,
        repo_id: uuid.UUID | None = None,
    ) -> str:
        stmt = select(CredentialModel).where(
            CredentialModel.org_id == org_id,
            CredentialModel.name == name,
        )
        if repo_id is None:
            stmt = stmt.where(CredentialModel.repo_id.is_(None))
        else:
            stmt = stmt.where(CredentialModel.repo_id == repo_id)

        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"Credential '{name}' not found for tenant organization"
            )

        return decrypt_secret(
            encrypted_data_base64=model.encrypted_data,
            nonce_base64=model.nonce,
            key_base64=settings.CREDENTIALS_ENCRYPTION_KEY,
        )

    async def list_by_org(self, org_id: uuid.UUID) -> list[CredentialMetadata]:
        stmt = (
            select(CredentialModel)
            .where(CredentialModel.org_id == org_id)
            .order_by(CredentialModel.created_at.desc())
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_metadata(m) for m in models]

    async def revoke_secret(self, org_id: uuid.UUID, credential_id: uuid.UUID) -> None:
        stmt = select(CredentialModel).where(
            CredentialModel.org_id == org_id,
            CredentialModel.id == credential_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Credential {credential_id} not found in organization")

        await self._session.delete(model)
        await self._session.flush()
