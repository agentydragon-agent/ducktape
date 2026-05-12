from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass

from augur.model.markets.market_model import MarketModel
from augur.model.markets.scenarios import HistoricalSeries


def _summarise_scores(scores: list[float]) -> tuple[float, float, float]:
    """Return (total, per_origin, mean_se) for a list of per-origin log-densities.

    `mean_se` is the sample-stdev / √n estimate, NaN when n < 2 (single
    observation; SE undefined). Used by rolling-origin and multi-step
    scorers; held-out single-split summary just sums.
    """
    n = len(scores)
    total = float(sum(scores))
    per_origin = total / n
    mean_se = statistics.stdev(scores) / math.sqrt(n) if n > 1 else float("nan")
    return total, per_origin, mean_se


@dataclass(frozen=True)
class HeldOutLogDensity:
    """Held-out predictive log-density score for one model on one historical series.

    `total` and `per_month` are `None` when the model returned None for any
    held-out month (i.e. it cannot expose a density). `unscored_reason`
    records why.

    `per_factor_total` / `per_factor_per_month`: per-factor marginal
    univariate log-densities aggregated over the held-out window. Useful
    to localise where a model's joint score comes from. Sums of marginal
    scores do **not** equal the joint score in general — cross-asset
    correlations live in the off-diagonal of the joint covariance and
    don't appear in the marginals. `None` when the model declines to
    expose marginals (e.g. block bootstrap).
    """

    model_label: str
    train_end: int
    held_out_count: int
    total: float | None
    per_month: float | None
    per_factor_total: dict[str, float] | None
    per_factor_per_month: dict[str, float] | None
    unscored_reason: str | None


