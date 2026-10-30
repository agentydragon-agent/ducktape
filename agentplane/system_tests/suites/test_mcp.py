"""System scenarios sharing one mcp k3s stack."""

import pytest_bazel

from agentplane.system_tests.scenarios.dcr import test_deployed_discovery_and_registration
from agentplane.system_tests.scenarios.mcp import (
    operator_bff,
    operator_credentials,
    policy_objects,
    test_agent_executes_mcp_action,
    test_agent_mcp_bff_decision,
    test_launcher_drives_only_the_sandbox_it_launched,
    test_operator_links_oauth_mcp_server,
    test_policy_binding_auto_approves_the_bound_sandbox,
)

__all__ = [
    "operator_bff",
    "operator_credentials",
    "policy_objects",
    "test_agent_executes_mcp_action",
    "test_agent_mcp_bff_decision",
    "test_deployed_discovery_and_registration",
    "test_launcher_drives_only_the_sandbox_it_launched",
    "test_operator_links_oauth_mcp_server",
    "test_policy_binding_auto_approves_the_bound_sandbox",
]

if __name__ == "__main__":
    pytest_bazel.main()
