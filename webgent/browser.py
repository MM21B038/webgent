from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from webgent.config import PROFILE_DIR
from webgent.files import resolve_upload_files
from webgent.page_state import PageSnapshotState
from webgent.screenshot import capture_screenshot, save_screenshot, screenshot_metadata
from webgent.snapshot import (
    DEFAULT_GET_NODE_DEPTH,
    DEFAULT_MAX_URL_LEN,
    click_ref,
    get_node_result,
    interactables_result,
    normalize_ref,
    read_locator_value,
    read_page_signals,
    ref_locator,
    snapshot_result,
)

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


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


async def page_info(page: Page, page_id: str, is_active: bool) -> dict[str, Any]:
    return {
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "is_active": is_active,
    }


class BrowserSession:
    def __init__(
        self,
        session_id: str,
        profile_name: str,
        context: BrowserContext,
        pages: dict[str, Page],
        active_page_id: str,
    ) -> None:
        self.session_id = session_id
        self.profile_name = profile_name
        self.context = context
        self.pages = pages
        self.active_page_id = active_page_id
        self._page_states: dict[str, PageSnapshotState] = {}

    @classmethod
    async def create(
        cls,
        playwright: Playwright,
        profile_name: str,
        *,
        initial_url: str = "about:blank",
    ) -> BrowserSession:
        safe_name = sanitize_profile_name(profile_name)
        user_data_dir = profile_path(safe_name)
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            no_viewport=True,
        )

        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()

        if initial_url and initial_url != "about:blank":
            await page.goto(initial_url)

        page_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        session = cls(
            session_id=session_id,
            profile_name=safe_name,
            context=context,
            pages={page_id: page},
            active_page_id=page_id,
        )
        session._attach_page_close_listener(page)
        session._install_context_listeners()
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

    def _attach_page_close_listener(self, page: Page) -> None:
        if getattr(page, "_webgent_close_listener", False):
            return
        loop = asyncio.get_running_loop()
        page.on(
            "close",
            lambda: loop.create_task(self._handle_page_closed(page)),
        )
        page._webgent_close_listener = True  # type: ignore[attr-defined]

    def _install_context_listeners(self) -> None:
        loop = asyncio.get_running_loop()
        self.context.on(
            "page",
            lambda page: loop.create_task(self._handle_new_page(page)),
        )

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

    async def _adopt_new_pages(self, *, activate: bool = True) -> str | None:
        new_page_id: str | None = None
        for _ in range(40):
            unregistered = [p for p in self.context.pages if self._find_page_id(p) is None]
            if unregistered:
                break
            await asyncio.sleep(0.05)
        for page in self.context.pages:
            if self._find_page_id(page) is not None:
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

    async def _finalize_action_page(
        self,
        acted_page_id: str,
        acted_page: Page,
    ) -> tuple[Page, str, dict[str, Any]]:
        meta: dict[str, Any] = {"opened_new_page": False}
        await self._adopt_new_pages(activate=True)
        active_page_id = self.active_page_id
        active_page = self.pages[active_page_id]
        if active_page_id != acted_page_id:
            meta["opened_new_page"] = True
            meta["previous_page_id"] = acted_page_id
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

    async def _run_action(
        self,
        acted_ref: str,
        action_fn: Callable[[Page], Awaitable[None]],
        page_id: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        await action_fn(page)
        active_page, active_page_id, page_meta = await self._finalize_action_page(
            resolved_page_id,
            page,
        )
        return {
            "page_id": active_page_id,
            "ref": normalize_ref(acted_ref),
            "url": active_page.url,
            "title": await active_page.title(),
            **page_meta,
            **extra,
        }

    async def add_page(self, url: str | None = None) -> dict[str, Any]:
        page = await self.context.new_page()
        if url:
            await page.goto(url)
        page_id = self._register_page(page, activate=True)
        await self._ensure_page_state(page_id)
        return await page_info(page, page_id, is_active=True)

    async def list_pages(self) -> dict[str, Any]:
        pages = []
        for page_id, page in self.pages.items():
            pages.append(
                await page_info(page, page_id, page_id == self.active_page_id)
            )
        return {"pages": pages}

    async def delete_page(self, page_id: str) -> dict[str, Any]:
        if len(self.pages) <= 1:
            raise ValueError("Cannot delete the last page in a session")
        page = self.pages.pop(page_id)
        self._page_states.pop(page_id, None)
        was_active = page_id == self.active_page_id
        if was_active and self.pages:
            self.active_page_id = next(iter(self.pages))
        await page.close()
        if was_active and self.pages:
            await self.pages[self.active_page_id].bring_to_front()
        return {
            "deleted_page_id": page_id,
            "active_page_id": self.active_page_id,
        }

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

    async def goto(self, url: str, page_id: str | None = None) -> dict[str, Any]:
        page, resolved_page_id = self._resolve_page(page_id)
        await page.goto(url)
        state = await self._sync_page_state(resolved_page_id)
        state.last_scope_ref = None
        return {
            "page_id": resolved_page_id,
            "url": page.url,
            "title": await page.title(),
        }

    async def close(self) -> None:
        await self.context.close()

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

    async def page_interactables(
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
        result = await interactables_result(
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
        href = await ref_locator(page, ref).get_attribute("href")
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
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: click_ref(page, ref),
            page_id,
        )

    async def type_text(
        self,
        ref: str,
        text: str,
        page_id: str | None = None,
        *,
        submit: bool = False,
        slowly: bool = False,
    ) -> dict[str, Any]:
        async def action(page: Page) -> None:
            locator = ref_locator(page, ref)
            if slowly:
                await locator.press_sequentially(text)
            else:
                await locator.fill(text)
            if submit:
                await locator.press("Enter")

        return await self._run_action(
            ref,
            action,
            page_id,
            text=text,
            submit=submit,
            slowly=slowly,
        )

    async def fill_field(
        self,
        ref: str,
        value: str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: ref_locator(page, ref).fill(value),
            page_id,
            value=value,
        )

    async def select_option(
        self,
        ref: str,
        values: list[str],
        page_id: str | None = None,
    ) -> dict[str, Any]:
        if not values:
            raise ValueError("values must contain at least one option to select")
        selected_values: list[str] = []

        async def action(page: Page) -> None:
            nonlocal selected_values
            selected_values = await ref_locator(page, ref).select_option(values)

        result = await self._run_action(
            ref,
            action,
            page_id,
            values=values,
        )
        result["selected"] = selected_values
        return result

    async def set_checkbox(
        self,
        ref: str,
        checked: bool,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: ref_locator(page, ref).set_checked(checked),
            page_id,
            checked=checked,
        )

    async def select_radio(
        self,
        ref: str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: ref_locator(page, ref).set_checked(True),
            page_id,
            checked=True,
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
    ) -> dict[str, Any]:
        files, names, source = resolve_upload_files(
            filepath=filepath,
            filepaths=filepaths,
            text=text,
            filename=filename,
        )

        async def action(page: Page) -> None:
            await ref_locator(page, ref).set_input_files(files)

        return await self._run_action(
            ref,
            action,
            page_id,
            files=names,
            source=source,
        )

    async def set_slider(
        self,
        ref: str,
        value: float | int | str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        async def action(page: Page) -> None:
            await ref_locator(page, ref).fill(str(value))

        result = await self._run_action(ref, action, page_id)
        page, _ = self._resolve_page(result["page_id"])
        result["value"] = await read_locator_value(ref_locator(page, ref))
        return result

    async def set_switch(
        self,
        ref: str,
        checked: bool,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: ref_locator(page, ref).set_checked(checked),
            page_id,
            checked=checked,
        )

    async def set_spinbutton(
        self,
        ref: str,
        value: float | int | str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        async def action(page: Page) -> None:
            await ref_locator(page, ref).fill(str(value))

        result = await self._run_action(ref, action, page_id)
        page, _ = self._resolve_page(result["page_id"])
        result["value"] = await read_locator_value(ref_locator(page, ref))
        return result

    async def select_tab(
        self,
        ref: str,
        page_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_action(
            ref,
            lambda page: ref_locator(page, ref).click(no_wait_after=True),
            page_id,
        )

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


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._sessions: dict[str, BrowserSession] = {}

    async def start(self) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def get_session(self, session_id: str) -> BrowserSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        return session

    async def create_session(
        self,
        profile_name: str = "default",
        *,
        initial_url: str = "about:blank",
    ) -> dict[str, Any]:
        if self._playwright is None:
            raise RuntimeError("BrowserManager is not started")
        session = await BrowserSession.create(
            self._playwright,
            profile_name,
            initial_url=initial_url,
        )
        self._sessions[session.session_id] = session
        return await session.session_info()

    async def close_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        await session.close()
        del self._sessions[session_id]
        return {"session_id": session_id, "closed": True}
