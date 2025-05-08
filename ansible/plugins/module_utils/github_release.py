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
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, cast

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

    def __init__(self, message: str, skip_install: bool = False):
        self.message = message
        self.skip_install = skip_install
        super().__init__(message)


def get_github_release_info(
    params: Dict[str, Any],
    task_vars: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Gets GitHub release info directly.

    Args:
        params: Parameters for GitHub release info
        task_vars: Task variables

    Returns:
        Dict containing release information
    """
    result = {}

    repo = params.get('repo')
    if not repo:
        return {'failed': True, 'msg': 'Missing required parameter: repo'}

    version = params.get('version', 'latest')
    asset_pattern = params.get('asset_pattern')
    arch_map = params.get('arch_map') or {}
    acknowledged_version = params.get('acknowledged_version')

    # Build GitHub API URL
    if version and version != 'latest':
        url = f"https://api.github.com/repos/{repo}/releases/tags/{version}"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/latest"

    # Make API request
    try:
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Ansible GitHub Release Handler',
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            content = response.read().decode('utf-8')
            release_data = json.loads(content)
    except Exception as e:
        return {'failed': True, 'msg': f"Failed to fetch release information: {str(e)}"}

    # Process release data
    latest_version = release_data.get('tag_name', '')
    if not latest_version:
        return {'failed': True, 'msg': "Failed to extract version information from release data"}

    result['latest_version'] = latest_version

    # Handle acknowledged version if provided
    if acknowledged_version:
        # Normalize versions by removing 'v' prefix for comparison
        normalized_latest = latest_version.lstrip('v')
        normalized_acknowledged = acknowledged_version.lstrip('v')

        # Check if acknowledged version is outdated
        if normalized_acknowledged != normalized_latest:
            result['has_new_version'] = True
            result['acknowledged_version'] = acknowledged_version

            # Fail task when new version available and acknowledged version set
            return {
                'failed': True,
                'msg': (
                    f"New version available: {latest_version}. "
                    f"Last acknowledged version: {acknowledged_version}. "
                    f"Please update the acknowledged version if you want to upgrade."
                )
            }

    result['has_new_version'] = False

    # Get architecture from facts
    arch = task_vars.get('ansible_architecture', 'amd64')
    if arch_map and arch in arch_map:
        arch = arch_map[arch]

    # Find matching asset
    pattern = asset_pattern or f".*{arch}.*"
    regex = re.compile(pattern)

    for asset in release_data.get('assets', []):
        if regex.search(asset.get('name', '')):
            result['asset_url'] = asset.get('browser_download_url', '')
            break

    # Make sure we found an asset
    if 'asset_url' not in result:
        return {'failed': True, 'msg': f"No matching asset found for architecture: {arch}"}

    # Add release data for reference
    result['release_data'] = release_data

    return result


def get_release_from_data(data: Any, version: Optional[str] = None) -> Dict[str, Any]:
    """Extract the relevant release from data, considering version."""
    if isinstance(data, list):
        if not data:
            return {}

        # If specific version requested, find that release
        if version and version != "latest":
            matching_releases = [rel for rel in data if rel.get("tag_name") == version]
            if matching_releases:
                return matching_releases[0]
            # Fall back to latest if specified version not found
            return data[0]
        else:
            # Latest release
            return data[0]
    else:
        # Single release object
        return data


def parse_release_data(
    release_json: Dict[str, Any], version: Optional[str] = None
) -> Dict[str, Any]:
    """Extract useful information from GitHub release data."""
    if not release_json:
        return {}

    # Get the specific release using the shared helper
    release = get_release_from_data(release_json, version)
    if not release:
        return {}

    return {
        "version": release.get("tag_name"),
        "name": release.get("name"),
        "published_at": release.get("published_at"),
        "assets": [
            {
                "name": asset.get("name"),
                "size": asset.get("size"),
                "download_url": asset.get("browser_download_url"),
                "content_type": asset.get("content_type"),
            }
            for asset in release.get("assets", [])
        ],
        "body": release.get("body"),
    }


@dataclass
class GitHubReleaseInfo:
    """Base class for GitHub release information."""

    repo: str
    version: Optional[str] = None
    asset_pattern: Optional[str] = None
    arch_map: Optional[Dict[str, str]] = None

    def get_api_url(self) -> str:
        """Return GitHub API URL for the release."""
        url_path = f"/repos/{self.repo}/releases"
        if self.version and self.version != "latest":
            url_path += f"/tags/{self.version}"
        else:
            url_path += "/latest"

        return f"https://api.github.com{url_path}"

    def get_version_from_json(self, release_data: Dict[str, Any]) -> str:
        """Extract version information from release data."""
        release = get_release_from_data(release_data)
        return release.get("tag_name", "")

    def get_asset_url_from_json(self, release_data: Dict[str, Any], arch: str) -> str:
        """Extract asset URL from release data for the specified architecture."""
        pattern = self.asset_pattern or f".*{arch}.*"
        regex = re.compile(pattern)

        release = get_release_from_data(release_data, self.version)

        # Find matching asset
        for asset in release.get("assets", []):
            if regex.search(asset.get("name", "")):
                return asset.get("browser_download_url", "")

        return ""


# Define base installer functionality
@dataclass
class GitHubInstaller(GitHubReleaseInfo):
    """Base class for GitHub release installers combining fetch and install logic."""

    @property
    def module_name(self) -> str:
        """Return the Ansible module name for this installation method."""
        raise NotImplementedError("Installation method must define module_name")

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for installing the asset."""
        raise NotImplementedError("Installation method must define install_module_args")

    def get_additional_info(self, asset_url: str, install_result: Dict[str, Any]) -> Dict[str, Any]:
        """Get additional information about the installed asset.

        This method is called after installation to get any additional information
        about the installed asset. Default implementation returns an empty dict.

        Args:
            asset_url: URL of the installed asset
            install_result: Result of the installation module call

        Returns:
            Dictionary of additional information to add to the result
        """
        return {}  # Default implementation returns no additional info


@dataclass
class DebInstall(GitHubInstaller):
    """Install a GitHub release as a Debian package."""

    @property
    def module_name(self) -> str:
        return "ansible.builtin.apt"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for installing the deb package."""
        return {"deb": asset_url}


@dataclass
class BinaryInstall(GitHubInstaller):
    """Install a GitHub release as a binary executable."""

    dest_path: Optional[str] = None

    def __post_init__(self):
        """Validate required parameters after initialization."""
        if not self.dest_path:
            raise ActionError("dest_path is required for binary installation")

    @property
    def module_name(self) -> str:
        return "ansible.builtin.get_url"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for installing the binary."""
        return {
            "url": asset_url,
            "dest": self.dest_path,
            "mode": "0755",
        }


@dataclass
class ArchiveInstall(GitHubInstaller):
    """Install a GitHub release from an archive file."""

    dest_path: Optional[str] = None
    creates_file: Optional[str] = None

    def __post_init__(self):
        """Validate required parameters after initialization."""
        if not self.dest_path:
            raise ActionError("dest_path is required for archive installation")

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

    def get_additional_info(self, asset_url: str, install_result: Dict[str, Any]) -> Dict[str, Any]:
        """Get additional information about the installed archive."""
        # Only return extracted info if the installation was successful
        if install_result.get("failed", False):
            return {}

        extracted_info = {}
        extracted_dir, extracted_pattern = get_extracted_info(asset_url)
        if extracted_dir:
            extracted_info["extracted_dir"] = extracted_dir
        if extracted_pattern:
            extracted_info["extracted_pattern"] = extracted_pattern

        return extracted_info


# Dictionary mapping method names to their implementation classes
INSTALL_METHODS: Dict[str, type[GitHubInstaller]] = {
    "deb": DebInstall,
    "binary": BinaryInstall,
    "archive": ArchiveInstall,
}


class GitHubReleaseBaseActionModule(ActionBase):
    """Base action module for GitHub release plugins with common functionality."""

    def _handle_step(
        self, result_dict: Dict[str, Any], step_name: str,
        func: Callable[..., R], *args: Any, **kwargs: Any
    ) -> R:
        """
        Execute a step function and handle errors consistently.

        Args:
            result_dict: Dictionary to update with failure info if step fails
            step_name: Name of the step for error messages
            func: Function to call
            args, kwargs: Arguments to pass to the function

        Returns:
            The function's return value

        Raises:
            ActionError: If the step fails
        """
        try:
            return func(*args, **kwargs)
        except ActionError as e:
            # Handle the error according to its flags
            if e.skip_install:
                # For errors that should just skip installation but not fail
                result_dict.update(
                    skipped=True,
                    msg=str(e),
                    skip_reason="check_only_mode"
                )
            else:
                # For real errors that should fail the task
                result_dict.update(failed=True, msg=str(e))
            raise
        except Exception as e:
            error_msg = f"Failed in {step_name}: {str(e)}"
            result_dict.update(failed=True, msg=error_msg)
            raise ActionError(error_msg) from e


def get_extracted_info(asset_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Determine extracted directory name and pattern from asset URL."""
    if not asset_url:
        return None, None

    # Extract just the filename from the URL
    filename = asset_url.split("/")[-1] if "/" in asset_url else asset_url
    extracted_dir = None
    extracted_pattern = None

    # Extract base name without extension(s)
    if filename.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar.zst")):
        # Handle various tar formats
        if ".tar." in filename:
            basename = filename.split(".tar.")[0]
        else:  # .tgz case
            basename = filename.rsplit(".", 1)[0]
        extracted_dir = basename
    elif filename.endswith(".zip"):
        basename = filename.rsplit(".", 1)[0]
        extracted_dir = basename
    else:
        return None, None

    # Try to determine directory structure pattern
    # Example: app-1.2.3-linux -> app-VERSION-linux
    version_pattern = r"[\d\.]+"
    if re.search(f"-{version_pattern}-", basename):
        parts = re.split(f"-({version_pattern})-", basename, 1)
        if len(parts) == 3:  # [prefix, version, suffix]
            extracted_pattern = f"{parts[0]}-VERSION-{parts[2]}"

    return extracted_dir, extracted_pattern

