from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


def tool_error(exc: BaseException) -> dict[str, Any]:
    return {
        "error": str(exc),
        "error_type": type(exc).__name__,
    }


def wrap_tool_result(
    fn: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T | dict[str, Any]]]:
    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            return tool_error(exc)

    return wrapper
