"""Build sim scenarios from product `ScenarioKey` payloads."""

from __future__ import annotations

from more_itertools import one

from augur.api.bootstrap import Property
from augur.api.config import Config
from augur.api.portfolio import PortfolioConfig
from augur.api.scenario_set import ActorRole
from augur.model.series import INFLATION_SERIES_ID, home_value_series_id, rent_series_id
from augur.product.wire import CashFinancing, FundingPolicy, MortgageFinancing, PropertyPurchase, ScenarioKey
from augur.sim.scenario import (
    Agent,
    InitialAccountBalance,
    InitialLot,
    LiquidityPolicy,
    MortgageFinancing as SimMortgageFinancing,
    MortgageInterestDeductionPolicy,
    ObligationType,
    PropertyTaxPolicy,
    RecurringObligation,
    Scenario,
    ScheduledPropertyPurchase,
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
PROPERTY_SELLER_AGENT_ID = "property_seller"
PROPERTY_SELLER_ACCOUNT_ID = "checking"
MORTGAGE_LENDER_AGENT_ID = "mortgage_lender"
MORTGAGE_LENDER_ACCOUNT_ID = "checking"
HOA_AGENT_ID = "hoa"
HOA_ACCOUNT_ID = "checking"
HOA_OBLIGATION_ID = "hoa_dues"
INSURER_AGENT_ID = "insurer"
INSURER_ACCOUNT_ID = "checking"
INSURANCE_OBLIGATION_ID = "homeowners_insurance"
MAINTENANCE_VENDOR_AGENT_ID = "maintenance_vendor"
MAINTENANCE_VENDOR_ACCOUNT_ID = "checking"
MAINTENANCE_OBLIGATION_ID = "property_maintenance"


def resolve_primary_agent_id(augur_config: Config) -> str:
    return one(agent.actor_id for agent in augur_config.agents if agent.role == ActorRole.PRIMARY_OWNER)


def initial_lots_from_portfolio(portfolio: PortfolioConfig, *, primary_agent_id: str) -> tuple[InitialLot, ...]:
    lots = portfolio.to_initial_lots()
    unsupported_owner_ids = sorted({lot.agent_id for lot in lots if lot.agent_id != primary_agent_id})
    if unsupported_owner_ids:
        raise ValueError(
            "product portfolio projection only supports holding lots owned by the primary agent; "
            f"got owner agent ids {unsupported_owner_ids}"
        )
    return lots


def asset_label_by_series_id(portfolio: PortfolioConfig) -> dict[str, str]:
    return {
        position.value_series_id: f"{position.label or position.symbol} ({position.symbol})"
        for position in portfolio.holdings
    }


def required_level_series(
    scenario_key: ScenarioKey, *, initial_lots: tuple[InitialLot, ...], properties_by_id: dict[str, Property]
) -> frozenset[str]:
    series_ids = {lot.asset_id for lot in initial_lots}
    if scenario_key.spend_index == "inflation":
        series_ids.add(INFLATION_SERIES_ID)
    if scenario_key.monthly_rent_usd > 0:
        assert scenario_key.rental_location_id is not None  # wire validator guarantees
        series_ids.add(rent_series_id(scenario_key.rental_location_id))
    if scenario_key.property_purchase is not None:
        property_ = properties_by_id[scenario_key.property_purchase.property_id]
        series_ids.add(home_value_series_id(property_.location_id))
        if property_.hoa_monthly_usd > 0:
            series_ids.add(INFLATION_SERIES_ID)
        if scenario_key.annual_insurance_pct > 0:
            series_ids.add(INFLATION_SERIES_ID)
        if scenario_key.annual_maintenance_pct > 0:
            series_ids.add(INFLATION_SERIES_ID)
    return frozenset(series_ids)


def build_scenario(
    scenario_key: ScenarioKey,
    *,
    primary_agent_id: str,
    initial_cash_usd: float,
    initial_lots: tuple[InitialLot, ...],
    properties_by_id: dict[str, Property],
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

    scheduled_property_purchases: list[ScheduledPropertyPurchase] = []
    property_tax_policies: list[PropertyTaxPolicy] = []
    mortgage_interest_deduction_policies: list[MortgageInterestDeductionPolicy] = []
    if scenario_key.property_purchase is not None:
        property_ = properties_by_id[scenario_key.property_purchase.property_id]
        agents.append(Agent(agent_id=PROPERTY_SELLER_AGENT_ID))
        initial_cash.append(
            InitialAccountBalance(
                agent_id=PROPERTY_SELLER_AGENT_ID, account_id=PROPERTY_SELLER_ACCOUNT_ID, balance_usd=0.0
            )
        )
        mortgage = _sim_mortgage_for(scenario_key.property_purchase, property_)
        if mortgage is not None:
            agents.append(Agent(agent_id=MORTGAGE_LENDER_AGENT_ID))
            initial_cash.append(
                InitialAccountBalance(
                    agent_id=MORTGAGE_LENDER_AGENT_ID, account_id=MORTGAGE_LENDER_ACCOUNT_ID, balance_usd=0.0
                )
            )
            if scenario_key.property_purchase.is_primary_residence:
                mortgage_interest_deduction_policies.append(
                    MortgageInterestDeductionPolicy(liability_id=mortgage.liability_id, owner_agent_id=primary_agent_id)
                )
        scheduled_property_purchases.append(
            _sim_property_purchase(
                scenario_key.property_purchase, property_, primary_agent_id=primary_agent_id, mortgage=mortgage
            )
        )
        property_tax_policies.append(
            PropertyTaxPolicy(
                property_id=property_.id,
                owner_agent_id=primary_agent_id,
                from_account_id=PRIMARY_ACCOUNT_ID,
                tax_authority_agent_id=TAX_AUTHORITY_AGENT_ID,
                tax_authority_account_id=TAX_AUTHORITY_ACCOUNT_ID,
                annual_tax_rate=None,  # fall back to location YAML
                start_month=0,
                end_month=end_month,
            )
        )
        if property_.hoa_monthly_usd > 0:
            agents.append(Agent(agent_id=HOA_AGENT_ID))
            initial_cash.append(
                InitialAccountBalance(agent_id=HOA_AGENT_ID, account_id=HOA_ACCOUNT_ID, balance_usd=0.0)
            )
            recurring_obligations.append(
                RecurringObligation(
                    start_month=0,
                    end_month=end_month,
                    obligation_id=HOA_OBLIGATION_ID,
                    obligation_type=ObligationType.HOA_DUES,
                    agent_id=primary_agent_id,
                    from_account_id=PRIMARY_ACCOUNT_ID,
                    to_agent_id=HOA_AGENT_ID,
                    to_account_id=HOA_ACCOUNT_ID,
                    amount_due_usd=SeriesIndexedAmount(
                        base_amount_usd=float(property_.hoa_monthly_usd),
                        series_id=INFLATION_SERIES_ID,
                        adjustment_period_months=1,
                    ),
                )
            )
        if scenario_key.annual_insurance_pct > 0:
            agents.append(Agent(agent_id=INSURER_AGENT_ID))
            initial_cash.append(
                InitialAccountBalance(agent_id=INSURER_AGENT_ID, account_id=INSURER_ACCOUNT_ID, balance_usd=0.0)
            )
            monthly_insurance_usd = float(scenario_key.annual_insurance_pct) / 100.0 * float(property_.price_usd) / 12.0
            recurring_obligations.append(
                RecurringObligation(
                    start_month=0,
                    end_month=end_month,
                    obligation_id=INSURANCE_OBLIGATION_ID,
                    obligation_type=ObligationType.HOMEOWNERS_INSURANCE,
                    agent_id=primary_agent_id,
                    from_account_id=PRIMARY_ACCOUNT_ID,
                    to_agent_id=INSURER_AGENT_ID,
                    to_account_id=INSURER_ACCOUNT_ID,
                    amount_due_usd=SeriesIndexedAmount(
                        base_amount_usd=monthly_insurance_usd, series_id=INFLATION_SERIES_ID, adjustment_period_months=1
                    ),
                )
            )
        if scenario_key.annual_maintenance_pct > 0:
            agents.append(Agent(agent_id=MAINTENANCE_VENDOR_AGENT_ID))
            initial_cash.append(
                InitialAccountBalance(
                    agent_id=MAINTENANCE_VENDOR_AGENT_ID, account_id=MAINTENANCE_VENDOR_ACCOUNT_ID, balance_usd=0.0
                )
            )
            monthly_maintenance_usd = (
                float(scenario_key.annual_maintenance_pct) / 100.0 * float(property_.price_usd) / 12.0
            )
            recurring_obligations.append(
                RecurringObligation(
                    start_month=0,
                    end_month=end_month,
                    obligation_id=MAINTENANCE_OBLIGATION_ID,
                    obligation_type=ObligationType.PROPERTY_MAINTENANCE,
                    agent_id=primary_agent_id,
                    from_account_id=PRIMARY_ACCOUNT_ID,
                    to_agent_id=MAINTENANCE_VENDOR_AGENT_ID,
                    to_account_id=MAINTENANCE_VENDOR_ACCOUNT_ID,
                    amount_due_usd=SeriesIndexedAmount(
                        base_amount_usd=monthly_maintenance_usd,
                        series_id=INFLATION_SERIES_ID,
                        adjustment_period_months=1,
                    ),
                )
            )

    return Scenario(
        agents=agents,
        initial_lots=list(initial_lots),
        initial_cash=initial_cash,
        recurring_obligations=recurring_obligations,
        scheduled_property_purchases=scheduled_property_purchases,
        property_tax_policies=property_tax_policies,
        mortgage_interest_deduction_policies=mortgage_interest_deduction_policies,
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


def _sim_mortgage_for(purchase: PropertyPurchase, property_: Property) -> SimMortgageFinancing | None:
    if isinstance(purchase.financing, CashFinancing):
        return None
    assert isinstance(purchase.financing, MortgageFinancing)
    principal = float(property_.price_usd) * (1.0 - purchase.financing.down_payment_pct / 100.0)
    return SimMortgageFinancing(
        liability_id=f"{property_.id}_mortgage",
        lender_agent_id=MORTGAGE_LENDER_AGENT_ID,
        lender_account_id=MORTGAGE_LENDER_ACCOUNT_ID,
        principal_usd=principal,
        annual_interest_rate=purchase.financing.annual_rate_pct / 100.0,
        term_months=purchase.financing.term_months,
    )


def _sim_property_purchase(
    purchase: PropertyPurchase, property_: Property, *, primary_agent_id: str, mortgage: SimMortgageFinancing | None
) -> ScheduledPropertyPurchase:
    purchase_price = float(property_.price_usd)
    if isinstance(purchase.financing, CashFinancing):
        down_payment = purchase_price
    else:
        down_payment = purchase_price * purchase.financing.down_payment_pct / 100.0
    return ScheduledPropertyPurchase(
        month=0,
        cause_id=f"{property_.id}_purchase",
        property_id=property_.id,
        location_id=property_.location_id,
        buyer_agent_id=primary_agent_id,
        buyer_account_id=PRIMARY_ACCOUNT_ID,
        seller_agent_id=PROPERTY_SELLER_AGENT_ID,
        seller_account_id=PROPERTY_SELLER_ACCOUNT_ID,
        purchase_price_usd=purchase_price,
        down_payment_usd=down_payment,
        buyer_closing_cost_usd=purchase_price * float(purchase.closing_cost_pct) / 100.0,
        ownership_pct=1.0,
        mortgage=mortgage,
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
    """Translate the wire's `sell_order` tuple to a deduplicated asset-ID list for the sim.

    `stocks` covers anything that isn't crypto or private equity — ETFs, individual stocks,
    mutual funds; `crypto` covers asset_ids under the `crypto:` namespace. Private equity
    (`private_equity:` namespace) is *never* included in any liquidity-sale bucket: it's only
    saleable at sparse tender events, dispatched by `PrivateEquityTenderPolicy` outside the
    liquidity-policy path. A bucket absent from `sell_order` means "don't auto-sell from this
    bucket"; an empty `sell_order` yields an empty chain (hard-demand failures still fire).
    """

    asset_ids: list[str] = []
    for bucket in funding_policy.sell_order:
        if bucket == "stocks":
            asset_ids.extend(
                lot.asset_id
                for lot in initial_lots
                if not lot.asset_id.startswith("crypto:") and not lot.asset_id.startswith("private_equity:")
            )
        elif bucket == "crypto":
            asset_ids.extend(lot.asset_id for lot in initial_lots if lot.asset_id.startswith("crypto:"))
        else:
            raise ValueError(f"unsupported sell_order bucket: {bucket!r}")
    return list(dict.fromkeys(asset_ids))
