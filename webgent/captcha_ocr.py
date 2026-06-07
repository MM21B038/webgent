from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import ddddocr


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
