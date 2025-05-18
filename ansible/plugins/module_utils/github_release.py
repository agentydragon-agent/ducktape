"""
GitHub Release Utility Module

This module provides shared functionality for GitHub release actions and modules.
It contains common classes and functions used by the GitHub release action
plugins.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from ansible.plugins.action import ActionBase

# Type variables for better type hints
T = TypeVar("T")
R = TypeVar("R")


class ActionError(Exception):
    """Custom exception for action module errors.

    Attributes:
        message: The error message
        skip_install: Whether this error should be treated as non-fatal and just skip installation
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _fail(result, msg: str) -> Dict[str, Any]:
    return result | {"failed": True, "msg": msg}


@dataclass
class ReleaseSpec:
    """Base class for GitHub release information."""

    repo: Optional[str] = None
    version: str = "latest"
    asset_pattern: Optional[str] = None
    acknowledged_version: Optional[str] = None

    def resolve(self) -> Dict[str, Any]:
        """Gets GitHub release info."""
        result = {}

        # Make API request
        try:
            req = urllib.request.Request(
                self.get_api_url(),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Ansible GitHub Release Handler",
                },
            )
            with urllib.request.urlopen(req) as response:
                release_data = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            return _fail(result, f"Error fetching release info: {str(e)}")

        # Clear known-unused keys
        for asset in release_data.get("assets", []):
            # explicitly kept: 'label', 'name', 'url'
            for key in [
                "content_type",
                "created_at",
                "download_count",
                "id",
                "node_id",
                "size",
                "state",
                "updated_at",
                "uploader",
            ]:
                if key in asset:
                    del asset[key]
        for key in [
            "author",
            "body",
            "created_at",
            "draft",
            "html_url",
            "id",
            "node_id",
            "prerelease",
            "published_at",
            "reactions",
        ]:
            if key in release_data:
                del release_data[key]

        result["release_data"] = release_data

        # Handle acknowledged version if provided
        if self.acknowledged_version:
            latest_version = release_data["tag_name"]
            if not latest_version:
                return _fail(
                    result, "Failed to extract version information of latest release."
                )
            result["latest_version"] = latest_version

            if self.acknowledged_version != latest_version:
                return _fail(
                    result,
                    f"Please acknowledge new version {latest_version}. "
                    f"Last acknowledged: {self.acknowledged_version}. ",
                )

        if not (assets := release_data.get("assets")):
            return _fail(result, "No assets found in release data.")
        if not self.asset_pattern:
            return _fail(result, "No asset pattern provided.")
        matches = [
            asset for asset in assets if re.search(self.asset_pattern, asset["name"])
        ]
        if len(matches) > 1:
            return _fail(
                result,
                f"{len(matches)} assets match {self.asset_pattern}. Use a more specific pattern.",
            )
        if not matches:
            return _fail(
                result,
                f"No assets match {self.asset_pattern}. Available: {', '.join(asset['name'] for asset in assets)}",
            )
        if not (url := matches[0].get("browser_download_url")):
            return _fail(result, "No download URL found for the asset.")
        return {"asset_url": url}

    def get_api_url(self) -> str:
        """Return GitHub API URL for the release."""
        url = f"https://api.github.com/repos/{self.repo}/releases"
        if self.version != "latest":
            url += f"/tags/{self.version}"
        else:
            url += "/latest"
        return url


@dataclass
class GitHubInstaller:
    """Base for GitHub release installers."""

    @property
    def module_name(self) -> str:
        """Ansible module name for this installation method."""
        raise NotImplementedError()

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        raise NotImplementedError()

    def get_additional_info(self, asset_url: str) -> Dict[str, Any]:
        """Extra information about installed asset."""
        return {}

    def validate(self) -> None:
        pass


@dataclass
class DebInstall(GitHubInstaller):
    """Install a GitHub release as a Debian package."""

    @property
    def module_name(self) -> str:
        return "ansible.builtin.apt"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        return {"deb": asset_url}


@dataclass
class BinaryInstall(GitHubInstaller):
    """Install a GitHub release as a binary executable."""

    dest_path: Optional[str] = None

    @property
    def module_name(self) -> str:
        return "ansible.builtin.get_url"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for installing the binary."""
        return {"url": asset_url, "dest": self.dest_path, "mode": "0755"}

    def validate(self) -> None:
        super().validate()
        if not self.dest_path:
            raise ActionError("dest_path is required for binary installation")


ARCHIVES = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar.zst", ".zip")


@dataclass
class ArchiveInstall(GitHubInstaller):
    """Install a GitHub release from an archive file."""

    dest_path: Optional[str] = None
    creates_file: Optional[str] = None

    @property
    def module_name(self) -> str:
        return "ansible.builtin.unarchive"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for extracting and installing the archive."""
        args = {
            "src": asset_url,
            "dest": self.dest_path,
            "remote_src": True,
        }
        if self.creates_file:
            args["creates"] = self.creates_file
        return args

    def validate(self) -> None:
        super().validate()
        if not self.dest_path:
            raise ActionError("dest_path is required for archive installation")

    def get_additional_info(self, asset_url: str) -> Dict[str, Any]:
        """Determine extracted directory name and pattern from asset URL."""
        filename = asset_url.split("/")[-1]
        # Extract base name without extension(s)
        for ext in ARCHIVES:
            if filename.endswith(ext):
                return {"extracted_dir": filename.removesuffix(ext)}
        return _fail({}, f"Can't guess extracted directory from URL: {asset_url}")


# Maps method name to implementation.
INSTALL_METHODS: Dict[str, type[GitHubInstaller]] = {
    "deb": DebInstall,
    "binary": BinaryInstall,
    "archive": ArchiveInstall,
}
