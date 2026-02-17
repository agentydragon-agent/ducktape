# Issues Missing graders_match_only_if_reported_on

Total: 298 single-file occurrences

## crush/2025-08-30-internal_db (46)

### `lsp-stdin-race.yaml` / `occ-0` [P10]

File: `internal/lsp/transport.go`

> LSP client performs unsynchronized concurrent writes to the server's stdin, risking interleaved headers/bodies
> and JSON‑RPC/LSP stream corruption.
>
> Evidence
>
> - WriteMessage writes header (fmt.Fprintf) then body (w.Write) with no locking.
> - Multiple goroutines call WriteMessage concurrently:
>   - replying to server requests (WriteMessage(c.stdin, response))
>   - sending requests (WriteMessage(c.stdin, msg))
>   - sending notifications (WriteMessage(c.stdin, msg))
>
> Why it matters
>
> - Concurrent fmt.Fprintf + Write to the same pipe can interleave bytes across messages (e.g.,
>   header from A + body from B).
> - Results in parse errors, dropped/ misrouted responses, and hard‑to‑debug protocol failures.
>
> Context
>
> - In typical Crush usage a single agent instance may drive LSP interactions mostly sequentially,
>   so the bug can be latent under light load. However, server‑initiated requests and concurrent notifications
>   still
>   overlap with client calls, and the code provides no serialization. Treat this as bad practice to be fixed
>   regardless of current incidence.
>
> Acceptance criteria
>
> - Serialize all writes to c.stdin (e.g., add a write mutex on the client and guard all WriteMessage calls).
> - Optional: buffer compose the full frame into a single []byte and write once under the mutex.
> - Add a stress test that concurrently Call/Notify + server replies and validates stream integrity.

### `sentinel-flag-pattern.yaml` / `occ-0` [P10]

File: `internal/shell/shell.go`

> ArgumentsBlocker in internal/shell/shell.go uses a sentinel flag inside an inner loop to decide post-loop
> behavior. Prefer a labeled continue to skip to the next outer iteration and keep the happy-path less indented.

### `renderer-guard-clauses.yaml` / `occ-0` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err != nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer already uses the guard-clause style.
>
> **Note:** editRenderer.Render: use guard clause for json unmarshal of params, proceed on happy path.

### `renderer-guard-clauses.yaml` / `occ-1` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err != nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer already uses the guard-clause style.
>
> **Note:** multiEditRenderer.Render: use guard clause for params unmarshal.

### `renderer-guard-clauses.yaml` / `occ-2` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err !=
> nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer
> already
> uses the guard-clause style.
>
> **Note:** writeRenderer.Render: prefer guard-clause style when unmarshalling params.

### `renderer-guard-clauses.yaml` / `occ-3` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err != nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer already uses the guard-clause style.
>
> **Note:** fetchRenderer.Render: use early bailout on unmarshal error then happy-path.

### `renderer-guard-clauses.yaml` / `occ-4` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err !=
> nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer
> already
> uses the guard-clause style.
>
> **Note:** downloadRenderer.Render: prefer guard-clause for metadata/params parsing.

### `renderer-guard-clauses.yaml` / `occ-5` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err != nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer already uses the guard-clause style.
>
> **Note:** globRenderer.Render: use guard-clause pattern.

### `renderer-guard-clauses.yaml` / `occ-6` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err !=
> nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer
> already
> uses the guard-clause style.
>
> **Note:** grepRenderer.Render: prefer early-return on unmarshal error then continue.

### `renderer-guard-clauses.yaml` / `occ-7` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err != nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer
> already
> uses the guard-clause style.
>
> **Note:** lsRenderer.Render: use guard clause for unmarshalling params.

### `renderer-guard-clauses.yaml` / `occ-8` [P15]

File: `internal/tui/components/chat/messages/renderer.go`

> Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ...
}` and
> then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...);
> err != nil
> { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash
> renderer already uses the guard-clause style.
>
> **Note:** sourcegraphRenderer.Render: prefer guard-clause for params/metadata parsing.

### `config-nil-chains.yaml` / `occ-0` [P20]

File: `internal/diff/external.go`

> Call-sites frequently chain nil checks (cfg != nil && cfg.Options != nil && cfg.Options.X != nil ...) which is
> noisy and error-prone. Centralize nil-safe accessors on Config (nil-receiver-safe methods) or pass
> \*config.Config by DI to eliminate repetitive pointer chains and consolidate defaults.
>
> **Note:** Example: Diff.ExternalCommand / ParseMode guarded by multi-level nil checks; centralize via
> config.Diff().ParseMode or a nil-safe helper.

### `config-nil-chains.yaml` / `occ-1` [P20]

File: `internal/lsp/watcher/watcher.go`

> Call-sites frequently chain nil checks (cfg != nil && cfg.Options != nil && cfg.Options.X != nil ...) which is
> noisy and error-prone. Centralize nil-safe accessors on Config (nil-receiver-safe methods) or pass
> \*config.Config by DI to eliminate repetitive pointer chains and consolidate defaults.
>
> **Note:** Numerous checks for cfg.Options.DebugLSP and config-derived guards; prefer
> config.DebugLSP()/config.CurrentLSPIgnore() helpers or DI.

### `config-nil-chains.yaml` / `occ-2` [P20]

File: `internal/llm/tools/tools.go`

> Call-sites frequently chain nil checks (cfg != nil && cfg.Options != nil && cfg.Options.X != nil ...) which is
> noisy and error-prone. Centralize nil-safe accessors on Config (nil-receiver-safe methods) or pass
> \*config.Config by DI to eliminate repetitive pointer chains and consolidate defaults.
>
> **Note:** Representative site for reading GrepTimeoutSecs, BashBlockedCommands, MaxToolOutputBytes — prefer
> config.GrepTimeoutSecs(), config.BashBlockedCommands() helpers or DI.

### `control-flow-complexity.yaml` / `occ-0` [P20]

File: `internal/tui/components/chat/chat.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** Combine nested type+value checks into single if (e.g., asMsg,ok := item.(MessageCmp); ok &&
> asMsg.GetMessage().ID == messageID) and guard for tc.Spinning with a single condition.

### `control-flow-complexity.yaml` / `occ-1` [P20]

File: `internal/message/content.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** Flatten nested type/id/finished guards across Content/Reasoning/Finish helper methods to reduce repetition and
> nesting.

### `control-flow-complexity.yaml` / `occ-2` [P20]

File: `internal/app/app.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** Flatten trivial guards when deriving MCP topic; prefer small guard or local helper to reduce nesting in the
> hot loop.

### `control-flow-complexity.yaml` / `occ-3` [P20]

File: `internal/lsp/client.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** WaitForServerReady: remove unnecessary else after an early return and use guard clauses.

### `control-flow-complexity.yaml` / `occ-4` [P20]

File: `e2e/scenario.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** Combine E2E_PER_STEP_SECS env read and value check into a single expression (read+parse+validate) to reduce
> nested conditionals.

### `control-flow-complexity.yaml` / `occ-5` [P20]

File: `internal/pubsub/broker.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** Use short if with initializer: if s := f.String(); s != "" { ... } instead of separate lines.

### `control-flow-complexity.yaml` / `occ-6` [P20]

File: `internal/history/file.go`

> Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial
> nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see
> Early bailout).
>
> **Note:** createWithVersion: flatten UNIQUE-constraint retry guard; use clearer retry loop and guard-clauses to avoid
> deep nesting.

### `hardcoded-timeouts.yaml` / `occ-0` [P20]

File: `internal/lsp/client.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** LSP client: Close() uses 5*time.Second; WaitForServerReady uses 30*time.Second and ticker
> 500\*time.Millisecond; maxFilesToOpen constant-like value 5. Define named consts like LSPStopTimeout,
> LSPWaitReadyTimeout, LSPReadyPollInterval, MaxFilesToOpen.

### `hardcoded-timeouts.yaml` / `occ-1` [P20]

File: `internal/diff/external.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** External diff runner uses context.WithTimeout(..., 2*time.Second). Define ExternalDiffTimeout = 2 *
> time.Second or make configurable via config.Diff.ExternalCommand timeout.

### `hardcoded-timeouts.yaml` / `occ-2` [P20]

File: `internal/lsp/diagnostics_wait.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** Diagnostics wait loop uses 5s deadline and 100ms poll interval; name these constants (DiagnosticsWaitTimeout /
> DiagnosticsPollInterval).

### `hardcoded-timeouts.yaml` / `occ-3` [P20]

File: `internal/app/lsp.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** App LSP init uses 30s init timeout; shutdown uses 5s shutdown timeout; name them LSPInitTimeout,
> LSPShutdownTimeout.

### `hardcoded-timeouts.yaml` / `occ-4` [P20]

File: `internal/app/app.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** App-wide timers: middleware debounce 30ms; select/drop timeout 2s; slow-op threshold (100ms) and shutdown
> timeout (5s) should be named constants or config options.

### `hardcoded-timeouts.yaml` / `occ-5` [P20]

File: `internal/lsp/watcher/watcher.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** Watcher defaults: debounceTime 300ms, default recursive max watched dirs 5000, default watch mode "recursive"
> — name these watcher defaults.

### `hardcoded-timeouts.yaml` / `occ-6` [P20]

File: `internal/llm/agent/sequence_transformer.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** Sequence transformer timing: overall deadline 1500ms; small sleep 50ms; per-call timeout 2500ms — name and
> centralize as AgentSequenceTimeouts.

### `hardcoded-timeouts.yaml` / `occ-7` [P20]

File: `internal/llm/agent/agent.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** Agent: 50ms delayed flush, 5s overall timeout, 200ms retry sleep — name these and consider DI/config.

### `hardcoded-timeouts.yaml` / `occ-8` [P20]

File: `internal/llm/tools/sourcegraph.go`

> Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner,
> app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or
> configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making
> them configuration options (with safe defaults). Preserve local comments about semantics when migrating to
> named constants.
>
> **Note:** Sourcegraph HTTP client timeouts: Timeout 30s, IdleConnTimeout 90s — name them and centralize.

### `path-schema-docs-mismatch.yaml` / `occ-0` [P20]

File: `internal/llm/tools/ls.go`

> Path schema/docs are inconsistent with runtime behavior in internal/llm/tools; the spec (schema/docs) and
> implementation
> disagree. Resolve by aligning the declared contract with code or updating the code to meet the declared
> contract.
>
> **Note:** ToolInfo.Required lists "path" as required (line 109), but Run allows empty path and defaults to workingDir
> (lines 119-123).

### `path-schema-docs-mismatch.yaml` / `occ-1` [P20]

File: `internal/llm/tools/edit.go`

> Path schema/docs are inconsistent with runtime behavior in internal/llm/tools; the spec (schema/docs) and
> implementation
> disagree. Resolve by aligning the declared contract with code or updating the code to meet the declared
> contract.
>
> **Note:** Description says absolute path only, but Run joins relative paths with workingDir.

### `timestamp-type-inconsistency.yaml` / `occ-0` [P20]

File: `internal/llm/tools/download.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** download.go: `Timeout`/`maxTimeout` should be time.Duration or suffixed (timeoutMS)

### `timestamp-type-inconsistency.yaml` / `occ-1` [P20]

File: `internal/llm/tools/fetch.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** fetch.go: `Timeout int` should be time.Duration

### `timestamp-type-inconsistency.yaml` / `occ-10` [P20]

File: `internal/transform/transform.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** transform.go: CreatedAt int64 should be time.Time

### `timestamp-type-inconsistency.yaml` / `occ-2` [P20]

File: `internal/llm/tools/tools.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** tools.go: `StartedAt`/`UpdatedAt int64` should be time.Time or suffixed (ms epoch)

### `timestamp-type-inconsistency.yaml` / `occ-3` [P20]

File: `internal/message/content.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** content.go: `{Started,Finished,Created,Updated}At`, `Finish.Time` should be time.Time

### `timestamp-type-inconsistency.yaml` / `occ-4` [P20]

File: `internal/message/message.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** message.go: Watermarks.\*TS and Message timestamps should be time.Time (UpdatedAt microseconds)

### `timestamp-type-inconsistency.yaml` / `occ-5` [P20]

File: `internal/history/file.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** file.go: CreatedAt/UpdatedAt int64 should be time.Time

### `timestamp-type-inconsistency.yaml` / `occ-6` [P20]

File: `internal/tui/components/chat/chat.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** chat.go: lastUserMessageTime int64 should be time.Time (epoch seconds)

### `timestamp-type-inconsistency.yaml` / `occ-7` [P20]

File: `internal/tui/components/chat/messages/renderer.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** renderer.go: timeout int should be time.Duration (seconds)

### `timestamp-type-inconsistency.yaml` / `occ-8` [P20]

File: `internal/pubsub/broker.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** broker.go: now := time.Now().UnixMilli() should use time.Time directly

### `timestamp-type-inconsistency.yaml` / `occ-9` [P20]

File: `internal/session/session.go`

> Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int,
> suffix
> units in names).
>
> **Note:** session.go: CreatedAt/UpdatedAt int64 should be time.Time

### `facade-law-of-demeter.yaml` / `occ-0` [SKIP - cross-file]

File: `internal/tui/page/chat/chat.go`

> App currently serves as both composition root and partial façade. TUI code reaches through app to call inner
> services (CoderAgent, Sessions, Permissions) directly, producing duplicated guards and unclear ownership. Pick
> one strategy: strengthen App as the agent façade (IsAgentBusy/RunAgent/CancelAgent/etc.) or treat App strictly
> as composition root and pass services by DI consistently.
>
> **Note:** chat page reaches through p.app.CoderAgent.\* and p.app.Sessions.Create(...) in many places; prefer unified
> agent façade or DI.

### `facade-law-of-demeter.yaml` / `occ-1` [SKIP - cross-file]

File: `internal/tui/tui.go`

> App currently serves as both composition root and partial façade. TUI code reaches through app to call inner
> services (CoderAgent, Sessions, Permissions) directly, producing duplicated guards and unclear ownership. Pick
> one strategy: strengthen App as the agent façade (IsAgentBusy/RunAgent/CancelAgent/etc.) or treat App strictly
> as composition root and pass services by DI consistently.
>
> **Note:** top-level TUI model uses a.app.CoderAgent.\* for busy checks and a.app.Permissions for toggles/grants;
> centralize agent/permission interactions behind App or DI.

### `facade-law-of-demeter.yaml` / `occ-2` [SKIP - cross-file]

File: `internal/tui/components/chat/editor/editor.go`

> App currently serves as both composition root and partial façade. TUI code reaches through app to call inner
> services (CoderAgent, Sessions, Permissions) directly, producing duplicated guards and unclear ownership. Pick
> one strategy: strengthen App as the agent façade (IsAgentBusy/RunAgent/CancelAgent/etc.) or treat App strictly
> as composition root and pass services by DI consistently.
>
> **Note:** editor reaches through to m.app.CoderAgent.IsSessionBusy/IsBusy and m.app.Permissions — consider routing via
> App façade methods or inject services explicitly.

## ducktape/2025-11-26-00 (34)

### `ask-approved-inflight.yaml` / `occ-0` [P20]

File: `adgn/src/adgn/mcp/policy_gateway/middleware.py`

> When user approves an ASK-case tool call (ContinueDecision at lines 252-258), middleware executes it but does
> NOT track
> it in `self._inflight`, making it invisible to `has_inflight_calls()` and `inflight_count()`.
>
> The ALLOW case (lines 167-225) correctly tracks in \_inflight during execution with try/finally cleanup.
>
> Problems: (1) `has_inflight_calls()` returns False even when ASK-approved call is executing, (2)
> `inflight_count()`
> doesn't count ASK-approved calls, (3) can't distinguish "waiting for approval" vs "approved and executing",
> (4)
> inconsistent tracking between ALLOW and ASK paths.
>
> Match the ALLOW pattern: add call to \_inflight before execution, clean up in finally block. Both paths should
> track
> consistently regardless of whether policy allowed or user approved.

```
     247:         if self._notify is not None:
     248:             await self._notify(call_id, tool_key, req.tool_call.args_json)
     249:
     250:         decision_obj = await wait_coro
     251:
>>>  252:         if isinstance(decision_obj, ContinueDecision):
>>>  253:             if self._record is not None:
>>>  254:                 await self._record(call_id, tool_key, ApprovalOutcome.POLICY_ALLOW)
>>>  255:             try:
>>>  256:                 return await call_next(context)
>>>  257:             except McpError as e:
>>>  258:                 _raise_if_reserved_code(e, name)
     259:                 raise
     260:         if isinstance(decision_obj, AbortTurnDecision):
     261:             if self._record is not None:
     262:                 await self._record(call_id, tool_key, ApprovalOutcome.POLICY_DENY_ABORT)
     263:             raise _policy_denied_error(ApprovalDecision.DENY_ABORT, name, decision_obj.reason)
   ...
     162:         if decision is ApprovalDecision.ALLOW:
     163:             if self._record is not None:
     164:                 await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_ALLOW)
     165:
     166:             # Track in-flight tool call
>>>  167:             call_id = uuid.uuid4().hex
>>>  168:             self._inflight[call_id] = tool_key
>>>  169:             try:
>>>  170:                 call_result = await call_next(context)
>>>  171:                 # If downstream returned an error ToolResult instead of raising,
>>>  172:                 # remap reserved policy codes/messages here using typed parsing when available.
>>>  173:                 if bool(getattr(call_result, "is_error", False)):
>>>  174:                     # Parse error details - ErrorData guarantees code: int per MCP/JSON-RPC spec
>>>  175:                     err = getattr(call_result, "error", None)
>>>  176:                     if err is None:
>>>  177:                         return call_result
>>>  178:
>>>  179:                     # Try parsing as ErrorData (validates code is int, message is str)
>>>  180:                     try:
>>>  181:                         ed = mtypes.ErrorData.model_validate(err)
>>>  182:                     except Exception:
>>>  183:                         # Non-conforming error format - pass through
>>>  184:                         return call_result
>>>  185:
>>>  186:                     # Check if error uses reserved policy codes/messages
>>>  187:                     stamped_downstream = isinstance(ed.data, dict) and ed.data.get(POLICY_GATEWAY_STAMP_KEY) is True
>>>  188:                     if (
>>>  189:                         stamped_downstream
>>>  190:                         or ed.code
>>>  191:                         in (POLICY_DENIED_ABORT_CODE, POLICY_DENIED_CONTINUE_CODE, POLICY_EVALUATOR_ERROR_CODE)
>>>  192:                         or ed.message
>>>  193:                         in (POLICY_DENIED_ABORT_MSG, POLICY_DENIED_CONTINUE_MSG, POLICY_EVALUATOR_ERROR_MSG)
>>>  194:                     ):
>>>  195:                         raise McpError(
>>>  196:                             ErrorData(
>>>  197:                                 code=POLICY_BACKEND_RESERVED_MISUSE_CODE,
>>>  198:                                 message=POLICY_BACKEND_RESERVED_MISUSE_MSG,
>>>  199:                                 data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "backend_code": ed.code},
>>>  200:                             )
>>>  201:                         )
>>>  202:                 return call_result
>>>  203:             except McpError as e:
>>>  204:                 _raise_if_reserved_code(e, name)
>>>  205:                 raise
>>>  206:             except Exception as e:
>>>  207:                 # Some servers may translate backend McpError into a ToolError before it reaches us.
>>>  208:                 # As a last resort, remap by inspecting the exception text.
>>>  209:                 s = str(e)
>>>  210:                 if (
>>>  211:                     (POLICY_DENIED_ABORT_MSG in s)
>>>  212:                     or (POLICY_DENIED_CONTINUE_MSG in s)
>>>  213:                     or (POLICY_EVALUATOR_ERROR_MSG in s)
>>>  214:                 ):
>>>  215:                     raise McpError(
>>>  216:                         ErrorData(
>>>  217:                             code=POLICY_BACKEND_RESERVED_MISUSE_CODE,
>>>  218:                             message=POLICY_BACKEND_RESERVED_MISUSE_MSG,
>>>  219:                             data={POLICY_GATEWAY_STAMP_KEY: True, "name": name, "backend_code": "unknown"},
>>>  220:                         )
>>>  221:                     )
>>>  222:                 raise
>>>  223:             finally:
>>>  224:                 # Remove from in-flight tracking when call completes (success or error)
>>>  225:                 self._inflight.pop(call_id, None)
     226:
     227:         if decision is ApprovalDecision.DENY_ABORT:
     228:             if self._record is not None:
     229:                 await self._record("pg:" + uuid.uuid4().hex, tool_key, ApprovalOutcome.POLICY_DENY_ABORT)
     230:             raise _policy_denied_error(ApprovalDecision.DENY_ABORT, name, rationale)
```

### `inline-treebuilder.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> Lines 136-137 create TreeBuilder, write it, and never use `tb` again. Inline:
>
> **Current:** `tb = repo.TreeBuilder() ; empty_tree_oid = tb.write()`
> **Fix:** `empty_tree_oid = repo.TreeBuilder().write()`

```
     131:         parent = head.parents[0]
     132:         parts.append("=== Original commit diff (HEAD^ to HEAD) ===")
     133:         parts.append(repo.diff(parent.id, head.id).patch or "")
     134:     else:
     135:         # First commit: diff from empty tree
>>>  136:         tb = repo.TreeBuilder()
>>>  137:         empty_tree_oid = tb.write()
     138:         parts.append("=== Original commit content ===")
     139:         parts.append(repo.diff(empty_tree_oid, head.id).patch or "")
     140:     # New changes
     141:     parts.append("\n=== New changes being added ===")
     142:     parts.append(_diff(repo, include_all).patch or "")
```

### `last-event-datetime-type.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/agents_ws.py`

> The `last_event_at` field in agents_ws.py is typed as `str | None` but should be `datetime | None`.
> The field is later converted to ISO string for JSON serialization (line 81), which is
> the correct place to do that conversion.
>
> **Current:**
>
> ```python
> last_event_at: str | None = None  # Line 73
> ...
> last_event_at=last.isoformat() if last else None,  # Line 81
> ```
>
> The field stores an ISO string, but semantically it represents a timestamp. Better to
> store as datetime and convert during serialization.
>
> **Better:**
>
> ```python
> last_event_at: datetime | None = None
> ...
> last_event_at=last.isoformat() if last else None,  // Conversion happens here
> ```
>
> **Benefits:**
>
> - Type accurately represents semantic meaning
> - Can do datetime operations on the field if needed
> - Conversion to string happens at serialization boundary

```
      68:     active_run_id: UUID | None = None
      69:     lifecycle: AgentLifecycle
      70:     run_phase: RunPhase
      71:     ui: UiStateLite
      72:     container: ContainerState
>>>   73:     last_event_at: str | None = None
      74:     model_config = ConfigDict(extra="forbid")
      75:
      76:     @classmethod
      77:     def from_core(cls, core: AgentStatusCore) -> AgentStatusData:
      78:         """Build a WS-friendly AgentStatusData from the internal status core.
   ...
      76:     @classmethod
      77:     def from_core(cls, core: AgentStatusCore) -> AgentStatusData:
      78:         """Build a WS-friendly AgentStatusData from the internal status core.
      79:
      80:         Centralizes the mapping and ensures JSON-friendly fields (e.g., last_event_at ISO string).
>>>   81:         Keeps the WS schema stable without exposing internal types directly.
      82:         """
      83:         last = core.last_event_at.isoformat() if core.last_event_at is not None else None
      84:         return cls(
      85:             id=core.id,
      86:             live=core.live,
```

### `list-conversion-unnecessary.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/resources/server.py`

> Lines 385-386 call `list(res.contents)` only to pass to `_build_window_payload()`. Creates unnecessary
> intermediate
> list
> and variable.
>
> Problems: (1) unnecessary `list()` conversion, (2) extra line for simple data transformation, (3)
> `_build_window_payload` signature (lines 191-194) too restrictive with `list` parameter type.
>
> Update `_build_window_payload` to accept `Sequence` instead of `list`, then inline at call site (pass
> `res.contents`
> directly). If function only needs iteration (not indexing), use `Iterable` instead of `Sequence`.

```
     380:           start_offset advanced by the bytes_returned of the previous window.
     381:         """
     382:         prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
     383:         uri_value = ANY_URL.validate_python(prefixed)
     384:         res = await compositor_client.read_resource_mcp(uri_value)
>>>  385:         contents = list(res.contents)
>>>  386:         return _build_window_payload(contents, input.start_offset, None if input.max_bytes == 0 else input.max_bytes)
     387:
     388:     @mcp.flat_model()
     389:     async def subscribe(input: ResourcesReadArgs) -> SimpleOk:
     390:         """Subscribe to updates for a resource."""
     391:         await _ensure_capability(input.server, feature=ResourceCapabilityFeature.SUBSCRIBE)
   ...
     186:             cursor += total_len
     187:         if remaining is not None and remaining <= 0:
     188:             break
     189:
     190:
>>>  191: def _build_window_payload(
>>>  192:     contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
>>>  193:     start_offset: int,
>>>  194:     max_bytes: int | None,
     195: ) -> ResourceReadResult:
     196:     parts_out: list[WindowedPart] = list(_iter_window_parts(contents, start_offset, max_bytes))
     197:     return ResourceReadResult(
     198:         window=ResourceWindowInfo(start_offset=start_offset, max_bytes=max_bytes or 0),
     199:         parts=parts_out,
```

### `mcpconfig-wrong-param.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/app.py`

> Line 189 uses `MCPConfig(servers={})` but the correct parameter name is `mcpServers`,
> not `servers`. This creates an extra unwanted field in the config object.
>
> **The problem:** Pydantic accepts `servers` due to field aliasing or extra fields config,
> but it's not canonical. Result: `{'mcpServers': {}, 'servers': {}}` (two fields instead
> of one).
>
> Verified: `MCPConfig().model_dump()` produces `{'mcpServers': {}}`, but
> `MCPConfig(servers={}).model_dump()` produces `{'mcpServers': {}, 'servers': {}}`.
>
> **Fix:** Use `MCPConfig()` (since default is empty dict) or `MCPConfig(mcpServers={})`
> for explicitness. Removes extra field and matches the actual schema.

```
     184:         # Create minimal infrastructure registry for agents server
     185:         # Note: This is a simplified setup - in production, you'd want proper registry management
     186:         app.state.mcp_registry = InfrastructureRegistry(
     187:             persistence=app.state.persistence,
     188:             docker_client=app.state.docker_client,
>>>  189:             mcp_config=MCPConfig(servers={}),
     190:             initial_policy=None,
     191:         )
     192:
     193:         # Create global compositor with two-level architecture
     194:         # TODO: Figure out gateway_client setup for resources server
```

### `model-str-common-trunk.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> Lines 86-90 parse model_str with branching logic, but both branches call `.strip()`
> on the result. The stripping is common trunk that should be factored out.
>
> **Current:**
>
> ```python
> if ":" in model_str:
>     _prefix, model_name = model_str.split(":", 1)
>     model_name = model_name.strip()
> else:
>     model_name = model_str.strip()
> ```
>
> **Simplified:**
>
> ```python
> if ":" in model_str:
>     _prefix, model_str = model_str.split(":", 1)
> model_name = model_str.strip()
> ```
>
> Splits model_str if it has ":", then always strips the result.

```
      80:                 with contextlib.suppress(ValueError):
      81:                     raw_timeout_secs = int(env_timeout)
      82:
      83:         timeout = None if raw_timeout_secs <= 0 else timedelta(seconds=raw_timeout_secs)
      84:
>>>   85:         # Backward-compat: allow optional "minicodex:" prefix; ignore any other
>>>   86:         if ":" in model_str:
>>>   87:             _prefix, model_name = model_str.split(":", 1)
>>>   88:             model_name = model_name.strip()
>>>   89:         else:
>>>   90:             model_name = model_str.strip()
      91:
      92:         return AppConfig(model_name=model_name, model_str=model_str, timeout=timeout)
      93:
      94:
      95: def _truncate_hunks(raw: str) -> str:
```

### `mutable-batch-accumulation.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/notifications/buffer.py`

> The class uses sets (`_updates`, `_list_changed`) during accumulation, then converts
> to frozen structures in NotificationsBatch. This is clunky.
>
> **Current pattern:**
>
> ```python
> # Accumulation storage (mutable sets)
> self._updates: dict[str, set[str]] = {}
> self._list_changed: set[str] = set()
>
> # On add:
> self._updates[server_name].add(uri)
> self._list_changed.add(server_name)
>
> # On poll/peek:
> resources = self._build_resources()  # Converts sets to frozen structures
> return NotificationsBatch(resources=resources)
> ```
>
> **Problem:** Clunky conversion between mutable sets and immutable structures.
>
> **Better approach:**
> Replace `dict[str, set[str]]` and `set[str]` with a single mutable `NotificationsBatch`
> instance (`self._batch`). On add operations, mutate `_batch` directly. On poll, return
> `self._batch.model_copy()` and reset `_batch = NotificationsBatch()`. On peek, return
> `self._batch.model_copy()`. This eliminates the conversion logic between sets and frozen
> structures.
>
> **Benefits:**
>
> 1. Simpler - one data structure instead of two representations
> 2. No conversion logic needed
> 3. More elegant and DRY
> 4. Clearer what's being accumulated

```
      35:     - Groups updates by server with deduplicated URIs using frozenset.
      36:     - Server names are derived via Compositor mount prefixes when possible; otherwise set to 'unknown'.
      37:     - Hooks can be registered to react to updates (e.g., push UI snapshots).
      38:     """
      39:
>>>   40:     def __init__(self, *, client: Client | None = None, compositor: Compositor) -> None:
>>>   41:         self._client = client
      42:         self._compositor = compositor
      43:         # Per-server updates (mutable sets during accumulation, converted to frozenset on poll/peek)
      44:         self._updates: dict[str, set[str]] = {}
      45:         self._list_changed: set[str] = set()
      46:         self._hooks: list[Callable[[], Awaitable[None]]] = []
```

### `poll-use-peek.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/notifications/buffer.py`

> Lines 62-72 define `poll()` and `peek()` which both call `_build_resources()` and
> create `NotificationsBatch` objects independently. This duplicates the batch creation
> logic.
>
> **The issue:** Both methods build resources and construct batch objects separately,
> obscuring that `poll()` is conceptually `peek()` plus clear operations.
>
> **Fix:** Make `poll()` call `peek()`, then clear buffers. This DRYs batch creation
> into one place and makes the relationship explicit: poll = peek + clear.
>
> If `_build_resources()` becomes single-use after this change, inline it into `peek()`.

```
      57:         self._hooks.append(hook)
      58:
      59:     def clear_hooks(self) -> None:
      60:         self._hooks.clear()
      61:
>>>   62:     def poll(self) -> NotificationsBatch:
>>>   63:         """Poll and clear buffered notifications, returning grouped batch."""
>>>   64:         resources = self._build_resources()
>>>   65:         self._updates.clear()
>>>   66:         self._list_changed.clear()
>>>   67:         return NotificationsBatch(resources=resources)
>>>   68:
>>>   69:     def peek(self) -> NotificationsBatch:
>>>   70:         """Peek at buffered notifications without clearing them."""
>>>   71:         resources = self._build_resources()
>>>   72:         return NotificationsBatch(resources=resources)
      73:
      74:     def _build_resources(self) -> dict[str, ResourcesServerNotice]:
      75:         """Build the grouped resources structure from current buffer state."""
      76:         resources: dict[str, ResourcesServerNotice] = {}
      77:         # Add servers with updated resources
```

### `proposal-status-enum-drift.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/app.py`

> Line 293 converts `rec.status` to `ProposalStatus` enum, suggesting the persistence
> layer and application layer use different types for the same concept.
>
> **The issue:** `PolicyProposal.status` (persist/**init**.py) is typed as `str`, not
> `ProposalStatus`. Line 293 must convert at the application boundary. This creates drift
> risk: invalid status strings in the database won't be caught by the type system, and
> runtime errors occur if the database contains unexpected values.
>
> **Fix:** Change `PolicyProposal.status` from `str` to `ProposalStatus` enum. Pydantic
> validates on construction. No conversion needed at line 293 - persistence layer enforces
> the enum, application layer receives typed values.
>
> Benefits: single source of truth, type safety throughout stack, no runtime conversion
> errors.

```
     288:     @app.get("/api/agents/{agent_id}/proposals", response_model=ProposalsList)
     289:     async def api_list_proposals(agent_id: AgentID) -> ProposalsList:
     290:         rows = await app.state.persistence.list_policy_proposals(agent_id)
     291:         items = [
     292:             ProposalRow(
>>>  293:                 id=rec.id, status=ProposalStatus(rec.status), created_at=rec.created_at, decided_at=rec.decided_at
     294:             )
     295:             for rec in rows
     296:         ]
     297:         return ProposalsList(proposals=items)
     298:
```

### `pygit2-auto-discover.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> Lines 700-704 manually discover the git directory using `pygit2.discover_repository()`,
> then check if it's None, then create the Repository. Per pygit2 documentation
> (https://www.pygit2.org/repository.html#pygit2.Repository) and test suite, `Repository()`
> auto-discovers the .git directory by default (only disabled with RepositoryOpenFlag.NO_SEARCH
> flag).
>
> **Current:**
>
> ```python
> gitdir = pygit2.discover_repository(Path.cwd())
> if not gitdir:
>     print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
>     raise ExitWithCode(128)
> repo = pygit2.Repository(gitdir)
> ```
>
> **Correct approach:**
>
> ```python
> try:
>     repo = pygit2.Repository(Path.cwd())
> except pygit2.GitError:
>     print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
>     raise ExitWithCode(128)
> ```
>
> **Benefits:**
>
> 1. Eliminates `gitdir` variable
> 2. Simpler - one call instead of two
> 3. More idiomatic - uses library's built-in discovery
> 4. Repository automatically searches parent directories for .git
>
> **Evidence:** pygit2 test suite
> (https://github.com/libgit2/pygit2/blob/a85f6fb274b237cb76d686b57f6865a90a3b3ef8/test/test_repository.py#L946-L952)
> shows `Repository(subdir_path)` successfully discovers parent .git directories by default.
> Auto-discovery is only disabled when RepositoryOpenFlag.NO_SEARCH is explicitly passed.

```
     695:     return "vi"
     696:
     697:
     698: async def async_main(argv: list[str] | None = None):
     699:     start_monotonic_s = time.monotonic()
>>>  700:     gitdir = pygit2.discover_repository(Path.cwd())
>>>  701:     if not gitdir:
>>>  702:         print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
>>>  703:         raise ExitWithCode(128)
>>>  704:     repo = pygit2.Repository(gitdir)
     705:
     706:     args, passthru = _parse_args_and_passthru(argv)
     707:
     708:     # Validate that -m/--message was not passed (we supply the commit message)
     709:     if args.message is not None:
```

### `refactor-cap-append.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/core.py`

> Lines 18-29 define `_cap_append()` which mutates parts list and handles truncation. Forces callers (lines
> 133-149) to
> think about truncation at each append.
>
> Problems: (1) caller must know when to use `_cap_append()` vs `parts.append()`, (2) truncation interleaved
> with data
> collection, (3) same cap/note constants repeated 4 times at call sites, (4) function mutates list and returns
> boolean,
> (5) magic constants duplicated instead of centralized.
>
> Replace with `join_with_truncation(parts, max_chars, note)` that takes complete list and truncates once at
> end.
> Callers
> build full list using plain `append()`, then call `join_with_truncation()` once. Define constants at module
> level, not
> repeated at call sites. Benefits: separation of concerns, pure function, constants defined once, easy to
> change
> behavior
> in one place.

```
      13:
      14: def _len_chars(s: str) -> int:
      15:     return len(s)
      16:
      17:
>>>   18: def _cap_append(parts: list[str], chunk: str, cap_chars: int, truncation_note: str) -> bool:
>>>   19:     """Append chunk to parts unless this would exceed cap; returns True if truncated."""
>>>   20:     current_chars = sum(_len_chars(p) for p in parts)
>>>   21:     needed_chars = _len_chars(chunk)
>>>   22:     if current_chars + needed_chars >= cap_chars:
>>>   23:         remaining_chars = cap_chars - current_chars
>>>   24:         if remaining_chars > 0:
>>>   25:             parts.append(chunk[:remaining_chars])
>>>   26:         parts.append(truncation_note + "\n")
>>>   27:         return True
>>>   28:     parts.append(chunk)
>>>   29:     return False
      30:
      31:
      32: def _diff(repo: pygit2.Repository, include_all: bool) -> pygit2.Diff:
      33:     return repo.diff(repo.head.target, None, cached=not include_all)
      34:
   ...
     128:
     129:
     130: def _build_ai_context(repo: pygit2.Repository, include_all: bool) -> str:
     131:     parts: list[str] = []
     132:
>>>  133:     parts.append("$ git status --porcelain\n")
>>>  134:     status_out = _format_status_porcelain(repo) + "\n"
>>>  135:     _cap_append(parts, status_out, MAX_PROMPT_CONTEXT_CHARS, "[Context truncated to 100k characters]")
>>>  136:
>>>  137:     ns_header = "git diff HEAD --name-status" if include_all else "git diff --cached --name-status"
>>>  138:     parts.append(f"$ {ns_header}\n")
>>>  139:     ns_out = _format_name_status(repo, include_all) + "\n"
>>>  140:     _cap_append(parts, ns_out, MAX_PROMPT_CONTEXT_CHARS, "[Context truncated to 100k characters]")
>>>  141:
>>>  142:     parts.append(f"$ git log --no-color -n {RECENT_COMMITS_FOR_CONTEXT} --stat --pretty=format:%h %B\n")
>>>  143:     log_out = "\n".join(_log_subjects(repo, RECENT_COMMITS_FOR_CONTEXT)) + "\n"
>>>  144:     _cap_append(parts, log_out, MAX_PROMPT_CONTEXT_CHARS, "[Context truncated to 100k characters]")
>>>  145:
>>>  146:     diff_header = "git diff HEAD --unified=0" if include_all else "git diff --cached --unified=0"
>>>  147:     parts.append(f"$ {diff_header}\n")
>>>  148:     diff_out = _format_unified_diff(repo, include_all) + "\n"
>>>  149:     _cap_append(parts, diff_out, MAX_PROMPT_CONTEXT_CHARS, "[Context truncated to 100k characters]")
     150:
     151:     out = "".join(parts)
     152:     if _len_chars(out) > MAX_PROMPT_CONTEXT_CHARS:
     153:         out = out[:MAX_PROMPT_CONTEXT_CHARS]
     154:         out += "\n[Context truncated to 100k characters]\n"
```

### `remove-boolean-param-amend.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> Lines 539-547 define `_get_previous_message_if_amend()` which takes `is_amend: bool` and returns None if
> False.
> Function
> wraps an if-statement (antipattern).
>
> Remove boolean parameter. Rename to `_get_previous_commit_message()` with non-nullable `str` return type. Move
> condition
> to call site (line 731): `previous_message = _get_previous_commit_message(repo) if is_amend else None`. Or
> inline
> entirely since it's called only once.

```
     534:         # Stage tracked changes (approximate 'git add -u')
     535:         repo.index.add_all()
     536:         repo.index.write()
     537:
     538:
>>>  539: def _get_previous_message_if_amend(repo: pygit2.Repository, is_amend: bool) -> str | None:
>>>  540:     if not is_amend:
>>>  541:         return None
>>>  542:     try:
>>>  543:         commit = repo.head.peel(pygit2.Commit)
>>>  544:         return (commit.message or "").strip()
>>>  545:     except (KeyError, pygit2.GitError) as e:
>>>  546:         print(f"Error: Cannot amend - failed to retrieve previous commit message: {e}", file=sys.stderr)
>>>  547:         raise ExitWithCode(1)
     548:
     549:
     550: # ---------- commit/editor helpers ------------------------------------
     551:
     552:
   ...
     726:
     727:     # Stage if requested (-a/--all)
     728:     _stage_all_if_requested(repo, include_all)
     729:
     730:     # Get previous commit message if amending
>>>  731:     previous_message = _get_previous_message_if_amend(repo, is_amend)
     732:
     733:     if not (diff := get_commit_diff(repo, include_all, previous_message)).strip():
     734:         # Check if there's truly nothing to commit
     735:         status = _format_status_porcelain(repo)
     736:         if not status:
```

### `resources-take-client.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/resources/server.py`

> Lines 238-241 create `Client(compositor)` internally, but resources server should receive Client as parameter
> instead
> of
> Compositor.
>
> Violates "take what you need" principle (Dependency Injection): (1) server receives Compositor but only uses
> it to
> create Client, (2) creates client internally instead of receiving it, (3) harder to test (can't inject
> mock/test
> client).
>
> Change signature to `make_resources_server(name: str, client: Client)` and use client directly. Caller creates
> Client
> and passes it. Delete useless comments about "bypassing policy gateway" (lines 238-240); parameter docstring
> should
> explain this instead. Benefits: takes what it needs, easier to test, clearer dependencies, follows standard
> DI.

```
     233:     """
     234:     mcp = NotifyingFastMCP(
     235:         name, instructions=("Resources aggregator for listing/reading resources across mounted servers.")
     236:     )
     237:
>>>  238:     # Direct client to compositor (bypasses policy gateway to prevent double enforcement)
>>>  239:     # This client is created without middleware since tools calling this server already
>>>  240:     # went through the policy gateway
>>>  241:     compositor_client = Client(compositor)
     242:
     243:     # ---- Subscriptions index (single resource) -----------------------------
     244:     # Internal store for subscriptions made via this server's subscribe tool.
     245:     # No principals for now; keys are (server, uri).
     246:     subs_lock = asyncio.Lock()
```

### `reversed-enumerate.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/state.py`

> Lines 110-115 define `_find_last_tool_index()` which manually iterates backwards using
> `range(len(state.items) - 1, -1, -1)` and a separate line to extract each item. This
> is verbose and error-prone.
>
> **Problems:**
> Manual index arithmetic (`len(...) - 1, -1, -1`) is verbose. Separate item access
> (`it = state.items[idx]`) adds an extra line. This pattern has a standard Python idiom:
> `reversed(enumerate(...))`.
>
> **Fix:** Use `for idx, it in reversed(list(enumerate(state.items)))`. This makes intent
> explicit ("iterate backwards over indexed items"), eliminates manual arithmetic, and
> combines index+item access in one line.
>
> Note: wrap `enumerate(...)` in `list()` before `reversed()` because enumerate returns
> an iterator that doesn't support reverse iteration directly.

```
     105:     content: ToolContent = ExecContent(cmd=cmd, args=args) if cmd is not None else JsonContent(args=args)
     106:     tool_call = ToolCall(name=tool, call_id=call_id, args_json=None)
     107:     return append_item(state, ToolItem(tool_call=tool_call, content=content))
     108:
     109:
>>>  110: def _find_last_tool_index(state: UiState, call_id: str) -> int | None:
>>>  111:     for idx in range(len(state.items) - 1, -1, -1):
>>>  112:         it = state.items[idx]
>>>  113:         if isinstance(it, ToolItem) and it.tool_call.call_id == call_id:
>>>  114:             return idx
>>>  115:     return None
     116:
     117:
     118: def update_tool_decision(state: UiState, call_id: str, decision: ApprovalKind | None) -> UiState:
     119:     idx = _find_last_tool_index(state, call_id)
     120:     if idx is None:
```

## ducktape/2025-11-20-00 (33)

### `collection-params-empty-tuple.yaml` / `occ-2` [P20]

File: `adgn/src/adgn/agent/persist/sqlite.py`

> Functions accept collection parameters as Optional, defaulting to None, then
> check for None and convert to empty collection. Should use empty collection
> as default instead.
>
> Benefits:
>
> - Simpler type: no Optional/union with None
> - No None checks or reassignments needed
> - Empty tuple is immutable and safe as default
> - Clearer intent: "no items" vs "missing value"
> - Empty collections are falsy if bool check needed
>
> This is a standard Python idiom for collection parameters.
>
> **Note:** attach/detach default to None, then reassigned with `attach or {}` and `detach if detach is not None else []`

```
      94:                 update(Agent).where(Agent.id == agent_id).values(mcp_config=spec_json)
      95:             )
      96:             await session.commit()
      97:
      98:     async def patch_agent_specs(
>>>   99:         self, agent_id: AgentID, *, attach: dict[str, MCPConfig] | None = None, detach: list[str] | None = None
     100:     ) -> MCPConfig:
     101:         attach = attach or {}
     102:         detach = detach if detach is not None else []
     103:         async with self._session() as session:
     104:             result = await session.execute(select(Agent).where(Agent.id == agent_id))
   ...
      96:             await session.commit()
      97:
      98:     async def patch_agent_specs(
      99:         self, agent_id: AgentID, *, attach: dict[str, MCPConfig] | None = None, detach: list[str] | None = None
     100:     ) -> MCPConfig:
>>>  101:         attach = attach or {}
>>>  102:         detach = detach if detach is not None else []
     103:         async with self._session() as session:
     104:             result = await session.execute(select(Agent).where(Agent.id == agent_id))
     105:             agent = result.scalar_one_or_none()
     106:             if not agent:
     107:                 raise KeyError(f"agent not found: {agent_id}")
```

### `collection-params-empty-tuple.yaml` / `occ-3` [P20]

File: `adgn/src/adgn/agent/persist/__init__.py`

> Functions accept collection parameters as Optional, defaulting to None, then
> check for None and convert to empty collection. Should use empty collection
> as default instead.
>
> Benefits:
>
> - Simpler type: no Optional/union with None
> - No None checks or reassignments needed
> - Empty tuple is immutable and safe as default
> - Clearer intent: "no items" vs "missing value"
> - Empty collections are falsy if bool check needed
>
> This is a standard Python idiom for collection parameters.
>
> **Note:** Protocol signature uses Optional instead of default empty collection

```
     136:
     137:     # Agents API ---------------------------------------------------------------
     138:     async def create_agent(self, *, mcp_config: MCPConfig, metadata: AgentMetadata) -> AgentID: ...
     139:     async def update_agent_specs(self, agent_id: AgentID, *, mcp_config: MCPConfig) -> None: ...
     140:     async def patch_agent_specs(
>>>  141:         self, agent_id: AgentID, *, attach: dict[str, MCPConfig] | None = None, detach: list[str] | None = None
     142:     ) -> MCPConfig: ...
     143:     async def list_agents(self) -> list[AgentRow]: ...
     144:     async def get_agent(self, agent_id: AgentID) -> AgentRow | None: ...
     145:     async def list_agents_last_activity(self) -> dict[AgentID, datetime | None]: ...
     146:     async def delete_agent(self, agent_id: AgentID) -> None: ...
```

### `proposal-id-type-mismatch.yaml` / `occ-0` [P20]

File: `adgn/src/adgn/agent/persist/models.py`

> Policy proposal_id (models.py:149) database column is int, but all APIs
> accept str and convert with try/except int() at runtime. 13 locations have
> identical conversion logic.
>
> Using domain types provides:
>
> - Type safety: can't mix different ID types
> - Semantic clarity: not just any string/int, but specific identifier
> - No runtime conversions/validation
> - Clear type contracts in signatures
>
> **Note:** Database model uses int for proposal_id

```
     144:     - SUPERSEDED: Was active, replaced by newer policy
     145:     """
     146:
     147:     __tablename__ = "policies"
     148:
>>>  149:     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
     150:     agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
     151:     content: Mapped[str] = mapped_column(Text, nullable=False)
     152:     status: Mapped[str] = mapped_column(String, nullable=False)  # active|proposed|rejected|superseded (PolicyStatus)
     153:     created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
     154:     decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

### `proposal-id-type-mismatch.yaml` / `occ-1` [P20]

File: `adgn/src/adgn/agent/persist/sqlite.py`

> Policy proposal_id (models.py:149) database column is int, but all APIs
> accept str and convert with try/except int() at runtime. 13 locations have
> identical conversion logic.
>
> Using domain types provides:
>
> - Type safety: can't mix different ID types
> - Semantic clarity: not just any string/int, but specific identifier
> - No runtime conversions/validation
> - Clear type contracts in signatures
>
> **Note:** SQLite layer converts str to int with try/except

```
     218:             await session.commit()
     219:             await session.refresh(policy)
     220:             return policy.id
     221:
     222:     # ---- Policy proposals (single-store: SQLite) ----------------------------
>>>  223:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: str, content: str) -> None:
     224:         async with self._session() as session:
     225:             # Use proposal_id as the policy id (stored as string in old schema, but new schema uses int autoincrement)
     226:             # We need to handle this carefully - let's store the proposal with PROPOSED status
     227:             # The proposal_id from the old API is not used as the primary key in new schema
     228:             policy = Policy(
   ...
     254:                         content="",  # content not selected in list; leave empty
     255:                     )
     256:                 )
     257:         return out
     258:
>>>  259:     async def get_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> PolicyProposal | None:
     260:         async with self._session() as session:
     261:             # proposal_id is now an integer in new schema
     262:             try:
     263:                 policy_id = int(proposal_id)
     264:             except ValueError:
   ...
     275:                 created_at=policy.created_at,
     276:                 decided_at=policy.decided_at,
     277:                 content=policy.content,
     278:             )
     279:
>>>  280:     async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int:
>>>  281:         """Mark proposal approved and make it the active policy.
>>>  282:
>>>  283:         Returns the new active policy id.
>>>  284:         """
>>>  285:         async with self._session() as session:
>>>  286:             try:
>>>  287:                 policy_id = int(proposal_id)
>>>  288:             except ValueError:
>>>  289:                 raise KeyError("proposal_not_found")
     290:
     291:             result = await session.execute(
     292:                 select(Policy).where(Policy.id == policy_id, Policy.agent_id == agent_id)
     293:             )
     294:             policy = result.scalar_one_or_none()
   ...
     306:             policy.status = PolicyStatus.ACTIVE.value
     307:             policy.decided_at = _now()
     308:             await session.commit()
     309:             return policy.id
     310:
>>>  311:     async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None:
>>>  312:         async with self._session() as session:
>>>  313:             try:
>>>  314:                 policy_id = int(proposal_id)
>>>  315:             except ValueError:
>>>  316:                 return
>>>  317:
>>>  318:             await session.execute(
>>>  319:                 update(Policy)
>>>  320:                 .where(Policy.id == policy_id, Policy.agent_id == agent_id)
>>>  321:                 .values(status=ProposalStatus.REJECTED, decided_at=_now())
     322:             )
     323:             await session.commit()
     324:
     325:     # Runs --------------------------------------------------------------------
     326:     async def start_run(
```

### `proposal-id-type-mismatch.yaml` / `occ-2` [P20]

File: `adgn/src/adgn/agent/persist/__init__.py`

> Policy proposal_id (models.py:149) database column is int, but all APIs
> accept str and convert with try/except int() at runtime. 13 locations have
> identical conversion logic.
>
> Using domain types provides:
>
> - Type safety: can't mix different ID types
> - Semantic clarity: not just any string/int, but specific identifier
> - No runtime conversions/validation
> - Clear type contracts in signatures
>
> **Note:** Protocol interface uses str return/param types

```
     197:     # Approval policy (per-agent) --------------------------------------------
     198:     async def get_latest_policy(self, agent_id: AgentID) -> tuple[str, int] | None: ...
     199:     async def set_policy(self, agent_id: AgentID, *, content: str) -> int: ...
     200:
     201:     # Approval policy proposals (single store impl: SQLite)
>>>  202:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: str, content: str) -> None: ...
     203:     async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]: ...
     204:     async def get_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> PolicyProposal | None: ...
     205:     async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int: ...
     206:     async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None: ...
   ...
     199:     async def set_policy(self, agent_id: AgentID, *, content: str) -> int: ...
     200:
     201:     # Approval policy proposals (single store impl: SQLite)
     202:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: str, content: str) -> None: ...
     203:     async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]: ...
>>>  204:     async def get_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> PolicyProposal | None: ...
     205:     async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int: ...
     206:     async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None: ...
   ...
     200:
     201:     # Approval policy proposals (single store impl: SQLite)
     202:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: str, content: str) -> None: ...
     203:     async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]: ...
     204:     async def get_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> PolicyProposal | None: ...
>>>  205:     async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int: ...
     206:     async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None: ...
   ...
     201:     # Approval policy proposals (single store impl: SQLite)
     202:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: str, content: str) -> None: ...
     203:     async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]: ...
     204:     async def get_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> PolicyProposal | None: ...
     205:     async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int: ...
>>>  206:     async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None: ...
```

### `approvals-pending-wrong-attributes.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

> approvals_pending_global builds URIs and JSON by accessing approval.call_id, approval.tool,
> and approval.args, but PendingApproval only exposes tool_call (a ToolCall object) and timestamp.
> The code raises AttributeError on every invocation because these attributes don't exist at the
> PendingApproval level - they need to be accessed via approval.tool_call.call_id,
> approval.tool_call.name, and approval.tool_call.args_json respectively.

```
     395:         "resource://approvals/pending",
     396:         name="approvals.pending.global",
     397:         mime_type="application/json",
     398:         description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)",
     399:     )
>>>  400:     async def approvals_pending_global():
>>>  401:         """Each approval is a separate MCP TextResourceContents block.
>>>  402:
>>>  403:         Crashes if any agent fails (no exception swallowing).
>>>  404:         """
>>>  405:         content_blocks: list[mcp_types.TextResourceContents] = []
>>>  406:
>>>  407:         for agent_id in registry.known_agents():
>>>  408:             infra = await registry.get_infrastructure(agent_id)
>>>  409:             pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)
>>>  410:
>>>  411:             for approval in pending_approvals:
>>>  412:                 approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
>>>  413:                 approval_data = {
>>>  414:                     "agent_id": agent_id,
>>>  415:                     "call_id": approval.call_id,
>>>  416:                     "tool": approval.tool,
>>>  417:                     "args": approval.args,
>>>  418:                     "timestamp": approval.timestamp.isoformat(),
>>>  419:                 }
>>>  420:                 block = mcp_types.TextResourceContents(
>>>  421:                     uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data)
>>>  422:                 )
     423:                 content_blocks.append(block)
     424:
     425:         return mcp_types.ReadResourceResult(contents=content_blocks)
     426:
     427:     @server.resource(
```

### `ensure-schema-destroys-data.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/sqlite.py`

> The `ensure_schema` method unconditionally drops ALL tables before recreating them,
> destroying all persisted data on every call. The function name suggests safe,
> idempotent behavior (ensuring schema exists), but the implementation calls
> `Base.metadata.drop_all()` followed by `create_all()`.
>
> This causes complete data loss on every application restart. Production call sites
> in app.py:176 and cli.py:124 invoke this during startup, wiping agents, runs,
> events, policies, and tool calls each time the server starts.
>
> SQLAlchemy's `create_all()` is already idempotent—it only creates missing tables.
> The `drop_all()` call serves no purpose except data destruction.

```
      62:     async def _session(self):
      63:         """Get an async session."""
      64:         async with self.async_session_maker() as session:
      65:             yield session
      66:
>>>   67:     async def ensure_schema(self) -> None:
>>>   68:         """Create all tables using SQLAlchemy ORM models."""
>>>   69:         async with self.engine.begin() as conn:
>>>   70:             # Drop all tables for clean slate (no backward compatibility)
>>>   71:             await conn.run_sync(Base.metadata.drop_all)
      72:             await conn.run_sync(Base.metadata.create_all)
      73:
      74:     # Agents -----------------------------------------------------------------
      75:     async def create_agent(self, *, mcp_config: MCPConfig, metadata: AgentMetadata) -> AgentID:
      76:         agent_id = AgentID(uuid.uuid4().hex)
```

### `exceptiongroup-not-error-strings.yaml` / `occ-0`

File: `adgn/src/adgn/agent/runtime/running.py`

> RunningInfrastructure.close() collects errors as strings and returns them
> in CloseResult, requiring callers to check return value (running.py:72-91).
>
> Current pattern:
> errors: list[str] = []
> for sidecar in reversed(self.\_sidecars):
> try:
> await sidecar.detach()
> except Exception as e:
> errors.append(f"{type(sidecar).**name**}: {e}")
>
> # ... more error collection
>
> if errors:
> return CloseResult(drained=False, error="; ".join(errors))
> return CloseResult(drained=True)
>
> Problems:
>
> - Caller must remember to check result.error (easy to forget)
> - Exception information degraded to strings (no stack traces)
> - Can't distinguish different error types
> - Loses structured exception hierarchy
> - Error handling is opt-in, not automatic
>
> Should raise ExceptionGroup (Python 3.11+):
> exceptions: list[Exception] = []
> for sidecar in reversed(self.\_sidecars):
> try:
> await sidecar.detach()
> except Exception as e:
> exceptions.append(e)
>
> # ... more error collection
>
> if exceptions:
> raise ExceptionGroup("Failed to close infrastructure", exceptions)
>
> Benefits:
>
> - Errors can't be ignored (exceptions propagate by default)
> - Preserves full exception context and stack traces
> - Standard Python pattern for multiple concurrent errors
> - Type-safe: can catch and handle specific exception types
> - Forces explicit error handling at call site
>
> ExceptionGroup designed exactly for this use case: collecting multiple
> exceptions during cleanup/teardown operations.

```
      67:     async def attach_sidecar(self, sidecar: Sidecar) -> None:
      68:         """Sidecars are detached in reverse order when close() is called."""
      69:         await sidecar.attach(self)
      70:         self._sidecars.append(sidecar)
      71:
>>>   72:     async def close(self) -> CloseResult:
>>>   73:         """Sidecars are detached in reverse order of attachment."""
>>>   74:         errors: list[str] = []
>>>   75:
>>>   76:         # Detach sidecars in reverse order
>>>   77:         for sidecar in reversed(self._sidecars):
>>>   78:             try:
>>>   79:                 await sidecar.detach()
>>>   80:             except Exception as e:
>>>   81:                 errors.append(f"{type(sidecar).__name__}: {e}")
>>>   82:
>>>   83:         # Close async exit stack
>>>   84:         try:
>>>   85:             await self._stack.aclose()
>>>   86:         except Exception as e:
>>>   87:             errors.append(f"stack: {e}")
>>>   88:
>>>   89:         if errors:
>>>   90:             return CloseResult(drained=False, error="; ".join(errors))
>>>   91:         return CloseResult(drained=True)
      92:
      93:     async def __aenter__(self) -> RunningInfrastructure:
      94:         return self
      95:
      96:     async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
```

### `parse-response-should-not-exist.yaml` / `occ-0`

File: `adgn/src/adgn/llm/sysrw/openai_typing.py`

> parse_response_messages accepts Any and converts to list[ResponseOutputMessage].
> This function exists because callers hold untyped data and need runtime validation.
>
> Problem: This defers type safety to runtime. Callers should receive properly
> typed data from API responses directly.
>
> Should instead:
>
> 1. Type API response parsing at source (where data enters system)
> 2. Callers work with list[ResponseOutputMessage] | None from the start
> 3. No runtime validation needed in application layer
>
> The function is a symptom of inadequate typing at API boundary.
>
> If using OpenAI SDK or similar, the response should already be typed.
> If parsing raw JSON, parse to typed Response object immediately, not dict[str, Any].
>
> Benefits of proper typing at source:
>
> - Type errors caught at compile time, not runtime
> - No defensive validation in application code
> - Clearer data flow: typed from API → typed throughout
> - No Any spreading through codebase
>
> Same principle applies to parse_chat_messages.
>
> **Note:** parse_response_messages function

```
     106:
     107:
     108: # Removed parse_tool_call and extract_*_tool_call_info - no longer needed since we work with typed objects directly
     109:
     110:
>>>  111: def parse_response_messages(messages: Any) -> list[ResponseOutputMessage] | None:
>>>  112:     """Parse messages into validated ResponseOutputMessage objects.
>>>  113:
>>>  114:     Args:
>>>  115:         messages: Unvalidated external payload (typically from OpenAI API response).
>>>  116:                   Structured validation happens via TypeAdapter within function.
>>>  117:
>>>  118:     Returns:
>>>  119:         Validated list of ResponseOutputMessage objects, or None if messages is falsy.
>>>  120:     """
>>>  121:     if not messages:
>>>  122:         return None
>>>  123:     return TypeAdapter(list[ResponseOutputMessage]).validate_python(messages)
     124:
     125:
     126: def dump_response_messages(messages: list[ResponseOutputMessage]) -> list[dict[str, Any]]:
     127:     """Convert validated ResponseOutputMessage objects back to dict form."""
     128:     return [msg.model_dump(by_alias=True) for msg in messages]
```

### `parse-response-should-not-exist.yaml` / `occ-1`

File: `adgn/src/adgn/llm/sysrw/openai_typing.py`

> parse_response_messages accepts Any and converts to list[ResponseOutputMessage].
> This function exists because callers hold untyped data and need runtime validation.
>
> Problem: This defers type safety to runtime. Callers should receive properly
> typed data from API responses directly.
>
> Should instead:
>
> 1. Type API response parsing at source (where data enters system)
> 2. Callers work with list[ResponseOutputMessage] | None from the start
> 3. No runtime validation needed in application layer
>
> The function is a symptom of inadequate typing at API boundary.
>
> If using OpenAI SDK or similar, the response should already be typed.
> If parsing raw JSON, parse to typed Response object immediately, not dict[str, Any].
>
> Benefits of proper typing at source:
>
> - Type errors caught at compile time, not runtime
> - No defensive validation in application code
> - Clearer data flow: typed from API → typed throughout
> - No Any spreading through codebase
>
> Same principle applies to parse_chat_messages.
>
> **Note:** parse_chat_messages function

```
     131: def dump_chat_messages(messages: list[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
     132:     """Convert ChatCompletionMessageParam objects to dict form."""
     133:     return [TypeAdapter(dict[str, Any]).validate_python(msg) for msg in messages]
     134:
     135:
>>>  136: def parse_chat_messages(messages: Any) -> list[ChatCompletionMessageParam] | None:
>>>  137:     """Parse messages into validated ChatCompletionMessageParam objects.
>>>  138:
>>>  139:     Args:
>>>  140:         messages: Unvalidated external payload (typically from stored state or API).
>>>  141:                   Structured validation happens via TypeAdapter within function.
>>>  142:
>>>  143:     Returns:
>>>  144:         Validated list of ChatCompletionMessageParam objects, or None if messages is falsy.
>>>  145:     """
>>>  146:     if not messages:
>>>  147:         return None
>>>  148:     return TypeAdapter(list[ChatCompletionMessageParam]).validate_python(messages)
     149:
     150:
     151: # Remove this function - parse the data into the right type first instead of handling unions
     152:
     153:
```

### `policy-table-status-enum-inconsistency.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/sqlite.py`

> The Policy table's status column is written with values from two different enums inconsistently:
> approve_policy_proposal (lines 303-308) writes PolicyStatus.ACTIVE and PolicyStatus.SUPERSEDED,
> while reject_policy_proposal (line 321) writes ProposalStatus.REJECTED. This means the same
> database column holds a mix of enum values from different types, making queries fragile and
> prone to type errors when instantiating Pydantic models (e.g., PolicyProposal expects
> ProposalStatus but may receive PolicyStatus values). These should be merged into a single enum
> representing all policy states (active, superseded, pending, approved, rejected) for a unified
> policy table that tracks both proposals and active policies. Additionally, the enum could be
> linked to the ORM using SQLAlchemy's Enum type (which creates a SQL-level CHECK constraint or
> native enum type) to prevent storing invalid status values and catch misuse at the API boundary.

```
     298:             # Mark existing ACTIVE policies as SUPERSEDED
     299:             await session.execute(
     300:                 update(Policy)
     301:                 .where(Policy.agent_id == agent_id, Policy.status == PolicyStatus.ACTIVE.value)
     302:                 .values(status=PolicyStatus.SUPERSEDED.value)
>>>  303:             )
>>>  304:
>>>  305:             # Mark proposal as ACTIVE
>>>  306:             policy.status = PolicyStatus.ACTIVE.value
>>>  307:             policy.decided_at = _now()
>>>  308:             await session.commit()
     309:             return policy.id
     310:
     311:     async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None:
     312:         async with self._session() as session:
     313:             try:
   ...
     316:                 return
     317:
     318:             await session.execute(
     319:                 update(Policy)
     320:                 .where(Policy.id == policy_id, Policy.agent_id == agent_id)
>>>  321:                 .values(status=ProposalStatus.REJECTED, decided_at=_now())
     322:             )
     323:             await session.commit()
     324:
     325:     # Runs --------------------------------------------------------------------
     326:     async def start_run(
```

### `policyerror-stage-strenum.yaml` / `occ-0`

File: `adgn/src/adgn/agent/models/policy_error.py`

> PolicyError.stage uses Literal["read", "parse", "tests"] instead of StrEnum
> for consistency with the rest of the codebase.
>
> Same file already uses StrEnum for PolicyErrorCode (lines 9-11), creating
> inconsistency. For fixed string sets with semantic meaning, StrEnum is
> preferred over Literal because it provides IDE autocomplete, type checking,
> refactoring support, and runtime validation.
>
> Should define PolicyErrorStage as StrEnum with READ/PARSE/TESTS members.
>
> Deeper question: Should stage field exist at all? PolicyErrorCode already
> captures error type (READ_ERROR, PARSE_ERROR). If stage is always derivable
> from code, it's redundant.

```
      10:     READ_ERROR = "read_error"
      11:     PARSE_ERROR = "parse_error"
      12:
      13:
      14: class PolicyError(BaseModel):
>>>   15:     stage: Literal["read", "parse", "tests"] = Field(description="Processing stage where error occurred")
      16:     code: PolicyErrorCode = Field(description="Error code (read_error, parse_error)")
      17:     index: int | None = Field(None, description="Character/token index where error occurred")
      18:     length: int | None = Field(None, description="Length of error span in characters/tokens")
      19:     message: str | None = Field(None, description="Human-readable error message")
      20:
```

### `preset-modified-at-datetime.yaml` / `occ-0`

File: `adgn/src/adgn/agent/presets.py`

> AgentPreset.modified_at uses str for timestamp instead of datetime type. Timestamps
> should use datetime, not strings, for type safety, operations (comparison, arithmetic),
> and automatic ISO-8601 serialization. Pydantic handles datetime serialization to JSON
> automatically. Only use str when interfacing with systems requiring precise control
> over format.

```
      25:     system: str | None = Field(None, description="System message for the agent")
      26:     specs: dict[str, JsonValue] = Field(default_factory=dict, description="Agent specifications (arbitrary JSON)")
      27:     approval_policy: str | None = Field(None, description="Approval policy Python source code")
      28:     # Source metadata (filled by loader; used by UI)
      29:     file_path: str | None = Field(None, description="Source file path for this preset")
>>>   30:     modified_at: str | None = Field(None, description="Last modification time (ISO-8601 string)")
      31:
      32:
      33: def _load_yaml(path: Path) -> dict[str, JsonValue]:
      34:     with path.open("r", encoding="utf-8") as f:
      35:         data = yaml.safe_load(f) or {}
```

### `pydantic-read-path.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/sqlite.py`

> Building intermediate dict before constructing Pydantic model at read boundary.
>
> Code creates row_dict from SQLAlchemy result (lines 445-454), then passes to
> parse_event. This intermediate dict step is unnecessary and loses type safety.
>
> Should construct EventRecord directly with keyword arguments for immediate field
> validation and type checking.
>
> Anti-pattern: dict as intermediate representation when going from DB row to
> typed model. Correct approach: pass SQLAlchemy row fields directly to Pydantic
> constructor using keyword arguments.
>
> Benefits:
>
> - Type safety: catch field mismatches at type-check time
> - No intermediate dict allocation
> - Immediate validation on construction
> - Clearer data flow

```
     440:         async with self._session() as session:
     441:             result = await session.execute(
     442:                 select(Event).where(Event.run_id == str(run_id)).order_by(Event.seq.asc())
     443:             )
     444:             events = result.scalars().all()
>>>  445:             for event in events:
>>>  446:                 row_dict = {
>>>  447:                     "seq": event.seq,
>>>  448:                     "ts": event.event_at,  # Map event_at back to ts for compatibility
>>>  449:                     "type": event.type,
>>>  450:                     "payload": event.payload,
>>>  451:                     "call_id": event.call_id,
>>>  452:                     "tool_key": event.tool_key,
>>>  453:                 }
>>>  454:                 out.append(parse_event(row_dict))
     455:         return out
     456:
     457:     # Tool Calls (new ToolCallRecord persistence) --------------------------------
     458:     async def save_tool_call(self, record: ToolCallRecord) -> None:
     459:         """Save or update a tool call record."""
```

### `pydantic-write-path.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/handler.py`

> Pre-serialization of Pydantic models before passing to persistence layer.
>
> Calls model_dump() at caller site (lines 102-103, 110, 145-146) before passing
> to persistence methods. This violates separation of concerns - caller shouldn't
> know about persistence format.
>
> Anti-pattern: Serialization at caller site instead of callee. Correct approach:
> append_event should accept typed EventRecord payload, ResponsePayload should
> accept Response model, and serialization should happen inside persistence layer.
>
> Benefits:
>
> - Type safety preserved across call boundary
> - Single serialization point (DRY)
> - Clearer responsibility boundaries
> - Caller doesn't need to know persistence format
> - Easier to change serialization strategy later

```
      97:         # Reset sequence if run changed (auto-bind path)
      98:         if self._last_run_id != rid:
      99:             self._last_run_id = rid
     100:             self._seq = 0
     101:         self._seq += 1
>>>  102:         # Convert TypedPayload to dict for persistence
>>>  103:         payload_dict = payload.model_dump(mode="json", exclude_none=True)
     104:         self._spawn(
     105:             self._persistence.append_event(
     106:                 run_id=rid,
     107:                 seq=self._seq,
     108:                 ts=self._now(),
   ...
     105:             self._persistence.append_event(
     106:                 run_id=rid,
     107:                 seq=self._seq,
     108:                 ts=self._now(),
     109:                 type=type,
>>>  110:                 payload=payload_dict,
     111:                 call_id=call_id,
     112:                 tool_key=tool_key,
     113:             )
     114:         )
     115:
   ...
     140:     def on_reasoning(self, item: ReasoningItem) -> None:
     141:         self._record_event(type=EventType.REASONING, payload=ReasoningPayload(text=item.text))
     142:
     143:     def on_response(self, evt: Response) -> None:
     144:         # Convert Response to ResponsePayload; for now pass full dumped content
>>>  145:         content_dict = evt.model_dump(mode="json", exclude_none=True)
>>>  146:         self._record_event(type=EventType.RESPONSE, payload=ResponsePayload(content=content_dict))
```

### `registry-get-missing.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/status_shared.py`

> InfrastructureRegistry.get() method is called but does not exist in the class definition.
>
> The calls should likely use get_running_infrastructure() instead,
> based on the usage pattern where the result is checked for None.
>
> **Note:** Called in build_agent_status_core: c = registry.get(agent_id)

```
     109:     container id (for non-ephemeral runtime), pending approvals, and run phase.
     110:     """
     111:     registry = app.state.registry
     112:     persistence = app.state.persistence
     113:
>>>  114:     c = registry.get(agent_id)
     115:     present = c is not None
     116:
     117:     # UI + approvals + active run
     118:     ui_ready = bool(c and c._ui_manager is not None)
     119:     pending = 0
```

### `registry-get-missing.yaml` / `occ-1`

File: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

> InfrastructureRegistry.get() method is called but does not exist in the class definition.
>
> The calls should likely use get_running_infrastructure() instead,
> based on the usage pattern where the result is checked for None.
>
> **Note:** Called in agent_ui_state_resource: runtime = registry.get(agent_id)

```
     511:         mime_type="application/json",
     512:         description="UI state (optional, only if UI server attached)",
     513:     )
     514:     async def agent_ui_state_resource(agent_id: AgentID) -> str:
     515:         """UI state (optional, only if UI server attached)."""
>>>  516:         runtime = registry.get(agent_id)
     517:         if not runtime or not runtime.runtime.session:
     518:             raise ValueError(f"Agent {agent_id} has no session")
     519:
     520:         ui_state = runtime.runtime.session.ui_state
     521:
```

### `return-result-not-reconstruct.yaml` / `occ-0`

File: `adgn/src/adgn/agent/runtime/registry.py`

> AgentContainer.close() deconstructs CloseResult to rebuild identical dict
> (registry.py:43-44):
>
> result = await self.running.close() # Returns CloseResult
> return {"drained": result.drained, "error": result.error}
>
> CloseResult is a dataclass with drained and error fields (running.py:28-31).
> The code extracts these fields to create a dict with the same structure.
>
> Should return the result directly:
> return await self.running.close()
>
> Or inline the call:
> await self.runtime.close()
> return await self.running.close()
>
> Benefits:
>
> - No useless reconstruction
> - Preserves type information (CloseResult vs untyped dict)
> - Clearer intent: propagate result from running.close()
> - Less code
>
> Investigation shows return value unused at call site (registry.py:105),
> so dict reconstruction serves no purpose. If serialization needed, use
> dataclasses.asdict() or Pydantic.

```
      38:     _ui_bus: ServerBus | None = None
      39:
      40:     async def close(self):
      41:         """Lifecycle management - close all components together."""
      42:         await self.runtime.close()
>>>   43:         result = await self.running.close()
>>>   44:         return {"drained": result.drained, "error": result.error}
      45:
      46:
      47: @dataclass
      48: class AgentRegistry:
      49:     """Registry for managing agent runtimes.
```

### `send-json-duplicate-logic.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/runtime.py`

> send_json and \_send_direct_all have identical logic except for how they send
> (runtime.py:119-128, 187-196).
>
> send_json uses q.put_nowait():
> for \_ws, q, \_task in list(self.\_clients.values()):
> q.put_nowait(dumped)
>
> \_send_direct_all uses ws.send_json():
> for ws, \_q, \_task in list(self.\_clients.values()):
> await ws.send_json(dumped)
>
> Both:
>
> 1. Create identical Envelope with same fields
> 2. Call model_dump(mode="json")
> 3. Iterate over self.\_clients.values()
> 4. Send to each client
>
> Only difference: synchronous put_nowait vs async send_json.
>
> Should extract common logic:
> def \_create_envelope(self, payload: ServerMessage) -> dict:
> return Envelope(
> session_id=self.\_session_id,
> event_id=self.\_next_event_id(),
> event_at=datetime.now(UTC),
> payload=payload,
> ).model_dump(mode="json")
>
> async def send_json(self, payload: ServerMessage) -> None:
> dumped = self.\_create_envelope(payload)
> for \_ws, q, \_task in list(self.\_clients.values()):
> q.put_nowait(dumped)
>
> async def \_send_direct_all(self, payload: ServerMessage) -> None:
> dumped = self.\_create_envelope(payload)
> for ws, \_q, \_task in list(self.\_clients.values()):
> await ws.send_json(dumped)
>
> Or unify completely if possible.
>
> Benefits:
>
> - DRY: envelope creation in one place
> - Easier to maintain: change once, affects both
> - Clear separation: envelope creation vs distribution

```
     114:
     115:     def _next_event_id(self) -> int:
     116:         self._event_id += 1
     117:         return self._event_id
     118:
>>>  119:     async def send_json(self, payload: ServerMessage) -> None:
>>>  120:         envelope = Envelope(
>>>  121:             session_id=self._session_id,
>>>  122:             event_id=self._next_event_id(),
>>>  123:             event_at=datetime.now(UTC),
>>>  124:             payload=payload,
>>>  125:         )
>>>  126:         dumped = envelope.model_dump(mode="json")
>>>  127:         for _ws, q, _task in list(self._clients.values()):
>>>  128:             q.put_nowait(dumped)
     129:
     130:     async def _send_and_reduce(self, payload: ServerMessage) -> None:
     131:         await self.send_payload(payload)
     132:         assert self._session is not None
     133:         await self._session._apply_ui_event(payload)
   ...
     182:         self._spawn(self._send_and_reduce(ut))
     183:         # Notify MCP bridge of session state change
     184:         if self._session_state_notifier is not None:
     185:             self._session_state_notifier()
     186:
>>>  187:     async def _send_direct_all(self, payload: ServerMessage) -> None:
>>>  188:         envelope = Envelope(
>>>  189:             session_id=self._session_id,
>>>  190:             event_id=self._next_event_id(),
>>>  191:             event_at=datetime.now(UTC),
>>>  192:             payload=payload,
>>>  193:         )
>>>  194:         dumped = envelope.model_dump(mode="json")
>>>  195:         for ws, _q, _task in list(self._clients.values()):
>>>  196:             await ws.send_json(dumped)
     197:
     198:     def on_assistant_text_event(self, evt: AssistantText) -> None:
     199:         raise RuntimeError("assistant_text not allowed in UI mode; use ui.send_message tool instead")
     200:
     201:     def on_tool_call_event(self, evt: ToolCall) -> None:
```

### `snapshot-misses-active-run-at-start.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/runtime.py`

> AgentSession.\_run_impl builds and sends a snapshot before setting self.active_run. Line 399
> calls `await self._manager.send_payload(await self.build_snapshot())` but self.active_run isn't
> assigned until line 400-402. Since build_snapshot only includes run metadata when
> self.active_run is non-None, the startup snapshot always contains active_run_id=None, empty
> pending_approvals, and no SnapshotDetails. UI clients reading the snapshot resource never learn
> that a run started until the next snapshot emission (typically at run completion). The
> active_run assignment should be moved before the build_snapshot call so the snapshot accurately
> reflects that a run is active.

```
     394:             await self._manager.broadcast_status(True, run_id)
     395:             # Also push a fresh Snapshot so UIs that rely on snapshot-only
     396:             # state (not incremental run_status) update immediately.
     397:             # This helps early UI elements like the Abort button appear
     398:             # deterministically even if they don't consume run_status events.
>>>  399:             await self._manager.send_payload(await self.build_snapshot())
>>>  400:             self.active_run = RunState(
>>>  401:                 run_id=run_id, status=UiRunStatus.RUNNING, started_at=started, pending_approvals=[], last_event_id=None
>>>  402:             )
     403:             self._run_counter += 1
     404:             # Notify MCP bridge of session state change (run started)
     405:             if self._manager._session_state_notifier is not None:
     406:                 self._manager._session_state_notifier()
     407:             finish_status = PersistenceRunStatus.FINISHED
```

### `str-fallback-on-structured.yaml` / `occ-0`

File: `adgn/src/adgn/llm/sysrw/openai_typing.py`

> chat_param_message_content_as_text (lines 75-105) claims to "extract text content", but when
> content is not a plain string (e.g., multi-part ChatCompletion\*MessageParam with structured
> content like [{'type': 'text', 'text': 'hi'}]), it falls back to str(content) (lines 85, 92,
> 99, 104), returning the Python repr of the structure instead of the actual text. This is
> misleading and makes it easy to abuse the API - callers receive strings like "[{'type':
>
> > 'text', 'text': 'hi'}]" and may not realize they're getting repr output rather than extracted
> > text. The function should be designed to make abuse hard: it should expect text-only content
> > and either raise an exception or return None (with a return type like str | None) when called
> > on non-text content, forcing callers to handle structured content explicitly. The name and
> > docstring should also clarify that this is only for text-only messages.

```
      80:         case MessageRole.ASSISTANT:
      81:             # ChatCompletionAssistantMessageParam - content is optional
      82:             content = message.get("content")
      83:             if isinstance(content, str):
      84:                 return content
>>>   85:             return str(content) if content else ""
      86:         case MessageRole.USER:
      87:             # ChatCompletionUserMessageParam - content is required
      88:             content = message["content"]
      89:             if isinstance(content, str):
      90:                 return content
   ...
      87:             # ChatCompletionUserMessageParam - content is required
      88:             content = message["content"]
      89:             if isinstance(content, str):
      90:                 return content
      91:             return str(content)
>>>   92:         case MessageRole.SYSTEM:
      93:             # ChatCompletionSystemMessageParam - content is required
      94:             content = message["content"]
      95:             if isinstance(content, str):
      96:                 return content
      97:             return str(content)
   ...
      94:             content = message["content"]
      95:             if isinstance(content, str):
      96:                 return content
      97:             return str(content)
      98:         case MessageRole.TOOL | MessageRole.FUNCTION | MessageRole.DEVELOPER:
>>>   99:             # Other message types - handle gracefully
     100:             content = message.get("content")
     101:             if isinstance(content, str):
     102:                 return content
     103:             return str(content) if content else ""
     104:         case _:
   ...
      99:             # Other message types - handle gracefully
     100:             content = message.get("content")
     101:             if isinstance(content, str):
     102:                 return content
     103:             return str(content) if content else ""
>>>  104:         case _:
     105:             raise ValueError(f"Unhandled MessageRole: {role}")
     106:
     107:
     108: # Removed parse_tool_call and extract_*_tool_call_info - no longer needed since we work with typed objects directly
     109:
```

### `stub-convenience-stack-method.yaml` / `occ-0`

File: `adgn/src/adgn/agent/runtime/infrastructure.py`

> Creating typed server stubs requires verbose boilerplate (infrastructure.py:180-186):
>
> reader_client = Client(reader_server)
> await stack.enter_async_context(reader_client)
> policy_reader = PolicyReaderStub(TypedClient(reader_client))
>
> approver_client = Client(approver_server)
> await stack.enter_async_context(approver_client)
> policy_approver = PolicyApproverStub(TypedClient(approver_client))
>
> This 3-line pattern repeats for every stub. Should provide convenience method:
>
> policy_reader = await PolicyReaderStub.for_server(stack, reader_server)
> policy_approver = await PolicyApproverStub.for_server(stack, approver_server)
>
> Or even simpler with context manager protocol on stub class.
>
> The for_server method would encapsulate:
>
> 1. Create Client from server
> 2. Enter into async context stack
> 3. Wrap in TypedClient
> 4. Return stub instance
>
> Benefits:
>
> - DRY: pattern in one place
> - Less error-prone: can't forget context manager entry
> - Clearer intent: "create stub from server"
> - Reduces line count 3:1
>
> This suggests base class method or helper function in server stub framework.
>
> **Note:** PolicyReaderStub creation boilerplate

```
     175:         )
     176:         await compositor.mount_inproc(APPROVAL_POLICY_SERVER_NAME_PROPOSER, proposer_server)
     177:
     178:         approver_server = ApprovalPolicyAdminServer(engine=approval_engine, name=APPROVAL_POLICY_SERVER_NAME_APPROVER)
     179:
>>>  180:         reader_client = Client(reader_server)
>>>  181:         await stack.enter_async_context(reader_client)
>>>  182:         policy_reader = PolicyReaderStub(TypedClient(reader_client))
     183:
     184:         approver_client = Client(approver_server)
     185:         await stack.enter_async_context(approver_client)
     186:         policy_approver = PolicyApproverStub(TypedClient(approver_client))
     187:
```

### `stub-convenience-stack-method.yaml` / `occ-1`

File: `adgn/src/adgn/agent/runtime/infrastructure.py`

> Creating typed server stubs requires verbose boilerplate (infrastructure.py:180-186):
>
> reader_client = Client(reader_server)
> await stack.enter_async_context(reader_client)
> policy_reader = PolicyReaderStub(TypedClient(reader_client))
>
> approver_client = Client(approver_server)
> await stack.enter_async_context(approver_client)
> policy_approver = PolicyApproverStub(TypedClient(approver_client))
>
> This 3-line pattern repeats for every stub. Should provide convenience method:
>
> policy_reader = await PolicyReaderStub.for_server(stack, reader_server)
> policy_approver = await PolicyApproverStub.for_server(stack, approver_server)
>
> Or even simpler with context manager protocol on stub class.
>
> The for_server method would encapsulate:
>
> 1. Create Client from server
> 2. Enter into async context stack
> 3. Wrap in TypedClient
> 4. Return stub instance
>
> Benefits:
>
> - DRY: pattern in one place
> - Less error-prone: can't forget context manager entry
> - Clearer intent: "create stub from server"
> - Reduces line count 3:1
>
> This suggests base class method or helper function in server stub framework.
>
> **Note:** PolicyApproverStub creation boilerplate

```
     179:
     180:         reader_client = Client(reader_server)
     181:         await stack.enter_async_context(reader_client)
     182:         policy_reader = PolicyReaderStub(TypedClient(reader_client))
     183:
>>>  184:         approver_client = Client(approver_server)
>>>  185:         await stack.enter_async_context(approver_client)
>>>  186:         policy_approver = PolicyApproverStub(TypedClient(approver_client))
     187:
     188:         return (policy_reader, policy_approver)
     189:
     190:     async def _install_policy_gateway(
     191:         self, compositor: Compositor, approval_hub: ApprovalHub, policy_reader: PolicyReaderStub
```

### `token-role-invalid-state.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/mcp_routing.py`

> TokenRole + agent_id (mcp_routing.py:76-97) accepts role and agent_id
> separately, allowing invalid state (AGENT role without agent_id). Should
> use discriminated union (HumanTokenInfo | AgentTokenInfo) to make invalid
> state unrepresentable.
>
> Current code has runtime check `if not agent_id` at line 86 to handle
> the invalid state that the type system allows.
>
> Using discriminated union provides:
>
> - Type safety: invalid states unrepresentable
> - No runtime validation needed
> - Clear type contracts in signatures

```
      71:                 auth_value = value.decode("utf-8")
      72:                 if auth_value.startswith("Bearer "):
      73:                     return auth_value[7:]  # Strip "Bearer " prefix
      74:         return None
      75:
>>>   76:     async def _get_backend_app(self, role: TokenRole, agent_id: str | None) -> ASGIApp:
>>>   77:         """Get or create backend ASGI app for the given role/agent_id."""
>>>   78:         if role == TokenRole.HUMAN:
>>>   79:             backend_key = "human"
>>>   80:             if backend_key not in self._backend_apps:
>>>   81:                 # Use the agents management server's HTTP app
>>>   82:                 self._backend_apps[backend_key] = self.agents_server.http_app()  # type: ignore[assignment]
>>>   83:             return self._backend_apps[backend_key]
>>>   84:
>>>   85:         if role == TokenRole.AGENT:
>>>   86:             if not agent_id:
>>>   87:                 raise ValueError("Agent role requires agent_id")
>>>   88:
>>>   89:             backend_key = f"agent:{agent_id}"
>>>   90:             if backend_key not in self._backend_apps:
>>>   91:                 # Get the agent's compositor HTTP app
>>>   92:                 container = await self.registry.ensure_live(AgentID(agent_id), with_ui=False)
>>>   93:                 compositor_app = container.running.compositor.http_app()
>>>   94:                 self._backend_apps[backend_key] = compositor_app  # type: ignore[assignment]
>>>   95:             return self._backend_apps[backend_key]
>>>   96:
>>>   97:         raise ValueError(f"Unknown role: {role}")
      98:
      99:     async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
     100:         """Route request to appropriate backend based on token."""
     101:         # Extract Bearer token
     102:         token = self._extract_bearer_token(request.scope["headers"])
   ...
      81:                 # Use the agents management server's HTTP app
      82:                 self._backend_apps[backend_key] = self.agents_server.http_app()  # type: ignore[assignment]
      83:             return self._backend_apps[backend_key]
      84:
      85:         if role == TokenRole.AGENT:
>>>   86:             if not agent_id:
      87:                 raise ValueError("Agent role requires agent_id")
      88:
      89:             backend_key = f"agent:{agent_id}"
      90:             if backend_key not in self._backend_apps:
      91:                 # Get the agent's compositor HTTP app
```

### `token-table-pydantic-model.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/mcp_routing.py`

> TOKEN_TABLE uses nested untyped dicts (mcp_routing.py:37-40):
>
> TOKEN_TABLE: dict[str, dict[str, str]] = {
> "human-token-123": {"role": "human"},
> "agent-token-abc": {"role": "agent", "agent_id": "agent-1"},
> }
>
> Problems:
>
> - No type safety: can't validate field presence
> - No autocomplete for fields (role, agent_id)
> - Field names are magic strings
> - Can't distinguish required vs optional fields
> - Code accesses with dict["role"], dict.get("agent_id")
>
> Should define Pydantic model:
> class TokenInfo(BaseModel):
> role: TokenRole # Already a StrEnum
> agent_id: AgentID | None = None
>
> TOKEN_TABLE: dict[str, TokenInfo] = {
> "human-token-123": TokenInfo(role=TokenRole.HUMAN),
> "agent-token-abc": TokenInfo(role=TokenRole.AGENT, agent_id="agent-1"),
> }
>
> Benefits:
>
> - Type safety: token_info.role, token_info.agent_id
> - Validation: can't create invalid TokenInfo
> - Clear schema: required role, optional agent_id
> - IDE support: autocomplete and type checking
>
> Code already uses TokenRole enum, should extend to full typed model.

```
      32:     AGENT = "agent"  # Routes to agent's compositor
      33:
      34:
      35: # Token table: token -> {role: str, agent_id?: str}
      36: # In production, this would be a database lookup or external service
>>>   37: TOKEN_TABLE: dict[str, dict[str, str]] = {
>>>   38:     "human-token-123": {"role": "human"},
>>>   39:     "agent-token-abc": {"role": "agent", "agent_id": "agent-1"},
>>>   40: }
      41:
      42:
      43: class MCPRoutingMiddleware(BaseHTTPMiddleware):
      44:     """Routes MCP connections based on Bearer token to appropriate backend server.
      45:
   ...
     110:             logger.warning(f"Invalid token: {token[:10]}...")
     111:             return Response(content="Invalid token", status_code=401)
     112:
     113:         # Determine role and routing
     114:         try:
>>>  115:             role = TokenRole(token_info["role"])
     116:             agent_id = token_info.get("agent_id")
     117:
     118:             logger.info(f"Routing MCP request: role={role}, agent_id={agent_id}")
     119:
     120:             # Get backend app
   ...
     111:             return Response(content="Invalid token", status_code=401)
     112:
     113:         # Determine role and routing
     114:         try:
     115:             role = TokenRole(token_info["role"])
>>>  116:             agent_id = token_info.get("agent_id")
     117:
     118:             logger.info(f"Routing MCP request: role={role}, agent_id={agent_id}")
     119:
     120:             # Get backend app
     121:             backend_app = await self._get_backend_app(role, agent_id)
```

### `unnecessary-wrapper-functions.yaml` / `occ-0`

File: `adgn/src/adgn/llm/sysrw/openai_typing.py`

> Trivial wrapper functions that add no abstraction value. Only create wrapper
> functions when they add real abstraction (combine multiple operations),
> provide domain-specific naming clarity, or encapsulate complex logic.
>
> **Note:** dump_response_messages/dump_chat_messages/parse_tool_params are one-line wrappers around Pydantic methods

```
     121:     if not messages:
     122:         return None
     123:     return TypeAdapter(list[ResponseOutputMessage]).validate_python(messages)
     124:
     125:
>>>  126: def dump_response_messages(messages: list[ResponseOutputMessage]) -> list[dict[str, Any]]:
>>>  127:     """Convert validated ResponseOutputMessage objects back to dict form."""
>>>  128:     return [msg.model_dump(by_alias=True) for msg in messages]
     129:
     130:
     131: def dump_chat_messages(messages: list[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
     132:     """Convert ChatCompletionMessageParam objects to dict form."""
     133:     return [TypeAdapter(dict[str, Any]).validate_python(msg) for msg in messages]
   ...
     126: def dump_response_messages(messages: list[ResponseOutputMessage]) -> list[dict[str, Any]]:
     127:     """Convert validated ResponseOutputMessage objects back to dict form."""
     128:     return [msg.model_dump(by_alias=True) for msg in messages]
     129:
     130:
>>>  131: def dump_chat_messages(messages: list[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
>>>  132:     """Convert ChatCompletionMessageParam objects to dict form."""
>>>  133:     return [TypeAdapter(dict[str, Any]).validate_python(msg) for msg in messages]
     134:
     135:
     136: def parse_chat_messages(messages: Any) -> list[ChatCompletionMessageParam] | None:
     137:     """Parse messages into validated ChatCompletionMessageParam objects.
     138:
   ...
     154: def parse_response(response: dict[str, Any]) -> Response:
     155:     """Parse response data into validated Response object."""
     156:     return TypeAdapter(Response).validate_python(response)
     157:
     158:
>>>  159: def parse_tool_params(params: dict[str, Any]) -> dict[str, Any]:
>>>  160:     """Parse and validate tool parameters.
>>>  161:
>>>  162:     Args:
>>>  163:         params: Tool parameters as dict. If you have a JSON string,
>>>  164:                 deserialize it first: parse_tool_params(json.loads(json_str))
>>>  165:
>>>  166:     Returns:
>>>  167:         Validated parameter dict.
>>>  168:     """
>>>  169:     return TypeAdapter(dict[str, Any]).validate_python(params)
     170:
     171:
     172: def parse_tools_list(tools: Any) -> list[dict[str, Any]]:
     173:     """Parse a list of tools into validated dicts.
     174:
```

### `unnecessary-wrapper-functions.yaml` / `occ-1`

File: `adgn/src/adgn/agent/agent.py`

> Trivial wrapper functions that add no abstraction value. Only create wrapper
> functions when they add real abstraction (combine multiple operations),
> provide domain-specific naming clarity, or encapsulate complex logic.
>
> **Note:** \_normalize_call_arguments accepts dict[str, Any] | str | None but dict case never occurs; defensive check for
> impossible case

```
     144:
     145: def _abort_result(reason: str | None = None) -> CallToolResult:
     146:     return _make_error_result(reason or DEFAULT_ABORT_ERROR)
     147:
     148:
>>>  149: def _normalize_call_arguments(arguments: dict[str, Any] | str | None) -> str | None:
>>>  150:     """Normalize function call arguments to JSON string.
>>>  151:
>>>  152:     Args:
>>>  153:         arguments: Structured data (dict), pre-serialized JSON string, or None.
>>>  154:
>>>  155:     Returns:
>>>  156:         JSON string representation or None if arguments is None.
>>>  157:     """
>>>  158:     if arguments is None or isinstance(arguments, str):
>>>  159:         return arguments
>>>  160:     return json.dumps(arguments)
     161:
     162:
     163: def _call_tool_result_from_json(output: str) -> CallToolResult:
     164:     """Parse CallToolResult from JSON using Pydantic for validation.
     165:
   ...
     264:             raise
     265:
     266:     async def _handle_pending_tool_calls(self) -> None:
     267:         function_calls: list[FunctionCallItem] = list(self.pending_function_calls)
     268:         calls: list[tuple[FunctionCallItem, str | None]] = [
>>>  269:             (function_call, _normalize_call_arguments(function_call.arguments)) for function_call in function_calls
     270:         ]
     271:
     272:         local_result_map: dict[str, CallToolResult] = {
     273:             evt.call_id: evt.result for evt in self._transcript if isinstance(evt, ToolCallOutput)
     274:         }
```

### `yaml-loader-falsy-coercion.yaml` / `occ-0`

File: `adgn/src/adgn/agent/presets.py`

> \_load_yaml coerces any falsy YAML payload to {} before the type check (line 35:
> `data = yaml.safe_load(f) or {}`). This means non-mapping presets like [], 0, false, or None
> are silently treated as empty mappings, bypassing the isinstance(data, dict) check on line 36
> that should raise "preset must be a mapping". The `or {}` should be removed - let yaml.safe_load
> return whatever it returns, and let the isinstance check fail naturally for non-dict values.
> This hides malformed presets and causes downstream validation errors instead of clear early
> failures.

```
      30:     modified_at: str | None = Field(None, description="Last modification time (ISO-8601 string)")
      31:
      32:
      33: def _load_yaml(path: Path) -> dict[str, JsonValue]:
      34:     with path.open("r", encoding="utf-8") as f:
>>>   35:         data = yaml.safe_load(f) or {}
      36:     if not isinstance(data, dict):
      37:         raise ValueError(f"preset must be a mapping: {path}")
      38:     return cast(dict[str, JsonValue], data)
      39:
      40:
```

## ducktape/2025-12-04-00 (30)

### `cast-may-be-unnecessary.yaml` / `occ-0`

File: `adgn/src/adgn/props/grader/models.py`

> Line 307 uses cast(GradeValidationContext, ctx) after already checking isinstance.
> After the isinstance check on line 305, mypy should already know the type.
> The cast may be unnecessary redundancy.

```
     302:             return None
     303:         ctx = info.context.get("grade_validation_context")
     304:         if ctx is None or not isinstance(ctx, GradeValidationContext):
     305:             return None
     306:         return cast(GradeValidationContext, ctx)
>>>  307:
     308:     @property
     309:     def _mentioned_tp_ids(self) -> set[InputIssueID]:
     310:         """Input IDs mentioned in canonical TP coverage."""
     311:         return set().union(*(cov.covered_by.keys() for cov in self.canonical_tp_coverage.values()))
     312:
```

### `dead-code.yaml` / `occ-7`

File: `adgn/src/adgn/openai_utils/model.py`

> Dead code that should be removed. These are definitions with zero call sites,
> commented-out code, or infrastructure left over from migrations.
>
> **Note:** Dead `responses` property providing unused .responses.create() interface

```
     343:
     344: @dataclass
     345: class OpenAIModel:
     346:     client: AsyncOpenAI
     347:
>>>  348:     @property
>>>  349:     def responses(self):  # Pydantic-only surface: .responses.create(ResponsesRequest)
>>>  350:         outer = self
>>>  351:
>>>  352:         class _Compat:
>>>  353:             async def create(self, req: ResponsesRequest) -> ResponsesResult:
>>>  354:                 result = await outer.responses_create(req)
>>>  355:                 return cast(ResponsesResult, result)
>>>  356:
>>>  357:         return _Compat()
     358:
     359:     async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
     360:         """Create a Responses completion (non-streaming) and convert to our types."""
     361:         if not isinstance(req, ResponsesRequest):
     362:             raise TypeError("responses_create expects a ResponsesRequest instance")
```

### `dead-code.yaml` / `occ-8`

File: `adgn/src/adgn/openai_utils/model.py`

> Dead code that should be removed. These are definitions with zero call sites,
> commented-out code, or infrastructure left over from migrations.
>
> **Note:** Dead \_coerce_text validator in AssistantMessageOut - coercion logic never triggered

```
     213:
     214:     kind: Literal["assistant_message"] = "assistant_message"
     215:     parts: list[OutputText]
     216:     model_config = ConfigDict(extra="allow")
     217:
>>>  218:     @model_validator(mode="before")
>>>  219:     @classmethod
>>>  220:     def _coerce_text(cls, data: str | dict[str, Any]) -> dict[str, Any]:
>>>  221:         if isinstance(data, str):
>>>  222:             return {"parts": [{"text": data}]}
>>>  223:         if isinstance(data, dict) and "parts" not in data:
>>>  224:             text = data.get("text")
>>>  225:             if isinstance(text, str):
>>>  226:                 new_data = dict(data)
>>>  227:                 new_data.pop("text", None)
>>>  228:                 new_data["parts"] = [{"text": text}]
>>>  229:                 return new_data
>>>  230:         return data
     231:
     232:     @property
     233:     def text(self) -> str:
     234:         return "\n".join(part.text for part in self.parts if part.text)
     235:
```

### `dead-constants-runs-context.yaml` / `occ-0`

File: `adgn/src/adgn/props/runs_context.py`

> Lines 15-19 define five constants (RUN_TYPE_CRITIC, RUN_TYPE_GRADER, INPUT_JSON, OUTPUT_JSON, EVENTS_JSONL)
> that are
> never imported or used anywhere in the codebase. The module's stated purpose is to be "the single source of
> truth for
> all runs-related path construction" and its docstring explicitly says "No path tokens ('grader',
> 'output.json', etc.)
> should be hardcoded outside this module."
>
> However, these constants are being unused/ignored and the some strings are hardcoded elsewhere instead:
>
> - "events.jsonl" hardcoded in cluster_unknowns.py:111, cli_app/shared.py:60, cli_app/main.py:536,
>   lint_issue.py:
> - [430, 430]
>   Either these constants should be used to replace the hardcoded strings, or they should be deleted as dead
>   code. The
>   module's purpose is being violated by not using these centralized constants.

```
      10: from pathlib import Path
      11:
      12: from adgn.props.prop_utils import pkg_dir
      13:
      14: # Path token constants - single source of truth
>>>   15: RUN_TYPE_CRITIC = "critic"
>>>   16: RUN_TYPE_GRADER = "grader"
>>>   17: INPUT_JSON = "input.json"
>>>   18: OUTPUT_JSON = "output.json"
>>>   19: EVENTS_JSONL = "events.jsonl"
      20:
      21:
      22: def format_timestamp_session(dt: datetime | None = None) -> str:
      23:     """Standard timestamp format for session/output directories: YYYYMMDD_HHMMSS.
      24:
```

### `duplicate-exit-code-constants.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/_shared/constants.py`

> Exit code constants (SIGNAL_EXIT_OFFSET, signal_exit_code(), EXIT_CODE_SIGTERM,
> EXIT_CODE_SIGKILL) are duplicated in both \_shared/constants.py and exec/models.py
> with identical definitions.
>
> This creates a maintenance burden and risks divergence. Since these constants are
> tightly coupled to the exec implementation and primarily used there, they should
> be defined in exec/models.py only.
>
> Resolution: Remove the duplicates from \_shared/constants.py and update
> container_session.py to import from exec/models.py instead.
>
> **Note:** First definition in shared constants

```
      13:
      14: # Canonical server/tool names for the agent runtime Docker MCP server
      15: RUNTIME_SERVER_NAME: Final[str] = "runtime"
      16: RUNTIME_EXEC_TOOL_NAME: Final[str] = "exec"
      17: RUNTIME_CONTAINER_INFO_URI: Final[str] = "resource://container.info"
>>>   18:
>>>   19: SIGNAL_EXIT_OFFSET: Final[int] = 128
>>>   20:
>>>   21:
>>>   22: def signal_exit_code(sig: int) -> int:
>>>   23:     return SIGNAL_EXIT_OFFSET + int(sig)
>>>   24:
>>>   25:
>>>   26: EXIT_CODE_SIGTERM: Final[int] = signal_exit_code(SIGTERM)
>>>   27: EXIT_CODE_SIGKILL: Final[int] = signal_exit_code(SIGKILL)
      28:
      29: # Common server names
      30: CRITIC_SUBMIT_SERVER_NAME: Final[str] = "critic_submit"
      31: MATRIX_CONTROL_SERVER_NAME: Final[str] = "matrix_control"
      32: UI_SERVER_NAME: Final[str] = "ui"
```

### `duplicate-exit-code-constants.yaml` / `occ-1`

File: `adgn/src/adgn/mcp/exec/models.py`

> Exit code constants (SIGNAL_EXIT_OFFSET, signal_exit_code(), EXIT_CODE_SIGTERM,
> EXIT_CODE_SIGKILL) are duplicated in both \_shared/constants.py and exec/models.py
> with identical definitions.
>
> This creates a maintenance burden and risks divergence. Since these constants are
> tightly coupled to the exec implementation and primarily used there, they should
> be defined in exec/models.py only.
>
> Resolution: Remove the duplicates from \_shared/constants.py and update
> container_session.py to import from exec/models.py instead.
>
> **Note:** Duplicate definition in exec/models

```
       9: import time
      10: from typing import Annotated, Final, Literal
      11:
      12: from pydantic import BaseModel, ConfigDict, Field
      13:
>>>   14: # Signal exit codes for process termination
>>>   15: SIGNAL_EXIT_OFFSET: Final[int] = 128
>>>   16:
>>>   17:
>>>   18: def signal_exit_code(sig: int) -> int:
>>>   19:     return SIGNAL_EXIT_OFFSET + int(sig)
      20:
      21:
      22: def perf_timer() -> float:
      23:     """Get current performance counter time."""
      24:     return time.perf_counter()
   ...
      50:         return round((loop.time() - start_time) * 1000)
      51:
      52:     yield get_duration_ms
      53:
      54:
>>>   55: EXIT_CODE_SIGTERM: Final[int] = signal_exit_code(SIGTERM)
>>>   56: EXIT_CODE_SIGKILL: Final[int] = signal_exit_code(SIGKILL)
      57:
      58: # Cap for stdout/stderr/stdin bytes in exec-like servers
      59: MAX_BYTES_CAP = 100_000
      60:
      61: # Cap for execution timeout across exec-like servers (milliseconds)
```

### `manual-snapshot-yaml-update.yaml` / `occ-0`

File: `adgn/src/adgn/props/cli_app/cmd_build_bundle.py`

> The `cmd_build_bundle` function (lines 335-363) uses pygit2 to create filtered
> commits and tags for snapshot bundles, but doesn't return the mapping of tag names
> to commit SHAs that it creates. The function has no return value.
>
> This forces callers to either:
>
> 1. Write placeholder commit SHAs and manually update them later
> 2. Query the bundle post-hoc using `git bundle list-heads`
>
> The function calls `_build_bundle_internal` which creates the commits and tags.
> That commit information should be captured and returned to callers for automatic
> snapshots.yaml updates.

```
     330:         if not p.exists() or not p.is_dir():
     331:             raise FileNotFoundError(f"Specimens directory not found in package resources: {p}")
     332:         return p
     333:
     334:
>>>  335: def cmd_build_bundle(
>>>  336:     specimens_dir: Path | None = None, source_repo_path: Path | None = None, output_bundle: Path | None = None
>>>  337: ):
>>>  338:     """Build snapshot bundle with per-snapshot filters.
>>>  339:
>>>  340:     Args:
>>>  341:         specimens_dir: Base directory containing snapshots.yaml and snapshot subdirs (default: from package resources)
>>>  342:         source_repo_path: Path to source git repository (default: auto-discovered from current directory)
>>>  343:         output_bundle: Output path for bundle file (default: specimens_dir/ducktape/snapshots.bundle)
>>>  344:
>>>  345:     Note: The default output path matches the relative URL in snapshots.yaml (file://../snapshots.bundle
>>>  346:     resolved from specimens/ducktape/{snapshot}/ directories).
>>>  347:     """
>>>  348:     # Use defaults if not provided
>>>  349:     if specimens_dir is None:
>>>  350:         specimens_dir = get_specimens_dir()
>>>  351:     if source_repo_path is None:
>>>  352:         # Discover repository from current directory
>>>  353:         discovered = pygit2.discover_repository(".")
>>>  354:         if not discovered:
>>>  355:             raise RuntimeError("Could not find git repository. Run from within ducktape repo.")
>>>  356:         # pygit2.discover_repository returns path to .git directory, get parent
>>>  357:         source_repo_path = Path(discovered).parent if discovered.endswith("/.git/") else Path(discovered).parent.parent
>>>  358:     if output_bundle is None:
>>>  359:         # Default to specimens/ducktape/snapshots.bundle to match snapshots.yaml URLs
>>>  360:         output_bundle = specimens_dir / "ducktape" / "snapshots.bundle"
>>>  361:
>>>  362:     # Call internal implementation
>>>  363:     _build_bundle_internal(specimens_dir, source_repo_path, output_bundle)
```

### `missing-docker-cpu-limit.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/_shared/container_session.py`

> Docker containers created by ContainerOptions and \_build_host_config() do not
> specify CPU limits. While the containers are otherwise well-isolated, it would be
> healthy to set explicit CPU constraints to prevent a single container from
> monopolizing CPU resources.
>
> Setting CPU limits helps:
>
> - Ensure fair resource sharing when multiple containers run concurrently
> - Make performance characteristics more predictable
> - Prevent accidental CPU exhaustion from runaway processes
>
> Docker supports NanoCpus (fractional CPUs, e.g., 1.5 CPUs = 1500000000 nanocpus)
> and CpuQuota/CpuPeriod in HostConfig. A reasonable default could be 2 CPUs for
> agent runtime containers and 1 CPU for critics/graders.
>
> Example addition to \_build_host_config():
> host_config["NanoCpus"] = opts.nano_cpus or (2 \* 1_000_000_000) # 2 CPUs default

```
      94:
      95: def _session_state_from_ctx(ctx: Any) -> ContainerSessionState:
      96:     return cast(ContainerSessionState, ctx.request_context.lifespan_context)
      97:
      98:
>>>   99: def _build_host_config(opts: ContainerOptions, *, auto_remove: bool = False) -> dict[str, Any]:
>>>  100:     """Build Docker HostConfig from ContainerOptions.
>>>  101:
>>>  102:     Args:
>>>  103:         opts: Container options with volumes and network_mode
>>>  104:         auto_remove: Whether to set AutoRemove (for per-session containers)
>>>  105:
>>>  106:     Returns:
>>>  107:         Docker HostConfig dict with Binds and NetworkMode if applicable
>>>  108:     """
>>>  109:     host_config: dict[str, Any] = {}
>>>  110:
>>>  111:     if auto_remove:
>>>  112:         host_config["AutoRemove"] = True
>>>  113:
>>>  114:     # Convert volumes to binds format
>>>  115:     if opts.volumes and isinstance(opts.volumes, dict):
>>>  116:         binds = []
>>>  117:         for host_path, volume_config in opts.volumes.items():
>>>  118:             bind = f"{host_path}:{volume_config['bind']}"
>>>  119:             if mode := volume_config.get("mode"):
>>>  120:                 bind += f":{mode}"
>>>  121:             binds.append(bind)
>>>  122:         if binds:
>>>  123:             host_config["Binds"] = binds
>>>  124:
>>>  125:     # Apply network mode if not 'none'
>>>  126:     if opts.network_mode != "none":
>>>  127:         host_config["NetworkMode"] = opts.network_mode
>>>  128:
>>>  129:     return host_config
     130:
     131:
     132: async def _start_container(*, client: aiodocker.Docker, opts: ContainerOptions) -> dict[str, Any]:
     133:     container_config = opts.to_container_config(cmd=SLEEP_FOREVER_CMD, auto_remove=True)
     134:
   ...
      47:
      48: def _shell_join(cmd: Iterable[str]) -> str:
      49:     return shlex.join(list(cmd))
      50:
      51:
>>>   52: @dataclass
>>>   53: class ContainerOptions:
>>>   54:     image: str
>>>   55:     working_dir: Path = WORKING_DIR
>>>   56:     volumes: dict[str, dict[str, str]] | list[str] | None = None
>>>   57:     network_mode: str = "none"
>>>   58:     environment: dict[str, str] | None = None
>>>   59:     labels: dict[str, str] | None = None
>>>   60:     describe: bool = True
>>>   61:     ephemeral: bool = False
      62:
      63:     def to_container_config(
      64:         self,
      65:         *,
      66:         cmd: list[str],
```

### `missing-docker-memory-limit.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/_shared/container_session.py`

> Docker containers created by ContainerOptions and \_build_host_config() do not
> specify memory limits. While containers are isolated by network mode ("none") and
> read-only volumes, it would be healthier to set explicit memory constraints.
>
> Setting memory limits helps:
>
> - Prevent runaway processes from affecting host stability
> - Make resource usage predictable and debuggable
> - Align with containerization best practices
>
> Docker supports Memory (hard limit) and MemoryReservation (soft limit) in HostConfig.
> A reasonable default could be 2-4GB for agent runtime containers and 1-2GB for
> critics/graders, with the option to override per use case.
>
> Example addition to \_build*host_config():
> host_config["Memory"] = opts.mem_limit or (2 * 1024 \_ 1024 \* 1024) # 2GB default

```
      94:
      95: def _session_state_from_ctx(ctx: Any) -> ContainerSessionState:
      96:     return cast(ContainerSessionState, ctx.request_context.lifespan_context)
      97:
      98:
>>>   99: def _build_host_config(opts: ContainerOptions, *, auto_remove: bool = False) -> dict[str, Any]:
>>>  100:     """Build Docker HostConfig from ContainerOptions.
>>>  101:
>>>  102:     Args:
>>>  103:         opts: Container options with volumes and network_mode
>>>  104:         auto_remove: Whether to set AutoRemove (for per-session containers)
>>>  105:
>>>  106:     Returns:
>>>  107:         Docker HostConfig dict with Binds and NetworkMode if applicable
>>>  108:     """
>>>  109:     host_config: dict[str, Any] = {}
>>>  110:
>>>  111:     if auto_remove:
>>>  112:         host_config["AutoRemove"] = True
>>>  113:
>>>  114:     # Convert volumes to binds format
>>>  115:     if opts.volumes and isinstance(opts.volumes, dict):
>>>  116:         binds = []
>>>  117:         for host_path, volume_config in opts.volumes.items():
>>>  118:             bind = f"{host_path}:{volume_config['bind']}"
>>>  119:             if mode := volume_config.get("mode"):
>>>  120:                 bind += f":{mode}"
>>>  121:             binds.append(bind)
>>>  122:         if binds:
>>>  123:             host_config["Binds"] = binds
>>>  124:
>>>  125:     # Apply network mode if not 'none'
>>>  126:     if opts.network_mode != "none":
>>>  127:         host_config["NetworkMode"] = opts.network_mode
>>>  128:
>>>  129:     return host_config
     130:
     131:
     132: async def _start_container(*, client: aiodocker.Docker, opts: ContainerOptions) -> dict[str, Any]:
     133:     container_config = opts.to_container_config(cmd=SLEEP_FOREVER_CMD, auto_remove=True)
     134:
   ...
      47:
      48: def _shell_join(cmd: Iterable[str]) -> str:
      49:     return shlex.join(list(cmd))
      50:
      51:
>>>   52: @dataclass
>>>   53: class ContainerOptions:
>>>   54:     image: str
>>>   55:     working_dir: Path = WORKING_DIR
>>>   56:     volumes: dict[str, dict[str, str]] | list[str] | None = None
>>>   57:     network_mode: str = "none"
>>>   58:     environment: dict[str, str] | None = None
>>>   59:     labels: dict[str, str] | None = None
>>>   60:     describe: bool = True
>>>   61:     ephemeral: bool = False
      62:
      63:     def to_container_config(
      64:         self,
      65:         *,
      66:         cmd: list[str],
```

### `mkdir-in-wrong-location.yaml` / `occ-0`

File: `adgn/src/adgn/agent/transcript_handler.py`

> Lines 36-37 in transcript_handler.py create the parent directory in `__init__`, which performs I/O
> during object construction. The comment on line 36 ("Create parent directory if needed") and the mkdir
> operation should be moved to `_write_event()` where the file is actually written. This follows the
> principle of lazy initialization and reduces work done during object construction. The mkdir call can
> be performed once before the first write operation.

```
      31:       MiniCodex.create(..., handlers=[h, ...])
      32:     """
      33:
      34:     def __init__(self, *, events_path: Path) -> None:
      35:         self._events_path = events_path
>>>   36:         # Create parent directory if needed
>>>   37:         self._events_path.parent.mkdir(parents=True, exist_ok=True)
      38:         # Fail fast if a transcript already exists at destination
      39:         if self._events_path.exists():
      40:             raise FileExistsError(f"Transcript already exists: {self._events_path}")
      41:
      42:     # ---- Event helpers ----
```

### `nullable-with-defaults.yaml` / `occ-0`

File: `adgn/src/adgn/props/cli_app/cmd_build_bundle.py`

> The apply_gitignore_patterns function accepts include and exclude as list[str] | None,
> then checks "if include:" and "if exclude:" at lines 37-42. These parameters should
> instead be Sequence[str] with default=() in the function signature, eliminating the
> need for None checks. This makes the contract clearer and reduces defensive code.

```
      13: import yaml
      14:
      15: from adgn.props.models.snapshot import GitSource, SnapshotDoc
      16:
      17:
>>>   18: def apply_gitignore_patterns(file_list: list[str], include: list[str] | None, exclude: list[str] | None) -> list[str]:
>>>   19:     """Apply gitignore-style include/exclude patterns to a file list.
>>>   20:
>>>   21:     Include patterns are applied first (whitelist), then exclude patterns (blacklist).
>>>   22:     """
>>>   23:
>>>   24:     def matches_pattern(path: str, pattern: str) -> bool:
>>>   25:         """Check if path matches gitignore-style pattern."""
>>>   26:         # Remove trailing slash from pattern (indicates directory)
>>>   27:         if pattern.endswith("/"):
>>>   28:             pattern = pattern.rstrip("/")
>>>   29:             # For directory patterns, match the directory and everything under it
>>>   30:             return path.startswith(pattern + "/") or path == pattern
>>>   31:         # For file patterns, use fnmatch
>>>   32:         return fnmatch.fnmatch(path, pattern) or path.startswith(pattern + "/")
>>>   33:
>>>   34:     result = file_list
>>>   35:
>>>   36:     # Apply include patterns (if specified, only keep matching files)
>>>   37:     if include:
>>>   38:         result = [f for f in result if any(matches_pattern(f, pattern) for pattern in include)]
>>>   39:
>>>   40:     # Apply exclude patterns (remove matching files)
>>>   41:     if exclude:
>>>   42:         result = [f for f in result if not any(matches_pattern(f, pattern) for pattern in exclude)]
>>>   43:
>>>   44:     return result
      45:
      46:
      47: def get_tree_files(repo: pygit2.Repository, tree: pygit2.Tree, prefix: str = "") -> dict[str, tuple[pygit2.Oid, int]]:
      48:     """Get all files in a tree recursively as path -> (oid, filemode) mappings."""
      49:     files: dict[str, tuple[pygit2.Oid, int]] = {}
```

### `openai-utils-bypass-reasoning-params.yaml` / `occ-0`

File: `adgn/src/adgn/openai_utils/model.py`

> Lines 390-391 in `BoundOpenAIModel.responses_create()` manually construct the reasoning dict:
>
> ```python
> if self.reasoning_effort and "reasoning" not in kwargs:
>     kwargs["reasoning"] = {"effort": self.reasoning_effort.value}
> ```
>
> This bypasses the existing type-safe `ReasoningParams` TypedDict (defined in `openai_utils/types.py`) and
> duplicates
> conversion logic that already exists.
>
> The codebase already has:
>
> - `ReasoningParams` TypedDict with `effort` and `summary` fields (types.py)
> - `ResponsesRequest.reasoning: ReasoningParams | None` field (line 178)
> - `build_reasoning_params()` helper function for constructing ReasoningParams (types.py)
> - `to_kwargs()` which calls `model_dump()` and would automatically serialize ReasoningParams
>
> The manual dict construction is redundant and type-unsafe. Instead, `BoundOpenAIModel` should either:
>
> 1. Construct a proper `ReasoningParams` object and inject it into the request before calling `to_kwargs()`, OR
> 2. Let callers pass the reasoning params in the ResponsesRequest (which already has the field)
>
> Manual dict manipulation after `to_kwargs()` bypasses the type system and creates maintenance burden.

```
     385:
     386:     async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
     387:         kwargs = req.to_kwargs()
     388:         # Enforce bound-model contract: always use the instance's model
     389:         kwargs["model"] = self.model
>>>  390:         if self.reasoning_effort and "reasoning" not in kwargs:
>>>  391:             kwargs["reasoning"] = {"effort": self.reasoning_effort.value}
     392:         sdk_resp: Response = await self.client.responses.create(**kwargs)
     393:         return ResponsesResult.from_sdk(sdk_resp)
     394:
     395:
     396: # ---------------------------------------------
   ...
     173:     tools: list[FunctionToolParam] | None = None
     174:     tool_choice: ToolChoice | None = None
     175:     parallel_tool_calls: bool | None = None
     176:     stream: bool = False
     177:     store: bool | None = None
>>>  178:     reasoning: ReasoningParams | None = None
     179:     max_output_tokens: int | None = None
     180:
     181:     # Allow unknown fields for forward-compat (timeouts, metadata, etc.)
     182:     model_config = ConfigDict(extra="allow")
     183:
```

### `openai-utils-redundant-singledispatch.yaml` / `occ-0`

File: `adgn/src/adgn/openai_utils/model.py`

> Lines 261-273 contain three redundant `@singledispatch` registered functions that are identical - they all
> just return
> `item` unchanged with the same comment "No conversion needed, X is already an InputItem".
>
> Current pattern (duplicated 3 times):
>
> ```python
> @response_out_item_to_input.register
> def _(item: ReasoningItem) -> InputItem:
>     return item  # No conversion needed, ReasoningItem is already an InputItem
>
> @response_out_item_to_input.register
> def _(item: FunctionCallItem) -> InputItem:
>     return item  # No conversion needed, FunctionCallItem is already an InputItem
>
> @response_out_item_to_input.register
> def _(item: FunctionCallOutputItem) -> InputItem:
>     return item  # No conversion needed, FunctionCallOutputItem is already an InputItem
> ```
>
> While `@singledispatch.register` doesn't support Union types like `item: (ReasoningItem | FunctionCallItem |
...)`,
> you
> CAN register the same function for multiple types to avoid duplication:
>
> ```python
> def _identity(item: InputItem) -> InputItem:
>     return item
>
> response_out_item_to_input.register(ReasoningItem)(_identity)
> response_out_item_to_input.register(FunctionCallItem)(_identity)
> response_out_item_to_input.register(FunctionCallOutputItem)(_identity)
> ```
>
> Or in a loop:
>
> ```python
> _identity_types = [ReasoningItem, FunctionCallItem, FunctionCallOutputItem]
> for typ in _identity_types:
>     response_out_item_to_input.register(typ)(lambda item: item)
> ```
>
> This eliminates the redundant function definitions while maintaining the same dispatch behavior.

```
     256: @singledispatch
     257: def response_out_item_to_input(item: BaseModel) -> InputItem:
     258:     raise TypeError(f"Unsupported response item type: {type(item)!r}")
     259:
     260:
>>>  261: @response_out_item_to_input.register
>>>  262: def _(item: ReasoningItem) -> InputItem:
>>>  263:     return item  # No conversion needed, ReasoningItem is already an InputItem
>>>  264:
>>>  265:
>>>  266: @response_out_item_to_input.register
>>>  267: def _(item: FunctionCallItem) -> InputItem:
>>>  268:     return item  # No conversion needed, FunctionCallItem is already an InputItem
>>>  269:
>>>  270:
>>>  271: @response_out_item_to_input.register
>>>  272: def _(item: FunctionCallOutputItem) -> InputItem:
>>>  273:     return item  # No conversion needed, FunctionCallOutputItem is already an InputItem
     274:
     275:
     276: @response_out_item_to_input.register
     277: def _(item: AssistantMessageOut) -> InputItem:
     278:     return item.to_input_item()
```

### `openai-utils-silent-error-skip.yaml` / `occ-0`

File: `adgn/src/adgn/openai_utils/model.py`

> The `_message_output_to_assistant` function (lines 281-294) returns `AssistantMessageOut | None`, and when it
> returns
> None (lines 292-293), the caller (lines 330-332) silently skips adding the item to `out_items`.
>
> This is dangerous for two reasons:
>
> 1. **OpenAI reasoning sensitivity**: OpenAI's reasoning feature is sensitive to being placed in exactly the
>    same
>    prefix it was sampled from. Silently dropping messages breaks this invariant and can cause subtle bugs.
> 2. **Silent error hiding**: If `_message_output_to_assistant` returns None because something went wrong (no
>    parts
>    found), this should be treated as an error that surfaces immediately, not silently ignored.
>
> The function should be changed to either:
>
> - Return a non-nullable `AssistantMessageOut` and raise an exception when parts is empty, OR
> - Have the caller raise an exception when None is returned instead of silently skipping
>
> Errors must cause breakage/raise, not be silently skipped.

```
     276: @response_out_item_to_input.register
     277: def _(item: AssistantMessageOut) -> InputItem:
     278:     return item.to_input_item()
     279:
     280:
>>>  281: def _message_output_to_assistant(message: ResponseOutputMessage) -> AssistantMessageOut | None:
     282:     parts: list[OutputText] = []
     283:     for content_item in message.content:
     284:         if isinstance(content_item, ResponseOutputText):
     285:             part = OutputText(
     286:                 text=content_item.text,
   ...
     287:                 annotations=[annotation.model_dump(exclude_none=True) for annotation in content_item.annotations]
     288:                 if content_item.annotations
     289:                 else None,
     290:             )
     291:             parts.append(part)
>>>  292:     if not parts:
>>>  293:         return None
     294:     return AssistantMessageOut(parts=parts)
     295:
     296:
     297: # Removed legacy aliases; use AssistantMessageOut and OutputText explicitly
     298:
   ...
     325:                         id=item.id,
     326:                         status=item.status,
     327:                     )
     328:                 )
     329:             elif isinstance(item, ResponseOutputMessage):
>>>  330:                 converted = _message_output_to_assistant(item)
>>>  331:                 if converted is not None:
>>>  332:                     out_items.append(converted)
     333:             else:
     334:                 raise NotImplementedError(f"Unsupported output item type: {type(item)}")
     335:         usage = ResponseUsage.from_sdk(sdk_resp.usage) if sdk_resp.usage else None
     336:         return cls(id=sdk_resp.id, usage=usage, output=out_items)
     337:
```

### `redundant-checks.yaml` / `occ-0`

File: `adgn/src/adgn/props/cli_app/cmd_build_bundle.py`

> Redundant checks and guards that serve no purpose and can be removed. These include checking the same
> condition twice,
> redundant None checks with isinstance, and redundant type validation.
>
> **Note:** Checks for bundle metadata twice - first at line 226 with dict.get(), then at line 233 with validated model

```
     219:
     220:     with snapshots_yaml.open() as f:
     221:         snapshots_data = yaml.safe_load(f) or {}
     222:
     223:     results = []
>>>  224:     for slug, snapshot_data in snapshots_data.items():
>>>  225:         # Skip snapshots without bundle metadata
>>>  226:         if not snapshot_data.get("bundle"):
>>>  227:             continue
>>>  228:
>>>  229:         # Parse and validate the snapshot doc (let validation errors propagate)
>>>  230:         snapshot = TypeAdapter(SnapshotDoc).validate_python(snapshot_data)
>>>  231:
>>>  232:         # Only include snapshots with complete bundle metadata
>>>  233:         if snapshot.bundle is not None:
>>>  234:             results.append((slug, snapshot))
>>>  235:
     236:     return results
     237:
     238:
     239: def _build_bundle_internal(specimens_dir: Path, source_repo_path: Path, output_bundle: Path) -> None:
     240:     """Internal bundle building implementation.
```

### `redundant-checks.yaml` / `occ-2`

File: `adgn/src/adgn/agent/agent.py`

> Redundant checks and guards that serve no purpose and can be removed. These include checking the same
> condition twice,
> redundant None checks with isinstance, and redundant type validation.
>
> **Note:** Redundant isinstance check: "if not isinstance(call_id, str) or not call_id" - second condition is sufficient

```
      82:     was_aborted: bool = False
      83:
      84:
      85: def _require_call_id(function_call: FunctionCallItem) -> str:
      86:     call_id = function_call.call_id
>>>   87:     if not isinstance(call_id, str) or not call_id:
      88:         raise RuntimeError("FunctionCallItem missing call_id")
      89:     return call_id
      90:
      91:
      92: def _dump_call_tool_result(res: mcp_types.CallToolResult) -> str:
```

### `redundant-compositor-names.yaml` / `occ-0`

File: `adgn/tests/conftest.py`

> Multiple places instantiate `Compositor` with explicit name arguments (e.g., `Compositor("test")`,
> `Compositor("comp")`), but these names serve no functional purpose in most cases.
>
> The `Compositor` class has a default name of `"compositor"` (server.py:134), so passing a name explicitly is
> redundant
> unless:
>
> 1. The compositor is being mounted inside another compositor (two-level pattern)
> 2. There's a specific need to distinguish compositors in logs/debugging
>
> **Why this is a problem:**
>
> - The explicit names don't affect behavior or functionality
> - They add visual noise and unnecessary parameters
> - They create inconsistency (different tests use different arbitrary names: "test", "comp", "compositor")
> - In test fixtures, the name is completely unused since compositors are not nested
>
> **Exception: Two-level compositor pattern**
> The `compositor_factory.py` case is special - it creates a "global" compositor that mounts an agents server.
> If this
> compositor itself can be mounted in another compositor, the name might be meaningful for debugging nested
> compositor
> structures. However, even there, the default name would likely suffice.
>
> **Fix:**
> Remove the explicit name argument and rely on the default: `Compositor()` instead of `Compositor("name")`.
>
> **Note:** Test fixtures using arbitrary "comp" name - name never referenced

```
      76:     # Ensure runtime/policy evaluation containers use a single image tag.
      77:     os.environ.setdefault("ADGN_RUNTIME_IMAGE", DEFAULT_RUNTIME_IMAGE)
      78:
      79:
      80: def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
>>>   81:     for item in items:
      82:         if item.get_closest_marker("requires_sandbox_exec") is not None:
      83:             item.add_marker(pytest.mark.macos)
      84:
      85:
      86: def pytest_runtest_setup(item: pytest.Item) -> None:
   ...
     350:
     351:
     352: @pytest.fixture
     353: async def pg_compositor_echo(echo_spec, make_pg_compositor):
     354:     """Async fixture with echo server and policy gateway.
>>>  355:
     356:     Yields (client, compositor, policy_engine).
     357:     """
     358:     async with make_pg_compositor(echo_spec) as result:
     359:         yield result
     360:
   ...
     374:     """Async helper to open a Compositor + Client with NotificationsBuffer.
     375:
     376:     Yields (client, compositor, buffer) so tests can read buffered notifications
     377:     or pass buffer.poll into handlers.
     378:     """
>>>  379:
     380:     @asynccontextmanager
     381:     async def _open(servers: McpServerSpecs):
     382:         comp = Compositor("comp")
     383:         await _mount_servers(comp, servers)
     384:         buf = NotificationsBuffer(compositor=comp)
   ...
     406: @pytest.fixture
     407: def live_openai(request):
     408:     """Provide a live AsyncOpenAI client for tests marked with `live_llm`.
     409:
     410:     - For non-`live_llm` tests that include this fixture in the signature but
>>>  411:       do not actually use it (e.g., parameterized tests with a mock branch),
     412:       return a lightweight no-op placeholder to avoid network work and keep
     413:       those tests running.
     414:     - For `live_llm` tests, require OPENAI_API_KEY and construct AsyncOpenAI;
     415:       skip if the key is not available.
     416:     """
   ...
     468:     """
     469:
     470:     def _make(decision: ApprovalDecision) -> PolicyEngine:
     471:         policy_source = make_policy_source(decision)
     472:         return make_approval_policy_server(policy_source)
>>>  473:
     474:     return _make
     475:
     476:
     477: @pytest.fixture
     478: async def approval_policy_reader_allow_all(sqlite_persistence, docker_client) -> FastMCP:
```

### `redundant-path-construction.yaml` / `occ-0`

File: `adgn/src/adgn/inop/engine/models.py`

> Line 380 converts self.workspace_path (str) to Path, but this field should already be typed as Path at the
> class
> definition level. The conversion is redundant if the model properly validates the field type on construction.

```
     375:
     376:         Returns:
     377:             Dictionary mapping relative file paths to contents
     378:         """
     379:         files: dict[str, str] = {}
>>>  380:         directory_path = Path(self.workspace_path)
     381:
     382:         if not directory_path.exists():
     383:             return files
     384:
     385:         for root, _, filenames in os.walk(self.workspace_path):
```

### `redundant-pydantic-type-param.yaml` / `occ-0`

File: `adgn/src/adgn/agent/agent.py`

> Line 133 in agent.py explicitly sets `type="text"` when constructing a TextContent object:
> `mcp_types.TextContent(type="text", text=message)`. This parameter is redundant if "text" is the
> default value for the type discriminator field. The construction should omit the type parameter
> unless it's required by the Pydantic model definition (i.e., has no default).

```
     128:             raise NotImplementedError(f"Unsupported CallToolResult content type: {type(block).__name__}")
     129:     return None
     130:
     131:
     132: def _make_error_result(message: str) -> mcp_types.CallToolResult:
>>>  133:     return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=message)], isError=True)
     134:
     135:
     136: DEFAULT_ABORT_ERROR = "tool execution aborted"
     137:
     138:
```

### `redundant-snapshot-hydration.yaml` / `occ-0`

File: `adgn/src/adgn/props/gepa/gepa_adapter.py`

> GEPA optimization repeatedly hydrates the same snapshots, causing ~200 redundant tar extractions and file
> discoveries
> during a typical optimization run.
>
> **The inefficiency:**
>
> Dataset loading (`load_datasets()`, lines 308-334) hydrates each snapshot once to extract metadata, then
> closes the
> hydrated context:
>
> ```python
> async with registry.load_and_hydrate(slug) as hydrated:
>     return SnapshotInput(slug=slug, target_files=..., ...)
> # Hydrated snapshot deleted here when context exits
> ```
>
> During optimization, each evaluation re-hydrates from scratch (`_evaluate_one_specimen()`, line 195):
>
> ```python
> async def _evaluate_one_specimen(self, specimen_input: SnapshotInput, ...):
>     async with self.registry.load_and_hydrate(slug) as hydrated:
>         # Run critic with fresh hydration
> ```
>
> **Performance impact:**
>
> With 5-10 unique snapshots and max_metric_calls=200:
>
> - Initial loading: 5-10 hydrations (~5-10 seconds)
> - Optimization evaluations: ~200 hydrations (~200-400 seconds total)
> - Each hydration: tar extraction, JSON parsing, file discovery (~1-2 seconds)
> - Same snapshot hydrated 20-40 times throughout the run
>
> **Why this matters:**
>
> Snapshots are mounted read-only to Docker containers, so the hydrated directories could be reused safely. The
> issue is
> architectural:
>
> - `SnapshotInput` stores only metadata (slug, target_files list, ground truth issues)
> - `HydratedSnapshot` objects are created and destroyed per-evaluation
> - No mechanism to keep snapshots hydrated throughout the GEPA run
>
> **Potential fix:**
>
> Keep `HydratedSnapshot` objects alive throughout GEPA optimization:
>
> - Load and hydrate snapshots once at start
> - Pass `HydratedSnapshot` references through the evaluation pipeline (not just metadata)
> - Reuse the same hydrated directories for all critic/grader runs
> - Clean up only at the end of GEPA run
>
> This would reduce ~200 hydrations to ~10, saving 3-6 minutes per optimization run.

```
     303: # =============================================================================
     304: # Dataset Loading
     305: # =============================================================================
     306:
     307:
>>>  308: async def load_datasets(registry: SnapshotRegistry) -> tuple[list[SnapshotInput], list[SnapshotInput]]:
>>>  309:     """Load train and validation datasets for GEPA.
>>>  310:
>>>  311:     This function hydrates snapshots to discover target files and uses the registry's
>>>  312:     TruePositiveIssue and KnownFalsePositive formats which are compatible with the grader.
>>>  313:
>>>  314:     For source-of-truth data models, see TrainingExample and FilesystemLoader.
>>>  315:
>>>  316:     Returns:
>>>  317:         (trainset, valset) tuple of SnapshotInput lists
>>>  318:     """
>>>  319:     train_slugs = registry.get_snapshots_by_split(Split.TRAIN)
>>>  320:     valid_slugs = registry.get_snapshots_by_split(Split.VALID)
>>>  321:
>>>  322:     async def load_snapshot(slug: SnapshotSlug) -> SnapshotInput:
>>>  323:         async with registry.load_and_hydrate(slug) as hydrated:
>>>  324:             return SnapshotInput(
>>>  325:                 slug=slug,
>>>  326:                 target_files=hydrated.files_with_issues(),
>>>  327:                 known_true_positives=hydrated.true_positives,
>>>  328:                 known_false_positives=hydrated.false_positives,
>>>  329:             )
>>>  330:
>>>  331:     trainset = [await load_snapshot(slug) for slug in train_slugs]
>>>  332:     valset = [await load_snapshot(slug) for slug in valid_slugs]
>>>  333:
>>>  334:     return trainset, valset
     335:
     336:
     337: def load_training_examples(specimens_dir: Path | None = None) -> tuple[list[TrainingExample], list[TrainingExample]]:
     338:     """Load train and validation TrainingExamples from filesystem.
     339:
   ...
     190:     ) -> EvaluationResult:
     191:         """Evaluate a single specimen (for parallel execution)."""
     192:         slug = specimen_input.slug
     193:
     194:         # Run critic
>>>  195:         async with self.registry.load_and_hydrate(slug) as hydrated:
     196:             critic_input = CriticInput(snapshot_slug=slug, files=ALL_FILES_WITH_ISSUES, prompt_sha256=prompt_sha256)
     197:
     198:             critic_output, critic_run_id, critique_id = await run_critic(
     199:                 input_data=critic_input,
     200:                 client=self.client,
   ...
     251:         """Async implementation of evaluate - runs specimens in parallel."""
     252:         system_prompt = candidate["system_prompt"]
     253:         prompt_sha256 = hash_and_upsert_prompt(system_prompt)
     254:
     255:         # Run all specimens in parallel
>>>  256:         tasks = [self._evaluate_one_specimen(specimen_input, prompt_sha256, capture_traces) for specimen_input in batch]
     257:         results = await asyncio.gather(*tasks)
     258:
     259:         return list(results)
     260:
     261:     def make_reflective_dataset(
```

### `resources-list-missing-inproc-servers.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/resources/server.py`

> The resources server's `list_resources_tool` function (lines 343-368) only inspects servers mounted from
> specs,
> missing
> resources from inproc servers. This is a design inconsistency - tools are multiplexed across ALL servers (both
> spec-based and inproc), but the resources list only shows spec-based servers.
>
> **The bug:**
> Lines 348-349 use `compositor.mount_specs()` which only returns spec-based (external/HTTP) servers:
>
> ```python
> specs = await compositor.mount_specs()
> mount_names = list(specs.keys())
> ```
>
> This means resources from inproc servers (like `compositor_meta`, `resources` itself, policy servers, etc.)
> are
> silently
> filtered out when `derive_origin_server` raises `ValueError` on line 354 because their names aren't in
> `mount_names`.
>
> **Evidence of the correct pattern:**
> Lines 250-254 show the `_present_servers()` function using the correct approach with an explicit comment:
>
> ```python
> async def _present_servers() -> set[str]:
>     # Include all mounted servers, including in-proc mounts without typed specs.
>     # Use compositor._mount_names() directly; do not swallow errors.
>     names = await compositor._mount_names()
>     return set(names)
> ```
>
> **The fix:**
> Replace lines 348-349 with:
>
> ```python
> mount_names = await compositor._mount_names()
> ```
>
> This ensures resources from ALL mounted servers (both spec-based and inproc) are included in the list results,
> maintaining consistency with how tools are already multiplexed.
>
> **Impact:**
>
> - Agents currently cannot discover resources from inproc servers like compositor_meta (which exposes server
>   state,
>   mount info, etc.)
> - The resources.subscriptions index resource (line 287) is itself hosted by the resources server,
>   so it likely doesn't appear in its own list results
> - Any other inproc servers mounted dynamically are invisible to agents

```
     343:     async def list_resources_tool(input: ResourcesListArgs) -> ResourcesListResult:
     344:         """List resources via aggregator; derive origin using FastMCP prefix logic."""
     345:         # Call compositor's internal _list_resources_mcp directly to avoid client dependency
     346:         # (resources server is tightly coupled to compositor for subscriptions/notifications/metadata)
     347:         mcp_list = await compositor._list_resources_mcp()
>>>  348:         specs = await compositor.mount_specs()
>>>  349:         mount_names = list(specs.keys())
     350:         out: list[ResourceEntry] = []
     351:         for r in mcp_list:
     352:             uri_str = str(r.uri)
     353:             try:
     354:                 origin = derive_origin_server(uri_str, mount_names, compositor.resource_prefix_format)
```

### `session-passing.yaml` / `occ-0`

File: `adgn/src/adgn/props/cli_app/cmd_db.py`

> Inconsistent session management: sync_detector_prompts() and sync_model_metadata()
> don't take a session parameter, while sync_snapshots_to_db() and sync_issues_to_db() do.
> This forces sync_all() to open a session for only 2 of 4 operations, then call the
> other 2 outside the session context.
>
> All four sync functions should take a session parameter for consistency, allowing
> sync_all() to be written as a single with-block that inlines the FullSyncResult
> construction with all four calls inside the session context.

```
      42:         DetectorPromptSyncResult(filename=filename, prompt_sha256=load_and_upsert_detector_prompt(filename))
      43:         for filename in discover_detector_prompts()
      44:     ]
      45:
      46:
>>>   47: def sync_all() -> FullSyncResult:
>>>   48:     """Sync snapshots, issues, detector prompts, and model metadata in a single operation.
>>>   49:
>>>   50:     Returns:
>>>   51:         Combined results from all sync operations
>>>   52:     """
>>>   53:     registry = SnapshotRegistry.from_package_resources()
>>>   54:     with get_session() as session:
>>>   55:         snapshot_stats = sync_snapshots_to_db(session, registry)
>>>   56:         issue_stats = sync_issues_to_db(session, registry)
>>>   57:
>>>   58:     return FullSyncResult(
>>>   59:         snapshot_stats=snapshot_stats,
>>>   60:         issue_stats=issue_stats,
>>>   61:         detector_prompts=sync_detector_prompts(),
>>>   62:         model_metadata_stats=sync_model_metadata(),
>>>   63:     )
      64:
      65:
      66: def recreate_database_schema() -> tuple[SyncStats, SyncStats]:
      67:     """Recreate database from scratch (destructive).
      68:
```

### `string-replace-db-url.yaml` / `occ-0`

File: `adgn/src/adgn/props/prompt_optimizer.py`

> Lines 370-379 read the database URL from environment variable PROPS_AGENT_DB_URL, then use string replacement
> `agent_db_url.replace("localhost:5433", "props-postgres:5432")` to transform the host-side URL into a
> container-accessible URL for Docker network access. This string manipulation is fragile and error-prone - it
> assumes a
> specific URL format and hardcodes both the source and target host/port values.

```
     365:
     366:         # Ground truth issues (TPs/FPs) are now accessed via database
     367:         # No longer mount libsonnet definitions from filesystem
     368:
     369:         # Get agent_user database URL from environment
>>>  370:         agent_db_url = os.environ.get("PROPS_AGENT_DB_URL")
>>>  371:         logger.info(f"PROPS_AGENT_DB_URL from environment: {agent_db_url}")
>>>  372:         if not agent_db_url:
>>>  373:             logger.warning(
>>>  374:                 "PROPS_AGENT_DB_URL not set - agent will not have database access. "
>>>  375:                 "Set to enable querying train data and valid aggregates."
>>>  376:             )
>>>  377:         else:
>>>  378:             # Transform localhost:5433 → props-postgres:5432 for Docker network access
>>>  379:             agent_db_url = agent_db_url.replace("localhost:5433", "props-postgres:5432")
     380:             logger.info(f"Transformed agent_db_url for container: {agent_db_url}")
     381:
     382:         # Create Docker wiring (no /repo mount - would leak test specimen definitions!)
     383:         # workspace_root will be mounted as /workspace (rw mode for agent to write prompts)
     384:         wiring = properties_docker_spec(
```

### `subscribe-tools-wrong-input-type.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/resources/server.py`

> Lines 386 and 413 define subscribe/unsubscribe tools that use ResourcesReadArgs as their input type. However,
> ResourcesReadArgs includes windowing parameters (start_offset and max_bytes on lines 51-52) that are only
> relevant for
> reading resources, not for subscribing/unsubscribing.
>
> The subscribe and unsubscribe tools only use input.server and input.uri - they never access the windowing
> parameters.
> These tools should use a separate, simpler input type (e.g., ResourceSubscriptionArgs) with just server and
> uri
> fields,
> making the tool interface clearer and avoiding unnecessary parameters.

```
     381:         # (resources server is tightly coupled to compositor for subscriptions/notifications/metadata)
     382:         contents = await compositor.read_resource_contents(uri_value)
     383:         return _build_window_payload(contents, input.start_offset, None if input.max_bytes == 0 else input.max_bytes)
     384:
     385:     @mcp.flat_model()
>>>  386:     async def subscribe(input: ResourcesReadArgs) -> SimpleOk:
     387:         """Subscribe to updates for a resource."""
     388:         await _ensure_capability(input.server, feature=ResourceCapabilityFeature.SUBSCRIBE)
     389:         prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
     390:         uri_value = ANY_URL.validate_python(prefixed)
     391:         # Attempt subscribe; reflect success/error in index and re-raise on error.
   ...
     408:                 rec.last_error = None
     409:             await _broadcast_subs_updated()
     410:             return SimpleOk(ok=True)
     411:
     412:     @mcp.flat_model()
>>>  413:     async def unsubscribe(input: ResourcesReadArgs) -> SimpleOk:
     414:         """Unsubscribe from updates for a resource."""
     415:         await _ensure_capability(input.server, feature=ResourceCapabilityFeature.SUBSCRIBE)
     416:         prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
     417:         uri_value = ANY_URL.validate_python(prefixed)
     418:         rec_key = (input.server, input.uri)
   ...
      46:
      47:
      48: class ResourcesReadArgs(BaseModel):
      49:     server: str = Field(description="Origin MCP server name that owns the resource")
      50:     uri: str = Field(description="Resource URI as reported by the origin server's list")
>>>   51:     start_offset: int = Field(default=0, ge=0, description="Start byte offset for windowed reads")
>>>   52:     max_bytes: int = Field(default=0, ge=0, description="Max bytes to return (0 means no limit)")
      53:     model_config = ConfigDict(extra="forbid")
      54:
      55:
      56: # No compositor meta resources here; see adgn.mcp.compositor_meta.server
      57:
```

### `unnecessary-tuple-unpacking.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/approval_policy/engine.py`

> The active_policy() resource handler unnecessarily calls get_policy() which
> returns a tuple (source, version), then unpacks and discards the version:
>
> Current code (lines 566-568):
> def active_policy() -> str:
> content, \_version = self.get_policy()
> return content
>
> This is awkward and requires unpacking a tuple just to discard half of it.
> Since the function only needs the policy source, it should directly access
> the private field:
>
> def active_policy() -> str:
> return self.\_policy_source
>
> Note: get_policy() has legitimate users that need both source and version
> (tests in test_preset_policy_loading.py verify version increments). But this
> resource handler only needs the source.
>
> Similar pattern exists in agent/policy_eval/container.py:38, but that's in
> a different context (agent layer calling into MCP layer).

```
     561:         @self.reader.resource(APPROVAL_POLICY_PROPOSALS_INDEX_URI + "/{id}", name="proposal", mime_type="text/x-python")
     562:         async def proposal_item(id: str) -> str:
     563:             if (got := await self.persistence.get_policy_proposal(self.agent_id, id)) is None:
     564:                 raise KeyError(id)
     565:             return got.content
>>>  566:
>>>  567:         @self.reader.resource(PENDING_CALLS_URI, name="pending_calls", mime_type="application/json")
>>>  568:         def pending_calls() -> dict:
     569:             """List all pending tool call approval requests."""
     570:             items = [
     571:                 PendingCallItem(
     572:                     call_id=call_id, tool_key=req.tool_key, args_json=req.tool_call.args_json if req.tool_call else None
     573:                 )
```

### `unused-seeded-prompts.yaml` / `occ-0`

File: `adgn/tests/props/conftest.py`

> The test_db fixture seeds four Prompt records that are never used by any test.
> Lines 257-260 create prompts with sha256 values "test123", "unknown", "test", and
> "train-test", but no test queries or references these values. All tests that use
> the Prompt table either create their own prompts (e.g., test_agent_queries.py
> line 105 creates "a"\*64) or call load_and_upsert_detector_prompt() which creates
> its own entries. These seeded prompts should be deleted.

```
     250:
     251:     # Initialize schema in the new database
     252:     init_db(test_config.admin_url)
     253:     recreate_database()
     254:
>>>  255:     # Create default test prompts
>>>  256:     with get_session() as session:
>>>  257:         for prompt_sha256 in ["test123", "unknown", "test", "train-test"]:
>>>  258:             prompt = Prompt(prompt_sha256=prompt_sha256, prompt_text=f"Test prompt for {prompt_sha256}")
>>>  259:             session.add(prompt)
>>>  260:         session.commit()
     261:
     262:     yield  # Test runs here
     263:
     264:     # Cleanup: drop the test database
     265:     with postgres_engine.connect() as conn:
```

### `useless-empty-check.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/compositor/server.py`

> Lines 311-312 silently succeed when given an empty server name: "if name in ('',): return". This is wrong
> because if
> validation fails and an empty string reaches this point, the caller receives None (appearing like success)
> instead of
> a
> clear error.
>
> If the upstream validation at line 253 is reliable, this check is redundant and should be removed. If this is
> meant as
> a
> defensive check against validation failures, it should raise ValueError("server name cannot be empty") rather
> than
> silently returning. Silent success on invalid input masks bugs and makes debugging harder.

```
     306:         if pinned:
     307:             self._pinned_servers.add(name)
     308:         await self._notify_mount_listeners(name, MountEvent.MOUNTED)
     309:
     310:     async def unmount_server(self, name: str) -> None:
>>>  311:         if name in ("",):
>>>  312:             return
     313:         # Prevent unmount of pinned servers
     314:         if name in self._pinned_servers:
     315:             raise RuntimeError(f"server '{name}' is pinned and cannot be unmounted")
     316:         async with self._lock:
     317:             mount = self._mounts.pop(name, None)
```

### `useless-fast-path-check.yaml` / `occ-0`

File: `adgn/src/adgn/agent/agent.py`

> Lines 620-621 in agent.py contain a useless fast-path return that checks if there are pending
> function calls before iterating and emitting results. This check doesn't provide any performance
> benefit since the following loop (lines 622-624) would naturally be a no-op if the list is empty.
> The early return adds unnecessary code without improving performance or clarity.

```
     615:         self._transcript.append(event)
     616:         self._controller.on_tool_result(event)
     617:
     618:     # Exposed for abort flows: synthesize aborted outputs for all pending calls
     619:     def abort_pending_tool_calls(self) -> None:
>>>  620:         if not self.pending_function_calls:
>>>  621:             return
     622:         for fc in list(self.pending_function_calls):
     623:             self._emit_tool_result(fc, _abort_result())
     624:         self.pending_function_calls.clear()
     625:
     626:     @property
```

### `uuid-test-db-name.yaml` / `occ-0`

File: `adgn/tests/props/conftest.py`

> Line 232 uses uuid4() for test database names. The issue suggests using actual test IDs if available
> from pytest (e.g., request.node.nodeid) and applying a whitelist-based sanitizer (keep
> alphanumeric/underscore,
> reject special chars) instead of just replacing hyphens. The length limit could also be increased to something
> more reasonable like 128 characters if PostgreSQL allows it.

```
     227:
     228:     Creates a unique database per test, initializes schema, and drops it after.
     229:     Safe for parallel pytest-xdist execution - each test gets its own database.
     230:     """
     231:     # Generate unique database name for this test
>>>  232:     test_id = str(uuid4()).replace("-", "")[:16]
>>>  233:     db_name = f"props_test_{test_id}"
     234:
     235:     # Get base config and parse admin URL
     236:     base_config = get_test_config()
     237:     # Parse admin URL to get connection params (connect to postgres db to create new db)
     238:     parsed = urlparse(base_config.admin_url)
```

## ducktape/2025-09-03-00 (30)

### `argparse-type-path.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py`

> Argparse can directly parse filesystem arguments into pathlib.Path objects by using `type=Path` on
> add_argument.
> Prefer declaring `ap.add_argument('--foo', type=Path, ...)` so callers receive a Path immediately and avoid
> scattershot
> `Path(args.foo)` conversions later.
>
> Why this matters:
>
> - Tightens contracts: handlers downstream get the correct type without ad-hoc wrapping.
> - Reduces one-off conversions and improves readability.
> - Avoids small bugs where a string path is treated differently than a Path (e.g.,
>   path / os.PathLike handling).

### `call-tool-shell-abstraction-confusion.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py`

> McpManager.call_tool() (lines 266-284) treats all MCP tools as if they were shell commands,
> manufacturing {"exit", "stdout", "stderr"} for everything. For local handlers that return
> dicts, it wraps them as {"exit": 0, "json": <result>} (line 281-282). This is confused
> about the abstraction: MCP tools are general-purpose operations that return CallToolResult
> (from mcp package), not necessarily shell command results. CallToolResult has proper fields
> (isError, content, structuredContent, meta) for representing tool execution results.
>
> The method should use CallToolResult throughout instead of manufacturing exit codes for
> non-command tools. This confusion causes issues like double-wrapping where LocalExecServer's
> {"exit": 1, "stderr": "error"} gets wrapped as {"exit": 0, "json": {"exit": 1, ...}},
> hiding failures from the agent.

### `cap-append-defaults.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> Calls like `_cap_append(parts, chunk, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated…]")` repeat the same
> constants at each site. Prefer giving `_cap_append` sensible defaults (or deriving the note from the cap)
> so callers only pass the varying pieces. This reduces duplication and drift risk across call sites.

### `collect-tools-openai-dict-duplication.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py`

> \_collect_tools_live has duplicated logic for building openai_tools dict entries.
> The stdio branch (lines 121-128) and local branch (lines 133-140) create identical
> dict structures with "type", "name", "description", "parameters" keys. Should extract
> a helper function that takes (server, tool_name, description, params_schema) and
> returns the tool dict, then call it from both branches. This would eliminate 8 lines
> of duplication and make the tool dict structure easier to maintain.

### `derive-model-str.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> `AppConfig.resolve` constructs `model_str` and also stores `provider` and `model_name` split from it, but
> later code reads the composite `model_str` only for logging/printing. Since `model_str` is trivially derivable
> as `f"{provider}:{model_name}"`, avoid storing this redundant field and derive it where needed.
>
> This reduces duplicated state and keeps the config focused on primary fields.

### `diagnostics-broad-catch.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py`

> During diagnostics the code catches broad Exception, prints a diagnostic message, and continues. In a
> diagnostics path
> this masks failures that were supposed to surface useful debug information — the wrapper should fail fast or
> at least
> propagate the error after logging full context.
>
> Diagnostics code should make problems visible and actionable. Silently continuing after printing a short
> message
> prevents test harnesses and callers from noticing failures and makes root-cause debugging much harder.
>
> Prefer: log full traceback and re-raise (or exit non-zero) so CI/tests detect the issue. Only suppress known,
> explicitly
> documented non-fatal exceptions.

### `docker-exec-mcp-typed-inputs.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py`

> Docker Exec MCP tool inputs should be declared as strongly-typed (Pydantic) parameters on the FastMCP
> tool function, so validation is handled by the framework and schemas are auto-exported to MCP clients.
>
> Current pattern (manual dict/field extraction in call_tool) leads to ad-hoc checks and coercions.
>
> FastMCP-idiomatic pattern (two options):
>
> - Single Pydantic payload model:
>   @app.tool()
>   async def docker_exec(payload: ExecInputs) -> ExecResultPayload: ...
>   where ExecInputs is a Pydantic BaseModel with strict field types.
> - Separate strongly-typed parameters:
>   @app.tool()
>   async def docker_exec(cmd: list[str], timeout_secs: float | None = None, ...) -> ExecResultPayload: ...
>
> Required input typing (minimum):
>
> - cmd: list[str] (non-empty)
> - cwd: str | None
> - env: dict[str, str] | None (values must be strings; reject non-strings)
> - user: str | None
> - tty: bool (no truthy-string coercion)
> - shell: bool (no truthy-string coercion)
> - timeout_secs: float | None (>= 0; no string coercion)
>
> Benefits:
>
> - Validation moves to FastMCP/Pydantic; no manual coercion.
> - JSON Schema for the tool is generated directly from the Pydantic model and visible to MCP clients.
> - Clear, self-documenting contracts; fewer runtime surprises.
>
> Acceptance criteria:
>
> - Define a Pydantic BaseModel ExecInputs with the fields above (strict types; min_items=1 for cmd).
> - Change the FastMCP registration to use a typed tool signature (either payload model or per-arg types).
> - Remove manual extraction/coercion in call_tool; rely on Pydantic validation (any invalid inputs must raise).
> - Keep existing shell/timeout composition logic, but operate only on already-validated,
>   correctly-typed values.

### `docker-exec-unbounded-output.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py`

> Docker Exec MCP returns unbounded stdout/stderr data, which is hazardous for MCP/LLM agents and
> can also lead to process memory growth.
>
> Primary impact (MCP/LLM):
>
> - Tool responses are fed back into an LLM context. Returning megabytes of text will quickly
>   blow the caller’s context/window, causing truncation, failures, or severe quality drops.
>   MCP tools must bound returned payload size.
>
> Secondary impact (server memory):
>
> - The server accumulates stdout/stderr into bytearrays with no cap. Very chatty commands can
>   cause high memory usage or OOM over time.
>
> Observed (specimen paths):
>
> - llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py collects into bytearrays without limits
>   and returns the full decoded strings in the tool payload.
>
> Acceptance criteria (bounded capture in MCP response):
>
> - Enforce an upper bound (bytes or characters) for stdout/stderr included in the tool return
>   (e.g., first N bytes, with a clear truncation note and total sizes).
> - Keep full data optional (e.g., tee to a temp file/log and return a path/reference), but the
>   MCP tool’s returned text must be bounded deterministically.
> - Document the cap and truncation behavior in the tool description so callers can plan.
>
> Optional (server memory hygiene):
>
> - Apply the same bound in the in-process accumulation path, or stream/tee to a file to avoid
>   unbounded memory growth while still allowing capped returns.

### `docker-mutable-singletons.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py`

> Module-level `_DOCKER_CLIENT` and `_CONTAINER_REF` introduce mutable global state that couples requests
> through hidden, process-wide singletons. This makes behavior order-dependent, complicates testing,
> and risks leaking configuration across calls.
>
> Prefer explicit dependency injection: pass a Docker client via parameters or a factory, or manage per-request
> context that resolves the container ref at call time. Keep state local to the request boundary.

### `editor-shell-injection.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> In llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py the editor is invoked via:
> `asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")`.
>
> This concatenates the filename into the shell command string. That is not Git-compatible and
> breaks with spaces/quotes in either the editor value or the path; it also changes parsing semantics.
>
> Correct Git-compatible invocation keeps shell semantics but appends the filename as a separate
> argument through the shell wrapper (like Git's run-command):
>
> /bin/sh -c '<editor> "$@"' <editor> <realpath-to-COMMIT_EDITMSG>
>
> # On Git for Windows, use `sh -c` rather than `/bin/sh -c`.
>
> Acceptance criteria:
>
> - Replace the f-string shell command with the shell-wrapper form above (or an equivalent that
>   passes the path as a separate arg rather than interpolating it into the command string).
> - Resolve the editor via `git var GIT_EDITOR` (respects precedence and ":" no-op).
> - Keep shell usage for full Git compatibility; do not flag shell usage itself.
> - (Optional) Validate COMMIT_EDITMSG path (e.g., symlink/permissions) before launch.

### `enforce-single-total-cap.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> Current caps are applied per git output block (status / name-status / log / diff), so the assembled
> prompt can reach many× the nominal cap. Prefer a single accumulator-based total cap enforced over the
> fully assembled prompt, or track remaining bytes across calls to `_cap_append` to share the budget.
>
> This yields predictable size, avoids double work, and makes tradeoffs explicit between sections.

### `exceptions-for-control-flow.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> Do not use try/except to detect normal, non-error conditions. Reserve exceptions for unexpected situations.
> The current "first commit" detection relies on catching a diff failure, which can also swallow unrelated
> errors.
> Prefer a positive repository capability/condition check with early bailout. Example pattern:
>
> - If we're in the 90% normal case (without executing a failing operation), run the normal path.
> - Else, handle the 10% case explicitly.
>   As a reviewer, seeing try/except signals "what's on fire" (unexpected), not a routine precondition check.
>
> **Note:** try/except used to detect first commit instead of positive check

### `gitpython-over-shell.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> `_get_editor` shells out via `asyncio.create_subprocess_exec("git", "var", "GIT_EDITOR", ...)` to
> obtain the editor. Prefer using the repo API directly (e.g., `repo.git.var("GIT_EDITOR")`) or a
> config reader fallback (`repo.config_reader().get_value("core", "editor", default)`). This reduces
> subprocess boilerplate and simplifies control flow.

### `legacy-policyconfig-shim.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py`

> The wrapper contains a legacy PolicyConfig shim that exists only for import compatibility with older tests.
> Keeping dead shims because "tests still reference it" is not a sufficient reason to retain the code: tests
> should be
> updated to the canonical model or provided a test-only shim.
>
> Why this is bad:
>
> - It preserves dead/unused code paths that increase maintenance burden and cognitive load.
> - New readers assume the shim is live behavior and may write code to support it, increasing cruft.
> - Tests depending on obsolete shims should be migrated or wrapped in explicit test fixtures rather than
>   perpetuating
>   legacy surface area.

### `literal-to-strenum.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/agent.py`

> For small, closed sets of string-valued discriminants (e.g. the tool policy values "auto", "required",
> "none"), prefer
> a
> StrEnum rather than ad-hoc Literal annotations.
>
> A StrEnum centralizes the allowed values as runtime objects, improves discoverability and IDE support, makes
> parsing
> and
> validation simpler (ToolPolicy(value) will raise on unknown values), and reduces accidental typos in call
> sites.

### `liveserver-close-leak.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py`

> \_LiveServer.close() awaits session.**aexit**() and only afterwards closes the stdio
> transport context manager. If the session close raises, the stdio cleanup never runs,
> leaking subprocess pipes and file descriptors.

### `max-prompt-cap-name.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> The constant name `MAX_PROMPT_CONTEXT_BYTES` uses two near-synonyms in this code path ("prompt" and
> "context").
> Either pick one term and scope it correctly, or enforce a true global prompt cap:
>
> Options:
>
> - Rename to reflect true scope (per-block cap): e.g.,
>   `MAX_PROMPT_GIT_OUTPUT_BYTES` (applies to each appended block)
> - Or adopt a global `MAX_PROMPT_BYTES` and enforce an overall cap,
>   leaving block-level caps as internal helpers
>
> This reduces ambiguity, communicates scope precisely, and prevents misinterpretation.

### `mcp-config-load-swallow.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/cli.py`

> The code currently conditionally reads an MCP config only if the file exists. That’s fine. The problem is the
> broad
> except that silently ignores _errors parsing or using the file_. If the .mcp.json exists but is malformed or
> otherwise
> unusable, the program must crash loudly so operator/CI notices and fixes the problem; do NOT silently ignore a
> present-but-broken config file.
>
> Swallowing initialization-time parsing/shape errors leads to silently degraded runtime behavior and
> hard-to-diagnose
> failures later. If the file exists, treat errors parsing/using it as fatal.

### `redundant-parallel-names.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> The editor flow uses redundant parallel variable names (`final_text` and `content_before`) that mirror each
> other
> without adding clarity. Keep a single source variable to reduce cognitive load and avoid confusion about which
> represents the canonical value.

### `remove-openai-key-plumb.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/agent.py`

> The OpenAI SDK already reads `OPENAI_API_KEY` and base URL env vars; hand-rolling a client factory that
> fetches
> env vars duplicates configuration paths and adds code surface without value.
>
> Prefer:
>
> - Call `openai.OpenAI()` directly and let the SDK read environment variables; or
> - Inject a client (DI) from the caller/tests to keep construction policy out of core logic.
>
> This reduces duplication and makes tests simpler (just pass a client/fake).

### `responses-turn-duplicate.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/cli.py`

> `responses_turn` and `responses_followup_with_tool_outputs` in the CLI duplicate ~20 lines of logic:
> assembling instructions (with optional MCP block), listing tools, building the payload, and
> calling Responses. This copy/paste raises drift risk and splits responsibility between CLI and agent.
>
> Preferred design:
>
> - Keep agent.py as the single owner of the agent loop and Responses flow (instructions assembly,
>   tools listing, payload construction, result parsing).
> - Make cli.py a thin wrapper that delegates to the agent (or a single helper) rather than repeating logic.
>
> Concretely: extract a shared helper (or call through to agent) used by both paths, removing the duplicate
> try/except + instruction assembly + tools list + responses.create blocks.

### `runner-branch-duplication.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> ParallelTaskRunner.create_and_run duplicates runner construction and update loop across branches; only output
> streaming
> differs.
> Prefer a single shared trunk: compute precommit_task (real or noop) and master_fd, construct the runner once,
> start
> the
> update loop once, and stream output only if master_fd is not None. This keeps the main path flat (early
> bailout for
> no-precommit).

### `scoped-try-except-swallow.yaml` / `occ-4`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py`

> Scoped try/except blocks swallow errors instead of failing loudly.
> Where there is no specific recovery/handling need, do not catch at all — let exceptions bubble normally.
> Where there is a specific reason to handle, catch only the narrow exception and do not swallow silently (log
> and/or
> re-raise as appropriate).
>
> **Note:** mkdir failure silently falls back to cwd, hiding operational problems

### `timeout-ms-propagation.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py`

> exec_handler converts timeout_ms to seconds early with int(timeout_ms / 1000), truncating
> sub-second precision (1500ms becomes 1s, 500ms becomes 0→1s). Timeout should be propagated
> as milliseconds (int) throughout the call chain and only divided by 1000.0 at the final
> subprocess.communicate() call. This requires changing: exec_handler to pass timeout_ms
> directly, \_run_in_sandbox(timeout_s: int) → \_run_in_sandbox(timeout_ms: int),
> \_run_proc(timeout_s: int) → \_run_proc(timeout_ms: int), and \_run_proc to convert at
> communicate: p.communicate(timeout=timeout_ms / 1000.0). Python >=3.11 is required
> and subprocess.communicate() has supported float timeout since Python 3.3.

### `timeout-noop-branch.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py`

> The timeout branch is a literal no-op:
>
> if timed_out: # We cannot reliably kill the exec unless wrapper handled it; return best-effort
> pass
>
> Timeout handling in this module:
>
> - With USE_CONTAINER_TIMEOUT_WRAPPER=1, commands are wrapped in `timeout -s TERM <secs>` inside the container
>   (see
>   lines 27–31), so the process is actually signaled on expiry.
> - Without the wrapper, we stop reading and return ExecResult with `timed_out=True`,
>   but the container process may keep running. Tests only assert `timed_out`; they do not verify termination.
>
> This is a footgun: timeouts can exceed and leave processes running. At the very least, document this behavior
> prominently and surface explicit return markers (e.g., `timeout_enforced=false` or `kill_attempted=false`) so
> callers
> can react.
>
> Preferred fix: require an always-correct timeout path. If a timeout is requested and the wrapper is
> unavailable, fail
> fast (refuse to run) instead of best-effort; or ensure the implementation enforces termination reliably.
> Delete the
> empty branch.

### `timeout-units-ambiguous.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py`

> Constants representing timeouts should carry units in their type or name. `_DEFAULT_TIMEOUT: float | None =
None` is
> ambiguous about units.
>
> Prefer one of two patterns:
>
> - Use a timedelta, e.g. `DEFAULT_TIMEOUT = timedelta(seconds=30)`, and name it DEFAULT_TIMEOUT.
> - If storing a numeric value, include the unit in the name and type,
>   e.g. `DEFAULT_TIMEOUT_S: int | None = None`.
>
> Benefits: reduces confusion about whether a timeout is seconds, milliseconds, or fractional seconds; makes
> call sites
> clearer and avoids silent misconfigurations.

### `trivial-wrapper-main.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/cli.py`

> The CLI `main()` in `mcp/sandboxed_jupyter_mcp/cli.py` merely delegates to `wrapper.main()` without adding any
> value
> (no
> argument transformation, validation, or help text).
> One-line passthrough wrappers like this add indirection and lines of code for no benefit. Prefer calling the
> implementation directly from entry points or consolidating the tiny delegating main into the wrapper to reduce
> churn
> and
> improve readability.

### `truncation-msg-hardcoded.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> The truncation note is hardcoded as "[Context truncated to 100 KiB]" in multiple places, while the cap
> is driven by MAX_PROMPT_CONTEXT_BYTES. This duplicates the limit in string form and risks drift.
>
> Prefer a single source of truth: derive the human text from the cap (e.g., f"[Context truncated to
>
> > {MAX_PROMPT_CONTEXT_BYTES // 1024} KiB]")
> > or use a generic stable marker like "[Context truncated]". Keep the message in one place and reuse it.

### `tty-guard-early-bailout.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> The TTY guard should use an early bailout to avoid unnecessary nesting.
> Instead of nesting the main logic under `if sys.stdout.isatty(): ...`, invert the condition and return/skip
> when not a
> TTY, then run the terminal sizing at the base level.

### `unused-prev-msg-default.yaml` / `occ-0`

File: `llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py`

> The parameter is declared with a default that callers never use:
>
> previous_message: str | None = None
>
> Unused defaults add unnecessary degrees of freedom and complicate API contracts.
> Prefer tightening the signature: drop the default (require an explicit value from callers)
> or make the parameter mandatory only where needed via a higher-level object.

## ducktape/2025-11-22-00 (29)

### `byte-length-for-token-budget.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/core.py`

> The code uses byte length (`_len_bytes()`) to cap context passed to LLMs,
> but LLM token budgets are better approximated by character count, not bytes.
>
> **Current implementation:**
> Byte-based logic with `_len_bytes()`, `MAX_PROMPT_CONTEXT_BYTES = 100 * 1024`,
> and byte-boundary truncation in `_cap_append()` (lines 14-29). Used to cap
> status, diff, and log output in `_build_ai_context()` (lines 141-166).
>
> **Problems:**
>
> 1. **Wrong approximation**: LLM tokens correlate with character count, not bytes.
>    Multi-byte UTF-8 (emoji/CJK) are 3-4 bytes but typically 1 token, so byte-based
>    limits penalize non-ASCII content unnecessarily.
> 2. **Arbitrary units**: "100 KiB" is meaningless for token budgets; should be
>    expressed as character count or approximate token count.
> 3. **Byte-boundary truncation**: Can break mid-character in UTF-8 (code handles
>    with `errors="ignore"` but adds complexity).
> 4. **Complexity**: Encoding/decoding is more complex than using `len(s)`.
>
> **Correct approach:**
> Use character count directly. Express cap as `MAX_PROMPT_CONTEXT_CHARS = 100_000`
> (~25k tokens at ~4 chars/token). Truncate via string slicing, which always
> produces valid strings.
>
> **Benefits:**
>
> 1. Better approximation: Chars correlate with tokens better than bytes
> 2. Clearer intent: "100k chars" is more meaningful than "100 KiB"
> 3. Simpler code: No encoding/decoding, just string slicing
> 4. No mid-character breaks: String slicing always produces valid strings
> 5. Portable: Byte lengths vary by encoding; char counts don't
>
> **Note:** For precise token counting, use a tokenizer (e.g., `tiktoken`). For
> rough caps, character count is a better heuristic than byte length.

```
       3: import re
       4:
       5: import pygit2
       6:
       7: # Shared constants used by backends and CLI
>>>    8: MAX_PROMPT_CONTEXT_BYTES = 100 * 1024  # 100 KiB cap for AI context block
       9: PAST_COMMITS_MAX_CHARS = 6000
      10: RECENT_COMMITS_FOR_CONTEXT = 30
      11: DIFF_SNIPPET_CHARS = 5000
      12:
      13:
   ...
       9: PAST_COMMITS_MAX_CHARS = 6000
      10: RECENT_COMMITS_FOR_CONTEXT = 30
      11: DIFF_SNIPPET_CHARS = 5000
      12:
      13:
>>>   14: def _len_bytes(s: str) -> int:
>>>   15:     return len(s.encode("utf-8"))
      16:
      17:
      18: def _cap_append(parts: list[str], chunk: str, cap_bytes: int, truncation_note: str) -> bool:
      19:     """Append chunk to parts unless this would exceed cap; returns True if truncated."""
      20:     current_bytes = _len_bytes("".join(parts))
   ...
      13:
      14: def _len_bytes(s: str) -> int:
      15:     return len(s.encode("utf-8"))
      16:
      17:
>>>   18: def _cap_append(parts: list[str], chunk: str, cap_bytes: int, truncation_note: str) -> bool:
>>>   19:     """Append chunk to parts unless this would exceed cap; returns True if truncated."""
>>>   20:     current_bytes = _len_bytes("".join(parts))
>>>   21:     needed_bytes = _len_bytes(chunk)
>>>   22:     if current_bytes + needed_bytes >= cap_bytes:
>>>   23:         remaining_bytes = cap_bytes - current_bytes
>>>   24:         if remaining_bytes > 0:
>>>   25:             parts.append(chunk.encode("utf-8")[:remaining_bytes].decode("utf-8", errors="ignore"))
>>>   26:         parts.append(truncation_note + "\n")
>>>   27:         return True
>>>   28:     parts.append(chunk)
>>>   29:     return False
      30:
      31:
      32: def _diff(repo: pygit2.Repository, include_all: bool) -> pygit2.Diff:
      33:     return repo.diff(repo.head.target, None, cached=not include_all)
      34:
   ...
     141: def _build_ai_context(repo: pygit2.Repository, include_all: bool) -> str:
     142:     parts: list[str] = []
     143:
     144:     parts.append("$ git status --porcelain\n")
     145:     status_out = _format_status_porcelain(repo) + "\n"
>>>  146:     _cap_append(parts, status_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     147:
     148:     ns_header = "git diff HEAD --name-status" if include_all else "git diff --cached --name-status"
     149:     parts.append(f"$ {ns_header}\n")
     150:     ns_out = _format_name_status(repo, include_all) + "\n"
     151:     _cap_append(parts, ns_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
   ...
     146:     _cap_append(parts, status_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     147:
     148:     ns_header = "git diff HEAD --name-status" if include_all else "git diff --cached --name-status"
     149:     parts.append(f"$ {ns_header}\n")
     150:     ns_out = _format_name_status(repo, include_all) + "\n"
>>>  151:     _cap_append(parts, ns_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     152:
     153:     parts.append(f"$ git log --no-color -n {RECENT_COMMITS_FOR_CONTEXT} --stat --pretty=format:%h %B\n")
     154:     log_out = "\n".join(_log_subjects(repo, RECENT_COMMITS_FOR_CONTEXT)) + "\n"
     155:     _cap_append(parts, log_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     156:
   ...
     150:     ns_out = _format_name_status(repo, include_all) + "\n"
     151:     _cap_append(parts, ns_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     152:
     153:     parts.append(f"$ git log --no-color -n {RECENT_COMMITS_FOR_CONTEXT} --stat --pretty=format:%h %B\n")
     154:     log_out = "\n".join(_log_subjects(repo, RECENT_COMMITS_FOR_CONTEXT)) + "\n"
>>>  155:     _cap_append(parts, log_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     156:
     157:     diff_header = "git diff HEAD --unified=0" if include_all else "git diff --cached --unified=0"
     158:     parts.append(f"$ {diff_header}\n")
     159:     diff_out = _format_unified_diff(repo, include_all) + "\n"
     160:     _cap_append(parts, diff_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
   ...
     155:     _cap_append(parts, log_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     156:
     157:     diff_header = "git diff HEAD --unified=0" if include_all else "git diff --cached --unified=0"
     158:     parts.append(f"$ {diff_header}\n")
     159:     diff_out = _format_unified_diff(repo, include_all) + "\n"
>>>  160:     _cap_append(parts, diff_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     161:
     162:     out = "".join(parts)
     163:     if _len_bytes(out) > MAX_PROMPT_CONTEXT_BYTES:
     164:         out = out.encode("utf-8")[:MAX_PROMPT_CONTEXT_BYTES].decode("utf-8", errors="ignore")
     165:         out += "\n[Context truncated to 100 KiB]\n"
   ...
     158:     parts.append(f"$ {diff_header}\n")
     159:     diff_out = _format_unified_diff(repo, include_all) + "\n"
     160:     _cap_append(parts, diff_out, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated to 100 KiB]")
     161:
     162:     out = "".join(parts)
>>>  163:     if _len_bytes(out) > MAX_PROMPT_CONTEXT_BYTES:
>>>  164:         out = out.encode("utf-8")[:MAX_PROMPT_CONTEXT_BYTES].decode("utf-8", errors="ignore")
>>>  165:         out += "\n[Context truncated to 100 KiB]\n"
     166:     return out
     167:
     168:
     169: def diffstat(repo: pygit2.Repository, passthru: list[str]) -> str:
     170:     include_all = include_all_from_passthru(passthru)
```

### `deprecated-datetime-utcnow.yaml` / `occ-0`

File: `adgn/src/adgn/agent/transcript_handler.py`

> Lines 45 and 52 use `datetime.utcnow().isoformat() + "Z"` for timestamp generation.
>
> `datetime.utcnow()` is deprecated as of Python 3.12 (scheduled for removal in future versions).
> It returns a timezone-naive datetime, requiring manual "Z" suffix concatenation.
>
> Replace with `datetime.now(timezone.utc)` which returns a timezone-aware datetime. The `.isoformat()`
> call automatically includes timezone offset (e.g., `2024-01-15T10:30:00+00:00`), eliminating the
> manual suffix. If "Z" format is required, use `.replace("+00:00", "Z")`.
>
> Timezone-aware datetime provides type safety (datetime knows it's UTC, not just a naive timestamp)
> and prevents accidentally forgetting the timezone suffix or using the wrong timezone.

```
      40:         # Fail fast if a transcript already exists at destination
      41:         if self._events_path.exists():
      42:             raise FileExistsError(f"Transcript already exists: {self._events_path}")
      43:         # Write a small metadata file once
      44:         (self._root / "metadata.json").write_text(
>>>   45:             json.dumps({"started": datetime.utcnow().isoformat() + "Z"}, indent=2), encoding="utf-8"
      46:         )
      47:
      48:     # ---- Event helpers ----
      49:     def _write_event(self, evt: UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem) -> None:
      50:         rec = to_jsonl_record(evt)
   ...
      47:
      48:     # ---- Event helpers ----
      49:     def _write_event(self, evt: UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem) -> None:
      50:         rec = to_jsonl_record(evt)
      51:         # Timestamped envelope (events.jsonl)
>>>   52:         out = {"ts": datetime.utcnow().isoformat() + "Z", **rec}
      53:         with self._events_path.open("a", encoding="utf-8") as f:
      54:             f.write(json.dumps(out, ensure_ascii=False) + "\n")
      55:         # Compact transcript (transcript.jsonl)
      56:         with self._transcript_path.open("a", encoding="utf-8") as g:
      57:             g.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

### `duplicate-style-definitions.yaml` / `occ-0`

File: `adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte`

> AgentsSidebar.svelte line 347 contains a useless historical comment: "Backdrop
> styling moved to ModalBackdrop component". This documents a past refactoring
> rather than explaining current behavior.
>
> Problems: (1) historical note provides no value to readers, (2) ModalBackdrop's
> existence is already obvious from imports and usage, (3) redundant with "Modal
> styles" section header.
>
> Delete the comment. Historical notes ("moved to...", "used to be...") clutter
> code without explaining current behavior. Comments should explain complexity,
> workarounds, or non-obvious behavior, not document past refactorings.

```
     342:   /* Keep the resize handle within the sidebar to avoid overlaying the chat area */
     343:   .left-resize { position: absolute; top: 0; right: 0; width: 6px; height: 100%; cursor: col-resize; background: transparent; border: none; padding: 0; }
     344:   .row { display: flex; gap: 0.5rem; align-items: center; }
     345:   .preset { flex: 1; min-width: 0; }
     346:   /* Modal styles */
>>>  347:   /* Backdrop styling moved to ModalBackdrop component */
     348:   .modal { background: var(--surface); color: var(--text); min-width: 320px; max-width: 90vw; border: 1px solid var(--border); border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,0.25); }
     349:   .modal header { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); font-weight: 600; }
     350:   .modal .body { padding: 0.75rem; display: grid; grid-template-columns: 1fr; gap: 0.5rem; }
     351:   .modal .row { display: flex; gap: 0.5rem; align-items: center; }
     352:   .modal footer { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 0.5rem 0.75rem; border-top: 1px solid var(--border); }
```

### `duplicate-transcript-files.yaml` / `occ-0`

File: `adgn/src/adgn/agent/transcript_handler.py`

> `TranscriptHandler` writes the same events to two nearly-identical files: `events.jsonl`
> (with timestamps) and `transcript.jsonl` (without timestamps). Lines 38-39 define both
> paths, lines 53-57 write to both files on every event.
>
> **Problems:**
>
> 1. Redundant storage: same data written twice, only difference is timestamp wrapper
> 2. Confusing naming: two files with similar names containing nearly identical content
> 3. Performance overhead: double I/O operations for every event
> 4. Storage waste: doubles disk usage for large transcripts
> 5. Unclear purpose: which file should tools read?
>
> **Fix:** Choose one format. Keep the timestamped format (`events.jsonl`) as primary since
> it preserves temporal information (timestamps are useful for debugging, analysis, replay;
> you can strip them if needed but can't add them back). Remove `_transcript_path` and the
> second write. If both formats are needed, generate the compact format on-demand from the
> timestamped one via an `export_compact_transcript()` method. Benefits: single source of
> truth, half the I/O, no redundant data, easier maintenance.

```
      33:     """
      34:
      35:     def __init__(self, *, dest_dir: Path) -> None:
      36:         self._root = dest_dir
      37:         self._root.mkdir(parents=True, exist_ok=True)
>>>   38:         self._events_path = self._root / "events.jsonl"
>>>   39:         self._transcript_path = self._root / "transcript.jsonl"
      40:         # Fail fast if a transcript already exists at destination
      41:         if self._events_path.exists():
      42:             raise FileExistsError(f"Transcript already exists: {self._events_path}")
      43:         # Write a small metadata file once
      44:         (self._root / "metadata.json").write_text(
   ...
      36:         self._root = dest_dir
      37:         self._root.mkdir(parents=True, exist_ok=True)
      38:         self._events_path = self._root / "events.jsonl"
      39:         self._transcript_path = self._root / "transcript.jsonl"
      40:         # Fail fast if a transcript already exists at destination
>>>   41:         if self._events_path.exists():
>>>   42:             raise FileExistsError(f"Transcript already exists: {self._events_path}")
      43:         # Write a small metadata file once
      44:         (self._root / "metadata.json").write_text(
      45:             json.dumps({"started": datetime.utcnow().isoformat() + "Z"}, indent=2), encoding="utf-8"
      46:         )
      47:
   ...
      48:     # ---- Event helpers ----
      49:     def _write_event(self, evt: UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem) -> None:
      50:         rec = to_jsonl_record(evt)
      51:         # Timestamped envelope (events.jsonl)
      52:         out = {"ts": datetime.utcnow().isoformat() + "Z", **rec}
>>>   53:         with self._events_path.open("a", encoding="utf-8") as f:
>>>   54:             f.write(json.dumps(out, ensure_ascii=False) + "\n")
>>>   55:         # Compact transcript (transcript.jsonl)
>>>   56:         with self._transcript_path.open("a", encoding="utf-8") as g:
>>>   57:             g.write(json.dumps(rec, ensure_ascii=False) + "\n")
      58:
      59:     # ---- BaseHandler hooks (typed) ----
      60:     def on_user_text_event(self, evt: UserText) -> None:
      61:         self._write_event(evt)
      62:
```

### `duplicated-agent-info.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/server.py`

> The code has two problems in server.py:
>
> **Problem 1: Duplicated agent info construction**
>
> Both `list_agents()` and `get_agent_info()` build the same `AgentInfo` object with identical
> logic (determine run phase, check mode, build capabilities), but the implementation is
> duplicated line-by-line instead of extracting a shared helper (server.py, lines 252-302).
>
> **The correct approach:**
> Extract a `_build_agent_info(agent_id, agent)` helper method and call it from both resources.
> Alternatively, have `list_agents` call `get_agent_info` for each agent.
>
> **Problem 2: Thin wrapper methods**
>
> Methods `get_infrastructure()`, `get_agent_mode()`, and `get_local_runtime()` are trivial
> wrappers that just call `_get_agent_or_raise()` and access one field (server.py, lines 187-198).
>
> **The correct approach:**
> Let callers use `_get_agent_or_raise()` directly and access fields themselves
> (`agent.running`, `agent.mode`, `agent.local_runtime`). Or if public access is needed,
> rename `_get_agent_or_raise` to `get_agent` and let callers access fields directly.
>
> **Benefits:**
>
> 1. Less code duplication (single agent info construction)
> 2. Easier maintenance (one place for changes)
> 3. Simpler API (fewer methods, clearer responsibilities)
> 4. More direct (no unnecessary jumps between wrapper methods)
> 5. Better testability (can test helper independently)
>
> **Why thin wrappers are harmful:**
> They add noise without meaningful abstraction, increase maintenance burden, and make it harder
> to see what's actually being accessed.

```
     247:         else:
     248:             return RunPhase.SAMPLING, pending_approvals
     249:
     250:     def _register_resources(self) -> None:
     251:         @self.resource("resource://agents/list", name="agents_list", mime_type="application/json")
>>>  252:         async def list_agents() -> AgentsListResponse:
>>>  253:             """List all agents with detailed status."""
>>>  254:             agents = []
>>>  255:             for agent_id, entry in self._agents.items():
>>>  256:                 if entry.agent is None:
>>>  257:                     continue  # Skip uninitialized agents
>>>  258:
>>>  259:                 agent = entry.agent
>>>  260:
>>>  261:                 # Get infrastructure if available
>>>  262:                 infra = agent.running
>>>  263:                 live = infra is not None
>>>  264:
>>>  265:                 # Determine run phase and pending approvals
>>>  266:                 run_phase, pending_approvals = self._determine_run_phase(infra)
>>>  267:
>>>  268:                 # Determine capabilities
>>>  269:                 is_local = agent.mode == AgentMode.LOCAL
>>>  270:
>>>  271:                 agents.append(
>>>  272:                     AgentInfo(
>>>  273:                         id=agent_id,
>>>  274:                         mode=agent.mode,
>>>  275:                         live=live,
>>>  276:                         run_phase=run_phase,
>>>  277:                         pending_approvals=pending_approvals,
>>>  278:                         capabilities=AgentCapabilities(chat=is_local, agent_loop=is_local),
>>>  279:                     )
     280:                 )
     281:
     282:             return AgentsListResponse(agents=agents)
     283:
     284:         @self.resource("resource://agents/{agent_id}/info", name="agent_info", mime_type="application/json")
   ...
     280:                 )
     281:
     282:             return AgentsListResponse(agents=agents)
     283:
     284:         @self.resource("resource://agents/{agent_id}/info", name="agent_info", mime_type="application/json")
>>>  285:         async def get_agent_info(agent_id: AgentID) -> AgentInfo:
>>>  286:             """Get detailed information about a specific agent."""
>>>  287:             agent = self._get_agent_or_raise(agent_id)
>>>  288:
>>>  289:             infra = agent.running
>>>  290:             live = infra is not None
>>>  291:
>>>  292:             # Determine run phase and pending approvals
>>>  293:             run_phase, pending_approvals = self._determine_run_phase(infra)
>>>  294:
>>>  295:             is_local = agent.mode == AgentMode.LOCAL
>>>  296:
>>>  297:             return AgentInfo(
>>>  298:                 id=agent_id,
>>>  299:                 mode=agent.mode,
>>>  300:                 live=live,
>>>  301:                 run_phase=run_phase,
>>>  302:                 pending_approvals=pending_approvals,
     303:                 capabilities=AgentCapabilities(chat=is_local, agent_loop=is_local),
     304:             )
     305:
     306:     def _register_tools(self) -> None:
     307:         @self.tool()
   ...
     182:             raise KeyError(f"Agent {agent_id} not found in registry")
     183:         if (agent := self._agents[agent_id].agent) is None:
     184:             raise KeyError(f"Agent {agent_id} not yet initialized")
     185:         return agent
     186:
>>>  187:     async def get_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure:
>>>  188:         """Get infrastructure. Raises KeyError if not found."""
>>>  189:         return self._get_agent_or_raise(agent_id).running
>>>  190:
>>>  191:     def get_agent_mode(self, agent_id: AgentID) -> AgentMode:
>>>  192:         """Get agent mode. Raises KeyError if not found."""
>>>  193:         return self._get_agent_or_raise(agent_id).mode
>>>  194:
>>>  195:     def get_local_runtime(self, agent_id: AgentID) -> LocalAgentRuntime | None:
>>>  196:         """Get local runtime or None if bridge agent. Raises KeyError if not found."""
>>>  197:         return self._get_agent_or_raise(agent_id).local_runtime
>>>  198:
     199:     def register_local_agent(
     200:         self,
     201:         agent_id: AgentID,
     202:         running: RunningInfrastructure,
     203:         compositor_app: FastAPI,
```

### `duplicated-notification-data.yaml` / `occ-0`

File: `adgn/src/adgn/agent/notifications/types.py`

> notifications/types.py duplicates data in two ways: (1) NotificationsBatch
> (lines 14-30) stores both parsed fields (resources_updated, resource_list_changed)
> and raw MCP notifications, creating redundancy and unclear source of truth;
> (2) NotificationsBatch and NotificationsForModel (lines 33-51) represent the same
> data in different shapes (flat lists vs grouped by server).
>
> Problems: Parsed fields are derivable from raw, creating sync risk. Two classes
> for the same data. Manual deduplication. No single source of truth.
>
> Replace with single grouped representation: one class with dict[server, notices],
> parse once at construction via from_raw() classmethod, use frozenset for
> deduplication. Remove NotificationsForModel entirely.
>
> Benefits: Single source of truth (derived from raw on construction), no
> duplication, efficient lookups (grouped by server), helper methods for access
> patterns.
>
> Principle: Store data in ONE efficient representation, derive views on-demand.

```
       9:
      10:     server: str = Field(description="Origin MCP server name (derived)")
      11:     uri: str = Field(description="Resource URI string for the update")
      12:
      13:
>>>   14: class NotificationsBatch(BaseModel):
>>>   15:     """Buffered notifications ready to be injected as model input or observed by UI.
>>>   16:
>>>   17:     Fields
>>>   18:     - resources_updated: derived per-update events with server+URI
>>>   19:     - resource_list_changed: list of server names where resources/list changed
>>>   20:     - raw: full MCP notification payloads captured for display/debugging
>>>   21:     """
>>>   22:
>>>   23:     resources_updated: list[ResourceUpdateEvent] = Field(
>>>   24:         default_factory=list, description="Derived resource update events (server, uri, version)"
>>>   25:     )
>>>   26:     resource_list_changed: list[str] = Field(default_factory=list, description="Servers with resources/list changed")
>>>   27:     # Raw MCP server notifications captured (only resources notifications are buffered here)
>>>   28:     raw: list[mcp_types.ResourceUpdatedNotification | mcp_types.ResourceListChangedNotification] = Field(
>>>   29:         default_factory=list, description="Full MCP resources notifications captured for display/debugging"
>>>   30:     )
      31:
      32:
      33: class ResourcesServerNotice(BaseModel):
      34:     """Per-server resources notice.
      35:
   ...
      28:     raw: list[mcp_types.ResourceUpdatedNotification | mcp_types.ResourceListChangedNotification] = Field(
      29:         default_factory=list, description="Full MCP resources notifications captured for display/debugging"
      30:     )
      31:
      32:
>>>   33: class ResourcesServerNotice(BaseModel):
>>>   34:     """Per-server resources notice.
>>>   35:
>>>   36:     - updated: list of resource URIs updated for this server
>>>   37:     - list_changed: whether a resources/list_changed occurred for this server (best effort)
>>>   38:     """
>>>   39:
>>>   40:     updated: list[str] = Field(default_factory=list)
>>>   41:     list_changed: bool = False
>>>   42:
>>>   43:
>>>   44: class NotificationsForModel(BaseModel):
>>>   45:     """Top-level structured notification envelope used for message injection."""
>>>   46:
>>>   47:     resources: dict[str, ResourcesServerNotice] = Field(
>>>   48:         default_factory=dict, description="Per-server resources notice: {server -> {updated, list_changed}}"
>>>   49:     )
```

### `duplicated-xdg-paths.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/cli.py`

> The code constructs XDG user data directory paths (using `user_data_dir("adgn", ...)`)
> in multiple places instead of defining these paths once in a central location.
>
> **Current implementation:** Each module independently calls `user_data_dir("adgn", "agentydragon")`
> and constructs paths like `DEFAULT_DB_PATH = Path(...) / "mcp-bridge.db"` (mcp_bridge/cli.py, line 36).
>
> **Problems:**
>
> 1. Duplication: Same platformdirs call in multiple files
> 2. Inconsistency risk: Easy to use different app name/author
> 3. Hard to change: Must update multiple files
> 4. No discoverability: Can't easily find all data paths
> 5. Testing difficulty: Can't easily override base directory
>
> **The correct approach:**
> Create a central paths module (e.g., `adgn/paths.py`) that defines XDG directories once
> (USER_DATA_DIR, USER_CACHE_DIR, USER_CONFIG_DIR) and specific application paths
> (MCP_BRIDGE_DB, RESPONSES_CACHE_DB, AUTH_TOKENS_FILE, etc.). Import these constants
> throughout the codebase.
>
> **Benefits:**
>
> 1. Single source of truth for all paths
> 2. Guaranteed consistency in app name/author
> 3. Easy to add environment variable overrides once
> 4. Testable: can patch the paths module
> 5. Follows XDG Base Directory Specification correctly across platforms

```
      31: from adgn.agent.persist.sqlite import SQLitePersistence
      32:
      33: logger = logging.getLogger(__name__)
      34:
      35: # Default database path in XDG user data directory
>>>   36: DEFAULT_DB_PATH = Path(user_data_dir("adgn", "agentydragon")) / "mcp-bridge.db"
      37:
      38:
      39: @click.group()
      40: def cli():
      41:     """HTTP MCP Bridge - expose policy-gated infrastructure to external agents."""
```

### `explicit-constructions-ui.yaml` / `occ-0`

File: `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte`

> Lines 29-36 define `parseArgs()` using manual `JSON.parse()` that returns `{}` on error (silent
> failure). Lines 115-121 manually parse approval blocks with `JSON.parse()`, destructuring
> `agent_id`, `tool_call`, `timestamp` without validation.
>
> Manual JSON parsing loses: (1) validation (accepts any JSON structure), (2) type safety
> (`Record<string, unknown>` doesn't match actual shape), (3) error visibility (parseArgs
> silently returns empty object), (4) schema checking (can't detect missing/extra fields).
>
> Backend has `ToolCall` Pydantic model (agent/types.py:20-25) with `name`, `call_id`,
> `args_json` fields. Frontend should use Zod schemas generated from Pydantic models via
> `adgn/scripts/generate_types.py` (commit 7c6cae7ad) extended with `json-schema-to-zod`.
>
> Replace `JSON.parse()` with `PendingApprovalSchema.parse(data)` for runtime validation,
> detailed error messages, and single source of truth (Backend Pydantic → Frontend Zod).

```
      24:   let expandedApprovals = new Set<string>()
      25:
      26:   /**
      27:    * Parse tool call args_json to object
      28:    */
>>>   29:   function parseArgs(argsJson: string | null): Record<string, unknown> {
>>>   30:     if (!argsJson) return {}
>>>   31:     try {
>>>   32:       return JSON.parse(argsJson)
>>>   33:     } catch {
>>>   34:       return {}
>>>   35:     }
>>>   36:   }
      37:
      38:   // Group approvals by agent_id for display
      39:   $: groupedApprovals = approvals.reduce((acc, approval) => {
      40:     const agentId = approval.agent_id
      41:     if (!acc[agentId]) {
   ...
     110:     if (!mcpClient) return
     111:
     112:     try {
     113:       // Read the global approvals resource
     114:       const contents = await readResource(mcpClient, MCPUris.approvalsPendingUri)
>>>  115:
>>>  116:       // Parse contents - it returns an array of TextResourceContents
>>>  117:       // Each block has: { uri, mimeType, text }
>>>  118:       // The text field contains JSON with: { agent_id, tool_call: { name, call_id, args_json }, timestamp }
>>>  119:       const parsedApprovals: Array<PendingApproval & { agent_id: string }> = []
>>>  120:
>>>  121:       for (const block of contents) {
     122:         if ('text' in block && block.mimeType === 'application/json') {
     123:           try {
     124:             const data = JSON.parse(block.text)
     125:             parsedApprovals.push({
     126:               agent_id: data.agent_id,
```

### `json-output-constraint.yaml` / `occ-0`

File: `adgn/src/adgn/agent/policy_eval/runner.py`

> Line 80 uses `.strip().splitlines()[-1]` to extract the last line, which unnecessarily constrains the policy
> output to
> not contain newlines in the JSON. Valid JSON can span multiple lines.
>
> **Current implementation assumes:**
>
> - Policy output is line-based
> - JSON response is on the last line
> - JSON can't contain newlines
>
> **Why this is problematic:**
>
> Valid pretty-printed JSON output would break:
>
> ```json
> {
>   "decision": "allow",
>   "rationale": "Looks good"
> }
> ```
>
> Gets parsed as: `json.loads('"rationale": "Looks good"\n}')` → Error!
>
> **Correct approach:**
>
> Parse the entire output directly (ideally policy should output ONLY JSON, not mix debug output and JSON. If
> debug
> output
> is needed, send it to stderr, not stdout):
>
> ```python
> try:
>     return PolicyResponse.model_validate_json(logs.strip())
> except Exception as e:
>     text = logs.decode("utf-8", errors="replace")
>     raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
> ```

```
      75:             raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
      76:         try:
      77:             data = json.loads(text.strip().splitlines()[-1]) if text.strip() else {}
      78:         except Exception as e:
      79:             raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
>>>   80:         return PolicyResponse.model_validate(data)
      81:     finally:
      82:         try:
      83:             container.remove(force=True)
      84:         except (docker.errors.APIError, docker.errors.NotFound) as e:
      85:             logger.warning("policy eval container cleanup failed", exc_info=e)
```

### `manual-dict-parsing.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/events.py`

> The `parse_event()` function manually parses event dictionaries using if-elif
> chains that inspect the `type` field and construct the appropriate payload class.
> This is exactly what Pydantic's discriminated union parsing does automatically,
> but the code reimplements it by hand.
>
> **Current implementation (events.py, lines 67-100):**
> The code defines `TypedPayload` with `Field(discriminator=None)` and implements
> a 30+ line `parse_event()` function with manual if-elif dispatching for each
> event type (USER_TEXT, ASSISTANT_TEXT, TOOL_CALL, etc.), manually extracting
> fields from dictionaries and constructing payload objects.
>
> **Problems:**
>
> 1. **Reimplements Pydantic**: Manual if-elif dispatching duplicates what Pydantic does
> 2. **Error-prone**: Easy to forget cases or mismatch type strings
> 3. **Verbose**: 30 lines of manual parsing vs 3 lines with discriminated unions
> 4. **No validation**: Manual `str()` casts and `.get()` don't validate structure
> 5. **Inconsistent**: Some fields use TypeAdapter, others use manual dict access
> 6. **Misleading type hint**: `Field(discriminator=None)` suggests discriminated union but doesn't use it
> 7. **Maintenance burden**: Adding a new event type requires updating if-elif chain
>
> **The correct approach:**
>
> Use Pydantic's discriminated union parsing: add `Literal["type"]` to each
> payload class, set `Field(discriminator="type")` on the union, and use
> `model_validate()`. This reduces the 30+ line manual parser to a 3-line
> function that injects the type field into the payload dict before validation.
>
> **Benefits:**
>
> 1. **Automatic dispatch**: Pydantic handles type-based routing
> 2. **Full validation**: All fields validated according to payload schema
> 3. **Type safety**: Type checkers understand the discriminated union
> 4. **Concise**: 3 lines instead of 30+ lines of if-elif
> 5. **Better errors**: ValidationError shows exactly what's wrong
> 6. **Easy to extend**: Add new event type = add new payload class to union
> 7. **Declarative**: Schema describes what's valid, not how to parse

```
      42:     content: Response | None = None
      43:
      44:
      45: TypedPayload = Annotated[
      46:     UserTextPayload
>>>   47:     | AssistantTextPayload
>>>   48:     | ToolCallPayload
>>>   49:     | FunctionCallOutputPayload
>>>   50:     | ReasoningPayload
      51:     | ResponsePayload,
      52:     Field(discriminator=None),
      53: ]
      54:
      55:
   ...
      62:     tool_key: str | None = None
      63:
      64:     model_config = ConfigDict(extra="forbid")
      65:
      66:
>>>   67: def parse_event(d: dict[str, Any]) -> EventRecord:
>>>   68:     raw_type = d.get("type")
>>>   69:     et = EventType(str(raw_type))
>>>   70:     seq = int(d.get("seq", 0))
>>>   71:     ts_raw = d.get("ts")
>>>   72:     ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))
>>>   73:     call_id = d.get("call_id")
>>>   74:     tool_key = d.get("tool_key")
>>>   75:     payload_raw = d.get("payload") or {}
>>>   76:
>>>   77:     payload: TypedPayload
>>>   78:     if et == EventType.USER_TEXT:
>>>   79:         payload = UserTextPayload(text=str(payload_raw.get("text", "")))
>>>   80:     elif et == EventType.ASSISTANT_TEXT:
>>>   81:         payload = AssistantTextPayload(text=str(payload_raw.get("text", "")))
>>>   82:     elif et == EventType.TOOL_CALL:
>>>   83:         payload = ToolCallPayload(
>>>   84:             name=str(payload_raw.get("name", "")),
>>>   85:             args_json=payload_raw.get("args_json"),
>>>   86:             call_id=str(payload_raw.get("call_id") or d.get("call_id") or ""),
>>>   87:         )
>>>   88:     elif et == EventType.FUNCTION_CALL_OUTPUT:
>>>   89:         # Persisted payload is the Pydantic MCP CallToolResult JSON (alias field names)
>>>   90:         result = TypeAdapter(mcp_types.CallToolResult).validate_python(payload_raw)
>>>   91:         payload = FunctionCallOutputPayload(call_id=str(d.get("call_id") or ""), result=result)
>>>   92:     elif et == EventType.REASONING:
>>>   93:         payload = ReasoningPayload(text=str(payload_raw.get("text", "")))
>>>   94:     elif et == EventType.RESPONSE:
>>>   95:         payload = ResponsePayload(content=payload_raw)
>>>   96:     else:
>>>   97:         # Fallback to response-like envelope
>>>   98:         payload = ResponsePayload(content=payload_raw)
>>>   99:
>>>  100:     return EventRecord(seq=seq, ts=ts, type=et, payload=payload, call_id=call_id, tool_key=tool_key)
     101:
     102:
     103: def parse_events(items: list[dict[str, Any]]) -> list[EventRecord]:
     104:     return [parse_event(d) for d in items]
```

### `manual-indentation-loop.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> Manual loop to indent lines instead of using `textwrap.indent()` from standard library.
>
> **Current code (cli.py:573-574):**
>
> ```python
> for line in previous_message.splitlines():
>     final_text += f"# {line}\n"
> ```
>
> **Problems:**
>
> - Reimplements standard library functionality
> - More verbose than stdlib solution
> - Harder to test independently
> - Potential edge cases not handled (empty lines, trailing newlines)
>
> **Correct approach:**
>
> ```python
> final_text += textwrap.indent(previous_message, "# ", lambda line: True)
> ```
>
> **Benefits:**
>
> - Uses standard, tested library function
> - More concise (1 line vs 2 lines)
> - Clearer intent (obviously indenting text)
> - Handles edge cases correctly

```
     568:     repo: pygit2.Repository, msg: str, previous_message: str | None, stats_comment: str, passthru: list[str]
     569: ) -> int:
     570:     final_text = msg
     571:     if previous_message:
     572:         final_text += "\n\n# Previous commit message (being amended):\n"
>>>  573:         for line in previous_message.splitlines():
>>>  574:             final_text += f"# {line}\n"
     575:     final_text += stats_comment + build_commit_template(repo, passthru)
     576:
     577:     commit_msg_path = Path(repo.path) / "COMMIT_EDITMSG"
     578:     commit_msg_path.write_text(final_text)
     579:
```

### `manual-init-not-dataclass.yaml` / `occ-0`

File: `adgn/src/adgn/agent/policy_eval/container.py`

> Class (container.py:17-46) uses manual `__init__` for simple field
> initialization. The constructor does assignment-only initialization
> with no complex logic, perfect candidate for `@dataclass`.
>
> Benefits of dataclass: less boilerplate (no manual assignments), free
> `__repr__` for debugging, free `__eq__` for testing, type annotations
> serve as field declarations, standard Python idiom for data-holding
> classes. Use `__post_init__` if complex initialization needed.

```
      12: from adgn.agent.types import AgentID
      13:
      14: logger = logging.getLogger(__name__)
      15:
      16:
>>>   17: class ContainerPolicyEvaluator:
>>>   18:     """Evaluate policy decisions inside a one-off Docker container (isolated).
>>>   19:
>>>   20:     The active policy source is executed directly via `python -c <source>`; no
>>>   21:     per-agent volumes are required. The image must have the `adgn` package
>>>   22:     installed so the policy can import helpers. Network is disabled; no RW
>>>   23:     mounts; no container reuse.
>>>   24:     """
>>>   25:
>>>   26:     def __init__(
>>>   27:         self,
>>>   28:         *,
>>>   29:         agent_id: AgentID,
>>>   30:         docker_client: DockerClient,
>>>   31:         engine: ApprovalPolicyEngine,
>>>   32:         image: str | None = None,
>>>   33:         timeout_secs: float | None = None,
>>>   34:     ) -> None:
>>>   35:         if not agent_id:
>>>   36:             raise ValueError("ContainerPolicyEvaluator requires agent_id")
>>>   37:         self.agent_id = agent_id
>>>   38:         self.image: str = image or resolve_runtime_image()
>>>   39:         self.timeout_secs = (
>>>   40:             timeout_secs if timeout_secs is not None else float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
>>>   41:         )
>>>   42:         self._docker = docker_client
>>>   43:         self._engine = engine
>>>   44:
>>>   45:     async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
>>>   46:         """Evaluate using the current policy source via run_policy_source."""
      47:         payload = {"name": policy_input.name, "arguments": policy_input.arguments}
      48:         policy_src, _ver = self._engine.get_policy()
      49:         return run_policy_source(
      50:             docker_client=self._docker,
      51:             source=policy_src,
```

### `manual-isinstance-validation.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/auth.py`

> The `reload()` method manually validates that the loaded JSON is a dict with string
> keys and values using `isinstance()` checks, but this can be done automatically and
> more robustly using Pydantic's `TypeAdapter`.
>
> **Current implementation:** Manual validation loop checking isinstance on each token/agent_id
> pair, raising generic ValueError on mismatch (auth.py, lines 60-69).
>
> **Problems:**
>
> 1. Verbose hand-written isinstance checks
> 2. Easy to miss edge cases (None, numbers)
> 3. Poor error messages (generic ValueError without location)
> 4. Not composable or reusable
> 5. Incomplete validation of nested structure
>
> **The correct approach:**
> Use Pydantic's `TypeAdapter(dict[str, AgentID])` to validate and parse in one step.
> Can call `validate_python(data)` after `json.loads()` or `validate_json(text)` directly.
>
> **Benefits:**
>
> 1. Automatic validation with better error messages showing exact path
> 2. Type-safe: TypeAdapter knows the shape is `dict[str, AgentID]`
> 3. Concise: 1 line instead of 10 lines of manual validation
> 4. Robust: handles edge cases correctly
> 5. Composable: can reuse the adapter elsewhere

```
      55:         """Reload mapping from file."""
      56:         if not self.path.exists():
      57:             raise FileNotFoundError(f"Token mapping file not found: {self.path}")
      58:
      59:         data = json.loads(self.path.read_text())
>>>   60:         if not isinstance(data, dict):
>>>   61:             raise ValueError("Token mapping must be a JSON object")
>>>   62:
>>>   63:         # Validate all values are strings and convert to AgentID
>>>   64:         mapping: dict[str, AgentID] = {}
>>>   65:         for token, agent_id in data.items():
>>>   66:             if not isinstance(token, str) or not isinstance(agent_id, str):
>>>   67:                 raise ValueError(f"Invalid mapping: {token} -> {agent_id}")
>>>   68:             mapping[token] = AgentID(agent_id)
>>>   69:
      70:         self._mapping = mapping
      71:         logger.info(f"Loaded {len(self._mapping)} token mappings from {self.path}")
      72:
      73:     def get_agent_id(self, token: str) -> AgentID | None:
      74:         """Get agent_id for a token, or None if not found."""
```

### `manual-json-parsing.yaml` / `occ-0`

File: `adgn/src/adgn/agent/policy_eval/runner.py`

> Line 80 does `json.loads(...)` to parse JSON, then passes the dict to `PolicyResponse.model_validate(data)`.
> Pydantic
> provides `model_validate_json()` which does both steps in one call and is more efficient.
>
> **Benefits of model_validate_json():**
>
> - Pydantic's JSON parser is faster (uses Rust)
> - Works directly on bytes (no decode needed for success case)
> - One-step parsing and validation
> - Better error messages from Pydantic
>
> **Correct approach:**
>
> Use `model_validate_json()` directly on bytes:
>
> ```python
> logs = container.logs(stdout=True, stderr=True) or b""
> if status != 0:
>     text = logs.decode("utf-8", errors="replace")
>     raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
> try:
>     return PolicyResponse.model_validate_json(logs.strip())
> except Exception as e:
>     text = logs.decode("utf-8", errors="replace")
>     raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
> ```

```
      71:         status = int(res.get("StatusCode", 1)) if isinstance(res, dict) else 1
      72:         logs = container.logs(stdout=True, stderr=True) or b""
      73:         text = logs.decode("utf-8", errors="replace")
      74:         if status != 0:
      75:             raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
>>>   76:         try:
>>>   77:             data = json.loads(text.strip().splitlines()[-1]) if text.strip() else {}
>>>   78:         except Exception as e:
>>>   79:             raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
>>>   80:         return PolicyResponse.model_validate(data)
>>>   81:     finally:
>>>   82:         try:
>>>   83:             container.remove(force=True)
      84:         except (docker.errors.APIError, docker.errors.NotFound) as e:
      85:             logger.warning("policy eval container cleanup failed", exc_info=e)
```

### `mixed-exit-code-conventions.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> Functions inconsistently mix two conventions for signaling exit codes: some declare
> `-> int` return types but actually raise `ExitWithCode` exceptions on error paths.
>
> **Evidence:**
>
> - `_commit_immediately` (lines 558-564): declared `-> int`, but raises `ExitWithCode(1)` on some paths
> - `_run_editor_flow` (lines 567-609): declared `-> int`, but has 7 paths that raise `ExitWithCode`
> - Callers (lines 728-732): expect int return, but `sys.exit(code)` is unreachable when exception raised
>
> **Problems:**
>
> 1. Type lies: functions promise `-> int` but raise exceptions, violating contracts
> 2. Unreachable code: code after exception-raising calls never executes
> 3. Easy to forget: callers must remember BOTH to check returns AND catch exceptions
> 4. No guidance: new code has no clear pattern to follow
>
> **Fix:** Pick ONE convention consistently. Option A (always raise exceptions, change
> signatures to `-> None`): impossible to forget, clear failure paths, consistent with
> Python's `SystemExit`. Option B (always return int): never raise, always return codes.
> Mixing both violates type contracts and creates ad-hoc error handling.

```
     546:         f"\n# ai-draft{'(cached)' if cached else ''}: prompt: {len(diff)} chars, "
     547:         f"response: {len(msg)} chars, elapsed: {elapsed_s:.2f}s\n"
     548:     )
     549:
     550:
>>>  551: class ExitWithCode(Exception):  # noqa: N818
>>>  552:     # TODO: Reconsider whether signalling exit codes via exceptions is the best approach
>>>  553:     def __init__(self, code: int):
>>>  554:         super().__init__(str(code))
>>>  555:         self.code = code
>>>  556:
     557:
     558: async def _commit_immediately(msg: str, passthru: list[str]) -> int:
     559:     if not msg.strip():
     560:         print("Aborting commit due to empty AI commit message.", file=sys.stderr)
     561:         raise ExitWithCode(1)
   ...
     553:     def __init__(self, code: int):
     554:         super().__init__(str(code))
     555:         self.code = code
     556:
     557:
>>>  558: async def _commit_immediately(msg: str, passthru: list[str]) -> int:
>>>  559:     if not msg.strip():
>>>  560:         print("Aborting commit due to empty AI commit message.", file=sys.stderr)
>>>  561:         raise ExitWithCode(1)
>>>  562:     commit_passthru = filter_commit_passthru(passthru)
>>>  563:     commit_proc = await asyncio.create_subprocess_exec("git", "commit", "-m", msg, "--no-verify", *commit_passthru)
>>>  564:     return await commit_proc.wait()
     565:
     566:
     567: async def _run_editor_flow(
     568:     repo: pygit2.Repository, msg: str, previous_message: str | None, stats_comment: str, passthru: list[str]
     569: ) -> int:
   ...
     562:     commit_passthru = filter_commit_passthru(passthru)
     563:     commit_proc = await asyncio.create_subprocess_exec("git", "commit", "-m", msg, "--no-verify", *commit_passthru)
     564:     return await commit_proc.wait()
     565:
     566:
>>>  567: async def _run_editor_flow(
>>>  568:     repo: pygit2.Repository, msg: str, previous_message: str | None, stats_comment: str, passthru: list[str]
>>>  569: ) -> int:
>>>  570:     final_text = msg
>>>  571:     if previous_message:
>>>  572:         final_text += "\n\n# Previous commit message (being amended):\n"
>>>  573:         for line in previous_message.splitlines():
>>>  574:             final_text += f"# {line}\n"
>>>  575:     final_text += stats_comment + build_commit_template(repo, passthru)
>>>  576:
>>>  577:     commit_msg_path = Path(repo.path) / "COMMIT_EDITMSG"
>>>  578:     commit_msg_path.write_text(final_text)
>>>  579:
>>>  580:     mtime_before = commit_msg_path.stat().st_mtime
>>>  581:     content_before = final_text
>>>  582:
>>>  583:     editor = await _get_editor()
>>>  584:     editor_proc = await asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")
>>>  585:     if (rc := await editor_proc.wait()) != 0:
>>>  586:         print(f"Aborting commit: editor exited with code {rc} (e.g., :cq)", file=sys.stderr)
>>>  587:         raise ExitWithCode(1)
>>>  588:
>>>  589:     try:
>>>  590:         final_content = commit_msg_path.read_text()
>>>  591:         mtime_after = commit_msg_path.stat().st_mtime
>>>  592:         saved = mtime_after != mtime_before
>>>  593:         changed = final_content.rstrip("\n") != content_before
>>>  594:         if not saved and not changed:
>>>  595:             print("Aborting commit: editor closed without saving (unchanged commit message).", file=sys.stderr)
>>>  596:             raise ExitWithCode(1)
>>>  597:     except FileNotFoundError:
>>>  598:         print("Aborting commit.", file=sys.stderr)
>>>  599:         raise ExitWithCode(1)
>>>  600:
>>>  601:     content_lines: list[str] = []
>>>  602:     for line in final_content.splitlines():
>>>  603:         if line.startswith(SCISSORS_MARK):
>>>  604:             break
>>>  605:         if line.strip() and not line.strip().startswith("#"):
>>>  606:             content_lines.append(line)
>>>  607:     if not content_lines:
>>>  608:         print("Aborting commit due to empty commit message.", file=sys.stderr)
>>>  609:         raise ExitWithCode(1)
     610:
     611:     commit_passthru = filter_commit_passthru(passthru)
     612:     commit_proc = await asyncio.create_subprocess_exec(
     613:         "git", "commit", "-F", commit_msg_path, "--cleanup=strip", "--no-verify", *commit_passthru
     614:     )
   ...
     723:
     724:         elapsed_s = time.monotonic() - start_monotonic_s
     725:         stats_comment = _make_stats_comment(cached, diff, msg, elapsed_s)
     726:
     727:         if args.accept_ai:
>>>  728:             code = await _commit_immediately(msg, passthru)
>>>  729:             sys.exit(code)
>>>  730:
>>>  731:         code = await _run_editor_flow(repo, msg, previous_message, stats_comment, passthru)
>>>  732:         sys.exit(code)
     733:     except ExitWithCode as e:
     734:         sys.exit(e.code)
     735:
     736:
     737: def main():
```

### `raw-sql-instead-of-orm.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/sqlite.py`

> Query (sqlite.py:145-165) uses raw SQL with `text()` instead of SQLAlchemy
> ORM constructs. The function executes a SELECT with GROUP BY and COALESCE
> using string-based column references.
>
> Problems with raw SQL: not type-safe (columns as strings), not portable
> (SQL syntax varies), hard to maintain (refactoring tools don't track
> renames), poor error messages (runtime vs import time), no IDE navigation.
>
> Fix: use SQLAlchemy ORM with `session.query(Run.agent_id, func.coalesce(...)).group_by()`.
> Benefits: type-safe references, database portability, refactoring support,
> better errors, IDE navigation.

```
     140:                 created_at=agent.created_at,
     141:                 mcp_config=MCPConfig.model_validate(agent.mcp_config) if agent.mcp_config else MCPConfig(),
     142:                 preset=agent.preset,
     143:             )
     144:
>>>  145:     async def list_agents_last_activity(self) -> dict[AgentID, datetime | None]:
>>>  146:         """Return a mapping of agent_id -> last activity timestamp (UTC) or None.
>>>  147:
>>>  148:         Activity considers any of: event event_at, run finished_at, run started_at, or
>>>  149:         agent created_at as a fallback, taking the maximum.
>>>  150:         """
>>>  151:         async with self._session() as session:
>>>  152:             # This is complex to do purely in ORM, so we'll use raw SQL
>>>  153:             result = await session.execute(
>>>  154:                 text("""
>>>  155: SELECT a.id as agent_id,
>>>  156:        MAX(
>>>  157:          COALESCE(e.event_at, r.finished_at, r.started_at, a.created_at)
>>>  158:        ) as last_ts
>>>  159: FROM agents a
>>>  160: LEFT JOIN runs r ON r.agent_id = a.id
>>>  161: LEFT JOIN events e ON e.run_id = r.id
>>>  162: GROUP BY a.id
>>>  163:                     """)
>>>  164:             )
>>>  165:             return {AgentID(row.agent_id): row.last_ts for row in result}
     166:
     167:     async def delete_agent(self, agent_id: AgentID) -> None:
     168:         """Delete an agent and all associated records (cascaded by ORM)."""
     169:         async with self._session() as session:
     170:             await session.execute(delete(Agent).where(Agent.id == agent_id))
```

### `redundant-exit-handler.yaml` / `occ-0`

File: `adgn/src/adgn/git_commit_ai/cli.py`

> cli.py async_main() (lines 659-734) has a try-except handler that catches
> ExitWithCode exceptions only to immediately call sys.exit() with the same code.
> This adds 4 lines and indents 70+ lines of main logic for no benefit.
>
> Problems: (1) redundant indentation of all main logic, (2) handler doesn't
> transform, log, or enrich the exit code, (3) misleading - suggests special
> handling that doesn't exist, (4) verbosity.
>
> Remove the try-except entirely. Let ExitWithCode propagate to the top level;
> Python's default behavior will still terminate with the exit code. Or if clean
> exit is needed, the existing sys.exit() calls at the end are sufficient.
>
> Benefits: 4 fewer lines, one less indent level, clearer code without false
> suggestion of special handling. Top-level functions typically don't catch their
> own exit exceptions.

```
     655:     result_stdout = stdout.decode() if stdout else ""
     656:     return result_stdout.strip() if proc.returncode == 0 else os.environ.get("EDITOR", "vi")
     657:
     658:
     659: async def async_main(argv: list[str] | None = None):
>>>  660:     try:
     661:         start_monotonic_s = time.monotonic()
     662:         gitdir = pygit2.discover_repository(str(Path.cwd()))
     663:         if not gitdir:
     664:             print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
     665:             raise ExitWithCode(128)
   ...
     728:             code = await _commit_immediately(msg, passthru)
     729:             sys.exit(code)
     730:
     731:         code = await _run_editor_flow(repo, msg, previous_message, stats_comment, passthru)
     732:         sys.exit(code)
>>>  733:     except ExitWithCode as e:
>>>  734:         sys.exit(e.code)
     735:
     736:
     737: def main():
     738:     asyncio.run(async_main())
     739:
```

### `redundant-policy-error-enum.yaml` / `occ-0`

File: `adgn/src/adgn/agent/models/policy_error.py`

> Lines 9-11 define `PolicyErrorCode` enum with `READ_ERROR` and `PARSE_ERROR` values. Lines 14-17
> define `PolicyErrorStage` enum with `READ`, `PARSE`, and `TESTS` values. Lines 21-22 in `PolicyError`
> model include both `stage: PolicyErrorStage` and `code: PolicyErrorCode` fields.
>
> These enums are redundant: error code is always stage + "\_error" suffix. Having both requires
> keeping enums in sync when adding stages, creates confusing dual representation, and leaves TESTS
> stage without corresponding error code. PolicyError fields are redundant (code fully determined by stage).
>
> Keep only `PolicyErrorStage` enum. Remove `code` field from `PolicyError` model (lines 21-22) or
> add `@property def code()` that returns `f"{self.stage}_error"` for backwards compatibility. Alternatively,
> merge into single unified enum with `READ_ERROR`, `PARSE_ERROR`, `TESTS_ERROR` values. Eliminates
> duplication, easier maintenance, no mismatch risk, complete coverage.

```
       4: from typing import Literal
       5:
       6: from pydantic import BaseModel, ConfigDict, Field
       7:
       8:
>>>    9: class PolicyErrorCode(StrEnum):
>>>   10:     READ_ERROR = "read_error"
>>>   11:     PARSE_ERROR = "parse_error"
      12:
      13:
      14: class PolicyErrorStage(StrEnum):
      15:     READ = "read"
      16:     PARSE = "parse"
   ...
       9: class PolicyErrorCode(StrEnum):
      10:     READ_ERROR = "read_error"
      11:     PARSE_ERROR = "parse_error"
      12:
      13:
>>>   14: class PolicyErrorStage(StrEnum):
>>>   15:     READ = "read"
>>>   16:     PARSE = "parse"
>>>   17:     TESTS = "tests"
      18:
      19:
      20: class PolicyError(BaseModel):
      21:     stage: PolicyErrorStage = Field(description="Processing stage where error occurred")
      22:     code: PolicyErrorCode = Field(description="Error code (read_error, parse_error)")
   ...
      16:     PARSE = "parse"
      17:     TESTS = "tests"
      18:
      19:
      20: class PolicyError(BaseModel):
>>>   21:     stage: PolicyErrorStage = Field(description="Processing stage where error occurred")
>>>   22:     code: PolicyErrorCode = Field(description="Error code (read_error, parse_error)")
      23:     index: int | None = Field(None, description="Character/token index where error occurred")
      24:     length: int | None = Field(None, description="Length of error span in characters/tokens")
      25:     message: str | None = Field(None, description="Human-readable error message")
      26:
      27:     model_config = ConfigDict(extra="forbid")
```

### `redundant-runtime-type-check.yaml` / `occ-0`

File: `adgn/src/adgn/agent/policy_eval/container.py`

> Redundant runtime type check for parameter when type system already guarantees non-None.
>
> **Current code (container.py:34-35):**
>
> ```python
> def __init__(self, agent_id: AgentID, ...):
>     if not agent_id:
>         raise ValueError("ContainerPolicyEvaluator requires agent_id")
> ```
>
> The type annotation `agent_id: AgentID` (not `AgentID | None`) already guarantees
> the parameter is provided. This check adds defensive programming noise without value.
>
> **The correct approach:**
>
> Remove the check. The type system guarantees `agent_id` is present. If you need
> to validate empty strings, add validation to the `AgentID` type itself:
>
> ```python
> class AgentID(str):
>     def __new__(cls, value: str):
>         if not value:
>             raise ValueError("AgentID cannot be empty")
>         return super().__new__(cls, value)
> ```
>
> This centralizes validation at the type level, not at every usage site.
>
> **Benefits:**
>
> - Less code
> - Type system is the source of truth
> - No redundant checks at call sites
> - Validation happens once (at type construction)

```
      29:         agent_id: AgentID,
      30:         docker_client: DockerClient,
      31:         engine: ApprovalPolicyEngine,
      32:         image: str | None = None,
      33:         timeout_secs: float | None = None,
>>>   34:     ) -> None:
>>>   35:         if not agent_id:
      36:             raise ValueError("ContainerPolicyEvaluator requires agent_id")
      37:         self.agent_id = agent_id
      38:         self.image: str = image or resolve_runtime_image()
      39:         self.timeout_secs = (
      40:             timeout_secs if timeout_secs is not None else float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
```

### `runtime-lifecycle-confusion.yaml` / `occ-0`

File: `adgn/src/adgn/agent/runtime/local_runtime.py`

> `LocalAgentRuntime` has lifecycle issues: missing type annotations
> (ui_bus, connection_manager at 81-82), "may be initialized" antipattern
> (session/agent nullable at 85-88, runtime checks at 155-158), incomplete
> cleanup (close() doesn't null fields at 160-165), and not being a proper
> context manager despite having start()/close() methods.
>
> "May be initialized" antipattern impact: object exists but isn't usable
> (half-initialized), every method must check initialization, type system
> can't help (fields are `T | None`), easy to forget start() call.
>
> Solutions: (1) async context manager (move start() logic to **aenter**,
> cleanup to **aexit**, automatic lifecycle, strong types, guaranteed
> cleanup), or (2) factory pattern (classmethod create() with async init,
> manual lifecycle but strong types).
>
> Current approach: manual unclear lifecycle, weak type safety, incomplete
> cleanup.

```
      76:     ):
      77:         self.running = running
      78:         self.model = model
      79:         self._client_factory = client_factory
      80:         self._system_override = system_override
>>>   81:         self._reasoning_effort = reasoning_effort
>>>   82:         self._reasoning_summary = reasoning_summary
      83:         self._parallel_tool_calls = parallel_tool_calls
      84:         self._extra_handlers = list(extra_handlers)
      85:         self._ui_bus = ui_bus
      86:         self._connection_manager = connection_manager
      87:
   ...
      80:         self._system_override = system_override
      81:         self._reasoning_effort = reasoning_effort
      82:         self._reasoning_summary = reasoning_summary
      83:         self._parallel_tool_calls = parallel_tool_calls
      84:         self._extra_handlers = list(extra_handlers)
>>>   85:         self._ui_bus = ui_bus
>>>   86:         self._connection_manager = connection_manager
>>>   87:
>>>   88:         # Initialized by start()
      89:         self.session: AgentSession | None = None
      90:         self.agent: MiniCodex | None = None
      91:
      92:     async def start(self) -> None:
      93:         # Create session with UI components if provided
   ...
      85:         self._ui_bus = ui_bus
      86:         self._connection_manager = connection_manager
      87:
      88:         # Initialized by start()
      89:         self.session: AgentSession | None = None
>>>   90:         self.agent: MiniCodex | None = None
>>>   91:
>>>   92:     async def start(self) -> None:
>>>   93:         # Create session with UI components if provided
>>>   94:         sess = AgentSession(
>>>   95:             manager=self._connection_manager,
>>>   96:             approval_hub=self.running.approval_hub,
>>>   97:             persistence=self.running.approval_engine.persistence,
>>>   98:             agent_id=self.running.agent_id,
>>>   99:             ui_bus=self._ui_bus,
>>>  100:             approval_engine=self.running.approval_engine,
>>>  101:         )
>>>  102:
>>>  103:         # LLM client
>>>  104:         client = self._client_factory(self.model)
>>>  105:
>>>  106:         # Define run ID helper
>>>  107:         def _get_run_id():
>>>  108:             return sess.active_run.run_id if sess.active_run else None
>>>  109:
>>>  110:         # Build handlers
>>>  111:         handlers, persist_handler = build_handlers(
>>>  112:             poll_notifications=self.running.notifications_buffer.poll,
>>>  113:             manager=self._connection_manager,
>>>  114:             persistence=self.running.approval_engine.persistence,
>>>  115:             approval_engine=self.running.approval_engine,
>>>  116:             approval_hub=self.running.approval_hub,
>>>  117:             get_run_id=_get_run_id,
>>>  118:             agent_id=self.running.agent_id,
>>>  119:             ui_bus=self._ui_bus,
>>>  120:         )
>>>  121:
>>>  122:         # Set persist handler on session
>>>  123:         sess.set_persist_handler(persist_handler)
>>>  124:
>>>  125:         # Compose base system text and dynamic instruction provider
>>>  126:         base_system = self._system_override or str(get_ui_system_message())
>>>  127:
>>>  128:         async def _dynamic_instructions() -> str:
>>>  129:             """Dynamically generate instructions from compositor state."""
>>>  130:             meta = CompositorMetaClient(self.running.compositor_client)
>>>  131:             states = await meta.list_states()
>>>  132:             text: str = render_compositor_instructions(states)
>>>  133:             return text
>>>  134:
>>>  135:         # Create agent
>>>  136:         agent = await MiniCodex.create(
>>>  137:             model=self.model,
>>>  138:             mcp_client=self.running.compositor_client,
>>>  139:             system=base_system,
>>>  140:             client=client,
>>>  141:             handlers=list(handlers) + self._extra_handlers,
>>>  142:             dynamic_instructions=_dynamic_instructions,
>>>  143:             reasoning_effort=self._reasoning_effort,
>>>  144:             reasoning_summary=self._reasoning_summary,
>>>  145:             parallel_tool_calls=self._parallel_tool_calls,
>>>  146:         )
>>>  147:
>>>  148:         # Store system used for persisted run metadata
>>>  149:         sess.attach_agent(agent, model=self.model, system=base_system)
>>>  150:
>>>  151:         # Store references
>>>  152:         self.session = sess
>>>  153:         self.agent = agent
     154:
     155:     async def run(self, user_text: str) -> AgentResult:
     156:         """Raises RuntimeError if agent not started."""
     157:         if self.agent is None:
     158:             raise RuntimeError("agent not started - call start() first")
   ...
     150:
     151:         # Store references
     152:         self.session = sess
     153:         self.agent = agent
     154:
>>>  155:     async def run(self, user_text: str) -> AgentResult:
>>>  156:         """Raises RuntimeError if agent not started."""
>>>  157:         if self.agent is None:
>>>  158:             raise RuntimeError("agent not started - call start() first")
     159:
     160:         return await self.agent.run(user_text)
     161:
     162:     async def close(self) -> None:
     163:         """Does NOT close the underlying RunningInfrastructure.
   ...
     155:     async def run(self, user_text: str) -> AgentResult:
     156:         """Raises RuntimeError if agent not started."""
     157:         if self.agent is None:
     158:             raise RuntimeError("agent not started - call start() first")
     159:
>>>  160:         return await self.agent.run(user_text)
>>>  161:
>>>  162:     async def close(self) -> None:
>>>  163:         """Does NOT close the underlying RunningInfrastructure.
>>>  164:         Call running.close() separately if needed.
>>>  165:         """
     166:         if self.session is not None:
     167:             await self.session.cancel_active_run()
```

### `silent-future-done-check.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> approve() and reject() tools in ApprovalHub check if a future is already done,
> but silently ignore this case instead of raising an error.
> If the future is already `.done()`, the code silently:
>
> - Doesn't set the result
> - Doesn't notify about the problem
> - Returns success status {"status": "approved"}
> - Could mask race conditions or double-approval bugs
>
> This can happen (for example) if:
>
> 1. User clicks "Approve" twice in quick succession
> 2. Two UI clients try to approve the same call_id
>
> **Why this is bad:**
>
> 1. **Hides bugs** (race conditions or double-processing silently ignored)
> 2. **Misleading response**: Returns success when request was not processed
> 3. **No visibility**: No log, no error, no way to detect the problem occurred
> 4. **Data integrity**: The fact that the future was already resolved might indicate
>    a serious bug that should be investigated, not hidden
>
> **Fix:** Raise an error if the future is already done, or at least return a warning in tool result
> to caller. Same fix needed for reject().
>
> Benefits of raising:
>
> - Fail-fast behavior catches bugs early
> - Clear signal that something unexpected happened
> - Prevents silent corruption of approval state
> - Forces callers to handle the race condition properly

```
     180:
     181:             Returns:
     182:                 Dictionary confirming the approval
     183:             """
     184:             # Inline resolve logic
>>>  185:             pending = self._pending.pop(call_id, None)
>>>  186:             if pending is not None and not pending.future.done():
>>>  187:                 pending.future.set_result(ContinueDecision(reasoning=reasoning))
>>>  188:             await self.notify_approvals_changed()
>>>  189:             return {"status": "approved", "call_id": call_id, "agent_id": self._agent_id}
     190:
     191:         @self.tool()
     192:         async def reject(call_id: str, reasoning: str | None = None) -> dict:
     193:             """Reject a pending tool call.
     194:
   ...
     194:
     195:             Returns:
     196:                 Dictionary confirming the rejection
     197:             """
     198:             # Inline resolve logic
>>>  199:             pending = self._pending.pop(call_id, None)
>>>  200:             if pending is not None and not pending.future.done():
>>>  201:                 pending.future.set_result(DenyContinueDecision(reason=reasoning or "Rejected by user"))
>>>  202:             await self.notify_approvals_changed()
>>>  203:             return {"status": "rejected", "call_id": call_id, "agent_id": self._agent_id}
     204:
     205:     async def notify_approvals_changed(self) -> None:
     206:         """Notify that approvals have changed."""
     207:         await self.broadcast_resource_updated("resource://approvals")
     208:
```

### `state-redundant-compositor.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/status_shared.py`

> status_shared.py AgentStatusCore duplicates data available via the 2-layer
> compositor. Three fields (mcp: McpState lines 76-78, policy: PolicyState lines
> 66-68, pending_approvals: int line 91) wrap compositor resources without adding
> behavior.
>
> Impact: Type indirection (must access .entries for data), manual state tracking
> instead of querying compositor, sync risks between custom status and MCP
> resources, redundant APIs.
>
> These fields map to MCP resources: mcp → resources://compositor/servers,
> policy → resources://approval-policy/policy.py, pending_approvals →
> len(resources://approval-policy/pending).
>
> Remove the three redundant fields from AgentStatusCore. Clients should query
> MCP resources directly for server state, policy, and pending approvals.
>
> Benefits: Single source of truth (MCP resources authoritative), automatic updates
> via resource subscriptions, consistent interface, simpler status model containing
> only non-MCP state.
>
> Principle: Don't duplicate MCP-available data in custom APIs. Let clients use
> standard MCP protocol to avoid sync issues.

```
      61:     STARTING = "starting"
      62:     READY = "ready"
      63:
      64:
      65: """Status models and builder (no host volumes reported)."""
>>>   66:
>>>   67:
>>>   68: class PolicyState(BaseModel):
      69:     id: int | None = None
      70:     model_config = ConfigDict(extra="forbid")
      71:
      72:
      73: class UiStateLite(BaseModel):
   ...
      71:
      72:
      73: class UiStateLite(BaseModel):
      74:     ready: bool
      75:     model_config = ConfigDict(extra="forbid")
>>>   76:
>>>   77:
>>>   78: class McpState(BaseModel):
      79:     entries: dict[str, ServerEntry]
      80:     model_config = ConfigDict(extra="forbid")
      81:
      82:
      83: class ContainerState(BaseModel):
   ...
      86:     ephemeral: bool
      87:     model_config = ConfigDict(extra="forbid")
      88:
      89:
      90: class AgentStatusCore(BaseModel):
>>>   91:     id: str
      92:     live: bool
      93:     active_run_id: UUID | None
      94:     lifecycle: AgentLifecycle
      95:     run_phase: RunPhase
      96:     policy: PolicyState
```

### `ui-factories-helpers-missing.yaml` / `occ-0`

File: `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte`

> GlobalApprovalsList.svelte contains explicit tool/resource constructions at 6 locations instead
> of using factories/helpers with defaults: MCP client creation (line 69: createMCPClient with
> name/url/token), resource subscription (line 78: subscribeToResource with URI), resource reading
> (line 107: readResource with URI), approval parsing (lines 115-121: manual object construction
> with agent_id/tool_call/timestamp), approve tool call (lines 138-142: callTool with approve_tool_call
> and agent_id/call_id), reject tool call (lines 175-180: callTool with reject_tool_call and
> agent_id/call_id/reason).
>
> This creates verbose boilerplate (repeated patterns), no default values (must specify all parameters),
> hard to test (can't mock without recreating full objects), duplication (same patterns across component),
> and fragile (API changes require updating many call sites).
>
> Create factories/helpers: `createApprovalsClient(options?)` with default name/url/token,
> `fetchPendingApprovals(client)`, `approveToolCall(client, agentId, callId)`,
> `parseApprovalContents(contents)`. Provides default values, centralized logic, easier testing
> (mock helpers not raw calls), type safety, less duplication.

```
      64:         throw new Error('No authentication token available')
      65:       }
      66:
      67:       // Connect to MCP server (requires backend to expose MCP endpoint)
      68:       // In a full implementation, this would connect to something like:
>>>   69:       // http://localhost:8765/api/mcp
>>>   70:       mcpClient = await createMCPClient({
>>>   71:         name: 'global-approvals-ui',
      72:         url: `${window.location.origin}/api/mcp`,
      73:         token
      74:       })
      75:
      76:       // Subscribe to resource updates for live refresh
   ...
      73:         token
      74:       })
      75:
      76:       // Subscribe to resource updates for live refresh
      77:       // NOTE: Subscription support would need to be added to the backend
>>>   78:       try {
      79:         await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
      80:       } catch (e) {
      81:         console.warn('Subscription not supported, will use polling:', e)
      82:       }
      83:
   ...
     102:
     103:   /**
     104:    * Fetch all pending approvals from the global mailbox
     105:    *
     106:    * The resource://approvals/pending resource returns multiple TextResourceContents blocks,
>>>  107:    * where each block contains a JSON-serialized approval.
     108:    */
     109:   async function fetchApprovals() {
     110:     if (!mcpClient) return
     111:
     112:     try {
   ...
     110:     if (!mcpClient) return
     111:
     112:     try {
     113:       // Read the global approvals resource
     114:       const contents = await readResource(mcpClient, MCPUris.approvalsPendingUri)
>>>  115:
>>>  116:       // Parse contents - it returns an array of TextResourceContents
>>>  117:       // Each block has: { uri, mimeType, text }
>>>  118:       // The text field contains JSON with: { agent_id, tool_call: { name, call_id, args_json }, timestamp }
>>>  119:       const parsedApprovals: Array<PendingApproval & { agent_id: string }> = []
>>>  120:
>>>  121:       for (const block of contents) {
     122:         if ('text' in block && block.mimeType === 'application/json') {
     123:           try {
     124:             const data = JSON.parse(block.text)
     125:             parsedApprovals.push({
     126:               agent_id: data.agent_id,
   ...
     133:         }
     134:       }
     135:
     136:       approvals = parsedApprovals
     137:       error = null
>>>  138:
>>>  139:     } catch (e) {
>>>  140:       error = `Failed to fetch approvals: ${e instanceof Error ? e.message : String(e)}`
>>>  141:       console.error('Fetch error:', e)
>>>  142:     }
     143:   }
     144:
     145:   /**
     146:    * Approve a tool call via MCP tool
     147:    */
   ...
     170:   /**
     171:    * Show rejection dialog
     172:    */
     173:   function showRejectDialogFor(agentId: string, callId: string) {
     174:     rejectAgentId = agentId
>>>  175:     rejectCallId = callId
>>>  176:     rejectReason = ''
>>>  177:     showRejectDialog = true
>>>  178:   }
>>>  179:
>>>  180:   /**
     181:    * Reject a tool call via MCP tool with reason
     182:    */
     183:   async function handleReject() {
     184:     if (!mcpClient || !rejectReason.trim()) return
     185:
```

### `unimplemented-websocket.yaml` / `occ-0`

File: `adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte`

> Four Svelte components create independent MCP client connections: AgentsSidebar (line 85), ChatPane
> (lines 87-91 and 124-128 - TWO separate clients in same component), MessageComposer (lines 16-20),
> and GlobalApprovalsList (lines 69-71 targeting non-existent /api/mcp endpoint).
>
> Each client creation involves handshake, auth, session setup, and dedicated connection. This wastes
> resources (multiple WebSocket/HTTP connections, repeated handshakes, memory/file descriptors), violates
> 2-level compositor architecture (intended: UI → shared client → compositor; actual: parallel connections),
> creates inconsistent state (separate sessions don't coordinate, race conditions), and duplicates connection
> management (multiple reconnection paths, error handling, token refresh).
>
> Create global MCP client store/context (e.g., `stores/mcp-client.ts` with `mcpClient` writable), initialize
> once at app startup, and have all components import and use the shared client. This provides single
> connection,
> consistent state, centralized reconnection, and proper resource subscriptions.
>
> GlobalApprovalsList: delete component until backend supports it, or expose global approvals through shared
> compositor.
>
> **Note:** Creates MCP client to list agents; should use shared client from store/context

```
      80:       const config: MCPClientConfig = {
      81:         name: 'agents-sidebar',
      82:         url: `${window.location.protocol}//${window.location.host}/mcp`,
      83:         token,
      84:       }
>>>   85:       mcpClient = await createMCPClient(config)
      86:
      87:       // Set up notification handler for resource updates
      88:       mcpClient.setNotificationHandler(
      89:         ResourceUpdatedNotificationSchema,
      90:         async (notification) => {
```

### `unimplemented-websocket.yaml` / `occ-1`

File: `adgn/src/adgn/agent/web/src/components/ChatPane.svelte`

> Four Svelte components create independent MCP client connections: AgentsSidebar (line 85), ChatPane
> (lines 87-91 and 124-128 - TWO separate clients in same component), MessageComposer (lines 16-20),
> and GlobalApprovalsList (lines 69-71 targeting non-existent /api/mcp endpoint).
>
> Each client creation involves handshake, auth, session setup, and dedicated connection. This wastes
> resources (multiple WebSocket/HTTP connections, repeated handshakes, memory/file descriptors), violates
> 2-level compositor architecture (intended: UI → shared client → compositor; actual: parallel connections),
> creates inconsistent state (separate sessions don't coordinate, race conditions), and duplicates connection
> management (multiple reconnection paths, error handling, token refresh).
>
> Create global MCP client store/context (e.g., `stores/mcp-client.ts` with `mcpClient` writable), initialize
> once at app startup, and have all components import and use the shared client. This provides single
> connection,
> consistent state, centralized reconnection, and proper resource subscriptions.
>
> GlobalApprovalsList: delete component until backend supports it, or expose global approvals through shared
> compositor.
>
> **Note:** Creates TWO separate clients in same component: chat-pane-client (line 87-91) for listing,
> chat-pane-abort-client (line 124-128) for aborting. Worst offender - not even reusing its own client

```
      82:         console.warn('No auth token available for MCP client')
      83:         agentMode = null
      84:         return
      85:       }
      86:
>>>   87:       const client = await createMCPClient({
>>>   88:         name: 'chat-pane-client',
>>>   89:         url: `${backendOrigin()}/mcp`,
>>>   90:         token
>>>   91:       })
      92:
      93:       const contents = await readResource(client, MCPUris.agentsListUri)
      94:
      95:       // Parse the resource contents
      96:       if (Array.isArray(contents) && contents.length > 0) {
   ...
     119:       if (!token) {
     120:         abortErrorMessage = 'Authentication required'
     121:         return
     122:       }
     123:
>>>  124:       const client = await createMCPClient({
>>>  125:         name: 'chat-pane-abort-client',
>>>  126:         url: `${backendOrigin()}/mcp`,
>>>  127:         token
>>>  128:       })
     129:
     130:       await callTool(client, 'abort_agent', { agent_id: id })
     131:     } catch (error) {
     132:       if (error instanceof MCPClientError) {
     133:         abortErrorMessage = `Abort failed: ${error.message}`
```

### `unimplemented-websocket.yaml` / `occ-2`

File: `adgn/src/adgn/agent/web/src/components/MessageComposer.svelte`

> Four Svelte components create independent MCP client connections: AgentsSidebar (line 85), ChatPane
> (lines 87-91 and 124-128 - TWO separate clients in same component), MessageComposer (lines 16-20),
> and GlobalApprovalsList (lines 69-71 targeting non-existent /api/mcp endpoint).
>
> Each client creation involves handshake, auth, session setup, and dedicated connection. This wastes
> resources (multiple WebSocket/HTTP connections, repeated handshakes, memory/file descriptors), violates
> 2-level compositor architecture (intended: UI → shared client → compositor; actual: parallel connections),
> creates inconsistent state (separate sessions don't coordinate, race conditions), and duplicates connection
> management (multiple reconnection paths, error handling, token refresh).
>
> Create global MCP client store/context (e.g., `stores/mcp-client.ts` with `mcpClient` writable), initialize
> once at app startup, and have all components import and use the shared client. This provides single
> connection,
> consistent state, centralized reconnection, and proper resource subscriptions.
>
> GlobalApprovalsList: delete component until backend supports it, or expose global approvals through shared
> compositor.
>
> **Note:** Creates new MCP client per message send operation; should use shared client

```
      11:   let message = ''
      12:   let sending = false
      13:   let error: string | null = null
      14:
      15:   // Send message to agent via MCP prompt tool
>>>   16:   async function sendMessage() {
>>>   17:     if (!message.trim() || !agentId || sending) return
>>>   18:
>>>   19:     sending = true
>>>   20:     error = null
      21:
      22:     try {
      23:       const token = getOrExtractToken()
      24:       if (!token) {
      25:         throw new Error('Authentication required')
```

### `unimplemented-websocket.yaml` / `occ-3`

File: `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte`

> Four Svelte components create independent MCP client connections: AgentsSidebar (line 85), ChatPane
> (lines 87-91 and 124-128 - TWO separate clients in same component), MessageComposer (lines 16-20),
> and GlobalApprovalsList (lines 69-71 targeting non-existent /api/mcp endpoint).
>
> Each client creation involves handshake, auth, session setup, and dedicated connection. This wastes
> resources (multiple WebSocket/HTTP connections, repeated handshakes, memory/file descriptors), violates
> 2-level compositor architecture (intended: UI → shared client → compositor; actual: parallel connections),
> creates inconsistent state (separate sessions don't coordinate, race conditions), and duplicates connection
> management (multiple reconnection paths, error handling, token refresh).
>
> Create global MCP client store/context (e.g., `stores/mcp-client.ts` with `mcpClient` writable), initialize
> once at app startup, and have all components import and use the shared client. This provides single
> connection,
> consistent state, centralized reconnection, and proper resource subscriptions.
>
> GlobalApprovalsList: delete component until backend supports it, or expose global approvals through shared
> compositor.
>
> **Note:** Creates separate client targeting /api/mcp (non-existent endpoint). Violates 2-level compositor architecture.
> User suggests: delete component or expose agent-global resource through compositor

```
      64:         throw new Error('No authentication token available')
      65:       }
      66:
      67:       // Connect to MCP server (requires backend to expose MCP endpoint)
      68:       // In a full implementation, this would connect to something like:
>>>   69:       // http://localhost:8765/api/mcp
>>>   70:       mcpClient = await createMCPClient({
>>>   71:         name: 'global-approvals-ui',
      72:         url: `${window.location.origin}/api/mcp`,
      73:         token
      74:       })
      75:
      76:       // Subscribe to resource updates for live refresh
```

### `unmounted-resource-uris.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/resources.py`

> The `resources.py` module defines ten parameterized resource URI helper functions
> (agent_state, agent_snapshot, agent_mcp_state, agent_approvals_pending, agent_approvals_history,
> agent_approval, agent_policy_proposals, agent_policy_state, agent_session_state, agent_ui_state)
> that construct URIs like `resource://agents/{agent_id}/state`, but only two URIs are actually
> mounted as resources in the MCP server: `resource://agents/list` and `resource://agents/{agent_id}/info`
> (server.py, lines 251-284).
>
> **Problems:**
>
> 1. Dead code: 10 URI helpers defined but never used
> 2. Confusing API: functions suggest resources exist when they don't
> 3. Maintenance burden: unused code + misleading docstrings
> 4. No clear plan: unclear if future features or abandoned work
> 5. Constants duplication: same URIs also in `_shared/constants.py`
>
> **The correct approach:**
> Either implement the missing resources or delete the unused helpers. Recommended: delete helpers
> for unmounted resources, keeping only what's actually implemented. Search for usages first; if used
> only in tests expecting future work, move to test fixtures.
>
> **Benefits of cleanup:**
>
> 1. No dead code, clear API surface
> 2. Less confusion for new developers
> 3. Honest documentation reflecting actual capabilities
> 4. Smaller maintenance burden

```
      11:
      12: ACTIVE_POLICY = "resource://approval-policy/policy.py"
      13: """Resource URI for active approval policy."""
      14:
      15:
>>>   16: # Parameterized resource URIs (functions)
>>>   17: def agent_state(agent_id: AgentID) -> str:
>>>   18:     """Resource URI for agent sampling state."""
>>>   19:     return f"resource://agents/{agent_id}/state"
>>>   20:
>>>   21:
>>>   22: def agent_snapshot(agent_id: AgentID) -> str:
>>>   23:     """Resource URI for full compositor sampling snapshot."""
>>>   24:     return f"resource://agents/{agent_id}/snapshot"
>>>   25:
>>>   26:
>>>   27: def agent_mcp_state(agent_id: AgentID) -> str:
>>>   28:     """Resource URI for MCP servers state."""
>>>   29:     return f"resource://agents/{agent_id}/mcp/state"
>>>   30:
>>>   31:
>>>   32: def agent_approvals_pending(agent_id: AgentID) -> str:
>>>   33:     """Resource URI for pending approvals for an agent."""
>>>   34:     return f"resource://agents/{agent_id}/approvals/pending"
>>>   35:
>>>   36:
>>>   37: def agent_approvals_history(agent_id: AgentID) -> str:
>>>   38:     """Resource URI for approval history timeline."""
>>>   39:     return f"resource://agents/{agent_id}/approvals/history"
>>>   40:
>>>   41:
>>>   42: def agent_approval(agent_id: AgentID, call_id: str) -> str:
>>>   43:     """Resource URI for a specific approval."""
>>>   44:     return f"resource://agents/{agent_id}/approvals/{call_id}"
>>>   45:
>>>   46:
>>>   47: def agent_policy_proposals(agent_id: AgentID) -> str:
>>>   48:     """Resource URI for policy proposals."""
>>>   49:     return f"resource://agents/{agent_id}/policy/proposals"
>>>   50:
>>>   51:
>>>   52: def agent_policy_state(agent_id: AgentID) -> str:
>>>   53:     """Resource URI for policy state (active policy + proposals)."""
>>>   54:     return f"resource://agents/{agent_id}/policy/state"
>>>   55:
>>>   56:
>>>   57: def agent_session_state(agent_id: AgentID) -> str:
>>>   58:     """Resource URI for agent session state and transcript."""
>>>   59:     return f"resource://agents/{agent_id}/session/state"
>>>   60:
>>>   61:
>>>   62: def agent_ui_state(agent_id: AgentID) -> str:
>>>   63:     """Resource URI for UI state (only if UI server attached)."""
>>>   64:     return f"resource://agents/{agent_id}/ui/state"
>>>   65:
>>>   66:
>>>   67: def policy_proposal(proposal_id: str) -> str:
      68:     """Resource URI for a specific policy proposal."""
      69:     return f"resource://approval-policy/proposals/{proposal_id}"
```

### `unnecessary-noop-overrides.yaml` / `occ-0`

File: `adgn/src/adgn/agent/reducer.py`

> Lines 244-265 in reducer.py define `NotificationsHandler(BaseHandler)` that overrides 7 event
> methods (`on_response`, `on_error`, `on_user_text`, `on_assistant_text`, `on_tool_call`,
> `on_tool_result`, `on_reasoning`) that all just `return None`. Base class already provides these
> no-op defaults.
>
> This creates unnecessary code (7 methods × 3 lines = 21 lines of no-ops), maintenance burden
> (must sync with base class changes), false signal (suggests methods do something different from
> base), and misleading comment ("Event forwarding (typed, observer-only)" but they just return None).
>
> Delete the 7 no-op method overrides (lines 244-265). Keep only `__init__` and `on_before_sample`
> which have actual implementation. Subclasses should override only what they specialize, not what
> returns base defaults. Saves 21 lines, clear intent (only overrides what matters), standard pattern,
> self-documenting (missing overrides signal "uses base behavior").

```
     239:
     240:         if msg is None:
     241:             logger.debug("NotificationsHandler: no updates")
     242:             return NoLoopDecision()
     243:
>>>  244:         self._msg_counter += 1
>>>  245:         logger.info(
>>>  246:             "NotificationsHandler: delivering %d updates (msg #%d)", len(batch.resources_updated), self._msg_counter
>>>  247:         )
>>>  248:         return Continue(Auto(), inserts_input=(msg,))
>>>  249:
>>>  250:     # ---- Event forwarding (typed, observer-only) ----
>>>  251:     def on_response(self, evt: Response) -> None:
>>>  252:         return None
>>>  253:
>>>  254:     def on_error(self, exc: Exception) -> None:
>>>  255:         return None
>>>  256:
>>>  257:     def on_user_text(self, evt: UserText) -> None:
>>>  258:         return None
>>>  259:
>>>  260:     def on_assistant_text(self, evt: AssistantText) -> None:
>>>  261:         return None
>>>  262:
>>>  263:     def on_tool_call(self, evt: ToolCall) -> None:
>>>  264:         return None
>>>  265:
     266:     # Agent-level before-tool gating removed; Policy Gateway middleware enforces approvals/denials
     267:
     268:     def on_tool_result(self, evt: ToolCallOutput) -> None:
     269:         return None
     270:
```

## gmail-archiver/2025-12-17-00 (28)

### `ad-hoc-action-signature-tuple.yaml` / `occ-0`

File: `gmail_archiver/cli/filters.py`

> The code constructs an ad-hoc tuple-of-tuples to represent an action's label changes
> for grouping purposes:
>
>     sig = (tuple(sorted(pa.action.labels_to_add)), tuple(sorted(pa.action.labels_to_remove)))
>
> Problems:
>
> - Uses tuples instead of frozensets (order shouldn't matter for set comparison)
> - Ad-hoc structure with gnarly type annotation
> - Duplicates knowledge of what makes an action "the same" for batching
>
> Fix: Create a frozen ActionSignature dataclass with frozenset fields in core.py:
>
>     @dataclass(frozen=True)
>     class ActionSignature:
>         labels_to_add: frozenset[str]
>         labels_to_remove: frozenset[str]
>
> Add Action.signature property that returns ActionSignature | None (None when no-op).
> Then grouping becomes: by_signature[pa.action.signature].append(message_id)

```
     365:     display_plan(plan, dry_run=dry_run is True)
     366:
     367:     # Execute using batch operations grouped by label change signature
     368:     def do_apply():
     369:         # Group messages by their label change signature for efficient batching
>>>  370:         by_signature: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = {}
>>>  371:         for message_id, pa in plan.actions.items():
>>>  372:             if pa.action.labels_to_add or pa.action.labels_to_remove:
>>>  373:                 sig = (tuple(sorted(pa.action.labels_to_add)), tuple(sorted(pa.action.labels_to_remove)))
>>>  374:                 if sig not in by_signature:
>>>  375:                     by_signature[sig] = []
>>>  376:                 by_signature[sig].append(message_id)
     377:
     378:         total_processed = 0
     379:         for (add_labels, remove_labels), msg_ids in by_signature.items():
     380:             # Use batchModify for efficiency
     381:             batch_size = 1000
```

### `duplicate-criteria-query-conversion.yaml` / `occ-0`

File: `gmail_archiver/filter_planner.py`

> The pattern of building "from:/to:/subject:" strings is duplicated across models:
>
> - criteria_to_gmail_query(FilterCriteria)
> - rule_to_gmail_query(FilterRule)
> - GmailFilterPlanner.**init** (from FilterCriteria)
> - format_filter_for_display(NormalizedFilter)
>
> NormalizedFilter has same criteria fields as FilterCriteria. Fix: add to_criteria()
> methods or use a Protocol, then single criteria_to_gmail_query() everywhere.
>
> **Note:** criteria_to_gmail_query(FilterCriteria)

```
       4: from gmail_archiver.gmail_api_models import FilterCriteria, GmailFilter
       5: from gmail_archiver.gmail_yaml_filters_models import FilterRule
       6: from gmail_archiver.inbox import GmailInbox
       7:
       8:
>>>    9: def criteria_to_gmail_query(criteria: FilterCriteria) -> str:
>>>   10:     """Convert FilterCriteria to Gmail search query string."""
>>>   11:     parts = []
>>>   12:     if criteria.from_:
>>>   13:         parts.append(f"from:({criteria.from_})")
>>>   14:     if criteria.to:
>>>   15:         parts.append(f"to:({criteria.to})")
>>>   16:     if criteria.subject:
>>>   17:         parts.append(f"subject:({criteria.subject})")
>>>   18:     if criteria.query:
>>>   19:         parts.append(criteria.query)
>>>   20:     if criteria.negated_query:
>>>   21:         parts.append(f"-({criteria.negated_query})")
>>>   22:     return " ".join(parts)
      23:
      24:
      25: def rule_to_gmail_query(rule: FilterRule) -> str:
      26:     """Convert FilterRule to Gmail search query string."""
      27:     parts = []
```

### `duplicate-criteria-query-conversion.yaml` / `occ-1`

File: `gmail_archiver/filter_planner.py`

> The pattern of building "from:/to:/subject:" strings is duplicated across models:
>
> - criteria_to_gmail_query(FilterCriteria)
> - rule_to_gmail_query(FilterRule)
> - GmailFilterPlanner.**init** (from FilterCriteria)
> - format_filter_for_display(NormalizedFilter)
>
> NormalizedFilter has same criteria fields as FilterCriteria. Fix: add to_criteria()
> methods or use a Protocol, then single criteria_to_gmail_query() everywhere.
>
> **Note:** rule_to_gmail_query(FilterRule)

```
      20:     if criteria.negated_query:
      21:         parts.append(f"-({criteria.negated_query})")
      22:     return " ".join(parts)
      23:
      24:
>>>   25: def rule_to_gmail_query(rule: FilterRule) -> str:
>>>   26:     """Convert FilterRule to Gmail search query string."""
>>>   27:     parts = []
>>>   28:
>>>   29:     if isinstance(rule.from_, str):
>>>   30:         parts.append(f"from:({rule.from_})")
>>>   31:     if isinstance(rule.to, str):
>>>   32:         parts.append(f"to:({rule.to})")
>>>   33:     if isinstance(rule.subject, str):
>>>   34:         parts.append(f"subject:({rule.subject})")
>>>   35:     if isinstance(rule.has, str):
>>>   36:         parts.append(rule.has)
>>>   37:     elif isinstance(rule.has, list):
>>>   38:         parts.extend(rule.has)
>>>   39:     if isinstance(rule.does_not_have, str):
>>>   40:         parts.append(f"-({rule.does_not_have})")
>>>   41:     elif isinstance(rule.does_not_have, list):
>>>   42:         for term in rule.does_not_have:
>>>   43:             parts.append(f"-({term})")
>>>   44:
>>>   45:     # Additional search operators
>>>   46:     if isinstance(rule.bcc, str):
>>>   47:         parts.append(f"bcc:({rule.bcc})")
>>>   48:     if isinstance(rule.cc, str):
>>>   49:         parts.append(f"cc:({rule.cc})")
>>>   50:     if isinstance(rule.list, str):
>>>   51:         parts.append(f"list:({rule.list})")
>>>   52:     if isinstance(rule.filename, str):
>>>   53:         parts.append(f"filename:({rule.filename})")
>>>   54:     if rule.larger:
>>>   55:         parts.append(f"larger:{rule.larger}")
>>>   56:     if rule.smaller:
>>>   57:         parts.append(f"smaller:{rule.smaller}")
>>>   58:
>>>   59:     return " ".join(parts)
      60:
      61:
      62: class SingleFilterPlanner:
      63:     """Planner that applies a single filter rule to matching emails."""
      64:
```

### `duplicate-criteria-query-conversion.yaml` / `occ-2`

File: `gmail_archiver/filter_planner.py`

> The pattern of building "from:/to:/subject:" strings is duplicated across models:
>
> - criteria_to_gmail_query(FilterCriteria)
> - rule_to_gmail_query(FilterRule)
> - GmailFilterPlanner.**init** (from FilterCriteria)
> - format_filter_for_display(NormalizedFilter)
>
> NormalizedFilter has same criteria fields as FilterCriteria. Fix: add to_criteria()
> methods or use a Protocol, then single criteria_to_gmail_query() everywhere.
>
> **Note:** GmailFilterPlanner.**init** name building from FilterCriteria

```
     151:         self.labels_by_id = labels_by_id
     152:         self.additional_query = additional_query
     153:
     154:         # Build display name from filter criteria
     155:         criteria = gmail_filter.criteria
>>>  156:         name_parts = []
>>>  157:         if criteria.from_:
>>>  158:             name_parts.append(f"from:{criteria.from_}")
>>>  159:         if criteria.subject:
>>>  160:             name_parts.append(f"subject:{criteria.subject}")
>>>  161:         if criteria.query:
>>>  162:             name_parts.append(criteria.query)
>>>  163:         suffix = " ".join(name_parts)[:50] if name_parts else "(unnamed)"
     164:         self.name = f"Filter: {suffix}"
     165:
     166:     def plan(self, inbox: GmailInbox) -> Plan:
     167:         plan = Plan(planner=self)
     168:
```

### `duplicate-criteria-query-conversion.yaml` / `occ-3`

File: `gmail_archiver/filter_sync.py`

> The pattern of building "from:/to:/subject:" strings is duplicated across models:
>
> - criteria_to_gmail_query(FilterCriteria)
> - rule_to_gmail_query(FilterRule)
> - GmailFilterPlanner.**init** (from FilterCriteria)
> - format_filter_for_display(NormalizedFilter)
>
> NormalizedFilter has same criteria fields as FilterCriteria. Fix: add to_criteria()
> methods or use a Protocol, then single criteria_to_gmail_query() everywhere.
>
> **Note:** format_filter_for_display() from NormalizedFilter

```
     210:             self.by_name[name] = label_id
     211:             self.by_id[label_id] = name
     212:         return self.by_name[name]
     213:
     214:
>>>  215: def format_filter_for_display(f: NormalizedFilter) -> str:
>>>  216:     """Format a filter for human-readable display."""
>>>  217:     parts = []
>>>  218:
>>>  219:     # Criteria
>>>  220:     if f.from_:
>>>  221:         parts.append(f"from:{f.from_}")
>>>  222:     if f.to:
>>>  223:         parts.append(f"to:{f.to}")
>>>  224:     if f.subject:
>>>  225:         parts.append(f"subject:{f.subject}")
>>>  226:     if f.query:
>>>  227:         parts.append(f"has:{f.query}")
>>>  228:     if f.negated_query:
>>>  229:         parts.append(f"-({f.negated_query})")
>>>  230:
>>>  231:     criteria_str = " ".join(parts) if parts else "(no criteria)"
     232:
     233:     # Actions
     234:     actions = []
     235:     if f.add_labels:
     236:         for label in sorted(f.add_labels):
```

### `duplicated-pagination-logic.yaml` / `occ-0`

File: `gmail_archiver/__main__.py`

> download_matching() in **main**.py manually implements paginated Gmail query
> (lines 155-174) instead of using the existing GmailClient.list_messages_by_query()
> which already handles pagination.
>
> **Note:** manual pagination loop duplicates GmailClient.list_messages_by_query()

```
     150:     client = get_gmail_client(token_file)
     151:
     152:     # Search for matching emails
     153:     console.print("Searching Gmail...")
     154:
>>>  155:     # Build search with pagination
>>>  156:     all_message_ids = []
>>>  157:     page_token = None
>>>  158:
>>>  159:     while True:
>>>  160:         search_params = {"userId": "me", "q": query, "maxResults": 500}
>>>  161:         if page_token:
>>>  162:             search_params["pageToken"] = page_token
>>>  163:
>>>  164:         results = client.service.users().messages().list(**search_params).execute()
>>>  165:         messages = results.get("messages", [])
>>>  166:         all_message_ids.extend([msg["id"] for msg in messages])
>>>  167:
>>>  168:         if max_results and len(all_message_ids) >= max_results:
>>>  169:             all_message_ids = all_message_ids[:max_results]
>>>  170:             break
>>>  171:
>>>  172:         page_token = results.get("nextPageToken")
>>>  173:         if not page_token:
>>>  174:             break
     175:
     176:     if not all_message_ids:
     177:         console.print("[yellow]No matching emails found.[/yellow]")
     178:         return
     179:
```

### `ignored-label-removals.yaml` / `occ-0`

File: `gmail_archiver/__main__.py`

> execute_action only handles INBOX removal, silently ignoring all other labels_to_remove:
>
>     if label == "INBOX":
>         client.remove_from_inbox(message_id)
>     # TODO: Handle other label removals
>
> If an action specifies removing UNREAD, STARRED, or any other label, it's silently
> dropped. This is a bug - the TODO acknowledges it but the fix is trivial:
> call client.remove_label(message_id, label) for non-INBOX labels.

```
     109:         if action.labels_to_add:
     110:             for label in action.labels_to_add:
     111:                 client.add_label(message_id, label)
     112:         if action.labels_to_remove:
     113:             for label in action.labels_to_remove:
>>>  114:                 if label == "INBOX":
>>>  115:                     client.remove_from_inbox(message_id)
>>>  116:                 # TODO: Handle other label removals
     117:
     118:     combined.execute(dry_run=dry_run, execute_fn=execute_action)
     119:
     120:     # Show summary
     121:     console.print(f"\n{summarize_plan(combined)}")
```

### `inconsistent-frozenset-building.yaml` / `occ-0`

File: `gmail_archiver/filter_sync.py`

> Building a set incrementally with .add() then converting to frozenset is
> inconsistent when other code paths already produce frozensets directly.
> normalize_yaml_rule builds add_labels and remove_labels as mutable sets then
> returns them as frozensets. Using set comprehensions or frozenset() directly
> would be more idiomatic.
>
> **Note:** add_labels and remove_labels built as set() then converted - could use frozenset comprehension

```
      71:
      72:
      73: def normalize_yaml_rule(rule: FilterRule) -> NormalizedFilter:
      74:     """Convert FilterRule from YAML to normalized form."""
      75:     # Build add_labels set
>>>   76:     add_labels: set[str] = set()
>>>   77:     if rule.label:
>>>   78:         add_labels.add(rule.label)
>>>   79:     if rule.important or rule.mark_as_important:
>>>   80:         add_labels.add("IMPORTANT")
>>>   81:     if rule.star:
>>>   82:         add_labels.add("STARRED")
>>>   83:     if rule.trash or rule.delete:
>>>   84:         add_labels.add("TRASH")
>>>   85:
>>>   86:     # Build remove_labels set
>>>   87:     remove_labels: set[str] = set()
      88:     if rule.archive:
      89:         remove_labels.add("INBOX")
      90:     if rule.read or rule.mark_as_read:
      91:         remove_labels.add("UNREAD")
      92:     if rule.not_important or rule.never_mark_as_important:
```

### `inline-link-parsing.yaml` / `occ-0`

File: `gmail_archiver/__main__.py`

> Gmail link parsing logic (lines 330-344) is inline in download_email command.
> Should be extracted as a separate function for reusability and testability.
>
> **Note:** link parsing in download_email() - extract to parse_gmail_link() or similar

```
     325:         gmail-archiver download-email 19b1c55967d81057
     326:         gmail-archiver download-email FMfcgzQcqtXwNDFwNDZXFhFgVnXRzQjw
     327:         gmail-archiver download-email https://mail.google.com/mail/u/0/#inbox/FMfcgzQcqtXwNDFwNDZXFhFgVnXRzQjw
     328:         gmail-archiver download-email 19b1c55967d81057 -o my_email.eml
     329:     """
>>>  330:     # Extract ID from link if needed
>>>  331:     extracted_id = id_or_link
>>>  332:     if id_or_link.startswith("http"):
>>>  333:         # Extract ID from Gmail link
>>>  334:         # Match hex IDs: /inbox/19b1c55967d81057
>>>  335:         match = re.search(r"/#[^/]+/([a-f0-9]{16})", id_or_link)
>>>  336:         if not match:
>>>  337:             print_error(f"Could not extract message ID from link: {id_or_link}")
>>>  338:             console.print(
>>>  339:                 "\nNote: Gmail web URLs use encoded IDs that don't work with the Gmail API. "
>>>  340:                 "To download an email, find its message ID by searching Gmail with the download-matching command."
>>>  341:             )
>>>  342:             raise typer.Exit(code=1)
>>>  343:         extracted_id = match.group(1)
>>>  344:         console.print(f"Extracted message ID: {extracted_id}")
     345:
     346:     # Connect to Gmail
     347:     client = get_gmail_client(token_file)
     348:
     349:     # Try fetching as message ID first (most common case)
```

### `iterate-values-not-items.yaml` / `occ-0`

File: `gmail_archiver/planners/aliexpress.py`

> Iterating with .items() when key is unused. Should use .values() instead
> when only the values are needed.
>
> **Note:** for \_order_id, order_emails in by_order.items() - should use .values()

```
     184:         if unparseable:
     185:             plan.add_message(f"Skipping {len(unparseable)} emails with unrecognized status:")
     186:             for msg, _error in unparseable:
     187:                 plan.add_message(f"  - {msg.subject[:60]}...")
     188:
>>>  189:         for _order_id, order_emails in by_order.items():
     190:             # Sort by date, newest first
     191:             sorted_emails = sorted(order_emails, key=lambda m: m.internal_date, reverse=True)
     192:             latest = sorted_emails[0]
     193:             latest_parsed = parsed_cache[latest.id]
     194:
```

### `manual-batch-slicing.yaml` / `occ-0`

File: `gmail_archiver/cli/filters.py`

> Manual batch slicing pattern:
>
>     for i in range(0, len(msg_ids), batch_size):
>         batch = msg_ids[i : i + batch_size]
>
> Python 3.12+ has itertools.batched() which handles this cleanly:
>
>     for batch in itertools.batched(msg_ids, batch_size):

```
     377:
     378:         total_processed = 0
     379:         for (add_labels, remove_labels), msg_ids in by_signature.items():
     380:             # Use batchModify for efficiency
     381:             batch_size = 1000
>>>  382:             for i in range(0, len(msg_ids), batch_size):
>>>  383:                 batch = msg_ids[i : i + batch_size]
     384:                 body: dict = {"ids": batch}
     385:                 if add_labels:
     386:                     body["addLabelIds"] = list(add_labels)
     387:                 if remove_labels:
     388:                     body["removeLabelIds"] = list(remove_labels)
```

### `manual-credentials-construction.yaml` / `occ-0`

File: `gmail_archiver/gmail_client.py`

> GmailClient constructor manually parses JSON and constructs Credentials field by field.
> Google's API provides Credentials.from_authorized_user_file() which handles this
> automatically, reducing boilerplate and risk of missing fields.

```
      94:         self.token_file = token_file
      95:         self.service = self._build_service()
      96:         self._label_cache: dict[str, str] | None = None  # name -> id
      97:
      98:     def _build_service(self):
>>>   99:         token_data = json.loads(self.token_file.read_text())
>>>  100:
>>>  101:         creds = Credentials(
>>>  102:             token=token_data["token"],
>>>  103:             refresh_token=token_data.get("refresh_token"),
>>>  104:             token_uri=token_data["token_uri"],
>>>  105:             client_id=token_data["client_id"],
>>>  106:             client_secret=token_data["client_secret"],
     107:             scopes=token_data.get("scopes", []),
     108:         )
     109:
     110:         return build("gmail", "v1", credentials=creds)
     111:
```

### `manual-path-existence-check.yaml` / `occ-0`

File: `gmail_archiver/__main__.py`

> Manual file existence check when typer provides `exists=True` parameter for
> path arguments. Should use `typer.Argument(exists=True)` instead of manual
> check with print_error + typer.Exit.
>
> **Note:** eml_file argument in classify_event() - should use exists=True in typer.Argument

```
     397:     console.print(f"  Date: {parsed.get('Date', '')}")
     398:
     399:
     400: @app.command()
     401: def classify_event(
>>>  402:     eml_file: Annotated[Path, typer.Argument(help="Path to .eml file to classify")],
     403:     no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache and re-classify")] = False,
     404: ):
     405:     """Recognize email template and extract structured data using OpenAI.
     406:
     407:     This command is for debugging the template extractor. It reads an .eml file,
   ...
     409:     (if any) the email matches and extracts structured data accordingly.
     410:
     411:     Example:
     412:         gmail-archiver classify-event inbox/19b18706c1c9ae8f.eml
     413:     """
>>>  414:     if not eml_file.exists():
>>>  415:         print_error(f"File not found: {eml_file}")
>>>  416:         raise typer.Exit(code=1)
     417:
     418:     # Parse .eml file
     419:     console.print(f"Reading {eml_file}...")
     420:     with eml_file.open("rb") as f:
     421:         msg = BytesParser(policy=default).parse(f)
```

### `module-level-extractor-singleton.yaml` / `occ-0`

File: `gmail_archiver/planners/dbsa.py`

> Module-level singleton creates hidden global state:
>
>     _extractor = EmailTemplateExtractor()
>
> This instantiates an OpenAI client and cache at import time. Problems:
>
> - Hidden dependency (not visible in function/class signatures)
> - Hard to test (can't inject mock extractor)
> - Imports have side effects (client creation, env var access)
> - Can't configure differently per use case
>
> Fix: Use dependency injection - pass EmailTemplateExtractor into
> DbsaEventPlanner.**init**() and store as instance attribute. The caller
> (autoclean_inbox) creates one extractor and passes it to planners that need it.

```
      15: class DBSASFEvent(BaseModel):
      16:     event_datetime: datetime | None = None
      17:     confidence: float = 0.0
      18:
      19:
>>>   20: _extractor = EmailTemplateExtractor()
      21:
      22:
      23: def parse_dbsa_sf(email: GmailMessage) -> DBSASFEvent:
      24:     """Extract DBSA SF event date using OpenAI (with caching)."""
      25:
```

### `plan-merge-bypasses-init.yaml` / `occ-0`

File: `gmail_archiver/core.py`

> Plan.merge() uses **new** to bypass **init** and manually initializes fields:
>
>     merged = Plan.__new__(Plan)
>     merged.planner = None
>     merged.actions = {}
>     merged.messages_by_id = {}
>     merged.messages = []
>
> This is fragile - if **init** ever adds setup logic, logging, validation, or new
> fields, this code will silently produce broken Plan instances. The hack exists
> because Plan.**init** requires a planner, but merged plans have no single owner.
>
> Better alternatives:
>
> - Make planner optional in **init**: def **init**(self, planner: Planner | None = None)
> - Use a @classmethod factory: Plan.create_merged(plans)
> - Use a dataclass with default_factory for fields

```
     115:         """Merge multiple plans into one. Raises ValueError on conflicts."""
     116:         if not plans:
     117:             raise ValueError("Cannot merge empty list of plans")
     118:
     119:         # Create merged plan (no specific planner owner)
>>>  120:         merged = Plan.__new__(Plan)
>>>  121:         merged.planner = None
>>>  122:         merged.actions = {}
>>>  123:         merged.messages_by_id = {}
>>>  124:         merged.messages = []
     125:
     126:         for plan in plans:
     127:             # Check for collisions before merging
     128:             for message_id, planned_action in plan.actions.items():
     129:                 if message_id in merged.actions:
```

### `silent-exception-swallowing.yaml` / `occ-0`

File: `gmail_archiver/event_classifier.py`

> ExtractionCache.get() catches all exceptions and silently returns None (line 78-79).
> This swallows errors like JSON decode failures or schema mismatches without any logging.
> Should either not catch, or at minimum log the error before returning None.
>
> **Note:** bare except returning None in cache get

```
      73:         cache_path = self._get_cache_path(message_id)
      74:         if cache_path.exists():
      75:             try:
      76:                 data = json.loads(cache_path.read_text())
      77:                 return EmailTemplateExtraction(**data)
>>>   78:             except Exception:
>>>   79:                 return None
      80:         return None
      81:
      82:     def set(self, message_id: str, extraction: EmailTemplateExtraction):
      83:         cache_path = self._get_cache_path(message_id)
      84:         cache_path.write_text(extraction.model_dump_json(indent=2))
```

### `sync-planner-wrapping-async.yaml` / `occ-0`

File: `gmail_archiver/planners/dbsa.py`

> DbsaEventPlanner.plan() is sync but calls async code via asyncio.run() per email:
>
>     def parse_dbsa_sf(email: GmailMessage) -> DBSASFEvent:
>         async def extract_async():
>             return await _extractor.extract(...)
>         extraction = asyncio.run(extract_async())
>
> This creates a new event loop per email, preventing concurrent API calls.
> The extractor already supports batching via extract_batch() with asyncio.gather().
>
> The fix is to make the planner async end-to-end:
>
> - Make Planner.plan() an async method
> - Make DbsaEventPlanner.plan() async and use extract_batch() or gather
> - Thread async through the caller (autoclean_inbox)
>
> This allows concurrent OpenAI calls instead of sequential with event loop overhead.

```
      21:
      22:
      23: def parse_dbsa_sf(email: GmailMessage) -> DBSASFEvent:
      24:     """Extract DBSA SF event date using OpenAI (with caching)."""
      25:
>>>   26:     async def extract_async():
>>>   27:         return await _extractor.extract(
>>>   28:             message_id=email.id, subject=email.subject, body=email.body, received_date=email.date, use_cache=True
>>>   29:         )
>>>   30:
>>>   31:     # Run async extraction in sync context
>>>   32:     extraction = asyncio.run(extract_async())
      33:
      34:     # Extract event datetime if this is a DBSA SF reminder
      35:     if extraction.data.template == "dbsa_sf_group_reminder" and extraction.data.event_datetime:
      36:         try:
      37:             event_dt = datetime.fromisoformat(extraction.data.event_datetime)
```

### `unbatched-incomplete-labels.yaml` / `occ-0`

File: `gmail_archiver/__main__.py`

> execute_action() in **main**.py has two issues:
>
> 1. Not batched - makes individual API calls per message instead of using Gmail
>    batch API for efficiency
> 2. Incomplete - only handles INBOX removal specially, silently ignores other
>    label removals (has TODO comment on line 116)
>
> **Note:** execute_action() - unbatched individual calls, ignores non-INBOX label removals

```
     103:
     104:     # Display unified table
     105:     display_plan(combined, dry_run=dry_run, group_by_category=True)
     106:
     107:     # Execute all Gmail API operations
>>>  108:     def execute_action(message_id: str, action: Action):
>>>  109:         if action.labels_to_add:
>>>  110:             for label in action.labels_to_add:
>>>  111:                 client.add_label(message_id, label)
>>>  112:         if action.labels_to_remove:
>>>  113:             for label in action.labels_to_remove:
>>>  114:                 if label == "INBOX":
>>>  115:                     client.remove_from_inbox(message_id)
>>>  116:                 # TODO: Handle other label removals
>>>  117:
>>>  118:     combined.execute(dry_run=dry_run, execute_fn=execute_action)
     119:
     120:     # Show summary
     121:     console.print(f"\n{summarize_plan(combined)}")
     122:
     123:
```

### `unfaithful-gmail-message.yaml` / `occ-0`

File: `gmail_archiver/models.py`

> GmailMessage extracts and stores only `body: str` from the raw email, discarding the
> original MIME data. This is premature data reduction - it loses information (HTML body,
> attachments, headers) and prevents fixing parsing bugs or adding new derived fields
> without re-fetching from the API. The model should preserve the raw email bytes and
> derive text content on demand.
>
> **Note:** GmailMessage.body is single str field, loses MIME structure

```
      20:     sender: str = Field(alias="from")
      21:     recipient: str | None = Field(default=None, alias="to")
      22:     subject: str
      23:     date: str
      24:     internal_date: int  # milliseconds since epoch
>>>   25:     body: str
      26:     snippet: str | None = None
      27:     label_ids: list[str] = Field(default_factory=list)
      28:
      29:
      30: class GmailLabel(BaseModel):
```

### `unfaithful-gmail-message.yaml` / `occ-1`

File: `gmail_archiver/gmail_client.py`

> GmailMessage extracts and stores only `body: str` from the raw email, discarding the
> original MIME data. This is premature data reduction - it loses information (HTML body,
> attachments, headers) and prevents fixing parsing bugs or adding new derived fields
> without re-fetching from the API. The model should preserve the raw email bytes and
> derive text content on demand.
>
> **Note:** get_messages_batch() plaintext extraction (no HTML fallback)

```
     445:                     # Parse the message
     446:                     raw_email = base64.urlsafe_b64decode(response["raw"]).decode("utf-8")
     447:                     parsed = email.message_from_string(raw_email)
     448:
     449:                     # Extract plain text body
>>>  450:                     body = ""
>>>  451:                     if parsed.is_multipart():
>>>  452:                         for part in parsed.walk():
>>>  453:                             if part.get_content_type() == "text/plain":
>>>  454:                                 payload = part.get_payload(decode=True)
>>>  455:                                 if payload:
>>>  456:                                     body = payload.decode("utf-8", errors="ignore")
>>>  457:                                     break
>>>  458:                     else:
>>>  459:                         payload = parsed.get_payload(decode=True)
>>>  460:                         if payload:
>>>  461:                             body = payload.decode("utf-8", errors="ignore")
     462:
     463:                     msg = GmailMessage(
     464:                         id=response["id"],
     465:                         thread_id=response.get("threadId"),
     466:                         sender=parsed.get("From", ""),
```

### `unfaithful-gmail-message.yaml` / `occ-2`

File: `gmail_archiver/gmail_client.py`

> GmailMessage extracts and stores only `body: str` from the raw email, discarding the
> original MIME data. This is premature data reduction - it loses information (HTML body,
> attachments, headers) and prevents fixing parsing bugs or adding new derived fields
> without re-fetching from the API. The model should preserve the raw email bytes and
> derive text content on demand.
>
> **Note:** get_message() plaintext extraction (no HTML fallback)

```
     512:         # Decode raw email using email.parser for proper header decoding
     513:         raw_bytes = base64.urlsafe_b64decode(msg["raw"])
     514:         parsed = BytesParser(policy=email_default_policy).parsebytes(raw_bytes)
     515:
     516:         # Extract plain text body
>>>  517:         body = ""
>>>  518:         if parsed.is_multipart():
>>>  519:             for part in parsed.walk():
>>>  520:                 if part.get_content_type() == "text/plain":
>>>  521:                     body = part.get_content()
>>>  522:                     break
>>>  523:         else:
>>>  524:             body = parsed.get_content() if parsed.get_content_type() == "text/plain" else ""
     525:
     526:         return GmailMessage(
     527:             id=msg["id"],
     528:             thread_id=msg.get("threadId"),
     529:             sender=str(parsed.get("From", "")),
```

### `unnecessary-attributeerror-suppression.yaml` / `occ-0`

File: `gmail_archiver/planners/square.py`

> The contextlib.suppress includes AttributeError but this exception cannot occur:
>
> - email.date is a str field (not optional), so no AttributeError from accessing it
> - datetime.strptime() raises ValueError on parse failure, not AttributeError
> - datetime.replace() is always available on datetime objects
>
> Even if AttributeError could somehow occur, suppressing it would mask a real bug
> (e.g., typo in attribute name, wrong object type). Suppressing AttributeError is
> almost never correct - it hides programming errors rather than handling expected
> failure modes.
>
> **Note:** contextlib.suppress(ValueError, AttributeError) for date parsing

```
      35:
      36:
      37: def parse_square(email: GmailMessage) -> SquareReceipt:
      38:     # Parse email date
      39:     email_dt = None
>>>   40:     with contextlib.suppress(ValueError, AttributeError):
      41:         email_dt = datetime.strptime(email.date, "%a, %d %b %Y %H:%M:%S %z")
      42:         email_dt = email_dt.replace(tzinfo=None)
      43:
      44:     # Extract text from HTML body
      45:     soup = BeautifulSoup(email.body, "html.parser")
```

### `unnecessary-attributeerror-suppression.yaml` / `occ-1`

File: `gmail_archiver/planners/anthem_eob.py`

> The contextlib.suppress includes AttributeError but this exception cannot occur:
>
> - email.date is a str field (not optional), so no AttributeError from accessing it
> - datetime.strptime() raises ValueError on parse failure, not AttributeError
> - datetime.replace() is always available on datetime objects
>
> Even if AttributeError could somehow occur, suppressing it would mask a real bug
> (e.g., typo in attribute name, wrong object type). Suppressing AttributeError is
> almost never correct - it hides programming errors rather than handling expected
> failure modes.
>
> **Note:** except (ValueError, AttributeError) for date parsing

```
      20:     """Extract received date from email for 180-day dispute window calculation."""
      21:     try:
      22:         received_dt = datetime.strptime(email.date, "%a, %d %b %Y %H:%M:%S %z")
      23:         received_dt = received_dt.replace(tzinfo=None)
      24:         return AnthemEOB(received_date=received_dt)
>>>   25:     except (ValueError, AttributeError):
>>>   26:         return AnthemEOB(received_date=None)
      27:
      28:
      29: class AnthemEobPlanner:
      30:     """Archives Anthem EOBs older than 180 days."""
      31:
```

### `unnecessary-exception-handling.yaml` / `occ-0`

File: `gmail_archiver/__main__.py`

> Try/except around Plan.merge() is unnecessary defensive coding. If merge
> fails with ValueError (plan collision), that's a bug in planners that should
> crash loudly, not be silently caught and return early.
>
> **Note:** try/except ValueError around Plan.merge() - should just call unguarded

```
      88:         except Exception as e:
      89:             console.print(f"[bold red]Error in {planner.name}:[/bold red] {e}")
      90:             continue
      91:
      92:     # Merge all plans
>>>   93:     try:
>>>   94:         combined = Plan.merge(plans)
>>>   95:     except ValueError as e:
>>>   96:         console.print(f"[bold red]Error merging plans:[/bold red] {e}")
>>>   97:         return
      98:
      99:     # Display category messages
     100:     for msg in combined.messages:
     101:         console.print(msg)
     102:     console.print()
```

### `unnecessary-list-conversion.yaml` / `occ-0`

File: `gmail_archiver/cli/filters.py`

> Calling list() on a set when passing to an API that accepts any iterable is
> unnecessary. The Gmail batchModify API accepts any iterable for label IDs,
> so the conversion adds noise without benefit.
>
> **Note:** list(add_labels) and list(remove_labels) - Gmail API accepts iterables

```
     381:             batch_size = 1000
     382:             for i in range(0, len(msg_ids), batch_size):
     383:                 batch = msg_ids[i : i + batch_size]
     384:                 body: dict = {"ids": batch}
     385:                 if add_labels:
>>>  386:                     body["addLabelIds"] = list(add_labels)
>>>  387:                 if remove_labels:
>>>  388:                     body["removeLabelIds"] = list(remove_labels)
     389:
     390:                 client.service.users().messages().batchModify(userId="me", body=body).execute()
     391:                 total_processed += len(batch)
     392:
     393:         console.print(f"[green]✓[/green] Applied filter to {total_processed} email(s)")
```

### `unnecessary-regex-for-substring.yaml` / `occ-0`

File: `gmail_archiver/planners/aliexpress.py`

> STATUS_PATTERNS uses compiled regex for simple substring checks. All patterns
> are plain strings with no regex metacharacters - just "delivered", "out for
> delivery", etc. with IGNORECASE. Should use simple str.lower() + "in" check
> instead of regex.
>
> **Note:** STATUS_PATTERNS - regex overkill for case-insensitive substring checks

```
      57:         return ""
      58:
      59:
      60: # Regex patterns for subject parsing
      61: ORDER_ID_PATTERN = re.compile(r"Order (\d+):")
>>>   62: STATUS_PATTERNS = [
>>>   63:     (re.compile(r"delivered", re.IGNORECASE), AliExpressStatus.DELIVERED),
>>>   64:     (re.compile(r"out for delivery", re.IGNORECASE), AliExpressStatus.OUT_FOR_DELIVERY),
>>>   65:     (re.compile(r"at delivery center", re.IGNORECASE), AliExpressStatus.AT_DELIVERY_CENTER),
>>>   66:     (re.compile(r"in your country", re.IGNORECASE), AliExpressStatus.IN_COUNTRY),
>>>   67:     (re.compile(r"cleared customs", re.IGNORECASE), AliExpressStatus.CLEARED_CUSTOMS),
>>>   68:     (re.compile(r"package in transit", re.IGNORECASE), AliExpressStatus.IN_TRANSIT),
>>>   69:     (re.compile(r"order shipped", re.IGNORECASE), AliExpressStatus.SHIPPED),
>>>   70:     (re.compile(r"ready to ship", re.IGNORECASE), AliExpressStatus.READY_TO_SHIP),
>>>   71:     (re.compile(r"order confirmed", re.IGNORECASE), AliExpressStatus.CONFIRMED),
>>>   72:     (re.compile(r"delivery update", re.IGNORECASE), AliExpressStatus.DELIVERY_UPDATE),
>>>   73:     (re.compile(r"awaiting confirmation", re.IGNORECASE), AliExpressStatus.AWAITING_CONFIRMATION),
>>>   74:     (re.compile(r"how did it go", re.IGNORECASE), AliExpressStatus.FEEDBACK_REQUEST),
>>>   75:     (re.compile(r"is closed", re.IGNORECASE), AliExpressStatus.CLOSED),
>>>   76:     (re.compile(r"delayed delivery coupon", re.IGNORECASE), AliExpressStatus.DELAYED_COUPON),
>>>   77: ]
      78:
      79:
      80: class AliExpressParseError(Exception):
      81:     """Raised when an AliExpress email cannot be parsed."""
      82:
```

### `untyped-email-tuple.yaml` / `occ-0`

File: `gmail_archiver/event_classifier.py`

> extract_batch() takes emails as list[tuple[str, str, str, str]] - a raw tuple
> with no indication of what each element means (message_id, subject, body,
> received_date). Should use one of the existing Pydantic Gmail models like
> GmailMessage, or a subset model if full GmailMessage is too heavy.
>
> **Note:** emails parameter in extract_batch() - tuple of (message_id, subject, body, received_date)

```
     166:         self.cache.set(message_id, classification)
     167:
     168:         return classification
     169:
     170:     async def extract_batch(
>>>  171:         self, emails: list[tuple[str, str, str, str]], use_cache: bool = True, max_concurrent: int = 10
     172:     ) -> list[tuple[str, EmailTemplateExtraction]]:
     173:         semaphore = asyncio.Semaphore(max_concurrent)
     174:
     175:         async def extract_with_limit(email_data):
     176:             message_id, subject, body, received_date = email_data
```

### `unused-tuple-element.yaml` / `occ-0`

File: `gmail_archiver/planners/aliexpress.py`

> Tuple element is stored but never used. unparseable is typed as
> list[tuple[GmailMessage, str]] and stores the error string, but when
> iterated it's ignored with \_error. Should just be list[GmailMessage].
>
> **Note:** unparseable stores error string that is never used

```
     166:             return plan
     167:
     168:         # Group by order ID
     169:         by_order: dict[str | None, list[GmailMessage]] = defaultdict(list)
     170:         parsed_cache: dict[str, AliExpressEmail] = {}
>>>  171:         unparseable: list[tuple[GmailMessage, str]] = []
     172:
     173:         for msg in messages:
     174:             try:
     175:                 parsed = parse_aliexpress_subject(msg.subject)
     176:                 parsed_cache[msg.id] = parsed
   ...
     174:             try:
     175:                 parsed = parse_aliexpress_subject(msg.subject)
     176:                 parsed_cache[msg.id] = parsed
     177:                 by_order[parsed.order_id].append(msg)
     178:             except AliExpressParseError as e:
>>>  179:                 unparseable.append((msg, str(e)))
     180:
     181:         now = datetime.now(UTC)
     182:
     183:         # Report unparseable emails but don't take action
     184:         if unparseable:
   ...
     181:         now = datetime.now(UTC)
     182:
     183:         # Report unparseable emails but don't take action
     184:         if unparseable:
     185:             plan.add_message(f"Skipping {len(unparseable)} emails with unrecognized status:")
>>>  186:             for msg, _error in unparseable:
     187:                 plan.add_message(f"  - {msg.subject[:60]}...")
     188:
     189:         for _order_id, order_emails in by_order.items():
     190:             # Sort by date, newest first
     191:             sorted_emails = sorted(order_emails, key=lambda m: m.internal_date, reverse=True)
```

## ducktape/2025-11-22-02 (24)

### `ambiguous-timestamp-field.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> The ApprovalItem model has a `timestamp` field whose meaning is ambiguous:
>
> ```python
> class ApprovalItem(BaseModel):
>     """A single approval (pending or decided)."""
>     call_id: str
>     tool_call: ToolCall
>     status: ApprovalStatus
>     reason: str | None = None
>     timestamp: datetime  # What does this represent?
> ```
>
> Looking at usage patterns reveals inconsistent semantics:
>
> - **Pending approvals** (line 167): `timestamp=datetime.now()` - uses current time when building the list
> - **Decided approvals** (line 189): `timestamp=record.decision.decided_at` - uses the decision time
>
> The field name "timestamp" doesn't clarify what event it's timestamping:
>
> - Is it when the tool call was requested?
> - When the approval decision was made?
> - When the approval item was last updated?
>
> For decided approvals it's explicitly the decision time (`decided_at`), but for pending approvals it's just
> "now"
> which
> is actually neither the request time nor a decision time. This semantic inconsistency makes the field unclear
> and
> potentially misleading.
>
> **Fix:**
> Rename to be more specific about what is being timestamped. Options include:
>
> - `updated_at` - if it represents last update time for both states
> - Split into `requested_at` and `decided_at` fields where decided_at is nullable
> - Use a union type with status-specific semantics
>
> The name should make it clear what temporal event is being recorded, and the semantics should be consistent
> across
> both
> pending and decided states.

```
      74:     REJECTED = "rejected"
      75:     DENIED = "denied"
      76:     ABORTED = "aborted"
      77:
      78:
>>>   79: class ApprovalItem(BaseModel):
>>>   80:     """A single approval (pending or decided)."""
>>>   81:     call_id: str
>>>   82:     tool_call: ToolCall
>>>   83:     status: ApprovalStatus
>>>   84:     reason: str | None = None
>>>   85:     timestamp: datetime
      86:
      87:
      88: class ApprovalsResponse(BaseModel):
      89:     """Response containing all approvals for an agent (pending + decided history)."""
      90:     agent_id: AgentID
   ...
     162:                 ApprovalItem(
     163:                     call_id=call_id,
     164:                     tool_call=tool_call,
     165:                     status=ApprovalStatus.PENDING,
     166:                     reason=None,
>>>  167:                     timestamp=datetime.now(),  # Approx timestamp for pending
     168:                 )
     169:                 for call_id, tool_call in pending_map.items()
     170:             ]
     171:
     172:             # Build decided approvals from persistence
   ...
     184:                 ApprovalItem(
     185:                     call_id=record.tool_call.id,
     186:                     tool_call=record.tool_call,
     187:                     status=map_outcome_to_status(record.decision.outcome),
     188:                     reason=record.decision.reason,
>>>  189:                     timestamp=record.decision.decided_at,
     190:                 )
     191:                 for record in records
     192:                 if record.decision is not None
     193:             ]
     194:
```

### `docker-check-at-call-sites.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> The pattern `if self.docker_client is not None: self.self_check(...)` appears
> twice (lines 344-345, 360-361). This conditional is repeated at every call site.
>
> The check should be internal to self_check() itself, not the caller's
> responsibility. Currently self_check() assumes docker_client is valid (line 342),
> forcing callers to guard it.
>
> Fix: Move the None check inside self_check():
>
> def self_check(self, source: str) -> None:
> if self.docker_client is None:
> return # Skip validation if Docker not available
> run_policy_source(docker_client=self.docker_client, ...)
>
> Then call sites simplify to: self.self_check(content)
>
> Benefits:
>
> - Single responsibility: self_check handles its own preconditions
> - DRY: check not repeated at call sites
> - Cleaner API: callers don't need to know about Docker availability

```
     339:
     340:         Validates the proposal content if docker_client is available,
     341:         persists it, and notifies about the change.
     342:         """
     343:         # Self-check proposal program if docker is available
>>>  344:         if self.docker_client is not None:
>>>  345:             self.self_check(content)
     346:         # Create proposal and get actual database-assigned ID
     347:         new_id = await self.persistence.create_policy_proposal(self.agent_id, proposal_id=0, content=content)
     348:         await self.notify_proposal_change(new_id)
     349:         return new_id
     350:
   ...
     355:         marks it approved in persistence, and notifies about the change.
     356:         """
     357:         if (got := await self.persistence.get_policy_proposal(self.agent_id, proposal_id)) is None:
     358:             raise KeyError(str(proposal_id))
     359:         # Self-check the proposal program before activation
>>>  360:         if self.docker_client is not None:
>>>  361:             self.self_check(got.content)
     362:         # Activate policy (notifies via engine's set_policy)
     363:         await self.set_policy(got.content)
     364:         await self.persistence.approve_policy_proposal(self.agent_id, proposal_id)
     365:         await self.notify_proposal_change(proposal_id)
     366:
```

### `duplicate-bearer-extraction.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/auth.py`

> Both TokenAuthMiddleware and UITokenAuthMiddleware duplicate the same
> Bearer token extraction logic:
>
> TokenAuthMiddleware.dispatch() (lines 75-91):
>
> - Check if Authorization header exists
> - Split on whitespace
> - Validate format is "Bearer <token>"
> - Extract the token (parts[1])
>
> UITokenAuthMiddleware.**call**() (lines 144-161):
>
> - Same exact pattern with slightly different error handling
>
> This is classic code duplication. Both implementations:
>
> 1. Check if Authorization header exists
> 2. Split on whitespace
> 3. Validate format is "Bearer <token>"
> 4. Extract the token (parts[1])
>
> Fix options:
>
> 1. Extract a shared helper function: extract_bearer_token(auth_header)
>    that returns (token | None, error_dict | None)
> 2. Preferred: Use FastMCP's authentication patterns if available
>    (investigate if FastMCP provides built-in Bearer token middleware,
>    authentication dependency injection, or standard auth utilities)
> 3. Consolidate middleware: if both are doing the same thing (Bearer
>    token validation), consider a single parameterized middleware:
>    BearerTokenMiddleware(token_validator: Callable)
>
> Most modern Python web frameworks (FastAPI, Starlette, etc.) provide
> standardized auth patterns. If FastMCP builds on these, use the provided
> patterns instead of rolling custom middleware.
>
> This eliminates the duplication entirely by extracting or unifying the
> two use cases.

```
      70:     def __init__(self, app, token_mapping: TokenMapping):
      71:         super().__init__(app)
      72:         self.token_mapping = token_mapping
      73:
      74:     async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
>>>   75:         auth_header = request.headers.get("Authorization")
>>>   76:         if not auth_header:
>>>   77:             raise HTTPException(
>>>   78:                 status_code=status.HTTP_401_UNAUTHORIZED,
>>>   79:                 detail="Missing Authorization header",
>>>   80:                 headers={"WWW-Authenticate": "Bearer"},
>>>   81:             )
>>>   82:
>>>   83:         parts = auth_header.split()
>>>   84:         if len(parts) != 2 or parts[0].lower() != "bearer":
>>>   85:             raise HTTPException(
>>>   86:                 status_code=status.HTTP_401_UNAUTHORIZED,
>>>   87:                 detail="Invalid Authorization header format (expected: Bearer <token>)",
>>>   88:                 headers={"WWW-Authenticate": "Bearer"},
>>>   89:             )
>>>   90:
>>>   91:         token = parts[1]
      92:
      93:         if (agent_id := self.token_mapping.get_agent_id(token)) is None:
      94:             raise HTTPException(
      95:                 status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"}
      96:             )
   ...
     139:             await self.app(scope, receive, send)
     140:             return
     141:
     142:         # Parse headers
     143:         headers = dict(scope.get("headers", []))
>>>  144:         auth_header = headers.get(b"authorization", b"").decode()
>>>  145:
>>>  146:         # Validate authentication
>>>  147:         error_response = None
>>>  148:         if not auth_header:
>>>  149:             error_response = self._create_error_response(
>>>  150:                 401, "Missing Authorization header"
>>>  151:             )
>>>  152:         else:
>>>  153:             parts = auth_header.split()
>>>  154:             if len(parts) != 2 or parts[0].lower() != "bearer":
>>>  155:                 error_response = self._create_error_response(
>>>  156:                     401, "Invalid Authorization header format (expected: Bearer <token>)"
>>>  157:                 )
>>>  158:             elif parts[1] != self.expected_token:
>>>  159:                 error_response = self._create_error_response(
>>>  160:                     401, "Invalid token"
>>>  161:                 )
     162:
     163:         # Send error or continue
     164:         if error_response:
     165:             await send({
     166:                 "type": "http.response.start",
```

### `duplicated-agent-lookup.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/server.py`

> Methods `get_agent_mode` (lines 168-177), `get_infrastructure` (lines 158-165), and
> `remove_agent` (lines 224-237) duplicate the same "get agent or raise KeyError" logic.
>
> Each method: (1) Checks if agent_id in self.\_agents. (2) Gets self.\_agents[agent_id].agent.
> (3) Checks if agent is None. (4) Raises KeyError with similar messages. Only difference is
> what field they return (agent.mode vs agent.running) or what they do with the agent.
>
> Classic code duplication. Extract common helper `_get_agent_or_raise(agent_id) -> RunningAgent`
> that consolidates the lookup logic and raises KeyError if not found/initialized. Then simplify
> all callers to one-liners: `return self._get_agent_or_raise(agent_id).mode`,
> `return self._get_agent_or_raise(agent_id).running`, etc.
>
> Benefits: DRY - single implementation of lookup logic, consistent error messages, easier to
> maintain. Could even inline some one-liners if called in few places.

```
     153:             return (running, compositor_app)
     154:
     155:     async def get_compositor_app(self, agent_id: AgentID) -> FastAPI:
     156:         """Get compositor app for an agent_id."""
     157:         _, app = await self.get_or_create_infrastructure(agent_id)
>>>  158:         return app
>>>  159:
>>>  160:     def get_running_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure | None:
>>>  161:         """Get running infrastructure if it exists (doesn't create)."""
>>>  162:         entry = self._agents.get(agent_id)
>>>  163:         return entry.agent.running if entry and entry.agent else None
>>>  164:
>>>  165:     def known_agents(self) -> list[AgentID]:
     166:         return list(self._agents.keys())
     167:
     168:     async def get_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure:
     169:         """Raises KeyError if agent not in registry or not yet initialized."""
     170:         if agent_id not in self._agents:
   ...
     163:         return entry.agent.running if entry and entry.agent else None
     164:
     165:     def known_agents(self) -> list[AgentID]:
     166:         return list(self._agents.keys())
     167:
>>>  168:     async def get_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure:
>>>  169:         """Raises KeyError if agent not in registry or not yet initialized."""
>>>  170:         if agent_id not in self._agents:
>>>  171:             raise KeyError(f"Agent {agent_id} not found in registry")
>>>  172:         agent = self._agents[agent_id].agent
>>>  173:         if agent is None:
>>>  174:             raise KeyError(f"Agent {agent_id} infrastructure not yet initialized")
>>>  175:         return agent.running
>>>  176:
>>>  177:     def get_agent_mode(self, agent_id: AgentID) -> AgentMode:
     178:         """Raises KeyError if agent not in registry or not yet initialized."""
     179:         if agent_id not in self._agents:
     180:             raise KeyError(f"Agent {agent_id} not found in registry")
     181:         agent = self._agents[agent_id].agent
     182:         if agent is None:
   ...
     219:         if agent_id not in self._agents:
     220:             raise KeyError(f"Agent {agent_id} not found in registry")
     221:         running, _ = await self.get_or_create_infrastructure(agent_id)
     222:         return running
     223:
>>>  224:     async def remove_agent(self, agent_id: AgentID) -> None:
>>>  225:         """Remove and clean up agent infrastructure.
>>>  226:
>>>  227:         Closes the running infrastructure and removes the agent from the registry.
>>>  228:         """
>>>  229:         if agent_id not in self._agents:
>>>  230:             raise KeyError(f"Agent {agent_id} not found in registry")
>>>  231:
>>>  232:         agent = self._agents[agent_id].agent
>>>  233:         if agent is not None:
>>>  234:             await agent.running.close()
>>>  235:
>>>  236:         del self._agents[agent_id]
>>>  237:
     238:         await self.notify_agents_list_changed()
     239:
     240:     def _register_resources(self) -> None:
     241:         @self.resource("resource://agents/list", name="agents_list", mime_type="application/json")
     242:         async def list_agents() -> AgentsListResponse:
```

### `duplicated-get-proposal-check.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> The "get proposal or raise KeyError if None" pattern appears twice:
>
> Lines 357-358 (approve_proposal):
> if (got := await self.persistence.get_policy_proposal(...)) is None:
> raise KeyError(str(proposal_id))
>
> Lines 399-401 (proposal_detail):
> got = await self.persistence.get_policy_proposal(...)
> if got is None:
> raise KeyError(f"Proposal {id} not found")
>
> This is code duplication. Both:
>
> 1. Call get_policy_proposal()
> 2. Check if result is None
> 3. Raise KeyError with the proposal ID
>
> The "get or None" version (get_policy_proposal) might not be used anywhere
> without this immediate None check. If that's the case, the persistence
> method itself should raise.
>
> Fix options:
>
> 1. Preferred: Add get_policy_proposal_or_raise() to persistence layer that
>    raises KeyError instead of returning None
> 2. Alternative: Add local helper method \_get_proposal_or_raise()
> 3. Check if nullable version is actually needed - if never called without
>    the None check, delete it and make the main method raise
>
> This simplifies call sites to: got = await persistence.get_policy_proposal_or_raise(...)

```
     352:         """Approve a pending policy proposal by ID and activate it.
     353:
     354:         Retrieves the proposal, validates it, activates it as the current policy,
     355:         marks it approved in persistence, and notifies about the change.
     356:         """
>>>  357:         if (got := await self.persistence.get_policy_proposal(self.agent_id, proposal_id)) is None:
>>>  358:             raise KeyError(str(proposal_id))
     359:         # Self-check the proposal program before activation
     360:         if self.docker_client is not None:
     361:             self.self_check(got.content)
     362:         # Activate policy (notifies via engine's set_policy)
     363:         await self.set_policy(got.content)
   ...
     394:             )
     395:
     396:         @self.resource("resource://proposals/{id}", name="proposal_detail", mime_type="application/json")
     397:         async def proposal_detail(id: str) -> ProposalDetail:
     398:             """Get full proposal details including content and metadata."""
>>>  399:             got = await self.persistence.get_policy_proposal(self.agent_id, id)
>>>  400:             if got is None:
>>>  401:                 raise KeyError(f"Proposal {id} not found")
     402:
     403:             return ProposalDetail(
     404:                 id=got.id,
     405:                 status=ProposalStatus(got.status),
     406:                 created_at=got.created_at,
```

### `duplicated-run-phase-logic.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/server.py`

> Run phase determination logic is duplicated across `list_agents()` resource
> (lines 255-267) and `get_agent_info()` resource (lines 296-304).
>
> Both compute run phase and pending approvals count using identical logic:
> check if infra exists, count pending approvals, decide between IDLE/WAITING_APPROVAL/SAMPLING.
>
> Should extract a helper method:
>
> ```python
> def _determine_run_phase(
>     self, infra: RunningInfrastructure | None
> ) -> tuple[RunPhase, int]:
>     """Determine run phase and pending approvals count."""
>     if not infra:
>         return RunPhase.IDLE, 0
>
>     pending_approvals = len(infra.approval_hub.pending)
>     if pending_approvals > 0:
>         return RunPhase.WAITING_APPROVAL, pending_approvals
>     else:
>         return RunPhase.SAMPLING, pending_approvals
> ```
>
> Then call it: `run_phase, pending_approvals = self._determine_run_phase(infra)`

```
     250:
     251:                 # Get infrastructure if available
     252:                 infra = self.get_running_infrastructure(agent_id)
     253:                 live = infra is not None
     254:
>>>  255:                 # Compute status fields
>>>  256:                 pending_approvals = 0
>>>  257:                 run_phase = RunPhase.IDLE
>>>  258:
>>>  259:                 if infra:
>>>  260:                     # Get pending approvals count
>>>  261:                     pending_approvals = len(infra.approval_hub.pending)
>>>  262:
>>>  263:                     # Derive run phase
>>>  264:                     if pending_approvals > 0:
>>>  265:                         run_phase = RunPhase.WAITING_APPROVAL
>>>  266:                     elif live:
>>>  267:                         run_phase = RunPhase.SAMPLING
     268:
     269:                 # Determine capabilities
     270:                 is_local = mode == AgentMode.LOCAL
     271:
     272:                 agents.append(
   ...
     291:                 raise KeyError(f"Agent {agent_id} not found")
     292:
     293:             infra = self.get_running_infrastructure(agent_id)
     294:             live = infra is not None
     295:
>>>  296:             pending_approvals = 0
>>>  297:             run_phase = RunPhase.IDLE
>>>  298:
>>>  299:             if infra:
>>>  300:                 pending_approvals = len(infra.approval_hub.pending)
>>>  301:                 if pending_approvals > 0:
>>>  302:                     run_phase = RunPhase.WAITING_APPROVAL
>>>  303:                 elif live:
>>>  304:                     run_phase = RunPhase.SAMPLING
     305:
     306:             is_local = mode == AgentMode.LOCAL
     307:
     308:             return AgentInfo(
     309:                 id=agent_id,
```

### `keyerror-iteration-mismatch.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/server.py`

> Iteration catches KeyError when agent isn't initialized (lines 245-249):
>
> ```python
> for agent_id in self.known_agents():
>     try:
>         mode = self.get_agent_mode(agent_id)
>     except KeyError:
>         continue
> ```
>
> This is a code smell indicating poorly structured iteration. We iterate over
> `known_agents()` (returns ALL agent IDs), then call `get_agent_mode()` which
> raises KeyError for uninitialized agents. The mismatch between iteration source
> and accessed data forces the try/except.
>
> Should iterate over a structure where agent mode is guaranteed to exist:
>
> ```python
> for agent_id, entry in self._agents.items():
>     if entry.agent is None:
>         continue  # Skip uninitialized agents
>     agent = entry.agent
>     infra = agent.running
>     # ... rest of logic with guaranteed agent data
> ```
>
> Or explicitly decide whether to include uninitialized agents with different status.

```
     240:     def _register_resources(self) -> None:
     241:         @self.resource("resource://agents/list", name="agents_list", mime_type="application/json")
     242:         async def list_agents() -> AgentsListResponse:
     243:             """List all agents with detailed status."""
     244:             agents = []
>>>  245:             for agent_id in self.known_agents():
>>>  246:                 try:
>>>  247:                     mode = self.get_agent_mode(agent_id)
>>>  248:                 except KeyError:
>>>  249:                     continue
     250:
     251:                 # Get infrastructure if available
     252:                 infra = self.get_running_infrastructure(agent_id)
     253:                 live = infra is not None
     254:
```

### `methods-only-called-by-mcp.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> Several methods in ApprovalHub and ApprovalPolicyEngine are called ONLY by their
> corresponding MCP tools/resources, and nowhere else in production code:
>
> 1. ApprovalHub.resolve() - only called by approve/reject tools (lines 142, 148)
> 2. ApprovalPolicyEngine.set_policy() - only called by set_policy tool (lines 316, 322)
> 3. ApprovalPolicyEngine.create_proposal() - only called by create_proposal tool (lines 337, 349)
> 4. ApprovalPolicyEngine.approve_proposal() - only called by approve_proposal tool (lines 351, 366)
> 5. ApprovalPolicyEngine.reject_proposal() - only called by reject_proposal tool (lines 367, 370)
>
> These are unnecessary abstractions - the methods exist solely to be called by
> their corresponding MCP tool, with no other callers.
>
> Fix: Inline these methods directly into their MCP tool/resource implementations.
>
> Example for ApprovalHub.resolve():
>
> Before:
> def resolve(self, call_id: str, decision: ...) -> None:
> pending = self.\_pending.pop(call_id, None)
> ...
>
> @self.tool()
> async def approve(...):
> self.resolve(call_id, decision)
>
> After:
> @self.tool()
> async def approve(...): # Inline resolve logic
> pending = self.\_pending.pop(call_id, None)
> ...
>
> Benefits:
>
> - Removes unnecessary indirection
> - Makes tool implementation self-contained and easier to understand
> - Reduces method count in the class
> - Clearer that this is the ONLY place this logic is used
>
> Note: Methods like await_decision(), get_policy(), load_policy(), and self_check()
> should NOT be inlined - they're called externally by production code.

```
     137:                 fut = pending.future
     138:         if self._has_mcp:
     139:             await self.notify_approvals_changed()
     140:         return await fut
     141:
>>>  142:     def resolve(self, call_id: str, decision: ContinueDecision | DenyContinueDecision | AbortTurnDecision) -> None:
>>>  143:         pending = self._pending.pop(call_id, None)
>>>  144:         if pending is not None and not pending.future.done():
>>>  145:             pending.future.set_result(decision)
>>>  146:         # Schedule notification asynchronously if MCP is enabled
>>>  147:         if self._has_mcp:
>>>  148:             asyncio.create_task(self.notify_approvals_changed())
     149:
     150:     @property
     151:     def pending(self) -> dict[str, ToolCall]:
     152:         """Public view of pending approval tool calls (immutable contract by convention)."""
     153:         return {call_id: p.tool_call for call_id, p in self._pending.items()}
   ...
     311:         self._register_tools()
     312:
     313:     def get_policy(self) -> tuple[str, int]:
     314:         return self._policy_source, self._policy_id
     315:
>>>  316:     async def set_policy(self, source: str) -> int:
>>>  317:         """Store new policy and return its database ID."""
>>>  318:         self._policy_source = source
>>>  319:         # Call persistence to get ACTUAL ID
>>>  320:         self._policy_id = await self.persistence.set_policy(self.agent_id, content=source)
>>>  321:         await self.notify_policy_changed()
>>>  322:         return self._policy_id
     323:
     324:     # Internal load used on startup to hydrate content/id from persistence
     325:     def load_policy(self, source: str, *, policy_id: int) -> None:
     326:         # Hydrate from persistence without executing the code
     327:         self._policy_source = source
   ...
     332:             docker_client=self.docker_client,
     333:             source=source,
     334:             input_payload={"name": build_mcp_function(UI_SERVER_NAME, "send_message"), "arguments": {}},
     335:         )
     336:
>>>  337:     async def create_proposal(self, content: str) -> int:
>>>  338:         """Create a new policy proposal and return its ID.
>>>  339:
>>>  340:         Validates the proposal content if docker_client is available,
>>>  341:         persists it, and notifies about the change.
>>>  342:         """
>>>  343:         # Self-check proposal program if docker is available
>>>  344:         if self.docker_client is not None:
>>>  345:             self.self_check(content)
>>>  346:         # Create proposal and get actual database-assigned ID
>>>  347:         new_id = await self.persistence.create_policy_proposal(self.agent_id, proposal_id=0, content=content)
>>>  348:         await self.notify_proposal_change(new_id)
>>>  349:         return new_id
     350:
     351:     async def approve_proposal(self, proposal_id: int) -> None:
     352:         """Approve a pending policy proposal by ID and activate it.
     353:
     354:         Retrieves the proposal, validates it, activates it as the current policy,
   ...
     346:         # Create proposal and get actual database-assigned ID
     347:         new_id = await self.persistence.create_policy_proposal(self.agent_id, proposal_id=0, content=content)
     348:         await self.notify_proposal_change(new_id)
     349:         return new_id
     350:
>>>  351:     async def approve_proposal(self, proposal_id: int) -> None:
>>>  352:         """Approve a pending policy proposal by ID and activate it.
>>>  353:
>>>  354:         Retrieves the proposal, validates it, activates it as the current policy,
>>>  355:         marks it approved in persistence, and notifies about the change.
>>>  356:         """
>>>  357:         if (got := await self.persistence.get_policy_proposal(self.agent_id, proposal_id)) is None:
>>>  358:             raise KeyError(str(proposal_id))
>>>  359:         # Self-check the proposal program before activation
>>>  360:         if self.docker_client is not None:
>>>  361:             self.self_check(got.content)
>>>  362:         # Activate policy (notifies via engine's set_policy)
>>>  363:         await self.set_policy(got.content)
>>>  364:         await self.persistence.approve_policy_proposal(self.agent_id, proposal_id)
>>>  365:         await self.notify_proposal_change(proposal_id)
>>>  366:
     367:     async def reject_proposal(self, proposal_id: int) -> None:
     368:         """Reject a pending policy proposal by ID."""
     369:         await self.persistence.reject_policy_proposal(self.agent_id, proposal_id)
     370:         await self.notify_proposal_change(proposal_id)
     371:
   ...
     362:         # Activate policy (notifies via engine's set_policy)
     363:         await self.set_policy(got.content)
     364:         await self.persistence.approve_policy_proposal(self.agent_id, proposal_id)
     365:         await self.notify_proposal_change(proposal_id)
     366:
>>>  367:     async def reject_proposal(self, proposal_id: int) -> None:
>>>  368:         """Reject a pending policy proposal by ID."""
>>>  369:         await self.persistence.reject_policy_proposal(self.agent_id, proposal_id)
>>>  370:         await self.notify_proposal_change(proposal_id)
     371:
     372:     def _register_resources(self) -> None:
     373:         @self.resource("resource://policy.py", name="policy.py", mime_type="text/x-python")
     374:         def active_policy() -> str:
     375:             """Get the active approval policy source code."""
```

### `missing-call-id-silent-fail.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> Both `resolve()` and `await_decision()` silently handle missing call_ids instead of failing fast.
>
> Problem 1 (lines 142-148): `resolve()` uses `pop(call_id, None)` which swallows missing call_ids AND still
> sends
> notification even though nothing changed. Should use direct dict access (`self._pending[call_id]`) to raise
> KeyError
> on
> missing entries.
>
> Problem 2 (lines 131-137): `await_decision()` uses `.get(call_id)` and auto-creates new pending approval if
> missing.
> Unclear if intentional for first-time calls or if it should raise on truly missing entries.
>
> Use direct dict access to surface errors immediately rather than silently swallowing them. Only notify when
> state
> actually changes.

```
     137:                 fut = pending.future
     138:         if self._has_mcp:
     139:             await self.notify_approvals_changed()
     140:         return await fut
     141:
>>>  142:     def resolve(self, call_id: str, decision: ContinueDecision | DenyContinueDecision | AbortTurnDecision) -> None:
>>>  143:         pending = self._pending.pop(call_id, None)
>>>  144:         if pending is not None and not pending.future.done():
>>>  145:             pending.future.set_result(decision)
>>>  146:         # Schedule notification asynchronously if MCP is enabled
>>>  147:         if self._has_mcp:
>>>  148:             asyncio.create_task(self.notify_approvals_changed())
     149:
     150:     @property
     151:     def pending(self) -> dict[str, ToolCall]:
     152:         """Public view of pending approval tool calls (immutable contract by convention)."""
     153:         return {call_id: p.tool_call for call_id, p in self._pending.items()}
   ...
     126:             self._register_tools()
     127:
     128:     async def await_decision(
     129:         self, call_id: str, tool_call: ToolCall
     130:     ) -> ContinueDecision | DenyContinueDecision | AbortTurnDecision:
>>>  131:         async with self._lock:
>>>  132:             pending = self._pending.get(call_id)
>>>  133:             if pending is None:
>>>  134:                 fut = asyncio.get_running_loop().create_future()
>>>  135:                 self._pending[call_id] = PendingApproval(tool_call=tool_call, future=fut)
>>>  136:             else:
>>>  137:                 fut = pending.future
     138:         if self._has_mcp:
     139:             await self.notify_approvals_changed()
     140:         return await fut
     141:
     142:     def resolve(self, call_id: str, decision: ContinueDecision | DenyContinueDecision | AbortTurnDecision) -> None:
```

### `redundant-function-call-param.yaml` / `occ-0`

File: `adgn/src/adgn/agent/agent.py`

> The invoker callback is called with both a FunctionCall object and its arguments as separate parameters:
>
> ```python
> outcome = await invoker(fc, fc.arguments)
> ```
>
> The second parameter `fc.arguments` is redundant because it can be trivially derived from the first parameter
> (fc.arguments). This violates DRY - the invoker should only need the FunctionCall object.
>
> This is essentially a form of unnecessary aliasing/renaming where the caller is extracting a field and passing
> it
> separately, forcing the callee to receive the same information twice. The invoker implementation should
> extract
> arguments internally when needed.
>
> **Fix:**
> Change the invoker signature to accept only the FunctionCall object:
>
> ```python
> outcome = await invoker(fc)
> ```
>
> Update the invoker implementation to extract arguments internally:
>
> ```python
> async def invoker(fc: FunctionCall) -> Outcome:
>     arguments = fc.arguments
>     # ... rest of logic
> ```
>
> This removes the redundant parameter and makes the API cleaner by avoiding unnecessary data extraction at the
> call
> site.

```
     300:             cancelled_exc = anyio.get_cancelled_exc_class()
     301:
     302:             async def runner(fc: FunctionCallItem) -> None:
     303:                 nonlocal abort_triggered
     304:                 try:
>>>  305:                     outcome = await invoker(fc, fc.arguments)
     306:                 except cancelled_exc:
     307:                     return
     308:                 cid = _require_call_id(fc)
     309:                 results[cid] = outcome
     310:                 if isinstance(outcome, ToolCallAborted):
```

### `redundant-mode-field-derived.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/server.py`

> Line 40 defines `RunningAgent` dataclass with both `mode: AgentMode` and
> `local_runtime: LocalAgentRuntime | None` fields. The mode is completely determined by
> whether local_runtime exists: `mode = BRIDGE` when `local_runtime = None`,
> `mode = LOCAL` when `local_runtime is not None`.
>
> This is redundant storage. Mode should be derived from local_runtime presence, not stored
> separately. Storing both creates risk of inconsistency (can't get out of sync if mode is
> computed).
>
> Replace the `mode` field with a property that returns `AgentMode.LOCAL if self.local_runtime
else AgentMode.BRIDGE`. Update construction sites to omit the mode parameter. Benefits:
> single source of truth, cannot desync, less data to maintain, clear semantic relationship.

```
      35:
      36:
      37: @dataclass
      38: class RunningAgent:
      39:     """All infrastructure for a running agent (single point of optionality)."""
>>>   40:
      41:     running: RunningInfrastructure
      42:     compositor_app: FastAPI
      43:     mode: AgentMode
      44:     local_runtime: LocalAgentRuntime | None  # None for bridge agents
      45:
```

### `redundant-status-conversion.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> Both resource handlers convert p.status and got.status to ProposalStatus:
>
> Line 388: status=ProposalStatus(p.status)
> Line 405: status=ProposalStatus(got.status)
>
> This conversion is necessarily redundant:
>
> Case 1: If p.status and got.status are already ProposalStatus, then
> ProposalStatus(p.status) is a no-op that should be p.status directly.
>
> Case 2: If p.status is a different type (e.g., string or database enum),
> this indicates a type inconsistency that should be fixed upstream.
>
> Similar to finding 024 (ApprovalOutcome vs ApprovalStatus), this suggests
> ProposalStatus might have a duplicate in the persistence layer, requiring
> conversion at the boundary.
>
> Fix options:
>
> 1. If already ProposalStatus: remove conversion, use status=p.status
> 2. If persistence returns different type: unify types - make persistence
>    return ProposalStatus directly, OR move conversion into persistence
>    layer's model so it returns objects with ProposalStatus already set
> 3. Most likely: duplicate enums that should be unified
>
> This is a type correctness issue - types should match at boundaries
> without runtime conversion.

```
     383:             return ProposalsList(
     384:                 agent_id=self.agent_id,
     385:                 proposals=[
     386:                     ProposalDescriptor(
     387:                         id=p.id,
>>>  388:                         status=ProposalStatus(p.status),
     389:                         created_at=p.created_at,
     390:                         decided_at=p.decided_at,
     391:                     )
     392:                     for p in proposals
     393:                 ]
   ...
     400:             if got is None:
     401:                 raise KeyError(f"Proposal {id} not found")
     402:
     403:             return ProposalDetail(
     404:                 id=got.id,
>>>  405:                 status=ProposalStatus(got.status),
     406:                 created_at=got.created_at,
     407:                 decided_at=got.decided_at,
     408:                 content=got.content,
     409:             )
     410:
```

### `redundant-total-tokens-field.yaml` / `occ-0`

File: `adgn/src/adgn/agent/handler.py`

> The TokenUsage model has a total_tokens field that is a trivial sum of two other fields:
>
> class TokenUsage(BaseModel):
> input_tokens: int | None = Field(None, ...)
> output_tokens: int | None = Field(None, ...)
> total_tokens: int | None = Field(None, description="Total tokens consumed (input + output)")
>
> The total_tokens field is redundant:
>
> - It's always input_tokens + output_tokens
> - No additional information
> - Must be kept in sync manually (error-prone)
> - Wastes storage/bandwidth
>
> This violates DRY - the total is trivially computable from the parts.
>
> Fix options:
>
> 1. Preferred: Remove total_tokens field entirely. Callers compute:
>    total = (usage.input_tokens or 0) + (usage.output_tokens or 0)
> 2. For API compatibility, make it a computed property:
>    @property
>    def total_tokens(self) -> int | None:
>    if self.input_tokens is None and self.output_tokens is None:
>    return None
>    return (self.input_tokens or 0) + (self.output_tokens or 0)
>
> This ensures:
>
> - Single source of truth (input + output)
> - Cannot get out of sync
> - No redundant storage
> - Backward compatible if needed

```
      24:     model: str = Field(description="Model name used for the request")
      25:     input_tokens: int | None = Field(None, description="Number of input tokens consumed")
      26:     input_tokens_details: InputTokensDetails | None = Field(None, description="Breakdown of input token usage")
      27:     output_tokens: int | None = Field(None, description="Number of output tokens generated")
      28:     output_tokens_details: OutputTokensDetails | None = Field(None, description="Breakdown of output token usage")
>>>   29:     total_tokens: int | None = Field(None, description="Total tokens consumed (input + output)")
      30:
      31:
      32: # ---- Typed events (no shared runtime base required) ----
      33: class UserText(BaseModel):
      34:     text: str
```

### `split-with-ui-conditional.yaml` / `occ-0`

File: `adgn/src/adgn/agent/runtime/builder.py`

> Lines 70-72 and 84-86 split with_ui conditional logic unnecessarily. First
> block creates ui_bus and connection_manager, then builder.start() executes,
> then second block attaches UI sidecar. These operations are independent and
> could be consolidated.
>
> **Problem:** Split conditional increases cognitive load and makes control flow
> harder to follow. The two if with_ui blocks could be merged, or consolidated
> entirely by moving ConnectionManager construction inline and creating ui_bus
> only when needed.
>
> **Fix:** Consolidate into single block after builder.start() by using inline
> conditional for connection_manager and creating ui_bus only in the final if
> block. Eliminates split conditional.

```
      65:     await runtime.close()
      66:     await running.close()
      67:     """
      68:     ui_bus: ServerBus | None = None
      69:     connection_manager: ConnectionManager | None = None
>>>   70:     if with_ui:
>>>   71:         ui_bus = ServerBus()
>>>   72:         connection_manager = ConnectionManager()
      73:
      74:     builder = MCPInfrastructure(
      75:         agent_id=agent_id,
      76:         persistence=persistence,
      77:         docker_client=docker_client,
   ...
      79:         connection_manager=connection_manager,
      80:     )
      81:
      82:     running = await builder.start(mcp_config)
      83:
>>>   84:     if with_ui:
>>>   85:         assert ui_bus is not None
>>>   86:         await running.attach_sidecar(UISidecar(ui_bus))
      87:     await running.attach_sidecar(ChatSidecar())
      88:     await running.attach_sidecar(LoopControlSidecar())
      89:
      90:     runtime = LocalAgentRuntime(
      91:         running=running,
```

### `swallow-initialization-error.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/compositor_factory.py`

> Lines 93-95 catch exceptions when mounting agent compositors and continue
> silently with logged error. This is dangerous initialization behavior.
>
> **Why this is wrong:**
>
> 1. Silent failure: server starts but missing critical infrastructure
> 2. Inconsistent state: some agents mounted, others missing
> 3. No recovery path: failed agent is simply absent forever
> 4. Violates fail-fast: better to crash loudly than fail silently
> 5. Debugging nightmare: errors logged but system appears "healthy"
>
> **Mounting compositors is critical infrastructure.** If it fails, the server
> is misconfigured and should not start.
>
> **Fix:** Remove try/except entirely. Let exception propagate so server crashes
> during startup, operator sees error immediately, and system never enters
> partially-broken state. Initialization failures should crash.
>
> If partial mounting is truly needed (unlikely), requires explicit tracking,
> health checks, error APIs, recovery logic, and documentation.

```
      88:     for agent_id in registry.known_agents():
      89:         try:
      90:             agent_comp = await create_agent_compositor(agent_id, registry)
      91:             await global_comp.mount_inproc(f"agent{agent_id}", agent_comp)
      92:             logger.info(f"Mounted agent compositor for agent {agent_id}")
>>>   93:         except Exception as e:
>>>   94:             logger.error(f"Failed to mount compositor for agent {agent_id}: {e}", exc_info=True)
>>>   95:             # Continue mounting other agents
      96:
      97:     # Standard infrastructure (resources aggregator, compositor metadata, admin)
      98:     if gateway_client is not None:
      99:         await mount_standard_inproc_servers(global_comp, gateway_client)
     100:         logger.info("Mounted standard infrastructure servers")
```

### `ternary-oneliner-needed.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/cli.py`

> The policy_source initialization uses two lines when it could be a single ternary expression:
>
> ```python
> policy_source = None
> if initial_policy:
>     policy_source = initial_policy.read_text()
> ```
>
> This is a simple conditional assignment - perfect for a ternary operator.
>
> Replace with ternary oneliner:
>
> ```python
> policy_source = initial_policy.read_text() if initial_policy else None
> ```
>
> Benefits:
>
> - More concise (one line vs three)
> - Standard Python idiom for conditional assignment
> - Clearer intent (assigning based on condition)
> - Variable is const-assigned (not mutated)

```
      83:     if mcp_config:
      84:         config = MCPConfig.model_validate_json(mcp_config.read_text())
      85:     else:
      86:         config = MCPConfig(mcpServers={})
      87:
>>>   88:     policy_source = None
>>>   89:     if initial_policy:
>>>   90:         policy_source = initial_policy.read_text()
      91:
      92:     asyncio.run(
      93:         _run_server(
      94:             agent_id=agent_id,
      95:             auth_tokens_path=auth_tokens,
```

### `test-dup-responses-create.yaml` / `occ-0`

File: `adgn/tests/agent/e2e/test_mcp_concurrent.py`

> The pattern of creating stateful mock response handlers (a dict with `{"i": 0}` and an
> `async def responses_create(_req)` function that increments the counter and returns
> tool calls from a sequence) is duplicated 16+ times across the test suite.
>
> **Why this is problematic:**
>
> - 40+ lines of duplicated code across test suite
> - Each occurrence is essentially identical with minor variations
> - Changes to the pattern must be replicated everywhere
> - Increases maintenance burden and risk of inconsistency
>
> **Fix:** Extract into a shared `make_stateful_responses(responses_factory, response_sequence)`
> helper in conftest.py or tests/agent/helpers.py that takes a list of (function_name,
> server_name, params) tuples and returns the stateful handler. This eliminates duplication
> across all 16+ instances.
>
> **Note:** Three instances in test_mcp_concurrent.py

```
      95:     - Subscribe to resource
      96:     - Unsubscribe
      97:     - Resubscribe
      98:     - State consistency maintained
      99:     """
>>>  100:     state = {"i": 0}
>>>  101:
>>>  102:     async def responses_create(_req):
>>>  103:         i = state["i"]
>>>  104:         state["i"] = i + 1
>>>  105:         if i == 0:
>>>  106:             return responses_factory.make_tool_call(
>>>  107:                 build_mcp_function("echo", "echo"), {"text": "first call"}, call_id="call_echo_1"
>>>  108:             )
>>>  109:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
>>>  110:
     111:     s = run_server(lambda model: make_mock(responses_create))
     112:     base = s["base_url"]
     113:
     114:     # Create agent
     115:     agent_id = api_create_agent(base)
   ...
     154:     - Subscribe to agent resource
     155:     - Delete agent via API
     156:     - No errors occur
     157:     - Graceful cleanup
     158:     """
>>>  159:     state = {"i": 0}
>>>  160:
>>>  161:     async def responses_create(_req):
>>>  162:         i = state["i"]
>>>  163:         state["i"] = i + 1
>>>  164:         if i == 0:
>>>  165:             return responses_factory.make_tool_call(
>>>  166:                 build_mcp_function("echo", "echo"), {"text": "test"}, call_id="call_echo_1"
>>>  167:             )
>>>  168:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
>>>  169:
     170:     s = run_server(lambda model: make_mock(responses_create))
     171:     base = s["base_url"]
     172:
     173:     # Create agent
     174:     agent_id = api_create_agent(base)
   ...
     264:     Verifies:
     265:     - Subscribe to resource
     266:     - Simulate network hiccup (pause/resume via offline mode)
     267:     - Subscription recovers correctly
     268:     """
>>>  269:     state = {"i": 0}
>>>  270:
>>>  271:     async def responses_create(_req):
>>>  272:         i = state["i"]
>>>  273:         state["i"] = i + 1
>>>  274:         if i == 0:
>>>  275:             return responses_factory.make_tool_call(
>>>  276:                 build_mcp_function("echo", "echo"), {"text": "before disconnect"}, call_id="call_echo_1"
>>>  277:             )
>>>  278:         if i == 1:
>>>  279:             return responses_factory.make_tool_call(
>>>  280:                 build_mcp_function("echo", "echo"), {"text": "after disconnect"}, call_id="call_echo_2"
>>>  281:             )
>>>  282:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
>>>  283:
     284:     s = run_server(lambda model: make_mock(responses_create))
     285:     base = s["base_url"]
     286:
     287:     # Create agent
     288:     agent_id = api_create_agent(base)
```

### `test-dup-responses-create.yaml` / `occ-1`

File: `adgn/tests/agent/e2e/test_mcp_errors.py`

> The pattern of creating stateful mock response handlers (a dict with `{"i": 0}` and an
> `async def responses_create(_req)` function that increments the counter and returns
> tool calls from a sequence) is duplicated 16+ times across the test suite.
>
> **Why this is problematic:**
>
> - 40+ lines of duplicated code across test suite
> - Each occurrence is essentially identical with minor variations
> - Changes to the pattern must be replicated everywhere
> - Increases maintenance burden and risk of inconsistency
>
> **Fix:** Extract into a shared `make_stateful_responses(responses_factory, response_sequence)`
> helper in conftest.py or tests/agent/helpers.py that takes a list of (function_name,
> server_name, params) tuples and returns the stateful handler. This eliminates duplication
> across all 16+ instances.
>
> **Note:** Four instances in test_mcp_errors.py

```
      68:     - Error message is shown to user
      69:     - Agent continues to function after error
      70:     """
      71:     state = {"i": 0}
      72:
>>>   73:     async def responses_create(_req):
>>>   74:         i = state["i"]
>>>   75:         state["i"] = i + 1
>>>   76:         if i == 0:
>>>   77:             # First call: try to use a tool from the broken server
>>>   78:             return responses_factory.make_tool_call(
>>>   79:                 build_mcp_function("broken", "broken_tool"), {"trigger": "break"}, call_id="call_broken_1"
>>>   80:             )
>>>   81:         # Second call: end turn
>>>   82:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
      83:
      84:     s = run_server(lambda model: make_mock(responses_create))
      85:     base = s["base_url"]
      86:
      87:     # Create agent
   ...
     122:     - Timeout message is shown to user
     123:     - System remains responsive after timeout
     124:     """
     125:     state = {"i": 0}
     126:
>>>  127:     async def responses_create(_req):
>>>  128:         i = state["i"]
>>>  129:         state["i"] = i + 1
>>>  130:         if i == 0:
>>>  131:             # Try to call the slow tool with a reasonable delay
>>>  132:             return responses_factory.make_tool_call(
>>>  133:                 build_mcp_function("slow", "slow_tool"), {"delay_seconds": 2}, call_id="call_slow_1"
>>>  134:             )
>>>  135:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
     136:
     137:     s = run_server(lambda model: make_mock(responses_create))
     138:     base = s["base_url"]
     139:
     140:     # Create agent
   ...
     179:     - System can recover or fail gracefully
     180:     """
     181:     # Use a simple echo server that we can "kill" by having it fail
     182:     state = {"i": 0, "should_fail": False}
     183:
>>>  184:     async def responses_create(_req):
>>>  185:         i = state["i"]
>>>  186:         state["i"] = i + 1
>>>  187:         if i == 0:
>>>  188:             # First call: use echo tool
>>>  189:             return responses_factory.make_tool_call(
>>>  190:                 build_mcp_function("echo", "echo"), {"text": "test message"}, call_id="call_echo_1"
>>>  191:             )
>>>  192:         # Subsequent calls: end turn
>>>  193:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
     194:
     195:     s = run_server(lambda model: make_mock(responses_create))
     196:     base = s["base_url"]
     197:
     198:     # Create agent
   ...
     244:     - No lingering references or memory leaks
     245:     - UI handles agent deletion appropriately
     246:     """
     247:     state = {"i": 0}
     248:
>>>  249:     async def responses_create(_req):
>>>  250:         i = state["i"]
>>>  251:         state["i"] = i + 1
>>>  252:         if i == 0:
>>>  253:             return responses_factory.make_tool_call(
>>>  254:                 build_mcp_function("echo", "echo"), {"text": "test"}, call_id="call_echo_1"
>>>  255:             )
>>>  256:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
     257:
     258:     s = run_server(lambda model: make_mock(responses_create))
     259:     base = s["base_url"]
     260:
     261:     # Create agent
```

### `test-dup-responses-create.yaml` / `occ-2`

File: `adgn/tests/agent/e2e/test_mcp_edge_cases.py`

> The pattern of creating stateful mock response handlers (a dict with `{"i": 0}` and an
> `async def responses_create(_req)` function that increments the counter and returns
> tool calls from a sequence) is duplicated 16+ times across the test suite.
>
> **Why this is problematic:**
>
> - 40+ lines of duplicated code across test suite
> - Each occurrence is essentially identical with minor variations
> - Changes to the pattern must be replicated everywhere
> - Increases maintenance burden and risk of inconsistency
>
> **Fix:** Extract into a shared `make_stateful_responses(responses_factory, response_sequence)`
> helper in conftest.py or tests/agent/helpers.py that takes a list of (function_name,
> server_name, params) tuples and returns the stateful handler. This eliminates duplication
> across all 16+ instances.
>
> **Note:** Five instances in test_mcp_edge_cases.py

```
      33:     - Agent can subscribe to a non-existent resource URI
      34:     - System returns appropriate error via notifications
      35:     - UI displays error state without crashing
      36:     - Agent continues to function after the error
      37:     """
>>>   38:     state = {"i": 0}
>>>   39:
>>>   40:     async def responses_create(_req):
>>>   41:         i = state["i"]
>>>   42:         state["i"] = i + 1
>>>   43:         if i == 0:
>>>   44:             # Try to subscribe to invalid resource
>>>   45:             return responses_factory.make_tool_call(
>>>   46:                 build_mcp_function("resources", "subscribe"),
>>>   47:                 {"server": "test_server", "uri": "resource://invalid/nonexistent"},
>>>   48:                 call_id="call_invalid_sub",
>>>   49:             )
>>>   50:         # End turn
>>>   51:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
      52:
      53:     s = run_server(lambda model: make_mock(responses_create))
      54:     base = s["base_url"]
      55:
      56:     # Create agent
   ...
      95:     - Immediately deleting the agent succeeds
      96:     - No resource leaks or dangling references
      97:     - System handles rapid lifecycle transitions gracefully
      98:     """
      99:
>>>  100:     async def responses_create(_req):
>>>  101:         return responses_factory.make_assistant_message("ok")
     102:
     103:     s = run_server(lambda model: make_mock(responses_create))
     104:     base = s["base_url"]
     105:
     106:     # Rapidly create and delete multiple agents
   ...
     134:     - Simulate server disconnect
     135:     - Reconnect server
     136:     - Verify subscription state is handled gracefully
     137:     - UI reflects current server state
     138:     """
>>>  139:     state = {"i": 0}
>>>  140:
>>>  141:     async def responses_create(_req):
>>>  142:         i = state["i"]
>>>  143:         state["i"] = i + 1
>>>  144:         if i == 0:
>>>  145:             # Subscribe to a resource
>>>  146:             return responses_factory.make_tool_call(
>>>  147:                 build_mcp_function("resources", "subscribe"),
>>>  148:                 {"server": "echo", "uri": "resource://test/data"},
>>>  149:                 call_id="call_sub_1",
>>>  150:             )
>>>  151:         # End turn
>>>  152:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
     153:
     154:     s = run_server(lambda model: make_mock(responses_create))
     155:     base = s["base_url"]
     156:
     157:     # Create agent
   ...
     202:     - UI shows appropriate error state
     203:     - System remains stable
     204:
     205:     Note: This test simulates the condition by using a slow/hanging resource.
     206:     """
>>>  207:     state = {"i": 0}
>>>  208:
>>>  209:     async def responses_create(_req):
>>>  210:         i = state["i"]
>>>  211:         state["i"] = i + 1
>>>  212:         if i == 0:
>>>  213:             # Try to read a resource that will timeout/hang
>>>  214:             return responses_factory.make_tool_call(
>>>  215:                 build_mcp_function("resources", "read"),
>>>  216:                 {"server": "slow_server", "uri": "resource://slow/data", "start_offset": 0, "max_bytes": 1024},
>>>  217:                 call_id="call_read_slow",
>>>  218:             )
>>>  219:         # End turn
>>>  220:         return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
     221:
     222:     s = run_server(lambda model: make_mock(responses_create))
     223:     base = s["base_url"]
     224:
     225:     # Create agent
   ...
     270:     Verifies:
     271:     - Agent creation succeeds
     272:     - Attempting to subscribe before MCP servers are attached is handled gracefully
     273:     - System queues or rejects the request appropriately
     274:     - No crashes or undefined behavior
>>>  275:     """
>>>  276:
>>>  277:     async def responses_create(_req):
>>>  278:         # Try to subscribe immediately (before server attached)
>>>  279:         return responses_factory.make_tool_call(
>>>  280:             build_mcp_function("resources", "subscribe"),
>>>  281:             {"server": "not_yet_attached", "uri": "resource://test/data"},
>>>  282:             call_id="call_early_sub",
>>>  283:         )
     284:
     285:     s = run_server(lambda model: make_mock(responses_create))
     286:     base = s["base_url"]
     287:
     288:     # Create agent (no MCP servers attached yet)
```

### `test-error-swallow.yaml` / `occ-0`

File: `adgn/tests/agent/e2e/test_mcp_concurrent.py`

> Tests use bare `except Exception:` blocks that swallow all errors, hiding real failures.
>
> Two pattern variations: `except Exception: break` in retry loops (lines 75-82 in
> test_mcp_concurrent.py) and `except Exception: pass` for optional operations (lines 171-175,
> 251-255 in test_mcp_edge_cases.py).
>
> This hides actual errors during test execution. If operations fail for real reasons (element
> not found, page crashed, network failure, timeout), the test silently continues and may pass
> when it should fail.
>
> Remove try/except entirely if operation should succeed, or catch only specific expected
> exceptions (TimeoutError, ElementNotFoundError). Let real errors propagate. If approvals are
> optional, check conditions explicitly rather than swallowing all errors.
>
> **Note:** Error-swallowing in approval loop with `except Exception: break`

```
      70:
      71:     # Wait for approvals to appear (we should see multiple pending)
      72:     wait_for_pending_approvals(page)
      73:
      74:     # Auto-approve all pending approvals by clicking approve repeatedly
>>>   75:     for _ in range(15):  # 5 agents x 3 calls each = 15 approvals
>>>   76:         try:
>>>   77:             approve_btn = page.get_by_role("button", name="Approve").first
>>>   78:             if approve_btn.count() > 0:
>>>   79:                 approve_btn.click()
>>>   80:                 page.wait_for_timeout(100)  # Small delay between approvals
>>>   81:         except Exception:
>>>   82:             break
      83:
      84:     # Verify all agents finished (check for finished status)
      85:     # The UI should show updates for all agents without missing any
      86:     page.wait_for_timeout(2000)  # Wait for all updates to propagate
      87:
```

### `test-error-swallow.yaml` / `occ-1`

File: `adgn/tests/agent/e2e/test_mcp_edge_cases.py`

> Tests use bare `except Exception:` blocks that swallow all errors, hiding real failures.
>
> Two pattern variations: `except Exception: break` in retry loops (lines 75-82 in
> test_mcp_concurrent.py) and `except Exception: pass` for optional operations (lines 171-175,
> 251-255 in test_mcp_edge_cases.py).
>
> This hides actual errors during test execution. If operations fail for real reasons (element
> not found, page crashed, network failure, timeout), the test silently continues and may pass
> when it should fail.
>
> Remove try/except entirely if operation should succeed, or catch only specific expected
> exceptions (TimeoutError, ElementNotFoundError). Let real errors propagate. If approvals are
> optional, check conditions explicitly rather than swallowing all errors.
>
> **Note:** Error-swallowing in optional approval checks with `except Exception: pass`

```
     166:
     167:     # Send prompt that triggers subscription
     168:     send_prompt(page, "subscribe to resource")
     169:
     170:     # Wait for approval (if needed) and approve
>>>  171:     try:
>>>  172:         wait_for_pending_approvals(page, count=1, timeout=5000)
>>>  173:         approve_first_pending(page)
>>>  174:     except Exception:
>>>  175:         pass  # No approval needed
     176:
     177:     # Wait for run to finish
     178:     page.get_by_text("Status: finished").wait_for(timeout=10000)
     179:
     180:     # Detach server (simulate disconnect)
   ...
     246:
     247:     # Send prompt that triggers slow resource read
     248:     send_prompt(page, "read slow resource")
     249:
     250:     # Wait for approval if needed and approve
>>>  251:     try:
>>>  252:         wait_for_pending_approvals(page, count=1, timeout=5000)
>>>  253:         approve_first_pending(page)
>>>  254:     except Exception:
>>>  255:         pass  # No approval needed
     256:
     257:     # Wait for run to complete (with extended timeout due to slow resource)
     258:     page.get_by_text("Status: finished").wait_for(timeout=15000)
     259:
     260:     # Verify the timeline is still accessible
```

### `test-overuse-suppress-exception.yaml` / `occ-0`

File: `adgn/tests/agent/e2e/test_mcp_errors.py`

> Multiple uses of `with suppress(Exception):` to hide errors in tests that are meant
> to verify error handling behavior.
>
> **Current pattern (appears 5 times):**
>
> ```python
> with suppress(Exception):
>     # Server attachment might fail; we're testing error handling
>     requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
> ```
>
> **Why this is problematic:**
> If the test is meant to verify error handling, it should explicitly check for expected
> errors, not suppress all exceptions. Tests that suppress exceptions provide no signal
> when they fail - they just silently skip over problems.
>
> When an operation is expected to fail in a test:
>
> - Use `pytest.raises(SpecificException)` to verify the specific error occurs
> - Assert on the error message or error state
> - Don't hide failures with blanket suppression
>
> **Correct approach:**
> Remove `suppress(Exception)` calls. Either:
>
> 1. Assert the operation succeeds (if it should)
> 2. Assert the operation fails with specific exception (using pytest.raises)
> 3. Verify the system handles the error appropriately (check error state, logs, etc.)
>
> Suppressing all exceptions makes the test unable to detect when something goes wrong.

```
      89:
      90:     # Attach broken MCP server
      91:     spec = {"broken": {"transport": "inproc", "factory": "tests.agent.e2e.test_mcp_errors:_make_broken_server"}}
      92:     # Note: We use a factory string that will attempt to create a server with malformed responses
      93:     # This tests the error path when server produces invalid data
>>>   94:     with suppress(Exception):
>>>   95:         # Server attachment might fail; we're testing error handling
>>>   96:         requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
      97:
      98:     # Open UI
      99:     page.goto(base + f"/?agent_id={agent_id}")
     100:
     101:     # Wait for WS connection (may succeed even if MCP attachment failed)
   ...
      97:
      98:     # Open UI
      99:     page.goto(base + f"/?agent_id={agent_id}")
     100:
     101:     # Wait for WS connection (may succeed even if MCP attachment failed)
>>>  102:     with suppress(Exception):
>>>  103:         page.locator(".ws .dot.on").wait_for(timeout=5000)
     104:
     105:     # Try to interact and verify UI shows error gracefully
     106:     send_prompt(page, "test broken resource")
     107:
     108:     # Give it a moment to process
   ...
     142:
     143:     # Attach slow MCP server (as in-proc)
     144:     # Note: For this test to work properly, we'd need the server to be properly instantiated
     145:     # For now, we test the UI's resilience to slow operations
     146:     spec = {"slow": {"transport": "inproc", "factory": "tests.agent.e2e.test_mcp_errors:_make_slow_server"}}
>>>  147:     with suppress(Exception):
>>>  148:         requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
     149:
     150:     # Open UI
     151:     page.goto(base + f"/?agent_id={agent_id}")
     152:
     153:     with suppress(Exception):
   ...
     148:         requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
     149:
     150:     # Open UI
     151:     page.goto(base + f"/?agent_id={agent_id}")
     152:
>>>  153:     with suppress(Exception):
>>>  154:         # Wait for connection with shorter timeout
>>>  155:         page.locator(".ws .dot.on").wait_for(timeout=5000)
     156:
     157:     # Verify UI is still responsive
     158:     assert page.title() is not None
     159:
     160:     # Try to interact
   ...
     225:
     226:     # Verify UI is still responsive and shows appropriate state
     227:     assert page.title() is not None
     228:
     229:     # Check if WS connection is still active (should be, agent still exists)
>>>  230:     with suppress(Exception):
>>>  231:         # If connection indicator changed, that's expected behavior
>>>  232:         page.locator(".ws .dot.on").wait_for(timeout=2000)
     233:
     234:     s["stop"]()
     235:
     236:
     237: def test_subscription_to_deleted_agent(page: Page, run_server, responses_factory):
```

### `test-unimplemented-ui-fallback.yaml` / `occ-0`

File: `adgn/tests/agent/e2e/test_mcp_errors.py`

> Lines 44-55 and 288-298 in test_mcp_errors.py check for unimplemented UI error elements
> (.error, .alert-error, [data-testid='error-message']) with fallback logic that accepts
> completely different behaviors (WS connection status).
>
> Three problems: tests unimplemented features (backend no longer implements those error UI
> elements); swallows all errors with bare `except Exception:` hiding actual test failures;
> accepts contradictory outcomes (either error indicators appear OR WS disconnects - having
> both as acceptable makes tests meaningless, they pass regardless of what happens).
>
> Tests should NOT have fallback logic accepting massively different behaviors. Pick ONE
> expected behavior per test and assert it happens. Remove tests for unimplemented UI features
> or implement the features first. Remove error-swallowing exception handlers. If testing error
> states, verify the specific error indicator that actually exists.
>
> **Note:** Two instances with unimplemented UI element checks and contradictory fallback logic

```
      39:     nonexistent_id = "00000000-0000-0000-0000-000000000000"
      40:     page.goto(base + f"/?agent_id={nonexistent_id}")
      41:
      42:     # Verify error message appears (UI should show that agent doesn't exist)
      43:     # The exact error message may vary, but we should see some indication of failure
>>>   44:     try:
>>>   45:         # Wait for either an error message or connection failure indicator
>>>   46:         error_indicator = page.locator(".error, .alert-error, [data-testid='error-message']").first
>>>   47:         error_indicator.wait_for(state="visible", timeout=5000)
>>>   48:         # Verify error text mentions the problem
>>>   49:         error_text = error_indicator.inner_text()
>>>   50:         assert_that(error_text, has_length(greater_than(0)), "Error message should not be empty")
>>>   51:     except Exception:
>>>   52:         # Alternative: check if WS connection shows as disconnected/failed
>>>   53:         ws_status = page.locator(".ws .dot")
>>>   54:         # Should not show "on" (connected) state
>>>   55:         ws_status.wait_for(timeout=5000)
      56:
      57:     # Verify UI is still responsive (not crashed)
      58:     assert page.title() is not None
      59:
      60:     s["stop"]()
   ...
     283:     # Wait a bit for cleanup to propagate
     284:     page.wait_for_timeout(1000)
     285:
     286:     # Try to interact with UI after agent deletion
     287:     # The WS connection should close or show disconnected state
>>>  288:     try:
>>>  289:         # Check if WS indicator shows disconnected
>>>  290:         page.locator(".ws .dot.off, .ws .dot:not(.on)").wait_for(timeout=5000)
>>>  291:     except Exception:
>>>  292:         # Or check for an error message
>>>  293:         try:
>>>  294:             error_indicator = page.locator(".error, .alert-error").first
>>>  295:             error_indicator.wait_for(state="visible", timeout=5000)
>>>  296:         except Exception:
>>>  297:             # At minimum, verify UI is still responsive
>>>  298:             pass
     299:
     300:     # Verify UI is still responsive
     301:     assert page.title() is not None
     302:
     303:     # Try to navigate back to agent (should fail gracefully)
```

### `untyped-tuple-returns.yaml` / `occ-0`

File: `adgn/src/adgn/agent/persist/__init__.py`

> Lines 188-189 define policy persistence methods with unclear return types:
> `get_latest_policy` returns `tuple[str, int] | None` where tuple unpacking
> requires remembering the order and the int's meaning (policy ID) is non-obvious.
> `set_policy` returns an undocumented int (the database-assigned policy ID).
>
> Problems: Tuple unpacking requires remembering element order, no semantic meaning
> to tuple positions, unclear what the int represents, requires checking None before
> unpacking, callers must know implementation details.
>
> Replace with a typed object (PolicyRecord or NamedTuple) containing id, content,
> timestamp, and agent_id fields. This provides self-documenting field names,
> type safety, IDE autocomplete, and clear semantics. Alternatively, at minimum
> add docstring documenting what the int represents.

```
     183:     async def list_runs(self, *, agent_id: AgentID | None = None, limit: int = 50) -> list[RunRow]: ...
     184:     async def get_run(self, run_id: UUID) -> RunRow | None: ...
     185:     async def load_events(self, run_id: UUID) -> list[EventRecord]: ...
     186:
     187:     # Approval policy (per-agent) --------------------------------------------
>>>  188:     async def get_latest_policy(self, agent_id: AgentID) -> tuple[str, int] | None: ...
     189:     async def set_policy(self, agent_id: AgentID, *, content: str) -> int: ...
     190:
     191:     # Approval policy proposals (single store impl: SQLite)
     192:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: int, content: str) -> int: ...
     193:     async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]: ...
   ...
     184:     async def get_run(self, run_id: UUID) -> RunRow | None: ...
     185:     async def load_events(self, run_id: UUID) -> list[EventRecord]: ...
     186:
     187:     # Approval policy (per-agent) --------------------------------------------
     188:     async def get_latest_policy(self, agent_id: AgentID) -> tuple[str, int] | None: ...
>>>  189:     async def set_policy(self, agent_id: AgentID, *, content: str) -> int: ...
     190:
     191:     # Approval policy proposals (single store impl: SQLite)
     192:     async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: int, content: str) -> int: ...
     193:     async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]: ...
     194:     async def get_policy_proposal(self, agent_id: AgentID, proposal_id: int) -> PolicyProposal | None: ...
```

## ducktape/2025-11-20-01 (23)

### `admin-server-fixture-needed.yaml` / `occ-0`

File: `adgn/tests/agent/test_policy_validation_reload.py`

> Repeated admin_server creation should be a shared fixture.
>
> Every test creates its own `ApprovalPolicyAdminServer(engine=engine)`. This appears at lines 43, 56, 70, 90,
> 107, 122,
> 133, 146.
>
> Should be a fixture that depends on the `engine` fixture.
>
> Benefits:
>
> - DRY principle
> - Consistent setup across tests
> - Easy to modify server configuration

```
      38:
      39: async def test_validate_policy_valid(engine_and_persistence, docker_client: DockerClient):
      40:     """Test validating a valid policy."""
      41:     engine, _ = engine_and_persistence
      42:
>>>   43:     admin_server = ApprovalPolicyAdminServer(engine=engine)
      44:
      45:     # Valid Python code
      46:     result = await admin_server._mcp_server._tools["validate_policy"].fn(ValidatePolicyArgs(source="print('hello')"))
      47:
      48:     assert result.valid is True
   ...
      51:
      52: async def test_validate_policy_syntax_error(engine_and_persistence):
      53:     """Test validating a policy with syntax errors."""
      54:     engine, _ = engine_and_persistence
      55:
>>>   56:     admin_server = ApprovalPolicyAdminServer(engine=engine)
      57:
      58:     # Invalid syntax
      59:     result = await admin_server._mcp_server._tools["validate_policy"].fn(ValidatePolicyArgs(source="print('hello'"))
      60:
      61:     assert result.valid is False
   ...
      65:
      66: async def test_validate_policy_runtime_error(engine_and_persistence, docker_client: DockerClient):
      67:     """Test validating a policy that fails at runtime."""
      68:     engine, _ = engine_and_persistence
      69:
>>>   70:     admin_server = ApprovalPolicyAdminServer(engine=engine)
      71:
      72:     # Syntactically valid but fails self-check (wrong structure)
      73:     result = await admin_server._mcp_server._tools["validate_policy"].fn(
      74:         ValidatePolicyArgs(source="import sys; sys.exit(1)")
      75:     )
   ...
      85:
      86:     # Save a policy to persistence
      87:     new_policy = "print('from persistence')"
      88:     await persistence.set_policy(engine.agent_id, content=new_policy)
      89:
>>>   90:     admin_server = ApprovalPolicyAdminServer(engine=engine)
      91:
      92:     # Change engine's in-memory policy
      93:     engine.set_policy("print('different')")
      94:
      95:     # Reload from persistence
   ...
     102:
     103: async def test_reload_policy_from_source(engine_and_persistence, docker_client: DockerClient):
     104:     """Test reloading policy from provided source."""
     105:     engine, _ = engine_and_persistence
     106:
>>>  107:     admin_server = ApprovalPolicyAdminServer(engine=engine)
     108:
     109:     # Reload with provided source
     110:     new_source = load_default_policy_source()
     111:     await admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source=new_source))
     112:
   ...
     117:
     118: async def test_reload_policy_validates_source(engine_and_persistence, docker_client: DockerClient):
     119:     """Test that reload validates the source before setting."""
     120:     engine, _ = engine_and_persistence
     121:
>>>  122:     admin_server = ApprovalPolicyAdminServer(engine=engine)
     123:
     124:     # Try to reload with invalid source
     125:     with pytest.raises(Exception):  # Should fail validation
     126:         await admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source="import sys; sys.exit(1)"))
     127:
   ...
     128:
     129: async def test_reload_policy_no_persistence_raises(engine_and_persistence):
     130:     """Test that reloading from empty persistence raises error."""
     131:     engine, persistence = engine_and_persistence
     132:
>>>  133:     admin_server = ApprovalPolicyAdminServer(engine=engine)
     134:
     135:     # Create a new agent with no policy in persistence
     136:     new_agent_id = await persistence.create_agent(mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test"))
     137:
     138:     # Create new engine with no persisted policy
   ...
     141:         agent_id=new_agent_id,
     142:         persistence=persistence,
     143:         policy_source=load_default_policy_source(),
     144:     )
     145:
>>>  146:     new_admin_server = ApprovalPolicyAdminServer(engine=new_engine)
     147:
     148:     # Try to reload (should fail - no policy in persistence)
     149:     with pytest.raises(ValueError, match="No policy found in persistence"):
     150:         await new_admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source=None))
     151:
```

### `attach-container-exec-inline.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/runtime/server.py`

> `attach_container_exec` has only one call site (runtime/server.py line 22) and is a
> trivial wrapper that just forwards parameters. This function should be inlined directly
> into its only caller to reduce indirection and simplify the code. The function body is
> a single await statement with parameter forwarding - no logic to justify the abstraction.

```
      17:
      18:
      19: async def attach_runtime(comp: Compositor, opts: ContainerOptions) -> None:
      20:     """Attach the runtime server (enforced adgn mount) in-proc with bearer auth."""
      21:     # Reuse docker_exec attach with Compositor
>>>   22:     await attach_container_exec(comp, opts, server_name=RUNTIME_SERVER_NAME, tool_exec_name=RUNTIME_EXEC_TOOL_NAME)
```

### `complex-nested-loop-assertion.yaml` / `occ-0`

File: `adgn/tests/agent/test_mcp_notifications_flow.py`

> Lines 136-147: Complex 12-line assertion with nested loops, boolean flag,
> and break statements should be replaced with declarative hamcrest matcher.
>
> **What it checks:**
> captured[-1].input contains a UserMessage with content containing InputTextPart
> where text includes "<system notification>".
>
> **Current approach:** Imperative loops with mutable found flag, manual
> isinstance checks, nested breaks.
>
> **Should use:** Hamcrest matchers like has_properties, instance_of, and
> contains_string to express the same check declaratively.
>
> **Benefits:** Declarative vs imperative, no manual loops/flags/breaks, better
> error messages (hamcrest shows diffs), more readable, consistent with other
> tests, eliminates mutable state.

```
     131:             system="n/a",
     132:         )
     133:         await agent.run("go")
     134:
     135:         # The second create call (post-tool) should include the injected system notification
>>>  136:         assert_that(captured, has_length(greater_than_or_equal_to(2)), "expected at least two sampling calls")
>>>  137:         second = captured[-1]
>>>  138:         found = False
>>>  139:         for msg in second.input or []:
>>>  140:             if isinstance(msg, UserMessage):
>>>  141:                 for c in msg.content or []:
>>>  142:                     if isinstance(c, InputTextPart) and "<system notification>" in c.text:
>>>  143:                         found = True
>>>  144:                         break
>>>  145:             if found:
>>>  146:                 break
>>>  147:         assert found, "expected system notification after tool-triggered update"
     148:
     149:
     150: async def test_notifications_broadcast_outside_tool(responses_factory: ResponsesFactory, make_buffered_client):
     151:     # Server that can broadcast notifications outside a tool
     152:     server = NotifyingFastMCP(name="notifier", instructions="Notifier test")
```

### `dead-code.yaml` / `occ-0`

File: `adgn/src/adgn/openai_utils/model.py`

> Functions with zero call sites in the codebase should be deleted as dead code.
> Reduces maintenance burden, eliminates confusion about unused code paths, and
> improves readability. Can always restore from git history if needed.
>
> **Note:** AssistantMessageOut.from_input_item - reverse conversion never used

```
     214:             part_data = part.model_dump(exclude_none=True)
     215:             part_data.setdefault("type", "input_text")
     216:             content_parts.append(InputTextPart.model_validate(part_data))
     217:         return AssistantMessage(role="assistant", content=content_parts)
     218:
>>>  219:     @classmethod
>>>  220:     def from_input_item(cls, item: AssistantMessage) -> AssistantMessageOut:
>>>  221:         parts: list[OutputText] = []
>>>  222:         for block in item.content or []:
>>>  223:             if isinstance(block, InputTextPart):
>>>  224:                 parts.append(OutputText.model_validate(block.model_dump(exclude_none=True)))
>>>  225:         return cls(parts=parts)
     226:
     227:
     228: ResponseOutItem = ReasoningItem | FunctionCallItem | FunctionCallOutputItem | AssistantMessageOut
     229:
     230:
```

### `dead-code.yaml` / `occ-1`

File: `adgn/src/adgn/openai_utils/model.py`

> Functions with zero call sites in the codebase should be deleted as dead code.
> Reduces maintenance burden, eliminates confusion about unused code paths, and
> improves readability. Can always restore from git history if needed.
>
> **Note:** ResponsesResult.to_input_items and its dependency response_out_item_to_input singledispatch - unused

```
     275: class ResponsesResult(BaseModel):
     276:     id: str
     277:     usage: ResponseUsage | None
     278:     output: list[ResponseOutItem]
     279:
>>>  280:     def to_input_items(self) -> list[InputItem]:
>>>  281:         return [response_out_item_to_input(item) for item in self.output]
     282:
     283:
     284: def convert_sdk_response(sdk_resp: Response) -> ResponsesResult:
     285:     """Convert an OpenAI SDK Response to our typed ResponsesResult.
     286:
   ...
     226:
     227:
     228: ResponseOutItem = ReasoningItem | FunctionCallItem | FunctionCallOutputItem | AssistantMessageOut
     229:
     230:
>>>  231: @singledispatch
>>>  232: def response_out_item_to_input(item: BaseModel) -> InputItem:
>>>  233:     raise TypeError(f"Unsupported response item type: {type(item)!r}")
>>>  234:
>>>  235:
>>>  236: @response_out_item_to_input.register
>>>  237: def _(item: ReasoningItem) -> InputItem:
>>>  238:     return item  # No conversion needed, ReasoningItem is already an InputItem
>>>  239:
>>>  240:
>>>  241: @response_out_item_to_input.register
>>>  242: def _(item: FunctionCallItem) -> InputItem:
>>>  243:     return item  # No conversion needed, FunctionCallItem is already an InputItem
>>>  244:
>>>  245:
>>>  246: @response_out_item_to_input.register
>>>  247: def _(item: FunctionCallOutputItem) -> InputItem:
>>>  248:     return item  # No conversion needed, FunctionCallOutputItem is already an InputItem
>>>  249:
>>>  250:
>>>  251: @response_out_item_to_input.register
>>>  252: def _(item: AssistantMessageOut) -> InputItem:
>>>  253:     return item.to_input_item()
     254:
     255:
     256: def _message_output_to_assistant(message: ResponseOutputMessage) -> AssistantMessageOut | None:
     257:     parts: list[OutputText] = []
     258:     for content_item in message.content:
```

### `dead-code.yaml` / `occ-2`

File: `adgn/src/adgn/mcp/policy_gateway/signals.py`

> Functions with zero call sites in the codebase should be deleted as dead code.
> Reduces maintenance burden, eliminates confusion about unused code paths, and
> improves readability. Can always restore from git history if needed.
>
> **Note:** detect_policy_gateway_error - 50 lines of complex error detection logic, documented as unused at line 110

```
      91:             logger.debug("Failed to extract ErrorData from object attributes: %s", e)
      92:             return None
      93:     return None
      94:
      95:
>>>   96: def detect_policy_gateway_error(
>>>   97:     err: FastMcpCallToolResult | mtypes.CallToolResult | McpError | dict[str, Any] | mtypes.ErrorData | BaseException,
>>>   98: ) -> PolicyGatewayError | None:
>>>   99:     """Detect and classify policy-gateway errors robustly.
>>>  100:
>>>  101:     Accepts either:
>>>  102:     - FastMCP CallToolResult with is_error=True
>>>  103:     - MCP types.CallToolResult with is_error=True
>>>  104:     - McpError exception (has .error attribute)
>>>  105:     - Raw error payload (dict or ErrorData)
>>>  106:     - Other exceptions (will return None unless they have .error attribute)
>>>  107:
>>>  108:     Returns a typed PolicyGatewayError when recognized; otherwise None.
>>>  109:
>>>  110:     NOTE: This function is currently unused in the codebase.
>>>  111:     """
>>>  112:     # Prefer structured error data when present (CallToolResult or exception with .error)
>>>  113:     error_data: mtypes.ErrorData | None = None
>>>  114:     # Check for CallToolResult with is_error=True
>>>  115:     if (isinstance(err, FastMcpCallToolResult | mtypes.CallToolResult) and err.is_error) or isinstance(err, McpError):
>>>  116:         error_data = _coerce_error_data(err.error)
>>>  117:     # Check for direct error data
>>>  118:     elif isinstance(err, dict | mtypes.ErrorData):
>>>  119:         error_data = _coerce_error_data(err)
>>>  120:     # Fallback: other exceptions with .error attribute
>>>  121:     elif hasattr(err, "error"):
>>>  122:         error_data = _coerce_error_data(err.error)
>>>  123:
>>>  124:     # Map structured error first
>>>  125:     if error_data is not None:
>>>  126:         # Extract minimally-typed fields
>>>  127:         code: int | None
>>>  128:         try:
>>>  129:             code = int(error_data.code)
>>>  130:         except Exception:
>>>  131:             code = None
>>>  132:         msg = str(error_data.message)
>>>  133:         data = error_data.data
>>>  134:
>>>  135:         # Only accept stamped errors as originating from the policy gateway.
>>>  136:         if not (isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True):
>>>  137:             return None
>>>  138:         kind = _CODE_TO_KIND.get(code) if code is not None else _MSG_TO_KIND.get(msg)
>>>  139:         if kind is None:
>>>  140:             # Unknown code/message but stamped as gateway: treat as evaluator error fallback
>>>  141:             kind = PolicyGatewayErrorKind.POLICY_EVALUATOR_ERROR
>>>  142:         return PolicyGatewayError(kind=kind, code=code, message=msg, data=data)
>>>  143:
>>>  144:     # Fallback: detect by message string on generic exceptions (e.g., ToolError)
>>>  145:     return None
```

### `delete-coerce-error-data.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/policy_gateway/signals.py`

> Lines 62-93 define \_coerce_error_data that tries to coerce various error representations
> to mtypes.ErrorData with extensive defensive fallbacks. Lines 56-60 define a Protocol
> for attribute-based fallback. This overly defensive function should be deleted entirely.
>
> Problems: swallows validation errors and tries manual construction (lines 75-85), has
> attribute-based fallback for objects with .code/.message (lines 87-92), mixes validation
> with data extraction, violates fail-fast principle, makes debugging harder.
>
> Delete \_coerce_error_data and \_ErrorFields Protocol. Replace three usage sites (lines
> 116, 119, 122) with direct mtypes.ErrorData.model_validate() calls. If data doesn't
> match schema, Pydantic raises clear validation errors instead of silently constructing
> minimal ErrorData or returning None.

```
      51:
      52: _CODE_TO_KIND: dict[int, PolicyGatewayErrorKind] = {code: kind for code, _msg, kind in _KINDS}
      53: _MSG_TO_KIND: dict[str, PolicyGatewayErrorKind] = {msg: kind for _code, msg, kind in _KINDS}
      54:
      55:
>>>   56: @runtime_checkable
>>>   57: class _ErrorFields(Protocol):
>>>   58:     code: Any
>>>   59:     message: Any
>>>   60:
      61:
      62: def _coerce_error_data(obj: Any) -> mtypes.ErrorData | None:
      63:     """Attempt to coerce various error representations to mcp.types.ErrorData.
      64:
      65:     - Accepts dicts, already-typed ErrorData, or objects with .code/.message attributes.
   ...
      57: class _ErrorFields(Protocol):
      58:     code: Any
      59:     message: Any
      60:
      61:
>>>   62: def _coerce_error_data(obj: Any) -> mtypes.ErrorData | None:
>>>   63:     """Attempt to coerce various error representations to mcp.types.ErrorData.
>>>   64:
>>>   65:     - Accepts dicts, already-typed ErrorData, or objects with .code/.message attributes.
>>>   66:     - Returns None if no minimally-typed shape is available.
>>>   67:     """
>>>   68:     if isinstance(obj, mtypes.ErrorData):
>>>   69:         return obj
>>>   70:     if isinstance(obj, dict):
>>>   71:         try:
>>>   72:             return mtypes.ErrorData.model_validate(obj)
>>>   73:         except Exception as e:
>>>   74:             logger.debug("Failed to validate dict as ErrorData: %s", e)
>>>   75:             try:
>>>   76:                 # Minimal acceptance: just code+message fields
>>>   77:                 code_val = obj.get("code")
>>>   78:                 msg_val = obj.get("message")
>>>   79:                 if code_val is None or msg_val is None:
>>>   80:                     logger.debug("Dict missing code or message fields")
>>>   81:                     return None
>>>   82:                 return mtypes.ErrorData(code=int(code_val), message=str(msg_val))
>>>   83:             except Exception as e2:
>>>   84:                 logger.debug("Failed to construct minimal ErrorData from dict: %s", e2)
>>>   85:                 return None
>>>   86:     # Attribute-style fallback
>>>   87:     if isinstance(obj, _ErrorFields):
>>>   88:         try:
>>>   89:             return mtypes.ErrorData(code=int(obj.code), message=str(obj.message))
>>>   90:         except Exception as e:
>>>   91:             logger.debug("Failed to extract ErrorData from object attributes: %s", e)
>>>   92:             return None
>>>   93:     return None
      94:
      95:
      96: def detect_policy_gateway_error(
      97:     err: FastMcpCallToolResult | mtypes.CallToolResult | McpError | dict[str, Any] | mtypes.ErrorData | BaseException,
      98: ) -> PolicyGatewayError | None:
   ...
     111:     """
     112:     # Prefer structured error data when present (CallToolResult or exception with .error)
     113:     error_data: mtypes.ErrorData | None = None
     114:     # Check for CallToolResult with is_error=True
     115:     if (isinstance(err, FastMcpCallToolResult | mtypes.CallToolResult) and err.is_error) or isinstance(err, McpError):
>>>  116:         error_data = _coerce_error_data(err.error)
     117:     # Check for direct error data
     118:     elif isinstance(err, dict | mtypes.ErrorData):
     119:         error_data = _coerce_error_data(err)
     120:     # Fallback: other exceptions with .error attribute
     121:     elif hasattr(err, "error"):
   ...
     114:     # Check for CallToolResult with is_error=True
     115:     if (isinstance(err, FastMcpCallToolResult | mtypes.CallToolResult) and err.is_error) or isinstance(err, McpError):
     116:         error_data = _coerce_error_data(err.error)
     117:     # Check for direct error data
     118:     elif isinstance(err, dict | mtypes.ErrorData):
>>>  119:         error_data = _coerce_error_data(err)
     120:     # Fallback: other exceptions with .error attribute
     121:     elif hasattr(err, "error"):
     122:         error_data = _coerce_error_data(err.error)
     123:
     124:     # Map structured error first
   ...
     117:     # Check for direct error data
     118:     elif isinstance(err, dict | mtypes.ErrorData):
     119:         error_data = _coerce_error_data(err)
     120:     # Fallback: other exceptions with .error attribute
     121:     elif hasattr(err, "error"):
>>>  122:         error_data = _coerce_error_data(err.error)
     123:
     124:     # Map structured error first
     125:     if error_data is not None:
     126:         # Extract minimally-typed fields
     127:         code: int | None
```

### `fragmented-assertions.yaml` / `occ-0`

File: `adgn/tests/agent/test_runtime_timeout.py`

> Tests use multiple separate assertions instead of structured matchers (hamcrest or Pydantic model equality).
>
> Benefits of structured matchers:
>
> - Single assertion with clear expected structure
> - Better error messages showing which specific property failed or full diff
> - Less verbose code
> - More explicit about intent
>
> **Note:** Multiple separate assertions for object properties (instance type, exit_code, stdout); should use
> has_properties

```
      33:         res_timeout = await stub(ExecInput(cmd=["sh", "-lc", "sleep 3"], timeout_ms=500, shell=True))
      34:         assert_that(res_timeout.exit, instance_of(TimedOut))
      35:
      36:         # Next call should work; container should have been restarted
      37:         res_ok = await stub(ExecInput(cmd=["/bin/echo", "-n", "ok"], timeout_ms=5000, shell=False))
>>>   38:         assert_that(res_ok.exit, instance_of(Exited))
>>>   39:         assert res_ok.exit.exit_code == 0
>>>   40:         assert (res_ok.stdout or "") == "ok"
```

### `fragmented-assertions.yaml` / `occ-1`

File: `adgn/tests/agent/test_policy_validation_reload.py`

> Tests use multiple separate assertions instead of structured matchers (hamcrest or Pydantic model equality).
>
> Benefits of structured matchers:
>
> - Single assertion with clear expected structure
> - Better error messages showing which specific property failed or full diff
> - Less verbose code
> - More explicit about intent
>
> **Note:** Multiple assertions to check error messages (length > 0, then substring); should use
> has_item(contains_string(...))

```
      57:
      58:     # Invalid syntax
      59:     result = await admin_server._mcp_server._tools["validate_policy"].fn(ValidatePolicyArgs(source="print('hello'"))
      60:
      61:     assert result.valid is False
>>>   62:     assert_that(result.errors, has_length(greater_than(0)))
>>>   63:     assert "Syntax error" in result.errors[0]
      64:
      65:
      66: async def test_validate_policy_runtime_error(engine_and_persistence, docker_client: DockerClient):
      67:     """Test validating a policy that fails at runtime."""
      68:     engine, _ = engine_and_persistence
   ...
      72:     # Syntactically valid but fails self-check (wrong structure)
      73:     result = await admin_server._mcp_server._tools["validate_policy"].fn(
      74:         ValidatePolicyArgs(source="import sys; sys.exit(1)")
      75:     )
      76:
>>>   77:     assert result.valid is False
>>>   78:     assert_that(result.errors, has_length(greater_than(0)))
>>>   79:     assert "Runtime validation failed" in result.errors[0]
      80:
      81:
      82: async def test_reload_policy_from_persistence(engine_and_persistence, docker_client: DockerClient):
      83:     """Test reloading policy from persistence."""
      84:     engine, persistence = engine_and_persistence
```

### `fragmented-assertions.yaml` / `occ-2`

File: `adgn/tests/mcp/approval_policy/test_policy_resources.py`

> Tests use multiple separate assertions instead of structured matchers (hamcrest or Pydantic model equality).
>
> Benefits of structured matchers:
>
> - Single assertion with clear expected structure
> - Better error messages showing which specific property failed or full diff
> - Less verbose code
> - More explicit about intent
>
> **Note:** Individual field assertions instead of structured comparison; should use Pydantic model equality or
> has_properties

```
     166:         )
     167:
     168:         assert result.isError is False
     169:
     170:         # Verify it was created in persistence
>>>  171:         policy = await persistence.get_policy("new-policy")
>>>  172:         assert policy is not None
>>>  173:         assert policy.id == "new-policy"
>>>  174:         assert policy.text == "print('new policy')"
>>>  175:         assert policy.description == "A new policy"
>>>  176:         assert policy.enabled is True
     177:
     178:     async def test_create_duplicate(self, admin_server, persistence):
     179:         """Test creating a policy with duplicate ID fails."""
     180:         # Create first policy
     181:         await admin_server._mcp_server.call_tool(
   ...
     208:             ).model_dump(),
     209:         )
     210:
     211:         assert result.isError is False
     212:
>>>  213:         policy = await persistence.get_policy("minimal")
>>>  214:         assert policy is not None
>>>  215:         assert policy.id == "minimal"
>>>  216:         assert policy.text == "pass"
>>>  217:         assert policy.description is None
>>>  218:         assert policy.enabled is True  # default
     219:
     220:
     221: class TestUpdatePolicyTool:
     222:     """Test the update_policy admin tool."""
     223:
   ...
     244:         )
     245:
     246:         assert result.isError is False
     247:
     248:         # Verify the update
>>>  249:         policy = await persistence.get_policy("update-me")
>>>  250:         assert policy is not None
>>>  251:         assert policy.text == "print('v2')"
>>>  252:         assert policy.description == "Version 2"
     253:
     254:     async def test_update_nonexistent(self, admin_server):
     255:         """Test updating a nonexistent policy fails."""
     256:         result = await admin_server._mcp_server.call_tool(
     257:             "update_policy",
   ...
     284:             ).model_dump(),
     285:         )
     286:
     287:         # Check that history was created (requires accessing policy_history table)
     288:         # For now, just verify the update worked
>>>  289:         policy = await persistence.get_policy("versioned")
>>>  290:         assert policy.text == "print('v2')"
     291:
     292:
     293: class TestDeletePolicyTool:
     294:     """Test the delete_policy admin tool."""
     295:
   ...
     303:                 text="print('bye')",
     304:             ).model_dump(),
     305:         )
     306:
     307:         # Verify it exists
>>>  308:         policy = await persistence.get_policy("delete-me")
>>>  309:         assert policy is not None
     310:
     311:         # Delete it
     312:         result = await admin_server._mcp_server.call_tool(
     313:             "delete_policy",
     314:             arguments=DeletePolicyArgs(id="delete-me").model_dump(),
   ...
     315:         )
     316:
     317:         assert result.isError is False
     318:
     319:         # Verify it's gone
>>>  320:         policy = await persistence.get_policy("delete-me")
>>>  321:         assert policy is None
     322:
     323:     async def test_delete_nonexistent(self, admin_server):
     324:         """Test deleting a nonexistent policy succeeds (idempotent)."""
     325:         result = await admin_server._mcp_server.call_tool(
     326:             "delete_policy",
```

### `from-server-too-long.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/stubs/typed_stubs.py`

> The from_server classmethod spans 69 lines (109-178), with a single for-loop body
> consuming 49 lines (128-177). This makes the method difficult to understand and maintain.
>
> Problems: single method doing too many things (registry access, tool introspection,
> type resolution, model extraction), 49-line loop body extremely hard to read, multiple
> nested try/except blocks and conditionals within loop, mixing different concerns,
> hard to test individual introspection logic pieces.
>
> Extract loop body into a static helper method \_extract_tool_models(tool) that returns
> tuple[str, ToolModels] | None. Simplify main loop to call helper, check result, and
> store. Benefits: single responsibility per method, easier to understand flow, helper
> testable independently, reduced cognitive load.

```
     104:     @property
     105:     def models(self) -> dict[str, ToolModels]:
     106:         return self._models
     107:
     108:     @classmethod
>>>  109:     def from_server(cls, server: FastMCP, session: Client, *, exclude_none: bool = True) -> TypedClient:
>>>  110:         """Create a TypedClient introspecting FastMCP's tool registry.
>>>  111:
>>>  112:         Requires a server created via FastMCP. Uses server._tool_manager.list_tools()
>>>  113:         and reads each tool.fn_metadata.arg_model/output_model.
>>>  114:         """
>>>  115:         # Access the internal tool manager and fetch local tools synchronously
>>>  116:         try:
>>>  117:             tm = server._tool_manager  # type: ignore[attr-defined]
>>>  118:         except AttributeError as exc:
>>>  119:             raise RuntimeError("Server does not expose _tool_manager") from exc
>>>  120:         # Prefer local tools; mounted tools aren't needed for typed tests here
>>>  121:         try:
>>>  122:             tools_by_name = tm._tools  # type: ignore[attr-defined]
>>>  123:         except AttributeError as exc:
>>>  124:             raise RuntimeError("Server tool manager does not expose _tools") from exc
>>>  125:         tools = list(tools_by_name.values())
>>>  126:
>>>  127:         client = cls(session, exclude_none=exclude_none)
>>>  128:         for t in tools:
>>>  129:             try:
>>>  130:                 fm = t.fn_metadata  # type: ignore[attr-defined]
>>>  131:             except AttributeError:
>>>  132:                 fm = None
>>>  133:             try:
>>>  134:                 fn = t.fn  # type: ignore[attr-defined]
>>>  135:             except AttributeError:
>>>  136:                 fn = None
>>>  137:             hinted_input = None
>>>  138:             hinted_output = None
>>>  139:             if fn is not None:
>>>  140:                 try:
>>>  141:                     hinted_input = fn._mcp_flat_input_model  # type: ignore[attr-defined]
>>>  142:                 except AttributeError:
>>>  143:                     hinted_input = None
>>>  144:                 try:
>>>  145:                     hinted_output = fn._mcp_flat_output_model  # type: ignore[attr-defined]
>>>  146:                 except AttributeError:
>>>  147:                     hinted_output = None
>>>  148:             if fm is None:
>>>  149:                 # Fall back to flat-model hints only
>>>  150:                 arg_model = hinted_input
>>>  151:                 out_model = hinted_output
>>>  152:                 if not (isinstance(arg_model, type) and issubclass(arg_model, BaseModel)):
>>>  153:                     continue
>>>  154:             else:
>>>  155:                 arg_model = fm.arg_model  # type: ignore[attr-defined]
>>>  156:                 out_model = fm.output_model  # type: ignore[attr-defined]
>>>  157:                 if out_model is None or arg_model is None:
>>>  158:                     continue
>>>  159:
>>>  160:             if isinstance(hinted_input, type) and issubclass(hinted_input, BaseModel):
>>>  161:                 input_type: type[BaseModel] | None = hinted_input
>>>  162:             elif isinstance(arg_model, type) and issubclass(arg_model, BaseModel):
>>>  163:                 input_type = arg_model
>>>  164:             else:
>>>  165:                 input_type = None
>>>  166:
>>>  167:             try:
>>>  168:                 tool_key = t.key  # type: ignore[attr-defined]
>>>  169:             except AttributeError:
>>>  170:                 try:
>>>  171:                     tool_key = t.name  # type: ignore[attr-defined]
>>>  172:                 except AttributeError:
>>>  173:                     tool_key = None
>>>  174:             if not isinstance(tool_key, str) or not tool_key:
>>>  175:                 continue
>>>  176:             output_type = _resolve_output_type(hinted_output, out_model)
>>>  177:             client._models[tool_key] = ToolModels(Input=input_type, Output=output_type, _arg_model=arg_model)
>>>  178:         return client
     179:
     180:     def error(self, name: str) -> Callable[[BaseModel], Awaitable[str]]:
     181:         models = self._models.get(name)
     182:         if not models:
     183:             raise AttributeError(name)
   ...
     123:         except AttributeError as exc:
     124:             raise RuntimeError("Server tool manager does not expose _tools") from exc
     125:         tools = list(tools_by_name.values())
     126:
     127:         client = cls(session, exclude_none=exclude_none)
>>>  128:         for t in tools:
>>>  129:             try:
>>>  130:                 fm = t.fn_metadata  # type: ignore[attr-defined]
>>>  131:             except AttributeError:
>>>  132:                 fm = None
>>>  133:             try:
>>>  134:                 fn = t.fn  # type: ignore[attr-defined]
>>>  135:             except AttributeError:
>>>  136:                 fn = None
>>>  137:             hinted_input = None
>>>  138:             hinted_output = None
>>>  139:             if fn is not None:
>>>  140:                 try:
>>>  141:                     hinted_input = fn._mcp_flat_input_model  # type: ignore[attr-defined]
>>>  142:                 except AttributeError:
>>>  143:                     hinted_input = None
>>>  144:                 try:
>>>  145:                     hinted_output = fn._mcp_flat_output_model  # type: ignore[attr-defined]
>>>  146:                 except AttributeError:
>>>  147:                     hinted_output = None
>>>  148:             if fm is None:
>>>  149:                 # Fall back to flat-model hints only
>>>  150:                 arg_model = hinted_input
>>>  151:                 out_model = hinted_output
>>>  152:                 if not (isinstance(arg_model, type) and issubclass(arg_model, BaseModel)):
>>>  153:                     continue
>>>  154:             else:
>>>  155:                 arg_model = fm.arg_model  # type: ignore[attr-defined]
>>>  156:                 out_model = fm.output_model  # type: ignore[attr-defined]
>>>  157:                 if out_model is None or arg_model is None:
>>>  158:                     continue
>>>  159:
>>>  160:             if isinstance(hinted_input, type) and issubclass(hinted_input, BaseModel):
>>>  161:                 input_type: type[BaseModel] | None = hinted_input
>>>  162:             elif isinstance(arg_model, type) and issubclass(arg_model, BaseModel):
>>>  163:                 input_type = arg_model
>>>  164:             else:
>>>  165:                 input_type = None
>>>  166:
>>>  167:             try:
>>>  168:                 tool_key = t.key  # type: ignore[attr-defined]
>>>  169:             except AttributeError:
>>>  170:                 try:
>>>  171:                     tool_key = t.name  # type: ignore[attr-defined]
>>>  172:                 except AttributeError:
>>>  173:                     tool_key = None
>>>  174:             if not isinstance(tool_key, str) or not tool_key:
>>>  175:                 continue
>>>  176:             output_type = _resolve_output_type(hinted_output, out_model)
>>>  177:             client._models[tool_key] = ToolModels(Input=input_type, Output=output_type, _arg_model=arg_model)
     178:         return client
     179:
     180:     def error(self, name: str) -> Callable[[BaseModel], Awaitable[str]]:
     181:         models = self._models.get(name)
     182:         if not models:
```

### `low-value-enum-assertions.yaml` / `occ-0`

File: `adgn/tests/agent/server/test_mcp_routing.py`

> The test contains low-value enum assertions that just duplicate production code definitions.
>
> **Current code (lines 149-150):**
>
> ```python
> @pytest.mark.asyncio
> async def test_token_role_enum(self):
>     """Test TokenRole enum values."""
>     assert TokenRole.HUMAN == "human"
>     assert TokenRole.AGENT == "agent"
>
>     # Test that enum can be created from string
>     role = TokenRole("human")
>     assert role == TokenRole.HUMAN
> ```
>
> **Why these assertions are low-value:**
>
> - Lines 149-150 just assert the enum values equal their string representations
> - This duplicates what's already in the production code definition
> - If someone changes the enum value, they'll see it immediately without needing a test
> - The assertions don't test any meaningful behavior
>
> **What should stay:**
> Lines 152-154 (testing enum construction from string) have value because they test
> actual behavior rather than just duplicating definitions. Keep these.
>
> **Recommended fix:**
> Delete assertions at lines 149-150. Keep the string-to-enum construction test (lines 152-154)
> as it verifies actual parsing behavior.

```
     144:             assert mock_agents_server.http_app.call_count == 1
     145:
     146:     @pytest.mark.asyncio
     147:     async def test_token_role_enum(self):
     148:         """Test TokenRole enum values."""
>>>  149:         assert TokenRole.HUMAN == "human"
>>>  150:         assert TokenRole.AGENT == "agent"
     151:
     152:         # Test that enum can be created from string
     153:         role = TokenRole("human")
     154:         assert role == TokenRole.HUMAN
     155:
```

### `message-wrapper-discriminator.yaml` / `occ-0`

File: `adgn/src/adgn/openai_utils/model.py`

> model.py input message types (AssistantMessage, UserMessage, SystemMessage lines
> 26-53) embed the discriminator field (role) directly in the message class,
> mixing API-level concerns with content structure.
>
> Current inconsistency: input messages use "role" as discriminator, other input
> items use "type" (ReasoningItem, FunctionCallItem), output messages use "kind"
> (AssistantMessageOut line 172-182). This creates three different discriminator
> naming conventions.
>
> Separate message from discriminator using wrapper pattern: message class contains
> content only, wrapper class contains discriminator "kind" plus message. This
> matches the output pattern (AssistantMessageOut) and enables clearer type
> discrimination for union types (InputItem line 93).
>
> Benefits: Consistent discriminator naming, separates transport/API concerns from
> content structure, message content can evolve independently from serialization
> format.

```
      21:     type: Literal["input_text"] = "input_text"
      22:     text: str
      23:     model_config = ConfigDict(extra="allow")
      24:
      25:
>>>   26: class AssistantMessage(BaseModel):
>>>   27:     role: Literal["assistant"] = "assistant"
>>>   28:     content: list[InputTextPart] | None = None
>>>   29:     model_config = ConfigDict(extra="allow")
>>>   30:
>>>   31:     @classmethod
>>>   32:     def text(cls, text: str) -> Self:
>>>   33:         return cls(content=[InputTextPart(text=text)])
      34:
      35:
      36: class UserMessage(BaseModel):
      37:     role: Literal["user"] = "user"
      38:     content: list[InputTextPart]
   ...
      31:     @classmethod
      32:     def text(cls, text: str) -> Self:
      33:         return cls(content=[InputTextPart(text=text)])
      34:
      35:
>>>   36: class UserMessage(BaseModel):
>>>   37:     role: Literal["user"] = "user"
>>>   38:     content: list[InputTextPart]
>>>   39:     model_config = ConfigDict(extra="allow")
>>>   40:
>>>   41:     @classmethod
>>>   42:     def text(cls, text: str) -> Self:
>>>   43:         return cls(content=[InputTextPart(text=text)])
      44:
      45:
      46: class SystemMessage(BaseModel):
      47:     role: Literal["system"] = "system"
      48:     content: list[InputTextPart]
   ...
      41:     @classmethod
      42:     def text(cls, text: str) -> Self:
      43:         return cls(content=[InputTextPart(text=text)])
      44:
      45:
>>>   46: class SystemMessage(BaseModel):
>>>   47:     role: Literal["system"] = "system"
>>>   48:     content: list[InputTextPart]
>>>   49:     model_config = ConfigDict(extra="allow")
>>>   50:
>>>   51:     @classmethod
>>>   52:     def text(cls, text: str) -> Self:
>>>   53:         return cls(content=[InputTextPart(text=text)])
      54:
      55:
      56: class ReasoningSummaryItem(BaseModel):
      57:     """Summary item within a reasoning block."""
      58:
   ...
      88:     call_id: str
      89:     output: str | None = Field(default=None, description="Tool output as string (JSON if structured)")
      90:     model_config = ConfigDict(extra="allow")
      91:
      92:
>>>   93: InputItem = AssistantMessage | UserMessage | SystemMessage | ReasoningItem | FunctionCallItem | FunctionCallOutputItem
      94:
      95:
      96: class ToolChoiceFunction(BaseModel):
      97:     type: Literal["function"] = "function"
      98:     name: str
   ...
     167:     text: str
     168:     annotations: list[dict[str, Any]] | None = None
     169:     model_config = ConfigDict(extra="allow")
     170:
     171:
>>>  172: class AssistantMessageOut(BaseModel):
>>>  173:     """Adapter-level assistant message output (text parts only for now).
>>>  174:
>>>  175:     Matches the SDK's message content shape we actually use: a list of text parts
>>>  176:     with optional annotations. This keeps a stable, Pydantic-validated shape
>>>  177:     for downstream use and can be extended if we support non-text parts later.
>>>  178:     """
>>>  179:
>>>  180:     kind: Literal["assistant_message"] = "assistant_message"
>>>  181:     parts: list[OutputText]
>>>  182:     model_config = ConfigDict(extra="allow")
     183:
     184:     @model_validator(mode="before")
     185:     @classmethod
     186:     def _coerce_text(cls, data: str | dict[str, Any]) -> dict[str, Any]:
     187:         """Coerce various input forms to the standard parts-based format.
```

### `policy-error-data-vague-type.yaml` / `occ-0`

File: `adgn/src/adgn/mcp/policy_gateway/signals.py`

> The `PolicyGatewayError` model (lines 33-37) has a `data: dict[str, Any] | None`
> field that's too vague.
>
> Field name "data" is generic; type `dict[str, Any]` provides no guidance on
> structure/contents; no documentation. Usage (line 136) checks for
> POLICY_GATEWAY_STAMP_KEY, but this isn't reflected in type or name. Unclear what
> other fields exist besides stamp key.
>
> **Fix options:**
>
> 1. Create typed model `PolicyGatewayErrorData` with `_policy_gateway_stamp: bool`
>    field (plus other discovered fields), use as type
> 2. Add Field description documenting exact contents (must contain stamp key, list
>    other specific fields)
> 3. Rename to more specific name (e.g., `mcp_error_metadata`)
>
> Don't add generic documentation like "data associated with the error". Real
> documentation requires understanding what actually gets stored and documenting
> specifics.

```
      28:     POLICY_DENIED = POLICY_DENIED_ABORT_MSG
      29:     POLICY_DENIED_CONTINUE = POLICY_DENIED_CONTINUE_MSG
      30:     POLICY_BACKEND_RESERVED_MISUSE = POLICY_BACKEND_RESERVED_MISUSE_MSG
      31:
      32:
>>>   33: class PolicyGatewayError(BaseModel):
>>>   34:     kind: PolicyGatewayErrorKind
>>>   35:     code: int | None = None
>>>   36:     message: str
>>>   37:     data: dict[str, Any] | None = None
      38:
      39:
      40: # Central registry for reserved gateway errors → kinds
      41: _KINDS: tuple[tuple[int, str, PolicyGatewayErrorKind], ...] = (
      42:     (POLICY_EVALUATOR_ERROR_CODE, POLICY_EVALUATOR_ERROR_MSG, PolicyGatewayErrorKind.POLICY_EVALUATOR_ERROR),
   ...
     128:         try:
     129:             code = int(error_data.code)
     130:         except Exception:
     131:             code = None
     132:         msg = str(error_data.message)
>>>  133:         data = error_data.data
     134:
     135:         # Only accept stamped errors as originating from the policy gateway.
     136:         if not (isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True):
     137:             return None
     138:         kind = _CODE_TO_KIND.get(code) if code is not None else _MSG_TO_KIND.get(msg)
   ...
     131:             code = None
     132:         msg = str(error_data.message)
     133:         data = error_data.data
     134:
     135:         # Only accept stamped errors as originating from the policy gateway.
>>>  136:         if not (isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True):
     137:             return None
     138:         kind = _CODE_TO_KIND.get(code) if code is not None else _MSG_TO_KIND.get(msg)
     139:         if kind is None:
     140:             # Unknown code/message but stamped as gateway: treat as evaluator error fallback
     141:             kind = PolicyGatewayErrorKind.POLICY_EVALUATOR_ERROR
   ...
     137:             return None
     138:         kind = _CODE_TO_KIND.get(code) if code is not None else _MSG_TO_KIND.get(msg)
     139:         if kind is None:
     140:             # Unknown code/message but stamped as gateway: treat as evaluator error fallback
     141:             kind = PolicyGatewayErrorKind.POLICY_EVALUATOR_ERROR
>>>  142:         return PolicyGatewayError(kind=kind, code=code, message=msg, data=data)
     143:
     144:     # Fallback: detect by message string on generic exceptions (e.g., ToolError)
     145:     return None
```

### `proposal-id-int-not-str.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> Lines 211-220 define notify_proposal_change with str signature, but all three callers
> (lines 236, 253, 258) have int proposal_id and must explicitly convert with str().
> This indicates wrong method signature.
>
> Problem: all callers (create_proposal line 239, approve_proposal line 239, reject_proposal
> line 255) have proposal_id as int in their signatures, persistence layer likely uses
> int, URI formatting at line 217 works fine with int (f-string converts automatically),
> unnecessary conversions add cognitive load.
>
> Change notify_proposal_change signature to accept int instead of str. Callers can then
> pass int directly without conversion. Benefits: eliminates unnecessary conversions,
> makes type consistency clear, aligns with persistence layer.
>
> Related to issue 022 about using wrong ID in create_proposal.

```
     206:     def notify_proposals_changed(self) -> None:
     207:         cb = self._notify
     208:         if cb:
     209:             cb(APPROVAL_POLICY_PROPOSALS_INDEX_URI)
     210:
>>>  211:     def notify_proposal_change(self, proposal_id: str) -> None:
>>>  212:         """Notify about a specific proposal change and the proposals index.
>>>  213:
>>>  214:         Convenience method that combines notifying about a specific proposal item
>>>  215:         and the proposals index list change.
>>>  216:         """
>>>  217:         self.notify_resource(f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{proposal_id}")
>>>  218:         self.notify_proposals_changed()
>>>  219:         # Also notify agent-specific policy state resource since proposals changed
>>>  220:         self.notify_resource(AGENTS_POLICY_STATE_URI_FMT.format(agent_id=self.agent_id))
     221:
     222:     async def create_proposal(self, content: str) -> int:
     223:         """Create a new policy proposal and return its ID.
     224:
     225:         Validates the proposal content if docker_client is available,
   ...
     212:         """Notify about a specific proposal change and the proposals index.
     213:
     214:         Convenience method that combines notifying about a specific proposal item
     215:         and the proposals index list change.
     216:         """
>>>  217:         self.notify_resource(f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{proposal_id}")
     218:         self.notify_proposals_changed()
     219:         # Also notify agent-specific policy state resource since proposals changed
     220:         self.notify_resource(AGENTS_POLICY_STATE_URI_FMT.format(agent_id=self.agent_id))
     221:
     222:     async def create_proposal(self, content: str) -> int:
   ...
     231:         # Generate new proposal ID (will be auto-generated by DB, use placeholder)
     232:         new_id = 0  # Placeholder, actual ID assigned by database
     233:         await self.persistence.create_policy_proposal(self.agent_id, proposal_id=new_id, content=content)
     234:         # Note: We don't have the actual ID here, but persistence will handle it
     235:         # For now, notify with string version for compatibility
>>>  236:         self.notify_proposal_change(str(new_id))
     237:         return new_id
     238:
     239:     async def approve_proposal(self, proposal_id: int) -> None:
     240:         """Approve a pending policy proposal by ID and activate it.
     241:
   ...
     248:         if self.docker_client is not None:
     249:             self.self_check(got.content)
     250:         # Activate policy (notifies via engine's set_policy)
     251:         self.set_policy(got.content)
     252:         await self.persistence.approve_policy_proposal(self.agent_id, proposal_id)
>>>  253:         self.notify_proposal_change(str(proposal_id))
     254:
     255:     async def reject_proposal(self, proposal_id: int) -> None:
     256:         """Reject a pending policy proposal by ID."""
     257:         await self.persistence.reject_policy_proposal(self.agent_id, proposal_id)
     258:         self.notify_proposal_change(str(proposal_id))
   ...
     253:         self.notify_proposal_change(str(proposal_id))
     254:
     255:     async def reject_proposal(self, proposal_id: int) -> None:
     256:         """Reject a pending policy proposal by ID."""
     257:         await self.persistence.reject_policy_proposal(self.agent_id, proposal_id)
>>>  258:         self.notify_proposal_change(str(proposal_id))
     259:
     260:
     261: def make_policy_engine(
     262:     *,
     263:     agent_id: AgentID,
```

### `proposal-notifies-wrong-id.yaml` / `occ-0`

File: `adgn/src/adgn/agent/approvals.py`

> Lines 232-237 define create_proposal that sets new_id = 0 as placeholder, calls
> persistence with that placeholder, and notifies with str(new_id) still as "0".
> The actual database-assigned ID is never retrieved or used.
>
> Bug: clients receiving the notification get wrong proposal ID (0), notification
> points to non-existent proposal, return value at line 237 also wrong (returns 0
> instead of actual ID), creates data inconsistency between notified and persisted.
>
> Fix: create_policy_proposal should return actual database-assigned ID, then notify
> and return that ID. Or if persistence doesn't return ID, refactor it to do so or
> query for newly created proposal. Comment at lines 234-235 acknowledges the problem.
>
> Related to issue 023 about proposal_id type inconsistency.

```
     227:         """
     228:         # Self-check proposal program if docker is available
     229:         if self.docker_client is not None:
     230:             self.self_check(content)
     231:         # Generate new proposal ID (will be auto-generated by DB, use placeholder)
>>>  232:         new_id = 0  # Placeholder, actual ID assigned by database
>>>  233:         await self.persistence.create_policy_proposal(self.agent_id, proposal_id=new_id, content=content)
>>>  234:         # Note: We don't have the actual ID here, but persistence will handle it
>>>  235:         # For now, notify with string version for compatibility
>>>  236:         self.notify_proposal_change(str(new_id))
>>>  237:         return new_id
     238:
     239:     async def approve_proposal(self, proposal_id: int) -> None:
     240:         """Approve a pending policy proposal by ID and activate it.
     241:
     242:         Retrieves the proposal, validates it, activates it as the current policy,
   ...
     229:         if self.docker_client is not None:
     230:             self.self_check(content)
     231:         # Generate new proposal ID (will be auto-generated by DB, use placeholder)
     232:         new_id = 0  # Placeholder, actual ID assigned by database
     233:         await self.persistence.create_policy_proposal(self.agent_id, proposal_id=new_id, content=content)
>>>  234:         # Note: We don't have the actual ID here, but persistence will handle it
>>>  235:         # For now, notify with string version for compatibility
     236:         self.notify_proposal_change(str(new_id))
     237:         return new_id
     238:
     239:     async def approve_proposal(self, proposal_id: int) -> None:
     240:         """Approve a pending policy proposal by ID and activate it.
```

### `ternary-policy-source.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/cli.py`

> The code initializes policy_source to None and then conditionally assigns a value.
> This should use a ternary operator for conciseness.
>
> **Current code (lines 88-90):**
>
> ```python
> policy_source = None
> if initial_policy:
>     policy_source = initial_policy.read_text()
> ```
>
> **Should be:**
>
> ```python
> policy_source = initial_policy.read_text() if initial_policy else None
> ```
>
> **Why ternary is better:**
>
> - One line instead of three
> - More concise and readable
> - Clearly expresses the conditional assignment pattern
> - Standard Python idiom for simple conditional values
> - Easier to see both branches at once
>
> **Pattern applicability:**
> This is a classic ternary operator use case: simple conditional assignment where
> one branch has a value and the other is None (or another default).
>
> **Type safety:**
> Both versions correctly type as `str | None`. The ternary makes the two possible
> values (read_text() result or None) more visually apparent.

```
      83:     if mcp_config:
      84:         config = MCPConfig.model_validate_json(mcp_config.read_text())
      85:     else:
      86:         config = MCPConfig(mcpServers={})
      87:
>>>   88:     policy_source = None
>>>   89:     if initial_policy:
>>>   90:         policy_source = initial_policy.read_text()
      91:
      92:     asyncio.run(
      93:         _run_server(
      94:             agent_id=agent_id,
      95:             auth_tokens_path=auth_tokens,
```

### `test-main-block.yaml` / `occ-0`

File: `adgn/tests/agent/test_policy_validation_reload.py`

> Test file has unnecessary `__main__` block.
>
> Lines 153-154 in test_policy_validation_reload.py contain:
>
> ```python
> if __name__ == "__main__":
>     pytest.main([__file__, "-v"])
> ```
>
> Pytest tests shouldn't have `__main__` blocks. Run with `pytest` command instead. This is an outdated pattern.

```
     148:     # Try to reload (should fail - no policy in persistence)
     149:     with pytest.raises(ValueError, match="No policy found in persistence"):
     150:         await new_admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source=None))
     151:
     152:
>>>  153: if __name__ == "__main__":
>>>  154:     pytest.main([__file__, "-v"])
```

### `test-tokens-plain-dict.yaml` / `occ-0`

File: `adgn/tests/agent/server/test_mcp_routing.py`

> The `test_tokens` fixture uses plain dict instead of Pydantic model for type safety.
>
> **Current code (lines 15-21):**
>
> ```python
> @pytest.fixture
> def test_tokens():
>     """Override the global TOKEN_TABLE for testing."""
>     return {
>         "test-human-token": {"role": "human"},
>         "test-agent-token": {"role": "agent", "agent_id": "test-agent-1"},
>         "test-invalid-role": {"role": "invalid"},
>     }
> ```
>
> **Why this is problematic:**
>
> - Test data doesn't match production types (loses type safety)
> - Type errors only caught at runtime, not at test construction
> - Refactoring is unsafe (Pydantic model changes won't break tests immediately)
> - Structure is implicit rather than explicit
>
> **Recommended fix:**
> If there's a TokenConfig or similar Pydantic model in production code, the fixture
> should construct instances of that model:
>
> ```python
> @pytest.fixture
> def test_tokens():
>     return {
>         "test-human-token": TokenConfig(role="human"),
>         "test-agent-token": TokenConfig(role="agent", agent_id="test-agent-1"),
>         "test-invalid-role": TokenConfig(role="invalid"),
>     }
> ```
>
> This ensures test data matches production types, catches errors early, and makes
> refactoring safer.

```
      10: from adgn.agent.server.app import create_app
      11: from adgn.agent.server.mcp_routing import TOKEN_TABLE, TokenRole
      12:
      13:
      14: @pytest.fixture
>>>   15: def test_tokens():
>>>   16:     """Override the global TOKEN_TABLE for testing."""
>>>   17:     return {
>>>   18:         "test-human-token": {"role": "human"},
>>>   19:         "test-agent-token": {"role": "agent", "agent_id": "test-agent-1"},
>>>   20:         "test-invalid-role": {"role": "invalid"},
>>>   21:     }
      22:
      23:
      24: @pytest.fixture
      25: def mock_registry():
      26:     """Mock AgentRegistry for testing."""
```

### `tests-nonexistent-api.yaml` / `occ-0`

File: `adgn/tests/mcp/approval_policy/test_policy_resources.py`

> The test file `adgn/tests/mcp/approval_policy/test_policy_resources.py` tests a policy
> CRUD API that was never implemented in the production code.
>
> **Problem:**
> The test imports and uses types that don't exist in the codebase:
>
> - `CreatePolicyArgs` - for creating policies via admin tools
> - `UpdatePolicyArgs` - for updating policies
> - `DeletePolicyArgs` - for deleting policies
>
> These test a full policy CRUD (Create, Read, Update, Delete) API that was apparently
> planned but never implemented. The actual ApprovalPolicyAdminServer only provides:
>
> - Proposal management: create_proposal, approve_proposal, reject_proposal
> - Policy operations: set_policy, validate_policy, reload_policy
>
> There is no separate "create_policy", "update_policy", or "delete_policy" tool/functionality.
> The test file appears to be a placeholder or leftover from an earlier design.
>
> **Evidence:**
>
> - Test imports CreatePolicyArgs, UpdatePolicyArgs, DeletePolicyArgs (line 11-14)
> - All test classes (TestPolicyListResource, TestPolicyDetailResource, TestCreatePolicyTool,
>   TestUpdatePolicyTool, TestDeletePolicyTool, TestPolicyPagination, TestErrorHandling)
>   reference these non-existent types
> - The production code uses a different model: policies are managed through proposals
>   (create → approve) rather than direct CRUD operations
>
> **Resolution:**
> Delete this test file entirely. It tests functionality that was never built and would
> require significant production code implementation to make valid. The actual policy
> functionality is tested in test_policy_validation_reload.py and test_proposals_resources.py.
>
> **Alternative considerations:**
>
> - If direct policy CRUD is desired, it should be implemented in production code first
> - The test could be kept as a specification/TODO, but it's confusing to have failing
>   tests for unimplemented features in the main test suite
> - Better to track this as a feature request in documentation rather than broken tests

```
>>>    1: """Tests for policy CRUD resources and tools in the approval policy MCP server."""
>>>    2:
>>>    3: from __future__ import annotations
>>>    4:
>>>    5: from docker import DockerClient
>>>    6: import pytest
>>>    7:
>>>    8: from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
>>>    9: from adgn.agent.persist.sqlite import SQLitePersistence
>>>   10: from adgn.mcp.approval_policy.server import (
>>>   11:     ApprovalPolicyAdminServer,
>>>   12:     ApprovalPolicyServer,
>>>   13:     CreatePolicyArgs,
>>>   14:     DeletePolicyArgs,
>>>   15:     UpdatePolicyArgs,
>>>   16: )
>>>   17:
>>>   18:
>>>   19: @pytest.fixture
>>>   20: async def persistence(tmp_path):
>>>   21:     """Create a temporary SQLite persistence instance."""
>>>   22:     db_path = tmp_path / "test.db"
>>>   23:     persist = SQLitePersistence(db_path)
>>>   24:     await persist.ensure_schema()
>>>   25:     return persist
>>>   26:
>>>   27:
>>>   28: @pytest.fixture
>>>   29: async def engine(persistence, docker_client: DockerClient):
>>>   30:     """Create an approval policy engine with test persistence."""
>>>   31:
>>>   32:     agent_id = "test-agent"
>>>   33:
>>>   34:     # Create agent in persistence
>>>   35:     from fastmcp.mcp_config import MCPConfig
>>>   36:
>>>   37:     from adgn.agent.persist import AgentMetadata
>>>   38:
>>>   39:     await persistence.create_agent(mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test"))
>>>   40:
>>>   41:     # Create engine with default policy
>>>   42:     policy_source = load_default_policy_source()
>>>   43:     engine = ApprovalPolicyEngine(
>>>   44:         docker_client=docker_client,
>>>   45:         agent_id=agent_id,
>>>   46:         persistence=persistence,
>>>   47:         policy_source=policy_source,
>>>   48:     )
>>>   49:     return engine
>>>   50:
>>>   51:
>>>   52: @pytest.fixture
>>>   53: async def policy_server(engine):
>>>   54:     """Create a policy server (reader) instance."""
>>>   55:     return ApprovalPolicyServer(engine)
>>>   56:
>>>   57:
>>>   58: @pytest.fixture
>>>   59: async def admin_server(engine):
>>>   60:     """Create an admin server instance."""
>>>   61:     return ApprovalPolicyAdminServer(engine=engine)
>>>   62:
>>>   63:
>>>   64: class TestPolicyListResource:
>>>   65:     """Test the policy list resource."""
>>>   66:
>>>   67:     async def test_list_empty(self, policy_server):
>>>   68:         """Test listing policies when none exist."""
>>>   69:         # Access the policies_list resource
>>>   70:         result = await policy_server._mcp_server.read_resource(uri="resource://policies/list")
>>>   71:         assert result is not None
>>>   72:         # Should return empty list as JSON
>>>   73:         import json
>>>   74:
>>>   75:         data = json.loads(result.contents[0].text)
>>>   76:         assert isinstance(data, list)
>>>   77:         assert len(data) == 0
>>>   78:
>>>   79:     async def test_list_with_policies(self, policy_server, admin_server, persistence):
>>>   80:         """Test listing policies after creating some."""
>>>   81:         # Create a few policies via admin tools
>>>   82:         policy1 = await admin_server._mcp_server.call_tool(
>>>   83:             "create_policy",
>>>   84:             arguments=CreatePolicyArgs(
>>>   85:                 id="policy-1",
>>>   86:                 text="print('policy 1')",
>>>   87:                 description="First test policy",
>>>   88:                 enabled=True,
>>>   89:             ).model_dump(),
>>>   90:         )
>>>   91:
>>>   92:         policy2 = await admin_server._mcp_server.call_tool(
>>>   93:             "create_policy",
>>>   94:             arguments=CreatePolicyArgs(
>>>   95:                 id="policy-2",
>>>   96:                 text="print('policy 2')",
>>>   97:                 description="Second test policy",
>>>   98:                 enabled=False,
>>>   99:             ).model_dump(),
>>>  100:         )
>>>  101:
>>>  102:         # Now list policies
>>>  103:         result = await policy_server._mcp_server.read_resource(uri="resource://policies/list")
>>>  104:         assert result is not None
>>>  105:
>>>  106:         import json
>>>  107:
>>>  108:         data = json.loads(result.contents[0].text)
>>>  109:         assert isinstance(data, list)
>>>  110:         assert len(data) == 2
>>>  111:
>>>  112:         # Verify structure (should be PolicyListItem)
>>>  113:         for item in data:
>>>  114:             assert "id" in item
>>>  115:             assert "description" in item
>>>  116:             assert "enabled" in item
>>>  117:
>>>  118:
>>>  119: class TestPolicyDetailResource:
>>>  120:     """Test the policy detail resource."""
>>>  121:
>>>  122:     async def test_get_nonexistent(self, policy_server):
>>>  123:         """Test getting a policy that doesn't exist."""
>>>  124:         with pytest.raises(KeyError):
>>>  125:             await policy_server._mcp_server.read_resource(uri="resource://policies/nonexistent")
>>>  126:
>>>  127:     async def test_get_existing(self, policy_server, admin_server):
>>>  128:         """Test getting an existing policy."""
>>>  129:         # Create a policy first
>>>  130:         await admin_server._mcp_server.call_tool(
>>>  131:             "create_policy",
>>>  132:             arguments=CreatePolicyArgs(
>>>  133:                 id="test-policy",
>>>  134:                 text="print('test policy')",
>>>  135:                 description="A test policy",
>>>  136:                 enabled=True,
>>>  137:             ).model_dump(),
>>>  138:         )
>>>  139:
>>>  140:         # Now get it
>>>  141:         result = await policy_server._mcp_server.read_resource(uri="resource://policies/test-policy")
>>>  142:         assert result is not None
>>>  143:
>>>  144:         import json
>>>  145:
>>>  146:         data = json.loads(result.contents[0].text)
>>>  147:         assert data["id"] == "test-policy"
>>>  148:         assert data["text"] == "print('test policy')"
>>>  149:         assert data["description"] == "A test policy"
>>>  150:         assert data["enabled"] is True
>>>  151:
>>>  152:
>>>  153: class TestCreatePolicyTool:
>>>  154:     """Test the create_policy admin tool."""
>>>  155:
>>>  156:     async def test_create_basic(self, admin_server, persistence):
>>>  157:         """Test creating a basic policy."""
>>>  158:         result = await admin_server._mcp_server.call_tool(
>>>  159:             "create_policy",
>>>  160:             arguments=CreatePolicyArgs(
>>>  161:                 id="new-policy",
>>>  162:                 text="print('new policy')",
>>>  163:                 description="A new policy",
>>>  164:                 enabled=True,
>>>  165:             ).model_dump(),
>>>  166:         )
>>>  167:
>>>  168:         assert result.isError is False
>>>  169:
>>>  170:         # Verify it was created in persistence
>>>  171:         policy = await persistence.get_policy("new-policy")
>>>  172:         assert policy is not None
>>>  173:         assert policy.id == "new-policy"
>>>  174:         assert policy.text == "print('new policy')"
>>>  175:         assert policy.description == "A new policy"
>>>  176:         assert policy.enabled is True
>>>  177:
>>>  178:     async def test_create_duplicate(self, admin_server, persistence):
>>>  179:         """Test creating a policy with duplicate ID fails."""
>>>  180:         # Create first policy
>>>  181:         await admin_server._mcp_server.call_tool(
>>>  182:             "create_policy",
>>>  183:             arguments=CreatePolicyArgs(
>>>  184:                 id="dup-policy",
>>>  185:                 text="print('dup')",
>>>  186:             ).model_dump(),
>>>  187:         )
>>>  188:
>>>  189:         # Try to create another with same ID
>>>  190:         result = await admin_server._mcp_server.call_tool(
>>>  191:             "create_policy",
>>>  192:             arguments=CreatePolicyArgs(
>>>  193:                 id="dup-policy",
>>>  194:                 text="print('dup 2')",
>>>  195:             ).model_dump(),
>>>  196:             raise_on_error=False,
>>>  197:         )
>>>  198:
>>>  199:         assert result.isError is True
>>>  200:
>>>  201:     async def test_create_minimal(self, admin_server, persistence):
>>>  202:         """Test creating a policy with minimal args."""
>>>  203:         result = await admin_server._mcp_server.call_tool(
>>>  204:             "create_policy",
>>>  205:             arguments=CreatePolicyArgs(
>>>  206:                 id="minimal",
>>>  207:                 text="pass",
>>>  208:             ).model_dump(),
>>>  209:         )
>>>  210:
>>>  211:         assert result.isError is False
>>>  212:
>>>  213:         policy = await persistence.get_policy("minimal")
>>>  214:         assert policy is not None
>>>  215:         assert policy.id == "minimal"
>>>  216:         assert policy.text == "pass"
>>>  217:         assert policy.description is None
>>>  218:         assert policy.enabled is True  # default
>>>  219:
>>>  220:
>>>  221: class TestUpdatePolicyTool:
>>>  222:     """Test the update_policy admin tool."""
>>>  223:
>>>  224:     async def test_update_existing(self, admin_server, persistence):
>>>  225:         """Test updating an existing policy."""
>>>  226:         # Create a policy first
>>>  227:         await admin_server._mcp_server.call_tool(
>>>  228:             "create_policy",
>>>  229:             arguments=CreatePolicyArgs(
>>>  230:                 id="update-me",
>>>  231:                 text="print('v1')",
>>>  232:                 description="Version 1",
>>>  233:             ).model_dump(),
>>>  234:         )
>>>  235:
>>>  236:         # Update it
>>>  237:         result = await admin_server._mcp_server.call_tool(
>>>  238:             "update_policy",
>>>  239:             arguments=UpdatePolicyArgs(
>>>  240:                 id="update-me",
>>>  241:                 text="print('v2')",
>>>  242:                 description="Version 2",
>>>  243:             ).model_dump(),
>>>  244:         )
>>>  245:
>>>  246:         assert result.isError is False
>>>  247:
>>>  248:         # Verify the update
>>>  249:         policy = await persistence.get_policy("update-me")
>>>  250:         assert policy is not None
>>>  251:         assert policy.text == "print('v2')"
>>>  252:         assert policy.description == "Version 2"
>>>  253:
>>>  254:     async def test_update_nonexistent(self, admin_server):
>>>  255:         """Test updating a nonexistent policy fails."""
>>>  256:         result = await admin_server._mcp_server.call_tool(
>>>  257:             "update_policy",
>>>  258:             arguments=UpdatePolicyArgs(
>>>  259:                 id="nonexistent",
>>>  260:                 text="print('new')",
>>>  261:             ).model_dump(),
>>>  262:             raise_on_error=False,
>>>  263:         )
>>>  264:
>>>  265:         assert result.isError is True
>>>  266:
>>>  267:     async def test_update_creates_history(self, admin_server, persistence):
>>>  268:         """Test that updating a policy creates a history entry."""
>>>  269:         # Create initial policy
>>>  270:         await admin_server._mcp_server.call_tool(
>>>  271:             "create_policy",
>>>  272:             arguments=CreatePolicyArgs(
>>>  273:                 id="versioned",
>>>  274:                 text="print('v1')",
>>>  275:             ).model_dump(),
>>>  276:         )
>>>  277:
>>>  278:         # Update it
>>>  279:         await admin_server._mcp_server.call_tool(
>>>  280:             "update_policy",
>>>  281:             arguments=UpdatePolicyArgs(
>>>  282:                 id="versioned",
>>>  283:                 text="print('v2')",
>>>  284:             ).model_dump(),
>>>  285:         )
>>>  286:
>>>  287:         # Check that history was created (requires accessing policy_history table)
>>>  288:         # For now, just verify the update worked
>>>  289:         policy = await persistence.get_policy("versioned")
>>>  290:         assert policy.text == "print('v2')"
>>>  291:
>>>  292:
>>>  293: class TestDeletePolicyTool:
>>>  294:     """Test the delete_policy admin tool."""
>>>  295:
>>>  296:     async def test_delete_existing(self, admin_server, persistence):
>>>  297:         """Test deleting an existing policy."""
>>>  298:         # Create a policy first
>>>  299:         await admin_server._mcp_server.call_tool(
>>>  300:             "create_policy",
>>>  301:             arguments=CreatePolicyArgs(
>>>  302:                 id="delete-me",
>>>  303:                 text="print('bye')",
>>>  304:             ).model_dump(),
>>>  305:         )
>>>  306:
>>>  307:         # Verify it exists
>>>  308:         policy = await persistence.get_policy("delete-me")
>>>  309:         assert policy is not None
>>>  310:
>>>  311:         # Delete it
>>>  312:         result = await admin_server._mcp_server.call_tool(
>>>  313:             "delete_policy",
>>>  314:             arguments=DeletePolicyArgs(id="delete-me").model_dump(),
>>>  315:         )
>>>  316:
>>>  317:         assert result.isError is False
>>>  318:
>>>  319:         # Verify it's gone
>>>  320:         policy = await persistence.get_policy("delete-me")
>>>  321:         assert policy is None
>>>  322:
>>>  323:     async def test_delete_nonexistent(self, admin_server):
>>>  324:         """Test deleting a nonexistent policy succeeds (idempotent)."""
>>>  325:         result = await admin_server._mcp_server.call_tool(
>>>  326:             "delete_policy",
>>>  327:             arguments=DeletePolicyArgs(id="nonexistent").model_dump(),
>>>  328:         )
>>>  329:
>>>  330:         # SQLite DELETE is idempotent, so this should succeed
>>>  331:         assert result.isError is False
>>>  332:
>>>  333:
>>>  334: class TestPolicyPagination:
>>>  335:     """Test pagination in policy list."""
>>>  336:
>>>  337:     async def test_pagination(self, admin_server, persistence):
>>>  338:         """Test that pagination works for policy list."""
>>>  339:         # Create multiple policies
>>>  340:         for i in range(10):
>>>  341:             await persistence.create_policy(
>>>  342:                 policy_id=f"policy-{i}",
>>>  343:                 text=f"print({i})",
>>>  344:                 description=f"Policy {i}",
>>>  345:             )
>>>  346:
>>>  347:         # List with limit
>>>  348:         policies = await persistence.list_policies(offset=0, limit=5)
>>>  349:         assert len(policies) == 5
>>>  350:
>>>  351:         # List next page
>>>  352:         policies = await persistence.list_policies(offset=5, limit=5)
>>>  353:         assert len(policies) == 5
>>>  354:
>>>  355:         # List all
>>>  356:         policies = await persistence.list_policies(offset=0, limit=100)
>>>  357:         assert len(policies) == 10
>>>  358:
>>>  359:
>>>  360: class TestErrorHandling:
>>>  361:     """Test error handling in policy CRUD operations."""
>>>  362:
>>>  363:     async def test_invalid_policy_text(self, admin_server):
>>>  364:         """Test that invalid Python syntax is caught."""
>>>  365:         # Note: create_policy doesn't validate syntax, so this should succeed
>>>  366:         result = await admin_server._mcp_server.call_tool(
>>>  367:             "create_policy",
>>>  368:             arguments=CreatePolicyArgs(
>>>  369:                 id="invalid",
>>>  370:                 text="this is not valid python !!!",
>>>  371:             ).model_dump(),
>>>  372:         )
>>>  373:
>>>  374:         # Creation succeeds (validation happens at execution time)
>>>  375:         assert result.isError is False
>>>  376:
>>>  377:     async def test_missing_required_fields(self, admin_server):
>>>  378:         """Test that missing required fields cause validation errors."""
>>>  379:         # Missing 'id' and 'text'
>>>  380:         with pytest.raises(Exception):  # Pydantic validation error
>>>  381:             await admin_server._mcp_server.call_tool(
>>>  382:                 "create_policy",
>>>  383:                 arguments={},  # Missing required fields
>>>  384:             )
```

### `typeadapter-token-mapping.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/auth.py`

> Lines 44-56 manually parse JSON and validate dict[str, str] structure with explicit
> isinstance checks and an imperative loop. This should use Pydantic's TypeAdapter
> for cleaner code and better error messages.
>
> Current approach: json.loads + manual dict check + loop with isinstance checks for
> each key/value pair. Problems: verbose (10 lines vs 3), generic error messages
> don't specify which field failed, duplicates validation logic Pydantic provides.
>
> Replace with TypeAdapter: 3 lines using adapter.validate_json() + dict comprehension
> to convert to AgentID. Benefits: integrated JSON parsing and validation, detailed
> validation errors with locations, no manual isinstance checks, more Pythonic.
>
> AgentID is NewType("AgentID", str), so dict comprehension conversion is safe.

```
      39:     def reload(self) -> None:
      40:         """Reload mapping from file."""
      41:         if not self.path.exists():
      42:             raise FileNotFoundError(f"Token mapping file not found: {self.path}")
      43:
>>>   44:         data = json.loads(self.path.read_text())
>>>   45:         if not isinstance(data, dict):
>>>   46:             raise ValueError("Token mapping must be a JSON object")
>>>   47:
>>>   48:         # Validate all values are strings and convert to AgentID
>>>   49:         mapping: dict[str, AgentID] = {}
>>>   50:         for token, agent_id in data.items():
>>>   51:             if not isinstance(token, str) or not isinstance(agent_id, str):
>>>   52:                 raise ValueError(f"Invalid mapping: {token} -> {agent_id}")
>>>   53:             mapping[token] = AgentID(agent_id)
>>>   54:
>>>   55:         self._mapping = mapping
      56:         logger.info(f"Loaded {len(self._mapping)} token mappings from {self.path}")
      57:
      58:     def get_agent_id(self, token: str) -> AgentID | None:
      59:         """Get agent_id for a token, or None if not found."""
      60:         return self._mapping.get(token)
   ...
       5: """
       6:
       7: from __future__ import annotations
       8:
       9: from collections.abc import Awaitable, Callable
>>>   10: import json
      11: import logging
      12: import os
      13: from pathlib import Path
      14: import secrets
      15:
```

### `use-path-read-text.yaml` / `occ-0`

File: `adgn/scripts/generate_frontend_code.py`

> The code uses `open()` with manual read when `Path.read_text()` is cleaner and more idiomatic.
>
> **Current code (lines 52-53):**
>
> ```python
> with open(python_file) as f:
>     code = f.read()
> ```
>
> **Should be:**
>
> ```python
> code = python_file.read_text()
> ```
>
> **Why Path.read_text() is better:**
>
> - `python_file` is already a `Path` object (line 47 signature shows `Path`)
> - `Path.read_text()` handles encoding automatically (defaults to locale encoding)
> - More concise - one line instead of two
> - Consistent with line 174 which already uses `output_file.write_text(ts_code)`
> - No need for manual context manager
> - More idiomatic modern Python
>
> **Context preservation:**
> The current code executes the file with `exec(code, namespace)` at line 54, so the code
> string is still needed. This is not about removing the intermediate variable, just using
> the cleaner Path API.

```
      47: def extract_constants_from_file(python_file: Path) -> dict[str, Any]:
      48:     """Extract Final[str] constants from a Python file using runtime evaluation."""
      49:     namespace: dict[str, Any] = {}
      50:
      51:     try:
>>>   52:         with open(python_file) as f:
>>>   53:             code = f.read()
      54:         exec(code, namespace)
      55:     except Exception as e:
      56:         print(f"Error executing constants file: {e}", file=sys.stderr)
      57:         raise
      58:
   ...
     169:     print(f"  Simple URIs: {len(simple_uris)}")
     170:     print(f"  Format strings: {len(format_uris)}")
     171:
     172:     ts_code = generate_mcp_constants_typescript(simple_uris, format_uris)
     173:
>>>  174:     output_file.write_text(ts_code)
     175:     print(f"  ✓ Generated {output_file}")
     176:
     177:
     178: # ============================================================================
     179: # TypeScript Types Generation
```

## ducktape/2025-11-21-00 (13)

### `agent-info-computable-uris.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

> The `state_uri`, `approvals_uri`, and `policy_proposals_uri` fields in `AgentInfo` (lines 144-146)
> can always be computed from `agent_id`. They should not be in the Pydantic model as they add no
> information and create unnecessary redundancy.
>
> URIs follow deterministic patterns: `resource://agents/{agent_id}/policy/state`,
> `resource://agents/{agent_id}/approvals/history`, `resource://agents/{agent_id}/policy/proposals`.
> Client can easily construct given agent_id.
>
> Problems: (1) Storing precomputed derivable values violates DRY, creates maintenance burden.
> (2) If URI patterns change, must update both construction logic AND field values. (3) All three
> are `str | None = None`, but could always be computed - `None` default misleadingly suggests
> sometimes unavailable. (4) Fields appear defined but not populated anywhere (no assignments
> found), dead weight. (5) Bloats response payloads with redundant URIs.
>
> Fix: Remove all three URI fields from AgentInfo. If clients need URIs, construct client-side
> from `agent_id` using helper, or use separate endpoint. Alternative: `@property` that computes
> on-demand, but removing entirely is preferred.
>
> Benefits: Single source of truth for URI patterns, smaller cleaner model, no risk of stale URIs,
> less code to maintain, clearer URIs are derived not stored.

```
     139: # Resource response models
     140: class AgentInfo(BaseModel):
     141:     """Information about a single agent."""
     142:
     143:     agent_id: AgentID
>>>  144:     capabilities: dict[str, bool]  # e.g., {"chat": True, "agent_loop": False}
>>>  145:     mode: AgentMode
>>>  146:     state_uri: str | None = None
     147:     approvals_uri: str | None = None
     148:     policy_proposals_uri: str | None = None
     149:
     150:
     151: class AgentList(BaseModel):
```

### `approvals-pending-manual-json.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

> Lines 395-424 define `approvals_pending_global` that manually constructs JSON dicts with
> string keys and `json.dumps()` instead of using Pydantic models.
>
> Problems: manual dict construction doesn't catch typos (`{"call_idd": x}`); no validation
> (wrong types like `{"call_id": 123}` slip through); hard to evolve (field changes require
> manual updates across dict literals); inconsistent with codebase (other functions use
> Pydantic like AgentApprovalsPending); nested tool_call dict manually constructed despite
> existing ToolCall model; no IDE autocomplete or type checking.
>
> Lines 411-419 manually build pending_list dicts; lines 421-424 manually construct result
> dicts with json.dumps.
>
> Replace with Pydantic models (PendingApprovalItem, AgentPendingApprovalsBlock, ResourceBlock)
> and use model_dump_json() for serialization. Benefits: type safety, automatic validation,
> IDE support, reuses existing ToolCall model, framework handles serialization.

```
     390:
     391:     @server.resource(
     392:         "resource://approvals/pending",
     393:         name="approvals.pending.global",
     394:         mime_type="application/json",
>>>  395:         description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)",
>>>  396:     )
>>>  397:     async def approvals_pending_global():
>>>  398:         """Each approval is a separate MCP TextResourceContents block.
>>>  399:
>>>  400:         Crashes if any agent fails (no exception swallowing).
>>>  401:         """
>>>  402:         content_blocks: list[mcp_types.TextResourceContents] = []
>>>  403:
>>>  404:         for agent_id in registry.known_agents():
>>>  405:             infra = await registry.get_infrastructure(agent_id)
>>>  406:             pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)
>>>  407:
>>>  408:             for approval in pending_approvals:
>>>  409:                 approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
>>>  410:                 approval_data = {
>>>  411:                     "agent_id": agent_id,
>>>  412:                     "call_id": approval.call_id,
>>>  413:                     "tool": approval.tool,
>>>  414:                     "args": approval.args,
>>>  415:                     "timestamp": approval.timestamp.isoformat(),
>>>  416:                 }
>>>  417:                 block = mcp_types.TextResourceContents(
>>>  418:                     uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data)
>>>  419:                 )
>>>  420:                 content_blocks.append(block)
>>>  421:
>>>  422:         return mcp_types.ReadResourceResult(contents=content_blocks)
>>>  423:
>>>  424:     @server.resource(
     425:         "resource://agents/{agent_id}/approvals/history",
     426:         name="agent.approvals.history",
     427:         mime_type="application/json",
     428:         description="Historical approval timeline for an agent (activity log)",
     429:     )
   ...
     406:             pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)
     407:
     408:             for approval in pending_approvals:
     409:                 approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
     410:                 approval_data = {
>>>  411:                     "agent_id": agent_id,
>>>  412:                     "call_id": approval.call_id,
>>>  413:                     "tool": approval.tool,
>>>  414:                     "args": approval.args,
>>>  415:                     "timestamp": approval.timestamp.isoformat(),
>>>  416:                 }
>>>  417:                 block = mcp_types.TextResourceContents(
>>>  418:                     uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data)
>>>  419:                 )
     420:                 content_blocks.append(block)
     421:
     422:         return mcp_types.ReadResourceResult(contents=content_blocks)
     423:
     424:     @server.resource(
   ...
     416:                 }
     417:                 block = mcp_types.TextResourceContents(
     418:                     uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data)
     419:                 )
     420:                 content_blocks.append(block)
>>>  421:
>>>  422:         return mcp_types.ReadResourceResult(contents=content_blocks)
>>>  423:
>>>  424:     @server.resource(
     425:         "resource://agents/{agent_id}/approvals/history",
     426:         name="agent.approvals.history",
     427:         mime_type="application/json",
     428:         description="Historical approval timeline for an agent (activity log)",
     429:     )
```

### `list-agents-manual-dicts.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

> Lines 270-312 manually construct dict objects with 7 fields (id, mode, live, active_run_id,
> run_phase, pending_approvals, capabilities) and serialize via `json.dumps()`, returning `str`.
>
> Manual dict construction loses: (1) type safety (typos in field names uncaught), (2) validation
> (wrong types or missing fields undetected), (3) IDE support (no autocomplete), (4) self-documentation
> (schema not explicit).
>
> The rest of the codebase uses Pydantic models for structured responses (e.g., `AgentInfo`,
> `AgentList`, `AgentApprovalsHistory`). This function is an outlier.
>
> Replace manual dict construction with Pydantic models: define `AgentListItem(BaseModel)` with the
> 7 fields, return `AgentsList(agents: list[AgentListItem])` instead of `str`, and remove the manual
> `json.dumps()` call (let the framework handle serialization).

```
     256:
     257:     @server.resource(
     258:         "resource://agents/list",
     259:         name="agents.list",
     260:         mime_type="application/json",
>>>  261:         description="List all agents with detailed status",
>>>  262:     )
>>>  263:     async def list_agents() -> str:
>>>  264:         """Global agent list with detailed status for each agent.
>>>  265:
>>>  266:         Returns JSON with agents array containing status information including:
>>>  267:         - id, mode, live status
>>>  268:         - active_run_id, run_phase
>>>  269:         - pending_approvals count
>>>  270:         - capabilities (chat, agent_loop)
>>>  271:         """
>>>  272:         agents = []
>>>  273:         for agent_id in registry.known_agents():
>>>  274:             try:
>>>  275:                 mode = registry.get_agent_mode(agent_id)
>>>  276:             except KeyError:
>>>  277:                 continue
>>>  278:
>>>  279:             # Get infrastructure if available
>>>  280:             infra = registry.get_running_infrastructure(agent_id)
>>>  281:             live = infra is not None
>>>  282:
>>>  283:             # Compute status fields
>>>  284:             active_run_id = None
>>>  285:             pending_approvals = 0
>>>  286:             run_phase = "idle"
>>>  287:
>>>  288:             if infra:
>>>  289:                 # Get pending approvals count
>>>  290:                 pending_approvals = len(infra.approval_hub.pending)
>>>  291:
>>>  292:                 # Derive run phase based on active state
>>>  293:                 if pending_approvals > 0:
>>>  294:                     run_phase = "waiting_approval"
>>>  295:                 elif live:
>>>  296:                     run_phase = "sampling"
>>>  297:
>>>  298:             # Determine capabilities
>>>  299:             is_local = mode == AgentMode.LOCAL
>>>  300:             capabilities = {"chat": is_local, "agent_loop": is_local}
>>>  301:
>>>  302:             agents.append(
>>>  303:                 {
>>>  304:                     "id": agent_id,
>>>  305:                     "mode": mode,
>>>  306:                     "live": live,
>>>  307:                     "active_run_id": str(active_run_id) if active_run_id else None,
>>>  308:                     "run_phase": run_phase,
>>>  309:                     "pending_approvals": pending_approvals,
>>>  310:                     "capabilities": capabilities,
>>>  311:                 }
>>>  312:             )
     313:
     314:         return json.dumps({"agents": agents})
     315:
     316:     @server.resource(
     317:         "resource://agents/{agent_id}/state",
   ...
     295:                 elif live:
     296:                     run_phase = "sampling"
     297:
     298:             # Determine capabilities
     299:             is_local = mode == AgentMode.LOCAL
>>>  300:             capabilities = {"chat": is_local, "agent_loop": is_local}
>>>  301:
>>>  302:             agents.append(
>>>  303:                 {
>>>  304:                     "id": agent_id,
>>>  305:                     "mode": mode,
>>>  306:                     "live": live,
>>>  307:                     "active_run_id": str(active_run_id) if active_run_id else None,
>>>  308:                     "run_phase": run_phase,
>>>  309:                     "pending_approvals": pending_approvals,
>>>  310:                     "capabilities": capabilities,
     311:                 }
     312:             )
     313:
     314:         return json.dumps({"agents": agents})
     315:
   ...
     307:                     "active_run_id": str(active_run_id) if active_run_id else None,
     308:                     "run_phase": run_phase,
     309:                     "pending_approvals": pending_approvals,
     310:                     "capabilities": capabilities,
     311:                 }
>>>  312:             )
     313:
     314:         return json.dumps({"agents": agents})
     315:
     316:     @server.resource(
     317:         "resource://agents/{agent_id}/state",
```

### `proposal-uri-computable.yaml` / `occ-0`

File: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

> Line 178 defines `PolicyProposalInfo` with a `proposal_uri` field that is trivially computable
> from the `id` field via `f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{id}"`.
>
> This creates redundancy and inconsistency risk: storing both `id` and `proposal_uri` violates
> DRY when one is derivable from the other. If the URI pattern changes, both the construction
> logic and this field must be updated. The field also bloats response payloads when listing
> many proposals.
>
> The codebase uses IDs as primary identifiers elsewhere, not URIs. Mixing both creates
> confusion about which is canonical.
>
> Remove `proposal_uri` field from the model; clients can construct URIs on-demand from IDs.
> Benefits: single source of truth, smaller payloads, no sync risk, consistency with ID-based
> patterns.

```
     173: class PolicyProposalInfo(BaseModel):
     174:     """Policy proposal metadata with URI to full content."""
     175:
     176:     id: str
     177:     status: ProposalStatus
>>>  178:     created_at: datetime
     179:     decided_at: datetime | None = None
     180:     proposal_uri: str  # URI to access full proposal content in policy server
     181:
     182:
     183: class AgentPolicyProposals(BaseModel):
```

### `redundant-tuple-construction.yaml` / `occ-0`

File: `adgn/src/adgn/agent/agent.py`

> Lines 255-258 build `calls: list[tuple[FunctionCallItem, str | None]]` duplicating
> `function_call.arguments` when it's already in the `FunctionCallItem` object.
>
> Current: constructs tuples `(function_call, function_call.arguments)`, then passes
> both `calls` (tuples) and `function_calls` (original list) to
> `_run_tool_calls_parallel` and `_run_tool_calls_sequential` (lines 291, 293).
>
> Sequential usage (line 336): `for i, (function_call, args_json) in enumerate(calls):`
> then `invoker(function_call, args_json)`. Could iterate `function_calls` directly
> and access `function_call.arguments`.
>
> Parallel usage (line 305): `runner(fc: FunctionCallItem, aj: str | None)` then
> unpacks tuples at line 310. Could take only `FunctionCallItem` and access
> `fc.arguments` inside.
>
> **Fix:** Delete tuple construction, pass only `function_calls` to both methods,
> access `.arguments` directly, remove tuple unpacking. Benefits: no duplication,
> simpler code, one less list, clearer that we're working with objects.

```
     250:         except Exception as exc:
     251:             self._controller.on_error(exc)
     252:             raise
     253:
     254:     async def _handle_pending_tool_calls(self) -> None:
>>>  255:         function_calls: list[FunctionCallItem] = list(self.pending_function_calls)
>>>  256:         calls: list[tuple[FunctionCallItem, str | None]] = [
>>>  257:             (function_call, function_call.arguments) for function_call in function_calls
>>>  258:         ]
     259:
     260:         local_result_map: dict[str, CallToolResult] = {
     261:             evt.call_id: evt.result for evt in self._transcript if isinstance(evt, ToolCallOutput)
     262:         }
     263:
   ...
     286:             if res.is_error:
     287:                 return ToolCallFailure(result=res, reason=_maybe_error_message(res))
     288:             return ToolCallSuccess(result=res)
     289:
     290:         if self._parallel_tool_calls:
>>>  291:             await self._run_tool_calls_parallel(calls, function_calls, _invoke)
     292:         else:
     293:             await self._run_tool_calls_sequential(calls, function_calls, _invoke)
     294:         self.pending_function_calls.clear()
     295:
     296:     async def _run_tool_calls_parallel(
   ...
     288:             return ToolCallSuccess(result=res)
     289:
     290:         if self._parallel_tool_calls:
     291:             await self._run_tool_calls_parallel(calls, function_calls, _invoke)
     292:         else:
>>>  293:             await self._run_tool_calls_sequential(calls, function_calls, _invoke)
     294:         self.pending_function_calls.clear()
     295:
     296:     async def _run_tool_calls_parallel(
     297:         self, calls: list[tuple[FunctionCallItem, str | None]], function_calls: list[FunctionCallItem], invoker
     298:     ) -> None:
   ...
     291:             await self._run_tool_calls_parallel(calls, function_calls, _invoke)
     292:         else:
     293:             await self._run_tool_calls_sequential(calls, function_calls, _invoke)
     294:         self.pending_function_calls.clear()
     295:
>>>  296:     async def _run_tool_calls_parallel(
>>>  297:         self, calls: list[tuple[FunctionCallItem, str | None]], function_calls: list[FunctionCallItem], invoker
>>>  298:     ) -> None:
     299:         results: dict[str, ToolCallOutcome] = {}
     300:         abort_triggered = False
     301:
     302:         async with anyio.create_task_group() as tg:
     303:             cancelled_exc = anyio.get_cancelled_exc_class()
   ...
     328:             if isinstance(outcome, ToolCallAborted):
     329:                 had_error = True
     330:         if had_error:
     331:             self.finished = True
     332:
>>>  333:     async def _run_tool_calls_sequential(
>>>  334:         self, calls: list[tuple[FunctionCallItem, str | None]], function_calls: list[FunctionCallItem], invoker
>>>  335:     ) -> None:
     336:         for i, (function_call, args_json) in enumerate(calls):
     337:             outcome = await invoker(function_call, args_json)
     338:             self._emit_tool_result(function_call, outcome.result)
     339:             if isinstance(outcome, ToolCallAborted):
     340:                 for remaining in function_calls[i + 1 :]:
   ...
     331:             self.finished = True
     332:
     333:     async def _run_tool_calls_sequential(
     334:         self, calls: list[tuple[FunctionCallItem, str | None]], function_calls: list[FunctionCallItem], invoker
     335:     ) -> None:
>>>  336:         for i, (function_call, args_json) in enumerate(calls):
     337:             outcome = await invoker(function_call, args_json)
     338:             self._emit_tool_result(function_call, outcome.result)
     339:             if isinstance(outcome, ToolCallAborted):
     340:                 for remaining in function_calls[i + 1 :]:
     341:                     self._emit_tool_result(remaining, _abort_result())
   ...
     300:         abort_triggered = False
     301:
     302:         async with anyio.create_task_group() as tg:
     303:             cancelled_exc = anyio.get_cancelled_exc_class()
     304:
>>>  305:             async def runner(fc: FunctionCallItem, aj: str | None) -> None:
     306:                 nonlocal abort_triggered
     307:                 try:
     308:                     outcome = await invoker(fc, aj)
     309:                 except cancelled_exc:
     310:                     return
   ...
     305:             async def runner(fc: FunctionCallItem, aj: str | None) -> None:
     306:                 nonlocal abort_triggered
     307:                 try:
     308:                     outcome = await invoker(fc, aj)
     309:                 except cancelled_exc:
>>>  310:                     return
     311:                 cid = _require_call_id(fc)
     312:                 results[cid] = outcome
     313:                 if isinstance(outcome, ToolCallAborted):
     314:                     abort_triggered = True
     315:                     tg.cancel_scope.cancel()
```

### `stringly-typed-backend-key.yaml` / `occ-0`

File: `adgn/src/adgn/agent/server/mcp_routing.py`

> Line 80 declares `_backend_apps: dict[str, ASGIApp]` with string keys. Lines 93-108 construct
> string keys ("human" or f"agent:{agent_id}") from strongly-typed TokenInfo discriminators, then
> use these strings for dict lookups.
>
> Stringly-typed keys lose type safety (typos in format strings uncaught), fragility (adding new
> TokenInfo types requires remembering string format), and IDE support (no autocomplete/refactoring).
> The match statement already discriminates on TokenInfo types; converting to strings duplicates
> this discrimination in a weaker form.
>
> Use TokenInfo directly as dict keys: change to `dict[TokenInfo, ASGIApp]` and replace `backend_key`
> string construction with `token_info` directly. Requires making HumanTokenInfo and AgentTokenInfo
> frozen Pydantic models (`model_config = ConfigDict(frozen=True)`) so they're hashable and can serve
> as dict keys. This preserves type information throughout the caching layer.

```
      75:         super().__init__(app)
      76:         self.token_table = token_table
      77:         self.registry = registry
      78:         self.agents_server = agents_server
      79:         # Cache for backend ASGI apps by routing key
>>>   80:         self._backend_apps: dict[str, ASGIApp] = {}
      81:
      82:     def _extract_bearer_token(self, headers: list[tuple[bytes, bytes]]) -> str | None:
      83:         """Extract Bearer token from Authorization header."""
      84:         for name, value in headers:
      85:             if name.lower() == b"authorization":
   ...
      88:                     return auth_value.removeprefix(BEARER_PREFIX)
      89:         return None
      90:
      91:     async def _get_backend_app(self, token_info: TokenInfo) -> ASGIApp:
      92:         """Get or create backend ASGI app for the given token info."""
>>>   93:         match token_info:
>>>   94:             case HumanTokenInfo():
>>>   95:                 backend_key = "human"
>>>   96:                 if backend_key not in self._backend_apps:
>>>   97:                     # Use the agents management server's HTTP app
>>>   98:                     self._backend_apps[backend_key] = self.agents_server.http_app()  # type: ignore[assignment]
>>>   99:                 return self._backend_apps[backend_key]
>>>  100:
>>>  101:             case AgentTokenInfo(agent_id=agent_id):
>>>  102:                 backend_key = f"agent:{agent_id}"
>>>  103:                 if backend_key not in self._backend_apps:
>>>  104:                     # Get the agent's compositor HTTP app
>>>  105:                     container = await self.registry.ensure_live(agent_id, with_ui=False)
>>>  106:                     compositor_app = container.running.compositor.http_app()
>>>  107:                     self._backend_apps[backend_key] = compositor_app  # type: ignore[assignment]
>>>  108:                 return self._backend_apps[backend_key]
     109:
     110:     async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
     111:         """Route request to appropriate backend based on token."""
     112:         # Extract Bearer token
     113:         token = self._extract_bearer_token(request.scope["headers"])
   ...
      33:
      34:     HUMAN = "human"  # Routes to agents management server
      35:     AGENT = "agent"  # Routes to agent's compositor
      36:
      37:
>>>   38: class HumanTokenInfo(BaseModel):
>>>   39:     """Token info for human connections (routes to agents management server)."""
>>>   40:
>>>   41:     role: Literal[TokenRole.HUMAN]
      42:
      43:
      44: class AgentTokenInfo(BaseModel):
      45:     """Token info for agent connections (routes to agent's compositor)."""
      46:
   ...
      39:     """Token info for human connections (routes to agents management server)."""
      40:
      41:     role: Literal[TokenRole.HUMAN]
      42:
      43:
>>>   44: class AgentTokenInfo(BaseModel):
>>>   45:     """Token info for agent connections (routes to agent's compositor)."""
>>>   46:
>>>   47:     role: Literal[TokenRole.AGENT]
>>>   48:     agent_id: AgentID  # Required for agent tokens
      49:
      50:
      51: TokenInfo = Annotated[HumanTokenInfo | AgentTokenInfo, Field(discriminator="role")]
      52:
      53:
```

## ducktape/2025-11-22-01 (8)

### `duplicate-ts-types.yaml` / `occ-0`

File: `adgn/src/adgn/agent/web/src/features/chat/channels.ts`

> The `channels.ts` file (lines 138-174) manually defines TypeScript types for
> WebSocket messages (SessionMessage, McpMessage, ApprovalsMessage, etc.).
>
> The codebase already has a Pydantic-to-TypeScript code generator at
> `adgn/scripts/generate_frontend_code.py` that uses `json-schema-to-typescript`,
> outputs to `adgn/agent/web/src/generated/types.ts`, and is invoked via
> `npm run codegen`.
>
> Manual types create duplication, drift risk (Python changes may not reflect in
> TypeScript), and maintenance burden (schema changes require two updates).
>
> **Fix:** Find or create Python Pydantic models for SessionMessage, McpMessage,
> ApprovalsMessage, PolicyMessage, UiMessage, ErrorMessage (likely in
> `adgn/agent/server/protocol.py`). Add them to `models_to_export` in
> `generate_frontend_code.py`. Run `npm run codegen`. Replace manual types in
> channels.ts with imports from `generated/types.ts`. Keep only envelope type
> manually defined (infrastructure, not data model).

```
     133:
     134: /**
     135:  * Channel message type guards
     136:  */
     137:
>>>  138: export type SessionMessage =
>>>  139:   | { type: 'session_snapshot'; session_state: any; run_state?: any }
>>>  140:   | { type: 'user_text'; text: string }
>>>  141:   | { type: 'assistant_text'; text: string }
>>>  142:   | { type: 'tool_call'; name: string; args_json?: string; call_id: string }
>>>  143:   | { type: 'tool_result'; call_id: string; output: string; is_error?: boolean }
>>>  144:   | { type: 'reasoning'; text: string }
>>>  145:   | { type: 'run_status'; run_state: any }
>>>  146:   | { type: 'turn_done' }
>>>  147:
>>>  148: export type McpMessage =
>>>  149:   | { type: 'mcp_snapshot'; sampling: any }
>>>  150:   | { type: 'mcp_server_attached'; name: string }
>>>  151:   | { type: 'mcp_server_detached'; name: string }
>>>  152:
>>>  153: export type ApprovalsMessage =
>>>  154:   | { type: 'approvals_snapshot'; pending: any[] }
>>>  155:   | { type: 'approval_pending'; call_id: string; tool_key: string; args_json?: string }
>>>  156:   | { type: 'approval_decision'; call_id: string; decision: string }
>>>  157:
>>>  158: export type PolicyMessage =
>>>  159:   | { type: 'policy_snapshot'; policy: any }
>>>  160:   | { type: 'policy_updated'; version: number }
>>>  161:   | { type: 'policy_proposal'; proposal: any }
>>>  162:
>>>  163: export type UiMessage =
>>>  164:   | { type: 'ui_state_snapshot'; v: string; seq: number; state: any }
>>>  165:   | { type: 'ui_state_updated'; v: string; seq: number; state: any }
>>>  166:   | { type: 'ui_message'; message: any }
>>>  167:   | { type: 'ui_end_turn' }
>>>  168:
>>>  169: export type ErrorMessage = {
>>>  170:   type: 'error'
>>>  171:   code: string
>>>  172:   message?: string
>>>  173:   details?: any
>>>  174: }
     175:
     176: export type AcceptedMessage = {
     177:   type: 'accepted'
     178: }
```
