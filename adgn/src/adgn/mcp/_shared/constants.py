"""Shared constants for MCP _shared modules."""

from pathlib import Path
from typing import Final

# ============================================================================
# Container Filesystem Paths
# ============================================================================
WORKING_DIR: Final[Path] = Path("/workspace")

# ============================================================================
# Container Lifecycle & Process Control
# ============================================================================
SLEEP_FOREVER_CMD: Final[list[str]] = ["/bin/sh", "-lc", "sleep infinity"]

# ============================================================================
# Server Mount Prefixes - Core Infrastructure
# ============================================================================
RESOURCES_MOUNT_PREFIX: Final[str] = "resources"
RUNTIME_MOUNT_PREFIX: Final[str] = "runtime"
COMPOSITOR_META_MOUNT_PREFIX: Final[str] = "compositor_meta"
UI_MOUNT_PREFIX: Final[str] = "ui"

# ============================================================================
# Server Mount Prefixes - Approval Policy
# ============================================================================
POLICY_READER_MOUNT_PREFIX: Final[str] = "policy_reader"
POLICY_PROPOSER_MOUNT_PREFIX: Final[str] = "policy_proposer"
APPROVAL_ADMIN_MOUNT_PREFIX: Final[str] = "approval_admin"

# ============================================================================
# Server Mount Prefixes - Optional/Specialized
# ============================================================================
SEATBELT_EXEC_MOUNT_PREFIX: Final[str] = "seatbelt_exec"
