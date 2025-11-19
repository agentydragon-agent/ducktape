# SBPL Library TODO / Potential Extensions

Status: living list of gaps and candidates for future work. Focus is on `adgn.seatbelt` (model/compile/validate/runner) and closely related tooling.

## Path Filters & Predicates
- [ ] Support additional SBPL path predicates beyond `literal` and `subpath` (e.g., `regex`, `home-literal`, `home-subpath`).
- [ ] Optional `vnode-type` predicate support for finer file rules (regular, dir, symlink, socket, etc.).
- [ ] Path normalization utilities and overlap detection (dedupe when `subpath("/a")` covers `literal("/a/file")`).
- [ ] Configurable parent-directory `file-read-metadata` expansion helper (builder-level, not in the compiler core).

## Boolean Composition & Macros
- [ ] Filter composition (logical and/or/not) for complex conditions where SBPL supports it.
- [ ] Macro/`define` support for reusable groups (kept explicit; no hidden defaults).
- [ ] Optional include/import of fragments (controlled; disabled by default).

## Operations Coverage (SBPL Surface)
- [ ] File ops beyond current subset: finer-grained `file-read-data`, `file-read-xattr`, `file-write-xattr`, `file-rename`, `file-unlink`, etc.
- [ ] Additional system ops: `sysctl-write`, other `system-*` toggles commonly used in Apple profiles.
- [ ] Mach: `mach-register` and other Mach message/port operations, in addition to existing `mach-lookup`.
- [ ] POSIX/IPC scopes (where applicable and stable): shared memory, semaphores, message queues, etc.
- [ ] IOKit and device access toggles where SBPL exposes safe, documented predicates.

## Network Predicates
- [ ] Extend network rules with remote IP/port predicates (ingress/egress scoping), protocol scoping (tcp/udp), and richer loopback options.

## Compiler Enhancements
- [ ] Strictly magic-free compile: remove or make optional the current implicit write for trace path. (See `compile_sbpl()` trace block.)
- [ ] Pretty/compact formatting options (indentation, grouping by op), stable sorting toggles while preserving caller order when desired.
- [ ] Robust SBPL quoting/escaping (backslashes, quotes, non‑ASCII, control chars) with round‑trip tests.
- [ ] Emit comments (optional) for readability in generated profiles.

## Validation Improvements
- [ ] Structured findings: codes, severity, categories, and suggested fixes (not just strings).
- [ ] Must‑fix vs warn classification, with an option to raise on must‑fix.
- [ ] Path hygiene: absolute‑path enforcement, `~`/relative rejection (message now; add targeted checks).
- [ ] Overlap analysis and rule‑count guardrails (warn on pathological policies).
- [ ] macOS compatibility matrix and heuristic checks (dyld/stdlib coverage, known abort patterns) with OS‑specific guidance.

## Runner & Tooling
- [ ] Synchronous convenience wrapper around async APIs (ergonomics only).
- [ ] Configurable artifacts directory and retention policy; consistent trace/unified‑log collection toggles.
- [ ] Optional unified log harvest when exit!=0 (currently disabled by default) with safe time windows.
- [ ] CLI (`python -m adgn.seatbelt`) with subcommands: `validate`, `compile`, `run` (thin wrapper around the library).

## Presets / Builders
- [ ] Provide explicit builders for common scenarios (opt‑in):
  - [ ] Minimal Python runtime (dyld roots, venv/bin/lib, device basics, loopback net).
  - [ ] Jupyter kernel sandbox presets (tunable read/write mounts, loopback).
  - [ ] “Echo smoke test” preset for environment validation.

## Parsing & Interop
- [ ] SBPL parser for round‑trip: `.sb` → `SBPLPolicy` (subset), enabling linting/normalization of existing profiles.
- [ ] Import helpers for Apple sample profiles (best‑effort mapping into our typed subset).

