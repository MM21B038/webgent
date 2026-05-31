from __future__ import annotations

import uuid
from typing import Any, Literal

from playwright.async_api import Page

from webgent.config import MEDIA_DIR
from webgent.snapshot import normalize_ref, ref_locator

ScreenshotMode = Literal["viewport", "full_page", "element"]
ImageType = Literal["png", "jpeg"]


async def capture_screenshot(
    page: Page,
    *,
    ref: str | None = None,
    full_page: bool = False,
    image_type: ImageType = "png",
    quality: int | None = None,
) -> tuple[bytes, ScreenshotMode]:
    screenshot_kwargs: dict[str, Any] = {"type": image_type}
    if quality is not None and image_type == "jpeg":
        screenshot_kwargs["quality"] = quality

    if ref is not None:
        data = await ref_locator(page, ref).screenshot(**screenshot_kwargs)
        return data, "element"

    if full_page:
        data = await page.screenshot(full_page=True, **screenshot_kwargs)
        return data, "full_page"

    data = await page.screenshot(full_page=False, **screenshot_kwargs)
    return data, "viewport"


async def screenshot_metadata(
    page: Page,
    page_id: str,
    *,
    mode: ScreenshotMode,
    ref: str | None = None,
    image_type: ImageType = "png",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "mode": mode,
        "image_type": image_type,
        "mime_type": f"image/{image_type}",
    }
    if ref is not None:
        metadata["ref"] = normalize_ref(ref)
    return metadata


def save_screenshot(
    image_data: bytes,
    metadata: dict[str, Any],
    *,
    image_type: ImageType = "png",
) -> dict[str, Any]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{image_type}"
    path = MEDIA_DIR / filename
    path.write_bytes(image_data)
    return {
        **metadata,
        "filename": filename,
        "path": str(path.resolve()),
    }
