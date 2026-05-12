from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from augur.core.augur_accounting import MONTHS_PER_YEAR
from augur.core.ownership import (
    MonthlyHouseUseComponents,
    OccupantContributionBuildsEquityPolicy,
    OccupantContributionResult,
    apply_occupant_contribution_builds_equity_policy,
)
from augur.core.schemas import PropertyRequest, ScenarioKnobs
from augur.core.vectorized import (
    MarketPathMatrix,
    VectorizedSimulation,
    deterministic_market_paths,
    simulate_property_vectorized,
)


@dataclass(frozen=True)
class RealEstateCaseResult:
    simulation: VectorizedSimulation
    ownership: OccupantContributionResult | None
    owner_actor: str
    occupant_actor: str | None
    owner_ownership_pct: np.ndarray
    occupant_ownership_pct: np.ndarray
    owner_sale_claim_usd: np.ndarray
    occupant_sale_claim_usd: np.ndarray


def _policy_with_owner_initial_equity(
    policy: OccupantContributionBuildsEquityPolicy, owner_initial_equity_usd: float
) -> OccupantContributionBuildsEquityPolicy:
    if policy.owner_initial_equity_usd != 0:
        return policy
    return replace(policy, owner_initial_equity_usd=owner_initial_equity_usd)


def house_use_components_from_rollout_arrays(simulation: VectorizedSimulation) -> MonthlyHouseUseComponents:
    return MonthlyHouseUseComponents(
        mortgage_interest_usd=simulation.mortgage_interest_usd[:, 1:],
        mortgage_principal_usd=simulation.mortgage_principal_usd[:, 1:],
        property_tax_usd=simulation.property_tax_usd[:, 1:],
        insurance_usd=simulation.insurance_usd[:, 1:],
        hoa_usd=simulation.hoa_usd[:, 1:],
        maintenance_usd=simulation.maintenance_usd[:, 1:],
    )


def simulate_real_estate_case(
    property_: PropertyRequest,
    knobs: ScenarioKnobs,
    market_paths: MarketPathMatrix | None = None,
    *,
    rollout_count: int = 1,
    ownership_policy: OccupantContributionBuildsEquityPolicy | None = None,
) -> RealEstateCaseResult:
    if market_paths is None:
        market_paths = deterministic_market_paths(
            knobs, hold_months=int(knobs.hold_years) * MONTHS_PER_YEAR, rollout_count=rollout_count
        )
    simulation = simulate_property_vectorized(property_, knobs, market_paths)
    if ownership_policy is None:
        owner_claim = simulation.sale_net_proceeds_usd[:, -1]
        occupant_claim = np.zeros_like(owner_claim)
        owner_pct = np.ones_like(owner_claim)
        occupant_pct = np.zeros_like(owner_claim)
        return RealEstateCaseResult(
            simulation=simulation,
            ownership=None,
            owner_actor="rai",
            occupant_actor=None,
            owner_ownership_pct=owner_pct,
            occupant_ownership_pct=occupant_pct,
            owner_sale_claim_usd=owner_claim,
            occupant_sale_claim_usd=occupant_claim,
        )

    policy = _policy_with_owner_initial_equity(ownership_policy, simulation.down_payment_usd)
    ownership = apply_occupant_contribution_builds_equity_policy(
        house_use_components_from_rollout_arrays(simulation), policy
    )
    occupant_pct = ownership.occupant_ownership_pct[:, -1]
    occupant_claim = simulation.sale_net_proceeds_usd[:, -1] * occupant_pct
    owner_claim = simulation.sale_net_proceeds_usd[:, -1] - occupant_claim
    return RealEstateCaseResult(
        simulation=simulation,
        ownership=ownership,
        owner_actor=policy.owner_actor,
        occupant_actor=policy.occupant_actor,
        owner_ownership_pct=1 - occupant_pct,
        occupant_ownership_pct=occupant_pct,
        owner_sale_claim_usd=owner_claim,
        occupant_sale_claim_usd=occupant_claim,
    )
