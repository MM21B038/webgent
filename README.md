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

## Run

Start the MCP server (stdio):

```bash
uv run webgent
```

### Cursor MCP config

Add to your MCP settings (adjust the path):

```json
{
  "mcpServers": {
    "webgent": {
      "command": "uv",
      "args": ["run", "webgent"],
      "cwd": "d:/app/backend/webgent"
    }
  }
}
```

Restart Cursor after changing MCP config or server code.

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
  - [e5] button "Submit" [cursor=pointer]
```

Combobox and listbox options are inlined on the parent line. Pass `ref` to scope interactables to a subtree; pass `depth` to limit capture depth.

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
  files.py       Upload file resolution
  config.py      Paths (profile/, media/)
profile/         Persistent browser profiles
media/           Screenshot output
scripts/         Smoke tests
```

## License

See repository license file if present.
