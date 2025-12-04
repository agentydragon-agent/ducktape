local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Infrastructure code manually reads `ADGN_AGENT_PRESETS_DIR` and passes it to
    `discover_presets()`. The discovery helper should own all environment variable
    handling for preset discovery.

    **Problem: Leaking implementation details**

    `infrastructure.py:142` does `discover_presets(os.getenv("ADGN_AGENT_PRESETS_DIR"))`,
    exposing preset implementation details to callers. The `discover_presets()` function
    should read the env var internally.

    **Impact:**
    - Breaks encapsulation (infrastructure knows preset internals)
    - Duplication risk (every caller must remember to read env var)
    - Hard to change (env var name change requires updating all callers)
    - Testing difficulty (must mock env var instead of parameter)

    **Solution: Internalize env var reading**

    | Aspect | Current | Correct |
    |--------|---------|---------|
    | Env var read | Caller's responsibility | Function's responsibility |
    | Parameter | `env_dir` (ambiguous) | `override_dir` (testing only) |
    | Production usage | `discover_presets(os.getenv(...))` | `discover_presets()` |
    | Test usage | Mock env var | Pass `override_dir` |

    ```python
    def discover_presets(*, override_dir: str | Path | None = None) -> dict[str, AgentPreset]:
        """Precedence: override_dir > ADGN_AGENT_PRESETS_DIR env > XDG config"""
        if override_dir is not None:
            roots = [Path(override_dir)]
        else:
            # Read env var internally (production)
            env_dir = os.getenv("ADGN_AGENT_PRESETS_DIR")
            roots = [Path(env_dir)] if env_dir else []
        roots.append(_xdg_presets_dir())
        ...
    ```

    **Benefits:**
    - Single responsibility (presets.py owns discovery logic)
    - No duplication (env var read once)
    - Clear ownership (`ADGN_AGENT_PRESETS_DIR` lives in presets.py)
    - Better testing (explicit override, no mocking)

    **Comparison with good pattern:** `resolve_runtime_image()` in images.py reads
    `ADGN_RUNTIME_IMAGE` internally; callers just call it without env var knowledge.

    **Principle:** Each module owns its environment variables. Callers shouldn't know
    implementation details. Testing uses explicit parameters, not env var mocking.
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
