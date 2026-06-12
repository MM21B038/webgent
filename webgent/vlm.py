from __future__ import annotations

import os

from composer import Agent, HumanMessage, Thread
from composer.image import to_data_url

from webgent.config import get_settings

VLM_UNAVAILABLE_MESSAGE = "VLM model is unavailable for now."


class VlmError(Exception):
    """VLM request failed."""


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def vlm_configured() -> bool:
    _load_env()
    settings = get_settings()
    return bool(
        os.getenv("BASE_URL", "").strip()
        and os.getenv("API_KEY", "").strip()
        and settings.agent.vlm_model.strip()
    )


def vlm_failure_reason(exc: BaseException) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return f"VLM request failed with HTTP {status_code}: {exc}"

    response = getattr(exc, "response", None)
    if response is not None:
        response_status = getattr(response, "status_code", None)
        if response_status is not None:
            return (
                f"VLM request failed with HTTP {response_status}: {exc}"
            )

    message = str(exc).strip()
    if message:
        return message
    return type(exc).__name__


def extract_vlm_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts).strip()
    return str(content).strip()


async def query_vlm(image: bytes, prompt: str) -> str:
    if not vlm_configured():
        raise VlmError(
            "VLM is not configured (BASE_URL, API_KEY, or vlm_model missing)"
        )

    settings = get_settings()
    agent = Agent(
        model=settings.agent.vlm_model,
        base_url=os.getenv("BASE_URL", "").strip(),
        api_key=os.getenv("API_KEY", "").strip(),
    )
    thread = Thread(
        auto_append_ai_message=False,
        auto_append_tool_calls=False,
        auto_append_tool_results=False,
    )
    data_url = to_data_url(image, "image/png")
    HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": data_url, "detail": "auto"},
            },
        ]
    ) | thread

    try:
        response = await (thread | agent)
    except Exception as exc:
        raise VlmError(vlm_failure_reason(exc)) from exc

    text = extract_vlm_text(response.content)
    if not text:
        raise VlmError("VLM returned empty response")
    return text
