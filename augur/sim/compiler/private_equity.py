"""Private-equity tender-policy compile output. Per-issuer + per-policy arrays that
drive the engine's `_apply_pe_tenders` phase: at each tender event the policy's
liquid-net-worth floor governs whether (and how much) of the issuer's lots gets sold."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl
from numpy.typing import NDArray

from augur.model.series import (
    PrivateEquityEventKindCode,
    PrivateEquityRegimeCode,
    issuer_id_from_private_equity_mark_wire_id,
    private_equity_eligible_fraction_series_id,
    private_equity_event_kind_code_series_id,
    private_equity_forced_recovery_cashout_usd_series_id,
    private_equity_forced_sale_fraction_series_id,
    private_equity_level_series_ids,
    private_equity_liquidity_blocked_series_id,
    private_equity_regime_code_series_id,
    private_equity_sale_capacity_fraction_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
)
from augur.sim.compiler.helpers import AMOUNT_FIXED, NO_CODE, StringTable, amount_arrays
from augur.sim.scenario import Scenario

_PRIVATE_EQUITY_REGIME_CODES = frozenset(int(code) for code in PrivateEquityRegimeCode)
_PRIVATE_EQUITY_EVENT_KIND_CODES = frozenset(int(code) for code in PrivateEquityEventKindCode)


@dataclass(frozen=True)
class PEIssuerCompileOutput:
    """Per-issuer arrays (one row per distinct `private_equity:<issuer>` asset). An issuer
    is `policy_index = NO_CODE` if no PrivateEquityTenderPolicy applies (issuer never
    tenders within horizon); the engine skips it. `lot_mask[i, l]` flags which lots
    belong to issuer `i`."""

    codes: NDArray[np.int64]
    issuer_ids: tuple[str, ...]
    event_series: NDArray[np.int64]
    level_series: NDArray[np.int64]
    regime_code_series: NDArray[np.int64]
    event_kind_code_series: NDArray[np.int64]
    sale_capacity_fraction_series: NDArray[np.int64]
    eligible_fraction_series: NDArray[np.int64]
    forced_sale_fraction_series: NDArray[np.int64]
    liquidity_blocked_series: NDArray[np.int64]
    forced_recovery_cashout_usd_series: NDArray[np.int64]
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


def compile_private_equity_tenders(
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
        lot_issuer = issuer_id_from_private_equity_mark_wire_id(lot.asset_id)
        if lot_issuer is not None:
            issuer_to_lots.setdefault(str(lot_issuer), []).append(lot_index)
    issuer_ids = tuple(sorted(issuer_to_lots))

    policies = scenario.private_equity_tender_policies
    policy_count = max(1, len(policies))
    lot_count = lot_agent_codes.shape[0]
    cash_count = cash_agent_codes.shape[0]
    issuer_count = max(1, len(issuer_ids))

    pe_issuer_codes = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_event_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_level_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_regime_code_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_event_kind_code_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_sale_capacity_fraction_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_eligible_fraction_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_forced_sale_fraction_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_liquidity_blocked_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
    pe_issuer_forced_recovery_cashout_usd_series_index = np.full(issuer_count, NO_CODE, dtype=np.int64)
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
        issuer_ids=issuer_ids,
        event_series=pe_issuer_event_series_index,
        level_series=pe_issuer_level_series_index,
        regime_code_series=pe_issuer_regime_code_series_index,
        event_kind_code_series=pe_issuer_event_kind_code_series_index,
        sale_capacity_fraction_series=pe_issuer_sale_capacity_fraction_series_index,
        eligible_fraction_series=pe_issuer_eligible_fraction_series_index,
        forced_sale_fraction_series=pe_issuer_forced_sale_fraction_series_index,
        liquidity_blocked_series=pe_issuer_liquidity_blocked_series_index,
        forced_recovery_cashout_usd_series=pe_issuer_forced_recovery_cashout_usd_series_index,
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
            pe_codes = {strings.require(private_equity_series_id(issuer)) for issuer in issuer_to_lots}
            non_pe_lot = ~np.isin(lot_asset_codes, list(pe_codes)) if pe_codes else np.ones(lot_count, dtype=np.bool_)
            pe_policy_owner_non_pe_lot_mask[policy_idx, :lot_count] = owner_lots & non_pe_lot

    # Per-issuer arrays.
    policy_index_by_owner = {int(pe_policy_owner_agent_codes[idx]): idx for idx in range(len(policies))}
    for issuer_idx, issuer in enumerate(issuer_ids):
        pe_issuer_codes[issuer_idx] = strings.require(issuer)
        level_series_id = private_equity_series_id(issuer)
        event_series_id = private_equity_sale_event_id(issuer)
        missing_level_series = sorted(private_equity_level_series_ids(issuer) - set(series_index_by_id))
        missing_event_series = sorted({event_series_id} - set(event_index_by_id))
        if missing_level_series or missing_event_series:
            details: list[str] = []
            if missing_level_series:
                details.append(f"missing level series {missing_level_series}")
            if missing_event_series:
                details.append(f"missing event series {missing_event_series}")
            raise ValueError(
                f"private-equity issuer {issuer!r} requires complete protocol series: {'; '.join(details)}"
            )

        pe_issuer_level_series_index[issuer_idx] = series_index_by_id[level_series_id]
        pe_issuer_event_series_index[issuer_idx] = event_index_by_id[event_series_id]
        control_level_series = (
            (private_equity_regime_code_series_id(issuer), pe_issuer_regime_code_series_index),
            (private_equity_event_kind_code_series_id(issuer), pe_issuer_event_kind_code_series_index),
            (private_equity_sale_capacity_fraction_series_id(issuer), pe_issuer_sale_capacity_fraction_series_index),
            (private_equity_eligible_fraction_series_id(issuer), pe_issuer_eligible_fraction_series_index),
            (private_equity_forced_sale_fraction_series_id(issuer), pe_issuer_forced_sale_fraction_series_index),
            (private_equity_liquidity_blocked_series_id(issuer), pe_issuer_liquidity_blocked_series_index),
            (
                private_equity_forced_recovery_cashout_usd_series_id(issuer),
                pe_issuer_forced_recovery_cashout_usd_series_index,
            ),
        )
        for series_id, target in control_level_series:
            target[issuer_idx] = series_index_by_id[series_id]
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


def compile_private_equity_protocol_codes(
    issuers: PEIssuerCompileOutput, *, private_equity_protocol: pl.DataFrame, rollout_count: int, horizon_months: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Materialize PE protocol code arrays from the typed protocol frame."""

    issuer_count = issuers.codes.shape[0]
    snapshot_months = horizon_months + 1
    regime_codes = np.full((issuer_count, rollout_count, snapshot_months), NO_CODE, dtype=np.int64)
    event_kind_codes = np.full(
        (issuer_count, rollout_count, snapshot_months), int(PrivateEquityEventKindCode.NONE), dtype=np.int64
    )
    for issuer_idx, issuer_code in enumerate(issuers.codes):
        if int(issuer_code) < 0:
            continue
        issuer_id = issuers.issuer_ids[issuer_idx]
        regime_codes[issuer_idx] = _compile_protocol_code_matrix(
            private_equity_protocol,
            issuer_id=issuer_id,
            value_column="regime_code",
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            label=f"private-equity protocol regime code for issuer {issuer_id!r}",
            allowed_values=_PRIVATE_EQUITY_REGIME_CODES,
        )
        event_kind_codes[issuer_idx] = _compile_protocol_code_matrix(
            private_equity_protocol,
            issuer_id=issuer_id,
            value_column="event_kind_code",
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            label=f"private-equity protocol event-kind code for issuer {issuer_id!r}",
            allowed_values=_PRIVATE_EQUITY_EVENT_KIND_CODES,
        )
    return regime_codes, event_kind_codes


