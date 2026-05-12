from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HistoricalSeries:
    factor_names: tuple[str, ...]
    levels: np.ndarray
    months: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.levels.ndim != 2:
            raise ValueError(f"levels must be 2-D (T+1, F); got shape {self.levels.shape}")
        if self.levels.shape[1] != len(self.factor_names):
            raise ValueError(
                f"levels has {self.levels.shape[1]} factor columns but factor_names has {len(self.factor_names)}"
            )
        if self.levels.shape[0] != len(self.months):
            raise ValueError(f"levels has {self.levels.shape[0]} time rows but months has {len(self.months)}")
        if self.levels.shape[0] < 2:
            raise ValueError("HistoricalSeries needs at least two time rows")
        if not np.all(self.levels > 0):
            raise ValueError("levels must be strictly positive")


@dataclass(frozen=True)
class Scenarios:
    factor_names: tuple[str, ...]
    multipliers: np.ndarray
    seed: int
    label: str

    def __post_init__(self) -> None:
        if self.multipliers.ndim != 3:
            raise ValueError(f"multipliers must be 3-D (n_paths, n_months+1, F); got shape {self.multipliers.shape}")
        if self.multipliers.shape[2] != len(self.factor_names):
            raise ValueError(
                f"multipliers has {self.multipliers.shape[2]} factor columns but factor_names has {len(self.factor_names)}"
            )
        if self.multipliers.shape[1] < 2:
            raise ValueError("Scenarios needs at least two time steps")
        if not np.all(self.multipliers > 0):
            raise ValueError("multipliers must be strictly positive")


def historical_log_returns(historical: HistoricalSeries) -> np.ndarray:
    """diff(log(levels), axis=time) → (T, F)."""
    return np.diff(np.log(historical.levels), axis=0)


def scenario_log_returns(scenarios: Scenarios) -> np.ndarray:
    """diff(log(multipliers), axis=time) → (n_paths, n_months, F)."""
    return np.diff(np.log(scenarios.multipliers), axis=1)
