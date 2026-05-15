from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

import numpy as np

from augur.core.augur_accounting import (
    DEPRECIATION_LIFE_YEARS,
    MONTHS_PER_YEAR,
    PROP_13_ANNUAL_CAP,
    RENT_COUNTERFACTUAL_SELECTED_PROPERTY,
    amortization_schedule,
    occupied_month_count,
    resolve_financing,
    room_rental_count,
    room_rental_share,
)
from augur.core.schemas import ColumnarTable, Financing, JointRolloutPath, PropertyRequest, ScenarioKnobs


@dataclass(frozen=True)
class MarketPathMatrix:
    home_value_multipliers: np.ndarray
    sale_home_value_multipliers: np.ndarray
    portfolio_multipliers: np.ndarray
    rent_multipliers: np.ndarray
    expense_inflation_multipliers: np.ndarray

    def __post_init__(self) -> None:
        shapes = {
            "home_value_multipliers": self.home_value_multipliers.shape,
            "sale_home_value_multipliers": self.sale_home_value_multipliers.shape,
            "portfolio_multipliers": self.portfolio_multipliers.shape,
            "rent_multipliers": self.rent_multipliers.shape,
            "expense_inflation_multipliers": self.expense_inflation_multipliers.shape,
        }
        if len(set(shapes.values())) != 1:
            raise ValueError(f"market path shapes must match, got {shapes}")
        if len(self.home_value_multipliers.shape) != 2:
            raise ValueError("market paths must be shaped (rollout, month)")
        for name, values in self._arrays().items():
            if not np.all(np.isfinite(values)):
                raise ValueError(f"{name} contains non-finite values")
            if np.any(values <= 0):
                raise ValueError(f"{name} must be positive")

    def _arrays(self) -> dict[str, np.ndarray]:
        return {
            "home_value_multipliers": self.home_value_multipliers,
            "sale_home_value_multipliers": self.sale_home_value_multipliers,
            "portfolio_multipliers": self.portfolio_multipliers,
            "rent_multipliers": self.rent_multipliers,
            "expense_inflation_multipliers": self.expense_inflation_multipliers,
        }

    @property
    def rollout_count(self) -> int:
        return int(self.home_value_multipliers.shape[0])

    @property
    def hold_months(self) -> int:
        return int(self.home_value_multipliers.shape[1] - 1)


@dataclass(frozen=True)
class CheckingFloorPolicy:
    floor_usd: float
    sale_amount_usd: float


@dataclass(frozen=True)
class CheckingFloorPolicyResult:
    checking_balance_usd: np.ndarray
    brokerage_value_usd: np.ndarray
    sp500_sales_usd: np.ndarray


@dataclass(frozen=True)
class VectorizedSimulation:
    market_paths: MarketPathMatrix
    financing: Financing
    purchase_price_usd: float
    down_payment_usd: float
    closing_buy_usd: float
    portfolio_liquidation_tax_usd: float
    initial_outlay_usd: float
    loan_amount_usd: float
    tax_rate: float
    initial_annual_tax_usd: float
    depreciable_basis_usd: float
    hold_months: int
    occupied_months: int
    month_index: np.ndarray
    home_value_usd: np.ndarray
    sale_home_value_usd: np.ndarray
    mortgage_balance_usd: np.ndarray
    mortgage_interest_usd: np.ndarray
    mortgage_principal_usd: np.ndarray
    property_tax_usd: np.ndarray
    insurance_usd: np.ndarray
    hoa_usd: np.ndarray
    maintenance_usd: np.ndarray
    tenant_rent_usd: np.ndarray
    room_rent_usd: np.ndarray
    tax_shield_usd: np.ndarray
    owner_cash_flow_usd: np.ndarray
    property_cash_flow_usd: np.ndarray
    owner_equity_ledger_usd: np.ndarray
    cumulative_depreciation_usd: np.ndarray
    monthly_depreciation_usd: np.ndarray
    rental_taxable_income_usd: np.ndarray
    suspended_passive_losses_usd: np.ndarray
    rental_income_tax_usd: np.ndarray
    sale_selling_costs_usd: np.ndarray
    sale_adjusted_basis_usd: np.ndarray
    sale_total_gain_usd: np.ndarray
    sale_recapture_gain_usd: np.ndarray
    sale_capital_gain_usd: np.ndarray
    sale_exclusion_usd: np.ndarray
    sale_recapture_tax_usd: np.ndarray
    sale_capital_gains_tax_usd: np.ndarray
    sale_passive_loss_release_benefit_usd: np.ndarray
    sale_net_proceeds_usd: np.ndarray
    sale_gross_equity_usd: np.ndarray
    sale_cg_tax_usd: np.ndarray
    rent_path_usd: np.ndarray
    buy_liquid_usd: np.ndarray
    buy_path_usd: np.ndarray
    delta_usd: np.ndarray
    project_buy_liquid_usd: np.ndarray
    project_own_usd: np.ndarray
    project_delta_usd: np.ndarray


