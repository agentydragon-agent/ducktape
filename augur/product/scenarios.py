"""Build sim scenarios from product `ScenarioKey` payloads."""

from __future__ import annotations

from more_itertools import one

from augur.api.config import Config
from augur.api.portfolio import PortfolioConfig
from augur.api.scenario_set import ActorRole
from augur.model.series import INFLATION_SERIES_ID, rent_series_id
from augur.product.wire import FundingPolicy, ScenarioKey
from augur.sim.scenario import (
    Agent,
    InitialAccountBalance,
    InitialLot,
    LiquidityPolicy,
    ObligationType,
    RecurringObligation,
    Scenario,
    SeriesIndexedAmount,
    TaxProfile,
)

PRIMARY_ACCOUNT_ID = "checking"
SPEND_SINK_AGENT_ID = "spend_sink"
SPEND_SINK_ACCOUNT_ID = "checking"
SPEND_OBLIGATION_ID = "monthly_spend"
LANDLORD_AGENT_ID = "landlord"
LANDLORD_ACCOUNT_ID = "checking"
RENT_OBLIGATION_ID = "outside_rent"
TAX_AUTHORITY_AGENT_ID = "tax_authority"
TAX_AUTHORITY_ACCOUNT_ID = "checking"


def resolve_primary_agent_id(augur_config: Config) -> str:
    return one(agent.actor_id for agent in augur_config.agents if agent.role == ActorRole.PRIMARY_OWNER)


def initial_lots_from_portfolio(portfolio: PortfolioConfig, *, primary_agent_id: str) -> tuple[InitialLot, ...]:
    lots = portfolio.to_initial_lots()
    unsupported_owner_ids = sorted({lot.agent_id for lot in lots if lot.agent_id != primary_agent_id})
    if unsupported_owner_ids:
        raise ValueError(
            "product portfolio projection only supports public-security lots owned by the primary agent; "
            f"got owner agent ids {unsupported_owner_ids}"
        )
    return lots


def asset_label_by_series_id(portfolio: PortfolioConfig) -> dict[str, str]:
    return {
        position.value_series_id: f"{position.label or position.symbol} ({position.symbol})"
        for position in portfolio.public_securities
    }


def required_level_series(scenario_key: ScenarioKey, *, initial_lots: tuple[InitialLot, ...]) -> frozenset[str]:
    series_ids = {lot.asset_id for lot in initial_lots}
    if scenario_key.spend_index == "inflation":
        series_ids.add(INFLATION_SERIES_ID)
    if scenario_key.monthly_rent_usd > 0:
        assert scenario_key.rental_location_id is not None  # wire validator guarantees
        series_ids.add(rent_series_id(scenario_key.rental_location_id))
    return frozenset(series_ids)


