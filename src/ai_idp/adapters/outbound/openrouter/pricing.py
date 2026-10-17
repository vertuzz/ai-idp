from __future__ import annotations

from typing import Any

# Price per 1M tokens (input_usd_per_1m, output_usd_per_1m)
MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "perplexity/pplx-decider-v1.2": (0.02, 0.0),
    "perplexity/pplx-decider-flash-v1.2": (0.01, 0.0),
    "anthropic/claude-haiku-5.5": (0.10, 0.50),
    "google/gemini-4-argon": (2.00, 10.00),
    "google/gemini-3.8-flash": (0.15, 0.60),
    "qwen/qwen3.8-flash": (0.065, 0.26),
}


def estimate_cost_usd(
    model_id: str,
    tokens_in: int,
    tokens_out: int,
    provider_usage: dict[str, Any] | None = None,
) -> float:
    """Return provider-reported cost if present, otherwise estimate from token schedule."""
    if provider_usage:
        reported = provider_usage.get("cost")
        if isinstance(reported, (int, float)) and reported >= 0:
            return float(reported)
        cost_details = provider_usage.get("cost_details")
        if isinstance(cost_details, dict):
            upstream = cost_details.get("upstream_inference_cost")
            if isinstance(upstream, (int, float)) and upstream >= 0:
                return float(upstream)

    rates = MODEL_PRICING_PER_1M.get(model_id)
    if rates is None:
        for prefix, candidate_rates in MODEL_PRICING_PER_1M.items():
            if model_id.startswith(prefix):
                rates = candidate_rates
                break
    if rates is None:
        rates = (0.50, 2.00)

    in_rate, out_rate = rates
    return round((tokens_in * in_rate + tokens_out * out_rate) / 1_000_000.0, 8)
