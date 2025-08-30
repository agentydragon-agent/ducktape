Runs: 1 = parallel_all, 2 = parallel_run2, 3 = parallel_run3

# internal/app/app.go
* [1] Early bailout (guard clauses and loop guards): Loop guard should use continue. Lines 427–431 wrap the entire loop body in an if to skip nil cleanups. Prefer an early continue guard so the body isn’t nested. Lines 427–431: for _, cleanup := range app.cleanupFuncs { if cleanup != nil { cleanup() } }
* [1] No one-off variables or trivial pass-through wrappers: Trivial pass-through wrapper. UpdateAgentModel simply forwards to app.CoderAgent.UpdateModel with no added value, context, or adaptation. Unless required for a public facade with a clear reason, this is a pass-through wrapper. Lines 253–255: func (app *App) UpdateAgentModel() error { return app.CoderAgent.UpdateModel() }
* [1] No unnecessary nesting (combine trivial guards): Nested trivial guards. The “derive topic for mcp” block nests four ifs that successively guard the inner body. These are trivial guard conditions without elses and can be flattened or partially combined to reduce nesting. Lines 312–321: nested checks on name == "mcp", v.Kind() == reflect.Struct, f.IsValid && f.Kind() == String, then s cast and non-empty
* [1] Self‑describing names for primitives (units and meaning): Ambiguous “bytes” count name. readBts is a primitive int representing bytes read but its name obscures meaning/units. Rename to read_bytes or readBytes to be self‑explanatory. Lines 211–213, 229–233: definition and uses of readBts
* [1] Self‑describing names for primitives (units and meaning): Unit-bearing locals without unit in name. maxSize and maxAge are primitives whose units are MB and days (as implied by the source fields). Consider maxSizeMB and maxAgeDays for clarity. Lines 111–118 (maxSize MB), 113–124 (maxAge days)
* [3] No one-off variables or trivial pass-through wrappers: Trivial pass-through method. Lines 253–255: func (app *App) UpdateAgentModel() error { return app.CoderAgent.UpdateModel() }
* [2] Self‑describing names for primitives (units and meaning): Lines 111–129: Local variables maxSize (megabytes) and maxAge (days) do not encode their units in the name. Suggest maxSizeMB, maxAgeDays.
* [2] Self‑describing names for primitives (units and meaning): Lines 212, 229–233, 241–243: Variable readBts is an abbreviation for “read bytes” and is not self‑describing. Suggest readBytes to make meaning and units clear.

# internal/app/lsp_events.go
* [1] Early bailout (guard clauses and loop guards): Function guard should early return. updateLSPDiagnostics wraps the entire function body in an if exists { … }. Use an early return when the precondition fails to avoid nesting and make the happy path top‑level. Lines 88–101: if info, exists := lspStates.Get(name); exists { … }

# internal/ansiext/ansi.go

# internal/cmd/root.go
* [1] No one-off variables or trivial pass-through wrappers: yolo is a single‑use variable that immediately forwards into cfg.Permissions.SkipRequests without adding clarity. Lines 133, 168. Rationale: Single‑use forwarding variables should be inlined unless they add non‑obvious value.
* [1] Self‑describing names for primitives (units and meaning): Ambiguous boolean name yolo does not convey meaning; booleans should be clear predicates like dangerous_mode, auto_accept_permissions, or skip_requests. Lines 133, 168.
* [3] Self‑describing names for primitives (units and meaning): The boolean flag and variable name yolo are not self‑descriptive. Lines 30 (CLI flag), 133, 168. Prefer names like --auto-accept / autoAccept or --skip-permission-requests / skipPermissionRequests.

# internal/config/config.go
* [3] No unnecessary line breaks: Two consecutive blank lines in a struct block reduce readability. Lines 166–167. Allow at most one blank line to separate logical sections.

