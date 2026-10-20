import httpx
import pytest

from baneh_mcp import catalog
from baneh_mcp.catalog import card

from .conftest import fixture

pytestmark = pytest.mark.anyio
P = "/wp-json/wc/store/v1/products"


def shop(items, total=None):
    """Fake products route: `include=` calls answer with image fixtures, everything else with `items`."""
    images = {p["id"]: p for p in fixture("products_images.json")}

    def handler(request):
        if "include" in request.url.params:
            ids = [int(i) for i in request.url.params["include"].split(",")]
            return httpx.Response(200, json=[images[i] for i in ids if i in images])
        return httpx.Response(200, json=items, headers={"X-WP-Total": str(len(items) if total is None else total)})

    return handler


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def test_card_toman_and_junk_prices():
    items = {p["id"]: p for p in fixture("products.json")["items"]}
    c = card(items[69045])
    assert c["final_price"] == 187300000 and c["in_stock"] and c["rating"] == 5.0
    assert c["url"].startswith("https://baaneeh.com/") and c["image"] is None
    assert "regular_price" not in c and "discount_pct" not in c
    zero = next(p for p in items.values() if p["prices"]["price"] == "0")
    assert card(zero)["final_price"] is None


def test_card_discount_and_range():
    p = {"id": 1, "name": "x", "prices": {"price": "800", "regular_price": "1000", "price_range": None}}
    assert card(p)["discount_pct"] == 20 and card(p)["regular_price"] == 1000
    p["prices"]["price_range"] = {"min_amount": "800", "max_amount": "900"}
    assert card(p)["max_price"] == 900


async def test_search_passes_filters_and_returns_cards(api, client):
    data = fixture("products.json")
    api[P] = shop(data["items"][:3], data["total"])
    out = await call(client, "bn_search", {"query": "تلویزیون", "min_price": 1000, "limit": 3})
    assert api.params(0) == {
        "search": "تلویزیون", "stock_status": "instock", "min_price": "1000", "per_page": "3", "page": "1",
        "_fields": catalog.LIST_FIELDS,
    }  # fmt: skip
    assert out["total"] == data["total"] and [p["id"] for p in out["products"]] == [p["id"] for p in data["items"][:3]]
    assert all(p["image"].startswith("https://baaneeh.com/wp-content/") for p in out["products"])


async def test_search_cheapest_sorts_here_and_skips_unpriced(api, client):
    api[P] = shop(fixture("products.json")["items"])
    out = await call(client, "bn_search", {"query": "tv", "sort": "cheapest", "limit": 10})
    priced = [p for p in fixture("products.json")["items"] if p["prices"]["price"] != "0"]
    prices = [p["final_price"] for p in out["products"]]
    assert prices == sorted(prices) and prices[0] > 0 and len(prices) == len(priced)  # price-0 items are left out
    assert out["scanned"] == len(fixture("products.json")["items"]) and "orderby" not in api.params(0)


async def test_find_cheapest_title_filter_and_phrase_fallback(api, client):
    phone = fixture("products_phone.json")

    def handler(request):
        q = request.url.params.get("search")
        if q == "گوشی اپل":
            return httpx.Response(200, json=[], headers={"X-WP-Total": "0"})
        return shop(phone)(request)

    api[P] = handler
    out = await call(client, "bn_find_cheapest", {"query": "گوشی اپل", "in_stock_only": False})
    assert api.params(1)["search"] == "گوشی"  # whole phrase found nothing, retried with the longest word
    titles = [o["title"] for o in out["offers"]]
    assert titles and all("اپل" in t and "گوشی" in t for t in titles)
    prices = [o["final_price"] for o in out["offers"]]
    assert prices == sorted(prices) and out["complete"]


async def test_browse_brand_category_and_requires_a_filter(api, client):
    api[P] = shop([])
    await call(client, "bn_browse", {"category": "tv", "brand": "lg", "max_price": 90000000})
    assert api.params(0)["attributes[0][slug]"] == "lg" and api.params(0)["category"] == "tv"
    result = await client.call_tool("bn_browse", {})
    assert result.is_error and "category" in result.content[0].text


async def test_categories_top_level_children_and_query(api, client):
    api[P + "/categories"] = (fixture("categories.json")["items"], 100)
    top = await call(client, "bn_categories", {"limit": 5})
    assert top["categories"] and all("parent" not in c for c in top["categories"])
    assert 17 not in {c["slug"] for c in top["categories"]} and "default-category" not in str(top)
    counts = [c["count"] for c in top["categories"]]
    assert counts == sorted(counts, reverse=True)
    kids = await call(client, "bn_categories", {"parent": top["categories"][0]["slug"]})
    assert all(c["parent"] == top["categories"][0]["slug"] for c in kids["categories"])
    hit = await call(client, "bn_categories", {"query": "iron"})
    assert hit["categories"] and all("iron" in c["slug"] or "اتو" in c["name"] for c in hit["categories"])
    assert len(api.calls) == 1  # cached after the first call


async def test_brands_query(api, client):
    api[P + "/attributes/1/terms"] = (fixture("brands.json")["items"], 100)
    out = await call(client, "bn_brands", {"query": "aeg"})
    assert out["brands"][0]["slug"] == "aeg" and out["brands"][0]["count"] > 0
