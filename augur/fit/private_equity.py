"""Train compact private-equity exogenous models from sparse JSONL observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import Field

from augur.model.schemas import StrictModel
from augur.model.trained_private_equity import TrainedPrivateEquityModelArtifact

_DAYS_PER_MONTH = 365.2425 / 12


class PriceObservation(StrictModel):
    type: Literal["price_observation"]
    issuer_id: str = Field(min_length=1)
    observed_at: date
    kind: Literal["tender_price", "ppu_mark"]
    price_usd_per_share: float = Field(gt=0)
    uncertainty_log_sigma: float = Field(gt=0)
    source_id: str = Field(min_length=1)
    notes: str = ""


class PrivateEquityTrainingPriors(StrictModel):
    min_monthly_log_return_sigma: float = Field(default=0.03, gt=0)
    student_t_nu: float = Field(default=5.0, gt=2)
    tender_interval_months_median_prior: float = Field(default=12.0, gt=0)
    tender_interval_log_sigma: float = Field(default=0.35, gt=0)
    tender_price_log_discount_mu: float = 0.0
    tender_price_log_discount_sigma: float = Field(default=0.08, ge=0)


class PrivateEquityTrainingConfig(StrictModel):
    issuer_id: str = Field(min_length=1)
    observations_path: str
    out_model_path: str
    as_of_date: date | None = None
    priors: PrivateEquityTrainingPriors = Field(default_factory=PrivateEquityTrainingPriors)


def load_price_observations_jsonl(path: Path) -> list[PriceObservation]:
    observations: list[PriceObservation] = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                observation_type = payload.get("type") if isinstance(payload, dict) else None
                if observation_type != "price_observation":
                    raise ValueError(f"unsupported observation type {observation_type!r}")
                observation = PriceObservation.model_validate(payload)
            except Exception as error:
                raise ValueError(f"{path} line {line_number}: {error}") from error
            observations.append(observation)
    if not observations:
        raise ValueError(f"{path} contains no price observations")
    return observations


def load_training_config(path: Path) -> PrivateEquityTrainingConfig:
    return PrivateEquityTrainingConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def fit_private_equity_model(
    observations: list[PriceObservation], config: PrivateEquityTrainingConfig
) -> TrainedPrivateEquityModelArtifact:
    issuer_observations = sorted(
        [observation for observation in observations if observation.issuer_id == config.issuer_id],
        key=lambda observation: observation.observed_at,
    )
    if len(issuer_observations) != len(observations):
        issuers = sorted({observation.issuer_id for observation in observations})
        raise ValueError(f"training config issuer_id={config.issuer_id!r} but observations include issuers {issuers}")
    if len(issuer_observations) < 2:
        raise ValueError("private-equity training needs at least two price observations")

    mark_observations = [observation for observation in issuer_observations if observation.kind == "ppu_mark"]
    if not mark_observations:
        raise ValueError("private-equity training needs at least one ppu_mark observation")
    current_mark = max(mark_observations, key=lambda observation: observation.observed_at)
    as_of_date = config.as_of_date or current_mark.observed_at
    if as_of_date < current_mark.observed_at:
        raise ValueError(
            f"as_of_date {as_of_date.isoformat()} cannot be before latest ppu_mark "
            f"{current_mark.observed_at.isoformat()}"
        )

    times = np.array(
        [_months_between(issuer_observations[0].observed_at, obs.observed_at) for obs in issuer_observations]
    )
    log_prices = np.log(np.array([obs.price_usd_per_share for obs in issuer_observations], dtype=np.float64))
    obs_sigmas = np.array([obs.uncertainty_log_sigma for obs in issuer_observations], dtype=np.float64)
    monthly_mu = _weighted_slope(times, log_prices, obs_sigmas)
    monthly_sigma = _monthly_sigma(
        times, log_prices, monthly_mu, obs_sigmas, config.priors.min_monthly_log_return_sigma
    )

    tender_observations = [observation for observation in issuer_observations if observation.kind == "tender_price"]
    tender_interval_median = _tender_interval_months_median(
        tender_observations, prior=config.priors.tender_interval_months_median_prior
    )
    last_tender = max((observation.observed_at for observation in tender_observations), default=None)

    return TrainedPrivateEquityModelArtifact(
        issuer_id=config.issuer_id,
        as_of_date=as_of_date,
        current_mark_usd=current_mark.price_usd_per_share,
        monthly_log_return_mu=monthly_mu,
        monthly_log_return_sigma=monthly_sigma,
        student_t_nu=config.priors.student_t_nu,
        tender_interval_months_median=tender_interval_median,
        tender_interval_log_sigma=config.priors.tender_interval_log_sigma,
        tender_price_log_discount_mu=config.priors.tender_price_log_discount_mu,
        tender_price_log_discount_sigma=config.priors.tender_price_log_discount_sigma,
        last_tender_observed_at=last_tender,
        evidence_digest=_evidence_digest(issuer_observations),
        provenance={
            "observation_count": len(issuer_observations),
            "tender_price_observation_count": len(tender_observations),
            "ppu_mark_observation_count": len(mark_observations),
            "source_ids": sorted({observation.source_id for observation in issuer_observations}),
        },
    )


def train_from_config(config_path: Path) -> TrainedPrivateEquityModelArtifact:
    config = load_training_config(config_path)
    base_dir = config_path.parent
    observations_path = _resolve_path(config.observations_path, base_dir)
    out_model_path = _resolve_path(config.out_model_path, base_dir)
    artifact = fit_private_equity_model(load_price_observations_jsonl(observations_path), config)
    out_model_path.parent.mkdir(parents=True, exist_ok=True)
    out_model_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return artifact


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a compact private-equity exogenous model.")
    parser.add_argument("--config", required=True, type=Path, help="Training YAML path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    artifact = train_from_config(args.config.resolve())
    print(f"trained private-equity model issuer={artifact.issuer_id} as_of={artifact.as_of_date.isoformat()}")
    print(f"current mark: ${artifact.current_mark_usd:,.2f}")
    print(f"evidence digest: {artifact.evidence_digest}")
    return 0


def _resolve_path(path: str | Path, base_dir: Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return (base_dir / value).resolve()


def _months_between(start: date, end: date) -> float:
    return (end - start).days / _DAYS_PER_MONTH


def _weighted_slope(times_months: np.ndarray, log_prices: np.ndarray, obs_sigmas: np.ndarray) -> float:
    if np.any(np.diff(times_months) <= 0):
        raise ValueError("price observations must have distinct increasing observed_at dates")
    weights = 1.0 / np.square(obs_sigmas)
    design = np.column_stack([np.ones_like(times_months), times_months])
    weighted_design = design * np.sqrt(weights[:, None])
    weighted_y = log_prices * np.sqrt(weights)
    _, slope = np.linalg.lstsq(weighted_design, weighted_y, rcond=None)[0]
    return float(slope)


def _monthly_sigma(
    times_months: np.ndarray, log_prices: np.ndarray, monthly_mu: float, obs_sigmas: np.ndarray, floor: float
) -> float:
    durations = np.diff(times_months)
    returns = np.diff(log_prices)
    residuals = (returns - monthly_mu * durations) / np.sqrt(durations)
    empirical = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else float(abs(residuals[0]))
    observation_noise_floor = float(np.median(obs_sigmas) / math.sqrt(max(float(np.median(durations)), 1.0)))
    return max(empirical, observation_noise_floor, floor)


def _tender_interval_months_median(observations: list[PriceObservation], *, prior: float) -> float:
    if len(observations) < 2:
        return float(prior)
    dates = [observation.observed_at for observation in sorted(observations, key=lambda obs: obs.observed_at)]
    intervals = np.array([_months_between(start, end) for start, end in pairwise(dates)])
    intervals = intervals[intervals > 0]
    if intervals.size == 0:
        return float(prior)
    # Light shrinkage keeps sparse/ambiguous tender histories from overfitting one short gap.
    return float((np.median(intervals) * intervals.size + prior) / (intervals.size + 1))


def _evidence_digest(observations: list[PriceObservation]) -> str:
    payload = [observation.model_dump(mode="json") for observation in observations]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
