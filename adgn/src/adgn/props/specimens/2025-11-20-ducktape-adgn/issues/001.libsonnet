local I = import '../../specimens/lib.libsonnet';

// iss-001: Normalization function for type that cannot occur (_normalize_call_arguments)
//
// Context:
// - FunctionCallItem.arguments is typed as `str | None` (never dict)
// - All creation paths serialize to JSON string at construction time:
//   - From OpenAI SDK: already a string (model.py:302 comment: "Already string from SDK")
//   - From builder: explicitly calls json.dumps() (builders.py:20)
// - The function accepts `dict[str, Any] | str | None` and has runtime type checking
// - The json.dumps() fallback branch is unreachable given actual usage
//
// Key insight (from user):
// "There naturally should NEVER be a path where one wouldn't know whether they hold a json dict
// or a string or None. Therefore a caller should always be reduced to *either* a json.dumps *or*
// identity."
//
// Properties violated:
// 1. type-correctness-and-specificity: Type signature too wide (includes dict case that never happens)
// 2. no-dead-code: The json.dumps() branch is unreachable
// 3. truthfulness: Function suggests runtime ambiguity that doesn't exist
//
// Fix: Remove the function entirely and use `function_call.arguments` directly (already str | None)

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
  properties=['type-correctness-and-specificity', 'no-dead-code', 'truthfulness'],
  filesToRanges={
    'adgn/src/adgn/agent/agent.py': [
      [149, 160],  // Function definition
      [269, 269],  // Call site that could be simplified
    ],
  },
)