## Docs & Testing
- [ ] Expand design doc with a formal subset spec and explicit non‑goals per macOS version.
- [ ] Golden tests for compiler output; snapshot tests for validation messages.
- [ ] Cookbook examples (policy → effect) and troubleshooting playbook for common denies/aborts.

## Compatibility & Fallbacks
- [ ] Clear behavior when `sandbox-exec` is missing/deprecated (diagnostics, suggested alternatives).
- [ ] Optional translation layer to container/VM policies for dynamic per‑run path scoping (documented outside SBPL core).

## MCP Security Integration
See `docs/seatbelt/MCP_SECURITY_INTEGRATION.md` for detailed documentation on seatbelt-MCP integration.

### Cross-Layer Security
- [ ] MCP approval policy should be aware of seatbelt policies; allow policy customization based on policy specificity
  - Example: `approve seatbelt_exec only if policy.files is non-empty`
  - Location: `src/adgn/agent/policies/default_policy.py`
  - Reference: `src/adgn/mcp/exec/seatbelt.py` (SandboxExecArgs.policy field)

- [ ] Unified audit log combining seatbelt kernel denials + MCP approval decisions
  - Location: `src/adgn/agent/persist/` (extend ApprovalOutcome/ToolCallExecution models)
  - Reference: `src/adgn/seatbelt/runner.py` (unified_sandbox_denies collection)

- [ ] Policy validation hook: expose seatbelt policy linting via MCP tool
  - Example: `seatbelt_validate_policy` tool that returns SBPL validation findings
  - Location: `src/adgn/mcp/exec/seatbelt.py`

### Policy Templates & Resources
- [ ] Seatbelt policy templates as MCP resources with versioning
  - Example: `resources://seatbelt/templates/jupyter-kernel` → compiled SBPL
  - Location: `src/adgn/mcp/resources/server.py` (add seatbelt template resources)

- [ ] Pre-built policy presets for common MCP use cases (Jupyter, read-only FS, loopback-only net)
  - Location: `src/adgn/seatbelt/presets.py` (new module)

### Dynamic Policies
- [ ] Policy modification via approval policy middleware
  - Allow approval policy to inject additional restrictions into seatbelt policies at runtime
  - Example: Policy says "yes, but restrict to /tmp" → modify policy before sandbox-exec
  - Location: `src/adgn/mcp/policy_gateway/middleware.py` + `src/adgn/mcp/exec/seatbelt.py`

- [ ] Default/fallback seatbelt policies for tools that don't provide one
  - Example: UI tool calling `seatbelt_exec` without explicit policy → use safe read-only default
  - Location: `src/adgn/mcp/exec/seatbelt.py` (SandboxExecArgs validation)

### User Experience & Observability
- [ ] Policy proposal UI for seatbelt policies (similar to approval policy proposals)
  - Allow users to draft, test, and propose new seatbelt policies
  - Location: UI + `src/adgn/agent/approvals.py`

- [ ] Enhanced trace output: explain seatbelt denials in terms of policy rules
  - Example: "Access to /etc/passwd denied by rule: (deny file-read* (literal \"/etc\"))"
  - Location: `src/adgn/seatbelt/runner.py` (trace parsing and rendering)

- [ ] Compatibility warning when approval policy + seatbelt policy conflict
  - Example: Approval says "yes" but seatbelt says "no" → warn in logs
  - Location: `src/adgn/agent/approvals.py` + policy evaluator

---

Notes
- Current implemented subset: `file-read*`, `file-write*`, `file-read-metadata`, `file-map-executable`, `process*`, `signal (target self)`, `network-(inbound|outbound|bind)` with `(local ip)`, `mach-lookup` by global name, `system-socket`, `sysctl-read`, `trace`.
- Keep core layering: models and compiler remain pure; validations/presets/runners are opt‑in and explicit.
- Seatbelt and MCP approval policy form a defense-in-depth security model: MCP gates access semantically, seatbelt enforces OS-level isolation. See `MCP_SECURITY_INTEGRATION.md` for the full architecture.

