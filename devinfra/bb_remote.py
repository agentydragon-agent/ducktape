"""bb-remote: wrapper around `bb remote` with sane defaults for this repo.

Validates git state, forwards CI secrets, sets RBE runner properties, and
appends --config=rbe. See devinfra/docs/bb_remote_internals.md for how
bb remote works under the hood.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pygit2

_RUNNER_EXEC_PROPERTIES = [
    "--runner_exec_properties=EstimatedFreeDiskBytes=50000000000",
    "--runner_exec_properties=workload-isolation-type=firecracker",
    "--runner_exec_properties=init-dockerd=true",
]


def _open_repo() -> pygit2.Repository:
    """Open the git repo containing cwd."""
    return pygit2.Repository(".")


def _validate_git_state(repo: pygit2.Repository) -> None:
    """Abort if the default branch has unpushed commits.

    bb remote selects the local HEAD as the base commit. If that commit
    doesn't exist on the remote, the runner fails during git fetch.
    """
    # Skip on detached HEAD.
    if repo.head_is_detached:
        return

    current_branch = repo.head.shorthand

    # Determine default branch from origin/HEAD (fallback: devel).
    try:
        origin_head = repo.references.get("refs/remotes/origin/HEAD")
        if origin_head is None:
            raise KeyError
        default_branch = origin_head.resolve().shorthand.removeprefix("origin/")
    except (KeyError, pygit2.GitError):
        default_branch = "devel"

    if current_branch != default_branch:
        return

    # Compare local vs remote SHA.
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
            f"bb-remote: aborting — {default_branch} has unpushed commits (local {local_oid} != origin {remote_oid}).",
            file=sys.stderr,
        )
        print("bb-remote: push first or use a feature branch.", file=sys.stderr)
        sys.exit(1)


def _read_rbe_image(repo_root: Path) -> str:
    """Read devinfra/image_pins.json and return 'image@digest'."""
    pins = json.loads((repo_root / "devinfra" / "image_pins.json").read_text())
    entry = pins["rbe_worker"]
    return f"{entry['image']}@{entry['digest']}"


def _build_secret_args() -> list[str]:
    """Build --remote_run_header and --env flags from CI secret env vars."""
    args: list[str] = []

    # DUCKTAPE_DOCKER_CLIENT_KEY is already base64-encoded — forward as-is.
    # The docker_mtls pytest fixture on the RBE worker decodes it and
    # assembles DOCKER_HOST / DOCKER_TLS_VERIFY / DOCKER_CERT_PATH.
    if dk_b64 := os.environ.get("DUCKTAPE_DOCKER_CLIENT_KEY"):
        args.append(f"--remote_run_header=x-buildbuddy-platform.env-overrides=DUCKTAPE_DOCKER_CLIENT_KEY={dk_b64}")

    if ghcr_token := os.environ.get("GHCR_TOKEN"):
        args.append(f"--remote_run_header=x-buildbuddy-platform.env-overrides=GHCR_TOKEN={ghcr_token}")
        args.append(f"--env=GHCR_USERNAME={os.environ.get('GHCR_USERNAME', 'agentydragon')}")

    if gh_release_pat := os.environ.get("GH_RELEASE_PAT"):
        args.append(f"--remote_run_header=x-buildbuddy-platform.env-overrides=GH_RELEASE_PAT={gh_release_pat}")

    return args


def _find_bb() -> str:
    """Locate the bb binary on PATH."""
    if path := shutil.which("bb"):
        return path
    print("bb-remote: 'bb' not found on PATH.", file=sys.stderr)
    sys.exit(1)


def build_command(repo: pygit2.Repository, user_args: list[str]) -> list[str]:
    """Assemble the full bb remote command line."""
    repo_root = Path(repo.workdir)
    rbe_image = _read_rbe_image(repo_root)
    secret_args = _build_secret_args()
    bb = _find_bb()

    return [
        bb,
        "remote",
        *_RUNNER_EXEC_PROPERTIES,
        f"--container_image=docker://{rbe_image}",
        *secret_args,
        *user_args,
        "--config=rbe",
    ]


def main() -> None:
    args = sys.argv[1:]

    # Extract wrapper-specific flags (before passthrough to bb remote).
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    repo = _open_repo()
    _validate_git_state(repo)
    cmd = build_command(repo, args)

    if dry_run:
        print(" ".join(cmd))
        return

    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
