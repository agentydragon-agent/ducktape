"""Validate Helm templates can render without errors.

Finds Cilium values files via runfiles and runs helm template dry-run.

Run via Bazel: bazel run //cluster/scripts:validate_helm_templates
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path

from cluster.scripts.runfiles_util import resolve_path

_HELM_BIN = resolve_path("multitool/tools/helm/helm")
_CILIUM_VALUES_RLOCATIONS = ["_main/cluster/terraform/01-infrastructure/cilium-values.yaml"]


def _get_values_files() -> list[Path]:
    """Get cilium values files from runfiles."""
    values_files = []
    for rlocation in _CILIUM_VALUES_RLOCATIONS:
        with contextlib.suppress(RuntimeError):
            values_files.append(resolve_path(rlocation))
    return values_files


def validate_helm_template(values_file: Path) -> tuple[bool, str]:
    """Validate a Helm chart can render with the given values file."""
    result = subprocess.run(
        [_HELM_BIN, "template", "test-release", "cilium/cilium", "-f", values_file, "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.strip()


def ensure_cilium_repo() -> bool:
    """Ensure the Cilium Helm repo is added."""
    result = subprocess.run([_HELM_BIN, "repo", "list", "-o", "json"], check=False, capture_output=True, text=True)
    if result.returncode == 0 and "cilium" in result.stdout:
        return True

    result = subprocess.run(
        [_HELM_BIN, "repo", "add", "cilium", "https://helm.cilium.io/"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ Failed to add Cilium Helm repo: {result.stderr}")
        return False

    result = subprocess.run([_HELM_BIN, "repo", "update"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠️  Failed to update Helm repos: {result.stderr}")

    return True


def main() -> int:
    values_files = _get_values_files()
    if not values_files:
        print("✅ No Cilium values files found")
        return 0

    if not ensure_cilium_repo():
        return 1

    failed = 0
    for values_file in values_files:
        success, error = validate_helm_template(values_file)
        if success:
            print(f"✅ {values_file}")
        else:
            print(f"❌ {values_file}")
            print(f"   Error: {error}")
            failed += 1

    if failed > 0:
        print()
        print(f"ERROR: {failed} Helm template(s) failed validation")
        return 1

    print()
    print(f"✅ All {len(values_files)} Helm templates validated successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
