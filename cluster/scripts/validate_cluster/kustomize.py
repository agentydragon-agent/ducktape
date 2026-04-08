"""Kustomize runtime: build execution using kustomize binary."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from cluster.scripts.validate_cluster.tool_resolve import resolve_tool
from cluster.validation.k8s import parse_k8s_resources
from cluster.validation.kustomize import KustomizeBuildResult


class KustomizeBuildError(Exception):
    """Raised when kustomize build fails."""

    def __init__(self, kustomization_path: Path, error: str) -> None:
        self.kustomization_path = kustomization_path
        super().__init__(f"kustomize build failed for {kustomization_path.parent}: {error}")


async def run_kustomize_build(kustomization_path: Path) -> KustomizeBuildResult:
    """Run kustomize build and parse the output. Raises KustomizeBuildError on failure."""
    kustomize_bin = resolve_tool("kustomize", "multitool/tools/kustomize/kustomize")
    proc = await asyncio.create_subprocess_exec(
        kustomize_bin,
        "build",
        kustomization_path.parent,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise KustomizeBuildError(kustomization_path, stderr.decode())

    output = stdout.decode()
    resources = parse_k8s_resources(yaml.safe_load_all(output))

    return KustomizeBuildResult(kustomization_path=kustomization_path, resources=resources)
