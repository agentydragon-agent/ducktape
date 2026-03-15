"""Test: all authentik blueprint YAML files listed in configMapGenerator."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel
import yaml

pytest_plugins = ["cluster.scripts.validate_cluster.conftest"]


def test_authentik_blueprint_completeness(k8s_dir: Path) -> None:
    authentik_kust = k8s_dir / "authentik" / "kustomization.yaml"
    blueprints_dir = k8s_dir / "authentik" / "blueprints"

    with authentik_kust.open() as f:
        doc = yaml.safe_load(f)

    listed_files: set[str] = set()
    for generator in doc.get("configMapGenerator", []):
        if generator.get("name") == "authentik-sso-blueprints":
            listed_files = {f.split("/")[-1] for f in generator.get("files", [])}
            break

    on_disk = {p.name for p in blueprints_dir.glob("*.yaml")}
    unlisted = sorted(on_disk - listed_files)

    assert not unlisted, "Authentik blueprints not listed in configMapGenerator:\n" + "\n".join(
        f"  {name} — add 'blueprints/{name}' to authentik-sso-blueprints files list" for name in unlisted
    )


if __name__ == "__main__":
    pytest_bazel.main()
