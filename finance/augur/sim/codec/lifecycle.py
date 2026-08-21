"""Lifecycle event decoder. The compile-side twin is `LifecycleEventCompileOutput`
+ `_compile_lifecycle_events` in `augur.sim.compiler`."""

from __future__ import annotations

import numpy as np
import polars as pl

from finance.augur.sim.codec.helpers import codes_to_strings, currency_quanta_column, frame_from_columns
from finance.augur.sim.compiler.plan import CompiledSimulation
from finance.augur.sim.enums import LifecycleKind
from finance.augur.sim.events import EVENT_FRAMES
from finance.augur.sim.output import DenseSimulationOutput


def decode_lifecycle_events(
    plan: CompiledSimulation, output: DenseSimulationOutput
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Decode `output.lifecycle` into per-kind polars frames.

    Each lifecycle event is fanned out to one row per active (rollout, event) pair using
    `output.lifecycle.fired`. The compile-time `lifecycle_event_kind` selects which schema
    each event belongs to; sale events additionally pull per-rollout dollar figures from the
    `sale_*` arrays.
    """

    event_count = int(plan.lifecycle_events.month.shape[0])
    if event_count == 0:
        return (
            EVENT_FRAMES.set_rented_fraction_events.empty(),
            EVENT_FRAMES.capital_improvement_events.empty(),
            EVENT_FRAMES.property_sale_events.empty(),
        )
    fired = output.lifecycle.fired[:event_count]  # (E, R)
    events_idx, rollouts = np.argwhere(fired).T if fired.any() else (np.array([], dtype=np.int64),) * 2
    if events_idx.size == 0:
        return (
            EVENT_FRAMES.set_rented_fraction_events.empty(),
            EVENT_FRAMES.capital_improvement_events.empty(),
            EVENT_FRAMES.property_sale_events.empty(),
        )
    months = plan.lifecycle_events.month.astype(np.int64)[events_idx]
    property_slots = plan.lifecycle_events.property_slot.astype(np.int64)[events_idx]
    property_ids = codes_to_strings(plan, plan.properties.id)[property_slots]
    kinds = plan.lifecycle_events.kind.astype(np.int64)[events_idx]
    fraction_mask = kinds == LifecycleKind.FRACTION
    capital_mask = kinds == LifecycleKind.CAPITAL_IMPROVEMENT
    sale_mask = kinds == LifecycleKind.SALE

    set_rented_fraction_frame = frame_from_columns(
        EVENT_FRAMES.set_rented_fraction_events,
        rollout_index=rollouts[fraction_mask],
        month_index=months[fraction_mask],
        property_id=property_ids[fraction_mask],
        rented_fraction=plan.lifecycle_events.rented_fraction.astype(np.float64)[events_idx[fraction_mask]],
    )
    capital_improvement_frame = frame_from_columns(
        EVENT_FRAMES.capital_improvement_events,
        rollout_index=rollouts[capital_mask],
        month_index=months[capital_mask],
        property_id=property_ids[capital_mask],
        amount_quanta=currency_quanta_column(plan.lifecycle_events.amount_quanta[events_idx[capital_mask]]),
        description=np.full(int(capital_mask.sum()), "", dtype=object),
    )
    property_sale_frame = frame_from_columns(
        EVENT_FRAMES.property_sale_events,
        rollout_index=rollouts[sale_mask],
        month_index=months[sale_mask],
        property_id=property_ids[sale_mask],
        gross_proceeds_quanta=currency_quanta_column(
            output.lifecycle.property_sales.gross_proceeds[events_idx[sale_mask], rollouts[sale_mask]]
        ),
        mortgage_payoff_quanta=currency_quanta_column(
            output.lifecycle.property_sales.mortgage_payoff[events_idx[sale_mask], rollouts[sale_mask]]
        ),
        net_cash_to_owner_quanta=currency_quanta_column(
            output.lifecycle.property_sales.net_cash[events_idx[sale_mask], rollouts[sale_mask]]
        ),
        realized_gain_quanta=currency_quanta_column(
            output.lifecycle.property_sales.realized_gain[events_idx[sale_mask], rollouts[sale_mask]]
        ),
        depreciation_recapture_quanta=currency_quanta_column(
            output.lifecycle.property_sales.depreciation_recapture[events_idx[sale_mask], rollouts[sale_mask]]
        ),
        section_121_exclusion_quanta=currency_quanta_column(
            output.lifecycle.property_sales.section_121_exclusion[events_idx[sale_mask], rollouts[sale_mask]]
        ),
        long_term_capital_gain_quanta=currency_quanta_column(
            output.lifecycle.property_sales.long_term_capital_gain[events_idx[sale_mask], rollouts[sale_mask]]
        ),
    )
    return set_rented_fraction_frame, capital_improvement_frame, property_sale_frame
