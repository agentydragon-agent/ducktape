"""Pin the safe Crossplane source-update canary to a CI-validated repository revision."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

CANARY_ROOT = "tf/gitops/crossplane-source-update-canary"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _is_commit(repo: Path, revision: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode == 0


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def _is_opentofu_input(path: str) -> bool:
    return path.endswith((".tf", ".tf.json", ".tfvars", ".tfvars.json"))


def changed_inputs(repo: Path, *, current_pin: str, before: str, candidate: str) -> list[str]:
    """Return OpenTofu input files changed since the pin, or since `before` initially."""
    if _is_commit(repo, current_pin):
        # A queued older CI run must not move the source pin backwards.
        if _is_ancestor(repo, candidate, current_pin):
            return []
        base = current_pin
    else:
        base = before

    if not _is_commit(repo, base) or not _is_commit(repo, candidate):
        raise ValueError(f"source revisions must exist locally: {base=} {candidate=}")

    result = _git(repo, "diff", "--name-only", base, candidate, "--", CANARY_ROOT)
    return [path for path in result.stdout.splitlines() if _is_opentofu_input(path)]


def pin_source(repo: Path, *, pin_file: Path, before: str, candidate: str) -> list[str]:
    current_pin = pin_file.read_text().strip()
    changed = changed_inputs(repo, current_pin=current_pin, before=before, candidate=candidate)
    if changed:
        pin_file.write_text(f"{candidate}\n")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--pin-file", type=Path, required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    pin_file = args.pin_file if args.pin_file.is_absolute() else args.repo / args.pin_file
    changed = pin_source(args.repo, pin_file=pin_file, before=args.before, candidate=args.candidate)
    output = f"changed={'true' if changed else 'false'}\n"
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with Path(github_output).open("a") as stream:
            stream.write(output)
    print(f"{output.strip()} files={','.join(changed)}")


if __name__ == "__main__":
    main()
