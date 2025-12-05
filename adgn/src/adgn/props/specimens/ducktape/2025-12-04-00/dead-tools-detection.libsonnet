local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Tool detection machinery (`detect_tools()`, `tools_section()` macro, `available_tools` parameter) is dead code because `include_tools` is hardcoded to `False` in `build_standard_context()`.

    The flow:
    1. `cli/main.py` calls `detect_tools()` to check which analysis tools (ruff, mypy, vulture, etc.) are available on PATH
    2. Result passed to `build_standard_context(available_tools=...)`
    3. Context sets `include_tools: False` (line 108)
    4. Jinja template checks `{% if include_tools %}` before rendering `tools_section(available_tools)`
    5. Condition is never true, so tool list never appears in prompts

    The `detect_tools()` function checks 21 tools (ruff, mypy, pyright, vulture, bandit, etc.) but this work is wasted since the output is never used.

    **Possible resolutions:**

    1. **Remove dead code** (simplest):
       - Delete `detect_tools()` from `cli/shared.py`
       - Remove `available_tools` parameter from `build_standard_context()`
       - Remove `tools_section()` macro from `prompts/_partials.j2`
       - Remove `{% if include_tools %}` conditional from `prompts/_base.j2.md`

    2. **Enable the feature**:
       - Set `include_tools=True` in appropriate contexts (e.g., when running `check` or `fix` commands)
       - Would tell LLM which tools it can use for analysis
       - Consider making it configurable per-command rather than always False

    3. **Autonomous tool detection**:
       - Remove host-side detection entirely
       - Provide LLM with reference list of ~100 common tools
       - Let LLM attempt to use tools and discover what's available
       - More robust (works in Docker, doesn't depend on host PATH)
       - Example prompt: "Common analysis tools: ruff, mypy, vulture, bandit... Try running tools to see what's available"

    Note: Host-side detection (`shutil.which()`) is problematic because the critic runs in Docker, so host PATH is irrelevant. Option 3 (autonomous detection) better matches the actual execution environment.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/prompts/util.py': [
      [86, 88],   // available_tools parameter
      [105, 105], // available_tools in context dict
      [108, 108], // include_tools: False (the smoking gun)
    ],
    'adgn/src/adgn/props/cli_app/shared.py': [[76, 111]],       // detect_tools() function definition
    'adgn/src/adgn/props/cli_app/main.py': [448],               // detect_tools() call site
    'adgn/src/adgn/props/prompts/_partials.j2': [[8, 21]],      // tools_section() macro
    'adgn/src/adgn/props/prompts/_base.j2.md': [86],            // conditional include
  },
  expect_caught_from=[
    // util.py NOT included: seeing "include_tools: False" leaves open "what if some context passes True?"
    // Would require deeper search to prove no caller ever passes True - tangential investigation
    ['adgn/src/adgn/props/cli_app/shared.py'],       // See detect_tools(), trace callers to dead end
    ['adgn/src/adgn/props/cli_app/main.py'],         // See call, trace to discover it's gated by False
    ['adgn/src/adgn/props/prompts/_partials.j2'],    // See tools_section() macro never called (gated by False)
    ['adgn/src/adgn/props/prompts/_base.j2.md'],     // See include_tools conditional, search for assignments → always False
  ],
)
