from __future__ import annotations

import math

import numpy as np
import pytest
import pytest_bazel
from pydantic import TypeAdapter

from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.exogenous_provider_config import ExogenousProviderConfig
from augur.model.private_equity_risk import PrivateEquityRiskIssuerConfig, PrivateEquityRiskProviderConfig
from augur.model.series import (
    PrivateEquityEventKindCode,
    PrivateEquityRegimeCode,
    private_equity_event_kind_code_series_id,
    private_equity_forced_recovery_cashout_usd_series_id,
    private_equity_forced_sale_fraction_series_id,
    private_equity_level_series_ids,
    private_equity_liquidity_blocked_series_id,
    private_equity_regime_code_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
)


def _issuer(**updates: object) -> PrivateEquityRiskIssuerConfig:
    fields = {
        "current_mark_usd": 100.0,
        "tender_interval_months_median": 120.0,
        "tender_interval_log_sigma": 0.0,
        **updates,
    }
    return PrivateEquityRiskIssuerConfig.model_validate(fields)


def _sample(issuer: PrivateEquityRiskIssuerConfig, *, horizon_months: int = 4):
    model = PrivateEquityRiskProviderConfig(issuers={"acme": issuer}).realize_model()
    return model.sample(
        ExogenousSamplingRequest(
            horizon_months=horizon_months,
            rollout_seeds=(7,),
            required_level_series=private_equity_level_series_ids("acme"),
            required_event_series=frozenset({private_equity_sale_event_id("acme")}),
        )
    )


def test_private_equity_risk_provider_config_roundtrips_through_union() -> None:
    adapter: TypeAdapter[ExogenousProviderConfig] = TypeAdapter(ExogenousProviderConfig)
    config = adapter.validate_python({"type": "private_equity_risk", "issuers": {"acme": {"current_mark_usd": 100.0}}})

    assert isinstance(config, PrivateEquityRiskProviderConfig)
    assert config.realize_model().sample(ExogenousSamplingRequest(horizon_months=1, rollout_seeds=(1,))).metadata[
        "private_equity_prices_usd"
    ] == {"acme": 100.0}


def test_private_equity_risk_samples_complete_required_protocol() -> None:
    sampled = _sample(_issuer(), horizon_months=2)

    assert set(sampled.levels.get_column("series_id").unique().to_list()) == private_equity_level_series_ids("acme")
    assert set(sampled.events.get_column("event_id").unique().to_list()) == {private_equity_sale_event_id("acme")}
    np.testing.assert_allclose(
        sampled.level_matrix(private_equity_series_id("acme"), rollout_count=1, horizon_months=2),
        np.array([[100.0, 100.0, 100.0]]),
    )


def test_private_equity_risk_private_mark_is_piecewise_constant_between_observed_ticks() -> None:
    sampled = _sample(_issuer(monthly_log_return_mu=math.log(2.0), monthly_log_return_sigma=0.0), horizon_months=4)

    mark = sampled.level_matrix(private_equity_series_id("acme"), rollout_count=1, horizon_months=4)

    np.testing.assert_allclose(mark, np.full((1, 5), 100.0))


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

    mark = sampled.level_matrix(private_equity_series_id("acme"), rollout_count=1, horizon_months=4)
    event_kind = sampled.level_matrix(
        private_equity_event_kind_code_series_id("acme"), rollout_count=1, horizon_months=4
    )
    tenders = sampled.event_matrix(private_equity_sale_event_id("acme"), rollout_count=1, horizon_months=4)

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

    mark = sampled.level_matrix(private_equity_series_id("acme"), rollout_count=1, horizon_months=3)
    event_kind = sampled.level_matrix(
        private_equity_event_kind_code_series_id("acme"), rollout_count=1, horizon_months=3
    )
    tenders = sampled.event_matrix(private_equity_sale_event_id("acme"), rollout_count=1, horizon_months=3)

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

    recovery = sampled.level_matrix(
        private_equity_forced_recovery_cashout_usd_series_id("acme"), rollout_count=1, horizon_months=3
    )
    event_kind = sampled.level_matrix(
        private_equity_event_kind_code_series_id("acme"), rollout_count=1, horizon_months=3
    )
    regime = sampled.level_matrix(private_equity_regime_code_series_id("acme"), rollout_count=1, horizon_months=3)
    blocked = sampled.level_matrix(
        private_equity_liquidity_blocked_series_id("acme"), rollout_count=1, horizon_months=3
    )

    assert recovery[0, 1] == pytest.approx(100.0)
    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.FORCED_RECOVERY)
    np.testing.assert_array_equal(regime[0, 1:], np.full(3, int(PrivateEquityRegimeCode.COLLAPSED)))
    np.testing.assert_array_equal(blocked[0, 1:], np.ones(3))


