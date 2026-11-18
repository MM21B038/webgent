# webgent

Playwright-based MCP server for headed browser automation. Built for AI agents that need to see pages, find controls by accessibility refs, act on them, and track multi-tab sessions.

## Features

- **Headed Chromium** with persistent profiles under `profile/`
- **Accessibility snapshots** — full YAML tree with refs via `snapshot`
- **Ref-based actions** — click, fill, select, upload, and more
- **Multi-tab sessions** — new tabs opened by clicks are registered automatically; action responses switch to the new active page
- **Metadata-only action responses** — actions return `page_id`, `url`, `title`, and related fields; call `snapshot` again to refresh refs after changes
- **Screenshots** — viewport, full-page, or element captures saved under `media/`
- **Network capture** — embedded mitmproxy (or an external Burp-style proxy) for exact request/response bodies
- **Vision** — `vision_query` and VLM-backed `captcha_ocr` via an OpenAI-compatible API

## Requirements

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose (recommended way to run the MCP server)
- Optional: an OpenAI-compatible API key for VLM tools

For local development without Docker: Python 3.14+, [uv](https://docs.astral.sh/uv/), and Playwright Chromium.

## Install

```bash
git clone <repo-url>
cd webgent
cp .env.example .env
```

Edit `.env` with `BASE_URL`, `API_KEY`, and any `WEBGENT_*` overrides (model names, ports, proxy). `settings.toml` is the file-based default; env wins over it.

## Run (Docker MCP)

webgent is an **HTTP** MCP server. The container binds `0.0.0.0:3333` and publishes it to the host.

```bash
docker compose up --build -d
```

MCP URL on the host: `http://127.0.0.1:3333/mcp`

```bash
docker compose logs -f webgent
docker compose down
```

Without Compose:

```bash
docker build -t webgent .
docker run --rm --name webgent --init --shm-size=2g -p 3333:3333 \
  --env-file .env \
  -e WEBGENT_IN_DOCKER=1 -e WEBGENT_SERVER_HOST=0.0.0.0 -e WEBGENT_HEADLESS=true \
  -v ./settings.toml:/app/settings.toml:ro \
  -v ./profile:/app/profile -v ./media:/app/media \
  -v ./registry:/app/registry -v ./mitmproxy:/app/mitmproxy \
  webgent
```

The image runs Chromium **headless** with `--no-sandbox` and `--disable-dev-shm-usage`. `settings.toml` `headless` / `display` for a local X11 session are ignored unless you set `WEBGENT_HEADLESS` / `WEBGENT_DISPLAY`.

If the VLM API runs on the host, use `http://host.docker.internal:PORT/v1` as `BASE_URL` (not `127.0.0.1` inside the container).

## Integrate with Cursor

1. Copy `.env.example` → `.env` and set `BASE_URL` / `API_KEY` if you need VLM tools. Set `WEBGENT_VLM_MODEL` (and other `WEBGENT_*` keys) here whenever you want to change models without editing the image.
2. Optionally adjust `settings.toml` (used when the matching env var is unset).
3. Start the container: `docker compose up --build -d`. Leave it running.
4. Add an **HTTP** MCP server in Cursor (`~/.cursor/mcp.json` or the MCP panel). Do not use a `command` / stdio block.

```json
{
  "mcpServers": {
    "webgent": {
      "url": "http://127.0.0.1:3333/mcp"
    }
  }
}
```

Do not put `API_KEY` in this JSON; Compose already passes `.env` into the container.

5. Reload MCP / restart Cursor after changing the JSON or the published port.
6. Use prompt `agent_system_prompt` and resource `webgent://server-info`.

Other HTTP MCP clients use the same URL. There is no stdio entrypoint.

## Configuration

Precedence, highest first:

1. Environment variables (including `.env` injected by Compose)
2. `settings.toml` (image default, or a file you mount)
3. Built-in defaults in code

Restart the container after changing `.env` or the mounted `settings.toml`. You do not rebuild or republish the image to change model names.

| File | Role |
|------|------|
| `.env` | Secrets (`BASE_URL`, `API_KEY`) and all `WEBGENT_*` overrides. Copy from `.env.example`. |
| `settings.toml` | File defaults for browser, proxy, HTTP MCP, snapshot, Cursor hints, and agent models. |

### Registry image (no rebuild)

Pull and run with only `.env` (the image already contains a default `settings.toml`):

```bash
docker pull ghcr.io/mm21b038/webgent:latest
docker run --rm --name webgent --init --shm-size=2g -p 3333:3333 \
  --env-file .env \
  -e WEBGENT_VLM_MODEL=openrouter/free \
  -e WEBGENT_LLM_MODEL=openrouter/free \
  -e WEBGENT_EMB_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free \
  ghcr.io/mm21b038/webgent:latest
```

To use a full local `settings.toml` instead of env keys:

```bash
docker run --rm --name webgent --init --shm-size=2g -p 3333:3333 \
  --env-file .env \
  -v ./settings.toml:/app/settings.toml:ro \
  ghcr.io/mm21b038/webgent:latest
```

Or point at another file with `WEBGENT_SETTINGS_PATH=/config/settings.toml` and mount that path.

### Environment

Every `settings.toml` key has a matching `WEBGENT_*` variable. Unset or blank env values fall through to `settings.toml`.

| Variable | `settings.toml` | Description |
|----------|-----------------|-------------|
| `BASE_URL` | — | OpenAI-compatible API base. From Docker, use `http://host.docker.internal:…` for a host-side API. |
| `API_KEY` | — | API key for that endpoint. |
| `WEBGENT_SETTINGS_PATH` | — | Alternate settings file path inside the container. |
| `WEBGENT_LLM_MODEL` | `[agent].llm_model` | Chat model id. |
| `WEBGENT_VLM_MODEL` | `[agent].vlm_model` | Vision model id (`vision_query`, VLM captcha). |
| `WEBGENT_EMB_MODEL` | `[agent].emb_model` | Embedding model id. |
| `WEBGENT_HEADLESS` | `[browser].headless` | Docker image defaults to `true`. |
| `WEBGENT_DISPLAY` | `[browser].display` | X11 display; ignored in Docker unless set. |
| `WEBGENT_IN_DOCKER` | — | Container Chromium flags; set by the image. |
| `WEBGENT_CHROMIUM_ARGS` | — | Extra Chromium flags (comma or space separated). |
| `WEBGENT_SERVER_TRANSPORT` | `[server].transport` | Keep `http`. |
| `WEBGENT_SERVER_HOST` | `[server].host` | Docker image defaults to `0.0.0.0`. |
| `WEBGENT_SERVER_PORT` | `[server].port` | MCP listen port. |
| `WEBGENT_PROXY_ENABLED` | `[proxy].enabled` | Intercepting proxy on/off. |
| `WEBGENT_PROXY_MODE` | `[proxy].mode` | `embedded` or `external`. |
| `WEBGENT_PROXY_HOST` | `[proxy].host` | Embedded mitmproxy host. |
| `WEBGENT_PROXY_PORT` | `[proxy].port` | Embedded mitmproxy port. |
| `WEBGENT_PROXY_EXTERNAL_SERVER` | `[proxy].external_server` | e.g. `http://127.0.0.1:8080`. |
| `WEBGENT_PROXY_MAX_BODY_BYTES` | `[proxy].max_body_bytes` | Capture body size cap. |
| `WEBGENT_PROXY_BYPASS_LOOPBACK` | `[proxy].bypass_loopback` | `false` recommended for full capture. |
| `WEBGENT_SNAPSHOT_LIST_THRESHOLD` | `[snapshot].list_threshold` | Truncation trigger. |
| `WEBGENT_SNAPSHOT_LIST_HEAD` | `[snapshot].list_head` | Keep first N items. |
| `WEBGENT_SNAPSHOT_LIST_TAIL` | `[snapshot].list_tail` | Keep last N items. |
| `WEBGENT_SNAPSHOT_IFRAME_RETRY_COUNT` | `[snapshot].iframe_retry_count` | Iframe retries. |
| `WEBGENT_SNAPSHOT_IFRAME_RETRY_DELAY_S` | `[snapshot].iframe_retry_delay_s` | Iframe retry delay. |
| `WEBGENT_MCP_URL` | `[mcp.cursor].url` | Client MCP URL hint. |
| `WEBGENT_MCP_PROMPT` | `[mcp.cursor].prompt` | MCP prompt name. |
| `WEBGENT_MCP_SERVER_INFO_RESOURCE` | `[mcp.cursor].server_info_resource` | README resource URI. |

`.env` is gitignored. Do not put keys in `settings.toml` or in Cursor MCP `env`.

### `settings.toml`

All keys currently read (or documented for Cursor) from the project root file:

```toml
[browser]
# false = visible Chromium; true = no window (servers, SSH, CI).
headless = false
# X11 display for headed mode. Non-empty value is applied before Chromium starts.
# Leave empty to use the process DISPLAY env (or DISPLAY in .env).
display = ":0.0"

[proxy]
# Intercepting proxy for exact request/response body capture.
enabled = true
# embedded = start mitmproxy in-process; external = use external_server only.
mode = "embedded"
host = "127.0.0.1"
port = 8888
# When mode = external, e.g. "http://127.0.0.1:8080" (Burp default).
external_server = ""
max_body_bytes = 1048576
# false = route localhost through the proxy (recommended for full capture).
bypass_loopback = false

[server]
# HTTP Streamable MCP (not stdio). Endpoint: http://{host}:{port}/mcp
# In Docker the image binds 0.0.0.0 via WEBGENT_SERVER_HOST; keep 127.0.0.1 for local uv.
transport = "http"
host = "127.0.0.1"
port = 3333

[snapshot]
# Collapse long option lists and repetitive rows when count exceeds list_threshold.
list_threshold = 30
list_head = 10
list_tail = 10
iframe_retry_count = 2
iframe_retry_delay_s = 0.5

[mcp.cursor]
# MCP URL defaults to http://{server.host}:{server.port}/mcp when url is omitted.
server_info_resource = "webgent://server-info"
prompt = "agent_system_prompt"

[agent]
# Model ids for the OpenAI-compatible client (used with BASE_URL / API_KEY).
llm_model = "openrouter/free"
vlm_model = "openrouter/free"
emb_model = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
```

#### `[browser]`

| Key | Default | Description |
|-----|---------|-------------|
| `headless` | `false` | `false` opens a visible Chromium window; `true` runs without a display. Docker defaults to headless via `WEBGENT_HEADLESS`. |
| `display` | `""` | X11 display (e.g. `:0.0`) for non-Docker headed mode. Ignored in Docker unless `WEBGENT_DISPLAY` is set. |

#### `[proxy]`

Used when tools record network with `capture_requests=true`.

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Turn intercepting proxy capture on or off. |
| `mode` | `"embedded"` | `embedded` starts mitmproxy in-process; `external` uses `external_server` only (e.g. Burp). |
| `host` | `"127.0.0.1"` | Listen host for embedded mitmproxy. |
| `port` | `8888` | Listen port for embedded mitmproxy. |
| `external_server` | `""` | Proxy URL when `mode = "external"`, e.g. `http://127.0.0.1:8080`. |
| `max_body_bytes` | `1048576` | Max captured request/response body size (1 MiB). |
| `bypass_loopback` | `false` | `false` routes localhost through the proxy (recommended for full capture). |

First run of embedded mitmproxy writes CA/config under `mitmproxy/`. Trust that CA in the browser profile if HTTPS capture is empty.

#### `[server]`

webgent is an **HTTP** MCP server (FastMCP streamable HTTP), not stdio.

| Key | Default | Description |
|-----|---------|-------------|
| `transport` | `"http"` | MCP transport. Keep `http` for Cursor `url` clients. |
| `host` | `"127.0.0.1"` | Bind address. Docker sets `WEBGENT_SERVER_HOST=0.0.0.0` so the port can be published. |
| `port` | `3333` | Bind port. Overridden by `WEBGENT_SERVER_PORT` if set. |

The MCP endpoint is `http://{host}:{port}/mcp`. From the host with Compose, use `http://127.0.0.1:3333/mcp`.

#### `[snapshot]`

| Key | Default | Description |
|-----|---------|-------------|
| `list_threshold` | `30` | Collapse middle of long option lists / repetitive rows above this count. |
| `list_head` | `10` | Items kept at the start when truncating. |
| `list_tail` | `10` | Items kept at the end when truncating. |
| `iframe_retry_count` | `2` | Retries when iframe content is not ready. |
| `iframe_retry_delay_s` | `0.5` | Delay between iframe retries (seconds). |

#### `[mcp.cursor]`

Hints for the Cursor entry below. Optional `url` is not required; it defaults to `http://{server.host}:{server.port}/mcp`.

| Key | Default | Description |
|-----|---------|-------------|
| `url` | derived | Full MCP HTTP URL for clients. Omit to auto-derive; `0.0.0.0` is rewritten to `127.0.0.1`. |
| `server_info_resource` | `webgent://server-info` | Resource URI for this README. |
| `prompt` | `agent_system_prompt` | MCP prompt name for `prompt.md`. |

#### `[agent]`

Model names passed to the OpenAI-compatible client. Credentials stay in `.env`.

| Key | Used by | Description |
|-----|---------|-------------|
| `vlm_model` | `vision_query`, `captcha_ocr` (VLM modes) | Vision model id. Override with `WEBGENT_VLM_MODEL`. |
| `llm_model` | reserved | Chat model id. Override with `WEBGENT_LLM_MODEL`. |
| `emb_model` | reserved | Embedding model id. Override with `WEBGENT_EMB_MODEL`. |

## Local development (without Docker)

```bash
uv sync
uv run playwright install chromium
uv run webgent
```

Default listen URL is `http://127.0.0.1:3333/mcp` from `settings.toml` (`[server].host` stays loopback).

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
| `captcha_ocr` | OCR a captcha by ref (`ddddocr`, `vlm`, or `both`; VLM needs `.env`) |
| `vision_query` | Ask the configured VLM about a viewport, full-page, or element screenshot |
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
settings.toml    Browser, proxy, HTTP MCP, snapshot, agent models
.env.example     Template for API keys and Docker/server overrides
Dockerfile       HTTP MCP image (Playwright Chromium)
docker-compose.yml  Publish :3333, shm, volumes, .env
profile/         Persistent browser profiles
media/           Screenshot output
scripts/         Smoke tests
```

## License

See repository license file if present.
