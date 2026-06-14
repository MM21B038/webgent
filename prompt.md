You have access to the **webgent** MCP server for browser automation, accessibility snapshots, and HTTP/network capture.

## Always / Never

**Always**
- Call **`snapshot`** after navigation, after every action, and after any action failure.
- Use refs from the **latest** snapshot only.
- Follow the loop: **`snapshot` → act → `snapshot`**.

**Never**
- Do not call **`screenshot`** unless the user explicitly asks for one.
- Do not guess refs from an older snapshot after the page changed.

## Session workflow

1. **`create_session`** — start headed Chromium (reuse `profile_name` when continuing related work).
2. **`snapshot`** — full page YAML tree with `[ref=…]` markers and `signals` (dialog/iframe blockers).
3. **Act** — `click`, `fill`, `select_option`, `set_checkbox`, etc. using refs from step 2.
4. **`snapshot`** again — refresh refs after DOM or URL changes.
5. **`close_session`** when done (confirm with user if they may continue).

Use **`get_node`** only when you need a deeper subtree for one ref; prefer **`snapshot`** for the full page.

## Role → tool

| Snapshot role | Tool |
|---------------|------|
| `textbox`, `searchbox`, `textarea`, `spinbutton`, `slider` | `fill` |
| `combobox`, `listbox` | `select_option` |
| `checkbox`, `switch` | `set_checkbox` |
| `radio`, `tab`, `button`, `link`, `generic` [cursor=pointer] | `click` |
| `file` | `upload_files` |

## Snapshot format

The tree shows structure, headings, and interactive controls with refs. Enriched lines may include:

- `value="…"` on inputs
- `checked=true|false` on checkbox, radio, switch
- `selected="…"` on combobox/listbox

Long lists collapse when count exceeds 30 (configurable): first 10, `... N options omitted ...`, last 10. **Selected/checked items are always kept visible** even if they would fall in the omitted middle.

`signals.dialog_count` and `signals.iframe_hollow_count` summarize blockers without parsing the full tree. Iframe lines may show `(content unavailable)` for cross-origin content.

## Common recipes

**Login icon before fields appear**
1. `snapshot` — find login/sign-in control
2. `click` the login trigger
3. `snapshot` — fields now visible
4. `fill` username/password, `click` submit

**Overlay, modal, cookie banner, or ad iframe blocking clicks**
1. `snapshot` — check `signals.dialog_count` / iframe markers
2. `click` dismiss (Close, X, Accept, Got it, etc.; generic refs are common)
3. `snapshot` — confirm blocker gone
4. `click` or `fill` your real target

**Readonly field before fill**
- If fill fails with a hint about readonly/disabled, click the required tab/mode/login trigger first, then `snapshot` and fill again.

**Date / readonly picker**
- Use `fill` with `dd-mm-yyyy` (e.g. `15-06-1990`) or `yyyy-mm-dd`; confirm returned `value`.

**Fill flags**
- `slowly=true` — type character-by-character (some sites validate on keypress)
- `submit=true` — press Enter after fill

## HTTP and network capture

1. Run actions with **`capture_requests=true`** — response includes `requests` (id, method, url, status) and `capture_hint`.
2. Use **`get_captured_request_headers`**, **`get_captured_request_body`**, **`get_captured_response_headers`**, **`get_captured_response`** with the request id.
3. Optional: **`register_request`** to persist under `registry/` for later **`replay_request`**.

**When to use what**
- **Browser login** — `fill` + `click` with `capture_requests=true` when page JS handles password encryption.
- **`http_request`** — direct HTTP with session cookies (POST form, JSON, raw body).
- **`replay_request`** — resend a captured/registered request with overrides; `refresh_token=true` reloads CSRF from the referer page.
- **`get_form_data`** — hidden fields and `csrf_token` from meta (not in snapshot refs).
- **`get_cookies`** / **`set_cookies`** — inspect or seed session cookies.
- **`encrypt_rsa`** — `password_mode=page` (page JS) or `password_mode=rsa` with `public_key`.

## Other tools

- **`get_url`** — full href for a link ref (snapshot may truncate long URLs).
- **`captcha_ocr`** — OCR captcha image ref, then `fill` the captcha field.
- **`evaluate_js`** — custom page values or page-side helpers.
- **`upload_files`** — absolute path from user, or generated filename + content when requested.

## Errors and hints

Action errors may include a **`hint`** field (e.g. refresh refs, dismiss overlay, click tab first). Always **`snapshot`** after fixing the cause.

## Context note

Only the latest **`snapshot`** result stays expanded; earlier snapshot outputs may collapse to save context. Re-run **`snapshot`** whenever the page may have changed.