# internal/config/provider.go
* [3] No one-off variables or trivial pass‑through wrappers: Single‑use variables immediately forwarded to the next call. Lines 83–85. Example: client and path created only to be passed once into loadProvidersOnce(...). Inline without loss of clarity.

# internal/csync/maps.go
* [1] No one-off variables or trivial pass-through wrappers: Violation: JSONSchemaAlias introduces a one‑off temporary only to return it (lines 111–114). Lines: 111–114: m := map[K]V{}; return m. Rationale: Inline the constructed value directly.
* [2] No one-off variables or trivial pass-through wrappers: Violation. Rationale: JSONSchemaAlias introduces a single‑use variable that is immediately returned without adding meaning. Lines: 111–114. Details: m := map[K]V{}; return m should be a direct return of the literal.
* [3] No one-off variables or trivial pass‑through wrappers: JSONSchemaAlias returns a throwaway temp. Lines 112–113. Rationale: Creates m := map[K]V{} solely to immediately return it; inline the literal instead to avoid a single‑use variable.

# internal/diff/word_inline.go
* [2] Out of defined properties but worth noting: constructs paths via string concatenation (oldPath := dir + "/old" and newPath := dir + "/new"). In Go, prefer filepath.Join(dir, "old")/filepath.Join(dir, "new") for portability.

# internal/env/env.go

# internal/format/spinner.go
* [2] No one-off variables or trivial pass‑through wrappers: Lines 47–57 define a single‑use local model variable that is immediately forwarded into tea.NewProgram without reuse. Inline the struct literal in the call to reduce noise.
* [2] No one-off variables or trivial pass‑through wrappers: Lines 59–68 define a single‑use local prog variable only to forward it into the Spinner struct literal. Inline tea.NewProgram(...) directly into the prog: field.

# internal/fsext/fileutil.go
* [1] No unnecessary nesting (combine trivial guards): Lines 91–96: if d.IsDir() { if walker.ShouldSkip(path) { return filepath.SkipDir } return nil }. Flatten by checking combined guard first (d.IsDir() && walker.ShouldSkip(path)).
* [1] Self‑describing names for primitives (units and meaning): Parameter names are ambiguous. Line 154: DirTrim(pwd string, lim int). Prefer workingDir string and maxSegments int (or similar) to make meaning/units obvious.

# internal/fsext/ignore_test.go
* [1] Self‑describing names for primitives (units and meaning): Variable name is abbreviated and not fully self‑describing. Lines 15, 18: oldWd (string path to previous working directory). Prefer a clearer name like prev_working_dir or prevDirPath.

# internal/fsext/ls.go
* [1] No unnecessary nesting (combine trivial guards): Lines 202–206: if dl.shouldIgnore(path, ignorePatterns) { if d.IsDir() { return filepath.SkipDir } return nil }. Flatten by checking combined condition first (ignore && isDir), then handle remaining case without nesting.

# internal/history/file.go
* [1] No unnecessary nesting (combine trivial guards): Lines 106–114: Nested trivial guards that can be combined. Current pattern: if strings.Contains(txErr.Error(), "UNIQUE constraint failed") { if attempt < maxRetries-1 { version++; continue } } return File{}, txErr. Rationale: Two‑level guard without elses; flatten to a single condition to reduce nesting.
* [1] Self‑describing names for primitives (units and meaning): Lines 24–25: Ambiguous timestamp primitives. Fields CreatedAt int64, UpdatedAt int64 lack explicit units or time type. Rationale: Use time.Time or encode units in the name (e.g., CreatedAtEpochMs, UpdatedAtEpochMs).
* [2] Self‑describing names for primitives (units and meaning): Lines 24–25: CreatedAt int64, UpdatedAt int64 use bare integer timestamps with ambiguous units. Prefer a time type (e.g., time.Time) or unit‑suffixed names (e.g., CreatedAtEpochMs, UpdatedAtEpochS).
* [3] Self‑describing names for primitives (units and meaning): Lines 24–25 (struct) and 207–208 (mapping): CreatedAt int64, UpdatedAt int64 use bare integers; prefer time.Time or explicit unit‑suffixed primitives, and keep units consistent across the codebase.