def array_columns(record: Any, *, rollout_index: int | None = None) -> dict[str, Any]:
    if not is_dataclass(record):
        raise TypeError("array_columns expects a dataclass instance")
    out: dict[str, Any] = {}
    for field in fields(record):
        value = getattr(record, field.name)
        if isinstance(value, np.ndarray):
            selected = value if rollout_index is None or value.ndim == 1 else value[rollout_index]
            out[field.name] = selected.tolist()
    return out


def columnar_table_from_columns(columns: Mapping[str, Any]) -> ColumnarTable:
    converted: dict[str, list[Any]] = {}
    row_count: int | None = None
    for name, values in columns.items():
        if isinstance(values, np.ndarray):
            column = values.tolist()
        elif isinstance(values, list):
            column = values
        elif isinstance(values, tuple):
            column = list(values)
        else:
            raise TypeError(f"column {name!r} must be an array or sequence")
        if row_count is None:
            row_count = len(column)
        elif len(column) != row_count:
            raise ValueError(f"column {name!r} length {len(column)} does not match row_count {row_count}")
        converted[name] = column
    return ColumnarTable(row_count=row_count or 0, columns=converted)


def columnar_table_from_rows(rows: Sequence[Mapping[str, Any]]) -> ColumnarTable:
    if not rows:
        return ColumnarTable(row_count=0, columns={})
    keys = tuple(rows[0].keys())
    expected = set(keys)
    columns: dict[str, list[Any]] = {key: [] for key in keys}
    for index, row in enumerate(rows):
        actual = set(row.keys())
        if actual != expected:
            raise ValueError(f"row {index} keys {sorted(actual)} do not match first row keys {sorted(expected)}")
        for key in keys:
            columns[key].append(row[key])
    return ColumnarTable(row_count=len(rows), columns=columns)


def array_table(
    record: Any, *, rollout_index: int | None = None, extra_columns: Mapping[str, Any] | None = None
) -> ColumnarTable:
    columns = array_columns(record, rollout_index=rollout_index)
    if extra_columns:
        columns.update(extra_columns)
    return columnar_table_from_columns(columns)


def _as_matrix(values: Any, *, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype="float64")
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.ndim != 2:
        raise ValueError(f"{name} must be one- or two-dimensional")
    return arr


def deterministic_market_paths(knobs: ScenarioKnobs, *, hold_months: int, rollout_count: int = 1) -> MarketPathMatrix:
    months = np.arange(0, hold_months + 1, dtype="float64")

    def annual_path(rate_pct: float) -> np.ndarray:
        return (1 + rate_pct / 100) ** (months / MONTHS_PER_YEAR)

    def choose(values: list[float] | None, fallback: np.ndarray, name: str) -> np.ndarray:
        if values is None:
            arr = fallback
        else:
            arr = np.asarray(values[: hold_months + 1], dtype="float64")
            if arr.shape[0] < hold_months + 1:
                raise ValueError(f"{name} length {arr.shape[0]} < {hold_months + 1}")
        return np.broadcast_to(arr, (rollout_count, hold_months + 1)).copy()

    home = choose(knobs.home_value_multipliers, annual_path(knobs.appreciation_rate), "home_value_multipliers")
    sale_home = choose(knobs.sale_home_value_multipliers, home[0], "sale_home_value_multipliers")
    portfolio = choose(knobs.portfolio_multipliers, annual_path(knobs.sp500_rate), "portfolio_multipliers")
    rent = choose(knobs.rent_multipliers, annual_path(knobs.inflation), "rent_multipliers")
    expenses = choose(
        knobs.expense_inflation_multipliers, annual_path(knobs.inflation), "expense_inflation_multipliers"
    )
    return MarketPathMatrix(
        home_value_multipliers=home,
        sale_home_value_multipliers=sale_home,
        portfolio_multipliers=portfolio,
        rent_multipliers=rent,
        expense_inflation_multipliers=expenses,
    )


