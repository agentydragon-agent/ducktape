from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from augur.core.scenario_set import (
    AccountType,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    FixedAmountPrivateEquitySaleRule,
    LiquidNetWorthFloorPrivateEquitySaleRule,
    MonthlySpendPolicy,
    PartnerEquityAccrualPolicy,
    Policy,
    PrivateEquitySalePolicy,
    PrivateEquitySaleProceedsDestination,
    Scenario,
    _PolicyBase,
)


@dataclass(frozen=True)
class ActorPolicyProgram:
    actor_id: str
    rules: tuple[Policy, ...]


@dataclass(frozen=True)
class ActorPolicyStep:
    actor_index: int
    rule_index: int
    sequence_index: int
    actor_id: str
    policy: Policy


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
class TransferCashInstructionBatch:
    actor_id: str
    policy_id: str
    recipient_actor_id: str
    amount_usd: np.ndarray
    category: str


@dataclass(frozen=True)
class MonthlySpendDecisionBatch:
    debit: DebitAccountInstructionBatch
    inflation_multiplier: np.ndarray


@dataclass(frozen=True)
class PrivateEquitySaleOpportunityBatch:
    sale_opportunity_mask: np.ndarray
    sale_opportunity_value_usd: np.ndarray
    private_equity_value_before_sale_usd: np.ndarray


@dataclass(frozen=True)
class PrivateEquitySaleInstructionBatch:
    actor_id: str
    policy_id: str
    requested_amount_usd: np.ndarray
    proceeds_destination: AccountType | AssetType


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
    counterparty_actor_id: str | None = None


@dataclass(frozen=True)
class BalanceSnapshotBatch:
    actor_id: str
    policy_id: str | None
    domain: str
    amount_usd: np.ndarray
    category: str
    counterparty_actor_id: str | None = None


@dataclass(frozen=True)
class DebitAccountApplication:
    current_cash_usd: np.ndarray
    debit_usd: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]


@dataclass(frozen=True)
class MortgagePaymentApplication:
    actor_id: str
    policy_id: str
    mortgage_payment_usd: np.ndarray
    mortgage_interest_usd: np.ndarray
    mortgage_principal_usd: np.ndarray
    mortgage_balance_after_usd: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]


@dataclass(frozen=True)
class PropertyOperatingCashFlowApplication:
    actor_id: str
    policy_id: str
    property_tax_usd: np.ndarray
    hoa_usd: np.ndarray
    insurance_usd: np.ndarray
    maintenance_usd: np.ndarray
    rental_gross_income_usd: np.ndarray
    rental_vacancy_loss_usd: np.ndarray
    rental_income_usd: np.ndarray
    rental_management_fee_usd: np.ndarray
    rental_leasing_fee_usd: np.ndarray
    property_carrying_cost_usd: np.ndarray
    net_operating_cash_flow_usd: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]


@dataclass(frozen=True)
class PartnerHouseCostContributionApplication:
    transfer: TransferCashInstructionBatch
    house_costs_usd: np.ndarray
    contribution_used_usd: np.ndarray
    unallocated_excess_usd: np.ndarray
    house_cost_share: np.ndarray
    principal_credit_usd: np.ndarray
    owner_principal_usd: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]


@dataclass(frozen=True)
class PartnerOwnershipAccrualApplication:
    transfer: TransferCashInstructionBatch
    owner_initial_equity_usd: float
    owner_principal_usd: np.ndarray
    partner_principal_credit_usd: np.ndarray
    partner_equity_ledger_usd: np.ndarray
    owner_equity_ledger_usd: np.ndarray
    total_equity_ledger_usd: np.ndarray
    live_ownership_pct: np.ndarray
    ownership_pct: np.ndarray
    home_equity_claim_usd: np.ndarray
    owner_home_equity_claim_usd: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]
    balance_snapshots: tuple[BalanceSnapshotBatch, ...]


@dataclass(frozen=True)
class PrivateEquitySaleApplication:
    sale_usd: np.ndarray
    basis_usd: np.ndarray
    taxable_gain_usd: np.ndarray
    estimated_tax_usd: np.ndarray
    after_tax_proceeds_usd: np.ndarray
    sold_units: np.ndarray
    sold_fraction: np.ndarray
    remaining_units: np.ndarray
    remaining_basis_usd: np.ndarray
    remaining_fraction: np.ndarray
    ledger_entries: tuple[LedgerEntryBatch, ...]


