from __future__ import annotations

from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode

from webgent.crypto_rsa import encrypt_rsa, encrypt_via_page
from webgent.http_client import http_request
from webgent.page_inspect import get_cookies, get_form_data

_SENSITIVE_FIELDS = frozenset({"password", "passwd", "pwd"})


def parse_form_body(body: str, content_type: str) -> dict[str, str]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/x-www-form-urlencoded":
        raise ValueError(
            f"Unsupported content type for replay: {content_type!r}. "
            "Only application/x-www-form-urlencoded is supported."
        )
    fields: dict[str, str] = {}
    for key, value in parse_qsl(body, keep_blank_values=True):
        fields[key] = value
    return fields


def build_form_body(fields: dict[str, str]) -> str:
    return urlencode(fields)


def _cookie_header(cookies: list[dict[str, Any]]) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))


def _redact_fields(fields: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in fields.items():
        if key.lower() in _SENSITIVE_FIELDS:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _pick_csrf_token(form_data: dict[str, Any]) -> str | None:
    token = form_data.get("csrf_token")
    if token:
        return str(token)
    form = form_data.get("form") or {}
    fields = form.get("fields") or {}
    if fields.get("_token"):
        return str(fields["_token"])
    return None


async def replay_request(
    session: Any,
    registry: Any,
    request_id: str,
    *,
    overrides: dict[str, str] | None = None,
    refresh_token: bool = False,
    refresh_url: str | None = None,
    encrypt_password: bool = False,
    password_mode: Literal["page", "rsa"] = "page",
    public_key: str | None = None,
    expression: str | None = None,
    max_bytes: int = 32768,
    format: Literal["tree", "raw"] = "tree",
) -> dict[str, Any]:
    if registry.exists(request_id):
        meta = registry.load_meta(request_id)
        headers = registry.load_request_headers(request_id)
        body_result = registry.get_request_body(request_id)
        method = str(meta.get("method") or "GET")
        url = str(meta.get("url") or "")
        content_type = str(body_result.get("content_type") or "")
        body = str(body_result.get("body") or "")
    else:
        entry = session._network_store.get(request_id)
        headers = await entry._request.all_headers()
        from webgent.request_body import resolve_request_body

        body_bytes, _ = await resolve_request_body(
            entry,
            session._proxy_capture,
            session._cdp_post_data,
        )
        body = body_bytes.decode("utf-8", errors="replace")
        method = entry.method
        url = entry.url
        content_type = entry._request.headers.get("content-type", "")

    if not url:
        raise ValueError(f"Could not resolve URL for request_id: {request_id}")

    fields = parse_form_body(body, content_type) if body else {}
    csrf_token: str | None = fields.get("_token") or headers.get("x-csrf-token")

    if refresh_token:
        target_url = refresh_url or headers.get("referer") or url
        page, page_id = session._resolve_page(None)
        await page.goto(target_url)
        form_data = await get_form_data(page)
        fresh = _pick_csrf_token(form_data)
        if fresh:
            csrf_token = fresh
            fields["_token"] = fresh

    if overrides:
        fields.update(overrides)

    if encrypt_password and "password" in fields:
        plain = fields["password"]
        if password_mode == "rsa":
            fields["password"] = encrypt_rsa(plain, public_key or "")
        else:
            page, _ = session._resolve_page(None)
            fields["password"] = await encrypt_via_page(
                page,
                plain,
                expression=expression,
            )

    if csrf_token:
        fields["_token"] = csrf_token

    replay_headers = {
        key: value
        for key, value in headers.items()
        if key.lower() not in {"content-length", "host", "cookie"}
        and not key.startswith(":")
    }
    if csrf_token:
        replay_headers["x-csrf-token"] = csrf_token

    cookie_result = await get_cookies(session.context)
    cookie_value = _cookie_header(cookie_result["cookies"])
    if cookie_value:
        replay_headers["cookie"] = cookie_value

    replay_body = build_form_body(fields)
    response = await http_request(
        session.context,
        method=method,
        url=url,
        headers=replay_headers,
        body=replay_body,
        content_type=content_type.split(";", 1)[0] if content_type else "application/x-www-form-urlencoded",
        max_bytes=max_bytes,
        format=format,
    )
    page, page_id = session._resolve_page(None)
    return {
        **response,
        "request_id": request_id,
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "csrf_token": csrf_token,
        "applied_fields": _redact_fields(fields),
    }
