from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.ai_gateway.errors import AIErrorCode, AIGatewayError

GENERATION_POLICY_KEY = "generation_policy"
MAX_OUTPUT_TOKENS_KEY = "max_output_tokens"


@dataclass(frozen=True, slots=True)
class AIGenerationPolicy:
    max_output_tokens: int | None = None


def generation_policy_from_config(config: dict[str, Any]) -> AIGenerationPolicy:
    """Read the typed generation policy stored inside a versioned task-route config."""
    raw_policy = config.get(GENERATION_POLICY_KEY)
    if raw_policy is None:
        return AIGenerationPolicy()
    if not isinstance(raw_policy, dict):
        raise AIGatewayError(
            AIErrorCode.INVALID_REQUEST,
            "AI Route generation_policy 必须是对象",
        )

    raw_max_output_tokens = raw_policy.get(MAX_OUTPUT_TOKENS_KEY)
    if raw_max_output_tokens is None:
        return AIGenerationPolicy()
    if isinstance(raw_max_output_tokens, bool) or not isinstance(raw_max_output_tokens, int):
        raise AIGatewayError(
            AIErrorCode.INVALID_REQUEST,
            "AI Route generation_policy.max_output_tokens 必须是正整数",
        )
    if raw_max_output_tokens <= 0:
        raise AIGatewayError(
            AIErrorCode.INVALID_REQUEST,
            "AI Route generation_policy.max_output_tokens 必须是正整数",
        )
    return AIGenerationPolicy(max_output_tokens=raw_max_output_tokens)


def resolve_max_output_tokens(
    *,
    route_config: dict[str, Any],
    fallback: int | None,
) -> int | None:
    """Route-level policy wins; existing caller value remains the code fallback."""
    configured = generation_policy_from_config(route_config).max_output_tokens
    return configured if configured is not None else fallback


def merge_generation_policy(
    *,
    config: dict[str, Any],
    max_output_tokens: int | None,
) -> dict[str, Any]:
    """Preserve unrelated route config while updating the typed generation policy."""
    merged = dict(config)
    existing = merged.get(GENERATION_POLICY_KEY)
    policy = dict(existing) if isinstance(existing, dict) else {}
    if max_output_tokens is None:
        policy.pop(MAX_OUTPUT_TOKENS_KEY, None)
    else:
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int):
            raise ValueError("max_output_tokens must be a positive integer")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        policy[MAX_OUTPUT_TOKENS_KEY] = max_output_tokens
    if policy:
        merged[GENERATION_POLICY_KEY] = policy
    else:
        merged.pop(GENERATION_POLICY_KEY, None)
    return merged