# internal/logging/recover.go
* [1] Early Bailout (guard clauses and loop guards): Function body wrapped in trivial if‑guard instead of early return (lines 13–24). Rationale: entire logic nested under if r := recover(); r != nil { ... } with no else; prefer early exit to avoid nesting.
* [2] Early bailout (guard clauses and loop guards): Violation: Entire function body nested under a top‑level if instead of using an early return guard. Lines: 13–24. Rationale: Assign r := recover(); if r == nil { return }, then main body unindented.

# internal/llm/prompt/anthropic.md
* [1] Markdown inline formatting for code identifiers, flags, paths, and URIs: Plaintext file name “CRUSH.md” should be inline code. Lines: 7, 13, 96. Plaintext commands “npm run lint”, “npm run typecheck”, “ruff” should be inline code. Line: 96. Plaintext paths “package.json” and “cargo.toml” should be inline code. Line: 80.
* [3] Markdown inline formatting for code identifiers, flags, paths, and URIs: CRUSH.md not formatted as inline code in prose (use `CRUSH.md`), lines 7, 13. File names in prose not code‑formatted, e.g., package.json and cargo.toml (use backticks), line 80. Path in prose not code‑formatted, e.g., src/foo.c (use backticks), line 59.

# internal/llm/prompt/gemini.md
* [1] Markdown inline formatting for code identifiers, flags, paths, and URIs: Plaintext file name “CRUSH.md” should be inline code. Lines: 7, 13. Quoted paths should use code spans, not quotes: 'package.json', 'Cargo.toml', 'requirements.txt', 'build.gradle'. Line: 18. Quoted commands should be inline code: 'tsc', 'npm run lint', 'ruff check .'. Line: 41.
* [3] Markdown inline formatting for code identifiers, flags, paths, and URIs: CRUSH.md not formatted as inline code in prose (use `CRUSH.md`), lines 7, 13. Configuration file names quoted with apostrophes instead of code spans (use backticks for `package.json`, `Cargo.toml`, `requirements.txt`, `build.gradle`), line 18. README mentioned in quotes instead of code span (use `README`), line 40.

# internal/llm/prompt/init.md
* [1] Markdown inline formatting for code identifiers, flags, paths, and URIs: Multiline content is wrapped in a single backtick instead of a fenced code block. Line: 1 (spans multiple lines). File name formatting: “CRUSH.md” is bolded rather than inline code. Lines: 1, 7.
* [3] Markdown inline formatting for code identifiers, flags, paths, and URIs: Misuse of inline code for multi‑line content: leading single backtick opens an unterminated inline code span across the whole file; multi‑line snippets must use fenced code blocks. Line 1. File name CRUSH.md is bolded instead of inline code (use `CRUSH.md`), lines 1, 7. No unnecessary line breaks: the unintended opening backtick also disrupts normal paragraph formatting.

# internal/llm/prompt/openai.md
* [1] Markdown inline formatting for code identifiers, flags, paths, and URIs: Plaintext file name “CRUSH.md” should be inline code. Lines: 10, 16. Plaintext identifiers “file_path”, “old_string”, “new_string” should be inline code in prose. Line: 25. Plaintext paths “package.json”, “cargo.toml” should be inline code. Line: 36. Plaintext path “.pre-commit-config.yaml” should be inline code. Line: 55. Plaintext commands “npm run lint”, “npm run typecheck”, “ruff” should be inline code. Line: 72.
* [3] Markdown inline formatting for code identifiers, flags, paths, and URIs: CRUSH.md not formatted as inline code in prose (use `CRUSH.md`), lines 10, 16. package.json and cargo.toml mentioned without code spans (use backticks), line 36. README referenced without code span (use `README`), line 71.

