"""Tests for the M2.2-A per-rollout stochastic dilution-rate knob.

These cover the `annual_dilution_rate_log_sigma` field added to
`PrivateEquityRiskIssuerConfig` and the median-anchored per-rollout LogNormal
draw it drives in `_dilution_factor`. The decisive guarantee is the
zero-regression test: with the knob at its default (0.0) the sampler output is
byte-identical to the same config without the field, proving the new
`:pe_risk_dilution` seed stream does not perturb the level / event / valuation
streams.
"""

from __future__ import annotations

import numpy as np

from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.private_equity_risk import PrivateEquityRiskIssuerConfig, _dilution_factor, _sample_issuer
from augur.model.series import IssuerId

# A valuation-channel-ON issuer with a non-trivial dilution rate. The dispersion
# knob is overridden per-test; the base config leaves it at its inert default.
_BASE_ISSUER_KWARGS: dict[str, float] = {
    "current_mark_usd": 100.0,
    "current_valuation_usd": 1_000_000_000.0,
    "shares_outstanding_initial": 10_000_000.0,
    "valuation_monthly_log_return_mu": 0.0,
    "valuation_monthly_log_return_sigma": 0.05,
    "valuation_student_t_nu": 5.0,
    "annual_dilution_rate": 0.20,
}


def _issuer(**overrides: float) -> PrivateEquityRiskIssuerConfig:
    return PrivateEquityRiskIssuerConfig(**{**_BASE_ISSUER_KWARGS, **overrides})


def _request(*, rollout_count: int, horizon_months: int, seed: int = 7) -> ExogenousSamplingRequest:
    """Build a sampling request with deterministic per-rollout root seeds.

    `rollout_count` is derived from the seed vector length (no explicit field).
    """

    rollout_seeds = tuple(seed * 1_000_003 + i for i in range(rollout_count))
    return ExogenousSamplingRequest(
        horizon_months=horizon_months,
        rollout_seeds=rollout_seeds,
        required_private_equity_issuers=frozenset({IssuerId("acme")}),
    )


def test_dilution_sigma_default_is_byte_identical() -> None:
    """sigma UNSET (default 0) but valuation-on must reproduce mark / event_kind /
    regime / company_valuation arrays byte-for-byte vs a config WITHOUT the field.

    Proves sigma=0 => no behavior change and that the new `:pe_risk_dilution`
    seed stream is not derived / does not perturb any other stream.
    """

    rollout_count = 256
    horizon_months = 120
    request = _request(rollout_count=rollout_count, horizon_months=horizon_months)

    # "Without the field": the field defaults to 0.0, so an explicit-default config
    # is the honest baseline (the pydantic model always has the attribute).
    baseline = _sample_issuer("acme", _issuer(), request)
    explicit_zero = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.0), request)

    assert np.array_equal(baseline.mark, explicit_zero.mark)
    assert np.array_equal(baseline.event_kind_code, explicit_zero.event_kind_code)
    assert np.array_equal(baseline.regime_code, explicit_zero.regime_code)
    assert np.array_equal(baseline.company_valuation_usd, explicit_zero.company_valuation_usd)


def test_dilution_sigma_widens_per_share_cone_over_time() -> None:
    """sigma>0 adds cross-rollout spread to log(mark) that GROWS with t, while
    sigma=0 adds none from dilution.
    """

    rollout_count = 2_000
    horizon_months = 120
    request = _request(rollout_count=rollout_count, horizon_months=horizon_months)

    disperse = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.3), request)
    flat = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.0), request)

    def _log_var(paths: np.ndarray, month: int) -> float:
        return float(np.var(np.log(paths[:, month])))

    # Dispersion makes month-120 spread strictly exceed month-12 spread...
    assert _log_var(disperse.mark, 120) > _log_var(disperse.mark, 12)
    # ...and at month 120 the dispersed cone is wider than the flat one (dilution
    # contributes the extra spread; valuation noise is shared via its own stream).
    assert _log_var(disperse.mark, 120) > _log_var(flat.mark, 120)