def _compile_protocol_code_matrix(
    protocol: pl.DataFrame,
    *,
    issuer_id: str,
    value_column: str,
    rollout_count: int,
    horizon_months: int,
    label: str,
    allowed_values: frozenset[int],
) -> npt.NDArray[np.int64]:
    selected = protocol.filter(pl.col("issuer_id") == issuer_id).sort(["rollout_index", "month_index"])
    if selected.is_empty():
        raise ValueError(f"private-equity issuer {issuer_id!r} requires typed protocol rows")

    expected_rows = rollout_count * (horizon_months + 1)
    if selected.height != expected_rows:
        raise ValueError(f"{label} has {selected.height} rows; expected {expected_rows}")

    expected_rollouts = np.repeat(np.arange(rollout_count, dtype=np.int64), horizon_months + 1)
    expected_months = np.tile(np.arange(horizon_months + 1, dtype=np.int64), rollout_count)
    actual_rollouts = selected.get_column("rollout_index").to_numpy()
    actual_months = selected.get_column("month_index").to_numpy()
    if not np.array_equal(actual_rollouts, expected_rollouts) or not np.array_equal(actual_months, expected_months):
        raise ValueError(f"{label} does not cover every rollout/month exactly once")

    codes = selected.get_column(value_column).to_numpy().astype(np.int64).reshape((rollout_count, horizon_months + 1))
    unknown = sorted(int(code) for code in np.unique(codes) if int(code) not in allowed_values)
    if unknown:
        raise ValueError(f"{label} produced unknown code(s): {unknown}")
    typed_codes: npt.NDArray[np.int64] = codes
    return typed_codes
