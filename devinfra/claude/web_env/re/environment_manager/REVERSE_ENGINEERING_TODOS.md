# Environment Manager Reverse Engineering - Remaining Work

Binary: Build ID `495ea204`, version `release-d84d76b7-ext`

**Status:** Binary diff (2026-03-26) revealed major code changes from a6f96673.
The source in `src/` contains dead code from removed features. All previously
missing source files have been created.

## Critical Constraint: Binary Is Garble-Obfuscated

The 495ea204 binary is obfuscated using garble (Go obfuscator):

- `go version -m` returns "unknown" -- module info stripped
- `go tool nm` returns no output -- symbol table garbled
- No DWARF debug info present
- Binary size doubled (27 MB -> 49 MB) from inlining and padding
- All function/type names replaced with random identifiers
- `CLAUDE_CODE_*` env var constants are obfuscated in the string table

**DWARF-based reconstruction (as done for a6f96673) is impossible.**

## Binary Diff Findings (2026-03-26)

See `BINDIFF_RESULTS.md` for full analysis. Key findings:

### Removed from 495ea204 (vs a6f96673)

1. **Supabase MCP server** -- entire package excised (0 of 199 strings remain)
2. **Vercel deploy backend** -- removed (0 of 32 strings remain)
3. **Antspace deploy backend** -- removed (0 of 42 strings remain)
4. **Baku project features** -- initialization, templates, settings (1 of 34 strings remain)

### Added in 495ea204

- `filestore_url`, `filesystem_id` JSON fields (new deploy mechanism)
- `jwt` JSON field (auth-related)

### Unchanged

- V0/V1 session context struct layouts
- API endpoint paths (minus Supabase provision)
- CLI flags and sandbox settings
- Heartbeat/lease response structure

## Priority 1: Remove Dead Code from `src/` (HIGH)

The binary diff proves these source files represent code no longer in the binary.
They must be removed to avoid misleading future RE work.

### Files to delete

- `internal/mcp/servers/supabase/client.go`
- `internal/mcp/servers/supabase/registration.go`
- `internal/mcp/servers/supabase/server.go`
- `internal/tunnel/actions/deploy/vercel.go`
- `internal/tunnel/actions/deploy/antspace.go`

### Code to remove from existing files

- `internal/auth/context.go`: Remove `supabaseAnonKey`, `supabaseDBPass`,
  `supabasePAT`, `supabaseProjectRef` fields and `HasSupabase()`,
  `GetSupabaseAnonKey()`, `GetSupabasePAT()`, `GetSupabaseDBPass()`,
  `GetSupabaseProjectRef()` methods. Remove `vercelDeployToken`,
  `antspaceAuthToken`, `antspaceControlPlaneURL` fields and their getters.
- `internal/manager/mcp.go`: Remove Supabase MCP server registration.
- `internal/envtype/anthropic/anthropic.go`: Remove `findExistingBakuProject()`,
  `initializeBakuProject()`, `bootstrapBakuSettings()` functions and Baku
  template paths (`/opt/baku-templates/vite-template`,
  `/home/claude/project/.baku/explorations`, `/home/claude/project/.baku/drafts`).
- `internal/envtype/anthropic/skill_content.go`: Remove Baku-specific embedded
  content (stop-hook-baku.sh, baku settings JSON).

## Priority 2: Add Discovered JSON Fields to RE Source (MEDIUM)

The verification report identified 17+ JSON fields present in the binary but
missing from the RE source structs. These should be added to the corresponding
Go struct definitions. See `VERIFICATION_REPORT.md` "New Fields Discovered"
section for the full list.

Key structs to update:

- Startup context / V1 input struct (`use_code_sessions`, `use_sandbox_gateway_config`, etc.)
- Gateway / StartupContext extended struct (`custom_system_prompt`, `append_system_prompt`, `model`, `allowed_tools`, etc.)
- Lease info struct (`lease_extended`, `state`, `last_heartbeat`, etc.)

Note: `internal/envtype/shared/` package contains embedded content (settings JSON,
stop hook scripts) that is currently in `skill_content.go`. In the actual source
this is a separate `shared` package used by both `anthropic` and `byoc` env types.

## Priority 3: Update Deploy Action for Filestore (LOW)

`internal/tunnel/actions/deploy/action.go` now uses `filestore_url` and
`filesystem_id` instead of Vercel/Antspace. The actual logic is fully garbled
and cannot be recovered without runtime observation of a live deployment.

## Priority 4: Investigate `jwt` Auth Field (LOW)

The new `json:"jwt"` field in the binary is not part of the V0/V1 session context
structs. It may be part of a new auth mechanism or internal API response. Location
in the code is unknown.

## Known Gaps in the Source

The source contains 27 `TODO(re)` markers across 8 files (inherited from the
a6f96673 reconstruction). With the binary diff findings, additional gaps are now
documented:

- **Dead Baku code**: Functions and embedded content that should be removed
- **Missing JSON fields**: 17+ fields discovered in verification not yet in RE source
- **New deploy mechanism**: `filestore_url`/`filesystem_id` logic is unknown
- **Obfuscated env vars**: `CLAUDE_CODE_*` constants are garbled in new binary
- **Stale binary addresses**: All `0x...` addresses in comments are from a6f96673

## What Was Verified (2026-03-26)

- CLI flags: all subcommands identical flags and defaults
- Sandbox settings: `enableWeakerNestedSandbox: false`, same domain lists
- Version string: `release-d84d76b7-ext`
- V0/V1 struct layouts: field-by-field match via garbled type recovery
- Removed features: confirmed via string count comparison (HIGH confidence)
- New fields: `filestore_url`, `filesystem_id`, `jwt` (HIGH confidence)