def market_paths_from_joint_rollouts(
    joint_rollout_paths: list[Any],
    *,
    hold_months: int,
    rollout_count: int | None = None,
    home_value_location_id: str | None = None,
    rent_location_id: str | None = None,
) -> MarketPathMatrix:
    if not joint_rollout_paths:
        raise ValueError("joint rollout paths are required")
    count = int(rollout_count or len(joint_rollout_paths))
    selected = [
        JointRolloutPath.model_validate(joint_rollout_paths[index % len(joint_rollout_paths)]) for index in range(count)
    ]

    def stack_values(paths: list[list[float]], *, label: str) -> np.ndarray:
        rows = []
        for index, path in enumerate(paths):
            values = np.asarray(path, dtype="float64")
            if values.shape[0] < hold_months + 1:
                raise ValueError(f"joint_rollout_paths[{index}].{label} length {values.shape[0]} < {hold_months + 1}")
            rows.append(values[: hold_months + 1])
        return np.vstack(rows)

    def stack(field: str) -> np.ndarray:
        return stack_values([getattr(path, field) for path in selected], label=field)

    def stack_location(mapping_field: str, location_id: str) -> np.ndarray:
        paths: list[list[float]] = []
        for index, path in enumerate(selected):
            mapping = getattr(path, mapping_field)
            try:
                paths.append(mapping[location_id])
            except KeyError as error:
                raise ValueError(f"joint_rollout_paths[{index}].{mapping_field} is missing {location_id!r}") from error
        return stack_values(paths, label=f"{mapping_field}[{location_id!r}]")

    home = (
        stack("home_value_multipliers")
        if home_value_location_id is None
        else stack_location("home_value_multipliers_by_location", home_value_location_id)
    )
    sale_home = stack("sale_home_value_multipliers") if home_value_location_id is None else home
    rent = (
        stack("rent_multipliers")
        if rent_location_id is None
        else stack_location("rent_multipliers_by_location", rent_location_id)
    )
    return MarketPathMatrix(
        home_value_multipliers=home,
        sale_home_value_multipliers=sale_home,
        portfolio_multipliers=stack("portfolio_multipliers"),
        rent_multipliers=rent,
        expense_inflation_multipliers=stack("expense_inflation_multipliers"),
    )


@dataclass(frozen=True)
class SaleOutcomeArrays:
    selling_costs_usd: np.ndarray
    gross_equity_usd: np.ndarray
    adjusted_basis_usd: np.ndarray
    total_gain_usd: np.ndarray
    recapture_gain_usd: np.ndarray
    capital_gain_usd: np.ndarray
    exclusion_usd: np.ndarray
    recapture_tax_usd: np.ndarray
    capital_gains_tax_usd: np.ndarray
    passive_loss_release_benefit_usd: np.ndarray
    cg_tax_usd: np.ndarray
    net_proceeds_usd: np.ndarray


