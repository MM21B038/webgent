"""Smoke test for browser manager and MCP tools."""

import asyncio
import tempfile
from pathlib import Path

from fastmcp import Client

from webgent.browser import BrowserManager
from webgent.snapshot import (
    compress_snapshot,
    extract_ref_from_line,
    normalize_ref,
    parse_node_headline,
    to_interactive_snapshot,
    truncate_url,
)

SERVER_PATH = Path(__file__).resolve().parent.parent / "webgent" / "server.py"

LONG_LINK_URL = "https://example.com/" + ("segment/" * 20) + "target?tracking=abcdef"
LINKS_PAGE_URL = (
    "data:text/html,<html><body>"
    "<nav aria-label='Links'>"
    f"<a href='{LONG_LINK_URL}'>Long link</a>"
    "<a href='/short'>Short link</a>"
    "</nav>"
    "<main aria-label='Main'><p>Content</p></main>"
    "</body></html>"
)

FORM_PAGE_URL = (
    "data:text/html,<html><body><form>"
    "<label>Email<input aria-label='Email'></label>"
    "<label>Country<select aria-label='Country'>"
    "<option value=''>Choose</option>"
    "<option value='us'>United States</option>"
    "<option value='uk'>United Kingdom</option>"
    "</select></label>"
    "<label><input type='checkbox' aria-label='Subscribe'>Subscribe</label>"
    "<label><input type='radio' name='plan' value='free' aria-label='Free plan'>Free</label>"
    "<label><input type='radio' name='plan' value='pro' aria-label='Pro plan'>Pro</label>"
    "<button>Submit</button>"
    "</form></body></html>"
)

UPLOAD_PAGE_URL = (
    "data:text/html,<html><body>"
    "<label>Upload<input type='file' aria-label='Upload file'></label>"
    "</body></html>"
)

NAV_PAGE_URL = (
    "data:text/html,<html><body>"
    "<a href='https://example.org/' aria-label='Navigate away'>Navigate away</a>"
    "</body></html>"
)

NEW_TAB_PAGE_URL = (
    "data:text/html,<html><body>"
    "<a href='https://example.org/' target='_blank' aria-label='Open new tab'>"
    "Open new tab"
    "</a>"
    "</body></html>"
)

DIALOG_PAGE_URL = (
    "data:text/html,<html><body>"
    "<button aria-label='Open dialog'>Open dialog</button>"
    "<dialog><p>Dialog content</p></dialog>"
    "<script>"
    "document.querySelector('button').onclick=function(){"
    "document.querySelector('dialog').showModal();};"
    "</script>"
    "</body></html>"
)

OVERLAY_SELECT_PAGE_URL = (
    "data:text/html,<html><body>"
    "<div style='position:relative;display:inline-block'>"
    "<select aria-label='Sort' style='position:absolute;inset:0;width:100%;height:100%;"
    "opacity:0;z-index:1'>"
    "<option>Featured</option><option>Price: Low to High</option>"
    "<option>Price: High to Low</option>"
    "</select>"
    "<span style='position:relative;z-index:2;padding:8px;border:1px solid #ccc;"
    "background:#fff'>Featured</span>"
    "</div></body></html>"
)

AMAZON_SORT_PAGE_URL = (
    "data:text/html,<html><body>"
    "<span class='a-button a-button-dropdown'>"
    "<span class='a-dropdown-prompt'>Featured</span>"
    "<select id='sort' aria-label='Sort by:' role='combobox' class='a-native-dropdown'>"
    "<option value='relevance'>Featured</option>"
    "<option value='price-asc'>Price: Low to High</option>"
    "<option value='price-desc'>Price: High to Low</option>"
    "</select>"
    "</span>"
    "</body></html>"
)

FULL_CONTROLS_PAGE_URL = (
    "data:text/html,<html><body><form>"
    "<label>Email<input aria-label='Email'></label>"
    "<label><input type='checkbox' aria-label='Subscribe'>Subscribe</label>"
    "<label><input type='radio' name='plan' aria-label='Pro plan'>Pro</label>"
    "<input type='file' aria-label='Upload file'>"
    "<input type='range' aria-label='Volume' min='0' max='100' value='50'>"
    "<input type='checkbox' role='switch' aria-label='Notifications'>"
    "<input type='number' aria-label='Quantity' value='1' min='0' max='99'>"
    "<div role='tablist'>"
    "<button role='tab' aria-label='Overview' aria-selected='true'>Overview</button>"
    "<button role='tab' aria-label='Details'>Details</button>"
    "</div>"
    "<details><summary>More options</summary><p>Extra</p></details>"
    "<img src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7' "
    "alt='Logo'>"
    "</form></body></html>"
)

FETCH_PAGE_URL = (
    "data:text/html,<html><body>"
    "<button aria-label='Fetch data'>Fetch data</button>"
    "<script>"
    "document.querySelector('button').onclick=function(){"
    "fetch('https://example.org/');};"
    "</script>"
    "</body></html>"
)

POST_FETCH_PAGE_URL = (
    "data:text/html,<html><body>"
    "<button aria-label='Post data'>Post data</button>"
    "<script>"
    "document.querySelector('button').onclick=function(){"
    "fetch('https://example.org/',{method:'POST',"
    "headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({hello:'world'})});};"
    "</script>"
    "</body></html>"
)

FORM_UPLOAD_POST_PAGE_URL = (
    "data:text/html,<html><body>"
    "<form action='https://httpbin.org/post' method='POST' "
    "enctype='multipart/form-data'>"
    "<input name='field1' value='hello'>"
    "<input type='file' name='file'>"
    "<button type='submit'>Upload submit</button>"
    "</form></body></html>"
)

FORM_DATA_PAGE_URL = (
    "data:text/html,<html><head>"
    "<meta name='csrf-token' content='csrf-abc'>"
    "</head><body>"
    "<form action='/submit' method='POST'>"
    "<input type='hidden' name='_token' value='tok-abc'>"
    "<input name='email' value=''>"
    "<input name='captcha' value=''>"
    "<button type='submit'>Send</button>"
    "</form></body></html>"
)

URLENCODED_FORM_PAGE_URL = (
    "data:text/html,<html><body>"
    "<form action='https://httpbingo.org/post' method='POST'>"
    "<input type='hidden' name='_token' value='tok123'>"
    "<input name='field1' value='hello'>"
    "<button type='submit'>Submit encoded</button>"
    "</form></body></html>"
)

ENCRYPT_PAGE_URL = (
    "data:text/html,<html><body>"
    "<script>window.encryptPassword=function(pw){return btoa(pw);};</script>"
    "<input type='password' name='password'>"
    "</body></html>"
)

