"""Test the default approval policy decision logic."""

import pytest

from adgn.agent.approvals import ApprovalPolicyEngine, ApprovalContext


class TestDefaultApprovalPolicy:
    """Test cases for the default approval policy."""

    @pytest.fixture
    def engine(self):
        """Create a fresh ApprovalPolicyEngine with default policy."""
        return ApprovalPolicyEngine()

    def test_ui_tools_allowed(self, engine):
        """UI communication tools should always be allowed."""
        ui_tools = [
            ApprovalContext(server="ui", tool="send_message", arguments={}),
            ApprovalContext(server="ui", tool="end_turn", arguments={}),
        ]

        for ctx in ui_tools:
            result = engine.decide(ctx)
            assert result == "allow", (
                f"UI tool {ctx.server}.{ctx.tool} should be allowed"
            )

    def test_approval_policy_tools_allowed(self, engine):
        """Approval policy management tools should always be allowed."""
        policy_tools = [
            ApprovalContext(server="approval_policy", tool="get_status", arguments={}),
            ApprovalContext(server="approval_policy", tool="propose", arguments={}),
            ApprovalContext(server="approval_policy", tool="withdraw", arguments={}),
        ]

        for ctx in policy_tools:
            result = engine.decide(ctx)
            assert result == "allow", (
                f"Policy tool {ctx.server}.{ctx.tool} should be allowed"
            )

    def test_resource_operations_allowed(self, engine):
        """All resource operations should be allowed."""
        resource_operations = [
            ApprovalContext(server="resources", tool="read", arguments={}),
            ApprovalContext(server="resources", tool="list", arguments={}),
            ApprovalContext(server="resources", tool="some_other_op", arguments={}),
        ]

        for ctx in resource_operations:
            result = engine.decide(ctx)
            assert result == "allow", (
                f"Resource operation {ctx.server}.{ctx.tool} should be allowed"
            )

    def test_approval_policy_server_allowed(self, engine):
        """Any operation on approval_policy server should be allowed."""
        approval_server_ops = [
            ApprovalContext(server="approval_policy", tool="custom_tool", arguments={}),
            ApprovalContext(
                server="approval_policy", tool="some_future_tool", arguments={}
            ),
        ]

        for ctx in approval_server_ops:
            result = engine.decide(ctx)
            assert result == "allow", (
                f"Approval server operation {ctx.server}.{ctx.tool} should be allowed"
            )

    def test_other_tools_require_approval(self, engine):
        """All other tools should require approval (ask)."""
        other_tools = [
            ApprovalContext(server="echo", tool="echo", arguments={}),
            ApprovalContext(server="git_ro", tool="list_files", arguments={}),
            ApprovalContext(server="docker_exec", tool="run", arguments={}),
            ApprovalContext(server="some_server", tool="some_tool", arguments={}),
        ]

        for ctx in other_tools:
            result = engine.decide(ctx)
            assert result == "ask", (
                f"Other tool {ctx.server}.{ctx.tool} should require approval"
            )

    def test_missing_keys_handled_gracefully(self, engine):
        """Policy should handle missing context keys gracefully."""
        ctx = ApprovalContext(server="random_server", tool="random_tool", arguments={})
        result = engine.decide(ctx)
        assert result == "ask"

    def test_policy_version_increments(self, engine):
        """Policy version should increment when policy is updated."""
        initial_version = engine._policy_version
        assert initial_version == 1, "Initial version should be 1"

        # Update policy
        new_policy = """def decide(ctx):
    return "allow"
"""
        new_version = engine.set_policy(new_policy)

        assert new_version == initial_version + 1, "Version should increment"
        assert engine._policy_version == new_version, "Internal version should match"

    def test_custom_policy_overrides_default(self, engine):
        """Custom policy should override default behavior."""
        # Set a custom policy that allows everything
        allow_all_policy = """def decide(ctx):
    return "allow"
"""
        engine.set_policy(allow_all_policy)

        # Now even non-allowed tools should be allowed
        result = engine.decide(
            ApprovalContext(server="echo", tool="echo", arguments={})
        )
        assert result == "allow", "Custom policy should override default"

    @pytest.mark.parametrize(
        "decision", ["allow", "ask", "deny_continue", "deny_abort"]
    )
    def test_valid_decision_values(self, engine, decision):
        """Policy should accept all valid decision values."""
        custom_policy = f'''def decide(ctx):
    return "{decision}"
'''
        engine.set_policy(custom_policy)

        result = engine.decide(
            ApprovalContext(server="test", tool="tool", arguments={})
        )
        assert result == decision, f"Policy should return {decision}"

    def test_invalid_policy_syntax_raises_exception(self, engine):
        """Invalid policy syntax should raise an exception."""
        # Use actual syntax error
        invalid_policy = """def decide(ctx):
    if True
        return "allow"  # Missing colon after if
"""
        with pytest.raises(Exception):
            engine.set_policy(invalid_policy)

    def test_policy_function_receives_context(self, engine):
        """Policy function should receive the full context."""
        context_checking_policy = """def decide(ctx):
    # Verify we get the expected context structure without relying on builtins
    try:
        _ = ctx.server
        _ = ctx.tool
        _ = ctx.arguments
        return "allow"
    except Exception:
        return "deny_abort"
"""
        engine.set_policy(context_checking_policy)

        full_context = ApprovalContext(
            server="test", tool="tool", arguments={"param": "value"}
        )

        result = engine.decide(full_context)
        assert result == "allow", "Policy should receive complete context"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
