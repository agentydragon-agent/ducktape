"""Adapt the canonical integer fixture to the existing Python/JAX simulator."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import numpy as np

from finance.augur.model.series import LevelSeriesKey, SecurityDistributionKey, SecurityKey, SecuritySymbol
from finance.augur.sim.external_series import ExternalSeriesContext
from finance.augur.sim.scenario import (
    ORDINARY_INCOME,
    Agent,
    DistributionTaxSlice,
    InitialAccountBalance,
    InitialLot,
    RecurringObligation,
    RecurringTransfer,
    Scenario,
    ScheduledAssetSale,
    ScheduledObligation,
    ScheduledTransfer,
    SecurityDistribution,
    TaxProfile,
)
from finance.augur.sim.simulate import simulate_with_external_series


def _money(quanta: int, quantum: str) -> Decimal:
    return Decimal(quanta) * Decimal(quantum)


def build_legacy_fixture(fixture: dict[str, Any]) -> tuple[Scenario, ExternalSeriesContext]:
    """Build existing-simulator inputs from one strict integer fixture.

    Conversion to legacy floats occurs only for the old quantity and external
    level surfaces. Money remains exact Decimal at the adapter boundary and is
    quantized by the existing simulator's fixed-point compiler.
    """

    quantum = cast(str, fixture["currency_quantum"])
    scenario_spec = cast(dict[str, Any], fixture["scenario"])
    account_specs = cast(list[dict[str, Any]], scenario_spec["accounts"])
    agents = sorted({cast(str, spec["account"]["agent_id"]) for spec in account_specs})

    rollout_count = cast(int, fixture["rollout_count"])
    lots = cast(list[dict[str, Any]], scenario_spec["initial_lots"])
    sales = cast(list[dict[str, Any]], scenario_spec["scheduled_sales"])
    level_blocks: list[tuple[LevelSeriesKey, Any]] = []
    price_matrices: dict[str, np.ndarray[Any, np.dtype[np.int64]]] = {}
    for series in fixture["series"]:
        series_id = cast(str, series["series_id"])
        if series_id.startswith("security:"):
            asset_id = series_id.removeprefix("security:")
            key: LevelSeriesKey = SecurityKey(symbol=SecuritySymbol(asset_id))
        elif series_id.startswith("security_distribution:"):
            asset_id = series_id.removeprefix("security_distribution:")
            key = SecurityDistributionKey(symbol=SecuritySymbol(asset_id))
        else:
            continue
        snapshots = cast(int, series["snapshots"])
        price_matrix_quanta = np.asarray(series["values"], dtype=np.int64).reshape(rollout_count, snapshots)
        price_matrix = price_matrix_quanta.astype(np.float64) * float(Decimal(quantum))
        if isinstance(key, SecurityKey):
            price_matrices[asset_id] = price_matrix_quanta
        level_blocks.append((key, price_matrix))

    pool_scales: dict[tuple[str, str, str], int] = {}
    for lot in lots:
        pool = (lot["agent_id"], lot["account_id"], lot["asset_id"])
        scale = cast(int, lot["quantity_scale"])
        previous = pool_scales.setdefault(pool, scale)
        if previous != scale:
            raise ValueError(f"mixed quantity scales for FIFO pool {pool!r}")
        if cast(int, lot["basis"]) * scale % cast(int, lot["units"]):
            raise ValueError(f"lot {lot['lot_id']!r} has non-integral legacy per-unit basis")

    def sale_price(spec: dict[str, Any]) -> Decimal:
        prices = price_matrices[cast(str, spec["asset_id"])][:, cast(int, spec["month"])]
        if np.unique(prices).size != 1:
            raise ValueError(
                f"legacy ScheduledAssetSale requires one fixed price across rollouts for {spec['cause_id']!r}"
            )
        return _money(int(prices[0]), quantum)

    scenario = Scenario(
        agents=[Agent(agent_id=agent_id) for agent_id in agents],
        initial_cash=[
            InitialAccountBalance(
                agent_id=spec["account"]["agent_id"],
                account_id=spec["account"]["account_id"],
                balance=_money(spec["opening_balance"], quantum),
            )
            for spec in account_specs
        ],
        scheduled_transfers=[
            ScheduledTransfer(
                month=spec["month"],
                cause_id=spec["cause_id"],
                from_agent_id=spec["from"]["agent_id"],
                from_account_id=spec["from"]["account_id"],
                to_agent_id=spec["to"]["agent_id"],
                to_account_id=spec["to"]["account_id"],
                amount=_money(spec["amount"], quantum),
                income_category=ORDINARY_INCOME if spec.get("income_category") == "ordinary" else None,
            )
            for spec in scenario_spec["scheduled_transfers"]
        ],
        recurring_transfers=[
            RecurringTransfer(
                start_month=spec["start_month"],
                end_month=spec["end_month"],
                cause_id=spec["cause_id"],
                from_agent_id=spec["from"]["agent_id"],
                from_account_id=spec["from"]["account_id"],
                to_agent_id=spec["to"]["agent_id"],
                to_account_id=spec["to"]["account_id"],
                amount=_money(spec["amount"], quantum),
                income_category=ORDINARY_INCOME if spec.get("income_category") == "ordinary" else None,
            )
            for spec in scenario_spec["recurring_transfers"]
        ],
        scheduled_obligations=[
            ScheduledObligation(
                month=spec["month"],
                obligation_id=spec["obligation_id"],
                obligation_type=spec.get("obligation_type", "cash_spend"),
                agent_id=spec["from"]["agent_id"],
                from_account_id=spec["from"]["account_id"],
                to_agent_id=spec["to"]["agent_id"],
                to_account_id=spec["to"]["account_id"],
                amount_due=_money(spec["amount_due"], quantum),
            )
            for spec in scenario_spec["obligations"]
        ],
        recurring_obligations=[
            RecurringObligation(
                start_month=spec["start_month"],
                end_month=spec["end_month"],
                obligation_id=spec["obligation_id"],
                obligation_type=spec.get("obligation_type", "cash_spend"),
                agent_id=spec["from"]["agent_id"],
                from_account_id=spec["from"]["account_id"],
                to_agent_id=spec["to"]["agent_id"],
                to_account_id=spec["to"]["account_id"],
                amount_due=_money(spec["amount_due"], quantum),
            )
            for spec in scenario_spec.get("recurring_obligations", [])
        ],
        initial_lots=[
            InitialLot(
                lot_id=spec["lot_id"],
                agent_id=spec["agent_id"],
                account_id=spec["account_id"],
                asset=SecurityKey(symbol=SecuritySymbol(spec["asset_id"])),
                purchase_month_index=spec["purchase_month"],
                quantity=spec["units"] / spec["quantity_scale"],
                cost_basis_per_unit=_money(spec["basis"] * spec["quantity_scale"] // spec["units"], quantum),
            )
            for spec in lots
        ],
        scheduled_asset_sales=[
            ScheduledAssetSale(
                month=spec["month"],
                cause_id=spec["cause_id"],
                agent_id=spec["agent_id"],
                source_account_id=spec["account_id"],
                asset=SecurityKey(symbol=SecuritySymbol(spec["asset_id"])),
                quantity=spec["units"] / pool_scales[(spec["agent_id"], spec["account_id"], spec["asset_id"])],
                proceeds_account_id=spec["proceeds_account_id"],
                price_per_unit=sale_price(spec),
            )
            for spec in sales
        ],
        security_distributions=[
            SecurityDistribution(
                asset=SecurityKey(symbol=SecuritySymbol(spec["asset_id"])),
                agent_id=spec["agent_id"],
                holding_account_id=spec["holding_account_id"],
                to_account_id=spec["to_account_id"],
                tax_character=(DistributionTaxSlice(fraction=1.0),),
            )
            for spec in scenario_spec.get("distributions", [])
        ],
        tax_profiles=[
            TaxProfile(
                agent_id=spec["agent_id"],
                jurisdiction_ids=[rules["jurisdiction_id"] for rules in spec["jurisdictions"]],
                tax_authority_agent_id=spec["tax_authority_agent_id"],
                payment_account_id=spec.get("payment_account_id", "checking"),
                tax_authority_account_id=spec.get("tax_authority_account_id", "checking"),
            )
            for spec in scenario_spec.get("tax_profiles", [])
        ],
        horizon_months=scenario_spec["horizon_months"],
    )
    external = ExternalSeriesContext.from_level_blocks(
        level_blocks, rollout_count=rollout_count, horizon_months=scenario_spec["horizon_months"]
    )
    return scenario, external


def run_legacy_fixture(fixture: dict[str, Any]):
    scenario, external = build_legacy_fixture(fixture)
    return simulate_with_external_series(
        scenario, rollout_count=cast(int, fixture["rollout_count"]), external_series=external, locations={}
    )
