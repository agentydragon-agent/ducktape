"""GJR-GARCH per factor + Engle (2002) Dynamic Conditional Correlation.

Two-stage fit:

1. Fit a univariate GJR-GARCH(1,1) per factor on its log-return series
   via the `arch` package:
        σ²_{t,k} = ω_k + α_k ε²_{t-1,k}
                 + γ_k ε²_{t-1,k} 1[ε_{t-1,k} < 0]
                 + β_k σ²_{t-1,k}
   GJR-GARCH adds the leverage term γ — equity-like asymmetry where
   negative shocks raise vol more than positive ones.

2. Standardize residuals z_t = ε_t / σ_t and fit the Engle DCC
   correlation recurrence:
        Q_t = (1 - a - b) Q̄ + a z_{t-1} z_{t-1}' + b Q_{t-1}
        R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}
   with (a, b) maximizing the second-stage Gaussian log-likelihood
   under the time-varying correlation R_t.

Predictive density: at each t, the log-pdf of (ε_t / σ_t = z_t) under
N(0, R_t), plus the per-factor univariate Gaussian log-pdfs that
contribute the σ_t scale. The decomposition is the standard DCC
predictive density (Engle 2002 §III).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from arch.univariate import GARCH, ConstantMean, Normal
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from pydantic import Field
from scipy.optimize import minimize

from augur.core.market_bundle import MarketBundleProvider
from augur.core.schemas import ApiModel
from augur.model.location_market_sources import LocationMarketSources, LocationMarketSourcesConfig
from augur.model.markets._density import gaussian_logpdf_from_samples
from augur.model.markets.scenarios import HistoricalSeries, Scenarios, historical_log_returns


@dataclass(frozen=True)
class DccGjrGarchConfig:
    """No hyperparameters today; empty config keeps the `(model_cls, config)`
    registry shape uniform across models. The univariate GJR-GARCH is fixed at
    (p=1, o=1, q=1, power=2.0) and the DCC stage is (a + b < 1) — exposing
    those as knobs requires touching the fit logic, not the config."""


def _zeros1() -> np.ndarray:
    return np.zeros((0,))


def _zeros2() -> np.ndarray:
    return np.zeros((0, 0))


def _zeros3() -> np.ndarray:
    return np.zeros((0, 0, 0))


@dataclass
class DccGjrGarch:
    label = "dcc_gjr_garch"

    config: DccGjrGarchConfig = field(default_factory=DccGjrGarchConfig)

    # Per-factor mean and GJR-GARCH parameters — shape (F,) each, empty
    # until `fit()` runs.
    mu: np.ndarray = field(default_factory=_zeros1)
    omega: np.ndarray = field(default_factory=_zeros1)
    alpha: np.ndarray = field(default_factory=_zeros1)
    gamma: np.ndarray = field(default_factory=_zeros1)
    beta: np.ndarray = field(default_factory=_zeros1)

    # DCC scalar parameters and unconditional standardized-residual covariance.
    dcc_a: float = 0.0
    dcc_b: float = 0.0
    q_bar: np.ndarray = field(default_factory=_zeros2)

    # Training-tail state needed to seed simulations.
    sigma_last: np.ndarray = field(default_factory=_zeros1)
    z_last: np.ndarray = field(default_factory=_zeros1)
    q_last: np.ndarray = field(default_factory=_zeros2)

    factor_names: tuple[str, ...] = ()
    n_factors: int = 0

    def fit(self, historical: HistoricalSeries) -> None:
        log_returns = historical_log_returns(historical)
        n_obs, n_factors = log_returns.shape
        if n_obs < 60:
            raise ValueError(f"DCC-GJR-GARCH wants at least 60 observations; got {n_obs}")

        mu = np.zeros(n_factors)
        omega = np.zeros(n_factors)
        alpha = np.zeros(n_factors)
        gamma = np.zeros(n_factors)
        beta = np.zeros(n_factors)
        sigma = np.empty((n_obs, n_factors))
        epsilon = np.empty((n_obs, n_factors))

        for k in range(n_factors):
            series = log_returns[:, k]
            model = ConstantMean(series, rescale=False)
            model.volatility = GARCH(p=1, o=1, q=1, power=2.0)
            model.distribution = Normal()
            res = model.fit(disp="off", show_warning=False)
            params = res.params
            mu[k] = float(params["mu"])
            omega[k] = float(params["omega"])
            alpha[k] = float(params["alpha[1]"])
            gamma[k] = float(params["gamma[1]"])
            beta[k] = float(params["beta[1]"])
            sigma[:, k] = np.asarray(res.conditional_volatility)
            epsilon[:, k] = series - mu[k]

        z = epsilon / sigma
        q_bar = np.cov(z.T, bias=True)
        a, b = self._fit_dcc_engle(z, q_bar)

        # Roll the DCC recurrence over the training window so we can record Q_{T-1}.
        q_t = q_bar.copy()
        for t in range(1, n_obs):
            q_t = (1.0 - a - b) * q_bar + a * np.outer(z[t - 1], z[t - 1]) + b * q_t

        self.mu = mu
        self.omega = omega
        self.alpha = alpha
        self.gamma = gamma
        self.beta = beta
        self.dcc_a = float(a)
        self.dcc_b = float(b)
        self.q_bar = q_bar
        self.sigma_last = sigma[-1].copy()
        self.z_last = z[-1].copy()
        self.q_last = q_t
        self.factor_names = historical.factor_names
        self.n_factors = n_factors

    @staticmethod
    def _fit_dcc_engle(z: np.ndarray, q_bar: np.ndarray) -> tuple[float, float]:
        """Maximize the DCC second-stage Gaussian log-likelihood
        Σ_t -0.5 (log|R_t| + z_t' R_t^{-1} z_t)
        over (a, b) with a, b >= 0 and a + b < 1. Uses scipy.optimize."""
        n_obs, _ = z.shape

        def neg_log_lik(params: np.ndarray) -> float:
            a, b = params
            if a < 0 or b < 0 or a + b >= 0.999:
                return 1e10
            q_t = q_bar.copy()
            total = 0.0
            for t in range(1, n_obs):
                q_t = (1.0 - a - b) * q_bar + a * np.outer(z[t - 1], z[t - 1]) + b * q_t
                d = np.sqrt(np.diag(q_t))
                r_t = q_t / np.outer(d, d)
                sign, log_det = np.linalg.slogdet(r_t)
                if sign <= 0 or not math.isfinite(log_det):
                    return 1e10
                try:
                    inv_r = np.linalg.inv(r_t)
                except np.linalg.LinAlgError:
                    return 1e10
                quad = float(z[t] @ inv_r @ z[t])
                total += 0.5 * (log_det + quad)
            return total

        result = minimize(
            neg_log_lik, x0=np.array([0.05, 0.90]), method="L-BFGS-B", bounds=[(1e-6, 0.5), (1e-6, 0.999)]
        )
        a, b = float(result.x[0]), float(result.x[1])
        if a + b >= 0.999:
            scale = 0.998 / (a + b)
            a *= scale
            b *= scale
        return a, b

    def _sigma_at(self, epsilon_path: np.ndarray, t: int) -> np.ndarray:
        """Univariate σ_t for each factor at time index t in `epsilon_path`."""
        n_factors = epsilon_path.shape[1]
        sigma_t = np.empty(n_factors)
        denom = np.maximum(1.0 - self.alpha - self.beta - 0.5 * self.gamma, 1e-6)
        for k in range(n_factors):
            sigma2 = self.omega[k] / denom[k]
            for s in range(t):
                eps_prev = epsilon_path[s, k]
                indicator = 1.0 if eps_prev < 0 else 0.0
                sigma2 = (
                    self.omega[k]
                    + self.alpha[k] * eps_prev**2
                    + self.gamma[k] * indicator * eps_prev**2
                    + self.beta[k] * sigma2
                )
            sigma_t[k] = math.sqrt(sigma2)
        return sigma_t

    def log_predictive_density(self, historical: HistoricalSeries, t: int) -> float | None:
        if t < 1:
            raise ValueError(f"DccGjrGarch needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        epsilon_path = log_returns - self.mu
        n_factors = epsilon_path.shape[1]

        sigma_t = self._sigma_at(epsilon_path, t)
        eps_t = epsilon_path[t]
        z_t = eps_t / sigma_t

        # Roll DCC forward to get Q_t and R_t.
        q_t = self.q_bar.copy()
        for s in range(1, t + 1):
            z_prev = epsilon_path[s - 1] / self._sigma_at(epsilon_path, s - 1)
            q_t = (
                (1.0 - self.dcc_a - self.dcc_b) * self.q_bar + self.dcc_a * np.outer(z_prev, z_prev) + self.dcc_b * q_t
            )
        d = np.sqrt(np.diag(q_t))
        r_t = q_t / np.outer(d, d)
        _, log_det_r = np.linalg.slogdet(r_t)
        inv_r = np.linalg.inv(r_t)

        log_det_h = 2.0 * float(np.sum(np.log(sigma_t)))
        quad = float(z_t @ inv_r @ z_t)
        return float(-0.5 * (n_factors * math.log(2 * math.pi) + log_det_h + log_det_r + quad))

    def log_predictive_marginals(self, historical: HistoricalSeries, t: int) -> dict[str, float] | None:
        if t < 1:
            raise ValueError(f"DccGjrGarch needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        epsilon_path = log_returns - self.mu
        sigma_t = self._sigma_at(epsilon_path, t)
        eps_t = epsilon_path[t]
        names = self.factor_names or tuple(f"f{i}" for i in range(eps_t.shape[0]))
        out: dict[str, float] = {}
        for k, name in enumerate(names):
            sd = sigma_t[k]
            out[name] = float(-0.5 * (math.log(2 * math.pi) + 2 * math.log(sd) + (eps_t[k] / sd) ** 2))
        return out

    def log_predictive_density_at_horizon(self, historical: HistoricalSeries, t: int, h: int) -> float | None:
        if h < 1:
            raise ValueError(f"h must be >= 1; got {h}")
        if t < 1:
            raise ValueError(f"DccGjrGarch needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        if t + h > log_returns.shape[0]:
            return None

        # Roll the model state to time t using the observed history, then
        # Monte Carlo from t for n_paths × h months and fit a Gaussian to
        # the cumulative h-step return distribution.
        epsilon_path = log_returns[:t] - self.mu
        sigma_t = self._sigma_at(epsilon_path, t)
        if t == 0:
            z_prev = np.zeros_like(self.mu)
            eps_prev = np.zeros_like(self.mu)
        else:
            sigma_prev = self._sigma_at(epsilon_path, t - 1)
            eps_prev = epsilon_path[t - 1]
            z_prev = eps_prev / sigma_prev

        q = self.q_bar.copy()
        for s in range(1, t):
            sigma_s_minus_one = self._sigma_at(epsilon_path, s - 1)
            z_s_minus_one = epsilon_path[s - 1] / sigma_s_minus_one
            q = (
                (1.0 - self.dcc_a - self.dcc_b) * self.q_bar
                + self.dcc_a * np.outer(z_s_minus_one, z_s_minus_one)
                + self.dcc_b * q
            )

        rng = np.random.default_rng(int(t) * 1009 + h)
        n_paths_mc = 5000
        n_factors = self.n_factors
        sigma2 = np.broadcast_to(sigma_t**2, (n_paths_mc, n_factors)).copy()
        eps_prev_paths = np.broadcast_to(eps_prev, (n_paths_mc, n_factors)).copy()
        z_prev_paths = np.broadcast_to(z_prev, (n_paths_mc, n_factors)).copy()
        q_paths = np.broadcast_to(q, (n_paths_mc, n_factors, n_factors)).copy()
        cum_returns = np.zeros((n_paths_mc, n_factors))
        for _step in range(h):
            indicator = (eps_prev_paths < 0).astype("float64")
            sigma2 = (
                self.omega[None, :]
                + self.alpha[None, :] * eps_prev_paths**2
                + self.gamma[None, :] * indicator * eps_prev_paths**2
                + self.beta[None, :] * sigma2
            )
            sigma_step = np.sqrt(sigma2)
            q_paths = (
                (1.0 - self.dcc_a - self.dcc_b) * self.q_bar[None, :, :]
                + self.dcc_a * np.einsum("ni,nj->nij", z_prev_paths, z_prev_paths)
                + self.dcc_b * q_paths
            )
            d = np.sqrt(np.diagonal(q_paths, axis1=1, axis2=2))
            r = q_paths / np.einsum("ni,nj->nij", d, d)
            chol_r = np.linalg.cholesky(r + 1e-12 * np.eye(n_factors)[None, :, :])
            normal_draws = rng.standard_normal((n_paths_mc, n_factors))
            z_step = np.einsum("nij,nj->ni", chol_r, normal_draws)
            eps_step = sigma_step * z_step
            r_step = self.mu[None, :] + eps_step
            cum_returns = cum_returns + r_step
            eps_prev_paths = eps_step
            z_prev_paths = z_step

        return gaussian_logpdf_from_samples(samples=cum_returns, observation=log_returns[t : t + h].sum(axis=0))

    def save(self, descriptor: DccGjrGarchMarketProviderConfig) -> None:
        """Persist post-fit state to the `.npz` archive named by the
        descriptor's `trained_blob` so the runtime can skip re-fitting at
        startup. Symmetric to `DccGjrGarch.load(descriptor)`."""
        np.savez_compressed(
            descriptor.trained_blob,
            mu=self.mu,
            omega=self.omega,
            alpha=self.alpha,
            gamma=self.gamma,
            beta=self.beta,
            dcc_a=np.array(self.dcc_a),
            dcc_b=np.array(self.dcc_b),
            q_bar=self.q_bar,
            sigma_last=self.sigma_last,
            z_last=self.z_last,
            q_last=self.q_last,
            factor_names=np.array(self.factor_names, dtype=object),
        )

    @staticmethod
    def load(descriptor: DccGjrGarchMarketProviderConfig) -> DccGjrGarch:
        with np.load(descriptor.trained_blob, allow_pickle=True) as data:
            factor_names = tuple(str(name) for name in data["factor_names"])
            model = DccGjrGarch(config=DccGjrGarchConfig())
            model.mu = np.asarray(data["mu"])
            model.omega = np.asarray(data["omega"])
            model.alpha = np.asarray(data["alpha"])
            model.gamma = np.asarray(data["gamma"])
            model.beta = np.asarray(data["beta"])
            model.dcc_a = float(data["dcc_a"])
            model.dcc_b = float(data["dcc_b"])
            model.q_bar = np.asarray(data["q_bar"])
            model.sigma_last = np.asarray(data["sigma_last"])
            model.z_last = np.asarray(data["z_last"])
            model.q_last = np.asarray(data["q_last"])
            model.factor_names = factor_names
            model.n_factors = len(factor_names)
        return model

    def simulate(self, n_paths: int, n_months: int, seed: int) -> Scenarios:
        rng = np.random.default_rng(seed)
        n_factors = self.n_factors

        sigma2 = np.broadcast_to(self.sigma_last**2, (n_paths, n_factors)).copy()
        z_prev = np.broadcast_to(self.z_last, (n_paths, n_factors)).copy()
        eps_prev = np.broadcast_to(self.sigma_last * self.z_last, (n_paths, n_factors)).copy()
        q = np.broadcast_to(self.q_last, (n_paths, n_factors, n_factors)).copy()

        log_returns = np.empty((n_paths, n_months, n_factors), dtype="float64")

        for step in range(n_months):
            indicator = (eps_prev < 0).astype("float64")
            sigma2 = (
                self.omega[None, :]
                + self.alpha[None, :] * eps_prev**2
                + self.gamma[None, :] * indicator * eps_prev**2
                + self.beta[None, :] * sigma2
            )
            sigma_t = np.sqrt(sigma2)

            q = (
                (1.0 - self.dcc_a - self.dcc_b) * self.q_bar[None, :, :]
                + self.dcc_a * np.einsum("ni,nj->nij", z_prev, z_prev)
                + self.dcc_b * q
            )
            d = np.sqrt(np.diagonal(q, axis1=1, axis2=2))
            r = q / np.einsum("ni,nj->nij", d, d)

            chol_r = np.linalg.cholesky(r + 1e-12 * np.eye(n_factors)[None, :, :])
            normal_draws = rng.standard_normal((n_paths, n_factors))
            z_t = np.einsum("nij,nj->ni", chol_r, normal_draws)

            eps_t = sigma_t * z_t
            r_t = self.mu[None, :] + eps_t
            log_returns[:, step, :] = r_t

            eps_prev = eps_t
            z_prev = z_t

        cum = np.concatenate([np.zeros((n_paths, 1, n_factors)), np.cumsum(log_returns, axis=1)], axis=1)
        return Scenarios(
            factor_names=self.factor_names or tuple(f"f{i}" for i in range(n_factors)),
            multipliers=np.exp(cum),
            seed=seed,
            label=self.label,
        )


class DccGjrGarchMarketProviderConfig(ApiModel):
    """Pre-trained DCC-GJR-GARCH provider config — points at the trained-state
    blob written by `bb run //augur/model/train:train`. The model is loaded at server
    startup; no fitting happens on the request path."""

    type: Literal["dcc_gjr_garch"] = "dcc_gjr_garch"
    trained_blob: Path = Field(description="Absolute path to the .npz produced by DccGjrGarch.save(descriptor).")
    latest_observations: dict[str, Any] = Field(
        description="Latest observed market state at the start of the simulation horizon (factor → value)."
    )
    current_mortgage30_rate_pct: float
    location_market_sources: LocationMarketSourcesConfig

    def realize(self, *, current_private_equity_price_usd: float) -> MarketBundleProvider:
        model = DccGjrGarch.load(self)
        return MacroMarketBundleProvider.from_loaded_model(
            model,
            latest_observations=self.latest_observations,
            current_mortgage30_rate_pct=self.current_mortgage30_rate_pct,
            current_private_equity_price_usd=current_private_equity_price_usd,
            location_market_sources=LocationMarketSources.from_config(self.location_market_sources),
            evidence_source_id=str(self.trained_blob),
        )
