"""Finding products: search, cheapest offers, category / brand listings, categories, brands."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .http import cached, rest
from .registry import tool

PRODUCTS = "wc/store/v1/products"
# _fields keeps a 100-product page at about 50 KB instead of 14 MB. Images (srcsets, 7 KB each) are not part of it:
# `_fields=images.src` returns nothing, so cards get their image from a second call for just the products shown.
LIST_FIELDS = (
    "id,name,permalink,sku,type,prices.price,prices.regular_price,prices.price_range,is_in_stock,"
    "low_stock_remaining,average_rating,review_count"
)
PAGE = 100  # largest per_page the Store API accepts
MAX_PAGES = 20  # 2,000 products: more than the whole in-stock catalog (about 1,900)
POOL_TTL = 300
JUNK_CATEGORIES = {17, 62597}  # 'فروشگاه خرید و قیمت بانه' (default, holds everything) and 'ناموجود' (out of stock)

Query = Annotated[
    str,
    Field(
        min_length=2,
        max_length=100,
        description="Product name or keyword, Persian or English, e.g. 'تلویزیون ال جی 55' or 'iphone'.",
    ),
]
CategorySlug = Annotated[
    str | None,
    Field(
        pattern=r"^[a-z0-9-]{2,80}$",
        description="Category slug from bn_categories, e.g. 'tv' or 'air-conditioners-cooler'.",
    ),
]
BrandSlug = Annotated[
    str | None,
    Field(pattern=r"^[a-z0-9-]{2,60}$", description="Brand slug from bn_brands, e.g. 'lg' or 'xiaomi'."),
]
Sort = Annotated[
    Literal["newest", "cheapest", "most_expensive", "top_rated"],
    Field(
        description="Order. 'newest' is the shop's own order (latest added first); the others are sorted here over all matches."
    ),
]
InStockOnly = Annotated[
    bool, Field(description="Only items in stock. Out-of-stock items are mostly discontinued, with stale prices.")
]
MinPrice = Annotated[int | None, Field(ge=0, description="Minimum price in Toman, e.g. 5000000.")]
MaxPrice = Annotated[int | None, Field(ge=1, description="Maximum price in Toman, e.g. 20000000.")]
Limit = Annotated[int, Field(ge=1, le=50, description="Max products to return.")]


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, str) and v.isdigit() else None


def card(p: dict[str, Any]) -> dict[str, Any]:
    """A listing card from a Store API product (prices are already Toman). Null fields are dropped."""
    pr = p.get("prices") or {}
    rng = pr.get("price_range") or {}
    price = _int(rng.get("min_amount")) or _int(pr.get("price")) or None  # '0' means no price set
    top = _int(rng.get("max_amount"))
    regular = _int(pr.get("regular_price"))
    card = {
        "id": p["id"],
        "title": p["name"],
        "final_price": price,
        "max_price": top if top and top != price else None,
        # the shop also stores a bogus 'regular_price' of 0 or below the price on some items
        "regular_price": regular if price and regular and regular > price else None,
        "discount_pct": round(100 * (regular - price) / regular) if price and regular and regular > price else None,
        "in_stock": bool(p.get("is_in_stock")),
        "low_stock": p.get("low_stock_remaining") or None,
        "rating": float(p["average_rating"]) if p.get("review_count") and p.get("average_rating") else None,
        "reviews": p.get("review_count") or None,
        "image": next((i["src"] for i in p.get("images") or [] if i.get("src")), None),
        "url": p.get("permalink"),
    }
    return {k: v for k, v in card.items() if v is not None or k in ("image", "url", "final_price")}


def _norm(s: str) -> str:
    """Lowercase, Arabic yeh/kaf to Persian, ZWNJ to space: titles mix both spellings."""
    return s.lower().translate({0x64A: 0x6CC, 0x643: 0x6A9, 0x200C: 0x20})


async def _fetch(params: dict[str, Any], pages: int) -> tuple[int, list[dict[str, Any]]]:
    """(X-WP-Total, product cards) for up to `pages` pages of 100, fetched 2 at a time; cached for 5 minutes."""

    async def make() -> tuple[int, list[dict[str, Any]]]:
        base = {**params, "per_page": PAGE, "_fields": LIST_FIELDS}
        first, total = await rest(PRODUCTS, {**base, "page": 1})
        total = total or len(first)
        rest_pages = range(2, 1 + min(pages, -(-total // PAGE)))
        more = await asyncio.gather(*[rest(PRODUCTS, {**base, "page": n}) for n in rest_pages])
        return total, [card(p) for page in [first, *(m[0] for m in more)] for p in page]

    return await cached((tuple(sorted(params.items())), pages), POOL_TTL, make)


def _params(
    query: str | None, category: str | None, brand: str | None, in_stock_only: bool, lo: int | None, hi: int | None
) -> dict[str, Any]:
    p: dict[str, Any] = {}
    if query:
        p["search"] = query.strip()
    if category:
        p["category"] = category
    if brand:
        p["attributes[0][attribute]"] = "pa_manufacturer"
        p["attributes[0][slug]"] = brand
    if in_stock_only:
        p["stock_status"] = "instock"
    if lo:
        p["min_price"] = lo
    if hi:
        p["max_price"] = hi
    return p


def _sort(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "newest":
        return items
    if sort == "top_rated":
        return sorted(items, key=lambda c: (-(c.get("rating") or 0), -(c.get("reviews") or 0)))
    priced = [c for c in items if c["final_price"]]  # a price of 0 means 'call the shop', not the cheapest
    return sorted(priced, key=lambda c: c["final_price"], reverse=sort == "most_expensive")


async def _with_images(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill in `image` on the cards (one extra call for all of them)."""
    if not cards:
        return cards
    ids = ",".join(str(c["id"]) for c in cards)
    data, _ = await rest(PRODUCTS, {"include": ids, "per_page": len(cards), "_fields": "id,images"})
    src = {p["id"]: next((i["src"] for i in p["images"] if i.get("src")), None) for p in data}
    return [{**c, "image": src.get(c["id"])} for c in cards]


