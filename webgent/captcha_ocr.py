from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any, Literal

import ddddocr

from webgent.vlm import VlmError, query_vlm, vlm_failure_reason

CaptchaMode = Literal["ddddocr", "vlm", "both"]
CAPTCHA_MODES: frozenset[str] = frozenset({"ddddocr", "vlm", "both"})

VLM_FALLBACK_MESSAGE = (
    "VLM model is unavailable for now, using ddddocr fallback."
)
CAPTCHA_PROMPT = (
    "Read the captcha text shown in this image. "
    "Reply with only the captcha characters, no explanation or punctuation."
)


@lru_cache(maxsize=2)
def _get_ocr(*, beta: bool) -> Any:
    return ddddocr.DdddOcr(show_ad=False, beta=beta)


def recognize_captcha_sync(
    image: bytes,
    *,
    beta: bool = False,
    png_fix: bool = False,
) -> str:
    ocr = _get_ocr(beta=beta)
    return ocr.classification(image, png_fix=png_fix)


async def recognize_captcha(
    image: bytes,
    *,
    beta: bool = False,
    png_fix: bool = False,
) -> str:
    return await asyncio.to_thread(
        recognize_captcha_sync,
        image,
        beta=beta,
        png_fix=png_fix,
    )


async def recognize_captcha_vlm(image: bytes) -> str:
    return await query_vlm(image, CAPTCHA_PROMPT)


async def _try_vlm(image: bytes) -> tuple[str | None, str | None, bool]:
    try:
        return await recognize_captcha_vlm(image), None, False
    except VlmError as exc:
        return None, str(exc), True
    except Exception as exc:
        return None, vlm_failure_reason(exc), True


async def recognize_captcha_with_mode(
    image: bytes,
    *,
    mode: CaptchaMode = "ddddocr",
    beta: bool = False,
    png_fix: bool = False,
) -> dict[str, Any]:
    if mode not in CAPTCHA_MODES:
        raise ValueError(
            f"Invalid mode {mode!r}; expected one of: ddddocr, vlm, both"
        )

    if mode == "ddddocr":
        text = await recognize_captcha(image, beta=beta, png_fix=png_fix)
        return {
            "mode": mode,
            "text": text,
        }

    if mode == "vlm":
        vlm_text, vlm_error, vlm_fallback = await _try_vlm(image)
        if vlm_fallback:
            ddddocr_text = await recognize_captcha(
                image,
                beta=beta,
                png_fix=png_fix,
            )
            return {
                "mode": mode,
                "text": ddddocr_text,
                "ddddocr_text": ddddocr_text,
                "vlm_fallback": True,
                "vlm_error": vlm_error,
                "message": VLM_FALLBACK_MESSAGE,
            }
        return {
            "mode": mode,
            "text": vlm_text,
            "vlm_text": vlm_text,
        }

    # mode == "both"
    ddddocr_text, vlm_result = await asyncio.gather(
        recognize_captcha(image, beta=beta, png_fix=png_fix),
        _try_vlm(image),
    )
    vlm_text, vlm_error, vlm_fallback = vlm_result
    result: dict[str, Any] = {
        "mode": mode,
        "ddddocr_text": ddddocr_text,
        "text": vlm_text if not vlm_fallback else ddddocr_text,
    }
    if vlm_fallback:
        result.update(
            {
                "vlm_fallback": True,
                "vlm_error": vlm_error,
                "message": VLM_FALLBACK_MESSAGE,
            }
        )
    else:
        result["vlm_text"] = vlm_text
    return result
