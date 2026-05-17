"""Vector Error Correction Model (VECM) on log-levels.

  Δr_t = α (β' x_{t-1} + μ) + Σ_{i=1..p-1} Γ_i Δr_{t-i} + ε_t,  ε_t ~ N(0, Σ)

where x_t is the F-vector of log-levels and `coint_rank` is the assumed
rank of the cointegration relationship. Equivalent to a VAR(p) on
log-levels with a long-run pull toward the cointegrating relationships
β' x + μ = 0; for the configured market factors this is what binds rent
and CPI to a shared trend rather than letting them drift apart over 30
years.

Fit via `statsmodels.tsa.vector_ar.vecm.VECM` once at training time; we
then extract α, β, Γ, the constant inside the relation, and the residual
covariance into typed attributes and drop the third-party fit object —
predict / simulate read these attributes directly. The predictive
density at month t is multivariate normal with mean from the fitted
recurrence and covariance from the fitted residual covariance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field
from statsmodels.tsa.vector_ar.vecm import VECM

from augur.core.market_bundle import MarketBundleProvider
from augur.core.schemas import ApiModel
from augur.model.location_market_sources import LocationMarketSources, LocationMarketSourcesConfig
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from augur.model.markets._density import gaussian_logpdf, gaussian_logpdf_from_samples
from augur.model.markets.scenarios import HistoricalSeries, Scenarios

# Constant inside the cointegration relation. Other deterministic options
# ("co", "lo", "li", "n") change which constants/trends statsmodels populates
# on the fit result; `fit()` below assumes "ci" when it copies parameters out.
# Add another mode only after extending the parameter copy + `_predict_mean`.
_DETERMINISTIC: Literal["ci"] = "ci"


@dataclass(frozen=True)
class VecmConfig:
    """Vecm hyperparameters fixed at construction. `k_ar_diff` is the lag
    order on Δlog-level terms; `coint_rank` is r in the rank-r
    cointegration assumption (1 binds the configured factors to a single
    long-run relationship)."""

    k_ar_diff: int = 1
    coint_rank: int = 1

    def __post_init__(self) -> None:
        if self.k_ar_diff < 0:
            raise ValueError(f"k_ar_diff must be >= 0; got {self.k_ar_diff}")
        if self.coint_rank < 1:
            raise ValueError(f"coint_rank must be >= 1; got {self.coint_rank}")


def _zeros2() -> np.ndarray:
    return np.zeros((0, 0))


def _zeros1() -> np.ndarray:
    return np.zeros((0,))


@dataclass
class VecmModel:
    label = "vecm"

    config: VecmConfig = field(default_factory=VecmConfig)

    # Parameters extracted from the statsmodels fit — empty until `fit()` runs.
    alpha: np.ndarray = field(default_factory=_zeros2)  # (F, r)
    beta: np.ndarray = field(default_factory=_zeros2)  # (F, r)
    gamma: np.ndarray = field(default_factory=_zeros2)  # (F, F * k_ar_diff)
    const_coint: np.ndarray = field(default_factory=_zeros1)  # (r,)
    inv_cov: np.ndarray = field(default_factory=_zeros2)  # (F, F)
    cov_chol: np.ndarray = field(default_factory=_zeros2)  # (F, F)
    cov_log_det: float = 0.0
    factor_names: tuple[str, ...] = ()
    n_factors: int = 0
    train_log_levels: np.ndarray = field(default_factory=_zeros2)  # for simulation seed

    def fit(self, historical: HistoricalSeries) -> None:
        log_levels = np.log(historical.levels)
        if log_levels.shape[0] < self.config.k_ar_diff + 3:
            raise ValueError("VECM needs more observations than k_ar_diff + 3")

        model = VECM(
            log_levels, k_ar_diff=self.config.k_ar_diff, coint_rank=self.config.coint_rank, deterministic=_DETERMINISTIC
        )
        fit = model.fit()

        residuals = np.asarray(fit.resid)
        n_obs, n_factors = residuals.shape
        cov = (residuals.T @ residuals) / max(1, n_obs - 1)
        cov = (cov + cov.T) / 2 + np.eye(n_factors) * 1e-12
        sign, log_det = np.linalg.slogdet(cov)
        if sign <= 0:
            raise ValueError("VECM residual covariance has non-positive determinant")

        # Extract typed parameter arrays from the statsmodels fit and drop the
        # third-party object — `_predict_mean` reads only these.
        self.alpha = np.asarray(fit.alpha)
        self.beta = np.asarray(fit.beta)
        self.gamma = np.asarray(fit.gamma)
        self.const_coint = np.asarray(fit.const_coint).reshape(-1)
        self.inv_cov = np.linalg.inv(cov)
        self.cov_chol = np.linalg.cholesky(cov)
        self.cov_log_det = float(log_det)
        self.factor_names = historical.factor_names
        self.n_factors = n_factors
        self.train_log_levels = log_levels.copy()

    def log_predictive_density(self, historical: HistoricalSeries, t: int) -> float | None:
        if t < self.config.k_ar_diff + 1:
            raise ValueError(f"VECM with k_ar_diff={self.config.k_ar_diff} needs t >= k_ar_diff + 1; got {t}")
        log_levels = np.log(historical.levels)
        # The fitted VECM recurrence predicts Δlog_level[t+1] from
        # log_level[t] and the previous k_ar_diff Δlog_levels:
        #   Δr_{t+1} = α @ (β' @ x_t + const_coint) + Γ_blocks @ stacked_Δr
        mu = self._predict_mean(log_levels, t)
        diff = log_levels[t + 1] - log_levels[t] - mu
        return gaussian_logpdf(diff=diff, inv_cov=self.inv_cov, log_det=self.cov_log_det)

    def log_predictive_marginals(self, historical: HistoricalSeries, t: int) -> dict[str, float] | None:
        if t < self.config.k_ar_diff + 1:
            raise ValueError(f"VECM with k_ar_diff={self.config.k_ar_diff} needs t >= k_ar_diff + 1; got {t}")
        log_levels = np.log(historical.levels)
        mu = self._predict_mean(log_levels, t)
        diff = log_levels[t + 1] - log_levels[t] - mu
        cov = np.linalg.inv(self.inv_cov)
        sd = np.sqrt(np.diag(cov))
        names = self.factor_names or tuple(f"f{i}" for i in range(diff.shape[0]))
        out: dict[str, float] = {}
        for k, name in enumerate(names):
            out[name] = float(-0.5 * (math.log(2 * math.pi) + 2 * math.log(sd[k]) + (diff[k] / sd[k]) ** 2))
        return out

    def log_predictive_density_at_horizon(self, historical: HistoricalSeries, t: int, h: int) -> float | None:
        if h < 1:
            raise ValueError(f"h must be >= 1; got {h}")
        if t < self.config.k_ar_diff + 1:
            return None
        log_returns_full = np.diff(np.log(historical.levels), axis=0)
        if t + h > log_returns_full.shape[0]:
            return None

        # Monte Carlo: roll the VECM recurrence forward from log_levels[:t+1].
        rng = np.random.default_rng(int(t) * 1009 + h)
        n_paths_mc = 5000
        n_factors = log_returns_full.shape[1]
        log_levels = np.log(historical.levels[: t + 1])

        history = log_levels[-(self.config.k_ar_diff + 2) :]
        log_levels_buf = np.broadcast_to(history, (n_paths_mc, history.shape[0], n_factors)).copy()

        innovations = rng.standard_normal((n_paths_mc, h, n_factors)) @ self.cov_chol.T
        cumulative_log_returns = np.zeros((n_paths_mc, n_factors))
        for step in range(h):
            for path_idx in range(n_paths_mc):
                tail = log_levels_buf[path_idx]
                t_local = tail.shape[0] - 1
                mu = self._predict_mean(tail, t_local)
                # Capture last log-level *before* mutating the buffer — tail is
                # a view, so the in-place update below would alias it to the
                # new next_level and zero out the diff.
                last_level = tail[-1].copy()
                next_level = last_level + mu + innovations[path_idx, step, :]
                log_levels_buf[path_idx] = np.concatenate([tail[1:], next_level[None, :]], axis=0)
                cumulative_log_returns[path_idx] += next_level - last_level

        observed_cumulative = log_returns_full[t : t + h].sum(axis=0)
        return gaussian_logpdf_from_samples(samples=cumulative_log_returns, observation=observed_cumulative)

    def _predict_mean(self, log_levels: np.ndarray, t: int) -> np.ndarray:
        """Predict E[Δlog_levels[t+1] | log_levels[:t+1]] under deterministic="ci"
        from the typed parameter arrays populated by `fit()`."""
        x = log_levels[t]
        beta_eff = self.beta[: x.shape[0]]
        coint_term = beta_eff.T @ x + self.const_coint
        mean = self.alpha @ coint_term

        if self.config.k_ar_diff > 0:
            diffs = [log_levels[t - i] - log_levels[t - i - 1] for i in range(self.config.k_ar_diff)]
            mean = mean + self.gamma @ np.concatenate(diffs)

        return np.asarray(mean)

    def save(self, descriptor: VecmMarketProviderConfig) -> None:
        """Persist post-fit state to the `.npz` archive named by the
        descriptor's `trained_blob` so the runtime can skip re-fitting at
        startup. Symmetric to `VecmModel.load(descriptor)`."""
        np.savez_compressed(
            descriptor.trained_blob,
            k_ar_diff=np.array(self.config.k_ar_diff),
            coint_rank=np.array(self.config.coint_rank),
            alpha=self.alpha,
            beta=self.beta,
            gamma=self.gamma,
            const_coint=self.const_coint,
            inv_cov=self.inv_cov,
            cov_chol=self.cov_chol,
            cov_log_det=np.array(self.cov_log_det),
            factor_names=np.array(self.factor_names, dtype=object),
            train_log_levels=self.train_log_levels,
        )

    @staticmethod
    def load(descriptor: VecmMarketProviderConfig) -> VecmModel:
        with np.load(descriptor.trained_blob, allow_pickle=True) as data:
            config = VecmConfig(k_ar_diff=int(data["k_ar_diff"]), coint_rank=int(data["coint_rank"]))
            factor_names = tuple(str(name) for name in data["factor_names"])
            model = VecmModel(config=config)
            model.alpha = np.asarray(data["alpha"])
            model.beta = np.asarray(data["beta"])
            model.gamma = np.asarray(data["gamma"])
            model.const_coint = np.asarray(data["const_coint"])
            model.inv_cov = np.asarray(data["inv_cov"])
            model.cov_chol = np.asarray(data["cov_chol"])
            model.cov_log_det = float(data["cov_log_det"])
            model.factor_names = factor_names
            model.n_factors = len(factor_names)
            model.train_log_levels = np.asarray(data["train_log_levels"])
        return model

    def simulate(self, n_paths: int, n_months: int, seed: int) -> Scenarios:
        rng = np.random.default_rng(seed)
        n_factors = self.n_factors
        train_log_levels = self.train_log_levels

        history = train_log_levels[-(self.config.k_ar_diff + 2) :]
        log_levels_buf = np.broadcast_to(history, (n_paths, history.shape[0], n_factors)).copy()

        out_log_levels = np.empty((n_paths, n_months + 1, n_factors), dtype="float64")
        out_log_levels[:, 0, :] = log_levels_buf[:, -1, :]

        innovations = rng.standard_normal((n_paths, n_months, n_factors)) @ self.cov_chol.T

        for step in range(n_months):
            for path_idx in range(n_paths):
                tail = log_levels_buf[path_idx]
                t_local = tail.shape[0] - 1
                mu = self._predict_mean(tail, t_local)
                next_level = tail[-1] + mu + innovations[path_idx, step, :]
                log_levels_buf[path_idx] = np.concatenate([tail[1:], next_level[None, :]], axis=0)
                out_log_levels[path_idx, step + 1, :] = next_level

        # Convert to multipliers normalized so multipliers[:, 0, :] = 1.0.
        multipliers = np.exp(out_log_levels - out_log_levels[:, :1, :])
        return Scenarios(
            factor_names=self.factor_names or tuple(f"f{i}" for i in range(n_factors)),
            multipliers=multipliers,
            seed=seed,
            label=self.label,
        )


class VecmMarketProviderConfig(ApiModel):
    """Pre-trained VECM provider config — points at the trained-state blob
    written by `bb run //augur/model:train`. The model is loaded at server
    startup; no fitting happens on the request path."""

    type: Literal["vecm"] = "vecm"
    trained_blob: Path = Field(description="Absolute path to the .npz produced by VecmModel.save(descriptor).")
    latest_observations: dict[str, Any] = Field(
        description="Latest observed market state at the start of the simulation horizon (factor → value)."
    )
    current_mortgage30_rate_pct: float
    location_market_sources: LocationMarketSourcesConfig

    def realize(self, *, current_private_equity_price_usd: float) -> MarketBundleProvider:
        model = VecmModel.load(self)
        return MacroMarketBundleProvider.from_loaded_model(
            model,
            latest_observations=self.latest_observations,
            current_mortgage30_rate_pct=self.current_mortgage30_rate_pct,
            current_private_equity_price_usd=current_private_equity_price_usd,
            location_market_sources=LocationMarketSources.from_config(self.location_market_sources),
            evidence_source_id=str(self.trained_blob),
        )
