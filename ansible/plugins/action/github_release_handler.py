"""
GitHub Release Handler Action Plugin

This plugin provides a unified approach to installing software from GitHub releases.
It supports multiple installation methods (deb packages, binaries, archives)
and provides rich information about the installed release for follow-up tasks.

Features:
- Pure Python implementation (no file I/O or external commands)
- Version pinning with optional failure on newer versions
- Smart detection of extracted directory names for archives
- Architecture-specific asset selection
- Detailed release information in the return value
- DRY error handling with custom exceptions

Usage:
  github_release_handler:
    # Required parameters
    repo: "owner/repo"                      # GitHub repository 
    method: "deb|binary|archive"            # Installation method
    
    # Optional common parameters
    version: "v1.0.0|latest"                # Version to install (defaults to latest)
    asset_pattern: ".*linux_amd64\\.deb$"   # Regex pattern to select asset
    
    # Version management parameters
    acknowledged_version: "v1.0.0"          # Last version seen/acknowledged by user (implies fail on newer)
    check_only: true|false                  # Only check versions without installing
    arch_map: {amd64: x86_64, arm64: arm}   # Optional mapping of architecture names

    # Method-specific parameters
    # For binary method:
    dest_path: "/usr/local/bin/app"         # Path where binary will be installed

    # For archive method:
    dest_path: "/opt/app"                   # Directory where archive will be extracted
    creates_file: "/opt/app/bin/app"        # Optional path that should exist after install

Example:
  - name: Install AppImageLauncher
    github_release_handler:
      repo: "TheAssassin/AppImageLauncher"
      method: deb
      version: "v3.0.0-alpha-4"
      asset_pattern: ".*_{{ dpkg_arch }}\\.deb$"
      fail_on_newer_version: true
    become: true
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Callable, TypeVar, cast

from ansible.errors import AnsibleError

# Type variables for better type hints
T = TypeVar('T')
R = TypeVar('R')

from ansible.plugins.action import ActionBase

# This function is no longer needed since we fetch directly to memory
# def load_release_json(file_path: str) -> Any:
#     """Load release JSON data from a file."""
#     with open(file_path, "r") as f:
#         return json.load(f)


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


@dataclass
class GitHubReleaseInstall:
    """Base class for GitHub release installations."""

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
class GitHubInstaller(GitHubReleaseInstall):
    """Base class for GitHub release installers combining fetch and install logic."""
    
    @property
    def module_name(self) -> str:
        """Return the Ansible module name for this installation method."""
        raise NotImplementedError("Installation method must define module_name")

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for installing the asset."""
        raise NotImplementedError("Installation method must define install_module_args")


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

    @property
    def module_name(self) -> str:
        return "ansible.builtin.get_url"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for installing the binary."""
        if not self.dest_path:
            raise ActionError("dest_path is required for binary installation")
            
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

    @property
    def module_name(self) -> str:
        return "ansible.builtin.unarchive"

    def install_module_args(self, asset_url: str) -> Dict[str, Any]:
        """Return arguments for extracting and installing the archive."""
        if not self.dest_path:
            raise ActionError("dest_path is required for archive installation")
            
        args = {
            "src": asset_url,
            "dest": self.dest_path,
            "remote_src": True,
        }
        if self.creates_file:
            args["creates"] = self.creates_file
        return args


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


def get_extracted_info(asset_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Determine extracted directory name and pattern from asset URL."""
    if not asset_url:
        return None, None

    asset_filename = os.path.basename(asset_url)
    extracted_dir = None
    extracted_pattern = None

    # Extract base name without extension(s)
    if asset_filename.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar.zst")):
        # Handle various tar formats
        if ".tar." in asset_filename:
            basename = asset_filename.split(".tar.")[0]
        else:  # .tgz case
            basename = asset_filename.rsplit(".", 1)[0]
        extracted_dir = basename
    elif asset_filename.endswith(".zip"):
        basename = asset_filename.rsplit(".", 1)[0]
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


# Dictionary mapping method names to their implementation classes
INSTALL_METHODS: Dict[str, type[GitHubInstaller]] = {
    "deb": DebInstall,
    "binary": BinaryInstall,
    "archive": ArchiveInstall,
}


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


