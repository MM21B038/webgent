from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from playwright.async_api import BrowserContext

from webgent.cdp_post_data import CdpPostDataCapture
from webgent.config import REGISTRY_DIR
from webgent.network_capture import DEFAULT_MAX_RESPONSE_BYTES
from webgent.request_body import resolve_request_body, resolve_response_body
from webgent.snapshot import capture_html_snapshot, is_html_content_type

if TYPE_CHECKING:
    from webgent.network_capture import CapturedRequest
    from webgent.proxy_capture import ProxyCaptureStore

REQUEST_HEADER_FILE = "request_header"
RESPONSE_HEADER_FILE = "response_header"
REQUEST_BODY_FILE = "request_body"
RESPONSE_FILE = "response"


def validate_request_id(request_id: str) -> str:
    value = request_id.strip()
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid request_id {request_id!r}. Expected a captured request UUID."
        ) from exc
    return value


def decode_body_bytes(
    body_bytes: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> tuple[str, int, bool]:
    full_size = len(body_bytes)
    truncated = full_size > max_bytes
    if truncated:
        body_bytes = body_bytes[:max_bytes]
    try:
        body = body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        body = body_bytes.decode("utf-8", errors="replace")
    return body, full_size, truncated


class RequestRegistry:
    def __init__(self, root: Path = REGISTRY_DIR) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def entry_dir(self, request_id: str) -> Path:
        safe_id = validate_request_id(request_id)
        path = (self._root / safe_id).resolve()
        if self._root.resolve() not in path.parents:
            raise ValueError(f"Invalid request_id: {request_id}")
        return path

    def exists(self, request_id: str) -> bool:
        return (self.entry_dir(request_id) / REQUEST_HEADER_FILE).is_file()

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _request_header_path(self, request_id: str) -> Path:
        return self.entry_dir(request_id) / REQUEST_HEADER_FILE

    def _response_header_path(self, request_id: str) -> Path:
        return self.entry_dir(request_id) / RESPONSE_HEADER_FILE

    def load_request_header(self, request_id: str) -> dict[str, Any]:
        path = self._request_header_path(request_id)
        if not path.is_file():
            raise ValueError(f"Unknown registered request_id: {request_id}")
        return self._read_json(path)

    def load_response_header(self, request_id: str) -> dict[str, Any]:
        path = self._response_header_path(request_id)
        if not path.is_file():
            raise ValueError(f"No response available for request_id: {request_id}")
        return self._read_json(path)

    def load_meta(self, request_id: str) -> dict[str, Any]:
        request_header = self.load_request_header(request_id)
        meta: dict[str, Any] = {
            "request_id": request_id,
            "method": request_header.get("method"),
            "url": request_header.get("url"),
            "resource_type": request_header.get("resource_type"),
            "request_content_type": request_header.get("content_type", ""),
            "registered_at": request_header.get("registered_at"),
        }
        response_header_path = self._response_header_path(request_id)
        if response_header_path.is_file():
            response_header = self.load_response_header(request_id)
            meta.update(
                {
                    "has_response": True,
                    "status": response_header.get("status"),
                    "ok": response_header.get("ok"),
                    "response_content_type": response_header.get("content_type", ""),
                    "response_format": response_header.get("format", "text"),
                }
            )
        else:
            meta["has_response"] = False
        return meta

    def load_request_headers(self, request_id: str) -> dict[str, str]:
        request_header = self.load_request_header(request_id)
        headers = request_header.get("headers")
        if not isinstance(headers, dict):
            raise ValueError(f"Missing request headers for request_id: {request_id}")
        return headers

    def load_response_headers(self, request_id: str) -> dict[str, str]:
        response_header = self.load_response_header(request_id)
        headers = response_header.get("headers")
        if not isinstance(headers, dict):
            raise ValueError(f"Missing response headers for request_id: {request_id}")
        return headers

    def load_request_body_bytes(self, request_id: str) -> bytes:
        path = self.entry_dir(request_id) / REQUEST_BODY_FILE
        if not path.is_file():
            return b""
        return path.read_bytes()

    def load_response_body_bytes(self, request_id: str) -> bytes:
        if not self._response_header_path(request_id).is_file():
            raise ValueError(f"No response available for request_id: {request_id}")
        path = self.entry_dir(request_id) / RESPONSE_FILE
        if not path.is_file():
            raise ValueError(f"Missing response body for request_id: {request_id}")
        return path.read_bytes()

    async def save_from_capture(
        self,
        entry: CapturedRequest,
        *,
        cdp_post_data: CdpPostDataCapture | None = None,
        proxy_capture: ProxyCaptureStore | None = None,
    ) -> dict[str, Any]:
        request_id = validate_request_id(entry.id)
        entry_dir = self.entry_dir(request_id)
        if self.exists(request_id):
            raise ValueError(f"request_id already registered: {request_id}")

        try:
            request_headers = await entry._request.all_headers()
        except Exception as exc:
            raise ValueError(
                f"Could not read request headers for request_id: {request_id}"
            ) from exc

        try:
            request_body, request_body_source = await resolve_request_body(
                entry,
                proxy_capture,
                cdp_post_data,
            )
        except Exception as exc:
            raise ValueError(
                f"Could not read request body for request_id: {request_id}"
            ) from exc

        response_headers: dict[str, str] = {}
        response_body = b""
        response_body_source = "unavailable"
        has_response = entry._response is not None
        if has_response:
            try:
                response_headers = await entry._response.all_headers()
            except Exception as exc:
                raise ValueError(
                    f"Could not read response headers for request_id: {request_id}"
                ) from exc
            try:
                response_body, response_body_source = await resolve_response_body(
                    entry,
                    proxy_capture,
                )
            except Exception as exc:
                raise ValueError(
                    f"Could not read response body for request_id: {request_id}"
                ) from exc

        request_content_type = entry._request.headers.get("content-type", "")
        response_content_type = (
            entry._response.headers.get("content-type", "") if entry._response else ""
        )

        entry_dir.mkdir(parents=True, exist_ok=False)
        (entry_dir / REQUEST_BODY_FILE).write_bytes(request_body)

        self._write_json(
            entry_dir / REQUEST_HEADER_FILE,
            {
                "method": entry.method,
                "url": entry.url,
                "resource_type": entry.resource_type,
                "content_type": request_content_type,
                "body_source": request_body_source,
                "registered_at": datetime.now(UTC).isoformat(),
                "headers": request_headers,
            },
        )

        if has_response:
            (entry_dir / RESPONSE_FILE).write_bytes(response_body)
            self._write_json(
                entry_dir / RESPONSE_HEADER_FILE,
                {
                    "status": entry.status,
                    "ok": entry.ok,
                    "content_type": response_content_type,
                    "body_source": response_body_source,
                    "format": "text",
                    "headers": response_headers,
                },
            )

        return {
            "request_id": request_id,
            "registry_path": str(entry_dir),
            "method": entry.method,
            "url": entry.url,
            "status": entry.status,
            "has_response": has_response,
        }

    async def get_response(
        self,
        request_id: str,
        context: BrowserContext | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        format: Literal["tree", "raw"] = "tree",
    ) -> dict[str, Any]:
        response_header = self.load_response_header(request_id)
        content_type = str(response_header.get("content_type", ""))
        response_format = str(response_header.get("format", "text"))
        body_bytes = self.load_response_body_bytes(request_id)
        body, full_size, truncated = decode_body_bytes(
            body_bytes,
            max_bytes=max_bytes,
        )
        result: dict[str, Any] = {
            "request_id": request_id,
            "status": response_header.get("status"),
            "content_type": content_type,
            "body": body,
            "size": full_size,
            "registered": True,
        }
        if truncated:
            result["truncated"] = True
        if format == "raw":
            result["format"] = "raw"
            return result
        if response_format == "tree":
            result["format"] = "tree"
            return result
        if is_html_content_type(content_type) and context is not None:
            try:
                result["body"] = await capture_html_snapshot(context, body)
                result["format"] = "tree"
            except Exception:
                result["format"] = "raw"
        else:
            result["format"] = "raw"
        return result

    def get_request_headers(self, request_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "headers": self.load_request_headers(request_id),
            "registered": True,
        }

    def get_request_body(
        self,
        request_id: str,
        *,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        meta = self.load_meta(request_id)
        request_header = self.load_request_header(request_id)
        body_bytes = self.load_request_body_bytes(request_id)
        body, full_size, truncated = decode_body_bytes(
            body_bytes,
            max_bytes=max_bytes,
        )
        result: dict[str, Any] = {
            "request_id": request_id,
            "method": meta.get("method"),
            "content_type": meta.get("request_content_type", ""),
            "body": body,
            "size": full_size,
            "registered": True,
        }
        body_source = request_header.get("body_source")
        if body_source:
            result["body_source"] = body_source
        if truncated:
            result["truncated"] = True
        return result

    def get_response_headers(self, request_id: str) -> dict[str, Any]:
        response_header = self.load_response_header(request_id)
        return {
            "request_id": request_id,
            "status": response_header.get("status"),
            "headers": self.load_response_headers(request_id),
            "registered": True,
        }
