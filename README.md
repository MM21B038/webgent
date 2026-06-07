# webgent

Playwright-based MCP server for headed browser automation. Built for AI agents that need to see pages, find controls by accessibility refs, act on them, and track multi-tab sessions.

## Features

- **Headed Chromium** with persistent profiles under `profile/`
- **Accessibility snapshots** — full YAML tree via `snapshot`, trimmed actionable tree via `interactables`
- **Ref-based actions** — click, type, fill, select, upload, sliders, switches, tabs, and more
- **Multi-tab sessions** — new tabs opened by clicks are registered automatically; action responses switch to the new active page
- **Metadata-only action responses** — actions return `page_id`, `url`, `title`, and related fields; call `interactables` again to refresh refs after changes
- **Screenshots** — viewport, full-page, or element captures saved under `media/`

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (recommended)

## Install

```bash
git clone <repo-url>
cd webgent
uv sync
uv run playwright install chromium
```

## Configuration

Edit `settings.toml` in the project root:

```toml
[browser]
headless = false
display = ":0.0"

[server]
transport = "http"
host = "127.0.0.1"
port = 1234

[mcp.cursor]
url = "http://127.0.0.1:1234/mcp"
```

- **`headless`** — `false` opens a visible Chromium window; `true` runs without a display (servers, SSH, CI).
- **`display`** — X11 display for headed mode (e.g. `:0.0`). When set, webgent applies it before launching the browser. Leave empty to use the process `DISPLAY` env.
- **`server`** — HTTP transport settings. The MCP endpoint is `http://{host}:{port}/mcp`.
- **`mcp.cursor`** — suggested URL, MCP prompt name, and server-info resource URI for the Cursor MCP entry below.

## Run

Start the MCP server over HTTP:

```bash
uv run webgent
```

The server listens at `http://127.0.0.1:1234/mcp` by default (see `settings.toml`).

### Cursor MCP config

Start `webgent` first, then add to your MCP settings using the URL from `settings.toml` (`mcp.cursor`):

```json
{
  "mcpServers": {
    "webgent": {
      "url": "http://127.0.0.1:1234/mcp"
    }
  }
}
```

After connecting, use the MCP prompt `agent_system_prompt` for agent instructions and read `webgent://server-info` for full project docs (names listed in `settings.toml` under `[mcp.cursor]`).

Display and headless mode are read from `settings.toml` at server startup — no need to pass `DISPLAY` in the MCP env block.

Restart Cursor after changing MCP config or server code.

### MCP prompt

Agent instructions from `prompt.md` are exposed as an MCP prompt (not a resource):

| Prompt name | File | Description |
|-------------|------|-------------|
| `agent_system_prompt` | `prompt.md` | When to use webgent, tool order, and action rules |

Fetch with `list_prompts` / `get_prompt`.

### MCP resources

Project documentation is exposed as an MCP resource:

| Resource URI | File | Description |
|--------------|------|-------------|
| `webgent://server-info` | `README.md` | Install, configuration, tools, and development notes |

Read with `list_resources` / `read_resource`.

## Agent workflow

1. **`create_session`** — start a browser session (optionally with `profile_name` and `initial_url`)
2. **`interactables`** — get a trimmed tree of actionable elements with `[eN]` refs
3. **Action** — `click`, `fill`, `select_option`, etc. using a ref from the latest interactables
4. **`interactables`** again — refresh refs after navigation or DOM changes
5. **`close_session`** — shut down when done

Use **`snapshot`** when you need the full accessibility tree (structure, text, roles). Use **`get_node`** to inspect one element in more detail.

### Interactables format

Non-actionable structure is kept as context; controls are compact lines with refs:

```yaml
- navigation "Links":
  - [e1] link "Home" [cursor=pointer]
  - [e2] link "About" [cursor=pointer]
- form:
  - [e3] textbox "Email"
  - [e4] combobox "Country" options="United States" | "United Kingdom"
  - [e5] checkbox "Subscribe"
  - [e6] radio "Pro plan"
  - [e7] file "Upload file"
  - [e8] button "Submit" [cursor=pointer]
```