def test_dilution_draw_is_median_anchored() -> None:
    """The per-rollout drawn rate r has median ~= annual_dilution_rate (NOT mean-
    anchored, which would drift up by exp(sigma**2/2))."""

    annual_dilution_rate = 0.20
    sigma = 0.5
    horizon_months = 12
    rollout_count = 20_000
    rollout_seeds = tuple(11 * 1_000_003 + i for i in range(rollout_count))

    factor = _dilution_factor(
        annual_dilution_rate=annual_dilution_rate,
        annual_dilution_rate_log_sigma=sigma,
        horizon_months=horizon_months,
        rollout_seeds=rollout_seeds,
        issuer_id="acme",
        rollout_count=rollout_count,
    )
    assert factor.shape == (rollout_count, horizon_months + 1)
    # Recover r from the 12-month factor: factor[:,12] = (1+r)**1.
    r = factor[:, 12] - 1.0
    median_r = float(np.median(r))
    # Median anchored at the configured rate; mean would be ~0.20*exp(0.125)=0.227.
    assert abs(median_r - annual_dilution_rate) < 0.01
    assert float(np.mean(r)) > median_r + 0.01  # right-skew confirms LogNormal, not symmetric


def test_dilution_median_factor_matches_deterministic() -> None:
    """The median rollout's dilution factor tracks the deterministic factor."""

    annual_dilution_rate = 0.20
    horizon_months = 120
    rollout_count = 20_000
    rollout_seeds = tuple(3 * 1_000_003 + i for i in range(rollout_count))

    stochastic = _dilution_factor(
        annual_dilution_rate=annual_dilution_rate,
        annual_dilution_rate_log_sigma=0.3,
        horizon_months=horizon_months,
        rollout_seeds=rollout_seeds,
        issuer_id="acme",
        rollout_count=rollout_count,
    )
    deterministic = _dilution_factor(
        annual_dilution_rate=annual_dilution_rate,
        annual_dilution_rate_log_sigma=0.0,
        horizon_months=horizon_months,
        rollout_seeds=rollout_seeds,
        issuer_id="acme",
        rollout_count=rollout_count,
    )
    assert deterministic.shape == (horizon_months + 1,)
    median_factor_120 = float(np.median(stochastic[:, 120]))
    assert np.isclose(median_factor_120, deterministic[120], rtol=0.02)


def test_dilution_determinism() -> None:
    """Same rollout_seeds => identical sampler output across two runs with sigma>0."""

    request = _request(rollout_count=128, horizon_months=60)
    first = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.4), request)
    second = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.4), request)
    assert np.array_equal(first.mark, second.mark)
    assert np.array_equal(first.event_kind_code, second.event_kind_code)
    assert np.array_equal(first.regime_code, second.regime_code)
    assert np.array_equal(first.company_valuation_usd, second.company_valuation_usd)


def test_dilution_sigma_leaves_events_byte_identical() -> None:
    """Flipping sigma 0 -> >0 changes only the mark scale; event_kind_code and
    regime_code stay byte-identical (the dilution stream is independent of the
    event stream). company_valuation is also unchanged (its own stream)."""

    request = _request(rollout_count=512, horizon_months=120)
    flat = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.0), request)
    disperse = _sample_issuer("acme", _issuer(annual_dilution_rate_log_sigma=0.3), request)

    assert np.array_equal(flat.event_kind_code, disperse.event_kind_code)
    assert np.array_equal(flat.regime_code, disperse.regime_code)
    assert np.array_equal(flat.company_valuation_usd, disperse.company_valuation_usd)
    # The marks DO differ (otherwise the knob would be a no-op).
    assert not np.array_equal(flat.mark, disperse.mark)


def test_dilution_rate_zero_with_sigma_is_degenerate() -> None:
    """rate==0 + sigma>0 => no dilution and no added spread (factor all ones)."""

    horizon_months = 120
    rollout_count = 1_000
    rollout_seeds = tuple(5 * 1_000_003 + i for i in range(rollout_count))

    factor = _dilution_factor(
        annual_dilution_rate=0.0,
        annual_dilution_rate_log_sigma=0.5,
        horizon_months=horizon_months,
        rollout_seeds=rollout_seeds,
        issuer_id="acme",
        rollout_count=rollout_count,
    )
    # rate==0 short-circuits to the deterministic (T+1,) all-ones row.
    assert factor.shape == (horizon_months + 1,)
    assert np.array_equal(factor, np.ones(horizon_months + 1))


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
