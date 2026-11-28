"""Credential redaction and XML delimiter escaping utilities for prompt safety."""

import re

_PEM_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.MULTILINE,
)
_URL_USERINFO_RE = re.compile(r"(https?://)([^:/\s@]+):([^@/\s]+)@")
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bpk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
_GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api_key|secret_key|access_token|auth_token|password|passwd|secret)"
    r"\s*([:=])\s*(['\"]?)([^\s'\",;]{6,})\3"
)


def redact_credentials(text: str) -> str:
    """Scrub secrets, API keys, tokens, and URL credentials with [REDACTED]."""
    if not text:
        return text

    result = _PEM_KEY_RE.sub("[REDACTED]", text)
    result = _URL_USERINFO_RE.sub(r"\1[REDACTED]@", result)
    for pattern in _TOKEN_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    result = _BEARER_RE.sub("Bearer [REDACTED]", result)
    result = _GENERIC_SECRET_RE.sub(r"\1\2[REDACTED]", result)
    return result


def escape_xml_delimiters(text: str) -> str:
    """Escape XML angle brackets to prevent prompt delimiter breakout."""
    if not text:
        return text
    return text.replace("<", "&lt;").replace(">", "&gt;")


def sanitize_prompt_text(text: str) -> str:
    """Redact credentials and escape XML angle brackets for prompt injection."""
    return escape_xml_delimiters(redact_credentials(text))
