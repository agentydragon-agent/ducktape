"""
GitHub Release Install Action Plugin

This plugin installs software from GitHub releases with integrated release information lookup.

Features:
- Pure Python implementation (no external commands)
- Multiple installation methods (deb, binary, archive)
- Integrated GitHub release information lookup
- Version acknowledgment system for controlling upgrades

Usage:
  github_release_install:
    # Required parameters
    repo: "owner/repo"                      # GitHub repository
    method: "deb|binary|archive"            # Installation method

    # Optional common parameters
    version: "v1.0.0|latest"                # Version to install (defaults to latest)
    asset_pattern: ".*linux_amd64\\.deb$"   # Regex pattern to select asset
    acknowledged_version: "v1.0.0"          # Last version seen/acknowledged by user
    arch_map: {amd64: x86_64, arm64: arm}   # Optional mapping of architecture names

    # Optional external release info
    release_info: "{{ release_info }}"      # Result from previously run task (optional)

    # Method-specific parameters
    # For binary method:
    dest_path: "/usr/local/bin/app"         # Path where binary will be installed

    # For archive method:
    dest_path: "/opt/app"                   # Directory where archive will be extracted
    creates_file: "/opt/app/bin/app"        # Optional path that should exist after install

Example:
  # One-step installation process (recommended)
  - name: Install AppImageLauncher
    github_release_install:
      repo: "TheAssassin/AppImageLauncher"
      method: deb
      version: "v3.0.0-alpha-4"
      acknowledged_version: "v3.0.0-alpha-4"
      asset_pattern: ".*_{{ dpkg_arch }}\\.deb$"
    become: true

  # Separate info-gathering for debugging (not required)
  - name: Show available releases
    github_release_install:
      repo: "TheAssassin/AppImageLauncher"
      method: deb
      version: "latest"
      asset_pattern: ".*_{{ dpkg_arch }}\\.deb$"
    check_mode: yes
    register: release_info

  - name: Debug release info
    debug:
      var: release_info
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, cast

# Add the parent directory to the path so we can use sibling modules
plugins_dir = str(Path(__file__).parent.parent)
if plugins_dir not in sys.path:
    sys.path.insert(0, plugins_dir)

from module_utils.github_release import (
    ActionError,
    GitHubReleaseBaseActionModule,
    GitHubInstaller,
    INSTALL_METHODS,
    get_github_release_info,
)

# Constants
ENSURE_ABSENT = "absent"
ENSURE_PRESENT = "present"


class ActionModule(GitHubReleaseBaseActionModule):
    """GitHub Release Install action plugin."""

    def _validate_args(self, args: Dict[str, Any]) -> str:
        """Validate required arguments and return method.

        Raises:
            ActionError: If validation fails
        """
        # When using release_info, repo validation is skipped
        if "release_info" not in args:
            # Use the common validation from the base class
            self._validate_common_args(args)

        if "method" not in args:
            raise ActionError("Missing required parameter: method")

        method = args["method"]
        if method not in INSTALL_METHODS:
            raise ActionError(
                f"Invalid method: {method}. Expected one of: {', '.join(INSTALL_METHODS.keys())}"
            )

        return method

    def _create_installer(self, method: str, args: Dict[str, Any]) -> GitHubInstaller:
        """Create installer instance based on method.

        Raises:
            ActionError: If installer creation fails
        """
        try:
            installer_class = INSTALL_METHODS[method]

            # Pass all arguments to the installer class, which will extract what it needs
            # The installer class constructor is responsible for validating required params

            # Remove 'method' key as it's not needed by installer classes
            args_copy = args.copy()
            if "method" in args_copy:
                args_copy.pop("method")

            # Create installer instance
            installer = installer_class(**args_copy)

            # Validate the installer (calls the validate method which checks required params)
            installer.validate()

            return cast(GitHubInstaller, installer)  # Ensure type safety
        except Exception as e:
            raise ActionError(f"Error creating {method} installer: {str(e)}")

    def _install_release(
        self, installer: GitHubInstaller, asset_url: str, task_vars: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Install the release using the appropriate method.

        Returns:
            Dict containing the installation result from Ansible
        """
        try:
            install_args = installer.install_module_args(asset_url)
            return self._execute_module(
                module_name=installer.module_name,
                module_args=install_args,
                task_vars=task_vars,
            )
        except Exception as e:
            raise ActionError(f"Installation failed: {str(e)}")

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

            # Check if we have release_info from a previous task
            asset_url = None
            if "release_info" in args and args["release_info"]:
                release_info = args["release_info"]
                if "asset_url" in release_info and release_info["asset_url"]:
                    asset_url = release_info["asset_url"]
                    result["asset_url"] = asset_url

                # Copy other useful information to this task's result
                for field in ["latest_version", "has_new_version", "release_data"]:
                    if field in release_info:
                        result[field] = release_info[field]

            # If we don't have the asset URL from release_info, we need to use
            # github_release_info functionality to get it
            if not asset_url:
                # We need to use a github_release_info task to get the asset URL
                # Prepare parameters for github_release_info
                info_args = {
                    k: args[k]
                    for k in [
                        "repo",
                        "version",
                        "asset_pattern",
                        "arch_map",
                        "acknowledged_version",
                    ]
                    if k in args
                }

                # Get release info using the shared module function
                info_result = get_github_release_info(info_args, task_vars)

                # Check if the release info retrieval succeeded
                if info_result.get("failed", False):
                    # Pass through the error
                    return info_result

                # Get the asset URL from the info result
                if "asset_url" not in info_result:
                    raise ActionError("Failed to get asset URL from release info")
                asset_url = info_result["asset_url"]

                # Copy other useful information to this task's result
                for field in ["latest_version", "has_new_version", "release_data"]:
                    if field in info_result:
                        result[field] = info_result[field]

            # Install the release
            install_result = self._handle_step(
                result,
                "installation",
                self._install_release,
                installer,
                asset_url,
                task_vars,
            )

            # Get additional info from the installer
            result.update(installer.get_additional_info(asset_url, install_result))

            # Update result with installation outcome
            result.update(
                changed=install_result.get("changed", False),
                install_result=install_result,
            )

        except ActionError:
            # Error handling is already done by the _handle_step method
            pass

        return result
