from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from webgent.captcha_ocr import CaptchaMode, recognize_captcha_with_mode
from webgent.cdp_post_data import CdpPostDataCapture
from webgent.config import PROFILE_DIR, get_settings
from webgent.files import resolve_upload_files
from webgent.page_state import PageSnapshotState
from webgent.screenshot import capture_screenshot, save_screenshot, screenshot_metadata
from webgent.vlm import VLM_UNAVAILABLE_MESSAGE, VlmError, query_vlm, vlm_failure_reason
from webgent.network_capture import (
    DEFAULT_MAX_RESPONSE_BYTES,
    ActionNetworkCapture,
    NetworkCaptureStore,
)
from webgent.proxy_capture import (
    ProxyCaptureServer,
    ProxyCaptureStore,
    playwright_proxy_options,
)
from webgent.request_body import resolve_request_body, resolve_response_body
from webgent.crypto_rsa import encrypt_rsa as encrypt_rsa_text
from webgent.crypto_rsa import encrypt_via_page
from webgent.http_client import http_request as send_http_request
from webgent.page_inspect import (
    evaluate_js as run_evaluate_js,
    get_cookies as read_cookies,
    get_form_data as read_form_data,
    set_cookies as write_cookies,
)
from webgent.replay import replay_request as run_replay_request
from webgent.request_registry import RequestRegistry, decode_body_bytes
from webgent.snapshot import (
    DEFAULT_GET_NODE_DEPTH,
    DEFAULT_MAX_URL_LEN,
    capture_html_snapshot,
    click_ref,
    fill_ref,
    get_node_result,
    is_html_content_type,
    normalize_ref,
    press_sequentially_ref,
    read_locator_value,
    read_page_signals,
    ref_locator,
    resolve_ref_locator,
    select_option_ref,
    set_checked_ref,
    set_input_files_ref,
    snapshot_result,
)

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_T = TypeVar("_T")


def sanitize_profile_name(profile_name: str) -> str:
    name = profile_name.strip()
    if not name:
        raise ValueError("profile_name must not be empty")
    if not _PROFILE_NAME_RE.match(name):
        raise ValueError(
            "profile_name may only contain letters, numbers, hyphens, and underscores"
        )
    return name


def profile_path(profile_name: str) -> str:
    safe_name = sanitize_profile_name(profile_name)
    path = (PROFILE_DIR / safe_name).resolve()
    if PROFILE_DIR.resolve() not in path.parents and path != PROFILE_DIR.resolve():
        raise ValueError("Invalid profile_name")
    return str(path)


def _merge_chromium_args(launch_kwargs: dict[str, Any]) -> None:
    extra = list(get_settings().browser.chromium_args)
    if not extra:
        return
    existing = list(launch_kwargs.get("args") or [])
    seen = set(existing)
    merged = list(existing)
    for arg in extra:
        if arg not in seen:
            seen.add(arg)
            merged.append(arg)
    launch_kwargs["args"] = merged


async def page_info(page: Page, page_id: str, is_active: bool) -> dict[str, Any]:
    return {
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "is_active": is_active,
    }


