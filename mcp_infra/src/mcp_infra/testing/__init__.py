"""Testing utilities for mcp_infra.

Register in downstream packages via:
    pytest_plugins = ["mcp_infra.testing.fixtures"]
"""

from mcp_infra.testing.fixtures import compositor, compositor_client

__all__ = ["compositor", "compositor_client"]
