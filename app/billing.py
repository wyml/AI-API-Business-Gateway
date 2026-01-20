from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailySpend, Wallet, WalletLog
from app.pricing import PricingError, calculate_model_cost


async def ensure_daily_spend_limit(
    session: AsyncSession,
    user_id: int,
    daily_limit: Decimal | float,
) -> None:
    limit = Decimal(str(daily_limit))
    today = date.today()
    result = await session.execute(
        select(DailySpend).where(DailySpend.user_id == user_id, DailySpend.day == today)
    )
    daily_spend = result.scalar_one_or_none()
    if daily_spend and daily_spend.spent >= limit:
        raise ValueError("Daily spend limit exceeded.")


async def charge_wallet(
    session: AsyncSession,
    user_id: int,
    usage: dict[str, Any],
    *,
    model: str,
    min_balance: Decimal | float = Decimal("0"),
    max_cost_per_request: Decimal | float = Decimal("1"),
    daily_spend_limit: Decimal | float = Decimal("100"),
) -> Decimal:
    """Deduct usage cost from wallet and append a wallet log entry.

    Example:
        cost = await charge_wallet(
            session,
            user_id=api_key.user_id,
            model=response_json.get("model", "gpt-4o-mini"),
            usage=response_json["usage"],
            min_balance=Decimal("1.00"),
            max_cost_per_request=Decimal("5.00"),
        )
    """
    minimum_balance = Decimal(str(min_balance))
    try:
        cost = await calculate_model_cost(
            session,
            model,
            usage,
            max_cost_per_request=max_cost_per_request,
        )
    except PricingError as exc:
        raise ValueError(str(exc)) from exc

    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user_id).with_for_update()
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise ValueError("Wallet not found.")

    if wallet.balance < minimum_balance:
        raise ValueError("Wallet balance below minimum threshold.")

    if wallet.balance < cost:
        raise ValueError("Insufficient wallet balance.")

    today = date.today()
    limit = Decimal(str(daily_spend_limit))
    daily_result = await session.execute(
        select(DailySpend)
        .where(DailySpend.user_id == user_id, DailySpend.day == today)
        .with_for_update()
    )
    daily_spend = daily_result.scalar_one_or_none()
    if daily_spend is None:
        daily_spend = DailySpend(user_id=user_id, day=today, spent=Decimal("0"))
        session.add(daily_spend)

    if daily_spend.spent + cost > limit:
        raise ValueError("Daily spend limit exceeded.")

    wallet.balance -= cost
    wallet.total_spent += cost
    daily_spend.spent += cost
    session.add(WalletLog(user_id=user_id, amount=-cost, type="debit"))
    await session.flush()

    return cost
