from __future__ import annotations

from contextlib import asynccontextmanager

from fastmcp import Context, FastMCP

from webgent.browser import BrowserManager

_manager: BrowserManager | None = None


@asynccontextmanager
async def app_lifespan(server):
    global _manager
    manager = BrowserManager()
    await manager.start()
    _manager = manager
    try:
        yield {"browser_manager": manager}
    finally:
        await manager.stop()
        _manager = None


mcp = FastMCP("webgent", lifespan=app_lifespan)


def _get_manager() -> BrowserManager:
    if _manager is None:
        raise RuntimeError("BrowserManager is not available")
    return _manager


_ACTION_DOC = (
    "Returns page_id, active_page_id, ref, url, and title. "
    "If a click opens a new tab, page_id switches to the new tab."
)

CREATE_SESSION_DOC = "Start a headed Chromium session with a persistent profile."
ADD_PAGE_DOC = "Open a new tab; optionally go to url."
LIST_PAGES_DOC = "List tabs with page_id, url, title, and is_active."
DELETE_PAGE_DOC = "Close a tab (not the last one in the session)."
SWITCH_PAGE_DOC = "Set the active tab."
GOTO_DOC = "Go to url. Clears snapshot scope; does not return a snapshot."
CLOSE_SESSION_DOC = "Close the session and all tabs."
SNAPSHOT_DOC = (
    "Full YAML accessibility tree. ref scopes capture; omit depth for unlimited depth."
)
INTERACTABLES_DOC = (
    "Trimmed YAML tree of actionable elements: structural parents (navigation, form, dialog) "
    "wrap compact [eN] role \"name\" lines for buttons, links, inputs, checkboxes, radios, "
    "file uploads, comboboxes, sliders, tabs, images, and similar controls. "
    "Combobox/listbox lines include options=. ref scopes capture; omit depth for unlimited depth."
)
GET_NODE_DOC = (
    "Get role, name, states, value, checked, and a small subtree for one ref. "
    "depth defaults to 3 unless passed."
)
GET_URL_DOC = "Get the full href for a link ref."
CLICK_DOC = (
    "Click by ref; falls back when a visible overlay intercepts pointer events. "
    + _ACTION_DOC
)
TYPE_DOC = "Type into an editable element by ref. " + _ACTION_DOC
FILL_DOC = "Fill an input by ref. " + _ACTION_DOC
SELECT_OPTION_DOC = "Select dropdown values by ref. " + _ACTION_DOC
SET_CHECKBOX_DOC = "Set checkbox checked state by ref. " + _ACTION_DOC
SELECT_RADIO_DOC = "Select a radio option by ref. " + _ACTION_DOC
UPLOAD_FILES_DOC = "Upload to a file input by ref. " + _ACTION_DOC
SET_SLIDER_DOC = "Set a slider/range input value by ref. " + _ACTION_DOC
SET_SWITCH_DOC = "Set a switch checked state by ref. " + _ACTION_DOC
SET_SPINBUTTON_DOC = "Set a spinbutton/number input value by ref. " + _ACTION_DOC
SELECT_TAB_DOC = "Select a tab by ref. " + _ACTION_DOC
SCREENSHOT_DOC = "Save a viewport, full-page, or element PNG/JPEG under media/."


@mcp.tool(description=CREATE_SESSION_DOC)
async def create_session(
    ctx: Context,
    profile_name: str = "default",
    initial_url: str = "about:blank",
) -> dict:
    manager = _get_manager()
    return await manager.create_session(
        profile_name,
        initial_url=initial_url,
    )