SEARCH_TYPE_PAGE_URL = (
    "data:text/html,<html><body>"
    "<input aria-label='Search Amazon.in'>"
    "<div role='dialog' hidden id='suggestions'><button>Suggestion</button></div>"
    "<script>"
    "const input=document.querySelector('input');"
    "const suggestions=document.getElementById('suggestions');"
    "input.addEventListener('input',()=>{"
    "history.replaceState({},'',location.pathname+'?k='+encodeURIComponent(input.value));"
    "document.title='Search: '+input.value;"
    "suggestions.hidden=!input.value;"
    "});"
    "</script>"
    "</body></html>"
)

CAPTCHA_PAGE_URL = (
    "data:text/html,<html><body>"
    "<img alt='Captcha' id='cap'>"
    "<script>"
    "const c=document.createElement('canvas');"
    "c.width=120;c.height=40;"
    "const x=c.getContext('2d');"
    "x.fillStyle='#fff';x.fillRect(0,0,120,40);"
    "x.fillStyle='#000';x.font='bold 28px monospace';"
    "x.fillText('8K4M',15,30);"
    "document.getElementById('cap').src=c.toDataURL('image/png');"
    "</script>"
    "</body></html>"
)


def find_ref(snapshot_text: str, *keywords: str) -> str | None:
    for line in snapshot_text.splitlines():
        lower = line.lower()
        ref = extract_ref_from_line(line)
        if ref is None:
            continue
        if all(keyword in lower for keyword in keywords):
            return ref
    return None


def test_compress_snapshot_helpers() -> None:
    raw = (
        '- link "Example" [ref=e1]:\n'
        f"  - /url: {LONG_LINK_URL}\n"
        '- button "Go" [ref=e2]'
    )
    stripped = compress_snapshot(raw)
    assert "/url:" not in stripped
    assert "[ref=e1]" in stripped

    truncated = compress_snapshot(raw, include_urls=True, max_url_len=40)
    assert "/url:" in truncated
    assert LONG_LINK_URL not in truncated
    assert truncate_url(LONG_LINK_URL, 40).endswith("…")
    print("compress snapshot helpers test passed")


def test_interactive_snapshot_helpers() -> None:
    tree = (
        '- generic [ref=e2]:\n'
        '  - navigation "Shortcuts menu" [ref=e3]:\n'
        '    - heading "Skip to" [level=2] [ref=e4]\n'
        '    - link "main content" [ref=e7] [cursor=pointer]:\n'
        '  - searchbox "Search Amazon.in" [ref=e90]\n'
        '  - button "Go" [ref=e91] [cursor=pointer]:'
    )
    interactive = to_interactive_snapshot(tree)
    assert interactive.splitlines() == [
        '- navigation "Shortcuts menu":',
        '  - [e7] link "main content" [cursor=pointer]',
        '- [e90] searchbox "Search Amazon.in"',
        '- [e91] button "Go" [cursor=pointer]',
    ]
    assert find_ref(interactive, "searchbox", "search") == "e90"
    assert find_ref(interactive, "link", "main", "content") == "e7"

    select_tree = (
        '- combobox "Country" [ref=e4]:\n'
        '  - option "Choose" [selected]\n'
        '  - option "United States"\n'
        '  - option "United Kingdom"'
    )
    select_interactive = to_interactive_snapshot(select_tree)
    assert select_interactive.splitlines() == [
        '- [e4] combobox "Country" options="Choose" [selected] | "United States" | "United Kingdom"',
    ]

    quoted_options_tree = (
        '- combobox "Sort by:" [ref=e3]:\n'
        '  - option "Featured" [selected]\n'
        '  - \'option "Price: Low to High"\'\n'
        '  - \'option "Price: High to Low"\''
    )
    quoted_interactive = to_interactive_snapshot(quoted_options_tree)
    assert "Price: Low to High" in quoted_interactive
    assert "Price: High to Low" in quoted_interactive

    pointer_generic_tree = (
        '- generic [ref=e20] [cursor=pointer]:\n'
        '  - text: Custom action'
    )
    pointer_interactive = to_interactive_snapshot(pointer_generic_tree)
    assert "- [e20] generic [cursor=pointer]" in pointer_interactive

    img_tree = (
        '- generic [ref=e1]:\n'
        '  - img "Product photo" [ref=e2] [cursor=pointer]\n'
        '  - button "Buy" [ref=e3]'
    )
    img_interactive = to_interactive_snapshot(img_tree)
    assert img_interactive.splitlines() == [
        '- generic:',
        '  - [e2] img "Product photo" [cursor=pointer]',
        '  - [e3] button "Buy"',
    ]

    tree_headline = parse_node_headline('- file "Upload file" [ref=e3]')
    assert tree_headline == {
        "ref": "e3",
        "role": "file",
        "name": "Upload file",
        "states": [],
    }
    compact_headline = parse_node_headline('- [e4] checkbox "Subscribe" [checked]')
    assert compact_headline == {
        "ref": "e4",
        "role": "checkbox",
        "name": "Subscribe",
        "states": ["checked"],
    }

    frame_tree = (
        '- generic [ref=e1]:\n'
        '  - iframe [ref=e2]:\n'
        '    - generic [ref=f1e1]:\n'
        '      - button "Close ad" [ref=f1e2] [cursor=pointer]'
    )
    frame_interactive = to_interactive_snapshot(frame_tree)
    assert find_ref(frame_interactive, "button", "close") == "f1e2"
    assert "- [f1e2] button \"Close ad\" [cursor=pointer]" in frame_interactive

    assert normalize_ref("e12") == "e12"
    assert normalize_ref("f56e8") == "f56e8"
    assert normalize_ref("[ref=f3e4]") == "f3e4"

    frame_headline = parse_node_headline('- button "Close ad" [ref=f1e2] [cursor=pointer]')
    assert frame_headline["ref"] == "f1e2"
    assert frame_headline["role"] == "button"
    assert frame_headline["name"] == "Close ad"

    print("interactive snapshot helpers test passed")


async def test_snapshot_role_normalization() -> None:
    from playwright.async_api import async_playwright

    from webgent.browser import BrowserManager
    from webgent.snapshot import capture_page_snapshot

    html = (
        "<input type='file' aria-label='Upload file'>"
        "<input type='checkbox' aria-label='Subscribe'>"
        "<input type='radio' name='plan' aria-label='Pro plan'>"
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(f"<html><body>{html}</body></html>")
        tree = await capture_page_snapshot(page, snapshot_format="tree")
        interactive = await capture_page_snapshot(page, snapshot_format="interactive")
        file_ref = find_ref(interactive, "file", "upload")
        assert file_ref is not None
        checkbox_ref = find_ref(interactive, "checkbox", "subscribe")
        radio_ref = find_ref(interactive, "radio", "pro")
        await browser.close()

    assert find_ref(interactive, "file", "upload") is not None
    assert find_ref(interactive, "checkbox", "subscribe") is not None
    assert find_ref(interactive, "radio", "pro") is not None
    assert 'file "Upload file"' in tree
    assert 'checkbox "Subscribe"' in tree
    assert 'radio "Pro plan"' in tree
    assert 'button "Upload file"' not in tree

    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "role-normalization-test",
            initial_url=f"data:text/html,<html><body>{html}</body></html>",
        )
        session = manager.get_session(session_info["session_id"])
        file_node = await session.get_node(file_ref)
        checkbox_node = await session.get_node(checkbox_ref)
        radio_node = await session.get_node(radio_ref)
        assert file_node["role"] == "file"
        assert checkbox_node["role"] == "checkbox"
        assert radio_node["role"] == "radio"
        assert 'file "Upload file"' in file_node["subtree"]
        await manager.close_session(session_info["session_id"])
    finally:
        await manager.stop()

    print("snapshot role normalization test passed")


