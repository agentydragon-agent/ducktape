local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The code swallows all exceptions from model_dump and continues:

      try:
        prior_tool_calls.append(item.model_dump(exclude_none=True))
      except Exception:
        pass

    This hides serialization bugs and corrupts the transcript/tool-call history.
    Do not catch exceptions here; let them surface and fail loudly. If there were
    a specific, expected error, catch it narrowly with context and re-raise — but
    in this location the correct fix is to remove the try/except entirely.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[204, 207]],
  },
)
