local I = import '../../specimens/lib.libsonnet';

// iss-001: Normalization function for type that cannot occur

I.issueOneOccurrence(
  rationale=|||
    Function `_normalize_call_arguments` accepts `dict[str, Any] | str | None` but the dict case
    never occurs in practice. The only caller passes `FunctionCallItem.arguments` which is typed
    as `str | None`. All FunctionCallItem construction paths guarantee JSON string format:
    - OpenAI SDK response: arguments already serialized to string
    - Programmatic construction: explicitly calls json.dumps() at construction time

    The runtime type check `isinstance(arguments, str)` and fallback `json.dumps()` are defensive
    programming against a case that cannot happen according to the type system.

    There should never be a code path with runtime ambiguity about whether data is serialized or not.
    Either serialize at construction (done here), or serialize at use site, but never both with
    runtime type inspection.

    Fix: Remove function entirely. Use `function_call.arguments` directly in agent.py:269.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/agent.py': [
      [149, 160],  // Function definition
      [269, 269],  // Call site that could be simplified
    ],
  },
)
