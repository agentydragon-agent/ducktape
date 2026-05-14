from __future__ import annotations

import math
from bisect import bisect_left
from typing import Any

import numpy as np

from augur.core._num import require_finite as required_number
from augur.core.augur_accounting import MONTHS_PER_YEAR
from augur.core.personal_wealth import build_private_equity_liquidity_path
from augur.core.scenario_set import LiquidityReservePolicy, PrivateEquitySalePolicy
from augur.core.schemas import (
    ColumnarTable,
    HistogramBucket,
    JointRolloutPath,
    KnobsConfig,
    MarketPath,
    ModelRunMetadata,
    Percentiles,
    PolicyAction,
    PolicyActionPrivateEquity,
    PolicyActionRental,
    PolicyActionTrade,
    PrivateEquityLiquidityPath,
    PropertyRequest,
    SamplePathColumns,
    ScenarioKnobs,
    SimulationResult,
    StochasticOutcomeView,
)
from augur.core.vectorized import (
    columnar_table_from_columns,
    columnar_table_from_rows,
    market_paths_from_joint_rollouts,
    simulate_property_vectorized,
)

FAN_PERCENTILES = [
    0.01,
    0.02,
    0.05,
    0.1,
    0.15,
    0.2,
    0.25,
    0.3,
    0.35,
    0.4,
    0.45,
    0.5,
    0.55,
    0.6,
    0.65,
    0.7,
    0.75,
    0.8,
    0.85,
    0.9,
    0.95,
    0.98,
    0.99,
]


def percentile_key(p: float) -> str:
    return f"p{round(p * 100):02d}"


def percentile_fields(values: list[float], percentiles: list[float] | None = None) -> Percentiles:
    percentiles = percentiles or [0.05, 0.25, 0.5, 0.75, 0.95]
    finite = np.asarray([v for v in values if math.isfinite(v)], dtype="float64")
    if finite.size == 0:
        return Percentiles.model_validate({percentile_key(p): 0.0 for p in percentiles})
    qs = np.percentile(finite, [p * 100 for p in percentiles])
    return Percentiles.model_validate({percentile_key(p): float(q) for p, q in zip(percentiles, qs, strict=False)})


def build_histogram(values: list[float], bins: int = 26) -> list[HistogramBucket]:
    sorted_values = sorted(v for v in values if math.isfinite(v))
    if not sorted_values:
        return []
    arr = np.asarray(sorted_values, dtype="float64")
    low, high = float(np.percentile(arr, 1)), float(np.percentile(arr, 99))
    if low == high:
        low -= 1
        high += 1
    width = (high - low) / bins
    edges = low + np.arange(bins + 1) * width
    counts, _ = np.histogram(arr, bins=edges)
    # np.histogram drops values outside [edges[0], edges[-1]]; the previous
    # Python loop clamped overflow into the top bucket and underflow into
    # the bottom bucket. Restore that semantics so `share` over all buckets
    # still sums to 1 even when the 1%/99% cuts trim outliers.
    underflow = int((arr < edges[0]).sum())
    overflow = int((arr > edges[-1]).sum())
    if underflow:
        counts[0] += underflow
    if overflow:
        counts[-1] += overflow
    total = len(sorted_values)
    cumulative_count = 0
    buckets: list[HistogramBucket] = []
    for index in range(bins):
        count = int(counts[index])
        cumulative_count += count
        from_value = float(edges[index])
        sort_index = bisect_left(sorted_values, from_value)
        percentile_low = -1 / total if sort_index >= total else sort_index / total
        buckets.append(
            HistogramBucket(
                from_value=from_value,
                to_value=float(edges[index + 1]),
                mid=float(edges[index]) + width / 2,
                count=count,
                share=count / total,
                percentile_low=1 if percentile_low < 0 else percentile_low,
                percentile_high=cumulative_count / total,
            )
        )
    return buckets


