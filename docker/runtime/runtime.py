"""Runtime entry point - imports all packages to verify installation."""

# Import all packages to verify they're available
import adgn  # noqa: F401
import agent_core  # noqa: F401
import agent_pkg_runtime  # noqa: F401
import agent_server  # noqa: F401
import cli_util  # noqa: F401
import mcp_infra  # noqa: F401
import net_util  # noqa: F401
import openai_utils  # noqa: F401

if __name__ == "__main__":
    print("adgn runtime image ready")
