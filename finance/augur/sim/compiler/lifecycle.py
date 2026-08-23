"""Property lifecycle event compile output. Pairs with `codec/lifecycle.py`.

A `PropertyLifecycleEvent` row (SetRentedFractionEvent, CapitalImprovementEvent,
or PropertySaleEvent in the scenario layer) is lowered into a single dense
SoA table here; the engine's `_apply_lifecycle_events` phase scans the relevant
month range via `month_starts` and dispatches on `kind`."""

from __future__ import annotations

# ruff: noqa: F722 -- jaxtyping shape strings are not Python forward-reference expressions.
from dataclasses import dataclass

import numpy as np
from jaxtyping import Float64, Int64

from finance.augur.sim.enums import LifecycleKind
from finance.augur.sim.fixed_point import currency_amount_to_quanta
from finance.augur.sim.scenario import CapitalImprovementEvent, PropertySaleEvent, Scenario, SetRentedFractionEvent


@dataclass(frozen=True)
class LifecycleEventCompileOutput:
    """PropertyLifecycleEvent rows compiled into per-month sparse storage. Sorted by
    month so the engine scans a per-month index range via `month_starts`:
    `events_for_month_M = events[month_starts[M]:month_starts[M+1]]`. `kind[i]` is
    `LifecycleKind.FRACTION` (0) for rented-fraction change (start/stop/change-rental
    -plan), `LifecycleKind.CAPITAL_IMPROVEMENT` (1) for cash + basis bump, or
    `LifecycleKind.SALE` (2). `rented_fraction[i]` is the new value (kind 0; 0.0
    otherwise). `amount[i]` is the USD spend (kind 1), the closing-cost percentage
    (kind 2; 0..100), or 0.0 (kind 0). `month_starts` has length `horizon_months + 1`
    so the engine can do `events[starts[M]:starts[M+1]]` for any month M."""

    month: Int64[np.ndarray, " event"]
    property_slot: Int64[np.ndarray, " event"]
    kind: Int64[np.ndarray, " event"]
    rented_fraction: Float64[np.ndarray, " event"]
    amount: Float64[np.ndarray, " event"]
    amount_quanta: Int64[np.ndarray, " event"]
    month_starts: Int64[np.ndarray, " month_boundary"]


def compile_lifecycle_events(scenario: Scenario, property_slot_by_id: dict[str, int]) -> LifecycleEventCompileOutput:
    events_sorted = sorted(scenario.property_lifecycle_events, key=lambda e: (int(e.month), e.property_id))
    count = len(events_sorted)
    month = np.empty(count, dtype=np.int64)
    property_slot = np.empty(count, dtype=np.int64)
    kind = np.empty(count, dtype=np.int64)
    rented_fraction = np.zeros(count, dtype=np.float64)
    amount = np.zeros(count, dtype=np.float64)
    amount_quanta = np.zeros(count, dtype=np.int64)
    for i, event in enumerate(events_sorted):
        if event.property_id not in property_slot_by_id:
            raise ValueError(
                f"PropertyLifecycleEvent at month {event.month} references unknown property_id "
                f"{event.property_id!r}; known: {sorted(property_slot_by_id)}"
            )
        slot = property_slot_by_id[event.property_id]
        purchase_month = int(scenario.scheduled_property_purchases[slot].month)
        if int(event.month) <= purchase_month:
            raise ValueError(
                f"PropertyLifecycleEvent for {event.property_id!r} fires at month {event.month} "
                f"but the property's purchase month is {purchase_month}; lifecycle events must "
                "fire strictly after purchase."
            )
        month[i] = int(event.month)
        property_slot[i] = slot
        if isinstance(event, SetRentedFractionEvent):
            kind[i] = LifecycleKind.FRACTION
            rented_fraction[i] = float(event.rented_fraction)
        elif isinstance(event, CapitalImprovementEvent):
            kind[i] = LifecycleKind.CAPITAL_IMPROVEMENT
            amount_quanta[i] = currency_amount_to_quanta(event.amount, quantum=scenario.currency.quantum)
        elif isinstance(event, PropertySaleEvent):
            kind[i] = LifecycleKind.SALE
            # Reuse `amount` as closing_cost_pct for sale events (different semantic per kind,
            # but storing in the same dense column avoids another array).
            amount[i] = float(event.closing_cost_pct)
        else:
            raise TypeError(f"unknown PropertyLifecycleEvent variant: {type(event).__name__}")
    # `starts[M]` = first event index for month >= M; `starts[H]` = count.
    month_starts = np.searchsorted(month, np.arange(int(scenario.horizon_months) + 1), side="left").astype(np.int64)
    return LifecycleEventCompileOutput(
        month=month,
        property_slot=property_slot,
        kind=kind,
        rented_fraction=rented_fraction,
        amount=amount,
        amount_quanta=amount_quanta,
        month_starts=month_starts,
    )
