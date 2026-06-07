from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from webgent.cdp_post_data import CdpPostDataCapture

if TYPE_CHECKING:
    from webgent.network_capture import CapturedRequest
    from webgent.proxy_capture import ProxyCaptureStore

BodySource = Literal["proxy", "cdp", "playwright", "unavailable"]


async def resolve_request_body(
    entry: CapturedRequest,
    proxy: ProxyCaptureStore | None,
    cdp: CdpPostDataCapture | None,
    *,
    wait_timeout_s: float = 2.0,
) -> tuple[bytes, BodySource]:
    if proxy is not None:
        body = proxy.get_request_body(entry.id)
        if body is None:
            body = proxy.claim_for_entry(entry.id, entry.method, entry.url)
        if body is None:
            body = await proxy.wait_for_request_body(entry.id, timeout=wait_timeout_s)
        if body is not None:
            return body, "proxy"

    try:
        body = entry._request.post_data_buffer
        if body:
            return body, "playwright"
    except Exception:
        pass

    if cdp is not None:
        body = await cdp.wait_for_body(entry.id, timeout=wait_timeout_s)
        if body:
            return body, "cdp"

    return b"", "unavailable"


async def resolve_response_body(
    entry: CapturedRequest,
    proxy: ProxyCaptureStore | None,
    *,
    wait_timeout_s: float = 2.0,
) -> tuple[bytes, BodySource]:
    if proxy is not None:
        body = proxy.get_response_body(entry.id)
        if body is None:
            body = proxy.claim_response_for_entry(entry.id, entry.method, entry.url)
        if body is None:
            body = await proxy.wait_for_response_body(entry.id, timeout=wait_timeout_s)
        if body is not None:
            return body, "proxy"

    if entry._response is None:
        return b"", "unavailable"
    try:
        body = await entry._response.body()
        if body:
            return body, "playwright"
    except Exception:
        pass
    return b"", "unavailable"