# internal/llm/prompt/v2.md
* [1] Markdown inline formatting for code identifiers, flags, paths, and URIs: Plaintext file name “CRUSH.md” should be inline code. Lines: 119, 125, 196. Plaintext paths “package.json”, “cargo.toml” should be inline code. Line: 180. Plaintext commands “npm run lint”, “npm run typecheck”, “ruff” should be inline code. Line: 196.
* [3] Markdown inline formatting for code identifiers, flags, paths, and URIs: CRUSH.md not formatted as inline code in prose (use `CRUSH.md`), lines 119, 125, 196. package.json and cargo.toml not formatted as inline code (use backticks), line 180. README referenced without code span (use `README`), line 195.

# internal/llm/tools/download.go
* [3] Self‑describing names for primitives (units and meaning): Ambiguous size unit: variable name maxSize holds a byte count; suffix unit (e.g., maxSizeBytes) for clarity, line 185.
* [3] Self‑describing names for primitives (units and meaning): Ambiguous timeout unit: maxTimeout is an int in seconds; suffix unit (e.g., maxTimeoutSecs) to clarify scale, lines 158–161. External API param Timeout int represents seconds; field name lacks unit. Consider a unit suffix (e.g., TimeoutSecs) or a duration type, lines 17–21 and 23–27.

# internal/llm/tools/tools.go
* [3] Self‑describing names for primitives (units and meaning): Epoch millisecond fields use bare int64s with ambiguous names; suffix units or use a time type: StartedAt int64 and UpdatedAt int64 represent milliseconds (json tags started_at_ms, updated_at_ms). Consider StartedAtMs/UpdatedAtMs or time.Time/time.Duration. Lines 55–56.

# internal/lsp/client.go
* [1] Early bailout (guard clauses and loop guards): Loop guard wraps entire body; prefer continue to reduce nesting. In openKeyConfigFiles, the for‑loop body is entirely under a conditional that checks file existence; invert the condition and continue. Lines 426–434.
* [3] Early bailout (guard clauses and loop guards): Unnecessary else after early return. Lines 343–356 (WaitForServerReady): after a successful ping the function returns; subsequent else wrapping a debug log is unnecessary and adds nesting. Prefer early return and place failure‑path logging after the if without an else.

# internal/lsp/watcher/watcher.go
* [1] No one‑off variables or trivial pass‑through wrappers: Temporary variables created only to immediately return or branch without adding meaning; inline the expression. Lines: 570–577, 599–603, 621–623, 626–631, 656–658, 663–665, 671–673, 726–729.
* [1] No unnecessary nesting (combine trivial guards): Nested cfg/LSP/name/WatchMode checks can be combined (ok && non‑empty). Lines 68–71. Nested cfg/LSP/name/RecursiveMaxWatchedDirs checks can be combined (> 0). Lines 76–79.
* [1] Self‑describing names for primitives (units and meaning): maxFileSize is bytes; consider renaming to maxFileSizeBytes. Line 816.
* [3] No one‑off variables or trivial pass‑through wrappers: Several single‑use temporaries merely forward into a return; inline directly. Lines 621–622, 626–627, 656–657, 663–664, 671–672, 726–728.
* [3] No unnecessary nesting (combine trivial guards): Redundant duplicate guard on basePath == "" in matchesPattern; the second check is unreachable and increases branching without benefit. Lines 699–705 and 707–709.
* [3] Self‑describing names for primitives (units and meaning): maxFileSize is an int64 threshold without unit in the name; should be suffixed (e.g., maxFileSizeBytes). Line 816 (decl.), uses at 850, 855, 858.

