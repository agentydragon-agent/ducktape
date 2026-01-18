"""Validate all SealedSecrets can be decrypted with terraform keypair.

Uses kubeseal --recovery-unseal (works offline, no cluster needed).

Run via Bazel: bazel run //cluster/scripts:validate_sealed_secrets
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cluster.scripts.runfiles_util import resolve_path

_KUBESEAL_BIN = resolve_path("multitool/tools/kubeseal/kubeseal")
_TOFU_BIN = resolve_path("multitool/tools/tofu/tofu")


def get_repo_root() -> Path:
    """Get the cluster repository root directory."""
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        return Path(workspace) / "cluster"
    return Path(__file__).parent.parent


def get_private_key_from_terraform(tf_dir: Path) -> str | None:
    """Extract sealed_secrets_private_key_pem from terraform state."""
    state_file = tf_dir / "terraform.tfstate"
    if not state_file.exists():
        return None

    result = subprocess.run(
        [_TOFU_BIN, "output", "-raw", "sealed_secrets_private_key_pem"],
        check=False,
        cwd=tf_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not read sealed_secrets_private_key_pem from terraform state: {result.stderr}")
    return result.stdout


def find_sealed_secrets(k8s_dir: Path) -> list[Path]:
    """Find all SealedSecret YAML files."""
    sealed_secrets = []
    for yaml_file in k8s_dir.rglob("*sealed*.yaml"):
        try:
            content = yaml_file.read_text()
            if "kind: SealedSecret" in content:
                sealed_secrets.append(yaml_file)
        except OSError:
            continue
    return sealed_secrets


def validate_sealed_secret(sealed_secret_path: Path, private_key_path: Path) -> tuple[bool, str]:
    """Validate a single SealedSecret can be decrypted."""
    result = subprocess.run(
        [_KUBESEAL_BIN, "--recovery-unseal", "--recovery-private-key", private_key_path],
        check=False,
        stdin=sealed_secret_path.open("rb"),
        capture_output=True,
    )
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.decode().strip()


def main() -> int:
    repo_root = get_repo_root()
    tf_dir = repo_root / "terraform" / "00-persistent-auth"
    k8s_dir = repo_root / "k8s"

    if not (tf_dir / "terraform.tfstate").exists():
        print(f"⚠️  No terraform state found at {tf_dir}/terraform.tfstate")
        print("   Skipping SealedSecret validation (state not initialized)")
        return 0

    private_key = get_private_key_from_terraform(tf_dir)
    if not private_key:
        print("⚠️  Could not read private key from terraform state")
        print(f"   Run 'tofu apply' in {tf_dir} first")
        return 1

    sealed_secrets = find_sealed_secrets(k8s_dir)
    if not sealed_secrets:
        print("✅ No SealedSecret files found")
        return 0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
        f.write(private_key)
        private_key_path = Path(f.name)

    try:
        failed = 0
        for sealed_secret in sealed_secrets:
            success, error = validate_sealed_secret(sealed_secret, private_key_path)
            if success:
                print(f"✅ {sealed_secret}")
            else:
                print(f"❌ {sealed_secret}")
                print(f"   Error: {error}")
                failed += 1

        if failed > 0:
            print()
            print("ERROR: Some SealedSecrets cannot be decrypted with the terraform keypair")
            print(f"Run 'cd {tf_dir} && tofu apply' to re-seal")
            return 1

        print()
        print(f"✅ All {len(sealed_secrets)} SealedSecrets validated successfully")
        return 0

    finally:
        private_key_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