async def _list(params: dict[str, Any], sort: str, limit: int, page: int) -> dict[str, Any]:
    """Listing in the output shape of bn_search / bn_browse."""
    if sort == "newest":  # the shop's own order: ask for just the page wanted
        data, total = await rest(PRODUCTS, {**params, "per_page": limit, "page": page, "_fields": LIST_FIELDS})
        return {"total": total or 0, "page": page, "products": await _with_images([card(p) for p in data])}
    total, items = await _fetch(params, MAX_PAGES)
    items = _sort(items, sort)
    return {"total": total, "scanned": min(total, PAGE * MAX_PAGES), "products": await _with_images(items[:limit])}


@tool("Search products")
async def bn_search(
    query: Query,
    sort: Sort = "newest",
    in_stock_only: InStockOnly = True,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    limit: Limit = 15,
    page: Annotated[
        int, Field(ge=1, le=50, description="Result page of `limit`-sized pages (only for sort 'newest').")
    ] = 1,
) -> dict[str, Any]:
    """Search Baneh products by name in Persian or English, with price (Toman), stock and rating.

    Use to find products and their ids. A multi-word query must appear as a phrase in the title; for the lowest
    price of a product use bn_find_cheapest, which matches words in any order. Next: bn_product for one id.
    """
    params = _params(query, None, None, in_stock_only, min_price, max_price)
    return await _list(params, sort, limit, page)


@tool("Find cheapest product")
async def bn_find_cheapest(
    query: Query,
    in_stock_only: InStockOnly = True,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    limit: Limit = 15,
) -> dict[str, Any]:
    """Find the cheapest products whose title contains every word of the query, one list sorted by price (Toman).

    Use for the lowest price of X. Words may come in any order. Raise min_price to skip accessories and spare parts.
    Items without a price are skipped. complete=false means more matches exist than were scanned (2,000 cap).
    Check bn_product before buying: the same title can be a different model or size.
    """
    words = _norm(query).split()
    params = _params(query, None, None, in_stock_only, min_price, max_price)
    total, items = await _fetch(params, MAX_PAGES)
    if not items and len(words) > 1:  # the shop matches the whole phrase; fall back to the longest word
        params["search"] = max(query.split(), key=len)
        total, items = await _fetch(params, MAX_PAGES)
    items = [c for c in items if all(w in _norm(c["title"]) for w in words)]
    offers = _sort(items, "cheapest")
    return {"total_matches": total, "complete": total <= PAGE * MAX_PAGES, "offers": await _with_images(offers[:limit])}


