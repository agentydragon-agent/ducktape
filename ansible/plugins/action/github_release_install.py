"""
GitHub Release Install Action Plugin

Installs software from GitHub releases with integrated release information lookup.

Features:
- Pure Python implementation (no external commands)
- Multiple installation methods (deb, binary, archive)
- Integrated GitHub release information lookup
- Version acknowledgment system for controlling upgrades

Usage:
  github_release_install:
    # Required parameters
    repo: "owner/repo"  # GitHub repository

    # Optional common parameters
    release_spec:
      version: "v1.0.0|latest"          # Version to install (defaults to latest)
      asset_pattern: ".*amd64\\.deb$"   # Regex pattern to select asset
      acknowledged_version: "v1.0.0"    # Last version seen/acknowledged by user

    # Optional release data from previous task
    release_data: "{{ release_data }}"

    method: deb  # Installation method (deb, binary, archive)

    method:
      name: binary
      dest_path: /usr/local/bin/app   # Path where binary will be installed

    method:
      name: archive
      dest_path: "/opt/app"         # Directory where archive will be extracted
      creates_file: "/opt/app/bin"  # Optional path that should exist after install

Example:
  # One-step installation process
  - name: Install AppImageLauncher
    github_release_install:
      repo: "TheAssassin/AppImageLauncher"
      method: deb
      version: "v3.0.0-alpha-4"
      acknowledged_version: "v3.0.0-alpha-4"
      asset_pattern: ".*_{{ dpkg_arch }}\\.deb$"
    become: true

  # Separate release info gathering
  - name: Show available releases
    github_release_install:
      repo: "TheAssassin/AppImageLauncher"
      method: deb
      version: "latest"
      asset_pattern: ".*_{{ dpkg_arch }}\\.deb$"
    register: release_data
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from ansible.plugins.action import ActionBase

# Add the parent directory to the path so we can use sibling modules
plugins_dir = str(Path(__file__).parent.parent)
if plugins_dir not in sys.path:
    sys.path.insert(0, plugins_dir)

from module_utils.github_release import (
    INSTALL_METHODS,
    ActionError,
    GitHubInstaller,
    ReleaseSpec,
    _fail,
)

# Constants
ENSURE_ABSENT = "absent"
ENSURE_PRESENT = "present"


class ActionModule(ActionBase):
    """GitHub Release Install action plugin."""

    def _create_installer(self, args: Dict[str, Any]) -> GitHubInstaller:
        """Create installer instance based on method.

        Raises:
            ActionError: If installer creation fails
        """
        # Pass all arguments to the installer class, which will extract what it needs
        # The installer class constructor is responsible for validating required params
        if not (method := args.get("method")):
            raise ActionError("Missing required parameter: method")

        if isinstance(method, str):
            method_name, method_args = method, {}
        elif isinstance(method, dict):
            method_name, method_args = method.get("name"), method.copy()
            method_args.pop("name")
        else:
            raise ActionError(f"Invalid {type(method) = }.")
        assert isinstance(method_name, str)
        if not (klass := INSTALL_METHODS.get(method_name)):
            raise ActionError(
                f"Invalid {method = }. Expected one of: {', '.join(INSTALL_METHODS.keys())}"
            )
        installer = klass(**method_args)
        installer.validate()
        return installer

    def run(self, tmp=None, task_vars=None):
        """Main entry point for the action plugin."""
        if task_vars is None:
            task_vars = {}

        result = super(ActionModule, self).run(tmp, task_vars)
        result.update(changed=False, failed=False)

        args = self._task.args.copy()

        # Check if we have release_data from a previous task
        if "release_data" not in args:
            # todo dedupe
            if "release_spec" not in args:
                return _fail(
                    result, "Missing required parameter: release_data xor release_spec"
                )
            result["release_data"] = (
                release_data := ReleaseSpec(**args["release_spec"]).resolve()
            )
            if release_data.get("failed"):
                return _fail(result, release_data["msg"])
        # todo dedupe
        elif not (release_data := args.get("release_data")):
            return _fail(
                result, "Missing required parameter: release_data xor release_spec"
            )
        if not (asset_url := release_data.get("asset_url")):
            return _fail(result, "No asset URL in release info")

        # Install the release
        try:
            installer = self._create_installer(args)
        except ActionError as e:
            return _fail(result, str(e))
        install_result = self._execute_module(
            module_name=installer.module_name,
            module_args=installer.install_module_args(asset_url),
            task_vars=task_vars,
            tmp=tmp,
        ) | installer.get_additional_info(asset_url)
        result["install_result"] = install_result

        if install_result.get("failed"):
            return _fail(result, install_result["msg"])

        return result | {"changed": install_result.get("changed", False)}
