from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from augur.core.scenario_set import (
    AccountType,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    MonthlySpendPolicy,
    Policy,
    Scenario,
    _PolicyBase,
)


@dataclass(frozen=True)
class ActorPolicyProgram:
    actor_id: str
    rules: tuple[Policy, ...]


@dataclass(frozen=True)
class PolicyContext:
    actor_id: str
    month_index: int


@dataclass(frozen=True)
class SellAssetInstructionBatch:
    actor_id: str
    policy_id: str
    asset_type: AssetType
    requested_amount_usd: np.ndarray
    target_cash_floor_usd: float | None = None


@dataclass(frozen=True)
class DebitAccountInstructionBatch:
    actor_id: str
    policy_id: str
    account_type: AccountType
    amount_usd: np.ndarray
    category: str


@dataclass(frozen=True)
class MonthlySpendDecisionBatch:
    debit: DebitAccountInstructionBatch
    inflation_multiplier: np.ndarray


@dataclass(frozen=True)
class GenericSp500SaleApplication:
    current_cash_usd: np.ndarray
    remaining_units: np.ndarray
    remaining_basis_usd: np.ndarray
    sale_usd: np.ndarray
    basis_usd: np.ndarray
    gain_usd: np.ndarray
    shortfall_usd: np.ndarray


@dataclass(frozen=True)
class LedgerEntryBatch:
    actor_id: str
    policy_id: str | None
    domain: str
    amount_usd: np.ndarray
    category: str


@dataclass(frozen=True)
class DebitAccountApplication:
    current_cash_usd: np.ndarray
    debit_usd: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]


def actor_policy_programs(scenario: Scenario) -> tuple[ActorPolicyProgram, ...]:
    return tuple(
        ActorPolicyProgram(
            actor_id=actor.actor_id,
            rules=tuple(policy for policy in scenario.policies if policy.enabled and policy.actor_id == actor.actor_id),
        )
        for actor in scenario.actors
    )


def enabled_rules_of_type[PolicyT: _PolicyBase](
    programs: tuple[ActorPolicyProgram, ...], cls: type[PolicyT]
) -> tuple[PolicyT, ...]:
    return tuple(rule for program in programs for rule in program.rules if isinstance(rule, cls))


def checking_floor_sell_public_stock_instruction(
    policy: CheckingFloorSellPublicStockPolicy, *, current_cash_usd: np.ndarray
) -> SellAssetInstructionBatch:
    requested_sale = np.where(current_cash_usd < policy.floor_usd, float(policy.sale_amount_usd), 0.0)
    return SellAssetInstructionBatch(
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        asset_type=AssetType.GENERIC_SP500_STOCK,
        requested_amount_usd=requested_sale,
        target_cash_floor_usd=float(policy.floor_usd),
    )


def monthly_spend_debit_instruction(
    policy: MonthlySpendPolicy, *, inflation_multiplier: np.ndarray
) -> MonthlySpendDecisionBatch:
    applied_multiplier = (
        inflation_multiplier if policy.inflation_adjusted else np.ones_like(inflation_multiplier, dtype="float64")
    )
    debit = DebitAccountInstructionBatch(
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        account_type=AccountType.CHECKING,
        amount_usd=float(policy.monthly_spend_usd) * applied_multiplier,
        category="monthly_spend",
    )
    return MonthlySpendDecisionBatch(debit=debit, inflation_multiplier=applied_multiplier)


def apply_debit_account_instruction(
    instruction: DebitAccountInstructionBatch, *, current_cash_usd: np.ndarray
) -> DebitAccountApplication:
    if instruction.account_type is not AccountType.CHECKING:
        raise ValueError(f"unsupported account type for cash debit applier: {instruction.account_type}")

    ledger_entry = LedgerEntryBatch(
        actor_id=instruction.actor_id,
        policy_id=instruction.policy_id,
        domain="cash",
        amount_usd=-instruction.amount_usd,
        category=instruction.category,
    )
    return DebitAccountApplication(
        current_cash_usd=current_cash_usd - instruction.amount_usd,
        debit_usd=instruction.amount_usd,
        ledger_entries=(ledger_entry,),
    )


def apply_generic_sp500_sale_instruction(
    instruction: SellAssetInstructionBatch,
    *,
    current_cash_usd: np.ndarray,
    remaining_units: np.ndarray,
    remaining_basis_usd: np.ndarray,
    sp500_unit_price_usd: np.ndarray,
) -> GenericSp500SaleApplication:
    if instruction.asset_type is not AssetType.GENERIC_SP500_STOCK:
        raise ValueError(f"unsupported asset type for SP500 sale applier: {instruction.asset_type}")

    value_usd = remaining_units * sp500_unit_price_usd
    sale_usd = np.minimum(instruction.requested_amount_usd, value_usd)
    basis_usd = np.divide(remaining_basis_usd * sale_usd, value_usd, out=np.zeros_like(sale_usd), where=value_usd > 0)
    sold_units = np.divide(sale_usd, sp500_unit_price_usd, out=np.zeros_like(sale_usd), where=sp500_unit_price_usd > 0)
    cash_after_sale = current_cash_usd + sale_usd
    if instruction.target_cash_floor_usd is None:
        shortfall_usd = np.zeros_like(sale_usd)
    else:
        shortfall_usd = np.maximum(0.0, instruction.target_cash_floor_usd - cash_after_sale)
    return GenericSp500SaleApplication(
        current_cash_usd=cash_after_sale,
        remaining_units=np.maximum(0.0, remaining_units - sold_units),
        remaining_basis_usd=np.maximum(0.0, remaining_basis_usd - basis_usd),
        sale_usd=sale_usd,
        basis_usd=basis_usd,
        gain_usd=sale_usd - basis_usd,
        shortfall_usd=shortfall_usd,
    )
