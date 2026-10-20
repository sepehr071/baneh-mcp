import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def assert_cards(items):
    assert items and all(i["image"].startswith("https://baaneeh.com/wp-content/") for i in items)
    assert all(i["url"].startswith("https://baaneeh.com/") and i["title"] for i in items)


async def test_bn_search(client):
    data = await call(client, "bn_search", {"query": "تلویزیون", "limit": 5})
    assert data["total"] > 100 and len(data["products"]) == 5
    assert all(p["in_stock"] for p in data["products"])
    assert_cards(data["products"])


async def test_bn_search_sorted_over_all_matches(client):
    data = await call(client, "bn_search", {"query": "iphone", "in_stock_only": False, "sort": "cheapest", "limit": 5})
    prices = [p["final_price"] for p in data["products"]]
    assert data["scanned"] > 20 and prices == sorted(prices) and prices[0] > 0


async def test_bn_find_cheapest(client):
    data = await call(client, "bn_find_cheapest", {"query": "تلویزیون سامسونگ", "min_price": 1000000, "limit": 8})
    prices = [o["final_price"] for o in data["offers"]]
    assert len(prices) >= 3 and prices == sorted(prices) and prices[0] >= 1000000
    assert all("سامسونگ" in o["title"] and "تلویزیون" in o["title"] for o in data["offers"])
    assert_cards(data["offers"])


async def test_bn_browse(client):
    args = {"category": "tv", "brand": "lg", "sort": "cheapest", "max_price": 150000000, "limit": 6}
    data = await call(client, "bn_browse", args)
    prices = [p["final_price"] for p in data["products"]]
    assert prices and prices == sorted(prices) and prices[-1] <= 150000000
    assert all("ال جی" in p["title"] for p in data["products"])
    assert_cards(data["products"])


async def test_bn_categories_and_brands(client):
    top = await call(client, "bn_categories", {})
    slugs = {c["slug"] for c in top["categories"]}
    assert {"tv", "home-appliances"} <= slugs
    kids = await call(client, "bn_categories", {"parent": "home-appliances"})
    assert len(kids["categories"]) > 5
    brands = await call(client, "bn_brands", {"query": "lg"})
    assert any(b["slug"] == "lg" and b["count"] > 50 for b in brands["brands"])


async def test_bn_product_and_reviews(client):
    found = await call(client, "bn_search", {"query": "تلویزیون", "limit": 1})
    pid = found["products"][0]["id"]
    product = await call(client, "bn_product", {"product_id": pid})
    assert product["id"] == pid and product["final_price"] > 0 and product["images"] and product["categories"]
    reviews = await call(client, "bn_reviews", {"product_id": pid, "limit": 3})
    assert reviews["total"] >= 1 and 1 <= len(reviews["reviews"]) <= 3
    assert all(len(r["text"]) <= 400 for r in reviews["reviews"])
