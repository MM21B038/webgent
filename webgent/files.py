from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Literal

UploadSource = Literal["inline", "path"]


def sanitize_filename(filename: str) -> str:
    name = filename.strip()
    if not name or name in {".", ".."}:
        raise ValueError("filename must not be empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("filename must not contain path separators")
    if Path(name).suffix == "":
        raise ValueError("filename must include an extension, e.g. notes.txt")
    return name


def validate_absolute_filepath(filepath: str) -> str:
    path = Path(filepath)
    if not path.is_absolute():
        raise ValueError(f"filepath must be absolute: {filepath!r}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"file not found: {filepath!r}")
    return str(resolved)


def resolve_upload_files(
    *,
    filepath: str | None = None,
    filepaths: list[str] | None = None,
    text: str | None = None,
    filename: str | None = None,
) -> tuple[list[str | dict[str, Any]], list[str], UploadSource]:
    has_path_input = filepath is not None or filepaths is not None
    has_inline_input = text is not None or filename is not None

    if has_path_input and has_inline_input:
        raise ValueError("Provide either filepath/filepaths or text+filename, not both")
    if not has_path_input and not has_inline_input:
        raise ValueError("Provide filepath, filepaths, or text+filename")

    if has_inline_input:
        if text is None or filename is None:
            raise ValueError("text and filename must both be provided together")
        safe_name = sanitize_filename(filename)
        mime_type, _ = mimetypes.guess_type(safe_name)
        payload: dict[str, Any] = {
            "name": safe_name,
            "mimeType": mime_type or "application/octet-stream",
            "buffer": text.encode("utf-8"),
        }
        return [payload], [safe_name], "inline"

    if filepath is not None and filepaths is not None:
        raise ValueError("Provide either filepath or filepaths, not both")

    if filepaths is not None:
        if not filepaths:
            raise ValueError("filepaths must contain at least one absolute filepath")
        paths = [validate_absolute_filepath(path) for path in filepaths]
        return paths, [Path(path).name for path in paths], "path"

    assert filepath is not None
    path = validate_absolute_filepath(filepath)
    return [path], [Path(path).name], "path"
