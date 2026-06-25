"""Model pricing table and cost calculator.

Computes USD cost per model call using known provider pricing.
All prices per 1M tokens. Falls back to estimates for unknown models.
"""

from typing import Dict, Tuple

# Pricing per 1M tokens (input, output)
# Sources: provider official pricing pages as of 2025
PRICING: Dict[str, Dict[str, Tuple[float, float]]] = {
    "deepseek": {
        "deepseek-chat": (0.27, 1.10),
        "deepseek-reasoner": (0.55, 2.19),
        "deepseek-v4-pro": (0.50, 1.50),
        "deepseek-v4-flash": (0.25, 0.80),
    },
    "openai": {
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.00, 30.00),
        "gpt-4": (30.00, 60.00),
        "gpt-3.5-turbo": (0.50, 1.50),
        "o1": (15.00, 60.00),
        "o1-mini": (1.10, 4.40),
        "o3-mini": (1.10, 4.40),
    },
    "anthropic": {
        "claude-3-5-sonnet-latest": (3.00, 15.00),
        "claude-3-5-haiku-latest": (1.00, 5.00),
        "claude-3-opus-latest": (15.00, 75.00),
        "claude-sonnet-4-20250514": (3.00, 15.00),
    },
    "google": {
        "gemini-2.0-flash": (0.10, 0.40),
        "gemini-2.0-pro": (2.00, 8.00),
        "gemini-1.5-pro": (1.25, 5.00),
        "gemini-1.5-flash": (0.075, 0.30),
    },
    "openclaw": {
        "default": (0.35, 1.20),
    },
}

# Fallback pricing for unknown models (conservative estimate)
FALLBACK_INPUT_PRICE = 1.00
FALLBACK_OUTPUT_PRICE = 4.00

# USD → CNY conversion rate (approximate, update as needed)
USD_TO_CNY = 7.25


def get_model_price(model: str, provider: str = "") -> Tuple[float, float]:
    """Look up (input_price_per_M, output_price_per_M) for a model.

    Tries exact match first, then falls back to wildcard per-provider,
    then to global fallback.
    """
    provider_pricing = PRICING.get(provider.lower(), {})

    # Exact match
    model_lower = model.lower()
    if model_lower in provider_pricing:
        return provider_pricing[model_lower]

    # Provider-level fallback
    if "default" in provider_pricing:
        return provider_pricing["default"]

    # Try matching by prefix (e.g. "claude-3-haiku" matches "claude")
    for key, price in PRICING.items():
        if model_lower.startswith(key):
            for m, p in price.items():
                if model_lower.startswith(m.split("-")[0]) or m == "default":
                    return p

    return (FALLBACK_INPUT_PRICE, FALLBACK_OUTPUT_PRICE)


def compute_cost(model: str, provider: str, input_tokens: int, output_tokens: int,
                 currency: str = "CNY") -> float:
    """Compute cost for a model call. Defaults to CNY."""
    in_price, out_price = get_model_price(model, provider)
    usd = (input_tokens / 1_000_000 * in_price) + (output_tokens / 1_000_000 * out_price)
    if currency.upper() == "CNY":
        return round(usd * USD_TO_CNY, 4)
    return round(usd, 6)


def compute_costs(token_usage_list: list) -> dict:
    """Compute aggregate costs from a list of token usage records.

    Each record: {model, provider, input_tokens, output_tokens, ...}
    Returns: {total_cost, by_model: [{model, provider, calls, input_tokens, output_tokens, cost}], total_tokens}
    """
    from collections import defaultdict

    model_agg = defaultdict(lambda: {
        "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0
    })

    total_cost = 0.0
    total_input = 0
    total_output = 0

    for usage in token_usage_list:
        model = usage.get("model", "unknown")
        provider = usage.get("provider", "")
        inp = usage.get("input_tokens", 0) or usage.get("input", 0)
        out = usage.get("output_tokens", 0) or usage.get("output", 0)
        cost = compute_cost(model, provider, inp, out)

        agg = model_agg[model]
        agg["model"] = model
        agg["provider"] = provider
        agg["calls"] += 1
        agg["input_tokens"] += inp
        agg["output_tokens"] += out
        agg["cost"] += cost

        total_cost += cost
        total_input += inp
        total_output += out

    return {
        "total_cost": round(total_cost, 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "by_model": sorted(model_agg.values(), key=lambda x: x["cost"], reverse=True),
    }
