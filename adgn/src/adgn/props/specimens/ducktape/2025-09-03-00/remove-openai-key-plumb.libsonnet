local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The OpenAI SDK already reads `OPENAI_API_KEY` and base URL env vars; hand-rolling a client factory that fetches
    env vars duplicates configuration paths and adds code surface without value.

    Prefer:
    - Call `openai.OpenAI()` directly and let the SDK read environment variables; or
    - Inject a client (DI) from the caller/tests to keep construction policy out of core logic.

    This reduces duplication and makes tests simpler (just pass a client/fake).
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[45, 55], [100, 111]],
  },
)