async def test_cross_frame_refs() -> None:
    import urllib.parse

    from playwright.async_api import async_playwright

    from webgent.browser import BrowserManager
    from webgent.snapshot import capture_page_snapshot, click_ref

    iframe_html = (
        "<html><body><button aria-label='Close ad'>X</button></body></html>"
    )
    outer_html = (
        "<html><body>"
        f"<iframe srcdoc=\"{iframe_html.replace('\"', '&quot;')}\"></iframe>"
        "</body></html>"
    )
    page_url = "data:text/html," + urllib.parse.quote(outer_html)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(outer_html, wait_until="domcontentloaded")
        await page.wait_for_timeout(300)

        tree = await capture_page_snapshot(page, snapshot_format="tree")
        interactive = await capture_page_snapshot(page, snapshot_format="interactive")
        close_ref = find_ref(interactive, "button", "close")
        assert close_ref is not None, f"missing close button in interactables:\n{interactive}"
        assert normalize_ref(close_ref) == close_ref
        assert "Close ad" in tree

        await click_ref(page, close_ref)
        await browser.close()

    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "cross-frame-ref-test",
            initial_url=page_url,
        )
        session = manager.get_session(session_info["session_id"])
        await asyncio.sleep(0.3)

        interactables = await session.page_interactables()
        close_ref = find_ref(interactables["interactables"], "button", "close")
        assert close_ref is not None, interactables["interactables"]

        clicked = await session.click(close_ref)
        assert clicked["ref"] == close_ref

        node = await session.get_node(close_ref)
        assert node["role"] == "button"
        assert node["name"] == "Close ad"

        await manager.close_session(session_info["session_id"])
    finally:
        await manager.stop()

    print("cross frame refs test passed")


async def test_vision_query() -> None:
    import os
    from unittest.mock import patch

    from webgent.vlm import VLM_UNAVAILABLE_MESSAGE

    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "vision-query-test",
            initial_url=(
                "data:text/html,<html><body>"
                '<img alt="Vision Test" '
                'src="data:image/gif;base64,'
                "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
                '">'
                "</body></html>"
            ),
        )
        session = manager.get_session(session_info["session_id"])

        with patch.dict(os.environ, {"BASE_URL": "", "API_KEY": ""}, clear=False):
            unavailable = await session.vision_query("What text is on this page?")
        assert unavailable["available"] is False
        assert unavailable["message"] == VLM_UNAVAILABLE_MESSAGE
        assert unavailable["mode"] == "viewport"
        assert unavailable["prompt"] == "What text is on this page?"
        assert unavailable["error"]

        with patch("webgent.browser.query_vlm", return_value="Vision Test"):
            success = await session.vision_query("What alt text is shown?")
        assert success["available"] is True
        assert success["response"] == "Vision Test"
        assert success["mode"] == "viewport"

        interactables = await session.page_interactables()
        img_ref = find_ref(interactables["interactables"], "img", "vision test")
        assert img_ref is not None
        with patch("webgent.browser.query_vlm", return_value="Vision Test"):
            element_result = await session.vision_query(
                "Describe this element",
                ref=img_ref,
            )
        assert element_result["available"] is True
        assert element_result["mode"] == "element"
        assert element_result["ref"] == img_ref

        await manager.close_session(session_info["session_id"])
    finally:
        await manager.stop()

    print("vision query test passed")