def test_private_equity_risk_collapse_blocks_liquidity_and_marks_down() -> None:
    sampled = _sample(_issuer(annual_collapse_probability=1.0, collapsed_mark_fraction=0.01), horizon_months=3)

    mark = sampled.level_matrix(private_equity_series_id("acme"), rollout_count=1, horizon_months=3)
    event_kind = sampled.level_matrix(
        private_equity_event_kind_code_series_id("acme"), rollout_count=1, horizon_months=3
    )
    regime = sampled.level_matrix(private_equity_regime_code_series_id("acme"), rollout_count=1, horizon_months=3)
    blocked = sampled.level_matrix(
        private_equity_liquidity_blocked_series_id("acme"), rollout_count=1, horizon_months=3
    )

    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.COLLAPSE)
    np.testing.assert_array_equal(regime[0, 1:], np.full(3, int(PrivateEquityRegimeCode.COLLAPSED)))
    np.testing.assert_array_equal(blocked[0, 1:], np.ones(3))
    np.testing.assert_allclose(mark[0, 1:], np.full(3, 1.0))


def test_private_equity_risk_public_market_is_absorbing_open_liquidity_regime() -> None:
    sampled = _sample(_issuer(annual_public_market_probability=1.0), horizon_months=3)

    event_kind = sampled.level_matrix(
        private_equity_event_kind_code_series_id("acme"), rollout_count=1, horizon_months=3
    )
    regime = sampled.level_matrix(private_equity_regime_code_series_id("acme"), rollout_count=1, horizon_months=3)
    blocked = sampled.level_matrix(
        private_equity_liquidity_blocked_series_id("acme"), rollout_count=1, horizon_months=3
    )

    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.PUBLIC_MARKET_OPEN)
    np.testing.assert_array_equal(regime[0, 1:], np.full(3, int(PrivateEquityRegimeCode.PUBLIC_MARKET)))
    np.testing.assert_array_equal(blocked[0, 1:], np.zeros(3))


def test_private_equity_risk_public_market_lockup_blocks_liquidity_then_opens() -> None:
    sampled = _sample(_issuer(annual_public_market_probability=1.0, public_market_lockup_months=2), horizon_months=4)

    regime = sampled.level_matrix(private_equity_regime_code_series_id("acme"), rollout_count=1, horizon_months=4)
    blocked = sampled.level_matrix(
        private_equity_liquidity_blocked_series_id("acme"), rollout_count=1, horizon_months=4
    )

    np.testing.assert_array_equal(regime[0, 1:], np.full(4, int(PrivateEquityRegimeCode.PUBLIC_MARKET)))
    np.testing.assert_array_equal(blocked[0], np.array([0.0, 1.0, 1.0, 0.0, 0.0]))


def test_private_equity_risk_forced_sale_emits_sale_fraction_without_tender() -> None:
    sampled = _sample(
        _issuer(annual_forced_sale_probability=1.0, forced_sale_fraction_alpha=1000.0, forced_sale_fraction_beta=1.0),
        horizon_months=2,
    )

    event_kind = sampled.level_matrix(
        private_equity_event_kind_code_series_id("acme"), rollout_count=1, horizon_months=2
    )
    forced_sale = sampled.level_matrix(
        private_equity_forced_sale_fraction_series_id("acme"), rollout_count=1, horizon_months=2
    )
    tenders = sampled.event_matrix(private_equity_sale_event_id("acme"), rollout_count=1, horizon_months=2)

    assert int(event_kind[0, 1]) == int(PrivateEquityEventKindCode.ACQUISITION_CASHOUT)
    regime = sampled.level_matrix(private_equity_regime_code_series_id("acme"), rollout_count=1, horizon_months=2)
    assert int(regime[0, 1]) == int(PrivateEquityRegimeCode.ACQUIRED)
    assert 0.0 < forced_sale[0, 1] <= 1.0
    assert not tenders[0, 1]


def test_private_equity_risk_rejects_missing_required_issuer_series() -> None:
    model = PrivateEquityRiskProviderConfig(issuers={"acme": _issuer()}).realize_model()

    with pytest.raises(ValueError, match="missing required level series"):
        model.sample(
            ExogenousSamplingRequest(
                horizon_months=1,
                rollout_seeds=(1,),
                required_level_series=private_equity_level_series_ids("other_issuer"),
            )
        )


if __name__ == "__main__":
    pytest_bazel.main()
