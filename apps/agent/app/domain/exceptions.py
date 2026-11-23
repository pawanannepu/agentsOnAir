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
