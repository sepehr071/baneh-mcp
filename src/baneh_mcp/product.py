"""One product: details and reviews."""

from __future__ import annotations

import html
import re
from typing import Annotated, Any

from pydantic import Field

from .catalog import JUNK_CATEGORIES, PRODUCTS, card
from .http import rest
from .registry import tool

ProductId = Annotated[
    int, Field(ge=1, description="Product id from bn_search, bn_find_cheapest or bn_browse, e.g. 69045.")
]
JUNK_ATTRIBUTES = {"pa_a-id-up"}  # 'ID آپدیت': the shop's internal update id, set on nearly every product


def _text(fragment: str | None) -> str:
    """Plain text of an HTML fragment, whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _clip(text: str, n: int | None) -> str:
    """Cap untrusted site text; the marker shows it was cut. n=None keeps it whole."""
    return text if n is None or len(text) <= n else text[: n - 1].rstrip() + "…"


@tool("Get product details")
async def bn_product(product_id: ProductId) -> dict[str, Any]:
    """Get one product: price (Toman), stock, rating, brand, categories, spec attributes, highlights, description, images.

    Use after a search or browse to check details of one id. Variable products list their variations
    (options only; the shop publishes no per-variation price or stock). Next: bn_reviews for buyer opinions.
    """
    p, _ = await rest(f"{PRODUCTS}/{product_id}")
    attrs = [a for a in p.get("attributes") or [] if a["taxonomy"] not in JUNK_ATTRIBUTES and a.get("terms")]
    brand = next((a["terms"][0]["name"] for a in attrs if a["taxonomy"] == "pa_manufacturer"), None)
    out = {
        **card(p),
        "sku": p.get("sku") or None,
        "brand": brand,
        "stock": _text(p.get("stock_availability", {}).get("text")) or None,
        "on_backorder": p.get("is_on_backorder") or None,
        "categories": [
            {"slug": c["slug"], "name": c["name"]} for c in p.get("categories") or [] if c["id"] not in JUNK_CATEGORIES
        ][:6],
        "attributes": [{"name": a["name"], "values": [t["name"] for t in a["terms"]][:10]} for a in attrs],
        "highlights": [
            t
            for t in (_text(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", p.get("short_description") or "", re.S))
            if t
        ][:20],
        "description": _clip(_text(p.get("description")), 1500) or None,
        "images": [i["src"] for i in p.get("images") or [] if i.get("src")][:5],
        "variations": [
            {"id": v["id"], "options": {a["name"]: a["value"] for a in v.get("attributes") or []}}
            for v in p.get("variations") or []
        ][:30]
        or None,
    }
    return {k: v for k, v in out.items() if v not in (None, [])}


@tool("Get product reviews")
async def bn_reviews(
    product_id: ProductId,
    limit: Annotated[int, Field(ge=1, le=30, description="Max reviews to return.")] = 10,
    page: Annotated[int, Field(ge=1, le=100, description="Result page of `limit`-sized pages.")] = 1,
    full_text: Annotated[
        bool, Field(description="Return whole review texts instead of cutting them at 400 characters.")
    ] = False,
) -> dict[str, Any]:
    """Get buyer reviews of one product, newest first: rating 1-5, author, date, text.

    Use to check quality or complaints. Many products carry one long generated 'summary of buyer opinions' by
    'دیدگاه خریداران' instead of real reviews; treat those as marketing text. Dates are Gregorian.
    """
    data, total = await rest(f"{PRODUCTS}/reviews", {"product_id": product_id, "per_page": limit, "page": page})
    return {
        "total": total or 0,
        "page": page,
        "reviews": [
            {
                "author": r.get("reviewer"),
                "date": (r.get("date_created") or "")[:10] or None,
                "rating": r.get("rating") or None,
                "verified_buyer": bool(r.get("verified")),
                "text": _clip(_text(r.get("review")), None if full_text else 400),
            }
            for r in data
        ],
    }
