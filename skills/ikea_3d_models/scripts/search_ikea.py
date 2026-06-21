#!/usr/bin/env python3
"""Search IKEA's public structured product API -- no cookies required.

Hits the `sik` search backend (the same JSON endpoint the website's search
page calls), which returns clean structured product records. This is far more
reliable than scraping the JS-rendered search HTML.

Usage:
    search_ikea.py "besta tv unit" [--size N] [--market us] [--lang en]
                   [--variants] [--json]

Prints one product per line: <itemNo>  <name> <type>  (<dimensions>)
With --variants, each product is followed by its color variants (item number +
color), read structurally from the search response's gprDescription -- no HTML
scraping. With --json, prints the full list (incl. variants) as JSON.

The 8-digit itemNo feeds directly into download_ikea_glb.sh. A variant whose
download 404s simply has no 3D model -- try another color's item number.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def _slug(pip_url):
    return pip_url.rstrip("/").rsplit("/", 1)[-1] if pip_url else ""


def _slug_tokens(slug):
    """Slug tokens minus the trailing item number (`s` prefix for combos)."""
    toks = slug.split("-")
    if toks and re.fullmatch(r"s?\d+", toks[-1]):
        toks = toks[:-1]
    return toks


def _variants(product):
    """Color variants from gprDescription -- structured, no HTML scraping.

    Each variant's `id` is its item number (leading `s` on combination products
    stripped, since the model URL wants digits only). The color is the variant
    slug with the product-type prefix (shared across all variants) removed:
    `besta-tv-unit-dark-gray-40575227` -> "dark gray".
    """
    raw = product.get("gprDescription", {}).get("variants", [])
    vtokens = [_slug_tokens(_slug(v.get("pipUrl", ""))) for v in raw]
    base = _slug_tokens(_slug(product.get("pipUrl", "")))
    # Longest run of leading tokens common to the base product and every
    # variant == the product-type prefix; the remainder is the color.
    common = 0
    if vtokens:
        for col in zip(base, *vtokens, strict=False):
            if len(set(col)) == 1:
                common += 1
            else:
                break
    out = []
    for v, toks in zip(raw, vtokens, strict=True):
        vid = v.get("id", "")
        if not vid:
            continue
        item_no = vid[1:] if re.fullmatch(r"s\d+", vid) else vid
        out.append(
            {"itemNo": item_no, "color": " ".join(toks[common:]) or " ".join(toks), "pipUrl": v.get("pipUrl", "")}
        )
    return out


def search(query, size=12, market="us", lang="en"):
    base = f"https://sik.search.blue.cdtapps.com/{market}/{lang}/search-result-page"
    qs = urllib.parse.urlencode({"q": query, "types": "PRODUCT", "size": size, "c": "sr", "v": "20240110"})
    req = urllib.request.Request(f"{base}?{qs}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    items = data.get("searchResultPage", {}).get("products", {}).get("main", {}).get("items", [])
    out = []
    for it in items:
        p = it.get("product")
        if not p:
            continue
        item_no = p.get("itemNoGlobal") or p.get("id")
        if not item_no:
            continue
        out.append(
            {
                "itemNo": item_no,
                "name": p.get("name", ""),
                "type": p.get("typeName", ""),
                "dimensions": p.get("itemMeasureReferenceText", ""),
                # gprDescription.variants[] -- every color, structurally (no scrape)
                "variants": _variants(p),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--size", type=int, default=12)
    ap.add_argument("--market", default="us")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--variants", action="store_true", help="also list each product's color variants")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = search(args.query, args.size, args.market, args.lang)
    if args.json:
        print(json.dumps(results, indent=2))
        return
    if not results:
        print("no products found", file=sys.stderr)
        sys.exit(1)
    for r in results:
        label = " ".join(x for x in (r["name"], r["type"]) if x)
        dims = f"  ({r['dimensions']})" if r["dimensions"] else ""
        print(f"{r['itemNo']}  {label}{dims}")
        if args.variants:
            for v in r["variants"]:
                print(f"    {v['itemNo']}  {v['color']}")


if __name__ == "__main__":
    main()
