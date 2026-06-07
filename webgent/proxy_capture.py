from __future__ import annotations

import asyncio
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from webgent.config import MITMPROXY_DIR, ProxySettings

MATCH_WINDOW_S = 5.0
MAX_FLOW_ENTRIES = 2000


def _pick_listen_port(host: str, preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return sock.getsockname()[1]
    raise RuntimeError(f"Could not bind proxy on {host}")


@dataclass
class ProxyFlowRecord:
    flow_id: str
    method: str
    url: str
    timestamp: float
    request_headers: dict[str, str]
    request_body: bytes
    request_truncated: bool = False
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: bytes = b""
    response_truncated: bool = False
    consumed: bool = False
    entry_id: str | None = None


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{path}?{parsed.query}"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _headers_dict(headers: http.Headers) -> dict[str, str]:
    return {str(key): str(value) for key, value in headers.items(multi=True)}


def _clip_body(body: bytes, max_bytes: int) -> tuple[bytes, bool]:
    if len(body) <= max_bytes:
        return body, False
    return body[:max_bytes], True


@dataclass
class CaptureHint:
    entry_id: str
    method: str
    url: str
    observed_at: float
    content_length: int | None


class ProxyCaptureStore:
    def __init__(self, *, max_body_bytes: int = 1_048_576) -> None:
        self._max_body_bytes = max_body_bytes
        self._flows: deque[ProxyFlowRecord] = deque(maxlen=MAX_FLOW_ENTRIES)
        self._hints: deque[CaptureHint] = deque()
        self._request_bodies: dict[str, bytes] = {}
        self._response_bodies: dict[str, bytes] = {}

    def record_request(self, flow: http.HTTPFlow) -> None:
        body, truncated = _clip_body(
            flow.request.raw_content or b"",
            self._max_body_bytes,
        )
        record = ProxyFlowRecord(
            flow_id=str(uuid.uuid4()),
            method=flow.request.method,
            url=_normalize_url(flow.request.pretty_url),
            timestamp=time.monotonic(),
            request_headers=_headers_dict(flow.request.headers),
            request_body=body,
            request_truncated=truncated,
        )
        self._flows.append(record)
        self._try_pair(record)

    def record_response(self, flow: http.HTTPFlow) -> None:
        url = _normalize_url(flow.request.pretty_url)
        record = self._find_open_flow(flow.request.method, url)
        if record is None:
            return
        body, truncated = _clip_body(
            flow.response.content or b"",
            self._max_body_bytes,
        )
        record.response_status = flow.response.status_code
        record.response_headers = _headers_dict(flow.response.headers)
        record.response_body = body
        record.response_truncated = truncated
        if record.entry_id is not None:
            self._response_bodies[record.entry_id] = body

    def register_capture(
        self,
        entry_id: str,
        method: str,
        url: str,
        *,
        content_length: int | None = None,
    ) -> None:
        now = time.monotonic()
        while self._hints and now - self._hints[0].observed_at > MATCH_WINDOW_S:
            self._hints.popleft()
        hint = CaptureHint(
            entry_id=entry_id,
            method=method,
            url=_normalize_url(url),
            observed_at=now,
            content_length=content_length,
        )
        self._hints.append(hint)
        self._try_pair_from_hint(hint)

    def claim_for_entry(self, entry_id: str, method: str, url: str) -> bytes | None:
        if entry_id in self._request_bodies:
            return self._request_bodies[entry_id]
        normalized = _normalize_url(url)
        for record in self._flows:
            if record.entry_id is not None:
                continue
            if record.method != method or record.url != normalized:
                continue
            self._assign(record, entry_id)
            return record.request_body
        return None

    def claim_response_for_entry(self, entry_id: str, method: str, url: str) -> bytes | None:
        if entry_id in self._response_bodies:
            return self._response_bodies[entry_id]
        self.claim_for_entry(entry_id, method, url)
        return self._response_bodies.get(entry_id)

    def get_request_body(self, entry_id: str) -> bytes | None:
        return self._request_bodies.get(entry_id)

    def get_response_body(self, entry_id: str) -> bytes | None:
        return self._response_bodies.get(entry_id)

    def request_was_truncated(self, entry_id: str) -> bool:
        for record in reversed(self._flows):
            if record.entry_id == entry_id:
                return record.request_truncated
        return False

    def response_was_truncated(self, entry_id: str) -> bool:
        for record in reversed(self._flows):
            if record.entry_id == entry_id:
                return record.response_truncated
        return False

    async def wait_for_request_body(
        self,
        entry_id: str,
        *,
        timeout: float = 2.0,
    ) -> bytes | None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            body = self._request_bodies.get(entry_id)
            if body is not None:
                return body
            await asyncio.sleep(0.05)
        return self._request_bodies.get(entry_id)

    async def wait_for_response_body(
        self,
        entry_id: str,
        *,
        timeout: float = 2.0,
    ) -> bytes | None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            body = self._response_bodies.get(entry_id)
            if body is not None:
                return body
            await asyncio.sleep(0.05)
        return self._response_bodies.get(entry_id)

    def _try_pair_from_hint(self, hint: CaptureHint) -> None:
        for record in self._flows:
            if record.consumed or record.entry_id is not None:
                continue
            if self._matches(hint, record):
                self._assign(record, hint.entry_id)
                return

    def _try_pair(self, record: ProxyFlowRecord) -> None:
        while self._hints:
            hint = self._hints[0]
            if hint.observed_at - record.timestamp > MATCH_WINDOW_S:
                self._hints.popleft()
                continue
            if record.timestamp - hint.observed_at > MATCH_WINDOW_S:
                break
            if self._matches(hint, record):
                self._hints.popleft()
                self._assign(record, hint.entry_id)
                return
            break

    def _assign(self, record: ProxyFlowRecord, entry_id: str) -> None:
        record.consumed = True
        record.entry_id = entry_id
        self._request_bodies[entry_id] = record.request_body
        if record.response_body:
            self._response_bodies[entry_id] = record.response_body
    def _matches(self, hint: CaptureHint, record: ProxyFlowRecord) -> bool:
        if hint.method != record.method or hint.url != record.url:
            return False
        return abs(record.timestamp - hint.observed_at) <= MATCH_WINDOW_S

    def _find_open_flow(self, method: str, url: str) -> ProxyFlowRecord | None:
        normalized = _normalize_url(url)
        for record in reversed(self._flows):
            if record.method == method and record.url == normalized:
                return record
        return None


class WebgentCaptureAddon:
    def __init__(self, store: ProxyCaptureStore) -> None:
        self._store = store

    def request(self, flow: http.HTTPFlow) -> None:
        self._store.record_request(flow)

    def response(self, flow: http.HTTPFlow) -> None:
        self._store.record_response(flow)


class ProxyCaptureServer:
    def __init__(self, settings: ProxySettings, store: ProxyCaptureStore) -> None:
        self._settings = settings
        self._store = store
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._master: DumpMaster | None = None
        self._ready = threading.Event()
        self._listen_host = settings.host
        self._listen_port = settings.port

    @property
    def listen_host(self) -> str:
        return self._listen_host

    @property
    def listen_port(self) -> int:
        return self._listen_port

    @property
    def proxy_server_url(self) -> str:
        if self._settings.mode == "external" and self._settings.external_server:
            return self._settings.external_server
        return f"http://{self._listen_host}:{self._listen_port}"

    def start(self) -> None:
        if self._settings.mode != "embedded" or not self._settings.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = None
        self._loop = None
        self._master = None
        self._ready.clear()
        self._listen_port = _pick_listen_port(
            self._settings.host,
            self._settings.port,
        )
        MITMPROXY_DIR.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._run_thread,
            name="webgent-mitmproxy",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise RuntimeError("mitmproxy failed to start within 15 seconds")

    def stop(self) -> None:
        master = self._master
        loop = self._loop
        thread = self._thread
        if master is not None and loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(master.shutdown)
            except RuntimeError:
                pass
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None
        self._loop = None
        self._master = None
        self._ready.clear()

    def _run_thread(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_master())
        finally:
            self._loop.close()

    async def _run_master(self) -> None:
        opts = Options(
            listen_host=self._settings.host,
            listen_port=self._listen_port,
            confdir=str(MITMPROXY_DIR),
        )
        self._master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        self._master.addons.add(WebgentCaptureAddon(self._store))
        self._listen_host = self._master.options.listen_host
        self._listen_port = int(self._master.options.listen_port)
        self._ready.set()
        await self._master.run()


def playwright_proxy_options(settings: ProxySettings, server_url: str) -> dict[str, Any]:
    launch_extras: dict[str, Any] = {
        "proxy": {"server": server_url},
        "ignore_https_errors": True,
    }
    if not settings.bypass_loopback:
        launch_extras["args"] = ["--proxy-bypass-list=<-loopback>"]
    return launch_extras
