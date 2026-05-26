"""Python boundary for the dense-array simulator.

This module owns all object-heavy work: string interning, Pydantic scenario
inspection, Polars external-series reshaping, and static event-slot planning.
The engine consumes only numeric arrays and writes numeric outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from augur.model.series import PRIVATE_EQUITY_SERIES_PREFIX, home_value_series_id, private_equity_sale_event_id
from augur.sim.compiler.assets import SaleCompileOutput, compile_sales
from augur.sim.compiler.helpers import (
    AMOUNT_FIXED,
    NO_CODE,
    ORDINARY_DEDUCTION_CATEGORY,
    StringTable,
    amount_arrays,
    empty_month_matrix,
    slot,
)
from augur.sim.compiler.lifecycle import LifecycleEventCompileOutput, compile_lifecycle_events
from augur.sim.compiler.liquidity import LiquidityPolicyCompileOutput, compile_liquidity_policies
from augur.sim.compiler.properties import (
    LiabilityCompileOutput,
    PropertyCompileOutput,
    compile_properties_and_liabilities,
)
from augur.sim.compiler.transfers import TransferCompileOutput, compile_transfer_slots
from augur.sim.external_series import ExternalSeriesContext
from augur.sim.jurisdictions import Jurisdiction
from augur.sim.locations import Location
from augur.sim.scenario import (
    FilingStatus,
    MortgageInterestDeductionPolicy,
    RecurringObligation,
    Scenario,
    ScheduledObligation,
    SeriesIndexedAmount,
)


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
    # value. NO_CODE if the series wasn't configured in the scenario.
    property_home_value_series_index: NDArray[np.int64]
    # PropertyLifecycleEvent rows compiled into per-month sparse storage. Sorted by month so
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

    series_ids = _collect_series_ids(scenario, external_series)
    series_index_by_id = {series_id: idx for idx, series_id in enumerate(series_ids)}
    external_values = _external_values_cube(
        external_series, series_index_by_id=series_index_by_id, rollout_count=rollout_count, horizon_months=horizon
    )
    external_event_ids = tuple(
        str(event_id)
        for event_id in external_series.series_events.select("event_id").unique().get_column("event_id").to_list()
    )
    external_event_index_by_id = {event_id: idx for idx, event_id in enumerate(external_event_ids)}
    external_event_values = _external_event_values_cube(
        external_series,
        event_index_by_id=external_event_index_by_id,
        rollout_count=rollout_count,
        horizon_months=horizon,
    )

    profile_index_by_agent = {profile.agent_id: idx for idx, profile in enumerate(scenario.tax_profiles)}
    tax = _compile_tax(scenario, strings, account_slot_by_key, jurisdictions)
    (capital_gain_agent_codes, tax_profile_capital_gain_index) = _compile_capital_gain_agents(scenario, strings)

    tax_liabilities = _compile_tax_liability_slots(horizon, tax)

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
    # Each property's home_value series — used at sale time to compute market value.

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

    mid = _compile_mortgage_interest_deductions(scenario, strings, tax=tax, liabilities=liabilities)
    salt = _compile_federal_salt_deductions(scenario, strings, tax=tax)

    sales = compile_sales(scenario, strings, account_slot_by_key, series_index_by_id)

    obligations = _compile_obligation_slots(
        scenario, strings, account_slot_by_key, series_index_by_id, properties, property_slot_by_id, liabilities, tax
    )

    liquidity_policies = compile_liquidity_policies(scenario, strings, account_slot_by_key, series_index_by_id)

    lot_id_codes = []
    lot_agent_codes = []
    lot_account_codes = []
    lot_asset_codes = []
    lot_purchase_month = []
    lot_cost_basis_per_unit = []
    lot_initial_quantity = []
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
    pe_issuers, pe_policies = _compile_private_equity_tenders(
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


def _collect_series_ids(scenario: Scenario, external_series: ExternalSeriesContext) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(series_id: str) -> None:
        if series_id not in seen:
            seen.add(series_id)
            ids.append(series_id)

    for value in external_series.series_values.select("series_id").unique().get_column("series_id").to_list():
        add(str(value))
    for transfer in [*scenario.scheduled_transfers, *scenario.recurring_transfers]:
        _add_amount_series_id(transfer.amount_usd, add)
    for obligation in [*scenario.scheduled_obligations, *scenario.recurring_obligations]:
        _add_amount_series_id(obligation.amount_due_usd, add)
    for sale in scenario.scheduled_asset_sales:
        if sale.price_per_unit_usd is None:
            add(sale.asset_id)
    for policy in scenario.liquidity_policies:
        for asset_id in policy.asset_preference_chain:
            add(asset_id)
    return tuple(ids)


def _add_amount_series_id(amount: Any, add: Any) -> None:
    if isinstance(amount, SeriesIndexedAmount):
        add(amount.series_id)


def _external_values_cube(
    external_series: ExternalSeriesContext,
    *,
    series_index_by_id: dict[str, int],
    rollout_count: int,
    horizon_months: int,
) -> np.ndarray:
    values = np.full((len(series_index_by_id), rollout_count, horizon_months + 1), np.nan, dtype=np.float64)
    if external_series.series_values.is_empty():
        return values
    for row in external_series.series_values.iter_rows(named=True):
        series_index = series_index_by_id.get(str(row["series_id"]))
        if series_index is None:
            continue
        rollout_index = int(row["rollout_index"])
        month_index = int(row["month_index"])
        if 0 <= rollout_index < rollout_count and 0 <= month_index <= horizon_months:
            values[series_index, rollout_index, month_index] = float(row["value"])
    return values


def _external_event_values_cube(
    external_series: ExternalSeriesContext,
    *,
    event_index_by_id: dict[str, int],
    rollout_count: int,
    horizon_months: int,
) -> np.ndarray:
    """Dense (event_count, rollout, month+1) boolean cube of sampled exogenous events."""

    values = np.zeros((max(1, len(event_index_by_id)), rollout_count, horizon_months + 1), dtype=np.bool_)
    if external_series.series_events.is_empty():
        return values
    for row in external_series.series_events.iter_rows(named=True):
        event_index = event_index_by_id.get(str(row["event_id"]))
        if event_index is None:
            continue
        rollout_index = int(row["rollout_index"])
        month_index = int(row["month_index"])
        if 0 <= rollout_index < rollout_count and 0 <= month_index <= horizon_months:
            values[event_index, rollout_index, month_index] = bool(row["active"])
    return values


@dataclass(frozen=True)
class PEIssuerCompileOutput:
    """Per-issuer arrays (one row per distinct `private_equity:<issuer>` asset). An issuer
    is `policy_index = NO_CODE` if no PrivateEquityTenderPolicy applies (issuer never
    tenders within horizon); the engine skips it. `lot_mask[i, l]` flags which lots
    belong to issuer `i`."""

    codes: NDArray[np.int64]
    event_series: NDArray[np.int64]
    level_series: NDArray[np.int64]
    policy_index: NDArray[np.int64]
    lot_mask: NDArray[np.bool_]


@dataclass(frozen=True)
class PEPolicyCompileOutput:
    """Per-policy arrays (one row per PrivateEquityTenderPolicy). `floor_*` is the
    indexed-amount schedule for the liquid-net-worth floor (CPI-indexable). `owner_cash_mask`
    + `owner_non_pe_lot_mask` are (policy × slot) masks the engine uses to compute LNW
    from the owner's non-PE liquid assets."""

    owner_agent: NDArray[np.int64]
    proceeds_cash_slot: NDArray[np.int64]
    floor_kind: NDArray[np.int64]
    floor_fixed: NDArray[np.float64]
    floor_base: NDArray[np.float64]
    floor_series: NDArray[np.int64]
    floor_base_month: NDArray[np.int64]
    floor_period: NDArray[np.int64]
    owner_cash_mask: NDArray[np.bool_]
    owner_non_pe_lot_mask: NDArray[np.bool_]


