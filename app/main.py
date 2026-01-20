from fastapi import Depends, FastAPI, HTTPException, Request, Response

from app import forward
from app.auth import verify_api_key
from app.config import get_settings
from app.db import init_db

app = FastAPI()


@app.on_event("startup")
async def startup_event() -> None:
    get_settings()
    await init_db()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, _: None = Depends(verify_api_key)) -> Response:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    response = await forward.forward_chat_completion(payload, headers=dict(request.headers))
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
    )
