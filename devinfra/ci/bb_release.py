#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic", "PyGithub", "pygit2"]
# ///
# Run standalone: uv run --project . devinfra/ci/bb_release.py
"""BB Release step: build dist, create GitHub releases for changed artifacts.

Expects: GH_RELEASE_PAT env var.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pygit2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from github import Auth, Github

from devinfra.ci.artifacts import ARTIFACTS, SOURCES_PATH, Sources, file_sha256

REPO = "agentydragon/ducktape"


def run(*cmd: str, **kwargs) -> None:
    subprocess.run(cmd, check=True, **kwargs)


def install_deps() -> None:
    # System deps for wheel builds only.
    run("sudo", "apt-get", "update", "-qq")
    run(
        "sudo",
        "apt-get",
        "install",
        "-y",
        "libcairo2-dev",
        "libgirepository-2.0-dev",
        "libdbus-1-dev",
        "libxcb1-dev",
        "pkg-config",
    )


def copy_artifact_to_dist(src_glob: str, dest: str) -> Path:
    src_path = Path(src_glob)
    matches = sorted(src_path.parent.glob(src_path.name))
    if not matches:
        raise FileNotFoundError(f"No files matching: {src_glob}")
    dest_path = Path(dest)
    if dest_path.is_dir():
        dest_path = dest_path / matches[0].name
    shutil.copy2(matches[0], dest_path)
    return dest_path


def main() -> None:
    repo_obj = pygit2.Repository(".")
    subject = repo_obj.head.peel(pygit2.Commit).message.splitlines()[0]
    if "[skip ci]" in subject:
        print("Commit message contains [skip ci], skipping release.")
        return

    gh_token = os.environ.get("GH_RELEASE_PAT")
    if not gh_token:
        raise RuntimeError("Missing required env var: GH_RELEASE_PAT (configure as a BuildBuddy Workflow secret)")

    install_deps()

    run("bazel", "build", "--config=rbe", "--remote_download_toplevel", *[a.bazel_target for a in ARTIFACTS])

    Path("dist").mkdir(exist_ok=True)

    short_sha = str(repo_obj.head.target)[:7]

    sources = Sources.model_validate_json(SOURCES_PATH.read_text())
    repo = Github(auth=Auth.Token(gh_token)).get_repo(REPO)

    changed = []
    for artifact in ARTIFACTS:
        dist_path = copy_artifact_to_dist(artifact.src_glob, artifact.dest)
        pin = sources.pins.get(artifact.pkg)
        if pin and file_sha256(dist_path) == pin.sha256:
            print(f"{artifact.pkg}: unchanged, skipping")
            continue
        tag = f"{artifact.pkg}-{short_sha}"
        print(f"{artifact.pkg}: content changed, creating release {tag}")
        release = repo.create_git_release(
            tag=tag, name=f"{artifact.pkg} ({short_sha})", message=artifact.notes, make_latest="false"
        )
        release.upload_asset(str(dist_path))
        changed.append(artifact.pkg)

    if not changed:
        print("No artifacts changed, skipping release")
        return

    print(f"Released: {' '.join(changed)}")
    print("Pins will be updated by the sync-pins workflow.")


if __name__ == "__main__":
    main()
