"""Compile-side plan: SlotPlan, CompiledSimulation, compile_simulation. Pairs with
`codec/plan.py` (DenseSimulationResult, decode_run) at the engine boundary.

`compile_simulation` is the orchestrator that interns strings, builds the shared
index maps, calls every per-domain `compile_*` helper, and assembles the
`CompiledSimulation` plan the engine consumes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from augur.model.series import home_value_series_id
from augur.sim.compiler.assets import SaleCompileOutput, compile_sales
from augur.sim.compiler.deductions import (
    MIDCompileOutput,
    SaltCompileOutput,
    compile_federal_salt_deductions,
    compile_mortgage_interest_deductions,
)
from augur.sim.compiler.helpers import NO_CODE, StringTable
from augur.sim.compiler.lifecycle import LifecycleEventCompileOutput, compile_lifecycle_events
from augur.sim.compiler.liquidity import LiquidityPolicyCompileOutput, compile_liquidity_policies
from augur.sim.compiler.obligations import ObligationCompileOutput, compile_obligation_slots
from augur.sim.compiler.private_equity import (
    PEIssuerCompileOutput,
    PEPolicyCompileOutput,
    compile_private_equity_tenders,
)
from augur.sim.compiler.properties import (
    LiabilityCompileOutput,
    PropertyCompileOutput,
    compile_properties_and_liabilities,
)
from augur.sim.compiler.series import collect_series_ids, external_event_values_cube, external_values_cube
from augur.sim.compiler.tax import (
    TaxCompileOutput,
    TaxLiabilityCompileOutput,
    compile_capital_gain_agents,
    compile_tax,
    compile_tax_liability_slots,
)
from augur.sim.compiler.transfers import TransferCompileOutput, compile_transfer_slots
from augur.sim.external_series import ExternalSeriesContext
from augur.sim.jurisdictions import Jurisdiction
from augur.sim.locations import Location
from augur.sim.scenario import PropertySaleEvent, Scenario


@dataclass(frozen=True)
class SlotPlan:
    """Dense shape contract for one compiled simulation.

    Dimensions use the notation from `augur/plans/dense_shape_discipline.md`.
    Counts that can be absent but are still iterated by engine phases use their
    allocated sentinel axis size, usually `max(1, actual_count)`.
    """

    event_months: int
    snapshot_months: int
    rollout_count: int
    cash_count: int
    lot_count: int
    tax_profile_count: int
    capital_gain_agent_count: int
    tax_link_count: int
    tax_liability_count: int
    property_count: int
    liability_count: int
    max_transfer_slots: int
    max_obligation_slots: int
    scheduled_sale_count: int
    liquidity_policy_count: int
    max_liquidity_policy_assets: int
    pe_issuer_count: int
    max_tax_settlement_slots: int


@dataclass(frozen=True)
class CompiledSimulation:
    horizon_months: int
    rollout_count: int
    slot_plan: SlotPlan
    strings: tuple[str, ...]
    series_ids: tuple[str, ...]
    external_values: NDArray[np.float64]
    cash_agent_codes: NDArray[np.int64]
    cash_account_codes: NDArray[np.int64]
    cash_initial_balance: NDArray[np.float64]
    lot_id_codes: NDArray[np.int64]
    lot_agent_codes: NDArray[np.int64]
    lot_account_codes: NDArray[np.int64]
    lot_asset_codes: NDArray[np.int64]
    # Per-lot index into `external_values` for the lot's pricing series. NO_CODE for lots
    # whose asset_id has no registered sampled level (defensive: shouldn't normally happen
    # for holdings, but the sentinel keeps lookups safe).
    lot_asset_series_index: NDArray[np.int64]
    lot_purchase_month: NDArray[np.int64]
    lot_cost_basis_per_unit: NDArray[np.float64]
    lot_initial_quantity: NDArray[np.float64]
    tax: TaxCompileOutput
    capital_gain_agent_codes: NDArray[np.int64]
    tax_profile_capital_gain_index: NDArray[np.int64]
    mid: MIDCompileOutput
    salt: SaltCompileOutput
    tax_liabilities: TaxLiabilityCompileOutput
    transfers: TransferCompileOutput
    properties: PropertyCompileOutput
    # Per-property rented_fraction (0..1). 0 = pure owner-occupied/off; 1 = pure investment.
    # Drives MID/SALT/Schedule E splits + monthly depreciation accrual.
    property_rented_fraction: NDArray[np.float64]
    # Per-property depreciable building basis = purchase_price × (1 - land_value_fraction) +
    # buyer_closing_cost. Land is non-depreciable; the 27.5-year SL clock applies only to the
    # building portion. Capitalized closing costs add to the depreciable basis.
    property_building_basis: NDArray[np.float64]
    # Profile index of each property's owner (buyer_agent_id → tax profile). NO_CODE if the
    # owner has no tax profile. Used to route Schedule E depreciation deductions.
    property_owner_profile_index: NDArray[np.int64]
    # Series index of each property's home_value series, used at sale time to compute market
    # value. NO_CODE only for properties without sale events whose series was not supplied.
    property_home_value_series_index: NDArray[np.int64]
    lifecycle_events: LifecycleEventCompileOutput
    liabilities: LiabilityCompileOutput
    # Profile index of each liability's owner. NO_CODE if the owner has no tax profile.
    liability_owner_profile_index: NDArray[np.int64]
    sales: SaleCompileOutput
    obligations: ObligationCompileOutput
    # External event-series tables, parallel to `series_ids` / `external_values` but for
    # boolean event paths (private-equity tender opportunities, future regime-change events).
    external_event_ids: tuple[str, ...]
    external_event_values: NDArray[np.bool_]
    # Per-PE-issuer arrays. Issuers are the distinct `private_equity:<issuer>` asset_ids
    # appearing in `initial_lots`. For each issuer:
    #   - the event-series index identifying its tender-opportunity stream (NO_CODE if no
    #     event series is registered for it — issuer never tenders within the sim horizon)
    #   - the level-series index for its sampled mark (used both for portfolio valuation and
    #     for sale-proceeds = units * mark at tender)
    #   - the policy index (into the per-policy arrays below) whose LNW-floor governs sales
    #     on tenders for this issuer (NO_CODE if no PrivateEquityTenderPolicy applies)
    pe_issuers: PEIssuerCompileOutput
    pe_policies: PEPolicyCompileOutput
    liquidity_policies: LiquidityPolicyCompileOutput


def compile_simulation(
    scenario: Scenario,
    *,
    rollout_count: int,
    external_series: ExternalSeriesContext,
    jurisdictions: dict[str, Jurisdiction],
    locations: dict[str, Location],
) -> CompiledSimulation:
    strings = StringTable()
    horizon = int(scenario.horizon_months)

    account_slot_by_key: dict[tuple[str, str], int] = {}
    cash_agent_codes: list[int] = []
    cash_account_codes: list[int] = []
    cash_initial_balance: list[float] = []
    for entry in scenario.initial_cash:
        key = (entry.agent_id, entry.account_id)
        if key in account_slot_by_key:
            raise ValueError(f"duplicate initial cash account: {entry.agent_id}/{entry.account_id}")
        account_slot_by_key[key] = len(cash_initial_balance)
        cash_agent_codes.append(strings.require(entry.agent_id))
        cash_account_codes.append(strings.require(entry.account_id))
        cash_initial_balance.append(float(entry.balance_usd))

    for agent in scenario.agents:
        strings.require(agent.agent_id)

    series_ids = collect_series_ids(scenario, external_series)
    series_index_by_id = {series_id: idx for idx, series_id in enumerate(series_ids)}
    _reject_missing_property_sale_home_values(scenario, external_series)
    external_values = external_values_cube(
        external_series, series_index_by_id=series_index_by_id, rollout_count=rollout_count, horizon_months=horizon
    )
    external_event_ids = tuple(
        str(event_id)
        for event_id in external_series.series_events.select("event_id").unique().get_column("event_id").to_list()
    )
    external_event_index_by_id = {event_id: idx for idx, event_id in enumerate(external_event_ids)}
    external_event_values = external_event_values_cube(
        external_series,
        event_index_by_id=external_event_index_by_id,
        rollout_count=rollout_count,
        horizon_months=horizon,
    )

    profile_index_by_agent = {profile.agent_id: idx for idx, profile in enumerate(scenario.tax_profiles)}
    tax = compile_tax(scenario, strings, account_slot_by_key, jurisdictions)
    (capital_gain_agent_codes, tax_profile_capital_gain_index) = compile_capital_gain_agents(scenario, strings)

    tax_liabilities = compile_tax_liability_slots(horizon, tax)

    transfers = compile_transfer_slots(
        scenario, strings, account_slot_by_key, profile_index_by_agent, series_index_by_id
    )

    properties, liabilities = compile_properties_and_liabilities(scenario, strings, account_slot_by_key, locations)

    # Per-liability rented_fraction: each liability is tied to one property via
    # liabilities.property_slot; the property's rented_fraction (0..1) drives both the MID
    # scale-down (MID applies only to owner-use share = 1 - rented_fraction) and the
    # Schedule E rental-interest deduction (= rented_fraction × interest_ytd).
    property_count = len(scenario.scheduled_property_purchases)
    property_slot_by_id: dict[str, int] = {
        p.property_id: i for i, p in enumerate(scenario.scheduled_property_purchases)
    }
    property_rented_fraction = np.array(
        [float(p.rented_fraction) for p in scenario.scheduled_property_purchases], dtype=np.float64
    )
    # Building basis = (purchase price × (1 - land_fraction)) + capitalized closing costs.
    property_building_basis = np.array(
        [
            float(p.purchase_price_usd) * (1.0 - float(p.land_value_fraction)) + float(p.buyer_closing_cost_usd)
            for p in scenario.scheduled_property_purchases
        ],
        dtype=np.float64,
    )
    property_owner_profile_index = np.array(
        [profile_index_by_agent.get(p.buyer_agent_id, NO_CODE) for p in scenario.scheduled_property_purchases],
        dtype=np.int64,
    )
    property_home_value_series_index = np.array(
        [
            series_index_by_id.get(home_value_series_id(p.location_id), NO_CODE)
            for p in scenario.scheduled_property_purchases
        ],
        dtype=np.int64,
    )
    # Allocate min-shape arrays for the no-property scenario so downstream callers can index
    # `property_building_basis[max(1, property_count)]` without special-casing.
    if property_count == 0:
        property_rented_fraction = np.zeros(1, dtype=np.float64)
        property_building_basis = np.zeros(1, dtype=np.float64)
        property_owner_profile_index = np.full(1, NO_CODE, dtype=np.int64)
        property_home_value_series_index = np.full(1, NO_CODE, dtype=np.int64)

    lifecycle_events = compile_lifecycle_events(scenario, property_slot_by_id)

    liability_owner_profile_index = np.array(
        [
            profile_index_by_agent.get(strings.values[int(liabilities.agent[lia])], NO_CODE)
            for lia in range(liabilities.codes.shape[0])
        ],
        dtype=np.int64,
    )

    mid = compile_mortgage_interest_deductions(scenario, strings, tax=tax, liabilities=liabilities)
    salt = compile_federal_salt_deductions(scenario, strings, tax=tax)

    sales = compile_sales(scenario, strings, account_slot_by_key, series_index_by_id)

    obligations = compile_obligation_slots(
        scenario, strings, account_slot_by_key, series_index_by_id, properties, property_slot_by_id, liabilities, tax
    )

    liquidity_policies = compile_liquidity_policies(scenario, strings, account_slot_by_key, series_index_by_id)

    lot_id_codes: list[int] = []
    lot_agent_codes: list[int] = []
    lot_account_codes: list[int] = []
    lot_asset_codes: list[int] = []
    lot_purchase_month: list[int] = []
    lot_cost_basis_per_unit: list[float] = []
    lot_initial_quantity: list[float] = []
    for lot in scenario.initial_lots:
        lot_id_codes.append(strings.require(lot.lot_id))
        lot_agent_codes.append(strings.require(lot.agent_id))
        lot_account_codes.append(strings.require(lot.account_id))
        lot_asset_codes.append(strings.require(lot.asset_id))
        lot_purchase_month.append(int(lot.purchase_month_index))
        lot_cost_basis_per_unit.append(float(lot.cost_basis_per_unit_usd))
        lot_initial_quantity.append(float(lot.quantity))

    lot_agent_codes_arr = np.asarray(lot_agent_codes, dtype=np.int64)
    lot_asset_codes_arr = np.asarray(lot_asset_codes, dtype=np.int64)
    lot_asset_series_index = np.asarray(
        [series_index_by_id.get(lot.asset_id, NO_CODE) for lot in scenario.initial_lots], dtype=np.int64
    )
    cash_agent_codes_arr = np.asarray([strings.require(b.agent_id) for b in scenario.initial_cash], dtype=np.int64)
    pe_issuers, pe_policies = compile_private_equity_tenders(
        scenario,
        strings,
        series_index_by_id=series_index_by_id,
        event_index_by_id=external_event_index_by_id,
        lot_agent_codes=lot_agent_codes_arr,
        lot_asset_codes=lot_asset_codes_arr,
        cash_agent_codes=cash_agent_codes_arr,
    )

    slot_plan = SlotPlan(
        event_months=horizon,
        snapshot_months=horizon + 1,
        rollout_count=rollout_count,
        cash_count=len(cash_initial_balance),
        lot_count=len(lot_id_codes),
        tax_profile_count=tax.profile_agent.shape[0],
        capital_gain_agent_count=capital_gain_agent_codes.shape[0],
        tax_link_count=max(1, tax.link_profile.shape[0]),
        tax_liability_count=tax_liabilities.profile_index.shape[0],
        property_count=properties.month.shape[0],
        liability_count=liabilities.codes.shape[0],
        max_transfer_slots=transfers.cause.shape[1],
        max_obligation_slots=obligations.cause.shape[1],
        scheduled_sale_count=sales.month.shape[0],
        liquidity_policy_count=liquidity_policies.assets.shape[0],
        max_liquidity_policy_assets=liquidity_policies.assets.shape[1],
        pe_issuer_count=pe_issuers.codes.shape[0],
        max_tax_settlement_slots=max(1, len(scenario.tax_profiles)),
    )

    return CompiledSimulation(
        horizon_months=horizon,
        rollout_count=rollout_count,
        slot_plan=slot_plan,
        strings=tuple(strings.values),
        series_ids=series_ids,
        external_values=external_values,
        cash_agent_codes=np.asarray(cash_agent_codes, dtype=np.int64),
        cash_account_codes=np.asarray(cash_account_codes, dtype=np.int64),
        cash_initial_balance=np.asarray(cash_initial_balance, dtype=np.float64),
        lot_id_codes=np.asarray(lot_id_codes, dtype=np.int64),
        lot_agent_codes=np.asarray(lot_agent_codes, dtype=np.int64),
        lot_account_codes=np.asarray(lot_account_codes, dtype=np.int64),
        lot_asset_codes=np.asarray(lot_asset_codes, dtype=np.int64),
        lot_asset_series_index=lot_asset_series_index,
        lot_purchase_month=np.asarray(lot_purchase_month, dtype=np.int64),
        lot_cost_basis_per_unit=np.asarray(lot_cost_basis_per_unit, dtype=np.float64),
        lot_initial_quantity=np.asarray(lot_initial_quantity, dtype=np.float64),
        tax=tax,
        capital_gain_agent_codes=capital_gain_agent_codes,
        tax_profile_capital_gain_index=tax_profile_capital_gain_index,
        mid=mid,
        salt=salt,
        tax_liabilities=tax_liabilities,
        transfers=transfers,
        properties=properties,
        liabilities=liabilities,
        liability_owner_profile_index=liability_owner_profile_index,
        property_rented_fraction=property_rented_fraction,
        property_building_basis=property_building_basis,
        property_owner_profile_index=property_owner_profile_index,
        property_home_value_series_index=property_home_value_series_index,
        lifecycle_events=lifecycle_events,
        sales=sales,
        obligations=obligations,
        external_event_ids=external_event_ids,
        external_event_values=external_event_values,
        pe_issuers=pe_issuers,
        pe_policies=pe_policies,
        liquidity_policies=liquidity_policies,
    )


def _reject_missing_property_sale_home_values(scenario: Scenario, external_series: ExternalSeriesContext) -> None:
    """Property sales need an explicit external home-value path for their location."""

    if not scenario.property_lifecycle_events:
        return
    property_by_id = {property_.property_id: property_ for property_ in scenario.scheduled_property_purchases}
    available_series_ids = {
        str(series_id)
        for series_id in external_series.series_values.select("series_id").unique().get_column("series_id").to_list()
    }
    for event in scenario.property_lifecycle_events:
        if not isinstance(event, PropertySaleEvent):
            continue
        property_ = property_by_id[event.property_id]
        required_series_id = home_value_series_id(property_.location_id)
        if required_series_id in available_series_ids:
            continue
        msg = (
            f"property sale for property_id {event.property_id!r} at month {event.month} requires external "
            f"home-value series {required_series_id!r}"
        )
        raise KeyError(msg)
