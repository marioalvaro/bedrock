"""What a classifier's tokens cost (docs/erd/face-tree.md "Prices"). Prices change: every cost
is an estimate."""

from decimal import Decimal

from bedrock.classify.types import Usage

# USD per million tokens (input, output), recorded 2026-11-16
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    # Anthropic price list (prompts up to 100K tokens)
    "claude:claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    # Anthropic price list
    "claude:claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    # TypeSafe launch post, 2026-09-15
    "jev:jev-latest": (Decimal("0.042"), Decimal("0")),
    # OpenRouter model list (openrouter.ai/api/v1/models), recorded 2026-11-17
    "openrouter:openai/gpt-6-luna": (Decimal("0.10"), Decimal("0.50")),
    # a free variant: no price, limited to 50 requests a day (OpenRouter limits page)
    "openrouter:nvidia/nemotron-3.5-super-vl:free": (Decimal("0"), Decimal("0")),
}
_MILLION = Decimal(1_000_000)


def cost(name: str, usage: Usage) -> Decimal:
    """USD for `usage` at the classifier's listed price; 0 for a name with no listed price (the
    fake)."""
    input_price, output_price = PRICES.get(name, (Decimal(0), Decimal(0)))
    return (input_price * usage.input_tokens + output_price * usage.output_tokens) / _MILLION