async def test_browser_manager() -> None:
    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "test-profile",
            initial_url="https://example.com",
        )
        session_id = session_info["session_id"]
        page_id = session_info["page_id"]
        assert "example.com" in session_info["url"]

        session = manager.get_session(session_id)
        pages = await session.list_pages()
        assert len(pages["pages"]) == 1

        added = await session.add_page("https://example.org")
        assert added["is_active"] is True

        pages = await session.list_pages()
        assert len(pages["pages"]) == 2

        switched = await session.switch_page(page_id)
        assert switched["active_page_id"] == page_id

        navigated = await session.goto("https://example.net")
        assert "example.net" in navigated["url"]

        page_snapshot = await session.page_snapshot()
        assert "snapshot" in page_snapshot
        assert isinstance(page_snapshot["snapshot"], str)
        assert len(page_snapshot["snapshot"]) > 0
        assert "[ref=" in page_snapshot["snapshot"]

        interactables = await session.page_interactables()
        assert "interactables" in interactables
        assert isinstance(interactables["interactables"], str)
        assert len(interactables["interactables"]) > 0
        interactables_text = interactables["interactables"]
        assert interactables_text.splitlines()[0].startswith("- ")
        assert any(
            extract_ref_from_line(line) is not None
            for line in interactables_text.splitlines()
        )

        screenshot_result = await session.take_screenshot()
        assert screenshot_result["mode"] == "viewport"
        assert screenshot_result["path"].endswith(".png")
        assert Path(screenshot_result["path"]).exists()
        assert Path(screenshot_result["path"]).parent.name == "media"

        full_page_result = await session.take_screenshot(full_page=True)
        assert full_page_result["mode"] == "full_page"
        assert Path(full_page_result["path"]).exists()

        await session.goto(CAPTCHA_PAGE_URL)
        captcha_interactables = await session.page_interactables()
        captcha_ref = find_ref(captcha_interactables["interactables"], "img", "captcha")
        assert captcha_ref is not None
        captcha_result = await session.captcha_ocr(captcha_ref)
        assert captcha_result["ref"] == captcha_ref
        assert isinstance(captcha_result["text"], str)
        assert len(captcha_result["text"]) > 0

        from unittest.mock import patch

        with patch("webgent.browser.query_vlm", return_value="AB12"):
            vision_result = await session.vision_query(
                "What captcha text is shown?",
                ref=captcha_ref,
            )
        assert vision_result["available"] is True
        assert vision_result["response"] == "AB12"
        assert vision_result["mode"] == "element"
        assert vision_result["ref"] == captcha_ref

        await session.goto(
            "data:text/html,<html><body>"
            '<img alt="Logo" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">'
            "</body></html>"
        )
        img_interactables = await session.page_interactables()
        img_ref = find_ref(img_interactables["interactables"], "img", "logo")
        assert img_ref is not None

        await session.goto(FORM_PAGE_URL)
        form_interactables = await session.page_interactables()
        interactables_text = form_interactables["interactables"]
        email_ref = find_ref(interactables_text, "textbox", "email")
        country_ref = find_ref(interactables_text, "combobox", "country")
        checkbox_ref = find_ref(interactables_text, "checkbox", "subscribe")
        radio_ref = find_ref(interactables_text, "radio", "pro")
        assert email_ref and country_ref and checkbox_ref and radio_ref
        assert any("checkbox" in line for line in interactables_text.splitlines())
        assert any("radio" in line for line in interactables_text.splitlines())
        country_line = next(
            line
            for line in form_interactables["interactables"].splitlines()
            if country_ref in line
        )
        assert "options=" in country_line
        assert "United States" in country_line
        assert "United Kingdom" in country_line

        node = await session.get_node(email_ref)
        assert node["ref"] == email_ref
        assert node["format"] == "tree"
        assert "subtree" in node
        assert node["value"] in (None, "user@example.com", "")

        filled = await session.fill_field(email_ref, "user@example.com")
        assert filled["value"] == "user@example.com"
        assert filled["ref"] == email_ref
        assert "snapshot" not in filled
        assert "url" in filled
        assert "title" in filled
        selected = await session.select_option(country_ref, ["United States"])
        assert selected["values"] == ["United States"]
        checked = await session.set_checkbox(checkbox_ref, True)
        assert checked["checked"] is True
        radio = await session.select_radio(radio_ref)
        assert radio["checked"] is True

        await session.goto(UPLOAD_PAGE_URL)
        upload_interactables = await session.page_interactables()
        upload_ref = find_ref(upload_interactables["interactables"], "file", "upload")
        if upload_ref is None:
            upload_ref = find_ref(upload_interactables["interactables"], "button", "upload")
        if upload_ref is None:
            upload_ref = find_ref(upload_interactables["interactables"], "input", "upload")
        assert upload_ref is not None

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            delete=False,
        ) as handle:
            handle.write("from disk")
            disk_path = handle.name

        try:
            uploaded = await session.upload_files(
                upload_ref,
                filepath=str(Path(disk_path).resolve()),
            )
            assert uploaded["source"] == "path"
            assert uploaded["files"] == [Path(disk_path).name]
        finally:
            Path(disk_path).unlink(missing_ok=True)

        await session.goto(UPLOAD_PAGE_URL)
        upload_interactables = await session.page_interactables()
        upload_ref = find_ref(upload_interactables["interactables"], "file", "upload")
        if upload_ref is None:
            upload_ref = find_ref(upload_interactables["interactables"], "button", "upload")
        if upload_ref is None:
            upload_ref = find_ref(upload_interactables["interactables"], "input", "upload")
        inline_upload = await session.upload_files(
            upload_ref,
            text="hello upload",
            filename="hello.txt",
        )
        assert inline_upload["source"] == "inline"
        assert inline_upload["files"] == ["hello.txt"]

        await session.goto(LINKS_PAGE_URL)
        links_interactables = await session.page_interactables()
        assert links_interactables["scope_ref"] is None
        link_ref = find_ref(links_interactables["interactables"], "long")
        assert link_ref is not None

        links_with_urls = await session.page_snapshot(
            include_urls=True,
            max_url_len=40,
        )
        assert "/url:" in links_with_urls["snapshot"]
        assert LONG_LINK_URL not in links_with_urls["snapshot"]

        full_url = await session.get_link_url(link_ref)
        assert full_url["url"] == LONG_LINK_URL

        nav_ref = find_ref(links_interactables["interactables"], "long")
        subtree = await session.page_interactables(ref=nav_ref)
        assert subtree["scope_ref"] == nav_ref
        assert len(subtree["interactables"]) <= len(links_interactables["interactables"])

        second_page_id = added["page_id"]
        await session.delete_page(second_page_id)
        pages = await session.list_pages()
        assert len(pages["pages"]) == 1

        closed = await manager.close_session(session_id)
        assert closed["closed"] is True
        print("browser manager smoke test passed")
    finally:
        await manager.stop()


async def test_action_metadata_only() -> None:
    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "action-metadata-test",
            initial_url="about:blank",
        )
        session = manager.get_session(session_info["session_id"])

        await session.goto(FORM_PAGE_URL)
        interactables = await session.page_interactables()
        email_ref = find_ref(interactables["interactables"], "textbox", "email")
        assert email_ref

        filled = await session.fill_field(email_ref, "scoped@example.com")
        assert filled["ref"] == email_ref
        assert filled["value"] == "scoped@example.com"
        assert "snapshot" not in filled
        assert "snapshot_mode" not in filled
        assert "major_change" not in filled

        await session.goto(NAV_PAGE_URL)
        nav_interactables = await session.page_interactables()
        link_ref = find_ref(nav_interactables["interactables"], "navigate")
        assert link_ref is not None
        before_url = nav_interactables["url"]
        navigated = await session.click(link_ref)
        assert navigated["ref"] == link_ref
        assert "snapshot" not in navigated
        assert navigated["url"] != before_url
        assert navigated["opened_new_page"] is False
        assert navigated["page_id"] == navigated["active_page_id"]

        await session.goto(NEW_TAB_PAGE_URL)
        tab_page_interactables = await session.page_interactables()
        before_page_id = tab_page_interactables["page_id"]
        new_tab_ref = find_ref(tab_page_interactables["interactables"], "open", "new", "tab")
        assert new_tab_ref is not None
        opened = await session.click(new_tab_ref)
        assert opened["opened_new_page"] is True
        assert opened["previous_page_id"] == before_page_id
        assert opened["page_id"] == opened["active_page_id"]
        assert opened["page_id"] != before_page_id
        assert "example.org" in opened["url"]
        pages = await session.list_pages()
        assert len(pages["pages"]) == 2

        await session.goto(DIALOG_PAGE_URL)
        dialog_interactables = await session.page_interactables()
        button_ref = find_ref(
            dialog_interactables["interactables"], "button", "open", "dialog"
        )
        assert button_ref is not None
        opened = await session.click(button_ref)
        assert opened["ref"] == button_ref
        assert "snapshot" not in opened

        await session.goto(OVERLAY_SELECT_PAGE_URL)
        overlay_interactables = await session.page_interactables()
        sort_ref = find_ref(overlay_interactables["interactables"], "combobox", "sort")
        assert sort_ref is not None
        sort_line = next(
            line
            for line in overlay_interactables["interactables"].splitlines()
            if sort_ref in line
        )
        assert "Price: Low to High" in sort_line
        assert "Price: High to Low" in sort_line
        clicked_sort = await session.click(sort_ref)
        assert clicked_sort["ref"] == sort_ref

        await session.goto(AMAZON_SORT_PAGE_URL)
        amazon_interactables = await session.page_interactables()
        amazon_sort_ref = find_ref(
            amazon_interactables["interactables"], "combobox", "sort"
        )
        assert amazon_sort_ref is not None
        amazon_sort_line = next(
            line
            for line in amazon_interactables["interactables"].splitlines()
            if amazon_sort_ref in line
        )
        assert "Price: Low to High" in amazon_sort_line
        assert "Price: High to Low" in amazon_sort_line

        assert "Price: High to Low" in amazon_sort_line

        await session.goto(FULL_CONTROLS_PAGE_URL)
        controls = await session.page_interactables()
        controls_text = controls["interactables"]
        for role_keyword in (
            "textbox",
            "checkbox",
            "radio",
            "file",
            "slider",
            "img",
        ):
            assert any(role_keyword in line for line in controls_text.splitlines()), (
                f"missing {role_keyword} in interactables:\n{controls_text}"
            )
        assert any("More options" in line for line in controls_text.splitlines())

        slider_ref = find_ref(controls_text, "slider", "volume")
        switch_ref = find_ref(controls_text, "switch", "notifications")
        spinbutton_ref = find_ref(controls_text, "spinbutton", "quantity")
        tab_ref = find_ref(controls_text, "tab", "details")
        assert slider_ref and switch_ref and spinbutton_ref and tab_ref

        slider_result = await session.set_slider(slider_ref, 75)
        assert slider_result["value"] == "75"
        switch_result = await session.set_switch(switch_ref, True)
        assert switch_result["checked"] is True
        spin_result = await session.set_spinbutton(spinbutton_ref, 5)
        assert spin_result["value"] == "5"
        tab_result = await session.select_tab(tab_ref)
        assert tab_result["ref"] == tab_ref

        await session.goto(SEARCH_TYPE_PAGE_URL)
        search_interactables = await session.page_interactables(depth=3)
        search_ref = find_ref(search_interactables["interactables"], "search")
        assert search_ref is not None
        typed = await session.type_text(search_ref, "laptop")
        assert typed["ref"] == search_ref
        assert typed["text"] == "laptop"
        assert "snapshot" not in typed

        await manager.close_session(session_info["session_id"])
        print("action metadata only smoke test passed")
    finally:
        await manager.stop()


