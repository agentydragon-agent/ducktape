from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from augur.core.augur_accounting import MONTHS_PER_YEAR


@dataclass(frozen=True)
class MonthlyHouseUseComponents:
    mortgage_interest_usd: Any
    mortgage_principal_usd: Any
    property_tax_usd: Any
    insurance_usd: Any
    hoa_usd: Any
    maintenance_usd: Any


@dataclass(frozen=True)
class OccupantContributionBuildsEquityPolicy:
    owner_actor: str = "rai"
    occupant_actor: str = "auragon"
    base_monthly_payment_usd: float = 0.0
    payment_growth_annual_pct: float = 0.0
    occupied_months: int = 0
    owner_initial_equity_usd: float = 0.0
    freeze_ownership_after_month: int | None = None


@dataclass(frozen=True)
class OccupantContributionResult:
    configured_payment_usd: np.ndarray
    contribution_used_usd: np.ndarray
    unallocated_excess_usd: np.ndarray
    contribution_share: np.ndarray
    occupant_interest_usd: np.ndarray
    occupant_principal_usd: np.ndarray
    occupant_property_tax_usd: np.ndarray
    occupant_insurance_usd: np.ndarray
    occupant_hoa_usd: np.ndarray
    occupant_maintenance_usd: np.ndarray
    owner_principal_usd: np.ndarray
    occupant_equity_ledger_usd: np.ndarray
    owner_equity_ledger_usd: np.ndarray
    live_occupant_ownership_pct: np.ndarray
    occupant_ownership_pct: np.ndarray


def _broadcast_components(components: MonthlyHouseUseComponents) -> tuple[np.ndarray, ...]:
    arrays = [
        np.asarray(components.mortgage_interest_usd, dtype="float64"),
        np.asarray(components.mortgage_principal_usd, dtype="float64"),
        np.asarray(components.property_tax_usd, dtype="float64"),
        np.asarray(components.insurance_usd, dtype="float64"),
        np.asarray(components.hoa_usd, dtype="float64"),
        np.asarray(components.maintenance_usd, dtype="float64"),
    ]
    broadcast = np.broadcast_arrays(*arrays)
    if not broadcast:
        raise ValueError("augur-use components are required")
    if broadcast[0].ndim == 0:
        raise ValueError("augur-use components must include a month axis")
    for values in broadcast:
        if not np.all(np.isfinite(values)):
            raise ValueError("augur-use components must be finite")
        if np.any(values < 0):
            raise ValueError("augur-use components must be non-negative")
    return tuple(np.asarray(values, dtype="float64") for values in broadcast)


def _default_month_index(shape: tuple[int, ...]) -> np.ndarray:
    month_count = shape[-1]
    month_index = np.arange(1, month_count + 1, dtype="int64")
    return np.broadcast_to(month_index, shape)


def _ownership_with_optional_freeze(
    live_ownership_pct: np.ndarray, month_index: np.ndarray, freeze_after_month: int | None
) -> np.ndarray:
    if freeze_after_month is None:
        return live_ownership_pct
    freeze_mask = month_index == freeze_after_month
    found = np.any(freeze_mask, axis=-1, keepdims=True)
    freeze_positions = np.argmax(freeze_mask, axis=-1)
    frozen = np.take_along_axis(live_ownership_pct, freeze_positions[..., None], axis=-1)
    should_freeze = (month_index >= freeze_after_month) & found
    return np.where(should_freeze, frozen, live_ownership_pct)


def apply_occupant_contribution_builds_equity_policy(
    components: MonthlyHouseUseComponents,
    policy: OccupantContributionBuildsEquityPolicy,
    *,
    month_index: Any | None = None,
) -> OccupantContributionResult:
    (interest, principal, property_tax, insurance, hoa, maintenance) = _broadcast_components(components)
    shape = interest.shape
    if month_index is None:
        month_index_array = _default_month_index(shape)
    else:
        month_index_array = np.broadcast_to(np.asarray(month_index, dtype="int64"), shape)

    if policy.base_monthly_payment_usd < 0:
        raise ValueError("base_monthly_payment_usd must be non-negative")
    if policy.owner_initial_equity_usd < 0:
        raise ValueError("owner_initial_equity_usd must be non-negative")

    total_house_uses = interest + principal + property_tax + insurance + hoa + maintenance
    occupied = month_index_array <= policy.occupied_months
    payment_growth = (1 + policy.payment_growth_annual_pct / 100) ** ((month_index_array - 1) / MONTHS_PER_YEAR)
    configured_payment = np.where(occupied, policy.base_monthly_payment_usd * payment_growth, 0.0)
    contribution_used = np.where(occupied, np.minimum(configured_payment, total_house_uses), 0.0)
    unallocated_excess = np.where(occupied, np.maximum(0.0, configured_payment - contribution_used), 0.0)
    contribution_share = np.divide(
        contribution_used,
        total_house_uses,
        out=np.zeros_like(contribution_used, dtype="float64"),
        where=total_house_uses > 0,
    )

    occupant_interest = interest * contribution_share
    occupant_principal = principal * contribution_share
    occupant_property_tax = property_tax * contribution_share
    occupant_insurance = insurance * contribution_share
    occupant_hoa = hoa * contribution_share
    occupant_maintenance = maintenance * contribution_share
    owner_principal = principal - occupant_principal

    occupant_equity_ledger = np.cumsum(occupant_principal, axis=-1)
    owner_equity_ledger = policy.owner_initial_equity_usd + np.cumsum(owner_principal, axis=-1)
    total_equity_ledger = occupant_equity_ledger + owner_equity_ledger
    live_ownership = np.divide(
        occupant_equity_ledger,
        total_equity_ledger,
        out=np.zeros_like(occupant_equity_ledger, dtype="float64"),
        where=total_equity_ledger > 0,
    )
    ownership = _ownership_with_optional_freeze(live_ownership, month_index_array, policy.freeze_ownership_after_month)

    return OccupantContributionResult(
        configured_payment_usd=configured_payment,
        contribution_used_usd=contribution_used,
        unallocated_excess_usd=unallocated_excess,
        contribution_share=contribution_share,
        occupant_interest_usd=occupant_interest,
        occupant_principal_usd=occupant_principal,
        occupant_property_tax_usd=occupant_property_tax,
        occupant_insurance_usd=occupant_insurance,
        occupant_hoa_usd=occupant_hoa,
        occupant_maintenance_usd=occupant_maintenance,
        owner_principal_usd=owner_principal,
        occupant_equity_ledger_usd=occupant_equity_ledger,
        owner_equity_ledger_usd=owner_equity_ledger,
        live_occupant_ownership_pct=live_ownership,
        occupant_ownership_pct=ownership,
    )