def _compile_private_equity_tenders(
    scenario: Scenario,
    strings: StringTable,
    *,
    series_index_by_id: dict[str, int],
    event_index_by_id: dict[str, int],
    lot_agent_codes: np.ndarray,
    lot_asset_codes: np.ndarray,
    cash_agent_codes: np.ndarray,
) -> tuple[PEIssuerCompileOutput, PEPolicyCompileOutput]:
    """Compile per-(issuer, policy) arrays driving the PE tender-sale path.

    Issuer set is derived from `initial_lots` (any `private_equity:<issuer>` asset_id);
    the policy set is `scenario.private_equity_tender_policies` (per-owner). Each issuer
    maps to a policy by matching the lot's owner_agent_id to the policy's owner. The
    engine uses these arrays to fire LNW-floor-driven sales when a tender event activates.
    """

    issuer_to_lots: dict[str, list[int]] = {}
    for lot_index, lot in enumerate(scenario.initial_lots):
        if not lot.asset_id.startswith(PRIVATE_EQUITY_SERIES_PREFIX):
            continue
        issuer = lot.asset_id[len(PRIVATE_EQUITY_SERIES_PREFIX) :]
        issuer_to_lots.setdefault(issuer, []).append(lot_index)
    issuer_ids = tuple(sorted(issuer_to_lots))

    policies = scenario.private_equity_tender_policies
    policy_count = max(1, len(policies))
    lot_count = lot_agent_codes.shape[0]
    cash_count = cash_agent_codes.shape[0]
    issuer_count = max(1, len(issuer_ids))

    pe_issuer_codes = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_event_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_level_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_policy_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_lot_mask = np.zeros((issuer_count, max(1, lot_count)), dtype=np.bool_)

    pe_policy_owner_agent_codes = np.full(policy_count, NO_CODE, dtype=np.int64)
    pe_policy_proceeds_cash_slot = np.full(policy_count, NO_CODE, dtype=np.int64)
    pe_policy_floor_kind = np.full(policy_count, AMOUNT_FIXED, dtype=np.int64)
    pe_policy_floor_fixed = np.zeros(policy_count, dtype=np.float64)
    pe_policy_floor_base = np.zeros(policy_count, dtype=np.float64)
    pe_policy_floor_series_index = np.full(policy_count, NO_CODE, dtype=np.int64)
    pe_policy_floor_base_month = np.zeros(policy_count, dtype=np.int64)
    pe_policy_floor_adjustment_period = np.ones(policy_count, dtype=np.int64)
    pe_policy_owner_cash_mask = np.zeros((policy_count, max(1, cash_count)), dtype=np.bool_)
    pe_policy_owner_non_pe_lot_mask = np.zeros((policy_count, max(1, lot_count)), dtype=np.bool_)

    issuers = PEIssuerCompileOutput(
        codes=pe_issuer_codes,
        event_series=pe_issuer_event_series_index,
        level_series=pe_issuer_level_series_index,
        policy_index=pe_issuer_policy_index,
        lot_mask=pe_issuer_lot_mask,
    )
    pe_policies = PEPolicyCompileOutput(
        owner_agent=pe_policy_owner_agent_codes,
        proceeds_cash_slot=pe_policy_proceeds_cash_slot,
        floor_kind=pe_policy_floor_kind,
        floor_fixed=pe_policy_floor_fixed,
        floor_base=pe_policy_floor_base,
        floor_series=pe_policy_floor_series_index,
        floor_base_month=pe_policy_floor_base_month,
        floor_period=pe_policy_floor_adjustment_period,
        owner_cash_mask=pe_policy_owner_cash_mask,
        owner_non_pe_lot_mask=pe_policy_owner_non_pe_lot_mask,
    )
    if not issuer_ids and not policies:
        return issuers, pe_policies

    # Per-policy arrays.
    for policy_idx, policy in enumerate(policies):
        owner_code = strings.require(policy.owner_agent_id)
        pe_policy_owner_agent_codes[policy_idx] = owner_code
        # Proceeds cash slot: the (owner_agent, proceeds_account_id) pair.
        proceeds_account_code = strings.require(policy.proceeds_account_id)
        # Account-slot lookup: scan cash_agent_codes for the agent + account match. Cash slots are
        # indexed by (agent, account) pair; we walk the cash table to find the right slot.
        # The compiled `cash_account_codes` array would also be helpful, but we don't have it
        # passed in — instead we use the strings agent code + a downstream lookup.
        # For now: we rely on the engine to look up the proceeds slot by matching agent code +
        # a parallel cash_account_codes (passed via plan.cash_account_codes elsewhere).
        # We store NO_CODE for the slot here; engine resolves at run time. Actually let's just
        # precompute it: take the first cash slot owned by the owner agent — convention is each
        # actor has a single primary "checking" slot.
        # TODO: when an actor has multiple accounts, we should match the policy.proceeds_account_id
        # explicitly. For v1 single-actor scenarios this is the same as the first matching slot.
        del proceeds_account_code  # unused for now; rely on owner-cash mask for proceeds
        owner_cash_slots = np.flatnonzero(cash_agent_codes == owner_code)
        if owner_cash_slots.size > 0:
            pe_policy_proceeds_cash_slot[policy_idx] = int(owner_cash_slots[0])
        kind, fixed, base, series, base_month, period = amount_arrays(policy.liquid_net_worth_floor, series_index_by_id)
        pe_policy_floor_kind[policy_idx] = kind
        pe_policy_floor_fixed[policy_idx] = fixed
        pe_policy_floor_base[policy_idx] = base
        pe_policy_floor_series_index[policy_idx] = series
        pe_policy_floor_base_month[policy_idx] = base_month
        pe_policy_floor_adjustment_period[policy_idx] = period
        if cash_count > 0:
            pe_policy_owner_cash_mask[policy_idx, :cash_count] = cash_agent_codes == owner_code
        if lot_count > 0:
            owner_lots = lot_agent_codes == owner_code
            pe_codes = {strings.require(f"{PRIVATE_EQUITY_SERIES_PREFIX}{issuer}") for issuer in issuer_to_lots}
            non_pe_lot = ~np.isin(lot_asset_codes, list(pe_codes)) if pe_codes else np.ones(lot_count, dtype=np.bool_)
            pe_policy_owner_non_pe_lot_mask[policy_idx, :lot_count] = owner_lots & non_pe_lot

    # Per-issuer arrays.
    policy_index_by_owner = {int(pe_policy_owner_agent_codes[idx]): idx for idx in range(len(policies))}
    for issuer_idx, issuer in enumerate(issuer_ids):
        pe_issuer_codes[issuer_idx] = strings.require(issuer)
        level_series_id = f"{PRIVATE_EQUITY_SERIES_PREFIX}{issuer}"
        event_series_id = private_equity_sale_event_id(issuer)
        if level_series_id in series_index_by_id:
            pe_issuer_level_series_index[issuer_idx] = series_index_by_id[level_series_id]
        if event_series_id in event_index_by_id:
            pe_issuer_event_series_index[issuer_idx] = event_index_by_id[event_series_id]
        # Lot indices owned by this issuer.
        lots = issuer_to_lots[issuer]
        for lot_index in lots:
            pe_issuer_lot_mask[issuer_idx, lot_index] = True
        # Resolve policy by owner-agent match. All lots for a given issuer in v1 are owned by
        # the same agent (single-actor scenarios); use the first lot's owner.
        owner_code = int(lot_agent_codes[lots[0]])
        if owner_code in policy_index_by_owner:
            pe_issuer_policy_index[issuer_idx] = policy_index_by_owner[owner_code]

    return issuers, pe_policies