READONLY_INPUT_PAGE_URL = (
    "data:text/html,<html><body>"
    "<input aria-label='Locked field' readonly value='fixed'>"
    "</body></html>"
)

JQUERY_DATEPICKER_PAGE_URL = (
    "data:text/html,<html><body>"
    "<input aria-label='Date of birth' name='date_of_birth' readonly "
    "class='hasDatepicker' value=''>"
    "<script>"
    "window.jQuery=function(el){const node=typeof el==='string'"
    "?document.querySelector(el):el.nodeType?el:el[0];return{"
    "datepicker(action,date){if(action==='setDate'&&date instanceof Date){"
    "const d=String(date.getDate()).padStart(2,'0');"
    "const m=String(date.getMonth()+1).padStart(2,'0');"
    "const y=date.getFullYear();node.value=d+'-'+m+'-'+y;"
    "node.dispatchEvent(new Event('change',{bubbles:true}));}}};};"
    "jQuery.fn={datepicker:function(){return this;}};"
    "jQuery.data=function(){return{settings:{dateFormat:'dd-mm-yy'}}};"
    "</script></body></html>"
)


async def test_fill_verifies_dom_value() -> None:
    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "fill-verify-test",
            initial_url=FORM_PAGE_URL,
        )
        session = manager.get_session(session_info["session_id"])
        interactables = await session.page_interactables()
        email_ref = find_ref(interactables["interactables"], "textbox", "email")
        assert email_ref

        filled = await session.fill_field(email_ref, "verified@example.com")
        assert filled["value"] == "verified@example.com"
        node = await session.get_node(email_ref)
        assert node["value"] == "verified@example.com"

        await session.goto(READONLY_INPUT_PAGE_URL)
        readonly_interactables = await session.page_interactables()
        locked_ref = find_ref(readonly_interactables["interactables"], "locked")
        assert locked_ref is not None
        try:
            await session.fill_field(locked_ref, "should-fail")
            raise AssertionError("fill should fail on readonly input")
        except ValueError as exc:
            assert "readonly" in str(exc).lower()

        await session.goto(JQUERY_DATEPICKER_PAGE_URL)
        date_interactables = await session.page_interactables()
        dob_ref = find_ref(date_interactables["interactables"], "date", "birth")
        assert dob_ref is not None
        filled_dob = await session.fill_field(dob_ref, "15-06-1990")
        assert filled_dob["value"] == "15-06-1990"
        dob_node = await session.get_node(dob_ref)
        assert dob_node["value"] == "15-06-1990"

        await manager.close_session(session_info["session_id"])
        print("fill verifies dom value test passed")
    finally:
        await manager.stop()


def assert_request_summaries(requests: list[dict]) -> str:
    assert requests, "expected at least one captured request"
    for entry in requests:
        assert "id" in entry
        assert "method" in entry
        assert "resource_type" in entry
        assert "url" in entry
        assert "status" in entry
        assert "body" not in entry
        assert "headers" not in entry
    return requests[0]["id"]


