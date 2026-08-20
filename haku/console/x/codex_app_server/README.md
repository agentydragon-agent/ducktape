# Dormant Codex app-server adapter

This isolated package parses and projects the app-server protocol shipped by
`@openai/codex@0.144.1`. It is intentionally unregistered: it adds no runtime selection,
configuration, database change, sandbox launch, credentials, or production dispatch.

The committed `testdata/real_text_command.sanitized.jsonl` is a real, reviewed capture from
`codex-cli 0.144.1` (two bounded turns: text-only and command execution). Its capture and
sanitization provenance is recorded in `testdata/README.md`; `testdata/schema_derived_turn.synthetic.jsonl`
is synthetic schema coverage and must not be described as observed wire evidence.

## Capture a real sanitized trace

Run inside a disposable credentialed Codex workspace with a fixed, reviewable prompt:

```sh
bbr run //haku/console/x/codex_app_server:capture_bin -- \
  --codex /path/to/pinned/codex \
  --cwd /disposable/workspace \
  --output /tmp/codex-app-server.sanitized.jsonl \
  --prompt 'Reply with exactly TRACE_OK. Do not inspect files or run commands.'
```

For a command lifecycle, use an equally bounded prompt that names a harmless command and expected
literal output. MCP lifecycle capture additionally requires a deliberately configured safe MCP
server; do not add credentials or MCP configuration to this package.

The utility:

- launches `codex app-server --listen stdio://`;
- performs `initialize`/`initialized`, `thread/start`, and `turn/start`;
- records direction-labelled JSONL through the matching `turn/completed`;
- drains but never records stderr;
- records no environment block and replaces values equal to inherited environment values;
- replaces the prompt, workspace paths, native IDs, credential-shaped keys, bearer values, and
  OpenAI-key-shaped strings before writing.

Sanitization is not a substitute for review. Follow `testdata/README.md` before committing output.
