# webgent

Playwright-based MCP server for headed browser automation. Built for AI agents that need to see pages, find controls by accessibility refs, act on them, and track multi-tab sessions.

## Features

- **Headed Chromium** with persistent profiles under `profile/`
- **Accessibility snapshots** — full YAML tree with refs via `snapshot`
- **Ref-based actions** — click, fill, select, upload, and more
- **Multi-tab sessions** — new tabs opened by clicks are registered automatically; action responses switch to the new active page
- **Metadata-only action responses** — actions return `page_id`, `url`, `title`, and related fields; call `snapshot` again to refresh refs after changes
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
port = 3333

[snapshot]
list_threshold = 30
list_head = 10
list_tail = 10
iframe_retry_count = 2
iframe_retry_delay_s = 0.5

[mcp.cursor]
# url defaults to http://{server.host}:{server.port}/mcp when omitted
server_info_resource = "webgent://server-info"
prompt = "agent_system_prompt"
```

- **`headless`** — `false` opens a visible Chromium window; `true` runs without a display (servers, SSH, CI).
- **`display`** — X11 display for headed mode (e.g. `:0.0`). When set, webgent applies it before launching the browser. Leave empty to use the process `DISPLAY` env.
- **`server`** — HTTP transport settings. The MCP endpoint is `http://{host}:{port}/mcp`.
- **`snapshot`** — list truncation thresholds and iframe retry timing for snapshot capture.
- **`mcp.cursor`** — MCP prompt name and server-info resource URI for the Cursor MCP entry below. Omit `url` to auto-derive from `server.host` and `server.port`.

## Run

Start the MCP server over HTTP:

```bash
uv run webgent
```

The server listens at `http://127.0.0.1:3333/mcp` by default (see `settings.toml`).

### Cursor MCP config

Start `webgent` first, then add to your MCP settings using the URL from `settings.toml` (`mcp.cursor`):

```json
{
  "mcpServers": {
    "webgent": {
      "url": "http://127.0.0.1:3333/mcp"
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
2. **`snapshot`** — get the full accessibility tree with `[ref=…]` markers
3. **Action** — `click`, `fill`, `select_option`, etc. using a ref from the latest snapshot
4. **`snapshot`** again — refresh refs after navigation or DOM changes
5. **`close_session`** — shut down when done

Use **`get_node`** to inspect one element in more detail when needed.

### Snapshot format

The tree includes structure, text, headings, and interactive controls with refs. The **`snapshot`** response also includes **`signals`**: `dialog_count` and `iframe_hollow_count` for quick blocker detection.

```yaml
- navigation "Links":
  - link "Home" [ref=e1] [cursor=pointer]
  - link "About" [ref=e2] [cursor=pointer]
- form:
  - textbox "Email" [ref=e3] value="user@example.com"
  - combobox "Country" [ref=e4] selected="us":
    - option "Choose"
    - option "United States" [selected]
    - ... 25 options omitted ...
    - option "Zimbabwe"
  - checkbox "Subscribe" [ref=e5] checked=true
  - radio "Pro plan" [ref=e6] checked=false
  - file "Upload file" [ref=e7]
  - button "Submit" [ref=e8] [cursor=pointer]
- iframe [ref=e9] (content unavailable)
```

**Enrichment** — inputs may show `value="…"`, `checked=true|false`, and `selected="…"` suffixes parsed from the live DOM.

**Truncation** — when a dropdown, repetitive rows, or inline `options=` list exceeds `list_threshold` (default 30), the middle collapses to `... N options omitted ...` while keeping the first/last 10 items; selected/checked entries are always preserved.

Roles are resolved from the DOM where the accessibility tree is misleading — for example `<input type="file">` is labeled `file` (not `button`). The same DOM role resolution applies to **`snapshot`** and **`get_node`**.

Pass `ref` to scope snapshot to a subtree; pass `depth` to limit capture depth.

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
| `goto` | Navigate the active tab (or a given `page_id`) |
| `close_session` | Close the session and all tabs |

### Discovery

| Tool | Description |
|------|-------------|
| `snapshot` | Full YAML accessibility tree with signals and DOM-enriched state |
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
| `click` | Click buttons, links, tabs, radios, and generic dismiss controls |
| `fill` | Fill text inputs, sliders, spinbuttons, and date fields |
| `select_option` | Select dropdown values |
| `set_checkbox` | Set checkbox or switch checked state |
| `upload_files` | Upload to a file input (path or inline text) |

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
  snapshot.py    Snapshots, tree formatting, ref helpers
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
