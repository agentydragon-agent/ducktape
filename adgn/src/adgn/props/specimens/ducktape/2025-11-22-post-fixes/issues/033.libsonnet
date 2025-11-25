local I = import '../../specimens/lib.libsonnet';

// iss-033: Leaking environment variable handling into downstream components

I.issueOneOccurrence(
  rationale= |||
    Infrastructure code manually reads `ADGN_AGENT_PRESETS_DIR` environment variable
    and passes it to `discover_presets()`, when the discovery helper should be responsible
    for all environment variable handling related to preset discovery.

    **Problem: Breaking encapsulation of preset discovery**

    The `discover_presets()` function in `presets.py` is designed to handle preset
    discovery, but callers are manually reading the `ADGN_AGENT_PRESETS_DIR` environment
    variable instead of letting the discovery function handle it.

    **Current implementation (infrastructure.py, line 142):**
    ```python
    async def _build_approval_engine(self) -> ApprovalPolicyEngine:
        """Resolve the approval policy (from persistence, initial_policy arg, preset,
        or default) and constructs the approval policy engine.
        """
        row = await self.persistence.get_agent(self.agent_id)
        preset_name: str | None = None
        if row:
            preset_name = row.preset

        presets = discover_presets(os.getenv("ADGN_AGENT_PRESETS_DIR")) if preset_name else {}
        preset = presets.get(preset_name) if preset_name else None
        ...
    ```

    **Current discover_presets signature (presets.py, line 59):**
    ```python
    def discover_presets(env_dir: str | None = None) -> dict[str, AgentPreset]:
        """Search for preset files in configured and default directories.

        Precedence: env_dir (if set) first, then DEFAULT_PRESETS_DIRS.
        Later directories do not override earlier names.
        """
        out: dict[str, AgentPreset] = {}
        roots: list[Path] = []
        if env_dir:
            roots.append(Path(env_dir))
        # Resolve only via platformdirs: user_config_dir('adgn') / 'presets'
        roots.append(_xdg_presets_dir())
        ...
    ```

    **Problems:**

    1. **Breaks encapsulation**: Infrastructure layer knows about preset implementation details
    2. **Duplication risk**: Every caller must remember to read `ADGN_AGENT_PRESETS_DIR`
    3. **Hard to change**: If env var name changes, must update all callers
    4. **Unclear responsibility**: Who owns the env var? presets.py or callers?
    5. **Testing difficulty**: Must mock env var in tests instead of parameter
    6. **Inconsistent with similar patterns**: Other discovery helpers read their own env vars

    **Why this happened:**

    The `env_dir` parameter was likely added to allow:
    - Testing with custom directories (pass explicit path)
    - Overriding via environment (pass `os.getenv(...)`)

    But the second use case should be internal to `discover_presets()`, not exposed
    to callers.

    **The correct approach:**

    Make `discover_presets()` handle the environment variable internally:

    ```python
    def discover_presets(*, override_dir: str | Path | None = None) -> dict[str, AgentPreset]:
        """Search for preset files in configured and default directories.

        Args:
            override_dir: Optional directory to use instead of env var + defaults.
                         Useful for testing. If None, uses ADGN_AGENT_PRESETS_DIR
                         env var (if set) followed by XDG config directory.

        Precedence: override_dir > ADGN_AGENT_PRESETS_DIR env > XDG config > built-in default
        """
        out: dict[str, AgentPreset] = {}
        roots: list[Path] = []

        # Handle override for testing
        if override_dir is not None:
            roots.append(Path(override_dir))
        else:
            # Read env var internally (production path)
            env_dir = os.getenv("ADGN_AGENT_PRESETS_DIR")
            if env_dir:
                roots.append(Path(env_dir))

        # Always check XDG directory
        roots.append(_xdg_presets_dir())

        for r in roots:
            for name, preset in load_presets_from_dir(r).items():
                if name not in out:
                    out[name] = preset

        # Always include a built-in default if none present
        if "default" not in out:
            out["default"] = AgentPreset(
                name="default",
                description="Default UI agent",
                system=None,
                specs={}
            )
        return out
    ```

    **Then callers become simpler:**

    ```python
    async def _build_approval_engine(self) -> ApprovalPolicyEngine:
        """Resolve the approval policy (from persistence, initial_policy arg, preset,
        or default) and constructs the approval policy engine.
        """
        row = await self.persistence.get_agent(self.agent_id)
        preset_name: str | None = None
        if row:
            preset_name = row.preset

        # Discovery helper handles env var internally
        presets = discover_presets() if preset_name else {}
        preset = presets.get(preset_name) if preset_name else None
        ...
    ```

    **Benefits:**

    1. **Single responsibility**: presets.py owns all preset discovery logic
    2. **No duplication**: Env var read in one place only
    3. **Easy to change**: Update env var name in one location
    4. **Clear ownership**: `ADGN_AGENT_PRESETS_DIR` lives in presets.py
    5. **Better testing**: Tests use `override_dir`, production uses env var
    6. **Consistent pattern**: Similar to `resolve_runtime_image()` in images.py

    **Comparison with good pattern (images.py):**

    ```python
    # images.py - GOOD: handles env var internally
    def resolve_runtime_image(*, fallback: str = DEFAULT_RUNTIME_IMAGE) -> str:
        """Return the Docker image tag used for runtime + policy evaluation flows."""
        img = os.getenv("ADGN_RUNTIME_IMAGE")  # ← Reads env var internally
        if img:
            return img
        return fallback

    # Callers just call it, no env var knowledge needed
    runtime_image = resolve_runtime_image()
    ```

    **When to expose env var parameter:**

    - Never for production use (function should read it internally)
    - Only for testing/injection via named parameter (like `override_dir`)
    - Document clearly: "This parameter is for testing; production uses env var"

    **Migration:**

    1. Update `discover_presets()` to read `ADGN_AGENT_PRESETS_DIR` internally
    2. Rename parameter from `env_dir` to `override_dir` to clarify intent
    3. Update infrastructure.py to call `discover_presets()` without arguments
    4. Update tests to use `override_dir` explicitly (not env var mocking)

    **Testing pattern:**

    ```python
    # Bad: mock environment variable
    @patch.dict(os.environ, {"ADGN_AGENT_PRESETS_DIR": "/test/presets"})
    def test_discover_presets():
        presets = discover_presets()
        ...

    # Good: use explicit override parameter
    def test_discover_presets(tmp_path):
        test_presets = tmp_path / "presets"
        test_presets.mkdir()
        presets = discover_presets(override_dir=test_presets)
        ...
    ```

    **Principle: "Encapsulate environment access"**

    - Each module owns its environment variables
    - Callers don't need to know implementation details (env var names)
    - Testing uses explicit parameters, not env var mocking
    - Changes to env var names are localized to one module
  |||,
  properties=['encapsulate-environment-access', 'single-responsibility', 'avoid-leaking-abstractions'],
  filesToRanges={
    'adgn/src/adgn/agent/runtime/infrastructure.py': [
      [142, 142],  // Manual os.getenv("ADGN_AGENT_PRESETS_DIR")
    ],
    'adgn/src/adgn/agent/presets.py': [
      [59, 78],  // discover_presets should read env var internally
    ],
  },
  gap_note= |||
    This finding illustrates **"encapsulate-environment-access"**: modules that
    provide discovery/resolution functions should handle their own environment
    variables internally, not require callers to read and pass them.

    Principle: Each module owns its configuration sources:
    - Environment variables
    - Config files
    - Default values
    - Override mechanisms

    Callers should only need to:
    - Call the function with domain parameters (e.g., preset name)
    - Optionally provide explicit overrides for testing
    - NOT know about env var names or config file locations

    Benefits of encapsulating env access:
    - Single source of truth for configuration
    - Easy to change env var names (one place)
    - Clear ownership (which module owns which config)
    - Better testing (explicit overrides, not env mocking)
    - Less duplication (not every caller reads env vars)

    Common patterns:

    **Good: Function handles env var internally**
    ```python
    def resolve_foo(*, override: str | None = None) -> str:
        if override is not None:
            return override
        return os.getenv("APP_FOO") or "default"
    ```

    **Bad: Caller must read env var**
    ```python
    def resolve_foo(value: str | None = None) -> str:
        return value or "default"

    # Every caller:
    foo = resolve_foo(os.getenv("APP_FOO"))  # ← Duplication
    ```

    When to expose configuration parameters:
    - For testing (explicit override, clearly documented)
    - For programmatic configuration (not from environment)
    - For dependency injection (pass configured objects)

    Related to **"single-responsibility"**: the presets module is responsible for
    all preset discovery logic, including reading relevant environment variables.
    Infrastructure code shouldn't need to know how presets are discovered.

    Related to **"avoid-leaking-abstractions"**: environment variable names are
    implementation details. Callers shouldn't need to know them to use discovery
    functions.
  |||,
)
