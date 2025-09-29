"""Test the default approval policy decision logic."""

import pytest

from adgn.llm.mini_codex.approvals import ApprovalPolicyEngine


class TestDefaultApprovalPolicy:
    """Test cases for the default approval policy."""

    @pytest.fixture
    def engine(self):
        """Create a fresh ApprovalPolicyEngine with default policy."""
        return ApprovalPolicyEngine()

    def test_ui_tools_allowed(self, engine):
        """UI communication tools should always be allowed."""
        ui_tools = [
            {"tool_key": "mcp__ui__send_message", "server": "ui"},
            {"tool_key": "mcp__ui__end_turn", "server": "ui"},
        ]

        for ctx in ui_tools:
            result = engine.decide(ctx)
            assert result == "allow", f"UI tool {ctx['tool_key']} should be allowed"

    def test_approval_policy_tools_allowed(self, engine):
        """Approval policy management tools should always be allowed."""
        policy_tools = [
            {"tool_key": "mcp__approval_policy__get_status", "server": "approval_policy"},
            {"tool_key": "mcp__approval_policy__propose", "server": "approval_policy"},
            {"tool_key": "mcp__approval_policy__withdraw", "server": "approval_policy"},
        ]

        for ctx in policy_tools:
            result = engine.decide(ctx)
            assert result == "allow", f"Policy tool {ctx['tool_key']} should be allowed"

    def test_resource_operations_allowed(self, engine):
        """All resource operations should be allowed."""
        resource_operations = [
            {"tool_key": "mcp__resources__read", "server": "resources"},
            {"tool_key": "mcp__resources__list", "server": "resources"},
            {"tool_key": "mcp__resources__some_other_op", "server": "resources"},
        ]

        for ctx in resource_operations:
            result = engine.decide(ctx)
            assert result == "allow", f"Resource operation {ctx['tool_key']} should be allowed"

    def test_approval_policy_server_allowed(self, engine):
        """Any operation on approval_policy server should be allowed."""
        approval_server_ops = [
            {"tool_key": "mcp__approval_policy__custom_tool", "server": "approval_policy"},
            {"tool_key": "mcp__approval_policy__some_future_tool", "server": "approval_policy"},
        ]

        for ctx in approval_server_ops:
            result = engine.decide(ctx)
            assert result == "allow", f"Approval server operation {ctx['tool_key']} should be allowed"

    def test_other_tools_require_approval(self, engine):
        """All other tools should require approval (ask)."""
        other_tools = [
            {"tool_key": "mcp__echo__echo", "server": "echo"},
            {"tool_key": "mcp__git_ro__list_files", "server": "git_ro"},
            {"tool_key": "mcp__docker_exec__run", "server": "docker_exec"},
            {"tool_key": "mcp__some_server__some_tool", "server": "some_server"},
        ]

        for ctx in other_tools:
            result = engine.decide(ctx)
            assert result == "ask", f"Other tool {ctx['tool_key']} should require approval"

    def test_missing_keys_handled_gracefully(self, engine):
        """Policy should handle missing context keys gracefully."""
        incomplete_contexts = [
            {"server": "echo"},  # Missing tool_key
            {"tool_key": "mcp__echo__echo"},  # Missing server
            {},  # Empty context
        ]

        for ctx in incomplete_contexts:
            result = engine.decide(ctx)
            # Should default to "ask" for safety
            assert result == "ask", f"Incomplete context {ctx} should default to ask"

    def test_policy_version_increments(self, engine):
        """Policy version should increment when policy is updated."""
        initial_version = engine._policy_version
        assert initial_version == 1, "Initial version should be 1"

        # Update policy
        new_policy = '''def decide(ctx):
    return "allow"
'''
        new_version = engine.set_policy(new_policy)

        assert new_version == initial_version + 1, "Version should increment"
        assert engine._policy_version == new_version, "Internal version should match"

    def test_custom_policy_overrides_default(self, engine):
        """Custom policy should override default behavior."""
        # Set a custom policy that allows everything
        allow_all_policy = '''def decide(ctx):
    return "allow"
'''
        engine.set_policy(allow_all_policy)

        # Now even non-allowed tools should be allowed
        result = engine.decide({"tool_key": "mcp__echo__echo", "server": "echo"})
        assert result == "allow", "Custom policy should override default"

    @pytest.mark.parametrize("decision", ["allow", "ask", "deny_continue", "deny_abort"])
    def test_valid_decision_values(self, engine, decision):
        """Policy should accept all valid decision values."""
        custom_policy = f'''def decide(ctx):
    return "{decision}"
'''
        engine.set_policy(custom_policy)

        result = engine.decide({"tool_key": "mcp__test__tool", "server": "test"})
        assert result == decision, f"Policy should return {decision}"

    def test_invalid_policy_syntax_raises_exception(self, engine):
        """Invalid policy syntax should raise an exception."""
        # Use actual syntax error
        invalid_policy = '''def decide(ctx):
    if True
        return "allow"  # Missing colon after if
'''
        engine.set_policy(invalid_policy)

        with pytest.raises(Exception):
            engine.decide({"tool_key": "mcp__test__tool", "server": "test"})

    def test_policy_function_receives_context(self, engine):
        """Policy function should receive the full context."""
        context_checking_policy = '''def decide(ctx):
    # Verify we get the expected context structure
    if "tool_key" in ctx and "server" in ctx and "arguments" in ctx:
        return "allow"
    return "deny_abort"
'''
        engine.set_policy(context_checking_policy)

        full_context = {
            "tool_key": "mcp__test__tool",
            "server": "test",
            "arguments": {"param": "value"}
        }

        result = engine.decide(full_context)
        assert result == "allow", "Policy should receive complete context"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])