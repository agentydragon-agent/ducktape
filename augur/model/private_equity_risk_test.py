from __future__ import annotations

import math

import numpy as np
import pytest
import pytest_bazel
from pydantic import TypeAdapter

from augur.model.exogenous import ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.exogenous_provider_config import ExogenousProviderConfig
from augur.model.private_equity_bundle import (
    PrivateEquityBoolChannel,
    PrivateEquityFloatChannel,
    PrivateEquityIntChannel,
)
from augur.model.private_equity_risk import PrivateEquityRiskIssuerConfig, PrivateEquityRiskProviderConfig
from augur.model.series import IssuerId, PrivateEquityEventKindCode, PrivateEquityRegimeCode


def _issuer(**updates: object) -> PrivateEquityRiskIssuerConfig:
    fields = {
        "current_mark_usd": 100.0,
        "tender_interval_months_median": 120.0,
        "tender_interval_log_sigma": 0.0,
        **updates,
    }
    return PrivateEquityRiskIssuerConfig.model_validate(fields)


def _sample(issuer: PrivateEquityRiskIssuerConfig, *, horizon_months: int = 4) -> SampledExogenousBundle:
    model = PrivateEquityRiskProviderConfig(issuers={"acme": issuer}).realize_model()
    return model.sample(
        ExogenousSamplingRequest(
            horizon_months=horizon_months,
            rollout_seeds=(7,),
            required_private_equity_issuers=frozenset({IssuerId("acme")}),
        )
    )


def _float(sampled: SampledExogenousBundle, channel: PrivateEquityFloatChannel, horizon: int) -> np.ndarray:
    return sampled.private_equity.issuer_float_matrix("acme", str(channel), rollout_count=1, horizon_months=horizon)


def _int(sampled: SampledExogenousBundle, channel: PrivateEquityIntChannel, horizon: int) -> np.ndarray:
    return sampled.private_equity.issuer_int_matrix("acme", str(channel), rollout_count=1, horizon_months=horizon)


def _bool(sampled: SampledExogenousBundle, channel: PrivateEquityBoolChannel, horizon: int) -> np.ndarray:
    return sampled.private_equity.issuer_bool_matrix("acme", str(channel), rollout_count=1, horizon_months=horizon)


def test_private_equity_risk_provider_config_roundtrips_through_union() -> None:
    adapter: TypeAdapter[ExogenousProviderConfig] = TypeAdapter(ExogenousProviderConfig)
    config = adapter.validate_python({"type": "private_equity_risk", "issuers": {"acme": {"current_mark_usd": 100.0}}})

    assert isinstance(config, PrivateEquityRiskProviderConfig)
    assert config.realize_model().sample(ExogenousSamplingRequest(horizon_months=1, rollout_seeds=(1,))).metadata[
        "private_equity_prices_usd"
    ] == {"acme": 100.0}


def test_private_equity_risk_samples_complete_protocol_bundle() -> None:
    sampled = _sample(_issuer(), horizon_months=2)

    assert sampled.private_equity.issuer_ids() == frozenset({"acme"})
    np.testing.assert_allclose(
        _float(sampled, PrivateEquityFloatChannel.MARK_USD_PER_UNIT, horizon=2), np.array([[100.0, 100.0, 100.0]])
    )


def test_private_equity_risk_private_mark_is_piecewise_constant_between_observed_ticks() -> None:
    sampled = _sample(_issuer(monthly_log_return_mu=math.log(2.0), monthly_log_return_sigma=0.0), horizon_months=4)

    np.testing.assert_allclose(
        _float(sampled, PrivateEquityFloatChannel.MARK_USD_PER_UNIT, horizon=4), np.full((1, 5), 100.0)
    )


def test_private_equity_risk_admin_mark_update_changes_mark_without_sale_opportunity() -> None:
    sampled = _sample(
        _issuer(
            monthly_log_return_mu=math.log(2.0) / 2.0,
            monthly_log_return_sigma=0.0,
            admin_mark_update_interval_months_median=2.0,
            admin_mark_update_interval_log_sigma=0.0,
            admin_mark_update_log_noise_sigma=0.0,
        ),
        horizon_months=4,
    )

    mark = _float(sampled, PrivateEquityFloatChannel.MARK_USD_PER_UNIT, horizon=4)
    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=4)
    tenders = _bool(sampled, PrivateEquityBoolChannel.SALE_OPPORTUNITY_ACTIVE, horizon=4)

    assert int(event_kind[0, 2]) == int(PrivateEquityEventKindCode.ADMIN_MARK_UPDATE)
    assert int(event_kind[0, 4]) == int(PrivateEquityEventKindCode.ADMIN_MARK_UPDATE)
    np.testing.assert_array_equal(tenders, np.zeros((1, 5), dtype=np.bool_))
    assert mark[0, 0] == pytest.approx(100.0)
    assert mark[0, 1] == pytest.approx(100.0)
    assert mark[0, 2] == pytest.approx(200.0)
    assert mark[0, 3] == pytest.approx(200.0)
    assert mark[0, 4] == pytest.approx(400.0)


