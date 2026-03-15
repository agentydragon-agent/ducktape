"""Test: all authentik blueprint YAML files listed in configMapGenerator."""

from __future__ import annotations

import pytest_bazel
import yaml

from util.bazel.runfiles import get_required_path


def test_authentik_blueprint_completeness() -> None:
    k8s_dir = get_required_path("_main/cluster/k8s/kustomization.yaml").parent
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

    assert not unlisted, "\n".join(
        f"Authentik blueprint not listed in configMapGenerator: {name}. "
        f"Add 'blueprints/{name}' to the authentik-sso-blueprints files list "
        f"in k8s/authentik/kustomization.yaml."
        for name in unlisted
    )


if __name__ == "__main__":
    pytest_bazel.main()
