"""The committed binding CRDs and kubeconform schemas are what `generate` writes (STYLE.md § Testing,
generated-output snapshot): regenerate with `bb run //agentplane/crds:generate_bin` and commit the
result when this fails.
"""

import re
from pathlib import Path

import pytest
import pytest_bazel
import yaml

from agentplane.crds.generate import CRD_FILES, CRDS_DIR, generated_files
from util.bazel.runfiles import get_required_path


def _committed(relative: Path) -> str:
    return get_required_path(f"_main/{relative}").read_text()


def test_committed_files_are_generated() -> None:
    for relative, content in generated_files({name: _committed(CRDS_DIR / name) for name in CRD_FILES}):
        assert content == _committed(relative), f"{relative} is stale"


@pytest.mark.parametrize(
    ("host", "valid"),
    [
        ("*", True),
        ("example.com", True),
        ("*.example.com", True),
        ("*example.com", False),
        ("example.*", False),
        ("**", False),
        ("", False),
    ],
)
def test_policy_host_schema_admits_only_supported_wildcards(host: str, valid: bool) -> None:
    crd = yaml.safe_load(_committed(CRDS_DIR / "crd-egresspolicies.yaml"))
    for version in crd["spec"]["versions"]:
        rule = version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["rules"]["items"]
        pattern = rule["properties"]["hosts"]["items"]["pattern"]
        assert bool(re.fullmatch(pattern, host)) is valid


if __name__ == "__main__":
    pytest_bazel.main()
