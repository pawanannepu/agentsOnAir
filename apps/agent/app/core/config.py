from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "agentsOnAir Agent Engine"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/agentsonair"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Ensure PostgreSQL URLs use the asyncpg driver and compatible query args."""
        if not isinstance(value, str):
            return value
        parsed = urlparse(value)
        scheme = parsed.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+asyncpg"
        elif scheme != "postgresql+asyncpg":
            return value

        raw_params = parse_qsl(parsed.query, keep_blank_values=True)
        has_ssl = any(k == "ssl" for k, _ in raw_params)
        sslmode = next((v for k, v in raw_params if k == "sslmode"), None)
        filtered = [
            (k, v) for k, v in raw_params if k not in ("sslmode", "channel_binding")
        ]
        if not has_ssl and sslmode in (
            "require",
            "verify-ca",
            "verify-full",
            "prefer",
        ):
            filtered.append(("ssl", "require"))

        return urlunparse(
            (
                scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(filtered),
                parsed.fragment,
            )
        )

    # Default 32-byte key base64-encoded for development/testing
    CREDENTIALS_ENCRYPTION_KEY: str = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

    # GitHub integration
    GITHUB_APP_ID: str | None = None
    GITHUB_APP_PRIVATE_KEY: str | None = None
    GITHUB_WEBHOOK_SECRET: str = "dev_webhook_secret"

    # Sandbox & Runner
    SANDBOX_PROVIDER: str = "docker"  # "e2b" or "docker"
    E2B_API_KEY: str | None = None
    SANDBOX_TIMEOUT_SECONDS: int = 600
    SANDBOX_COMMAND_TIMEOUT_SECONDS: int = 120

    # Model providers
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # Clerk authentication
    CLERK_SECRET_KEY: str | None = None
    CLERK_ISSUER_URL: str | None = None
    CLERK_JWT_KEY: str | None = None
    CLERK_WEBHOOK_SIGNING_SECRET: str | None = None

    # Interruption watchdog timeout (15 minutes)
    INTERRUPTION_TIMEOUT_SECONDS: int = 900
    DEFAULT_APPROVAL_TIMEOUT_SECONDS: int | None = None

    # Model pricing overrides JSON: model_name -> {input, output}_cents_per_million
    MODEL_PRICING_OVERRIDES_JSON: str | None = None

    # Redis telemetry and pubsub
    REDIS_URL: str = "redis://localhost:6379/0"
    ANALYTICS_CACHE_TTL_SECONDS: int = 0

    @property
    def approval_timeout_seconds(self) -> int:
        """Return configured approval watchdog timeout in seconds."""
        return (
            self.DEFAULT_APPROVAL_TIMEOUT_SECONDS or self.INTERRUPTION_TIMEOUT_SECONDS
        )


settings = Settings()
