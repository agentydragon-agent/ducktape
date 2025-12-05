local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    `responses_turn` and `responses_followup_with_tool_outputs` in the CLI duplicate ~20 lines of logic:
    assembling instructions (with optional MCP block), listing tools, building the payload, and
    calling Responses. This copy/paste raises drift risk and splits responsibility between CLI and agent.

    Preferred design:
    - Keep agent.py as the single owner of the agent loop and Responses flow (instructions assembly,
      tools listing, payload construction, result parsing).
    - Make cli.py a thin wrapper that delegates to the agent (or a single helper) rather than repeating logic.

    Concretely: extract a shared helper (or call through to agent) used by both paths, removing the duplicate
    try/except + instruction assembly + tools list + responses.create blocks.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[188, 218], [276, 306]],
  },
)
