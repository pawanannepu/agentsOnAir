"""HTTPX adapter for Clerk Backend API organization lookups."""

import httpx

from app.application.ports.clerk_gateway import (
    ClerkOrganizationGateway,
    ClerkOrganizationInfo,
)
from app.domain.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    NotFoundError,
)

PLACEHOLDER_CLERK_SECRETS = {"sk_test_placeholder", ""}


class HttpxClerkOrganizationGateway(ClerkOrganizationGateway):
    """Fetches organization metadata from Clerk Backend API with a 5.0s timeout."""

    def __init__(
        self,
        secret_key: str | None,
        *,
        base_url: str = "https://api.clerk.com",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._secret_key = secret_key.strip() if secret_key else None
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def get_organization(self, clerk_org_id: str) -> ClerkOrganizationInfo:
        if not self._secret_key or self._secret_key in PLACEHOLDER_CLERK_SECRETS:
            raise ConfigurationError(
                "CLERK_SECRET_KEY is not configured for Clerk Backend API sync"
            )

        url = f"{self._base_url}/v1/organizations/{clerk_org_id}"
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                f"Clerk Backend API request failed: {exc}"
            ) from exc

        if response.status_code == 404:
            raise NotFoundError(
                f"Clerk organization '{clerk_org_id}' does not exist or is inactive"
            )
        if response.status_code >= 400:
            raise ExternalServiceError(
                f"Clerk Backend API returned HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ExternalServiceError(
                "Clerk Backend API returned invalid JSON payload"
            ) from exc

        resolved_id = str(data.get("id") or clerk_org_id)
        name = str(data.get("name") or resolved_id)
        raw_slug = data.get("slug")
        slug = (
            str(raw_slug)
            if isinstance(raw_slug, str) and raw_slug.strip()
            else f"org-{resolved_id.lower()}"
        )
        return ClerkOrganizationInfo(
            clerk_org_id=resolved_id,
            name=name,
            slug=slug,
        )
