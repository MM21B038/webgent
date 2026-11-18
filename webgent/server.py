from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import warnings

from authlib.deprecate import AuthlibDeprecationWarning

warnings.filterwarnings(
    "ignore",
    category=AuthlibDeprecationWarning,
)

from fastmcp import Context, FastMCP

from webgent.browser import BrowserManager
from webgent.config import (
    PROMPT_PATH,
    README_PATH,
    get_settings,
)
from webgent.mcp_tools import ToolErrorAsResponseMiddleware, wrap_tool_result

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
mcp.add_middleware(ToolErrorAsResponseMiddleware())
_mcp_cursor = get_settings().mcp_cursor


def _get_manager() -> BrowserManager:
    if _manager is None:
        raise RuntimeError("BrowserManager is not available")
    return _manager


def tool(*, description: str):
    def decorator(fn):
        return mcp.tool(description=description)(wrap_tool_result(fn))

    return decorator


def _read_project_markdown(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing project file: {path.name}")
    return path.read_text(encoding="utf-8")


@mcp.resource(
    _mcp_cursor.server_info_resource,
    name="server-info",
    description="Project README: install, configuration, tools, and agent workflow.",
    mime_type="text/markdown",
)
def readme() -> str:
    return _read_project_markdown(README_PATH)


@mcp.prompt(
    name=_mcp_cursor.prompt,
    description="Agent instructions for when and how to use webgent MCP tools.",
)
def prompt() -> str:
    return _read_project_markdown(PROMPT_PATH)


_ACTION_DOC = (
    "Returns page_id, active_page_id, ref, url, and title. "
    "If a click opens a new tab, page_id switches to the new tab."
)
_CAPTURE_DOC = (
    " capture_requests=true records network activity during the action and returns "
    "a compact requests list (id, method, resource_type, url, status). "
    "Fetch request/response bodies and headers separately by request id."
)

CREATE_SESSION_DOC = (
    "Start a headed Chromium session with a persistent profile. "
    "Multiple sessions can share the same profile_name; each gets its own tabs."
)
ADD_PAGE_DOC = "Open a new tab; optionally go to url." + _CAPTURE_DOC
LIST_PAGES_DOC = "List tabs with page_id, url, title, and is_active."
SWITCH_PAGE_DOC = "Set the active tab."
GOTO_DOC = (
    "Go to url. Clears snapshot scope; does not return a snapshot." + _CAPTURE_DOC
)
CLOSE_SESSION_DOC = "Close the session and all tabs."
SNAPSHOT_DOC = (
    "Full YAML accessibility tree with [ref=…] markers. "
    "Returns signals.dialog_count and signals.iframe_hollow_count for blockers. "
    "Enriched lines include value=, checked=, and selected= suffixes. "
    "Long option lists collapse to first 10 + ... N omitted ... + last 10; "
    "selected/checked items stay visible. "
    "ref scopes capture; omit depth for unlimited depth. "
    "Always call snapshot after navigation or any action failure."
)
GET_NODE_DOC = (
    "Inspect one ref: role, name, states, value, checked, and a scoped subtree "
    "(same truncation and enrichment as snapshot). "
    "Use for deep inspection; prefer snapshot for the full page."
)
GET_URL_DOC = "Get the full href for a link ref."
CLICK_DOC = (
    "Click by ref (button, tab, radio, link, or generic). "
    "Scrolls into view first; off-screen elements fall back to DOM click. "
    "Falls back when a visible overlay intercepts pointer events. "
    "On failure, check error hint and run snapshot to find blockers. "
    + _ACTION_DOC
    + _CAPTURE_DOC
)
FILL_DOC = (
    "Fill textbox, searchbox, textarea, spinbutton, slider, or date field by ref. "
    "Scrolls into view first with DOM fallback for off-screen fields. "
    "Verifies the value was written; check returned value. "
    "slowly=true types character-by-character; submit=true presses Enter after fill. "
    "Readonly date pickers accept dd-mm-yyyy or yyyy-mm-dd. "
    + _ACTION_DOC
    + _CAPTURE_DOC
)
SELECT_OPTION_DOC = (
    "Select combobox or listbox values by ref. "
    "Scrolls into view first with DOM fallback for off-screen controls. "
    + _ACTION_DOC
    + _CAPTURE_DOC
)
SET_CHECKBOX_DOC = (
    "Set checkbox or switch checked state by ref (checked true/false). "
    "Scrolls into view first with DOM fallback for off-screen controls. "
    + _ACTION_DOC
    + _CAPTURE_DOC
)
UPLOAD_FILES_DOC = (
    "Upload to a file input by ref. Scrolls into view before attaching files. "
    + _ACTION_DOC
    + _CAPTURE_DOC
)
SCREENSHOT_DOC = (
    "Save a viewport, full-page, or element PNG/JPEG under media/. "
    "Do not use unless the user explicitly asks for a screenshot."
)
CAPTCHA_OCR_DOC = (
    "Screenshot a captcha image element by ref and recognize captcha text. "
    "mode=ddddocr uses ddddocr only; mode=vlm uses the configured VLM agent "
    "(BASE_URL, API_KEY, agent.vlm_model) with ddddocr fallback on any VLM error; "
    "mode=both runs both and prefers VLM text when available. "
    "Returns ref and recognized text. Use beta=true for the newer ddddocr model; "
    "png_fix=true for transparent PNG captchas."
)
VISION_QUERY_DOC = (
    "Capture a temporary screenshot and ask the configured VLM a prompt about it. "
    "Screenshot is in-memory only (not saved to media/). "
    "Use ref for an element screenshot, or omit ref for viewport (default) or "
    "full_page=true for a full-page capture. "
    "Requires BASE_URL, API_KEY, and agent.vlm_model. "
    "Returns available=true with response on success, or available=false with "
    "message when VLM is not configured or the call fails."
)
GET_CAPTURED_RESPONSE_DOC = (
    "Get response body for a captured or registered request id. "
    "HTML responses are returned as parsed snapshot YAML when format=tree; "
    "format=raw returns the original response text. "
    "Use after capture_requests=true actions; see capture_hint on the action response. "
    "Optional session_id scopes lookup to one session; otherwise searches active sessions. "
    "Ephemeral captures are cleared on close_session; registered requests persist under registry/."
)
EVALUATE_JS_DOC = (
    "Run JavaScript in the active page context via page.evaluate. "
    "Returns JSON-serializable result and type. Optional arg is passed to the expression."
)
GET_FORM_DATA_DOC = (
    "Extract form fields from the page, including hidden inputs and csrf_token "
    "from meta[name=csrf-token]. Returns all forms plus the selected form by form_index."
)
GET_COOKIES_DOC = (
    "List cookies in the browser session. Optional urls filters cookies for those URLs."
)
SET_COOKIES_DOC = (
    "Add cookies to the browser session. Each cookie needs name, value, domain, and path."
)
HTTP_REQUEST_DOC = (
    "Send an HTTP request using the session cookie jar via context.request. "
    "Supports raw body, form data dict, or json dict. "
    "HTML responses use format=tree for snapshot YAML or format=raw for text. "
    "Prefer browser login (fill + click with capture_requests) when page JS handles encryption."
)
ENCRYPT_RSA_DOC = (
    "Encrypt plaintext for form submission. password_mode=page uses the loaded page's "
    "encryption JS; password_mode=rsa encrypts server-side with public_key (PEM or base64 SPKI)."
)
REPLAY_REQUEST_DOC = (
    "Replay a captured or registered request with optional field overrides. "
    "refresh_token reloads the referer page and updates _token / X-CSRF-TOKEN. "
    "encrypt_password re-encrypts the password field via page JS or RSA. "
    "Use register_request to persist captures for later replay."
)
GET_CAPTURED_REQUEST_HEADERS_DOC = (
    "Get request headers for a captured or registered request id. "
    "Use the id from requests returned by capture_requests=true actions. "
    "Optional session_id scopes lookup to one session; otherwise searches active sessions. "
    "Ephemeral captures are cleared on close_session; registered requests persist under registry/."
)
GET_CAPTURED_REQUEST_BODY_DOC = (
    "Get request body for a captured or registered request id. "
    "Use the id from requests returned by capture_requests=true actions. "
    "Optional session_id scopes lookup to one session; otherwise searches active sessions. "
    "Ephemeral captures are cleared on close_session; registered requests persist under registry/."
)
GET_CAPTURED_RESPONSE_HEADERS_DOC = (
    "Get response headers for a captured or registered request id. "
    "Use the id from requests returned by capture_requests=true actions. "
    "Optional session_id scopes lookup to one session; otherwise searches active sessions. "
    "Ephemeral captures are cleared on close_session; registered requests persist under registry/."
)
REGISTER_REQUEST_DOC = (
    "Persist a captured request id to registry/{request_id}/ as four files: "
    "request_header, response_header, request_body, and response (raw body bytes). "
    "Use after capture_requests=true to save a login or API call for replay_request. "
    "Registered entries are read by get_captured_* tools using only request_id."
)


@tool(description=CREATE_SESSION_DOC)
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


@tool(description=ADD_PAGE_DOC)
async def add_page(
    ctx: Context,
    session_id: str,
    url: str | None = None,
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.add_page(
        url,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=LIST_PAGES_DOC)
async def list_pages(ctx: Context, session_id: str) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.list_pages()


@tool(description=SWITCH_PAGE_DOC)
async def switch_page(ctx: Context, session_id: str, page_id: str) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.switch_page(page_id)


@tool(description=GOTO_DOC)
async def goto(
    ctx: Context,
    session_id: str,
    url: str,
    page_id: str | None = None,
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.goto(
        url,
        page_id,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=CLOSE_SESSION_DOC)
async def close_session(ctx: Context, session_id: str) -> dict:
    manager = _get_manager()
    return await manager.close_session(session_id)


@tool(description=SNAPSHOT_DOC)
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


@tool(description=GET_NODE_DOC)
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


@tool(description=GET_URL_DOC)
async def get_url(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.get_link_url(ref, page_id)


@tool(description=EVALUATE_JS_DOC)
async def evaluate_js(
    ctx: Context,
    session_id: str,
    expression: str,
    page_id: str | None = None,
    arg: Any = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.evaluate_js(expression, page_id, arg=arg)


@tool(description=GET_FORM_DATA_DOC)
async def get_form_data(
    ctx: Context,
    session_id: str,
    page_id: str | None = None,
    form_index: int = 0,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.get_form_data(page_id, form_index=form_index)


@tool(description=GET_COOKIES_DOC)
async def get_cookies(
    ctx: Context,
    session_id: str,
    urls: list[str] | None = None,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.get_cookies(urls=urls)


@tool(description=SET_COOKIES_DOC)
async def set_cookies(
    ctx: Context,
    session_id: str,
    cookies: list[dict[str, Any]],
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.set_cookies(cookies)


@tool(description=CLICK_DOC)
async def click(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    element: str | None = None,
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.click(
        ref,
        page_id,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=FILL_DOC)
async def fill(
    ctx: Context,
    session_id: str,
    ref: str,
    value: str,
    page_id: str | None = None,
    element: str | None = None,
    slowly: bool = False,
    submit: bool = False,
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.fill_field(
        ref,
        value,
        page_id,
        slowly=slowly,
        submit=submit,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=SELECT_OPTION_DOC)
async def select_option(
    ctx: Context,
    session_id: str,
    ref: str,
    values: list[str],
    page_id: str | None = None,
    element: str | None = None,
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.select_option(
        ref,
        values,
        page_id,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=SET_CHECKBOX_DOC)
async def set_checkbox(
    ctx: Context,
    session_id: str,
    ref: str,
    checked: bool,
    page_id: str | None = None,
    element: str | None = None,
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.set_checkbox(
        ref,
        checked,
        page_id,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=UPLOAD_FILES_DOC)
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
    capture_requests: bool = False,
    max_url_len: int = 80,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.upload_files(
        ref,
        page_id,
        filepath=filepath,
        filepaths=filepaths,
        text=text,
        filename=filename,
        capture_requests=capture_requests,
        max_url_len=max_url_len,
    )


@tool(description=REGISTER_REQUEST_DOC)
async def register_request(
    ctx: Context,
    request_id: str,
    session_id: str | None = None,
) -> dict:
    return await _get_manager().register_request(
        request_id,
        session_id=session_id,
    )


@tool(description=GET_CAPTURED_RESPONSE_DOC)
async def get_captured_response(
    ctx: Context,
    request_id: str,
    session_id: str | None = None,
    max_bytes: int = 32768,
    format: str = "tree",
) -> dict:
    if format not in {"tree", "raw"}:
        raise ValueError("format must be 'tree' or 'raw'")
    return await _get_manager().get_captured_response(
        request_id,
        session_id=session_id,
        max_bytes=max_bytes,
        format=format,  # type: ignore[arg-type]
    )


@tool(description=GET_CAPTURED_REQUEST_HEADERS_DOC)
async def get_captured_request_headers(
    ctx: Context,
    request_id: str,
    session_id: str | None = None,
) -> dict:
    return await _get_manager().get_captured_request_headers(
        request_id,
        session_id=session_id,
    )


@tool(description=GET_CAPTURED_REQUEST_BODY_DOC)
async def get_captured_request_body(
    ctx: Context,
    request_id: str,
    session_id: str | None = None,
    max_bytes: int = 32768,
) -> dict:
    return await _get_manager().get_captured_request_body(
        request_id,
        session_id=session_id,
        max_bytes=max_bytes,
    )


@tool(description=GET_CAPTURED_RESPONSE_HEADERS_DOC)
async def get_captured_response_headers(
    ctx: Context,
    request_id: str,
    session_id: str | None = None,
) -> dict:
    return await _get_manager().get_captured_response_headers(
        request_id,
        session_id=session_id,
    )


@tool(description=HTTP_REQUEST_DOC)
async def http_request(
    ctx: Context,
    session_id: str,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    data: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    content_type: str | None = None,
    max_bytes: int = 32768,
    format: str = "tree",
) -> dict:
    if format not in {"tree", "raw"}:
        raise ValueError("format must be 'tree' or 'raw'")
    session = _get_manager().get_session(session_id)
    return await session.http_request(
        method=method,
        url=url,
        headers=headers,
        body=body,
        data=data,
        json_body=json,
        content_type=content_type,
        max_bytes=max_bytes,
        format=format,  # type: ignore[arg-type]
    )


@tool(description=ENCRYPT_RSA_DOC)
async def encrypt_rsa(
    ctx: Context,
    plaintext: str,
    public_key: str | None = None,
    session_id: str | None = None,
    page_id: str | None = None,
    password_mode: str = "page",
    expression: str | None = None,
) -> dict:
    if password_mode not in {"page", "rsa"}:
        raise ValueError("password_mode must be 'page' or 'rsa'")
    if session_id is None:
        raise ValueError("session_id is required")
    session = _get_manager().get_session(session_id)
    return await session.encrypt_rsa(
        plaintext,
        public_key=public_key,
        page_id=page_id,
        password_mode=password_mode,  # type: ignore[arg-type]
        expression=expression,
    )


@tool(description=REPLAY_REQUEST_DOC)
async def replay_request(
    ctx: Context,
    session_id: str,
    request_id: str,
    overrides: dict[str, str] | None = None,
    refresh_token: bool = False,
    refresh_url: str | None = None,
    encrypt_password: bool = False,
    password_mode: str = "page",
    public_key: str | None = None,
    expression: str | None = None,
    max_bytes: int = 32768,
    format: str = "tree",
) -> dict:
    if password_mode not in {"page", "rsa"}:
        raise ValueError("password_mode must be 'page' or 'rsa'")
    if format not in {"tree", "raw"}:
        raise ValueError("format must be 'tree' or 'raw'")
    return await _get_manager().replay_request(
        session_id,
        request_id,
        overrides=overrides,
        refresh_token=refresh_token,
        refresh_url=refresh_url,
        encrypt_password=encrypt_password,
        password_mode=password_mode,  # type: ignore[arg-type]
        public_key=public_key,
        expression=expression,
        max_bytes=max_bytes,
        format=format,  # type: ignore[arg-type]
    )


@tool(description=SCREENSHOT_DOC)
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


@tool(description=CAPTCHA_OCR_DOC)
async def captcha_ocr(
    ctx: Context,
    session_id: str,
    ref: str,
    page_id: str | None = None,
    mode: str = "ddddocr",
    beta: bool = False,
    png_fix: bool = False,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.captcha_ocr(
        ref,
        page_id,
        mode=mode,  # type: ignore[arg-type]
        beta=beta,
        png_fix=png_fix,
    )


@tool(description=VISION_QUERY_DOC)
async def vision_query(
    ctx: Context,
    session_id: str,
    prompt: str,
    page_id: str | None = None,
    ref: str | None = None,
    full_page: bool = False,
) -> dict:
    session = _get_manager().get_session(session_id)
    return await session.vision_query(
        prompt,
        page_id,
        ref=ref,
        full_page=full_page,
    )


def main() -> None:
    from webgent.config import apply_browser_env, get_settings

    apply_browser_env()
    server = get_settings().server
    mcp.run(
        transport=server.transport,
        host=server.host,
        port=server.port,
    )


if __name__ == "__main__":
    main()