async def test_network_capture() -> None:
    manager = BrowserManager()
    await manager.start()
    try:
        session_info = await manager.create_session(
            "network-capture-test",
            initial_url="about:blank",
        )
        session = manager.get_session(session_info["session_id"])

        navigated = await session.goto("https://example.com")
        assert "requests" not in navigated

        captured = await session.goto(
            "https://example.org",
            capture_requests=True,
        )
        assert "requests" in captured
        request_id = assert_request_summaries(captured["requests"])

        req_headers = await session.get_captured_request_headers(request_id)
        assert req_headers["request_id"] == request_id
        assert isinstance(req_headers["headers"], dict)
        assert req_headers["headers"]

        req_body = await session.get_captured_request_body(request_id)
        assert req_body["request_id"] == request_id
        assert req_body["method"] == "GET"
        assert req_body["body"] == ""
        assert req_body["size"] == 0

        resp_headers = await session.get_captured_response_headers(request_id)
        assert resp_headers["request_id"] == request_id
        assert resp_headers["status"] is not None
        assert isinstance(resp_headers["headers"], dict)

        response = await session.get_captured_response(request_id)
        assert response["request_id"] == request_id
        assert response["status"] is not None
        assert response["body"]
        assert response["size"] > 0
        assert response["format"] == "tree"
        assert "<html" not in response["body"].lower()
        assert "[ref=" in response["body"]

        await session.goto(FETCH_PAGE_URL)
        interactables = await session.page_interactables()
        fetch_ref = find_ref(interactables["interactables"], "button", "fetch data")
        assert fetch_ref is not None
        clicked = await session.click(fetch_ref, capture_requests=True)
        xhr_requests = [
            entry
            for entry in clicked.get("requests", [])
            if entry["resource_type"] in {"fetch", "xhr"}
        ]
        assert xhr_requests, "expected fetch/xhr request after click"
        assert xhr_requests[0]["method"] == "GET"

        await session.goto(POST_FETCH_PAGE_URL)
        post_interactables = await session.page_interactables()
        post_ref = find_ref(post_interactables["interactables"], "button", "post data")
        assert post_ref is not None
        posted = await session.click(post_ref, capture_requests=True)
        post_requests = [
            entry
            for entry in posted.get("requests", [])
            if entry["resource_type"] in {"fetch", "xhr"} and entry["method"] == "POST"
        ]
        assert post_requests, "expected POST fetch/xhr request after click"
        post_request_id = post_requests[0]["id"]
        post_body = await session.get_captured_request_body(post_request_id)
        assert post_body["request_id"] == post_request_id
        assert post_body["method"] == "POST"
        assert "application/json" in post_body["content_type"]
        assert "hello" in post_body["body"]
        assert post_body["size"] > 0

        await session.goto(FORM_UPLOAD_POST_PAGE_URL)
        upload_interactables = await session.page_interactables()
        file_ref = find_ref(upload_interactables["interactables"], "file", "file")
        submit_ref = find_ref(
            upload_interactables["interactables"],
            "button",
            "upload submit",
        )
        assert file_ref is not None
        assert submit_ref is not None
        await session.upload_files(
            file_ref,
            text="uploaded file",
            filename="payload.txt",
        )
        submitted = await session.click(submit_ref, capture_requests=True)
        form_post_requests = [
            entry
            for entry in submitted.get("requests", [])
            if entry["method"] == "POST" and "httpbin.org/post" in entry["url"]
        ]
        assert form_post_requests, "expected multipart form POST after submit"
        form_post_id = form_post_requests[0]["id"]
        form_post_body = await session.get_captured_request_body(form_post_id)
        assert form_post_body["method"] == "POST"
        assert "multipart/form-data" in form_post_body["content_type"]
        assert 'name="field1"' in form_post_body["body"]
        assert "hello" in form_post_body["body"]
        assert form_post_body["size"] > 0
        assert form_post_body.get("body_source") == "proxy"

        await manager.close_session(session_info["session_id"])
        try:
            manager.get_session(session_info["session_id"])
            raise AssertionError("expected closed session to be removed")
        except ValueError:
            pass
        print("network capture smoke test passed")
    finally:
        await manager.stop()


