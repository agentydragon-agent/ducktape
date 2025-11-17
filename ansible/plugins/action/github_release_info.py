"""
GitHub Release Info Action Plugin

Fetches information about GitHub releases (without installing).
Works with github_release_install, or standalone for checking versions.

Features:
- Pure Python implementation (no external commands)
- Returns detailed release information
- Version comparison and acknowledgment checking
- Check-only operation by design

Usage:
  github_release_info:
    repo: "owner/repo"   # GitHub repo; required

    # Optional parameters
    version: "v1.0.0|latest"                # Version to query (defaults to latest)
    asset_pattern: ".*linux_amd64\\.deb$"   # Regex pattern to select asset
    acknowledged_version: "v1.0.0"          # Last version acknowledged by user
                                            # (fails if newer version available)

Example:
  - name: Check Latest AppImageLauncher Release
    github_release_info:
      repo: "TheAssassin/AppImageLauncher"
      version: "latest"
      asset_pattern: ".*_{{ common_dpkg_arch }}\\.deb$"
    register: release_data
"""

from __future__ import annotations

from pathlib import Path
import sys

from ansible.plugins.action import ActionBase

# Add parent directory to the path so we can use sibling modules
plugins_dir = str(Path(__file__).parent.parent)
if plugins_dir not in sys.path:
    sys.path.insert(0, plugins_dir)

from module_utils.github_release import ReleaseSpec  # noqa: E402


class ActionModule(ActionBase):
    """GitHub Release Info action plugin.

    Wraps get_github_release_info from shared github_release module.
    """

    def run(self, tmp=None, task_vars=None):
        """Main entry point for the action plugin."""
        return ReleaseSpec(**self._task.args).resolve()
