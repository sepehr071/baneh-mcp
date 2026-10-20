<!-- mcp-name: io.github.sepehr071/baneh-mcp -->

<div align="center">

# baneh-mcp: Baneh MCP server for AI agents

**Unofficial, read-only MCP server that lets your AI agent shop for home appliances, TVs and electronics on Baneh (بانه, baaneeh.com), an Iranian online shop.**<br>
Search products, find the cheapest in-stock match, browse by category or brand and read reviews, all from Claude, Cursor or Copilot.

[![PyPI](https://img.shields.io/pypi/v/baneh-mcp?color=2563eb)](https://pypi.org/project/baneh-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/baneh-mcp/blob/main/LICENSE)

[Quick start](#quick-start) · [For AI agents](#for-ai-agents) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## For AI agents

- **What:** unofficial MCP server for Baneh (baaneeh.com, بانه), an Iranian shop for home appliances, TVs, tools and car audio. Queries work in Persian and English; prices are in Toman.
- **Install:** `claude mcp add baneh -- uvx baneh-mcp` (stdio transport, needs [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.10+).
- **Auth:** none. Optional `BANEH_MCP_PROXY` sets an HTTP proxy for requests to baaneeh.com.
- **Access:** read-only. No login, cart, orders or posted reviews, so no write tools exist.
- **Tools:** 7, all prefixed `bn_`. Start with `bn_find_cheapest` or `bn_search`. Typical sequence: `bn_find_cheapest` → `bn_product` → `bn_reviews`.
- **Use when:** comparing prices, stock and reviews of TVs, fridges, washing machines, kitchen appliances and tools on Baneh.
- **Do not use when:** the user wants to buy (no cart or checkout), wants phones (almost all are discontinued), or wants discounts (nothing in stock is discounted).
- **Output:** compact JSON. `final_price` is Toman. Null fields are left out: no `regular_price` means no discount, no `rating` means no reviews.
- **Machine-readable:** [`server.json`](server.json), and the catalog of all Iranian MCP servers at [awesome-iran-mcp](https://github.com/sepehr071/awesome-iran-mcp).

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). No API key or account.

```bash
claude mcp add baneh -- uvx baneh-mcp
```

Claude Desktop, Cursor and others take the same command in their MCP config:

```json
{ "mcpServers": { "baneh": { "command": "uvx", "args": ["baneh-mcp"] } } }
```

Then ask:

- "Cheapest in-stock Samsung TV above 20 million Toman?"
- "Show LG washing machines sorted by price, and the reviews of the cheapest one."
- <span dir="rtl">ارزان&zwnj;ترین یخچال ساید بای ساید موجود در بانه کدام است؟</span>

## How it works

```text
  AI agent  ──MCP over stdio──▶  baneh-mcp (your machine)  ──HTTPS──▶  baaneeh.com  (WooCommerce Store API)
```

It calls the public WooCommerce Store API that the website itself exposes. No hosted server, no API key.

## Tools

| Tool | What it does |
|---|---|
| `bn_search` | Search by keyword: price, stock, rating, with sort and price range |
| `bn_find_cheapest` | Cheapest matches for a keyword, titles must contain every word (any order) |
| `bn_browse` | A category and/or brand, sorted by price or rating, with a price range |
| `bn_categories` | Categories with slugs and product counts (top level, children of one, or search) |
| `bn_brands` | Brands (LG, Samsung, Bosch, ...) with slugs and product counts |
| `bn_product` | One product: price, stock, brand, categories, spec attributes, highlights, description, images |
| `bn_reviews` | Buyer reviews of one product with ratings |

All 7 tools are annotated `readOnlyHint: true` and return compact JSON.

## Good to know

- **In stock only by default.** The catalog lists about 9,200 products but only about 1,900 are in stock. The rest, almost all of the phones and tablets, are discontinued and their prices are stale. Pass `in_stock_only: false` to include them.
- **Sorting is done by the server of this tool, not the shop**, which ignores sort parameters. Price and rating sorts scan up to 2,000 matches (about 5 s per 100); the reply shows `scanned`. A whole-shop price sort takes about 30 s the first time.
- **No deals tool**: no in-stock product has a sale price.
- **Prices** are the shop's own Toman amounts. A few look wrong (a USB cable at 144 million Toman); check the product page before relying on extremes.
- **Reviews**: many products carry one long generated "summary of buyer opinions" instead of real reviews.
- **Shipping fees and policies** are not available through the public API.

## FAQ

<details>
<summary><b>Can it place an order for me?</b></summary>

No. It has no login and never touches the cart or checkout. The agent finds the best option; you buy it on baaneeh.com.
</details>

<details>
<summary><b>Is baneh.com the same shop?</b></summary>

Yes. baneh.com redirects to baaneeh.com, which is where the server connects.
</details>

<details>
<summary><b>I get "Could not reach baaneeh.com"</b></summary>

Check your internet connection. System proxy variables are ignored on purpose; set `BANEH_MCP_PROXY` if you need a proxy.
</details>

<details>
<summary><b>How do I debug what the agent sees?</b></summary>

```bash
npx @modelcontextprotocol/inspector uvx baneh-mcp
```
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BANEH_MCP_PROXY` | unset | HTTP proxy for every request, e.g. `http://user:pass@host:port`; a comma-separated list is used one at a time, moving on after a connect error |

<a id="فارسی"></a>

## فارسی: سرور MCP بانه

<div dir="rtl">

**baneh-mcp** یک سرور MCP غیررسمی برای فروشگاه اینترنتی بانه (baaneeh.com) است و به دستیار هوش مصنوعی شما اجازه می&zwnj;دهد
لوازم خانگی، تلویزیون و ابزار را جستجو کند، ارزان&zwnj;ترین کالای موجود را پیدا کند و نظرات خریداران را بخواند.

- فقط خواندنی است: وارد حساب نمی&zwnj;شود، سبد خرید نمی&zwnj;سازد و سفارش ثبت نمی&zwnj;کند.
- قیمت&zwnj;ها به تومان است.

نصب در Claude Code: `claude mcp add baneh -- uvx baneh-mcp`

</div>

## Development

```bash
git clone https://github.com/sepehr071/baneh-mcp && cd baneh-mcp
uv sync
uv run python -m pytest            # offline, against recorded responses
uv run python -m pytest -m live    # real baaneeh.com
uv run ruff check .
```

Tools live in `src/baneh_mcp/catalog.py` and `product.py`; each is a typed async function with a docstring that tells the agent when to use it.

## Related servers

- [Asal Banoo MCP server](https://github.com/sepehr071/asalbanoo-mcp) for cosmetics and skin care
- All Iranian MCP servers: [awesome-iran-mcp](https://github.com/sepehr071/awesome-iran-mcp)

## Disclaimer

Unofficial and not affiliated with or endorsed by Baneh. It uses the public API of the baaneeh.com website, which can
change without notice. Please keep request rates reasonable.

## License

[MIT](https://github.com/sepehr071/baneh-mcp/blob/main/LICENSE)
