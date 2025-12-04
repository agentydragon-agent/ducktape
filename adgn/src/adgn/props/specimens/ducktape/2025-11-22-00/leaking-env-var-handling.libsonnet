local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Infrastructure code (infrastructure.py:142) manually reads
    `ADGN_AGENT_PRESETS_DIR` and passes it to `discover_presets()`, leaking
    implementation details. The discovery function should read the env var
    internally.

    Problems: breaks encapsulation (infrastructure knows preset internals),
    duplication risk (every caller must remember env var), hard to change
    (env var rename requires updating all callers), testing difficulty
    (must mock env var).

    Fix: `discover_presets()` should accept `override_dir` parameter (testing
    only) and read `ADGN_AGENT_PRESETS_DIR` internally when override not
    provided. Production calls `discover_presets()`, tests pass `override_dir`.

    Principle: each module owns its environment variables. Compare with
    `resolve_runtime_image()` in images.py, which reads `ADGN_RUNTIME_IMAGE`
    internally.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/infrastructure.py': [
      [142, 142],  // Manual os.getenv("ADGN_AGENT_PRESETS_DIR")
    ],
    'adgn/src/adgn/agent/presets.py': [
      [59, 78],  // discover_presets should read env var internally
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/infrastructure.py'],
    ['adgn/src/adgn/agent/presets.py'],
  ],
)