def aggregate_fan_matrix(matrix: np.ndarray) -> ColumnarTable:
    values = np.asarray(matrix, dtype="float64")
    if values.ndim != 2:
        raise ValueError("fan matrix must be shaped (rollout, month)")
    finite = np.where(np.isfinite(values), values, np.nan)
    qs = np.nanpercentile(finite, [p * 100 for p in FAN_PERCENTILES], axis=0)
    keys = [percentile_key(p) for p in FAN_PERCENTILES]
    month_index = np.arange(values.shape[1], dtype="int64")
    columns: dict[str, Any] = {"month_index": month_index, "year": month_index / MONTHS_PER_YEAR}
    columns.update({key: qs[key_index] for key_index, key in enumerate(keys)})
    return columnar_table_from_columns(columns)


def coerce_joint_rollout_path(path: Any, hold_months: int, index: int) -> JointRolloutPath:
    if path is None:
        raise ValueError(f"Missing joint rollout path at index {index}")
    rollout = path if isinstance(path, JointRolloutPath) else JointRolloutPath.model_validate(path)
    expected = hold_months + 1
    for series_name in (
        "home_value_multipliers",
        "sale_home_value_multipliers",
        "portfolio_multipliers",
        "rent_multipliers",
        "expense_inflation_multipliers",
    ):
        series = getattr(rollout, series_name)
        if len(series) < expected:
            raise ValueError(f"jointRolloutPaths[{index}].{series_name} length {len(series)} < {expected}")
        for month_index, value in enumerate(series[:expected]):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"jointRolloutPaths[{index}].{series_name}[{month_index}] must be positive finite")
    open_ai = rollout.private_equity_path
    if len(open_ai.price_path) < expected:
        raise ValueError(
            f"jointRolloutPaths[{index}].privateEquityPath.pricePath length {len(open_ai.price_path)} < {expected}"
        )
    if not math.isfinite(open_ai.current_price_usd) or open_ai.current_price_usd <= 0:
        raise ValueError(f"jointRolloutPaths[{index}].privateEquityPath.currentPriceUsd must be positive finite")
    for month_index, price in enumerate(open_ai.price_path[:expected]):
        if not math.isfinite(price) or price <= 0:
            raise ValueError(
                f"jointRolloutPaths[{index}].privateEquityPath.pricePath[{month_index}] must be positive finite"
            )
    for event_index, event in enumerate(open_ai.events):
        if not math.isfinite(event.price_usd_per_unit) or event.price_usd_per_unit <= 0:
            raise ValueError(
                f"jointRolloutPaths[{index}].privateEquityPath.events[{event_index}].priceUsdPerUnit must be positive finite"
            )
    return rollout


def annual_cagr_pct(multiplier: float, hold_years: int) -> float:
    return math.expm1(math.log(required_number(multiplier, "rollout multiplier")) / max(1, hold_years)) * 100


def market_path_from_joint_rollout(path: JointRolloutPath, hold_years: int, hold_months: int) -> MarketPath:
    home = path.home_value_multipliers
    sale_home = path.sale_home_value_multipliers
    portfolio = path.portfolio_multipliers
    rent = path.rent_multipliers
    inflation = path.expense_inflation_multipliers
    terminal_home_log_growth = math.log(home[hold_months])
    terminal_sale_log_growth = math.log(sale_home[hold_months])
    return MarketPath(
        home_value_multipliers=list(home),
        sale_home_value_multipliers=list(sale_home),
        portfolio_multipliers=list(portfolio),
        rent_multipliers=list(rent),
        expense_inflation_multipliers=list(inflation),
        mortgage30_rate_path=list(path.mortgage30_rate_path),
        terminal_home_annual_cagr_pct=annual_cagr_pct(home[hold_months], hold_years),
        terminal_sale_annual_cagr_pct=annual_cagr_pct(sale_home[hold_months], hold_years),
        terminal_sp500_annual_cagr_pct=annual_cagr_pct(portfolio[hold_months], hold_years),
        terminal_rent_annual_cagr_pct=annual_cagr_pct(rent[hold_months], hold_years),
        terminal_inflation_annual_cagr_pct=annual_cagr_pct(inflation[hold_months], hold_years),
        terminal_appreciation_pct=math.expm1(terminal_sale_log_growth) * 100,
        cumulative_home_appreciation_pct=[math.expm1(math.log(value)) * 100 for value in home],
        terminal_home_log_growth=terminal_home_log_growth,
    )


def choose_joint_rollout(joint_rollout_paths: list[Any], index: int, hold_months: int) -> JointRolloutPath:
    path_index = index % len(joint_rollout_paths)
    return coerce_joint_rollout_path(joint_rollout_paths[path_index], hold_months, path_index)