SECTION_1250_FEDERAL_CAP_RATE = 0.25
SECTION_1250_FEDERAL_JURISDICTION_ID = "federal_us"

# §121 primary-residence exclusion cap (post-recapture LTCG that can be excluded from federal
# capital gains on a sale of a qualifying residence). Single filer: $250k. The lookup table
# is the single source of truth; new `FilingStatus` variants must add an entry here or
# `_section_121_exclusion_for` raises NotImplementedError — which keeps "I forgot this
# branch" from silently falling through to a wrong tax number.
_SECTION_121_EXCLUSION_USD_BY_FILING_STATUS: dict[FilingStatus, float] = {FilingStatus.SINGLE: 250_000.0}


def _section_121_exclusion_for(filing_status: FilingStatus) -> float:
    if filing_status not in _SECTION_121_EXCLUSION_USD_BY_FILING_STATUS:
        raise NotImplementedError(
            f"§121 exclusion cap is not implemented for filing_status={filing_status!r}; "
            f"add a {filing_status} entry to _SECTION_121_EXCLUSION_USD_BY_FILING_STATUS "
            f"and audit every other place that branches on filing status (jurisdiction "
            f"bracket lookups, standard-deduction lookups, MID, SALT cap, NIIT thresholds)."
        )
    return _SECTION_121_EXCLUSION_USD_BY_FILING_STATUS[filing_status]


@dataclass(frozen=True)
class TaxCompileOutput:
    """Tax-profile + tax-link arrays produced by `_compile_tax`. Each row of
    `profile_*` is one TaxProfile; each row of `link_*` is one (profile, jurisdiction)
    pair. `*_upper/*_rate/*_count` are rectangular bracket tables — `count[link]` is
    the active prefix length for that link's brackets (zero-padded beyond).

    Notable fields:

    - `profile_section_121_exclusion`: §121 primary-residence exclusion cap, USD.
      Looked up by filing status at compile time
      (`_SECTION_121_EXCLUSION_USD_BY_FILING_STATUS`); only `single` is wired today
      ($250k). Engine reads on every property sale to compute the exclusion ceiling.
    - `link_section_1250_rate`: §1250 unrecaptured-depreciation rate cap. Positive ⇒
      federal-style flat rate (0.25 for `federal_us`); 0.0 ⇒ no separate cap, recapture
      is taxed as ordinary inside the standard bracket walk (state-style, e.g. CA)."""

    profile_agent: NDArray[np.int64]
    profile_payment_slot: NDArray[np.int64]
    profile_payment_account: NDArray[np.int64]
    profile_authority_agent: NDArray[np.int64]
    profile_authority_account: NDArray[np.int64]
    profile_prior_year_tax: NDArray[np.float64]
    profile_section_121_exclusion: NDArray[np.float64]
    link_profile: NDArray[np.int64]
    link_jurisdiction: NDArray[np.int64]
    link_standard_deduction: NDArray[np.float64]
    link_has_ltcg: NDArray[np.int64]
    link_section_1250_rate: NDArray[np.float64]
    link_ordinary_upper: NDArray[np.float64]
    link_ordinary_rate: NDArray[np.float64]
    link_ordinary_count: NDArray[np.int64]
    link_ltcg_upper: NDArray[np.float64]
    link_ltcg_rate: NDArray[np.float64]
    link_ltcg_count: NDArray[np.int64]


