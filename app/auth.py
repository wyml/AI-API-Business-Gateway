from fastapi import HTTPException, Request, status

from app.config import get_settings


async def verify_api_key(request: Request) -> None:
    settings = get_settings()
    header_key = request.headers.get("x-api-key")
    auth_header = request.headers.get("authorization")
    token = None

    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            token = auth_header

    token = token or header_key

    if not token or token != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
