from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest_bazel

INVENTORY_PATH = Path(__file__).with_name("legacy_economics_inventory.json")

VALID_DISPOSITIONS = {"planned", "merged_into", "rejected"}
VALID_LEGACY_APPS = {"sf", "vallejo", "shared"}
HISTORICAL_PROVENANCE_COMMIT = "d0a581643750b47e3537fe8128c03e61ff808bcd"
REQUIRED_OPEN_CATEGORIES = {
    "generic_sp500_stock",
    "tax_lots",
    "private_equity_stock",
    "mortgage_tax_shield",
    "occupancy_rental",
    "buy_sell_costs",
    "local_tax_sale_costs",
    "depreciation_sale_taxes",
    "partner_equity",
    "reporting_outputs",
    "market_model",
}


def _load_rows() -> list[dict[str, Any]]:
    rows = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def test_legacy_economics_inventory_rows_are_classified() -> None:
    rows = _load_rows()
    assert rows
    ids = [row.get("id") for row in rows]
    assert len(ids) == len(set(ids))

    for row in rows:
        assert isinstance(row.get("id"), str)
        assert row["id"]
        assert isinstance(row.get("legacy_apps"), list)
        assert row["legacy_apps"]
        assert set(row["legacy_apps"]) <= VALID_LEGACY_APPS
        assert isinstance(row.get("legacy_kind"), str)
        assert row["legacy_kind"]
        assert isinstance(row.get("legacy_names"), list)
        assert row["legacy_names"]
        assert isinstance(row.get("category"), str)
        assert row["category"]
        assert row.get("disposition") in VALID_DISPOSITIONS
        assert "source_refs" not in row
        live_source_refs = row.get("live_source_refs", [])
        historical_source_refs = row.get("historical_source_refs", [])
        assert isinstance(live_source_refs, list)
        assert isinstance(historical_source_refs, list)
        assert live_source_refs or historical_source_refs
        for ref in live_source_refs:
            assert isinstance(ref, str)
            assert ref
            assert not ref.startswith(f"{HISTORICAL_PROVENANCE_COMMIT}:")
            assert "/legacy/" not in ref
        for ref in historical_source_refs:
            assert isinstance(ref, str)
            assert ref
            commit, separator, path = ref.partition(":")
            assert separator
            assert commit == HISTORICAL_PROVENANCE_COMMIT
            assert path.startswith("x/augur/legacy/")
        assert isinstance(row.get("notes"), str)
        assert row["notes"]

        if row["disposition"] == "rejected":
            assert isinstance(row.get("rejection_reason"), str)
            assert row["rejection_reason"]
        else:
            assert isinstance(row.get("new_model_fields"), list)
            assert row["new_model_fields"]


def test_legacy_economics_inventory_covers_required_open_economic_buckets() -> None:
    categories = {row["category"] for row in _load_rows()}
    assert categories >= REQUIRED_OPEN_CATEGORIES


if __name__ == "__main__":
    pytest_bazel.main()