def _vectorized_sale_outcomes(
    *,
    home_value: np.ndarray,
    mortgage_balance: np.ndarray,
    month_index: np.ndarray,
    knobs: ScenarioKnobs,
    cost_basis: float,
    depreciation_taken: np.ndarray,
    suspended_passive_losses: np.ndarray,
) -> SaleOutcomeArrays:
    selling_costs = home_value * (knobs.closing_cost_sell_pct / 100)
    gross_equity = home_value - mortgage_balance - selling_costs
    adjusted_basis = cost_basis - depreciation_taken
    total_gain = np.maximum(0, home_value - selling_costs - adjusted_basis)
    recapture_gain = np.minimum(depreciation_taken, total_gain)
    capital_gain = np.maximum(0, total_gain - recapture_gain)

    occupied_months = occupied_month_count(knobs)
    lookback_start_exclusive = np.maximum(0, month_index - 5 * MONTHS_PER_YEAR)
    occupied_end = np.minimum(month_index, occupied_months)
    occupied_last_five = np.maximum(0, occupied_end - lookback_start_exclusive)
    exclusion_applies = occupied_last_five >= 24
    qualified_use_months = np.minimum(occupied_months, month_index)
    qualified_fraction = np.divide(
        qualified_use_months, month_index, out=np.zeros_like(month_index, dtype="float64"), where=month_index > 0
    )
    exclusion = np.where(exclusion_applies, knobs.cap_gains_exclusion_usd * qualified_fraction, 0.0)
    taxable_gain = np.maximum(0, capital_gain - exclusion)
    recapture_marginal = min(knobs.marginal_tax_rate, 38.3)
    recapture_tax = recapture_gain * (recapture_marginal / 100)
    capital_gains_tax = taxable_gain * (knobs.cap_gains_rate / 100)
    cg_tax = recapture_tax + capital_gains_tax
    passive_loss_release_benefit = suspended_passive_losses * (knobs.marginal_tax_rate / 100)
    net_sale_proceeds = gross_equity - cg_tax + passive_loss_release_benefit
    return SaleOutcomeArrays(
        selling_costs_usd=selling_costs,
        gross_equity_usd=gross_equity,
        adjusted_basis_usd=adjusted_basis,
        total_gain_usd=total_gain,
        recapture_gain_usd=recapture_gain,
        capital_gain_usd=capital_gain,
        exclusion_usd=exclusion,
        recapture_tax_usd=recapture_tax,
        capital_gains_tax_usd=capital_gains_tax,
        passive_loss_release_benefit_usd=passive_loss_release_benefit,
        cg_tax_usd=cg_tax,
        net_proceeds_usd=net_sale_proceeds,
    )