def _compile_tax(
    scenario: Scenario,
    strings: StringTable,
    account_slot_by_key: dict[tuple[str, str], int],
    jurisdictions: dict[str, Jurisdiction],
) -> TaxCompileOutput:
    profile_agent = []
    payment_slot = []
    payment_account = []
    authority_agent = []
    authority_account = []
    prior_year_tax = []
    link_profile = []
    link_jurisdiction = []
    standard_deduction = []
    has_ltcg = []
    section_1250_rate: list[float] = []
    ordinary_brackets: list[list[tuple[float, float]]] = []
    ltcg_brackets: list[list[tuple[float, float]]] = []
    section_121_exclusion: list[float] = []

    max_ord = 1
    max_ltcg = 1
    for profile_index, profile in enumerate(scenario.tax_profiles):
        profile_agent.append(strings.require(profile.agent_id))
        payment_slot.append(slot(account_slot_by_key, profile.agent_id, profile.payment_account_id))
        payment_account.append(strings.require(profile.payment_account_id))
        authority_agent.append(strings.require(profile.tax_authority_agent_id))
        authority_account.append(strings.require(profile.tax_authority_account_id))
        prior_year_tax.append(float(profile.prior_year_tax_usd))
        section_121_exclusion.append(_section_121_exclusion_for(profile.filing_status))
        for jurisdiction_id in profile.jurisdiction_ids:
            jurisdiction = jurisdictions[jurisdiction_id]
            ordinary = [
                (float(bracket.upper_usd), float(bracket.rate))
                for bracket in jurisdiction.ordinary_income_brackets[profile.filing_status]
            ]
            ltcg = (
                [
                    (float(bracket.upper_usd), float(bracket.rate))
                    for bracket in jurisdiction.ltcg_brackets[profile.filing_status]
                ]
                if jurisdiction.ltcg_brackets is not None
                else []
            )
            max_ord = max(max_ord, len(ordinary))
            max_ltcg = max(max_ltcg, len(ltcg))
            link_profile.append(profile_index)
            link_jurisdiction.append(strings.require(jurisdiction_id))
            standard_deduction.append(float(jurisdiction.standard_deduction[profile.filing_status]))
            has_ltcg.append(1 if jurisdiction.ltcg_brackets is not None else 0)
            # Federal-us gets the §1250 25% flat rate cap; all other jurisdictions tax
            # unrecaptured-depreciation as ordinary income (CA, etc.).
            section_1250_rate.append(
                SECTION_1250_FEDERAL_CAP_RATE if jurisdiction_id == SECTION_1250_FEDERAL_JURISDICTION_ID else 0.0
            )
            ordinary_brackets.append(ordinary)
            ltcg_brackets.append(ltcg)

    link_count = len(link_profile)
    ordinary_upper = np.zeros((max(1, link_count), max_ord), dtype=np.float64)
    ordinary_rate = np.zeros((max(1, link_count), max_ord), dtype=np.float64)
    ordinary_count = np.zeros(max(1, link_count), dtype=np.int64)
    ltcg_upper = np.zeros((max(1, link_count), max_ltcg), dtype=np.float64)
    ltcg_rate = np.zeros((max(1, link_count), max_ltcg), dtype=np.float64)
    ltcg_count = np.zeros(max(1, link_count), dtype=np.int64)
    for idx, ordinary in enumerate(ordinary_brackets):
        ordinary_count[idx] = len(ordinary)
        for bracket_idx, (upper, rate) in enumerate(ordinary):
            ordinary_upper[idx, bracket_idx] = upper
            ordinary_rate[idx, bracket_idx] = rate
    for idx, ltcg in enumerate(ltcg_brackets):
        ltcg_count[idx] = len(ltcg)
        for bracket_idx, (upper, rate) in enumerate(ltcg):
            ltcg_upper[idx, bracket_idx] = upper
            ltcg_rate[idx, bracket_idx] = rate

    return TaxCompileOutput(
        profile_agent=np.asarray(profile_agent, dtype=np.int64),
        profile_payment_slot=np.asarray(payment_slot, dtype=np.int64),
        profile_payment_account=np.asarray(payment_account, dtype=np.int64),
        profile_authority_agent=np.asarray(authority_agent, dtype=np.int64),
        profile_authority_account=np.asarray(authority_account, dtype=np.int64),
        profile_prior_year_tax=np.asarray(prior_year_tax, dtype=np.float64),
        profile_section_121_exclusion=np.asarray(section_121_exclusion, dtype=np.float64),
        link_profile=np.asarray(link_profile, dtype=np.int64),
        link_jurisdiction=np.asarray(link_jurisdiction, dtype=np.int64),
        link_standard_deduction=np.asarray(standard_deduction, dtype=np.float64),
        link_has_ltcg=np.asarray(has_ltcg, dtype=np.int64),
        link_section_1250_rate=np.asarray(section_1250_rate, dtype=np.float64),
        link_ordinary_upper=ordinary_upper,
        link_ordinary_rate=ordinary_rate,
        link_ordinary_count=ordinary_count,
        link_ltcg_upper=ltcg_upper,
        link_ltcg_rate=ltcg_rate,
        link_ltcg_count=ltcg_count,
    )


