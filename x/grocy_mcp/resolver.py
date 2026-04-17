"""Entity name/ID resolver for Grocy MCP tools.

Provides a unified cache that resolves `int | str` references to Grocy
entities (products, locations, quantity units) into validated (id, name)
pairs. Each cache is loaded lazily on first access and shared within a
single batch call.

Grocy enforces `name TEXT NOT NULL UNIQUE` on products, locations, and
quantity_units at the database level. Name-based resolution is therefore
unambiguous by construction. Duplicate-name checks are retained as a
defensive measure in case Grocy relaxes this constraint.

QU conversion support: when a tool specifies a QU that differs from the
product's stock QU, the resolver looks up the conversion factor from
Grocy's `quantity_unit_conversions_resolved` entity and returns it.
Grocy's stock API only accepts amounts in the stock QU, so the caller
must multiply by the conversion factor before sending to Grocy.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resolved:
    """A resolved entity reference: guaranteed-valid (id, name) pair."""

    id: int
    name: str


@dataclass(frozen=True)
class ResolvedQU:
    """A resolved QU reference with optional conversion to stock QU."""

    id: int
    name: str
    stock_qu_id: int
    stock_qu_name: str
    conversion_factor: float
    """Factor to multiply input amount by to get stock QU amount.
    1.0 when the input QU is the stock QU."""


class _EntityCache:
    """Lazy-loaded, per-batch cache for a single Grocy entity type."""

    def __init__(self, client: httpx.AsyncClient, entity_path: str, entity_label: str) -> None:
        self._client = client
        self._entity_path = entity_path
        self._entity_label = entity_label
        self._by_id: dict[int, dict[str, Any]] | None = None
        self._by_name: dict[str, dict[str, Any]] | None = None
        self._all_names: list[str] | None = None
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._by_id is not None:
            return
        async with self._lock:
            if self._by_id is not None:
                return
            r = await self._client.get(self._entity_path)
            r.raise_for_status()
            rows: list[dict[str, Any]] = r.json()
            self._by_id = {int(row["id"]): row for row in rows}
            self._by_name = {}
            for row in rows:
                name_lower = str(row["name"]).lower()
                if name_lower in self._by_name:
                    # Defensive: Grocy enforces UNIQUE but we guard anyway.
                    logger.warning(
                        "duplicate %s name %r (IDs: %d, %d)",
                        self._entity_label,
                        row["name"],
                        self._by_name[name_lower]["id"],
                        row["id"],
                    )
                self._by_name[name_lower] = row
            self._all_names = sorted({str(row["name"]) for row in rows})

    async def resolve(self, ref: int | str) -> Resolved:
        """Resolve an int (ID) or str (name) to a validated (id, name) pair."""
        await self._ensure_loaded()
        assert self._by_id is not None
        assert self._by_name is not None
        assert self._all_names is not None

        if isinstance(ref, int):
            row = self._by_id.get(ref)
            if row is None:
                raise ValueError(f"No {self._entity_label} with id={ref}. Available: {self._all_names}")
            return Resolved(id=int(row["id"]), name=str(row["name"]))

        row = self._by_name.get(ref.lower())
        if row is not None:
            return Resolved(id=int(row["id"]), name=str(row["name"]))

        close = get_close_matches(ref.lower(), list(self._by_name.keys()), n=5, cutoff=0.4)
        suggestions = [str(self._by_name[m]["name"]) for m in close] if close else self._all_names[:10]
        raise ValueError(f"No {self._entity_label} named {ref!r}. Similar: {suggestions}")

    async def get_name(self, entity_id: int) -> str:
        """Look up name by ID. Returns 'id=N' if not found."""
        await self._ensure_loaded()
        assert self._by_id is not None
        row = self._by_id.get(entity_id)
        return str(row["name"]) if row else f"id={entity_id}"

    async def get_raw(self, entity_id: int) -> dict[str, Any] | None:
        """Get the raw entity dict by ID."""
        await self._ensure_loaded()
        assert self._by_id is not None
        return self._by_id.get(entity_id)

    async def all_rows(self) -> list[dict[str, Any]]:
        """Return all cached rows."""
        await self._ensure_loaded()
        assert self._by_id is not None
        return list(self._by_id.values())


class EntityResolver:
    """Per-batch entity resolver supporting products, locations, QUs, and QU conversions.

    Create one instance per tool call / batch operation. Caches are loaded
    lazily on first access and shared across all items in the batch.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._products = _EntityCache(client, "/objects/products", "product")
        self._locations = _EntityCache(client, "/objects/locations", "location")
        self._qus = _EntityCache(client, "/objects/quantity_units", "quantity unit")
        self._product_groups = _EntityCache(client, "/objects/product_groups", "product group")
        self._shopping_lists = _EntityCache(client, "/objects/shopping_lists", "shopping list")
        self._conversions: list[dict[str, Any]] | None = None
        self._conversions_lock = asyncio.Lock()

    # ── Direct entity resolution ─────────────────────────────────────

    async def resolve_product(self, ref: int | str) -> Resolved:
        return await self._products.resolve(ref)

    async def resolve_location(self, ref: int | str) -> Resolved:
        return await self._locations.resolve(ref)

    async def resolve_qu(self, ref: int | str) -> Resolved:
        return await self._qus.resolve(ref)

    async def resolve_product_group(self, ref: int | str) -> Resolved:
        return await self._product_groups.resolve(ref)

    async def resolve_shopping_list(self, ref: int | str) -> Resolved:
        return await self._shopping_lists.resolve(ref)

    # ── Name lookups ─────────────────────────────────────────────────

    async def product_name(self, product_id: int) -> str:
        return await self._products.get_name(product_id)

    async def location_name(self, location_id: int) -> str:
        return await self._locations.get_name(location_id)

    async def qu_name(self, qu_id: int) -> str:
        return await self._qus.get_name(qu_id)

    # ── Raw data access ──────────────────────────────────────────────

    async def get_product(self, product_id: int) -> dict[str, Any] | None:
        return await self._products.get_raw(product_id)

    async def all_products(self) -> list[dict[str, Any]]:
        return await self._products.all_rows()

    async def all_locations(self) -> list[dict[str, Any]]:
        return await self._locations.all_rows()

    async def all_qus(self) -> list[dict[str, Any]]:
        return await self._qus.all_rows()

    async def all_product_groups(self) -> list[dict[str, Any]]:
        return await self._product_groups.all_rows()

    # ── QU validation with conversion support ────────────────────────

    async def _ensure_conversions_loaded(self) -> None:
        if self._conversions is not None:
            return
        async with self._conversions_lock:
            if self._conversions is not None:
                return
            r = await self._client.get("/objects/quantity_unit_conversions_resolved")
            r.raise_for_status()
            self._conversions = r.json()

    async def resolve_qu_for_product(self, qu_ref: int | str, product_id: int) -> ResolvedQU:
        """Resolve a QU reference and validate it against a product's stock QU.

        If the QU matches the stock QU, returns conversion_factor=1.0.
        If a conversion exists (product-specific or global), returns the factor.
        Otherwise raises ValueError with the stock QU name and available conversions.
        """
        resolved = await self.resolve_qu(qu_ref)
        product = await self._products.get_raw(product_id)
        if product is None:
            raise ValueError(f"Product id={product_id} not found")

        stock_qu_id = int(product["qu_id_stock"])
        stock_qu_name = await self.qu_name(stock_qu_id)

        # Direct match — no conversion needed
        if resolved.id == stock_qu_id:
            return ResolvedQU(
                id=resolved.id,
                name=resolved.name,
                stock_qu_id=stock_qu_id,
                stock_qu_name=stock_qu_name,
                conversion_factor=1.0,
            )

        # Look for a conversion
        await self._ensure_conversions_loaded()
        assert self._conversions is not None

        # Grocy's quantity_unit_conversions_resolved stores pre-computed
        # transitive conversions. Look for from_qu_id → to_qu_id matching
        # our input QU → stock QU, optionally product-specific.
        factor: float | None = None
        for conv in self._conversions:
            if int(conv["from_qu_id"]) != resolved.id or int(conv["to_qu_id"]) != stock_qu_id:
                continue
            conv_product_id = conv.get("product_id")
            if conv_product_id is not None and int(conv_product_id) == product_id:
                # Product-specific conversion takes priority
                factor = float(conv["factor"])
                break
            if conv_product_id is None and factor is None:
                # Global conversion as fallback
                factor = float(conv["factor"])

        if factor is not None:
            return ResolvedQU(
                id=resolved.id,
                name=resolved.name,
                stock_qu_id=stock_qu_id,
                stock_qu_name=stock_qu_name,
                conversion_factor=factor,
            )

        # No conversion found — error with helpful info
        available_from_qus: set[str] = set()
        for conv in self._conversions:
            if int(conv["to_qu_id"]) == stock_qu_id:
                cp = conv.get("product_id")
                if cp is None or int(cp) == product_id:
                    from_id = int(conv["from_qu_id"])
                    from_name = await self.qu_name(from_id)
                    available_from_qus.add(from_name)

        product_name = str(product["name"])
        raise ValueError(
            f"No conversion from {resolved.name!r} to stock QU {stock_qu_name!r} "
            f"for product {product_name!r}. "
            f"Use qu: {stock_qu_name!r} directly"
            + (f", or one of: {sorted(available_from_qus)}" if available_from_qus else "")
            + "."
        )