# internal/message/content.go
* [1] No unnecessary nesting (combine trivial guards): Lines 358–362: Nested guards if c, ok := ...; ok { if c.FinishedAt == 0 { ... } } can be flattened to a single condition.
* [1] No unnecessary nesting (combine trivial guards): Lines 382–394: Nested guards on ToolCall and ID == toolCallID can be combined into one if condition.
* [1] No unnecessary nesting (combine trivial guards): Lines 399–411: Same nested guard pattern in AppendToolCallInput; flattenable into a single condition.
* [1] No unnecessary nesting (combine trivial guards): Lines 416–423: Same nested guard pattern in AddToolCall; flattenable into a single condition.
* [1] Self‑describing names for primitives (units and meaning): Lines 41–42, 51–52, 61–62: StartedAt int64, FinishedAt int64 fields hold Unix seconds but names don’t encode units. Prefer time types or suffix units (e.g., started_at_epoch_s).
* [1] Self‑describing names for primitives (units and meaning): Line 193: Time int64 in Finish lacks unit; populated with time.Now().Unix() elsewhere. Name should encode units or use time.Time.
* [1] Self‑describing names for primitives (units and meaning): Lines 207–208: CreatedAt int64, UpdatedAt int64 are ambiguous; additionally, units are inconsistent with usage in other files (UpdatedAt sometimes set in microseconds). Prefer time.Time or suffix units consistently.
* [2] No unnecessary nesting (combine trivial guards): Lines 359–363: Nested ifs in FinishThinking; combine type check and FinishedAt check into a single condition.
* [2] No unnecessary nesting (combine trivial guards): Lines 383–394: Nested ifs in FinishToolCall; combine type assertion and ID equality.
* [2] No unnecessary nesting (combine trivial guards): Lines 399–412: Nested ifs in AppendToolCallInput; combine type assertion and ID equality.
* [2] No unnecessary nesting (combine trivial guards): Lines 417–422: Nested ifs in AddToolCall; combine type assertion and ID equality.
* [2] Self‑describing names for primitives (units and meaning): Lines 41–42, 51–52, 61–62: Timestamp fields StartedAt, FinishedAt use bare integers; prefer time.Time or suffix unit explicitly.
* [2] Self‑describing names for primitives (units and meaning): Line 193: Finish.Time int64 lacks unit; prefer time.Time or a unit‑suffixed name.
* [2] Self‑describing names for primitives (units and meaning): Lines 207–208: Message.CreatedAt, UpdatedAt are epoch integers; prefer time.Time or suffix unit (note mixed units risk elsewhere).

# internal/message/message.go
* [1] Early Bailout (guard clauses and loop guards): Lines 110–116: Loop body is wrapped in an if message.SessionID == sessionID { ... } with no else. Prefer a loop guard with continue to reduce nesting (and the guard may be redundant because the list is already session‑filtered).
* [1] Self‑Describing Names for Primitives (units and meaning): Lines 43, 45: MessagesTS int64, ToolTS int64 are seconds‑per‑comments but names do not encode units. Prefer time.Time or suffix units (e.g., messages_ts_s, tool_ts_s).
* [1] Self‑Describing Names for Primitives (units and meaning): Line 233: message.UpdatedAt = time.Now().UnixMicro() writes microseconds into an int64 called UpdatedAt without unit suffix, while related timestamps elsewhere use seconds. This inconsistency plus missing unit suffix is ambiguous.
* [2] Early bailout (guard clauses and loop guards): Lines 110–116: In DeleteSessionMessages, body only executes when message.SessionID == sessionID; prefer early continue when it doesn’t match.
* [2] Self‑describing names for primitives (units and meaning): Lines 43 and 45: Watermarks.MessagesTS and Watermarks.ToolTS are int64 with unit only in comments; names should encode units (e.g., messages_ts_epoch_s, tool_ts_epoch_s), or use time.Time.
* [3] Early bailout (guard clauses and loop guards): Lines 110–117: Loop body wrapped entirely in an if (if message.SessionID == sessionID { … }). Use continue to reduce nesting.
* [3] Self‑describing names for primitives (units and meaning): Lines 24–34, 28, 32: Interface method params id string are ambiguous; prefer messageID to make the entity explicit.
* [3] Self‑describing names for primitives (units and meaning): Line 61: Method Delete(ctx, id string) uses ambiguous id; prefer messageID.
* [3] Self‑describing names for primitives (units and meaning): Lines 43, 45: Watermarks.MessagesTS int64, ToolTS int64 are epoch integers; prefer time.Time or explicit unit suffix.
* [3] Self‑describing names for primitives (units and meaning): Lines 207–208: Message.CreatedAt int64, UpdatedAt int64 are epoch integers; prefer time.Time or unit suffix.