def required_row_field(rows: list[Any], month_index: int, field: str, label: str) -> float:
    if month_index >= len(rows):
        raise ValueError(f"Missing required model row: {label}[{month_index}]")
    row = rows[month_index]
    value = getattr(row, field, None) if not isinstance(row, dict) else row.get(field)
    return required_number(value, f"{label}[{month_index}].{field}")


def required_array_value(values: list[float], index: int, label: str) -> float:
    if not isinstance(values, list) or index >= len(values):
        raise ValueError(f"Missing required model array value: {label}[{index}]")
    return required_number(values[index], f"{label}[{index}]")


def ledger_net_cash_by_month(simulation: SimulationResult) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in simulation.ledger:
        if row.actor == "owner" and row.domain == "cash":
            out[row.month_index] = out.get(row.month_index, 0) + row.amount_usd
    return out


def policy_minimum_liquid_reserve(simulation: SimulationResult, reserve_policy: LiquidityReservePolicy) -> float:
    explicit_reserve = reserve_policy.min_reserve_usd
    if reserve_policy.mode == "fixed":
        return explicit_reserve
    months = max(0, int(reserve_policy.forward_months))
    if months <= 0:
        return explicit_reserve
    cash_by_month = ledger_net_cash_by_month(simulation)
    hold_months = int(simulation.hold_months or months)
    recurring_deficits = [
        max(0.0, -cash_by_month.get(month_index, 0.0)) for month_index in range(1, min(months, hold_months) + 1)
    ]
    return max(explicit_reserve, sum(recurring_deficits))


def build_policy_actions(
    simulation: SimulationResult, private_equity_liquidity_path: PrivateEquityLiquidityPath
) -> list[PolicyAction]:
    actions: list[PolicyAction] = []
    for month_index, net_cash in sorted(ledger_net_cash_by_month(simulation).items()):
        if abs(net_cash) < 1:
            continue
        if net_cash < 0:
            actions.append(
                PolicyActionTrade(
                    month_index=month_index,
                    action_type="sold_sp500",
                    amount_usd=round(-net_cash),
                    reason="purchase_funding" if month_index == 0 else "housing_cashflow",
                )
            )
        else:
            actions.append(
                PolicyActionTrade(
                    month_index=month_index,
                    action_type="bought_sp500",
                    amount_usd=round(net_cash),
                    reason="housing_surplus",
                )
            )

    occupied_months = int(simulation.occupied_months or 0)
    hold_months = int(simulation.hold_months or 0)
    if occupied_months < hold_months:
        month_index = max(1, occupied_months + 1)
        actions.append(
            PolicyActionRental(
                month_index=month_index,
                action_type="moved_out_and_rented_property"
                if occupied_months > 0
                else "rented_property_out_from_start",
            )
        )

    actions.extend(
        PolicyActionPrivateEquity(
            month_index=sale.month_index,
            action_type="sold_privateEquity",
            event_type=sale.event_type,
            units=sale.units,
            price_usd_per_unit=sale.price_usd_per_unit,
            after_tax_proceeds_usd=round(sale.after_tax_proceeds_usd),
            reason="guardrail_policy",
        )
        for sale in private_equity_liquidity_path.sales
    )

    actions.sort(key=lambda action: (action.month_index, action.action_type))
    return actions


