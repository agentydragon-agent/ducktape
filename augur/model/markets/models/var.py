"""VAR(1) on monthly log-returns with Gaussian innovations.

  r_t   = c + A r_{t-1} + ε_t,    ε_t ~ N(0, Σ)

Fit by OLS over the historical log-return series. The predictive density
log p(r_t | r_{t-1}) is the multivariate normal log-pdf at r_t with mean
c + A r_{t-1} and covariance Σ. `simulate` rolls the recurrence forward
from the last observed log-return.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from augur.model.markets._density import gaussian_logpdf
from augur.model.markets.scenarios import HistoricalSeries, Scenarios, historical_log_returns


@dataclass(frozen=True)
class Var1Config:
    """VAR(1) Gaussian has no hyperparameters; an empty config keeps the
    `(model_cls, config)` registry shape uniform across models."""


def _zeros2() -> np.ndarray:
    return np.zeros((0, 0))


def _zeros1() -> np.ndarray:
    return np.zeros((0,))


@dataclass
class Var1Gaussian:
    label = "var1_gaussian"

    config: Var1Config = field(default_factory=Var1Config)

    # Parameters — empty until `fit()` runs.
    intercept: np.ndarray = field(default_factory=_zeros1)
    coef: np.ndarray = field(default_factory=_zeros2)
    inv_cov: np.ndarray = field(default_factory=_zeros2)
    cov_chol: np.ndarray = field(default_factory=_zeros2)
    cov_log_det: float = 0.0
    last_log_return: np.ndarray = field(default_factory=_zeros1)
    factor_names: tuple[str, ...] = ()

    def fit(self, historical: HistoricalSeries) -> None:
        log_returns = historical_log_returns(historical)
        if log_returns.shape[0] < 3:
            raise ValueError("VAR(1) needs at least three log-returns to fit (one lag pair + headroom)")
        n_factors = log_returns.shape[1]

        y = log_returns[1:]
        x_lag = log_returns[:-1]
        n_obs = y.shape[0]
        x_design = np.concatenate([np.ones((n_obs, 1)), x_lag], axis=1)
        beta, _, _, _ = np.linalg.lstsq(x_design, y, rcond=None)
        intercept = beta[0]
        coef = beta[1:].T

        residuals = y - (intercept + x_lag @ coef.T)
        dof = max(1, n_obs - (n_factors + 1))
        cov = (residuals.T @ residuals) / dof
        cov = (cov + cov.T) / 2 + np.eye(n_factors) * 1e-12

        sign, log_det = np.linalg.slogdet(cov)
        if sign <= 0:
            raise ValueError("residual covariance has non-positive determinant")

        self.intercept = intercept
        self.coef = coef
        self.inv_cov = np.linalg.inv(cov)
        self.cov_chol = np.linalg.cholesky(cov)
        self.cov_log_det = float(log_det)
        self.last_log_return = log_returns[-1].copy()
        self.factor_names = historical.factor_names

    def log_predictive_density(self, historical: HistoricalSeries, t: int) -> float | None:
        if t < 1:
            raise ValueError(f"VAR(1) predictive density needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        mu = self.intercept + self.coef @ log_returns[t - 1]
        return gaussian_logpdf(diff=log_returns[t] - mu, inv_cov=self.inv_cov, log_det=self.cov_log_det)

    def log_predictive_marginals(self, historical: HistoricalSeries, t: int) -> dict[str, float] | None:
        if t < 1:
            raise ValueError(f"VAR(1) predictive marginals need t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        r_t = log_returns[t]
        r_prev = log_returns[t - 1]
        mu = self.intercept + self.coef @ r_prev
        cov_diag = np.diag(np.linalg.inv(self.inv_cov))
        sd = np.sqrt(cov_diag)
        out: dict[str, float] = {}
        names = self.factor_names or tuple(f"f{i}" for i in range(r_t.shape[0]))
        for k, name in enumerate(names):
            diff = r_t[k] - mu[k]
            out[name] = float(-0.5 * (math.log(2 * math.pi) + 2 * math.log(sd[k]) + (diff / sd[k]) ** 2))
        return out

    def log_predictive_density_at_horizon(self, historical: HistoricalSeries, t: int, h: int) -> float | None:
        if h < 1:
            raise ValueError(f"h must be >= 1; got {h}")
        if t < 1:
            raise ValueError(f"VAR(1) needs t >= 1; got {t}")
        log_returns = historical_log_returns(historical)
        if t + h > log_returns.shape[0]:
            return None
        cov_residual = np.linalg.inv(self.inv_cov)
        return _var1_horizon_density(
            intercept=self.intercept,
            coef=self.coef,
            cov_residual=cov_residual,
            last_return=log_returns[t - 1],
            observed_cumulative=log_returns[t : t + h].sum(axis=0),
            h=h,
        )

    def simulate(self, n_paths: int, n_months: int, seed: int) -> Scenarios:
        n_factors = self.intercept.shape[0]
        rng = np.random.default_rng(seed)

        normal_steps = rng.standard_normal((n_paths, n_months, n_factors))
        innovations = normal_steps @ self.cov_chol.T

        log_returns = np.empty((n_paths, n_months, n_factors), dtype="float64")
        prev = np.broadcast_to(self.last_log_return, (n_paths, n_factors)).copy()
        for step in range(n_months):
            current = self.intercept + prev @ self.coef.T + innovations[:, step, :]
            log_returns[:, step, :] = current
            prev = current

        cum = np.concatenate([np.zeros((n_paths, 1, n_factors)), np.cumsum(log_returns, axis=1)], axis=1)
        return Scenarios(
            factor_names=self.factor_names or tuple(f"f{i}" for i in range(n_factors)),
            multipliers=np.exp(cum),
            seed=seed,
            label=self.label,
        )


def _var1_horizon_density(
    *,
    intercept: np.ndarray,
    coef: np.ndarray,
    cov_residual: np.ndarray,
    last_return: np.ndarray,
    observed_cumulative: np.ndarray,
    h: int,
) -> float | None:
    """Closed-form log-density of Σ_{k=1..h} r_{t+k} under
        r_{t+k} = intercept + coef @ r_{t+k-1} + ε_{t+k},  ε ~ N(0, cov_residual)
    given r_t = `last_return`. Returns None when the cumulative covariance is
    not positive definite (numerical fallback)."""
    n_factors = intercept.shape[0]

    a_powers = [np.eye(n_factors)]
    for _ in range(h):
        a_powers.append(coef @ a_powers[-1])

    cumulative_mean = np.zeros(n_factors)
    accumulated_a_power_c = np.zeros(n_factors)
    for k in range(1, h + 1):
        accumulated_a_power_c = accumulated_a_power_c + a_powers[k - 1] @ intercept
        cumulative_mean = cumulative_mean + accumulated_a_power_c + a_powers[k] @ last_return

    cov_cumulative = np.zeros((n_factors, n_factors))
    for s in range(1, h + 1):
        # `sum(<generator>)` defaults to int 0 for empty iterables, so mypy
        # widens the result to `int | ndarray`; the loop range guarantees at
        # least one term, so cast for the matmul.
        m_s = np.asarray(sum(a_powers[m] for m in range(h - s + 1)))
        cov_cumulative = cov_cumulative + m_s @ cov_residual @ m_s.T

    cov_cumulative = (cov_cumulative + cov_cumulative.T) / 2 + np.eye(n_factors) * 1e-12
    sign, log_det = np.linalg.slogdet(cov_cumulative)
    if sign <= 0 or not math.isfinite(log_det):
        return None
    inv_cov = np.linalg.inv(cov_cumulative)
    diff = observed_cumulative - cumulative_mean
    quad = float(diff @ inv_cov @ diff)
    return float(-0.5 * (n_factors * math.log(2 * math.pi) + log_det + quad))