def actor_policy_programs(scenario: Scenario) -> tuple[ActorPolicyProgram, ...]:
    return tuple(
        ActorPolicyProgram(
            actor_id=actor.actor_id,
            rules=tuple(policy for policy in scenario.policies if policy.enabled and policy.actor_id == actor.actor_id),
        )
        for actor in scenario.actors
    )


def actor_policy_steps(programs: tuple[ActorPolicyProgram, ...]) -> tuple[ActorPolicyStep, ...]:
    steps: list[ActorPolicyStep] = []
    sequence_index = 0
    for actor_index, program in enumerate(programs):
        for rule_index, policy in enumerate(program.rules):
            steps.append(
                ActorPolicyStep(
                    actor_index=actor_index,
                    rule_index=rule_index,
                    sequence_index=sequence_index,
                    actor_id=program.actor_id,
                    policy=policy,
                )
            )
            sequence_index += 1
    return tuple(steps)


def enabled_rules_of_type[PolicyT: _PolicyBase](
    programs: tuple[ActorPolicyProgram, ...], cls: type[PolicyT]
) -> tuple[PolicyT, ...]:
    return tuple(rule for program in programs for rule in program.rules if isinstance(rule, cls))


def policy_steps_of_type[PolicyT: _PolicyBase](
    steps: tuple[ActorPolicyStep, ...], cls: type[PolicyT]
) -> tuple[ActorPolicyStep, ...]:
    return tuple(step for step in steps if isinstance(step.policy, cls))


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


def partner_contribution_instruction(
    policy: PartnerEquityAccrualPolicy, *, recipient_actor_id: str, contribution_usd: np.ndarray
) -> TransferCashInstructionBatch:
    return TransferCashInstructionBatch(
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        recipient_actor_id=recipient_actor_id,
        amount_usd=contribution_usd,
        category="partner_contribution",
    )


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


def apply_partner_house_cost_contribution(
    instruction: TransferCashInstructionBatch, *, house_costs_usd: np.ndarray, mortgage_principal_usd: np.ndarray
) -> PartnerHouseCostContributionApplication:
    contribution_used_usd = np.minimum(instruction.amount_usd, house_costs_usd)
    unallocated_excess_usd = np.maximum(0.0, instruction.amount_usd - contribution_used_usd)
    house_cost_share = np.divide(
        contribution_used_usd, house_costs_usd, out=np.zeros_like(contribution_used_usd), where=house_costs_usd > 0
    )
    principal_credit_usd = mortgage_principal_usd * house_cost_share
    owner_principal_usd = np.maximum(0.0, mortgage_principal_usd - principal_credit_usd)
    ledger_entries = (
        LedgerEntryBatch(
            actor_id=instruction.actor_id,
            policy_id=instruction.policy_id,
            domain="cash",
            amount_usd=-instruction.amount_usd,
            category="partner_contribution_transfer",
            counterparty_actor_id=instruction.recipient_actor_id,
        ),
        LedgerEntryBatch(
            actor_id=instruction.recipient_actor_id,
            policy_id=instruction.policy_id,
            domain="cash",
            amount_usd=contribution_used_usd,
            category="partner_contribution_used_for_house_costs",
            counterparty_actor_id=instruction.actor_id,
        ),
        LedgerEntryBatch(
            actor_id=instruction.recipient_actor_id,
            policy_id=instruction.policy_id,
            domain="escrow",
            amount_usd=unallocated_excess_usd,
            category="partner_contribution_unallocated",
            counterparty_actor_id=instruction.actor_id,
        ),
        LedgerEntryBatch(
            actor_id=instruction.actor_id,
            policy_id=instruction.policy_id,
            domain="ownership",
            amount_usd=principal_credit_usd,
            category="partner_principal_credit",
            counterparty_actor_id=instruction.recipient_actor_id,
        ),
    )
    return PartnerHouseCostContributionApplication(
        transfer=instruction,
        house_costs_usd=house_costs_usd,
        contribution_used_usd=contribution_used_usd,
        unallocated_excess_usd=unallocated_excess_usd,
        house_cost_share=house_cost_share,
        principal_credit_usd=principal_credit_usd,
        owner_principal_usd=owner_principal_usd,
        ledger_entries=ledger_entries,
    )