Roles are resolved from the DOM where the accessibility tree is misleading — for example `<input type="file">` is labeled `file` (not `button`), and `<select>` dropdown options are inlined on combobox lines. Checkbox, radio, slider, switch, spinbutton, and other input types use their control role when present. The same DOM role resolution applies to **`snapshot`**, **`get_node`**, and **`interactables`**.

Pass `ref` to scope interactables to a subtree; pass `depth` to limit capture depth.

### Action responses

Actions return metadata only (no embedded snapshot):

```json
{
  "page_id": "...",
  "active_page_id": "...",
  "ref": "e5",
  "url": "https://example.com/done",
  "title": "Done",
  "opened_new_page": false
}
```

When a click opens a new tab, `opened_new_page` is `true`, `previous_page_id` is set, and `page_id` moves to the new tab. Use `list_pages` / `switch_page` to move between tabs.

## Tools

### Session & pages

| Tool | Description |
|------|-------------|
| `create_session` | Start headed Chromium with a persistent profile |
| `add_page` | Open a new tab; optionally navigate to a URL |
| `list_pages` | List tabs with `page_id`, `url`, `title`, `is_active` |
| `switch_page` | Set the active tab |
| `delete_page` | Close a tab (not the last one) |
| `goto` | Navigate the active tab (or a given `page_id`) |
| `close_session` | Close the session and all tabs |

### Discovery

| Tool | Description |
|------|-------------|
| `snapshot` | Full YAML accessibility tree |
| `interactables` | Trimmed tree of actionable elements |
| `get_node` | Role, name, states, value, checked, and a small subtree for one ref |
| `get_url` | Full `href` for a link ref |
| `screenshot` | Viewport, full-page, or element PNG/JPEG under `media/` |
| `captcha_ocr` | OCR a captcha image element by ref via ddddocr |
| `evaluate_js` | Run JavaScript in the page context |
| `get_form_data` | Extract forms, hidden fields, and CSRF token from the page |
| `get_cookies` | List session cookies (optional URL filter) |
| `set_cookies` | Add cookies to the session |

### Network capture

| Tool | Description |
|------|-------------|
| `get_captured_response` | Response body (`format=tree` or `format=raw`) |
| `get_captured_request_headers` | Request headers for a capture id |
| `get_captured_request_body` | Request body for a capture id |
| `get_captured_response_headers` | Response headers for a capture id |
| `register_request` | Persist a capture to `registry/{request_id}/` |

Pass `capture_requests=true` on navigation and action tools to record network activity.

### HTTP replay

| Tool | Description |
|------|-------------|
| `http_request` | Send HTTP with session cookies (`body`, `data`, or `json`) |
| `encrypt_rsa` | Encrypt plaintext via page JS or server-side RSA |
| `replay_request` | Replay a capture/registered request with overrides |

### Actions

All actions take `session_id`, `ref`, and optional `page_id`. Responses include `page_id`, `active_page_id`, `ref`, `url`, and `title`.

| Tool | Description |
|------|-------------|
| `click` | Click; falls back when overlays intercept pointer events |
| `type` | Type into an editable element (`submit`, `slowly` optional) |
| `fill` | Fill an input |
| `select_option` | Select dropdown values |
| `set_checkbox` | Set checkbox checked state |
| `select_radio` | Select a radio option |
| `upload_files` | Upload to a file input (path or inline text) |
| `set_slider` | Set a range/slider value |
| `set_switch` | Set a switch checked state |
| `set_spinbutton` | Set a number input value |
| `select_tab` | Select a tab |

## Development

Run the smoke tests:

```bash
uv run python scripts/smoke_test.py
```

### Project layout

```
webgent/
  server.py      MCP tool definitions
  browser.py     Session, page, and action logic
  snapshot.py    Snapshots, interactables tree, ref helpers
  screenshot.py  Screenshot capture
  captcha_ocr.py Captcha OCR via ddddocr
  files.py       Upload file resolution
  config.py      Settings loader and paths (profile/, media/)
settings.toml    Browser headless/display and MCP hints
profile/         Persistent browser profiles
media/           Screenshot output
scripts/         Smoke tests
```

## License

See repository license file if present.
