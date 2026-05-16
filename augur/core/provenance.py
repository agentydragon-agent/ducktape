from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


def stable_identity_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(_json_stable(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def path_set_id(
    *,
    market_model_id: str,
    market_model_version_id: str,
    scenario_generator_id: str,
    scenario_generator_version_id: str,
    evidence_set_id: str,
    calibration_artifact_id: str,
    risk_factor_set_id: str,
    seed: int,
    rollout_count: int,
    horizon_months: int,
    event_stream_ids: Sequence[str],
) -> str:
    digest = stable_identity_digest(
        {
            "market_model_id": market_model_id,
            "market_model_version_id": market_model_version_id,
            "scenario_generator_id": scenario_generator_id,
            "scenario_generator_version_id": scenario_generator_version_id,
            "evidence_set_id": evidence_set_id,
            "calibration_artifact_id": calibration_artifact_id,
            "risk_factor_set_id": risk_factor_set_id,
            "seed": seed,
            "rollout_count": rollout_count,
            "horizon_months": horizon_months,
            "event_stream_ids": tuple(event_stream_ids),
        }
    )
    return f"path_set:{digest}"


def exogenous_path_id(*, path_set_id: str, rollout_index: int) -> str:
    return f"{path_set_id}:path:{rollout_index}"


def policy_program_set_id(*, scenario_id: str, policies: Sequence[Any]) -> str:
    digest = stable_identity_digest(
        {"scenario_id": scenario_id, "policies": tuple(_model_dump(policy) for policy in policies)}
    )
    return f"policy_program_set:{digest}"


def scenario_input_id(scenario: Any) -> str:
    digest = stable_identity_digest(_model_dump(scenario))
    return f"scenario_input:{digest}"


def projection_trajectory_id(
    *, scenario_id: str, scenario_input_id: str, exogenous_path_id: str, policy_program_set_id: str
) -> str:
    digest = stable_identity_digest(
        {
            "scenario_id": scenario_id,
            "scenario_input_id": scenario_input_id,
            "exogenous_path_id": exogenous_path_id,
            "policy_program_set_id": policy_program_set_id,
        }
    )
    return f"trajectory:{digest}"


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _json_stable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_stable(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_stable(inner) for key, inner in value.items()}
    if isinstance(value, tuple | list):
        return [_json_stable(inner) for inner in value]
    return value
