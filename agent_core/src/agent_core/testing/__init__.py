"""Testing utilities for agent_core.

This subpackage provides reusable test infrastructure for packages built on agent_core:
- Mock OpenAI clients (FakeOpenAIModel, CapturingOpenAIModel)
- Response factories (ResponsesFactory, StepRunner)
- Echo server for MCP testing
- Pytest fixtures (via fixtures module)
- Hamcrest matchers for assertions
- Declarative step types for mock conversations

Usage in downstream packages:
    # In conftest.py
    pytest_plugins = ["agent_core.testing.fixtures"]

Install with: pip install agent-core[testing]
"""

from agent_core.testing.assertions import (
    assert_and_extract,
    assert_last_call,
    extract_output,
    get_last_function_output,
    is_all_function_calls,
    is_all_user_messages,
)
from agent_core.testing.echo_server import ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput, EchoOutput, make_echo_server
from agent_core.testing.fixtures import FAIL_TOOL_NAME, RecordingHandler, ValidationServer
from agent_core.testing.matchers import (
    HasErrorText,
    assert_function_call_output_structured,
    assert_items_exclude_instance,
    assert_items_include_instances,
    assert_payloads_have,
    contains_err,
    has_function_call_output_structured,
    is_function_call_output,
    is_function_call_output_end_turn,
    is_ui_message,
    tool_call_with_error_text,
)
from agent_core.testing.openai_mock import LIVE, CapturingOpenAIModel, FakeOpenAIModel, NoopOpenAIClient, make_mock
from agent_core.testing.responses import ResponsesFactory, StepRunner
from agent_core.testing.steps import (
    AssertDockerExecThenCall,
    AssertDockerExecThenFinish,
    AssistantMessage,
    CheckThenCall,
    DockerExecCall,
    EchoCall,
    EmptyArgs,
    ExtractThenCall,
    Finish,
    MakeCall,
    Step,
)

__all__ = [
    "ECHO_MOUNT_PREFIX",
    "ECHO_TOOL_NAME",
    "FAIL_TOOL_NAME",
    "LIVE",
    "AssertDockerExecThenCall",
    "AssertDockerExecThenFinish",
    "AssistantMessage",
    "CapturingOpenAIModel",
    "CheckThenCall",
    "DockerExecCall",
    "EchoCall",
    "EchoInput",
    "EchoOutput",
    "EmptyArgs",
    "ExtractThenCall",
    "FakeOpenAIModel",
    "Finish",
    "HasErrorText",
    "MakeCall",
    "NoopOpenAIClient",
    "RecordingHandler",
    "ResponsesFactory",
    "Step",
    "StepRunner",
    "ValidationServer",
    "assert_and_extract",
    "assert_function_call_output_structured",
    "assert_items_exclude_instance",
    "assert_items_include_instances",
    "assert_last_call",
    "assert_payloads_have",
    "contains_err",
    "extract_output",
    "get_last_function_output",
    "has_function_call_output_structured",
    "is_all_function_calls",
    "is_all_user_messages",
    "is_function_call_output",
    "is_function_call_output_end_turn",
    "is_ui_message",
    "make_echo_server",
    "make_mock",
    "tool_call_with_error_text",
]
