"""Top-level codec orchestrator: wraps the per-domain decoders into a single
`decode_run` that produces a `SimulationRun` from a (plan, buffers, external_series)
triple. `DenseSimulationResult` lives here too so engine.py can stay free of the
codec dependency."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from augur.sim.buffers import SimulationBuffers
from augur.sim.codec.assets import (
    decode_asset_lots,
    decode_cash,
    decode_liquidity_dispositions,
    decode_pe_dispositions,
    decode_sched_dispositions,
)
from augur.sim.codec.liabilities import decode_liabilities, decode_mortgage_originations, decode_mortgage_payments
from augur.sim.codec.lifecycle import decode_lifecycle_events
from augur.sim.codec.obligations import decode_obligations
from augur.sim.codec.primary_residence import decode_primary_residence_events
from augur.sim.codec.properties import decode_property_purchases, decode_property_stakes, decode_property_state
from augur.sim.codec.tax import (
    decode_capital_gains,
    decode_ordinary_income,
    decode_tax_accruals,
    decode_tax_liabilities,
    decode_tax_settlements,
)
from augur.sim.codec.transfers import decode_transfers
from augur.sim.compiler import CompiledSimulation
from augur.sim.events import EVENT_FRAMES, EventLog
from augur.sim.external_series import ExternalSeriesContext
from augur.sim.state import ROLLOUT_STATUS_FRAME


@dataclass(frozen=True)
class SimulationRun:
    """Outputs of a simulation. Long-form polars frames keyed by
    `(rollout_index, month_index, ...)` plus the event log."""

    cash_balances: pl.DataFrame
    asset_lots: pl.DataFrame
    ordinary_income_ytd: pl.DataFrame
    capital_gains_ytd: pl.DataFrame
    tax_liabilities: pl.DataFrame
    property_state: pl.DataFrame
    property_stakes: pl.DataFrame
    liabilities: pl.DataFrame
    rollout_status_history: pl.DataFrame
    rollout_status: pl.DataFrame
    series_values: pl.DataFrame
    events_log: EventLog


@dataclass
class DenseSimulationResult:
    plan: CompiledSimulation
    buffers: SimulationBuffers
    external_series: ExternalSeriesContext

    def decode(self) -> SimulationRun:
        return decode_run(self.plan, self.buffers, self.external_series)


def decode_run(
    plan: CompiledSimulation, buffers: SimulationBuffers, external_series: ExternalSeriesContext
) -> SimulationRun:
    events = decode_events(plan, buffers)
    return SimulationRun(
        cash_balances=decode_cash(plan, buffers),
        asset_lots=decode_asset_lots(plan, buffers),
        ordinary_income_ytd=decode_ordinary_income(plan, buffers),
        capital_gains_ytd=decode_capital_gains(plan, buffers),
        tax_liabilities=decode_tax_liabilities(plan, buffers),
        property_state=decode_property_state(plan, buffers),
        property_stakes=decode_property_stakes(plan, buffers),
        liabilities=decode_liabilities(plan, buffers),
        rollout_status_history=decode_rollout_status_history(plan, buffers),
        rollout_status=decode_final_rollout_status(plan, buffers),
        events_log=events,
        series_values=external_series.series_values,
    )


def decode_events(plan: CompiledSimulation, buffers: SimulationBuffers) -> EventLog:
    transfer_frames: list[pl.DataFrame] = []
    lot_frames: list[pl.DataFrame] = []
    transfer_frames.append(decode_transfers(plan, buffers))
    property_purchases_frame, property_transfer_frame = decode_property_purchases(plan, buffers)
    transfer_frames.append(property_transfer_frame)
    lot_frames.append(decode_sched_dispositions(plan, buffers))
    lot_frames.append(decode_liquidity_dispositions(plan, buffers))
    lot_frames.append(decode_pe_dispositions(plan, buffers))
    tax_accruals_frame, tax_breakdowns_frame = decode_tax_accruals(plan, buffers)
    obligation_accruals_frame, obligation_settlements_frame, obligation_transfer_frame, failure_frame = (
        decode_obligations(plan, buffers)
    )
    transfer_frames.append(obligation_transfer_frame)
    set_rented_fraction_frame, capital_improvement_frame, property_sale_frame = decode_lifecycle_events(plan, buffers)
    return EventLog.from_frames(
        {
            "transfers": EVENT_FRAMES.transfers.concat(transfer_frames),
            "lot_dispositions": EVENT_FRAMES.lot_dispositions.concat(lot_frames),
            "tax_accruals": tax_accruals_frame,
            "tax_breakdowns": tax_breakdowns_frame,
            "tax_settlements": decode_tax_settlements(plan, buffers),
            "obligation_accruals": obligation_accruals_frame,
            "obligation_settlements": obligation_settlements_frame,
            "property_purchases": property_purchases_frame,
            "mortgage_originations": decode_mortgage_originations(plan, buffers),
            "mortgage_payments": decode_mortgage_payments(plan, buffers),
            "rollout_failures": failure_frame,
            "set_rented_fraction_events": set_rented_fraction_frame,
            "set_primary_residence_events": decode_primary_residence_events(plan, buffers),
            "capital_improvement_events": capital_improvement_frame,
            "property_sale_events": property_sale_frame,
        }
    )


def decode_rollout_status_history(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    failed_state = buffers.state.rollout_failed_state  # (H+1, r) bool
    failed_month_state = buffers.state.rollout_failed_month_state.astype(np.int64)  # (H+1, r) int
    h1, r = failed_state.shape
    months = np.broadcast_to(np.arange(h1, dtype=np.int64)[:, None], (h1, r)).ravel()
    rollouts = np.broadcast_to(np.arange(r, dtype=np.int64)[None, :], (h1, r)).ravel()
    status = np.where(failed_state.reshape(-1), "failed_insufficient_cash", "active")
    failed_month_flat = failed_month_state.reshape(-1)
    # Polars rejects an object-dtype column for an Int64 schema; build the int|None list explicitly.
    # `h1*r` is small (≤ horizon × rollout_count) so the Python loop is fine.
    failed_month_col = [None if m < 0 else int(m) for m in failed_month_flat]
    return pl.DataFrame(
        {"rollout_index": rollouts, "month_index": months, "status": status, "failed_month": failed_month_col},
        schema={
            "rollout_index": pl.Int64(),
            "month_index": pl.Int64(),
            "status": pl.Utf8(),
            "failed_month": pl.Int64(),
        },
    )


def decode_final_rollout_status(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    month = plan.horizon_months
    failed = buffers.state.rollout_failed_state[month]  # (r,) bool
    failed_month = buffers.state.rollout_failed_month_state[month].astype(np.int64)  # (r,) int
    r = failed.shape[0]
    if r == 0:
        return ROLLOUT_STATUS_FRAME.empty()
    rollouts = np.arange(r, dtype=np.int64)
    status = np.where(failed, "failed_insufficient_cash", "active")
    failed_month_col = [None if m < 0 else int(m) for m in failed_month]
    return ROLLOUT_STATUS_FRAME.normalize(
        pl.DataFrame(
            {"rollout_index": rollouts, "status": status, "failed_month": failed_month_col},
            schema={"rollout_index": pl.Int64(), "status": pl.Utf8(), "failed_month": pl.Int64()},
        )
    )
