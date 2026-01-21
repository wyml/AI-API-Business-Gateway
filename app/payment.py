from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_async_session
from app.models import Payment, Wallet, WalletLog

router = APIRouter(prefix="/payment", tags=["payment"])


class CreatePaymentRequest(BaseModel):
    user_id: int
    amount: Decimal = Field(..., gt=Decimal("0"))


class CreatePaymentResponse(BaseModel):
    payment_id: int
    provider: str
    provider_payment_id: str
    client_secret: str


@dataclass(frozen=True)
class PaymentResult:
    wallet_balance: Decimal
    total_recharged: Decimal


def _configure_stripe() -> None:
    settings = get_settings()
    stripe.api_key = settings.stripe_api_key


@router.post("/create", response_model=CreatePaymentResponse)
async def create_payment(
    payload: CreatePaymentRequest,
    session: AsyncSession = Depends(get_async_session),
) -> CreatePaymentResponse:
    settings = get_settings()
    _configure_stripe()
    amount_in_cents = int((payload.amount * 100).to_integral_value())

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_in_cents,
            currency=settings.stripe_currency,
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    payment = Payment(
        user_id=payload.user_id,
        provider="stripe",
        provider_payment_id=intent.id,
        amount=payload.amount,
        currency=settings.stripe_currency,
        status="pending",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    return CreatePaymentResponse(
        payment_id=payment.id,
        provider="stripe",
        provider_payment_id=intent.id,
        client_secret=intent.client_secret,
    )


async def _apply_payment(
    session: AsyncSession,
    payment: Payment,
    amount: Decimal,
) -> PaymentResult:
    wallet_result = await session.execute(
        select(Wallet).where(Wallet.user_id == payment.user_id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")

    wallet.balance += amount
    wallet.total_recharged += amount
    payment.status = "succeeded"
    session.add(WalletLog(user_id=payment.user_id, amount=amount, type="recharge"))
    await session.flush()

    return PaymentResult(wallet_balance=wallet.balance, total_recharged=wallet.total_recharged)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if not sig_header:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from exc

    if event["type"] != "payment_intent.succeeded":
        return {"status": "ignored"}

    intent = event["data"]["object"]
    intent_id = intent.get("id")
    amount_received = intent.get("amount_received") or intent.get("amount")
    if not intent_id or amount_received is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    amount = (Decimal(amount_received) / Decimal("100")).quantize(Decimal("0.01"))

    result = await session.execute(
        select(Payment)
        .where(Payment.provider == "stripe", Payment.provider_payment_id == intent_id)
        .with_for_update()
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    if payment.status == "succeeded":
        return {"status": "already_processed"}

    await _apply_payment(session, payment, amount)
    await session.commit()

    return {"status": "succeeded"}