def _compile_mortgage_interest_deductions(
    scenario: Scenario, strings: StringTable, *, tax: TaxCompileOutput, liabilities: LiabilityCompileOutput
) -> MIDCompileOutput:
    """Compile the precomputed per-(tax_link, liability) MID ratio matrix.

    For each (link, liability) pair, the ratio is the pro-rata
    `min(1, principal_cap / origination_principal)` factor applied to YTD interest
    when the engine sums MID at year-end. Zero where: (a) the liability isn't
    owned by the link's profile agent, (b) the liability has no
    MortgageInterestDeductionPolicy entry, (c) the policy's
    per_jurisdiction_principal_cap_usd map omits the link's jurisdiction, or
    (d) the policy's `debt_class == "home_equity"` (TCJA disallow §163(h)(3)).
    """

    link_count = tax.link_profile.shape[0]
    liability_count = liabilities.codes.shape[0]
    ratio = np.zeros((max(1, link_count), max(1, liability_count)), dtype=np.float64)
    active = np.zeros(max(1, link_count), dtype=np.bool_)

    if link_count == 0 or liability_count == 0 or not scenario.mortgage_interest_deduction_policies:
        return MIDCompileOutput(principal_ratio=ratio, link_active=active)

    liability_slot_by_code = {int(liabilities.codes[lia]): lia for lia in range(liability_count)}
    policies_by_liability_slot: dict[int, MortgageInterestDeductionPolicy] = {}
    for policy in scenario.mortgage_interest_deduction_policies:
        liability_code = strings.require(policy.liability_id)
        if liability_code not in liability_slot_by_code:
            raise ValueError(
                f"mortgage_interest_deduction_policies references unknown liability_id "
                f"{policy.liability_id!r}; known liabilities: {sorted(strings.values[int(c)] for c in liabilities.codes)}"
            )
        lia_slot = liability_slot_by_code[liability_code]
        owner_code = strings.require(policy.owner_agent_id)
        if int(liabilities.agent[lia_slot]) != owner_code:
            raise ValueError(
                f"mortgage_interest_deduction_policies owner_agent_id={policy.owner_agent_id!r} does not match "
                f"the liability's owner for liability_id={policy.liability_id!r}"
            )
        policies_by_liability_slot[lia_slot] = policy

    for link in range(link_count):
        profile_index = int(tax.link_profile[link])
        link_agent_code = int(tax.profile_agent[profile_index])
        jurisdiction_id = strings.values[int(tax.link_jurisdiction[link])]
        for lia_slot, policy in policies_by_liability_slot.items():
            if int(liabilities.agent[lia_slot]) != link_agent_code:
                continue
            if policy.debt_class == "home_equity":
                # TCJA (§163(h)(3), 2018-2025): home-equity-debt interest is not deductible.
                # Leave ratio[link, lia_slot] at 0.0 so the engine sums in nothing for this
                # liability. Callers who layer a HELOC-for-improvement should tag it
                # "acquisition" — we do not model the substantial-improvement carve-out.
                continue
            cap = policy.per_jurisdiction_principal_cap_usd.get(jurisdiction_id)
            if cap is None:
                continue
            principal = float(liabilities.principal[lia_slot])
            if principal <= 0.0:
                continue
            # Principal-cap ratio only. The owner-vs-rented split is now applied at runtime
            # via parallel `liability_rental_interest_ytd` accumulation that mirrors
            # `current.property_rented_fraction` — mid-horizon lifecycle events take effect
            # immediately in MID/Schedule E.
            ratio[link, lia_slot] = min(1.0, float(cap) / principal)
        active[link] = bool(np.any(ratio[link] > 0.0))

    return MIDCompileOutput(principal_ratio=ratio, link_active=active)


@dataclass(frozen=True)
class MIDCompileOutput:
    """Per-(tax_link, liability) Mortgage Interest Deduction (§163(h)(3)) plumbing.

    - `principal_ratio[link, lia]` = pro-rata `min(1, principal_cap[jurisdiction] /
      liability_principal[lia])` for liabilities owned by the link's profile agent and
      listed in a MortgageInterestDeductionPolicy; 0.0 otherwise. Engine does
      `interest_ytd @ principal_ratio[link]` per link to get MID per rollout.
    - `link_active[link]`: True iff that link has at least one non-zero principal_ratio
      entry; lets the engine skip the matmul + max for jurisdictions or scenarios
      without MID-eligible debt."""

    principal_ratio: NDArray[np.float64]
    link_active: NDArray[np.bool_]


@dataclass(frozen=True)
class SaltCompileOutput:
    """Per-tax-link federal SALT-deduction plumbing.

    - `link_active[link]`: True iff `link` is the federal jurisdiction of a profile with a
      FederalSaltDeductionPolicy. Federal SALT deduction is only computed for these links.
    - `cap_by_year[link, year]`: per-calendar-year SALT cap in USD for SALT-active links;
      0.0 elsewhere (and unread on the engine side). Year index 0 = first horizon year.
    - `contributing_mask[link, other_link]`: True iff `other_link` is a non-federal sibling
      (same profile) of the SALT-active federal `link`. Engine sums the first-pass annual
      tax of these state links into the federal SALT total."""

    link_active: NDArray[np.bool_]
    cap_by_year: NDArray[np.float64]
    contributing_mask: NDArray[np.bool_]


