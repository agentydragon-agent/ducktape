# SBPL Sandbox Library — Design Draft

Status: draft
Owner: mpokorny (@agentydragon)
Scope: Python Pydantic-first library that models a useful subset of macOS Seatbelt SBPL, validates policies with context-aware warnings, compiles to SBPL text, and optionally wraps sandbox-exec for execution.

## Layering (strict separation)

- Core (SBPL data model + compiler)
  - Pydantic models that directly map to SBPL constructs (1:1). No hidden defaults, no auto-path injection, no parent-dir metadata expansion, no version-dependent tweaks.
  - Compiler: pure function policy -> SBPL text. Deterministic, order-stable. If the policy is invalid syntactically, raise; do not "fix" it.
- Validators (optional, separate module)
  - Read-only analysis of an SBPLPolicy with an explicit Context (e.g., detected macOS version, presence of sandbox-exec).
  - Emit structured findings (warnings/errors) with clear messages and suggested fixes; never mutate the policy.
  - Example warning: SBPL102 MACOS_DYLD_MISSING — "On macOS 14.6+, with default deny, your policy lacks dyld/stdlib read allowances; Python is likely to fail to start. Consider allowing file-map-executable and file-read* for: /System, /usr/lib, /private/var/db/dyld, /System/Volumes/Preboot, /System/Cryptexes."
- Presets/Builders (optional convenience)
  - Small helpers that construct SBPLPolicy instances for common scenarios (e.g., minimal_python_runtime(venv_root)).
  - Explicit and opt-in. They may add standard allowances, but the core compiler remains magic-free.
- Runner wrapper (optional)
  - Executes sandbox-exec with a compiled SBPL file. Does not alter policy; may surface validator findings and handle trace file paths.

Guarantees
- compile(policy) is pure and magic-free; validators and presets live above, and are never invoked implicitly by compile.
- run(policy, argv, ...) uses the exact compiled SBPL; no in-flight modifications.

## Goals
- SBPL-specific, typed representation (Pydantic models) of a practical subset of Seatbelt policies.
- Helpful validations with actionable messages, e.g. macOS version/feature checks, dyld and stdlib prerequisites, known crash/abort patterns, path normalization/overlap checks.
- SBPL text compiler: policy → .sb string (configurable rendering options).
- Optional runner: policy + argv → run via sandbox-exec with trace handling.
- Keep scope limited to SBPL (no bwrap/landlock/etc.). Downstream wrappers may translate into this model.

## Non‑Goals
- Full SBPL language parity (macros, defines, all filters/patterns, complex set expressions).
- Cross-platform sandboxing; this is macOS Seatbelt only.
- Shipping production-hardened isolation on new macOS where sandbox-exec may be deprecated; we document constraints and provide warnings.

## Package namespace and layout

- Package: adgn.seatbelt (SBPL-specific, macOS seatbelt)
- Modules (initial):
  - model.py — Pydantic SBPL types (pure data)
  - compile.py — policy -> SBPL text compiler (pure, deterministic)
  - validate.py — optional validators (messages only; no mutation)
  - runner.py — optional sandbox-exec wrapper (no policy mutation)
  - presets.py — optional builders for common cases (opt-in)

Rationale
- Name is explicit to macOS seatbelt and SBPL; keeps room for other sandbox tech elsewhere (e.g., adgn.sandbox.*).
- Clear separation of concerns within the package matches the layering above.

## Background and current state
- A minimal generator/runner exists today at src/adgn/llm/sandboxer.py (generic policy, not SBPL-typed) and is used by the Jupyter sandbox composer.
- On this host, narrow allowlists for file-read* caused libsandbox aborts (rc −6/134) pre-trace. We’ll detect and warn for such configurations. See docs/llm/sandboxer/SUPPORTED_SANDBOX.md.

## High-level model

- Top-level Policy (deny-by-default model assumed; allow-rules opt-in)
- Rule categories supported:
  - File access: file-read*, file-write*, file-read-metadata, file-map-executable
  - Process core: process*, signal (target self)
  - Network: network-inbound/outbound/bind with (local ip) predicate
  - System/Mach: mach-lookup (by global-name), system-socket, sysctl-read
  - Trace: trace path
- Path filters allowed: literal, subpath (regex/pattern omitted for MVP)

### Pydantic models (skeleton)

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class PathFilter(BaseModel):
    kind: Literal["literal", "subpath"]
    value: str  # absolute path; ~ not allowed
    model_config = ConfigDict(extra="forbid")

class FileRule(BaseModel):
    # Applies to file-read*, file-write*, file-read-metadata, file-map-executable
    action: Literal["allow", "deny"] = "allow"
    op: Literal[
        "file-read*", "file-write*", "file-read-metadata", "file-map-executable"
    ]
    filters: list[PathFilter] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")

class MachLookupRule(BaseModel):
    action: Literal["allow", "deny"] = "allow"
    global_names: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")

class NetworkRule(BaseModel):
    action: Literal["allow", "deny"] = "allow"
    op: Literal["network-inbound", "network-outbound", "network-bind"]
    local_only: bool = False  # renders (local ip)
    model_config = ConfigDict(extra="forbid")

class SystemRule(BaseModel):
    system_socket: bool = False
    sysctl_read: bool = False
    model_config = ConfigDict(extra="forbid")

class ProcessRule(BaseModel):
    allow_process_star: bool = True
    allow_signal_self: bool = True
    model_config = ConfigDict(extra="forbid")

class TraceConfig(BaseModel):
    enabled: bool = False
    path: str | None = None
    model_config = ConfigDict(extra="forbid")

