"""Wilkie-style cascade for configured market factors (Wilkie 1986/1995/2011).

A constrained VAR(1) where each factor depends only on itself and on
factors above it in the cascade ordering. Inflation drives everything;
rent / home / sp500 each regress on lagged inflation plus their own lag.
Per-factor Gaussian innovations with a diagonal residual covariance.

  inflation_t = c₀ + φ₀ inflation_{t-1} + ε₀
  rent_t      = c₁ + ψ₁ inflation_{t-1} + φ₁ rent_{t-1}      + ε₁
  home_t      = c₂ + ψ₂ inflation_{t-1} + φ₂ home_{t-1}      + ε₂
  sp500_t     = c₃ + ψ₃ inflation_{t-1} + φ₃ sp500_{t-1}     + ε₃

with `ε_t ~ N(0, diag(σ²))` (independent across factors).

Factor order is taken from `historical.factor_names`; the column named
"inflation" is the cascade root regardless of position. Predictive
density is the sum of independent univariate Gaussian log-pdfs. Strictly
fewer free parameters than VAR(1) — useful for testing
whether the cascade structure helps out-of-sample fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from augur.model.markets.models.var import _var1_horizon_density
from pydantic import Field

from augur.core.market_bundle import MarketBundleProvider
from augur.core.schemas import ApiModel
from augur.model.location_market_sources import LocationMarketSources, LocationMarketSourcesConfig
from augur.model.markets.scenarios import HistoricalSeries, Scenarios, historical_log_returns


@dataclass(frozen=True)
class WilkieConfig:
    """Wilkie cascade has no hyperparameters today (the cascade structure is
    fixed by the inflation-as-root convention); empty config keeps the
    `(model_cls, config)` registry shape uniform across models."""


def _zeros1() -> np.ndarray:
    return np.zeros((0,))


@dataclass
class WilkieCascade:
    label = "wilkie_cascade"

    config: WilkieConfig = field(default_factory=WilkieConfig)

    # Parameters — empty until `fit()` runs.
    intercept: np.ndarray = field(default_factory=_zeros1)  # (F,)
    weight_inflation: np.ndarray = field(default_factory=_zeros1)  # (F,) zero on inflation row
    weight_own: np.ndarray = field(default_factory=_zeros1)  # (F,)
    residual_sd: np.ndarray = field(default_factory=_zeros1)  # (F,)
    inflation_index: int = 0
    last_log_return: np.ndarray = field(default_factory=_zeros1)
    factor_names: tuple[str, ...] = ()

    def fit(self, historical: HistoricalSeries) -> None:
        if "inflation" not in historical.factor_names:
            raise ValueError(
                "WilkieCascade requires a factor named 'inflation' as the cascade root; "
                f"got {historical.factor_names!r}"
            )
        log_returns = historical_log_returns(historical)
        if log_returns.shape[0] < 3:
            raise ValueError("WilkieCascade needs at least three log-returns to fit")
        n_factors = log_returns.shape[1]
        inflation_index = historical.factor_names.index("inflation")

        intercept = np.zeros(n_factors)
        weight_inflation = np.zeros(n_factors)
        weight_own = np.zeros(n_factors)
        residual_sd = np.zeros(n_factors)

        y_all = log_returns[1:]
        x_lag_all = log_returns[:-1]
        n_obs = y_all.shape[0]

        for k in range(n_factors):
            y = y_all[:, k]
            if k == inflation_index:
                x = np.column_stack([np.ones(n_obs), x_lag_all[:, k]])
                beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
                intercept[k] = beta[0]
                weight_inflation[k] = 0.0
                weight_own[k] = beta[1]
            else:
                x = np.column_stack([np.ones(n_obs), x_lag_all[:, inflation_index], x_lag_all[:, k]])
                beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
                intercept[k] = beta[0]
                weight_inflation[k] = beta[1]
                weight_own[k] = beta[2]
            fitted = x @ beta
            residuals = y - fitted
            dof = max(1, n_obs - x.shape[1])
            residual_sd[k] = float(np.sqrt(np.sum(residuals**2) / dof))

        self.intercept = intercept
        self.weight_inflation = weight_inflation
        self.weight_own = weight_own
        self.residual_sd = residual_sd
        self.inflation_index = inflation_index
        self.last_log_return = log_returns[-1].copy()
        self.factor_names = historical.factor_names

    def log_predictive_density(self, historical: HistoricalSeries, t: int) -> float | None:
        if t < 1:
            raise ValueError(f"WilkieCascade predictive density needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        r_t = log_returns[t]
        r_prev = log_returns[t - 1]
        inflation_lag = r_prev[self.inflation_index]
        mu = self.intercept + self.weight_inflation * inflation_lag + self.weight_own * r_prev
        diff = r_t - mu
        sd = self.residual_sd
        log_density = -0.5 * np.sum((diff / sd) ** 2 + 2 * np.log(sd) + math.log(2 * math.pi))
        return float(log_density)

    def log_predictive_marginals(self, historical: HistoricalSeries, t: int) -> dict[str, float] | None:
        # Wilkie has independent univariate Gaussian innovations per factor,
        # so the marginals coincide with the per-factor terms in
        # `log_predictive_density` and their sum equals the joint score.
        if t < 1:
            raise ValueError(f"WilkieCascade predictive marginals need t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        r_t = log_returns[t]
        r_prev = log_returns[t - 1]
        inflation_lag = r_prev[self.inflation_index]
        mu = self.intercept + self.weight_inflation * inflation_lag + self.weight_own * r_prev
        diff = r_t - mu
        sd = self.residual_sd
        out: dict[str, float] = {}
        names = self.factor_names or tuple(f"f{i}" for i in range(r_t.shape[0]))
        for k, name in enumerate(names):
            out[name] = float(-0.5 * (math.log(2 * math.pi) + 2 * math.log(sd[k]) + (diff[k] / sd[k]) ** 2))
        return out

    def log_predictive_density_at_horizon(self, historical: HistoricalSeries, t: int, h: int) -> float | None:
        if h < 1:
            raise ValueError(f"h must be >= 1; got {h}")
        if t < 1:
            raise ValueError(f"WilkieCascade needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        if t + h > log_returns.shape[0]:
            return None

        # Lift to VAR(1): A_kj = ψ_k δ(j, inflation_index) + φ_k δ(k, j).
        n_factors = self.intercept.shape[0]
        coef = np.zeros((n_factors, n_factors))
        coef[:, self.inflation_index] = self.weight_inflation
        coef[np.arange(n_factors), np.arange(n_factors)] = self.weight_own
        cov_residual = np.diag(self.residual_sd**2)

        return _var1_horizon_density(
            intercept=self.intercept,
            coef=coef,
            cov_residual=cov_residual,
            last_return=log_returns[t - 1],
            observed_cumulative=log_returns[t : t + h].sum(axis=0),
            h=h,
        )

    def save(self, descriptor: WilkieCascadeMarketProviderConfig) -> None:
        """Persist post-fit state to the `.npz` archive named by the
        descriptor's `trained_blob` so the runtime can skip re-fitting at
        startup. Symmetric to `WilkieCascade.load(descriptor)`."""
        np.savez_compressed(
            descriptor.trained_blob,
            intercept=self.intercept,
            weight_inflation=self.weight_inflation,
            weight_own=self.weight_own,
            residual_sd=self.residual_sd,
            inflation_index=np.array(self.inflation_index),
            last_log_return=self.last_log_return,
            factor_names=np.array(self.factor_names, dtype=object),
        )

    @staticmethod
    def load(descriptor: WilkieCascadeMarketProviderConfig) -> WilkieCascade:
        with np.load(descriptor.trained_blob, allow_pickle=True) as data:
            factor_names = tuple(str(name) for name in data["factor_names"])
            model = WilkieCascade(config=WilkieConfig())
            model.intercept = np.asarray(data["intercept"])
            model.weight_inflation = np.asarray(data["weight_inflation"])
            model.weight_own = np.asarray(data["weight_own"])
            model.residual_sd = np.asarray(data["residual_sd"])
            model.inflation_index = int(data["inflation_index"])
            model.last_log_return = np.asarray(data["last_log_return"])
            model.factor_names = factor_names
        return model

    def simulate(self, n_paths: int, n_months: int, seed: int) -> Scenarios:
        n_factors = self.intercept.shape[0]
        rng = np.random.default_rng(seed)
        innovations = rng.standard_normal((n_paths, n_months, n_factors)) * self.residual_sd

        log_returns = np.empty((n_paths, n_months, n_factors), dtype="float64")
        prev = np.broadcast_to(self.last_log_return, (n_paths, n_factors)).copy()
        for step in range(n_months):
            inflation_lag = prev[:, self.inflation_index]
            current = (
                self.intercept
                + self.weight_inflation[None, :] * inflation_lag[:, None]
                + self.weight_own[None, :] * prev
                + innovations[:, step, :]
            )
            log_returns[:, step, :] = current
            prev = current

        cum = np.concatenate([np.zeros((n_paths, 1, n_factors)), np.cumsum(log_returns, axis=1)], axis=1)
        return Scenarios(
            factor_names=self.factor_names or tuple(f"f{i}" for i in range(n_factors)),
            multipliers=np.exp(cum),
            seed=seed,
            label=self.label,
        )


class WilkieCascadeMarketProviderConfig(ApiModel):
    """Pre-trained Wilkie cascade provider config — points at the trained-state
    blob written by `bb run //augur/model/train:train`. The model is loaded at server
    startup; no fitting happens on the request path."""

    type: Literal["wilkie_cascade"] = "wilkie_cascade"
    trained_blob: Path = Field(description="Absolute path to the .npz produced by WilkieCascade.save(descriptor).")
    latest_observations: dict[str, Any] = Field(
        description="Latest observed market state at the start of the simulation horizon (factor → value)."
    )
    current_mortgage30_rate_pct: float
    location_market_sources: LocationMarketSourcesConfig

    def realize(self, *, current_private_equity_price_usd: float) -> MarketBundleProvider:
        model = WilkieCascade.load(self)
        return MacroMarketBundleProvider.from_loaded_model(
            model,
            latest_observations=self.latest_observations,
            current_mortgage30_rate_pct=self.current_mortgage30_rate_pct,
            current_private_equity_price_usd=current_private_equity_price_usd,
            location_market_sources=LocationMarketSources.from_config(self.location_market_sources),
            evidence_source_id=str(self.trained_blob),
        )
