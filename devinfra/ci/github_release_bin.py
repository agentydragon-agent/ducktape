"""Release a single artifact to GitHub if its content changed.

Resolves the artifact from Bazel runfiles, computes SHA256, compares against
the pinned value in npins/sources.json, and creates a GitHub Release if changed.

Usage: bazel run //pkg:release_target
Expects: GH_RELEASE_PAT env var.
"""

import argparse
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from github import Auth, Github, GithubException

from devinfra.ci.artifacts import Sources, file_sha256, is_tag_for_pkg, sources_path
from util.bazel.runfiles import get_required_path
from util.bazel.workspace import get_build_workspace_directory

REPO = "agentydragon/ducktape"
_RETENTION_DAYS = 30


def _delete_release_and_tag(gh_repo, release) -> None:
    tag = release.tag_name
    release.delete_release()
    try:
        gh_repo.get_git_ref(f"tags/{tag}").delete()
    except GithubException as e:
        if e.status != 404:
            raise


def _prune_old_releases(gh_repo, pkg: str, keep_tag: str) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=_RETENTION_DAYS)
    for release in gh_repo.get_releases():
        if not is_tag_for_pkg(release.tag_name, pkg):
            continue
        if release.tag_name == keep_tag:
            continue
        if release.created_at >= cutoff:
            continue
        print(f"  pruning {release.tag_name} ({release.created_at.date()})")
        _delete_release_and_tag(gh_repo, release)


def main() -> None:
    parser = argparse.ArgumentParser(description="Release artifact to GitHub")
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--artifact-rlocation", required=True)
    args = parser.parse_args()

    os.chdir(get_build_workspace_directory())

    subject = subprocess.check_output(["git", "log", "-1", "--format=%s"], text=True).strip()
    if "[skip ci]" in subject:
        print("Commit message contains [skip ci], skipping release.")
        return

    gh_token = os.environ.get("GH_RELEASE_PAT")
    if not gh_token:
        raise RuntimeError("Missing required env var: GH_RELEASE_PAT")

    artifact_path = Path(get_required_path(args.artifact_rlocation))
    sha = file_sha256(artifact_path)

    sources = Sources.model_validate_json(sources_path().read_text())
    pin = sources.pins.get(args.pkg)
    if pin and sha == pin.sha256:
        print(f"{args.pkg}: unchanged, skipping")
        return

    short_sha = subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"], text=True).strip()
    tag = f"{args.pkg}-{short_sha}"
    print(f"{args.pkg}: content changed, creating release {tag}")

    gh_repo = Github(auth=Auth.Token(gh_token)).get_repo(REPO)
    release = gh_repo.create_git_release(
        tag=tag, name=f"{args.pkg} ({short_sha})", message=args.notes, make_latest="false"
    )
    release.upload_asset(str(artifact_path), name=args.filename)
    _prune_old_releases(gh_repo, args.pkg, keep_tag=tag)
    print(f"Released: {args.pkg}")


if __name__ == "__main__":
    main()