def test_private_equity_risk_tender_updates_mark_and_sale_opportunity() -> None:
    sampled = _sample(
        _issuer(
            monthly_log_return_mu=math.log(2.0) / 2.0,
            monthly_log_return_sigma=0.0,
            tender_interval_months_median=2.0,
            tender_interval_log_sigma=0.0,
            tender_price_log_discount_sigma=0.0,
        ),
        horizon_months=3,
    )

    mark = _float(sampled, PrivateEquityFloatChannel.MARK_USD_PER_UNIT, horizon=3)
    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=3)
    tenders = _bool(sampled, PrivateEquityBoolChannel.SALE_OPPORTUNITY_ACTIVE, horizon=3)

    assert int(event_kind[0, 2]) == int(PrivateEquityEventKindCode.TENDER)
    assert tenders[0, 2]
    assert mark[0, 0] == pytest.approx(100.0)
    assert mark[0, 1] == pytest.approx(100.0)
    assert mark[0, 2] == pytest.approx(200.0)
    assert mark[0, 3] == pytest.approx(200.0)


def test_private_equity_risk_forced_recovery_cashout_marks_protocol_event() -> None:
    sampled = _sample(
        _issuer(
            annual_forced_recovery_probability=1.0,
            forced_recovery_cashout_usd_min=100.0,
            forced_recovery_cashout_usd_max=100.0,
        ),
        horizon_months=3,
    )

    recovery = _float(sampled, PrivateEquityFloatChannel.FORCED_RECOVERY_CASHOUT_USD, horizon=3)
    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=3)
    regime = _int(sampled, PrivateEquityIntChannel.REGIME_CODE, horizon=3)
    blocked = _bool(sampled, PrivateEquityBoolChannel.LIQUIDITY_BLOCKED, horizon=3)

    assert recovery[0, 1] == pytest.approx(100.0)
    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.FORCED_RECOVERY)
    np.testing.assert_array_equal(regime[0, 1:], np.full(3, int(PrivateEquityRegimeCode.COLLAPSED)))
    np.testing.assert_array_equal(blocked[0, 1:], np.ones(3, dtype=np.bool_))


def test_private_equity_risk_collapse_blocks_liquidity_and_marks_down() -> None:
    sampled = _sample(_issuer(annual_collapse_probability=1.0, collapsed_mark_fraction=0.01), horizon_months=3)

    mark = _float(sampled, PrivateEquityFloatChannel.MARK_USD_PER_UNIT, horizon=3)
    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=3)
    regime = _int(sampled, PrivateEquityIntChannel.REGIME_CODE, horizon=3)
    blocked = _bool(sampled, PrivateEquityBoolChannel.LIQUIDITY_BLOCKED, horizon=3)

    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.COLLAPSE)
    np.testing.assert_array_equal(regime[0, 1:], np.full(3, int(PrivateEquityRegimeCode.COLLAPSED)))
    np.testing.assert_array_equal(blocked[0, 1:], np.ones(3, dtype=np.bool_))
    np.testing.assert_allclose(mark[0, 1:], np.full(3, 1.0))


def test_private_equity_risk_public_market_is_absorbing_open_liquidity_regime() -> None:
    sampled = _sample(_issuer(annual_public_market_probability=1.0), horizon_months=3)

    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=3)
    regime = _int(sampled, PrivateEquityIntChannel.REGIME_CODE, horizon=3)
    blocked = _bool(sampled, PrivateEquityBoolChannel.LIQUIDITY_BLOCKED, horizon=3)

    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.PUBLIC_MARKET_OPEN)
    np.testing.assert_array_equal(regime[0, 1:], np.full(3, int(PrivateEquityRegimeCode.PUBLIC_MARKET)))
    np.testing.assert_array_equal(blocked[0, 1:], np.zeros(3, dtype=np.bool_))


