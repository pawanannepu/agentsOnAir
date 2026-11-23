"""Sandbox provider factory."""

from app.application.ports.sandbox import SandboxProvider
from app.core.config import settings
from app.infrastructure.sandbox.docker_sandbox import DockerSandboxProvider
from app.infrastructure.sandbox.e2b_sandbox import E2BSandboxProvider
from app.infrastructure.sandbox.mock_sandbox import MockSandboxProvider


def get_sandbox_provider(provider_name: str | None = None) -> SandboxProvider:
    """Return configured sandbox provider based on settings."""
    chosen = (provider_name or settings.SANDBOX_PROVIDER).lower()
    if chosen == "e2b":
        return E2BSandboxProvider(api_key=settings.E2B_API_KEY)
    elif chosen == "docker":
        return DockerSandboxProvider()
    else:
        return MockSandboxProvider()
