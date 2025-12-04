local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 58-60 define `AgentStatus` which inherits from `AgentStatusCore` but adds nothing (no fields, methods, or config). Pure noop wrapper.

    Used at lines 266-267 for response model/return type, and line 270 performs unnecessary conversion (`AgentStatus(**core.model_dump(mode="json"))`).

    Delete the class entirely. Replace all uses with `AgentStatusCore`. Simplify lines 268-270 to just `return await build_agent_status_core(app, agent_id)`. Keep `build_agent_status_core` as shared function (used in 2 places).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [58, 60],  // AgentStatus class (noop, delete)
      [266, 266],  // response_model=AgentStatus (use AgentStatusCore)
      [267, 267],  // -> AgentStatus return type (use AgentStatusCore)
      [268, 270],  // Unnecessary conversion (just return await build_agent_status_core)
    ],
  },
)
