"""Test: no orphaned YAML files (every file referenced by a kustomization)."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.validation.cluster import ParsedCluster


def test_no_orphaned_files(cluster: ParsedCluster, k8s_dir: Path) -> None:
    referenced: set[Path] = set()
    for kust in cluster.kustomize_files.values():
        referenced.update(kust.resources)
        referenced.update(kust.patches)
        for resource in kust.resources:
            if resource.is_dir():
                referenced.add(resource / "kustomization.yaml")

    orphaned = sorted(
        yaml_file.relative_to(k8s_dir)
        for yaml_file in cluster.all_yaml_files
        if yaml_file.name != "kustomization.yaml" and yaml_file not in referenced
    )
    assert not orphaned, "Orphaned files not referenced by any kustomization:\n" + "\n".join(f"  {f}" for f in orphaned)


if __name__ == "__main__":
    pytest_bazel.main()