def _compile_federal_salt_deductions(
    scenario: Scenario, strings: StringTable, *, tax: TaxCompileOutput
) -> SaltCompileOutput:
    """Compile federal SALT-deduction plumbing.

    Returns three arrays sized to the tax-link grid:

    - `salt_active[link]`: True iff `link` is the federal jurisdiction of a profile
      with a FederalSaltDeductionPolicy.
    - `salt_cap_by_year[link, year]`: per-calendar-year SALT cap in USD for SALT-active
      links; the schedule's cap entries are forward-filled across the horizon.
    - `contributing_mask[link, other_link]`: True iff `other_link` is a non-federal
      sibling (same profile) of the SALT-active federal `link`. Engine sums the
      first-pass annual tax of these state links into the federal SALT total.
    """

    link_count = tax.link_profile.shape[0]
    horizon = int(scenario.horizon_months)
    year_count = max(1, (horizon + 11) // 12)
    salt_active = np.zeros(max(1, link_count), dtype=np.bool_)
    salt_cap_by_year = np.zeros((max(1, link_count), year_count), dtype=np.float64)
    contributing_mask = np.zeros((max(1, link_count), max(1, link_count)), dtype=np.bool_)

    if link_count == 0 or not scenario.federal_salt_deduction_policies:
        return SaltCompileOutput(
            link_active=salt_active, cap_by_year=salt_cap_by_year, contributing_mask=contributing_mask
        )

    # Map (profile_index, jurisdiction_code) -> link_index for cross-link lookups.
    link_by_profile_jurisdiction: dict[tuple[int, int], int] = {}
    for link in range(link_count):
        profile_idx = int(tax.link_profile[link])
        jur_code = int(tax.link_jurisdiction[link])
        link_by_profile_jurisdiction[(profile_idx, jur_code)] = link

    profile_index_by_agent: dict[int, int] = {
        strings.require(p.agent_id): i for i, p in enumerate(scenario.tax_profiles)
    }

    for policy in scenario.federal_salt_deduction_policies:
        profile_agent_code = strings.require(policy.profile_id)
        profile_index = profile_index_by_agent.get(profile_agent_code)
        if profile_index is None:
            raise ValueError(
                f"federal_salt_deduction_policies profile_id={policy.profile_id!r} does not match "
                f"any TaxProfile.agent_id"
            )
        federal_jur_code = strings.require(policy.federal_jurisdiction_id)
        federal_link = link_by_profile_jurisdiction.get((profile_index, federal_jur_code))
        if federal_link is None:
            raise ValueError(
                f"federal_salt_deduction_policies profile_id={policy.profile_id!r} does not have a "
                f"tax link for federal_jurisdiction_id={policy.federal_jurisdiction_id!r}"
            )
        salt_active[federal_link] = True
        for sibling in range(link_count):
            if sibling == federal_link:
                continue
            if int(tax.link_profile[sibling]) != profile_index:
                continue
            contributing_mask[federal_link, sibling] = True

        # Forward-fill the cap schedule across the horizon's calendar years. Entries are
        # tuples (effective_year_index, cap_usd); for each year, pick the latest entry whose
        # effective_year_index <= year. If no entry applies (e.g. schedule starts at year 2),
        # the cap is 0 (no allowed deduction). An empty schedule means SALT is effectively
        # uncapped — represent that by a large sentinel cap.
        if not policy.cap_schedule:
            salt_cap_by_year[federal_link, :] = np.inf
            continue
        sorted_entries = sorted(policy.cap_schedule, key=lambda entry: entry.effective_year_index)
        for year in range(year_count):
            applicable = [entry for entry in sorted_entries if entry.effective_year_index <= year]
            if not applicable:
                salt_cap_by_year[federal_link, year] = 0.0
            else:
                salt_cap_by_year[federal_link, year] = float(applicable[-1].cap_usd)

    return SaltCompileOutput(link_active=salt_active, cap_by_year=salt_cap_by_year, contributing_mask=contributing_mask)


def _compile_capital_gain_agents(scenario: Scenario, strings: StringTable) -> tuple[np.ndarray, np.ndarray]:
    agent_ids: list[str] = []
    seen: set[str] = set()

    def add(agent_id: str) -> None:
        if agent_id in seen:
            return
        seen.add(agent_id)
        agent_ids.append(agent_id)

    for profile in scenario.tax_profiles:
        add(profile.agent_id)
    for lot in scenario.initial_lots:
        add(lot.agent_id)
    for sale in scenario.scheduled_asset_sales:
        add(sale.agent_id)
    for policy in scenario.liquidity_policies:
        add(policy.agent_id)

    index_by_agent = {agent_id: idx for idx, agent_id in enumerate(agent_ids)}
    return (
        np.asarray([strings.require(agent_id) for agent_id in agent_ids], dtype=np.int64),
        np.asarray([index_by_agent[profile.agent_id] for profile in scenario.tax_profiles], dtype=np.int64),
    )


@dataclass(frozen=True)
class TaxLiabilityCompileOutput:
    """Per-tax-liability arrays produced by `_compile_tax_liability_slots`. One row per
    (link, year-end-month) pair where a tax liability accrues. Engine looks up the
    profile + link + payment month to schedule estimated-tax/true-up obligations."""

    profile_index: NDArray[np.int64]
    link_index: NDArray[np.int64]
    year_end_month: NDArray[np.int64]


def _compile_tax_liability_slots(horizon: int, tax: TaxCompileOutput) -> TaxLiabilityCompileOutput:
    profile_indices = []
    link_indices = []
    end_months = []
    for month in range(horizon):
        if month % 12 != 11:
            continue
        for link_index, profile_index in enumerate(tax.link_profile.tolist()):
            profile_indices.append(profile_index)
            link_indices.append(link_index)
            end_months.append(month)
    return TaxLiabilityCompileOutput(
        profile_index=np.asarray(profile_indices, dtype=np.int64),
        link_index=np.asarray(link_indices, dtype=np.int64),
        year_end_month=np.asarray(end_months, dtype=np.int64),
    )


@dataclass(frozen=True)
class ObligationCompileOutput:
    """Per-(month, slot) obligation plumbing covering scheduled/recurring
    obligations + mortgage payments + property-tax accruals + estimated-tax/
    true-up payments. `source_kind`/`source_index` discriminate which subsystem
    drives this slot (kind 0 = scenario obligation, 1 = mortgage, 2 = property
    tax, 3 = quarterly estimated tax, 4 = Q4 estimate, 5 = year-end true-up).
    `property_tax_profile` + `property_slot` are populated for kind==2 only
    (NO_CODE elsewhere). `deduction_profile`/`deductible_fraction` route
    Schedule-E deductions for obligations whose `deduction_category` was set."""

    cause: NDArray[np.int64]
    id: NDArray[np.int64]
    type: NDArray[np.int64]
    agent: NDArray[np.int64]
    from_account: NDArray[np.int64]
    from_slot: NDArray[np.int64]
    to_agent: NDArray[np.int64]
    to_account: NDArray[np.int64]
    to_slot: NDArray[np.int64]
    amount_kind: NDArray[np.int64]
    amount_fixed: NDArray[np.float64]
    amount_base: NDArray[np.float64]
    amount_series: NDArray[np.int64]
    amount_base_month: NDArray[np.int64]
    amount_period: NDArray[np.int64]
    source_kind: NDArray[np.int64]
    source_index: NDArray[np.int64]
    property_tax_profile: NDArray[np.int64]
    property_slot: NDArray[np.int64]
    deduction_profile: NDArray[np.int64]
    deductible_fraction: NDArray[np.float64]


def _compile_obligation_slots(
    scenario: Scenario,
    strings: StringTable,
    account_slot_by_key: dict[tuple[str, str], int],
    series_index_by_id: dict[str, int],
    properties: PropertyCompileOutput,
    property_slot_by_id: dict[str, int],
    liabilities: LiabilityCompileOutput,
    tax: TaxCompileOutput,
) -> ObligationCompileOutput:
    horizon = int(scenario.horizon_months)
    monthly_specs: list[list[dict[str, Any]]] = [[] for _ in range(horizon)]

    for obligation in scenario.scheduled_obligations:
        if 0 <= obligation.month < horizon:
            monthly_specs[obligation.month].append({"kind": 0, "source": NO_CODE, "config": obligation})
    for month in range(horizon):
        for obligation in scenario.recurring_obligations:
            if obligation.is_active_at(month):
                monthly_specs[month].append({"kind": 0, "source": NO_CODE, "config": obligation})

    for month in range(horizon):
        for liability_slot, liability_code in enumerate(liabilities.codes.tolist()):
            prop_slot = int(liabilities.property_slot[liability_slot])
            monthly_specs[month].append(
                {"kind": 1, "source": liability_slot, "liability_code": liability_code, "prop_slot": prop_slot}
            )

    for month in range(horizon):
        for prop_slot, prop_code in enumerate(properties.id.tolist()):
            if prop_slot < properties.month.shape[0]:
                monthly_specs[month].append({"kind": 2, "source": prop_slot, "property_code": prop_code})

    for month in range(horizon):
        quarter = _estimated_tax_quarter(month)
        if quarter in {1, 2, 3}:
            for profile_index, prior_year_tax in enumerate(tax.profile_prior_year_tax.tolist()):
                if prior_year_tax > 0:
                    monthly_specs[month].append({"kind": 3, "source": profile_index, "quarter": quarter})
        elif quarter == 4:
            tax_year = month // 12 - 1
            if tax_year >= 0:
                for profile_index in range(len(tax.profile_prior_year_tax)):
                    monthly_specs[month].append({"kind": 4, "source": profile_index, "tax_year": tax_year})
                    monthly_specs[month].append({"kind": 5, "source": profile_index, "tax_year": tax_year})

    max_slots = max(1, max((len(specs) for specs in monthly_specs), default=0))
    cause = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    obligation_id = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    obligation_type = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    agent = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    from_account = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    from_slot = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    to_agent = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    to_account = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    to_slot = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    amount_kind = empty_month_matrix(horizon, max_slots, np.int64, AMOUNT_FIXED)
    amount_fixed = empty_month_matrix(horizon, max_slots, np.float64, 0.0)
    amount_base = empty_month_matrix(horizon, max_slots, np.float64, 0.0)
    amount_series = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    amount_base_month = empty_month_matrix(horizon, max_slots, np.int64, 0)
    amount_period = empty_month_matrix(horizon, max_slots, np.int64, 1)
    source_kind = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    source_index = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    # Default NO_CODE; populated only for property-tax obligations whose owner has a TaxProfile.
    property_tax_profile = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    # Property slot for property-tax obligations. NO_CODE elsewhere.
    property_slot_matrix = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    # Schedule E deduction wiring: NO_CODE / 0.0 unless the obligation declares
    # deduction_category. Engine decrements ordinary_ytd by amount × deductible_fraction
    # at settlement time when deduction_profile >= 0.
    deduction_profile = empty_month_matrix(horizon, max_slots, np.int64, NO_CODE)
    deductible_fraction = empty_month_matrix(horizon, max_slots, np.float64, 0.0)
    agent_to_profile_index: dict[int, int] = {
        strings.require(p.agent_id): i for i, p in enumerate(scenario.tax_profiles)
    }

    profile_by_index = scenario.tax_profiles
    for month, specs in enumerate(monthly_specs):
        for idx, spec in enumerate(specs):
            source_kind[month, idx] = int(spec["kind"])
            source_index[month, idx] = int(spec["source"])
            if spec["kind"] == 0:
                config = spec["config"]
                assert isinstance(config, ScheduledObligation | RecurringObligation)
                cause_text = f"{config.obligation_id}_m{month}"
                cause[month, idx] = strings.require(cause_text)
                obligation_id[month, idx] = strings.require(cause_text)
                obligation_type[month, idx] = strings.require(config.obligation_type)
                agent[month, idx] = strings.require(config.agent_id)
                from_account[month, idx] = strings.require(config.from_account_id)
                from_slot[month, idx] = slot(account_slot_by_key, config.agent_id, config.from_account_id)
                to_agent[month, idx] = strings.require(config.to_agent_id)
                to_account[month, idx] = strings.require(config.to_account_id)
                to_slot[month, idx] = slot(account_slot_by_key, config.to_agent_id, config.to_account_id)
                kind, fixed, base, series, base_month, period = amount_arrays(config.amount_due_usd, series_index_by_id)
                amount_kind[month, idx] = kind
                amount_fixed[month, idx] = fixed
                amount_base[month, idx] = base
                amount_series[month, idx] = series
                amount_base_month[month, idx] = base_month
                amount_period[month, idx] = period
                if config.deduction_category == ORDINARY_DEDUCTION_CATEGORY:
                    profile = agent_to_profile_index.get(strings.require(config.agent_id), NO_CODE)
                    deduction_profile[month, idx] = profile
                    deductible_fraction[month, idx] = float(config.deductible_fraction)
                # Tie the obligation to a property if requested so the engine reads runtime
                # rented_fraction at settlement time instead of the compile-time fraction.
                if config.property_id is not None:
                    if config.property_id not in property_slot_by_id:
                        raise ValueError(
                            f"Obligation {config.obligation_id!r} references unknown property_id {config.property_id!r}"
                        )
                    property_slot_matrix[month, idx] = property_slot_by_id[config.property_id]
            elif spec["kind"] in {1, 2, 3, 4, 5}:
                # The dynamic source fields are decoded later from source_kind/source_index.
                continue

    # Fill dynamic source metadata after all strings that profiles/properties need are interned.
    for month, specs in enumerate(monthly_specs):
        for idx, spec in enumerate(specs):
            kind = int(spec["kind"])
            if kind == 1:
                liability_slot = int(spec["source"])
                if liability_slot >= liabilities.property_slot.shape[0]:
                    continue
                purchase = scenario.scheduled_property_purchases[int(liabilities.property_slot[liability_slot])]
                if purchase.mortgage is None:
                    continue
                cause_text = f"{purchase.mortgage.liability_id}_payment_m{month}"
                cause[month, idx] = strings.require(cause_text)
                obligation_id[month, idx] = strings.require(cause_text)
                obligation_type[month, idx] = strings.require("mortgage_payment")
                agent[month, idx] = strings.require(purchase.buyer_agent_id)
                from_account[month, idx] = strings.require(purchase.buyer_account_id)
                from_slot[month, idx] = slot(account_slot_by_key, purchase.buyer_agent_id, purchase.buyer_account_id)
                to_agent[month, idx] = strings.require(purchase.mortgage.lender_agent_id)
                to_account[month, idx] = strings.require(purchase.mortgage.lender_account_id)
                to_slot[month, idx] = slot(
                    account_slot_by_key, purchase.mortgage.lender_agent_id, purchase.mortgage.lender_account_id
                )
            elif kind == 2:
                prop_slot = int(spec["source"])
                if prop_slot >= len(scenario.scheduled_property_purchases):
                    continue
                purchase = scenario.scheduled_property_purchases[prop_slot]
                policy = next(
                    (
                        p
                        for p in scenario.property_tax_policies
                        if p.property_id == purchase.property_id and p.is_active_at(month)
                    ),
                    None,
                )
                if policy is None:
                    source_kind[month, idx] = NO_CODE
                    continue
                cause_text = f"{policy.property_id}_property_tax_m{month}"
                cause[month, idx] = strings.require(cause_text)
                obligation_id[month, idx] = strings.require(cause_text)
                obligation_type[month, idx] = strings.require("property_tax")
                agent[month, idx] = strings.require(policy.owner_agent_id)
                from_account[month, idx] = strings.require(policy.from_account_id)
                from_slot[month, idx] = slot(account_slot_by_key, policy.owner_agent_id, policy.from_account_id)
                to_agent[month, idx] = strings.require(policy.tax_authority_agent_id)
                to_account[month, idx] = strings.require(policy.tax_authority_account_id)
                to_slot[month, idx] = slot(
                    account_slot_by_key, policy.tax_authority_agent_id, policy.tax_authority_account_id
                )
                amount_fixed[month, idx] = (
                    float(policy.annual_tax_rate) if policy.annual_tax_rate is not None else np.nan
                )
                owner_code = strings.require(policy.owner_agent_id)
                owner_profile = agent_to_profile_index.get(owner_code, NO_CODE)
                property_tax_profile[month, idx] = owner_profile
                # Wire the property slot so the engine can look up runtime rented_fraction at
                # settlement time. SALT/Schedule E split moves with mid-horizon lifecycle events.
                property_slot_matrix[month, idx] = prop_slot
                rented_fraction_val = float(purchase.rented_fraction)
                if owner_profile >= 0:
                    deduction_profile[month, idx] = owner_profile
                    deductible_fraction[month, idx] = rented_fraction_val
            elif kind in {3, 4, 5}:
                profile_index = int(spec["source"])
                profile = profile_by_index[profile_index]
                if kind == 3:
                    quarter = int(spec["quarter"])
                    tax_year = month // 12
                    cause_text = f"{profile.agent_id}_estimated_tax_q{quarter}_y{tax_year}"
                    obligation_type_text = "estimated_tax"
                elif kind == 4:
                    tax_year = int(spec["tax_year"])
                    cause_text = f"{profile.agent_id}_estimated_tax_q4_y{tax_year}"
                    obligation_type_text = "estimated_tax"
                else:
                    tax_year = int(spec["tax_year"])
                    cause_text = f"{profile.agent_id}_tax_true_up_y{tax_year}"
                    obligation_type_text = "tax_true_up"
                cause[month, idx] = strings.require(cause_text)
                obligation_id[month, idx] = strings.require(cause_text)
                obligation_type[month, idx] = strings.require(obligation_type_text)
                agent[month, idx] = strings.require(profile.agent_id)
                from_account[month, idx] = strings.require(profile.payment_account_id)
                from_slot[month, idx] = slot(account_slot_by_key, profile.agent_id, profile.payment_account_id)
                to_agent[month, idx] = strings.require(profile.tax_authority_agent_id)
                to_account[month, idx] = strings.require(profile.tax_authority_account_id)
                to_slot[month, idx] = slot(
                    account_slot_by_key, profile.tax_authority_agent_id, profile.tax_authority_account_id
                )
    return ObligationCompileOutput(
        cause=cause,
        id=obligation_id,
        type=obligation_type,
        agent=agent,
        from_account=from_account,
        from_slot=from_slot,
        to_agent=to_agent,
        to_account=to_account,
        to_slot=to_slot,
        amount_kind=amount_kind,
        amount_fixed=amount_fixed,
        amount_base=amount_base,
        amount_series=amount_series,
        amount_base_month=amount_base_month,
        amount_period=amount_period,
        source_kind=source_kind,
        source_index=source_index,
        property_tax_profile=property_tax_profile,
        property_slot=property_slot_matrix,
        deduction_profile=deduction_profile,
        deductible_fraction=deductible_fraction,
    )


def _estimated_tax_quarter(month: int) -> int | None:
    month_in_year = month % 12
    if month_in_year == 3:
        return 1
    if month_in_year == 5:
        return 2
    if month_in_year == 8:
        return 3
    if month_in_year == 0 and month > 0:
        return 4
    return None
