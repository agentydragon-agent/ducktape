local I = import '../../lib.libsonnet';

// Merged: walrus-env-token, walrus-eval-index, walrus-models-getattr
// All describe assign-and-check patterns that should use walrus operator

I.issue(
  rationale= |||
    Multiple locations extract values and immediately test or use them, where the
    walrus operator (:=) would combine assignment and usage more idiomatically.

    **Pattern 1: os.environ.get with immediate check** (auth.py:113-116):
    env_token = os.environ.get("ADGN_UI_TOKEN")
    if env_token:
        logger.info("Using ADGN_UI_TOKEN from environment")
        return env_token

    Should use: if env_token := os.environ.get("ADGN_UI_TOKEN"):

    **Pattern 2: Create object and immediately use** (eval_harness.py:580-581):
    eval_index = EvalIndex(samples=list(entries))
    (root / "index.json").write_text(eval_index.model_dump_json(...), ...)

    The variable is needed later but can be created inline:
    (root / "index.json").write_text((eval_index := EvalIndex(samples=list(entries))).model_dump_json(...), ...)

    **Pattern 3: dict.get with None check** (typed_stubs.py:205-207):
    models = self._models.get(name)
    if not models:
        raise AttributeError(name)

    Should use: if not (models := self._models.get(name)):

    Benefits of walrus operator (PEP 572):
    - Combines retrieval and check into one line
    - More concise without sacrificing readability
    - Standard Python 3.8+ pattern for "get and check" scenarios
    - Variable scope is correctly limited to where it's needed
    - Consistent with modern Python idioms

    Note: These transformations maintain the same behavior while reducing
    line count and making the bind-and-test pattern explicit.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [113, 116],  // env_token extraction and check
    ],
    'adgn/src/adgn/props/eval_harness.py': [
      [580, 581],  // eval_index creation and immediate write use
    ],
    'adgn/src/adgn/mcp/stubs/typed_stubs.py': [
      [205, 207],  // models.get and check in __getattr__
      [181, 183],  // Same pattern in error method
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/auth.py'],
    ['adgn/src/adgn/props/eval_harness.py'],
    ['adgn/src/adgn/mcp/stubs/typed_stubs.py'],
  ],
)