def simulate_property_vectorized(
    property_: PropertyRequest, knobs: ScenarioKnobs, market_paths: MarketPathMatrix
) -> VectorizedSimulation:
    hold_months = market_paths.hold_months
    if hold_months != int(knobs.hold_years) * MONTHS_PER_YEAR:
        raise ValueError(f"market paths horizon {hold_months} months does not match hold_years={knobs.hold_years}")

    n = market_paths.rollout_count
    financing = resolve_financing(knobs)
    purchase_price = property_.price_usd
    down_payment = purchase_price * (financing.down_payment_pct / 100)
    closing_buy = purchase_price * (knobs.closing_cost_buy_pct / 100)
    portfolio_liquidation_tax = (down_payment + closing_buy) * (knobs.portfolio_liquidation_tax_pct / 100)
    initial_outlay = down_payment + closing_buy + portfolio_liquidation_tax
    loan_amount = purchase_price - down_payment
    occupied_months = occupied_month_count(knobs)
    month_index = np.arange(0, hold_months + 1, dtype="int64")
    month_numbers = np.arange(1, hold_months + 1, dtype="int64")

    amortization = amortization_schedule(
        loan_amount, financing.rate_pct / 100, financing.term_years, int(knobs.hold_years)
    )
    interest = np.asarray([month.interest_usd for month in amortization.monthly], dtype="float64")
    principal = np.asarray([month.principal_usd for month in amortization.monthly], dtype="float64")
    balance_monthly = np.asarray([month.balance_usd for month in amortization.monthly], dtype="float64")

    home_value = purchase_price * market_paths.home_value_multipliers
    sale_home_value = purchase_price * market_paths.sale_home_value_multipliers
    mortgage_balance = np.broadcast_to(np.concatenate([[loan_amount], balance_monthly]), (n, hold_months + 1)).copy()
    mortgage_interest = np.zeros((n, hold_months + 1), dtype="float64")
    mortgage_principal = np.zeros((n, hold_months + 1), dtype="float64")
    mortgage_interest[:, 1:] = interest[None, :]
    mortgage_principal[:, 1:] = principal[None, :]

    tax_rate = property_.tax_rate_override if property_.tax_rate_override is not None else 0.0118268325
    initial_annual_tax = purchase_price * tax_rate
    property_tax = (
        initial_annual_tax * (1 + PROP_13_ANNUAL_CAP) ** ((month_numbers - 1) / MONTHS_PER_YEAR) / MONTHS_PER_YEAR
    )
    expense_multiplier = market_paths.expense_inflation_multipliers[:, :hold_months]
    rent_multiplier = market_paths.rent_multipliers[:, :hold_months]
    insurance = (knobs.insurance_annual_usd / MONTHS_PER_YEAR) * expense_multiplier
    hoa = property_.hoa_monthly_usd * expense_multiplier
    maintenance = (purchase_price * (knobs.maintenance_pct / 100)) / MONTHS_PER_YEAR * expense_multiplier
    property_tax_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    insurance_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    hoa_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    maintenance_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    property_tax_with_zero[:, 1:] = property_tax[None, :]
    insurance_with_zero[:, 1:] = insurance
    hoa_with_zero[:, 1:] = hoa
    maintenance_with_zero[:, 1:] = maintenance

    phase_occupied = month_numbers <= occupied_months
    rent_zestimate = property_.rent_zestimate_usd or 0.0
    tenant_rent_gross = rent_zestimate * rent_multiplier
    collected_rent = tenant_rent_gross * (1 - knobs.vacancy_pct / 100)
    tenant_rent = np.where(
        phase_occupied[None, :],
        0.0,
        collected_rent * (1 - knobs.mgmt_pct / 100)
        - tenant_rent_gross * (knobs.leasing_fee_pct / 100) / MONTHS_PER_YEAR,
    )
    rooms_rented = room_rental_count(property_, knobs)
    room_rent_gross = rooms_rented * knobs.room_rent_monthly_usd * rent_multiplier
    room_rent = np.where(
        phase_occupied[None, :] & (rooms_rented > 0), room_rent_gross * (1 - knobs.room_vacancy_pct / 100), 0.0
    )
    tenant_rent_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    room_rent_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    tenant_rent_with_zero[:, 1:] = tenant_rent
    room_rent_with_zero[:, 1:] = room_rent
    active_rental_share = np.where(phase_occupied, room_rental_share(property_, knobs), 1.0)

    balance_at_start = balance_monthly + principal
    deductible_share = np.divide(
        750_000, balance_at_start, out=np.zeros_like(balance_at_start), where=balance_at_start > 0
    )
    deductible_share = np.minimum(1.0, deductible_share)
    personal_interest = interest * (1 - active_rental_share)
    tax_shield = np.where(phase_occupied, personal_interest * deductible_share * (knobs.marginal_tax_rate / 100), 0.0)
    tax_shield_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    tax_shield_with_zero[:, 1:] = tax_shield[None, :]

    depreciable_basis = (purchase_price + closing_buy) * (knobs.depreciable_basis_pct / 100)
    monthly_depreciation = depreciable_basis / (DEPRECIATION_LIFE_YEARS * MONTHS_PER_YEAR) * active_rental_share
    monthly_depreciation_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    monthly_depreciation_with_zero[:, 1:] = monthly_depreciation[None, :]
    cumulative_depreciation = np.zeros((n, hold_months + 1), dtype="float64")
    suspended_passive_losses = np.zeros((n, hold_months + 1), dtype="float64")
    rental_income_tax = np.zeros((n, hold_months + 1), dtype="float64")
    rental_income_for_tax = np.where(phase_occupied[None, :], room_rent, tenant_rent)
    house_uses = interest[None, :] + property_tax[None, :] + insurance + hoa + maintenance
    rental_taxable_income = (
        rental_income_for_tax - house_uses * active_rental_share[None, :] - monthly_depreciation[None, :]
    )
    rental_taxable_income_with_zero = np.zeros((n, hold_months + 1), dtype="float64")
    rental_taxable_income_with_zero[:, 1:] = rental_taxable_income
    for idx in range(hold_months):
        cumulative_depreciation[:, idx + 1] = cumulative_depreciation[:, idx] + monthly_depreciation[idx]
        taxable = rental_taxable_income[:, idx]
        previous_suspended = suspended_passive_losses[:, idx]
        positive = taxable > 0
        offset = np.where(positive, np.minimum(taxable, previous_suspended), 0.0)
        rental_income_tax[:, idx + 1] = np.where(positive, (taxable - offset) * (knobs.marginal_tax_rate / 100), 0.0)
        suspended_passive_losses[:, idx + 1] = np.where(
            positive, previous_suspended - offset, previous_suspended + np.maximum(0.0, -taxable)
        )

    owner_cash_flow = np.zeros((n, hold_months + 1), dtype="float64")
    owner_cash_flow[:, 0] = -down_payment - closing_buy - portfolio_liquidation_tax
    monthly_cash_flow = (
        -interest[None, :]
        - principal[None, :]
        - property_tax[None, :]
        - insurance
        - hoa
        - maintenance
        + tenant_rent
        + room_rent
        + tax_shield[None, :]
        - rental_income_tax[:, 1:]
    )
    owner_cash_flow[:, 1:] = monthly_cash_flow
    property_cash_flow = owner_cash_flow.copy()

    principal_cumulative = np.concatenate([[0.0], np.cumsum(principal)])
    owner_equity_ledger = np.broadcast_to(down_payment + principal_cumulative, (n, hold_months + 1)).copy()

    month_grid = np.broadcast_to(month_index, (n, hold_months + 1))
    sale = _vectorized_sale_outcomes(
        home_value=sale_home_value,
        mortgage_balance=mortgage_balance,
        month_index=month_grid,
        knobs=knobs,
        cost_basis=purchase_price,
        depreciation_taken=cumulative_depreciation,
        suspended_passive_losses=suspended_passive_losses,
    )

    portfolio = market_paths.portfolio_multipliers
    owner_cash_units = np.cumsum(owner_cash_flow / portfolio, axis=1)
    property_cash_units = np.cumsum(property_cash_flow / portfolio, axis=1)
    buy_liquid = portfolio * (knobs.starting_portfolio_usd + owner_cash_units)
    project_buy_liquid = portfolio * (knobs.starting_portfolio_usd + property_cash_units)

    if knobs.rent_counterfactual_mode == RENT_COUNTERFACTUAL_SELECTED_PROPERTY:
        base_rent = property_.rent_zestimate_usd or 0.0
    else:
        base_rent = knobs.custom_counterfactual_rent_monthly_usd
    counterfactual_rent = np.zeros((n, hold_months + 1), dtype="float64")
    counterfactual_rent[:, 1:] = base_rent * market_paths.rent_multipliers[:, :hold_months]
    counterfactual_units = np.cumsum(counterfactual_rent / portfolio, axis=1)
    rent_path = portfolio * (knobs.starting_portfolio_usd - counterfactual_units)

    buy_path = buy_liquid + sale.net_proceeds_usd
    project_own = project_buy_liquid + sale.net_proceeds_usd
    return VectorizedSimulation(
        market_paths=market_paths,
        financing=financing,
        purchase_price_usd=purchase_price,
        down_payment_usd=down_payment,
        closing_buy_usd=closing_buy,
        portfolio_liquidation_tax_usd=portfolio_liquidation_tax,
        initial_outlay_usd=initial_outlay,
        loan_amount_usd=loan_amount,
        tax_rate=tax_rate,
        initial_annual_tax_usd=initial_annual_tax,
        depreciable_basis_usd=depreciable_basis,
        hold_months=hold_months,
        occupied_months=occupied_months,
        month_index=month_index,
        home_value_usd=home_value,
        sale_home_value_usd=sale_home_value,
        mortgage_balance_usd=mortgage_balance,
        mortgage_interest_usd=mortgage_interest,
        mortgage_principal_usd=mortgage_principal,
        property_tax_usd=property_tax_with_zero,
        insurance_usd=insurance_with_zero,
        hoa_usd=hoa_with_zero,
        maintenance_usd=maintenance_with_zero,
        tenant_rent_usd=tenant_rent_with_zero,
        room_rent_usd=room_rent_with_zero,
        tax_shield_usd=tax_shield_with_zero,
        owner_cash_flow_usd=owner_cash_flow,
        property_cash_flow_usd=property_cash_flow,
        owner_equity_ledger_usd=owner_equity_ledger,
        cumulative_depreciation_usd=cumulative_depreciation,
        monthly_depreciation_usd=monthly_depreciation_with_zero,
        rental_taxable_income_usd=rental_taxable_income_with_zero,
        suspended_passive_losses_usd=suspended_passive_losses,
        rental_income_tax_usd=rental_income_tax,
        sale_selling_costs_usd=sale.selling_costs_usd,
        sale_adjusted_basis_usd=sale.adjusted_basis_usd,
        sale_total_gain_usd=sale.total_gain_usd,
        sale_recapture_gain_usd=sale.recapture_gain_usd,
        sale_capital_gain_usd=sale.capital_gain_usd,
        sale_exclusion_usd=sale.exclusion_usd,
        sale_recapture_tax_usd=sale.recapture_tax_usd,
        sale_capital_gains_tax_usd=sale.capital_gains_tax_usd,
        sale_passive_loss_release_benefit_usd=sale.passive_loss_release_benefit_usd,
        sale_net_proceeds_usd=sale.net_proceeds_usd,
        sale_gross_equity_usd=sale.gross_equity_usd,
        sale_cg_tax_usd=sale.cg_tax_usd,
        rent_path_usd=rent_path,
        buy_liquid_usd=buy_liquid,
        buy_path_usd=buy_path,
        delta_usd=buy_path - rent_path,
        project_buy_liquid_usd=project_buy_liquid,
        project_own_usd=project_own,
        project_delta_usd=project_own - rent_path,
    )


