"""
GitHub Release Info Action Plugin

This plugin fetches information about GitHub releases without installing them.
It's designed to work in tandem with the github_release_install plugin or standalone
for checking versions.

Features:
- Pure Python implementation (no external commands)
- Returns detailed release information
- Version comparison and acknowledgment checking
- Check-only operation by design

Usage:
  github_release_info:
    # Required parameters
    repo: "owner/repo"                      # GitHub repository

    # Optional parameters
    version: "v1.0.0|latest"                # Version to query (defaults to latest)
    asset_pattern: ".*linux_amd64\\.deb$"   # Regex pattern to select asset
    acknowledged_version: "v1.0.0"          # Last version seen/acknowledged by user
                                           # (fails task if newer version available)
    arch_map: {amd64: x86_64, arm64: arm}   # Optional mapping of architecture names

Example:
  - name: Check Latest AppImageLauncher Release
    github_release_info:
      repo: "TheAssassin/AppImageLauncher"
      version: "latest"
      asset_pattern: ".*_{{ dpkg_arch }}\\.deb$"
    register: release_info
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

# Add the parent directory to the path so we can use sibling modules
plugins_dir = str(Path(__file__).parent.parent)
if plugins_dir not in sys.path:
    sys.path.insert(0, plugins_dir)

from module_utils.github_release import (
    ActionError,
    GitHubReleaseBaseActionModule,
    get_github_release_info
)


class ActionModule(GitHubReleaseBaseActionModule):
    """GitHub Release Info action plugin.

    This plugin is a simple wrapper around the get_github_release_info function
    in the shared github_release module. It validates the arguments and then
    delegates to the shared function.
    """

    def _validate_args(self, args: Dict[str, Any]) -> None:
        """Validate required arguments.

        Raises:
            ActionError: If validation fails
        """
        if "repo" not in args:
            raise ActionError("Missing required parameter: repo")

    def run(self, tmp=None, task_vars=None):
        """Main entry point for the action plugin."""
        if task_vars is None:
            task_vars = {}

        result = super(ActionModule, self).run(tmp, task_vars)
        result.update(changed=False, failed=False)

        try:
            # Parse and validate arguments
            args = self._task.args.copy()
            self._handle_step(result, "argument validation", self._validate_args, args)

            # Use the shared get_github_release_info function
            info_result = get_github_release_info(args, task_vars)

            # Handle any errors from the info function
            if info_result.get("failed", False):
                return info_result

            # Copy all info fields to our result
            result.update(info_result)

        except ActionError:
            # Error handling is already done by the _handle_step method
            pass

        return result