def held_out_predictive_log_density(
    model: MarketModel, historical: HistoricalSeries, *, train_fraction: float = 0.8
) -> HeldOutLogDensity:
    """Fit `model` on the first `train_fraction` of months, then sum
    `log_predictive_density` over the held-out months.

    The model only ever sees the training prefix during `fit`. During
    scoring, `log_predictive_density(historical, t)` is called with the full
    series and is expected to condition on `levels[:t+1]` to predict
    `levels[t+1]` — the model decides how it uses information past
    `train_end` (a Markov / state-space model conditions only on the
    immediate past; a frequentist VAR conditions on its lag window; a
    Bayesian posterior wrapper conditions on its sampled paths).
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(f"train_fraction must be in (0, 1); got {train_fraction}")
    n_steps = historical.levels.shape[0] - 1
    if n_steps < 2:
        raise ValueError("need at least two transitions to split into train and test")
    train_end = max(1, round(n_steps * train_fraction))
    if train_end >= n_steps:
        raise ValueError(
            f"train_fraction {train_fraction} leaves no held-out months (train_end={train_end}, n_steps={n_steps})"
        )

    train_series = HistoricalSeries(
        factor_names=historical.factor_names,
        levels=historical.levels[: train_end + 1],
        months=historical.months[: train_end + 1],
    )
    model.fit(train_series)

    held_out_count = n_steps - train_end
    log_densities: list[float] = []
    per_factor_totals: dict[str, float] = dict.fromkeys(historical.factor_names, 0.0)
    per_factor_supported = True
    for t in range(train_end, n_steps):
        density = model.log_predictive_density(historical, t)
        if density is None:
            return HeldOutLogDensity(
                model_label=model.label,
                train_end=train_end,
                held_out_count=held_out_count,
                total=None,
                per_month=None,
                per_factor_total=None,
                per_factor_per_month=None,
                unscored_reason=f"{model.label}.log_predictive_density returned None at t={t}",
            )
        log_densities.append(density)
        if per_factor_supported:
            marginals = model.log_predictive_marginals(historical, t)
            if marginals is None:
                per_factor_supported = False
            else:
                for name, value in marginals.items():
                    per_factor_totals[name] += float(value)

    total = float(sum(log_densities))
    if per_factor_supported:
        per_factor_total = per_factor_totals
        per_factor_per_month = {name: value / held_out_count for name, value in per_factor_totals.items()}
    else:
        per_factor_total = None
        per_factor_per_month = None
    return HeldOutLogDensity(
        model_label=model.label,
        train_end=train_end,
        held_out_count=held_out_count,
        total=total,
        per_month=total / held_out_count,
        per_factor_total=per_factor_total,
        per_factor_per_month=per_factor_per_month,
        unscored_reason=None,
    )


@dataclass(frozen=True)
class RollingOriginLogDensity:
    """Rolling-origin one-step-ahead predictive log-density.

    Refits the model at each origin `t ∈ [min_train, n_steps)` (optionally
    only every `refit_every` steps) and scores the one-step-ahead density
    `log p(r_{t+1} | r_{1:t+1})`. Compared to the single 80/20 split this
    yields ~50× more evaluation points on a 117-month series, shrinking
    the per-month standard error by √(n_eval / 23).

    `mean_se` is the standard error of `per_month`, computed from the
    variance of the per-origin log-densities.
    """

    model_label: str
    min_train: int
    refit_every: int
    n_origins: int
    total: float | None
    per_month: float | None
    mean_se: float | None
    per_factor_total: dict[str, float] | None
    per_factor_per_month: dict[str, float] | None
    unscored_reason: str | None


def rolling_origin_predictive_log_density(
    model_factory: Callable[[], MarketModel], historical: HistoricalSeries, *, min_train: int = 60, refit_every: int = 1
) -> RollingOriginLogDensity:
    """Refit at each origin `t ∈ [min_train, n_steps)` (every `refit_every`
    steps to control cost on slow-fitting models like DCC-GARCH) and score
    the one-step-ahead predictive density at `t`.

    `model_factory()` must return a fresh `MarketModel` instance — fits are
    independent and state must reset.
    """
    if min_train < 2:
        raise ValueError(f"min_train must be >= 2; got {min_train}")
    if refit_every < 1:
        raise ValueError(f"refit_every must be >= 1; got {refit_every}")
    n_steps = historical.levels.shape[0] - 1
    if min_train >= n_steps:
        raise ValueError(f"min_train {min_train} leaves no held-out months (n_steps={n_steps})")

    label_holder = model_factory().label

    fit_cache: MarketModel | None = None
    fit_origin: int | None = None  # last origin at which fit_cache was refit
    log_densities: list[float] = []
    per_factor_totals: dict[str, float] = dict.fromkeys(historical.factor_names, 0.0)
    per_factor_supported = True

    for t in range(min_train, n_steps):
        # Refit cadence: t == min_train, min_train + refit_every, ...
        if fit_cache is None or (t - min_train) % refit_every == 0:
            fit_cache = model_factory()
            train_series = HistoricalSeries(
                factor_names=historical.factor_names,
                levels=historical.levels[: t + 1],
                months=historical.months[: t + 1],
            )
            fit_cache.fit(train_series)
            fit_origin = t

        density = fit_cache.log_predictive_density(historical, t)
        if density is None:
            return RollingOriginLogDensity(
                model_label=label_holder,
                min_train=min_train,
                refit_every=refit_every,
                n_origins=t - min_train,
                total=None,
                per_month=None,
                mean_se=None,
                per_factor_total=None,
                per_factor_per_month=None,
                unscored_reason=(
                    f"{label_holder}.log_predictive_density returned None at t={t} (fit at origin {fit_origin})"
                ),
            )
        log_densities.append(density)
        if per_factor_supported:
            marginals = fit_cache.log_predictive_marginals(historical, t)
            if marginals is None:
                per_factor_supported = False
            else:
                for name, value in marginals.items():
                    per_factor_totals[name] += float(value)

    total, per_month, mean_se = _summarise_scores(log_densities)
    n_origins = len(log_densities)

    if per_factor_supported:
        per_factor_total = per_factor_totals
        per_factor_per_month = {name: value / n_origins for name, value in per_factor_totals.items()}
    else:
        per_factor_total = None
        per_factor_per_month = None

    return RollingOriginLogDensity(
        model_label=label_holder,
        min_train=min_train,
        refit_every=refit_every,
        n_origins=n_origins,
        total=total,
        per_month=per_month,
        mean_se=mean_se,
        per_factor_total=per_factor_total,
        per_factor_per_month=per_factor_per_month,
        unscored_reason=None,
    )


@dataclass(frozen=True)
class MultiStepLogDensityRow:
    horizon_months: int
    n_origins: int
    total: float | None
    per_origin: float | None
    mean_se: float | None
    unscored_reason: str | None


@dataclass(frozen=True)
class MultiStepLogDensity:
    """Multi-step (cumulative h-month) predictive log-density per horizon.

    For each origin t in the held-out window and each horizon h in
    `horizons`, score the joint log-density of `Σ_{k=1..h} r_{t+k}` under
    the model's `log_predictive_density_at_horizon(historical, t, h)`.
    Reveals structural differences (vol clustering, cointegration pull,
    cascade dynamics) that single-step density smooths over.
    """

    model_label: str
    train_end: int
    horizons: tuple[int, ...]
    rows: tuple[MultiStepLogDensityRow, ...]


def multi_step_predictive_log_density(
    model: MarketModel,
    historical: HistoricalSeries,
    *,
    horizons: tuple[int, ...] = (1, 6, 12),
    train_fraction: float = 0.8,
) -> MultiStepLogDensity:
    """Fit `model` on the first `train_fraction` of months, then score
    `log_predictive_density_at_horizon(historical, t, h)` at every origin
    `t` in the held-out window such that `t + h ≤ n_steps`."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(f"train_fraction must be in (0, 1); got {train_fraction}")
    if not horizons:
        raise ValueError("horizons must be non-empty")
    n_steps = historical.levels.shape[0] - 1
    train_end = max(1, round(n_steps * train_fraction))
    if train_end >= n_steps:
        raise ValueError(
            f"train_fraction {train_fraction} leaves no held-out months (train_end={train_end}, n_steps={n_steps})"
        )

    train_series = HistoricalSeries(
        factor_names=historical.factor_names,
        levels=historical.levels[: train_end + 1],
        months=historical.months[: train_end + 1],
    )
    model.fit(train_series)

    horizon_rows: list[MultiStepLogDensityRow] = []
    for h in horizons:
        scores: list[float] = []
        unscored_reason: str | None = None
        for t in range(train_end, n_steps - h + 1):
            value = model.log_predictive_density_at_horizon(historical, t, h)
            if value is None:
                unscored_reason = f"{model.label}.log_predictive_density_at_horizon returned None at t={t}, h={h}"
                break
            scores.append(value)
        if unscored_reason is not None or not scores:
            horizon_rows.append(
                MultiStepLogDensityRow(
                    horizon_months=h,
                    n_origins=0,
                    total=None,
                    per_origin=None,
                    mean_se=None,
                    unscored_reason=unscored_reason or f"no origins available for horizon {h}",
                )
            )
            continue
        total, per_origin, mean_se = _summarise_scores(scores)
        n_origins = len(scores)
        horizon_rows.append(
            MultiStepLogDensityRow(
                horizon_months=h,
                n_origins=n_origins,
                total=total,
                per_origin=per_origin,
                mean_se=mean_se,
                unscored_reason=None,
            )
        )

    return MultiStepLogDensity(
        model_label=model.label, train_end=train_end, horizons=tuple(horizons), rows=tuple(horizon_rows)
    )
