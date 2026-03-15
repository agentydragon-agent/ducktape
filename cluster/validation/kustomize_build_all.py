"""Build all kustomizations and serialize results to JSON.

Runs kustomize build in parallel on all kustomization.yaml files found in the
cluster k8s directory, and writes the results as a JSON array to a file.
This allows downstream checks to consume the output without re-running kustomize.

Usage:
  bazel run //cluster/validation:kustomize_build_all -- <k8s-dir> <output-json>
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from cluster.validation.cluster import parse_cluster
from cluster.validation.k8s import parse_k8s_resources
from cluster.validation.kustomize import KustomizeBuildResult
from util.bazel.runfiles import get_required_path


async def _run_kustomize_build(kustomization_path: Path) -> KustomizeBuildResult:
    """Run kustomize build and parse the output."""
    kustomize_bin = get_required_path("multitool/tools/kustomize/kustomize")
    proc = await asyncio.create_subprocess_exec(
        kustomize_bin,
        "build",
        kustomization_path.parent,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return KustomizeBuildResult(kustomization_path=kustomization_path, success=False, error=stderr.decode())

    output = stdout.decode()
    resources = parse_k8s_resources(yaml.safe_load_all(output))
    return KustomizeBuildResult(kustomization_path=kustomization_path, success=True, resources=resources)


async def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <k8s-dir> <output-json-path>", file=sys.stderr)
        return 1

    k8s_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    cluster = parse_cluster(k8s_dir)

    kustomization_files = list(cluster.kustomize_files)
    if not kustomization_files:
        print(f"No kustomizations found in {k8s_dir}", file=sys.stderr)
        output_path.write_text("[]")
        return 0

    tasks = [_run_kustomize_build(k) for k in kustomization_files]
    results = await asyncio.gather(*tasks)

    # Relativize kustomization_path to k8s_dir for portability
    for r in results:
        r.kustomization_path = r.kustomization_path.relative_to(k8s_dir)

    adapter = TypeAdapter(list[KustomizeBuildResult])
    output_path.write_text(adapter.dump_json(results, indent=2).decode())

    failures = [r for r in results if not r.success]
    if failures:
        for r in failures:
            print(f"FAIL: {r.kustomization_path.parent}: {r.error.strip()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
