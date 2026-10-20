"""Shared async HTTP client for baaneeh.com.

Every tool goes through `rest`, which calls the WooCommerce Store API (or WordPress REST) under /wp-json/.
`_send` caps concurrency, retries timeouts, dropped connections, 429 and 5xx (never 403) with jittered backoff and
turns HTTP failures into `ToolError` messages the model can act on. The wire format is a Chrome impersonation
(curl_cffi). Only GET requests exist here: the cart and checkout routes are never called.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://baaneeh.com"

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/",
}

MAX_CONCURRENCY = 2
JITTER = (0.1, 0.4)  # seconds before each upstream call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
RETRY_DELAY = 0.5

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_cache: dict[Any, tuple[float, Any]] = {}


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client and the cache."""
    global _transport, _client, _limit, _proxy_index
    _transport, _client, _limit, _proxy_index = transport, None, None, 0
    _cache.clear()


async def cached(key: Any, ttl: float, make: Callable[[], Awaitable[Any]]) -> Any:
    """Return make()'s result, reused for `ttl` seconds per key. Only for results nobody mutates."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = await make()
    _cache[key] = (time.monotonic(), value)
    return value


def _proxies() -> list[str]:
    """BANEH_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("BANEH_MCP_PROXY", "").split(",") if p.strip()]


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a connect error; the next call rebuilds the client.

    Only the client that failed may rotate. The old client is closed late because other requests may still use it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(70)  # longer than the 60 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # Direct connections work; a proxy is only used when the user opts in with BANEH_MCP_PROXY.
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or AsyncCurlTransport(
                impersonate="chrome",
                default_headers=True,
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=60,  # the shop answers in 3-8 s and big pages are slower
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=True,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def rest(route: str, params: dict[str, Any] | None = None) -> tuple[Any, int | None]:
    """GET /wp-json/<route>; returns (parsed body, X-WP-Total header or None)."""
    r = await _send(f"{BASE}/wp-json/{route}", params=params)
    try:
        data = r.json()
    except ValueError as e:
        raise ApiError(f"baaneeh.com returned a non-JSON response for {route} (HTTP {r.status_code}).") from e
    total = r.headers.get("X-WP-Total")
    return data, int(total) if total and total.isdigit() else None


async def _send(url: str, **kwargs: Any) -> httpx.Response:
    host = httpx.URL(BASE).host
    retries = 0
    while True:
        client, limit = _get_client()
        wait = None
        try:
            async with limit:
                await asyncio.sleep(random.uniform(*JITTER))
                r = await client.get(url, **kwargs)
        except httpx.TimeoutException as e:
            err = ApiError(f"{host} did not answer in time. Try again in a moment.")
            err.__cause__ = e
        except httpx.TransportError as e:
            # The server sometimes closes a keep-alive connection; a retry works.
            if isinstance(e, httpx.ConnectError | httpx.ProxyError):
                _next_proxy(client)
            err = ApiError(
                f"Could not reach {host} ({type(e).__name__}). Check the internet connection, or set BANEH_MCP_PROXY."
            )
            err.__cause__ = e
        else:
            if r.status_code != 429 and r.status_code < 500:
                if r.status_code >= 400:
                    raise ApiError(_status_message(r), r.status_code)
                return r
            err = ApiError(_status_message(r), r.status_code)
            wait = _retry_after(r)
        if retries == MAX_RETRIES:
            raise err
        wait = wait if wait is not None else RETRY_DELAY * 2**retries * random.uniform(1, 1.5)
        retries += 1
        await asyncio.sleep(min(wait, MAX_RETRY_WAIT))


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


def _status_message(r: httpx.Response) -> str:
    code = r.status_code
    if code == 403:
        return "baaneeh.com blocked the request (HTTP 403). Turn off VPN/proxy or set BANEH_MCP_PROXY."
    if code == 404:
        return "Not found on baaneeh.com (HTTP 404). Check the product id or category slug."
    if code == 429:
        return "baaneeh.com is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"baaneeh.com had a server error (HTTP {code}). Try again later."
    try:  # WordPress REST errors: {"code": "rest_invalid_param", "message": "..."}
        detail = r.json().get("message")
    except (ValueError, AttributeError):
        detail = None
    return f"baaneeh.com rejected the request (HTTP {code}){': ' + str(detail)[:300] if detail else '.'}"