def apply_partner_ownership_accrual(
    transfer: TransferCashInstructionBatch,
    *,
    owner_initial_equity_usd: float,
    home_equity_usd: np.ndarray,
    owner_principal_usd: np.ndarray,
    partner_principal_credit_usd: np.ndarray,
    month_index: np.ndarray,
    freeze_after_month: int | None,
    owner_equity_ledger_usd: np.ndarray | None = None,
    total_partner_equity_ledger_usd: np.ndarray | None = None,
) -> PartnerOwnershipAccrualApplication:
    partner_equity_ledger_usd = np.cumsum(partner_principal_credit_usd, axis=1)
    if owner_equity_ledger_usd is None:
        owner_equity_ledger_usd = float(owner_initial_equity_usd) + np.cumsum(owner_principal_usd, axis=1)
    if total_partner_equity_ledger_usd is None:
        total_partner_equity_ledger_usd = partner_equity_ledger_usd
    total_equity_ledger_usd = total_partner_equity_ledger_usd + owner_equity_ledger_usd
    live_ownership_pct = np.divide(
        partner_equity_ledger_usd,
        total_equity_ledger_usd,
        out=np.zeros_like(partner_equity_ledger_usd),
        where=total_equity_ledger_usd > 0,
    )
    ownership_pct = _freeze_ownership_pct(live_ownership_pct, month_index, freeze_after_month)
    home_equity_claim_usd = np.maximum(home_equity_usd, 0.0) * ownership_pct
    owner_home_equity_claim_usd = home_equity_usd - home_equity_claim_usd
    ledger_entries = (
        LedgerEntryBatch(
            actor_id=transfer.actor_id,
            policy_id=transfer.policy_id,
            domain="ownership",
            amount_usd=partner_principal_credit_usd,
            category="partner_principal_credit",
            counterparty_actor_id=transfer.recipient_actor_id,
        ),
        LedgerEntryBatch(
            actor_id=transfer.recipient_actor_id,
            policy_id=transfer.policy_id,
            domain="ownership",
            amount_usd=owner_principal_usd,
            category="owner_principal_credit",
            counterparty_actor_id=transfer.actor_id,
        ),
    )
    balance_snapshots = (
        BalanceSnapshotBatch(
            actor_id=transfer.actor_id,
            policy_id=transfer.policy_id,
            domain="ownership",
            amount_usd=partner_equity_ledger_usd,
            category="partner_equity_ledger",
            counterparty_actor_id=transfer.recipient_actor_id,
        ),
        BalanceSnapshotBatch(
            actor_id=transfer.recipient_actor_id,
            policy_id=transfer.policy_id,
            domain="ownership",
            amount_usd=owner_equity_ledger_usd,
            category="owner_equity_ledger",
            counterparty_actor_id=transfer.actor_id,
        ),
        BalanceSnapshotBatch(
            actor_id=transfer.actor_id,
            policy_id=transfer.policy_id,
            domain="ownership",
            amount_usd=home_equity_claim_usd,
            category="partner_home_equity_claim",
            counterparty_actor_id=transfer.recipient_actor_id,
        ),
        BalanceSnapshotBatch(
            actor_id=transfer.recipient_actor_id,
            policy_id=transfer.policy_id,
            domain="ownership",
            amount_usd=owner_home_equity_claim_usd,
            category="owner_home_equity_claim",
            counterparty_actor_id=transfer.actor_id,
        ),
    )
    return PartnerOwnershipAccrualApplication(
        transfer=transfer,
        owner_initial_equity_usd=float(owner_initial_equity_usd),
        owner_principal_usd=owner_principal_usd,
        partner_principal_credit_usd=partner_principal_credit_usd,
        partner_equity_ledger_usd=partner_equity_ledger_usd,
        owner_equity_ledger_usd=owner_equity_ledger_usd,
        total_equity_ledger_usd=total_equity_ledger_usd,
        live_ownership_pct=live_ownership_pct,
        ownership_pct=ownership_pct,
        home_equity_claim_usd=home_equity_claim_usd,
        owner_home_equity_claim_usd=owner_home_equity_claim_usd,
        ledger_entries=ledger_entries,
        balance_snapshots=balance_snapshots,
    )


def apply_mortgage_payment(
    *,
    actor_id: str,
    policy_id: str,
    mortgage_payment_usd: np.ndarray,
    mortgage_interest_usd: np.ndarray,
    mortgage_principal_usd: np.ndarray,
    mortgage_balance_after_usd: np.ndarray,
) -> MortgagePaymentApplication:
    ledger_entries = (
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="cash",
            amount_usd=-mortgage_interest_usd,
            category="mortgage_interest",
        ),
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="cash",
            amount_usd=-mortgage_principal_usd,
            category="mortgage_principal",
        ),
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="liability",
            amount_usd=-mortgage_principal_usd,
            category="mortgage_principal",
        ),
    )
    return MortgagePaymentApplication(
        actor_id=actor_id,
        policy_id=policy_id,
        mortgage_payment_usd=mortgage_payment_usd,
        mortgage_interest_usd=mortgage_interest_usd,
        mortgage_principal_usd=mortgage_principal_usd,
        mortgage_balance_after_usd=mortgage_balance_after_usd,
        ledger_entries=ledger_entries,
    )


