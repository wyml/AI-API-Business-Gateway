from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelPricing


class PricingError(ValueError):
    """Raised when pricing configuration is missing or invalid."""


def _get_token_count(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    if isinstance(value, int):
        return value
    return int(value or 0)


async def calculate_model_cost(
    session: AsyncSession,
    model: str,
    usage: dict[str, Any],
    *,
    max_cost_per_request: Decimal | float,
) -> Decimal:
    if not model:
        raise PricingError("Model name is required.")

    result = await session.execute(
        select(ModelPricing).where(ModelPricing.model == model)
    )
    pricing = result.scalar_one_or_none()
    if not pricing or not pricing.enabled:
        raise PricingError("Model pricing disabled or not found.")

    prompt_tokens = _get_token_count(usage, "prompt_tokens")
    completion_tokens = _get_token_count(usage, "completion_tokens")

    input_cost = (Decimal(prompt_tokens) / Decimal(1000)) * pricing.input_price_per_1k
    output_cost = (Decimal(completion_tokens) / Decimal(1000)) * pricing.output_price_per_1k
    total_cost = input_cost + output_cost

    max_cost = Decimal(str(max_cost_per_request))
    if total_cost > max_cost:
        raise PricingError("Cost exceeds maximum per-request limit.")

    return total_cost