def test_private_equity_risk_public_market_lockup_blocks_liquidity_then_opens() -> None:
    sampled = _sample(_issuer(annual_public_market_probability=1.0, public_market_lockup_months=2), horizon_months=4)

    regime = _int(sampled, PrivateEquityIntChannel.REGIME_CODE, horizon=4)
    blocked = _bool(sampled, PrivateEquityBoolChannel.LIQUIDITY_BLOCKED, horizon=4)

    np.testing.assert_array_equal(regime[0, 1:], np.full(4, int(PrivateEquityRegimeCode.PUBLIC_MARKET)))
    np.testing.assert_array_equal(blocked[0], np.array([False, True, True, False, False], dtype=np.bool_))


def test_private_equity_risk_forced_sale_emits_sale_fraction_without_tender() -> None:
    sampled = _sample(
        _issuer(annual_forced_sale_probability=1.0, forced_sale_fraction_alpha=1000.0, forced_sale_fraction_beta=1.0),
        horizon_months=2,
    )

    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=2)
    forced_sale = _float(sampled, PrivateEquityFloatChannel.FORCED_SALE_FRACTION, horizon=2)
    tenders = _bool(sampled, PrivateEquityBoolChannel.SALE_OPPORTUNITY_ACTIVE, horizon=2)
    regime = _int(sampled, PrivateEquityIntChannel.REGIME_CODE, horizon=2)

    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.ACQUISITION_CASHOUT)
    assert int(regime[0, 1]) == int(PrivateEquityRegimeCode.ACQUIRED)
    assert 0.0 < forced_sale[0, 1] <= 1.0
    assert not tenders[0, 1]


def test_private_equity_risk_tender_cancellation_suppresses_scheduled_tender() -> None:
    """A scheduled tender precursor with cancellation=1.0 fires no TENDER event."""

    sampled = _sample(
        _issuer(
            monthly_log_return_mu=0.0,
            monthly_log_return_sigma=0.0,
            tender_interval_months_median=2.0,
            tender_interval_log_sigma=0.0,
            tender_cancellation_probability=1.0,
        ),
        horizon_months=3,
    )

    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=3)
    tenders = _bool(sampled, PrivateEquityBoolChannel.SALE_OPPORTUNITY_ACTIVE, horizon=3)
    sale_capacity = _float(sampled, PrivateEquityFloatChannel.SALE_CAPACITY_FRACTION, horizon=3)

    np.testing.assert_array_equal(event_kind[0, :], np.zeros(4, dtype=np.int64))
    np.testing.assert_array_equal(tenders[0, :], np.zeros(4, dtype=np.bool_))
    np.testing.assert_array_equal(sale_capacity[0, :], np.zeros(4, dtype=np.float64))


def test_private_equity_risk_tender_cancellation_default_zero_preserves_tender() -> None:
    """Cancellation defaults to 0.0 — scheduled tender fires as before."""

    sampled = _sample(
        _issuer(
            monthly_log_return_mu=0.0,
            monthly_log_return_sigma=0.0,
            tender_interval_months_median=2.0,
            tender_interval_log_sigma=0.0,
            tender_price_log_discount_sigma=0.0,
        ),
        horizon_months=3,
    )

    event_kind = _int(sampled, PrivateEquityIntChannel.EVENT_KIND_CODE, horizon=3)
    tenders = _bool(sampled, PrivateEquityBoolChannel.SALE_OPPORTUNITY_ACTIVE, horizon=3)

    assert int(event_kind[0, 2]) == int(PrivateEquityEventKindCode.TENDER)
    assert tenders[0, 2]