def apply_property_operating_cash_flows(
    *,
    actor_id: str,
    policy_id: str,
    property_tax_usd: np.ndarray,
    hoa_usd: np.ndarray,
    insurance_usd: np.ndarray,
    maintenance_usd: np.ndarray,
    rental_gross_income_usd: np.ndarray,
    rental_vacancy_loss_usd: np.ndarray,
    rental_income_usd: np.ndarray,
    rental_management_fee_usd: np.ndarray,
    rental_leasing_fee_usd: np.ndarray,
) -> PropertyOperatingCashFlowApplication:
    property_carrying_cost_usd = (
        property_tax_usd
        + hoa_usd
        + insurance_usd
        + maintenance_usd
        + rental_management_fee_usd
        + rental_leasing_fee_usd
    )
    net_operating_cash_flow_usd = rental_income_usd - property_carrying_cost_usd
    ledger_entries = (
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="rental",
            amount_usd=rental_gross_income_usd,
            category="rental_gross_income",
        ),
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="rental",
            amount_usd=-rental_vacancy_loss_usd,
            category="rental_vacancy_loss",
        ),
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="cash",
            amount_usd=rental_income_usd,
            category="rental_income",
        ),
        LedgerEntryBatch(
            actor_id=actor_id, policy_id=policy_id, domain="cash", amount_usd=-property_tax_usd, category="property_tax"
        ),
        LedgerEntryBatch(actor_id=actor_id, policy_id=policy_id, domain="cash", amount_usd=-hoa_usd, category="hoa"),
        LedgerEntryBatch(
            actor_id=actor_id, policy_id=policy_id, domain="cash", amount_usd=-insurance_usd, category="insurance"
        ),
        LedgerEntryBatch(
            actor_id=actor_id, policy_id=policy_id, domain="cash", amount_usd=-maintenance_usd, category="maintenance"
        ),
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="cash",
            amount_usd=-rental_management_fee_usd,
            category="rental_management_fee",
        ),
        LedgerEntryBatch(
            actor_id=actor_id,
            policy_id=policy_id,
            domain="cash",
            amount_usd=-rental_leasing_fee_usd,
            category="rental_leasing_fee",
        ),
    )
    return PropertyOperatingCashFlowApplication(
        actor_id=actor_id,
        policy_id=policy_id,
        property_tax_usd=property_tax_usd,
        hoa_usd=hoa_usd,
        insurance_usd=insurance_usd,
        maintenance_usd=maintenance_usd,
        rental_gross_income_usd=rental_gross_income_usd,
        rental_vacancy_loss_usd=rental_vacancy_loss_usd,
        rental_income_usd=rental_income_usd,
        rental_management_fee_usd=rental_management_fee_usd,
        rental_leasing_fee_usd=rental_leasing_fee_usd,
        property_carrying_cost_usd=property_carrying_cost_usd,
        net_operating_cash_flow_usd=net_operating_cash_flow_usd,
        ledger_entries=ledger_entries,
    )


def private_equity_sale_opportunity(
    *, sale_opportunity_mask: np.ndarray, private_equity_value_before_sale_usd: np.ndarray
) -> PrivateEquitySaleOpportunityBatch:
    return PrivateEquitySaleOpportunityBatch(
        sale_opportunity_mask=sale_opportunity_mask,
        sale_opportunity_value_usd=np.where(sale_opportunity_mask, private_equity_value_before_sale_usd, 0.0),
        private_equity_value_before_sale_usd=private_equity_value_before_sale_usd,
    )


