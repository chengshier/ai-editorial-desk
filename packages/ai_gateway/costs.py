from __future__ import annotations

from decimal import Decimal

from packages.ai_gateway.domain import AIModelTarget, AIUsage

MILLION = Decimal("1000000")


def pricing_snapshot(target: AIModelTarget) -> dict[str, object]:
    return {
        "pricing_version": target.pricing_version,
        "input_price_per_million": _decimal_text(target.input_price_per_million),
        "output_price_per_million": _decimal_text(target.output_price_per_million),
        "embedding_price_per_million": _decimal_text(target.embedding_price_per_million),
    }


def estimate_cost(
    *,
    target: AIModelTarget,
    capability: str,
    usage: AIUsage,
) -> Decimal | None:
    if capability == "embedding":
        tokens = usage.total_tokens if usage.total_tokens is not None else usage.input_tokens
        if tokens is None or target.embedding_price_per_million is None:
            return None
        return _cost(tokens, target.embedding_price_per_million)
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    if target.input_price_per_million is None or target.output_price_per_million is None:
        return None
    return _cost(usage.input_tokens, target.input_price_per_million) + _cost(
        usage.output_tokens,
        target.output_price_per_million,
    )


def reserve_estimate(
    *,
    target: AIModelTarget,
    capability: str,
    estimated_input_tokens: int,
    reserved_output_tokens: int,
) -> tuple[Decimal | None, int]:
    estimated_input_tokens = max(1, estimated_input_tokens)
    if capability == "embedding":
        if target.embedding_price_per_million is None:
            return None, estimated_input_tokens
        return _cost(estimated_input_tokens, target.embedding_price_per_million), estimated_input_tokens
    total_tokens = estimated_input_tokens + max(0, reserved_output_tokens)
    if target.input_price_per_million is None or target.output_price_per_million is None:
        return None, total_tokens
    return (
        _cost(estimated_input_tokens, target.input_price_per_million)
        + _cost(max(0, reserved_output_tokens), target.output_price_per_million),
        total_tokens,
    )


def approximate_input_tokens(text: str) -> int:
    """Conservative routing estimate only; provider usage remains the accounting source of truth."""

    return max(1, (len(text.encode("utf-8")) + 2) // 3)


def _cost(tokens: int, price_per_million: Decimal) -> Decimal:
    return (Decimal(tokens) * price_per_million / MILLION).quantize(Decimal("0.00000001"))


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