def build_scenario(
    scenario_key: ScenarioKey, *, primary_agent_id: str, initial_cash_usd: float, initial_lots: tuple[InitialLot, ...]
) -> Scenario:
    horizon_months = int(scenario_key.horizon_months)
    end_month = horizon_months - 1

    agents = [
        Agent(agent_id=primary_agent_id),
        Agent(agent_id=SPEND_SINK_AGENT_ID),
        Agent(agent_id=TAX_AUTHORITY_AGENT_ID),
    ]
    initial_cash = [
        InitialAccountBalance(agent_id=primary_agent_id, account_id=PRIMARY_ACCOUNT_ID, balance_usd=initial_cash_usd),
        InitialAccountBalance(agent_id=SPEND_SINK_AGENT_ID, account_id=SPEND_SINK_ACCOUNT_ID, balance_usd=0.0),
        InitialAccountBalance(agent_id=TAX_AUTHORITY_AGENT_ID, account_id=TAX_AUTHORITY_ACCOUNT_ID, balance_usd=0.0),
    ]
    recurring_obligations = [
        RecurringObligation(
            start_month=0,
            end_month=end_month,
            obligation_id=SPEND_OBLIGATION_ID,
            obligation_type=ObligationType.CASH_SPEND,
            agent_id=primary_agent_id,
            from_account_id=PRIMARY_ACCOUNT_ID,
            to_agent_id=SPEND_SINK_AGENT_ID,
            to_account_id=SPEND_SINK_ACCOUNT_ID,
            amount_due_usd=_monthly_spend_amount(scenario_key),
        )
    ]

    if scenario_key.monthly_rent_usd > 0:
        assert scenario_key.rental_location_id is not None  # wire validator guarantees
        agents.append(Agent(agent_id=LANDLORD_AGENT_ID))
        initial_cash.append(
            InitialAccountBalance(agent_id=LANDLORD_AGENT_ID, account_id=LANDLORD_ACCOUNT_ID, balance_usd=0.0)
        )
        recurring_obligations.append(
            RecurringObligation(
                start_month=0,
                end_month=end_month,
                obligation_id=RENT_OBLIGATION_ID,
                obligation_type=ObligationType.OUTSIDE_RENT,
                agent_id=primary_agent_id,
                from_account_id=PRIMARY_ACCOUNT_ID,
                to_agent_id=LANDLORD_AGENT_ID,
                to_account_id=LANDLORD_ACCOUNT_ID,
                amount_due_usd=SeriesIndexedAmount(
                    base_amount_usd=float(scenario_key.monthly_rent_usd),
                    series_id=rent_series_id(scenario_key.rental_location_id),
                    adjustment_period_months=12,
                ),
            )
        )

    return Scenario(
        agents=agents,
        initial_lots=list(initial_lots),
        initial_cash=initial_cash,
        recurring_obligations=recurring_obligations,
        tax_profiles=[
            TaxProfile(
                agent_id=primary_agent_id,
                filing_status="single",
                jurisdiction_ids=["federal_us", "california"],
                tax_authority_agent_id=TAX_AUTHORITY_AGENT_ID,
                payment_account_id=PRIMARY_ACCOUNT_ID,
                tax_authority_account_id=TAX_AUTHORITY_ACCOUNT_ID,
            )
        ],
        liquidity_policies=_liquidity_policies_from_funding_policy(
            scenario_key.funding_policy, primary_agent_id=primary_agent_id, initial_lots=initial_lots
        ),
        horizon_months=horizon_months,
    )


def _monthly_spend_amount(scenario_key: ScenarioKey) -> float | SeriesIndexedAmount:
    if scenario_key.spend_index == "inflation":
        return SeriesIndexedAmount(
            base_amount_usd=float(scenario_key.monthly_spend_usd),
            series_id=INFLATION_SERIES_ID,
            adjustment_period_months=1,
        )
    if scenario_key.spend_index == "none":
        return float(scenario_key.monthly_spend_usd)
    raise ValueError(f"unsupported spend_index: {scenario_key.spend_index!r}")


def _liquidity_policies_from_funding_policy(
    funding_policy: FundingPolicy, *, primary_agent_id: str, initial_lots: tuple[InitialLot, ...]
) -> list[LiquidityPolicy]:
    asset_preference_chain = _asset_preference_chain_from_sell_order(funding_policy, initial_lots=initial_lots)
    if not asset_preference_chain:
        return []
    return [
        LiquidityPolicy(
            agent_id=primary_agent_id,
            account_id=PRIMARY_ACCOUNT_ID,
            asset_preference_chain=asset_preference_chain,
            cash_buffer_trigger_below_usd=float(funding_policy.cash_buffer_trigger_below_usd),
            cash_buffer_sale_usd=float(funding_policy.cash_buffer_sale_usd),
            cause_id_prefix="product_funding_sale",
        )
    ]


def _asset_preference_chain_from_sell_order(
    funding_policy: FundingPolicy, *, initial_lots: tuple[InitialLot, ...]
) -> list[str]:
    asset_ids: list[str] = []
    for bucket in funding_policy.sell_order:
        if bucket == "public_securities":
            asset_ids.extend(lot.asset_id for lot in initial_lots)
        else:
            raise ValueError(f"unsupported sell_order bucket: {bucket!r}")
    return list(dict.fromkeys(asset_ids))
