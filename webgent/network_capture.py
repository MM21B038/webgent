from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from playwright.async_api import Request, Response

from webgent.snapshot import DEFAULT_MAX_URL_LEN, truncate_url

if TYPE_CHECKING:
    from webgent.browser import BrowserSession

DEFAULT_MAX_RESPONSE_BYTES = 32768
MAX_CAPTURE_ENTRIES = 500
SETTLE_TIMEOUT_MS = 2000
RESPONSE_WAIT_TIMEOUT_S = 2.0


@dataclass
class CapturedRequest:
    id: str
    method: str
    url: str
    resource_type: str
    _request: Request
    status: int | None = None
    ok: bool | None = None
    _response: Response | None = field(default=None, repr=False)

    def summary(self, max_url_len: int = DEFAULT_MAX_URL_LEN) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "resource_type": self.resource_type,
            "url": truncate_url(self.url, max_url_len),
            "status": self.status,
        }


class NetworkCaptureStore:
    def __init__(self, max_entries: int = MAX_CAPTURE_ENTRIES) -> None:
        self._entries: dict[str, CapturedRequest] = {}
        self._by_request: dict[int, str] = {}
        self._max_entries = max_entries

    def add_from_request(self, request: Request) -> CapturedRequest | None:
        request_key = id(request)
        existing_id = self._by_request.get(request_key)
        if existing_id is not None:
            return self._entries[existing_id]
        if len(self._entries) >= self._max_entries:
            return None
        entry_id = str(uuid.uuid4())
        entry = CapturedRequest(
            id=entry_id,
            method=request.method,
            url=request.url,
            resource_type=request.resource_type,
            _request=request,
        )
        self._entries[entry_id] = entry
        self._by_request[request_key] = entry_id
        return entry

    def attach_response(self, response: Response) -> None:
        request_key = id(response.request)
        entry_id = self._by_request.get(request_key)
        if entry_id is None:
            entry = self.add_from_request(response.request)
            if entry is None:
                return
            entry_id = entry.id
        entry = self._entries[entry_id]
        entry._response = response
        entry.status = response.status
        entry.ok = response.ok

    def get(self, request_id: str) -> CapturedRequest:
        entry = self._entries.get(request_id)
        if entry is None:
            raise ValueError(f"Unknown request_id: {request_id}")
        return entry

    def try_get(self, request_id: str) -> CapturedRequest | None:
        return self._entries.get(request_id)

    def summaries(
        self,
        entry_ids: list[str],
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> list[dict[str, Any]]:
        return [
            self._entries[entry_id].summary(max_url_len)
            for entry_id in entry_ids
            if entry_id in self._entries
        ]

    def clear(self) -> None:
        self._entries.clear()
        self._by_request.clear()


class ActionNetworkCapture:
    def __init__(
        self,
        store: NetworkCaptureStore,
        session: BrowserSession,
        *,
        cdp_post_data: Any | None = None,
        proxy_capture: Any | None = None,
    ) -> None:
        self._store = store
        self._session = session
        self._cdp_post_data = cdp_post_data
        self._proxy_capture = proxy_capture
        self._active = False
        self.captured_ids: list[str] = []

    def _belongs_to_session(self, page: Any) -> bool:
        return any(tracked is page for tracked in self._session.pages.values())

    def _on_request(self, request: Request) -> None:
        if not self._active:
            return
        page = request.frame.page
        if not self._belongs_to_session(page):
            return
        entry = self._store.add_from_request(request)
        if entry is not None and entry.id not in self.captured_ids:
            self.captured_ids.append(entry.id)
            if self._proxy_capture is not None:
                self._proxy_capture.register_capture(
                    entry.id,
                    request.method,
                    request.url,
                )
            if self._cdp_post_data is not None:
                from webgent.cdp_post_data import request_likely_has_body

                try:
                    has_buffer = bool(request.post_data_buffer)
                except Exception:
                    has_buffer = False
                if not has_buffer and request_likely_has_body(request):
                    self._cdp_post_data.register_pending(entry.id)

    def _on_response(self, response: Response) -> None:
        if not self._active:
            return
        page = response.frame.page
        if not self._belongs_to_session(page):
            return
        self._store.attach_response(response)

    async def __aenter__(self) -> ActionNetworkCapture:
        self._active = True
        self.captured_ids = []
        self._session.context.on("request", self._on_request)
        self._session.context.on("response", self._on_response)
        return self

    async def _finalize_pending_responses(self) -> None:
        for entry_id in self.captured_ids:
            entry = self._store.get(entry_id)
            if entry._response is not None:
                continue
            try:
                response = await asyncio.wait_for(
                    entry._request.response(),
                    timeout=RESPONSE_WAIT_TIMEOUT_S,
                )
            except Exception:
                continue
            if response is not None:
                self._store.attach_response(response)

    async def __aexit__(self, *args: Any) -> None:
        if self._session.pages:
            try:
                page = self._session.pages[self._session.active_page_id]
                await page.wait_for_load_state(
                    "networkidle",
                    timeout=SETTLE_TIMEOUT_MS,
                )
            except Exception:
                pass
        await self._finalize_pending_responses()
        self._active = False
        self._session.context.remove_listener("request", self._on_request)
        self._session.context.remove_listener("response", self._on_response)
