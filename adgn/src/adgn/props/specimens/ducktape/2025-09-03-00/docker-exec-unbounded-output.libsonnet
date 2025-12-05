local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Docker Exec MCP returns unbounded stdout/stderr data, which is hazardous for MCP/LLM agents and
    can also lead to process memory growth.

    Primary impact (MCP/LLM):
    - Tool responses are fed back into an LLM context. Returning megabytes of text will quickly
      blow the caller’s context/window, causing truncation, failures, or severe quality drops.
      MCP tools must bound returned payload size.

    Secondary impact (server memory):
    - The server accumulates stdout/stderr into bytearrays with no cap. Very chatty commands can
      cause high memory usage or OOM over time.

    Observed (specimen paths):
    - llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py collects into bytearrays without limits
      and returns the full decoded strings in the tool payload.

    Acceptance criteria (bounded capture in MCP response):
    - Enforce an upper bound (bytes or characters) for stdout/stderr included in the tool return
      (e.g., first N bytes, with a clear truncation note and total sizes).
    - Keep full data optional (e.g., tee to a temp file/log and return a path/reference), but the
      MCP tool’s returned text must be bounded deterministically.
    - Document the cap and truncation behavior in the tool description so callers can plan.

    Optional (server memory hygiene):
    - Apply the same bound in the in-process accumulation path, or stream/tee to a file to avoid
      unbounded memory growth while still allowing capped returns.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [[146, 200], [241, 250]],
  },
)
