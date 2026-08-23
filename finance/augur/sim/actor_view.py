"""What an actor can see when its policy runs.

The observation half of the policy contract. A policy is a pure function
`(batch of observations) -> (batch of actions)` in the RL sense, so this is a struct OF
ARRAYS, not an array of structs: every field carries the rollout axis last, and one call
decides for every rollout at once. No per-rollout Python anywhere, and a learned policy
would drop into the same signature.

## What "can see" means

Two restrictions, and both are structural rather than conventional:

- **Own rows only.** The view is built by slicing with compile-time index sets naming one
  agent's accounts and lots. Other agents' balances and the `rest_of_world` contra row are
  not merely absent from the type — `ActorSlots.__post_init__` rejects them, so an invalid
  set cannot be constructed and no caller can pass one in by accident.
- **Nothing from the future.** Every field is a function of state as of `month` and of
  marks at `month`. The builder holds no price cube it could index past the current month —
  marks arrive already resolved — so `month` reaches exactly one output, the holding period.
  That is what stops a policy from quietly becoming clairvoyant and making every backtest
  look brilliant.

## What it deliberately carries

Lot-level rather than sleeve-level quantities. A brokerage statement shows lots, and lot
identity is what tax-aware selection needs; aggregating to sleeves is a policy's own step,
done with compile-time index sets. Carrying only sleeve totals would foreclose lot-level
policies for a saving the dense shapes do not need.

PRICES, on their own axis, for every instrument the actor may trade — not only the ones it
holds. What something trades at is a fact about the market, so there is no visibility rule
to enforce here and no reason to withhold it. Carrying it matters because a policy that
inferred price from `value / quanta` of its own holdings could not price an instrument it
owns none of, which is exactly the one a target allocation is trying to buy. The instrument
axis is built by the engine from the actor's tradable set; today one policy's sleeves are
that set in order, and a shared instrument table is what a second policy kind would need.

`scheduled_outflow_quanta` is what the month is already committed to paying. It belongs in
the observation because the agent genuinely knows its own bills before it decides how to
fund them — and because deciding against the projected end-of-month balance rather than
the current one is what lets funding happen once a month instead of twice.
"""

from __future__ import annotations

# ruff: noqa: F722 -- jaxtyping shape strings are not Python forward-reference expressions.
from dataclasses import dataclass
from typing import NamedTuple

import jax.numpy as jnp
import numpy as np
from jaxtyping import Array, Int64


@dataclass(frozen=True)
class ActorSlots:
    """Compile-time index sets naming the rows one agent may look at.

    Every visibility rule is checked in `__post_init__`, so an invalid set cannot be
    constructed at all — there is no separate validate step a caller can forget, which is
    the failure mode a "remember to call this" API eventually has.

    That is why the plan's shape travels with the slots. `external_cash_slot` in particular
    is load-bearing: `rest_of_world` holds money that LEFT the modeled world, so an actor
    able to see it would read its own past spending as an asset.
    """

    cash_slots: tuple[int, ...]
    lot_slots: tuple[int, ...]
    external_cash_slot: int
    cash_count: int
    lot_count: int

    def __post_init__(self) -> None:
        if len(set(self.cash_slots)) != len(self.cash_slots):
            raise ValueError(f"duplicate cash slot in actor view: {self.cash_slots}")
        if len(set(self.lot_slots)) != len(self.lot_slots):
            raise ValueError(f"duplicate lot slot in actor view: {self.lot_slots}")
        if self.external_cash_slot in self.cash_slots:
            raise ValueError(
                f"actor view would expose the external contra row ({self.external_cash_slot=}); "
                "an actor may only see its own accounts"
            )
        if any(not 0 <= slot < self.cash_count for slot in self.cash_slots):
            raise ValueError(f"actor view cash slot out of range for cash_count={self.cash_count}: {self.cash_slots}")
        if any(not 0 <= slot < self.lot_count for slot in self.lot_slots):
            raise ValueError(f"actor view lot slot out of range for lot_count={self.lot_count}: {self.lot_slots}")


