"""BuildBuddy remote cache configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

BUILDBUDDY_BAZELRC = Path.home() / ".config" / "bazel" / "buildbuddy.bazelrc"


def is_buildbuddy_configured() -> bool:
    """Check if BuildBuddy remote cache is configured on this machine."""
    return BUILDBUDDY_BAZELRC.exists()


@dataclass
class BuildbuddySetup:
    """Result of BuildBuddy configuration."""

    configured: bool


def setup_buildbuddy(*, api_key: str | None = None) -> BuildbuddySetup:
    """Configure BuildBuddy remote cache.

    Writes config to ~/.config/bazel/buildbuddy.bazelrc. The session bazelrc
    template includes a try-import for this file.
    """
    if not api_key:
        logger.info("BuildBuddy API key not provided, skipping setup")
        return BuildbuddySetup(configured=False)

    BUILDBUDDY_BAZELRC.parent.mkdir(parents=True, exist_ok=True)
    BUILDBUDDY_BAZELRC.write_text(
        "# BuildBuddy authentication (auto-generated)\n"
        "# Static configuration is in .bazelrc under build:rbe\n"
        f"common --remote_header=x-buildbuddy-api-key={api_key}\n"
        "\n"
        "# Enable RBE (platforms, exec properties in .bazelrc + BUILD.bazel platform)\n"
        "build --config=rbe\n"
    )

    logger.info("BuildBuddy remote cache configured at %s", BUILDBUDDY_BAZELRC)
    return BuildbuddySetup(configured=True)
