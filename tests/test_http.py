import httpx
import pytest

from baneh_mcp import http

pytestmark = pytest.mark.anyio


def serve(*responses):
    calls = []

    def handler(request):
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    http.set_transport(httpx.MockTransport(handler))
    return calls


async def test_rest_returns_body_and_total():
    serve(httpx.Response(200, json=[1], headers={"X-WP-Total": "9191"}))
    assert await http.rest("wc/store/v1/products") == ([1], 9191)


async def test_retries_5xx_then_succeeds_and_gives_up():
    calls = serve(httpx.Response(503), httpx.Response(200, json={"ok": 1}))
    assert (await http.rest("x"))[0] == {"ok": 1} and len(calls) == 2
    calls = serve(httpx.Response(500))
    with pytest.raises(http.ApiError, match="server error"):
        await http.rest("x")
    assert len(calls) == 3


async def test_403_is_not_retried_and_404_message():
    calls = serve(httpx.Response(403, text="no"))
    with pytest.raises(http.ApiError, match="blocked") as e:
        await http.rest("x")
    assert e.value.status == 403 and len(calls) == 1
    serve(httpx.Response(404, json={"message": "bad id"}))
    with pytest.raises(http.ApiError, match="Not found"):
        await http.rest("x")


async def test_400_includes_site_message_and_non_json_fails():
    serve(httpx.Response(400, json={"message": "invalid orderby"}))
    with pytest.raises(http.ApiError, match="invalid orderby"):
        await http.rest("x")
    serve(httpx.Response(200, text="<html>"))
    with pytest.raises(http.ApiError, match="non-JSON"):
        await http.rest("x")


async def test_timeout_and_proxy_env(monkeypatch):
    def boom(request):
        raise httpx.ReadTimeout("slow")

    http.set_transport(httpx.MockTransport(boom))
    with pytest.raises(http.ApiError, match="did not answer"):
        await http.rest("x")
    monkeypatch.setenv("BANEH_MCP_PROXY", " http://a:1 , http://b:2 ")
    assert http._proxies() == ["http://a:1", "http://b:2"]


async def test_cached_reuses_value():
    n = 0

    async def make():
        nonlocal n
        n += 1
        return n

    assert [await http.cached("k", 60, make), await http.cached("k", 60, make)] == [1, 1]
