"""Emit the backend rollout-event ordering contract as a TypeScript module."""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from finance.augur.product.wire import ROLLOUT_EVENT_KIND_ORDER, RolloutEvent


def _schema_kinds() -> frozenset[str]:
    schema = TypeAdapter(RolloutEvent).json_schema()
    discriminator = schema.get("discriminator")
    if not isinstance(discriminator, dict):
        raise ValueError("RolloutEvent schema must expose its kind discriminator")
    mapping = discriminator.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("RolloutEvent kind discriminator must expose its variants")
    return frozenset(mapping)


def main() -> None:
    order = tuple(ROLLOUT_EVENT_KIND_ORDER)
    if len(set(order)) != len(order):
        raise ValueError("ROLLOUT_EVENT_KIND_ORDER must not contain duplicates")
    schema_kinds = _schema_kinds()
    if frozenset(order) != schema_kinds:
        raise ValueError(
            "ROLLOUT_EVENT_KIND_ORDER must cover every RolloutEvent discriminator exactly; "
            f"missing={sorted(schema_kinds - set(order))}, extra={sorted(set(order) - schema_kinds)}"
        )

    order_json = json.dumps(order, indent=2)
    print("// Generated from finance.augur.product.wire; do not edit.")
    print(f"export const ROLLOUT_EVENT_KIND_ORDER = {order_json} as const;")
    print("export type RolloutEventKind = (typeof ROLLOUT_EVENT_KIND_ORDER)[number];")


if __name__ == "__main__":
    main()