class ActionModule(ActionBase):
    """GitHub Release Handler action plugin."""

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

    def _validate_args(self, args: Dict[str, Any]) -> str:
        """Validate required arguments and return method.

        Raises:
            ActionError: If validation fails
        """
        if "repo" not in args:
            raise ActionError("Missing required parameter: repo")

        if "method" not in args:
            raise ActionError("Missing required parameter: method")

        method = args.get("method")
        if method not in INSTALL_METHODS:
            raise ActionError(
                f"Invalid method: {method}. Expected one of: {', '.join(INSTALL_METHODS.keys())}"
            )

        return method

    def _create_installer(
        self, method: str, args: Dict[str, Any]
    ) -> GitHubInstaller:
        """Create installer instance based on method.

        Raises:
            ActionError: If installer creation fails
        """
        try:
            installer_class = INSTALL_METHODS[method]
            
            # Filter out any arguments that aren't relevant to the installer class
            # Common parameters: repo, version, asset_pattern, arch_map
            # Method-specific parameters depend on the installer class
            common_params = ['repo', 'version', 'asset_pattern', 'arch_map']
            
            # Get valid parameters for this installer class by inspecting its fields
            import inspect
            sig = inspect.signature(installer_class.__init__)
            valid_params = [p.name for p in sig.parameters.values() 
                           if p.name != 'self' and p.kind != inspect.Parameter.VAR_KEYWORD]
            
            # Combine common and specific parameters
            valid_params = set(common_params + valid_params)
            
            # Filter arguments to only include valid parameters
            installer_args = {k: v for k, v in args.items() 
                             if k in valid_params and k != "method"}
            
            # Check for required dest_path parameter for binary and archive methods
            if method in ["binary", "archive"] and "dest_path" not in installer_args:
                raise ActionError(f"Missing required parameter 'dest_path' for {method} method")
                
            installer = installer_class(**installer_args)
            return cast(GitHubInstaller, installer)  # Ensure type safety
        except TypeError as e:
            # Provide better error message for missing parameters
            raise ActionError(f"Error creating {method} installer: {str(e)}")
        except Exception as e:
            raise ActionError(f"Error creating installer: {str(e)}")

    def _fetch_release_info(
        self, installer: GitHubInstaller, task_vars: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fetch release information from GitHub API.

        Raises:
            ActionError: If fetch fails
        """
        fetch_result = self._execute_module(
            module_name="ansible.builtin.uri",
            module_args={
                "url": installer.get_api_url(),
                "method": "GET",
                "return_content": True,
                "headers": {
                    "Accept": "application/json",
                    "User-Agent": "Ansible GitHub Release Handler",
                },
            },
            task_vars=task_vars,
        )

        if fetch_result.get("failed", False):
            raise ActionError(
                f"Failed to fetch release information: {fetch_result.get('msg', '')}"
            )

        if not fetch_result.get("content"):
            raise ActionError("Empty response from GitHub API")

        # Parse JSON content from response
        try:
            return json.loads(fetch_result["content"])
        except json.JSONDecodeError as e:
            raise ActionError(f"Failed to parse GitHub API response: {str(e)}")

    def _check_version(
        self,
        installer: GitHubInstaller,
        release_data: Dict[str, Any],
        args: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        """Check version information and handle version comparison.

        Handles three different version checks:
        1. Pinned version vs latest (when version is specified)
        2. Acknowledged version vs latest (when acknowledged_version is specified)
        3. Check-only mode (when check_only is true)

        Raises:
            ActionError: If version check fails or newer version is available
                         when fail_on_newer_version is set
        """
        latest_version = installer.get_version_from_json(release_data)
        if not latest_version:
            raise ActionError("Failed to extract version information from release data")

        result["latest_version"] = latest_version
        
        # Case 1: Check if acknowledged version is outdated
        if args.get("acknowledged_version") and args.get("acknowledged_version") != latest_version:
            result["has_new_version"] = True
            result["acknowledged_version"] = args.get("acknowledged_version")
            
            # If acknowledged_version is set, always fail on newer versions
            raise ActionError(
                f"New version available: {latest_version}. Last acknowledged version: {args.get('acknowledged_version')}. "
                f"Please update the acknowledged version if you want to upgrade."
            )
        else:
            result["has_new_version"] = False
        
        # Case 2: Check if pinned version is outdated compared to latest
        if (
            args.get("version")
            and args.get("version") != "latest"
            and args.get("version") != latest_version
        ):
            result["version_difference"] = {
                "requested": args.get("version"),
                "latest": latest_version,
            }
            
            # Only check pinned version vs latest when acknowledged_version is not set
            # (since acknowledged_version handling already takes care of version comparison)
            if args.get("fail_on_newer_version", False) and not args.get("acknowledged_version"):
                raise ActionError(
                    f"New version available: {latest_version}. Current pinned version: {args.get('version')}. "
                    f"Please update the pinned version if you want to upgrade."
                )
        
        # Case 3: Check-only mode (don't continue with installation)
        if args.get("check_only", False):
            result["check_only"] = True
            # Use skip_install flag to indicate this is not an error but we should skip installation
            raise ActionError("Check-only mode - installation skipped", skip_install=True)

    def _get_asset_url(
        self,
        installer: GitHubInstaller,
        release_data: Dict[str, Any],
        arch: str,
        result: Dict[str, Any],
    ) -> str:
        """Get the asset URL for the specified architecture.

        Raises:
            ActionError: If asset URL cannot be found
        """
        asset_url = installer.get_asset_url_from_json(release_data, arch)
        if not asset_url:
            raise ActionError(f"No matching asset found for architecture: {arch}")

        result["asset_url"] = asset_url
        return asset_url

    def _install_release(
        self, installer: GitHubInstaller, asset_url: str, task_vars: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Install the release using the appropriate method.
        
        Returns:
            Dict containing the installation result from Ansible
        """
        install_args = installer.install_module_args(asset_url)
        return self._execute_module(
            module_name=installer.module_name,
            module_args=install_args,
            task_vars=task_vars,
        )

    def _add_release_data(
        self,
        release_data: Dict[str, Any],
        method: str,
        asset_url: str,
        args: Dict[str, Any],
        install_result: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        """Add detailed release information to the result.
        
        This is a non-critical step that enriches the return data
        with useful information about the release and extracted files.
        """
        try:
            result["release_data"] = parse_release_data(
                release_data, args.get("version")
            )

            # For archive installations, extract directory structure information
            if method == "archive" and not install_result.get("failed", False):
                extracted_dir, extracted_pattern = get_extracted_info(asset_url)
                if extracted_dir:
                    result["extracted_dir"] = extracted_dir
                if extracted_pattern:
                    result["extracted_pattern"] = extracted_pattern

        except Exception as e:
            result["warning"] = f"Could not extract detailed release data: {str(e)}"

    def run(self, tmp=None, task_vars=None):
        """Main entry point for the action plugin."""
        if task_vars is None:
            task_vars = {}

        result = super(ActionModule, self).run(tmp, task_vars)
        result.update(changed=False, failed=False)

        try:
            # Parse and validate arguments
            args = self._task.args.copy()
            method = self._handle_step(
                result, "argument validation", self._validate_args, args
            )

            # Create installer
            installer = self._handle_step(
                result, "installer creation", self._create_installer, method, args
            )

            # Fetch release information directly using API
            release_data = self._handle_step(
                result,
                "release info fetch",
                self._fetch_release_info,
                installer,
                task_vars,
            )

            # Check version information
            self._handle_step(
                result,
                "version check",
                self._check_version,
                installer,
                release_data,
                args,
                result,
            )

            # Get architecture
            arch = task_vars.get(
                "dpkg_arch", task_vars.get("ansible_architecture", "amd64")
            )
            if installer.arch_map and arch in installer.arch_map:
                arch = installer.arch_map[arch]

            # Get asset URL
            asset_url = self._handle_step(
                result,
                "asset URL retrieval",
                self._get_asset_url,
                installer,
                release_data,
                arch,
                result,
            )

            # Install the release (unless in check_only mode)
            if not args.get("check_only", False):
                install_result = self._handle_step(
                    result,
                    "installation",
                    self._install_release,
                    installer,
                    asset_url,
                    task_vars,
                )
            else:
                # In check_only mode, we skip installation
                result["check_only_mode"] = True
                install_result = {"changed": False, "skipped": True}

            # Add release data
            try:
                self._add_release_data(
                    release_data, method, asset_url, args, install_result, result
                )
            except Exception as e:
                # Non-critical step, just add a warning
                result["warning"] = f"Failed to add release data: {str(e)}"

            # Update result with installation outcome
            result.update(
                changed=install_result.get("changed", False),
                install_result=install_result,
            )

        except ActionError:
            # Error handling is already done by the _handle_step method
            pass

        return result

