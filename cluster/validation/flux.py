"""Flux domain: models and parsing."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class DependsOn(BaseModel):
    """Flux Kustomization dependency reference."""

    model_config = ConfigDict(extra="ignore")

    name: str
    namespace: str | None = None


class HealthCheck(BaseModel):
    """Flux Kustomization health check reference."""

    model_config = ConfigDict(extra="ignore")

    kind: str = ""
    name: str = ""
    namespace: str = ""


class FluxKustomization(BaseModel):
    """Parsed flux-kustomization.yaml Kustomization CR."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    file_path: Path
    spec_path: str = Field(default="", alias="path")
    depends_on: list[DependsOn] = Field(default=[], alias="dependsOn")
    health_checks: list[HealthCheck] = Field(default=[], alias="healthChecks")


def parse_flux_kustomization(flux_file: Path) -> list[FluxKustomization]:
    """Parse a flux-kustomization.yaml file (may contain multiple documents)."""
    results = []
    with flux_file.open() as f:
        for doc in yaml.safe_load_all(f):
            if not doc:
                continue
            if doc.get("kind") != "Kustomization":
                continue
            if not doc.get("apiVersion", "").startswith("kustomize.toolkit.fluxcd.io"):
                continue

            metadata = doc.get("metadata", {}) or {}
            name = metadata.get("name", "")
            if not name:
                continue

            spec = doc.get("spec", {}) or {}
            results.append(FluxKustomization.model_validate({"name": name, "file_path": flux_file, **spec}))

    return results


