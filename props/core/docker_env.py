from __future__ import annotations

# Docker network name for properties containers
# Agent containers connect to this network to access:
# - props-postgres (for RLS-controlled database queries)
# - props-registry-proxy (for OCI image operations with ACL enforcement)
# This network is non-internal to allow container→host communication for MCP HTTP mode
PROPS_NETWORK_NAME = "props-agents"