@mcp.tool(description=ADD_PAGE_DOC)
async def add_page(
    ctx: Context,
    session_id: str,
    url: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.add_page(url)


@mcp.tool(description=LIST_PAGES_DOC)
async def list_pages(ctx: Context, session_id: str) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.list_pages()


@mcp.tool(description=DELETE_PAGE_DOC)
async def delete_page(ctx: Context, session_id: str, page_id: str) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.delete_page(page_id)


@mcp.tool(description=SWITCH_PAGE_DOC)
async def switch_page(ctx: Context, session_id: str, page_id: str) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.switch_page(page_id)


@mcp.tool(description=GOTO_DOC)
async def goto(
    ctx: Context,
    session_id: str,
    url: str,
    page_id: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.goto(url, page_id)


@mcp.tool(description=CLOSE_SESSION_DOC)
async def close_session(ctx: Context, session_id: str) -> dict:
    manager = _get_manager()
    return await manager.close_session(session_id)


@mcp.tool(description=SNAPSHOT_DOC)
async def snapshot(
    ctx: Context,
    session_id: str,
    page_id: str | None = None,
    ref: str | None = None,
    depth: int | None = None,
    boxes: bool = False,
    include_urls: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.page_snapshot(
        page_id,
        ref=ref,
        depth=depth,
        boxes=boxes,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )


@mcp.tool(description=INTERACTABLES_DOC)
async def interactables(
    ctx: Context,
    session_id: str,
    page_id: str | None = None,
    ref: str | None = None,
    depth: int | None = None,
    boxes: bool = False,
    include_urls: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.page_interactables(
        page_id,
        ref=ref,
        depth=depth,
        boxes=boxes,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )


@mcp.tool(description=GET_NODE_DOC)
async def get_node(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    depth: int = 3,
    include_urls: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.get_node(
        ref,
        page_id,
        depth=depth,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )


@mcp.tool(description=GET_URL_DOC)
async def get_url(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.get_link_url(ref, page_id)


@mcp.tool(description=CLICK_DOC)
async def click(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.click(ref, page_id)


@mcp.tool(description=TYPE_DOC)
async def type(
    ctx: Context,
    session_id: str,
    ref: str,
    text: str,
    page_id: str | None = None,
    element: str | None = None,
    submit: bool = False,
    slowly: bool = False,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.type_text(
        ref,
        text,
        page_id,
        submit=submit,
        slowly=slowly,
    )


@mcp.tool(description=FILL_DOC)
async def fill(
    ctx: Context,
    session_id: str,
    ref: str,
    value: str,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.fill_field(ref, value, page_id)


@mcp.tool(description=SELECT_OPTION_DOC)
async def select_option(
    ctx: Context,
    session_id: str,
    ref: str,
    values: list[str],
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.select_option(ref, values, page_id)


@mcp.tool(description=SET_CHECKBOX_DOC)
async def set_checkbox(
    ctx: Context,
    session_id: str,
    ref: str,
    checked: bool,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.set_checkbox(ref, checked, page_id)


@mcp.tool(description=SELECT_RADIO_DOC)
async def select_radio(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.select_radio(ref, page_id)


@mcp.tool(description=UPLOAD_FILES_DOC)
async def upload_files(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    element: str | None = None,
    filepath: str | None = None,
    filepaths: list[str] | None = None,
    text: str | None = None,
    filename: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.upload_files(
        ref,
        page_id,
        filepath=filepath,
        filepaths=filepaths,
        text=text,
        filename=filename,
    )


@mcp.tool(description=SET_SLIDER_DOC)
async def set_slider(
    ctx: Context,
    session_id: str,
    ref: str,
    value: float | int | str,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.set_slider(ref, value, page_id)


@mcp.tool(description=SET_SWITCH_DOC)
async def set_switch(
    ctx: Context,
    session_id: str,
    ref: str,
    checked: bool,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.set_switch(ref, checked, page_id)


@mcp.tool(description=SET_SPINBUTTON_DOC)
async def set_spinbutton(
    ctx: Context,
    session_id: str,
    ref: str,
    value: float | int | str,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.set_spinbutton(ref, value, page_id)


@mcp.tool(description=SELECT_TAB_DOC)
async def select_tab(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    element: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.select_tab(ref, page_id)


@mcp.tool(description=SCREENSHOT_DOC)
async def screenshot(
    ctx: Context,
    session_id: str,
    page_id: str | None = None,
    ref: str | None = None,
    full_page: bool = False,
    image_type: str = "png",
    quality: int | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.take_screenshot(
        page_id,
        ref=ref,
        full_page=full_page,
        image_type=image_type,
        quality=quality,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
