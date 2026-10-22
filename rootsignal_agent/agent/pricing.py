"""Cost estimates for the CLI footer and the --all spend guard."""

# USD per million tokens, as (input, output). These are list prices for prompts under
# 100K tokens, so they are estimates, not a bill. output_tokens includes any thinking
# tokens, because the API counts them as output.
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost in USD, or None when the model has no entry in PRICING."""
    prices = PRICING.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
