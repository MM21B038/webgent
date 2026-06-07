You have access to the Butcher MCP server. It will perform all web based task and network request capturing tasks and much more.

WHEN TO USE THIS SERVER
If task or any sub task needs to perform any web interaction then in that case this was the best server tools you can use.

ORDER OF OPERATION
1. continue with the already created/used session or create new session (preferred for the different new task).
2. use the respective best out of butcher server tools to perform any required web action and network request/response capturing.
3. use snapshot tools to get full page overview and full structured with all interactables already included so this the best tool to use and use it with full scope using depth parameter of it by keeping it large etc. Use it to understand about the page, instructions, headings, text, form instruction, etc. 
4. use the interactables tool to get only all interactable ref elements only if just needed that only.
5. if getting stuck/block tools not woking look at the `HANDLING BLOCKERS, ERRORS AND FEEL STUCK STATE` section to handle it in a correct way.
6. always use the respective tool to perform any action on interactive respective ref elements like for example:
  6.1 use only click tool to click on button element.
  6.2 you can use click tool to also click on generic ref element and any type of element as well whenever needed but required exact correct ref.
  6.3 use fill much better then type to fill the content in the element and not just to type else use type.
    - fill verifies the value was actually written; check the returned `value` field matches what you intended.
    - prefer fill for textboxes, textareas, and date fields; use type only when you need slow keystrokes or Enter-to-submit.
  6.3a date / readonly picker fields:
      - if interactables shows a textbox with `[readonly]`, do NOT use type — it will fail.
      - use fill with a date string: `dd-mm-yyyy` (recommended, e.g. `15-06-1990`) or `yyyy-mm-dd` try different format which ever with works fine.
      - fill handles jQuery UI datepicker, flatpickr, and native date inputs automatically.
      - after fill, confirm `value` in the response (or use get_node) before moving on.
  6.3b if fill returns "element is readonly" and it is NOT a date field:
      - the field may be disabled until another choice is made (tab, radio, login mode).
      - re-fetch interactables, click the required tab/mode first, then fill again.
  6.4 select option for selecting dropdown option.
  6.5 use file upload tool to upload via 2 options:
    - if user provided the absolute file path use that absolute file path.
    - else use the filename(with extenstion) + text to put into that file or whenever user specifically asked for it. (recommended)
  6.6 similarly checkbox, radio, etc respectively.
  6.7 donot use the screenshot tool until unless user specifically specified for to use it.
  6.8 use `captcha_ocr` with the captcha image ref to read captcha text via ddddocr; then `fill` the captcha input field.
7. close the session after completing task and doesn't wanted to do more after askeing and confirmation from user.

PAGE DATA AND HTTP REPLAY
1. use `get_form_data` to read hidden fields like `_token` and `csrf_token` from meta tags; hidden inputs are not in interactables.
2. use `evaluate_js` when you need custom page values or to call page-side helper functions.
3. use `get_cookies` after `goto` to confirm session cookies; use `set_cookies` to seed cookies when needed.
4. use `get_captured_response(format="raw")` when you need original HTML/text from a captured GET (for example CSRF in page source).
5. prefer browser login via `fill` + `click` with `capture_requests=true` so page JS handles password encryption automatically.
6. use `encrypt_rsa` with `password_mode="page"` to encrypt via page JS, or `password_mode="rsa"` with `public_key` for server-side RSA.
7. use `http_request` for direct HTTP calls with the session cookie jar (POST form data, JSON, or raw body).
8. use `replay_request` to resend a captured/registered request with `overrides`; set `refresh_token=true` to reload the referer page and refresh `_token` / `X-CSRF-TOKEN` before replay.

HANDLING BLOCKERS, ERRORS AND FEEL STUCK STATE
1. if any actionabe tools not working like click, type, select option, upload file. there are two possibilities wrong `ref` or the blockers. 
2. for the 1st type wrong `ref` one you will get that error in the tool response so use interactable/snapshot again for getting update live current ref that you can use.
3. for the 2nd type blockers which could be popup/modal(cookie banner, ad, dialog) so in this case 
  - you should use snapshot tool to get full and clear structure first as the close elemen could be generic or other type not could be the input element type.
  - look for blocking UI under structure parents like dialog or named with like Close / X / Dismiss / Accept / Agree / Got it / Continue / No thanks.
  - For unnamed generic elements (common with ad/consent UIs), try clicking the generic ref that looks like a close area.
  - Click the dismiss control first, then re-fetch interactables and click your real target.

NOTE
- only on calling `interactable` or `snapshot` tool the previous these same respective tool call result will be colapse automatically with some short message to maintain the context size.
- so you can call these both tools on after some action whenever required or page change and url change during the ongoing task.