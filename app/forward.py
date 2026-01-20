from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping

from fastapi.responses import Response, StreamingResponse

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class ForwardResult:
    response: Response
    usage: dict[str, Any] | None


def _build_outbound_headers(headers: Mapping[str, str] | None, api_key: str) -> dict[str, str]:
    outbound_headers = {"Authorization": f"Bearer {api_key}"}
    if headers:
        content_type = headers.get("content-type")
        if content_type:
            outbound_headers["Content-Type"] = content_type
    return outbound_headers


async def _stream_response(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_bytes():
        yield chunk


async def forward_chat_completion(
    payload: dict[str, Any],
    headers: Mapping[str, str] | None = None,
) -> ForwardResult:
    settings = get_settings()
    base_url = settings.downstream_base_url.rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    outbound_headers = _build_outbound_headers(headers, settings.downstream_api_key)

    if payload.get("stream") is True:
        client = httpx.AsyncClient(timeout=None)
        response = await client.stream("POST", url, json=payload, headers=outbound_headers)

        streaming_response = StreamingResponse(
            _stream_response(response),
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )

        async def _cleanup() -> None:
            await response.aclose()
            await client.aclose()

        streaming_response.call_on_close(_cleanup)
        return ForwardResult(response=streaming_response, usage=None)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=outbound_headers)
    usage: dict[str, Any] | None = None
    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        if isinstance(body, dict):
            usage = body.get("usage")

    return ForwardResult(
        response=Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        ),
        usage=usage,
    )
