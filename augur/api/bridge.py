"""Bridge from current API scenario shapes into `augur/sim`.

This is not a parity shim for the deleted legacy core engine. It is the first
narrow translator for scenarios that already have native runtime equivalents.
Unsupported legacy API features fail loudly so they can be ported deliberately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import polars as pl

from augur.api.scenario_set import (
    AccountType as CoreAccountType,
    ActorRole,
    AssetType as CoreAssetType,
    CheckingFloorSellPublicStockPolicy as CoreCheckingFloorSellPublicStockPolicy,
    CryptoAssetPosition,
    Event as CoreEvent,
    FinancingMode,
    GenericSp500StockPosition,
    MarketRequest,
    MonthlySpendPolicy,
    MortgageOriginationEvent,
    PrivateEquityPosition,
    PrivateEquitySalePolicy,
    PropertyPurchaseEvent,
    Scenario as CoreScenario,
    ScenarioSet,
)
from augur.model.market_api import MARKET_LEVELS_SCHEMA, JointMarketModel, MarketSamplingRequest, SampledMarketBundle
from augur.model.series import SP500_SERIES_ID, private_equity_series_id
from augur.sim.market import materialize_sampled_market
from augur.sim.run import SimulationRun
from augur.sim.scenario import (
    Agent,
    InitialAccountBalance,
    InitialLot,
    LiquidityPolicy,
    MortgageFinancing,
    RecurringObligation,
    Scenario,
    ScheduledPropertyPurchase,
)
from augur.sim.simulate import simulate_with_market

EXTERNAL_AGENT_ID = "external"
EXTERNAL_ACCOUNT_ID = "checking"
DEFAULT_ACCOUNT_ID = "checking"
PROPERTY_SELLER_AGENT_ID = "property_seller"
MORTGAGE_LENDER_AGENT_ID = "mortgage_lender"


class UnsupportedBridgeScenarioError(ValueError):
    """Raised when the current bridge would drop API scenario semantics."""


@dataclass(frozen=True)
class ScenarioTranslation:
    scenario_id: str
    scenario: Scenario
    required_level_series: frozenset[str]
    required_event_series: frozenset[str] = frozenset()


def translate_scenario_set(
    scenario_set: ScenarioSet, *, configured_lots: tuple[InitialLot, ...] = ()
) -> tuple[ScenarioTranslation, ...]:
    """Translate enabled API scenarios into runtime scenarios."""

    return tuple(
        translate_scenario(scenario, market_request=scenario_set.market_request, configured_lots=configured_lots)
        for scenario in scenario_set.scenarios
        if scenario.enabled
    )


def translate_scenario(
    scenario: CoreScenario, *, market_request: MarketRequest, configured_lots: tuple[InitialLot, ...] = ()
) -> ScenarioTranslation:
    _reject_unsupported_features(scenario)
    initial_lots = [*configured_lots, *_initial_lots(scenario, include_public_positions=not configured_lots)]
    property_purchases = _property_purchases(scenario)
    translated_scenario = Scenario(
        agents=_agents(scenario, initial_lots=initial_lots, property_purchases=property_purchases),
        initial_cash=_initial_cash(scenario, property_purchases=property_purchases),
        initial_lots=initial_lots,
        scheduled_property_purchases=property_purchases,
        recurring_obligations=_monthly_spend_obligations(scenario),
        liquidity_policies=_liquidity_policies(scenario),
        horizon_months=market_request.horizon_months,
    )
    return ScenarioTranslation(
        scenario_id=scenario.scenario_id,
        scenario=translated_scenario,
        required_level_series=required_level_series_for_scenario(translated_scenario),
    )


def required_level_series_for_scenario(scenario: Scenario) -> frozenset[str]:
    """Market level series needed to execute this scenario."""

    return frozenset(
        [
            *(lot.asset_id for lot in scenario.initial_lots),
            *(sale.asset_id for sale in scenario.scheduled_asset_sales if sale.price_per_unit_usd is None),
            *(asset_id for policy in scenario.liquidity_policies for asset_id in policy.asset_preference_chain),
        ]
    )


def sample_market_for_scenario(
    market_model: JointMarketModel,
    translation: ScenarioTranslation,
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
    translation: ScenarioTranslation,
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
    translation: ScenarioTranslation,
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
    translations: tuple[ScenarioTranslation, ...],
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


def _agents(
    scenario: CoreScenario, *, initial_lots: list[InitialLot], property_purchases: list[ScheduledPropertyPurchase]
) -> list[Agent]:
    agent_ids = {actor.actor_id for actor in scenario.actors}
    agent_ids.update(lot.agent_id for lot in initial_lots)
    agent_ids.update(purchase.seller_agent_id for purchase in property_purchases)
    agent_ids.update(
        purchase.mortgage.lender_agent_id for purchase in property_purchases if purchase.mortgage is not None
    )
    if scenario.policies:
        agent_ids.add(EXTERNAL_AGENT_ID)
    return [Agent(agent_id=agent_id) for agent_id in sorted(agent_ids)]


def _initial_cash(
    scenario: CoreScenario, *, property_purchases: list[ScheduledPropertyPurchase]
) -> list[InitialAccountBalance]:
    balances = [
        InitialAccountBalance(
            agent_id=account.owner_actor_id, account_id=account.account_id, balance_usd=account.balance_usd
        )
        for account in scenario.initial_balance_sheet.accounts
    ]
    existing = {(balance.agent_id, balance.account_id) for balance in balances}
    for agent_id, account_id in _counterparty_accounts(property_purchases):
        if (agent_id, account_id) in existing:
            continue
        balances.append(InitialAccountBalance(agent_id=agent_id, account_id=account_id, balance_usd=0.0))
        existing.add((agent_id, account_id))
    return balances


def _counterparty_accounts(property_purchases: list[ScheduledPropertyPurchase]) -> list[tuple[str, str]]:
    accounts: list[tuple[str, str]] = []
    for purchase in property_purchases:
        accounts.append((purchase.seller_agent_id, purchase.seller_account_id))
        if purchase.mortgage is not None:
            accounts.append((purchase.mortgage.lender_agent_id, purchase.mortgage.lender_account_id))
    return accounts


def _initial_lots(scenario: CoreScenario, *, include_public_positions: bool = True) -> list[InitialLot]:
    lots: list[InitialLot] = []
    for asset in scenario.initial_balance_sheet.assets:
        if isinstance(asset, GenericSp500StockPosition):
            if not include_public_positions or asset.value_usd <= 0:
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
        elif isinstance(asset, PrivateEquityPosition):
            lots.append(
                InitialLot(
                    lot_id=f"{asset.asset_id}_lot",
                    agent_id=asset.owner_actor_id,
                    asset_id=private_equity_series_id(asset.market_routing_key),
                    purchase_month_index=0,
                    quantity=float(asset.units),
                    cost_basis_per_unit_usd=_private_equity_cost_basis_per_unit(asset),
                )
            )
    return lots


def _cost_basis_per_unit(asset: GenericSp500StockPosition) -> float:
    if asset.value_usd <= 0:
        return 0.0
    return (asset.cost_basis_usd if asset.cost_basis_usd is not None else asset.value_usd) / asset.value_usd


def _private_equity_cost_basis_per_unit(asset: PrivateEquityPosition) -> float:
    return float(asset.cost_basis_usd or 0.0) / float(asset.units)


def _property_purchases(scenario: CoreScenario) -> list[ScheduledPropertyPurchase]:
    selection = scenario.property_selection
    if selection.property_id is None:
        return []
    if selection.location_id is None:
        raise UnsupportedBridgeScenarioError(
            f"scenario {scenario.scenario_id!r} selects property {selection.property_id!r} without location_id"
        )
    if selection.purchase_price_usd is None:
        raise UnsupportedBridgeScenarioError(
            f"scenario {scenario.scenario_id!r} selects property {selection.property_id!r} without purchase_price_usd"
        )

    purchase_price_usd = float(selection.purchase_price_usd)
    loan_principal_usd = _loan_principal_usd(scenario, purchase_price_usd=purchase_price_usd)
    mortgage = _mortgage_financing(scenario, property_id=selection.property_id, principal_usd=loan_principal_usd)
    return [
        ScheduledPropertyPurchase(
            month=0,
            cause_id=f"{selection.property_id}_purchase",
            property_id=selection.property_id,
            location_id=selection.location_id,
            buyer_agent_id=_primary_owner_actor_id(scenario),
            buyer_account_id=DEFAULT_ACCOUNT_ID,
            seller_agent_id=PROPERTY_SELLER_AGENT_ID,
            seller_account_id=DEFAULT_ACCOUNT_ID,
            purchase_price_usd=purchase_price_usd,
            down_payment_usd=purchase_price_usd - loan_principal_usd,
            buyer_closing_cost_usd=purchase_price_usd * float(scenario.transaction_costs.closing_cost_buy_pct) / 100.0,
            ownership_pct=1.0,
            mortgage=mortgage,
        )
    ]


def _primary_owner_actor_id(scenario: CoreScenario) -> str:
    primary_owner_ids = [actor.actor_id for actor in scenario.actors if actor.role is ActorRole.PRIMARY_OWNER]
    if len(primary_owner_ids) != 1:
        raise UnsupportedBridgeScenarioError(
            f"scenario {scenario.scenario_id!r} must have exactly one primary_owner actor for sim translation"
        )
    return primary_owner_ids[0]


def _loan_principal_usd(scenario: CoreScenario, *, purchase_price_usd: float) -> float:
    financing = scenario.financing
    if financing.financing_mode is FinancingMode.CASH:
        if financing.loan_amount_usd not in (None, 0):
            raise UnsupportedBridgeScenarioError("cash financing must not set loan_amount_usd")
        return 0.0
    if financing.loan_amount_usd is not None:
        loan_principal_usd = float(financing.loan_amount_usd)
    else:
        if financing.down_payment_pct > 100:
            raise UnsupportedBridgeScenarioError("down_payment_pct must be <= 100 for sim translation")
        loan_principal_usd = purchase_price_usd * (1.0 - float(financing.down_payment_pct) / 100.0)
    if loan_principal_usd > purchase_price_usd:
        raise UnsupportedBridgeScenarioError("loan_amount_usd must not exceed purchase_price_usd")
    return loan_principal_usd


def _mortgage_financing(scenario: CoreScenario, *, property_id: str, principal_usd: float) -> MortgageFinancing | None:
    if principal_usd <= 0:
        return None
    financing = scenario.financing
    if financing.mortgage_rate_pct is None:
        raise UnsupportedBridgeScenarioError(
            f"scenario {scenario.scenario_id!r} needs mortgage_rate_pct for sim mortgage translation"
        )
    return MortgageFinancing(
        liability_id=f"{property_id}_mortgage",
        lender_agent_id=MORTGAGE_LENDER_AGENT_ID,
        lender_account_id=DEFAULT_ACCOUNT_ID,
        principal_usd=principal_usd,
        annual_interest_rate=float(financing.mortgage_rate_pct) / 100.0,
        term_months=_mortgage_term_months(scenario),
    )


def _mortgage_term_months(scenario: CoreScenario) -> int:
    financing = scenario.financing
    if financing.financing_mode is FinancingMode.FIXED_30:
        return 30 * 12
    if financing.financing_mode is FinancingMode.FIXED_15:
        return 15 * 12
    if financing.financing_mode is FinancingMode.CUSTOM:
        if financing.mortgage_term_years is None:
            raise UnsupportedBridgeScenarioError(
                f"scenario {scenario.scenario_id!r} needs mortgage_term_years for custom sim mortgage translation"
            )
        return int(financing.mortgage_term_years) * 12
    raise UnsupportedBridgeScenarioError(f"financing mode {financing.financing_mode} is not ported to augur/sim yet")


def _monthly_spend_obligations(scenario: CoreScenario) -> list[RecurringObligation]:
    obligations: list[RecurringObligation] = []
    for policy in scenario.policies:
        if not isinstance(policy, MonthlySpendPolicy) or policy.monthly_spend_usd <= 0:
            continue
        if policy.inflation_adjusted:
            raise UnsupportedBridgeScenarioError("inflation-adjusted monthly spend is not ported to augur/sim yet")
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
    raise UnsupportedBridgeScenarioError(f"liquidity preference {asset_type} is not ported to augur/sim yet")


def _reject_unsupported_features(scenario: CoreScenario) -> None:
    unsupported: list[str] = []
    unsupported_events = _unsupported_events(scenario)
    if unsupported_events:
        unsupported.append(f"events ({', '.join(unsupported_events)})")
    if scenario.tax_profile.annual_ordinary_income_usd:
        unsupported.append("tax_profile.annual_ordinary_income_usd")
    if scenario.occupancy_plan.outside_rent_monthly_usd:
        unsupported.append("occupancy_plan.outside_rent_monthly_usd")
    if any(account.account_type is not CoreAccountType.CHECKING for account in scenario.initial_balance_sheet.accounts):
        unsupported.append("non-checking accounts")
    if any(isinstance(asset, CryptoAssetPosition) for asset in scenario.initial_balance_sheet.assets):
        unsupported.append("crypto positions")
    if any(
        isinstance(asset, PrivateEquityPosition) and asset.value_usd is not None
        for asset in scenario.initial_balance_sheet.assets
    ):
        unsupported.append("private-equity explicit value marks")
    if any(isinstance(policy, PrivateEquitySalePolicy) for policy in scenario.policies):
        unsupported.append("private-equity sale policies")
    if unsupported:
        raise UnsupportedBridgeScenarioError(
            f"scenario {scenario.scenario_id!r} uses unsupported sim bridge features: {', '.join(unsupported)}"
        )


def _unsupported_events(scenario: CoreScenario) -> list[str]:
    return [
        str(event.event_type)
        for event in scenario.events
        if not _is_redundant_property_bootstrap_event(scenario, event)
    ]


def _is_redundant_property_bootstrap_event(scenario: CoreScenario, event: CoreEvent) -> bool:
    selection = scenario.property_selection
    if selection.property_id is None or selection.purchase_price_usd is None:
        return False
    if not isinstance(event, PropertyPurchaseEvent | MortgageOriginationEvent):
        return False
    if event.month_index != 0 or event.property_id != selection.property_id:
        return False
    primary_owner_id = _primary_owner_actor_id(scenario)
    if event.actor_id is not None and event.actor_id != primary_owner_id:
        return False
    if isinstance(event, PropertyPurchaseEvent):
        return _optional_amount_matches(event.amount_usd, float(selection.purchase_price_usd))
    loan_principal_usd = _loan_principal_usd(scenario, purchase_price_usd=float(selection.purchase_price_usd))
    return _optional_amount_matches(event.amount_usd, loan_principal_usd)


def _optional_amount_matches(amount_usd: float | None, expected_usd: float) -> bool:
    return amount_usd is None or bool(np.isclose(float(amount_usd), expected_usd, rtol=0.0, atol=0.01))
