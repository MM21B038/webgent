from __future__ import annotations

import json
from typing import Any

from playwright.async_api import BrowserContext, Page

_GET_FORM_DATA_JS = """(formIndex) => {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrf_token = csrfMeta ? csrfMeta.getAttribute('content') : null;
    const forms = [...document.querySelectorAll('form')].map((form) => {
        const fields = {};
        for (const el of form.elements) {
            if (!el.name) continue;
            const type = (el.type || '').toLowerCase();
            if (type === 'checkbox') {
                fields[el.name] = el.checked ? (el.value || 'on') : '';
                continue;
            }
            if (type === 'radio') {
                if (el.checked) fields[el.name] = el.value;
                continue;
            }
            if (el.tagName === 'SELECT') {
                fields[el.name] = el.value;
                continue;
            }
            fields[el.name] = el.value ?? '';
        }
        return {
            action: form.action || '',
            method: (form.method || 'get').toLowerCase(),
            fields,
        };
    });
    const selected = forms[formIndex] ?? null;
    return { csrf_token, forms, form: selected };
}"""


def _serialize_eval_result(value: Any) -> tuple[Any, str]:
    if value is None:
        return None, "null"
    if isinstance(value, (bool, int, float, str)):
        return value, type(value).__name__
    if isinstance(value, (list, dict)):
        try:
            json.dumps(value)
            return value, type(value).__name__
        except (TypeError, ValueError):
            return str(value), type(value).__name__
    return str(value), type(value).__name__


async def evaluate_js(
    page: Page,
    expression: str,
    arg: Any = None,
) -> dict[str, Any]:
    if not expression.strip():
        raise ValueError("expression must not be empty")
    if arg is None:
        raw = await page.evaluate(expression)
    else:
        raw = await page.evaluate(expression, arg)
    result, result_type = _serialize_eval_result(raw)
    return {"result": result, "type": result_type}


async def get_form_data(page: Page, *, form_index: int = 0) -> dict[str, Any]:
    if form_index < 0:
        raise ValueError("form_index must be >= 0")
    data = await page.evaluate(_GET_FORM_DATA_JS, form_index)
    if not isinstance(data, dict):
        raise ValueError("Unexpected form data result from page")
    return {
        "csrf_token": data.get("csrf_token"),
        "forms": data.get("forms") or [],
        "form": data.get("form"),
        "form_index": form_index,
    }


async def get_cookies(
    context: BrowserContext,
    *,
    urls: list[str] | None = None,
) -> dict[str, Any]:
    cookies = await context.cookies(urls=urls)
    return {"cookies": cookies, "count": len(cookies)}


def _validate_cookie(cookie: dict[str, Any]) -> None:
    required = ("name", "value", "domain", "path")
    missing = [key for key in required if not cookie.get(key) and cookie.get(key) != ""]
    if missing:
        raise ValueError(
            f"Each cookie must include {', '.join(required)}; missing: {', '.join(missing)}"
        )


async def set_cookies(
    context: BrowserContext,
    cookies: list[dict[str, Any]],
) -> dict[str, Any]:
    if not cookies:
        raise ValueError("cookies must contain at least one cookie")
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise ValueError("Each cookie must be an object")
        _validate_cookie(cookie)
    await context.add_cookies(cookies)  # type: ignore[arg-type]
    return {"added": len(cookies)}
