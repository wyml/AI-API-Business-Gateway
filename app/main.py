from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import forward
from app.auth import authenticate
from app.billing import charge_wallet, ensure_daily_spend_limit
from app.config import get_settings
from app.db import get_async_session, init_db
from app.models import ApiKey
from app.rate_limit import check_rate_limit
from app.payment import router as payment_router

app = FastAPI()
app.include_router(payment_router)


@app.on_event("startup")
async def startup_event() -> None:
    get_settings()
    await init_db()


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    api_key: ApiKey = Depends(authenticate),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    allowed = await check_rate_limit(api_key.key)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

    settings = get_settings()
    try:
        await ensure_daily_spend_limit(session, api_key.user_id, settings.daily_spend_limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc

    result = await forward.forward_chat_completion(payload, headers=dict(request.headers))
    if result.usage:
        try:
            await charge_wallet(
                session,
                user_id=api_key.user_id,
                model=payload.get("model", ""),
                usage=result.usage,
                min_balance=settings.min_wallet_balance,
                max_cost_per_request=settings.max_cost_per_request,
                daily_spend_limit=settings.daily_spend_limit,
            )
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    return result.response
