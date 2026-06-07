from __future__ import annotations

import json
from typing import Any, Literal

from playwright.async_api import APIResponse, BrowserContext

from webgent.network_capture import DEFAULT_MAX_RESPONSE_BYTES
from webgent.request_registry import decode_body_bytes
from webgent.snapshot import capture_html_snapshot, is_html_content_type

_SUPPORTED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
_STRIP_HEADERS = frozenset({"content-length", "host"})
_PSEUDO_HEADER_PREFIX = ":"


def _normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _STRIP_HEADERS
        and not key.startswith(_PSEUDO_HEADER_PREFIX)
    }


async def http_request(
    context: BrowserContext,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    data: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    content_type: str | None = None,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    format: Literal["tree", "raw"] = "tree",
) -> dict[str, Any]:
    verb = method.strip().upper()
    if verb not in _SUPPORTED_METHODS:
        raise ValueError(f"Unsupported HTTP method: {method!r}")

    request_kwargs: dict[str, Any] = {
        "method": verb,
        "headers": _normalize_headers(headers),
    }
    if json_body is not None:
        request_kwargs["data"] = json.dumps(json_body)
        request_kwargs["headers"] = {
            **request_kwargs["headers"],
            "content-type": content_type or "application/json",
        }
    elif data is not None:
        request_kwargs["form"] = data
        if content_type:
            request_kwargs["headers"] = {
                **request_kwargs["headers"],
                "content-type": content_type,
            }
    elif body is not None:
        request_kwargs["data"] = body
        if content_type:
            request_kwargs["headers"] = {
                **request_kwargs["headers"],
                "content-type": content_type,
            }

    response: APIResponse = await context.request.fetch(url, **request_kwargs)
    body_bytes = await response.body()
    text_body, full_size, truncated = decode_body_bytes(
        body_bytes,
        max_bytes=max_bytes,
    )
    response_content_type = response.headers.get("content-type", "")
    result: dict[str, Any] = {
        "status": response.status,
        "ok": response.ok,
        "url": response.url,
        "headers": dict(response.headers),
        "content_type": response_content_type,
        "body": text_body,
        "size": full_size,
    }
    if truncated:
        result["truncated"] = True
    if is_html_content_type(response_content_type) and format == "tree":
        try:
            result["body"] = await capture_html_snapshot(context, text_body)
            result["format"] = "tree"
        except Exception:
            result["format"] = "raw"
    else:
        result["format"] = "raw"
    return result
