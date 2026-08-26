# Fixture provenance and sanitization

Every file says what kind of evidence it is in its filename. Never relabel a schema-derived fixture
as a real capture.

- `schema_derived_turn.synthetic.jsonl` is **synthetic**. Its notification and item shapes were
  transcribed from the generated 0.144.1 TypeScript schemas listed in
  `../docs/protocol_evidence.md`. It deliberately covers command and MCP lifecycles even when a
  safely credentialed run does not produce both.
- `real_text_command.sanitized.jsonl` is a **real** `codex app-server` stdio exchange captured on
  2026-08-19 UTC from the pinned agent-workspace image (`codex-cli 0.144.1`). It contains two real
  turns: a text-only `TRACE_TEXT_OK` answer, then a shell `printf TRACE_CMD_OK` command followed by
  `TRACE_COMMAND_DONE`. It was staged at `.openclaw/codex-trace-4431/`; before commit, fixed
  prompts and remaining absolute paths were replaced with explicit placeholders. The raw trace
  remains in the ephemeral sandbox and is not part of this PR.

  The capture used the existing in-cluster LiteLLM Responses provider and an injected credential,
  but no credential was read, copied, printed, or serialized. Prompts forbade file, environment,
  credential, and network access. Paths, timestamps, process IDs, and native IDs were sanitized by
  the capture workflow before staging. The provenance notes in `.openclaw/codex-trace-4431/README.md`
  are the source record for this fixture.

- `real_high_demand_failure.sanitized.jsonl` is a **real** `codex app-server` stdio exchange
  captured on 2026-08-26 UTC from the deployed Haku Console Codex runtime. A harmless Web prompt
  reached the backend, which exhausted five reconnect attempts before reporting a terminal temporary
  high-demand failure. The extraction was bounded to that turn's known frame range. The prompt,
  native IDs, database positions, timestamps and duration were replaced with type-compatible
  placeholders; protocol methods, retry/error shapes, status transitions and provider wording were
  retained. No credential, environment value, system prompt, repository content, path, tool call or
  unrelated session data was read into the fixture. Production evidence and the conversation-level
  error-handling follow-up are recorded in issue #4752.

The capture program writes sanitized records only. Before committing a real capture, review every
line for all of the following:

1. no authorization headers, API keys, tokens, cookies, credentials, or environment values;
2. no real user text, repository contents, usernames, hostnames, absolute paths, or tool output;
3. thread/turn/item/process/client IDs replaced by stable placeholders;
4. only the intended bounded initialize → thread/start → turn/start → turn/completed exchange;
5. no stderr (the utility drains and discards it).

A real fixture should use a disposable directory and a fixed prompt whose expected output is safe
to publish. If any line is uncertain, omit the fixture and document the case as synthetic instead.