class SBPLPolicy(BaseModel):
    version: int = 1
    default_behavior: Literal["deny", "allow"] = "deny"  # MVP expects "deny"
    process: ProcessRule = Field(default_factory=ProcessRule)
    files: list[FileRule] = Field(default_factory=list)
    network: list[NetworkRule] = Field(default_factory=list)
    mach: MachLookupRule = Field(default_factory=MachLookupRule)
    system: SystemRule = Field(default_factory=SystemRule)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    model_config = ConfigDict(extra="forbid")
```

Notes:
- We keep the schema small and explicit to produce stable JSON Schema for tools/agents.
- Filters are literal/subpath only for MVP; consider regex only after we confirm stability and usefulness.

## Validation plan

1) Platform checks
- Detect macOS via sys.platform and sw_vers (or platform.mac_ver()).
- Locate sandbox-exec; warn if missing or if Apple’s deprecation is detected.

2) Known instability detection
- If default_behavior == "deny" and files rules lack core dyld/std roots, raise error with fix suggestions:
  - Ensure file-map-executable is allowed globally.
  - Ensure file-read* includes: /System, /usr/lib, /private/var/db/dyld, /System/Volumes/Preboot, /System/Cryptexes, /System/Volumes/Preboot/Cryptexes.
- Warn on very narrow file-read* that don’t include the Python venv/bin/lib paths when runner hints are available.
- Warn when using param-style -D expansion (we’ll keep it off initially; add a feature flag guarded by validation).

3) Path hygiene
- Normalize to absolute paths; forbid ~ and relative.
- De-duplicate overlapping filters (subpath("/a") covers literal("/a/file")).
- Optionally cap rule count to avoid pathological policies.

4) Mach/system sanity
- Warn if system_socket or sysctl_read are enabled with default deny and no explicit need.
- Validate global_names for mach-lookup as non-empty, printable.

5) Network policy
- If any network rule is present without local_only and default deny, warn about unintended egress.

Validation output
- Structured warnings with codes and suggested fixes; raise ValidationError on must-fix issues (e.g., missing dyld paths under deny default).

## SBPL compiler (policy → text)

Rendering rules
- Header: (version 1) and default allow/deny line.
- Process block: allow process* and signal self per flags.
- Files: group by op and filter kind; render (allow <op> (literal ...)) and (allow <op> (subpath ...)).
- Parent directory metadata: optional helper to add (allow file-read-metadata (literal "/…")) for path traversal if requested by caller.
- Network: render ops; add (local ip) predicates if local_only.
- System/Mach: render (allow mach-lookup (global-name "...")) per name; (allow system-socket), (allow sysctl-read) as toggles.
- Trace: (trace "<path>") when enabled.

Options
- Compact vs pretty formatting.
- Auto-insert dyld/stdlib allowances flag (off by default; rely on validation to guide users).

## Runner (optional)

- runner.run(policy: SBPLPolicy, argv: list[str], env: dict[str,str] | None, debug: bool) -> CompletedProcess-like result
- Writes policy to a temp file, constructs sandbox-exec args, handles trace file creation (under caller-specified writable dir), returns exit code/stdout/stderr.
- Behavior on error: if sandbox-exec missing or platform unsupported, return a typed error with message; do not crash.

## Integration points

- Jupyter composer can translate its higher-level config into SBPLPolicy directly.
- Existing adgn.llm.sandboxer can be deprecated in favor of this library once parity is reached; initial cut may coexist.

## Limitations and alternatives (documented behavior)

- sandbox-exec is deprecated and may behave differently across macOS versions. The library will:
  - Provide explicit warnings and a compatibility matrix reference.
  - Offer feature flags to switch between literal/subpath rendering strategies.
  - Not attempt to silently broaden policies to “make it work”.
- For stronger/modern isolation, see docs/llm/sandboxer/SUPPORTED_SANDBOX.md (App Sandbox or VM/container). Out of scope here.

## Milestones

1) v0: Schema + compiler
- Implement SBPLPolicy models and compiler.
- Golden tests: policy → expected SBPL strings (fixtures).

2) v0.1: Validation
- Implement platform/dyld checks, path hygiene, network/mach warnings.
- Unit tests for each validator with failing/repair examples.

3) v0.2: Runner
- Minimal runner using sandbox-exec, with trace file handling and debug echo.
- Integration test: echo, python -c, loopback networking sample.

4) v0.3: Composer integration
- Replace adgn.llm.sandboxer usage in the Jupyter composer with this library.
- Keep escape hatch to fallback to old generator if needed.

## Open questions
- Should we include a convenience “stdlib_minimums()” helper that adds dyld roots and venv/bin/lib, or keep that responsibility in callers? (Leaning: helper + explicit toggle.)
- Do we want to support regex filters later? (Only if we have concrete use cases and confidence in stability.)
- How should we expose parent-directory metadata allowances (auto vs explicit)?

## Acceptance criteria
- Given a minimal policy (deny default + dyld roots + venv paths), Python can print("ok") under sandbox-exec on supported macOS.
- Validators produce clear warnings for policies that will likely abort or fail to run Python.
- Compiler output is deterministic and covered by snapshot tests.
- Runner returns structured results without masking sandbox denial vs compiler/runtime abort.

## References
- Existing generator/runner: src/adgn/llm/sandboxer.py
- Jupyter composer policy handling: src/adgn/llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py
- Notes on macOS isolation choices: docs/llm/sandboxer/SUPPORTED_SANDBOX.md

---

## Progress log

- 2025-09-17: Drafted initial design doc with schema, validation plan, compiler/runner outline.