# internal/message/middleware/debounce.go
* [3] Self‑describing names for primitives (units and meaning): Lines 33, 44, 94: Parameters named id string are ambiguous; these represent a message ID. Prefer messageID for clarity.

# internal/message/middleware/serialized.go
* [3] Self‑describing names for primitives (units and meaning): Line 39: sessionWorker.id string is ambiguous; prefer sessionID. Line 45: newSessionWorker(id string, …) uses ambiguous id; prefer sessionID. Line 134: Delete(ctx, id string) uses ambiguous id; prefer messageID. Line 31: op.createSess string uses an abbreviation; prefer sessionID. Line 33: op.deleteID string is better as messageID to disambiguate.

# internal/profile/profile.go
* [1] Self‑describing names for primitives (units and meaning): Lines 7, 9: Parameter s and local s are ambiguous string names; prefer a descriptive name like address. Line 10: Local v is a non‑descriptive identifier; consider stored or storedAddr to clarify purpose.

# internal/profile/server.go
* [1] Self‑describing names for primitives (units and meaning): Line 26: Local v holds CRUSH_PROFILE env value but the name is ambiguous; use a descriptive name such as profileEnv or profileSetting. Line 35: Local pstr (pprof port string) is terse; consider pprofPortStr or pprofPortEnv to make meaning explicit.

# internal/pubsub/broker.go
* [1] Self‑Describing Names for Primitives (units and meaning): Lines 54, 170: Uses now := time.Now().UnixMilli() where now is an int64 epoch in milliseconds. As a primitive timestamp, its units are implicit; either use a time type (time.Time) or suffix the unit in the name (e.g., nowUnixMs) to make units unambiguous.
* [2] No Unnecessary Nesting (combine trivial guards): Trivial nested guard can be flattened for clarity. Lines 183–186: Inner if s != "" { … } after computing s; prefer if s := f.String(); s != "" { topic = "mcp:" + s }.
* [3] No one‑off variables or trivial pass‑through wrappers: Lines 183–186: Single‑use variable s is introduced only to immediately check and concatenate. Prefer the idiomatic inline short statement in Go: if s := f.String(); s != "" { topic = "mcp:" + s }.
* [3] Self‑describing names for primitives (units and meaning): Lines 54, 170: Uses now := time.Now().UnixMilli() where now is an int64 epoch‑milliseconds timestamp. Name lacks unit and meaning. Prefer a time type or suffix unit explicitly (e.g., nowUnixMs or nowMs).

