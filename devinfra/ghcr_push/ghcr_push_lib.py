"""Push an OCI image to GHCR with conditional tagging.

Uses crane to compare local vs remote digests before pushing. Only creates a
new pinned tag (branch-YYYYMMDDHHMMSS-sha7) when the image digest actually
changed, preventing spurious Flux repins.
"""

import argparse
import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from util.bazel.runfiles import get_required_path
from util.bazel.workspace import BazelLabel, get_build_workspace_directory
from util.crane import Crane
from util.env import get_required_env
from util.oci import read_oci_layout_digest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GhcrImage:
    image_target: str
    repository: str


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _image_runfiles_dir(image_target: str) -> Path:
    """Resolve the OCI layout directory from runfiles."""
    label = BazelLabel.parse(image_target)
    return get_required_path(f"_main/{label.package}/{label.name}")


def _ensure_package_public(package_name: str, token: str) -> None:
    """Set GHCR package visibility to public via GitHub API.

    Idempotent — already-public packages return 200. This is needed because
    packages pushed via crane (BuildBuddy CI) default to private, unlike
    packages pushed via GitHub Actions GITHUB_TOKEN which auto-inherit repo
    visibility.
    """
    url = f"https://api.github.com/user/packages/container/{package_name}"
    data = json.dumps({"visibility": "public"}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="PATCH",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req)
        logger.info("%s: package visibility set to public", package_name)
    except urllib.error.HTTPError as e:
        # 404 = package doesn't exist yet (first push in progress), will be
        # set on next CI run. Don't fail the push for this.
        logger.warning("%s: failed to set package visibility (HTTP %d): %s", package_name, e.code, e.reason)


class ImagePusher:
    def __init__(self, crane: Crane, branch: str, pinned_tag: str, ghcr_token: str) -> None:
        self.crane = crane
        self.branch = branch
        self.pinned_tag = pinned_tag
        self.ghcr_token = ghcr_token

    def _latest_pinned_tag(self, repo: str) -> str | None:
        try:
            tags = self.crane.ls(repo)
        except subprocess.CalledProcessError:
            return None
        branch_tags = sorted(t for t in tags if t.startswith(f"{self.branch}-"))
        return branch_tags[-1] if branch_tags else None

    def push_and_tag(self, img: GhcrImage) -> None:
        image_dir = _image_runfiles_dir(img.image_target)
        local_digest = read_oci_layout_digest(image_dir)
        ref = f"{img.repository}@{local_digest}"

        current_tag = self._latest_pinned_tag(img.repository)
        if current_tag and local_digest == self.crane.digest(f"{img.repository}:{current_tag}"):
            print(f"{img.repository}: digest unchanged ({local_digest[:19]}), skipping")
            return

        print(f"{img.repository}: pushing {local_digest[:19]}")
        self.crane.push(image_dir, ref)
        self.crane.tag(ref, "latest")
        print(f"{img.repository}: tagging {self.pinned_tag}")
        self.crane.tag(ref, self.pinned_tag)

        # Extract package name from "ghcr.io/owner/name" → "name"
        package_name = img.repository.rsplit("/", 1)[-1]
        _ensure_package_public(package_name, self.ghcr_token)


def main() -> None:
    """Push a single OCI image to GHCR if its digest changed."""
    parser = argparse.ArgumentParser(description="Push OCI image to GHCR")
    parser.add_argument("--image-target", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()

    os.chdir(get_build_workspace_directory())

    if "[skip ci]" in _git("log", "-1", "--format=%s"):
        print("Commit message contains [skip ci], skipping image push.")
        return

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    sha = _git("rev-parse", "--short=7", "HEAD")

    ghcr_token = get_required_env("GHCR_TOKEN")
    pusher = ImagePusher(
        crane=Crane(registry="ghcr.io", username=get_required_env("GHCR_USERNAME"), password=ghcr_token),
        branch=branch,
        pinned_tag=f"{branch}-{ts}-{sha}",
        ghcr_token=ghcr_token,
    )
    pusher.push_and_tag(GhcrImage(image_target=args.image_target, repository=args.repository))


if __name__ == "__main__":
    main()