async def test_request_registry() -> None:
    manager = BrowserManager()
    await manager.start()
    saved_paths: list[Path] = []
    try:
        session_info = await manager.create_session(
            "registry-test",
            initial_url="about:blank",
        )
        session = manager.get_session(session_info["session_id"])

        captured = await session.goto(
            "https://example.org",
            capture_requests=True,
        )
        request_id = assert_request_summaries(captured["requests"])

        registered = await manager.register_request(request_id)
        assert registered["request_id"] == request_id
        assert registered.get("already_registered") is not True
        registry_path = Path(registered["registry_path"])
        saved_paths.append(registry_path)
        assert registry_path.is_dir()
        assert (registry_path / "request_header").is_file()
        assert (registry_path / "response_header").is_file()
        assert (registry_path / "request_body").is_file()
        assert (registry_path / "response").is_file()
        raw_response = (registry_path / "response").read_text(encoding="utf-8")
        assert "<html" in raw_response.lower()

        await manager.close_session(session_info["session_id"])

        response = await manager.get_captured_response(request_id)
        assert response["registered"] is True
        assert response["format"] == "tree"
        assert "<html" not in response["body"].lower()
        assert "[ref=" in response["body"]

        req_headers = await manager.get_captured_request_headers(request_id)
        assert req_headers["registered"] is True
        assert req_headers["headers"]

        resp_headers = await manager.get_captured_response_headers(request_id)
        assert resp_headers["registered"] is True
        assert resp_headers["headers"]

        raw_response = await manager.get_captured_response(request_id, format="raw")
        assert raw_response["format"] == "raw"
        assert "<html" in raw_response["body"].lower()

        print("request registry smoke test passed")
    finally:
        for path in saved_paths:
            if path.is_dir():
                for child in sorted(path.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                for child in sorted(path.rglob("*"), reverse=True):
                    if child.is_dir():
                        child.rmdir()
                path.rmdir()
        await manager.stop()


async def test_page_inspect_and_http_tools() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from webgent.crypto_rsa import encrypt_rsa as encrypt_rsa_fn

    manager = BrowserManager()
    await manager.start()
    saved_paths: list[Path] = []
    try:
        session_info = await manager.create_session(
            "page-inspect-test",
            initial_url="about:blank",
        )
        session = manager.get_session(session_info["session_id"])

        await session.goto(FORM_DATA_PAGE_URL)
        form_data = await session.get_form_data()
        assert form_data["csrf_token"] == "csrf-abc"
        assert form_data["form"]["fields"]["_token"] == "tok-abc"
        assert form_data["form"]["fields"]["email"] == ""

        interactables = await session.page_interactables()
        assert "_token" not in interactables["interactables"]

        evaluated = await session.evaluate_js(
            '() => document.querySelector("meta[name=csrf-token]").content'
        )
        assert evaluated["result"] == "csrf-abc"
        assert evaluated["type"] == "str"

        await session.goto("https://example.com")
        cookies_before = await session.get_cookies()
        assert cookies_before["count"] >= 0

        await session.set_cookies(
            [
                {
                    "name": "webgent_test",
                    "value": "cookie-value",
                    "domain": ".example.com",
                    "path": "/",
                }
            ]
        )
        cookies_after = await session.get_cookies(urls=["https://example.com"])
        assert any(c["name"] == "webgent_test" for c in cookies_after["cookies"])

        captured = await session.goto(
            "https://example.org",
            capture_requests=True,
        )
        request_id = assert_request_summaries(captured["requests"])
        raw = await session.get_captured_response(request_id, format="raw")
        assert raw["format"] == "raw"
        assert "<html" in raw["body"].lower()

        http_result = await session.http_request(
            method="POST",
            url="https://httpbingo.org/post",
            data={"hello": "world"},
        )
        assert http_result["status"] == 200
        assert "hello" in http_result["body"]

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        ciphertext = encrypt_rsa_fn("secret", public_pem)
        assert ciphertext

        await session.goto(ENCRYPT_PAGE_URL)
        encrypted = await session.encrypt_rsa("secret", password_mode="page")
        assert encrypted["mode"] == "page"
        assert encrypted["ciphertext"] == "c2VjcmV0"

        await session.goto(URLENCODED_FORM_PAGE_URL)
        submit_ref = find_ref(
            (await session.page_interactables())["interactables"],
            "button",
            "submit encoded",
        )
        assert submit_ref is not None
        submitted = await session.click(submit_ref, capture_requests=True)
        post_requests = [
            entry
            for entry in submitted.get("requests", [])
            if entry["method"] == "POST" and "httpbingo.org/post" in entry["url"]
        ]
        assert post_requests, "expected urlencoded POST"
        post_id = post_requests[0]["id"]
        registered = await manager.register_request(post_id)
        saved_paths.append(Path(registered["registry_path"]))

        replayed = await manager.replay_request(
            session_info["session_id"],
            post_id,
            overrides={"field1": "updated"},
            refresh_token=False,
        )
        assert replayed["status"] == 200
        assert replayed["applied_fields"]["field1"] == "updated"
        assert replayed["applied_fields"]["_token"] == "tok123"

        await manager.close_session(session_info["session_id"])
        print("page inspect and http tools smoke test passed")
    finally:
        for path in saved_paths:
            if path.is_dir():
                for child in sorted(path.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                path.rmdir()
        await manager.stop()


async def test_mcp_tools() -> None:
    async with Client(str(SERVER_PATH)) as client:
        prompts = await client.list_prompts()
        prompt_names = {item.name for item in prompts}
        assert "agent_system_prompt" in prompt_names

        prompt_result = await client.get_prompt("agent_system_prompt")
        prompt_text = prompt_result.messages[0].content.text
        assert "interactable" in prompt_text.lower() or "interactables" in prompt_text.lower()

        resources = await client.list_resources()
        resource_uris = {resource.uri for resource in resources}
        assert "webgent://server-info" in resource_uris
        assert "webgent://prompt" not in resource_uris

        readme_contents = await client.read_resource("webgent://server-info")
        readme_text = readme_contents[0].text
        assert "webgent" in readme_text.lower()
        assert "MCP" in readme_text or "mcp" in readme_text.lower()

        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        expected = {
            "create_session",
            "add_page",
            "list_pages",
            "delete_page",
            "switch_page",
            "goto",
            "go_back",
            "go_forward",
            "close_session",
            "snapshot",
            "interactables",
            "get_node",
            "click",
            "type",
            "fill",
            "select_option",
            "set_checkbox",
            "select_radio",
            "upload_files",
            "set_slider",
            "set_switch",
            "set_spinbutton",
            "select_tab",
            "get_url",
            "screenshot",
            "captcha_ocr",
            "vision_query",
            "get_captured_response",
            "get_captured_request_headers",
            "get_captured_request_body",
            "get_captured_response_headers",
            "register_request",
            "evaluate_js",
            "get_form_data",
            "get_cookies",
            "set_cookies",
            "http_request",
            "encrypt_rsa",
            "replay_request",
        }
        assert expected.issubset(tool_names), f"missing tools: {expected - tool_names}"

        result = await client.call_tool(
            "create_session",
            {
                "profile_name": "mcp-test",
                "initial_url": "https://example.com",
            },
        )
        data = result.data
        session_id = data["session_id"]
        page_id = data["page_id"]

        result = await client.call_tool("add_page", {"session_id": session_id})
        second_page_id = result.data["page_id"]

        result = await client.call_tool("list_pages", {"session_id": session_id})
        assert len(result.data["pages"]) == 2

        result = await client.call_tool(
            "switch_page",
            {"session_id": session_id, "page_id": page_id},
        )
        assert result.data["active_page_id"] == page_id

        result = await client.call_tool(
            "goto",
            {"session_id": session_id, "url": "https://example.org"},
        )
        assert "example.org" in result.data["url"]

        result = await client.call_tool(
            "snapshot",
            {"session_id": session_id},
        )
        assert "snapshot" in result.data
        assert "[ref=" in result.data["snapshot"]

        result = await client.call_tool(
            "interactables",
            {"session_id": session_id},
        )
        assert "interactables" in result.data
        assert any(
            extract_ref_from_line(line) is not None
            for line in result.data["interactables"].splitlines()
        )

        result = await client.call_tool(
            "goto",
            {
                "session_id": session_id,
                "url": "data:text/html,<html><body><label>Search<input aria-label='Search query'></label><button>Go</button></body></html>",
            },
        )

        result = await client.call_tool(
            "interactables",
            {"session_id": session_id},
        )
        snapshot_text = result.data["interactables"]
        ref_match = find_ref(snapshot_text, "textbox", "search")
        assert ref_match is not None, f"expected a textbox ref in interactables:\n{snapshot_text}"
        button_ref = find_ref(snapshot_text, "button")
        assert button_ref is not None, "expected a button ref in interactables"

        result = await client.call_tool(
            "type",
            {
                "session_id": session_id,
                "ref": ref_match,
                "text": "webgent",
            },
        )
        assert result.data["ref"] == ref_match
        assert result.data["text"] == "webgent"
        assert "snapshot" not in result.data

        result = await client.call_tool(
            "click",
            {
                "session_id": session_id,
                "ref": button_ref,
            },
        )
        assert result.data["ref"] == button_ref
        assert "snapshot" not in result.data

        result = await client.call_tool(
            "screenshot",
            {"session_id": session_id},
        )
        assert "path" in result.data
        assert Path(result.data["path"]).exists()
        assert result.data["mode"] == "viewport"

        result = await client.call_tool(
            "screenshot",
            {"session_id": session_id, "full_page": True},
        )
        assert "path" in result.data
        assert Path(result.data["path"]).exists()
        assert result.data["mode"] == "full_page"

        result = await client.call_tool(
            "screenshot",
            {"session_id": session_id, "ref": button_ref},
        )
        assert "path" in result.data
        assert Path(result.data["path"]).exists()
        assert result.data["mode"] == "element"
        assert result.data["ref"] == button_ref

        result = await client.call_tool(
            "goto",
            {"session_id": session_id, "url": CAPTCHA_PAGE_URL},
        )
        result = await client.call_tool("interactables", {"session_id": session_id})
        captcha_ref = find_ref(result.data["interactables"], "img", "captcha")
        assert captcha_ref is not None
        result = await client.call_tool(
            "captcha_ocr",
            {"session_id": session_id, "ref": captcha_ref},
        )
        assert result.data["ref"] == captcha_ref
        assert isinstance(result.data["text"], str)
        assert len(result.data["text"]) > 0

        result = await client.call_tool(
            "vision_query",
            {
                "session_id": session_id,
                "prompt": "Describe the captcha image briefly.",
                "ref": captcha_ref,
            },
        )
        vision_data = result.data
        assert isinstance(vision_data.get("available"), bool)
        assert vision_data["mode"] == "element"
        assert vision_data["ref"] == captcha_ref
        if vision_data["available"]:
            assert isinstance(vision_data["response"], str)
            assert len(vision_data["response"]) > 0
        else:
            assert "unavailable" in vision_data["message"].lower()

        result = await client.call_tool(
            "goto",
            {"session_id": session_id, "url": FORM_PAGE_URL},
        )
        result = await client.call_tool("interactables", {"session_id": session_id})
        form_snapshot = result.data["interactables"]
        email_ref = find_ref(form_snapshot, "textbox", "email")
        country_ref = find_ref(form_snapshot, "combobox", "country")
        checkbox_ref = find_ref(form_snapshot, "checkbox", "subscribe")
        radio_ref = find_ref(form_snapshot, "radio", "pro")
        assert email_ref and country_ref and checkbox_ref and radio_ref

        result = await client.call_tool(
            "get_node",
            {"session_id": session_id, "ref": email_ref},
        )
        assert result.data["ref"] == email_ref
        assert result.data["format"] == "tree"
        assert "subtree" in result.data

        result = await client.call_tool(
            "fill",
            {"session_id": session_id, "ref": email_ref, "value": "user@example.com"},
        )
        assert result.data["value"] == "user@example.com"

        result = await client.call_tool(
            "select_option",
            {
                "session_id": session_id,
                "ref": country_ref,
                "values": ["United States"],
            },
        )
        assert result.data["values"] == ["United States"]

        result = await client.call_tool(
            "set_checkbox",
            {"session_id": session_id, "ref": checkbox_ref, "checked": True},
        )
        assert result.data["checked"] is True

        result = await client.call_tool(
            "select_radio",
            {"session_id": session_id, "ref": radio_ref},
        )
        assert result.data["checked"] is True

        result = await client.call_tool(
            "goto",
            {"session_id": session_id, "url": UPLOAD_PAGE_URL},
        )
        result = await client.call_tool("interactables", {"session_id": session_id})
        upload_ref = find_ref(result.data["interactables"], "file", "upload")
        if upload_ref is None:
            upload_ref = find_ref(result.data["interactables"], "button", "upload")
        if upload_ref is None:
            upload_ref = find_ref(result.data["interactables"], "input", "upload")
        assert upload_ref is not None

        result = await client.call_tool(
            "upload_files",
            {
                "session_id": session_id,
                "ref": upload_ref,
                "text": "inline content",
                "filename": "upload.txt",
            },
        )
        assert result.data["source"] == "inline"
        assert result.data["files"] == ["upload.txt"]

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            delete=False,
        ) as handle:
            handle.write("disk content")
            disk_path = handle.name

        try:
            result = await client.call_tool(
                "goto",
                {"session_id": session_id, "url": UPLOAD_PAGE_URL},
            )
            result = await client.call_tool("interactables", {"session_id": session_id})
            upload_ref = find_ref(result.data["interactables"], "file", "upload")
            if upload_ref is None:
                upload_ref = find_ref(result.data["interactables"], "button", "upload")
            if upload_ref is None:
                upload_ref = find_ref(result.data["interactables"], "input", "upload")
            assert upload_ref is not None

            result = await client.call_tool(
                "upload_files",
                {
                    "session_id": session_id,
                    "ref": upload_ref,
                    "filepath": str(Path(disk_path).resolve()),
                },
            )
            assert result.data["source"] == "path"
            assert result.data["files"] == [Path(disk_path).name]
        finally:
            Path(disk_path).unlink(missing_ok=True)

        result = await client.call_tool(
            "goto",
            {"session_id": session_id, "url": LINKS_PAGE_URL},
        )
        result = await client.call_tool("interactables", {"session_id": session_id})
        assert result.data["scope_ref"] is None
        link_ref = find_ref(result.data["interactables"], "long")
        assert link_ref is not None

        result = await client.call_tool(
            "snapshot",
            {
                "session_id": session_id,
                "include_urls": True,
                "max_url_len": 40,
            },
        )
        assert "/url:" in result.data["snapshot"]
        assert LONG_LINK_URL not in result.data["snapshot"]

        result = await client.call_tool(
            "get_url",
            {"session_id": session_id, "ref": link_ref},
        )
        assert result.data["url"] == LONG_LINK_URL

        result = await client.call_tool(
            "interactables",
            {"session_id": session_id, "ref": link_ref},
        )
        assert result.data["scope_ref"] == link_ref

        result = await client.call_tool(
            "delete_page",
            {"session_id": session_id, "page_id": second_page_id},
        )
        assert result.data["active_page_id"] == page_id

        result = await client.call_tool(
            "goto",
            {
                "session_id": session_id,
                "url": "https://example.net",
                "capture_requests": True,
            },
        )
        assert "requests" in result.data
        request_id = assert_request_summaries(result.data["requests"])

        result = await client.call_tool(
            "get_captured_request_headers",
            {"request_id": request_id},
        )
        assert result.data["headers"]

        result = await client.call_tool(
            "get_captured_request_body",
            {"request_id": request_id},
        )
        assert "body" in result.data
        assert result.data["size"] == 0

        result = await client.call_tool(
            "get_captured_response_headers",
            {"request_id": request_id},
        )
        assert result.data["headers"]

        result = await client.call_tool(
            "get_captured_response",
            {"request_id": request_id},
        )
        assert result.data["body"]

        result = await client.call_tool(
            "close_session",
            {"session_id": session_id},
        )
        assert result.data["closed"] is True
        print("mcp tools smoke test passed")


async def test_tool_errors_as_responses() -> None:
    from fastmcp import FastMCP

    from webgent.mcp_tools import ToolErrorAsResponseMiddleware, wrap_tool_result

    app = FastMCP("tool-error-test")
    app.add_middleware(ToolErrorAsResponseMiddleware())

    @app.tool
    @wrap_tool_result
    async def raises_runtime() -> dict:
        raise ValueError("runtime failure")

    @app.tool
    async def bad_args(required: str) -> dict:
        return {"required": required}

    runtime = await app.call_tool("raises_runtime", {})
    assert runtime.structured_content["error_type"] == "ValueError"
    assert "runtime failure" in runtime.structured_content["error"]

    invalid = await app.call_tool(
        "bad_args",
        {"unexpected": "value"},
    )
    assert invalid.structured_content["error_type"] == "ValidationError"
    assert invalid.structured_content["tool"] == "bad_args"
    assert invalid.structured_content["validation_errors"]

    missing = await app.call_tool("missing_tool", {})
    assert missing.structured_content["error_type"] == "NotFoundError"
    assert missing.structured_content["tool"] == "missing_tool"

    print("tool error response smoke test passed")


async def main() -> None:
    test_compress_snapshot_helpers()
    test_interactive_snapshot_helpers()
    await test_snapshot_role_normalization()
    await test_cross_frame_refs()
    await test_vision_query()
    await test_browser_manager()
    await test_action_metadata_only()
    await test_fill_verifies_dom_value()
    await test_network_capture()
    await test_request_registry()
    await test_page_inspect_and_http_tools()
    await test_tool_errors_as_responses()
    await test_mcp_tools()


if __name__ == "__main__":
    asyncio.run(main())
