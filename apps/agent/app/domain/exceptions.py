"""Domain layer exceptions.

Pure Python exception classes independent of any external frameworks.
"""


class DomainError(Exception):
    """Base exception for all domain logic failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """Raised when an entity is not found within the requested tenant scope."""


class ConflictError(DomainError):
    """Raised when a unique constraint or business conflict prevents entity creation."""


class ValidationError(DomainError):
    """Raised when business invariants or validation rules are violated."""


class ConcurrencyError(DomainError):
    """Raised when an optimistic concurrency check detects a version mismatch."""


class DecryptionError(DomainError):
    """Raised when secret decryption or authentication tag verification fails."""


class InvalidStateTransitionError(DomainError):
    """Raised when an entity cannot transition to the target state."""


class WebhookSignatureError(DomainError):
    """Raised when GitHub webhook signature verification fails."""


class BaselineTestFailedError(DomainError):
    """Raised when base branch baseline tests fail before agent modifications."""


class ReviewCycleLimitExhaustedError(DomainError):
    """Raised when the outer review loop exhausts its maximum cycle cap."""


class AuthenticationError(DomainError):
    """Raised when caller authentication credentials are missing or invalid."""


class ConfigurationError(DomainError):
    """Raised when a required server secret or provider key is not configured."""


class ExternalServiceError(DomainError):
    """Raised when an upstream external service call fails or times out."""


class ProtectedBranchError(DomainError):
    """Raised when a push or PR targets a protected branch."""


class ApprovalRequiredError(DomainError):
    """Raised when a risky sandbox or host action requires org:admin approval."""

    def __init__(self, classification: object) -> None:
        summary = getattr(classification, "action_summary", "Approval required")
        super().__init__(summary)
        self.classification = classification


class GuardrailBlockedError(DomainError):
    """Raised when a guardrail policy blocks an action outright."""

    def __init__(self, message: str, reason: str = "guardrail_blocked") -> None:
        super().__init__(message)
        self.reason = reason


class BudgetExceededError(DomainError):
    """Raised when task or monthly organization spending cap is reached."""


class TaskTimeoutError(DomainError):
    """Raised when active execution time exceeds configured timeout_minutes."""
