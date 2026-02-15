"""Retries, backoff, JSON parsing helpers, and time utilities."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import httpx

P = ParamSpec("P")

logger = logging.getLogger(__name__)

T = TypeVar("T")


def utc_now_iso8601() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


def exponential_backoff(base: float = 1.0, factor: float = 2.0, attempt: int = 0) -> float:
    """Compute sleep seconds for exponential backoff."""
    return base * (factor ** attempt)


def is_transient_error(exc: BaseException) -> bool:
    """Return True if error is transient (network, 5xx) and worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError))


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """
    Extract a JSON object from text (handles markdown code blocks and trailing text).
    Returns None if no valid JSON found.
    """
    text = text.strip()
    # Try parsing entire text first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in code block
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find first { ... } block
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


async def retry_async(
    coro_func: Callable[P, Awaitable[T]],
    *args: P.args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    is_transient: Callable[[BaseException], bool] = is_transient_error,
    **kwargs: P.kwargs,
) -> T:
    """Execute async callable with exponential backoff on transient errors."""
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except BaseException as e:
            last_exc = e
            if attempt < max_retries and is_transient(e):
                delay = exponential_backoff(base_delay, 2.0, attempt)
                logger.warning("Transient error (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, max_retries + 1, delay, type(e).__name__)
                await _async_sleep(delay)
            else:
                raise
    raise last_exc


def retry_sync(
    fn: Callable[P, T],
    *args: P.args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    is_transient: Callable[[BaseException], bool] = is_transient_error,
    **kwargs: P.kwargs,
) -> T:
    """Execute sync callable with exponential backoff on transient errors."""
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except BaseException as e:
            last_exc = e
            if attempt < max_retries and is_transient(e):
                delay = exponential_backoff(base_delay, 2.0, attempt)
                logger.warning("Transient error (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, max_retries + 1, delay, type(e).__name__)
                time.sleep(delay)
            else:
                raise
    raise last_exc


async def _async_sleep(seconds: float) -> None:
    """Async sleep helper (avoids importing asyncio at top level for sync paths)."""
    import asyncio
    await asyncio.sleep(seconds)
