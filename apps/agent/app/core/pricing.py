"""Versioned integer-cent LLM pricing catalog and cost estimation."""

import json
import math
from dataclasses import dataclass

from app.core.config import settings

PRICING_TABLE_VERSION = "2026-11-26"


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Per-million token rates in integer cents."""

    input_cents_per_million: int
    output_cents_per_million: int


# Built-in rates in integer cents per 1M tokens.
DEFAULT_MODEL_RATES: dict[str, ModelRate] = {
    "claude-sonnet-4": ModelRate(
        input_cents_per_million=300,
        output_cents_per_million=1500,
    ),
    "claude-3-7-sonnet": ModelRate(
        input_cents_per_million=300,
        output_cents_per_million=1500,
    ),
    "claude-3-5-sonnet": ModelRate(
        input_cents_per_million=300,
        output_cents_per_million=1500,
    ),
    "claude-3-5-haiku": ModelRate(
        input_cents_per_million=80,
        output_cents_per_million=400,
    ),
    "claude-3-opus": ModelRate(
        input_cents_per_million=1500,
        output_cents_per_million=7500,
    ),
    "gpt-4o": ModelRate(
        input_cents_per_million=250,
        output_cents_per_million=1000,
    ),
    "gpt-4o-mini": ModelRate(
        input_cents_per_million=15,
        output_cents_per_million=60,
    ),
    "o3-mini": ModelRate(
        input_cents_per_million=110,
        output_cents_per_million=440,
    ),
    "mock-forge-v1": ModelRate(
        input_cents_per_million=300,
        output_cents_per_million=1500,
    ),
    "mock-reviewer-v1": ModelRate(
        input_cents_per_million=300,
        output_cents_per_million=1500,
    ),
}

# Conservative fallback rate for unknown models so budget caps never undercount.
CONSERVATIVE_FALLBACK_RATE = ModelRate(
    input_cents_per_million=1000,
    output_cents_per_million=3000,
)


def _load_overrides() -> dict[str, ModelRate]:
    raw = settings.MODEL_PRICING_OVERRIDES_JSON
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    overrides: dict[str, ModelRate] = {}
    for model_name, value in parsed.items():
        if not isinstance(model_name, str) or not isinstance(value, dict):
            continue
        inp = value.get("input_cents_per_million")
        out = value.get("output_cents_per_million")
        if isinstance(inp, int) and isinstance(out, int) and inp >= 0 and out >= 0:
            overrides[model_name.lower()] = ModelRate(
                input_cents_per_million=inp,
                output_cents_per_million=out,
            )
    return overrides


def get_model_rate(model: str) -> ModelRate:
    """Resolve model pricing rate, applying environment overrides then prefix match."""
    normalized = model.strip().lower()
    overrides = _load_overrides()
    if normalized in overrides:
        return overrides[normalized]

    for prefix, rate in overrides.items():
        if normalized.startswith(prefix):
            return rate

    if normalized in DEFAULT_MODEL_RATES:
        return DEFAULT_MODEL_RATES[normalized]

    for prefix, rate in DEFAULT_MODEL_RATES.items():
        if normalized.startswith(prefix):
            return rate

    return CONSERVATIVE_FALLBACK_RATE


def estimate_cost_cents(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """Compute ceiling integer cent cost (minimum 1 cent for any non-zero call)."""
    safe_prompt = max(0, prompt_tokens)
    safe_completion = max(0, completion_tokens)
    if safe_prompt == 0 and safe_completion == 0:
        return 0

    rate = get_model_rate(model)
    raw_cents = (
        safe_prompt * rate.input_cents_per_million
        + safe_completion * rate.output_cents_per_million
    ) / 1_000_000
    return max(1, math.ceil(raw_cents))
