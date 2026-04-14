"""Tests for the build-time OpenAPI spec fixups."""

from __future__ import annotations

import pytest_bazel

from x.grocy_mcp.fix_openapi_spec import fix_entity_refs, strip_empty_enums


def test_strip_empty_enums_removes_empty_enum() -> None:
    spec = {
        "components": {"schemas": {"Bad": {"type": "string", "enum": []}, "Good": {"type": "string", "enum": ["ok"]}}}
    }
    strip_empty_enums(spec)
    assert "enum" not in spec["components"]["schemas"]["Bad"]
    assert spec["components"]["schemas"]["Good"]["enum"] == ["ok"]


def test_fix_entity_refs_materializes_missing_schemas() -> None:
    spec: dict = {
        "components": {
            "schemas": {
                "ExposedEntity": {"type": "string", "enum": ["products", "locations", "stock_log"]},
                "ExposedEntityNoEdit": {"type": "string", "enum": ["stock_log"]},
                "ExposedEntityNoDelete": {"type": "string", "enum": ["stock_log"]},
                "ExposedEntityNoListing": {"type": "string", "enum": []},
            }
        }
    }
    fix_entity_refs(spec)
    schemas = spec["components"]["schemas"]

    assert schemas["ExposedEntity_NotIncludingNotEditable"]["enum"] == ["locations", "products"]
    assert schemas["ExposedEntity_NotIncludingNotDeletable"]["enum"] == ["locations", "products"]
    assert schemas["ExposedEntity_NotIncludingNotListable"]["enum"] == ["locations", "products", "stock_log"]
    assert schemas["ExposedEntity_IncludingUserEntities"]["enum"] == ["locations", "products", "stock_log"]
    assert schemas["ExposedEntity_IncludingUserEntities_NotIncludingNotEditable"]["enum"] == ["locations", "products"]


if __name__ == "__main__":
    pytest_bazel.main()
