from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from ember.integrations.gitea import GiteaRepository

from .definitions import ScenarioSuite
from .steps import ScenarioSuiteResult


class RunLabels(BaseModel):
    run_id: str
    image: str
    managed: bool = True

    def namespace_labels(self) -> dict[str, str]:
        return {
            "ember.run/id": self.run_id,
            "ember.run/managed": str(self.managed).lower(),
            "ember.run/image": self.image,
        }

    def pod_labels(self, release: str) -> dict[str, str]:
        labels = self.namespace_labels().copy()
        labels["ember.run/release"] = release
        return labels


class RuntimeSecretNames(BaseModel):
    matrix: str
    gitea: str
    rspcache: str

    def to_projection(self) -> dict[str, str]:
        return {
            "matrix": self.matrix,
            "gitea": self.gitea,
            "rspcache": self.rspcache,
        }


@dataclass(frozen=True)
class EvalRunRequest:
    run_id: str
    namespace: str
    release: str
    labels: RunLabels
    matrix_base_url: str
    matrix_access_token: str
    gitea_token: str
    gitea_base_url: str
    gitea_repo: GiteaRepository
    gitea_username: str | None
    rspcache_api_base: str
    rspcache_api_key: str
    suite_key: str
    suite: ScenarioSuite
    preserve: bool
    artifact_dir: Path
    secrets: RuntimeSecretNames
    image: str
    matrix_room_id: str | None
    ember_user_id: str


class EvalRunMetadata(BaseModel):
    run_id: str
    namespace: str
    release: str
    image: str
    suite_key: str
    suite_name: str | None = None
    suite_version: str | None = None
    labels: RunLabels
    secrets: RuntimeSecretNames
    started_at: str
    status: str
    ready_at: str | None = None
    failed_at: str | None = None
    error: str | None = None


class EvalRunErrorReport(BaseModel):
    metadata: EvalRunMetadata
    scenarios: ScenarioSuiteResult | None = None
