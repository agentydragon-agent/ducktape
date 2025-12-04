local I = import '../../lib.libsonnet';

// iss-067: Prefer system_message over generic system parameter name
I.issue(
  snapshot='ducktape/2025-09-03-00',
  rationale=|||
    The parameter name `system` is generic/overloaded and can be confused with modules/variables.
    Prefer a more specific name like `system_message` to communicate intent clearly (pairs with
    `SYSTEM_INSTRUCTIONS`). Rename the arg and private field for clarity.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[96, 106]],
  },
)
