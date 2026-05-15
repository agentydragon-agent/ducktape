"""Load aligned monthly log-returns for the market factors.

`load_evidence(...)` is the single entry point. It returns a typed
`(HistoricalSeries, MarketEvidence)` tuple. Tries the Yahoo-SPY + Zillow
loader (`augur.model.market_data.load_market_evidence`) first; falls
back to a FRED-only synthesised `MarketEvidence` when those LFS sources
are unreadable.

`load_historical(...)` is a thin wrapper for the metric harness, which
only needs `HistoricalSeries`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from augur.core.schemas import SourceDataConfig
from augur.model.location_market_sources import LocationMarketSources
from augur.model.market_data import (
    MarketEvidence,
    PeriodReturns,
    calibrate_market_path_priors,
    load_market_evidence,
    resolve_path,
)
from augur.model.markets.scenarios import HistoricalSeries

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "joint_config.example.json"


def load_evidence(config_path: Path | None = None) -> tuple[HistoricalSeries, MarketEvidence]:
    """Load the full `MarketEvidence` and a derived `HistoricalSeries`.

    Tries the Yahoo+Zillow `load_market_evidence`; on JSON / OS / value
    errors (e.g. LFS pointer files) falls back to a FRED-only
    synthesised `MarketEvidence`.
    """
    path = (config_path or DEFAULT_CONFIG_PATH).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    try:
        evidence = load_market_evidence(config, path.parent)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(
            f"markets.data: load_market_evidence failed ({exc!r}); falling back to FRED-only synthesised evidence.",
            file=sys.stderr,
        )
        return _evidence_fred_only(config, path.parent)
    return _historical_from_evidence(evidence), evidence


def load_historical(config_path: Path | None = None) -> HistoricalSeries:
    return load_evidence(config_path)[0]


# ---------------------------------------------------------------------------
# Internals.
# ---------------------------------------------------------------------------


def _read_fred_csv(path: Path, column: str) -> pd.Series:
    frame = pd.read_csv(path)
    if "observation_date" not in frame.columns or column not in frame.columns:
        raise ValueError(f"{path} must contain observation_date and {column}")
    dates = pd.to_datetime(frame["observation_date"], errors="raise")
    values = pd.to_numeric(frame[column], errors="coerce")
    series = pd.Series(values.to_numpy(dtype="float64"), index=dates).dropna()
    series = series[series > 0]
    if series.empty:
        raise ValueError(f"{path} contains no positive observations for {column}")
    return series.sort_index()


def _monthly_last(series: pd.Series) -> pd.Series:
    assert isinstance(series.index, pd.DatetimeIndex), f"expected DatetimeIndex, got {type(series.index).__name__}"
    out = series.groupby(series.index.to_period("M")).last().dropna()
    return out[out > 0]


def _historical_from_evidence(evidence: MarketEvidence) -> HistoricalSeries:
    return _historical_from_log_returns(
        evidence.factor_names, evidence.monthly_log_returns, evidence.monthly_return_months
    )


def _evidence_fred_only(config: dict[str, Any], base_dir: Path) -> tuple[HistoricalSeries, MarketEvidence]:
    """Read only FRED CSVs (no Yahoo, no Zillow) and synthesise a
    `MarketEvidence` matching the production loader's shape with what we
    can construct: SP500 from FRED price-level (no dividends), Case-Shiller
    SF for housing, FRED rent CPI, FRED US CPI, FRED 30-year mortgage."""
    source = SourceDataConfig.model_validate(config.get("source_data"))
    market_sources = LocationMarketSources.from_config(config)
    home_factor_names = tuple(dict.fromkeys(market_sources.home_value.values()))
    market_factors = ("sp500", *home_factor_names, "rent", "inflation")
    sp500_path = resolve_path(source.fred_sp500_csv, base_dir)
    home_path = resolve_path(source.fred_sfxrsa_csv, base_dir)
    rent_path = resolve_path(source.fred_sf_rent_cpi_csv, base_dir)
    cpi_path = resolve_path(source.fred_cpi_us_csv, base_dir)
    mortgage_path = resolve_path(source.fred_mortgage30_csv, base_dir)

    sp500 = _monthly_last(_read_fred_csv(sp500_path, "SP500"))
    home = _monthly_last(_read_fred_csv(home_path, "SFXRSA"))
    rent = _monthly_last(_read_fred_csv(rent_path, "CUURA422SEHA"))
    cpi = _monthly_last(_read_fred_csv(cpi_path, "CPIAUCSL"))
    mortgage = _read_fred_csv(mortgage_path, "MORTGAGE30US")

    aligned = pd.concat(
        {"sp500": sp500, **dict.fromkeys(home_factor_names, home), "rent": rent, "inflation": cpi}, axis=1, join="inner"
    ).dropna()
    if len(aligned) < 36:
        raise ValueError(f"only {len(aligned)} aligned months across the FRED fallback series")

    monthly_log_returns = np.diff(np.log(aligned.loc[:, list(market_factors)].to_numpy(dtype="float64")), axis=0)
    return_months = tuple(str(period) for period in aligned.index[1:])
    historical = _historical_from_log_returns(market_factors, monthly_log_returns, return_months)

    durations = np.ones_like(monthly_log_returns[:, 0])
    marginal = {
        name: PeriodReturns(log_returns=monthly_log_returns[:, idx], duration_months=durations)
        for idx, name in enumerate(market_factors)
    }
    market_path_calibration, calibrated_market_path_priors = calibrate_market_path_priors(market_factors, marginal)
    latest_observations: dict[str, Any] = {
        "sp500_price_latest": {
            "date": str(sp500.index[-1]),
            "value": float(sp500.iloc[-1]),
            "source": str(sp500_path.name),
        },
        "case_shiller_sf_latest": {
            "date": str(home.index[-1]),
            "value": float(home.iloc[-1]),
            "source": str(home_path.name),
        },
        "case_shiller_home_value_latest_by_factor": {
            factor_name: {"date": str(home.index[-1]), "value": float(home.iloc[-1]), "source": str(home_path.name)}
            for factor_name in home_factor_names
        },
        "sf_rent_cpi_latest": {
            "date": str(rent.index[-1]),
            "value": float(rent.iloc[-1]),
            "source": str(rent_path.name),
        },
        "cpi_latest": {"date": str(cpi.index[-1]), "value": float(cpi.iloc[-1]), "source": str(cpi_path.name)},
        "mortgage30_latest": {
            "date": mortgage.index[-1].date().isoformat(),
            "value": float(mortgage.iloc[-1]),
            "source": str(mortgage_path.name),
        },
        "data_path_note": "FRED-only fallback (Yahoo SPY / Zillow ZHVI unreadable)",
    }
    evidence = MarketEvidence(
        factor_names=market_factors,
        monthly_log_returns=monthly_log_returns,
        monthly_return_months=return_months,
        marginal_returns=marginal,
        market_path_calibration=market_path_calibration,
        calibrated_market_path_priors=calibrated_market_path_priors,
        current_mortgage30_rate_pct=float(mortgage.iloc[-1]),
        latest_observations=latest_observations,
    )
    return historical, evidence


def _historical_from_log_returns(
    factor_names: tuple[str, ...], monthly_log_returns: np.ndarray, return_months: tuple[str, ...]
) -> HistoricalSeries:
    n_factors = monthly_log_returns.shape[1]
    cum = np.concatenate([np.zeros((1, n_factors)), np.cumsum(monthly_log_returns, axis=0)], axis=0)
    levels = np.exp(cum)
    first_period = pd.Period(return_months[0], freq="M") - 1
    months = (str(first_period), *tuple(return_months))
    return HistoricalSeries(factor_names=factor_names, levels=levels, months=months)
