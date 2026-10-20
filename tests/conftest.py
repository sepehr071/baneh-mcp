import json
from pathlib import Path

import httpx
import pytest
from mcp import Client

from baneh_mcp import http
from baneh_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    """A recorded response (parsed JSON)."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_http_client(monkeypatch):
    """The shared httpx client is bound to one event loop; each test gets a new loop."""
    monkeypatch.setattr(http, "RETRY_DELAY", 0)
    monkeypatch.setattr(http, "JITTER", (0, 0))
    http.set_transport(None)
    yield
    http.set_transport(None)


@pytest.fixture
def api():
    """Route table for a fake baaneeh.com.

    Keys are URL paths (api["/wp-json/wc/store/v1/products"]). Values: a dict/list (JSON), a tuple
    (body, total) that also sets X-WP-Total, or a callable(request) -> httpx.Response. Unknown keys return 404.
    Every request is appended to api.calls.
    """

    class Routes(dict):
        calls: list[httpx.Request]

        def params(self, i: int = -1) -> dict[str, str]:
            return dict(self.calls[i].url.params)

    routes = Routes()
    routes.calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        routes.calls.append(request)
        target = routes.get(request.url.path)
        if target is None:
            return httpx.Response(404, json={"code": "woocommerce_rest_product_invalid_id", "message": "nope"})
        if callable(target):
            return target(request)
        if isinstance(target, tuple):
            return httpx.Response(200, json=target[0], headers={"X-WP-Total": str(target[1])})
        return httpx.Response(200, json=target)

    http.set_transport(httpx.MockTransport(handler))
    return routes


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        call_tool = c.call_tool

        async def compact_as_structured(*args, **kwargs):
            result = await call_tool(*args, **kwargs)
            if not result.is_error:
                result.structured_content = json.loads(result.content[0].text)
            return result

        c.call_tool = compact_as_structured
        yield c
