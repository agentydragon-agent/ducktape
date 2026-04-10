"""bbr: wrapper around `bb remote` with sane defaults for this repo.

Validates git state, forwards CI secrets, sets RBE runner properties, and
appends --config=rbe. See devinfra/docs/bb_remote_internals.md for how
bb remote works under the hood.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pygit2

_RUNNER_PROPERTIES = {
    "EstimatedFreeDiskBytes": "50000000000",
    "EstimatedComputeUnits": "4",
    "workload-isolation-type": "firecracker",
    "init-dockerd": "true",
}

_INVOCATION_ID_DIR = Path.home() / ".cache" / "bbr"
_INVOCATION_ID_FILE = _INVOCATION_ID_DIR / "last_invocation_id"


def _validate_git_state(repo: pygit2.Repository) -> None:
    """Abort if the default branch has unpushed commits.

    bb remote selects the local HEAD as the base commit. If that commit
    doesn't exist on the remote, the runner fails during git fetch.
    """
    if repo.head_is_detached:
        return

    current_branch = repo.head.shorthand

    origin_head = repo.references.get("refs/remotes/origin/HEAD")
    if origin_head is None:
        # CI (actions/checkout) doesn't set origin/HEAD — skip validation.
        return
    default_branch = origin_head.resolve().shorthand.removeprefix("origin/")

    if current_branch != default_branch:
        return

    try:
        local_oid = repo.references[f"refs/heads/{default_branch}"].resolve().target
    except KeyError:
        return
    try:
        remote_oid = repo.references[f"refs/remotes/origin/{default_branch}"].resolve().target
    except KeyError:
        return

    if local_oid != remote_oid:
        print(
            f"bbr: aborting — {default_branch} has unpushed commits (local {local_oid} != origin {remote_oid}).",
            file=sys.stderr,
        )
        print("bbr: push first or use a feature branch.", file=sys.stderr)
        sys.exit(1)


def _read_rbe_image(repo_root: Path) -> str:
    """Read devinfra/image_pins.json and return 'image@digest'."""
    pins = json.loads((repo_root / "devinfra" / "image_pins.json").read_text())
    entry = pins["rbe_worker"]
    return f"{entry['image']}@{entry['digest']}"


def _env_override(key: str, value: str) -> str:
    """Build a --remote_run_header flag that sets an env var on the runner."""
    return f"--remote_run_header=x-buildbuddy-platform.env-overrides={key}={value}"


def _build_secret_args() -> list[str]:
    """Build --remote_run_header and --env flags from CI secret env vars."""
    args: list[str] = []

    # DUCKTAPE_DOCKER_CLIENT_KEY is already base64-encoded — forward as-is.
    # The docker_mtls pytest fixture on the RBE worker decodes it and
    # assembles DOCKER_HOST / DOCKER_TLS_VERIFY / DOCKER_CERT_PATH.
    if dk_b64 := os.environ.get("DUCKTAPE_DOCKER_CLIENT_KEY"):
        args.append(_env_override("DUCKTAPE_DOCKER_CLIENT_KEY", dk_b64))

    if ghcr_token := os.environ.get("GHCR_TOKEN"):
        args.append(_env_override("GHCR_TOKEN", ghcr_token))

    if ghcr_username := os.environ.get("GHCR_USERNAME"):
        args.append(f"--env=GHCR_USERNAME={ghcr_username}")

    if gh_release_pat := os.environ.get("GH_RELEASE_PAT"):
        args.append(_env_override("GH_RELEASE_PAT", gh_release_pat))

    return args


def _find_bb() -> str:
    """Locate the bb binary on PATH."""
    if path := shutil.which("bb"):
        return path
    print("bbr: 'bb' not found on PATH.", file=sys.stderr)
    sys.exit(1)


def build_command(repo: pygit2.Repository, user_args: list[str]) -> list[str]:
    """Assemble the full bb remote command line."""
    repo_root = Path(repo.workdir)
    rbe_image = _read_rbe_image(repo_root)
    secret_args = _build_secret_args()
    bb = _find_bb()

    _INVOCATION_ID_DIR.mkdir(parents=True, exist_ok=True)

    return [
        bb,
        "remote",
        f"--invocation_id_file={_INVOCATION_ID_FILE}",
        *[f"--runner_exec_properties={k}={v}" for k, v in _RUNNER_PROPERTIES.items()],
        f"--container_image=docker://{rbe_image}",
        *secret_args,
        *user_args,
        "--config=rbe",
    ]


def _print_post_run_summary() -> None:
    """Print invocation ID and useful commands after bb remote completes."""
    try:
        inv_id = _INVOCATION_ID_FILE.read_text().strip()
    except OSError:
        return
    if not inv_id:
        return
    print(f"bbr: invocation {inv_id}", file=sys.stderr)
    print(f"bbr:   targets:  bbapi target {inv_id}", file=sys.stderr)
    print(f"bbr:   logs:     bbapi target log {inv_id} <target>", file=sys.stderr)
    print(f"bbr:   artifacts: bbapi artifact {inv_id}", file=sys.stderr)
    print(f"bbr:   details:  bbapi invocation {inv_id}", file=sys.stderr)


def main() -> None:
    args = sys.argv[1:]

    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    repo = pygit2.Repository(".")
    _validate_git_state(repo)
    cmd = build_command(repo, args)

    if dry_run:
        print(" ".join(cmd))
        return

    result = subprocess.run(cmd, check=False)
    _print_post_run_summary()
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
