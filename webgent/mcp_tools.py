from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import mcp.types as mt
from pydantic import ValidationError as PydanticValidationError

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

P = ParamSpec("P")
T = TypeVar("T")


def tool_error(
    exc: BaseException,
    *,
    tool: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "error": str(exc),
        "error_type": type(exc).__name__,
    }
    if tool is not None:
        result["tool"] = tool
    hint = getattr(exc, "hint", None)
    if hint:
        result["hint"] = hint
    if isinstance(exc, PydanticValidationError):
        result["validation_errors"] = exc.errors(include_url=False)
    return result


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


class ToolErrorAsResponseMiddleware(Middleware):
    """Return tool failures as structured responses instead of MCP errors."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: Callable[..., Awaitable[ToolResult]],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except Exception as exc:
            return ToolResult(
                structured_content=tool_error(
                    exc,
                    tool=context.message.name,
                ),
            )