def apply_checking_floor_policy(
    *,
    net_cash_flow_usd: np.ndarray,
    portfolio_multipliers: np.ndarray,
    initial_checking_usd: float,
    initial_brokerage_usd: float,
    policy: CheckingFloorPolicy,
) -> CheckingFloorPolicyResult:
    cash_flow = _as_matrix(net_cash_flow_usd, name="net_cash_flow_usd")
    portfolio = _as_matrix(portfolio_multipliers, name="portfolio_multipliers")
    if cash_flow.shape != portfolio.shape:
        raise ValueError(f"net cash flow shape {cash_flow.shape} must match portfolio shape {portfolio.shape}")
    checking = np.zeros_like(cash_flow, dtype="float64")
    brokerage = np.zeros_like(cash_flow, dtype="float64")
    sales = np.zeros_like(cash_flow, dtype="float64")
    units = np.full(cash_flow.shape[0], initial_brokerage_usd, dtype="float64") / portfolio[:, 0]
    current_checking = np.full(cash_flow.shape[0], initial_checking_usd, dtype="float64")
    for month in range(cash_flow.shape[1]):
        current_checking = current_checking + cash_flow[:, month]
        current_brokerage = units * portfolio[:, month]
        should_sell = current_checking < policy.floor_usd
        sale = np.where(should_sell, np.minimum(policy.sale_amount_usd, current_brokerage), 0.0)
        current_checking = current_checking + sale
        units = units - np.divide(sale, portfolio[:, month], out=np.zeros_like(sale), where=portfolio[:, month] > 0)
        checking[:, month] = current_checking
        brokerage[:, month] = units * portfolio[:, month]
        sales[:, month] = sale
    return CheckingFloorPolicyResult(
        checking_balance_usd=checking, brokerage_value_usd=brokerage, sp500_sales_usd=sales
    )