# internal/session/session.go
* [1] Self‑describing names for primitives (units and meaning): CreatedAt/UpdatedAt are int64 without units or time type. Rationale: Timestamps should use a time type (e.g., time.Time) or encode units explicitly in the name (e.g., CreatedAtEpochMs). Lines: struct fields at L21–L22; mapping at L145–L146.
* [1] Self‑describing names for primitives (units and meaning): Cost is a float64 with ambiguous unit/scale. Rationale: Monetary values should convey currency/scale in the name (e.g., CostUsd) and generally avoid binary floating point for money (prefer fixed‑point/decimal type or integer minor units). Lines: struct field at L20; mapping at L144.
* [2] No one‑off variables or trivial pass‑through wrappers: Violation: One‑off variable broker immediately forwarded into struct literal without added meaning. Lines 151–156: broker := pubsub.NewBroker[Session]() used only to populate &service{broker, q}. Inline for clarity: return &service{pubsub.NewBroker[Session](), q}.
* [2] Self‑describing names for primitives (units and meaning): Violation: Timestamp fields use bare int64 without units or time type. Lines 21–22 (CreatedAt, UpdatedAt), 145–146 (assignments).
* [3] No one‑off variables or trivial pass‑through wrappers: Violation: Single‑use temporary broker immediately forwarded into struct initialization; inline would be clearer (lines 151–155).
* [3] Self‑describing names for primitives (units and meaning): Violation: Timestamp fields CreatedAt and UpdatedAt are int64 without unit in the name (lines 21–22, 145–146). Prefer time.Time or explicit unit suffix.

# internal/shell/shell.go
* [1] Early bailout (guard clauses and loop guards): Loop guard should use continue. Lines 186–200: in ArgumentsBlocker, the loop’s first statement guards the entire loop body with an if‑block. Prefer inverting the condition and using continue to avoid wrapping the whole body.
* [2] Early bailout (guard clauses and loop guards): Loop guard as wrapping if‑block; should use continue. Lines 186–199 wrap the entire loop body in if len(args) >= len(blocked) { … }. Prefer if len(args) < len(blocked) { continue } to avoid nesting and express intent to skip.
* [2] No unnecessary nesting (combine trivial guards): Trivial loop‑wide guard is nested. Lines 186–200: The guard if len(args) >= len(blocked) is a trivial loop‑wide condition that can be flattened by inverting it with a continue, reducing nesting.
* [3] Early bailout (guard clauses and loop guards): Sentinel flag used instead of early loop bailout. Lines 188–197 set match := true, flip it on mismatch, and check after the inner loop. Prefer a labeled continue to the outer loop upon mismatch, eliminating the flag.

# internal/tui/components/chat/chat.go
* [3] No unnecessary nesting (combine trivial guards): Lines 345–351 and 505–516 contain nested ifs without elses that can be flattened. Example: if tc, ok := items[i].(messages.ToolCallCmp); ok && tc.GetToolCall().ID == event.Payload.SessionID { … }.
* [3] Self‑describing names for primitives (units and meaning): lastUserMessageTime is an int64 epoch seconds value; name lacks unit and uses a primitive where time.Time would be clearer. Declared at 69; assigned at 449, 637, 673; used via time.Unix(lastUserMessageTime, 0) at 544, 678. Prefer time.Time or a unit‑suffixed name.

# internal/tui/components/chat/messages/renderer.go
* [3] Self‑describing names for primitives (units and meaning): Ambiguous duration units on primitive. Lines 436–442: func formatTimeout(timeout int) string. The parameter is seconds (per comment), but name + type don’t encode the unit. Prefer timeoutSeconds or time.Duration.

# internal/version/version.go

# internal/transform/transform.go
* [1] Self‑describing names for primitives (units and meaning): Violation: CreatedAt int64 uses a bare integer timestamp without explicit unit or a time type. Lines: 31–37 (field at line 36). Prefer time.Time or suffix unit explicitly (e.g., CreatedAtEpochMs int64).
* [2] Self‑describing names for primitives (units and meaning): Violation: MessageDTO.CreatedAt uses int64 without unit, making the timestamp’s scale ambiguous; prefer time.Time or an explicit unit‑suffixed primitive (e.g., CreatedAtEpochMs int64). Lines: 31–38 (field at line 36).
* [3] Self‑describing names for primitives (units and meaning): CreatedAt uses an ambiguous primitive timestamp: CreatedAt int64 without units makes scale unclear. Prefer time.Time or suffix the unit explicitly (e.g., CreatedAtEpochMs int64). Line: 36.

# internal/tui (other files noted explicitly in items above)

# (unscoped)