def private_equity_sale_instruction(
    policy: PrivateEquitySalePolicy, *, opportunity: PrivateEquitySaleOpportunityBatch, liquid_net_worth_usd: np.ndarray
) -> PrivateEquitySaleInstructionBatch:
    if liquid_net_worth_usd.shape != opportunity.sale_opportunity_mask.shape:
        raise ValueError("liquid_net_worth_usd must match private equity opportunity rollout shape")
    if isinstance(policy.sale_rule, FixedAmountPrivateEquitySaleRule):
        requested_amount = np.where(opportunity.sale_opportunity_mask, float(policy.sale_rule.amount_usd), 0.0)
    elif isinstance(policy.sale_rule, LiquidNetWorthFloorPrivateEquitySaleRule):
        requested_amount = np.where(
            opportunity.sale_opportunity_mask
            & (liquid_net_worth_usd < float(policy.sale_rule.min_liquid_net_worth_usd)),
            float(policy.sale_rule.sale_amount_usd),
            0.0,
        )
    else:
        raise TypeError(f"unsupported private equity sale rule: {policy.sale_rule!r}")

    return PrivateEquitySaleInstructionBatch(
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        requested_amount_usd=requested_amount,
        proceeds_destination=private_equity_sale_proceeds_destination(policy),
    )


def private_equity_sale_proceeds_destination(policy: PrivateEquitySalePolicy) -> AccountType | AssetType:
    if policy.proceeds_destination is PrivateEquitySaleProceedsDestination.GENERIC_SP500_STOCK:
        return AssetType.GENERIC_SP500_STOCK
    return AccountType.CHECKING


def apply_private_equity_sale_instruction(
    instruction: PrivateEquitySaleInstructionBatch,
    *,
    opportunity: PrivateEquitySaleOpportunityBatch,
    remaining_basis_usd: np.ndarray,
    remaining_units: np.ndarray,
    remaining_fraction: np.ndarray,
    cap_gains_rate_pct: float,
) -> PrivateEquitySaleApplication:
    sale_usd = np.minimum(instruction.requested_amount_usd, opportunity.sale_opportunity_value_usd)
    sold_fraction = np.divide(
        sale_usd,
        opportunity.private_equity_value_before_sale_usd,
        out=np.zeros_like(sale_usd),
        where=opportunity.private_equity_value_before_sale_usd > 0,
    )
    basis_usd = remaining_basis_usd * sold_fraction
    taxable_gain_usd = np.maximum(0.0, sale_usd - basis_usd)
    estimated_tax_usd = taxable_gain_usd * cap_gains_rate_pct / 100
    after_tax_proceeds_usd = np.maximum(0.0, sale_usd - estimated_tax_usd)
    sold_units = remaining_units * sold_fraction
    destination_domain = "asset" if instruction.proceeds_destination is AssetType.GENERIC_SP500_STOCK else "cash"
    ledger_entries = (
        LedgerEntryBatch(
            actor_id=instruction.actor_id,
            policy_id=instruction.policy_id,
            domain="asset",
            amount_usd=-sale_usd,
            category="private_equity_sale",
        ),
        LedgerEntryBatch(
            actor_id=instruction.actor_id,
            policy_id=instruction.policy_id,
            domain="tax",
            amount_usd=-estimated_tax_usd,
            category="private_equity_capital_gains_tax",
        ),
        LedgerEntryBatch(
            actor_id=instruction.actor_id,
            policy_id=instruction.policy_id,
            domain=destination_domain,
            amount_usd=after_tax_proceeds_usd,
            category="private_equity_after_tax_proceeds",
        ),
    )
    return PrivateEquitySaleApplication(
        sale_usd=sale_usd,
        basis_usd=basis_usd,
        taxable_gain_usd=taxable_gain_usd,
        estimated_tax_usd=estimated_tax_usd,
        after_tax_proceeds_usd=after_tax_proceeds_usd,
        sold_units=sold_units,
        sold_fraction=sold_fraction,
        remaining_units=np.maximum(0.0, remaining_units - sold_units),
        remaining_basis_usd=np.maximum(0.0, remaining_basis_usd - basis_usd),
        remaining_fraction=np.maximum(0.0, remaining_fraction * (1 - sold_fraction)),
        ledger_entries=ledger_entries,
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


def _freeze_ownership_pct(
    live_ownership_pct: np.ndarray, month_index: np.ndarray, freeze_after_month: int | None
) -> np.ndarray:
    if freeze_after_month is None:
        return live_ownership_pct
    month_matrix = (
        np.broadcast_to(month_index[None, :], live_ownership_pct.shape) if month_index.ndim == 1 else month_index
    )
    freeze_mask = month_matrix == freeze_after_month
    has_freeze_month = np.any(freeze_mask, axis=1, keepdims=True)
    freeze_positions = np.argmax(freeze_mask, axis=1)
    frozen_pct = np.take_along_axis(live_ownership_pct, freeze_positions[:, None], axis=1)
    should_freeze = (month_matrix >= freeze_after_month) & has_freeze_month
    return np.where(should_freeze, frozen_pct, live_ownership_pct)
