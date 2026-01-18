"""Terraform/OpenTofu validation with tfmirror.dev network mirror.

Run via Bazel: bazel run //cluster/scripts:validate_tofu -- <module_directory>
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cluster.scripts.runfiles_util import resolve_path

_TOFU_BIN = resolve_path("multitool/tools/tofu/tofu")

_TOFU_CONFIG = """\
provider_installation {
  network_mirror {
    url = "https://tfmirror.dev/"
  }
}
"""


def get_repo_root() -> Path:
    """Get the cluster repository root directory."""
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        return Path(workspace) / "cluster"
    return Path(__file__).parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_tofu.py <module_directory>", file=sys.stderr)
        print("  module_directory: relative path from cluster/ (e.g., terraform/00-persistent-auth)")
        return 1

    module_rel = sys.argv[1]
    repo_root = get_repo_root()
    module_dir = repo_root / module_rel

    if not module_dir.is_dir():
        print(f"Error: module directory not found: {module_dir}", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tofurc", delete=False) as f:
        f.write(_TOFU_CONFIG)
        config_path = Path(f.name)

    env = os.environ.copy()
    env["TF_CLI_CONFIG_FILE"] = str(config_path)

    try:
        print(f"Initializing terraform in {module_dir}...")
        result = subprocess.run(
            [_TOFU_BIN, "init", "-backend=false", "-input=false", "-no-color"], cwd=module_dir, env=env, check=False
        )
        if result.returncode != 0:
            print("Error: tofu init failed", file=sys.stderr)
            return result.returncode

        print("Validating terraform configuration...")
        result = subprocess.run([_TOFU_BIN, "validate", "-no-color"], cwd=module_dir, env=env, check=False)
        if result.returncode != 0:
            print("Error: tofu validate failed", file=sys.stderr)
            return result.returncode

        print("Validation successful!")
        return 0

    finally:
        config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