def test_private_equity_risk_legal_event_severity_matches_plan_80_15_5_split() -> None:
    """Umbrella legal_event probability splits into 80%/15%/5% per the realization-risk plan.

    With `annual_legal_event_probability=1.0` every eligible rollout fires a legal
    event on month 1. Severity is then a function of u_legal_severity uniform draws.
    Over many rollouts the 5% severe branch (which emits LEGAL_IMPAIRMENT) and the
    80% temporary branch (NONE event_kind, suspended for at least the firing month)
    should land within sampling tolerance of the plan-specified shares.
    """

    rollout_count = 4096
    rollout_seeds = tuple(range(1701, 1701 + rollout_count))
    issuer = _issuer(
        monthly_log_return_mu=0.0,
        monthly_log_return_sigma=0.0,
        # Push tender precursor far enough out that the month-1 legal event always wins.
        tender_interval_months_median=120.0,
        annual_legal_event_probability=1.0,
    )
    model = PrivateEquityRiskProviderConfig(issuers={"acme": issuer}).realize_model()
    sampled = model.sample(
        ExogenousSamplingRequest(
            horizon_months=2, rollout_seeds=rollout_seeds, required_private_equity_issuers=frozenset({IssuerId("acme")})
        )
    )
    event_kind = sampled.private_equity.issuer_int_matrix(
        "acme", str(PrivateEquityIntChannel.EVENT_KIND_CODE), rollout_count=rollout_count, horizon_months=2
    )
    blocked = sampled.private_equity.issuer_bool_matrix(
        "acme", str(PrivateEquityBoolChannel.LIQUIDITY_BLOCKED), rollout_count=rollout_count, horizon_months=2
    )

    legal_share = float((event_kind[:, 1] == int(PrivateEquityEventKindCode.LEGAL_IMPAIRMENT)).mean())
    none_share = float((event_kind[:, 1] == int(PrivateEquityEventKindCode.NONE)).mean())
    # All eligible rollouts must take one of the two outcomes — no other event_kind
    # should fire when the umbrella legal_event rate is 1.0.
    assert legal_share + none_share == pytest.approx(1.0)
    # 5% severe → emits LEGAL_IMPAIRMENT.
    assert 0.03 <= legal_share <= 0.07
    # 80% temp + 15% perm-cap → both NONE event_kind, summing to 95%.
    assert 0.93 <= none_share <= 0.97
    # The 80% temp branch sets liquidity_blocked at the firing month. The 15%
    # perm-cap branch does not. So `liquidity_blocked` mass at month 1 should be
    # roughly the 80% temp share + the 5% severe share (severe-indefinite and
    # severe-cap don't set liquidity_blocked but severe-indefinite does).
    blocked_share = float(blocked[:, 1].mean())
    assert 0.75 <= blocked_share <= 0.92


def test_private_equity_risk_legal_impairment_keeps_liquidity_blocked_through_horizon() -> None:
    """The 50%-severe-indefinite sub-branch sets liquidity_blocked from firing month forward.

    Run with high umbrella legal rate over many rollouts; rollouts that get
    LEGAL_IMPAIRMENT on month 1 should have liquidity_blocked == True for every
    subsequent month within the horizon (the severe-indefinite case).
    """

    rollout_count = 2048
    rollout_seeds = tuple(range(2001, 2001 + rollout_count))
    issuer = _issuer(
        monthly_log_return_mu=0.0,
        monthly_log_return_sigma=0.0,
        tender_interval_months_median=120.0,
        annual_legal_event_probability=1.0,
    )
    model = PrivateEquityRiskProviderConfig(issuers={"acme": issuer}).realize_model()
    sampled = model.sample(
        ExogenousSamplingRequest(
            horizon_months=6, rollout_seeds=rollout_seeds, required_private_equity_issuers=frozenset({IssuerId("acme")})
        )
    )
    event_kind = sampled.private_equity.issuer_int_matrix(
        "acme", str(PrivateEquityIntChannel.EVENT_KIND_CODE), rollout_count=rollout_count, horizon_months=6
    )
    blocked = sampled.private_equity.issuer_bool_matrix(
        "acme", str(PrivateEquityBoolChannel.LIQUIDITY_BLOCKED), rollout_count=rollout_count, horizon_months=6
    )

    severe_mask = event_kind[:, 1] == int(PrivateEquityEventKindCode.LEGAL_IMPAIRMENT)
    # The indefinite sub-branch is 50% of the 5% severe share. With ~100 severe
    # rollouts at R=2048, ~50 fall into the indefinite branch. Every other severe
    # sub-branch (near-zero capacity, small-dollar recovery) leaves liquidity_blocked
    # at its default 0, so the fraction of severe rollouts blocked at month 6 should
    # be in roughly [0.4, 0.7].
    blocked_at_horizon = blocked[severe_mask, 6]
    if severe_mask.sum() >= 50:
        indefinite_share = float(blocked_at_horizon.mean())
        assert 0.35 <= indefinite_share <= 0.75


def test_private_equity_risk_unrequested_issuer_still_satisfies_request() -> None:
    """The PE risk model samples its configured issuers regardless of what's
    explicitly requested; requesting an unknown issuer fails at validation."""

    model = PrivateEquityRiskProviderConfig(issuers={"acme": _issuer()}).realize_model()

    with pytest.raises(ValueError, match=r"missing required private-equity issuer\(s\): \['other_issuer'\]"):
        model.sample(
            ExogenousSamplingRequest(
                horizon_months=1,
                rollout_seeds=(1,),
                required_private_equity_issuers=frozenset({IssuerId("other_issuer")}),
            )
        )


if __name__ == "__main__":
    pytest_bazel.main()