@tool("Browse a category or brand")
async def bn_browse(
    category: CategorySlug = None,
    brand: BrandSlug = None,
    sort: Sort = "newest",
    in_stock_only: InStockOnly = True,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    limit: Limit = 15,
    page: Annotated[
        int, Field(ge=1, le=50, description="Result page of `limit`-sized pages (only for sort 'newest').")
    ] = 1,
) -> dict[str, Any]:
    """List products of a category and/or brand, optionally in a price range, sorted by price or rating.

    Use after bn_categories / bn_brands to see what a section holds, e.g. the cheapest in-stock LG TVs
    (category='tv', brand='lg', sort='cheapest'). Give at least one of category, brand or a price bound.
    """
    if not (category or brand or min_price or max_price):
        raise ToolError("Give a category, a brand or a price range; use bn_search for keywords.")
    params = _params(None, category, brand, in_stock_only, min_price, max_price)
    return await _list(params, sort, limit, page)


async def _all_categories() -> list[dict[str, Any]]:
    async def make() -> list[dict[str, Any]]:
        params = {"per_page": 100, "_fields": "id,name,slug,parent,count"}
        first, total = await rest(f"{PRODUCTS}/categories", {**params, "page": 1})
        more = await asyncio.gather(
            *[rest(f"{PRODUCTS}/categories", {**params, "page": n}) for n in range(2, 1 + -(-(total or 0) // 100))]
        )
        return [c for page in [first, *(m[0] for m in more)] for c in page if c["id"] not in JUNK_CATEGORIES]

    return await cached("categories", 3600, make)


@tool("List categories")
async def bn_categories(
    query: Annotated[
        str | None,
        Field(max_length=60, description="Only categories whose name or slug contains this, e.g. 'یخچال' or 'tv'."),
    ] = None,
    parent: Annotated[
        str | None,
        Field(
            pattern=r"^[a-z0-9-]{2,80}$",
            description="Slug of a parent category to list its subcategories, e.g. 'home-appliances'.",
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Max categories to return.")] = 40,
) -> dict[str, Any]:
    """List shop categories with slug and product count, biggest first.

    Without arguments returns the top-level sections. Use `parent` to open one, or `query` to search all of them.
    Counts include out-of-stock products. The shop has hundreds of SEO-style subcategories under 'tv'
    (e.g. 'best tv', 'tv price'); they hold the same products. Pass a slug to bn_browse as `category`.
    """
    cats = await _all_categories()
    by_id = {c["id"]: c for c in cats}
    if parent:
        pid = next((c["id"] for c in cats if c["slug"] == parent), None)
        cats = [c for c in cats if c["parent"] == pid]
    elif query:
        q = _norm(query)
        cats = [c for c in cats if q in _norm(c["name"]) or q in c["slug"]]
    else:
        cats = [c for c in cats if c["parent"] == 0]
    cats.sort(key=lambda c: -c["count"])
    return {
        "total": len(cats),
        "categories": [
            {
                "slug": c["slug"],
                "name": c["name"],
                "count": c["count"],
                **({"parent": by_id[c["parent"]]["slug"]} if c["parent"] in by_id else {}),
            }
            for c in cats[:limit]
        ],
    }


async def _brands() -> list[dict[str, Any]]:
    async def make() -> list[dict[str, Any]]:
        route = f"{PRODUCTS}/attributes/1/terms"  # pa_manufacturer, the 'brand' attribute of TVs and appliances
        first, total = await rest(route, {"per_page": 100, "page": 1})
        more = await asyncio.gather(
            *[rest(route, {"per_page": 100, "page": n}) for n in range(2, 1 + -(-(total or 0) // 100))]
        )
        return [b for page in [first, *(m[0] for m in more)] for b in page]

    return await cached("brands", 3600, make)


@tool("List brands")
async def bn_brands(
    query: Annotated[
        str | None,
        Field(max_length=60, description="Only brands whose name or slug contains this, e.g. 'سامسونگ' or 'bosch'."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Max brands to return.")] = 50,
) -> dict[str, Any]:
    """List brands (about 150, e.g. LG, Samsung, Bosch, Xiaomi) with slug and product count, biggest first.

    Use to get the slug for bn_browse's `brand`. Counts include out-of-stock products.
    Brands exist only for the products tagged with the shop's brand attribute (not every tool or phone).
    """
    brands = await _brands()
    if query:
        q = _norm(query)
        brands = [b for b in brands if q in _norm(b["name"]) or q in b["slug"]]
    brands = sorted(brands, key=lambda b: -b["count"])
    return {
        "total": len(brands),
        "brands": [{"slug": b["slug"], "name": b["name"], "count": b["count"]} for b in brands[:limit]],
    }
