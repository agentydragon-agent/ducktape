"""Forward simulation entrypoints.

`simulate(scenario, rollout_count) -> SimulationRun` materializes external
series and runs the dense-array engine. The engine keeps the month loop in
NumPy arrays and decodes the resulting boundary tables as Polars
DataFrames for API and product projection code.
"""

from __future__ import annotations

from augur.sim.engine import (
    DenseSimulationResult,
    simulate_with_external_series_dense,
    simulate_with_external_series_dense_result,
)
from augur.sim.external_series import ExternalSeriesContext, materialize_external_series
from augur.sim.run import SimulationRun
from augur.sim.scenario import Scenario, SeriesIndexedAmount


def simulate(scenario: Scenario, *, rollout_count: int) -> SimulationRun:
    if rollout_count <= 0:
        msg = f"rollout_count must be positive; got {rollout_count}"
        raise ValueError(msg)
    external_series = materialize_external_series(
        scenario.external_series, rollout_seeds=tuple(range(rollout_count)), horizon_months=int(scenario.horizon_months)
    )
    return simulate_with_external_series(scenario, rollout_count=rollout_count, external_series=external_series)


def simulate_with_external_series(
    scenario: Scenario, *, rollout_count: int, external_series: ExternalSeriesContext
) -> SimulationRun:
    if rollout_count <= 0:
        msg = f"rollout_count must be positive; got {rollout_count}"
        raise ValueError(msg)
    _validate_series_indexed_amounts(scenario, rollout_count=rollout_count, external_series=external_series)
    return simulate_with_external_series_dense(scenario, rollout_count=rollout_count, external_series=external_series)


def simulate_dense_with_external_series(
    scenario: Scenario, *, rollout_count: int, external_series: ExternalSeriesContext
) -> DenseSimulationResult:
    if rollout_count <= 0:
        msg = f"rollout_count must be positive; got {rollout_count}"
        raise ValueError(msg)
    _validate_series_indexed_amounts(scenario, rollout_count=rollout_count, external_series=external_series)
    return simulate_with_external_series_dense_result(
        scenario, rollout_count=rollout_count, external_series=external_series
    )


def _validate_series_indexed_amounts(
    scenario: Scenario, *, rollout_count: int, external_series: ExternalSeriesContext
) -> None:
    """Validate path-indexed amount schedules before compiling dense arrays."""

    series_levels: dict[tuple[str, int, int], float | None] = {}
    for row in external_series.series_values.iter_rows(named=True):
        value = row["value"]
        series_levels[(str(row["series_id"]), int(row["month_index"]), int(row["rollout_index"]))] = (
            None if value is None else float(value)
        )

    for label, amount, months in _series_indexed_amount_uses(scenario):
        if not isinstance(amount, SeriesIndexedAmount) or not months:
            continue
        before_base = [month for month in months if month < amount.base_month_index]
        if before_base:
            raise ValueError(
                f"series-indexed amount {label} is active at month {before_base[0]} "
                f"before base month {amount.base_month_index}"
            )
        required_months = {int(amount.base_month_index)}
        required_months.update(amount._reset_month(month) for month in months)
        for month in sorted(required_months):
            missing_rollouts = [
                rollout_index
                for rollout_index in range(rollout_count)
                if series_levels.get((amount.series_id, month, rollout_index)) is None
            ]
            if missing_rollouts:
                raise KeyError(
                    f"series-indexed amount {label} references external series {amount.series_id!r} "
                    f"at month {month}, but it is missing rollout(s): {_format_rollout_sample(missing_rollouts)}"
                )
        zero_base_rollouts = [
            rollout_index
            for rollout_index in range(rollout_count)
            if series_levels[(amount.series_id, int(amount.base_month_index), rollout_index)] == 0.0
        ]
        if zero_base_rollouts:
            raise ValueError(
                f"external series {amount.series_id!r} has zero base level at month "
                f"{amount.base_month_index} for rollout(s): {_format_rollout_sample(zero_base_rollouts)}"
            )


def _series_indexed_amount_uses(scenario: Scenario) -> list[tuple[str, object, tuple[int, ...]]]:
    horizon = int(scenario.horizon_months)
    uses: list[tuple[str, object, tuple[int, ...]]] = []
    for scheduled_transfer in scenario.scheduled_transfers:
        transfer_months: tuple[int, ...] = (
            (scheduled_transfer.month,) if 0 <= scheduled_transfer.month < horizon else ()
        )
        uses.append(
            (f"scheduled transfer {scheduled_transfer.cause_id!r}", scheduled_transfer.amount_usd, transfer_months)
        )
    for recurring_transfer in scenario.recurring_transfers:
        recurring_transfer_months = tuple(month for month in range(horizon) if recurring_transfer.is_active_at(month))
        uses.append(
            (
                f"recurring transfer {recurring_transfer.cause_id!r}",
                recurring_transfer.amount_usd,
                recurring_transfer_months,
            )
        )
    for scheduled_obligation in scenario.scheduled_obligations:
        obligation_months: tuple[int, ...] = (
            (scheduled_obligation.month,) if 0 <= scheduled_obligation.month < horizon else ()
        )
        uses.append(
            (
                f"scheduled obligation {scheduled_obligation.obligation_id!r}",
                scheduled_obligation.amount_due_usd,
                obligation_months,
            )
        )
    for recurring_obligation in scenario.recurring_obligations:
        recurring_obligation_months = tuple(
            month for month in range(horizon) if recurring_obligation.is_active_at(month)
        )
        uses.append(
            (
                f"recurring obligation {recurring_obligation.obligation_id!r}",
                recurring_obligation.amount_due_usd,
                recurring_obligation_months,
            )
        )
    return uses


def _format_rollout_sample(rollout_indices: list[int]) -> str:
    sample = ", ".join(str(index) for index in rollout_indices[:5])
    if len(rollout_indices) > 5:
        sample += ", ..."
    return sample
