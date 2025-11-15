"""Test multiline predicate evaluation."""

from datetime import datetime, timedelta

from ducktape_llm_common.claude_linter_v2.access.context import PredicateContext
from ducktape_llm_common.claude_linter_v2.access.evaluator import PredicateEvaluator
from ducktape_llm_common.claude_linter_v2.types import SessionID
import pytest


class TestMultilinePredicates:
    """Test complex multiline predicate evaluation."""

    @pytest.fixture
    def evaluator(self):
        """Create evaluator instance."""
        return PredicateEvaluator()

    @pytest.fixture
    def context(self):
        """Create test context."""
        return PredicateContext(
            tool="Bash",
            path="/home/user/test.py",
            content="print('hello')",
            command="grep -r pattern",
            session_id=SessionID("test-session"),
            timestamp=datetime.now(),
        )

    def test_simple_multiline_function(self, evaluator, context):
        """Test basic multiline function."""
        predicate = """
def check_bash(ctx):
    return ctx.tool == "Bash"

check_bash(ctx)
"""
        assert evaluator.evaluate(predicate, context) is True

        # Change tool
        context.tool = "Edit"
        assert evaluator.evaluate(predicate, context) is False

    def test_complex_shell_pipeline_check(self, evaluator, context):
        """Test complex shell pipeline validation."""
        predicate = """
import shlex

def is_safe_pipeline(ctx):
    if ctx.tool != "Bash" or not ctx.command:
        return False

    SAFE_COMMANDS = {
        "grep": {"-r", "-i", "-n", "-v", "-E"},
        "find": {"-name", "-type", "-path"},
        "cat": set(),
        "wc": {"-l", "-w", "-c"},
    }

    # Parse pipeline
    parts = ctx.command.split("|")
    for part in parts:
        part = part.strip()
        if not part:
            continue

        try:
            tokens = shlex.split(part)
            if not tokens:
                continue

            cmd = tokens[0]
            if cmd not in SAFE_COMMANDS:
                return False

            # Check flags
            allowed_flags = SAFE_COMMANDS[cmd]
            for token in tokens[1:]:
                if token.startswith("-") and token not in allowed_flags:
                    return False

        except ValueError:
            return False

    return True

is_safe_pipeline(ctx)
"""
        # Safe pipeline
        context.command = "grep -r pattern | wc -l"
        assert evaluator.evaluate(predicate, context) is True

        # Unsafe command
        context.command = "rm -rf /"
        assert evaluator.evaluate(predicate, context) is False

        # Unknown flag
        context.command = "grep -X pattern"
        assert evaluator.evaluate(predicate, context) is False

    def test_domain_specific_mcp_check(self, evaluator):
        """Test domain-specific MCP tool validation (stock broker example)."""
        predicate = """
# Stock broker MCP safety check
MAX_ACCOUNT_VALUE = 500
MAX_MARGIN = 5

def check_broker_limits(ctx):
    if not ctx.tool.startswith("mcp_broker_"):
        return True  # Not a broker tool

    # Parse the tool input for trade parameters
    tool_input = getattr(ctx, "tool_input", {})

    # Check account value limit
    if "amount" in tool_input:
        if tool_input["amount"] > MAX_ACCOUNT_VALUE:
            return False

    # Check margin limit
    if "margin_multiplier" in tool_input:
        if tool_input["margin_multiplier"] > MAX_MARGIN:
            return False

    # Check for forbidden operations
    forbidden_ops = ["withdraw", "transfer", "close_account"]
    if any(op in ctx.tool for op in forbidden_ops):
        return False

    return True

check_broker_limits(ctx)
"""
        # Create context for broker MCP
        broker_context = PredicateContext(
            tool="mcp_broker_place_order", session_id=SessionID("broker-session"), timestamp=datetime.now()
        )

        # Add tool_input to context (simulating MCP tool input)
        broker_context.tool_input = {"amount": 100, "margin_multiplier": 2}
        assert evaluator.evaluate(predicate, broker_context) is True

        # Exceed amount limit
        broker_context.tool_input = {"amount": 1000, "margin_multiplier": 2}
        assert evaluator.evaluate(predicate, broker_context) is False

        # Exceed margin limit
        broker_context.tool_input = {"amount": 100, "margin_multiplier": 10}
        assert evaluator.evaluate(predicate, broker_context) is False

        # Forbidden operation
        broker_context.tool = "mcp_broker_withdraw"
        assert evaluator.evaluate(predicate, broker_context) is False

    def test_result_variable_style(self, evaluator, context):
        """Test using result variable instead of expression."""
        predicate = """
# Check if editing Python test files only
if ctx.tool == "Edit" and ctx.path:
    path = pathlib.Path(ctx.path)
    result = path.suffix == ".py" and "test" in path.name
else:
    result = False
"""
        context.tool = "Edit"
        context.path = "/home/user/test_foo.py"
        assert evaluator.evaluate(predicate, context) is True

        context.path = "/home/user/foo.py"
        assert evaluator.evaluate(predicate, context) is False

    def test_imports_and_modules(self, evaluator, context):
        """Test that imports work correctly."""
        predicate = """
import json
import re
from datetime import datetime, timedelta

def check_recent_activity(ctx):
    # Check if activity is within last hour
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    return ctx.timestamp > one_hour_ago

check_recent_activity(ctx)
"""
        # Recent timestamp
        context.timestamp = datetime.now()
        assert evaluator.evaluate(predicate, context) is True

        # Old timestamp
        context.timestamp = datetime.now() - timedelta(hours=2)
        assert evaluator.evaluate(predicate, context) is False

    def test_error_handling(self, evaluator, context):
        """Test error handling in multiline predicates."""
        # Missing return/result
        predicate = """
def check(ctx):
    if ctx.tool == "Bash":
        pass  # Forgot to return!
"""
        with pytest.raises(ValueError, match="must either set 'result' variable or end with an expression"):
            evaluator.evaluate(predicate, context)

        # Syntax error
        predicate = """
def check(ctx:
    return True
"""
        with pytest.raises(ValueError, match="Invalid multiline predicate"):
            evaluator.evaluate(predicate, context)

    def test_mixed_single_and_multiline(self, evaluator, context):
        """Test that single-line predicates still work."""
        # Single line
        assert evaluator.evaluate("ctx.tool == 'Bash'", context) is True
        assert evaluator.evaluate("safe_git_commands(ctx)", context) is False  # Not a git command

        # Single line with function call
        context.command = "git status"
        assert evaluator.evaluate("safe_git_commands(ctx)", context) is True
