"""Model-agnostic sanity checks for sampled exogenous trajectories."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from pydantic import Field, TypeAdapter, model_validator

from augur.model.exogenous import ExogenousSamplingRequest, validate_sample_satisfies_request
from augur.model.exogenous_provider_config import (
    CompositeExogenousProviderConfig,
    ExogenousProviderConfig,
    StateSpaceExogenousProviderConfig,
    TrainedPrivateEquityProviderConfig,
    VecmExogenousProviderConfig,
)
from augur.model.schemas import FrozenModel
from util.bazel.runfiles import get_required_path

_ADAPTER: TypeAdapter[ExogenousProviderConfig] = TypeAdapter(ExogenousProviderConfig)


class PercentileBound(FrozenModel):
    percentile: float = Field(ge=0.0, le=100.0)
    month: int = Field(ge=0)
    lower: float | None = None
    upper: float | None = None


class PercentileRangeBound(FrozenModel):
    lower_percentile: float = Field(ge=0.0, le=100.0)
    upper_percentile: float = Field(ge=0.0, le=100.0)
    month: int = Field(ge=0)
    lower: float
    upper: float

    @model_validator(mode="after")
    def _validate_ordering(self) -> PercentileRangeBound:
        if self.lower_percentile > self.upper_percentile:
            raise ValueError("lower_percentile must be <= upper_percentile")
        if self.lower > self.upper:
            raise ValueError("lower must be <= upper")
        return self


class EventCountPercentileBound(FrozenModel):
    percentile: float = Field(ge=0.0, le=100.0)
    lower: float | None = None
    upper: float | None = None


class EventCountPercentileRangeBound(FrozenModel):
    lower_percentile: float = Field(ge=0.0, le=100.0)
    upper_percentile: float = Field(ge=0.0, le=100.0)
    lower: float
    upper: float

    @model_validator(mode="after")
    def _validate_ordering(self) -> EventCountPercentileRangeBound:
        if self.lower_percentile > self.upper_percentile:
            raise ValueError("lower_percentile must be <= upper_percentile")
        if self.lower > self.upper:
            raise ValueError("lower must be <= upper")
        return self


class LevelSeriesSanityCheck(FrozenModel):
    series_id: str
    initial_value: float | None = None
    initial_atol: float = Field(default=1e-6, ge=0.0)
    initial_rtol: float = Field(default=1e-9, ge=0.0)
    require_positive: bool = True
    value_percentile_bounds: tuple[PercentileBound, ...] = ()
    value_percentile_ranges: tuple[PercentileRangeBound, ...] = ()
    ratio_percentile_bounds: tuple[PercentileBound, ...] = ()
    ratio_percentile_ranges: tuple[PercentileRangeBound, ...] = ()


class EventSeriesSanityCheck(FrozenModel):
    event_id: str
    active_count_percentile_bounds: tuple[EventCountPercentileBound, ...] = ()
    active_count_percentile_ranges: tuple[EventCountPercentileRangeBound, ...] = ()


class SampleSanitySpec(FrozenModel):
    provider_config_path: Path
    horizon_months: int = Field(ge=0)
    rollout_seed_start: int = Field(default=1301, ge=0)
    rollout_count: int = Field(gt=0)
    required_level_series: tuple[str, ...] = ()
    required_event_series: tuple[str, ...] = ()
    level_checks: tuple[LevelSeriesSanityCheck, ...] = ()
    event_checks: tuple[EventSeriesSanityCheck, ...] = ()

    @property
    def rollout_seeds(self) -> tuple[int, ...]:
        return tuple(range(self.rollout_seed_start, self.rollout_seed_start + self.rollout_count))


def run_sample_sanity_file(path: Path) -> None:
    spec = SampleSanitySpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    run_sample_sanity(spec, base_dir=path.parent)


def run_sample_sanity(spec: SampleSanitySpec, *, base_dir: Path) -> None:
    provider_config_path = _resolve_path(spec.provider_config_path, base_dir=base_dir)
    provider = _load_provider_config(provider_config_path)
    model = provider.realize_model()
    request = ExogenousSamplingRequest(
        horizon_months=spec.horizon_months,
        rollout_seeds=spec.rollout_seeds,
        required_level_series=frozenset(spec.required_level_series),
        required_event_series=frozenset(spec.required_event_series),
    )
    sampled = model.sample(request)
    validate_sample_satisfies_request(request, sampled)

    for level_check in spec.level_checks:
        levels = sampled.level_matrix(
            level_check.series_id, rollout_count=spec.rollout_count, horizon_months=spec.horizon_months
        )
        _assert_finite(levels, label=level_check.series_id)
        if level_check.require_positive and np.any(levels <= 0.0):
            raise AssertionError(f"series {level_check.series_id!r} produced non-positive level(s)")
        if level_check.initial_value is not None:
            np.testing.assert_allclose(
                levels[:, 0],
                np.full(spec.rollout_count, float(level_check.initial_value), dtype=np.float64),
                atol=level_check.initial_atol,
                rtol=level_check.initial_rtol,
                err_msg=f"series {level_check.series_id!r} month-0 anchor mismatch",
            )
        for value_bound in level_check.value_percentile_bounds:
            _check_percentile_bound(
                levels[:, value_bound.month], value_bound, label=f"{level_check.series_id} value m{value_bound.month}"
            )
        for value_range in level_check.value_percentile_ranges:
            _check_percentile_range_bound(
                levels[:, value_range.month], value_range, label=f"{level_check.series_id} value m{value_range.month}"
            )
        for ratio_bound in level_check.ratio_percentile_bounds:
            ratios = levels[:, ratio_bound.month] / levels[:, 0]
            _check_percentile_bound(ratios, ratio_bound, label=f"{level_check.series_id} ratio m{ratio_bound.month}/m0")
        for ratio_range in level_check.ratio_percentile_ranges:
            ratios = levels[:, ratio_range.month] / levels[:, 0]
            _check_percentile_range_bound(
                ratios, ratio_range, label=f"{level_check.series_id} ratio m{ratio_range.month}/m0"
            )

    for event_check in spec.event_checks:
        events = sampled.event_matrix(
            event_check.event_id, rollout_count=spec.rollout_count, horizon_months=spec.horizon_months
        )
        active_counts = events.astype(np.int64).sum(axis=1)
        for active_count_bound in event_check.active_count_percentile_bounds:
            value = float(np.percentile(active_counts, active_count_bound.percentile))
            _assert_bound(
                value,
                lower=active_count_bound.lower,
                upper=active_count_bound.upper,
                label=f"{event_check.event_id} active-count p{active_count_bound.percentile:g}",
            )
        for active_count_range in event_check.active_count_percentile_ranges:
            _check_percentile_count_range_bound(
                active_counts, active_count_range, label=f"{event_check.event_id} active-count"
            )


def _load_provider_config(path: Path) -> ExogenousProviderConfig:
    provider = _ADAPTER.validate_python(yaml.safe_load(path.read_text(encoding="utf-8")))
    return _anchor_provider_paths(provider, base_dir=path.parent)


def _anchor_provider_paths(provider: ExogenousProviderConfig, *, base_dir: Path) -> ExogenousProviderConfig:
    if isinstance(provider, TrainedPrivateEquityProviderConfig):
        trained_model_path = _resolve_path(provider.trained_model_path, base_dir=base_dir)
        return provider.model_copy(update={"trained_model_path": trained_model_path})
    if isinstance(provider, StateSpaceExogenousProviderConfig):
        trained_artifact_path = _resolve_path(provider.trained_artifact_path, base_dir=base_dir)
        return provider.model_copy(update={"trained_artifact_path": trained_artifact_path})
    if isinstance(provider, VecmExogenousProviderConfig):
        trained_blob = (
            None if provider.trained_blob is None else _resolve_path(provider.trained_blob, base_dir=base_dir)
        )
        return provider.model_copy(update={"trained_blob": trained_blob})
    if isinstance(provider, CompositeExogenousProviderConfig):
        return provider.model_copy(
            update={
                "macro": _anchor_provider_paths(provider.macro, base_dir=base_dir),
                "private_equity": _anchor_provider_paths(provider.private_equity, base_dir=base_dir),
            }
        )
    return provider


def _resolve_path(path: Path, *, base_dir: Path) -> Path:
    runfile_prefix = "runfile:"
    path_text = str(path)
    if path_text.startswith(runfile_prefix):
        return get_required_path(path_text.removeprefix(runfile_prefix))
    return path if path.is_absolute() else (base_dir / path).resolve()


def _assert_finite(values: np.ndarray, *, label: str) -> None:
    if not np.all(np.isfinite(values)):
        raise AssertionError(f"{label} produced non-finite value(s)")


def _check_percentile_bound(values: np.ndarray, bound: PercentileBound, *, label: str) -> None:
    value = float(np.percentile(values, bound.percentile))
    _assert_bound(value, lower=bound.lower, upper=bound.upper, label=f"{label} p{bound.percentile:g}")


def _check_percentile_range_bound(values: np.ndarray, bound: PercentileRangeBound, *, label: str) -> None:
    lower_value = float(np.percentile(values, bound.lower_percentile))
    upper_value = float(np.percentile(values, bound.upper_percentile))
    _assert_range_bound(
        lower_value,
        upper_value,
        lower=bound.lower,
        upper=bound.upper,
        label=f"{label} p{bound.lower_percentile:g}..p{bound.upper_percentile:g}",
    )


def _check_percentile_count_range_bound(
    values: np.ndarray, bound: EventCountPercentileRangeBound, *, label: str
) -> None:
    lower_value = float(np.percentile(values, bound.lower_percentile))
    upper_value = float(np.percentile(values, bound.upper_percentile))
    _assert_range_bound(
        lower_value,
        upper_value,
        lower=bound.lower,
        upper=bound.upper,
        label=f"{label} p{bound.lower_percentile:g}..p{bound.upper_percentile:g}",
    )


def _assert_bound(value: float, *, lower: float | None, upper: float | None, label: str) -> None:
    if lower is not None and value < lower:
        raise AssertionError(f"{label}={value:g} is below lower bound {lower:g}")
    if upper is not None and value > upper:
        raise AssertionError(f"{label}={value:g} is above upper bound {upper:g}")


def _assert_range_bound(lower_value: float, upper_value: float, *, lower: float, upper: float, label: str) -> None:
    if lower_value < lower or upper_value > upper:
        raise AssertionError(
            f"{label}=[{lower_value:g}, {upper_value:g}] is outside expected range [{lower:g}, {upper:g}]"
        )