class ProfileBrowser:
    """One persistent Chromium context per profile; shared by multiple sessions."""

    def __init__(
        self,
        profile_name: str,
        context: BrowserContext,
        *,
        proxy_capture: ProxyCaptureStore | None = None,
    ) -> None:
        self.profile_name = profile_name
        self.context = context
        self._sessions: dict[str, BrowserSession] = {}
        self._context_listener_installed = False
        self._closed = False
        self._cdp_post_data = CdpPostDataCapture()
        self._proxy_capture = proxy_capture

    @classmethod
    async def launch(
        cls,
        playwright: Playwright,
        profile_name: str,
        *,
        launch_extras: dict[str, Any] | None = None,
        proxy_capture: ProxyCaptureStore | None = None,
    ) -> ProfileBrowser:
        safe_name = sanitize_profile_name(profile_name)
        user_data_dir = profile_path(safe_name)
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "headless": get_settings().browser.headless,
            "no_viewport": True,
        }
        if launch_extras:
            launch_kwargs.update(launch_extras)
        _merge_chromium_args(launch_kwargs)
        context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
        profile = cls(safe_name, context, proxy_capture=proxy_capture)
        profile._install_context_listener()
        if context.pages:
            install_page = context.pages[0]
        else:
            install_page = await context.new_page()
        await profile._cdp_post_data.install(context, install_page)
        return profile

    def register_session(self, session: BrowserSession) -> None:
        self._sessions[session.session_id] = session

    def unregister_session(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        return not self._sessions

    def is_alive(self) -> bool:
        return not self._closed

    def _install_context_listener(self) -> None:
        if self._context_listener_installed:
            return
        loop = asyncio.get_running_loop()
        self.context.on(
            "page",
            lambda page: loop.create_task(self._route_new_page(page)),
        )
        self._context_listener_installed = True

    async def _route_new_page(self, page: Page) -> None:
        for session in self._sessions.values():
            if await session._page_belongs_to_session(page):
                await session._handle_new_page(page)
                return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.context.close()
        except Exception:
            pass


class BrowserSession:
    def __init__(
        self,
        session_id: str,
        profile_name: str,
        context: BrowserContext,
        pages: dict[str, Page],
        active_page_id: str,
        *,
        cdp_post_data: CdpPostDataCapture,
        proxy_capture: ProxyCaptureStore | None,
    ) -> None:
        self.session_id = session_id
        self.profile_name = profile_name
        self.context = context
        self.pages = pages
        self.active_page_id = active_page_id
        self._page_states: dict[str, PageSnapshotState] = {}
        self._network_store = NetworkCaptureStore()
        self._cdp_post_data = cdp_post_data
        self._proxy_capture = proxy_capture

    @classmethod
    async def create(
        cls,
        profile: ProfileBrowser,
        *,
        initial_url: str = "about:blank",
        adopt_restored_pages: bool = False,
    ) -> BrowserSession:
        session_id = str(uuid.uuid4())
        pages: dict[str, Page] = {}
        active_page_id = ""

        if adopt_restored_pages and profile.context.pages:
            for page in profile.context.pages:
                page_id = str(uuid.uuid4())
                pages[page_id] = page
                if not active_page_id:
                    active_page_id = page_id
        else:
            page = await profile.context.new_page()
            page_id = str(uuid.uuid4())
            pages[page_id] = page
            active_page_id = page_id
            if initial_url and initial_url != "about:blank":
                await page.goto(initial_url)

        session = cls(
            session_id=session_id,
            profile_name=profile.profile_name,
            context=profile.context,
            pages=pages,
            active_page_id=active_page_id,
            cdp_post_data=profile._cdp_post_data,
            proxy_capture=profile._proxy_capture,
        )
        for page in pages.values():
            session._attach_page_close_listener(page)
        if adopt_restored_pages and initial_url and initial_url != "about:blank":
            await pages[active_page_id].goto(initial_url)
        for page_id in pages:
            await session._ensure_page_state(page_id)
        return session

    def _find_page_id(self, page: Page) -> str | None:
        for page_id, tracked in self.pages.items():
            if tracked is page:
                return page_id
        return None

    def _register_page(self, page: Page, *, activate: bool = False) -> str:
        existing = self._find_page_id(page)
        if existing is not None:
            if activate:
                self.active_page_id = existing
            return existing
        page_id = str(uuid.uuid4())
        self.pages[page_id] = page
        self._attach_page_close_listener(page)
        if activate:
            self.active_page_id = page_id
        return page_id

    async def _page_belongs_to_session(self, page: Page) -> bool:
        opener = await page.opener()
        if opener is None:
            return False
        return self._find_page_id(opener) is not None

    def _attach_page_close_listener(self, page: Page) -> None:
        if getattr(page, "_webgent_close_listener", False):
            return
        loop = asyncio.get_running_loop()
        page.on(
            "close",
            lambda: loop.create_task(self._handle_page_closed(page)),
        )
        page._webgent_close_listener = True  # type: ignore[attr-defined]

    async def _handle_new_page(self, page: Page) -> None:
        page_id = self._register_page(page, activate=True)
        await self._ensure_page_state(page_id)
        state = self._page_states[page_id]
        state.last_scope_ref = None
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await page.bring_to_front()

    async def _handle_page_closed(self, page: Page) -> None:
        page_id = self._find_page_id(page)
        if page_id is None:
            return
        self.pages.pop(page_id, None)
        self._page_states.pop(page_id, None)
        if page_id == self.active_page_id and self.pages:
            self.active_page_id = next(iter(self.pages))
            try:
                await self.pages[self.active_page_id].bring_to_front()
            except Exception:
                pass

    async def _should_adopt_page(
        self,
        page: Page,
        *,
        pages_before: frozenset[Page] | None = None,
    ) -> bool:
        if await self._page_belongs_to_session(page):
            return True
        # target=_blank cross-origin popups often lose opener metadata.
        if pages_before is None or page in pages_before:
            return False
        return await page.opener() is None

    async def _adopt_new_pages(
        self,
        *,
        activate: bool = True,
        pages_before: frozenset[Page] | None = None,
    ) -> str | None:
        new_page_id: str | None = None
        for _ in range(40):
            unregistered = []
            for candidate in self.context.pages:
                if self._find_page_id(candidate) is not None:
                    continue
                if await self._should_adopt_page(
                    candidate,
                    pages_before=pages_before,
                ):
                    unregistered.append(candidate)
            if unregistered:
                break
            await asyncio.sleep(0.05)
        for page in self.context.pages:
            if self._find_page_id(page) is not None:
                continue
            if not await self._should_adopt_page(page, pages_before=pages_before):
                continue
            new_page_id = self._register_page(page, activate=False)
            await self._ensure_page_state(new_page_id)
            state = self._page_states[new_page_id]
            state.last_scope_ref = None
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
        if activate and new_page_id is not None:
            self.active_page_id = new_page_id
            await self.pages[new_page_id].bring_to_front()
        return new_page_id

    async def _has_pending_popup_pages(
        self,
        *,
        pages_before: frozenset[Page] | None = None,
    ) -> bool:
        for page in self.context.pages:
            if self._find_page_id(page) is not None:
                continue
            if await self._should_adopt_page(page, pages_before=pages_before):
                return True
        return False

    async def _finalize_action_page(
        self,
        acted_page_id: str,
        acted_page: Page,
        *,
        pages_before: frozenset[Page] | None = None,
    ) -> tuple[Page, str, dict[str, Any]]:
        meta: dict[str, Any] = {"opened_new_page": False}
        for _ in range(60):
            await self._adopt_new_pages(
                activate=True,
                pages_before=pages_before,
            )
            if self.active_page_id != acted_page_id:
                break
            if not await self._has_pending_popup_pages(pages_before=pages_before):
                break
            await asyncio.sleep(0.05)
        active_page_id = self.active_page_id
        active_page = self.pages[active_page_id]
        if active_page_id != acted_page_id:
            meta["opened_new_page"] = True
            meta["previous_page_id"] = acted_page_id
        try:
            await active_page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await self._sync_page_state(active_page_id)
        meta["active_page_id"] = active_page_id
        return active_page, active_page_id, meta

    def _get_page(self, page_id: str) -> Page:
        if page_id not in self.pages:
            raise ValueError(f"Unknown page_id: {page_id}")
        return self.pages[page_id]

    def _active_page(self) -> Page:
        return self._get_page(self.active_page_id)

    async def _ensure_page_state(self, page_id: str) -> PageSnapshotState:
        if page_id not in self._page_states:
            page = self._get_page(page_id)
            signals = await read_page_signals(page)
            self._page_states[page_id] = PageSnapshotState.from_signals(signals)
        return self._page_states[page_id]

    async def _sync_page_state(self, page_id: str) -> PageSnapshotState:
        page = self._get_page(page_id)
        signals = await read_page_signals(page)
        state = await self._ensure_page_state(page_id)
        state.sync_from_signals(signals)
        return state

    def _resolve_page(self, page_id: str | None) -> tuple[Page, str]:
        resolved_page_id = page_id or self.active_page_id
        return self._get_page(resolved_page_id), resolved_page_id

    async def _with_optional_capture(
        self,
        action: Callable[[], Awaitable[_T]],
        *,
        capture_requests: bool,
        max_url_len: int,
    ) -> tuple[_T, list[dict[str, Any]] | None]:
        if not capture_requests:
            return await action(), None
        async with ActionNetworkCapture(
            self._network_store,
            self,
            cdp_post_data=self._cdp_post_data,
            proxy_capture=self._proxy_capture,
        ) as capture:
            result = await action()
        return result, self._network_store.summaries(
            capture.captured_ids,
            max_url_len,
        )

    def _append_requests(
        self,
        result: dict[str, Any],
        requests: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if requests is not None:
            result["requests"] = requests
            if requests:
                sample_ids = ", ".join(entry["id"] for entry in requests[:3])
                extra = f" (+{len(requests) - 3} more)" if len(requests) > 3 else ""
                result["capture_hint"] = (
                    "Use get_captured_response with request_id from requests "
                    f"(e.g. {sample_ids}{extra})."
                )
        return result

    async def _run_action(
        self,
        acted_ref: str,
        action_fn: Callable[[Page], Awaitable[None]],
        page_id: str | None = None,
        *,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
        **extra: Any,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        await resolve_ref_locator(page, acted_ref)

        async def do_action() -> tuple[Page, str, dict[str, Any]]:
            pages_before = frozenset(self.context.pages)
            await action_fn(page)
            return await self._finalize_action_page(
                resolved_page_id,
                page,
                pages_before=pages_before,
            )

        (active_page, active_page_id, page_meta), requests = (
            await self._with_optional_capture(
                do_action,
                capture_requests=capture_requests,
                max_url_len=max_url_len,
            )
        )
        return self._append_requests(
            {
                "page_id": active_page_id,
                "ref": normalize_ref(acted_ref),
                "url": active_page.url,
                "title": await active_page.title(),
                **page_meta,
                **extra,
            },
            requests,
        )

    async def add_page(
        self,
        url: str | None = None,
        *,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        page = await self.context.new_page()
        page_id = self._register_page(page, activate=True)

        if url:

            async def do_nav() -> None:
                await page.goto(url)

            _, requests = await self._with_optional_capture(
                do_nav,
                capture_requests=capture_requests,
                max_url_len=max_url_len,
            )
        else:
            requests = None

        await self._ensure_page_state(page_id)
        return self._append_requests(
            await page_info(page, page_id, is_active=True),
            requests,
        )

    async def list_pages(self) -> dict[str, Any]:
        pages = []
        for page_id, page in self.pages.items():
            pages.append(
                await page_info(page, page_id, page_id == self.active_page_id)
            )
        return {"pages": pages}

    async def switch_page(self, page_id: str) -> dict[str, Any]:
        page = self._get_page(page_id)
        self.active_page_id = page_id
        await page.bring_to_front()
        await self._ensure_page_state(page_id)
        return {
            "active_page_id": page_id,
            "url": page.url,
            "title": await page.title(),
        }

    async def goto(
        self,
        url: str,
        page_id: str | None = None,
        *,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)

        async def do_nav() -> None:
            await page.goto(url)
            state = await self._sync_page_state(resolved_page_id)
            state.last_scope_ref = None

        _, requests = await self._with_optional_capture(
            do_nav,
            capture_requests=capture_requests,
            max_url_len=max_url_len,
        )
        return self._append_requests(
            {
                "page_id": resolved_page_id,
                "url": page.url,
                "title": await page.title(),
            },
            requests,
        )

    async def get_captured_response(
        self,
        request_id: str,
        *,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        format: Literal["tree", "raw"] = "tree",
    ) -> dict[str, Any]:
        entry = self._network_store.get(request_id)
        if entry._response is None:
            raise ValueError(f"No response available for request_id: {request_id}")
        body_bytes, body_source = await resolve_response_body(
            entry,
            self._proxy_capture,
        )
        body, full_size, truncated = decode_body_bytes(
            body_bytes,
            max_bytes=max_bytes,
        )
        content_type = entry._response.headers.get("content-type", "")
        result: dict[str, Any] = {
            "request_id": request_id,
            "status": entry.status,
            "content_type": content_type,
            "body": body,
            "size": full_size,
            "body_source": body_source,
        }
        if truncated:
            result["truncated"] = True
        if is_html_content_type(content_type) and format == "tree":
            try:
                result["body"] = await capture_html_snapshot(self.context, body)
                result["format"] = "tree"
            except Exception:
                result["format"] = "raw"
        else:
            result["format"] = "raw"
        return result

    async def get_captured_request_headers(
        self,
        request_id: str,
    ) -> dict[str, Any]:
        entry = self._network_store.get(request_id)
        try:
            headers = await entry._request.all_headers()
        except Exception as exc:
            raise ValueError(
                f"Could not read request headers for request_id: {request_id}"
            ) from exc
        return {"request_id": request_id, "headers": headers}

    async def get_captured_request_body(
        self,
        request_id: str,
        *,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        entry = self._network_store.get(request_id)
        body_bytes, body_source = await resolve_request_body(
            entry,
            self._proxy_capture,
            self._cdp_post_data,
        )
        body, full_size, truncated = decode_body_bytes(
            body_bytes,
            max_bytes=max_bytes,
        )
        result: dict[str, Any] = {
            "request_id": request_id,
            "method": entry.method,
            "content_type": entry._request.headers.get("content-type", ""),
            "body": body,
            "size": full_size,
            "body_source": body_source,
        }
        if truncated:
            result["truncated"] = True
        if self._proxy_capture is not None and self._proxy_capture.request_was_truncated(
            request_id
        ):
            result["proxy_truncated"] = True
        return result

    async def get_captured_response_headers(
        self,
        request_id: str,
    ) -> dict[str, Any]:
        entry = self._network_store.get(request_id)
        if entry._response is None:
            raise ValueError(f"No response available for request_id: {request_id}")
        try:
            headers = await entry._response.all_headers()
        except Exception as exc:
            raise ValueError(
                f"Could not read response headers for request_id: {request_id}"
            ) from exc
        return {
            "request_id": request_id,
            "status": entry.status,
            "headers": headers,
        }

    async def close(self) -> None:
        for page in list(self.pages.values()):
            try:
                await page.close()
            except Exception:
                pass
        self.pages.clear()
        self._page_states.clear()
        self._network_store.clear()

    async def session_info(self) -> dict[str, Any]:
        page = self._active_page()
        return {
            "session_id": self.session_id,
            "profile_name": self.profile_name,
            "page_id": self.active_page_id,
            "url": page.url,
            "title": await page.title(),
        }

    async def page_snapshot(
        self,
        page_id: str | None = None,
        *,
        ref: str | None = None,
        depth: int | None = None,
        boxes: bool = False,
        include_urls: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        state = await self._ensure_page_state(resolved_page_id)
        if ref is not None:
            state.last_scope_ref = normalize_ref(ref)
        else:
            state.last_scope_ref = None
        result = await snapshot_result(
            page,
            resolved_page_id,
            scope_ref=ref,
            depth=depth,
            boxes=boxes,
            include_urls=include_urls,
            max_url_len=max_url_len,
        )
        await self._sync_page_state(resolved_page_id)
        return result

    async def get_node(
        self,
        ref: str,
        page_id: str | None = None,
        *,
        depth: int = DEFAULT_GET_NODE_DEPTH,
        include_urls: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        return await get_node_result(
            page,
            resolved_page_id,
            ref,
            depth=depth,
            include_urls=include_urls,
            max_url_len=max_url_len,
        )

    async def get_link_url(
        self,
        ref: str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        locator = await resolve_ref_locator(page, ref)
        href = await locator.get_attribute("href")
        if not href:
            raise ValueError(f"Element {ref!r} has no href attribute")
        return {
            "page_id": resolved_page_id,
            "ref": normalize_ref(ref),
            "url": href,
        }

    async def click(
        self,
        ref: str,
        page_id: str | None = None,
        *,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: click_ref(page, ref),
            page_id,
            capture_requests=capture_requests,
            max_url_len=max_url_len,
        )

    async def fill_field(
        self,
        ref: str,
        value: str,
        page_id: str | None = None,
        *,
        slowly: bool = False,
        submit: bool = False,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        async def action(page: Page) -> None:
            locator = ref_locator(page, ref)
            if slowly:
                await press_sequentially_ref(locator, value)
            else:
                await fill_ref(locator, value)
            if submit:
                await locator.press("Enter")

        result = await self._run_action(
            ref,
            action,
            page_id,
            capture_requests=capture_requests,
            max_url_len=max_url_len,
        )
        page, _ = self._resolve_page(result["page_id"])
        result["value"] = await read_locator_value(ref_locator(page, ref))
        return result

    async def select_option(
        self,
        ref: str,
        values: list[str],
        page_id: str | None = None,
        *,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        if not values:
            raise ValueError("values must contain at least one option to select")
        selected_values: list[str] = []

        async def action(page: Page) -> None:
            nonlocal selected_values
            selected_values = await select_option_ref(ref_locator(page, ref), values)

        result = await self._run_action(
            ref,
            action,
            page_id,
            capture_requests=capture_requests,
            max_url_len=max_url_len,
            values=values,
        )
        result["selected"] = selected_values
        return result

    async def set_checkbox(
        self,
        ref: str,
        checked: bool,
        page_id: str | None = None,
        *,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: set_checked_ref(ref_locator(page, ref), checked),
            page_id,
            capture_requests=capture_requests,
            max_url_len=max_url_len,
            checked=checked,
        )

    async def upload_files(
        self,
        ref: str,
        page_id: str | None = None,
        *,
        filepath: str | None = None,
        filepaths: list[str] | None = None,
        text: str | None = None,
        filename: str | None = None,
        capture_requests: bool = False,
        max_url_len: int = DEFAULT_MAX_URL_LEN,
    ) -> dict[str, Any]:
        files, names, source = resolve_upload_files(
            filepath=filepath,
            filepaths=filepaths,
            text=text,
            filename=filename,
        )

        async def action(page: Page) -> None:
            await set_input_files_ref(ref_locator(page, ref), files)

        return await self._run_action(
            ref,
            action,
            page_id,
            capture_requests=capture_requests,
            max_url_len=max_url_len,
            files=names,
            source=source,
        )

    async def evaluate_js(
        self,
        expression: str,
        page_id: str | None = None,
        *,
        arg: Any = None,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        result = await run_evaluate_js(page, expression, arg)
        return {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
            **result,
        }

    async def get_form_data(
        self,
        page_id: str | None = None,
        *,
        form_index: int = 0,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        result = await read_form_data(page, form_index=form_index)
        return {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
            **result,
        }

    async def get_cookies(
        self,
        *,
        urls: list[str] | None = None,
    ) -> dict[str, Any]:
        return await read_cookies(self.context, urls=urls)

    async def set_cookies(
        self,
        cookies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await write_cookies(self.context, cookies)

    async def http_request(
        self,
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
        page, resolved_page_id = self._resolve_page(None)
        result = await send_http_request(
            self.context,
            method=method,
            url=url,
            headers=headers,
            body=body,
            data=data,
            json_body=json_body,
            content_type=content_type,
            max_bytes=max_bytes,
            format=format,
        )
        return {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
            **result,
        }

    async def encrypt_rsa(
        self,
        plaintext: str,
        *,
        public_key: str | None = None,
        page_id: str | None = None,
        password_mode: Literal["page", "rsa"] = "page",
        expression: str | None = None,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        if password_mode == "rsa":
            ciphertext = encrypt_rsa_text(plaintext, public_key or "")
            mode = "rsa"
        else:
            ciphertext = await encrypt_via_page(page, plaintext, expression=expression)
            mode = "page"
        return {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
            "ciphertext": ciphertext,
            "mode": mode,
        }

    async def take_screenshot(
        self,
        page_id: str | None = None,
        *,
        ref: str | None = None,
        full_page: bool = False,
        image_type: str = "png",
        quality: int | None = None,
    ):
        if image_type not in {"png", "jpeg"}:
            raise ValueError("image_type must be 'png' or 'jpeg'")
        if ref is not None and full_page:
            full_page = False

        page, resolved_page_id = self._resolve_page(page_id)
        image_data, mode = await capture_screenshot(
            page,
            ref=ref,
            full_page=full_page,
            image_type=image_type,  # type: ignore[arg-type]
            quality=quality,
        )
        metadata = await screenshot_metadata(
            page,
            resolved_page_id,
            mode=mode,
            ref=ref,
            image_type=image_type,  # type: ignore[arg-type]
        )
        return save_screenshot(
            image_data,
            metadata,
            image_type=image_type,  # type: ignore[arg-type]
        )

    async def captcha_ocr(
        self,
        ref: str,
        page_id: str | None = None,
        *,
        mode: CaptchaMode = "ddddocr",
        beta: bool = False,
        png_fix: bool = False,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        locator = await resolve_ref_locator(page, ref)
        image_data = await locator.screenshot(type="png")
        ocr_result = await recognize_captcha_with_mode(
            image_data,
            mode=mode,
            beta=beta,
            png_fix=png_fix,
        )
        return {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
            "ref": normalize_ref(ref),
            **ocr_result,
        }

    async def vision_query(
        self,
        prompt: str,
        page_id: str | None = None,
        *,
        ref: str | None = None,
        full_page: bool = False,
    ) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")

        if ref is not None and full_page:
            full_page = False

        page, resolved_page_id = self._resolve_page(page_id)
        image_data, mode = await capture_screenshot(
            page,
            ref=ref,
            full_page=full_page,
            image_type="png",
        )
        result: dict[str, Any] = {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
            "mode": mode,
            "prompt": prompt,
        }
        if ref is not None:
            result["ref"] = normalize_ref(ref)

        try:
            response = await query_vlm(image_data, prompt)
        except VlmError as exc:
            result.update(
                {
                    "available": False,
                    "error": str(exc),
                    "message": VLM_UNAVAILABLE_MESSAGE,
                }
            )
            return result
        except Exception as exc:
            result.update(
                {
                    "available": False,
                    "error": vlm_failure_reason(exc),
                    "message": VLM_UNAVAILABLE_MESSAGE,
                }
            )
            return result

        result.update({"available": True, "response": response})
        return result


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._profiles: dict[str, ProfileBrowser] = {}
        self._sessions: dict[str, BrowserSession] = {}
        self._registry = RequestRegistry()
        proxy_settings = get_settings().proxy
        self._proxy_store = ProxyCaptureStore(
            max_body_bytes=proxy_settings.max_body_bytes,
        )
        self._proxy_server = ProxyCaptureServer(proxy_settings, self._proxy_store)
        self._transform_browser: Browser | None = None
        self._transform_context: BrowserContext | None = None

    def _proxy_launch_extras(self) -> dict[str, Any] | None:
        settings = get_settings().proxy
        if not settings.enabled:
            return None
        return playwright_proxy_options(settings, self._proxy_server.proxy_server_url)

    async def start(self) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        if get_settings().proxy.enabled and get_settings().proxy.mode == "embedded":
            self._proxy_server.start()

    async def stop(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        for profile in list(self._profiles.values()):
            await profile.close()
        self._profiles.clear()
        await self._close_transform_context()
        self._proxy_server.stop()
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def get_session(self, session_id: str) -> BrowserSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        return session

    def _find_session_with_request(self, request_id: str) -> BrowserSession | None:
        for session in self._sessions.values():
            if session._network_store.try_get(request_id) is not None:
                return session
        return None

    def _session_for_request(
        self,
        request_id: str,
        session_id: str | None = None,
    ) -> BrowserSession:
        if session_id is not None:
            session = self.get_session(session_id)
            if session._network_store.try_get(request_id) is None:
                raise ValueError(f"Unknown request_id: {request_id}")
            return session
        session = self._find_session_with_request(request_id)
        if session is None:
            raise ValueError(f"Unknown request_id: {request_id}")
        return session

    def _any_context(self) -> BrowserContext | None:
        for session in self._sessions.values():
            return session.context
        for profile in self._profiles.values():
            if profile.is_alive():
                return profile.context
        return None

    async def _close_transform_context(self) -> None:
        context = self._transform_context
        browser = self._transform_browser
        self._transform_context = None
        self._transform_browser = None
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass

    async def _registry_context(self) -> BrowserContext | None:
        context = self._any_context()
        if context is not None:
            return context
        if self._playwright is None:
            return None
        if self._transform_context is None:
            launch_kwargs: dict[str, Any] = {"headless": True}
            _merge_chromium_args(launch_kwargs)
            self._transform_browser = await self._playwright.chromium.launch(
                **launch_kwargs,
            )
            self._transform_context = await self._transform_browser.new_context()
        return self._transform_context

    async def register_request(
        self,
        request_id: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._registry.exists(request_id):
            meta = self._registry.load_meta(request_id)
            return {
                "request_id": request_id,
                "registry_path": str(self._registry.entry_dir(request_id)),
                "method": meta.get("method"),
                "url": meta.get("url"),
                "status": meta.get("status"),
                "has_response": meta.get("has_response"),
                "already_registered": True,
            }
        session = self._session_for_request(request_id, session_id)
        return await self._registry.save_from_capture(
            session._network_store.get(request_id),
            cdp_post_data=session._cdp_post_data,
            proxy_capture=session._proxy_capture,
        )

    async def get_captured_response(
        self,
        request_id: str,
        *,
        session_id: str | None = None,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        format: Literal["tree", "raw"] = "tree",
    ) -> dict[str, Any]:
        if self._registry.exists(request_id):
            return await self._registry.get_response(
                request_id,
                await self._registry_context(),
                max_bytes=max_bytes,
                format=format,
            )
        session = self._session_for_request(request_id, session_id)
        return await session.get_captured_response(
            request_id,
            max_bytes=max_bytes,
            format=format,
        )

    async def replay_request(
        self,
        session_id: str,
        request_id: str,
        *,
        overrides: dict[str, str] | None = None,
        refresh_token: bool = False,
        refresh_url: str | None = None,
        encrypt_password: bool = False,
        password_mode: Literal["page", "rsa"] = "page",
        public_key: str | None = None,
        expression: str | None = None,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        format: Literal["tree", "raw"] = "tree",
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        return await run_replay_request(
            session,
            self._registry,
            request_id,
            overrides=overrides,
            refresh_token=refresh_token,
            refresh_url=refresh_url,
            encrypt_password=encrypt_password,
            password_mode=password_mode,
            public_key=public_key,
            expression=expression,
            max_bytes=max_bytes,
            format=format,
        )

    async def get_captured_request_headers(
        self,
        request_id: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._registry.exists(request_id):
            return self._registry.get_request_headers(request_id)
        session = self._session_for_request(request_id, session_id)
        return await session.get_captured_request_headers(request_id)

    async def get_captured_request_body(
        self,
        request_id: str,
        *,
        session_id: str | None = None,
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        if self._registry.exists(request_id):
            return self._registry.get_request_body(request_id, max_bytes=max_bytes)
        session = self._session_for_request(request_id, session_id)
        return await session.get_captured_request_body(
            request_id,
            max_bytes=max_bytes,
        )

    async def get_captured_response_headers(
        self,
        request_id: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._registry.exists(request_id):
            return self._registry.get_response_headers(request_id)
        session = self._session_for_request(request_id, session_id)
        return await session.get_captured_response_headers(request_id)

    async def create_session(
        self,
        profile_name: str = "default",
        *,
        initial_url: str = "about:blank",
    ) -> dict[str, Any]:
        if self._playwright is None:
            raise RuntimeError("BrowserManager is not started")
        safe_name = sanitize_profile_name(profile_name)
        profile = self._profiles.get(safe_name)
        adopt_restored_pages = profile is None
        if profile is not None and not profile.is_alive():
            self._drop_profile(safe_name)
            profile = None
            adopt_restored_pages = True
        if profile is None:
            profile = await ProfileBrowser.launch(
                self._playwright,
                safe_name,
                launch_extras=self._proxy_launch_extras(),
                proxy_capture=self._proxy_store,
            )
            self._profiles[safe_name] = profile
        try:
            session = await BrowserSession.create(
                profile,
                initial_url=initial_url,
                adopt_restored_pages=adopt_restored_pages,
            )
        except Exception as exc:
            if type(exc).__name__ != "TargetClosedError":
                raise
            self._drop_profile(safe_name)
            profile = await ProfileBrowser.launch(
                self._playwright,
                safe_name,
                launch_extras=self._proxy_launch_extras(),
                proxy_capture=self._proxy_store,
            )
            self._profiles[safe_name] = profile
            session = await BrowserSession.create(
                profile,
                initial_url=initial_url,
                adopt_restored_pages=True,
            )
        profile.register_session(session)
        self._sessions[session.session_id] = session
        return await session.session_info()

    def _drop_profile(self, profile_name: str) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.profile_name == profile_name:
                del self._sessions[session_id]
        self._profiles.pop(profile_name, None)

    async def close_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        profile = self._profiles.get(session.profile_name)
        await session.close()
        del self._sessions[session_id]
        if profile is not None and profile.unregister_session(session_id):
            await profile.close()
            del self._profiles[session.profile_name]
        return {"session_id": session_id, "closed": True}
