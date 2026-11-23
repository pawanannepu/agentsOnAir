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

    # Redis telemetry and pubsub
    REDIS_URL: str = "redis://localhost:6379/0"


settings = Settings()