class ActorView(NamedTuple):
    """One month's observation, batched over rollouts.

    Shapes: `month` is a scalar; `cash_quanta` is `(account, R)`; every `lot_*` field is
    `(lot, R)`; the rest are `(R,)`. Account and lot axes are in `ActorSlots` order.
    """

    month: Int64[Array, ""]
    cash_quanta: Int64[Array, " cash rollout"]
    lot_quantity: Int64[Array, " lot rollout"]
    # Marked at this month's price, NOT held at cost — a policy reasoning about allocation
    # needs what a sleeve is worth now, not what it was bought for.
    lot_value_quanta: Int64[Array, " lot rollout"]
    lot_cost_basis_per_unit_quanta: Int64[Array, " lot rollout"]
    # Months since acquisition, so a policy can weigh the long/short capital-gain boundary
    # without reaching into the engine's classification.
    lot_holding_months: Int64[Array, " lot rollout"]
    scheduled_outflow_quanta: Int64[Array, " rollout"]
    # What the market charges this month, per tradable instrument, `(instrument, R)`. Zero
    # means unpriceable — no modeled price series — rather than free.
    instrument_price_quanta: Int64[Array, " instrument rollout"]
    # Quanta per unit, `(instrument,)`. A market convention about divisibility, not a fact
    # about the position, which is why it sits on the instrument axis and not the lot one.
    instrument_quantity_scale: Int64[Array, " instrument"]

    @property
    def total_cash_quanta(self) -> Int64[Array, " rollout"]:
        return self.cash_quanta.sum(axis=0)

    def sleeve_value_quanta(self, sleeve_lot_rows: tuple[tuple[int, ...], ...]) -> Int64[Array, " sleeve rollout"]:
        """Aggregate lot values into `(sleeve, R)` using compile-time row groups.

        Rows index the VIEW's lot axis, not the plan's — the view has already narrowed to
        this agent, so a group referring to plan indices would silently read the wrong lots.
        """

        return jnp.stack(
            [self.lot_value_quanta[np.asarray(rows, dtype=np.int64)].sum(axis=0) for rows in sleeve_lot_rows]
        )

    def sleeve_quanta(self, sleeve_lot_rows: tuple[tuple[int, ...], ...]) -> Int64[Array, " sleeve rollout"]:
        """Aggregate lot quantities into `(sleeve, R)`, same row groups as the value aggregate.

        What a sell order has to be capped by: a policy may want to raise more than a sleeve
        holds, and asking for it would be an order the executor could only refuse.
        """

        return jnp.stack([self.lot_quantity[np.asarray(rows, dtype=np.int64)].sum(axis=0) for rows in sleeve_lot_rows])


def build_actor_view(
    *,
    month: Int64[Array, ""],
    slots: ActorSlots,
    cash_quanta: Int64[Array, " cash rollout"],
    lot_quantity: Int64[Array, " lot rollout"],
    lot_cost_basis_per_unit_quanta: Int64[Array, " lot rollout"],
    lot_value_quanta: Int64[Array, " lot rollout"],
    lot_purchase_month: Int64[Array, " lot rollout"] | Int64[np.ndarray, " lot"],
    scheduled_outflow_quanta: Int64[Array, " rollout"],
    instrument_price_quanta: Int64[Array, " instrument rollout"],
    instrument_quantity_scale: Int64[Array, " instrument"] | Int64[np.ndarray, " instrument"],
) -> ActorView:
    """Narrow full engine state to one agent's observation.

    `cash_quanta` and the `lot_*` tensors are the engine's full `(row, R)` state; the
    slicing to this agent happens here so the visibility rule has exactly one
    implementation.

    `lot_value_quanta` is marked-to-this-month VALUE, and it is passed in rather than derived
    from a price here on purpose: valuing quanta is engine accounting
    (`_value_quanta_from_quanta`, which rounds half away from zero), and a second
    implementation would round differently. Flooring here would report a sleeve worth a cent
    less than selling it actually yields, so a policy asking for the whole sleeve would come
    up short. One valuation, owned by the side that does the selling.

    `instrument_price_quanta` arrives resolved for `month` for the same reason marks do, and
    for one more: the builder must not hold a price cube it could index past the current
    month. A policy that could read next month's price would make every backtest brilliant.
    """

    cash_rows = np.asarray(slots.cash_slots, dtype=np.int64)
    lot_rows = np.asarray(slots.lot_slots, dtype=np.int64)
    quantity = lot_quantity[lot_rows]
    return ActorView(
        month=month,
        cash_quanta=cash_quanta[cash_rows],
        lot_quantity=quantity,
        lot_value_quanta=lot_value_quanta[lot_rows],
        lot_cost_basis_per_unit_quanta=lot_cost_basis_per_unit_quanta[lot_rows],
        # Already `(lot, R)`: the purchase month is per-rollout carried state, because a slot
        # a policy chose to fill is bought in a different month in each rollout.
        lot_holding_months=(month - lot_purchase_month[lot_rows]).astype(jnp.int64),
        scheduled_outflow_quanta=scheduled_outflow_quanta,
        instrument_price_quanta=instrument_price_quanta,
        instrument_quantity_scale=jnp.asarray(instrument_quantity_scale, dtype=jnp.int64),
    )
