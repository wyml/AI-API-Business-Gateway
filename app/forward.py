from typing import Any, Mapping

import httpx

from app.config import get_settings


async def forward_chat_completion(payload: dict[str, Any], headers: Mapping[str, str] | None = None) -> httpx.Response:
    settings = get_settings()
    base_url = settings.downstream_base_url.rstrip("/")
    url = f"{base_url}/v1/chat/completions"

    outbound_headers = {"Authorization": f"Bearer {settings.downstream_api_key}"}
    if headers:
        content_type = headers.get("content-type")
        if content_type:
            outbound_headers["Content-Type"] = content_type

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=outbound_headers)

    return response