def build_stochastic_outcome_view(
    property_: PropertyRequest,
    knobs: KnobsConfig,
    *,
    joint_rollout_paths: list[Any],
    cash_usd: float,
    private_equity_units: float,
    private_equity_basis_per_unit_usd: float,
    sale_policy: PrivateEquitySalePolicy,
    reserve_policy: LiquidityReservePolicy,
    rollouts: int | None = None,
) -> StochasticOutcomeView:
    hold_years = max(1, math.floor(knobs.hold_years))
    hold_months = hold_years * MONTHS_PER_YEAR
    rollout_count = int(rollouts or len(joint_rollout_paths))
    if rollout_count <= 0:
        raise ValueError(f"Stochastic outcomes require a positive rollout count, got {rollouts}")
    if not joint_rollout_paths:
        raise ValueError("Stochastic outcomes require explicit PyMC joint rollout samples")
    selected_rollouts = [
        choose_joint_rollout(joint_rollout_paths, index, hold_months) for index in range(rollout_count)
    ]
    market_paths = market_paths_from_joint_rollouts(
        selected_rollouts, hold_months=hold_months, rollout_count=rollout_count
    )
    scenario_knobs = ScenarioKnobs.from_knobs(knobs)
    housing = simulate_property_vectorized(property_, scenario_knobs, market_paths)

    if reserve_policy.mode == "fixed":
        minimum_reserves = np.full(rollout_count, reserve_policy.min_reserve_usd, dtype="float64")
    else:
        months = min(max(0, int(reserve_policy.forward_months)), hold_months)
        deficits = np.maximum(0.0, -housing.owner_cash_flow_usd[:, 1 : months + 1])
        minimum_reserves = np.maximum(reserve_policy.min_reserve_usd, deficits.sum(axis=1))

    private_equity_liquid = np.zeros((rollout_count, hold_months + 1), dtype="float64")
    private_equity_mark = np.zeros((rollout_count, hold_months + 1), dtype="float64")
    liquidity_shortfalls: list[bool] = []
    private_equity_sales: list[bool] = []
    private_equity_liquidity_paths: list[PrivateEquityLiquidityPath] = []
    for index, joint_rollout in enumerate(selected_rollouts):
        private_equity_liquidity_path = build_private_equity_liquidity_path(
            base_liquid_path=housing.buy_liquid_usd[index].tolist(),
            private_equity_path=joint_rollout.private_equity_path,
            cash_usd=cash_usd,
            private_equity_units=private_equity_units,
            private_equity_basis_per_unit_usd=private_equity_basis_per_unit_usd,
            minimum_liquid_reserve_usd=float(minimum_reserves[index]),
            sale_policy=sale_policy,
            portfolio_multipliers=market_paths.portfolio_multipliers[index].tolist(),
        )
        private_equity_liquidity_paths.append(private_equity_liquidity_path)
        liquidity_shortfalls.append(private_equity_liquidity_path.had_liquidity_shortfall)
        private_equity_sales.append(private_equity_liquidity_path.had_eligible_sale)
        private_equity_liquid[index] = [
            row.liquid_private_equity_proceeds_usd for row in private_equity_liquidity_path.rows
        ]
        private_equity_mark[index] = [
            row.private_equity_after_tax_mark_value_usd for row in private_equity_liquidity_path.rows
        ]

    liquid_net_worth = housing.buy_liquid_usd + private_equity_liquid
    economic_net_worth = housing.buy_path_usd + private_equity_liquid + private_equity_mark
    terminal_deltas = housing.delta_usd[:, hold_months]
    terminal_economic_net_worth = economic_net_worth[:, hold_months]
    terminal_liquid_net_worth = liquid_net_worth[:, hold_months]
    terminal_private_equity_event_pv = private_equity_mark[:, hold_months]
    terminal_private_equity_liquid_value = private_equity_liquid[:, hold_months]

    def annual_cagr(values: np.ndarray) -> np.ndarray:
        return np.asarray(np.expm1(np.log(values) / hold_years) * 100)

    terminal_annual_appreciation = annual_cagr(market_paths.sale_home_value_multipliers[:, hold_months])
    terminal_appreciation = (market_paths.sale_home_value_multipliers[:, hold_months] - 1) * 100
    terminal_sp500_annual_return = annual_cagr(market_paths.portfolio_multipliers[:, hold_months])
    terminal_rent_growth = annual_cagr(market_paths.rent_multipliers[:, hold_months])
    appreciation_matrix = (market_paths.home_value_multipliers - 1) * 100

    yearly_months = list(range(0, hold_months + 1, MONTHS_PER_YEAR))

    def policy_actions_for_rollout(index: int) -> list[PolicyAction]:
        actions: list[PolicyAction] = []
        for month_index, net_cash in enumerate(housing.owner_cash_flow_usd[index]):
            if abs(net_cash) < 1:
                continue
            actions.append(
                PolicyActionTrade(
                    month_index=month_index,
                    action_type="sold_sp500" if net_cash < 0 else "bought_sp500",
                    amount_usd=round(abs(net_cash)),
                    reason="purchase_funding" if month_index == 0 and net_cash < 0 else "housing_cashflow",
                )
            )
        if housing.occupied_months < hold_months:
            actions.append(
                PolicyActionRental(
                    month_index=max(1, housing.occupied_months + 1),
                    action_type="moved_out_and_rented_property"
                    if housing.occupied_months > 0
                    else "rented_property_out_from_start",
                )
            )
        actions.extend(
            PolicyActionPrivateEquity(
                month_index=sale.month_index,
                action_type="sold_privateEquity",
                event_type=sale.event_type,
                units=sale.units,
                price_usd_per_unit=sale.price_usd_per_unit,
                after_tax_proceeds_usd=round(sale.after_tax_proceeds_usd),
                reason="guardrail_policy",
            )
            for sale in private_equity_liquidity_paths[index].sales
        )
        actions.sort(key=lambda action: (action.month_index, action.action_type))
        return actions

    return StochasticOutcomeView(
        model_run=ModelRunMetadata(
            fitted_with="PyMC joint backend",
            policy={"private_equity_sale": sale_policy.model_dump(), "reserve": reserve_policy.model_dump()},
        ),
        rollouts=rollout_count,
        probability_buy_wins=float(np.mean(terminal_deltas > 0)),
        probability_liquidity_shortfall=sum(1 for value in liquidity_shortfalls if value) / rollout_count,
        probability_private_equity_sale=sum(1 for value in private_equity_sales if value) / rollout_count,
        terminal_economic_net_worth=percentile_fields(terminal_economic_net_worth.tolist()),
        terminal_liquid_net_worth=percentile_fields(terminal_liquid_net_worth.tolist()),
        terminal_private_equity_event_pv=percentile_fields(terminal_private_equity_event_pv.tolist()),
        terminal_private_equity_liquid_value=percentile_fields(terminal_private_equity_liquid_value.tolist()),
        terminal_delta=percentile_fields(terminal_deltas.tolist()),
        terminal_annual_appreciation=percentile_fields(terminal_annual_appreciation.tolist()),
        terminal_appreciation=percentile_fields(terminal_appreciation.tolist()),
        terminal_sp500_annual_return=percentile_fields(terminal_sp500_annual_return.tolist()),
        terminal_rent_growth=percentile_fields(terminal_rent_growth.tolist()),
        rent_path_fan_columns=aggregate_fan_matrix(housing.rent_path_usd),
        buy_liquid_fan_columns=aggregate_fan_matrix(housing.buy_liquid_usd),
        buy_path_fan_columns=aggregate_fan_matrix(housing.buy_path_usd),
        economic_net_worth_fan_columns=aggregate_fan_matrix(economic_net_worth),
        liquid_net_worth_fan_columns=aggregate_fan_matrix(liquid_net_worth),
        private_equity_event_pv_fan_columns=aggregate_fan_matrix(private_equity_mark),
        delta_fan_columns=aggregate_fan_matrix(housing.delta_usd),
        appreciation_fan_columns=aggregate_fan_matrix(appreciation_matrix),
        delta_histogram=build_histogram(terminal_deltas.tolist()),
        sample_path_columns=[
            SamplePathColumns(
                delta_path_columns=columnar_table_from_rows(
                    [
                        {
                            "month_index": month_index,
                            "year": month_index / MONTHS_PER_YEAR,
                            "delta_usd": float(housing.delta_usd[index, month_index]),
                        }
                        for month_index in yearly_months
                    ]
                ),
                economic_net_worth_path_columns=columnar_table_from_rows(
                    [
                        {
                            "month_index": month_index,
                            "year": month_index / MONTHS_PER_YEAR,
                            "economic_net_worth_usd": float(economic_net_worth[index, month_index]),
                        }
                        for month_index in range(hold_months + 1)
                    ]
                ),
                appreciation_path_columns=columnar_table_from_rows(
                    [
                        {
                            "month_index": month_index,
                            "year": month_index / MONTHS_PER_YEAR,
                            "cumulative_appreciation_pct": float(appreciation_matrix[index, month_index]),
                        }
                        for month_index in range(hold_months + 1)
                    ]
                ),
                policy_actions=policy_actions_for_rollout(index),
            )
            for index in range(min(12, rollout_count))
        ],
    )
