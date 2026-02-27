import pytest_bazel

from approval_gate.proxy_server import _wrap_tool_schema


def test_wraps_original_schema_under_input():
    original = {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
    result = _wrap_tool_schema(original)
    assert result["properties"]["input"] == original


def test_adds_justification_and_session_key_at_top_level():
    result = _wrap_tool_schema({})
    assert "justification" in result["properties"]
    assert "session_key" in result["properties"]


def test_required_contains_input_and_justification():
    result = _wrap_tool_schema({})
    assert "input" in result["required"]
    assert "justification" in result["required"]
    # session_key is optional (has a default)
    assert "session_key" not in result["required"]


def test_no_collision_between_input_fields_and_envelope_fields():
    # A backend tool with fields named 'justification' and 'session_key' must not
    # shadow or be shadowed by the envelope fields — they live under 'input'.
    original = {
        "type": "object",
        "properties": {"justification": {"type": "integer"}, "session_key": {"type": "boolean"}},
    }
    result = _wrap_tool_schema(original)
    # Backend fields remain untouched inside 'input'
    assert result["properties"]["input"]["properties"]["justification"] == {"type": "integer"}
    assert result["properties"]["input"]["properties"]["session_key"] == {"type": "boolean"}
    # Envelope fields are the approval-gate versions, not the backend's
    assert result["properties"]["justification"]["type"] == "string"
    assert result["properties"]["session_key"]["type"] == ["string", "null"]


def test_does_not_mutate_original_schema():
    original: dict = {"properties": {"x": {"type": "string"}}, "required": ["x"]}
    _wrap_tool_schema(original)
    assert list(original["properties"].keys()) == ["x"]
    assert original["required"] == ["x"]


if __name__ == "__main__":
    pytest_bazel.main()
