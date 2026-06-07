from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

from playwright.async_api import BrowserContext, Page, Request

if TYPE_CHECKING:
    from webgent.network_capture import CapturedRequest

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def request_likely_has_body(request: Request) -> bool:
    if request.method not in _BODY_METHODS:
        return False
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > 0:
        return True
    content_type = request.headers.get("content-type", "")
    return bool(content_type)


async def resolve_request_body(
    entry: CapturedRequest,
    cdp: CdpPostDataCapture | None,
    *,
    wait_timeout_s: float = 2.0,
) -> bytes:
    """Legacy helper; prefer webgent.request_body.resolve_request_body."""
    from webgent.request_body import resolve_request_body as resolve

    body, _source = await resolve(entry, None, cdp, wait_timeout_s=wait_timeout_s)
    return body


class CdpPostDataCapture:
    """Fetch POST bodies via CDP when Playwright omits post_data_buffer."""

    def __init__(self) -> None:
        self._pending: deque[str] = deque()
        self._bodies: dict[str, bytes] = {}
        self._installed = False

    async def install(self, context: BrowserContext, page: Page) -> None:
        if self._installed:
            return
        cdp = await context.new_cdp_session(page)
        await cdp.send("Network.enable")

        async def on_request_will_be_sent(params: dict[str, Any]) -> None:
            request = params.get("request", {})
            if not request.get("hasPostData"):
                return
            try:
                result = await cdp.send(
                    "Network.getRequestPostData",
                    {"requestId": params["requestId"]},
                )
                post_data = result.get("postData")
                body = b"" if post_data is None else post_data.encode("latin-1")
            except Exception:
                body = b""
            self._deliver(body)

        cdp.on(
            "Network.requestWillBeSent",
            lambda params: asyncio.create_task(on_request_will_be_sent(params)),
        )
        self._installed = True

    def register_pending(self, entry_id: str) -> None:
        if entry_id not in self._bodies and entry_id not in self._pending:
            self._pending.append(entry_id)

    def _deliver(self, body: bytes) -> None:
        if not self._pending:
            return
        entry_id = self._pending.popleft()
        if body:
            self._bodies[entry_id] = body

    async def wait_for_body(
        self,
        entry_id: str,
        *,
        timeout: float = 2.0,
    ) -> bytes | None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            body = self._bodies.get(entry_id)
            if body is not None:
                return body
            await asyncio.sleep(0.05)
        return self._bodies.get(entry_id)
