# environment-manager RE Plan (64bc4dc1)

Reconstruction plan for `environment-manager` binary
(Build ID `64bc4dc1a5a3a38ce5732655f7fdfbeb62b8598d`).

## Binary Summary

| Property             | Value                                                              |
| -------------------- | ------------------------------------------------------------------ |
| Build ID             | `64bc4dc1a5a3a38ce5732655f7fdfbeb62b8598d`                         |
| Version              | `release-9f4ec76fbc-ext`                                           |
| Channel              | `release` (production, was `staging` in a6f96673)                  |
| Go version           | Unknown (garble strips module info — `go version -m` returns "unknown") |
| Binary size          | 49 MB (was 27 MB — garble inlines and pads code)                   |
| Anthropic functions  | N/A (symbol table garbled — `go tool nm` returns no output)        |
| Source files (DWARF) | N/A (no DWARF debug info — garble strips it)                       |
| Obfuscation          | garble (Go obfuscator) — all symbol names garbled                  |

## Obfuscation Evidence

The new binary is fully obfuscated using garble:

- `go version -m /tmp/env-manager-new` returns "unknown" — garble strips module info
- `go tool nm /tmp/env-manager-new` returns no output — symbol table is garbled
- Obfuscated names visible in strings: `qbbw3lR`, `pVHE5Urql8v`, `gDCX1skL`, etc.
- Binary size doubled: 27 MB → 49 MB (garble inlines and pads code)
- Version string `release-9f4ec76fbc-ext` visible as a literal constant (not obfuscated)
- JSON field names and error strings are still visible (runtime string literals)

## What Can Still Be Extracted

1. **CLI --help output** — Cobra CLI strings are runtime literals, not obfuscated
2. **print-sandbox-settings** — JSON output with runtime literal strings
3. **String analysis** — `strings` on binary reveals JSON field names, error messages,
   OTEL attribute names, metric paths
4. **Runtime behavior** — Execute the binary to observe behavior

## Verified CLI Behavior (from runtime analysis)

All CLI flags and subcommands verified unchanged from a6f96673 via `--help` output:
- `orchestrator`, `setup`, `task-run`, `poll`, `print-sandbox-settings`, `completion`
- All flags identical to a6f96673 (same names, defaults, descriptions)

## Verified Sandbox Settings (from print-sandbox-settings)

```json
{
  "network": {
    "allowedDomains": ["api.anthropic.com", "api-staging.anthropic.com", "*.anthropic.com"],
    "deniedDomains": []
  },
  "filesystem": {
    "denyRead": ["~/.ssh", "~/.aws", "~/.config/gcloud", "/etc/shadow", "/etc/passwd-", "/secrets"],
    "allowWrite": ["/tmp", "/tmp/claude", "~", "/workspace"],
    "denyWrite": [],
    "allowGitConfig": true
  },
  "enableWeakerNestedSandbox": false
}
```

`enableWeakerNestedSandbox` is `false` (unchanged from a6f96673).

## New OTEL/Telemetry Strings (added in 64bc4dc1)

Found in string analysis of new vs old binary:

- `gcp.apphub.service.criticality_type`
- `gcp.apphub.service.environment_type`
- `gcp.apphub.workload.criticality_type`
- `gcp.apphub.workload.environment_type`
- `feature_flag.evaluation.reason`
- `feature_flag.result.reason`
- `grpc.internal.transport.networktype`
- `grpc.internal.address.metadata`
- `rpc.connect_rpc.error_code`
- New runtime metrics: `/cpu/classes/`, `/gc/cycles/`, `/sched/pauses/`, `/memory/classes/` paths

These likely come from updated gRPC and OTel dependency versions, not application-level changes.

## Dependency/Source Analysis Status

**BLOCKED** — garble obfuscation makes DWARF-based dependency analysis impossible.

From the a6f96673 source (go.mod), the dependency versions are known. The new
binary may have updated versions but they cannot be extracted from the binary.
The go.mod in `src/` reflects a6f96673 versions and is left unchanged as the
best available approximation.

## Phase 1: Census & Diff

- [x] Confirmed obfuscation via `go version -m`, `go tool nm`
- [x] Binary size: 49 MB confirmed
- [x] Version string: `release-9f4ec76fbc-ext` confirmed
- [x] CLI flags verified via `--help` (all subcommands)
- [x] Sandbox settings verified via `print-sandbox-settings`
- [x] String diff against a6f96673 for new OTEL attributes
- [ ] Full string diff for new application-level changes (blocked by obfuscation volume)

## Phase 2: Source Updates

- [x] Updated BUILD.bazel files (replaced a6f96673 paths with 64bc4dc1)
- [x] Updated Go source file headers (Build ID comment)
- [x] Updated main.go version string and obfuscation notice
- [x] Updated PLAN.md and REVERSE_ENGINEERING_TODOS.md
- [ ] DWARF-based reconstruction (IMPOSSIBLE — binary is garble-obfuscated)

## Key Finding: DWARF-Based RE Is Now Impossible

The old binary (a6f96673) had full DWARF debug info and a readable symbol table,
making reconstruction tractable via `go tool nm`, `go tool objdump`, and DWARF
inspection. The new binary (64bc4dc1) has neither — garble strips all of this.

Future RE for this binary must rely solely on:
1. Runtime behavior (execute and observe)
2. String analysis (`strings` on binary)
3. CLI help output
4. Comparison with known-good a6f96673 source

## Open Items

1. **Dependency versions**: Cannot extract from garbled binary; go.mod reflects a6f96673
2. **New application features**: Cannot determine without DWARF; may be present
3. **Internal behavior changes**: Cannot verify without symbol table
