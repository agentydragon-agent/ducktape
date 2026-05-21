"""Load aligned monthly log-returns for the exogenous factors.

`load_evidence(...)` returns a typed `(HistoricalSeries, ExogenousEvidence)`
tuple from parsed `EvidenceConfig` plus configured Yahoo-SPY, Zillow, and
FRED source data. Config/source-data errors propagate by default. Callers
that intentionally want lower-fidelity FRED-only synthesised evidence
must opt in with `fred_only=True` or `load_fred_only_evidence(...)`.

`load_historical(...)` is a thin wrapper for the metric harness, which
only needs `HistoricalSeries`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from augur.fit.evidence_config import EvidenceConfig, load_evidence_config
from augur.fit.evidence_data import (
    ExogenousEvidence,
    PeriodReturns,
    calibrate_series_path_priors,
    load_exogenous_evidence,
    resolve_path,
)
from augur.model.location_series_sources import LocationSeriesSources
from augur.model.path_models.scenarios import HistoricalSeries

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "model" / "train" / "config" / "exogenous_evidence.example.json"
)


def load_evidence(
    config: EvidenceConfig, base_dir: Path, *, fred_only: bool = False
) -> tuple[HistoricalSeries, ExogenousEvidence]:
    """Load the full `ExogenousEvidence` and a derived `HistoricalSeries`.

    The default path loads the configured Yahoo+Zillow+FRED exogenous
    evidence and lets malformed config or unreadable source data raise.
    `fred_only=True` is an explicit lower-fidelity fixture/degraded mode;
    its evidence metadata is labelled as synthesized.
    """
    if fred_only:
        return _evidence_fred_only(config, base_dir)
    evidence = load_exogenous_evidence(config.source_data, base_dir)
    return _historical_from_evidence(evidence), evidence


def load_evidence_from_path(
    config_path: Path | None = None, *, fred_only: bool = False
) -> tuple[HistoricalSeries, ExogenousEvidence]:
    path = (config_path or DEFAULT_CONFIG_PATH).resolve()
    return load_evidence(load_evidence_config(path), path.parent, fred_only=fred_only)


def load_fred_only_evidence(config: EvidenceConfig, base_dir: Path) -> tuple[HistoricalSeries, ExogenousEvidence]:
    """Load explicitly selected FRED-only synthesized exogenous evidence."""
    return load_evidence(config, base_dir, fred_only=True)


def load_historical(config_path: Path | None = None, *, fred_only: bool = False) -> HistoricalSeries:
    return load_evidence_from_path(config_path, fred_only=fred_only)[0]


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


def _historical_from_evidence(evidence: ExogenousEvidence) -> HistoricalSeries:
    return _historical_from_log_returns(
        evidence.factor_names, evidence.monthly_log_returns, evidence.monthly_return_months
    )


def _evidence_fred_only(config: EvidenceConfig, base_dir: Path) -> tuple[HistoricalSeries, ExogenousEvidence]:
    """Read only FRED CSVs (no Yahoo, no Zillow) and synthesise a
    `ExogenousEvidence` matching the production loader's shape with what we
    can construct: SP500 from FRED price-level (no dividends), Case-Shiller
    SF for housing, FRED rent CPI, FRED US CPI, FRED 30-year mortgage."""
    source = config.source_data
    series_sources = LocationSeriesSources.from_config(config.location_series_sources)
    home_factor_names = tuple(dict.fromkeys(series_sources.home_value.values()))
    factor_names = ("sp500", *home_factor_names, "rent", "inflation")
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
        raise ValueError(f"only {len(aligned)} aligned months across the FRED-only synthesized series")

    monthly_log_returns = np.diff(np.log(aligned.loc[:, list(factor_names)].to_numpy(dtype="float64")), axis=0)
    return_months = tuple(str(period) for period in aligned.index[1:])
    historical = _historical_from_log_returns(factor_names, monthly_log_returns, return_months)

    durations = np.ones_like(monthly_log_returns[:, 0])
    marginal = {
        name: PeriodReturns(log_returns=monthly_log_returns[:, idx], duration_months=durations)
        for idx, name in enumerate(factor_names)
    }
    series_path_calibration, calibrated_series_path_priors = calibrate_series_path_priors(factor_names, marginal)
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
        "evidence_mode": {
            "mode": "fred_only_synthesized",
            "explicit": True,
            "description": "FRED-only synthesized evidence explicitly selected; Yahoo SPY and Zillow ZHVI were not loaded.",
        },
    }
    evidence = ExogenousEvidence(
        factor_names=factor_names,
        monthly_log_returns=monthly_log_returns,
        monthly_return_months=return_months,
        marginal_returns=marginal,
        series_path_calibration=series_path_calibration,
        calibrated_series_path_priors=calibrated_series_path_priors,
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
