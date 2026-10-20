import pytest

from .conftest import fixture

pytestmark = pytest.mark.anyio
P = "/wp-json/wc/store/v1/products"


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_product(api, client):
    api[P + "/69045"] = fixture("product_69045.json")
    p = await call(client, "bn_product", {"product_id": 69045})
    assert p["final_price"] == 187300000 and p["brand"] == "شیائومی" and p["in_stock"]
    assert p["highlights"] and "<" not in p["description"] and len(p["description"]) <= 1500
    assert [c["slug"] for c in p["categories"]][0] == "xiaomi" and "default-category" not in str(p["categories"])
    assert p["images"] and all(i.startswith("https://") for i in p["images"])
    assert "variations" not in p and "ID آپدیت" not in str(p["attributes"])


async def test_variable_product_lists_variation_options(api, client):
    api[P + "/3533"] = fixture("product_variable_3533.json")
    p = await call(client, "bn_product", {"product_id": 3533})
    assert p["in_stock"] is False and p["variations"][0]["id"] and p["variations"][0]["options"]


async def test_unknown_product_is_a_tool_error(api, client):
    result = await client.call_tool("bn_product", {"product_id": 1})
    assert result.is_error and "404" in result.content[0].text


async def test_reviews_clip_and_shape(api, client):
    data = fixture("reviews_6663.json")
    api[P + "/reviews"] = (data["items"], data["total"])
    out = await call(client, "bn_reviews", {"product_id": 6663, "limit": 5})
    assert api.params()["product_id"] == "6663" and out["total"] == data["total"]
    r = out["reviews"][0]
    assert r["rating"] == 5 and r["date"] == "2026-03-13" and "<" not in r["text"]
    assert set(r) == {"author", "date", "rating", "verified_buyer", "text"}


async def test_reviews_long_text_clipped_unless_full(api, client):
    item = {**fixture("reviews_69045.json")["items"][0], "review": "<p>" + "ب" * 1000 + "</p>"}
    api[P + "/reviews"] = ([item], 1)
    short = await call(client, "bn_reviews", {"product_id": 1})
    full = await call(client, "bn_reviews", {"product_id": 1, "full_text": True})
    assert len(short["reviews"][0]["text"]) == 400 and len(full["reviews"][0]["text"]) == 1000
