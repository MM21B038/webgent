"""Smoke test for browser manager and MCP tools."""

import asyncio
import tempfile
from pathlib import Path

from fastmcp import Client

from webgent.browser import BrowserManager
from webgent.snapshot import (
    compress_snapshot,
    extract_ref_from_line,
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
    print("interactive snapshot helpers test passed")


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

        resp_headers = await session.get_captured_response_headers(request_id)
        assert resp_headers["request_id"] == request_id
        assert resp_headers["status"] is not None
        assert isinstance(resp_headers["headers"], dict)

        response = await session.get_captured_response(request_id)
        assert response["request_id"] == request_id
        assert response["status"] is not None
        assert response["body"]
        assert response["size"] > 0

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

        await manager.close_session(session_info["session_id"])
        try:
            manager.get_session(session_info["session_id"])
            raise AssertionError("expected closed session to be removed")
        except ValueError:
            pass
        print("network capture smoke test passed")
    finally:
        await manager.stop()


async def test_mcp_tools() -> None:
    async with Client(str(SERVER_PATH)) as client:
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
            "get_captured_response",
            "get_captured_request_headers",
            "get_captured_response_headers",
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
            {"session_id": session_id, "request_id": request_id},
        )
        assert result.data["headers"]

        result = await client.call_tool(
            "get_captured_response_headers",
            {"session_id": session_id, "request_id": request_id},
        )
        assert result.data["headers"]

        result = await client.call_tool(
            "get_captured_response",
            {"session_id": session_id, "request_id": request_id},
        )
        assert result.data["body"]

        result = await client.call_tool(
            "close_session",
            {"session_id": session_id},
        )
        assert result.data["closed"] is True
        print("mcp tools smoke test passed")


async def main() -> None:
    test_compress_snapshot_helpers()
    test_interactive_snapshot_helpers()
    await test_browser_manager()
    await test_action_metadata_only()
    await test_network_capture()
    await test_mcp_tools()


if __name__ == "__main__":
    asyncio.run(main())
