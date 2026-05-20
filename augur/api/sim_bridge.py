"""Bridge from current API scenario shapes into `augur/sim`.

This is not a parity shim for `augur/core`. It is the first narrow translator
for scenarios that already have native sim equivalents. Unsupported core
features fail loudly so they can be ported deliberately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import polars as pl

from augur.core.scenario_set import (
    AccountType as CoreAccountType,
    AssetType as CoreAssetType,
    CheckingFloorSellPublicStockPolicy as CoreCheckingFloorSellPublicStockPolicy,
    CryptoAssetPosition,
    GenericSp500StockPosition,
    MarketRequest,
    MonthlySpendPolicy,
    PrivateEquityPosition,
    Scenario as CoreScenario,
    ScenarioSet,
)
from augur.model.sim_market_api import (
    MARKET_LEVELS_SCHEMA,
    JointMarketModel,
    MarketSamplingRequest,
    SampledMarketBundle,
)
from augur.model.sim_market_series import SP500_SERIES_ID
from augur.sim.market import materialize_sampled_market
from augur.sim.run import SimulationRun
from augur.sim.scenario import Agent, InitialAccountBalance, InitialLot, LiquidityPolicy, RecurringObligation, Scenario
from augur.sim.simulate import simulate_with_market

EXTERNAL_AGENT_ID = "external"
EXTERNAL_ACCOUNT_ID = "checking"
DEFAULT_ACCOUNT_ID = "checking"


class UnsupportedSimBridgeScenarioError(ValueError):
    """Raised when the current bridge would drop API scenario semantics."""


@dataclass(frozen=True)
class SimScenarioTranslation:
    scenario_id: str
    scenario: Scenario
    required_level_series: frozenset[str]
    required_event_series: frozenset[str] = frozenset()


def translate_scenario_set(
    scenario_set: ScenarioSet, *, configured_lots: tuple[InitialLot, ...] = ()
) -> tuple[SimScenarioTranslation, ...]:
    """Translate enabled API scenarios into native sim scenarios."""

    return tuple(
        translate_scenario(scenario, market_request=scenario_set.market_request, configured_lots=configured_lots)
        for scenario in scenario_set.scenarios
        if scenario.enabled
    )


def translate_scenario(
    scenario: CoreScenario, *, market_request: MarketRequest, configured_lots: tuple[InitialLot, ...] = ()
) -> SimScenarioTranslation:
    _reject_unsupported_features(scenario)
    initial_lots = list(configured_lots) if configured_lots else _initial_lots(scenario)
    sim_scenario = Scenario(
        agents=_agents(scenario, initial_lots=initial_lots),
        initial_cash=_initial_cash(scenario),
        initial_lots=initial_lots,
        recurring_obligations=_monthly_spend_obligations(scenario),
        liquidity_policies=_liquidity_policies(scenario),
        horizon_months=market_request.horizon_months,
    )
    return SimScenarioTranslation(
        scenario_id=scenario.scenario_id,
        scenario=sim_scenario,
        required_level_series=required_level_series_for_scenario(sim_scenario),
    )


def required_level_series_for_scenario(scenario: Scenario) -> frozenset[str]:
    """Market level series needed to execute this sim scenario."""

    return frozenset(
        [
            *(lot.asset_id for lot in scenario.initial_lots),
            *(sale.asset_id for sale in scenario.scheduled_asset_sales if sale.price_per_unit_usd is None),
            *(asset_id for policy in scenario.liquidity_policies for asset_id in policy.asset_preference_chain),
        ]
    )


def sample_market_for_scenario(
    market_model: JointMarketModel,
    translation: SimScenarioTranslation,
    *,
    market_request: MarketRequest,
    level_anchors: Mapping[str, float] | None = None,
) -> SampledMarketBundle:
    sampled = market_model.sample(
        _market_sampling_request(
            horizon_months=translation.scenario.horizon_months,
            market_request=market_request,
            required_level_series=translation.required_level_series,
            required_event_series=translation.required_event_series,
        )
    )
    return anchor_sampled_market_levels(sampled, level_anchors or {})


def simulate_translation(
    market_model: JointMarketModel,
    translation: SimScenarioTranslation,
    *,
    market_request: MarketRequest,
    level_anchors: Mapping[str, float] | None = None,
) -> SimulationRun:
    _, run = sample_and_simulate_translation(
        market_model, translation, market_request=market_request, level_anchors=level_anchors
    )
    return run


def sample_and_simulate_translation(
    market_model: JointMarketModel,
    translation: SimScenarioTranslation,
    *,
    market_request: MarketRequest,
    level_anchors: Mapping[str, float] | None = None,
) -> tuple[SampledMarketBundle, SimulationRun]:
    sampled = sample_market_for_scenario(
        market_model, translation, market_request=market_request, level_anchors=level_anchors
    )
    return (
        sampled,
        simulate_with_market(
            translation.scenario, rollout_count=market_request.rollout_count, market=materialize_sampled_market(sampled)
        ),
    )


def sample_market_for_translations(
    market_model: JointMarketModel,
    translations: tuple[SimScenarioTranslation, ...],
    *,
    market_request: MarketRequest,
    level_anchors: Mapping[str, float] | None = None,
) -> SampledMarketBundle:
    sampled = market_model.sample(
        _market_sampling_request(
            horizon_months=market_request.horizon_months,
            market_request=market_request,
            required_level_series=frozenset(
                series for translation in translations for series in translation.required_level_series
            ),
            required_event_series=frozenset(
                series for translation in translations for series in translation.required_event_series
            ),
        )
    )
    return anchor_sampled_market_levels(sampled, level_anchors or {})


def anchor_sampled_market_levels(
    sampled: SampledMarketBundle, level_anchors: Mapping[str, float]
) -> SampledMarketBundle:
    anchors = {series_id: float(value) for series_id, value in level_anchors.items()}
    if not anchors or sampled.levels.is_empty():
        return sampled

    sampled_series = set(sampled.levels.get_column("series_id").unique().to_list())
    active_anchors = {series_id: value for series_id, value in anchors.items() if series_id in sampled_series}
    if not active_anchors:
        return SampledMarketBundle(
            levels=sampled.levels, events=sampled.events, metadata={**sampled.metadata, "level_anchors": anchors}
        )

    anchor_frame = pl.DataFrame(
        {"series_id": list(active_anchors), "_anchor_value": list(active_anchors.values())},
        schema={"series_id": pl.Utf8(), "_anchor_value": pl.Float64()},
    )
    bases = (
        sampled.levels.filter(pl.col("month_index") == 0)
        .join(anchor_frame, on="series_id", how="inner")
        .select("rollout_index", "series_id", "_anchor_value", pl.col("value").alias("_base_value"))
    )
    zero_bases = bases.filter(pl.col("_base_value") == 0.0)
    if not zero_bases.is_empty():
        series_ids = sorted(set(zero_bases.get_column("series_id").to_list()))
        raise ValueError(f"sampled market level(s) have zero month-0 value and cannot be anchored: {series_ids}")

    levels = (
        sampled.levels.join(bases, on=["rollout_index", "series_id"], how="left")
        .with_columns(
            value=pl.when(pl.col("_anchor_value").is_not_null())
            .then(pl.col("value") * pl.col("_anchor_value") / pl.col("_base_value"))
            .otherwise(pl.col("value"))
        )
        .select(MARKET_LEVELS_SCHEMA.names())
    )
    return SampledMarketBundle(
        levels=levels, events=sampled.events, metadata={**sampled.metadata, "level_anchors": anchors}
    )


def _market_sampling_request(
    *,
    horizon_months: int,
    market_request: MarketRequest,
    required_level_series: frozenset[str],
    required_event_series: frozenset[str],
) -> MarketSamplingRequest:
    return MarketSamplingRequest(
        horizon_months=horizon_months,
        rollout_seeds=rollout_seeds_from_market_request(market_request),
        required_level_series=required_level_series,
        required_event_series=required_event_series,
    )


def rollout_seeds_from_market_request(market_request: MarketRequest) -> tuple[int, ...]:
    return tuple(
        int(child.generate_state(1, dtype=np.uint64)[0])
        for child in np.random.SeedSequence(market_request.seed).spawn(market_request.rollout_count)
    )


def _agents(scenario: CoreScenario, *, initial_lots: list[InitialLot]) -> list[Agent]:
    agent_ids = {actor.actor_id for actor in scenario.actors}
    agent_ids.update(lot.agent_id for lot in initial_lots)
    if scenario.policies:
        agent_ids.add(EXTERNAL_AGENT_ID)
    return [Agent(agent_id=agent_id) for agent_id in sorted(agent_ids)]


def _initial_cash(scenario: CoreScenario) -> list[InitialAccountBalance]:
    return [
        InitialAccountBalance(
            agent_id=account.owner_actor_id, account_id=account.account_id, balance_usd=account.balance_usd
        )
        for account in scenario.initial_balance_sheet.accounts
    ]


def _initial_lots(scenario: CoreScenario) -> list[InitialLot]:
    lots: list[InitialLot] = []
    for asset in scenario.initial_balance_sheet.assets:
        if not isinstance(asset, GenericSp500StockPosition):
            continue
        if asset.value_usd <= 0:
            continue
        lots.append(
            InitialLot(
                lot_id=f"{asset.asset_id}_lot",
                agent_id=asset.owner_actor_id,
                asset_id=SP500_SERIES_ID,
                purchase_month_index=0,
                quantity=asset.value_usd,
                cost_basis_per_unit_usd=_cost_basis_per_unit(asset),
            )
        )
    return lots


def _cost_basis_per_unit(asset: GenericSp500StockPosition) -> float:
    if asset.value_usd <= 0:
        return 0.0
    return (asset.cost_basis_usd if asset.cost_basis_usd is not None else asset.value_usd) / asset.value_usd


def _monthly_spend_obligations(scenario: CoreScenario) -> list[RecurringObligation]:
    obligations: list[RecurringObligation] = []
    for policy in scenario.policies:
        if not isinstance(policy, MonthlySpendPolicy) or policy.monthly_spend_usd <= 0:
            continue
        if policy.inflation_adjusted:
            raise UnsupportedSimBridgeScenarioError("inflation-adjusted monthly spend is not ported to augur/sim yet")
        obligations.append(
            RecurringObligation(
                start_month=0,
                obligation_id=policy.policy_id,
                obligation_type="monthly_spend",
                agent_id=policy.actor_id,
                from_account_id=DEFAULT_ACCOUNT_ID,
                to_agent_id=EXTERNAL_AGENT_ID,
                to_account_id=EXTERNAL_ACCOUNT_ID,
                amount_due_usd=policy.monthly_spend_usd,
            )
        )
    return obligations


def _liquidity_policies(scenario: CoreScenario) -> list[LiquidityPolicy]:
    policies: list[LiquidityPolicy] = []
    for policy in scenario.policies:
        if not isinstance(policy, CoreCheckingFloorSellPublicStockPolicy):
            continue
        policies.append(
            LiquidityPolicy(
                agent_id=policy.actor_id,
                account_id=DEFAULT_ACCOUNT_ID,
                asset_preference_chain=[_asset_preference(asset_type) for asset_type in policy.sale_asset_preference],
                cash_buffer_trigger_below_usd=policy.floor_usd,
                cash_buffer_sale_usd=policy.sale_amount_usd,
                cause_id_prefix=policy.policy_id,
            )
        )
    return policies


def _asset_preference(asset_type: CoreAssetType) -> str:
    if asset_type is CoreAssetType.GENERIC_SP500_STOCK:
        return SP500_SERIES_ID
    raise UnsupportedSimBridgeScenarioError(f"liquidity preference {asset_type} is not ported to augur/sim yet")


def _reject_unsupported_features(scenario: CoreScenario) -> None:
    unsupported: list[str] = []
    if scenario.events:
        unsupported.append("events")
    if scenario.property_selection.property_id is not None:
        unsupported.append("property_selection")
    if scenario.tax_profile.annual_ordinary_income_usd:
        unsupported.append("tax_profile.annual_ordinary_income_usd")
    if scenario.occupancy_plan.outside_rent_monthly_usd:
        unsupported.append("occupancy_plan.outside_rent_monthly_usd")
    if any(account.account_type is not CoreAccountType.CHECKING for account in scenario.initial_balance_sheet.accounts):
        unsupported.append("non-checking accounts")
    if any(
        isinstance(asset, CryptoAssetPosition | PrivateEquityPosition)
        for asset in scenario.initial_balance_sheet.assets
    ):
        unsupported.append("crypto/private-equity positions")
    if unsupported:
        raise UnsupportedSimBridgeScenarioError(
            f"scenario {scenario.scenario_id!r} uses unsupported sim bridge features: {', '.join(unsupported)}"
        )
